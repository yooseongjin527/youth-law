"""평가(eval) 스모크 — eval 머신러리가 '동작하는지'만 확인(빠름·결정적).

★ 왜 계약 테스트(test_contracts.py)에서 분리했나 ★
hit@k·grounding rate '실측'은 라이브 LLM + 전체 평가셋이 필요해 비싸고(분 단위)
비결정적이다. 그건 계약(I/O 구조) 검증이 아니라 '품질 측정'이며, 전용 도구
scripts/evaluate.py로 담당자가 온디맨드로 돌린다(3축 스코어카드·이력 누적,
smoke/benchmark split). CI 게이트에 라이브 평가를 넣으면 평가셋·분야가 늘수록
CI 시간이 선형으로 폭발한다(예: 4분야 × 수십문항 × LLM 2회 = 수십 분).

→ 여기서는 Bedrock을 mock해 "평가 함수가 깨지지 않고 유효한 형태를 반환하는지"만
   본다(분야 수·평가셋 크기와 무관하게 초 단위). 실측 숫자는 scripts/evaluate.py의 몫.
   (CLAUDE.md 원칙: 계약 = 구조 검증 / 평가 = evaluate.py 온디맨드)

검색축(eval_retrieval)은 Bedrock을 안 쓰므로 mock 없이도 가볍다(임베딩/스텁).
환각축(eval_grounding)만 에이전트+verifier의 LLM 호출을 mock으로 대체한다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state import DOMAINS  # noqa: E402


@pytest.fixture
def mock_bedrock(monkeypatch):
    """모든 분야 에이전트·verifier의 Bedrock 호출을 형태 유효한 스텁으로 대체(무네트워크).

    바인딩 위치가 제각각이라(모듈상단 import vs 함수내 lazy import) 소스 한 곳만
    패치하면 모듈상단 import는 안 잡힌다 → 알려진 바인딩 지점을 모두 패치한다.
    """
    def fake_json(prompt, required_keys, task="answer", **kw):
        keys = set(required_keys)
        if "ungrounded" in keys:        # verifier 판정 → 전부 근거 있음
            return {"ungrounded": []}
        if "used" in keys:              # housing 답변 → 인용 가지치기 없음
            return {"answer": "근거 조문 기반 모의 답변입니다.", "used": []}
        if "domains" in keys:           # supervisor 분류(eval 경로엔 없지만 안전)
            return {"domains": [], "confidence": 0.9}
        return {"answer": "근거 조문 기반 모의 답변입니다.", "confidence": 0.8}

    def fake_text(prompt, task="answer", **kw):  # labor: run_domain_agent → call_bedrock
        return "근거 조문 기반 모의 답변입니다."

    import agents.housing
    import agents.verifier
    import common.base_agent_answer
    import common.llm

    # call_bedrock_json: lazy importer(consumer/finance)는 common.llm 패치로,
    # 모듈상단 importer(housing/verifier)는 각 모듈을 직접 패치.
    for mod in (common.llm, agents.housing, agents.verifier):
        if hasattr(mod, "call_bedrock_json"):
            monkeypatch.setattr(mod, "call_bedrock_json", fake_json)
    # call_bedrock(평문): labor 경로(base_agent_answer 모듈상단 import).
    for mod in (common.llm, common.base_agent_answer):
        if hasattr(mod, "call_bedrock"):
            monkeypatch.setattr(mod, "call_bedrock", fake_text)


@pytest.mark.parametrize("domain", DOMAINS)
def test_eval_retrieval_smoke(domain):
    """축① 검색: hit@k 측정이 평가셋으로 실행됨(Bedrock 무관 — mock 불필요)."""
    sys.path.insert(0, ".")
    from scripts.evaluate import eval_retrieval

    r = eval_retrieval(domain)
    assert r["n"] >= 3                  # 평가셋 존재
    assert r["hit_at_k"] is not None    # 측정 자체가 동작


@pytest.mark.parametrize("domain", DOMAINS)
def test_eval_grounding_smoke(domain, mock_bedrock):
    """축③ 환각: grounding rate 측정이 실행됨(Bedrock mock — 라이브·비결정성 제거).

    분야·평가셋 크기와 무관하게 무네트워크라 항상 초 단위 → CI 폭발 방지.
    """
    sys.path.insert(0, ".")
    from scripts.evaluate import eval_grounding

    r = eval_grounding(domain)
    assert r["n"] >= 3
    assert 0.0 <= r["grounding_rate"] <= 1.0
