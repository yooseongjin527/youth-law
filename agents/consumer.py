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
- ★ 법 라우팅 ★: consumer는 전자상거래·방문판매(계속거래)·할부거래 3법을 다룬다.
  세 법은 청약철회·계약해지 표현이 거의 동일해 한 통에 섞어 검색하면 서로 희석된다
  (측정: hit@3 0.68→0.46). 그래서 질문 의도로 법을 1개 골라 그 법만 검색한다
  (_route_law): "할부"→할부거래법, "구독/정기/멤버십/계속거래"→방문판매법, 그 외→전자상거래법.
  덕분에 흔한 전자상거래 질문 정확도는 단일법 수준(0.68)으로 유지하면서 구독·할부도 커버.

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
    domain_query,
    domain_result,
    extractive_answer,
    safe_search,
)
from common.drafter import make_draft
from common.rag import DomainRAG, RetrievedChunk
from state import LegalState

_rag = DomainRAG(domain="consumer", corpus_path="data/consumer")

# ── 분야 내 법 라우팅 ──────────────────────────────────────────
# 세 법은 청약철회·계약해지 언어가 거의 같아 섞어 검색하면 희석된다 → 의도로 1개 선택.
_LAW_ECOMMERCE = "전자상거래 등에서의 소비자보호에 관한 법률"  # 기본(통신판매 청약철회·환불)
_LAW_CONTINUOUS = "방문판매 등에 관한 법률"                    # 계속거래(구독) 해지
_LAW_INSTALLMENT = "할부거래에 관한 법률"                      # 할부 청약철회·항변권
# 트리거는 각 법 고유어로. "자동결제"는 다크패턴(전자상거래법)과 겹쳐 의도적으로 제외.
_INSTALLMENT_KW = ("할부", "상조", "선불식", "항변")           # 할부거래법
_DOOR_KW = (                                                  # 방문판매법
    "방문판매", "전화권유", "다단계", "후원", "구독",
    "정기결제", "정기구독", "정기배송", "멤버십", "계속거래", "회원권",
)


def _route_law(query: str) -> str:
    """질문 의도로 검색할 법 1개를 고른다(기본: 전자상거래법). 할부거래법 우선 검사
    ('선불식 할부'처럼 두 신호가 겹치면 할부거래법이 맞음)."""
    if any(k in query for k in _INSTALLMENT_KW):
        return _LAW_INSTALLMENT
    if any(k in query for k in _DOOR_KW):
        return _LAW_CONTINUOUS
    return _LAW_ECOMMERCE

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
    "- ★질문에 타 분야(노동·주택·금융) 내용이 섞여 있어도 그 부분은 무시하고, "
    "소비자 쟁점만 기준으로 답·confidence를 정하세요(섞였다는 이유로 confidence를 낮추지 말 것).\n"
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
    query = domain_query(state, "consumer")  # 멀티도메인 분해 시 consumer 조각(없으면 전체질문)
    # 의도로 법 1개 선택 → 그 법만 검색(희석 방지). 기본은 전자상거래법.
    chunks = safe_search(_rag, query, k=3, law=_route_law(query))

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
