import json
from collections.abc import Iterator
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engine.extractor import ExtractedMaterial, Extraction
from app.engine.llm import LLMError, get_llm
from app.main import app
from app.models import WritingSession
from tests.fakes import FakeLLM, failing_review, state_text

UTTER = "회의실이었어요. 팀장님이 또 같은 얘기를 하는데, 아 이건 아니다 싶었어요. 창밖만 보고 있었어요."


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


@pytest.fixture
def fake() -> Iterator[FakeLLM]:
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


def _start(client: TestClient) -> str:
    return client.post("/sessions", json={}).json()["id"]


def _send(client: TestClient, sid: str, text: str = UTTER, **extra) -> list[tuple[str, dict]]:
    res = client.post(f"/sessions/{sid}/turns", json={"text": text, **extra})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    return parse_sse(res.text)


def test_turn_happy_path(client: TestClient, fake: FakeLLM, db_session: Session) -> None:
    fake.extractions.append(
        Extraction(
            materials=[
                ExtractedMaterial(text="회의실이었어요", type="place", arc_block="scene"),
                ExtractedMaterial(text="창밖만 보고 있었어요", type="scene", arc_block="scene"),
                ExtractedMaterial(text="창밖에 비가 내렸어요", type="sense", arc_block="scene"),
            ],
            key_words=["창밖", "또 같은 얘기"],
            open_gaps=["팀장님의 그 얘기"],
        )
    )
    question = "'또 같은 얘기'라고 하셨어요. 그날 들은 문장 중에 기억나는 게 있어요?"
    fake.questions.append(question)
    sid = _start(client)

    events = _send(client, sid, input_mode="voice")
    kinds = [k for k, _ in events if k != "question_delta"]
    assert kinds == ["status", "materials", "question"]
    # 질문은 글자 단위로 먼저 흘러가고, 이어 붙이면 최종 질문과 같다
    streamed = "".join(d["text"] for k, d in events if k == "question_delta")
    assert streamed == question
    materials = dict(events)["materials"]
    # 지어낸 재료(원문에 없는 '비가 내렸어요')는 저장되지 않는다
    assert [m["text"] for m in materials["added"]] == ["회의실이었어요", "창밖만 보고 있었어요"]
    assert [m["label"] for m in materials["added"]] == ["m1", "m2"]
    assert materials["session"]["arc"]["scene"] == 2
    assert materials["session"]["gaps"] == ["팀장님의 그 얘기"]
    assert events[-1][1]["turn"]["text"] == question

    turns = client.get(f"/sessions/{sid}/turns").json()
    assert [(t["role"], t["input_mode"]) for t in turns] == [
        ("coach", None), ("user", "voice"), ("coach", None)
    ]
    assert turns[1]["text"] == UTTER  # 사용자 원문 그대로

    meta = db_session.get(WritingSession, sid).turns[-1].meta
    assert meta["passed"] is True and len(meta["attempts"]) == 1
    assert meta["review"]["passed"] is True  # LLM 검수는 보낸 뒤 기록용으로 돈다

def test_repeated_words_counted_across_turns(client: TestClient, fake: FakeLLM) -> None:
    fake.extractions += [Extraction(key_words=["창밖"]), Extraction(key_words=["창밖"])]
    sid = _start(client)
    _send(client, sid)
    events = _send(client, sid, text="그날도 창밖을 봤어요. 창밖엔 주차장이 있었어요.")
    session = dict(events)["materials"]["session"]
    assert session["repeated"] == [{"value": "창밖", "count": 3}]


def test_rule_failure_triggers_regeneration_with_feedback(
    client: TestClient, fake: FakeLLM, db_session: Session
) -> None:
    fake.questions += ["그때 어디였어요? 누구와 있었어요?", "'창밖만'이라고 하셨어요. 창밖에 무엇이 보였어요?"]
    sid = _start(client)
    events = _send(client, sid)
    kinds = [k for k, _ in events]
    assert "question_reset" in kinds  # 화면은 흘러가던 질문을 지우고 다시 받는다
    assert events[-1][1]["turn"]["text"].startswith("'창밖만'")
    # 두 번째 생성 요청에는 탈락 사유가 피드백으로 들어간다
    second_state = state_text(fake.text_calls[1])
    assert "물음표가 2개" in second_state
    assert db_session.get(WritingSession, sid).turns[-1].meta["passed"] is True

