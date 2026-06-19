"""노동 분야 전문가 — 담당 A 전용.
입력: user_query  →  출력: domain_answers(자기 분야 1건 append), messages

★ 4명의 전문가가 모두 이 패턴 ★
1) 자기 분야 DomainRAG로 현행 법령 검색 (자기 컬렉션)
2) 검색 조문을 근거로 답변 생성 (Bedrock) — 검색 밖 내용 금지(환각 방지)
3) 연락처는 get_contacts로 검증 데이터에서 (LLM 생성 금지)
4) DomainAnswer 반환

★ 이번 변경 ★
- 검색기: common/rag_hybrid.py 의 DomainRAG(BM25+임베딩 하이브리드, 분야별 α·쿼리확장).
  common/rag.py 와 동일 인터페이스라 drop-in. (synonyms/labor.jsonl 기준 hit@3 0.65→0.90)
- 불변식(빈 검색·Bedrock 실패 폴백·DomainAnswer 조립·반환 구조)은
  common/base_agent_answer.py 의 run_domain_agent 가 한곳에서 강제.
  → labor.py 는 '분야 특성'(검색기·프롬프트)만 주입한다.
"""
from common.base_agent_answer import run_domain_agent
from common.drafter import make_draft
from common.rag_hybrid import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="labor", corpus_path="data/labor")

# 베이스 run_domain_agent 플레이스홀더: {query}, {context}
_PROMPT_TEMPLATE = """
당신은 청년 대상 노동법 상담사입니다. 아래 검색된 법령 조문만을 근거로 답변하세요.

★ 규칙 ★
- 검색된 조문 밖의 내용은 절대 포함하지 마세요 (환각 방지).
- 법령명, 조번호, 시행일을 반드시 언급하세요.
- 청년이 이해할 수 있는 쉬운 말로 답하세요.
- 답변 끝에 "구체적 사건은 전문가 상담을 권합니다"를 붙이세요.

[검색된 조문]
{context}

[질문]
{query}
"""


def labor_agent(state: LegalState) -> dict:
    """노동 분야 전문가 노드 — 공통 흐름(run_domain_agent)에 분야 특성만 주입."""
    return run_domain_agent(
        state,
        domain="labor",
        rag=_rag,
        prompt_template=_PROMPT_TEMPLATE,
        search_k=3,
    )


def labor_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """labor 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = labor_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
