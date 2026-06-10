"""금융·채무 분야 전문가 — 담당 D 전용.
labor.py와 동일 패턴 — 자기 분야 코퍼스(컬렉션)만 다름.
다루는 범위: 채무조정·개인회생(채무자회생법), 보이스피싱 피해(통신사기피해환급법),
            불법추심·사금융(채권추심법·대부업법).
※ 투자 조언 아님. '관련 법령 안내'로 엄격히 프레이밍.

────────────────────────────────────────────────────────
TODO 우선순위 (담당 D)
  [D/Day1] ① 데이터 수집: 채무자회생법 + 통신사기피해환급법 + 채권추심법 + 대부업법
  [D/Day2] ② finance 컬렉션 인덱싱 (python scripts/build_index.py finance)
  [D/Day3] ③ 답변 생성 Bedrock으로 (채무조정·보이스피싱·불법추심; 검색 조문 근거만)
  [D/Day4] ④ 답변-근거 정합성 체크
  --- 자기 분야 끝나면 공용(rag.py 고도화 / 평가 / planner)으로 ---
────────────────────────────────────────────────────────
"""
from common.contacts import get_contacts
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="finance", corpus_path="data/finance")


def finance_agent(state: LegalState) -> dict:
    chunks = _rag.search(state["user_query"], k=3)
    # TODO(D/Day3): chunks 근거로 Bedrock 답변 생성. 검색 조문 밖 내용 금지.
    answer: dict = {
        "domain": "finance",
        "answer": "stub: 금융·채무 관점 답변",
        "citations": [
            {
                "law_name": c["law_name"], "article": c["article"],
                "enforced_date": c["enforced_date"], "snippet": c["text"],
                "source_url": c["source_url"],
            } for c in chunks
        ],
        "contacts": get_contacts("finance"),
        "confidence": 0.8,
    }
    return {"domain_answers": [answer], "messages": ["[finance] stub 실행됨 (RAG)"]}

def finance_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """finance 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = finance_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