def test_llm_review_runs_after_sending_and_does_not_block(
    client: TestClient, fake: FakeLLM, db_session: Session
) -> None:
    """LLM 검수가 탈락시켜도 다시 만들지 않는다 (속도). 결과는 기록만 남는다."""
    fake.questions.append("'창밖만'이라고 하셨어요. 무엇이 보였어요?")
    fake.reviews.append(failing_review("구체성이 부족하다."))
    sid = _start(client)
    events = _send(client, sid)
    assert "question_reset" not in [k for k, _ in events]
    meta = db_session.get(WritingSession, sid).turns[-1].meta
    assert meta["passed"] is True and meta["review"] == {
        "passed": False, "reasons": ["구체성이 부족하다."]
    }

def test_gives_up_after_three_attempts_but_still_asks(
    client: TestClient, fake: FakeLLM, db_session: Session
) -> None:
    fake.questions += ["질문1? 어디였어요?", "질문2? 어디였어요?", "질문3? 어디였어요?"]
    sid = _start(client)
    events = _send(client, sid)
    assert [k for k, _ in events].count("question_reset") == 2
    assert events[-1][0] == "question"
    assert events[-1][1]["turn"]["text"] == "질문3? 어디였어요?"
    meta = db_session.get(WritingSession, sid).turns[-1].meta
    assert meta["passed"] is False and len(meta["attempts"]) == 3
    assert "review" not in meta  # 규칙에서 탈락한 질문은 LLM 검수를 하지 않는다

def test_distress_sends_fixed_reply_without_streaming_question(
    client: TestClient, fake: FakeLLM
) -> None:
    fake.extractions.append(Extraction(distress=True))
    sid = _start(client)
    events = _send(client, sid, text="이 얘기를 하니까 너무 괴로워서 견딜 수가 없어요")
    # 질문 생성은 동시에 시작했지만, 추출 전까지 화면에 보내지 않았고 버렸다
    assert "question_delta" not in [k for k, _ in events]
    assert events[-1][0] == "question"
    assert "멈춰도 괜찮아요" in events[-1][1]["turn"]["text"]

def test_skip_request_is_remembered(client: TestClient, fake: FakeLLM) -> None:
    fake.extractions.append(Extraction(skip_request=True, skip_topic="아버지 이야기"))
    sid = _start(client)
    _send(client, sid, text="아버지 얘기는 넘어갈게요")
    # 질문 생성은 추출과 동시에 시작하므로, 이번 턴의 넘어가기는 다음 턴의 상태부터 들어간다
    # (이번 턴 질문자도 대화 기록에서 "넘어갈게요"를 직접 본다)
    _send(client, sid, text="고등학교 때 버스 얘기를 할게요")
    state = state_text(fake.text_calls[-1])
    assert "skipped_topics:\n- 아버지 이야기" in state


def test_card_offered_once_when_stage_ready(client: TestClient, fake: FakeLLM) -> None:
    ready = Extraction(
        materials=[ExtractedMaterial(text="회의실이었어요", type="place", arc_block="scene")],
        topic_sentence="창밖만 보고 있었어요",
        target_length="medium",
    )
    fake.extractions += [ready, Extraction()]
    sid = _start(client)
    first = [k for k, _ in _send(client, sid)]
    assert "card" in first and first.index("card") < first.index("question")
    second = [k for k, _ in _send(client, sid, text="네 맞아요.")]
    assert "card" not in second

    card = client.get(f"/sessions/{sid}/material-card").json()
    assert card["ready"] is True and card["missing"] == []
    assert card["topic_sentence"] == "창밖만 보고 있었어요"
    assert card["blocks"][0]["materials"][0]["text"] == "회의실이었어요"


def test_extractor_failure_does_not_block_question(client: TestClient, fake: FakeLLM) -> None:
    original = fake.parse

    async def extractor_broken(**kwargs: object) -> object:
        if kwargs["schema"] is Extraction:
            raise LLMError("boom")
        return await original(**kwargs)

    fake.parse = extractor_broken  # type: ignore[method-assign]
    fake.questions.append("'창밖만'이라고 하셨어요. 무엇이 보였어요?")
    sid = _start(client)
    events = _send(client, sid)
    assert dict(events)["materials"]["added"] == []
    assert events[-1][0] == "question"
    assert client.get(f"/sessions/{sid}/turns").json()[1]["text"] == UTTER


def test_question_failure_sends_error_and_keeps_user_turn(
    client: TestClient, fake: FakeLLM
) -> None:
    async def broken(**_: object):
        raise LLMError("boom")
        yield ""  # 비동기 생성기로 만들기 위한 줄 (도달하지 않음)

    fake.stream_text = broken  # type: ignore[method-assign]
    sid = _start(client)
    events = _send(client, sid)
    assert events[-1][0] == "error"
    turns = client.get(f"/sessions/{sid}/turns").json()
    assert [t["role"] for t in turns] == ["coach", "user"]
    assert turns[-1]["text"] == UTTER

