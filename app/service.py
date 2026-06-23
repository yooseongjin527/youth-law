"""서비스 레이어 — FastAPI와 Streamlit이 공유하는 비즈니스 로직.

그래프 호출을 한 곳으로 모은다 → 두 UI가 따로 그래프를 다루다 어긋나는 것 방지.
(초기 state 모양이 바뀌면 여기 한 곳만 고치면 됨)
"""
from functools import lru_cache
from typing import Optional

from agents.consumer import consumer_draft
from agents.finance import finance_draft
from agents.housing import housing_draft
from agents.labor import labor_draft
from app.contextualize import contextualize
from app.session_store import append_turn, clear, get_history
from common.logging_store import save_consultation
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
        "domain_queries": None,
        "domain_answers": [], "verified_answers": None,
        "verification_report": None, "answer_blocks": None, "messages": [],
    }


def consult(question: str, session_id: Optional[str] = None) -> dict:
    """질문 → 그래프 실행 → UI가 그릴 수 있는 형태로 반환.

    session_id가 있으면 멀티턴: 직전 대화로 후속 질문을 독립형으로 재작성한 뒤
    기존 그래프에 단발로 투입한다(그래프·State 무변경). session_id 없으면 종전과 동일.
    """
    history = get_history(session_id)
    effective_q = contextualize(history, question) if history else question
    result = get_graph().invoke(init_state(effective_q))
    payload = {
        "question": question,  # 사용자가 입력한 원문(화면 표시용)
        # 재작성이 실제로 일어났을 때만 채움 → UI가 "이렇게 이해했어요" 안내 가능
        "rewritten_question": effective_q if effective_q != question else None,
        "domains": [
            {"id": d, "name": DOMAIN_KR.get(d, d)} for d in result["target_domains"]
        ],
        "in_scope": result["in_scope"],
        "final_answer": result["final_answer"],
        "answer_blocks": result.get("answer_blocks") or [],
        "verification_report": result.get("verification_report") or [],
    }
    if session_id:
        append_turn(
            session_id, question, payload["final_answer"] or "", result["target_domains"]
        )
    save_consultation(payload)  # RDS 로깅(꺼져 있으면 no-op, 실패해도 상담 안 죽음)
    return payload


def make_draft(question: str, domain: str) -> dict:
    """분야 문서 초안 생성 (상담 후 '초안 생성' 버튼)."""
    if domain not in _DRAFTERS:
        raise ValueError(f"지원하지 않는 분야: {domain}")
    return _DRAFTERS[domain](init_state(question))


def clear_session(session_id: Optional[str]) -> dict:
    """멀티턴 메모리 세션을 명시적으로 비운다."""
    clear(session_id)
    return {"cleared": bool(session_id)}
