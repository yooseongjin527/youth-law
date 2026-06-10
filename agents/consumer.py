"""소비자보호 분야 전문가 — 담당 C 전용.
labor.py와 동일 패턴 — 자기 분야 코퍼스(컬렉션)만 다름.

────────────────────────────────────────────────────────
TODO 우선순위 (담당 C)
  [C/Day1] ① 소비자보호 데이터 수집 → scripts/build_index.py 의 load_corpus
  [C/Day2] ② consumer 컬렉션 인덱싱 (python scripts/build_index.py consumer)
  [C/Day3] ③ 답변 생성 Bedrock으로 (청약철회·환불·온라인거래; 검색 조문 근거만)
  [C/Day4] ④ 답변-근거 정합성 체크
  --- 자기 분야 끝나면 공용(rag.py 고도화 / 평가 / planner)으로 ---
────────────────────────────────────────────────────────
"""
from common.contacts import get_contacts
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="consumer", corpus_path="data/consumer")


def consumer_agent(state: LegalState) -> dict:
    chunks = _rag.search(state["user_query"], k=3)
    # TODO(C/Day3): chunks 근거로 Bedrock 답변 생성. 검색 조문 밖 내용 금지.
    answer: dict = {
        "domain": "consumer",
        "answer": "stub: 소비자보호 관점 답변",
        "citations": [
            {
                "law_name": c["law_name"], "article": c["article"],
                "enforced_date": c["enforced_date"], "snippet": c["text"],
                "source_url": c["source_url"],
            } for c in chunks
        ],
        "contacts": get_contacts("consumer"),
        "confidence": 0.8,
    }
    return {"domain_answers": [answer], "messages": ["[consumer] stub 실행됨 (RAG)"]}

def consumer_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """consumer 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = consumer_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
