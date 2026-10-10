"""ORM 객체 → 응답 스키마 변환."""

from collections import Counter

from app.engine import progress, stage_machine
from app.models import ARC_BLOCKS, Material, WritingSession
from app.schemas import (
    STAGE_NAMES,
    CardBlock,
    MaterialCard,
    MaterialOut,
    RepeatedWord,
    SessionDetail,
    SessionSummary,
)

TOP_REPEATED = 3
ARC_LABELS = {
    "scene": "장면",
    "event": "사건과 배경",
    "meaning": "의미",
    "present": "현재의 나",
    "resonance": "여운",
}


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
        updated_at=session.updated_at,
    )


def material_out(material: Material) -> MaterialOut:
    return MaterialOut(
        id=material.id,
        label=material.label,
        text=material.text,
        type=material.type,  # type: ignore[arg-type]
        arc_block=material.arc_block,  # type: ignore[arg-type]
        emotion_word=material.emotion_word,
        excluded=material.excluded,
    )


def _repeated(session: WritingSession) -> list[RepeatedWord]:
    signals = sorted(
        (s for s in session.signals if s.kind == "repeated" and s.count >= 2),
        key=lambda s: s.count,
        reverse=True,
    )[:TOP_REPEATED]
    return [RepeatedWord(value=s.value, count=s.count) for s in signals]


def _gaps(session: WritingSession) -> list[str]:
    return [s.value for s in session.signals if s.kind == "gap" and not s.resolved]


def session_detail(session: WritingSession) -> SessionDetail:
    active = [m for m in session.materials if not m.excluded]
    arc_counts = Counter(m.arc_block for m in active if m.arc_block)
    return SessionDetail(
        **session_summary(session).model_dump(),
        topic_sentence=session.topic_sentence,
        target_length=session.target_length,
        sequence_pattern=session.sequence_pattern,
        material_count=len(active),
        arc={block: arc_counts.get(block, 0) for block in ARC_BLOCKS},
        repeated=_repeated(session),
        gaps=_gaps(session),
        progress=progress.build(session),
    )


def material_card(session: WritingSession) -> MaterialCard:
    """재료 카드: 사용자가 한 말을 원문 그대로 블록별로 모은다 (SKILL.md 3장). 해석은 넣지 않는다."""
    missing = stage_machine.missing(session)
    return MaterialCard(
        stage=session.stage,
        stage_name=STAGE_NAMES[session.stage],
        ready=not missing,
        missing=missing,
        topic_sentence=session.topic_sentence,
        target_length=session.target_length,
        blocks=[
            CardBlock(
                block=block,
                label=ARC_LABELS[block],
                materials=[material_out(m) for m in session.materials if m.arc_block == block],
            )
            for block in ARC_BLOCKS
        ],
        unplaced=[material_out(m) for m in session.materials if m.arc_block is None],
        repeated=_repeated(session),
        gaps=_gaps(session),
    )
