"""한 턴 처리. 원본: docs/claude-code-guide.md 7장.

사용자 발화 저장 → 재료 추출 → (넘어가기·고통 신호) → 질문 생성 ⇄ 검수 → 코치 턴 저장.
진행 상황은 이벤트로 내보내고, 검수를 통과한 질문만 사용자에게 보낸다.
"""

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine import extractor, prompt_builder, questioner, resources, reviewer, stage_machine
from app.engine.extractor import Extraction
from app.engine.llm import LLM, UNAVAILABLE_MESSAGE, LLMError, LLMUnavailable
from app.models import Material, Signal, Turn, WritingSession
from app.schemas import TurnOut
from app.views import material_out, session_detail

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

Event = dict[str, Any]


def _event(kind: str, **data: Any) -> Event:
    return {"event": kind, "data": data}


def _last_question(session: WritingSession) -> str | None:
    return next((t.text for t in reversed(session.turns) if t.role == "coach"), None)


def _signal(session: WritingSession, kind: str, value: str) -> Signal | None:
    return next((s for s in session.signals if s.kind == kind and s.value == value), None)


def apply_extraction(session: WritingSession, turn: Turn, extraction: Extraction) -> list[Material]:
    """추출 결과를 세션에 반영하고 새 재료를 돌려준다."""
    next_seq = max((m.seq for m in session.materials), default=0) + 1
    added: list[Material] = []
    for item in extraction.materials:
        material = Material(
            seq=next_seq,
            turn_id=turn.id,
            text=item.text,
            type=item.type,
            arc_block=item.arc_block,
            emotion_word=item.emotion_word,
        )
        session.materials.append(material)
        added.append(material)
        next_seq += 1

    # 반복된 말: 사용자 발화 전체에서 다시 센다 (사람은 중요한 대목에서 반복한다, SKILL.md 2장)
    user_text = "\n".join(t.text for t in session.turns if t.role == "user")
    for word in extraction.key_words:
        if _signal(session, "repeated", word) is None:
            session.signals.append(Signal(kind="repeated", value=word, count=0))
    for s in session.signals:
        if s.kind == "repeated":
            s.count = user_text.count(s.value)

    for value in extraction.hesitations:
        if _signal(session, "hesitation", value) is None:
            session.signals.append(Signal(kind="hesitation", value=value))
    for value in extraction.open_gaps:
        value = value.strip()
        if value and _signal(session, "gap", value) is None:
            session.signals.append(Signal(kind="gap", value=value))
    if extraction.skip_request:
        topic = (extraction.skip_topic or _last_question(session) or "").strip()
        if topic and _signal(session, "skipped", topic) is None:
            session.signals.append(Signal(kind="skipped", value=topic))

    # 주제 문장·목표 길이는 사용자가 직접 말했을 때만 채운다. 이미 있으면 덮지 않는다 (PATCH로 수정)
    if extraction.topic_sentence and not session.topic_sentence:
        session.topic_sentence = extraction.topic_sentence
    if extraction.target_length and not session.target_length:
        session.target_length = extraction.target_length
    return added


async def _extract(
    llm: LLM, session: WritingSession, text: str, last_question: str | None
) -> Extraction:
    try:
        return await extractor.run(
            llm,
            utterance=text,
            stage=session.stage,
            last_question=last_question,
            known_gaps=[s.value for s in session.signals if s.kind == "gap"],
        )
    except LLMError:
        log.exception("재료 추출 실패 (session=%s)", session.id)
        return Extraction()


async def _ask(
    llm: LLM, session: WritingSession, opening: bool = False, hint: str | None = None
) -> AsyncIterator[Event]:
    """질문을 글자 단위로 내보내고(question_delta), 규칙 검사에 걸리면 다시 만든다(question_reset).

    속도를 위해 실시간 경로에는 규칙 검사만 둔다 (물음표 1개, 두 질문 잇기, 상투어, 인용 원문,
    직전 질문 되풀이). LLM 검수는 질문을 보낸 뒤 품질 기록용으로 돈다 (_review_later).
    마지막에 ('_final', question, meta)를 낸다.
    """
    # hint: 이번 질문에만 붙는 안내 ('막혔어요' 등). 재시도 피드백 앞에 늘 둔다
    feedback: str | None = hint
    attempts: list[dict[str, Any]] = []
    user_texts = [t.text for t in session.turns if t.role == "user"]
    previous_question = _last_question(session)
    question = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            yield _event("question_reset", attempt=attempt)
        chunks: list[str] = []
        async for chunk in questioner.stream(llm, session, feedback, opening):
            chunks.append(chunk)
            yield _event("question_delta", text=chunk)
        question = "".join(chunks).strip()
        reasons = reviewer.rule_check(question, user_texts, previous_question)
        attempts.append({"question": question, "passed": not reasons, "reasons": reasons})
        if not reasons:
            break
        feedback = prompt_builder.feedback_text(reasons, question)
        if hint:
            feedback = hint + "\n\n" + feedback
    passed = attempts[-1]["passed"]
    if not question:
        question = resources.data("fixed_replies")["fallback_question"]
    if not passed:
        log.warning("규칙 검사 %d회 탈락, 마지막 시도를 보냄: %s", MAX_ATTEMPTS, attempts[-1]["reasons"])
    yield _event("_final", question=question, meta={"attempts": attempts, "passed": passed})


