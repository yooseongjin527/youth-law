"""금융·채무 분야 전문가 (공통 베이스 적용 뼈대) — 담당 D(mason) 전용.
※ 투자 조언 아님. '관련 법령 안내'로 엄격히 프레이밍.

원본 agents/finance.py는 보존하고, 공통 베이스(run_domain_agent)를 쓰도록 만든 뼈대.
이 파일은 분야 특성(검색·_PROMPT_TEMPLATE)만 관리하고,
달라지면 안 되는 것(폴백/빈결과/조립/에러핸들링)은 베이스가 강제한다.

★ 담당자(D) 확인 필요 — 베이스가 '아직' 못 담는 원본 고유 정책 ★
  - 원본은 _expand_query()로 평어 질의에 법률 용어를 덧붙여 검색 적중률(hit@k)을 올린다.
    베이스는 rag.search(query)를 그대로 호출하므로 이 쿼리 확장이 빠진다.
    (확장 사전 _FINANCE_SYNONYMS는 finance 평가 점수에 직결되므로 반드시 검토할 것.)
  - 원본은 call_bedrock_json으로 answer + confidence를 받고, 실패 시 _extractive_answer로
    폴백한다. 베이스는 plain call_bedrock + 고정 confidence + 정해진 폴백 문구를 쓴다.
  - 아래 _PROMPT_TEMPLATE은 원본 _ANSWER_PROMPT를 '그대로' 옮긴 것이라 여전히 JSON
    (answer/confidence) 출력을 요구한다. 쿼리확장·추출폴백 유지 여부는 담당자가 결정.
"""
from common.base_agent_mk_20260618_ import run_domain_agent
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="finance", corpus_path="data/finance")

# 원본 agents/finance.py 의 _ANSWER_PROMPT 그대로 이식 (플레이스홀더 {query}/{context} 동일).
_PROMPT_TEMPLATE = (
    "당신은 청년에게 금융·채무 관련 '현행 법령 정보'를 안내하는 도우미입니다.\n"
    "아래 [검색된 조문]에 있는 내용만 근거로 답하세요.\n"
    "- 첫 문장: 핵심 법적 결론을 조문의 정확한 용어(제도·권리·의무 명칭)를 그대로 써서 제시.\n"
    "- 다음: 근거 조문의 요건·효과를 구체적으로 — 기한·대상·절차·금액이 조문에 있으면 그 표현/수치 그대로.\n"
    "- 마지막: 청년이 이해할 쉬운 말로 한두 문장 풀이.\n"
    "- 조문에 없는 내용·수치·기관명 지어내기 금지. 조문만으로 부족하면 그 사실을 밝히고 confidence를 0.5 미만으로.\n"
    "- 군더더기·일반론·과한 면책 문구는 빼고 핵심만 3~5문장. 투자 조언이 아니라 법령 안내이며,\n"
    "  단정적 자문 표현은 피하되 법령 용어는 정확히 쓰세요.\n\n"
    "[검색된 조문]\n{context}\n\n"
    "[질문]\n{query}\n\n"
    'JSON으로만 답하세요: {{"answer": "...", "confidence": 0.0~1.0}}'
)


def finance_agent(state: LegalState) -> dict:
    return run_domain_agent(
        state,
        domain="finance",
        rag=_rag,
        prompt_template=_PROMPT_TEMPLATE,
    )


def finance_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """finance 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = finance_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
