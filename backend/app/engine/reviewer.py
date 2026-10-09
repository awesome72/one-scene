"""질문 검수: 규칙 검사 → LLM 판정. 기준 원본: SKILL.md 3장 질문 품질 기준."""

import re

from pydantic import BaseModel, Field

from app.config import get_settings
from app.engine import resources
from app.engine.llm import LLM

MAX_TOKENS = 1500
_SENTENCE_END = re.compile(r"[.?!。？！]+(?=\s|$)")


class Review(BaseModel):
    single_question: bool
    quotes_or_follows_user: bool
    concrete_not_abstract: bool
    not_leading: bool
    no_summary_or_advice: bool
    no_empathy_cliche: bool
    passed: bool
    reasons: list[str] = Field(default_factory=list)


def count_sentences(text: str) -> int:
    pieces = [p for p in _SENTENCE_END.split(text) if p.strip()]
    return len(pieces)


def rule_check(question: str) -> list[str]:
    """LLM 없이 잡을 수 있는 위반. 빈 목록이면 통과."""
    rules = resources.data("reviewer_rules")
    reasons: list[str] = []
    text = question.strip()
    if not text:
        return ["응답이 비어 있다."]
    marks = text.count("?") + text.count("？")
    if marks != 1:
        reasons.append(f"물음표가 {marks}개다. 질문은 정확히 하나여야 한다.")
    elif not text.endswith(("?", "？")):
        reasons.append("질문이 응답 맨 끝에 와야 한다.")
    if any(re.search(p, text) for p in rules["joined_question_markers"]):
        reasons.append("'그리고/또는/아니면'으로 질문 두 개를 잇고 있다.")
    if count_sentences(text) > rules["max_sentences"]:
        reasons.append(f"{rules['max_sentences']}문장을 넘는다. 반응 한 줄과 질문 하나로 줄인다.")
    for phrase in rules["empathy_cliches"]:
        if phrase in text:
            reasons.append(f"공감·평가 상투어 '{phrase}'가 있다.")
    for phrase in rules["summary_markers"]:
        if phrase in text:
            reasons.append(f"요약·의미 부여 표현 '{phrase}'가 있다.")
    return reasons


def build_user_message(*, question: str, last_user_text: str | None, stage: int) -> str:
    return (
        f"현재 단계: {stage}\n\n"
        f"<사용자가 방금 한 말>\n{last_user_text or '(대화 첫머리라 없음)'}\n</사용자가 방금 한 말>\n\n"
        f"<코치가 보내려는 응답>\n{question}\n</코치가 보내려는 응답>"
    )


async def run(llm: LLM, *, question: str, last_user_text: str | None, stage: int) -> Review:
    rule_reasons = rule_check(question)
    if rule_reasons:
        # 규칙에서 걸리면 LLM을 부르지 않는다 (비용·지연 절약)
        return Review(
            single_question=not any("질문" in r for r in rule_reasons),
            quotes_or_follows_user=True,
            concrete_not_abstract=True,
            not_leading=True,
            no_summary_or_advice=not any("요약" in r for r in rule_reasons),
            no_empathy_cliche=not any("상투어" in r for r in rule_reasons),
            passed=False,
            reasons=rule_reasons,
        )
    review = await llm.parse(
        model=get_settings().model_reviewer,
        system=resources.prompt("reviewer"),
        user=build_user_message(question=question, last_user_text=last_user_text, stage=stage),
        schema=Review,
        max_tokens=MAX_TOKENS,
    )
    checks = [
        review.single_question,
        review.quotes_or_follows_user,
        review.concrete_not_abstract,
        review.not_leading,
        review.no_summary_or_advice,
        review.no_empathy_cliche,
    ]
    # 모델이 passed를 항목과 어긋나게 내도 항목 판정을 따른다
    return review.model_copy(update={"passed": all(checks)})
