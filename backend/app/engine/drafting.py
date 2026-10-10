"""3단계 개요 저장, 4단계 초안 조립·진실성 검사·교정 점검, 교정 질문에 대한 답 기록."""

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine import assembler, cliche_linter, fidelity, outline, resources
from app.engine.assembler import AssembledDraft, DraftParagraph, DraftSentence
from app.engine.extractor import Extraction
from app.engine.llm import LLM, UNAVAILABLE_MESSAGE, LLMError, LLMUnavailable
from app.engine.pipeline import Event, _event, _extract, apply_extraction
from app.models import Draft, Material, OutlineItem, Turn, WritingSession
from app.schemas_draft import (
    DraftOut,
    DraftParagraphOut,
    DraftSentenceOut,
    LintHitOut,
    OutlineItemOut,
    OutlineOut,
    PatternOut,
)
from app.views import material_out

log = logging.getLogger(__name__)


# ---------- 3단계: 개요 ----------


def _patterns() -> list[PatternOut]:
    return [PatternOut(id=k, **v) for k, v in outline.PATTERNS.items()]


def _bookends(session: WritingSession, first: list[Material], last: list[Material]) -> list[str]:
    words = [s.value for s in session.signals if s.kind == "repeated" and s.count >= 2]
    first_text = " ".join(m.text for m in first)
    last_text = " ".join(m.text for m in last)
    return [w for w in words if w in first_text and w in last_text]


def outline_view(session: WritingSession, pattern: str | None = None) -> OutlineOut:
    """pattern을 주면 미리보기, 안 주면 저장된 개요(없으면 기본 직선형 미리보기)."""
    by_id = {m.id: m for m in session.materials}
    if pattern is None and session.outline_items:
        items = [
            OutlineItemOut(
                position=i.position,
                arc_block=i.arc_block,  # type: ignore[arg-type]
                label=i.label or i.arc_block or "",
                materials=[material_out(by_id[m]) for m in i.material_ids if m in by_id],
                target_chars=i.target_chars or 0,
            )
            for i in session.outline_items
        ]
        chosen, saved = session.sequence_pattern, True
        first = [by_id[m] for m in session.outline_items[0].material_ids if m in by_id]
        last = [by_id[m] for m in session.outline_items[-1].material_ids if m in by_id]
    else:
        chosen = pattern or session.sequence_pattern or "linear"
        planned = outline.plan(session, chosen)  # type: ignore[arg-type]
        items = [
            OutlineItemOut(
                position=p.position,
                arc_block=p.arc_block,  # type: ignore[arg-type]
                label=p.label,
                materials=[material_out(m) for m in p.materials],
                target_chars=p.target_chars,
            )
            for p in planned
        ]
        saved = bool(session.outline_items) and chosen == session.sequence_pattern
        first, last = planned[0].materials, planned[-1].materials
    return OutlineOut(
        pattern=chosen,  # type: ignore[arg-type]
        patterns=_patterns(),
        items=items,
        total_chars=sum(i.target_chars for i in items),
        saved=saved,
        bookends=_bookends(session, first, last),
    )


def save_outline(db: Session, session: WritingSession, pattern: str) -> OutlineOut:
    _replan(db, session, pattern)
    db.commit()
    return outline_view(session)


def _replan(db: Session, session: WritingSession, pattern: str) -> None:
    session.outline_items.clear()
    db.flush()
    for p in outline.plan(session, pattern):  # type: ignore[arg-type]
        session.outline_items.append(
            OutlineItem(
                position=p.position,
                arc_block=p.arc_block,
                label=p.label,
                material_ids=[m.id for m in p.materials],
                target_chars=p.target_chars,
            )
        )
    session.sequence_pattern = pattern


# ---------- 4단계: 초안 ----------


def _lint(sentence_map: list[dict[str, Any]], previous: list[dict] | None) -> list[dict]:
    hits = cliche_linter.lint_sentences(
        [s["text"] for s in sentence_map], [s["is_blank"] for s in sentence_map]
    )
    # 문장 번호는 다시 만들거나 고치면 바뀌므로 (종류, 표시된 말)로 이어받는다
    dismissed = {(h["kind"], h["text"]) for h in previous or [] if h.get("dismissed")}
    out = []
    for h in hits:
        d = h.to_dict()
        d["dismissed"] = (h.kind, h.text) in dismissed
        out.append(d)
    return out


