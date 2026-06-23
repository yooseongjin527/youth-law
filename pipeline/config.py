"""파이프라인 설정 — ★여기가 팀이 채우는 동적 내용의 중심★

코드는 손댈 필요 없고, 이 파일의 법령 목록과 .env의 키만 채우면
전체 파이프라인(수집→청킹→임베딩→적재→증분갱신)이 돈다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# .env 로드 — config가 모두의 import 진입점이라 여기서 한 번만 부르면
# 파이프라인·에이전트·rag 어디서든 os.getenv가 .env 값을 읽는다.
load_dotenv()

# ── 경로 (medallion 레이어) ──────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
BRONZE_DIR = DATA_DIR / "bronze"     # 원본 API 응답 (XML/JSON 그대로)
SILVER_DIR = DATA_DIR / "silver"     # 조문 단위 청크 (jsonl)
CHROMA_DIR = DATA_DIR / "chroma"     # Gold: 벡터DB 영속 저장
MANIFEST = DATA_DIR / "manifest.json"  # 증분 감지용: 법령별 시행일 기록

# ── API 키 (.env에서) ────────────────────────────────
LAW_OC = os.getenv("LAW_GO_KR_OC", "")           # 국가법령정보센터

# ── 임베딩 ───────────────────────────────────────────
EMBED_MODEL = os.getenv("EMBED_MODEL", "jhgan/ko-sroberta-multitask")

# ── ★동적 내용①: 분야별 수집 법령 목록★ ─────────────
# 국가법령정보센터에 등록된 정확한 법령명으로. (Day1 샘플 호출로 확인)
# 약칭이 아니라 정식 명칭이어야 검색이 정확함.
LAW_LIST: dict[str, list[str]] = {
    "labor": [
        "근로기준법",
        "최저임금법",
    ],
    "housing": [
        "주택임대차보호법",
    ],
    "consumer": [
        "전자상거래 등에서의 소비자보호에 관한 법률",
        "방문판매 등에 관한 법률",      # 계속거래·자동결제(구독) 해지 근거
        "할부거래에 관한 법률",         # 할부 청약철회·항변권 근거
    ],
    "finance": [
        "채무자 회생 및 파산에 관한 법률",
        "전기통신금융사기 피해 방지 및 피해금 환급에 관한 특별법",
        "채권의 공정한 추심에 관한 법률",
        "대부업 등의 등록 및 금융이용자 보호에 관한 법률",
    ],
}
