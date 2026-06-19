"""소비자보호 분야 전문가 — 담당 C 전용.

공통 베이스(common/base_agent_answer)의 **잎 헬퍼를 그대로 사용**해
불변식(검색 크래시 방지·DomainAnswer 조립·반환 구조·연락처·추출 폴백)을 베이스에
위임한다(housing.py·finance.py와 동일 패턴). → 베이스가 바뀌면 consumer도 자동 추종.
다루는 범위: 전자상거래·통신판매, 청약철회·환불, 온라인거래 분쟁(전자상거래소비자보호법).

★ consumer 고유 정책 (베이스 plain 흐름에 없는 것) ★
- _llm_answer: call_bedrock_json으로 answer + confidence(근거성 점수)를 받는다.
  빈 답변은 None으로 떨궈 추출 폴백으로 보낸다(#4 빈 답 통과 방지).
- 쿼리 확장(synonyms)은 **의도적으로 안 한다** — 홀드아웃 검증 결과 consumer는
  BM25·동의어 이득이 박빙이라 순수 임베딩 단독이 더 단순·합리적(rag_hybrid 미사용).

동작 모드 (어느 모드든 검색된 조문 밖 내용은 답변에 들어갈 수 없다 — 환각 방지):
  1) Bedrock 모드: common/llm.py 완성 시 자동 활성. 검색 조문만 근거로 생성하고
     JSON 형식(answer/confidence)을 강제(call_bedrock_json 하네스).
  2) 폴백(추출) 모드: llm.py 미구현·호출 실패 시. 베이스 extractive_answer로 검색
     조문을 '그대로' 안내문으로 조립한다 — 생성 자체가 없어 환각 0, 그래프·CI가 항상 동작.
  ★ 호출 실패가 그래프를 죽이지 않도록 _llm_answer가 모든 예외를 흡수해 폴백한다. ★

────────────────────────────────────────────────────────
TODO 우선순위 (담당 C)
  [C/Day2] ① consumer 컬렉션 인덱싱 검증 + evals/consumer.jsonl로 hit@k 측정
  [C/Day3] ② llm.py 완성 후 _ANSWER_PROMPT 튜닝 (청약철회·환불 용어, 요약/상세)
  [C/Day4] ③ 답변-근거 정합성 체크 (verifier 2단계와 연동)
  [C/Day4] ④ 초안: 청약철회·환불 요구 내용증명 doc_type 점검
────────────────────────────────────────────────────────
"""
from common.base_agent_answer import (
    build_domain_answer,
    domain_result,
    extractive_answer,
    safe_search,
)
from common.drafter import make_draft
from common.rag import DomainRAG, RetrievedChunk
from state import LegalState

_rag = DomainRAG(domain="consumer", corpus_path="data/consumer")

# 검색 결과 자체가 없을 때 — 환각 없이 정직 거절(낮은 confidence로 verifier 탈락).
_NO_CHUNKS = (
    "검색된 현행 법령 조문이 없어 정확한 답변을 드리기 어렵습니다. "
    "아래 공식 기관 상담을 권합니다."
)

# 폴백(추출) 모드 confidence — 조문 원문을 그대로 안내하므로 근거성은 보장(verifier 0.5↑),
# 생성 모드보다 보수적으로. 검색 적합도 품질은 scripts/evaluate.py hit@k로 측정.
_FALLBACK_CONFIDENCE = 0.7

# ★ 환각 방지 프롬프트 — 검색 조문 안에서만 답하도록 강제 (최종 방어는 verifier) ★
_ANSWER_PROMPT = (
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


def _format_context(chunks: list[RetrievedChunk]) -> str:
    """검색 청크를 프롬프트용 컨텍스트 텍스트로 (consumer 프롬프트 전용 포맷)."""
    return "\n".join(
        f"({i}) {c['law_name']} {c['article']} (시행 {c['enforced_date']}): {c['text']}"
        for i, c in enumerate(chunks, start=1)
    )


def _llm_answer(query: str, chunks: list[RetrievedChunk]) -> tuple[str, float] | None:
    """Bedrock 답변 시도. llm.py 미구현이거나 호출 실패하면 None (폴백 모드로).
    ★ 모든 예외를 흡수 — 한 분야 LLM 실패가 그래프 전체를 죽이지 않게. ★"""
    try:
        from common.llm import call_bedrock_json

        data = call_bedrock_json(
            _ANSWER_PROMPT.format(context=_format_context(chunks), query=query),
            required_keys=["answer", "confidence"],
            task="answer",
        )
        ans = str(data["answer"]).strip()
        if not ans:                       # 빈 답변은 폴백(추출)으로 — 빈 답 통과 방지(#4)
            return None
        conf = max(0.0, min(1.0, float(data["confidence"])))
        return ans, conf
    except Exception:
        return None  # NotImplementedError(Day3 전)·재시도 소진·네트워크 등 → 추출 모드


def consumer_agent(state: LegalState) -> dict:
    query = state["user_query"]
    chunks = safe_search(_rag, query, k=3)  # 베이스: 검색 크래시 방지(빈 리스트 폴백)

    if not chunks:
        # 빈 검색결과 → 인용 0건. verifier가 탈락시키고 planner가 정직 거절.
        answer_text, confidence, mode = _NO_CHUNKS, 0.2, "no-hit"
    else:
        llm = _llm_answer(query, chunks)
        if llm is not None:
            answer_text, confidence = llm
            mode = "bedrock"
        else:
            # Bedrock 실패/미구현 — 베이스 extractive_answer로 검색 조문만 안내(정직 degraded).
            answer_text, confidence = extractive_answer(chunks), _FALLBACK_CONFIDENCE
            mode = "extractive"

    # 베이스 조립 — citation은 검색 청크에서, 연락처·반환 구조는 베이스가 강제(환각 0).
    answer = build_domain_answer(
        domain="consumer", answer=answer_text, chunks=chunks, confidence=confidence,
    )
    rag_mode = "실모드" if getattr(_rag, "is_real", False) else "stub"
    return domain_result("consumer", answer, f"실행됨 (RAG={rag_mode}, 답변={mode})")


def consumer_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """consumer 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = consumer_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
