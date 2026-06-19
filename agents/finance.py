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
from common.rag import DomainRAG, RetrievedChunk
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

# ── 쿼리 확장 (평어 → 법률 용어) — finance 전용 ────────────────────────
# 청년의 평어 질문과 법조문 용어 사이 의미 격차를 메워 검색 적중률(hit@k)을 올린다.
# (예: "돈 돌려받다" 질문엔 정답 조문 용어 "피해환급금/지급정지"가 한 글자도 없어
#  임베딩이 정답 조문을 top-k 밖으로 밀어낸다.)
# ★ 검색(임베딩) 입력에만 덧붙인다 — 답변 프롬프트·인용·연락처엔 영향 없음(환각과 무관).
# ★ 공용 rag.py를 건드리지 않으려고 일부러 finance.py 안에 둔다: 전역 동의어 사전은
#   타 분야(노동/주거/소비자) 어휘를 오염시킬 수 있어 분야 한정이 안전하다.
# 트리거(평어 부분문자열) → 덧붙일 법률 용어. evaluate.py per-question 결과로 계속 튜닝.
_FINANCE_SYNONYMS: dict[str, list[str]] = {
    # 정의(definition) 질문: "~이/가 뭔가요·무엇·뜻" → '용어의 정의' 조문으로 (예: 제579조).
    # 절차 용어(변제계획안·절차개시 등)가 BM25를 절차 조문으로 끌어가 정의 조문을 묻어버리는 것을
    # 상쇄한다. "용어/정의"는 정의 조문에만 나오는 고-IDF 토큰이라 BM25 변별력이 크다. (Q7 근거)
    "뭔가요": ["용어의 정의"],
    "뭐예요": ["용어의 정의"],
    "뭐야": ["용어의 정의"],
    "무엇": ["용어의 정의"],
    "뜻이": ["용어의 정의"],
    # 보이스피싱·전기통신금융사기 (통신사기피해환급법)
    # ★ "보이스피싱"은 방향이 갈린다(피해자 송금 / 명의인 이의제기 / 전화번호 정지).
    #   피해자용 '피해구제 신청·지급정지'를 무조건 붙이면 명의인(제7조)·전화번호(제13조의3)
    #   질문에 노이즈가 돼 제3·4조로 끌려간다 → 중립 우산용어만 두고,
    #   피해자 용어는 방향이 분명한 송금 키워드(보냈/송금)로 분리한다. (evaluate.py Q4/Q5 근거)
    "보이스피싱": ["전기통신금융사기"],
    # 피해자(돈을 보낸 쪽) 방향 — 피해구제 신청(제3조)·지급정지(제4조)
    "보냈": ["피해구제 신청", "지급정지"],
    "송금": ["피해구제 신청", "지급정지"],
    "사기": ["전기통신금융사기", "지급정지", "사기이용계좌"],
    "돌려받": ["피해환급금", "채권소멸절차", "지급정지"],
    "통장": ["사기이용계좌", "명의인", "전자금융거래 제한"],
    "전화번호": ["전화번호 이용중지"],
    "억울": ["지급정지 이의제기"],
    # 개인회생·파산·면책 (채무자회생법)
    "개인회생": ["개인회생절차 개시", "변제계획안"],
    "빚": ["채무", "변제"],
    "파산": ["파산선고", "면책"],
    "면책": ["면책 신청", "면책 기각사유"],
    "계획서": ["변제계획안 제출"],
    # 불법추심 (채권추심법)
    "협박": ["폭행·협박 등 금지", "불공정한 행위"],
    "찾아": ["야간 방문", "반복적인 방문"],
    "변호사": ["채무자 대리인", "대리인 연락 금지"],
    "가족": ["관계인 연락 금지", "개인정보 누설"],
    "동료": ["관계인 연락 금지"],
    "독촉": ["복수 채권추심 위임 금지", "반복 추심"],
    "서류": ["채무확인서 교부"],
    "비용": ["채권추심 비용", "부당한 비용 청구"],
    "추심": ["채권추심", "불공정한 행위"],
    # 사금융 (대부업법)
    "이자": ["이자율 제한"],
    "능력": ["과잉 대부 금지"],
    "사채": ["미등록 대부업자", "불법사금융"],
    "무등록": ["미등록 대부업자", "대부계약 효력"],
    "광고": ["허위·과장 광고 금지"],
    "수수료": ["부대비용"],
}
_MAX_EXPANSION_TERMS = 6  # 너무 많이 붙이면 임베딩이 희석돼 역효과 → 상한


def _expand_query(query: str) -> str:
    """평어 질의에 매칭되는 법률 용어를 덧붙여 검색 적중률(hit@k)을 높인다.
    트리거 키워드가 질의에 실제로 있을 때만 추가(무관 용어로 인한 희석 방지)."""
    extra: list[str] = []
    for trigger, terms in _FINANCE_SYNONYMS.items():
        if trigger in query:
            for t in terms:
                if t not in extra:
                    extra.append(t)
    if not extra:
        return query
    return query + " " + " ".join(extra[:_MAX_EXPANSION_TERMS])


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
    # 평어 질의를 법률 용어로 확장해 검색(임베딩) 입력만 보강 — 답변·인용은 원문 기준
    chunks = safe_search(_rag, _expand_query(query), k=3)

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
