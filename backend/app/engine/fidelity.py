"""진실성 검사: 초안의 모든 문장은 재료에 기대야 한다. 원본: docs/claude-code-guide.md 8장.

1) 구조 검사 — 빈칸이 아닌 문장에 출처 재료가 없거나, 없는 재료를 가리키면 실패
2) 의미 검사 — 문장과 출처 재료 원문을 함께 보내 재료에 없는 것이 더해졌는지 판정
3) 실패한 문장은 [빈칸: 질문]으로 바꾼다. 절대 지어낸 문장을 남기지 않는다.
"""

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.config import get_settings
from app.engine import resources
from app.engine.assembler import AssembledDraft
from app.engine.llm import LLM
from app.models import Material

log = logging.getLogger(__name__)

MAX_TOKENS = 8000
# 속도: 문장마다 '재료에 있나'만 보는 판정이라 low로 충분하다
EFFORT = "low"
DEFAULT_QUESTION = "이 자리에 들어갈 장면을 말해 주실래요?"


class SentenceVerdict(BaseModel):
    index: int
    ok: bool
    added: str | None = None
    question: str | None = None


class FidelityResult(BaseModel):
    verdicts: list[SentenceVerdict]


@dataclass
class CheckedSentence:
    paragraph: int
    text: str
    material_ids: list[str] = field(default_factory=list)  # DB id
    is_blank: bool = False
    note: str | None = None  # 빈칸이 된 이유 (출처 없음, 재료에 없는 내용 등)
    suggestion: str | None = None  # 빈칸에 붙는 'AI 제안' 문장


def blank(question: str) -> str:
    return f"[빈칸: {question.strip().rstrip('.')}]"


def structural(draft: AssembledDraft, materials: list[Material]) -> list[CheckedSentence]:
    """재료 번호(m3) → DB id. 출처가 없거나 없는 재료를 가리키는 문장은 빈칸으로."""
    by_label = {m.label: m for m in materials if not m.excluded}
    out: list[CheckedSentence] = []
    for p in draft.paragraphs:
        for s in p.sentences:
            text = s.text.strip()
            if not text:
                continue
            if s.is_blank or text.startswith("[빈칸"):
                body = text if text.startswith("[빈칸") else blank(text)
                out.append(CheckedSentence(p.outline_position, body, [], True, "조립기가 비움",
                                           (s.suggestion or "").strip() or None))
                continue
            ids = [by_label[label].id for label in s.material_ids if label in by_label]
            if not ids or len(ids) != len(s.material_ids):
                # 출처 없는 문장은 본문에서 빼고, 그 문장을 AI 제안으로 돌린다
                out.append(CheckedSentence(
                    p.outline_position, blank(DEFAULT_QUESTION), [], True,
                    f"출처 없음: {text}", text,
                ))
                continue
            out.append(CheckedSentence(p.outline_position, text, ids))
    return out


def build_user_message(
    sentences: list[CheckedSentence], materials: list[Material], utterances: dict[str, str]
) -> str:
    """utterances: 재료가 나온 턴 id → 사용자 발화 원문 (재료 조각의 맥락)."""
    by_id = {m.id: m for m in materials}
    lines = []
    for i, s in enumerate(sentences):
        if s.is_blank:
            continue
        lines.append(f"## 문장 {i}\n{s.text}\n출처 재료:")
        lines += [f"- {by_id[mid].text}" for mid in s.material_ids]
        context = {utterances[by_id[mid].turn_id] for mid in s.material_ids
                   if by_id[mid].turn_id in utterances}
        if context:
            lines.append("재료가 나온 사용자 발화 (맥락):")
            lines += [f"> {u}" for u in sorted(context)]
        lines.append("")
    return "\n".join(lines)


async def semantic(
    llm: LLM,
    sentences: list[CheckedSentence],
    materials: list[Material],
    utterances: dict[str, str] | None = None,
) -> list[CheckedSentence]:
    if not any(not s.is_blank for s in sentences):
        return sentences
    result = await llm.parse(
        model=get_settings().model_fidelity,
        system=resources.prompt("fidelity"),
        user=build_user_message(sentences, materials, utterances or {}),
        schema=FidelityResult,
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
    )
    verdicts = {v.index: v for v in result.verdicts}
    out: list[CheckedSentence] = []
    for i, s in enumerate(sentences):
        v = verdicts.get(i)
        if s.is_blank or (v is not None and v.ok):
            out.append(s)
        elif v is None:
            # 판정이 빠진 문장은 확인하지 못한 문장이다. 지어냈을 수 있으니 남기지 않는다 (제품 규칙 2)
            log.warning("진실성 판정 누락 → 빈칸: 문장 %d", i)
            out.append(CheckedSentence(
                s.paragraph, blank(DEFAULT_QUESTION), [], True,
                f"진실성 판정 누락 / 원래 문장: {s.text}", s.text,
            ))
        else:
            # 재료에 없는 내용이 더해진 문장 → 본문에서 빼고 AI 제안으로 (받아들이면 글이 된다)
            out.append(CheckedSentence(
                s.paragraph, blank(v.question or DEFAULT_QUESTION), [], True,
                f"재료에 없는 내용: {v.added or '?'} / 원래 문장: {s.text}", s.text,
            ))
    return out


async def check(
    llm: LLM,
    draft: AssembledDraft,
    materials: list[Material],
    utterances: dict[str, str] | None = None,
) -> list[CheckedSentence]:
    return await semantic(llm, structural(draft, materials), materials, utterances)