def test_patch_session_and_exclude_material(client: TestClient, fake: FakeLLM) -> None:
    fake.extractions.append(
        Extraction(materials=[ExtractedMaterial(text="회의실이었어요", type="place",
                                                 arc_block="scene")])
    )
    sid = _start(client)
    mid = dict(_send(client, sid))["materials"]["added"][0]["id"]

    res = client.patch(f"/sessions/{sid}", json={"title": "회사를 그만둔 날"})
    assert res.json()["title"] == "회사를 그만둔 날"
    res = client.patch(f"/sessions/{sid}/materials/{mid}", json={"excluded": True})
    assert res.json()["excluded"] is True
    assert client.get(f"/sessions/{sid}").json()["arc"]["scene"] == 0
    # 원문은 바꿀 수 없다: text 필드는 무시된다
    res = client.patch(f"/sessions/{sid}/materials/{mid}", json={"excluded": False, "text": "x"})
    assert res.json()["text"] == "회의실이었어요"
    # 블록 옮기기: 빼 두기 상태는 그대로, 아크 개수에 바로 반영
    res = client.patch(f"/sessions/{sid}/materials/{mid}", json={"arc_block": "resonance"})
    assert res.json()["arc_block"] == "resonance" and res.json()["excluded"] is False
    arc = client.get(f"/sessions/{sid}").json()["arc"]
    assert arc["resonance"] == 1 and arc["scene"] == 0
    assert client.patch(f"/sessions/{sid}/materials/{mid}", json={"arc_block": "x"}).status_code == 422


def test_turn_validation(client: TestClient, fake: FakeLLM) -> None:
    sid = _start(client)
    assert client.post(f"/sessions/{sid}/turns", json={"text": ""}).status_code == 422
    other = {"X-User-Id": "someone-else"}
    assert client.post(f"/sessions/{sid}/turns", json={"text": "a"}, headers=other).status_code == 404


def test_skip_button_records_last_question_without_extraction(
    client: TestClient, fake: FakeLLM
) -> None:
    sid = _start(client)
    first_q = client.get(f"/sessions/{sid}/turns").json()[0]["text"]
    events = _send(client, sid, text="이 질문은 넘어갈게요.", skip=True)
    assert "extracting" not in [d.get("step") for k, d in events if k == "status"]
    assert [c for c in fake.parse_calls if c["schema"] is Extraction] == []
    state = state_text(fake.text_calls[0])
    assert f"skipped_topics:\n- {first_q}" in state


def test_stage_opening_question_after_advance(client: TestClient, fake: FakeLLM) -> None:
    sid = _start(client)
    _send(client, sid)
    client.post(f"/sessions/{sid}/advance", json={"approved": True})
    fake.questions.append("오프닝으로 고른 그 회의실에서, 손은 무엇을 하고 있었어요?")
    res = client.post(f"/sessions/{sid}/coach")
    events = parse_sse(res.text)
    assert events[-1][0] == "question"
    assert events[-1][1]["turn"]["stage"] == 2
    messages = [m for m in fake.text_calls[-1]["messages"] if m["role"] != "system"]
    last = messages[-1]
    text = last["content"] if isinstance(last["content"], str) else last["content"][0]["text"]
    assert last["role"] == "user" and "단락 구성" in text

    # 다음 턴에서는 연달아 있는 코치 턴 사이에 단계 시작 표시가 들어가 역할이 번갈아 나온다
    _send(client, sid, text="볼펜을 쥐고 있었어요.")
    roles = [m["role"] for m in fake.text_calls[-1]["messages"] if m["role"] != "system"]
    assert all(a != b for a, b in pairwise(roles))
    assert roles[0] == "user" and roles[-1] == "user"


def test_daily_llm_limit(client: TestClient, fake: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "daily_llm_limit", 1)
    sid = _start(client)
    assert client.post(f"/sessions/{sid}/turns", json={"text": "첫 답"}).status_code == 200
    res = client.post(f"/sessions/{sid}/turns", json={"text": "둘째 답"})
    assert res.status_code == 429
    assert "내일" in res.json()["detail"]
    assert client.get(f"/sessions/{sid}").status_code == 200  # 읽기는 막지 않는다


def test_per_user_daily_limit(client: TestClient, fake: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "daily_llm_limit_per_user", 1)
    a = client.post("/sessions", json={}, headers={"X-User-Id": "alice"}).json()["id"]
    b = client.post("/sessions", json={}, headers={"X-User-Id": "bob"}).json()["id"]
    assert client.post(f"/sessions/{a}/turns", json={"text": "첫 답"}, headers={"X-User-Id": "alice"}).status_code == 200
    res = client.post(f"/sessions/{a}/turns", json={"text": "둘째"}, headers={"X-User-Id": "alice"})
    assert res.status_code == 429 and "오늘은 여기까지" in res.json()["detail"]
    # 다른 사람은 영향을 받지 않는다
    assert client.post(f"/sessions/{b}/turns", json={"text": "첫 답"}, headers={"X-User-Id": "bob"}).status_code == 200


