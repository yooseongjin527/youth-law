"""주택임대차 분야 전문가 — 담당 B 전용.

공통 베이스(common/base_agent_mk_20260618_.run_domain_agent)의 **불변식·규약을 따르되**,
housing 고유 정책인 **citation 가지치기**(답변이 실제 쓴 조문만 근거로)를 위해
베이스를 직접 호출하지 않고 같은 흐름을 자기 파일에서 구현한다.
(베이스 docstring이 "housing 인용 가지치기 같은 특수 정책은 자기 파일 직접 구현 허용"이라 명시)

★ 베이스와 맞춘 불변식 ★
- 검색/Bedrock 실패에 크래시하지 않는다(그래프 보호).
- confidence ↔ verifier 임계값(_MIN_CONFIDENCE=0.5) 정합:
    · 빈 검색결과 → 0.2(<0.5) → verifier 탈락 → planner 정직 거절
    · 검색은 됐는데 Bedrock만 실패 → 0.6(>=0.5) → 검색 조문 근거로 생존
    · 정상 → 0.8
- citation은 RAG 청크에서만(환각 0), 연락처는 contacts.py에서만.
- 반환 구조/메시지 포맷(`[domain] note (RAG=실모드/stub)`)을 베이스와 통일.

★ housing 고유(베이스 plain 흐름과 다른 점) ★
- 번호 매긴 컨텍스트 + call_bedrock_json으로 answer + used(실제 인용 조문 번호)를 받아
  답변이 실제 쓴 조문만 citation으로 가지치기(평균 근거 수↓, 근거 정합↑).
"""
from common.contacts import get_contacts
from common.drafter import make_draft
from common.llm import call_bedrock_json
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="housing", corpus_path="data/housing")

# 폴백/빈결과 문구·confidence 의미는 베이스(base_agent_mk)와 동일하게 맞춘다.
_FALLBACK = (
    "아래 현행 법령 조문을 근거 자료로 안내드립니다. "
    "구체적 사안은 함께 안내한 공식 기관 상담을 권합니다."
)
_NO_CHUNKS = (
    "검색된 현행 법령 조문이 없어 정확한 답변을 드리기 어렵습니다. "
    "아래 공식 기관 상담을 권합니다."
)
_OK_CONF, _DEGRADED_CONF, _EMPTY_CONF = 0.8, 0.6, 0.2

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
    """검색 조문을 프롬프트용으로 번호 매겨 정리(used 참조용)."""
    return "\n".join(
        f'[{i}] {c["law_name"]} {c["article"]} (시행 {c["enforced_date"]})\n"{c["text"]}"'
        for i, c in enumerate(chunks, 1)
    )


def _to_citations(chunks: list[dict]) -> list[dict]:
    """RAG 청크 → LegalCitation(snippet). 환각 0 — 검색 청크에서만."""
    return [
        {
            "law_name": c["law_name"], "article": c["article"],
            "enforced_date": c["enforced_date"], "snippet": c["text"],
            "source_url": c["source_url"],
        }
        for c in chunks
    ]


def housing_agent(state: LegalState) -> dict:
    query = state["user_query"]

    # 1) RAG 검색 — 실패해도 그래프를 죽이지 않게 빈 리스트 폴백(베이스 불변식).
    try:
        chunks = _rag.search(query, k=3)
    except Exception:
        chunks = []

    used: list[int] | None = None
    if not chunks:
        # 2a) 빈 검색결과 → 환각 없이 정직 거절(낮은 confidence로 verifier 탈락).
        answer_text, confidence, note = _NO_CHUNKS, _EMPTY_CONF, "검색결과 없음"
    else:
        # 2b) 검색 충분 → answer + used 구조화 호출. 실패 시 검색 조문 안내(정직한 degraded).
        prompt = _PROMPT_TEMPLATE.format(query=query, context=_format_context(chunks))
        try:
            data = call_bedrock_json(prompt, required_keys=["answer", "used"], task="answer")
            answer_text = str(data["answer"]).strip()
            raw = data.get("used") or []
            used = [int(x) for x in raw if str(x).strip().lstrip("-").isdigit()]
            confidence, note = _OK_CONF, "Bedrock 답변 생성"
        except Exception:
            answer_text, confidence, note = _FALLBACK, _DEGRADED_CONF, "Bedrock 실패 폴백"

    # 3) ★housing 고유★ citation 가지치기 — 답변이 실제 쓴 조문만. used 비면 전체 유지(안전).
    cited = chunks
    if used:
        picked = [chunks[i - 1] for i in used if 1 <= i <= len(chunks)]
        if picked:
            cited = picked

    # 4) DomainAnswer 조립 + 검증 연락처 + 반환 구조 통일(베이스와 동일).
    answer: dict = {
        "domain": "housing",
        "answer": answer_text,
        "citations": _to_citations(cited),
        "contacts": get_contacts("housing"),
        "confidence": confidence,
    }
    rag_mode = "실모드" if getattr(_rag, "is_real", False) else "stub"
    return {"domain_answers": [answer], "messages": [f"[housing] {note} (RAG={rag_mode})"]}


def housing_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """housing 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = housing_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
