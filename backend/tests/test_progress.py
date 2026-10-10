"""진행 신호(engine/progress.py)와 단계별 이탈 기록(journey_events)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JourneyEvent, LlmUsage, Material, Turn, WritingSession

APPROVE = {"approved": True}


def _start(client: TestClient) -> dict:
    res = client.post("/sessions", json={})
    assert res.status_code == 201
    return res.json()


def _add(db: Session, sid: str, block: str, type_: str = "scene", text: str = "창밖") -> None:
    session = db.get(WritingSession, sid)
    turn = Turn(idx=len(session.turns), role="user", text=text, stage=session.stage)
    session.turns.append(turn)
    db.flush()
    seq = len(session.materials) + 1
    session.materials.append(Material(seq=seq, turn_id=turn.id, text=text, type=type_,
                                      arc_block=block))
    db.commit()


def test_new_session_progress_shows_stage1_conditions(client: TestClient) -> None:
    p = _start(client)["progress"]
    assert [c["key"] for c in p["conditions"]] == ["topic", "opening_scene", "length"]
    assert not any(c["done"] for c in p["conditions"])
    assert p["journey"] == 0 and p["stage_fraction"] == 0 and p["ready"] is False
    assert p["next_need"] == "이 글이 무엇에 관한 이야기인지 한 문장으로"
    assert p["expected_turns"] == [8, 12] and p["turns_in_stage"] == 0
    # 남은 시간: 네 단계 전체 범위 (10~15 + 15~25 + 5~10 + 10~20)
    assert p["remaining_minutes"] == [40, 70]


def test_progress_follows_materials_and_stage(client: TestClient, db_session: Session) -> None:
    sid = _start(client)["id"]
    _add(db_session, sid, "scene")
    s = db_session.get(WritingSession, sid)
    s.topic_sentence, s.target_length = "그만둔 날", "medium"
    db_session.commit()
    detail = client.get(f"/sessions/{sid}").json()
    p = detail["progress"]
    assert p["ready"] and p["stage_fraction"] == 1 and p["next_need"] is None
    assert p["turns_in_stage"] == 1 and p["journey"] == 1.0
    assert detail["stage"] == 1  # ready여도 단계는 그대로 (이동은 사용자 승인으로만)

    p = client.post(f"/sessions/{sid}/advance", json=APPROVE).json()["progress"]
    keys = {c["key"]: c for c in p["conditions"]}
    assert keys["block_scene"]["done"] and not keys["block_meaning"]["done"]
    assert (keys["scene_senses"]["have"], keys["scene_senses"]["need"]) == (0, 2)
    assert 1 < p["journey"] < 2 and p["next_block"] == "event"
    assert p["turns_in_stage"] == 0  # 1단계의 대답은 세지 않는다

    _add(db_session, sid, "scene", "sense", "빗소리")
    p2 = client.get(f"/sessions/{sid}").json()["progress"]
    assert p2["stage_fraction"] > p["stage_fraction"]


def test_finished_session_progress_is_complete(client: TestClient, db_session: Session) -> None:
    sid = _start(client)["id"]
    s = db_session.get(WritingSession, sid)
    s.status = "done"
    db_session.commit()
    p = client.get(f"/sessions/{sid}").json()["progress"]
    assert p["journey"] == 5 and p["remaining_minutes"] == [0, 0] and not p["ready"]


def test_journey_events_record_start_and_moves(client: TestClient, db_session: Session) -> None:
    sid = _start(client)["id"]
    client.post(f"/sessions/{sid}/advance", json=APPROVE)
    client.post(f"/sessions/{sid}/back", json=APPROVE)
    rows = db_session.scalars(select(JourneyEvent).order_by(JourneyEvent.created_at)).all()
    assert [(r.kind, r.stage) for r in rows] == [("start", 1), ("advance", 2), ("back", 1)]
    assert {r.session_id for r in rows} == {sid}


def test_delete_my_data_removes_journey_and_anonymizes_cost(
    client: TestClient, db_session: Session
) -> None:
    sid = _start(client)["id"]
    db_session.add(LlmUsage(user_id="dev-user", session_id=sid, kind="turn", model="m"))
    db_session.commit()
    assert client.delete("/me/data").status_code == 204
    assert db_session.scalars(select(JourneyEvent)).all() == []
    usage = db_session.scalars(select(LlmUsage)).one()
    assert usage.user_id == "deleted" and usage.session_id is None
