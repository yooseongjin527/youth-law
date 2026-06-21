"""RAG 백엔드 선택·폴백 테스트 — common/rag.py 공용 변경 검증.

pgvector 백엔드를 라이브 DB 없이 검증한다: 백엔드 선택 우선순위와,
설정이 불완전할 때 죽지 않고 stub으로 안전 폴백하는지.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.rag import DomainRAG


def test_pgvector_backend_falls_back_to_stub_without_database_url(monkeypatch):
    """RAG_BACKEND=pgvector 인데 DATABASE_URL이 없으면 죽지 않고 stub으로 폴백한다.

    명시적으로 pgvector를 골랐는데 연결이 안 되면 chroma로 슬쩍 넘어가지 않고
    stub으로 떨어진다(오설정을 가리지 않기 위해). 검색 자체는 계속 동작해야 한다.
    """
    monkeypatch.setenv("RAG_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "")

    rag = DomainRAG("labor")

    assert rag.backend == "stub"
    assert rag.is_real is False
    results = rag.search("질문", k=2)
    assert len(results) == 2            # 폴백이어도 검색은 동작
    assert results[0]["enforced_date"]  # 계약 유지(시행일 필수)


def test_default_backend_never_pgvector(monkeypatch):
    """RAG_BACKEND 미설정이면 pgvector를 고르지 않는다(기존 Chroma 동작 보존)."""
    monkeypatch.delenv("RAG_BACKEND", raising=False)

    rag = DomainRAG("labor")

    assert rag.backend in ("chroma", "stub")
    assert rag.backend != "pgvector"


def test_load_domain_dispatches_to_pgvector(monkeypatch):
    """인덱싱도 RAG_BACKEND=pgvector면 pgvector 적재기로 위임한다."""
    from pipeline import gold
    calls = []
    monkeypatch.setattr(gold, "load_pgvector", lambda d: calls.append(("pg", d)) or 1)
    monkeypatch.setattr(gold, "load_gold", lambda d: calls.append(("chroma", d)) or 1)
    monkeypatch.setenv("RAG_BACKEND", "pgvector")

    gold.load_domain("labor")

    assert calls == [("pg", "labor")]


def test_load_domain_defaults_to_chroma(monkeypatch):
    """RAG_BACKEND 미설정이면 인덱싱은 Chroma 적재기로 위임(기존 동작 보존)."""
    from pipeline import gold
    calls = []
    monkeypatch.setattr(gold, "load_pgvector", lambda d: calls.append(("pg", d)) or 1)
    monkeypatch.setattr(gold, "load_gold", lambda d: calls.append(("chroma", d)) or 1)
    monkeypatch.delenv("RAG_BACKEND", raising=False)

    gold.load_domain("labor")

    assert calls == [("chroma", "labor")]
