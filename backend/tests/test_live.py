"""실제 Claude API를 부르는 테스트. 비용이 들므로 RUN_LIVE=1일 때만 돈다.

    cd backend && RUN_LIVE=1 PYTHONUTF8=1 uv run pytest tests/test_live.py -v
"""

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import get_settings
from app.engine import extractor, reviewer
from app.engine.llm import AnthropicLLM, get_llm
from app.main import app
from tests.test_turns import UTTER, parse_sse

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="RUN_LIVE=1일 때만")

GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden" / "quit_job.yaml").read_text(encoding="utf-8")
)


def _golden_pairs() -> list[tuple[list[str], str]]:
    """(그때까지의 사용자 발화 전체, 코치 응답) 쌍."""
    pairs, users = [], []
    for turn in GOLDEN["turns"]:
        if turn["role"] == "user":
            users.append(turn["text"])
        else:
            pairs.append((list(users), turn["text"]))
    return pairs


@pytest.mark.asyncio
@pytest.mark.parametrize(("users", "coach"), _golden_pairs())
async def test_golden_coach_responses_pass_llm_review(users: list[str], coach: str) -> None:
    review = await reviewer.run(
        AnthropicLLM(), question=coach, last_user_text=users[-1], stage=1, user_texts=users
    )
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


@pytest.mark.asyncio
async def test_fidelity_catches_invented_weather_live() -> None:
    from app.engine import fidelity
    from app.engine.assembler import AssembledDraft, DraftParagraph, DraftSentence
    from tests.test_drafting import _materials

    draft = AssembledDraft(paragraphs=[DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="비가 내리는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
        DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
        DraftSentence(text="팀장은 \"이번 분기만 버티자\"고 했다.", material_ids=["m2"]),
    ])])
    utterances = {"t": '회의실 창밖만 보고 있었어요. 팀장님이 또 "이번 분기만 버티자"래요.'}
    out = await fidelity.check(AnthropicLLM(), draft, _materials(), utterances)
    print("\n", [(s.is_blank, s.text) for s in out])
    assert out[0].is_blank, "지어낸 날씨를 놓침"
    assert not out[1].is_blank and not out[2].is_blank, "원문을 다듬은 문장까지 지움"


def test_assemble_real_draft(client: TestClient, db_session) -> None:
    from tests.test_drafting import _seed

    app.dependency_overrides.pop(get_llm, None)
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    events = parse_sse(client.post(f"/sessions/{sid}/drafts").text)
    kind, data = events[-1]
    assert kind == "draft", events
    draft = data["draft"]
    print()
    for p in draft["paragraphs"]:
        print(f"[{p['position']}]", " ".join(s["text"] for s in p["sentences"]))
    print("표시:", [(h["label"], h["text"]) for h in draft["hits"]])
    for p in draft["paragraphs"]:
        for s in p["sentences"]:
            assert s["is_blank"] or s["materials"], f"출처 없는 문장: {s['text']}"


@pytest.mark.asyncio
@pytest.mark.skipif(not get_settings().openai_api_key, reason="OPENAI_API_KEY 없음")
async def test_voice_round_trip_live() -> None:
    """질문을 합성(TTS)한 mp3를 다시 받아쓰기(STT)해 원문과 비교한다."""
    from difflib import SequenceMatcher

    from app.voice.openai_voice import OpenAIVoice

    text = "‘창밖만 보고 있었어요’라고 하셨어요. 그때 창밖에는 무엇이 보였어요?"
    voice = OpenAIVoice()
    mp3 = await voice.speak(text)
    assert mp3[:3] == b"ID3" or mp3[:2] == b"\xff\xfb" or len(mp3) > 1000
    heard = await voice.transcribe(mp3, filename="q.mp3", content_type="audio/mpeg",
                                   hint="창밖 회의실")
    print("\n받아쓴 글:", heard)
    plain = lambda s: "".join(ch for ch in s if ch.isalnum())
    assert SequenceMatcher(None, plain(text), plain(heard)).ratio() > 0.8
