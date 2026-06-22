"""계약 테스트 — docs/SPEC.md §3 I/O 표를 코드화. CI에서 강제."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.consumer import consumer_agent
from agents.finance import finance_agent
from agents.housing import housing_agent
from agents.labor import labor_agent, labor_draft
from state import DOMAINS


@pytest.fixture(autouse=True)
def _mock_live_llm(monkeypatch):
    """계약 테스트는 구조 검증만 하고 live Bedrock 네트워크를 타지 않는다."""
    import agents.housing as housing
    import agents.verifier as verifier
    import common.base_agent_answer as base_agent
    import common.llm as llm

    def fake_json(*args, required_keys=None, **kwargs):
        keys = set(required_keys or [])
        if "domains" in keys:
            return {"domains": [], "confidence": 0.0}
        if "used" in keys:
            return {"answer": "검색된 조문에 근거한 테스트 답변입니다.", "used": [1]}
        if "ungrounded" in keys:
            return {"ungrounded": []}
        return {"answer": "검색된 조문에 근거한 테스트 답변입니다.", "confidence": 0.8}

    monkeypatch.setattr(
        base_agent,
        "call_bedrock",
        lambda *a, **k: "검색된 조문에 근거한 테스트 답변입니다.",
    )
    monkeypatch.setattr(llm, "call_bedrock_json", fake_json)
    monkeypatch.setattr(housing, "call_bedrock_json", fake_json)
    monkeypatch.setattr(verifier, "call_bedrock_json", fake_json)


def _state(q="테스트"):
    return {
        "user_query": q, "target_domains": [], "in_scope": True,
        "domain_answers": [], "verified_answers": None,
        "verification_report": None, "answer_blocks": None, "messages": [],
    }


def _check(out, domain):
    assert len(out["domain_answers"]) == 1
    a = out["domain_answers"][0]
    assert a["domain"] == domain
    assert isinstance(a["answer"], str)
    # 신뢰성 계약: citation에 시행일·출처 있어야
    for c in a["citations"]:
        assert c["law_name"] and c["article"]
        assert c["enforced_date"]      # 현행법 시행일 필수
        assert c["source_url"]
    # 연락처 계약: 전화·기관 있어야 (환각 방지 데이터)
    for ct in a["contacts"]:
        assert ct["org"] and ct["phone"]


def test_labor():    _check(labor_agent(_state()), "labor")
def test_housing():  _check(housing_agent(_state()), "housing")
def test_consumer(): _check(consumer_agent(_state()), "consumer")
def test_finance():  _check(finance_agent(_state()), "finance")


def test_all_domains_covered():
    covered = {ag(_state())["domain_answers"][0]["domain"]
               for ag in (labor_agent, housing_agent, consumer_agent, finance_agent)}
    assert covered == set(DOMAINS)


def test_contacts_not_empty():
    """모든 분야가 검증된 연락처를 1건 이상 가져야 (행동 연결 차별점)."""
    for ag in (labor_agent, housing_agent, consumer_agent, finance_agent):
        assert len(ag(_state())["domain_answers"][0]["contacts"]) >= 1


def test_graph_single():
    from graph import build_graph
    r = build_graph().invoke(_state("보증금 안 돌려줘요"))
    assert r["final_answer"] and len(r["domain_answers"]) == 1
    # 구조화 블록 + 조문 원문 출력 검증
    assert r["answer_blocks"] and len(r["answer_blocks"]) == 1
    b = r["answer_blocks"][0]
    assert b["citations"] and b["citations"][0]["text"]   # 조문 원문 존재
    assert b["citations"][0]["enforced_date"]             # 시행일 존재


def test_graph_multi():
    from graph import build_graph
    r = build_graph().invoke(_state("월급도 안 주고 보증금도 안 줘요"))
    assert len(r["domain_answers"]) == 2


def test_graph_out_of_scope():
    from graph import build_graph
    r = build_graph().invoke(_state("친구를 고소하고 싶어요"))
    assert len(r["domain_answers"]) == 0
    assert "범위" in r["final_answer"]


def test_document_draft():
    """문서 초안 생성: 종류·본문·근거·안내 + '초안' 경고 검증."""
    state = _state("월급을 안 줘요")
    draft = labor_draft(state)
    assert draft["doc_type"]
    assert draft["body"]
    assert isinstance(draft["based_on"], list)
    # 안전: '초안' 명시 + 검토 권장 경고 필수
    assert "초안" in draft["guide"]
    assert "검토" in draft["guide"]


def _answer(text, conf=0.8):
    return {
        "domain": "labor", "answer": text,
        "citations": [{"law_name": "근로기준법", "article": "제43조",
                       "enforced_date": "2021-11-19",
                       "snippet": "임금은 매월 1회 이상 일정한 날짜를 정하여 지급하여야 한다.",
                       "source_url": "https://law.go.kr"}],
        "contacts": [], "confidence": conf,
    }


def test_verifier_passes_grounded(monkeypatch):
    """검증: 근거된 답변은 그대로 통과 (판정기 mock으로 결정적 테스트)."""
    import agents.verifier as v
    monkeypatch.setattr(v, "call_bedrock_json", lambda *a, **k: {"ungrounded": []})
    state = _state()
    state["domain_answers"] = [_answer("임금은 매월 1회 이상 지급해야 합니다.")]
    r = v.verifier_agent(state)
    assert len(r["verified_answers"]) == 1
    assert r["verification_report"][0]["dropped"] is False
    assert (
        r["verified_answers"][0]["answer"]
        == "임금은 매월 1회 이상 지급해야 합니다."
    )  # 변형 없음


def test_verifier_removes_hallucinated_sentence(monkeypatch):
    """검증(B): 환각 문장만 제거하고 나머지는 정제본으로 통과."""
    import agents.verifier as v
    monkeypatch.setattr(v, "call_bedrock_json", lambda *a, **k: {"ungrounded": [2]})
    state = _state()
    state["domain_answers"] = [
        _answer("임금은 매월 지급해야 합니다.\n사용자는 제999조로 즉시 해고할 수 있습니다.")
    ]
    r = v.verifier_agent(state)
    assert len(r["verified_answers"]) == 1
    ans = r["verified_answers"][0]["answer"]
    assert "제999조" not in ans      # 환각 문장 제거됨
    assert "임금은 매월" in ans        # 근거 문장 보존


def test_verifier_drops_all_hallucinated(monkeypatch):
    """검증(B): 모든 문장이 환각이면 통째 탈락 (정직 거절 경로)."""
    import agents.verifier as v
    monkeypatch.setattr(v, "call_bedrock_json", lambda *a, **k: {"ungrounded": [1, 2]})
    state = _state()
    state["domain_answers"] = [_answer("지어낸 주장 하나. 지어낸 주장 둘.")]
    r = v.verifier_agent(state)
    assert len(r["verified_answers"]) == 0
    assert r["verification_report"][0]["dropped"] is True


def test_verifier_drops_uncited():
    """하네스: 인용 없는 답변은 탈락 — 사용자 도달 경로 차단."""
    from agents.verifier import verifier_agent
    state = _state()
    state["domain_answers"] = [{
        "domain": "labor", "answer": "근거 없는 답변",
        "citations": [], "contacts": [], "confidence": 0.9,
    }]
    r = verifier_agent(state)
    assert len(r["verified_answers"]) == 0
    assert r["verification_report"][0]["dropped"] is True


def test_planner_honest_when_all_dropped():
    """하네스: 전부 검증 탈락 시 지어내지 않고 정직하게 거절."""
    from agents.planner import planner_agent
    state = _state()
    state["domain_answers"] = [{"domain": "labor", "answer": "x",
                                 "citations": [], "contacts": [], "confidence": 0.9}]
    state["verified_answers"] = []   # verifier가 전부 탈락시킨 상황
    r = planner_agent(state)
    assert "어렵습니다" in r["final_answer"] or "132" in r["final_answer"]
    assert r["answer_blocks"] == []


def test_cost_tracker():
    """비용 축: 티어별 기록·집계가 동작."""
    from common.cost import UsageTracker
    t = UsageTracker()
    t.record("classify", 100, 50)   # small 티어
    t.record("answer", 1000, 500)   # main 티어
    r = t.report()
    assert r["calls"] == 2
    assert r["total_cost_usd"] > 0
    assert r["by_task"]["classify"]["calls"] == 1


# 평가(eval) 스모크는 tests/test_eval_smoke.py 로 분리했다.
# 이유: hit@k·grounding rate '실측'은 라이브 LLM·전체 평가셋이 필요해 비싸고(분 단위)
#   비결정적이라, 계약(I/O 구조) 게이트에 두면 평가셋·분야가 늘수록 CI가 폭발한다
#   (eval_grounding은 분야당 문항수 × LLM 2회 호출). → 실측은 scripts/evaluate.py
#   (온디맨드), CI 스모크는 Bedrock mock으로 가볍게(무네트워크·결정적).


def test_diff_laws_incremental():
    """파이프라인: 증분 감지 — 신규/개정만 골라내고 동일은 스킵."""
    from pipeline.detect import diff_laws
    manifest = {"laws": {
        "근로기준법": {"enforced_date": "20211119"},
        "최저임금법": {"enforced_date": "20200526"},
    }}
    current = [
        {"law_name": "근로기준법", "enforced_date": "20211119"},  # 동일 → 스킵
        {"law_name": "최저임금법", "enforced_date": "20260101"},  # 개정 → 갱신
        {"law_name": "주택임대차보호법", "enforced_date": "20230719"},  # 신규
    ]
    changed = diff_laws(manifest, current)
    names = {c["law_name"] for c in changed}
    assert names == {"최저임금법", "주택임대차보호법"}


def test_silver_chunking():
    """파이프라인: 조문 단위 청킹 + 메타데이터 부착."""
    from pipeline.silver import parse_law_xml
    xml = """<법령>
      <조문단위>
        <조문번호>36</조문번호>
        <조문제목>금품 청산</조문제목>
        <조문내용>사용자는 근로자가 퇴직한 경우 14일 이내에 임금을 지급하여야 한다.</조문내용>
      </조문단위>
      <조문단위>
        <조문번호>43</조문번호>
        <조문제목>임금 지급</조문제목>
        <조문내용>임금은 통화로 직접 근로자에게 지급하여야 한다.</조문내용>
      </조문단위>
    </법령>"""
    chunks = parse_law_xml(xml, "근로기준법", "20211119")
    assert len(chunks) == 2
    c = chunks[0]
    assert c["article"] == "제36조"
    assert "14일" in c["text"]
    assert c["enforced_date"] == "20211119"   # 신뢰성 메타데이터
    assert c["source_url"]


def test_silver_chunking_항본문_누락방지():
    """긴 조문은 조문내용에 헤더만 오고 실제 본문은 항·호 하위요소에 온다.
    조문내용(헤더)만 본문으로 쓰면 청약철회 같은 핵심 조문이 빈 껍데기가 된다 → 누락 금지."""
    from pipeline.silver import parse_law_xml
    xml = """<법령>
      <조문단위>
        <조문번호>17</조문번호>
        <조문여부>조문</조문여부>
        <조문제목>청약철회등</조문제목>
        <조문내용>제17조(청약철회등)</조문내용>
        <항>
          <항번호>①</항번호>
          <항내용>① 소비자는 다음 각 호의 기간 이내에 청약철회를 할 수 있다.</항내용>
          <호>
            <호번호>1.</호번호>
            <호내용>1. 계약내용에 관한 서면을 받은 날부터 7일</호내용>
          </호>
        </항>
      </조문단위>
    </법령>"""
    chunks = parse_law_xml(xml, "전자상거래법", "20260721")
    assert len(chunks) == 1
    c = chunks[0]
    assert c["article"] == "제17조"
    assert "청약철회를 할 수 있다" in c["text"]   # 항 본문 누락 금지
    assert "7일" in c["text"]                      # 호 본문 누락 금지


def test_api_consult():
    """웹서비스: /api/consult 가 분류·카드·검증리포트를 반환."""
    from fastapi.testclient import TestClient

    from app.api import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.post("/api/consult", json={"question": "보증금을 안 돌려줘요"})
    assert r.status_code == 200
    data = r.json()
    assert data["in_scope"] is True
    assert data["domains"][0]["id"] == "housing"
    assert data["answer_blocks"][0]["citations"]


def test_api_draft():
    """웹서비스: /api/draft 가 '초안' 경고 포함 문서를 반환."""
    from fastapi.testclient import TestClient

    from app.api import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.post("/api/draft", json={"question": "월급을 못 받았어요", "domain": "labor"})
    assert r.status_code == 200
    assert "초안" in r.json()["guide"]


def test_api_index_page():
    """웹서비스: 메인 화면(Jinja)이 렌더링됨."""
    from fastapi.testclient import TestClient

    from app.api import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.get("/")
    assert r.status_code == 200
    assert "법률" in r.text