def test_late_distress_signal_resets_streamed_question(client: TestClient, fake: FakeLLM) -> None:
    """위험 표현이 없어 질문을 먼저 흘려보냈는데 추출이 고통 신호를 잡으면, 질문을 지우고 바꾼다."""
    fake.extractions.append(Extraction(distress=True))
    sid = _start(client)
    events = _send(client, sid, text="그날 이후로 아무것도 하기가 싫어요")
    kinds = [k for k, _ in events]
    assert "question_delta" in kinds
    assert kinds.index("question_reset") > kinds.index("question_delta")
    assert "멈춰도 괜찮아요" in events[-1][1]["turn"]["text"]
    turns = client.get(f"/sessions/{sid}/turns").json()
    assert len(turns) == 3 and "멈춰도 괜찮아요" in turns[-1]["text"]  # 흘러간 질문은 저장되지 않았다


def test_streaming_starts_before_extraction_finishes(client: TestClient, fake: FakeLLM) -> None:
    """추출이 느려도 질문 조각은 먼저 나간다 (속도)."""
    import asyncio

    original = fake.parse

    async def slow_parse(**kwargs: object) -> object:
        if kwargs["schema"] is Extraction:
            await asyncio.sleep(0.2)
        return await original(**kwargs)

    fake.parse = slow_parse  # type: ignore[method-assign]
    sid = _start(client)
    kinds = [k for k, _ in _send(client, sid)]
    assert kinds.index("question_delta") < kinds.index("materials") < kinds.index("question")


def test_other_ai_requests_count_toward_daily_limit(
    client: TestClient, fake: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "daily_llm_limit_per_user", 2)
    sid = _start(client)
    client.post(f"/sessions/{sid}/advance", json={"approved": True})
    assert client.post(f"/sessions/{sid}/coach").status_code == 200  # 여는 질문 1건
    assert client.post(f"/sessions/{sid}/turns", json={"text": "첫 답"}).status_code == 200  # 2건
    assert client.post(f"/sessions/{sid}/coach").status_code == 429


def test_turn_records_llm_usage(client: TestClient, fake: FakeLLM, db_session: Session) -> None:
    """운영 비용 감시: 한 턴의 LLM 호출(추출·질문·검수)이 llm_usage에 남는다."""
    from sqlalchemy import select

    from app.models import LlmUsage

    sid = _start(client)
    _send(client, sid)
    rows = db_session.scalars(select(LlmUsage)).all()
    assert len(rows) >= 2  # 추출 + 질문 (사후 검수는 저장 뒤에 끝날 수 있다)
    assert {r.kind for r in rows} == {"turn"} and {r.session_id for r in rows} == {sid}
    assert all(r.user_id == "dev-user" and r.input_tokens == 100 for r in rows)


def test_stuck_button_asks_easier_question_without_extraction(
    client: TestClient, fake: FakeLLM
) -> None:
    """'막혔어요': 추출 없이, 같은 장면을 더 작은 질문으로 다시 묻게 하는 안내가 질문자에게 간다."""
    fake.questions.append("그때 손에 무엇을 들고 있었어요?")
    sid = _start(client)
    events = _send(client, sid, text="잘 떠오르지 않아요.", stuck=True)
    assert [c for c in fake.parse_calls if c["schema"] is Extraction] == []
    assert events[-1][0] == "question"
    assert "막혔어요" in state_text(fake.text_calls[0])
    turns = client.get(f"/sessions/{sid}/turns").json()
    assert [t["role"] for t in turns] == ["coach", "user", "coach"]
    # 넘어가기와 달리 넘어간 주제로 기록하지 않는다
    assert client.get(f"/sessions/{sid}/material-card").json()["missing"]


def test_extractor_gets_first_scene_for_resonance(client: TestClient, fake: FakeLLM) -> None:
    """여운 판정: 추출기는 첫 장면의 재료를 함께 본다 (발화 하나만으로는 '다시 나온 사물'을 모른다)."""
    fake.extractions.append(Extraction(materials=[
        ExtractedMaterial(text="볼펜 뚜껑을 딸깍거렸어요", type="scene", arc_block="scene")]))
    sid = _start(client)
    _send(client, sid, text="볼펜 뚜껑을 딸깍거렸어요.")
    _send(client, sid, text="요즘도 회의 때 볼펜을 딸깍거려요.")
    user = [c for c in fake.parse_calls if c["schema"] is Extraction][-1]["user"]
    assert "첫 장면의 재료" in user and "- 볼펜 뚜껑을 딸깍거렸어요" in user
