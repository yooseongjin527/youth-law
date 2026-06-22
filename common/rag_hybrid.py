"""[통합 후보 — common/rag.py 승격 대기] 하이브리드 검색 RAG.

⚠️ 이 파일은 아직 공용 common/rag.py가 아니다. 두 실험본을 하나로 합친 '후보'다.
    팀 리뷰(PR) + 전원 동의 후에야 이 로직을 common/rag.py로 승격한다.
    그 전까지 prod 경로(common/rag.py, agents/*.py)는 그대로 둔다.

합친 것 (브리프 §6 추천 절충안):
  · 검색 로직   = 성헌 실험본 : BM25(kiwipiepy) + 임베딩 가중결합, 분야별 α, 정의의도 공통처리
  · 파일 구조   = 민지 실험본 : 쿼리확장 map을 common/synonyms/<domain>.jsonl로 분리 + 로드/캐싱
  · 매칭 방식   = 성헌 실험본 : substring(`key in query`) — 긴 평어 트리거 보존
                  (민지 토큰매칭은 긴 트리거가 안 잡혀 채택 안 함)
  (보류) cross-encoder 리랭킹 → 한국어 법령서 성능저하 확인되어 v2로

승격 시 추가 작업(이번 PR 범위 아님):
  · 이 파일 로직을 common/rag.py로 이전
  · agents/finance.py 내부 _FINANCE_SYNONYMS / _expand_query 제거(중복 확장 방지)

실행(검색축만 — Bedrock 불필요):
  .venv/bin/python common/rag_hybrid.py finance   # finance 평가셋 hit@3/MRR + α 스윕
  .venv/bin/python common/rag_hybrid.py all       # 데이터 적재된 분야 전부
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 'python common/rag_hybrid.py'로 직접 실행 시 repo 루트를 path에 (pipeline import용).
# 모듈로 import될 땐 이미 path에 있어 no-op.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from typing import TypedDict  # noqa: E402

from pipeline.config import CHROMA_DIR, EMBED_MODEL  # noqa: E402

# ── 분야별 튜닝 노브 ────────────────────────────────────────────────
_DEFAULT_ALPHA = 0.7
# α=1.0 = 임베딩만, α↓일수록 BM25 비중↑. 분야별 스윕으로 '비퇴화' 확정(현 평가셋 기준).
# ★ 교훈: synonyms가 비면 BM25가 평어 토큰을 노이즈로 매칭 → 임베딩만 못함.
#   synonyms 충실한 분야만 BM25를 낮은 α로 섞고, 빈 분야는 α=1.0(임베딩)로 둔다.
_ALPHA_BY_DOMAIN = {
    "finance": 0.6,    # benchmark hit@3 우선(α=0.9는 MRR 우세)
    "labor":   0.7,    # 민지 synonyms → hit@3 0.65→0.90
    "housing": 0.9,    # synonyms 채움 → hit@3 0.875→1.0 (MRR 0.667→0.969)
    "consumer": 0.9,   # synonyms 채움 → hit@3 0.864→1.0 (MRR 0.712→0.871)
}
_MAX_EXPANSION_TERMS = 6  # 너무 많이 붙이면 임베딩 희석 → 상한

# ── 정의(definition) 의도 — 분야 공통 ───────────────────────────────
# "용어/정의"는 각 법의 '정의' 조문에만 나오는 고-IDF 토큰이라 BM25 변별력이 크다.
_DEFINITION_TRIGGERS = ("뭔가요", "뭐예요", "뭐야", "무엇", "뜻이")
_DEFINITION_TERM = "용어의 정의"

# ── 분야별 쿼리확장 사전 (민지식 파일 분리) ──────────────────────────
_SYNONYMS_DIR = Path(__file__).parent / "synonyms"
_synonym_cache: dict[str, dict[str, list[str]]] = {}


def _load_synonyms(domain: str) -> dict[str, list[str]]:
    """common/synonyms/<domain>.jsonl 을 로드하고 캐싱한다. 파일 없으면 빈 맵."""
    if domain in _synonym_cache:
        return _synonym_cache[domain]
    syn_map: dict[str, list[str]] = {}
    path = _SYNONYMS_DIR / f"{domain}.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            syn_map[entry["key"]] = entry["synonyms"]
    _synonym_cache[domain] = syn_map
    return syn_map


def _expand_query(domain: str, query: str) -> str:
    """평어 질의에 (정의 의도 + 분야별 동의어)를 덧붙여 검색 적중률을 높인다.
    트리거가 질의에 substring으로 있을 때만 추가(무관 용어 희석 방지). 상한 _MAX_EXPANSION_TERMS.
    ★검색(임베딩·BM25) 입력에만 적용 — 답변·인용과 무관."""
    extra: list[str] = []
    if any(t in query for t in _DEFINITION_TRIGGERS):
        extra.append(_DEFINITION_TERM)
    for key, terms in _load_synonyms(domain).items():
        if key in query:                 # ★ substring 매칭 (성헌 방식)
            for t in terms:
                if t not in extra:
                    extra.append(t)
    if not extra:
        return query
    return query + " " + " ".join(extra[:_MAX_EXPANSION_TERMS])


class RetrievedChunk(TypedDict):
    law_name: str
    article: str
    enforced_date: str
    text: str
    source_url: str
    score: float


_model = None
_kiwi = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def _tokenize_ko(text: str) -> list[str]:
    """형태소 단위 토크나이징 — 명사/동사/형용사 어근만(조사·어미 제거). BM25용."""
    tokens = _get_kiwi().tokenize(text)
    pos = {"NNG", "NNP", "NNB", "VV", "VA", "SL"}
    return [t.form for t in tokens if t.tag in pos]


class DomainRAG:
    """한 분야 컬렉션(law_{domain}) 검색기 — 하이브리드 + 분야별 확장/α.

    common/rag.py의 DomainRAG와 동일한 공개 인터페이스(domain, is_real, search)를 유지한다
    → 승격 시 drop-in 교체 가능."""

    def __init__(self, domain: str, corpus_path: str | None = None):
        self.domain = domain
        self.corpus_path = corpus_path or f"data/{domain}"
        self.collection_name = f"law_{domain}"
        self.collection = None
        self._bm25 = None
        self._bm25_corpus_docs: list[dict] = []
        # 분야별 α (env HYBRID_ALPHA가 있으면 스윕용으로 우선)
        self.alpha = float(os.getenv("HYBRID_ALPHA", _ALPHA_BY_DOMAIN.get(domain, _DEFAULT_ALPHA)))
        try:  # 실제 백엔드 연결 시도 — 실패 시 stub 폴백
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            col = client.get_or_create_collection(self.collection_name)
            if col.count() > 0:               # 데이터가 있어야 실모드
                self.collection = col
                self._build_bm25_index()      # Chroma 데이터로 BM25 인덱스 구축
        except Exception:
            self.collection = None            # 폴백 (라이브러리 없음/미적재)

    @property
    def is_real(self) -> bool:
        return self.collection is not None

    @property
    def has_bm25(self) -> bool:
        return self._bm25 is not None

    def _build_bm25_index(self) -> None:
        """Chroma 컬렉션의 전체 문서로 BM25 인덱스를 구축한다. rank_bm25 없으면 임베딩-only."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            return
        data = self.collection.get(include=["documents", "metadatas"])
        if not data["documents"]:
            return
        tokenized = [_tokenize_ko(d) for d in data["documents"]]
        self._bm25 = BM25Okapi(tokenized)
        self._bm25_corpus_docs = [
            {"law_name": m["law_name"], "article": m["article"],
             "enforced_date": m["enforced_date"], "text": d, "source_url": m["source_url"]}
            for d, m in zip(data["documents"], data["metadatas"])
        ]

    def search(self, query: str, k: int = 3) -> list[RetrievedChunk]:
        """질의 → (분야별 확장) → 하이브리드/임베딩 검색 top-k."""
        if not self.is_real:
            return self._search_stub(k)
        eq = _expand_query(self.domain, query)   # ★검색 입력만 확장
        if self.has_bm25:
            return self._search_hybrid(eq, k)
        return self._search_embedding_only(eq, k)

    def _search_embedding_only(self, query: str, k: int) -> list[RetrievedChunk]:
        emb = _get_model().encode([query]).tolist()
        res = self.collection.query(query_embeddings=emb, n_results=k)
        out = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            out.append({"law_name": meta["law_name"], "article": meta["article"],
                        "enforced_date": meta["enforced_date"], "text": doc,
                        "source_url": meta["source_url"], "score": round(1 - dist, 4)})
        return out

    def _search_hybrid(self, query: str, k: int) -> list[RetrievedChunk]:
        fetch_k = k * 3
        # ① 임베딩
        emb = _get_model().encode([query]).tolist()
        eres = self.collection.query(query_embeddings=emb, n_results=fetch_k)
        emb_scores, data = {}, {}
        edocs, emetas, edists = eres["documents"][0], eres["metadatas"][0], eres["distances"][0]
        for doc, meta, dist in zip(edocs, emetas, edists):
            did = f"{meta['law_name']}_{meta['article']}"
            emb_scores[did] = 1 - dist
            data[did] = {"law_name": meta["law_name"], "article": meta["article"],
                         "enforced_date": meta["enforced_date"], "text": doc,
                         "source_url": meta["source_url"]}
        # ② BM25
        raw = self._bm25.get_scores(_tokenize_ko(query))
        bmax = max(raw) if max(raw) > 0 else 1.0
        bm_scores = {}
        for idx in sorted(range(len(raw)), key=lambda i: raw[i], reverse=True)[:fetch_k]:
            cd = self._bm25_corpus_docs[idx]
            did = f"{cd['law_name']}_{cd['article']}"
            bm_scores[did] = raw[idx] / bmax
            data.setdefault(did, cd)
        # ③ 가중결합 (분야별 α): α·임베딩 + (1-α)·BM25
        a = self.alpha
        combined = [(did, a * emb_scores.get(did, 0.0) + (1 - a) * bm_scores.get(did, 0.0))
                    for did in set(emb_scores) | set(bm_scores)]
        combined.sort(key=lambda x: x[1], reverse=True)
        out = []
        for did, sc in combined[:k]:
            d = data[did]
            out.append({"law_name": d["law_name"], "article": d["article"],
                        "enforced_date": d["enforced_date"], "text": d["text"],
                        "source_url": d["source_url"], "score": round(sc, 4)})
        return out

    def _search_stub(self, k: int) -> list[RetrievedChunk]:
        return [{"law_name": f"[{self.domain}] stub법", "article": f"제{i+1}조",
                 "enforced_date": "2024-01-01", "text": f"({self.domain}) stub {i}",
                 "source_url": "https://www.law.go.kr/", "score": 0.9 - i * 0.1}
                for i in range(k)]


