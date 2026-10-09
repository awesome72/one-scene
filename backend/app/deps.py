from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select

from app.auth import AuthError, BannedUser, auth_mode, verify
from app.config import get_settings
from app.db import DbDep
from app.models import Draft, Turn, User, WritingSession

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


def require_llm_quota(db: DbDep) -> None:
    """하루 전체 AI 작업 상한 (config.daily_llm_limit). 로그인 없이 공개 배포하는 동안의 비용 안전장치.

    사용자 발화(추출+질문)와 초안 조립을 한 건씩 센다. UTC 자정에 초기화된다.
    """
    limit = get_settings().daily_llm_limit
    if limit <= 0:
        return
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        db.scalar(select(func.count()).where(Turn.role == "user", Turn.created_at >= today)) or 0
    ) + (db.scalar(select(func.count()).where(Draft.created_at >= today)) or 0)
    if used >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "오늘 쓸 수 있는 양을 다 썼어요. 내일 다시 이어서 써 주세요.",
        )


LlmQuotaDep = Depends(require_llm_quota)
