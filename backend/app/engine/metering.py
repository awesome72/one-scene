"""LLM 호출별 토큰 사용량과 비용 기록 (운영 비용 감시).

요청 하나(턴, 초안, 태그 제안 …)를 `metered()`로 감싸면, 그 안에서 일어난 LLM 호출의
사용량이 `llm_usage` 표에 한 줄씩 남는다. 호출을 기록하는 쪽(`AnthropicLLM._check`)은
`record()`만 부르고, 어디에 쌓일지는 contextvar가 정한다 (엔진 함수의 인자를 늘리지 않으려고).
"""

from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.models import LlmUsage

T = TypeVar("T")

# 백만 토큰당 달러. 캐시 쓰기는 입력 단가의 1.25배(5분), 2배(1시간)
PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0, "cache_read": 0.10},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "cache_read": 0.10},
    "claude-opus-5-5": {"in": 4.0, "out": 20.0, "cache_read": 0.20},
}

_sink: ContextVar[list[dict[str, Any]] | None] = ContextVar("llm_usage_sink", default=None)


def cost(u: dict[str, Any]) -> float:
    p = PRICES.get(u["model"])
    if not p:
        return 0.0
    write_1h = u.get("cache_write_1h", 0)
    write_5m = u.get("cache_write", 0) - write_1h
    discount = 0.5 if u.get("batch") else 1.0  # Message Batches API는 절반
    return discount * (
        u["input"] * p["in"]
        + write_5m * p["in"] * 1.25
        + write_1h * p["in"] * 2.0
        + u.get("cache_read", 0) * p["cache_read"]
        + u["output"] * p["out"]
    ) / 1_000_000


def record(usage: dict[str, Any]) -> None:
    sink = _sink.get()
    if sink is not None:
        sink.append(usage)


def _save(db: Session, rows: list[dict[str, Any]], user_id: str, session_id: str | None,
          kind: str) -> None:
    if not rows:
        return
    for u in rows:
        db.add(LlmUsage(
            user_id=user_id, session_id=session_id, kind=kind, model=u["model"],
            input_tokens=u["input"], output_tokens=u["output"],
            cache_read_tokens=u.get("cache_read", 0), cache_write_tokens=u.get("cache_write", 0),
            cost_usd=cost(u),
        ))
    db.commit()


async def metered(
    stream: AsyncIterator[T], db: Session, user_id: str, session_id: str | None, kind: str
) -> AsyncIterator[T]:
    """SSE 스트림을 감싸 그 안의 LLM 사용량을 기록한다.

    sink는 스트림을 시작하기 전에 정한다: 엔진이 만드는 하위 작업(추출 등)이 같은 목록을 물려받는다.
    질문을 보낸 뒤 도는 사후 검수(표본)는 저장 뒤에 끝날 수 있어 기록에서 빠질 수 있다.
    """
    rows: list[dict[str, Any]] = []
    _sink.set(rows)
    try:
        async for item in stream:
            yield item
    finally:
        _save(db, rows, user_id, session_id, kind)


async def metered_call(coro: Any, db: Session, user_id: str, session_id: str | None,
                       kind: str) -> Any:
    rows: list[dict[str, Any]] = []
    token = _sink.set(rows)
    try:
        return await coro
    finally:
        _sink.reset(token)
        _save(db, rows, user_id, session_id, kind)
