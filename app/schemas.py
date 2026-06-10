"""API 요청/응답 모델 — docs/SPEC.md의 answer_blocks·DocumentDraft에 대응."""
from pydantic import BaseModel, Field


class ConsultRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500, description="평어 법률 질문")


class DomainTag(BaseModel):
    id: str
    name: str


class ConsultResponse(BaseModel):
    question: str
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
