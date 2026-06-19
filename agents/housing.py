"""주택임대차 분야 전문가 — 담당 B 전용.

공통 베이스(common/base_agent_answer)의 **조립 헬퍼를 그대로 사용**해
불변식(검색 크래시 방지·DomainAnswer 조립·반환 구조·연락처)을 베이스에 위임한다.
→ 베이스가 바뀌면 housing도 자동으로 따라간다(finance.py와 동일 패턴).

★ housing 고유 정책 (베이스 plain 흐름에 없는 것) ★
- call_bedrock_json으로 answer + used(실제 인용 조문 번호)를 받아 **답변이 실제 쓴
  조문만 citation으로 가지치기**(근거 정합↑). 가지친 청크를 build_domain_answer(chunks=)에
  넘기므로 베이스 조립과 그대로 호환된다.
- used 참조를 위해 **번호 매긴 컨텍스트**를 쓴다.
- confidence는 베이스 규약과 정합: 빈 검색 0.2(탈락) / Bedrock만 실패 0.6(생존) / 정상 0.8.
"""
from common.base_agent_answer import (
    build_domain_answer,
    domain_result,
    extractive_answer,
    safe_search,
)
from common.drafter import make_draft
from common.llm import call_bedrock_json
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="housing", corpus_path="data/housing")

# 검색 결과 자체가 없을 때 — 환각 없이 정직 거절(낮은 confidence로 verifier 탈락).
_NO_CHUNKS = (
    "검색된 현행 법령 조문이 없어 정확한 답변을 드리기 어렵습니다. "
    "아래 공식 기관 상담을 권합니다."
)

# ★환각 방지★: 검색된 조문 안에서만 답하게 강제 + used(실제 인용 조문 번호) 출력 요구.
_PROMPT_TEMPLATE = """당신은 청년에게 주택임대차 법령 '정보'를 안내하는 도우미입니다.
아래 [검색된 현행 법령 조문]만을 근거로 사용자 질문에 답하세요.

규칙:
- 제시된 조문에 없는 내용은 절대 지어내지 마세요(법조문·숫자·기한 포함).
- 근거가 부족하면 "검색된 조문만으로는 정확히 답하기 어렵다"고 정직하게 답하세요.
- 단정적 법률 자문이 아니라 '법령 정보 안내'입니다. 답변 끝에 전문가 상담을 권하세요.
- 평어로 물어본 청년이 이해하기 쉽게, 군더더기 없이.

[출력]
- answer: 위 규칙에 따른 답변.
- used: 답변의 근거로 실제 사용한 조문의 번호 배열(예: [1, 3]). 근거로 안 쓴 조문은
  넣지 말고, 조문 근거 없이 답했으면 빈 배열 [].

[사용자 질문]
{query}

[검색된 현행 법령 조문]
{context}
"""


def _format_context(chunks: list[dict]) -> str:
    """검색 조문을 프롬프트용으로 번호 매겨 정리(used 참조용 — housing 고유)."""
    return "\n".join(
        f'[{i}] {c["law_name"]} {c["article"]} (시행 {c["enforced_date"]})\n"{c["text"]}"'
        for i, c in enumerate(chunks, 1)
    )


def housing_agent(state: LegalState) -> dict:
    query = state["user_query"]
    chunks = safe_search(_rag, query, k=3)  # 베이스: 검색 크래시 방지

    used: list[int] | None = None
    if not chunks:
        # 빈 검색결과 → 환각 없이 정직 거절(verifier 탈락).
        answer_text, confidence, mode = _NO_CHUNKS, 0.2, "no-hit"
    else:
        prompt = _PROMPT_TEMPLATE.format(query=query, context=_format_context(chunks))
        try:
            data = call_bedrock_json(prompt, required_keys=["answer", "used"], task="answer")
            answer_text = str(data["answer"]).strip()
            raw = data.get("used") or []
            used = [int(x) for x in raw if str(x).strip().lstrip("-").isdigit()]
            confidence, mode = 0.8, "bedrock"
        except Exception:
            # Bedrock 실패/미구현 — 베이스 extractive_answer로 검색 조문만 안내(정직 degraded).
            answer_text, confidence, mode = extractive_answer(chunks), 0.6, "extractive"

    # ★housing 고유★ citation 가지치기 — 답변이 실제 쓴 조문만. used 비면 전체 유지(안전).
    cited = chunks
    if used:
        picked = [chunks[i - 1] for i in used if 1 <= i <= len(chunks)]
        if picked:
            cited = picked

    # 베이스 조립 — citation은 가지친 청크에서, 연락처·반환 구조는 베이스가 강제.
    answer = build_domain_answer(
        domain="housing", answer=answer_text, chunks=cited, confidence=confidence,
    )
    rag_mode = "실모드" if getattr(_rag, "is_real", False) else "stub"
    return domain_result("housing", answer, f"실행됨 (RAG={rag_mode}, 답변={mode})")


def housing_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """housing 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = housing_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
