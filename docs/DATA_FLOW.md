# DATA_FLOW.md — 데이터 흐름 (메달리온 아키텍처)

> `data/`에 쌓이는 데이터가 **어떤 형태로, 어떻게 흘러가는지** 정리한 문서.
> 코드 위치: `pipeline/`(bronze·silver·gold·detect), 실행: `scripts/build_index.py`·`update_laws.py`, 검색: `common/rag.py`.

## 한 줄 요약
국가법령정보센터 API의 **원본 XML(Bronze)** → **조문 단위 JSON 청크(Silver)** → **임베딩 벡터 + 메타(Gold/Chroma)** 로 단계마다 "검색·답변에 바로 쓰는 형태"로 정제한다. `manifest.json`이 시행일을 기억해 **바뀐 법령만** 다시 처리한다.

## 흐름 한눈에

```
                                 ┌─ manifest.json (시행일 대장) ─┐
                                 │   API 현재 시행일과 비교       │
                                 ▼   → 바뀐 법령만 재처리         ▲
국가법령정보센터 API ──수집──> 🥉 BRONZE ──청킹──> 🥈 SILVER ──임베딩──> 🥇 GOLD ──검색──> 에이전트 답변
  lawSearch/lawService        원본 XML          조문 JSONL        Chroma 벡터DB     (top-k 조문 근거)
                          bronze/<분야>/*.xml  silver/<분야>.jsonl  chroma/ (law_<분야>)
```

## data/ 디렉토리 구조

```
data/                         # ★ .gitignore — 각자 build_index로 생성 (커밋 안 됨)
├── bronze/                   # 1단계: 원본 XML (가공 0)
│   ├── consumer/<법령명>.xml
│   ├── labor/   housing/   finance/
├── silver/                   # 2단계: 조문 청크 (1줄=1조문)
│   └── <분야>.jsonl          # 현재(10개 법령): labor 166 / housing 42 / consumer 192 / finance 812
├── chroma/                   # 3단계(Gold): 벡터DB
│   ├── chroma.sqlite3        # 문서·메타·임베딩 본체
│   └── <uuid>/ × 4           # 분야별 HNSW 인덱스 폴더
└── manifest.json             # 증분 감지용 시행일 대장
```

---

## 단계별 데이터 형태 — 제1조(목적) 하나가 통과하는 모습

### 🥉 1. Bronze — `pipeline/bronze.py`
국가법령정보센터 API 응답 XML을 **가공 없이 그대로** 저장.
- 목록 API(`lawSearch.do`)로 MST·시행일 메타 조회 → 본문 API(`lawService.do`)로 전체 XML
- 저장 위치: `data/bronze/<분야>/<법령명>.xml`
- 내부 구조: `<법령>` 안에 여러 `<조문단위>`, 각각 아래 자식을 가짐

```xml
<조문단위>
  <조문번호>1</조문번호>
  <조문여부>조문</조문여부>        <!-- "전문"(장·절 제목)이면 Silver에서 스킵 -->
  <조문가지번호>2</조문가지번호>   <!-- 있으면 제N조의2 (없는 경우가 대부분) -->
  <조문제목>목적</조문제목>
  <조문내용>제1조(목적) 이 법은 …</조문내용>
  <항>…</항> <호>…</호> <목>…</목>  <!-- 하위 항·호·목 -->
</조문단위>
```
> **왜 원본을 보존하나**: 청킹 전략을 바꿔도 API 재호출 없이 Silver만 다시 돌리면 된다.
> ⚠️ API 호출은 https + User-Agent + 재시도 필수 (기본 파이썬 UA 거부·간헐 연결 리셋).

### 🥈 2. Silver — `pipeline/silver.py`
`<조문단위>` 1개 → JSON 1줄(jsonl). **답변의 출처표시 재료가 여기서 만들어진다.**
- `조문여부="전문"`(장·절 제목) 스킵, `조문가지번호` 반영(제43조의2) → 중복 id 방지
- 저장 위치: `data/silver/<분야>.jsonl`

