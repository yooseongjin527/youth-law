"""문서 초안 생성 헬퍼 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

차별점 '행동 연결'의 정점: 답변에서 끝나지 않고 실제 쓸 수 있는
내용증명·진정서 초안을 법령 근거 담아 만든다.

각 전문가가 자기 분야 답변(DomainAnswer)을 넘기면 초안을 생성한다.
생성 패턴은 공통, 분야별 문서 종류/양식만 다르다.

★ 안전 원칙 ★
- 항상 '초안(draft)'임을 명시. 완성된 법적 문서 아님.
- guide에 "제출 전 검토 권장 + 전문가 상담" 경고 필수.
- 본문 법적 주장은 답변의 citations(검색된 조문) 안에서만 (환각 방지).

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day4] ① make_draft 본문 생성을 Bedrock으로 (지금은 템플릿 stub)
  [공용/Day4] ② 분야별 문서 양식 정교화 (내용증명/진정서 형식 차이)
  [공용/Day5] ③ 사용자 입력값(날짜·금액 등) 빈칸 [   ] 처리 + 채우기 안내
────────────────────────────────────────────────────────
"""

# 분야별 기본 문서 종류 (실제 상황에 맞게 전문가가 선택)
_DOC_TYPE = {
    "labor": "임금체불 진정서",
    "housing": "보증금 반환 요구 내용증명",
    "consumer": "청약철회·환불 요구 내용증명",
    "finance": "채무 변제 관련 통지서",  # 보이스피싱은 지급정지 신청서, 채무는 조정신청 등 상황별
}

_GUIDE_BASE = (
    "※ 이 문서는 작성을 돕기 위한 초안입니다. 완성된 법적 문서가 아니므로, "
    "[   ] 부분을 본인 상황에 맞게 채우고, 제출 전 반드시 내용을 검토하세요. "
    "필요 시 아래 기관 또는 변호사 상담을 권합니다."
)


def make_draft(answer: dict, doc_type: str | None = None) -> dict:
    """DomainAnswer를 받아 문서 초안(DocumentDraft) 생성.
    answer: 해당 분야 전문가의 DomainAnswer (citations 포함)
    doc_type: 문서 종류 지정(없으면 분야 기본값)
    """
    domain = answer["domain"]
    dtype = doc_type or _DOC_TYPE.get(domain, "통지서")
    based_on = [f"{c['law_name']} {c['article']}" for c in answer.get("citations", [])]

    # TODO(공용/Day4): 아래 본문을 Bedrock으로 생성.
    #   - answer['citations']의 조문을 근거로 (검색 밖 주장 금지)
    #   - 날짜·금액·당사자명은 [   ] 빈칸으로 두고 사용자가 채우게
    body = (
        f"제목: {dtype}\n\n"
        f"수신: [   상대방(회사/임대인 등)   ]\n"
        f"발신: [   본인 성명·연락처   ]\n\n"
        f"1. 귀하의 무궁한 발전을 기원합니다.\n"
        f"2. 본인은 [   상황 설명   ]와 관련하여 아래와 같이 요구합니다.\n"
        f"3. [   구체적 요구사항: 예) 미지급 임금 OOO원을 O일 이내 지급   ]\n"
        f"4. 위 요구는 다음 법령에 근거합니다: {', '.join(based_on) or '[근거 법령]'}\n\n"
        f"[   작성일   ]    [   본인 성명   ] (서명)"
    )

    guide = _GUIDE_BASE
    if answer.get("contacts"):
        c = answer["contacts"][0]
        guide += f" 문의: {c['org']} ☎ {c['phone']}"

    return {
        "doc_type": dtype,
        "domain": domain,
        "title": dtype,
        "body": body,
        "based_on": based_on,
        "guide": guide,
    }
