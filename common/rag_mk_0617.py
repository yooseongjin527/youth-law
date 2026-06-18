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
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict

from pipeline.config import CHROMA_DIR, EMBED_MODEL

# 내가 수정: 하이브리드 검색 가중치 (α=1.0이면 임베딩만, α=0.0이면 BM25만)
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.6"))

# 내가 수정: cross-encoder 리랭킹 — 한국어 법령에서 성능 저하 확인되어 비활성화
# RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
# RERANK_ENABLED = os.getenv("RERANK_ENABLED", "1") == "1"
RERANK_ENABLED = False


class RetrievedChunk(TypedDict):
    law_name: str
    article: str
    enforced_date: str   # 시행일 (현행법 신뢰성)
    text: str
    source_url: str
    score: float


_model = None  # 임베딩 모델 싱글톤 (4개 인스턴스가 공유)
_kiwi = None   # 내가 수정: 한국어 형태소 분석기 싱글톤
# _cross_encoder = None  # 내가 수정: cross-encoder 리랭킹 모델 싱글톤 (비활성화)


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


# 내가 수정: 한국어 형태소 분석 토크나이저 (BM25용)
def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def _tokenize_ko(text: str) -> list[str]:
    """한국어 텍스트를 형태소 단위로 토크나이징한다. (내가 수정)"""
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    # 명사(NNG, NNP), 동사(VV), 형용사(VA) 어근만 추출 — 조사·어미 제거
    pos_filter = {"NNG", "NNP", "NNB", "VV", "VA", "SL"}
    return [t.form for t in tokens if t.tag in pos_filter]


# 내가 수정: cross-encoder 리랭킹 모델 로더 (비활성화)
# def _get_cross_encoder():
#     global _cross_encoder
#     if _cross_encoder is None:
#         from sentence_transformers import CrossEncoder
#         _cross_encoder = CrossEncoder(RERANK_MODEL)
#     return _cross_encoder


_SYNONYMS_DIR = Path(__file__).parent / "synonyms"
_synonym_cache: dict[str, dict[str, list[str]]] = {}


def _load_synonyms(domain: str) -> dict[str, list[str]]:
    """분야별 동의어 사전(JSONL)을 로드하고 캐싱한다."""
    if domain in _synonym_cache:
        return _synonym_cache[domain]

    syn_map: dict[str, list[str]] = {}
    path = _SYNONYMS_DIR / f"{domain}.jsonl"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                syn_map[entry["key"]] = entry["synonyms"]

    _synonym_cache[domain] = syn_map
    return syn_map


def _expand_query(query: str, domain: str) -> str:
    """평어 쿼리에 분야별 동의어 사전의 법률 키워드를 추가한다."""
    synonym_map = _load_synonyms(domain)
    if not synonym_map:
        return query
    tokens = _tokenize_ko(query)
    extra: list[str] = []
    for token in tokens:
        if token in synonym_map:
            extra.extend(synonym_map[token])
    if not extra:
        return query
    return query + " " + " ".join(dict.fromkeys(extra))