def draft_out(draft: Draft, session: WritingSession) -> DraftOut:
    by_id = {m.id: m for m in session.materials}
    labels = {i.position: i.label for i in session.outline_items}
    paragraphs: list[DraftParagraphOut] = []
    for index, s in enumerate(draft.sentence_map):
        if not paragraphs or paragraphs[-1].position != s["paragraph"]:
            paragraphs.append(
                DraftParagraphOut(position=s["paragraph"], label=labels.get(s["paragraph"]),
                                  sentences=[])
            )
        paragraphs[-1].sentences.append(
            DraftSentenceOut(
                index=index,
                text=s["text"],
                is_blank=s["is_blank"],
                edited=s.get("source") in ("user", "accepted"),
                accepted=s.get("source") == "accepted",
                suggestion=s.get("suggestion") if s["is_blank"] else None,
                materials=[material_out(by_id[m]) for m in s["material_ids"] if m in by_id],
            )
        )
    hits = [LintHitOut(**h) for h in draft.lint_result or []]
    return DraftOut(
        id=draft.id,
        version=draft.version,
        created_at=draft.created_at,
        paragraphs=paragraphs,
        hits=hits,
        open_hits=sum(1 for h in hits if not h.dismissed),
        char_count=sum(len(s["text"]) for s in draft.sentence_map if not s["is_blank"]),
        blank_count=sum(1 for s in draft.sentence_map if s["is_blank"]),
        suggestion_count=sum(
            1 for s in draft.sentence_map if s["is_blank"] and s.get("suggestion")
        ),
    )


def _body(sentence_map: list[dict[str, Any]]) -> str:
    paragraphs: list[list[str]] = []
    last = None
    for s in sentence_map:
        if s["paragraph"] != last:
            paragraphs.append([])
            last = s["paragraph"]
        paragraphs[-1].append(s["text"])
    return "\n\n".join(" ".join(p) for p in paragraphs)


