"""질문자 프롬프트 조립: core.md + 단계 모듈 + 출력 규칙 + 세션 상태 YAML + 최근 대화.

캐시를 위해 바뀌지 않는 부분(core + 단계 + 출력 규칙)을 앞 블록에 두고 cache_control을 붙인다.
매 턴 바뀌는 세션 상태와 재시도 피드백은 그 뒤 블록에 둔다.
"""

from typing import Any

import yaml

from app.engine import resources, stage_machine
from app.models import ARC_BLOCKS, WritingSession
from app.schemas import STAGE_NAMES

STAGE_MODULES = {
    1: "stage1_topic",
    2: "stage2_paragraph",
    3: "stage3_sequence",
    4: "stage4_revise",
}
MAX_HISTORY_TURNS = 40


def stable_system(stage: int) -> str:
    return "\n\n---\n\n".join(
        [resources.prompt("core"), resources.prompt(STAGE_MODULES[stage]),
         resources.prompt("questioner")]
    )


def session_state(session: WritingSession) -> dict[str, Any]:
    """SKILL.md 11장 세션 상태의 실제 값."""
    active = [m for m in session.materials if not m.excluded]
    arc = {
        block: [f"{m.label}: {m.text}" for m in active if m.arc_block == block]
        for block in ARC_BLOCKS
    }
    signals = session.signals
    return {
        "stage": session.stage,
        "topic_sentence": session.topic_sentence,
        "target_length": session.target_length,
        "arc": arc,
        "repeated_words": {
            s.value: s.count for s in signals if s.kind == "repeated" and s.count >= 2
        },
        "open_gaps": [s.value for s in signals if s.kind == "gap" and not s.resolved],
        "skipped_topics": [s.value for s in signals if s.kind == "skipped"],
        "hesitations": [s.value for s in signals if s.kind == "hesitation"][-5:],
        "stage_ready": stage_machine.is_ready_to_close(session),
        "stage_missing": stage_machine.missing(session),
    }


def state_block(session: WritingSession, feedback: str | None = None) -> str:
    state = yaml.safe_dump(session_state(session), allow_unicode=True, sort_keys=False)
    text = f"# 세션 상태\n\n```yaml\n{state}```"
    if feedback:
        text += "\n\n" + feedback
    return text


def stage_opened(stage: int) -> str:
    return resources.prompt("stage_opened").format(stage_name=STAGE_NAMES[stage])


def history(session: WritingSession, opening_stage: int | None = None) -> list[dict[str, Any]]:
    """최근 대화를 messages로.

    messages는 user로 시작해 user로 끝나야 한다 (마지막이 assistant면 prefill이 되어 거부된다).
    - 코치가 먼저 연 대화: 맨 앞에 시작 표시
    - 코치 턴이 연달아 있는 곳(단계를 넘긴 뒤의 여는 질문): 사이에 단계 시작 표시
    - opening_stage: 지금 새 단계의 여는 질문을 만들 때 끝에 붙이는 단계 시작 표시
    """
    turns = session.turns[-MAX_HISTORY_TURNS:]
    messages: list[dict[str, Any]] = []
    for turn in turns:
        role = "assistant" if turn.role == "coach" else "user"
        if messages and messages[-1]["role"] == role:
            if role == "assistant":
                messages.append({"role": "user", "content": stage_opened(turn.stage)})
                messages.append({"role": role, "content": turn.text})
            else:
                messages[-1]["content"] += "\n\n" + turn.text
        else:
            messages.append({"role": role, "content": turn.text})
    if messages and messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": resources.prompt("session_start")})
    if opening_stage is not None:
        marker = stage_opened(opening_stage)
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] += "\n\n" + marker
        else:
            messages.append({"role": "user", "content": marker})
    return messages


def feedback_text(reasons: list[str], rejected: str) -> str:
    return resources.prompt("questioner_feedback").format(
        reasons="\n".join(f"- {r}" for r in reasons), rejected=rejected
    )


def build(
    session: WritingSession, feedback: str | None = None, opening: bool = False
) -> dict[str, Any]:
    return {
        "system": [
            {
                "type": "text",
                "text": stable_system(session.stage),
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": state_block(session, feedback)},
        ],
        "messages": history(session, session.stage if opening else None),
    }
