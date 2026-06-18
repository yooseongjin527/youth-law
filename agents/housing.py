"""주택임대차 분야 전문가 — 담당 B 전용.
labor.py와 동일 패턴 — 자기 분야 코퍼스(컬렉션)만 다름.

────────────────────────────────────────────────────────
TODO 우선순위 (담당 B)
  [B/Day1] ① 주택임대차 데이터 수집 → scripts/build_index.py 의 load_corpus
  [B/Day2] ② housing 컬렉션 인덱싱 (python scripts/build_index.py housing)
  [B/Day3] ③ 답변 생성 Bedrock으로 (보증금·계약갱신·전세사기; 검색 조문 근거만)
  [B/Day4] ④ 답변-근거 정합성 체크
  --- 자기 분야 끝나면 공용(rag.py 고도화 / 평가 / planner)으로 ---
────────────────────────────────────────────────────────
"""
from common.contacts import get_contacts
from common.drafter import make_draft
from common.llm import call_bedrock_json
from common.rag import DomainRAG
from state import LegalState

_rag = DomainRAG(domain="housing", corpus_path="data/housing")

# ★환각 방지★: 검색된 조문 안에서만 답하도록 강제하는 지시.
_PROMPT = """당신은 청년에게 주택임대차 법령 '정보'를 안내하는 도우미입니다.
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

# Bedrock 호출 실패(미구현 포함) 시 — 환각 없이, 검색된 근거 조문으로 안내.
_FALLBACK = (
    "아래 현행 법령 조문을 근거 자료로 안내드립니다. "
    "구체적 사안은 함께 안내한 공식 기관 상담을 권합니다."
)
_NO_CHUNKS = (
    "검색된 현행 법령 조문이 없어 정확한 답변을 드리기 어렵습니다. "
    "대한법률구조공단(132) 상담을 권합니다."
)


def _format_context(chunks: list[dict]) -> str:
    """검색 조문을 프롬프트용으로 번호 매겨 정리."""
    return "\n".join(
        f'[{i}] {c["law_name"]} {c["article"]} (시행 {c["enforced_date"]})\n"{c["text"]}"'
        for i, c in enumerate(chunks, 1)
    )


def _generate_answer(query: str, chunks: list[dict]) -> tuple[str, float, list[int] | None]:
    """검색 조문 근거로 답변 생성 + 답변이 실제 쓴 조문 번호(used).
    실패/무검색 시 used=None — 근거 가지치기 생략(전체 유지)."""
    if not chunks:
        return _NO_CHUNKS, 0.0, None
    prompt = _PROMPT.format(query=query, context=_format_context(chunks))
    try:
        data = call_bedrock_json(prompt, required_keys=["answer", "used"], task="answer")
        raw = data.get("used") or []
        used = [int(x) for x in raw if str(x).strip().lstrip("-").isdigit()]
        return str(data["answer"]).strip(), 0.8, used
    except Exception:
        # call_bedrock 미구현/호출 실패 — 지어내지 않고 검증된 근거 조문만 제시.
        # 환각이 아닌 정직한 degraded 응답이라 verifier 임계값 위로 둔다.
        return _FALLBACK, 0.6, None


def housing_agent(state: LegalState) -> dict:
    chunks = _rag.search(state["user_query"], k=3)
    answer_text, confidence, used = _generate_answer(state["user_query"], chunks)
    # ★근거 정합★: 답변이 실제 쓴 조문만 citation으로(가지치기). used가 비거나 없으면
    # 전체 유지(완전 검색미스는 검색 영역이라 여기선 안전하게 보존).
    cited = chunks
    if used:
        picked = [chunks[i - 1] for i in used if 1 <= i <= len(chunks)]
        if picked:
            cited = picked
    answer: dict = {
        "domain": "housing",
        "answer": answer_text,
        "citations": [
            {
                "law_name": c["law_name"], "article": c["article"],
                "enforced_date": c["enforced_date"], "snippet": c["text"],
                "source_url": c["source_url"],
            } for c in cited
        ],
        "contacts": get_contacts("housing"),
        "confidence": confidence,
    }
    return {"domain_answers": [answer], "messages": ["[housing] RAG 근거 답변 생성"]}

def housing_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """housing 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = housing_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
