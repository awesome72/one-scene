"""4단계 태그와 보관함. 원본: SKILL.md 4-3 태그, 기획안 F8·F11, 목업 ⑦."""

import logging

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine import resources
from app.engine.llm import LLM, LLMError
from app.models import Tag, WritingSession

log = logging.getLogger(__name__)

MAX_TOKENS = 2000
KINDS = ("period", "person", "place", "object", "gap")


class TagSet(BaseModel):
    period: list[str] = Field(default_factory=list)
    person: list[str] = Field(default_factory=list)
    place: list[str] = Field(default_factory=list)
    object: list[str] = Field(default_factory=list)
    gap: list[str] = Field(default_factory=list)


class TagSuggestion(TagSet):
    # 제목 후보 (마무리 화면에서 고르거나 고쳐 쓴다)
    titles: list[str] = Field(default_factory=list)


def current(session: WritingSession) -> TagSet:
    grouped: dict[str, list[str]] = {k: [] for k in KINDS}
    for t in session.tags:
        grouped[t.kind].append(t.value)
    return TagSet(**grouped)


def save(db: Session, session: WritingSession, tags: TagSet) -> TagSet:
    session.tags.clear()
    for kind in KINDS:
        seen: set[str] = set()
        for value in getattr(tags, kind):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                session.tags.append(Tag(kind=kind, value=value))
    db.commit()
    return current(session)


def _unused_materials(session: WritingSession) -> list[str]:
    """초안 문장에 한 번도 쓰이지 않은 재료 = 열린 틈 후보."""
    used: set[str] = set()
    if session.drafts:
        for s in session.drafts[-1].sentence_map:
            used.update(s["material_ids"])
    return [m.text for m in session.materials if m.id not in used]


def build_user_message(session: WritingSession) -> str:
    body = session.drafts[-1].body if session.drafts else "(초안 없음)"
    repeated = [f"{s.value}({s.count}회)" for s in session.signals
                if s.kind == "repeated" and s.count >= 2]
    gaps = [s.value for s in session.signals if s.kind == "gap" and not s.resolved]
    skipped = [s.value for s in session.signals if s.kind == "skipped"]
    lines = [
        "## 완성된 글", body, "",
        "## 반복된 말", ", ".join(repeated) or "(없음)", "",
        "## 대화에서 나왔지만 글에 쓰지 않은 말 (사용자 원문)",
        *[f"- {t}" for t in _unused_materials(session)], "",
        "## 대화 중 기록된 열린 틈", *[f"- {g}" for g in gaps], "",
        "## 사용자가 넘어가자고 한 것 (다음 글감으로 제안하지 않는다)", *[f"- {s}" for s in skipped],
    ]
    return "\n".join(lines)


async def suggest(llm: LLM, session: WritingSession) -> TagSuggestion:
    try:
        return await llm.parse(
            model=get_settings().model_extractor,
            system=resources.prompt("tagger"),
            user=build_user_message(session),
            schema=TagSuggestion,
            max_tokens=MAX_TOKENS,
        )
    except LLMError:
        log.exception("태그 제안 실패 (session=%s)", session.id)
        # 제안이 실패해도 사용자가 직접 붙일 수 있게 빈 제안 + 반복된 말만
        objects = [s.value for s in session.signals if s.kind == "repeated" and s.count >= 2]
        return TagSuggestion(object=objects[:2])


def first_sentence(session: WritingSession) -> str | None:
    if not session.drafts:
        return None
    return next((s["text"] for s in session.drafts[-1].sentence_map if not s["is_blank"]), None)


def used_openings(db: Session, user_id: str) -> set[str]:
    """이미 새 글의 첫 질문으로 쓴 질문들 (다음 글감에서 뺀다)."""
    rows = db.scalars(select(WritingSession).where(WritingSession.user_id == user_id))
    return {s.turns[0].text for s in rows if s.turns and s.turns[0].role == "coach"}
