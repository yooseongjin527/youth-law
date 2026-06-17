"""공통 RAG 헬퍼 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

각 전문가는 자기 분야 이름으로 DomainRAG 인스턴스를 만든다.
→ 분야마다 별도 벡터DB 컬렉션(law_labor 등). 4명이 각자 자기 컬렉션을 독립 구축.
검색 '기법'은 여기 하나로 통일(고도화도 여기서만) → 4분야 자동 적용.

★ 실제 구현 완료 (Chroma + sentence-transformers) ★
- 라이브러리·컬렉션이 있으면: 실제 임베딩 검색
- 없으면(개발 초기, CI): stub 결과로 폴백 — 그래프·테스트가 항상 동작
- 인덱싱은 pipeline/gold.py 가 담당 (scripts/update_laws.py 로 실행)

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day5] ① 하이브리드 검색(BM25+임베딩) — search()에 rank_bm25 결합
  [공용/Day5] ② 리랭킹(cross-encoder) 추가
  [공용/Day5] ③ scripts/evaluate.py 로 단순 vs 하이브리드 hit@k 비교 (발표)
────────────────────────────────────────────────────────
"""
from typing import TypedDict

from pipeline.config import CHROMA_DIR, EMBED_MODEL


class RetrievedChunk(TypedDict):
    law_name: str
    article: str
    enforced_date: str   # 시행일 (현행법 신뢰성)
    text: str
    source_url: str
    score: float


_model = None  # 임베딩 모델 싱글톤 (4개 인스턴스가 공유)


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


class DomainRAG:
    """한 분야의 벡터DB 컬렉션(law_{domain})을 감싸는 검색기."""

    def __init__(self, domain: str, corpus_path: str | None = None):
        self.domain = domain
        self.corpus_path = corpus_path or f"data/{domain}"
        self.collection_name = f"law_{domain}"
        self.collection = None
        try:  # 실제 백엔드 연결 시도 — 실패 시 stub 폴백
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            col = client.get_or_create_collection(self.collection_name)
            if col.count() > 0:          # 데이터가 있어야 실모드
                self.collection = col
        except Exception:
            self.collection = None       # 폴백 (라이브러리 없음/미적재)

    @property
    def is_real(self) -> bool:
        return self.collection is not None

    def search(self, query: str, k: int = 3) -> list[RetrievedChunk]:
        """질의로 자기 분야 컬렉션에서 top-k 검색."""
        if self.is_real:
            return self._search_chroma(query, k)
        return self._search_stub(k)

    # ── 실제 검색 ──────────────────────────────────
    def _search_chroma(self, query: str, k: int) -> list[RetrievedChunk]:
        emb = _get_model().encode([query]).tolist()
        res = self.collection.query(query_embeddings=emb, n_results=k)
        chunks = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            chunks.append({
                "law_name": meta["law_name"],
                "article": meta["article"],
                "enforced_date": meta["enforced_date"],
                "text": doc,
                "source_url": meta["source_url"],
                "score": round(1 - dist, 4),   # 거리 → 유사도
            })
        # TODO(공용/Day5): 여기서 BM25 점수와 가중 결합(하이브리드) → 리랭킹
        return chunks

    # ── stub 폴백 (개발 초기·CI) ────────────────────
    def _search_stub(self, k: int) -> list[RetrievedChunk]:
        return [
            {
                "law_name": f"[{self.domain}] stub법",
                "article": f"제{i + 1}조",
                "enforced_date": "2024-01-01",
                "text": f"({self.domain}) 사용자는 ...하여야 한다. [조문 원문 stub {i}]",
                "source_url": "https://www.law.go.kr/",
                "score": 0.9 - i * 0.1,
            }
            for i in range(k)
        ]

    def index(self, docs: list[dict]) -> int:
        """(하위호환) 직접 인덱싱 — 실제 적재는 pipeline/gold.py 사용 권장."""
        from pipeline.gold import load_gold
        return load_gold(self.domain)
