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
from tests.fakes import PASS, FakeLLM, failing_review

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
    kinds = [k for k, _ in events]
    assert kinds == ["status", "materials", "status", "status", "question"]
    materials = events[1][1]
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


def test_repeated_words_counted_across_turns(client: TestClient, fake: FakeLLM) -> None:
    fake.extractions += [Extraction(key_words=["창밖"]), Extraction(key_words=["창밖"])]
    sid = _start(client)
    _send(client, sid)
    events = _send(client, sid, text="그날도 창밖을 봤어요. 창밖엔 주차장이 있었어요.")
    session = dict(events)["materials"]["session"]
    assert session["repeated"] == [{"value": "창밖", "count": 3}]


def test_reviewer_failure_triggers_regeneration_with_feedback(
    client: TestClient, fake: FakeLLM, db_session: Session
) -> None:
    fake.questions += ["그때 어디에 있었어요?", "'창밖만'이라고 하셨어요. 창밖에 무엇이 보였어요?"]
    fake.reviews += [failing_review("직전 발화를 이어받지 않는다."), PASS]
    sid = _start(client)
    events = _send(client, sid)
    assert [d.get("attempt") for k, d in events if k == "status"] == [None, 1, 1, 2, 2]
    assert events[-1][1]["turn"]["text"].startswith("'창밖만'")
    # 두 번째 생성 요청에는 탈락 사유가 피드백으로 들어간다
    second_state = fake.text_calls[1]["system"][1]["text"]
    assert "직전 발화를 이어받지 않는다." in second_state
    assert db_session.get(WritingSession, sid).turns[-1].meta["passed"] is True


def test_rule_failure_does_not_call_llm_reviewer(client: TestClient, fake: FakeLLM) -> None:
    fake.questions += ["멋진 이야기네요. 어디였어요?", "'창밖만'이라고 하셨어요. 무엇이 보였어요?"]
    sid = _start(client)
    _send(client, sid)
    reviewer_calls = [c for c in fake.parse_calls if c["schema"].__name__ == "Review"]
    assert len(reviewer_calls) == 1  # 첫 시도는 규칙에서 탈락해 LLM 검수를 건너뛴다


def test_gives_up_after_three_attempts_but_still_asks(
    client: TestClient, fake: FakeLLM, db_session: Session
) -> None:
    fake.questions += ["질문1 어디였어요?", "질문2 어디였어요?", "질문3 어디였어요?"]
    fake.reviews += [failing_review("x")] * 3
    sid = _start(client)
    events = _send(client, sid)
    assert events[-1][0] == "question"
    assert events[-1][1]["turn"]["text"] == "질문3 어디였어요?"
    meta = db_session.get(WritingSession, sid).turns[-1].meta
    assert meta["passed"] is False and len(meta["attempts"]) == 3


def test_distress_sends_fixed_reply_without_asking(client: TestClient, fake: FakeLLM) -> None:
    fake.extractions.append(Extraction(distress=True))
    sid = _start(client)
    events = _send(client, sid, text="이 얘기를 하니까 너무 괴로워서 견딜 수가 없어요")
    assert fake.text_calls == []
    assert events[-1][0] == "question"
    assert "멈춰도 괜찮아요" in events[-1][1]["turn"]["text"]


def test_skip_request_is_remembered(client: TestClient, fake: FakeLLM) -> None:
    fake.extractions.append(Extraction(skip_request=True, skip_topic="아버지 이야기"))
    sid = _start(client)
    _send(client, sid, text="아버지 얘기는 넘어갈게요")
    state = fake.text_calls[0]["system"][1]["text"]
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
    assert events[1][1]["added"] == []
    assert events[-1][0] == "question"
    assert client.get(f"/sessions/{sid}/turns").json()[1]["text"] == UTTER


def test_question_failure_sends_error_and_keeps_user_turn(
    client: TestClient, fake: FakeLLM
) -> None:
    async def broken(**_: object) -> str:
        raise LLMError("boom")

    fake.text = broken  # type: ignore[method-assign]
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
    state = fake.text_calls[0]["system"][1]["text"]
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
    messages = fake.text_calls[-1]["messages"]
    assert messages[-1]["role"] == "user" and "단락 구성" in messages[-1]["content"]

    # 다음 턴에서는 연달아 있는 코치 턴 사이에 단계 시작 표시가 들어가 역할이 번갈아 나온다
    _send(client, sid, text="볼펜을 쥐고 있었어요.")
    roles = [m["role"] for m in fake.text_calls[-1]["messages"]]
    assert all(a != b for a, b in pairwise(roles))
    assert roles[0] == "user" and roles[-1] == "user"
