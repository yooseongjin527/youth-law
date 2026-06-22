"""멀티턴 후속질문 계약 테스트 — 세션 저장소 + 질의 재작성(contextualize).

핵심 불변식:
  - 마커 없는/맥락 없는 질문은 원문 그대로(LLM 호출 0) → 단발 경로 회귀 0.
  - 재작성 실패는 조용히 원문 폴백 → 상담이 죽지 않음.
  - 세션은 최근 N턴만 보관(메모리 바운드).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import contextualize as ctx  # noqa: E402
from app import session_store as store  # noqa: E402


# ---- 세션 저장소 ----
def test_session_append_and_get():
    sid = "t-append"
    store.clear(sid)
    store.append_turn(sid, "알바비를 못 받았어요", "근로기준법 제36조...", ["labor"])
    hist = store.get_history(sid)
    assert len(hist) == 1
    assert hist[0]["question"] == "알바비를 못 받았어요"
    assert hist[0]["domains"] == ["labor"]


def test_session_caps_recent_turns():
    sid = "t-cap"
    store.clear(sid)
    for i in range(store._MAX_TURNS + 3):
        store.append_turn(sid, f"q{i}", f"a{i}", ["labor"])
    hist = store.get_history(sid)
    assert len(hist) == store._MAX_TURNS
    assert hist[-1]["question"] == f"q{store._MAX_TURNS + 2}"  # 최신 보존
    assert hist[0]["question"] == "q3"  # 오래된 것 폐기


def test_empty_session_id_is_noop():
    store.append_turn("", "q", "a", ["labor"])
    assert store.get_history("") == []
    assert store.get_history(None) == []


# ---- contextualize 마커 가드 ----
def test_no_history_returns_original():
    # 첫 턴: history 비어 있으면 무조건 원문(LLM 호출 없음)
    assert ctx.contextualize([], "그건 며칠 안에 가능해?") == "그건 며칠 안에 가능해?"


def test_no_marker_returns_original_without_llm(monkeypatch):
    # 참조 표지 없는 독립 질문은 history가 있어도 재작성하지 않는다(회귀 0).
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("마커 없는 질문에 LLM을 호출하면 안 됨")

    monkeypatch.setattr("common.llm.call_bedrock_json", _boom)
    history = [{
        "question": "전세 보증금을 안 줘요",
        "answer": "주택임대차보호법...",
        "domains": ["housing"],
    }]
    q = "월세 계약 갱신은 어떻게 하나요?"
    assert ctx.contextualize(history, q) == q
    assert called["n"] == 0


def test_marker_triggers_rewrite(monkeypatch):
    monkeypatch.setattr(
        "common.llm.call_bedrock_json",
        lambda *a, **k: {"standalone": "인터넷으로 산 의류의 청약철회는 며칠 이내에 가능한가요?"},
    )
    history = [{
        "question": "인터넷에서 옷 샀는데 환불돼요?",
        "answer": "청약철회...",
        "domains": ["consumer"],
    }]
    out = ctx.contextualize(history, "그거 며칠 안에 가능해?")
    assert "청약철회" in out and "그거" not in out


def test_rewrite_failure_falls_back_to_original(monkeypatch):
    def _fail(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("common.llm.call_bedrock_json", _fail)
    history = [{"question": "보증금 못 받았어요", "answer": "...", "domains": ["housing"]}]
    q = "그건 어디에 신고해요?"
    assert ctx.contextualize(history, q) == q  # 죽지 않고 원문