def merge_blanks(sentence_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 단락에서 연달아 나온 빈칸을 하나로 합친다. 빈칸 셋이 나란히 있으면 사용자는 무엇부터
    답해야 할지 모른다 (여정 시뮬레이션). 질문은 첫 빈칸 것을, AI 제안은 이어 붙인다."""
    out: list[dict[str, Any]] = []
    for s in sentence_map:
        prev = out[-1] if out else None
        if s["is_blank"] and prev and prev["is_blank"] and prev["paragraph"] == s["paragraph"]:
            joined = " ".join(x for x in (prev.get("suggestion"), s.get("suggestion")) if x)
            out[-1] = {**prev, "suggestion": joined or None}
            continue
        out.append(dict(s))
    return out


async def handle_draft(db: Session, llm: LLM, session: WritingSession) -> AsyncIterator[Event]:
    if not session.outline_items or not session.sequence_pattern:
        yield _event("error", message="먼저 단락 순서를 정해 주세요.")
        return
    # 개요를 정한 뒤에 생긴 재료(교정 질문에 한 답 등)도 들어가도록 같은 패턴으로 다시 배치한다
    _replan(db, session, session.sequence_pattern)
    db.commit()
    try:
        yield _event("status", step="assembling")
        assembled = await assembler.run(llm, session, session.outline_items)
        yield _event("status", step="checking")
        utterances = {t.id: t.text for t in session.turns if t.role == "user"}
        checked = await fidelity.check(llm, assembled, session.materials, utterances)
    except LLMError as exc:
        log.exception("초안 조립 실패 (session=%s)", session.id)
        message = (UNAVAILABLE_MESSAGE if isinstance(exc, LLMUnavailable)
                   else "초안을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요.")
        yield _event("error", message=message)
        return

    sentence_map = merge_blanks([
        {"paragraph": s.paragraph, "text": s.text, "material_ids": s.material_ids,
         "is_blank": s.is_blank, "note": s.note, "suggestion": s.suggestion}
        for s in checked
    ])
    previous = session.drafts[-1] if session.drafts else None
    draft = Draft(
        version=(previous.version + 1) if previous else 1,
        body=_body(sentence_map),
        sentence_map=sentence_map,
        lint_result=_lint(sentence_map, previous.lint_result if previous else None),
    )
    session.drafts.append(draft)
    db.commit()
    yield _event("draft", draft=draft_out(draft, session).model_dump(mode="json"))


def dismiss_hit(db: Session, session: WritingSession, draft: Draft, hit_id: str) -> DraftOut:
    """'그대로 두기' (open-questions B5)."""
    result = [dict(h) for h in draft.lint_result or []]
    for h in result:
        if h["id"] == hit_id:
            h["dismissed"] = True
    draft.lint_result = result  # JSON 컬럼은 새 객체를 넣어야 변경이 저장된다
    db.commit()
    return draft_out(draft, session)


async def answer_hit(
    db: Session, llm: LLM, session: WritingSession, draft: Draft, hit_id: str, text: str,
    input_mode: str,
) -> tuple[list[Material], DraftOut]:
    """교정 질문에 대한 답: 질문과 답을 대화 기록에 남기고, 답에서 원문 재료를 뽑는다.

    빈칸에 대한 답이면 그 자리를 바로 채운다 (fill_blank): 답의 재료로만 쓴 문장 한두 개가
    진실성 검사를 통과하면 빈칸을 대신한다. 여정 시뮬레이션에서 빈칸에 답하고 다시 만들어도
    빈칸이 줄지 않았다 (다시 조립하면 다른 자리가 빈다). 그 밖의 표시(상투어 등)에 대한 답은
    재료로만 남고 '초안 다시 만들기' 때 반영된다."""
    hit = next((h for h in draft.lint_result or [] if h["id"] == hit_id), None)
    if hit is None:
        raise KeyError(hit_id)
    question = hit["question"]
    session.turns.append(
        Turn(idx=len(session.turns), role="coach", text=question, stage=session.stage,
             meta={"revise_hit": hit_id, "draft": draft.id})
    )
    # 코치 턴을 이미 붙였으므로 len이 곧 다음 번호다 (+1을 하면 다음 턴과 번호가 겹친다)
    user_turn = Turn(idx=len(session.turns), role="user", text=text, input_mode=input_mode,
                     stage=session.stage)
    session.turns.append(user_turn)
    db.commit()
    extraction: Extraction = await _extract(llm, session, text, question)
    added = apply_extraction(session, user_turn, extraction)
    db.commit()
    filled = False
    if hit["kind"] == "blank" and added:
        filled = await _fill_blank(llm, session, draft, hit["sentence"], question, added, user_turn)
    if not filled:
        result = [dict(h) for h in draft.lint_result or []]
        for h in result:
            if h["id"] == hit_id:
                h["dismissed"] = True
                h["answered"] = True
        draft.lint_result = result
    db.commit()
    return added, draft_out(draft, session)


class FilledSentence(BaseModel):
    text: str
    material_ids: list[str] = Field(default_factory=list)


class FilledBlank(BaseModel):
    sentences: list[FilledSentence] = Field(default_factory=list)


async def _fill_blank(
    llm: LLM, session: WritingSession, draft: Draft, index: int, question: str,
    added: list[Material], user_turn: Turn,
) -> bool:
    """빈칸 하나를 답의 재료로 채운다. 진실성 검사를 통과한 문장만 넣고, 하나도 없으면 빈칸을 둔다."""
    smap = draft.sentence_map
    if not 0 <= index < len(smap) or not smap[index].get("is_blank"):
        return False
    paragraph = smap[index]["paragraph"]
    prev = next((s for s in reversed(smap[:index]) if not s["is_blank"]), None)
    nxt = next((s for s in smap[index + 1:] if not s["is_blank"]), None)
    # 앞뒤 문장이 기대는 재료도 준다: 맥락의 말("주간 회의 때")을 쓰면 그 재료 번호를 함께 달아야
    # 진실성 검사를 통과한다 (실제 API 여정에서 새 재료만 달아 세 번 모두 탈락했다)
    by_id = {m.id: m for m in session.materials if not m.excluded}
    near_ids = [i for s in (prev, nxt) if s for i in s["material_ids"]]
    near = [by_id[i] for i in dict.fromkeys(near_ids) if i in by_id and by_id[i] not in added]
    user = "\n".join([
        f"앞 문장: {prev['text'] if prev else '(없음)'}", f"뒤 문장: {nxt['text'] if nxt else '(없음)'}",
        f"빈칸 질문: {question}", f"사용자의 답: {user_turn.text}", "", "## 새 재료",
        *[f"- {m.label} ({m.type}): {m.text}" for m in added],
        "", "## 앞뒤 문장의 재료 (이 말을 쓰면 번호를 함께 단다)",
        *([f"- {m.label} ({m.type}): {m.text}" for m in near] or ["(없음)"]),
    ])
    utterances = {t.id: t.text for t in session.turns if t.role == "user"}
    try:
        out = await llm.parse(
            model=get_settings().model_assembler, system=_fill_system(), user=user,
            schema=FilledBlank, max_tokens=2000, effort="low",
        )
        assembled = AssembledDraft(paragraphs=[DraftParagraph(
            outline_position=paragraph,
            sentences=[DraftSentence(text=s.text, material_ids=s.material_ids) for s in out.sentences],
        )])
        checked = await fidelity.check(llm, assembled, session.materials, utterances)
    except LLMError:
        log.exception("빈칸 채우기 실패 (session=%s)", session.id)
        return False
    good = [c for c in checked if not c.is_blank]
    if not good:
        return False
    # 빈칸 한 자리에 그대로 넣는다 (두 문장이어도 한 칸): 뒤 문장들의 번호와 교정 표시 id가 바뀌지 않게
    ids = list(dict.fromkeys(i for c in good for i in c.material_ids))
    new = {"paragraph": paragraph, "text": " ".join(c.text for c in good), "material_ids": ids,
           "is_blank": False, "note": None, "source": "filled"}
    sentence_map = smap[:index] + [new] + smap[index + 1:]
    draft.sentence_map = sentence_map
    draft.body = _body(sentence_map)
    draft.lint_result = _lint(sentence_map, draft.lint_result)
    return True


def _fill_system() -> list[dict]:
    # 초안 조립과 같은 캐시 앞부분 (assembler.revise_prefix)
    return [assembler.revise_prefix(), {"type": "text", "text": resources.prompt("fill_blank")}]


# ---------- 4단계: 직접 고치기 ----------

# 문장 끝(마침표·물음표·느낌표·말줄임표, 닫는 따옴표 포함) 뒤의 공백에서 자른다
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"'”’)])\s+")


def split_sentences(paragraph: str) -> list[str]:
    parts = re.split(r"(\[빈칸:[^\]]*\])", paragraph.strip())
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if cliche_linter.BLANK.match(part):
            out.append(part)
        else:
            out += [s.strip() for s in _SENTENCE_SPLIT.split(part) if s.strip()]
    return out


def edit_draft(
    db: Session, session: WritingSession, draft: Draft, paragraphs: list[str]
) -> DraftOut:
    """사용자가 직접 고친 본문을 새 초안 버전으로 저장한다.

    글의 주인은 사용자다. 그대로 남은 문장은 출처 재료 연결을 유지하고, 고치거나 새로 쓴 문장은
    source="user"로 표시한다 (진실성 검사는 AI가 조립한 문장에만 적용한다). 교정 점검은 다시 돈다.
    """
    old = {s["text"]: s for s in draft.sentence_map}
    old_positions = sorted({s["paragraph"] for s in draft.sentence_map})
    sentence_map: list[dict[str, Any]] = []
    for i, paragraph in enumerate(p for p in paragraphs if p.strip()):
        position = old_positions[i] if i < len(old_positions) else max(old_positions or [0]) + i
        for text in split_sentences(paragraph):
            kept = old.get(text)
            if kept is not None:
                sentence_map.append({**kept, "paragraph": position})
            elif cliche_linter.BLANK.match(text):
                sentence_map.append({"paragraph": position, "text": text, "material_ids": [],
                                     "is_blank": True, "note": "사용자가 남긴 빈칸"})
            else:
                sentence_map.append({"paragraph": position, "text": text, "material_ids": [],
                                     "is_blank": False, "note": None, "source": "user"})
    new = Draft(
        version=session.drafts[-1].version + 1,
        body=_body(sentence_map),
        sentence_map=sentence_map,
        lint_result=_lint(sentence_map, draft.lint_result),
    )
    session.drafts.append(new)
    db.commit()
    return draft_out(new, session)


# ---------- 4단계: AI 제안 받아들이기 ----------


def accept_suggestions(
    db: Session, session: WritingSession, draft: Draft, index: int | None, text: str | None = None
) -> DraftOut:
    """빈칸의 AI 제안을 본문으로 받아들인다. index가 None이면 제안이 있는 빈칸 모두.

    받아들인 문장은 source="accepted"로 표시한다 (사용자가 확인한 문장, 출처 재료 없음).
    같은 초안 버전 안에서 바꾸고 교정 점검을 다시 돌린다.
    """
    sentence_map = [dict(s) for s in draft.sentence_map]
    targets = range(len(sentence_map)) if index is None else [index]
    changed = 0
    for i in targets:
        if not 0 <= i < len(sentence_map):
            raise IndexError(i)
        s = sentence_map[i]
        new_text = (text or "").strip() if index is not None and text else s.get("suggestion")
        if not s["is_blank"] or not new_text:
            continue
        sentence_map[i] = {
            **s, "text": new_text.strip(), "is_blank": False, "material_ids": [],
            "source": "accepted", "note": f"AI 제안 받아들임 / 빈칸: {s['text']}",
        }
        changed += 1
    if changed:
        draft.sentence_map = sentence_map
        draft.body = _body(sentence_map)
        draft.lint_result = _lint(sentence_map, draft.lint_result)
        db.commit()
    return draft_out(draft, session)
