"""단락 개요: 계열 패턴 + 재료 → 단락 순서와 분량. LLM 없이 결정적으로 만든다.

원본: SKILL.md 5장 3단계 계열 패턴, 6장 길이 기준·블록별 배분. 패턴별 순서는 목업(design-spec.md 5절).
"""

from dataclasses import dataclass, field
from typing import Literal

from app.models import Material, WritingSession

Pattern = Literal["linear", "return", "frame", "cross"]

PATTERNS: dict[Pattern, dict[str, str]] = {
    "linear": {"name": "직선형", "desc": "장면에서 여운까지 차례대로"},
    "return": {"name": "회귀형", "desc": "결정적 장면에서 과거로 갔다 돌아오기"},
    "frame": {"name": "액자형", "desc": "지금의 장면 안에 과거를 넣기"},
    "cross": {"name": "교차형", "desc": "과거와 현재를 번갈아"},
}

# (블록, 화면에 보일 이름)
SEQUENCES: dict[Pattern, list[tuple[str, str]]] = {
    "linear": [("scene", "장면"), ("event", "사건과 배경"), ("meaning", "의미"),
               ("present", "현재의 나"), ("resonance", "여운")],
    "return": [("scene", "장면"), ("event", "사건과 배경"), ("scene", "장면으로 돌아오기"),
               ("meaning", "의미"), ("present", "현재의 나"), ("resonance", "여운")],
    "frame": [("present", "지금의 장면"), ("scene", "장면"), ("event", "사건과 배경"),
              ("meaning", "의미"), ("present", "지금으로 돌아오기"), ("resonance", "여운")],
    "cross": [("present", "지금의 장면"), ("scene", "장면"), ("present", "현재의 나"),
              ("event", "사건과 배경"), ("meaning", "의미"), ("resonance", "여운")],
}

# 6장: 짧은 글 800~1,200 / 보통 2,000~3,000 / 긴 글 4,000~6,000자 → 가운데 값
TOTAL_CHARS = {"short": 1000, "medium": 2500, "long": 5000}
# 6장 블록별 배분 (보통 글 기준, 여운은 10~15%의 위쪽)
BLOCK_SHARE = {"scene": 0.15, "event": 0.30, "meaning": 0.20, "present": 0.20, "resonance": 0.15}


@dataclass
class PlannedItem:
    position: int
    arc_block: str
    label: str
    materials: list[Material] = field(default_factory=list)
    target_chars: int = 0


def _split(items: list[Material], parts: int) -> list[list[Material]]:
    """같은 블록이 개요에 두 번 나오면 재료를 앞뒤로 나눈다. 재료가 모자라면 같이 쓴다."""
    if parts == 1 or len(items) < parts:
        return [items] * parts
    size = -(-len(items) // parts)
    return [items[i * size : (i + 1) * size] for i in range(parts)]


def plan(session: WritingSession, pattern: Pattern) -> list[PlannedItem]:
    sequence = SEQUENCES[pattern]
    active = [m for m in session.materials if not m.excluded]
    total = TOTAL_CHARS.get(session.target_length or "medium", TOTAL_CHARS["medium"])

    occurrences: dict[str, int] = {}
    for block, _ in sequence:
        occurrences[block] = occurrences.get(block, 0) + 1
    chunks = {
        block: _split([m for m in active if m.arc_block == block], n)
        for block, n in occurrences.items()
    }

    seen: dict[str, int] = {}
    items: list[PlannedItem] = []
    for position, (block, label) in enumerate(sequence, start=1):
        k = seen.get(block, 0)
        seen[block] = k + 1
        share = BLOCK_SHARE[block] / occurrences[block]
        items.append(
            PlannedItem(
                position=position,
                arc_block=block,
                label=label,
                materials=chunks[block][k],
                target_chars=round(total * share / 50) * 50,
            )
        )
    return items
