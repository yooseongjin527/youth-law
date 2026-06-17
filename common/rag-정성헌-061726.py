"""[개발 스테이징 — 정성헌 / 2026-06-17] 검색 고도화 rag (공용 common/rag.py 후보).

⚠️ 이 파일은 PR 전 개인 개발본이다. 공용 common/rag.py는 건드리지 않는다.
    검증이 끝나면 이 로직을 common/rag.py로 올리는 PR을 별도로 낸다(전원 승인).
    파일명에 하이픈이 있어 import 불가 → '실행형'으로 구성(맨 아래 평가 진입점).

담은 것 (finance에서 hit@3 0.52→1.0, held-out 0.857로 검증된 조합을 4분야로 일반화):
  ① 하이브리드 검색  : BM25(kiwipiepy 형태소) + 임베딩 가중결합  (구 PR #17 로직)
  ② 분야별 쿼리확장  : 평어→법률어. ★전역 금지★ {domain: MAP}로 분야 한정(타 분야 오염 방지)
  ③ 분야별 α        : HYBRID_ALPHA 전역 단일 → {domain: α}. finance=0.6 확정, 나머지 스윕 대상
  ④ 정의 의도 공통처리: "뭔가요/무엇/뜻"→"용어의 정의"(고-IDF). 분야 불문 일반화 확인됨
  (보류) cross-encoder 리랭킹 → v2 (한국어 법령서 성능저하 확인)

실행:
  python common/rag-정성헌-061726.py finance     # finance 평가셋으로 hit@3/MRR + α 스윕
  python common/rag-정성헌-061726.py all          # 데이터 적재된 분야 전부
"""
from __future__ import annotations

import os
import sys

# 이 파일을 'python common/rag-...py'로 직접 실행할 때 repo 루트를 path에 (pipeline import용)
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from typing import TypedDict  # noqa: E402

from pipeline.config import CHROMA_DIR, EMBED_MODEL  # noqa: E402

# ── 분야별 튜닝 노브 (③) ────────────────────────────────────────────
_DEFAULT_ALPHA = 0.7
_ALPHA_BY_DOMAIN = {
    "finance": 0.6,   # 스윕 결과 확정 (hit@3 1.0 + MRR 최고)
    "labor": 0.7,     # 데이터 받으면 스윕
    "housing": 0.7,
    "consumer": 0.7,
}
_MAX_EXPANSION_TERMS = 6  # 너무 많이 붙이면 임베딩 희석 → 상한

# ── 정의(definition) 의도 — 분야 공통 (④) ──────────────────────────
# "용어/정의"는 각 법의 '정의' 조문에만 나오는 고-IDF 토큰이라 BM25 변별력이 크다.
_DEFINITION_TRIGGERS = ("뭔가요", "뭐예요", "뭐야", "무엇", "뜻이")
_DEFINITION_TERM = "용어의 정의"

# ── 분야별 쿼리확장 사전 (②) — 각 분야 담당이 자기 MAP 기여 ───────────
# 트리거(평어 부분문자열) → 덧붙일 법률 용어. 검색(임베딩·BM25) 입력에만 적용.
_SYNONYMS_BY_DOMAIN: dict[str, dict[str, list[str]]] = {
    "finance": {
        # 보이스피싱·전기통신금융사기 — 방향이 갈려 우산용어/송금방향 분리
        "보이스피싱": ["전기통신금융사기"],
        "보냈": ["피해구제 신청", "지급정지"],
        "송금": ["피해구제 신청", "지급정지"],
        "사기": ["전기통신금융사기", "지급정지", "사기이용계좌"],
        "돌려받": ["피해환급금", "채권소멸절차", "지급정지"],
        "통장": ["사기이용계좌", "명의인", "전자금융거래 제한"],
        "전화번호": ["전화번호 이용중지"],
        "억울": ["지급정지 이의제기"],
        # 개인회생·파산·면책
        "개인회생": ["개인회생절차 개시", "변제계획안"],
        "빚": ["채무", "변제"],
        "파산": ["파산선고", "면책"],
        "면책": ["면책 신청", "면책 기각사유"],
        "계획서": ["변제계획안 제출"],
        # 불법추심
        "협박": ["폭행·협박 등 금지", "불공정한 행위"],
        "찾아": ["야간 방문", "반복적인 방문"],
        "변호사": ["채무자 대리인", "대리인 연락 금지"],
        "가족": ["관계인 연락 금지", "개인정보 누설"],
        "부모님": ["관계인 연락 금지", "개인정보 누설"],  # held-out H4 보강
        "동료": ["관계인 연락 금지"],
        "독촉": ["복수 채권추심 위임 금지", "반복 추심"],
        "서류": ["채무확인서 교부"],
        "비용": ["채권추심 비용", "부당한 비용 청구"],
        "추심": ["채권추심", "불공정한 행위"],
        # 사금융
        "이자": ["이자율 제한"],
        "능력": ["과잉 대부 금지"],
        "사채": ["미등록 대부업자", "불법사금융"],
        "무등록": ["미등록 대부업자", "대부계약 효력"],
        "광고": ["허위·과장 광고 금지"],
        "수수료": ["부대비용"],
    },
    "labor": {},     # TODO(담당 A): 노동 동의어 — 데이터 받으면 채움
    "housing": {},   # TODO(담당 B)
    "consumer": {},  # TODO(담당 C)
}


