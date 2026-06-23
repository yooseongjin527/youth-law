"""멀티도메인 서브쿼리 분해(①) + confidence 스코핑(②) 계약 테스트.

배경(트러블슈팅): 3-way 혼합 질문에서 fan-out된 전문가가 모두 '질문 전체'로
검색·답변하면, 비주력 분야(finance)는 cross-domain 노이즈에 검색·confidence가
희석돼 verifier 0.5 컷에서 조용히 탈락한다. → Supervisor가 분야별 서브질의로
분해해 각 전문가에게 자기 조각만 넘긴다(노이즈 제거).

이 테스트들은 Bedrock 네트워크 없이 결정적으로 돈다(safe_search/call_bedrock_json mock).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common.llm as llm  # noqa: E402
from agents.consumer import consumer_agent  # noqa: E402
from agents.finance import finance_agent  # noqa: E402
from agents.housing import housing_agent  # noqa: E402
from agents.labor import labor_agent  # noqa: E402
from agents.supervisor import supervisor_agent  # noqa: E402
from common.base_agent_answer import domain_query  # noqa: E402


def _state(q="테스트", domain_queries=None):
    return {
        "user_query": q, "target_domains": [], "in_scope": True,
        "domain_queries": domain_queries,
        "domain_answers": [], "verified_answers": None,
        "verification_report": None, "answer_blocks": None, "messages": [],
    }


_EXPERTS = {
    "labor": labor_agent, "housing": housing_agent,
    "consumer": consumer_agent, "finance": finance_agent,
}


# ── ① domain_query 헬퍼 ────────────────────────────────────────────
def test_domain_query_returns_subquery_when_present():
    st = _state("월급도 보증금도 못 받음", {"finance": "사채 빚 독촉 대응"})
    assert domain_query(st, "finance") == "사채 빚 독촉 대응"


def test_domain_query_falls_back_to_full_query():
    st = _state("월급 못 받음", None)
    assert domain_query(st, "finance") == "월급 못 받음"


def test_domain_query_falls_back_when_domain_missing():
    # 분해 맵에 해당 분야가 없으면 전체 질문 사용(부분 분해 안전)
    st = _state("월급 못 받음", {"labor": "월급 못 받음"})
    assert domain_query(st, "finance") == "월급 못 받음"


# ── ① 전문가가 서브쿼리로 검색 ───────────────────────────────────────
def _capture_search(monkeypatch, domain):
    """해당 분야 에이전트의 safe_search를 가로채 전달된 질의를 기록(빈 결과 반환→무네트워크)."""
    captured = {}

    def fake(rag, query, k=3):
        captured["q"] = query
        return []  # 빈 검색결과 → no-chunks 경로 → LLM 호출 없음(결정적)

    monkeypatch.setattr(f"agents.{domain}.safe_search", fake)
    return captured


def test_each_expert_searches_with_its_subquery(monkeypatch):
    for domain, agent in _EXPERTS.items():
        cap = _capture_search(monkeypatch, domain)
        sub = f"{domain} 전용 서브질의"
        agent(_state("회사 망해서 월급·사채빚·보증금 다 문제", {domain: sub}))
        assert cap["q"] == sub, f"{domain} expert가 서브쿼리로 검색하지 않음"


def test_each_expert_uses_full_query_without_decomposition(monkeypatch):
    for domain, agent in _EXPERTS.items():
        cap = _capture_search(monkeypatch, domain)
        agent(_state("월급 못 받았어요", None))
        assert cap["q"] == "월급 못 받았어요", f"{domain} 하위호환(전체질의) 깨짐"


# ── ① Supervisor 분해 ──────────────────────────────────────────────
def _patch_llm(monkeypatch, subq_handler):
    """call_bedrock_json mock: 분류(domains)와 분해(subqueries)를 분기 처리."""
    def fake(*args, required_keys=None, **kwargs):
        keys = set(required_keys or [])
        if "subqueries" in keys:
            return subq_handler()
        if "domains" in keys:
            return {"domains": ["labor", "housing"], "confidence": 0.9}
        return {}
    monkeypatch.setattr(llm, "call_bedrock_json", fake)


def test_supervisor_decomposes_multidomain(monkeypatch):
    _patch_llm(monkeypatch, lambda: {"subqueries": {
        "labor": "월급을 못 받았는데 어떻게 하나요?",
        "housing": "기숙사 보증금을 못 받았는데 어떻게 돌려받나요?",
    }})
    out = supervisor_agent(_state("월급도 못 받고 기숙사 보증금도 못 받았어요"))
    assert out["target_domains"] == ["labor", "housing"]
    assert out["domain_queries"] == {
        "labor": "월급을 못 받았는데 어떻게 하나요?",
        "housing": "기숙사 보증금을 못 받았는데 어떻게 돌려받나요?",
    }


def test_supervisor_single_domain_skips_decomposition(monkeypatch):
    def fake(*args, required_keys=None, **kwargs):
        keys = set(required_keys or [])
        if "subqueries" in keys:
            raise AssertionError("단일 분야는 분해 LLM을 호출하면 안 됨(비용/무의미)")
        return {"domains": ["labor"], "confidence": 0.95}
    monkeypatch.setattr(llm, "call_bedrock_json", fake)
    out = supervisor_agent(_state("월급을 못 받았어요"))
    assert out["target_domains"] == ["labor"]
    assert out["domain_queries"] == {}


def test_supervisor_decompose_failure_is_graceful(monkeypatch):
    def _boom():
        raise RuntimeError("LLM down")
    _patch_llm(monkeypatch, _boom)
    out = supervisor_agent(_state("월급도 보증금도 못 받았어요"))
    # 분류는 유지, 분해만 폴백(빈 맵) → 전문가들이 전체 질의로 동작(현행)
    assert out["target_domains"] == ["labor", "housing"]
    assert out["in_scope"] is True
    assert out["domain_queries"] == {}


# ── ② confidence 스코핑 프롬프트 ─────────────────────────────────────
def test_finance_prompt_scopes_confidence_to_domain():
    from agents.finance import _ANSWER_PROMPT
    # 타 분야가 섞여도 자기 분야 기준으로만 confidence를 매기라는 지시가 있어야
    assert "무시" in _ANSWER_PROMPT
    assert "confidence" in _ANSWER_PROMPT


def test_consumer_prompt_scopes_confidence_to_domain():
    from agents.consumer import _ANSWER_PROMPT
    assert "무시" in _ANSWER_PROMPT
