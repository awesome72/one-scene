"""API를 부르지 않는 가짜 LLM. 정해 둔 응답을 순서대로 돌려주고, 받은 요청을 기록한다."""

from collections import deque
from typing import Any, TypeVar

from pydantic import BaseModel

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

    async def text(self, **kwargs: Any) -> str:
        self.text_calls.append(kwargs)
        return self.questions.popleft() if self.questions else "그때 어디에 있었어요?"

    async def parse(self, **kwargs: Any) -> Any:
        self.parse_calls.append(kwargs)
        schema = kwargs["schema"]
        if schema is Extraction:
            return self.extractions.popleft() if self.extractions else Extraction()
        if schema is Review:
            return self.reviews.popleft() if self.reviews else PASS
        if self.responses.get(schema):
            return self.responses[schema].popleft()
        raise AssertionError(f"예상하지 못한 스키마 {schema}")
