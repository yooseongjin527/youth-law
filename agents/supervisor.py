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
from state import LegalState

# stub용 키워드 분류기. 실제로는 Bedrock few-shot 분류로 교체.
_KEYWORDS = {
    "labor": ["월급", "임금", "해고", "알바", "근로", "퇴직", "수당", "야근"],
    "housing": ["보증금", "전세", "월세", "임대", "집주인", "계약갱신", "확정일자"],
    "consumer": ["환불", "구매", "결제", "청약철회", "쇼핑", "배송", "중고거래", "교환"],
    "finance": ["대출", "추심", "채무", "빚", "이자", "독촉", "연체", "회생",
                "파산", "보이스피싱", "사기", "지급정지", "환급", "사금융"],
}


def supervisor_agent(state: LegalState) -> dict:
    query = state["user_query"]
    matched = [d for d, kws in _KEYWORDS.items() if any(k in query for k in kws)]

    if not matched:
        return {
            "target_domains": [],
            "in_scope": False,
            "messages": ["[supervisor] 범위 밖 — out_of_scope"],
        }
    return {
        "target_domains": matched,
        "in_scope": True,
        "messages": [f"[supervisor] 자동 분류: {matched}"],
    }


def route(state: LegalState) -> list[str]:
    """add_conditional_edges용. 태울 전문가 노드명 리스트 반환.
    범위 밖이면 planner 직행(거절)."""
    if not state["in_scope"]:
        return ["planner"]
    return state["target_domains"]