async def _review_later(
    db: Session, llm: LLM, session: WritingSession, turn: Turn, last_user_text: str | None
) -> None:
    """보낸 질문을 LLM으로 검수해 기록만 한다 (평가 지표용, 사용자를 기다리게 하지 않는다)."""
    meta = dict(turn.meta or {})
    if not meta.get("passed"):
        return
    # 비용: 사용자에게 영향이 없는 기록용 검수라 일부만 표본으로 돌린다 (REVIEW_SAMPLE_RATE)
    if random.random() >= get_settings().review_sample_rate:
        return
    try:
        review = await reviewer.run(
            llm,
            question=turn.text,
            last_user_text=last_user_text,
            stage=session.stage,
            user_texts=[t.text for t in session.turns if t.role == "user"],
        )
    except LLMError:
        log.exception("사후 검수 실패 (turn=%s)", turn.id)
        return
    meta["review"] = {"passed": review.passed, "reasons": review.reasons}
    turn.meta = meta  # JSON 컬럼은 새 객체를 넣어야 저장된다
    db.commit()


def _save_coach_turn(
    db: Session, session: WritingSession, reply: str, meta: dict[str, Any]
) -> tuple[Turn, Event]:
    coach_turn = Turn(
        idx=len(session.turns), role="coach", text=reply, stage=session.stage, meta=meta
    )
    session.turns.append(coach_turn)
    db.commit()
    return coach_turn, _event(
        "question",
        turn=TurnOut.model_validate(coach_turn, from_attributes=True).model_dump(mode="json"),
    )


def _error(exc: Exception) -> Event:
    # 오류 원문(크레딧·키 등)은 로그에만 남기고 사용자에게는 정해 둔 문구만 보낸다
    if isinstance(exc, LLMUnavailable):
        return _event("error", message=UNAVAILABLE_MESSAGE)
    return _event("error", message="질문을 만들지 못했어요. 잠시 뒤 다시 보내 주세요.")


async def _pump(source: AsyncIterator[Event], queue: asyncio.Queue) -> None:
    """질문 생성 이벤트를 큐로 옮긴다. 끝나면 None."""
    try:
        async for event in source:
            await queue.put(event)
    except LLMError as exc:
        log.exception("질문 생성 실패")
        await queue.put(_error(exc))
    except Exception as exc:  # 예상 못 한 오류도 대화를 멈추게 두지 않는다 (끝 표시가 늘 간다)
        log.exception("질문 생성 중 예상 못 한 오류")
        await queue.put(_error(exc))
    finally:
        await queue.put(None)


async def _ask_and_save(
    db: Session,
    llm: LLM,
    session: WritingSession,
    last_user_text: str | None,
    *,
    opening: bool = False,
    queue: asyncio.Queue | None = None,
    held: list[Event] | None = None,
    hint: str | None = None,
) -> AsyncIterator[Event]:
    """질문 이벤트를 내보내고 코치 턴을 저장한다.

    queue가 있으면 이미 돌고 있는 생성을 이어받고, held는 그 큐에서 먼저 꺼내 둔 이벤트다.
    """
    if queue is None:
        queue = asyncio.Queue()
        asyncio.create_task(_pump(_ask(llm, session, opening, hint), queue))
    reply, meta = "", {}

    async def events() -> AsyncIterator[Event | None]:
        for e in held or []:
            yield e
        while True:
            yield await queue.get()

    async for event in events():
        if event is None:
            break
        if event["event"] == "_final":
            reply, meta = event["data"]["question"], event["data"]["meta"]
        elif event["event"] == "error":
            yield event
            return
        else:
            yield event
    if opening:
        meta["opening"] = True
    turn, saved = _save_coach_turn(db, session, reply, meta)
    yield saved
    await _review_later(db, llm, session, turn, last_user_text)


