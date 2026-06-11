# API_SETUP.md — 데이터 API 인증키 신청 절차

> 국가법령정보센터 OC 키 **하나만** 신청하면 된다(수동 승인 1~2일, 평일 신청 권장).
> 키는 한 명이 받아 팀 `.env`로 공유 (이미 .gitignore에 포함됨).

## 국가법령정보센터 (근거 조문·시행일 = 검색 코퍼스) — open.law.go.kr
1. open.law.go.kr (국가법령정보 공동활용) 회원가입/로그인
2. 상단 메뉴 **OPEN API → OPEN API 신청**
3. 서비스 선택: **법령 목록 + 법령 본문** (조문 수집에 둘 다 필요)
4. 활용목적: 비상업/학습·포트폴리오로 작성. ⚠️ 반드시 **비상업** — 상업 이용 시 제한됨
5. 담당자 수동 승인 대기 (1~2일, 주말 끼면 더. 평일 신청 권장)
6. 마이페이지에서 인증키(OC) 확인
- 호출 패턴: `law.go.kr/DRF/lawSearch.do`(목록) → `lawService.do`(본문 XML)
- ⚠️ https + User-Agent 필수 (기본 파이썬 UA 거부·간헐 연결 리셋 → pipeline/bronze.py가 재시도로 처리)

## .env 구성 (레포 루트, 커밋 금지)
```
LAW_GO_KR_OC=발급받은_OC값
AWS_REGION=us-west-2
BEDROCK_MODEL_MAIN=답변생성용_모델ID
BEDROCK_MODEL_SMALL=분류용_모델ID
```

## 팁
- **OC 키 하나로 벡터DB 전체(4분야)를 구축**한다 → `python scripts/build_index.py all`.
  (Windows는 `set PYTHONUTF8=1` 후 실행 — 콘솔 인코딩 크래시 방지)
- 막히면: 국가법령정보 공동활용 고객지원(open.law.go.kr) 문의.
