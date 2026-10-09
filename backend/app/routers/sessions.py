from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.db import DbDep
from app.deps import CurrentUserDep, OwnedSessionDep
from app.models import MAX_STAGE, MIN_STAGE, Material, Turn, WritingSession
from app.schemas import (
    MaterialCard,
    MaterialOut,
    MaterialUpdate,
    SessionCreate,
    SessionDetail,
    SessionSummary,
    SessionUpdate,
    StageApproval,
    TurnOut,
)
from app.views import material_card, material_out, session_detail, session_summary

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


@router.patch("/sessions/{session_id}")
def update_session(body: SessionUpdate, session: OwnedSessionDep, db: DbDep) -> SessionDetail:
    """제목·주제 문장·목표 길이를 사용자가 직접 정하거나 고친다."""
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(session, field, value)
    db.commit()
    return session_detail(session)


@router.get("/sessions/{session_id}/material-card")
def get_material_card(session: OwnedSessionDep) -> MaterialCard:
    return material_card(session)


@router.patch("/sessions/{session_id}/materials/{material_id}")
def update_material(
    material_id: str, body: MaterialUpdate, session: OwnedSessionDep, db: DbDep
) -> MaterialOut:
    """재료 빼 두기/되살리기. 재료 원문(text)은 바꿀 수 없다 (CLAUDE.md 제품 규칙 3)."""
    material = db.get(Material, material_id)
    if material is None or material.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "재료를 찾을 수 없습니다.")
    material.excluded = body.excluded
    db.commit()
    return material_out(material)


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
