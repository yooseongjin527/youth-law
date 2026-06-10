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
from state import LegalState

# 검증 통과 기준: 이 값 미만이면 답변을 탈락시키고 리포트에 기록
_MIN_CONFIDENCE = 0.5


def _is_grounded(answer_text: str, citations: list[dict]) -> tuple[bool, str]:
    """답변이 인용 조문에 근거하는지 검사.
    return: (통과 여부, 사유)

    TODO(공용/Day4): 실제 구현. 지금은 stub — '인용이 1건 이상 존재'만 본다.
    실제 구현 전략(2단계):
      1) 어휘 겹침: 답변의 핵심 명사들이 citations의 snippet 안에 등장하는가
      2) (정밀) Bedrock 판정: "주장-조문 쌍을 주고 근거 여부 YES/NO"
    """
    if not citations:
        return False, "인용된 조문이 없음"
    if not any(c.get("snippet") for c in citations):
        return False, "조문 원문(snippet)이 비어 있음"
    # TODO(공용/Day4): 여기서 어휘 겹침/Bedrock 판정 수행
    return True, "ok"


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
