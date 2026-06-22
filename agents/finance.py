"""금융·채무 분야 전문가 — 담당 D(mason) 전용.
labor.py와 동일 패턴 — 자기 분야 코퍼스(컬렉션)만 다름.
다루는 범위: 채무조정·개인회생(채무자회생법), 보이스피싱 피해(통신사기피해환급법),
            불법추심·사금융(채권추심법·대부업법).
※ 투자 조언 아님. '관련 법령 안내'로 엄격히 프레이밍.

동작 모드 (어느 모드든 검색된 조문 밖 내용은 답변에 들어갈 수 없다 — 환각 방지):
  1) Bedrock 모드: common/llm.py 완성 시 자동 활성. 검색 조문만 근거로 생성하고
     JSON 형식(answer/confidence)을 강제(call_bedrock_json 하네스).
  2) 폴백(추출) 모드: llm.py 미구현·호출 실패 시. 검색 조문을 '그대로' 안내문으로
     조립한다 — 생성 자체가 없어 환각 0, 그래프·CI가 항상 동작.

★ 검색기 ★: common/rag_hybrid 의 DomainRAG(BM25+임베딩 하이브리드, 분야별 α·쿼리확장).
  common/rag.py 와 동일 인터페이스라 drop-in(labor.py와 같은 패턴). 평어→법률용어 쿼리확장은
  common/synonyms/finance.jsonl + rag_hybrid.search 내부에서 수행한다 — finance.py 자체 확장은
  제거(이중 확장 방지). (synonyms/finance.jsonl 기준 hit@3 0.52→1.0)

────────────────────────────────────────────────────────
TODO 우선순위 (담당 D)
  [D/Day2] ① finance 컬렉션 인덱싱 검증 + evals/finance.jsonl로 hit@k 측정 — 완료(0.32)
  [D/Day3] ② llm.py 완성 후 _ANSWER_PROMPT 튜닝 (요약/상세 분리, 분야 용어)
  [D/Day4] ③ 답변-근거 정합성 체크 (verifier 2단계와 연동)
  [D/Day4] ④ 초안: 채무조정(개인회생) 신청 안내 doc_type 추가
────────────────────────────────────────────────────────
"""
from common.base_agent_answer import (
    build_domain_answer,
    domain_result,
    extractive_answer,
    safe_search,
)
from common.drafter import make_draft
from common.rag_hybrid import DomainRAG, RetrievedChunk
from state import LegalState

_rag = DomainRAG(domain="finance", corpus_path="data/finance")

# 폴백(추출) 모드 confidence — 조문 원문을 그대로 안내하므로 근거성은 보장되나
# (verifier 통과 기준 0.5 이상), 생성 모드보다 보수적으로 둔다.
# 검색 '적합도' 품질은 여기가 아니라 scripts/evaluate.py hit@k로 측정한다.
_FALLBACK_CONFIDENCE = 0.7

# ★ 환각 방지 프롬프트 — 검색 조문 안에서만 답하도록 3중 강제 ★
# (지시는 '부탁'일 뿐이므로, 최종 방어는 verifier가 한다)
# ★ 답변 품질 패턴 (sim 0.84→0.88 검증) — '조문 정확 용어 + 구체 수치/기한 그대로 + 군더더기 제거' ★
# 분야 무관 구조라 타 분야 프롬프트·planner 종합에도 그대로 이식 가능.
_ANSWER_PROMPT = (
    "당신은 청년에게 금융·채무 관련 '현행 법령 정보'를 안내하는 도우미입니다.\n"
    "아래 [검색된 조문]에 있는 내용만 근거로 답하세요.\n"
    "- 첫 문장: 핵심 법적 결론을 조문의 정확한 용어(제도·권리·의무 명칭)를 그대로 써서 제시.\n"
    "- 다음: 근거 조문의 요건·효과를 구체적으로 — 기한·대상·절차·금액이 "
    "조문에 있으면 그 표현/수치 그대로.\n"
    "- 마지막: 청년이 이해할 쉬운 말로 한두 문장 풀이.\n"
    "- 조문에 없는 내용·수치·기관명 지어내기 금지. 조문만으로 부족하면 "
    "그 사실을 밝히고 confidence를 0.5 미만으로.\n"
    "- 군더더기·일반론·과한 면책 문구는 빼고 핵심만 3~5문장. 투자 조언이 아니라 법령 안내이며,\n"
    "  단정적 자문 표현은 피하되 법령 용어는 정확히 쓰세요.\n\n"
    "[검색된 조문]\n{context}\n\n"
    "[질문]\n{query}\n\n"
    'JSON으로만 답하세요: {{"answer": "...", "confidence": 0.0~1.0}}'
)


def _format_context(chunks: list[RetrievedChunk]) -> str:
    """검색 청크를 프롬프트용 컨텍스트 텍스트로."""
    return "\n".join(
        f"({i}) {c['law_name']} {c['article']} (시행 {c['enforced_date']}): {c['text']}"
        for i, c in enumerate(chunks, start=1)
    )


def _llm_answer(query: str, chunks: list[RetrievedChunk]) -> tuple[str, float] | None:
    """Bedrock 답변 시도. llm.py 미구현이거나 실패하면 None (폴백 모드로)."""
    try:
        from common.llm import call_bedrock_json

        data = call_bedrock_json(
            _ANSWER_PROMPT.format(context=_format_context(chunks), query=query),
            required_keys=["answer", "confidence"],
            task="answer",
        )
        conf = max(0.0, min(1.0, float(data["confidence"])))
        return str(data["answer"]), conf
    except Exception:
        return None  # NotImplementedError(Day3 전)·재시도 소진 등 → 추출 모드 폴백


def finance_agent(state: LegalState) -> dict:
    query = state["user_query"]
    # 검색기는 common/rag_hybrid(BM25+임베딩 하이브리드). 평어→법률용어 쿼리확장은
    # rag_hybrid.search 내부(synonyms/finance.jsonl)에서 수행 — 여기선 원질의만 넘긴다
    # (이중 확장 방지). 확장은 검색 입력에만 영향, 답변·인용은 원문 기준.
    chunks = safe_search(_rag, query, k=3)

    if not chunks:
        # 검색 결과 없음 → 인용 0건 답변. verifier가 탈락시키고 planner가 정직 거절.
        answer_text, confidence, mode = "관련 조문을 찾지 못했습니다.", 0.0, "no-hit"
    else:
        llm = _llm_answer(query, chunks)
        if llm is not None:
            answer_text, confidence = llm
            mode = "bedrock"
        else:
            answer_text, confidence = extractive_answer(chunks), _FALLBACK_CONFIDENCE
            mode = "extractive"

    answer = build_domain_answer(
        domain="finance",
        answer=answer_text,
        chunks=chunks,
        confidence=confidence,
    )
    rag_mode = "실모드" if _rag.is_real else "stub"
    return domain_result("finance", answer, f"실행됨 (RAG={rag_mode}, 답변={mode})")


def finance_draft(state: LegalState, doc_type: str | None = None) -> dict:
    """finance 분야 문서 초안 생성. 답변을 먼저 만든 뒤 그 근거로 초안 작성.
    사용자가 '초안 생성'을 요청하면 호출(그래프 흐름과 별개의 진입점)."""
    answer = finance_agent(state)["domain_answers"][0]
    return make_draft(answer, doc_type)
