"""주택임대차 분야 전문가 (공통 베이스 적용 뼈대) — 담당 B 전용.

원본 agents/housing.py는 보존하고, 공통 베이스(run_domain_agent)를 쓰도록 새로 만든 뼈대.
이 파일은 분야 특성(검색·_PROMPT_TEMPLATE)만 관리하고,
달라지면 안 되는 것(폴백/빈결과/조립/에러핸들링)은 베이스가 강제한다.

★ 담당자(B) 확인 필요 — 베이스가 '아직' 못 담는 원본 고유 정책 ★
  - 원본은 call_bedrock_json으로 answer + used(실제 인용 조문 번호)를 받아
    citation '가지치기'를 한다. 베이스는 plain call_bedrock(텍스트)만 호출하므로
    used 기반 가지치기가 빠진다 → 전체 검색 조문이 citation으로 남는다.
  - 아래 _PROMPT_TEMPLATE은 원본 _PROMPT를 '그대로' 옮긴 것이라 여전히 used 출력을
    요구한다. 베이스 흐름(plain)에서는 그 지시가 답변 텍스트에 섞일 수 있으니,
    가지치기를 유지할지(원본 사용) / 단순화할지(이 뼈대 사용)는 담당자가 결정.
"""
from common._mk_20260618_base_agent import run_domain_agent
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="housing", corpus_path="data/housing")

# 원본 agents/housing.py 의 _PROMPT 그대로 이식 (플레이스홀더 {query}/{context} 동일).
_PROMPT_TEMPLATE = """당신은 청년에게 주택임대차 법령 '정보'를 안내하는 도우미입니다.
아래 [검색된 현행 법령 조문]만을 근거로 사용자 질문에 답하세요.

규칙:
- 제시된 조문에 없는 내용은 절대 지어내지 마세요(법조문·숫자·기한 포함).
- 근거가 부족하면 "검색된 조문만으로는 정확히 답하기 어렵다"고 정직하게 답하세요.
- 단정적 법률 자문이 아니라 '법령 정보 안내'입니다. 답변 끝에 전문가 상담을 권하세요.
- 평어로 물어본 청년이 이해하기 쉽게, 군더더기 없이.

[사용자 질문]
{query}

[검색된 현행 법령 조문]
{context}
"""


def housing_agent(state: LegalState) -> dict:
    return run_domain_agent(
        state,
        domain="housing",
        rag=_rag,
        prompt_template=_PROMPT_TEMPLATE,
    )


def housing_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """housing 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = housing_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
