"""단계 마감 조건 판정. 원본: docs/claude-code-guide.md 10장.

조건 충족은 '제안'일 뿐이다. 실제 단계 이동은 사용자가 /advance로 승인할 때만 일어난다.
"""

from app.models import ARC_BLOCKS, Material, WritingSession


def _active(session: WritingSession) -> list[Material]:
    return [m for m in session.materials if not m.excluded]


def _in_block(session: WritingSession, block: str) -> list[Material]:
    return [m for m in _active(session) if m.arc_block == block]


def missing(session: WritingSession) -> list[str]:
    """현재 단계에서 아직 채워지지 않은 조건 (사람이 읽을 수 있는 말). 빈 목록이면 마감 가능."""
    out: list[str] = []
    if session.stage == 1:
        if not session.topic_sentence:
            out.append("한 문장 주제")
        if not _in_block(session, "scene"):
            out.append("오프닝 장면")
        if not session.target_length:
            out.append("목표 길이")
    elif session.stage == 2:
        names = {
            "scene": "장면", "event": "사건과 배경", "meaning": "의미",
            "present": "현재의 나", "resonance": "여운",
        }
        for block in ARC_BLOCKS:
            if not _in_block(session, block):
                out.append(f"{names[block]} 재료")
        senses = [m for m in _in_block(session, "scene") if m.type in ("sense", "object")]
        if len(senses) < 2:
            out.append("장면 블록의 감각·사물 재료 2개")
        if not any(m.type == "interpretation" for m in _in_block(session, "meaning")):
            out.append("의미 블록의 당신 자신의 말")
    elif session.stage == 3:
        items = session.outline_items
        if not items:
            out.append("단락 개요")
        else:
            if items[0].arc_block != "scene":
                out.append("장면으로 시작하는 첫 단락")
            resonance_ids = {m.id for m in _in_block(session, "resonance")}
            if not resonance_ids.intersection(items[-1].material_ids or []):
                out.append("여운 재료가 있는 마지막 단락")
    elif session.stage == 4:
        draft = session.drafts[-1] if session.drafts else None
        if draft is None:
            out.append("초안")
        elif any(s.get("is_blank") for s in draft.sentence_map):
            out.append("빈칸 채우기")
        if not session.tags:
            out.append("태그")
    return out


def is_ready_to_close(session: WritingSession) -> bool:
    return not missing(session)
