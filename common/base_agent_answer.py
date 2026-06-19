"""공통 도메인 에이전트 베이스 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).
_mk_ 접두사: 공용 파일 신규/수정 시 개인 규약(CLAUDE.local.md) 적용.

★ 왜 있는가 ★
agents/<분야>.py 4개가 각자 구현하면 '분야 특성(달라야 하는 것)'뿐 아니라
'사용자 경험 불변식(달라지면 안 되는 것)'까지 제각각이 된다.
  - 달라야 하는 것  : _rag.search() 호출 방식(k 등) · _PROMPT_TEMPLATE(톤·강조점)
  - 달라지면 안 됨   : 검색 실패 폴백 · 빈 검색결과 대응 · Bedrock 에러 핸들링 ·
                      DomainAnswer 조립 · 반환 구조(domain_answers/messages)
이 베이스가 후자(불변식)를 한곳에서 강제한다. 분야 특성은 인자로 '주입'한다.

★ 커스터마이징 ★
- 기본은 run_domain_agent(state, domain, rag, prompt_template)만으로 충분.
- 분야가 폴백 confidence를 달리 두고 싶으면 *_confidence 인자를 덮어쓴다.
- 베이스로 표현 안 되는 분야 정책(예: housing 인용 가지치기, consumer 추출 폴백)은
  이 베이스를 호출하지 않고 자기 파일에서 직접 구현해도 된다(강제 아님).

★ 불변식 ★
- 어떤 분야도 빈 검색결과·Bedrock 실패에 크래시하지 않는다(그래프 보호).
- 폴백 confidence는 verifier 임계값(_MIN_CONFIDENCE=0.5)과 정합한다:
    · 검색 자체가 없음 → empty_confidence(<0.5) → verifier 탈락 → planner 정직 거절
    · 검색은 됐는데 Bedrock만 실패 → degraded_confidence(>=0.5) → 검색 조문 근거로 생존
- citation은 RAG 청크에서만 만든다(환각 0). 연락처는 contacts.py에서만.
"""
from common.contacts import get_contacts
from common.llm import call_bedrock
from state import LegalState

# Bedrock 실패(미구현 포함) 시 — 지어내지 않고 검색된 근거 조문으로만 안내.
_FALLBACK = (
    "아래 현행 법령 조문을 근거 자료로 안내드립니다. "
    "구체적 사안은 함께 안내한 공식 기관 상담을 권합니다."
)
# 검색 결과 자체가 없을 때 — 환각 없이 정직하게 거절.
_NO_CHUNKS = (
    "검색된 현행 법령 조문이 없어 정확한 답변을 드리기 어렵습니다. "
    "아래 공식 기관 상담을 권합니다."
)


def safe_search(rag, query: str, k: int = 3) -> list[dict]:
    """Run domain RAG without letting retrieval failures crash the graph."""
    try:
        return rag.search(query, k=k)
    except Exception:
        return []


def chunks_to_citations(chunks: list[dict]) -> list[dict]:
    """RAG 청크(text) → LegalCitation(snippet) 형태로 변환. 키 매핑만 한다."""
    return [
        {
            "law_name": c["law_name"], "article": c["article"],
            "enforced_date": c["enforced_date"], "snippet": c["text"],
            "source_url": c["source_url"],
        }
        for c in chunks
    ]


def build_domain_answer(
    *,
    domain: str,
    answer: str,
    chunks: list[dict],
    confidence: float,
    contacts: list[dict] | None = None,
) -> dict:
    """Assemble the shared DomainAnswer shape while preserving domain logic upstream."""
    return {
        "domain": domain,
        "answer": answer,
        "citations": chunks_to_citations(chunks),
        "contacts": contacts if contacts is not None else get_contacts(domain),
        "confidence": confidence,
    }


def domain_result(domain: str, answer: dict, message: str) -> dict:
    """Return the shared LangGraph node update shape."""
    return {
        "domain_answers": [answer],
        "messages": [f"[{domain}] {message}"],
    }


def extractive_answer(chunks: list[dict]) -> str:
    """Build a safe fallback answer from retrieved law references only."""
    refs: list[str] = []
    for c in chunks:
        ref = f"{c['law_name']} {c['article']}"
        if ref not in refs:
            refs.append(ref)
    return (
        "문의하신 내용과 관련된 현행 법령 조문을 찾았습니다: "
        + ", ".join(refs)
        + ". 아래 근거 조문 원문(시행일 포함)과 검증된 공식 연락처를 확인해 주세요. "
        "구체적인 적용은 상황에 따라 다를 수 있어 전문가 상담을 권합니다."
    )


def _format_context(chunks: list[dict]) -> str:
    """검색 조문을 프롬프트용 컨텍스트로. (원본 labor.py와 동일 포맷)"""
    return "\n\n".join(
        f"[{c['law_name']} {c['article']}] (시행 {c['enforced_date']})\n{c['text']}"
        for c in chunks
    )


def run_domain_agent(
    state: LegalState,
    *,
    domain: str,
    rag,
    prompt_template: str,
    search_k: int = 3,
    ok_confidence: float = 0.8,
    degraded_confidence: float = 0.6,
    empty_confidence: float = 0.2,
) -> dict:
    """한 분야 전문가의 공통 흐름. 분야는 domain/rag/prompt_template만 주입한다.

    prompt_template 플레이스홀더: {query}, {context}
    return: {"domain_answers": [DomainAnswer], "messages": [...]} (계약 통일)
    """
    query = state["user_query"]

    # 1) RAG 검색 — 실패해도 그래프를 죽이지 않게 빈 리스트로 폴백.
    chunks = safe_search(rag, query, k=search_k)

    # 2) 빈 검색결과 → 안전 응답 / 검색 충분 → Bedrock 답변(실패 시 검색 조문 안내).
    if not chunks:
        answer_text, confidence, note = _NO_CHUNKS, empty_confidence, "검색결과 없음"
    else:
        prompt = prompt_template.format(query=query, context=_format_context(chunks))
        try:
            answer_text = call_bedrock(prompt, task="answer")
            confidence, note = ok_confidence, "Bedrock 답변 생성"
        except Exception:
            # 호출 실패/미구현 — 지어내지 않고 검색된 근거 조문만 제시(정직한 degraded).
            answer_text, confidence, note = _FALLBACK, degraded_confidence, "Bedrock 실패 폴백"

    # 3) DomainAnswer 조립 + 검증 연락처 연결 + 반환 구조 통일.
    answer = build_domain_answer(
        domain=domain,
        answer=answer_text,
        chunks=chunks,
        confidence=confidence,
    )
    rag_mode = "실모드" if getattr(rag, "is_real", False) else "stub"
    return domain_result(domain, answer, f"{note} (RAG={rag_mode})")