async def handle_user_turn(
    db: Session,
    llm: LLM,
    session: WritingSession,
    text: str,
    input_mode: str,
    skip: bool = False,
    stuck: bool = False,
) -> AsyncIterator[Event]:
    last_question = _last_question(session)
    user_turn = Turn(
        idx=len(session.turns), role="user", text=text, input_mode=input_mode, stage=session.stage
    )
    session.turns.append(user_turn)
    db.commit()

    if skip:
        # '넘어가기' 버튼: 추출 없이 직전 질문을 넘어간 주제로 기록하고 바로 다음 질문
        apply_extraction(session, user_turn, Extraction(skip_request=True, skip_topic=last_question))
        db.commit()
        yield _event("materials", added=[], session=session_detail(session).model_dump(mode="json"))
        yield _event("status", step="asking")
        async for event in _ask_and_save(db, llm, session, None):
            yield event
        return

    if stuck:
        # '막혔어요' 버튼: 추출 없이 같은 장면을 더 작고 쉬운 질문으로 다시 묻는다 (글을 대신 쓰지 않는다)
        yield _event("materials", added=[], session=session_detail(session).model_dump(mode="json"))
        yield _event("status", step="asking")
        hint = resources.prompt("questioner_stuck")
        async for event in _ask_and_save(db, llm, session, None, hint=hint):
            yield event
        return

    # 속도: 재료 추출과 질문 생성을 동시에 시작하고, 질문은 만들어지는 대로 흘려보낸다.
    # 질문 생성은 사용자 발화를 이미 대화 기록으로 본다. 질문 저장은 추출(고통 신호 판정)이 끝난 뒤에 한다.
    # 위험한 표현이 보이는 답은 추출이 끝날 때까지 질문을 화면에 보내지 않는다 (SKILL.md 9장)
    yield _event("status", step="asking")
    hold_all = _looks_distressed(text)
    queue: asyncio.Queue = asyncio.Queue()
    ask_task = asyncio.create_task(_pump(_ask(llm, session), queue))
    if _trivial(text):
        # 비용: "네", "맞아요" 같은 짧은 답에는 재료가 없으니 추출을 부르지 않는다
        extract_task = asyncio.create_task(_no_extraction())
    else:
        extract_task = asyncio.create_task(_extract(llm, session, text, last_question))
    held: list[Event] = []  # 아직 보내지 않은 질문 이벤트 (위험 표현, 또는 저장 대기 중인 _final)
    streamed = False
    getter: asyncio.Task | None = asyncio.create_task(queue.get())
    while not extract_task.done():
        waiting = {extract_task} | ({getter} if getter else set())
        await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        if getter and getter.done():
            event = getter.result()
            getter = None
            if event is None or event["event"] in ("_final", "error") or hold_all:
                held.append(event)  # 끝·저장·오류는 추출이 끝난 뒤에 처리한다
            else:
                streamed = True
                yield event
            if event is not None and event["event"] not in ("_final", "error"):
                getter = asyncio.create_task(queue.get())
    if getter is not None:
        getter.cancel()
    extraction = extract_task.result()
    added = apply_extraction(session, user_turn, extraction)
    db.commit()
    yield _event(
        "materials",
        added=[material_out(m).model_dump(mode="json") for m in added],
        session=session_detail(session).model_dump(mode="json"),
    )

    # 고통 신호: 만들던 질문은 버리고 상태를 묻는다 (SKILL.md 9장). 이미 흘러간 질문은 화면에서 지운다
    if extraction.distress:
        ask_task.cancel()
        if streamed:
            yield _event("question_reset", attempt=0)
        reply = resources.data("fixed_replies")["distress"]
        _, saved = _save_coach_turn(db, session, reply, {"fixed": "distress"})
        yield saved
        return

    # 단계 마감 조건 충족(1단계는 주제·길이만 남았을 때도) → 재료 카드 제안 (같은 단계에서는 한 번만)
    if stage_machine.card_due(session) and session.card_offered_stage != session.stage:
        session.card_offered_stage = session.stage
        db.commit()
        yield _event("card", stage=session.stage)

    async for event in _ask_and_save(db, llm, session, text, queue=queue, held=held):
        yield event


TRIVIAL_MAX_CHARS = 6
_KEEP_FOR_EXTRACTION = ("넘어", "싫", "패스", "그만")


def _trivial(text: str) -> bool:
    """재료 추출이 필요 없는 아주 짧은 답 (넘어가기·위험 표현은 제외)."""
    t = text.strip()
    return (
        len(t.replace(" ", "")) <= TRIVIAL_MAX_CHARS
        and not any(k in t for k in _KEEP_FOR_EXTRACTION)
        and not any(q in t for q in "\"“”‘’'")
        and not _looks_distressed(t)
    )


async def _no_extraction() -> Extraction:
    return Extraction()


def _looks_distressed(text: str) -> bool:
    markers = resources.data("fixed_replies").get("distress_markers", [])
    compact = text.replace(" ", "")
    return any(m.replace(" ", "") in compact for m in markers)


async def handle_stage_open(
    db: Session, llm: LLM, session: WritingSession
) -> AsyncIterator[Event]:
    """새 단계의 여는 질문. 사용자가 단계를 넘기거나 되돌린 뒤 화면이 부른다."""
    yield _event("status", step="asking")
    async for event in _ask_and_save(db, llm, session, None, opening=True):
        yield event
