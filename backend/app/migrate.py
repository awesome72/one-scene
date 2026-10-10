"""서버가 켜질 때 DB 스키마를 최신으로 (Alembic).

- 빈 DB: 처음부터 모든 마이그레이션을 적용한다.
- create_all로 만든 예전 DB(운영 포함): 표는 있는데 alembic_version이 없으면 기준선(0001)으로
  표시만 하고(stamp) 그 뒤 마이그레이션을 적용한다. 0001은 create_all 시절 스키마 그대로다.
- PostgreSQL에서는 advisory lock으로 여러 서버리스 인스턴스가 동시에 마이그레이션하지 않게 한다.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE = "0001"
LOCK_ID = 727_001  # pg_advisory_lock 키 (이 앱 전용 임의 숫자)


def _config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def upgrade(engine: Engine) -> None:
    cfg = _config()
    with engine.begin() as conn:
        is_pg = conn.dialect.name == "postgresql"
        if is_pg:
            conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": LOCK_ID})
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "sessions" in tables:
            log.info("create_all로 만든 DB: 기준선 %s로 표시", BASELINE)
            command.stamp(cfg, BASELINE)
        command.upgrade(cfg, "head")
