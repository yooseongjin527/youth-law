# ONBOARDING.md — 작업 시작 가이드

> 데이터·RAG·협업 규약 세팅이 끝났습니다. 아래대로 하면 각자 환경에서 실데이터로 바로 개발 시작할 수 있어요.
> (규약은 CLAUDE.md/SPEC.md, 절차·리듬은 TEAM_GUIDE.md가 진실의 원천 — 이 문서는 "처음 한 번"의 셋업·확인 절차)

## 1. 최초 환경 셋업 (1인당 1회, ~10분)

```powershell
git clone <레포 URL> ; cd youth_law

# 가상환경 (권장)
python -m venv .venv ; .\.venv\Scripts\Activate.ps1

# 의존성
pip install -r requirements.txt
pip install chromadb sentence-transformers   # 무거워서 따로 (검색/빌드에 필요)

# 환경변수 — .env.example 복사 후 OC 키 채우기
copy .env.example .env
# .env 열어서 LAW_GO_KR_OC=<공유받은 OC키> 입력 (이 키 하나면 데이터 구축 됨)
```

> **OC 키는 유성진에게 요청**하세요. (`data/`는 git에 안 올라가서 각자 빌드합니다)

## 2. 데이터 구축 (1회, 첫 실행 시 임베딩 모델 ~400MB 다운로드)

```powershell
$env:PYTHONUTF8=1        # ★Windows 필수★ (없으면 콘솔 인코딩 크래시)
python scripts/build_index.py all
```
> macOS/Linux: `PYTHONUTF8=1 python scripts/build_index.py all`

성공 로그 예시:
```
✓ gold: law_labor 컬렉션 166건 upsert
✓ gold: law_housing 컬렉션 42건 upsert
✓ gold: law_consumer 컬렉션 58건 upsert
✓ gold: law_finance 컬렉션 812건 upsert
```

## 2-B. 데이터 공유 (S3) — 빌드 대신 받거나, 결과 올리기

`data/`(벡터DB)는 git에 안 올라가므로 **S3 공용 버킷**으로 나눈다. OC 키·임베딩 재실행 없이 남이 빌드한 걸 바로 받아 쓸 수 있다.

> ⚠️ **충돌 주의**: `silver/<분야>`·`bronze/<분야>`·`evals` 는 분야별 파일이라 각자 올려도 안 겹치지만,
> **chroma(벡터DB)·manifest 는 4분야 한 덩어리**라 여러 명이 올리면 덮어쓴다.
> → chroma는 **'빌더' 한 명(또는 EC2)만** 올린다. 그래서 명령이 스코프로 나뉨.

**최초 1회 (한 명만):** 버킷 생성
```powershell
aws s3 mb s3://youth-law-data --region us-west-2   # 버킷명은 팀이 정함(전역 고유)
```
**받기 (모두, 안전):** `.env`에 `S3_DATA_BUCKET` 넣고
```powershell
python scripts/sync_data.py pull        # S3 → 로컬 (통합 chroma + 전 분야 silver/평가)
```
**자기 분야 산출물 올리기 (각자):** `.env`의 `MY_DOMAIN` 사용(또는 분야 직접 지정)
```powershell
python scripts/sync_data.py push mine            # 내 분야 silver/bronze/evals만
python scripts/sync_data.py push mine consumer   # 분야 직접 지정도 가능
```
**통합 벡터DB 올리기 (빌더 1명만):** pull로 전 분야 silver 모은 뒤
```powershell
python scripts/build_index.py all                # 4분야 통합 빌드
python scripts/sync_data.py push corpus          # chroma + manifest 올림
```
> 정리: **각자 `push mine` → 빌더가 `pull` 후 통합 빌드 → `push corpus` → 나머지 `pull`.**
> 사전: `aws configure`로 자격증명 1회 설정.

## 3. 데이터·RAG 확인

**(a) 계약 테스트**
```powershell
$env:PYTHONUTF8=1 ; python -m pytest tests/ -q     # 21 passed 면 OK
```

**(b) 실검색 동작 확인** (stub이 아니라 진짜 벡터검색인지)
```powershell
python scripts/check_rag.py consumer        # 분야 바꿔가며: labor / housing / finance
```
→ `실모드: True` + 관련 조문(제17조 청약철회 등)이 뜨면 정상.
(이 스크립트는 셸 따옴표·콘솔 인코딩 문제 없이 어디서나 동작 — PYTHONUTF8 설정도 불필요)

**(c) manifest 확인** (어떤 법령이 어느 시행일 기준으로 들어갔는지)
```powershell
$env:PYTHONUTF8=1 ; python -c "import json; [print(k, v['enforced_date']) for k,v in json.load(open('data/manifest.json',encoding='utf-8'))['laws'].items()]"
```

## 4. 작업 시작

**(a) 개인 설정 파일** (커밋 안 됨, 자기 메모용)
```powershell
copy CLAUDE.local.md.example CLAUDE.local.md
```

**(b) 작업 브랜치** (규약: `<type>/<scope>-주제`)
```powershell
git switch main ; git pull --rebase origin main
git switch -c feat/consumer-answer      # 예시 (자기 분야로)
```

**(c) 어디를 작업하나** — 자기 분야 파일만

| 담당 | 파일 |
|---|---|
| A 노동 | `agents/labor.py` |
| B 주택 | `agents/housing.py` |
| C 소비자 | `agents/consumer.py` |
| D 금융 | `agents/finance.py` |

+ 자기 분야 평가셋 `evals/<분야>.jsonl`, 연락처는 `common/contacts.py`(공용→PR).
각 파일 상단 주석에 TODO, 전체 보드는 `docs/TODO.md`.

## 5. 협업 규약 (요약 — 전문은 CLAUDE.md)

- **커밋**: `<type>(<scope>): 한글 제목` 예) `feat(consumer): 청약철회 답변 생성`
- **푸시/PR 기준**:
  - 변경 **5개 미만 + 공용파일 아님** → `main` 직접 push OK (단 **push 전 `pytest` 통과** 필수)
  - **5개 이상 또는 공용파일**(state/graph/rag/contacts/drafter/supervisor/planner/llm/cost/pipeline) → 기능 브랜치 + PR
  - 공용 파일은 개수 무관 **항상 PR + 전원 승인**

## 6. 막히면 볼 문서
- `README.md` — 전체 개요·실행법
- `docs/STRUCTURE.md` — "이거 고치려면 어디?" 색인
- `docs/SPEC.md` — State·I/O 계약 (코드보다 우선)
- `docs/TEAM_GUIDE.md` — Day별 절차·리듬

---

> ⚠️ **현재 답변은 stub(가짜)입니다.** 검색(RAG)은 실제로 동작하지만, 실제 답변 생성(Bedrock)은
> 모델 설정 후 Day3부터 붙입니다. 그 전까지는 "검색 결과를 어떻게 다룰지" 로직 위주로 작업하세요.
