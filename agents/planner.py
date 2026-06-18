"""Planner — 공용 파일 ⚠️ (변경은 PR + 전원 합의).
전문가들의 domain_answers를 종합.
- final_answer: 텍스트 종합 (조문 원문 포함) — 콘솔/간단 출력용
- answer_blocks: 분야별 구조화 데이터 — Streamlit 카드 렌더링용
범위 밖이면 정직한 거절.

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day3] ① 각 분야 answer를 Bedrock으로 자연스럽게 (요약 + 상세 분리)
  [공용/Day4] ② 답변-근거 정합성 검증 (snippet에 없는 주장 제거)
  [공용/Day5] ③ 복수 분야 우선순위/연결 안내 (예: 노동→주택 순서)
────────────────────────────────────────────────────────
"""
from state import DOMAIN_KR, LegalState

_OUT_OF_SCOPE = (
    "이 서비스는 노동·주택·소비자·금융(채무) 4개 분야의 법령 정보를 안내합니다. "
    "문의 내용은 다루는 범위 밖이라 정확히 답하기 어렵습니다. "
    "대한법률구조공단(132) 상담을 권합니다."
)

_DISCLAIMER = (
    "\n※ 국가법령정보센터 현행 법령을 근거로 한 일반 정보 안내입니다. "
    "조문은 원문 인용이며, 구체적 사건은 전문가 상담을 권합니다."
)


_SNIPPET_MAX = 120  # 근거 조문 표시 길이 — 조문 전문 도배 방지(원문은 source_url로)


def _truncate(text: str, n: int = _SNIPPET_MAX) -> str:
    """근거 조문을 표시용으로 줄임. 공백·줄바꿈 정리 후 n자 초과면 … 붙임."""
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _build_block(a: dict) -> dict:
    """한 분야 답을 화면 카드용 구조로 정리. citation에 조문 원문(snippet) 포함."""
    return {
        "domain": a["domain"],
        "domain_kr": DOMAIN_KR.get(a["domain"], a["domain"]),
        "answer": a["answer"],
        "citations": [
            {
                "law_name": c["law_name"],
                "article": c["article"],
                "enforced_date": c["enforced_date"],
                "text": _truncate(c["snippet"]),   # ← 조문 원문 미리보기(절단). 전체는 source_url
                "source_url": c["source_url"],
            }
            for c in a["citations"][:2]
        ],
        "contacts": a["contacts"],
    }


def _block_to_text(b: dict) -> str:
    """구조화 블록을 텍스트로 (콘솔/간단 출력용)."""
    lines = [f"【{b['domain_kr']} 분야】", b["answer"]]
    for c in b["citations"]:
        lines.append(f"\n  ◆ 근거: {c['law_name']} {c['article']} (시행 {c['enforced_date']})")
        lines.append(f'     "{c["text"]}"')          # 조문 원문 인용
        lines.append(f"     원문: {c['source_url']}")
    for ct in b["contacts"]:
        lines.append(f"  ☎ {ct['org']} {ct['phone']} ({ct['note']})")
    return "\n".join(lines)


def planner_agent(state: LegalState) -> dict:
    if not state["in_scope"]:
        return {
            "final_answer": _OUT_OF_SCOPE,
            "answer_blocks": [],
            "messages": ["[planner] 범위 밖 거절"],
        }

    # ★ 하네스: verifier를 통과한 답변만 사용. 검증 안 된 답변은
    #   사용자에게 도달할 경로가 구조적으로 없다.
    answers = state.get("verified_answers")
    if answers is None:  # verifier 미경유(직접 호출 등) 시 안전 폴백
        answers = state["domain_answers"]

    if not answers:  # 전부 검증 탈락 → 지어내지 않고 정직하게
        return {
            "final_answer": (
                "검색된 법령 근거가 충분하지 않아 정확한 답변을 드리기 어렵습니다. "
                "대한법률구조공단(132) 상담을 권합니다."
            ),
            "answer_blocks": [],
            "messages": ["[planner] 검증 통과 답변 없음 — 정직 거절"],
        }

    blocks = [_build_block(a) for a in answers]
    final = "\n\n".join(_block_to_text(b) for b in blocks) + "\n" + _DISCLAIMER

    return {
        "final_answer": final,          # 텍스트 (조문 원문 포함)
        "answer_blocks": blocks,        # 구조화 (Streamlit 카드용)
        "messages": ["[planner] 종합 응답 생성"],
    }
