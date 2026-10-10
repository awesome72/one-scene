"""진행 신호: 여정(글 한 편) · 단계(마감 조건) · 분량 (docs: 개선안 '세 층의 신호').

LLM 없이 저장된 값으로만 계산한다. 화면은 이 값만 그린다 (서버가 원천).
평가·칭찬은 넣지 않는다: 개수, 조건, 범위만.
"""

from app.engine import stage_machine
from app.models import WritingSession
from app.schemas import ConditionOut, Progress

# 기획안 2.0 '네 단계의 대화': 단계별 대답 수와 시간(분) 범위
EXPECTED_TURNS = {1: (8, 12), 2: (12, 20), 3: (5, 8), 4: (8, 15)}
EXPECTED_MINUTES = {1: (10, 15), 2: (15, 25), 3: (5, 10), 4: (10, 20)}


def _round5(x: float) -> int:
    return int(round(x / 5) * 5)


def stage_fraction(conds: list[stage_machine.Condition]) -> float:
    """단계 안 진행 정도 0~1: 조건을 채운 양의 비율."""
    need = sum(c.need for c in conds)
    if need == 0:
        return 1.0
    return sum(min(c.have, c.need) for c in conds) / need


def build(session: WritingSession) -> Progress:
    stage = session.stage
    conds = [c for c in stage_machine.conditions(session) if c.need > 0]
    frac = stage_fraction(conds)
    turns = sum(1 for t in session.turns if t.role == "user" and t.stage == stage)
    done = session.status == "done"

    if done:
        remaining = (0, 0)
    else:
        lo, hi = EXPECTED_MINUTES[stage]
        rest = [EXPECTED_MINUTES[s] for s in range(stage + 1, 5)]
        remaining = (
            _round5(lo * (1 - frac) + sum(r[0] for r in rest)),
            _round5(hi * (1 - frac) + sum(r[1] for r in rest)),
        )
    next_cond = next((c for c in conds if not c.done), None)
    return Progress(
        journey=5.0 if done else (stage - 1) + frac,
        stage_fraction=1.0 if done else frac,
        conditions=[
            ConditionOut(key=c.key, label=c.label, have=c.have, need=c.need, done=c.done,
                         block=c.block, hint=c.hint)
            for c in conds
        ],
        next_need=None if done or next_cond is None else (next_cond.hint or next_cond.label),
        next_block=None if done or next_cond is None else next_cond.block,
        turns_in_stage=turns,
        expected_turns=EXPECTED_TURNS[stage],
        expected_minutes=EXPECTED_MINUTES[stage],
        remaining_minutes=remaining,
        ready=not done and next_cond is None,
    )
