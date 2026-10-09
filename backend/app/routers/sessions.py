from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.db import DbDep
from app.deps import CurrentUserDep, OwnedSessionDep
from app.models import MAX_STAGE, MIN_STAGE, Turn, WritingSession
from app.schemas import SessionCreate, SessionDetail, SessionSummary, StageApproval, TurnOut
from app.views import session_detail, session_summary

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

router = APIRouter(tags=["sessions"])


@lru_cache
def opening_questions() -> list[str]:
    with open(DATA_DIR / "opening_questions.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@router.get("/opening-questions")
def list_opening_questions() -> list[str]:
    return opening_questions()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(body: SessionCreate, db: DbDep, user: CurrentUserDep) -> SessionDetail:
    """새 글 시작. 첫 질문을 코치 턴으로 저장해 돌려준다."""
    question = body.opening_question or opening_questions()[0]
    session = WritingSession(user_id=user.id)
    session.turns.append(Turn(idx=0, role="coach", text=question, stage=MIN_STAGE))
    db.add(session)
    db.commit()
    return session_detail(session)


@router.get("/sessions")
def list_sessions(db: DbDep, user: CurrentUserDep) -> list[SessionSummary]:
    rows = db.scalars(
        select(WritingSession)
        .where(WritingSession.user_id == user.id)
        .order_by(WritingSession.updated_at.desc())
    )
    return [session_summary(s) for s in rows]


@router.get("/sessions/{session_id}")
def get_session(session: OwnedSessionDep) -> SessionDetail:
    return session_detail(session)


@router.get("/sessions/{session_id}/turns")
def list_turns(session: OwnedSessionDep) -> list[TurnOut]:
    return [TurnOut.model_validate(t, from_attributes=True) for t in session.turns]


@router.post("/sessions/{session_id}/advance")
def advance_stage(_: StageApproval, session: OwnedSessionDep, db: DbDep) -> SessionDetail:
    """사용자 승인으로 다음 단계로. 마감 조건 충족 여부와 무관하게 사용자가 정한다 (SKILL.md 5장)."""
    if session.stage >= MAX_STAGE:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 마지막 단계입니다.")
    session.stage += 1
    db.commit()
    return session_detail(session)


@router.post("/sessions/{session_id}/back")
def back_stage(_: StageApproval, session: OwnedSessionDep, db: DbDep) -> SessionDetail:
    if session.stage <= MIN_STAGE:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 첫 단계입니다.")
    session.stage -= 1
    db.commit()
    return session_detail(session)
