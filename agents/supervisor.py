"""Supervisor — 공용 파일 ⚠️ (변경은 PR + 전원 합의).
질문을 읽고 4분야 중 어디에 해당하는지 자동 판별(사용자는 분야 선택 안 함).
- 1개 분야 → 전문가 1명
- 2개+ 분야 → 여러 전문가 동시(fan-out)
- 0개      → out_of_scope (정직하게 거절)

────────────────────────────────────────────────────────
TODO 우선순위 (공용 — 자기 분야 끝낸 사람이 가져가세요)
  [공용/Day3] ① 키워드 분류를 Bedrock few-shot 분류로 교체 (정확도↑)
  [공용/Day4] ② 모호한 질문 처리 (어느 분야인지 애매할 때 confidence 기반)
  [공용/Day5] ③ 분류 정확도 평가셋 만들기 (발표용 지표)
────────────────────────────────────────────────────────
"""
from state import DOMAINS, LegalState

# 키워드 분류기 — Bedrock 실패/오프라인/CI용 폴백(그래프·테스트가 항상 동작).
_KEYWORDS = {
    "labor": ["월급", "임금", "해고", "알바", "근로", "퇴직", "수당", "야근"],
    "housing": ["보증금", "전세", "월세", "임대", "집주인", "계약갱신", "확정일자"],
    "consumer": ["환불", "구매", "결제", "청약철회", "쇼핑", "배송", "중고거래", "교환"],
    "finance": ["대출", "추심", "채무", "빚", "이자", "독촉", "연체", "회생",
                "파산", "보이스피싱", "사기", "지급정지", "환급", "사금융"],
}

# ★ Bedrock few-shot 분류 프롬프트 — 구조화 JSON 강제(prose 방지) ★
# 분야는 복수 가능(fan-out), 4분야 밖이면 빈 배열(out_of_scope).
_CLASSIFY_PROMPT = (
    "당신은 청년 생활법률 상담의 '분야 분류기'입니다. 질문이 아래 4개 분야 중\n"
    "어디에 해당하는지 고르세요(해당 분야 전부, 복수 가능).\n"
    "- labor(노동): 임금/월급/해고/알바/근로시간/퇴직금/수당\n"
    "- housing(주택): 전세/월세/보증금/임대차/집주인/계약갱신\n"
    "- consumer(소비자): 환불/청약철회/온라인구매/결제/배송/중고거래/교환\n"
    "- finance(금융·채무): 대출/이자/빚/추심/독촉/개인회생/파산/보이스피싱/사금융\n\n"
    "규칙:\n"
    "- domains에는 labor/housing/consumer/finance 중에서만.\n"
    "- 4개 분야 어디에도 안 들면 domains는 빈 배열 [] (형사·가족법·행정 등은 범위 밖).\n"
    "- 애매하면 confidence를 낮게.\n\n"
    "예시:\n"
    '질문: "알바비를 안 줘요" → {{"domains":["labor"],"confidence":0.95}}\n'
    '질문: "전세 보증금을 집주인이 안 돌려줘요" → {{"domains":["housing"],"confidence":0.95}}\n'
    '질문: "인터넷으로 산 옷 환불하고 싶어요" → {{"domains":["consumer"],"confidence":0.9}}\n'
    '질문: "사채업자가 매일 협박 전화해요" → {{"domains":["finance"],"confidence":0.95}}\n'
    '질문: "사기당한 돈 때문에 사기범 계좌를 바로 정지시킬 수 있나요" → '
    '{{"domains":["finance"],"confidence":0.9}}\n'
    '질문: "보이스피싱 당했는데 지급정지 신청하고 싶어요" → '
    '{{"domains":["finance"],"confidence":0.95}}\n'
    '질문: "회사 그만두는데 월급도 안 주고 기숙사 보증금도 안 줘요" → '
    '{{"domains":["labor","housing"],"confidence":0.9}}\n'
    '질문: "친구가 때려서 고소하고 싶어요" → {{"domains":[],"confidence":0.9}}\n\n'
    '질문: "{query}"\n'
    'JSON으로만 답하세요: {{"domains": [...], "confidence": 0.0~1.0}}'
)


def _classify_keyword(query: str) -> list[str]:
    """폴백: 키워드 substring 매칭."""
    return [d for d, kws in _KEYWORDS.items() if any(k in query for k in kws)]


def _classify_bedrock(query: str) -> tuple[list[str], float]:
    """Bedrock few-shot 분류. 실패 시 예외 → 호출부에서 키워드 폴백."""
    from common.llm import call_bedrock_json

    data = call_bedrock_json(
        _CLASSIFY_PROMPT.format(query=query),
        required_keys=["domains", "confidence"],
        task="classify",
    )
    # DOMAINS에 있는 값만 채택(환각 분야명 방어), 원래 순서 보존
    domains = [d for d in DOMAINS if d in set(data["domains"])]
    conf = max(0.0, min(1.0, float(data["confidence"])))
    return domains, conf


def supervisor_agent(state: LegalState) -> dict:
    query = state["user_query"]
    try:
        matched, conf = _classify_bedrock(query)
        mode = f"bedrock(conf={conf:.2f})"
    except Exception:
        matched = _classify_keyword(query)  # 오프라인/실패 폴백
        mode = "keyword"

    # 백스톱: Bedrock이 빈 배열(범위 밖)로 판단했어도 분야 키워드가 뚜렷하면 구제한다.
    # 진짜 법률 질문을 false out_of_scope로 거절하는 게 최악(신뢰성↓) — 분류 비결정성 방어.
    if not matched:
        kw = _classify_keyword(query)
        if kw:
            matched = kw
            mode += "→keyword백스톱"

    if not matched:
        return {
            "target_domains": [],
            "in_scope": False,
            "messages": [f"[supervisor] 범위 밖 — out_of_scope ({mode})"],
        }
    return {
        "target_domains": matched,
        "in_scope": True,
        "messages": [f"[supervisor] 자동 분류 {matched} ({mode})"],
    }


def route(state: LegalState) -> list[str]:
    """add_conditional_edges용. 태울 전문가 노드명 리스트 반환.
    범위 밖이면 planner 직행(거절)."""
    if not state["in_scope"]:
        return ["planner"]
    return state["target_domains"]
