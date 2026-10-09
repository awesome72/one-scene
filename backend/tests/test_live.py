"""실제 Claude API를 부르는 테스트. 비용이 들므로 RUN_LIVE=1일 때만 돈다.

    cd backend && RUN_LIVE=1 PYTHONUTF8=1 uv run pytest tests/test_live.py -v
"""

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.engine import extractor, reviewer
from app.engine.llm import AnthropicLLM, get_llm
from app.main import app
from tests.test_turns import UTTER, parse_sse

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="RUN_LIVE=1일 때만")

GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden" / "quit_job.yaml").read_text(encoding="utf-8")
)


def _golden_pairs() -> list[tuple[str | None, str]]:
    """(직전 사용자 발화, 코치 응답) 쌍."""
    pairs, last_user = [], None
    for turn in GOLDEN["turns"]:
        if turn["role"] == "user":
            last_user = turn["text"]
        else:
            pairs.append((last_user, turn["text"]))
    return pairs


@pytest.mark.asyncio
@pytest.mark.parametrize(("user", "coach"), _golden_pairs())
async def test_golden_coach_responses_pass_llm_review(user: str | None, coach: str) -> None:
    review = await reviewer.run(AnthropicLLM(), question=coach, last_user_text=user, stage=1)
    assert review.passed, review.reasons


@pytest.mark.asyncio
async def test_generic_question_fails_llm_review() -> None:
    """규칙은 통과하지만 어느 대답 뒤에 붙여도 되는 추상 질문 → LLM 검수에서 탈락해야 한다."""
    question = "그때 기분이 어땠어요?"
    assert reviewer.rule_check(question) == []
    review = await reviewer.run(AnthropicLLM(), question=question, last_user_text=UTTER, stage=1)
    assert not review.passed


@pytest.mark.asyncio
async def test_extractor_keeps_only_verbatim() -> None:
    result = await extractor.run(
        AnthropicLLM(), utterance=UTTER, stage=1,
        last_question="그만두기로 마음먹은 그 순간, 어디에 있었어요?", known_gaps=[],
    )
    assert result.materials, "재료를 하나도 못 뽑음"
    assert all(m.text in UTTER for m in result.materials)
    print([(m.text, m.type, m.arc_block) for m in result.materials], result.key_words)


def test_full_turn_through_api(client: TestClient) -> None:
    app.dependency_overrides.pop(get_llm, None)
    sid = client.post(
        "/sessions", json={"opening_question": "그만두기로 마음먹은 그 순간, 어디에 있었어요?"}
    ).json()["id"]
    res = client.post(f"/sessions/{sid}/turns", json={"text": UTTER})
    events = parse_sse(res.text)
    kind, data = events[-1]
    assert kind == "question", events
    question = data["turn"]["text"]
    print("\n코치:", question)
    assert reviewer.rule_check(question) == []
