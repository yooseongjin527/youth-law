"""분야별 공식 연락처 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

★ 차별점의 핵심 ★
연락처는 절대 LLM이 생성하지 않는다. 전화번호 하나 틀리면 신뢰가 무너진다.
여기 하드코딩된 검증 데이터에서만 가져온다 → 환각 0 보장.
각 전문가는 답변 생성 후 get_contacts(domain)으로 자기 분야 연락처를 붙인다.

⚠️ 실제 번호/URL은 Day 1에 각 담당자가 공식 사이트에서 직접 확인해 갱신할 것.
   아래는 골격 검증용 예시값.

────────────────────────────────────────────────────────
TODO 우선순위
  [각자/Day1] ① 자기 분야 공식 연락처를 공식 사이트에서 확인해 갱신
  [공용/Day4] ② 상황별 세부 연락처 분기 (예: 지역별 노동청)
────────────────────────────────────────────────────────
"""

_CONTACTS: dict[str, list[dict]] = {
    "labor": [
        {
            "org": "고용노동부 고객상담센터",
            "phone": "1350",
            "url": "https://1350.moel.go.kr/home/",
            "note": "임금체불·부당해고·출산휴가 등 노동관계 민원 상담",
        },
        {
            "org": "노동위원회",
            "phone": "044-202-8226",
            "url": "https://nlrc.go.kr/nlrc/main/main.do",
            "note": "부당해고·부당노동행위 구제, 노동쟁의 조정, 차별시정 신청",
        },
        {
            "org": "근로복지공단",
            "phone": "1588-0075",
            "url": "https://www.comwel.or.kr/comwel/help/index.jsp",
            "note": "산재보상·요양·재활, 고용·산재보험 가입·납부, 근로복지서비스 상담",
        },
        {
            "org": "청소년·청년근로권익센터",
            "phone": "1644-3119",
            "url": "https://www.youthlabor.co.kr/customer/info",
            "note": "청소년·청년 노동상담, 부당대우 상담, 진정사건 대리 등 무료 권리구제 지원",
        },
        {
            "org": "국가인권위원회",
            "phone": "1331",
            "url": "https://case.humanrights.go.kr/cnslt/guide.do",
            "note": "직장 내 차별·성희롱·인권침해 상담 및 진정 안내",
        },
        {
            "org": "대한법률구조공단",
            "phone": "132",
            "url": "https://www.klac.or.kr/",
            "note": "임금체불·해고 등 노동분쟁 관련 무료 법률상담, 소송구조·소송서류 작성 지원",
        },
    ],
    "housing": [
        {
            "org": "대한법률구조공단",
            "phone": "132",
            "url": "https://www.klac.or.kr/",
            "note": "보증금·임대차 분쟁 무료 법률상담",
        },
        {
            "org": "전세피해지원센터",
            "phone": "1533-8119",
            "url": "https://www.khug.or.kr/",
            "note": "전세사기 피해 지원",
        },
    ],
    "consumer": [
        {
            "org": "한국소비자원 소비자상담센터",
            "phone": "1372",
            "url": "https://www.ccn.go.kr/",
            "note": "환불·계약·온라인거래 분쟁 상담",
        },
    ],
    "finance": [
        {
            "org": "신용회복위원회",
            "phone": "1600-5500",
            "url": "https://www.ccrs.or.kr/",
            "note": "채무조정·개인워크아웃 상담 (빚 해결)",
        },
        {
            "org": "금융감독원",
            "phone": "1332",
            "url": "https://www.fss.or.kr/",
            "note": "보이스피싱 신고·지급정지, 불법추심·사금융 신고",
        },
        {
            "org": "경찰청 (보이스피싱)",
            "phone": "112",
            "url": "https://www.police.go.kr/",
            "note": "전기통신금융사기 피해 즉시 신고",
        },
        {
            "org": "대한법률구조공단",
            "phone": "132",
            "url": "https://www.klac.or.kr/",
            "note": "개인회생·파산 무료 법률상담",
        },
    ],
}


def get_contacts(domain: str) -> list[dict]:
    """분야의 검증된 공식 연락처 반환. 없으면 빈 리스트."""
    return _CONTACTS.get(domain, [])
