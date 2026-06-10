"""공유 State 스키마 — docs/SPEC.md §2의 코드화. 공용 파일 ⚠️ (변경은 PR + 전원 합의)"""
from operator import add
from typing import Annotated, Optional, TypedDict

# 4개 법률 분야 식별자. 라우팅 키로도 쓰인다.
DOMAINS = ["labor", "housing", "consumer", "finance"]
DOMAIN_KR = {
    "labor": "노동",
    "housing": "주택",
    "consumer": "소비자",
    "finance": "금융·채무",
}


class LegalCitation(TypedDict):
    """답변 근거가 된 법령 출처 한 건. 신뢰성 차별점의 핵심."""
    law_name: str            # 예: "주택임대차보호법"
    article: str             # 예: "제3조의2"
    enforced_date: str       # 시행일 (예: "2024-07-19") — '현행법' 신뢰성 표시
    snippet: str             # 인용 텍스트(요약, 15어절 이내 권장)
    source_url: str          # 국가법령정보센터/easylaw 링크


class Contact(TypedDict):
    """분야별 공식 연락처. LLM 생성 금지 — common/contacts.py의 검증 데이터에서만."""
    org: str                 # 기관명 (예: "고용노동부 고객상담센터")
    phone: str               # 전화 (예: "1350")
    url: str                 # 신청/안내 링크
    note: str                # 한 줄 안내 (예: "임금체불 온라인 진정")


class DomainAnswer(TypedDict):
    """한 분야 전문가가 내놓는 답. 4명 모두 이 모양으로 반환(계약 통일)."""
    domain: str                      # DOMAINS 중 하나
    answer: str                      # 해당 분야 관점 답변
    citations: list[LegalCitation]   # RAG로 끌어온 현행 법령 근거
    contacts: list[Contact]          # 검증된 공식 연락처 (환각 0)
    confidence: float                # 0.0~1.0


class DocumentDraft(TypedDict):
    """문서 초안(내용증명·진정서 등). 차별점 '행동 연결'의 정점.
    각 전문가가 자기 분야 문서를 법령 근거 담아 생성한다.
    ★ 반드시 '초안'임을 명시. 완성된 법적 문서가 아님. ★
    """
    doc_type: str            # 예: "내용증명", "임금체불 진정서"
    domain: str              # DOMAINS 중 하나
    title: str               # 문서 제목
    body: str                # 문서 본문 (법령 근거 포함)
    based_on: list[str]      # 근거 법령 (예: ["근로기준법 제36조"])
    guide: str               # 작성·제출 안내 + "초안 검토 권장" 경고


class LegalState(TypedDict):
    # --- 입력 (Supervisor가 초기화) ---
    user_query: str

    # --- 라우팅 제어 (Supervisor 전용 쓰기) ---
    target_domains: list[str]        # 매칭된 분야들. 예: ["labor","housing"]
    in_scope: bool                   # 4분야 안에 드는 질문인지

    # --- 각 분야 전문가 결과 (담당자만 자기 분야 1건 append) ---
    domain_answers: Annotated[list[DomainAnswer], add]

    # --- 검증 결과 (Verifier 전용 쓰기) — 하네스: 환각을 구조로 차단 ---
    verified_answers: Optional[list]         # 검증 통과한 DomainAnswer들
    verification_report: Optional[list]      # 검증 리포트 [{domain, dropped, reason}]

    # --- 최종 산출 (Planner 전용 쓰기) ---
    final_answer: Optional[str]              # 텍스트 종합 (조문 원문 포함)
    answer_blocks: Optional[list]            # 분야별 구조화 데이터 (Streamlit 카드용)

    # --- 공용 로그 (append만) ---
    messages: Annotated[list, add]
