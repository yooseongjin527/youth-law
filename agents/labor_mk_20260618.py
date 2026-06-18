"""노동 분야 전문가 (공통 베이스 적용판) — 담당 A 전용.

원본 agents/labor.py는 보존하고, 공통 베이스(run_domain_agent)를 쓰도록 새로 작성한 파일.
달라지면 안 되는 것(폴백/빈결과/조립/에러핸들링)은 베이스가 강제하고,
이 파일은 분야 특성(검색 방식·_PROMPT_TEMPLATE)만 관리한다.

원본 대비 바뀐 점(코드 그대로 이전 + 최소 보정):
  - 깨져 있던 import 정리: common.rag_0617/llm_0617(존재 안 함) → 표준 common.rag/베이스
  - 프롬프트 플레이스홀더 {question} → {query} (베이스 계약에 맞춤)
  - try 없이 노출돼 크래시하던 Bedrock 호출 → 베이스가 폴백 처리
"""
from common._mk_20260618_base_agent import run_domain_agent
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="labor", corpus_path="data/labor")

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
    return run_domain_agent(
        state,
        domain="labor",
        rag=_rag,
        prompt_template=_PROMPT_TEMPLATE,
    )


def labor_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """labor 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = labor_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
