from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.db import DbDep
from app.deps import CurrentUserDep, LlmQuotaDep, OwnedSessionDep, record_journey, record_usage
from app.engine import stage_machine, tagging
from app.engine.llm import LLM, get_llm
from app.engine.metering import metered_call
from app.engine.tagging import TagSet, TagSuggestion
from app.models import WritingSession
from app.schemas import SessionDetail, StageApproval, UtcDatetime
from app.views import session_detail

router = APIRouter(tags=["library"])

LlmDep = Annotated[LLM, Depends(get_llm)]


class LibraryItem(BaseModel):
    id: str
    title: str
    finished_at: UtcDatetime
    paragraphs: int
    chars: int
    first_sentence: str | None
    tags: TagSet


class NextTopic(BaseModel):
    question: str
    from_session_id: str
    from_title: str


class Library(BaseModel):
    done: list[LibraryItem]
    next_topics: list[NextTopic]


def _title(s: WritingSession) -> str:
    return s.title or s.topic_sentence or "제목 없는 글"


@router.get("/sessions/{session_id}/tags")
def get_tags(session: OwnedSessionDep) -> TagSet:
    return tagging.current(session)


@router.post("/sessions/{session_id}/tags/suggest", dependencies=[LlmQuotaDep])
async def suggest_tags(
    session: OwnedSessionDep, llm: LlmDep, db: DbDep, user: CurrentUserDep
) -> TagSuggestion:
    """태그 제안. 저장하지 않는다 — 사용자가 고른 것만 PUT으로 저장한다."""
    record_usage(db, user, "tags")
    return await metered_call(tagging.suggest(llm, session), db, user.id, session.id, "tags")


@router.put("/sessions/{session_id}/tags")
def save_tags(body: TagSet, session: OwnedSessionDep, db: DbDep) -> TagSet:
    return tagging.save(db, session, body)


@router.post("/sessions/{session_id}/finish")
def finish(_: StageApproval, session: OwnedSessionDep, db: DbDep) -> SessionDetail:
    """글을 보관함에 넣는다. 초안이 있어야 한다. 남은 빈칸·태그는 경고만 하고 사용자가 정한다."""
    if not session.drafts:
        raise HTTPException(status.HTTP_409_CONFLICT, "아직 초안이 없습니다.")
    session.status = "done"
    record_journey(db, session, "finish")
    db.commit()
    return session_detail(session)


@router.post("/sessions/{session_id}/reopen")
def reopen(_: StageApproval, session: OwnedSessionDep, db: DbDep) -> SessionDetail:
    session.status = "active"
    record_journey(db, session, "reopen")
    db.commit()
    return session_detail(session)


@router.get("/sessions/{session_id}/finish-check")
def finish_check(session: OwnedSessionDep) -> list[str]:
    """보관하기 전에 남은 것 (빈칸, 태그). 비어 있으면 모두 채워진 상태."""
    return stage_machine.missing(session) if session.stage == 4 else ["4단계 태그와 교정"]


@router.get("/library")
def library(db: DbDep, user: CurrentUserDep) -> Library:
    done = list(db.scalars(
        select(WritingSession)
        .where(WritingSession.user_id == user.id, WritingSession.status == "done")
        .order_by(WritingSession.updated_at.desc())
    ))
    used = tagging.used_openings(db, user.id)
    items, topics = [], []
    for s in done:
        draft = s.drafts[-1] if s.drafts else None
        sentences = [x for x in draft.sentence_map if not x["is_blank"]] if draft else []
        tags = tagging.current(s)
        items.append(LibraryItem(
            id=s.id,
            title=_title(s),
            finished_at=s.updated_at,
            paragraphs=len({x["paragraph"] for x in sentences}),
            chars=sum(len(x["text"]) for x in sentences),
            first_sentence=tagging.first_sentence(s),
            tags=tags,
        ))
        topics += [
            NextTopic(question=q, from_session_id=s.id, from_title=_title(s))
            for q in tags.gap if q not in used
        ]
    return Library(done=items, next_topics=topics)
