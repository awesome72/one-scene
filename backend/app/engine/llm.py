"""Claude API 호출. LLM 호출은 engine/ 안에서만 한다 (CLAUDE.md).

엔진 모듈은 `LLM` 프로토콜에만 의존하므로 테스트에서는 가짜 구현을 넣는다.
"""

from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

# 서버 측 refusal fallback("default" 형식)을 받는 모델 (claude-api 스킬 기준)
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


class LLM(Protocol):
    async def text(
        self,
        *,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        effort: str | None = None,
    ) -> str: ...

    async def parse(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int,
    ) -> T: ...


def _supports_effort(model: str) -> bool:
    return not model.startswith("claude-haiku")


class AnthropicLLM:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self.client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None
        )

    def _extra(self, model: str, effort: str | None) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if effort and _supports_effort(model):
            extra["output_config"] = {"effort": effort}
        if model in FALLBACK_MODELS:
            # 안전 분류기의 오탐이 서비스 중단이 되지 않게 서버 측 fallback을 켠다
            extra["betas"] = [FALLBACK_BETA]
            extra["fallbacks"] = "default"
        return extra

    @staticmethod
    def _check(message: Any) -> None:
        if message.stop_reason == "refusal":
            raise LLMRefusal(f"refusal ({getattr(message, '_request_id', '')})")

    async def text(
        self,
        *,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        message = await self.client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
            **self._extra(model, effort),
        )
        self._check(message)
        return "".join(b.text for b in message.content if b.type == "text").strip()

    async def parse(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int,
    ) -> T:
        message = await self.client.beta.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            **self._extra(model, None),
        )
        self._check(message)
        if message.parsed_output is None:
            raise LLMError(f"구조화 출력 파싱 실패 (stop_reason={message.stop_reason})")
        return message.parsed_output


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = AnthropicLLM()
    return _llm
