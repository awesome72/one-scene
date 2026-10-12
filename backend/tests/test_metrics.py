"""기획안 10장 성공 지표 계산 (app/engine/metrics.py)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.engine import metrics
from app.models import Draft, JourneyEvent, Material, Turn, User, WritingSession


def _m(id_: str, block: str) -> Material:
    return Material(id=id_, seq=1, turn_id="t", text="x", type="scene", arc_block=block)


def test_draft_quality_counts_sources_cliches_and_first_scene() -> None:
    mats = {"a": _m("a", "scene"), "b": _m("b", "event")}
    draft = Draft(version=1, body="", sentence_map=[
        {"paragraph": 1, "text": "회의실 창밖을 봤다.", "material_ids": ["a"], "is_blank": False},
        {"paragraph": 1, "text": "[빈칸: 손은?]", "material_ids": [], "is_blank": True},
        {"paragraph": 2, "text": "가슴이 먹먹했다.", "material_ids": ["b"], "is_blank": False},
        {"paragraph": 2, "text": "내가 고쳐 쓴 문장.", "material_ids": [], "is_blank": False,
         "source": "user"},
        {"paragraph": 3, "text": "출처 없는 문장.", "material_ids": [], "is_blank": False},
    ], lint_result=[
        {"kind": "cliche", "dismissed": True},  # 그대로 두기여도 글에 남아 있으면 센다
        {"kind": "blank", "dismissed": False},  # 상투어 사전이 아니다
    ])
    q = metrics.draft_quality(draft, mats)
    assert (q.sentences, q.sourced) == (4, 3) and q.source_rate == 0.75
    assert q.dictionary_hits == 1 and q.first_is_scene is True
    assert q.cliches_per_1000 == 1 / q.chars * 1000


def test_first_sentence_without_source_is_not_judged() -> None:
    draft = Draft(version=1, body="", sentence_map=[
        {"paragraph": 1, "text": "고친 문장.", "material_ids": [], "is_blank": False, "source": "user"},
    ], lint_result=[])
    assert metrics.draft_quality(draft, {}).first_is_scene is None


def test_behaviour_rates(db_session: Session) -> None:
    now = datetime.now(UTC)
    since = now - timedelta(days=30)
    for uid in ("a", "b", "c"):
        db_session.add(User(id=uid))
    sessions = {}
    for sid, uid in (("s1", "a"), ("s2", "a"), ("s3", "b"), ("old", "c")):
        sessions[sid] = WritingSession(id=sid, user_id=uid)
        db_session.add(sessions[sid])
    db_session.flush()

    def ev(uid: str, sid: str, kind: str, stage: int, days_ago: float) -> None:
        db_session.add(JourneyEvent(user_id=uid, session_id=sid, kind=kind, stage=stage,
                                    created_at=now - timedelta(days=days_ago)))

    # a: 첫 글 s1에서 2단계로, 두 편 완성 / b: 첫 글에서 1단계에 멈춤 / c: 첫 글이 기간 밖
    ev("a", "s1", "start", 1, 10)
    ev("a", "s1", "advance", 2, 9)
    ev("a", "s1", "finish", 4, 8)
    ev("a", "s2", "start", 1, 5)
    ev("a", "s2", "finish", 4, 2)
    ev("b", "s3", "start", 1, 3)
    ev("c", "old", "start", 1, 60)
    sessions["s1"].turns += [Turn(idx=0, role="user", text="말", input_mode="voice", stage=1),
                             Turn(idx=1, role="user", text="글", input_mode="text", stage=1),
                             Turn(idx=2, role="coach", text="질문?", stage=1)]
    db_session.commit()

    b = metrics.behaviour(db_session, since)
    assert b["first_session_stage1_rate"] == (1, 2)  # a 성공, b 실패 (c는 기간 밖)
    assert b["two_pieces_month_rate"] == (1, 2)  # 활동한 a, b 중 a만 2편
    assert b["voice_rate"] == (1, 2)
