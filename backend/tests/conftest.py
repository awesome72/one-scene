from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, make_engine
from app.main import app


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        yield db
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    # 컨텍스트 매니저로 열지 않는다: lifespan이 실제 DB 파일을 만들지 않게
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def review_every_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트는 사후 LLM 검수를 표본이 아니라 매번 돌려 결과를 고정한다."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "review_sample_rate", 1.0)
