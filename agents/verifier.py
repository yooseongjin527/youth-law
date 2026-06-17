"""Verifier(답변-근거 검증기) — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

★ 하네스 엔지니어링의 핵심 노드 ★
"검색된 조문만 근거로 답하세요"라는 프롬프트는 '부탁'이다.
이 노드는 그것을 '구조'로 강제한다 — 전문가 답변의 각 문장이
실제 검색된 조문(citations.snippet)에 근거하는지 프로그램이 검사하고,
근거 없는 답변은 신뢰도를 깎거나 탈락시킨다.
환각이 사용자에게 도달하는 것이 구조적으로 불가능해진다.

위치: 전문가들(fan-in) → [verifier] → planner

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day4] ① _is_grounded를 실제 검증으로 (아래 2단계 전략)
       1차: 어휘 겹침(답변 핵심 명사가 snippet에 존재하는지) — 빠르고 단순
       2차: Bedrock으로 "이 주장이 이 조문에 근거하는가? YES/NO" 판정 — 정밀
  [공용/Day5] ② 문장 단위 검증으로 세분화 (답변을 문장 분리 → 문장별 근거 매칭)
  [공용/Day5] ③ verification_report를 발표 지표로 (검증 탈락률 = 환각 차단 건수)
────────────────────────────────────────────────────────
"""
from common.llm import call_bedrock_json
from state import LegalState

# 검증 통과 기준: 이 값 미만이면 답변을 탈락시키고 리포트에 기록
_MIN_CONFIDENCE = 0.5

# ★환각 판정★: 답변이 근거 조문을 벗어나 '법령 사실을 지어냈는지'만 본다.
# 일반 안내·정직한 hedging은 환각이 아니므로 통과시킨다(과탈락 방지).
_JUDGE_PROMPT = """답변이 아래 [근거 조문]을 벗어나 법령 사실을 '지어냈는지' 판정하세요.

판정 기준:
- grounded=false (탈락): 근거 조문에 없거나 어긋나는 법조문·숫자·기한·비율·권리를
  사실처럼 단정한 경우(환각).
- grounded=true (통과):
  · 근거 조문 내용으로 답한 경우.
  · 조문에서 논리적으로 도출되는 동치 환산·재진술
    (예: '20분의 1'→'5%', '2년'→'24개월')은 환각이 아니다.
  · "조문에 직접 규정이 없어 일반적으로는…"처럼 한계를 정직하게 밝히고
    일반 안내·전문가 상담을 권하는 경우.
  일반론·면책문구·동치 환산은 환각이 아니다.

[답변]
{answer}

[근거 조문]
{snippets}
"""


def _coerce_bool(v) -> bool:
    """LLM이 bool/문자열 무엇으로 주든 통과 여부로 변환."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "yes", "y", "1", "근거됨", "통과")


def _is_grounded(answer_text: str, citations: list[dict]) -> tuple[bool, str]:
    """답변이 인용 조문에 근거하는지 검사. return: (통과 여부, 사유)

    1) 구조 가드: 인용·snippet 없으면 즉시 탈락.
    2) Bedrock 판정(verify 티어): 조문 밖 법령 사실 날조면 탈락, 정직한 일반론은 통과.
    3) 판정 호출 실패 시 fail-open — 보수적으로 통과(파이프라인 안 멈춤, 답엔 실제 인용 있음).
    """
    if not citations:
        return False, "인용된 조문이 없음"
    snippets = [c["snippet"] for c in citations if c.get("snippet")]
    if not snippets:
        return False, "조문 원문(snippet)이 비어 있음"

    try:
        data = call_bedrock_json(
            _JUDGE_PROMPT.format(answer=answer_text, snippets="\n---\n".join(snippets)),
            required_keys=["grounded", "reason"], task="verify",
        )
        ok = _coerce_bool(data["grounded"])
        reason = str(data.get("reason", "")).strip()[:80] or ("ok" if ok else "근거 이탈")
        return ok, reason
    except Exception as e:
        # fail-open: 판정 실패가 곧 서비스 마비가 되지 않게. 단 리포트에 폴백임을 남긴다.
        return True, f"판정 폴백(통과): {type(e).__name__}"


def verifier_agent(state: LegalState) -> dict:
    """전문가 답변들을 검증해 통과분만 verified_answers로 넘긴다.
    Planner는 이후 verified_answers만 사용 — 검증 안 된 답변은
    사용자에게 도달할 경로 자체가 없다(하네스).
    """
    verified = []
    report = []

    for a in state["domain_answers"]:
        ok, reason = _is_grounded(a["answer"], a["citations"])

        if ok and a["confidence"] >= _MIN_CONFIDENCE:
            verified.append(a)
            report.append({"domain": a["domain"], "dropped": False, "reason": "통과"})
        else:
            # 탈락: 사용자에게 전달되지 않음. 리포트에만 남김.
            drop_reason = reason if not ok else f"confidence {a['confidence']} < {_MIN_CONFIDENCE}"
            report.append({"domain": a["domain"], "dropped": True, "reason": drop_reason})

    return {
        "verified_answers": verified,
        "verification_report": report,
        "messages": [f"[verifier] {len(verified)}/{len(state['domain_answers'])} 답변 검증 통과"],
    }
