from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select

from app.auth import AuthError, BannedUser, auth_mode, verify
from app.config import get_settings
from app.db import DbDep
from app.models import Draft, JourneyEvent, Turn, UsageEvent, User, WritingSession

DEV_USER_ID = "dev-user"


def get_current_user(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header(max_length=64)] = None,
) -> User:
    """로그인한 사용자 (open-questions B2, app/auth.py).

    neon 모드(운영): Bearer JWT 필수, 사용자 ID는 토큰의 sub. X-User-Id는 무시한다.
    dev 모드(로컬·테스트): X-User-Id 헤더, 없으면 개발용 사용자.
    """
    if auth_mode() == "neon":
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "로그인이 필요해요.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            claims = verify(token)
        except BannedUser:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "이용이 제한된 계정이에요.") from None
        except AuthError:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "로그인이 만료됐어요. 다시 로그인해 주세요.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        user_id = str(claims["sub"])[:64]
    else:
        user_id = x_user_id or DEV_USER_ID
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        db.add(user)
        db.commit()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_owned_session(session_id: str, db: DbDep, user: CurrentUserDep) -> WritingSession:
    session = db.get(WritingSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다.")
    return session


OwnedSessionDep = Annotated[WritingSession, Depends(get_owned_session)]


def _jobs_today(db: DbDep, user_id: str | None = None) -> int:
    """오늘(UTC) AI 작업 수: 사용자 발화(추출+질문), 초안 조립, 그 밖의 AI·음성 요청을 한 건씩 센다."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    turns = select(func.count()).select_from(Turn).where(
        Turn.role == "user", Turn.created_at >= today
    )
    drafts = select(func.count()).select_from(Draft).where(Draft.created_at >= today)
    others = select(func.count()).select_from(UsageEvent).where(
        UsageEvent.created_at >= today, UsageEvent.kind.in_(AI_KINDS)
    )
    if user_id is not None:
        turns = turns.join(WritingSession).where(WritingSession.user_id == user_id)
        drafts = drafts.join(WritingSession).where(WritingSession.user_id == user_id)
        others = others.where(UsageEvent.user_id == user_id)
    return (db.scalar(turns) or 0) + (db.scalar(drafts) or 0) + (db.scalar(others) or 0)


AI_KINDS = ("opening", "tags")  # Claude를 부르는 요청 → AI 상한
VOICE_KINDS = ("stt", "tts")  # OpenAI 음성 → 음성 상한 (건당 비용이 작아 따로 넉넉하게)


def require_voice_quota(db: DbDep, user: CurrentUserDep) -> None:
    limit = get_settings().daily_voice_limit_per_user
    if limit <= 0:
        return
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(UsageEvent).where(
        UsageEvent.user_id == user.id, UsageEvent.created_at >= today,
        UsageEvent.kind.in_(VOICE_KINDS),
    )) or 0
    if used >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "오늘은 음성을 더 쓸 수 없어요. 글로 이어서 써 주세요.",
        )


VoiceQuotaDep = Depends(require_voice_quota)


def record_usage(db: DbDep, user: User, kind: str) -> None:
    """턴·초안이 아닌 AI·음성 요청을 하루 상한에 센다 (opening|tags|stt|tts)."""
    db.add(UsageEvent(user_id=user.id, kind=kind))
    db.commit()


def require_llm_quota(db: DbDep, user: CurrentUserDep) -> None:
    """하루 AI 작업 상한 — 비용 안전장치. 0이면 끈다. UTC 자정에 초기화된다.

    사용자별 상한(daily_llm_limit_per_user)이 한 사람이 전체 상한을 다 써 버리는 것을 막고,
    전체 상한(daily_llm_limit)이 가입을 여러 번 해서 우회하는 것을 막는다.
    """
    settings = get_settings()
    per_user = settings.daily_llm_limit_per_user
    if per_user > 0 and _jobs_today(db, user.id) >= per_user:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "오늘은 여기까지 쓸 수 있어요. 내일 다시 이어서 써 주세요.",
        )
    total = settings.daily_llm_limit
    if total > 0 and _jobs_today(db) >= total:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "오늘 서비스 사용량이 가득 찼어요. 내일 다시 이어서 써 주세요.",
        )


LlmQuotaDep = Depends(require_llm_quota)


def record_journey(db: DbDep, session: WritingSession, kind: str) -> None:
    """단계별 이탈 측정용 기록. 호출하는 쪽이 commit한다."""
    db.add(JourneyEvent(user_id=session.user_id, session_id=session.id, kind=kind,
                        stage=session.stage))
