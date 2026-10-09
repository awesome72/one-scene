"""한 턴 처리. 원본: docs/claude-code-guide.md 7장.

사용자 발화 저장 → 재료 추출 → (넘어가기·고통 신호) → 질문 생성 ⇄ 검수 → 코치 턴 저장.
진행 상황은 이벤트로 내보내고, 검수를 통과한 질문만 사용자에게 보낸다.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from app.engine import extractor, prompt_builder, questioner, resources, reviewer, stage_machine
from app.engine.extractor import Extraction
from app.engine.llm import LLM, LLMError
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
    llm: LLM, session: WritingSession, last_user_text: str | None, opening: bool = False
) -> AsyncIterator[Event]:
    """질문 생성 ⇄ 검수. 마지막에 ('_final', question, meta) 이벤트를 낸다."""
    feedback: str | None = None
    attempts: list[dict[str, Any]] = []
    question = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        yield _event("status", step="asking", attempt=attempt)
        question = await questioner.run(llm, session, feedback, opening)
        yield _event("status", step="reviewing", attempt=attempt)
        review = await reviewer.run(
            llm, question=question, last_user_text=last_user_text, stage=session.stage
        )
        attempts.append({"question": question, "passed": review.passed, "reasons": review.reasons})
        if review.passed:
            break
        feedback = prompt_builder.feedback_text(review.reasons, question)
    passed = attempts[-1]["passed"]
    if not question:
        question = resources.data("fixed_replies")["fallback_question"]
    if not passed:
        log.warning("검수 %d회 탈락, 마지막 시도를 보냄: %s", MAX_ATTEMPTS, attempts[-1]["reasons"])
    yield _event("_final", question=question, meta={"attempts": attempts, "passed": passed})


async def _ask_and_save(
    db: Session,
    llm: LLM,
    session: WritingSession,
    last_user_text: str | None,
    opening: bool = False,
) -> AsyncIterator[Event]:
    reply, meta = "", {}
    try:
        async for event in _ask(llm, session, last_user_text, opening):
            if event["event"] == "_final":
                reply, meta = event["data"]["question"], event["data"]["meta"]
            else:
                yield event
    except LLMError as exc:
        log.exception("질문 생성 실패 (session=%s)", session.id)
        yield _event(
            "error", message="질문을 만들지 못했어요. 잠시 뒤 다시 보내 주세요.", detail=str(exc)
        )
        return
    if opening:
        meta["opening"] = True
    yield _save_coach_turn(db, session, reply, meta)


def _save_coach_turn(
    db: Session, session: WritingSession, reply: str, meta: dict[str, Any]
) -> Event:
    coach_turn = Turn(
        idx=len(session.turns), role="coach", text=reply, stage=session.stage, meta=meta
    )
    session.turns.append(coach_turn)
    db.commit()
    return _event(
        "question",
        turn=TurnOut.model_validate(coach_turn, from_attributes=True).model_dump(mode="json"),
    )


async def handle_user_turn(
    db: Session,
    llm: LLM,
    session: WritingSession,
    text: str,
    input_mode: str,
    skip: bool = False,
) -> AsyncIterator[Event]:
    last_question = _last_question(session)
    user_turn = Turn(
        idx=len(session.turns), role="user", text=text, input_mode=input_mode, stage=session.stage
    )
    session.turns.append(user_turn)
    db.commit()

    if skip:
        # '넘어가기' 버튼: 추출 없이 직전 질문을 넘어간 주제로 기록한다 (SKILL.md 8장)
        extraction = Extraction(skip_request=True, skip_topic=last_question)
    else:
        # 1) 재료 추출. 실패해도 대화는 이어간다 (사용자 발화 원문은 이미 저장됨)
        yield _event("status", step="extracting")
        extraction = await _extract(llm, session, text, last_question)
    added = apply_extraction(session, user_turn, extraction)
    db.commit()
    yield _event(
        "materials",
        added=[material_out(m).model_dump(mode="json") for m in added],
        session=session_detail(session).model_dump(mode="json"),
    )

    # 2) 고통 신호: 질문 대신 상태를 묻는다 (SKILL.md 9장)
    if extraction.distress:
        reply = resources.data("fixed_replies")["distress"]
        yield _save_coach_turn(db, session, reply, {"fixed": "distress"})
        return

    # 3) 단계 마감 조건 충족 → 재료 카드 제안 (같은 단계에서는 한 번만)
    if stage_machine.is_ready_to_close(session) and session.card_offered_stage != session.stage:
        session.card_offered_stage = session.stage
        db.commit()
        yield _event("card", stage=session.stage)

    # 4) 질문 생성 ⇄ 검수 → 코치 턴 저장
    async for event in _ask_and_save(db, llm, session, None if skip else text):
        yield event


async def handle_stage_open(
    db: Session, llm: LLM, session: WritingSession
) -> AsyncIterator[Event]:
    """새 단계의 여는 질문. 사용자가 단계를 넘기거나 되돌린 뒤 화면이 부른다."""
    async for event in _ask_and_save(db, llm, session, None, opening=True):
        yield event
