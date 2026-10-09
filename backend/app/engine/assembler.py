"""초안 조립: 단락 개요 + 재료 → 문장마다 출처 재료 번호가 달린 초안."""

from pydantic import BaseModel, Field

from app.config import get_settings
from app.engine import resources
from app.engine.llm import LLM
from app.models import OutlineItem, WritingSession

MAX_TOKENS = 16000
LENGTH_NAMES = {"short": "짧은 글", "medium": "보통 글", "long": "긴 글"}


class DraftSentence(BaseModel):
    text: str
    material_ids: list[str] = Field(default_factory=list)  # m3 같은 재료 번호
    is_blank: bool = False


class DraftParagraph(BaseModel):
    outline_position: int
    sentences: list[DraftSentence]


class AssembledDraft(BaseModel):
    paragraphs: list[DraftParagraph]


def system_prompt() -> str:
    return "\n\n---\n\n".join(
        [resources.prompt("core"), resources.prompt("stage4_revise"),
         resources.prompt("assembler")]
    )


def build_user_message(session: WritingSession, items: list[OutlineItem]) -> str:
    by_id = {m.id: m for m in session.materials if not m.excluded}
    lines = [
        f"한 문장 주제: {session.topic_sentence or '(정하지 않음)'}",
        f"목표 길이: {LENGTH_NAMES.get(session.target_length or 'medium')}",
        "",
        "## 단락 개요",
    ]
    for item in items:
        lines.append(f"\n### {item.position}. [{item.arc_block}] 예상 분량 {item.target_chars}자")
        materials = [by_id[i] for i in item.material_ids if i in by_id]
        if not materials:
            lines.append("(재료 없음 — 이 단락은 빈칸으로 남긴다)")
        for m in materials:
            lines.append(f"- {m.label} ({m.type}): {m.text}")
    repeated = [s for s in session.signals if s.kind == "repeated" and s.count >= 2]
    if repeated:
        lines.append("\n## 반복된 말 (핵심어 후보)")
        lines += [f"- {s.value} ({s.count}회)" for s in repeated]
    return "\n".join(lines)


async def run(llm: LLM, session: WritingSession, items: list[OutlineItem]) -> AssembledDraft:
    return await llm.parse(
        model=get_settings().model_assembler,
        system=system_prompt(),
        user=build_user_message(session, items),
        schema=AssembledDraft,
        max_tokens=MAX_TOKENS,
    )
