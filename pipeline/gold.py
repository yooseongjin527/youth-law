"""Gold: Silver 청크 → 임베딩 → Chroma 컬렉션 적재.

medallion 3단계 — 분야별 별도 컬렉션(law_labor 등)에 upsert.
같은 id(법령_조문)면 덮어쓰므로 증분 갱신과 자연스럽게 호환.

요구 패키지: chromadb, sentence-transformers (EC2에서 설치)
"""
import json
import sys

from pipeline.config import CHROMA_DIR, EMBED_MODEL, SILVER_DIR

_model = None  # 모델 싱글톤 (분야마다 재로딩 방지)


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def load_gold(domain: str) -> int:
    """분야 silver jsonl을 임베딩해 law_{domain} 컬렉션에 upsert."""
    import chromadb
    silver_path = SILVER_DIR / f"{domain}.jsonl"
    chunks = [json.loads(line) for line in open(silver_path, encoding="utf-8")]
    if not chunks:
        return 0

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = client.get_or_create_collection(f"law_{domain}")

    ids = [f"{c['law_name']}_{c['article']}" for c in chunks]
    texts = [c["text"] for c in chunks]
    metas = [{k: c[k] for k in ("law_name", "article", "enforced_date", "source_url")}
             for c in chunks]
    embeddings = _get_model().encode(texts, show_progress_bar=True).tolist()

    col.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metas)
    print(f"  ✓ gold: law_{domain} 컬렉션 {len(ids)}건 upsert")
    return len(ids)


if __name__ == "__main__":
    domain = sys.argv[1] if len(sys.argv) > 1 else "labor"
    load_gold(domain)
