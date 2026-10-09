from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.models import ArcBlock, InputMode, MaterialType, TargetLength


def _as_utc(value: datetime) -> datetime:
    # SQLite는 시간대를 저장하지 않으므로 시간대 없는 값은 UTC로 간주한다
    return value if value.tzinfo else value.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]

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
    updated_at: UtcDatetime


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
    created_at: UtcDatetime


class SessionUpdate(BaseModel):
    # 사용자가 직접 고치는 값. 보내지 않은 필드는 그대로 둔다
    title: str | None = Field(default=None, max_length=200)
    topic_sentence: str | None = Field(default=None, max_length=500)
    target_length: TargetLength | None = None


class TurnCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    input_mode: InputMode = "text"
    # '이 질문은 넘어가기' 버튼으로 보낸 턴. 재료를 뽑지 않고 직전 질문을 넘어간 주제로 기록
    skip: bool = False


class MaterialOut(BaseModel):
    id: str
    label: str
    text: str
    type: MaterialType
    arc_block: ArcBlock | None
    emotion_word: bool
    excluded: bool


class MaterialUpdate(BaseModel):
    excluded: bool


class CardBlock(BaseModel):
    block: ArcBlock
    label: str
    materials: list[MaterialOut]


class MaterialCard(BaseModel):
    stage: int
    stage_name: str
    ready: bool
    missing: list[str]
    topic_sentence: str | None
    target_length: str | None
    blocks: list[CardBlock]
    unplaced: list[MaterialOut]
    repeated: list[RepeatedWord]
    gaps: list[str]
