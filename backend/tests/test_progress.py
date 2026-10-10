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
    # 장면이 먼저 (주제는 장면에서 나온다. 여정 시뮬레이션에서 주제부터 쫓다 1단계가 길어졌다)
    assert [c["key"] for c in p["conditions"]] == ["opening_scene", "topic", "length"]
    assert not any(c["done"] for c in p["conditions"])
    assert p["journey"] == 0 and p["stage_fraction"] == 0 and p["ready"] is False
    assert p["next_need"] == "글이 시작될 한 순간"
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


def test_story_feedback_upsert_and_validation(client: TestClient, db_session: Session) -> None:
    from app.models import StoryFeedback

    sid = _start(client)["id"]
    assert client.get(f"/sessions/{sid}/feedback").json() == {"score": None}
    assert client.put(f"/sessions/{sid}/feedback", json={"score": 6}).status_code == 422
    assert client.put(f"/sessions/{sid}/feedback", json={"score": 4}).json() == {"score": 4}
    assert client.put(f"/sessions/{sid}/feedback", json={"score": 5}).json() == {"score": 5}
    assert db_session.get(StoryFeedback, sid).score == 5
    # 남의 글에는 남길 수 없다
    res = client.put(f"/sessions/{sid}/feedback", json={"score": 1}, headers={"X-User-Id": "other"})
    assert res.status_code == 404
    # 글을 지우면 함께 지워진다
    assert client.delete(f"/sessions/{sid}").status_code == 204
    db_session.expire_all()
    assert db_session.get(StoryFeedback, sid) is None


def test_stage1_card_comes_early_when_only_card_choices_left(
    client: TestClient, db_session: Session
) -> None:
    """1단계: 장면이 나오고 주제·길이만 남으면 대답 4번째에 카드를 띄운다 (대화로 쫓지 않는다)."""
    from app.engine import stage_machine

    sid = _start(client)["id"]
    s = db_session.get(WritingSession, sid)
    _add(db_session, sid, "scene")
    assert not stage_machine.card_due(s)  # 대답 1번
    for _ in range(3):
        _add(db_session, sid, "event", "fact", "3년 동안")
    assert stage_machine.card_due(s)
    # 질문자에게는 카드에서 고르는 조건을 넘기지 않는다
    assert stage_machine.conversational_missing(s) == []
    assert set(stage_machine.missing(s)) == {"한 문장 주제", "목표 길이"}


def test_merge_blanks_joins_consecutive_blanks_in_a_paragraph() -> None:
    from app.engine.drafting import merge_blanks

    def blank(p: int, q: str, sug: str | None) -> dict:
        return {"paragraph": p, "text": f"[빈칸: {q}]", "material_ids": [], "is_blank": True,
                "note": None, "suggestion": sug}

    own = {"paragraph": 1, "text": "주간 회의 때였다.", "material_ids": ["m"], "is_blank": False,
           "note": None, "suggestion": None}
    out = merge_blanks([own, blank(1, "누가 있었어요?", "팀장이 있었다."), blank(1, "무엇을?", None),
                        blank(1, "소리?", "볼펜 소리가 났다."), blank(2, "그 뒤?", None)])
    assert [s["is_blank"] for s in out] == [False, True, True]
    assert out[1]["text"] == "[빈칸: 누가 있었어요?]"
    assert out[1]["suggestion"] == "팀장이 있었다. 볼펜 소리가 났다."
    assert out[2]["paragraph"] == 2  # 다른 단락의 빈칸은 따로


def test_new_session_removes_unanswered_ones(client: TestClient, db_session: Session) -> None:
    first = _start(client)["id"]
    answered = _start(client)["id"]  # first는 대답이 없어 지워진다
    _add(db_session, answered, "scene")
    third = _start(client)["id"]  # answered는 남는다
    ids = {s["id"] for s in client.get("/sessions").json()}
    assert ids == {answered, third} and first not in ids
