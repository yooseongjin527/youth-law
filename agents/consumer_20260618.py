"""소비자보호 분야 전문가 (공통 베이스 적용 뼈대) — 담당 C 전용.

원본 agents/consumer.py는 보존하고, 공통 베이스(run_domain_agent)를 쓰도록 만든 뼈대.
이 파일은 분야 특성(검색·_PROMPT_TEMPLATE)만 관리하고,
달라지면 안 되는 것(폴백/빈결과/조립/에러핸들링)은 베이스가 강제한다.

★ 담당자(C) 확인 필요 — 베이스가 '아직' 못 담는 원본 고유 정책 ★
  - 원본은 call_bedrock_json으로 answer + confidence(LLM이 산출)를 받고,
    LLM 실패 시 _extractive_answer(검색 조문 그대로 조립) 모드로 폴백한다.
  - 베이스는 plain call_bedrock(텍스트)만 호출하고 confidence는 고정값,
    LLM 실패 시 정해진 폴백 문구를 쓴다 → 추출 모드/LLM confidence가 빠진다.
  - 아래 _PROMPT_TEMPLATE은 원본 _ANSWER_PROMPT를 '그대로' 옮긴 것이라 여전히 JSON
    (answer/confidence) 출력을 요구한다. 추출 폴백·confidence 정책을 유지할지는 담당자가 결정.
"""
from common._mk_20260618_base_agent import run_domain_agent
from common.drafter import make_draft
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="consumer", corpus_path="data/consumer")

# 원본 agents/consumer.py 의 _ANSWER_PROMPT 그대로 이식 (플레이스홀더 {query}/{context} 동일).
_PROMPT_TEMPLATE = (
    "당신은 청년에게 소비자보호 관련 '현행 법령 정보'를 안내하는 도우미입니다.\n"
    "아래 [검색된 조문]에 있는 내용만 근거로 답하세요.\n"
    "- 조문에 없는 내용·기간·금액·기관명을 지어내지 마세요.\n"
    "- confidence는 '답이 검색된 조문에 실제로 근거하는 정도'입니다(확신도가 아님):\n"
    "  · 0.7 이상: 질문에 답하는 내용이 위 조문에 분명히 들어 있음\n"
    "  · 0.5~0.7: 위 조문에 부분적으로 근거가 있어 일부라도 답할 수 있음\n"
    "  · 0.5 미만: 검색된 조문이 질문과 무관하거나 근거가 없음(이때만 모른다고 답)\n"
    "- 단정적 법률 자문이 아니라 법령 안내입니다.\n"
    "- 청년이 이해할 쉬운 말로 4~6문장.\n\n"
    "[검색된 조문]\n{context}\n\n"
    "[질문]\n{query}\n\n"
    'JSON으로만 답하세요: {{"answer": "...", "confidence": 0.0~1.0}}'
)


def consumer_agent(state: LegalState) -> dict:
    return run_domain_agent(
        state,
        domain="consumer",
        rag=_rag,
        prompt_template=_PROMPT_TEMPLATE,
    )


def consumer_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """consumer 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = consumer_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
