"""scripts/check_rag.py 출력 보조 로직 테스트."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_rag import _chunk_count  # noqa: E402


def test_chunk_count_uses_chroma_collection():
    class Collection:
        def count(self):
            return 42

    rag = SimpleNamespace(backend="chroma", collection=Collection())

    assert _chunk_count(rag) == 42


def test_chunk_count_uses_pgvector_engine(monkeypatch):
    class Result:
        def scalar(self):
            return 7

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt, params):
            assert "law_chunks" in stmt
            assert params == {"domain": "finance"}
            return Result()

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        SimpleNamespace(text=lambda sql: sql),
    )

    rag = SimpleNamespace(
        backend="pgvector",
        _engine=Engine(),
        domain="finance",
        collection=None,
    )

    assert _chunk_count(rag) == 7
