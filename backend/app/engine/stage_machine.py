"""단계 마감 조건 판정. 원본: docs/claude-code-guide.md 10장.

조건 충족은 '제안'일 뿐이다. 실제 단계 이동은 사용자가 /advance로 승인할 때만 일어난다.
"""

from dataclasses import dataclass

from app.models import ARC_BLOCKS, Material, WritingSession


def _active(session: WritingSession) -> list[Material]:
    return [m for m in session.materials if not m.excluded]


def _in_block(session: WritingSession, block: str) -> list[Material]:
    return [m for m in _active(session) if m.arc_block == block]


@dataclass(frozen=True)
class Condition:
    """단계 마감 조건 하나. label은 프롬프트(stage_missing)와 화면이 함께 쓴다."""

    key: str
    label: str
    have: int
    need: int = 1
    block: str | None = None  # 아크 블록과 관련된 조건이면 그 블록 (화면이 곡선 위에 표시)
    hint: str | None = None  # '다음 할 일'로 보여 줄 짧은 말

    @property
    def done(self) -> bool:
        return self.have >= self.need


BLOCK_NAMES = {
    "scene": "장면", "event": "사건과 배경", "meaning": "의미",
    "present": "현재의 나", "resonance": "여운",
}
BLOCK_HINTS = {
    "scene": "그 순간 어디에서 무엇을 하고 있었는지",
    "event": "그 순간에 이르기까지 있었던 일",
    "meaning": "그 일이 나에게 무엇이었는지, 내 말로",
    "present": "요즘의 나는 어떻게 지내는지",
    "resonance": "그 장면의 무엇이 지금 다시 보이는지",
}


def conditions(session: WritingSession) -> list[Condition]:
    """현재 단계의 마감 조건과 지금까지 채운 정도."""
    if session.stage == 1:
        return [
            Condition("topic", "한 문장 주제", int(bool(session.topic_sentence)),
                      hint="이 글이 무엇에 관한 이야기인지 한 문장으로"),
            Condition("opening_scene", "오프닝 장면", len(_in_block(session, "scene")),
                      block="scene", hint="글이 시작될 한 순간"),
            Condition("length", "목표 길이", int(bool(session.target_length)),
                      hint="짧은 글, 보통 글, 긴 글 중 하나"),
        ]
    if session.stage == 2:
        out = [
            Condition(f"block_{b}", f"{BLOCK_NAMES[b]} 재료", len(_in_block(session, b)),
                      block=b, hint=BLOCK_HINTS[b])
            for b in ARC_BLOCKS
        ]
        senses = [m for m in _in_block(session, "scene") if m.type in ("sense", "object")]
        out.append(Condition("scene_senses", "장면 블록의 감각·사물 재료 2개", len(senses),
                             need=2, block="scene",
                             hint="그 순간 보이고 들리던 것, 손에 있던 것"))
        own = any(m.type == "interpretation" for m in _in_block(session, "meaning"))
        out.append(Condition("meaning_own_words", "의미 블록의 당신 자신의 말", int(own),
                             block="meaning", hint=BLOCK_HINTS["meaning"]))
        return out
    if session.stage == 3:
        items = session.outline_items
        if not items:
            return [Condition("outline", "단락 개요", 0, hint="모은 장면을 놓을 순서 고르기")]
        resonance_ids = {m.id for m in _in_block(session, "resonance")}
        return [
            Condition("outline", "단락 개요", 1),
            Condition("first_scene", "장면으로 시작하는 첫 단락",
                      int(items[0].arc_block == "scene"), hint="첫 단락을 장면으로"),
            Condition("last_resonance", "여운 재료가 있는 마지막 단락",
                      int(bool(resonance_ids.intersection(items[-1].material_ids or []))),
                      block="resonance", hint="마지막 단락에 여운 재료"),
        ]
    draft = session.drafts[-1] if session.drafts else None
    out = []
    if draft is None:
        out.append(Condition("draft", "초안", 0, hint="모은 재료로 초안 만들기"))
    else:
        # 빈칸은 채우거나, 사용자가 '그대로 두기'로 남기기로 한 것만 통과 (open-questions B5)
        kept = {h["id"] for h in draft.lint_result or [] if h.get("dismissed")}
        blanks = [i for i, s in enumerate(draft.sentence_map) if s.get("is_blank")]
        open_blanks = [i for i in blanks if f"{i}:0:blank" not in kept]
        out.append(Condition("blanks", "빈칸 채우기", len(blanks) - len(open_blanks),
                             need=len(blanks), hint="초안의 빈칸에 답하기"))
    out.append(Condition("tags", "태그", int(bool(session.tags)), hint="시기·인물·장소 태그 저장"))
    return out


def missing(session: WritingSession) -> list[str]:
    """현재 단계에서 아직 채워지지 않은 조건 (사람이 읽을 수 있는 말). 빈 목록이면 마감 가능."""
    return [c.label for c in conditions(session) if not c.done]


def is_ready_to_close(session: WritingSession) -> bool:
    return not missing(session)
