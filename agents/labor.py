"""노동 분야 전문가 — 담당 A 전용.
입력: user_query  →  출력: domain_answers(자기 분야 1건 append), messages

★ 4명의 전문가가 모두 이 패턴 ★
1) 자기 분야 DomainRAG로 현행 법령 검색 (자기 컬렉션)
2) 검색 조문을 근거로 답변 생성 (Bedrock) — 검색 밖 내용 금지(환각 방지)
3) 연락처는 get_contacts로 검증 데이터에서 (LLM 생성 금지)
4) DomainAnswer 반환

★ 이번 변경 ★
- 검색기: common/rag.py 의 DomainRAG(BM25+임베딩 하이브리드, 분야별 α·쿼리확장).
  4분야 공통 엔진(하이브리드 승격 완료). (synonyms/labor.jsonl 기준 hit@3 0.65→0.90)
- 불변식(빈 검색·Bedrock 실패 폴백·DomainAnswer 조립·반환 구조)은
  common/base_agent_answer.py 헬퍼에 위임한다.
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

_rag = DomainRAG(domain="labor", corpus_path="data/labor")

# 검색 결과 자체가 없을 때 — 환각 없이 정직 거절(낮은 confidence로 verifier 탈락).
_NO_CHUNKS = (
    "검색된 현행 법령 조문이 없어 정확한 답변을 드리기 어렵습니다. "
    "아래 공식 기관 상담을 권합니다."
)

# ★환각 방지★: 검색된 조문 안에서만 답하게 강제 + used(실제 인용 조문 번호) 출력 요구.
_PROMPT_TEMPLATE = """당신은 청년 대상 노동법 상담사입니다.
아래 [검색된 조문]만을 근거로 답변하세요.

★ 규칙 ★
- 검색된 조문 밖의 내용은 절대 포함하지 마세요 (환각 방지).
- 법령명, 조번호, 시행일을 반드시 언급하세요.
- 청년이 이해할 수 있는 쉬운 말로 답하세요.
- 답변 끝에 "구체적 사건은 전문가 상담을 권합니다"를 붙이세요.

[출력]
- answer: 위 규칙에 따른 답변.
- used: 답변의 근거로 실제 사용한 조문의 번호 배열(예: [1, 3]). 근거로 안 쓴 조문은
  넣지 말고, 조문 근거 없이 답했으면 빈 배열 [].

[검색된 조문]
{context}

[질문]
{query}
"""


def _format_context(chunks: list[dict]) -> str:
    """검색 조문을 프롬프트용으로 번호 매겨 정리(used 참조용)."""
    return "\n".join(
        f'[{i}] {c["law_name"]} {c["article"]} (시행 {c["enforced_date"]})\n"{c["text"]}"'
        for i, c in enumerate(chunks, 1)
    )


def labor_agent(state: LegalState) -> dict:
    """노동 분야 전문가 노드 — 하이브리드 검색 + 답변-근거 가지치기."""
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
            # Bedrock 실패/미구현 — 검색 조문만 안내(정직 degraded). used 없음 → 가지치기 0.
            answer_text, confidence, mode = extractive_answer(chunks), 0.6, "extractive"

    # ★가지치기★ 답변이 실제 쓴 조문만 citation으로. used 비면 전체 유지(안전).
    cited = chunks
    if used:
        picked = [chunks[i - 1] for i in used if 1 <= i <= len(chunks)]
        if picked:
            cited = picked

    # 베이스 조립 — citation은 가지친 청크에서, 연락처·반환 구조는 베이스가 강제.
    answer = build_domain_answer(
        domain="labor", answer=answer_text, chunks=cited, confidence=confidence,
    )
    rag_mode = "실모드" if getattr(_rag, "is_real", False) else "stub"
    return domain_result("labor", answer, f"실행됨 (RAG={rag_mode}, 답변={mode})")


def labor_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """labor 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = labor_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
