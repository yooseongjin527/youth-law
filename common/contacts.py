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
            "org": "청소년·청년근로권익센터",
            "phone": "1644-3119",
            "url": "https://www.youthlabor.co.kr/customer/info",
            "note": "청소년·청년 노동상담, 부당대우 상담, 진정사건 대리 등 무료 권리구제 지원",
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
            "note": "온라인거래·방문판매·전화권유·다단계·할부·상조 등 소비자 분쟁 상담",
        },
        {
            "org": "공정거래위원회",
            "phone": "110",
            "url": "https://www.ftc.go.kr/www/index.do",
            "note": "전자상거래·방문판매·할부거래 등 사업자 법 위반행위 신고",
        },
        {
            "org": "직접판매공제조합",
            "phone": "02-566-1202",
            "url": "https://www.macco.or.kr/ko/main/main.do",
            "note": "다단계판매 피해 시 공제(환급) 청구",
        },
        {
            "org": "특수판매공제조합",
            "phone": "02-2058-0831",
            "url": "https://www.kossa.or.kr/",
            "note": "방문판매·후원방문판매 등 피해 시 공제(환급) 청구",
        },
        {
            "org": "한국상조공제조합",
            "phone": "1688-0972",
            "url": "https://www.kmaca.or.kr/main/main.do",
            "note": "상조 등 선불식 할부 업체 폐업 시 피해보상",
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
