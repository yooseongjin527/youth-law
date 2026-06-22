"""후속 질문 → 독립형 질문 재작성 (멀티턴 1단계).

설계(옵션 1): 후속 질문을 직전 대화로 '혼자서도 이해되는' 질문으로 LLM 재작성한 뒤
기존 그래프에 그대로 투입한다 → graph/state/agents 무변경. supervisor가 재작성된
독립형 질문을 자연스럽게 (재)분류하므로 분야 전환도 그대로 처리된다.

★ 마커 가드 ★: 참조 표지(그거/그건/그럼…)가 있을 때만 재작성한다. 없으면 원문
그대로 통과 → 단발 질문 경로는 기존과 100% 동일(회귀 위험 0, LLM 호출 0).
보수적으로: 못 잡은 후속은 '맥락 없는 단발'처럼 동작(우아한 저하)뿐이지만, 멀쩡한
독립 질문을 잘못 재작성하면 답이 틀어진다 → 표지는 좁게 잡는다.
"""

# 직전 맥락을 가리키는 지시 표지. 이게 없으면 후속이 아니라 독립 질문으로 본다.
# (broad한 '그'·'더'·'또' 등은 일반 질문에서도 흔해 오작동 → 의도적으로 제외)
_REF_MARKERS = (
    "그거", "그건", "그게", "그걸", "그런", "그렇", "그럼", "그러면",
    "그때", "그땐", "이거", "이건", "저거", "거기", "그곳", "방금",
    "아까", "위에", "해당", "그분", "그쪽", "그것", "이것",
)

_REWRITE_PROMPT = """아래는 청년 생활법률 상담 대화의 직전 맥락입니다.

[직전 대화]
{history}

[사용자의 후속 질문]
{query}

이 후속 질문을 '직전 대화를 모르는 사람도 이해할 수 있는 완전한 질문'으로
한국어로 다시 쓰세요.
- 지시어(그거/그건/그럼 등)를 직전 대화의 구체적 대상으로 치환
- 질문의 의도·분야를 절대 바꾸지 말 것 (없는 내용 추가 금지)
- 후속 질문이 이미 독립적이면 거의 그대로 두세요
JSON으로만 답하세요: {{"standalone": "..."}}"""


def _has_reference_marker(query: str) -> bool:
    return any(m in query for m in _REF_MARKERS)


def _format_history(history: list[dict], max_turns: int = 2) -> str:
    """재작성 프롬프트에 넣을 최근 대화. 답변은 길이 제한(프롬프트 비대 방지)."""
    lines: list[str] = []
    for t in history[-max_turns:]:
        q = (t.get("question") or "").strip()
        a = " ".join((t.get("answer") or "").split())[:200]
        lines.append(f"Q: {q}")
        lines.append(f"A: {a}")
    return "\n".join(lines)


def contextualize(history: list[dict], query: str) -> str:
    """후속 질문을 독립형으로 재작성. 맥락 불필요하면 원문 그대로 반환.

    안전 설계:
      - history 비었거나 참조 표지 없으면 즉시 원문 반환(LLM 호출 0, 기존 동작 동일).
      - 재작성 실패(파싱/네트워크/빈 결과)는 조용히 원문으로 폴백 — 상담이 죽지 않게.
    """
    if not history or not _has_reference_marker(query):
        return query
    from common.llm import call_bedrock_json
    try:
        data = call_bedrock_json(
            _REWRITE_PROMPT.format(history=_format_history(history), query=query),
            required_keys=["standalone"],
            task="classify",  # Haiku급 — 싸고 빠른 재작성
        )
        rewritten = (data.get("standalone") or "").strip()
        return rewritten or query
    except Exception:
        return query