```json
{
  "law_name": "전자상거래 등에서의 소비자보호에 관한 법률",
  "article": "제1조",
  "title": "목적",
  "text": "목적. 제1조(목적) 이 법은 …",   // ← 실제 임베딩·표시되는 본문
  "enforced_date": "20260120",            // 시행일 (현행법 신뢰성)
  "source_url": "https://www.law.go.kr/법령/전자상거래…"
}
```

### 🥇 3. Gold (Chroma) — `pipeline/gold.py`
`text`를 임베딩(jhgan/ko-sroberta-multitask, **768차원**)해 컬렉션 `law_<분야>`에 upsert.

```
id        = "전자상거래 등에서의 소비자보호에 관한 법률_제1조"   ← 고유키(법령명_제N조)
document  = "목적. 제1조(목적) 이 법은 …"                        (원문)
embedding = [0.235, 0.132, 0.431, -0.043, …]   ← 768개 실수
metadata  = {law_name, article, enforced_date, source_url}
```
- 실체: `data/chroma/chroma.sqlite3` + 분야별 HNSW 인덱스 폴더
- **id가 `법령명_제N조`** 라 같은 조문 재적재 시 덮어씀 → 증분 갱신과 자연 호환
- 백엔드는 env `RAG_BACKEND`로 선택(common/rag.py와 한 쌍): 로컬·CI는 **Chroma**, EC2 운영은 **RDS pgvector**(`law_chunks` 테이블, gold.py `load_pgvector` — 분야별 삭제 후 삽입으로 멱등). 같은 silver를 양쪽에 적재.

### 📋 4. Manifest — `pipeline/detect.py`
적재한 법령의 시행일을 기록 → 증분 감지의 기준.

```json
"전자상거래…법률": {
  "mst": "282793", "law_id": "009318",
  "enforced_date": "20260120",          // update_laws.py가 API 현재값과 비교
  "bronze_path": "data/bronze/consumer/…xml", "domain": "consumer"
}
```

---

## 검색 시 흐름 (질문 → 답변) — `common/rag.py`
```
"인터넷 쇼핑 환불…"  → ko-sroberta(768d)  → law_consumer 최근접 top-k
  → RetrievedChunk(law_name·article·enforced_date·text·source_url·score)
  → 에이전트가 그 조문 안에서만 답변 (검색 밖 내용 금지 = 환각 방지)
```
→ Silver의 메타(시행일·출처)가 그대로 답변에 붙어 **"출처·시행일 표시" 차별점**이 만들어진다.

## 핵심 원리 4가지
1. **원본 보존(Bronze)** — 청킹 바꿔도 재호출 없이 Silver만 재생성.
2. **고유 id(`법령명_제N조`)** — 재적재 시 덮어쓰기 → 증분과 호환, 중복 적재 방지.
3. **메타가 차별점의 재료** — 시행일·출처 URL이 답변 신뢰성으로 직결.
4. **질문도 같은 임베딩 모델** — 768d 동일 공간에서 최근접 검색.

## 실행 / 재생성
```bash
# Windows는 먼저:  set PYTHONUTF8=1   (PowerShell: $env:PYTHONUTF8=1)
python scripts/build_index.py all     # 최초 전체 구축 (bronze→silver→gold)
python scripts/update_laws.py         # 증분 갱신 — 시행일 바뀐 법령만 (주1회 배치)
python scripts/check_rag.py consumer  # 적재·검색 확인 (실모드/조문수/샘플 검색)
```
> 수집 법령을 늘리려면 `pipeline/config.py`의 `LAW_LIST`에 정식 법령명 추가(공용 파일 → PR).

## 코드 위치 맵
| 단계 | 파일 | 역할 |
|---|---|---|
| Bronze | `pipeline/bronze.py` | API 수집 → 원본 XML 저장 |
| Silver | `pipeline/silver.py` | XML 파싱 → 조문 청크(jsonl) |
| Gold | `pipeline/gold.py` | 임베딩 → Chroma upsert |
| 증분 | `pipeline/detect.py` | manifest 시행일 비교 |
| 설정 | `pipeline/config.py` | 경로 + `LAW_LIST`(수집 법령) |
| 검색 | `common/rag.py` | 질의 임베딩 → top-k 검색 |
| 실행 | `scripts/build_index.py`·`update_laws.py` | 최초 구축 / 증분 배치 |
