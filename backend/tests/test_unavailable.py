"""AI API를 쓸 수 없을 때 (크레딧 소진·키 오류·과부하·연결 실패): 대화가 멈추지 않고,
사용자에게는 오류 원문 대신 정해 둔 문구가 가고, 쓴 답은 저장된다 (2026-10-10 크레딧 소진 때 확인)."""

from collections.abc import Iterator

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.engine.llm import UNAVAILABLE_MESSAGE, AnthropicLLM, LLMUnavailable, get_llm
from app.main import app
from tests.fakes import FakeLLM
from tests.test_turns import UTTER, _send, _start

RAW = "Your credit balance is too low to access the Anthropic API."


def _billing_error() -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(RAW, response=httpx.Response(400, request=request), body=None)


class _Messages:
    async def create(self, **_: object) -> None:
        raise _billing_error()

    async def parse(self, **_: object) -> None:
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    def stream(self, **_: object) -> object:
        raise _billing_error()


class _Client:
    class beta:
        messages = _Messages()


@pytest.fixture
def down() -> Iterator[FakeLLM]:
    llm = FakeLLM()

    async def broken_stream(**_: object):
        raise LLMUnavailable("BadRequestError status=400")
        yield ""  # 비동기 생성기로 만들기 위한 줄

    async def broken_parse(**_: object) -> object:
        raise LLMUnavailable("BadRequestError status=400")

    llm.stream_text = broken_stream  # type: ignore[method-assign]
    llm.parse = broken_parse  # type: ignore[method-assign]
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


async def test_sdk_errors_become_llm_unavailable() -> None:
    llm = AnthropicLLM(client=_Client())  # type: ignore[arg-type]
    with pytest.raises(LLMUnavailable, match="BadRequestError status=400"):
        await llm.text(model="m", system=[], messages=[], max_tokens=10)
    with pytest.raises(LLMUnavailable, match="APIConnectionError"):
        await llm.parse(model="m", system="", user="", schema=object, max_tokens=10)  # type: ignore[arg-type]
    with pytest.raises(LLMUnavailable):
        async for _ in llm.stream_text(model="m", system=[], messages=[], max_tokens=10):
            pass


def test_turn_when_ai_is_down_keeps_answer_and_says_so(client: TestClient, down: FakeLLM) -> None:
    sid = _start(client)
    events = _send(client, sid)
    kind, data = events[-1]
    assert kind == "error" and data == {"message": UNAVAILABLE_MESSAGE}
    assert RAW not in str(events)
    turns = client.get(f"/sessions/{sid}/turns").json()
    assert turns[-1]["text"] == UTTER  # 쓴 답은 저장됐다


def test_tag_suggestion_degrades_when_ai_is_down(client: TestClient, down: FakeLLM) -> None:
    sid = _start(client)
    res = client.post(f"/sessions/{sid}/tags/suggest")
    assert res.status_code == 200 and res.json()["period"] == []  # 빈 제안, 직접 붙일 수 있다


async def test_unhandled_llm_error_becomes_503_with_message() -> None:
    """잡지 않은 AI 오류의 안전망: 500 대신 503과 정해 둔 문구 (원문은 로그에만)."""
    from starlette.requests import Request

    from app.main import llm_error

    res = await llm_error(Request({"type": "http"}), LLMUnavailable(RAW))
    assert res.status_code == 503
    assert res.body.decode() == '{"detail":"' + UNAVAILABLE_MESSAGE + '"}'
