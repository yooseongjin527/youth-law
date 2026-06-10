"""서비스 레이어 — FastAPI와 Streamlit이 공유하는 비즈니스 로직.

그래프 호출을 한 곳으로 모은다 → 두 UI가 따로 그래프를 다루다 어긋나는 것 방지.
(초기 state 모양이 바뀌면 여기 한 곳만 고치면 됨)
"""
from functools import lru_cache

from agents.consumer import consumer_draft
from agents.finance import finance_draft
from agents.housing import housing_draft
from agents.labor import labor_draft
from graph import build_graph
from state import DOMAIN_KR

_DRAFTERS = {
    "labor": labor_draft, "housing": housing_draft,
    "consumer": consumer_draft, "finance": finance_draft,
}


@lru_cache(maxsize=1)
def get_graph():
    """컴파일된 그래프 싱글톤 (요청마다 재컴파일 방지)."""
    return build_graph()


def init_state(question: str) -> dict:
    return {
        "user_query": question, "target_domains": [], "in_scope": True,
        "domain_answers": [], "verified_answers": None,
        "verification_report": None, "answer_blocks": None, "messages": [],
    }


def consult(question: str) -> dict:
    """질문 → 그래프 실행 → UI가 그릴 수 있는 형태로 반환."""
    result = get_graph().invoke(init_state(question))
    return {
        "question": question,
        "domains": [
            {"id": d, "name": DOMAIN_KR.get(d, d)} for d in result["target_domains"]
        ],
        "in_scope": result["in_scope"],
        "final_answer": result["final_answer"],
        "answer_blocks": result.get("answer_blocks") or [],
        "verification_report": result.get("verification_report") or [],
    }


def make_draft(question: str, domain: str) -> dict:
    """분야 문서 초안 생성 (상담 후 '초안 생성' 버튼)."""
    if domain not in _DRAFTERS:
        raise ValueError(f"지원하지 않는 분야: {domain}")
    return _DRAFTERS[domain](init_state(question))