class DomainRAG:
    """한 분야의 벡터DB 컬렉션(law_{domain})을 감싸는 검색기."""

    def __init__(self, domain: str, corpus_path: str | None = None):
        self.domain = domain
        self.corpus_path = corpus_path or f"data/{domain}"
        self.collection_name = f"law_{domain}"
        self.collection = None
        # 내가 수정: BM25 인덱스 관련 필드
        self._bm25 = None
        self._bm25_corpus_docs: list[dict] = []
        try:  # 실제 백엔드 연결 시도 — 실패 시 stub 폴백
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            col = client.get_or_create_collection(self.collection_name)
            if col.count() > 0:          # 데이터가 있어야 실모드
                self.collection = col
                self._build_bm25_index()  # 내가 수정: Chroma 데이터로 BM25 인덱스 구축
        except Exception:
            self.collection = None       # 폴백 (라이브러리 없음/미적재)

    @property
    def is_real(self) -> bool:
        return self.collection is not None

    # 내가 수정: BM25 인덱스 구축 로직
    def _build_bm25_index(self) -> None:
        """Chroma 컬렉션의 전체 문서를 가져와 BM25 인덱스를 구축한다."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            return

        all_data = self.collection.get(include=["documents", "metadatas"])
        if not all_data["documents"]:
            return

        tokenized_corpus = [_tokenize_ko(doc) for doc in all_data["documents"]]  # 내가 수정: 형태소 분석 토크나이징
        self._bm25 = BM25Okapi(tokenized_corpus)
        self._bm25_corpus_docs = [
            {
                "law_name": meta["law_name"],
                "article": meta["article"],
                "enforced_date": meta["enforced_date"],
                "text": doc,
                "source_url": meta["source_url"],
            }
            for doc, meta in zip(all_data["documents"], all_data["metadatas"])
        ]

    @property
    def has_bm25(self) -> bool:  # 내가 수정
        return self._bm25 is not None

    def search(self, query: str, k: int = 3) -> list[RetrievedChunk]:
        """질의로 자기 분야 컬렉션에서 top-k 검색."""
        if self.is_real:
            return self._search_chroma(query, k)
        return self._search_stub(k)

    # ── 실제 검색 ──────────────────────────────────
    def _search_chroma(self, query: str, k: int) -> list[RetrievedChunk]:
        # 내가 수정: BM25가 있으면 하이브리드, 없으면 기존 임베딩 전용
        if self.has_bm25:
            return self._search_hybrid(query, k)
        return self._search_embedding_only(query, k)

    def _search_embedding_only(self, query: str, k: int) -> list[RetrievedChunk]:
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
                "score": round(1 - dist, 4),
            })
        return chunks

    # 내가 수정: 하이브리드 검색 (BM25 + 임베딩 가중 결합)
    def _search_hybrid(self, query: str, k: int) -> list[RetrievedChunk]:
        fetch_k = k * 3  # 결합 전 넉넉히 가져옴

        # ① 임베딩 검색
        emb = _get_model().encode([query]).tolist()
        emb_res = self.collection.query(query_embeddings=emb, n_results=fetch_k)
        emb_scores: dict[str, float] = {}
        emb_data: dict[str, dict] = {}
        for doc, meta, dist in zip(
            emb_res["documents"][0], emb_res["metadatas"][0], emb_res["distances"][0]
        ):
            doc_id = f"{meta['law_name']}_{meta['article']}"
            emb_scores[doc_id] = 1 - dist
            emb_data[doc_id] = {
                "law_name": meta["law_name"],
                "article": meta["article"],
                "enforced_date": meta["enforced_date"],
                "text": doc,
                "source_url": meta["source_url"],
            }

        # ② BM25 검색 (쿼리 확장 적용)
        expanded = _expand_query(query, self.domain)
        tokenized_query = _tokenize_ko(expanded)  # 내가 수정: 형태소 분석 토크나이징
        bm25_raw = self._bm25.get_scores(tokenized_query)
        bm25_max = max(bm25_raw) if max(bm25_raw) > 0 else 1.0
        bm25_top_indices = sorted(
            range(len(bm25_raw)), key=lambda i: bm25_raw[i], reverse=True
        )[:fetch_k]

        bm25_scores: dict[str, float] = {}
        for idx in bm25_top_indices:
            corpus_doc = self._bm25_corpus_docs[idx]
            doc_id = f"{corpus_doc['law_name']}_{corpus_doc['article']}"
            bm25_scores[doc_id] = bm25_raw[idx] / bm25_max  # 0~1 정규화
            if doc_id not in emb_data:
                emb_data[doc_id] = corpus_doc

        # ③ 가중 결합: α * 임베딩 + (1-α) * BM25  # 내가 수정: HYBRID_ALPHA로 튜닝
        all_ids = set(emb_scores) | set(bm25_scores)
        combined: list[tuple[str, float]] = []
        for doc_id in all_ids:
            e_score = emb_scores.get(doc_id, 0.0)
            b_score = bm25_scores.get(doc_id, 0.0)
            final = HYBRID_ALPHA * e_score + (1 - HYBRID_ALPHA) * b_score
            combined.append((doc_id, final))

        combined.sort(key=lambda x: x[1], reverse=True)

        # ④ 리랭킹 또는 바로 top-k 반환  # 내가 수정: cross-encoder 리랭킹 단계 추가
        candidates = combined[: k * 3]
        if RERANK_ENABLED:
            candidates = self._rerank(query, candidates, emb_data)

        chunks: list[RetrievedChunk] = []
        for doc_id, score in candidates[:k]:
            d = emb_data[doc_id]
            chunks.append({
                "law_name": d["law_name"],
                "article": d["article"],
                "enforced_date": d["enforced_date"],
                "text": d["text"],
                "source_url": d["source_url"],
                "score": round(score, 4),
            })
        return chunks

    # 내가 수정: cross-encoder 리랭킹 (비활성화 — 한국어 법령에서 성능 저하 확인)
    # def _rerank(
    #     self,
    #     query: str,
    #     candidates: list[tuple[str, float]],
    #     doc_data: dict[str, dict],
    # ) -> list[tuple[str, float]]:
    #     """하이브리드 후보를 cross-encoder로 재정렬한다."""
    #     try:
    #         ce = _get_cross_encoder()
    #     except Exception:
    #         return candidates
    #
    #     pairs = [(query, doc_data[doc_id]["text"]) for doc_id, _ in candidates]
    #     scores = ce.predict(pairs)
    #     reranked = [
    #         (doc_id, float(score))
    #         for (doc_id, _), score in zip(candidates, scores)
    #     ]
    #     reranked.sort(key=lambda x: x[1], reverse=True)
    #     return reranked

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
