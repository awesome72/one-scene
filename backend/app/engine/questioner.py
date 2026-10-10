"""다음 질문 하나 생성."""

from collections.abc import AsyncIterator

from app.config import get_settings
from app.engine import prompt_builder
from app.engine.llm import LLM
from app.models import WritingSession

MAX_TOKENS = 8000
# 짧은 대화형 응답이라 낮은 effort로 충분하다. 품질 평가(Phase 8) 결과로 조정한다
EFFORT = "low"
# 비용·속도: 질문 한 줄에는 생각 토큰이 필요 없다 (평가로 품질 확인, docs/PROGRESS.md)
THINKING_OFF = True


async def run(
    llm: LLM, session: WritingSession, feedback: str | None = None, opening: bool = False
) -> str:
    prompt = prompt_builder.build(session, feedback, opening, get_settings().model_questioner)
    return await llm.text(
        model=get_settings().model_questioner,
        system=prompt["system"],
        messages=prompt["messages"],
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        thinking_off=THINKING_OFF,
    )


def stream(
    llm: LLM, session: WritingSession, feedback: str | None = None, opening: bool = False
) -> AsyncIterator[str]:
    """질문을 글자가 생기는 대로 내보낸다."""
    prompt = prompt_builder.build(session, feedback, opening, get_settings().model_questioner)
    return llm.stream_text(
        model=get_settings().model_questioner,
        system=prompt["system"],
        messages=prompt["messages"],
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        thinking_off=THINKING_OFF,
    )
