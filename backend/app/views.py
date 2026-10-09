"""ORM 객체 → 응답 스키마 변환."""

from collections import Counter
from datetime import UTC, datetime

from app.models import ARC_BLOCKS, WritingSession
from app.schemas import STAGE_NAMES, RepeatedWord, SessionDetail, SessionSummary

TOP_REPEATED = 3


def _utc(value: datetime) -> datetime:
    # SQLite는 시간대를 저장하지 않으므로 읽어 온 값은 UTC로 간주한다
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _last_question(session: WritingSession) -> str | None:
    for turn in reversed(session.turns):
        if turn.role == "coach":
            return turn.text
    return None


def session_summary(session: WritingSession) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        title=session.title,
        stage=session.stage,
        stage_name=STAGE_NAMES[session.stage],
        status=session.status,
        last_question=_last_question(session),
        updated_at=_utc(session.updated_at),
    )


def session_detail(session: WritingSession) -> SessionDetail:
    active = [m for m in session.materials if not m.excluded]
    arc_counts = Counter(m.arc_block for m in active if m.arc_block)
    repeated = sorted(
        (s for s in session.signals if s.kind == "repeated" and s.count >= 2),
        key=lambda s: s.count,
        reverse=True,
    )[:TOP_REPEATED]
    gaps = [s.value for s in session.signals if s.kind == "gap" and not s.resolved]
    return SessionDetail(
        **session_summary(session).model_dump(),
        topic_sentence=session.topic_sentence,
        target_length=session.target_length,
        sequence_pattern=session.sequence_pattern,
        material_count=len(active),
        arc={block: arc_counts.get(block, 0) for block in ARC_BLOCKS},
        repeated=[RepeatedWord(value=s.value, count=s.count) for s in repeated],
        gaps=gaps,
    )
