from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.db import DbDep
from app.deps import LlmQuotaDep, OwnedSessionDep
from app.engine import drafting
from app.engine.llm import LLM, get_llm
from app.models import Draft, WritingSession
from app.schemas_draft import (
    AcceptSuggestion,
    DraftEdit,
    DraftOut,
    HitAnswer,
    HitAnswerOut,
    OutlineOut,
    OutlineSave,
    PatternId,
)
from app.views import material_out

router = APIRouter(prefix="/sessions/{session_id}", tags=["drafts"])

LlmDep = Annotated[LLM, Depends(get_llm)]


def _draft(session: WritingSession, draft_id: str) -> Draft:
    draft = next((d for d in session.drafts if d.id == draft_id), None)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "초안을 찾을 수 없습니다.")
    return draft


@router.get("/outline")
def get_outline(
    session: OwnedSessionDep, pattern: Annotated[PatternId | None, Query()] = None
) -> OutlineOut:
    """pattern을 주면 그 패턴의 미리보기, 안 주면 저장된 개요."""
    return drafting.outline_view(session, pattern)


@router.post("/outline")
def save_outline(body: OutlineSave, session: OwnedSessionDep, db: DbDep) -> OutlineOut:
    return drafting.save_outline(db, session, body.pattern)


@router.post("/drafts", response_class=EventSourceResponse, dependencies=[LlmQuotaDep])
async def create_draft(
    session: OwnedSessionDep, db: DbDep, llm: LlmDep
) -> AsyncIterable[ServerSentEvent]:
    """초안 조립 → 진실성 검사 → 교정 점검. 이벤트: status(assembling|checking) → draft | error"""
    async for event in drafting.handle_draft(db, llm, session):
        yield ServerSentEvent(event=event["event"], data=event["data"])


@router.get("/drafts/latest")
def latest_draft(session: OwnedSessionDep) -> DraftOut:
    if not session.drafts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "아직 초안이 없습니다.")
    return drafting.draft_out(session.drafts[-1], session)


@router.post("/drafts/{draft_id}/edit")
def edit_draft(draft_id: str, body: DraftEdit, session: OwnedSessionDep, db: DbDep) -> DraftOut:
    """사용자가 직접 고친 본문 → 새 초안 버전. LLM을 부르지 않는다."""
    return drafting.edit_draft(db, session, _draft(session, draft_id), body.paragraphs)


@router.post("/drafts/{draft_id}/sentences/{index}/accept")
def accept_suggestion(
    draft_id: str, index: int, body: AcceptSuggestion, session: OwnedSessionDep, db: DbDep
) -> DraftOut:
    """빈칸의 AI 제안을 받아들인다 (text를 주면 고쳐 쓴 문장으로)."""
    try:
        return drafting.accept_suggestions(db, session, _draft(session, draft_id), index, body.text)
    except IndexError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "문장을 찾을 수 없습니다.") from None


@router.post("/drafts/{draft_id}/accept-all")
def accept_all_suggestions(draft_id: str, session: OwnedSessionDep, db: DbDep) -> DraftOut:
    """제안이 있는 빈칸을 모두 받아들인다."""
    return drafting.accept_suggestions(db, session, _draft(session, draft_id), None)


@router.post("/drafts/{draft_id}/hits/{hit_id}/dismiss")
def dismiss_hit(draft_id: str, hit_id: str, session: OwnedSessionDep, db: DbDep) -> DraftOut:
    """'그대로 두기'."""
    return drafting.dismiss_hit(db, session, _draft(session, draft_id), hit_id)


@router.post("/drafts/{draft_id}/hits/{hit_id}/answer", dependencies=[LlmQuotaDep])
async def answer_hit(
    draft_id: str, hit_id: str, body: HitAnswer, session: OwnedSessionDep, db: DbDep,
    llm: LlmDep,
) -> HitAnswerOut:
    """교정 질문에 답하기. 답은 원문 재료가 되고, 다음 초안에 쓰인다."""
    try:
        added, draft = await drafting.answer_hit(
            db, llm, session, _draft(session, draft_id), hit_id, body.text, body.input_mode
        )
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "교정 표시를 찾을 수 없습니다.") from None
    return HitAnswerOut(added=[material_out(m) for m in added], draft=draft)
