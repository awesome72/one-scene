from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import ArcBlock

STAGE_NAMES: dict[int, str] = {1: "주제 설정", 2: "단락 구성", 3: "계열 짜기", 4: "태그와 교정"}


class SessionCreate(BaseModel):
    # 홈의 '새 글을 여는 질문'이나 보관함의 '다음 글감'에서 고른 질문. 없으면 기본 질문
    opening_question: str | None = Field(default=None, min_length=1, max_length=300)


class StageApproval(BaseModel):
    # 단계 이동은 사용자 승인으로만 일어난다 (CLAUDE.md 제품 규칙 4)
    approved: Literal[True]


class RepeatedWord(BaseModel):
    value: str
    count: int


class SessionSummary(BaseModel):
    id: str
    title: str | None
    stage: int
    stage_name: str
    status: str
    last_question: str | None
    updated_at: datetime


class SessionDetail(SessionSummary):
    topic_sentence: str | None
    target_length: str | None
    sequence_pattern: str | None
    material_count: int
    arc: dict[ArcBlock, int]
    repeated: list[RepeatedWord]
    gaps: list[str]


class TurnOut(BaseModel):
    id: str
    idx: int
    role: str
    text: str
    input_mode: str | None
    stage: int
    created_at: datetime
