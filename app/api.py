"""FastAPI 서버 — 웹서비스 진입점.

실행:  uvicorn app.api:app --host 0.0.0.0 --port 8000
화면:  GET /            → Jinja 메인 페이지 (질문 폼 + 결과 카드, JS fetch)
API:   POST /api/consult → 상담 (분류·답변·근거·연락처)
       POST /api/draft   → 문서 초안 생성
       GET  /health      → 헬스체크 (배포·모니터링용)
문서:  GET /docs         → Swagger UI 자동 생성

UI 확장 시: app/templates/ 에 Jinja 템플릿 추가 (base.html 상속).
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import service
from app.schemas import ConsultRequest, ConsultResponse, DraftRequest, DraftResponse

_HERE = Path(__file__).resolve().parent

app = FastAPI(
    title="청년 생활법률 상담 AI",
    description="현행 법령 근거 + 공식 연락처 + 문서초안 — 노동/주택/소비자/금융",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
templates = Jinja2Templates(directory=_HERE / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """메인 화면 (Jinja). 질문 입력 → JS가 /api/consult 호출 → 카드 렌더링."""
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/consult", response_model=ConsultResponse)
def consult(req: ConsultRequest):
    return service.consult(req.question)


@app.post("/api/draft", response_model=DraftResponse)
def draft(req: DraftRequest):
    return service.make_draft(req.question, req.domain)


@app.get("/health")
def health():
    return {"status": "ok"}
