"""Gold: Silver 청크 → 임베딩 → 벡터DB 적재.

medallion 3단계 — 백엔드는 env RAG_BACKEND로 선택(common/rag.py와 한 쌍):
- chroma (기본): 분야별 컬렉션(law_labor 등)에 upsert. 로컬·CI.
- pgvector: RDS PostgreSQL law_chunks 테이블에 적재. "한 DB 통합" 데모용.
같은 id(법령_조문)면 덮어쓰므로 증분 갱신과 자연스럽게 호환.

요구 패키지: chromadb, sentence-transformers (+ pgvector면 sqlalchemy/psycopg) — EC2에서 설치
"""
import json
import os
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
    # 코사인 거리로 (재)생성 — 문장 임베딩(ko-sroberta)은 코사인이 표준이고,
    # 기본값 L2는 비정규화 벡터에서 score(=1-dist)가 음수 쓰레기값이 된다.
    # 도메인 전체를 매번 재적재하므로 삭제 후 재생성이 안전(삭제된 조문도 정리됨).
    try:
        client.delete_collection(f"law_{domain}")
    except Exception:
        pass
    col = client.create_collection(f"law_{domain}", metadata={"hnsw:space": "cosine"})

    ids = [f"{c['law_name']}_{c['article']}" for c in chunks]
    texts = [c["text"] for c in chunks]
    metas = [{k: c[k] for k in ("law_name", "article", "enforced_date", "source_url")}
             for c in chunks]
    embeddings = _get_model().encode(texts, show_progress_bar=True).tolist()

    col.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metas)
    print(f"  ✓ gold: law_{domain} 컬렉션 {len(ids)}건 upsert")
    return len(ids)


def load_pgvector(domain: str) -> int:
    """분야 silver jsonl을 임베딩해 RDS PostgreSQL law_chunks 테이블에 적재.

    pgvector 통합 백엔드용(DATABASE_URL 필요). 분야 전체를 매번 재적재(삭제 후 삽입)해
    삭제된 조문도 정리한다(Chroma load_gold와 동일 의미). 임베딩 차원은 ko-sroberta=768.
    """
    from sqlalchemy import create_engine, text

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 이 .env에 없습니다 — pgvector 적재 불가.")

    silver_path = SILVER_DIR / f"{domain}.jsonl"
    chunks = [json.loads(line) for line in open(silver_path, encoding="utf-8")]
    if not chunks:
        return 0

    texts = [c["text"] for c in chunks]
    embeddings = _get_model().encode(texts, show_progress_bar=True).tolist()
    rows = []
    for c, emb in zip(chunks, embeddings):
        rows.append({
            "id": f"{c['law_name']}_{c['article']}",
            "domain": domain,
            "law_name": c["law_name"],
            "article": c["article"],
            "enforced_date": c.get("enforced_date", ""),
            "source_url": c.get("source_url", ""),
            "content": c["text"],
            "vec": "[" + ",".join(f"{x:.6f}" for x in emb) + "]",  # pgvector 리터럴
        })

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("create extension if not exists vector"))
        conn.execute(text(
            "create table if not exists law_chunks ("
            " id text primary key, domain text not null, law_name text not null,"
            " article text not null, enforced_date text, source_url text,"
            " content text not null, embedding vector(768))"
        ))
        conn.execute(text(
            "create index if not exists law_chunks_embedding_hnsw "
            "on law_chunks using hnsw (embedding vector_cosine_ops)"
        ))
        conn.execute(text("delete from law_chunks where domain = :d"), {"d": domain})
        conn.execute(text(
            "insert into law_chunks (id, domain, law_name, article, enforced_date,"
            " source_url, content, embedding) values (:id, :domain, :law_name,"
            " :article, :enforced_date, :source_url, :content, cast(:vec as vector))"
        ), rows)
    print(f"  ✓ gold(pgvector): law_chunks domain={domain} {len(rows)}건 적재")
    return len(rows)


def load_domain(domain: str) -> int:
    """RAG_BACKEND에 맞는 적재기로 위임 (chroma 기본, pgvector 선택)."""
    if os.getenv("RAG_BACKEND", "chroma").lower() == "pgvector":
        return load_pgvector(domain)
    return load_gold(domain)


if __name__ == "__main__":
    domain = sys.argv[1] if len(sys.argv) > 1 else "labor"
    load_domain(domain)
