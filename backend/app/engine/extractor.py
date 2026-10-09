"""재료 추출: 사용자 발화 → 재료 JSON. 원문 보존이 '지어내지 않기'의 첫 번째 방어선이다."""

import re

from pydantic import BaseModel, Field

from app.config import get_settings
from app.engine import resources
from app.engine.llm import LLM
from app.models import ArcBlock, MaterialType, TargetLength

MAX_TOKENS = 4000


class ExtractedMaterial(BaseModel):
    text: str
    type: MaterialType
    arc_block: ArcBlock | None = None
    emotion_word: bool = False


class Extraction(BaseModel):
    materials: list[ExtractedMaterial] = Field(default_factory=list)
    key_words: list[str] = Field(default_factory=list)
    hesitations: list[str] = Field(default_factory=list)
    open_gaps: list[str] = Field(default_factory=list)
    skip_request: bool = False
    skip_topic: str | None = None
    distress: bool = False
    topic_sentence: str | None = None
    target_length: TargetLength | None = None


# 공백 차이와 곧은/굽은 따옴표 차이는 같은 글자로 본다 (open-questions B4)
_QUOTE_CLASSES = {
    "'": "['‘’]",
    "‘": "['‘’]",
    "’": "['‘’]",
    '"': '["“”]',
    "“": '["“”]',
    "”": '["“”]',
}


def find_verbatim(fragment: str, utterance: str) -> str | None:
    """fragment가 utterance의 연속된 부분이면 utterance 쪽 원문을 돌려준다. 아니면 None."""
    fragment = fragment.strip()
    if not fragment:
        return None
    if fragment in utterance:
        return fragment
    parts: list[str] = []
    for ch in fragment:
        if ch.isspace():
            if not parts or parts[-1] != r"\s+":
                parts.append(r"\s+")
        else:
            parts.append(_QUOTE_CLASSES.get(ch, re.escape(ch)))
    match = re.search("".join(parts), utterance)
    return match.group() if match else None


def keep_verbatim(extraction: Extraction, utterance: str) -> Extraction:
    """원문에 없는 조각은 버리고, 있는 조각은 원문 표기로 바꾼다."""
    materials = []
    seen: set[str] = set()
    for m in extraction.materials:
        text = find_verbatim(m.text, utterance)
        if text and text not in seen:
            seen.add(text)
            materials.append(m.model_copy(update={"text": text}))

    def verbatim_list(items: list[str]) -> list[str]:
        out: list[str] = []
        for item in items:
            text = find_verbatim(item, utterance)
            if text and text not in out:
                out.append(text)
        return out

    topic = find_verbatim(extraction.topic_sentence or "", utterance)
    return extraction.model_copy(
        update={
            "materials": materials,
            "key_words": [w for w in verbatim_list(extraction.key_words) if len(w) >= 2],
            "hesitations": verbatim_list(extraction.hesitations),
            "topic_sentence": topic,
        }
    )


def build_user_message(
    *, utterance: str, stage: int, last_question: str | None, known_gaps: list[str]
) -> str:
    gaps = "\n".join(f"- {g}" for g in known_gaps) or "(없음)"
    return (
        f"현재 단계: {stage}\n"
        f"코치의 직전 질문: {last_question or '(없음)'}\n"
        f"이미 기록된 열린 틈:\n{gaps}\n\n"
        f"<사용자 발화>\n{utterance}\n</사용자 발화>"
    )


async def run(
    llm: LLM, *, utterance: str, stage: int, last_question: str | None, known_gaps: list[str]
) -> Extraction:
    raw = await llm.parse(
        model=get_settings().model_extractor,
        system=resources.prompt("extractor"),
        user=build_user_message(
            utterance=utterance, stage=stage, last_question=last_question, known_gaps=known_gaps
        ),
        schema=Extraction,
        max_tokens=MAX_TOKENS,
    )
    return keep_verbatim(raw, utterance)
