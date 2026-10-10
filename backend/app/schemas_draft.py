"""3단계(계열 짜기)·4단계(초안과 교정) 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models import ArcBlock, InputMode
from app.schemas import MaterialOut, UtcDatetime

PatternId = Literal["linear", "return", "frame", "cross"]


class PatternOut(BaseModel):
    id: PatternId
    name: str
    desc: str


class OutlineItemOut(BaseModel):
    position: int
    arc_block: ArcBlock
    label: str
    materials: list[MaterialOut]
    target_chars: int


class OutlineOut(BaseModel):
    pattern: PatternId | None
    patterns: list[PatternOut]
    items: list[OutlineItemOut]
    total_chars: int
    saved: bool
    # 반복된 말 중 첫 단락과 마지막 단락에 모두 나오는 것 (목업: "'창밖'이 첫 장면과 마지막 장면에 모두 있어요")
    bookends: list[str]


class OutlineSave(BaseModel):
    pattern: PatternId


class LintHitOut(BaseModel):
    id: str
    kind: str
    label: str
    sentence: int
    start: int
    end: int
    text: str
    why: str
    question: str
    dismissed: bool


class DraftSentenceOut(BaseModel):
    index: int
    text: str
    is_blank: bool
    # 사용자가 직접 고치거나 쓴 문장, 또는 받아들인 AI 제안 (출처 재료 없음)
    edited: bool = False
    accepted: bool = False  # 받아들인 AI 제안
    suggestion: str | None = None  # 빈칸에 붙은 'AI 제안' (받아들이기 전에는 글이 아님)
    materials: list[MaterialOut]


class DraftEdit(BaseModel):
    # 단락별 본문. 빈칸을 남기려면 "[빈칸: 질문]"을 그대로 둔다
    paragraphs: list[str] = Field(min_length=1, max_length=60)


class DraftParagraphOut(BaseModel):
    position: int
    label: str | None
    sentences: list[DraftSentenceOut]


class DraftOut(BaseModel):
    id: str
    version: int
    created_at: UtcDatetime
    paragraphs: list[DraftParagraphOut]
    hits: list[LintHitOut]
    open_hits: int
    char_count: int
    blank_count: int
    suggestion_count: int = 0


class AcceptSuggestion(BaseModel):
    # 비우면 제안 그대로, 있으면 고쳐 쓴 문장으로 받아들인다
    text: str | None = Field(default=None, max_length=1000)


class HitAnswer(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    input_mode: InputMode = "text"


class HitAnswerOut(BaseModel):
    added: list[MaterialOut]
    draft: DraftOut
