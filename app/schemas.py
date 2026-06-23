"""API 요청/응답 모델 — docs/SPEC.md의 answer_blocks·DocumentDraft에 대응."""
from typing import Optional

from pydantic import BaseModel, Field


class ConsultRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500, description="이용자의 생활법률 질문")
    # 멀티턴 세션 식별자. 없으면(None) 단발 상담 — 종전 동작과 동일.
    session_id: Optional[str] = Field(
        default=None, max_length=64, description="연속 상담 세션 ID(후속 질문 맥락 복원용)"
    )


class DomainTag(BaseModel):
    id: str
    name: str


class ConsultResponse(BaseModel):
    question: str
    # 후속 질문을 독립형으로 재작성했을 때만 채워짐(단발·재작성 불필요 시 None)
    rewritten_question: Optional[str] = None
    domains: list[DomainTag]
    in_scope: bool
    final_answer: str
    answer_blocks: list[dict]          # SPEC: 분야별 카드 (answer/citations/contacts)
    verification_report: list[dict]    # 하네스: 검증 통과/탈락 리포트


class DraftRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    domain: str = Field(pattern="^(labor|housing|consumer|finance)$")


class DraftResponse(BaseModel):
    doc_type: str
    domain: str
    title: str
    body: str
    based_on: list[str]
    guide: str
