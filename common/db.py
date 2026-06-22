"""RDS(PostgreSQL) 연결 헬퍼 — 신규 파일.

DATABASE_URL이 없으면 engine=None을 돌려준다 → 앱이 죽지 않고 로깅만 건너뛴다.
로깅은 ENABLE_RDS_LOGGING=true + DATABASE_URL이 둘 다 있을 때만 켜진다(기본 꺼짐).
실제 적재는 common/logging_store.py, 테이블 생성은 scripts/init_db.py.
"""
import os
from functools import lru_cache


def logging_enabled() -> bool:
    """RDS 로깅을 켤지 — 둘 다 충족해야 켜짐(기본 꺼짐, 로컬·CI 안전)."""
    return (
        os.getenv("ENABLE_RDS_LOGGING", "false").lower() == "true"
        and bool(os.getenv("DATABASE_URL"))
    )


@lru_cache(maxsize=4)
def _engine_for(url: str):
    """URL당 engine 1개 캐시 — record()가 매 호출마다 풀을 새로 만들지 않게."""
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True, future=True)


def get_engine():
    """DATABASE_URL 기반 SQLAlchemy engine. 없거나 생성 실패면 None."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return None
    try:
        return _engine_for(url)
    except Exception:
        return None
