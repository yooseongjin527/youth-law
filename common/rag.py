"""공통 RAG 헬퍼 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

각 전문가는 자기 분야 이름으로 DomainRAG 인스턴스를 만든다.
→ 분야마다 별도 벡터DB 컬렉션(law_labor 등). 4명이 각자 자기 컬렉션을 독립 구축.
검색 '기법'은 여기 하나로 통일(고도화도 여기서만) → 4분야 자동 적용.

★ 검색 엔진 승격 완료 — 분야별 검색기법 게이트 ★
하이브리드 로직은 common/rag_hybrid.py에 '승격 대기'로 분리돼 있던 것을 이 파일로 흡수했다.
단, 4분야를 일괄 하이브리드로 바꾸지 않고 분야별로 검색기법을 고른다(_HYBRID_DOMAINS):
  · finance·labor      → 하이브리드(BM25+임베딩) + 분야별 α·쿼리확장 (담당이 합의·튜닝한 분야)
  · housing·consumer   → 기존 임베딩-only(쿼리확장·BM25 없음) — 동작 불변(미합의 분야 보존)
새 기법을 쓰려면 _HYBRID_DOMAINS에 분야를 추가한다(해당 담당 합의 후).

구성:
  · 하이브리드   = BM25(kiwipiepy)+임베딩 가중결합, 분야별 α, 정의의도 공통처리, synonyms 쿼리확장
  · 임베딩-only  = 질의 임베딩 → Chroma 최근접(확장 없음). housing/consumer 승격 전 동작 그대로
  · 폴백: 라이브러리(chromadb/rank_bm25)·컬렉션 없으면 임베딩-only → stub 으로 단계적 폴백
          → 그래프·CI가 항상 동작. 인덱싱은 pipeline/gold.py 가 담당.
  (보류) cross-encoder 리랭킹 → 한국어 법령서 성능저하 확인되어 v2로

검증(검색축만 — Bedrock 불필요):
  .venv/bin/python common/rag.py finance   # finance 평가셋 hit@3/MRR + α 스윕
  .venv/bin/python common/rag.py all       # 데이터 적재된 분야 전부

★ 환각 하네스: LLM 동적 확장어는 검색 입력(임베딩·BM25)에만 쓰고,
  답변 citation은 반드시 검색 chunk에서만 만든다. 확장은 인용/답변과 무관. ★
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 'python common/rag.py'로 직접 실행 시 repo 루트를 path에 (pipeline import용).
# 모듈로 import될 땐 이미 path에 있어 no-op.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from typing import TypedDict  # noqa: E402

from pipeline.config import CHROMA_DIR, EMBED_MODEL  # noqa: E402

# ── 분야별 검색기법 게이트 ──────────────────────────────────────────
# 하이브리드(BM25+임베딩+쿼리확장)를 적용할 분야. 나머지(housing/consumer)는 임베딩-only
# (rag.py 승격 전 동작 그대로). 분야 담당이 합의·튜닝하면 여기에 추가한다.
_HYBRID_DOMAINS = {"finance", "labor"}

# ── 분야별 튜닝 노브 (하이브리드 분야에서만 사용) ─────────────────────
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

# ── 분야별 쿼리확장 사전 (파일 분리) ────────────────────────────────
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
        if key in query:                 # ★ substring 매칭
            for t in terms:
                if t not in extra:
                    extra.append(t)
    if not extra:
        return query
    return query + " " + " ".join(extra[:_MAX_EXPANSION_TERMS])


class RetrievedChunk(TypedDict):
    law_name: str
    article: str
    enforced_date: str   # 시행일 (현행법 신뢰성)
    text: str
    source_url: str
    score: float


_model = None  # 임베딩 모델 싱글톤 (4개 인스턴스가 공유)
_kiwi = None   # 형태소 분석기 싱글톤 (BM25 토크나이저)


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
    """한 분야 컬렉션(law_{domain}) 검색기.

    검색기법은 분야별로 갈린다(_HYBRID_DOMAINS):
      finance·labor → 하이브리드(BM25+임베딩) + 쿼리확장 / housing·consumer → 임베딩-only.
    공개 인터페이스(domain, is_real, search)는 동일 → 에이전트 코드 변경 없이 drop-in."""

    def __init__(self, domain: str, corpus_path: str | None = None):
        self.domain = domain
        self.corpus_path = corpus_path or f"data/{domain}"
        self.collection_name = f"law_{domain}"
        self.collection = None
        self._bm25 = None
        self._bm25_corpus_docs: list[dict] = []
        # 이 분야가 하이브리드(BM25+쿼리확장)를 쓰는가. 아니면 임베딩-only.
        self.hybrid_enabled = domain in _HYBRID_DOMAINS
        # 분야별 α (env HYBRID_ALPHA가 있으면 스윕용으로 우선) — 하이브리드 분야에서만 사용
        self.alpha = float(os.getenv("HYBRID_ALPHA", _ALPHA_BY_DOMAIN.get(domain, _DEFAULT_ALPHA)))
        try:  # 실제 백엔드 연결 시도 — 실패 시 stub 폴백
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            col = client.get_or_create_collection(self.collection_name)
            if col.count() > 0:               # 데이터가 있어야 실모드
                self.collection = col
                if self.hybrid_enabled:       # 하이브리드 분야만 BM25 인덱스 구축
                    self._build_bm25_index()  # Chroma 데이터로 BM25 인덱스 구축
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
        """질의 → 분야별 검색기법 → top-k.
        finance·labor: 쿼리확장 + 하이브리드(BM25 없으면 확장-임베딩).
        housing·consumer: 임베딩-only(확장 없음) — 승격 전 동작 그대로."""
        if not self.is_real:
            return self._search_stub(k)
        if not self.hybrid_enabled:              # housing/consumer: 기존 임베딩-only
            return self._search_embedding_only(query, k)
        eq = _expand_query(self.domain, query)   # ★finance/labor만 확장 (검색 입력만)
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

    # ── stub 폴백 (개발 초기·CI) ────────────────────
    def _search_stub(self, k: int) -> list[RetrievedChunk]:
        return [{"law_name": f"[{self.domain}] stub법", "article": f"제{i + 1}조",
                 "enforced_date": "2024-01-01",
                 "text": f"({self.domain}) 사용자는 ...하여야 한다. [조문 원문 stub {i}]",
                 "source_url": "https://www.law.go.kr/", "score": 0.9 - i * 0.1}
                for i in range(k)]

    def index(self, docs: list[dict]) -> int:
        """(하위호환) 직접 인덱싱 — 실제 적재는 pipeline/gold.py 사용 권장."""
        from pipeline.gold import load_gold
        return load_gold(self.domain)


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
    miss = [f"Q{i + 1}" for i, r in enumerate(ranks) if not r]
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
