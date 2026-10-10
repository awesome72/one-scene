"""API를 부르지 않는 가짜 LLM. 정해 둔 응답을 순서대로 돌려주고, 받은 요청을 기록한다."""

from collections import deque
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from app.engine import metering
from app.engine.extractor import Extraction
from app.engine.reviewer import Review

T = TypeVar("T", bound=BaseModel)

PASS = Review(
    single_question=True,
    quotes_or_follows_user=True,
    concrete_not_abstract=True,
    not_leading=True,
    no_summary_or_advice=True,
    no_empathy_cliche=True,
    passed=True,
)


def failing_review(reason: str) -> Review:
    return PASS.model_copy(update={"quotes_or_follows_user": False, "reasons": [reason]})


class FakeLLM:
    def __init__(
        self,
        questions: list[str] | None = None,
        extractions: list[Extraction] | None = None,
        reviews: list[Review] | None = None,
    ) -> None:
        self.questions = deque(questions or [])
        self.extractions = deque(extractions or [])
        self.reviews = deque(reviews or [])
        self.text_calls: list[dict[str, Any]] = []
        self.parse_calls: list[dict[str, Any]] = []
        # 그 밖의 스키마(초안 조립, 진실성 검사 등): 스키마 → 응답 목록
        self.responses: dict[type, deque] = {}

    def queue(self, response: BaseModel) -> None:
        self.responses.setdefault(type(response), deque()).append(response)

    @staticmethod
    def _meter(kwargs: dict[str, Any]) -> None:
        """실제 클라이언트처럼 사용량을 기록한다 (운영 비용 기록 테스트용, 비용 0)."""
        metering.record({"model": kwargs.get("model") or "fake", "input": 100, "output": 10,
                         "cache_read": 0, "cache_write": 0})

    async def text(self, **kwargs: Any) -> str:
        self._meter(kwargs)
        self.text_calls.append(kwargs)
        return self.questions.popleft() if self.questions else "그때 어디에 있었어요?"

    async def stream_text(self, **kwargs: Any) -> AsyncIterator[str]:
        """실제처럼 몇 글자씩 나눠 낸다. 요청은 text_calls에 같이 기록한다."""
        self._meter(kwargs)
        self.text_calls.append(kwargs)
        text = self.questions.popleft() if self.questions else "그때 어디에 있었어요?"
        for i in range(0, len(text), 5):
            yield text[i : i + 5]

    async def parse(self, **kwargs: Any) -> Any:
        self._meter(kwargs)
        self.parse_calls.append(kwargs)
        schema = kwargs["schema"]
        if schema is Extraction:
            return self.extractions.popleft() if self.extractions else Extraction()
        if schema is Review:
            return self.reviews.popleft() if self.reviews else PASS
        if self.responses.get(schema):
            return self.responses[schema].popleft()
        raise AssertionError(f"예상하지 못한 스키마 {schema}")


def state_text(call: dict[str, Any]) -> str:
    """질문자 요청에서 세션 상태 블록: 대화 끝 system 메시지 또는 마지막 사용자 말의 끝 블록."""
    last = call["messages"][-1]
    if last["role"] == "system":
        return last["content"]
    return last["content"][-1]["text"]
