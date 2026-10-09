from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_postgres_url_is_normalized() -> None:
    from app.config import Settings

    s = Settings(database_url="postgres://u:p@host/db?sslmode=require")
    assert s.sqlalchemy_url == "postgresql+psycopg://u:p@host/db?sslmode=require"
    s = Settings(database_url="postgresql://u:p@host/db")
    assert s.sqlalchemy_url.startswith("postgresql+psycopg://")
    assert Settings(database_url="sqlite:///x.db").sqlalchemy_url == "sqlite:///x.db"
