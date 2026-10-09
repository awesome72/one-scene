"""ORM 모델. 설계 원본: docs/claude-code-guide.md 5장."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

TargetLength = Literal["short", "medium", "long"]
SequencePattern = Literal["linear", "return", "frame", "cross"]
SessionStatus = Literal["active", "paused", "done"]
Role = Literal["user", "coach"]
InputMode = Literal["voice", "text"]
MaterialType = Literal[
    "scene", "object", "sense", "dialogue", "person", "fact", "interpretation", "time", "place"
]
ArcBlock = Literal["scene", "event", "meaning", "present", "resonance"]
SignalKind = Literal["repeated", "gap", "skipped", "hesitation"]
TagKind = Literal["period", "person", "place", "object", "gap"]

ARC_BLOCKS: tuple[ArcBlock, ...] = ("scene", "event", "meaning", "present", "resonance")
MIN_STAGE = 1
MAX_STAGE = 4


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WritingSession(Base):
    """글 한 편 = 세션 하나."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("stage BETWEEN 1 AND 4", name="ck_sessions_stage"),
        CheckConstraint(
            "target_length IS NULL OR " + _in("target_length", ("short", "medium", "long")),
            name="ck_sessions_target_length",
        ),
        CheckConstraint(
            "sequence_pattern IS NULL OR "
            + _in("sequence_pattern", ("linear", "return", "frame", "cross")),
            name="ck_sessions_sequence_pattern",
        ),
        CheckConstraint(_in("status", ("active", "paused", "done")), name="ck_sessions_status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    stage: Mapped[int] = mapped_column(Integer, default=MIN_STAGE)
    topic_sentence: Mapped[str | None] = mapped_column(Text)  # 사용자 원문
    target_length: Mapped[str | None] = mapped_column(String(10))
    sequence_pattern: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="active")
    # 재료 카드를 이미 제안한 단계. 같은 단계에서 매 턴 카드를 다시 띄우지 않기 위해
    card_offered_stage: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session", order_by="Turn.idx", cascade="all, delete-orphan"
    )
    materials: Mapped[list["Material"]] = relationship(
        back_populates="session", order_by="Material.seq", cascade="all, delete-orphan"
    )
    signals: Mapped[list["Signal"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    outline_items: Mapped[list["OutlineItem"]] = relationship(
        back_populates="session", order_by="OutlineItem.position", cascade="all, delete-orphan"
    )
    drafts: Mapped[list["Draft"]] = relationship(
        back_populates="session", order_by="Draft.version", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        CheckConstraint(_in("role", ("user", "coach")), name="ck_turns_role"),
        CheckConstraint(
            "input_mode IS NULL OR " + _in("input_mode", ("voice", "text")),
            name="ck_turns_input_mode",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    input_mode: Mapped[str | None] = mapped_column(String(10))
    stage: Mapped[int] = mapped_column(Integer)
    # 코치 턴: 생성 시도 횟수, 검수 결과, 고정 응답 여부 등 (평가용, 사용자에게 안 보임)
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    session: Mapped[WritingSession] = relationship(back_populates="turns")


class Material(Base):
    """재료: 사용자 발화에서 추출. text는 원문 그대로 (수정 금지)."""

    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(
            _in(
                "type",
                (
                    "scene", "object", "sense", "dialogue", "person",
                    "fact", "interpretation", "time", "place",
                ),
            ),
            name="ck_materials_type",
        ),
        CheckConstraint(
            "arc_block IS NULL OR "
            + _in("arc_block", ("scene", "event", "meaning", "present", "resonance")),
            name="ck_materials_arc_block",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 세션 안 번호. 프롬프트에서는 m{seq}로 부른다
    turn_id: Mapped[str] = mapped_column(ForeignKey("turns.id"))
    text: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20))
    arc_block: Mapped[str | None] = mapped_column(String(10))
    emotion_word: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[WritingSession] = relationship(back_populates="materials")

    @property
    def label(self) -> str:
        return f"m{self.seq}"


class Signal(Base):
    """반복된 말, 열린 틈, 넘어간 주제, 머뭇거림."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            _in("kind", ("repeated", "gap", "skipped", "hesitation")), name="ck_signals_kind"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    value: Mapped[str] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer, default=1)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[WritingSession] = relationship(back_populates="signals")


class OutlineItem(Base):
    __tablename__ = "outline_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    arc_block: Mapped[str | None] = mapped_column(String(10))
    label: Mapped[str | None] = mapped_column(String(40))  # "장면으로 돌아오기" 등 화면 이름
    material_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_chars: Mapped[int | None] = mapped_column(Integer)

    session: Mapped[WritingSession] = relationship(back_populates="outline_items")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    # [{sentence, material_ids, is_blank}]
    sentence_map: Mapped[list[dict]] = mapped_column(JSON)
    # 린트 결과. 사용자가 '그대로 두기'한 항목은 dismissed=true (open-questions B5)
    lint_result: Mapped[list[dict] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    session: Mapped[WritingSession] = relationship(back_populates="drafts")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint(
            _in("kind", ("period", "person", "place", "object", "gap")), name="ck_tags_kind"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[str] = mapped_column(Text)

    session: Mapped[WritingSession] = relationship(back_populates="tags")
