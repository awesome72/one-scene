from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Material, Signal, WritingSession
from app.routers.sessions import opening_questions

APPROVE = {"approved": True}


def _create(client: TestClient, **body) -> dict:
    res = client.post("/sessions", json=body)
    assert res.status_code == 201
    return res.json()


def test_create_session_returns_default_first_question(client: TestClient) -> None:
    data = _create(client)
    assert data["stage"] == 1
    assert data["stage_name"] == "주제 설정"
    assert data["status"] == "active"
    assert data["last_question"] == opening_questions()[0]
    assert data["arc"] == {"scene": 0, "event": 0, "meaning": 0, "present": 0, "resonance": 0}


def test_create_session_with_chosen_opening_question(client: TestClient) -> None:
    question = "그 말을 처음 들었던 날, 어디에 있었어요?"
    data = _create(client, opening_question=question)
    turns = client.get(f"/sessions/{data['id']}/turns").json()
    assert [(t["role"], t["text"], t["idx"]) for t in turns] == [("coach", question, 0)]


def test_opening_questions_list(client: TestClient) -> None:
    res = client.get("/opening-questions")
    assert res.status_code == 200
    assert len(res.json()) >= 4


def test_advance_requires_explicit_approval(client: TestClient) -> None:
    sid = _create(client)["id"]
    assert client.post(f"/sessions/{sid}/advance").status_code == 422
    assert client.post(f"/sessions/{sid}/advance", json={"approved": False}).status_code == 422
    assert client.get(f"/sessions/{sid}").json()["stage"] == 1


def test_advance_and_back_move_one_stage(client: TestClient) -> None:
    sid = _create(client)["id"]
    res = client.post(f"/sessions/{sid}/advance", json=APPROVE)
    assert res.status_code == 200
    assert res.json()["stage"] == 2
    assert res.json()["stage_name"] == "단락 구성"
    res = client.post(f"/sessions/{sid}/back", json=APPROVE)
    assert res.json()["stage"] == 1


def test_stage_bounds(client: TestClient) -> None:
    sid = _create(client)["id"]
    assert client.post(f"/sessions/{sid}/back", json=APPROVE).status_code == 409
    for _ in range(3):
        assert client.post(f"/sessions/{sid}/advance", json=APPROVE).status_code == 200
    assert client.post(f"/sessions/{sid}/advance", json=APPROVE).status_code == 409
    assert client.get(f"/sessions/{sid}").json()["stage"] == 4


def test_sessions_are_private_to_user(client: TestClient) -> None:
    sid = client.post("/sessions", json={}, headers={"X-User-Id": "alice"}).json()["id"]
    other = {"X-User-Id": "bob"}
    assert client.get(f"/sessions/{sid}", headers=other).status_code == 404
    assert client.post(f"/sessions/{sid}/advance", json=APPROVE, headers=other).status_code == 404
    assert client.get("/sessions", headers=other).json() == []
    assert len(client.get("/sessions", headers={"X-User-Id": "alice"}).json()) == 1


def test_unknown_session_404(client: TestClient) -> None:
    assert client.get("/sessions/nope").status_code == 404


def test_detail_counts_materials_and_signals(client: TestClient, db_session: Session) -> None:
    sid = _create(client)["id"]
    session = db_session.get(WritingSession, sid)
    turn = session.turns[0]
    session.materials += [
        Material(seq=1, turn_id=turn.id, text="회의실이었어요", type="place", arc_block="scene"),
        Material(seq=2, turn_id=turn.id, text="창밖만 보고", type="scene", arc_block="scene"),
        Material(
            seq=3, turn_id=turn.id, text="빼 둔 재료", type="fact", arc_block="event", excluded=True
        ),
    ]
    session.signals += [
        Signal(kind="repeated", value="창밖", count=3),
        Signal(kind="repeated", value="한 번만", count=1),
        Signal(kind="gap", value="그 말을 처음 들은 날"),
        Signal(kind="gap", value="해결된 틈", resolved=True),
    ]
    db_session.commit()

    data = client.get(f"/sessions/{sid}").json()
    assert data["material_count"] == 2
    assert data["arc"]["scene"] == 2
    assert data["arc"]["event"] == 0  # 빼 둔 재료는 세지 않는다
    assert data["repeated"] == [{"value": "창밖", "count": 3}]
    assert data["gaps"] == ["그 말을 처음 들은 날"]


def test_timestamps_are_utc_aware(client: TestClient, db_session: Session) -> None:
    sid = _create(client)["id"]
    db_session.expire_all()  # DB에서 다시 읽게 한다
    listed = client.get("/sessions").json()[0]["updated_at"]
    assert listed.endswith(("Z", "+00:00")), listed
    assert client.get(f"/sessions/{sid}").status_code == 200
