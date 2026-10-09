from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engine.assembler import AssembledDraft, DraftParagraph, DraftSentence
from app.engine.fidelity import FidelityResult, SentenceVerdict
from app.engine.llm import LLMError, get_llm
from app.engine.tagging import TagSet
from app.main import app
from app.models import WritingSession
from tests.fakes import FakeLLM
from tests.test_drafting import _seed
from tests.test_turns import parse_sse

APPROVE = {"approved": True}


@pytest.fixture
def fake() -> Iterator[FakeLLM]:
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


def _drafted(db: Session, client: TestClient, fake: FakeLLM) -> str:
    sid = _seed(db, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    client.post(f"/sessions/{sid}/advance", json=APPROVE)
    fake.queue(AssembledDraft(paragraphs=[
        DraftParagraph(outline_position=1, sentences=[
            DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"])]),
        DraftParagraph(outline_position=5, sentences=[
            DraftSentence(text="창밖을 봤는데 그냥 하늘이 보였다.", material_ids=["m5"])]),
    ]))
    fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=0, ok=True),
                                        SentenceVerdict(index=1, ok=True)]))
    parse_sse(client.post(f"/sessions/{sid}/drafts").text)
    return sid


def test_suggest_does_not_save(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid = _drafted(db_session, client, fake)
    fake.queue(TagSet(person=["팀장님"], place=["회의실"], object=["창밖"],
                      gap=["그 말을 처음 들었던 날, 어디에 있었어요?"]))
    suggested = client.post(f"/sessions/{sid}/tags/suggest").json()
    assert suggested["place"] == ["회의실"]
    assert client.get(f"/sessions/{sid}/tags").json()["place"] == []
    # 제안 프롬프트에는 글 본문과 쓰지 않은 재료가 들어간다
    prompt = fake.parse_calls[-1]["user"]
    assert "나는 회의실 창밖만 보고 있었다." in prompt
    assert "- 이번 분기만 버티자" in prompt


def test_suggest_falls_back_to_repeated_words(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _drafted(db_session, client, fake)

    async def broken(**_: object) -> object:
        raise LLMError("boom")

    fake.parse = broken  # type: ignore[method-assign]
    assert client.post(f"/sessions/{sid}/tags/suggest").json()["object"] == ["창밖"]


def test_save_finish_and_library(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid = _drafted(db_session, client, fake)
    gap_q = "그 말을 처음 들었던 날, 어디에 있었어요?"
    saved = client.put(f"/sessions/{sid}/tags", json={
        "period": ["첫 직장"], "person": ["팀장님", "팀장님", " "], "place": ["회의실"],
        "object": ["창밖"], "gap": [gap_q],
    }).json()
    assert saved["person"] == ["팀장님"]  # 중복·빈 값 제거
    assert client.get(f"/sessions/{sid}/finish-check").json() == []

    client.patch(f"/sessions/{sid}", json={"title": "회사를 그만둔 날"})
    assert client.post(f"/sessions/{sid}/finish", json=APPROVE).json()["status"] == "done"

    lib = client.get("/library").json()
    [item] = lib["done"]
    assert item["title"] == "회사를 그만둔 날"
    assert item["paragraphs"] == 2
    assert item["first_sentence"] == "나는 회의실 창밖만 보고 있었다."
    assert item["tags"]["object"] == ["창밖"]
    assert lib["next_topics"] == [
        {"question": gap_q, "from_session_id": sid, "from_title": "회사를 그만둔 날"}
    ]

    # 다음 글감으로 새 글을 시작하면 그 질문은 목록에서 빠진다
    client.post("/sessions", json={"opening_question": gap_q})
    assert client.get("/library").json()["next_topics"] == []


def test_finish_requires_draft_and_approval(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _seed(db_session, client)
    assert client.post(f"/sessions/{sid}/finish", json={"approved": False}).status_code == 422
    assert client.post(f"/sessions/{sid}/finish", json=APPROVE).status_code == 409
    assert db_session.get(WritingSession, sid).status == "active"


def test_library_is_private(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid = _drafted(db_session, client, fake)
    client.post(f"/sessions/{sid}/finish", json=APPROVE)
    assert client.get("/library", headers={"X-User-Id": "other"}).json()["done"] == []
