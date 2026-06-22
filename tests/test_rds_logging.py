"""RDS 로깅 안전성 테스트 — 신규 파일(common/db.py·logging_store.py) 검증.

라이브 DB 없이 핵심 불변식만 못 박는다:
- 로깅 미설정이면 no-op(False) — 로컬·CI·다른 팀원 동작에 영향 0.
- DB가 안 떠 있어도(잘못된 URL) 저장이 예외를 던지지 않는다 — 상담이 절대 죽지 않게.
실제 적재(쓰기 성공)는 EC2/RDS 통합 검증 대상.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import db
from common.logging_store import (
    save_consultation,
    save_eval_scorecard,
    save_usage,
)

_CONSULT = {
    "question": "전세금 못 받았어요",
    "domains": [{"id": "housing", "name": "주거"}],
    "in_scope": True,
    "final_answer": "보증금 반환은 ...",
    "answer_blocks": [],
    "verification_report": [],
}
_USAGE = {"task": "answer", "tier": "main",
          "input_tokens": 10, "output_tokens": 20, "cost_usd": 0.001}
_EVAL = {"date": "2026-06-19", "domain": "housing",
         "retrieval": {"hit_at_k": 0.8}, "cost": {"calls": 3}, "grounding": {"rate": 0.9}}


def test_get_engine_none_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.get_engine() is None


def test_postgres_engine_uses_connect_timeout(monkeypatch):
    """RDS 장애/보안그룹 문제 때 상담 응답이 DB 연결에 오래 묶이지 않게 한다."""
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        SimpleNamespace(create_engine=fake_create_engine),
    )
    db._engine_for.cache_clear()
    try:
        engine = db._engine_for("postgresql+psycopg://u:p@example:5432/youthlaw")
    finally:
        db._engine_for.cache_clear()

    assert engine is not None
    assert captured["kwargs"]["connect_args"] == {"connect_timeout": 5}


def test_logging_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_RDS_LOGGING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.logging_enabled() is False


def test_saves_are_noop_when_disabled(monkeypatch):
    """미설정이면 세 저장 함수 모두 조용히 False (예외 없이)."""
    monkeypatch.delenv("ENABLE_RDS_LOGGING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert save_consultation(_CONSULT) is False
    assert save_usage(_USAGE) is False
    assert save_eval_scorecard(_EVAL) is False


def test_saves_swallow_db_errors(monkeypatch):
    """로깅 켜졌는데 DB가 안 떠 있어도 예외를 던지지 않고 False."""
    monkeypatch.setenv("ENABLE_RDS_LOGGING", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/nodb")
    assert save_consultation(_CONSULT) is False
    assert save_usage(_USAGE) is False
    assert save_eval_scorecard(_EVAL) is False
