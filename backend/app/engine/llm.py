"""Claude API 호출. LLM 호출은 engine/ 안에서만 한다 (CLAUDE.md).

엔진 모듈은 `LLM` 프로토콜에만 의존하므로 테스트에서는 가짜 구현을 넣는다.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import get_settings
from app.engine import metering

T = TypeVar("T", bound=BaseModel)

# 서버 측 refusal fallback("default" 형식)을 받는 모델 (claude-api 스킬 기준)
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 생각(thinking)을 끌 수 있는 모델과 그 방법 (claude-api 스킬: Sonnet 5.5는 between_tools, effort high 이하)
THINKING_OFF = {"claude-sonnet-5-5": {"type": "between_tools"}}


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


class LLMUnavailable(LLMError):
    """API를 지금 쓸 수 없다: 크레딧 소진·키 오류·과부하·연결 실패 등 SDK 오류.

    SDK 예외를 그대로 두면 파이프라인이 잡지 못해 대화가 멈춘다 (2026-10-10 크레딧 소진 때 확인).
    사용자에게는 원문 대신 정해 둔 문구만 보인다 (UNAVAILABLE_MESSAGE).
    """


UNAVAILABLE_MESSAGE = "지금 AI가 잠시 쉬고 있어요. 쓰신 답은 저장됐어요. 조금 뒤에 이어서 써 주세요."
_SDK_ERRORS = (anthropic.APIStatusError, anthropic.APIConnectionError)


def _unavailable(exc: Exception) -> LLMUnavailable:
    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    return LLMUnavailable(f"{type(exc).__name__} status={status} request_id={request_id}")


class LLM(Protocol):
    async def text(
        self,
        *,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        effort: str | None = None,
        thinking_off: bool = False,
    ) -> str: ...

    def stream_text(
        self,
        *,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        effort: str | None = None,
        thinking_off: bool = False,
    ) -> AsyncIterator[str]:
        """글자가 생기는 대로 조각을 낸다 (화면에 질문을 실시간으로 보이기 위해)."""
        ...

    async def parse(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int,
        effort: str | None = None,
    ) -> T: ...


def _supports_effort(model: str) -> bool:
    return not model.startswith("claude-haiku")


class AnthropicLLM:
    def __init__(
        self, client: anthropic.AsyncAnthropic | None = None, keep_usage: bool = True
    ) -> None:
        settings = get_settings()
        self.client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None
        )
        # 호출별 토큰 사용량 (평가 스크립트가 비용 계산에 쓴다). 서버의 공용 인스턴스는 쌓지 않는다
        # (오래 사는 함수 인스턴스에서 끝없이 자라므로). 운영 기록은 metering이 요청별로 남긴다
        self.keep_usage = keep_usage
        self.usage: list[dict[str, Any]] = []

    def _extra(self, model: str, effort: str | None, thinking_off: bool = False) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if effort and _supports_effort(model):
            extra["output_config"] = {"effort": effort}
        if thinking_off and model in THINKING_OFF:
            # 비용·속도: 짧은 질문 한 줄에는 생각 토큰(출력 요금)이 필요 없다
            extra["thinking"] = THINKING_OFF[model]
        if model in FALLBACK_MODELS:
            # 안전 분류기의 오탐이 서비스 중단이 되지 않게 서버 측 fallback을 켠다
            extra["betas"] = [FALLBACK_BETA]
            extra["fallbacks"] = "default"
        return extra

    def _check(self, message: Any, model: str) -> None:
        u = message.usage
        creation = getattr(u, "cache_creation", None)
        usage = {
            "model": model,
            "input": u.input_tokens,
            "output": u.output_tokens,
            "cache_read": u.cache_read_input_tokens or 0,
            "cache_write": u.cache_creation_input_tokens or 0,
            # 1시간 캐시 쓰기는 단가가 다르다 (입력의 2배)
            "cache_write_1h": getattr(creation, "ephemeral_1h_input_tokens", 0) or 0,
        }
        if self.keep_usage:
            self.usage.append(usage)
        metering.record(usage)
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
        thinking_off: bool = False,
    ) -> str:
        try:
            message = await self.client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                **self._extra(model, effort, thinking_off),
            )
        except _SDK_ERRORS as exc:
            raise _unavailable(exc) from exc
        self._check(message, model)
        return "".join(b.text for b in message.content if b.type == "text").strip()

    async def stream_text(
        self,
        *,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        effort: str | None = None,
        thinking_off: bool = False,
    ) -> AsyncIterator[str]:
        try:
            async with self.client.beta.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                **self._extra(model, effort, thinking_off),
            ) as stream:
                async for chunk in stream.text_stream:
                    yield chunk
                final = await stream.get_final_message()
        except _SDK_ERRORS as exc:
            raise _unavailable(exc) from exc
        self._check(final, model)

    async def parse(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int,
        effort: str | None = None,
    ) -> T:
        try:
            message = await self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                **self._extra(model, effort),
            )
        except _SDK_ERRORS as exc:
            raise _unavailable(exc) from exc
        self._check(message, model)
        if message.parsed_output is None:
            raise LLMError(f"구조화 출력 파싱 실패 (stop_reason={message.stop_reason})")
        return message.parsed_output


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = AnthropicLLM(keep_usage=False)
    return _llm