def _expand_query(domain: str, query: str) -> str:
    """평어 질의에 (정의 의도 + 분야별 동의어)를 덧붙여 검색 적중률을 높인다.
    트리거가 실제 질의에 있을 때만 추가(무관 용어 희석 방지). 상한 _MAX_EXPANSION_TERMS."""
    extra: list[str] = []
    if any(t in query for t in _DEFINITION_TRIGGERS):
        extra.append(_DEFINITION_TERM)
    for trigger, terms in _SYNONYMS_BY_DOMAIN.get(domain, {}).items():
        if trigger in query:
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
    """형태소 단위 토크나이징 — 명사/동사/형용사 어근만(조사·어미 제거)."""
    tokens = _get_kiwi().tokenize(text)
    pos = {"NNG", "NNP", "NNB", "VV", "VA", "SL"}
    return [t.form for t in tokens if t.tag in pos]


class DomainRAG:
    """한 분야 컬렉션(law_{domain}) 검색기 — 하이브리드 + 분야별 확장/α."""

    def __init__(self, domain: str, corpus_path: str | None = None):
        self.domain = domain
        self.corpus_path = corpus_path or f"data/{domain}"
        self.collection_name = f"law_{domain}"
        self.collection = None
        self._bm25 = None
        self._bm25_corpus_docs: list[dict] = []
        # 분야별 α (env HYBRID_ALPHA가 있으면 스윕용으로 우선)
        self.alpha = float(os.getenv("HYBRID_ALPHA", _ALPHA_BY_DOMAIN.get(domain, _DEFAULT_ALPHA)))
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            col = client.get_or_create_collection(self.collection_name)
            if col.count() > 0:
                self.collection = col
                self._build_bm25_index()
        except Exception:
            self.collection = None

    @property
    def is_real(self) -> bool:
        return self.collection is not None

    @property
    def has_bm25(self) -> bool:
        return self._bm25 is not None

    def _build_bm25_index(self) -> None:
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
        eq = _expand_query(self.domain, query)  # ★검색 입력만 확장(답변·인용 무관)
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
        for doc, meta, dist in zip(eres["documents"][0], eres["metadatas"][0], eres["distances"][0]):
            did = f"{meta['law_name']}_{meta['article']}"
            emb_scores[did] = 1 - dist
            data[did] = {"law_name": meta["law_name"], "article": meta["article"],
                         "enforced_date": meta["enforced_date"], "text": doc,
                         "source_url": meta["source_url"]}
        # ② BM25
        tok = _tokenize_ko(query)
        raw = self._bm25.get_scores(tok)
        bmax = max(raw) if max(raw) > 0 else 1.0
        bm_scores = {}
        for idx in sorted(range(len(raw)), key=lambda i: raw[i], reverse=True)[:fetch_k]:
            cd = self._bm25_corpus_docs[idx]
            did = f"{cd['law_name']}_{cd['article']}"
            bm_scores[did] = raw[idx] / bmax
            data.setdefault(did, cd)
        # ③ 가중결합 (분야별 α)
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
    import json
    path = os.path.join(_REPO, "evals", f"{domain}.jsonl")
    if not os.path.exists(path):
        print(f"[{domain}] 평가셋 없음 — 건너뜀")
        return
    items = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    rag = DomainRAG(domain=domain)
    if not rag.is_real:
        print(f"[{domain}] 컬렉션 미적재(0건) — 팀원 silver 대기. 건너뜀")
        return
    h, m, ranks = _score(rag, items)
    print(f"\n[{domain}] n={len(items)}  hybrid={rag.has_bm25}  α={rag.alpha}")
    print(f"  hit@3 = {h}   MRR = {m}")
    miss = [f"Q{i+1}" for i, r in enumerate(ranks) if not r]
    if miss:
        print(f"  miss: {', '.join(miss)}")
    # α 스윕
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