# ── 내장 평가 진입점 (검색축만 — Bedrock 불필요) ─────────────────────
def _matches(expected: str, chunk: dict) -> bool:
    got = f"{chunk['law_name']} {chunk['article']}"
    return expected.replace(" ", "") in got.replace(" ", "")


def _score(rag: DomainRAG, items: list[dict], k: int = 3):
    hits = rr = 0.0
    ranks = []
    for it in items:
        chunks = rag.search(it["question"], k=k)
        rank = next((i for i, c in enumerate(chunks, 1)
                     if any(_matches(e, c) for e in it["expected_articles"])), None)
        ranks.append(rank)
        if rank:
            hits += 1
            rr += 1.0 / rank
    n = len(items)
    return round(hits / n, 3), round(rr / n, 3), ranks


def _eval_domain(domain: str):
    path = os.path.join(_REPO, "evals", f"{domain}.jsonl")
    if not os.path.exists(path):
        print(f"[{domain}] 평가셋 없음 — 건너뜀")
        return
    items = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    rag = DomainRAG(domain=domain)
    if not rag.is_real:
        print(f"[{domain}] 컬렉션 미적재(0건) — 건너뜀 (chromadb·데이터 필요)")
        return
    h, m, ranks = _score(rag, items)
    print(f"\n[{domain}] n={len(items)}  hybrid={rag.has_bm25}  α={rag.alpha}")
    print(f"  hit@3 = {h}   MRR = {m}")
    miss = [f"Q{i+1}" for i, r in enumerate(ranks) if not r]
    if miss:
        print(f"  miss: {', '.join(miss)}")
    print("  α 스윕:", end=" ")
    for a in (0.8, 0.7, 0.6, 0.5, 0.4):
        rag.alpha = a
        hh, mm, _ = _score(rag, items)
        print(f"{a}:{hh}/{mm}", end="  ")
    print()


if __name__ == "__main__":
    from pipeline.config import LAW_LIST
    target = sys.argv[1] if len(sys.argv) > 1 else "finance"
    domains = list(LAW_LIST) if target == "all" else [target]
    for d in domains:
        _eval_domain(d)
