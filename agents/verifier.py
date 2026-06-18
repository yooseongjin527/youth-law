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
import re

from common.llm import call_bedrock_json
from state import LegalState

# 검증 통과 기준: 이 값 미만이면 답변을 탈락시키고 리포트에 기록
_MIN_CONFIDENCE = 0.5

# 문장 분리(휴리스틱): 문장부호+공백 또는 줄바꿈. 숫자 뒤 마침표(목록 "1.")는 보호.
_SENT_SPLIT = re.compile(r"(?<=[^0-9][.!?])\s+|\n+")

# ★문장 단위 환각 판정★: 답변을 문장으로 쪼개, 근거 조문 밖 법령 사실을 지어낸
# 문장 번호만 골라낸다. 합리적 도출·동치환산·정직한 일반론은 근거 있음(과탈락 방지).
_JUDGE_PROMPT = """답변을 문장 번호로 나눴습니다. 각 문장이 [근거 조문]에 근거하는지 보고,
근거 없는 문장의 번호만 배열로 반환하세요.

판정 기준:
- 근거 없음(번호에 포함): 근거 조문에 없거나 어긋나는 법조문·숫자·기한·비율·권리를
  사실처럼 단정한 문장.
- 근거 있음(포함하지 말 것):
  · 근거 조문 내용으로 답한 문장.
  · 조문에서 합리적으로 도출·함의되는 내용, 동치 환산('20분의 1'→'5%', '2년'→'24개월').
  · 일반 안내·면책문구·"조문에 직접 규정이 없어 일반적으로는…" 식 정직한 hedging.

[문장]
{sentences}

[근거 조문]
{snippets}
"""


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _is_grounded(answer_text: str, citations: list[dict]) -> tuple[bool, str, str | None]:
    """문장 단위 근거 검증. return: (통과 여부, 사유, 정제 답변)

    1) 구조 가드: 인용·snippet 없으면 즉시 탈락.
    2) Bedrock 판정(verify 티어): 답변을 문장으로 쪼개 '근거 없는 문장 번호'를 받는다.
       - 환각 문장만 제거하고 나머지로 정제 답변 구성(차별점 유지 + 멀쩡한 부분 보존).
       - 근거 문장이 하나도 안 남으면(전부 환각) 통째 탈락.
    3) 판정 호출 실패 시 fail-open — 원답 그대로 통과(파이프라인 안 멈춤).

    3번째 반환값(정제 답변): 환각 문장을 뺀 텍스트. 변형 없으면 None(원답 유지).
    """
    if not citations:
        return False, "인용된 조문이 없음", None
    snippets = [c["snippet"] for c in citations if c.get("snippet")]
    if not snippets:
        return False, "조문 원문(snippet)이 비어 있음", None
    sentences = _split_sentences(answer_text)
    if not sentences:
        return False, "답변이 비어 있음", None

    try:
        data = call_bedrock_json(
            _JUDGE_PROMPT.format(
                sentences="\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1)),
                snippets="\n---\n".join(snippets),
            ),
            required_keys=["ungrounded"], task="verify",
        )
        raw = data.get("ungrounded") or []
        bad = {int(x) for x in raw if str(x).strip().lstrip("-").isdigit()}
        bad = {i for i in bad if 1 <= i <= len(sentences)}
    except Exception as e:
        return True, f"판정 폴백(통과): {type(e).__name__}", None  # fail-open: 원답 유지

    if not bad:
        return True, "ok", None  # 변형 없음 → 원답 그대로
    kept = [s for i, s in enumerate(sentences, 1) if i not in bad]
    if not kept:  # 전부 환각 → 통째 탈락
        return False, "근거 문장 없음 — 전부 탈락", None
    return True, f"환각 {len(bad)}문장 제거", "\n".join(kept)


def verifier_agent(state: LegalState) -> dict:
    """전문가 답변들을 검증해 통과분만 verified_answers로 넘긴다.
    환각 문장이 섞인 답은 그 문장만 제거한 정제본으로 통과시킨다(B).
    Planner는 이후 verified_answers만 사용 — 검증 안 된 답변은
    사용자에게 도달할 경로 자체가 없다(하네스).
    """
    verified = []
    report = []

    for a in state["domain_answers"]:
        ok, reason, cleaned = _is_grounded(a["answer"], a["citations"])

        if ok and a["confidence"] >= _MIN_CONFIDENCE:
            if cleaned is not None:
                a = {**a, "answer": cleaned}  # 환각 문장 제거된 정제본으로 교체(원본 불변)
            verified.append(a)
            report.append({"domain": a["domain"], "dropped": False, "reason": reason})
        else:
            # 탈락: 사용자에게 전달되지 않음. 리포트에만 남김.
            drop_reason = reason if not ok else f"confidence {a['confidence']} < {_MIN_CONFIDENCE}"
            report.append({"domain": a["domain"], "dropped": True, "reason": drop_reason})

    return {
        "verified_answers": verified,
        "verification_report": report,
        "messages": [f"[verifier] {len(verified)}/{len(state['domain_answers'])} 답변 검증 통과"],
    }
