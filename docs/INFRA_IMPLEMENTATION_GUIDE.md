# 인프라 구현 가이드

> 담당자용 실행 문서. 기획서에 적힌 EC2, S3, RDS, Airflow, Terraform, 앱 연결 범위를
> 실제 MVP 구현과 운영 확장 설계로 나누어 정리한다.

## 0. 목표와 발표 기준

### 목표

이번 인프라 구현의 목표는 "기획서에 적힌 인프라를 과장 없이 실제 데모 가능한 수준으로
증명"하는 것이다.

MVP 기준으로는 다음을 실제로 보여준다.

- EC2에서 FastAPI/Jinja 웹 화면 또는 Streamlit 데모 UI 실행
- EC2에서 Chroma 벡터DB 기반 RAG 데이터 구축
- S3에 법령 원본, 청킹 결과, Chroma 산출물, 평가 결과 백업
- RDS PostgreSQL에 상담 로그, 비용 로그, 평가 결과 저장
- Airflow에서 주간 법령 증분 갱신 DAG 실행
- Terraform으로 주요 AWS 리소스 재현 가능하게 정의

확장 설계 기준으로는 다음을 명확히 분리해서 설명한다.

- 현재 검색 엔진: Chroma
- 운영 확장 검색 엔진: RDS PostgreSQL + pgvector
- 현재 배포 형태: EC2 단일 서버
- 운영 확장 형태: EC2/App 서버 + RDS + S3 + IaC + 배치 스케줄러

### 발표용 한 문장

> 이번 MVP는 EC2 단일 서버에서 FastAPI, Streamlit, LangGraph, Chroma, Airflow를 운영하는
> 구조입니다. 법령 원본과 인덱스 산출물은 S3에 백업하고, 상담 로그와 비용/평가 지표는
> RDS PostgreSQL에 저장하도록 구성했습니다. 벡터 검색은 데모 안정성을 위해 Chroma를
> 사용했고, RDS PostgreSQL의 pgvector 확장으로 벡터 인덱스를 통합하는 스키마까지
> 설계했습니다. Terraform으로 EC2, S3, RDS, 보안 그룹을 재현 가능하게 만들고, 발표 후
> destroy로 비용을 정리할 수 있습니다.

### 공식 참고 문서

- EC2 Security Groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html
- S3 Getting Started: https://docs.aws.amazon.com/AmazonS3/latest/userguide/GetStartedWithS3.html
- RDS for PostgreSQL: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html
- RDS PostgreSQL Extensions: https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html
- Terraform AWS Provider: https://registry.terraform.io/providers/hashicorp/aws/latest
- DuckDNS: https://www.duckdns.org/about.jsp
- DuckDNS FAQ: https://www.duckdns.org/faqs.jsp
- Certbot Nginx: https://certbot.eff.org/instructions?ws=nginx&os=snap
- GitHub Actions Workflow Syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub Actions Secrets: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

## 1. EC2 구현 가이드

### 역할

EC2는 이번 MVP의 중심 서버다.

- FastAPI 웹서비스 실행
- Streamlit 발표 데모 UI 실행
- Chroma 벡터DB 로컬 저장
- 법령 데이터 파이프라인 실행
- Airflow 또는 cron 배치 실행
- Bedrock 호출 실행 환경 제공

### 권장 사양

| 항목 | 권장값 | 이유 |
|---|---|---|
| Region | us-west-2 | `.env.example` 기본값과 일치, Bedrock 사용 고려 |
| AMI | Ubuntu 24.04 LTS | Python 환경 구성 쉬움 |
| Instance | t3.large | 임베딩 모델 + Chroma + Airflow 동시 실행 여유 |
| 최소 Instance | t3.medium | 가능하지만 Airflow와 임베딩 동시 실행 시 메모리 빠듯 |
| EBS | gp3 30GB 이상 | Chroma, 모델 캐시, 로그 저장 |
| Elastic IP | 선택 | 발표 URL 고정이 필요하면 사용 |

### 보안 그룹

EC2 보안 그룹은 필요한 포트만 연다.

| 포트 | 용도 | 평소 Source | 발표 시 Source |
|---|---|---|---|
| 22 | SSH | 내 IP `/32` | 내 IP `/32` |
| 8000 | FastAPI/Jinja | 내 IP 또는 팀 IP | 필요 시 `0.0.0.0/0` |
| 8501 | Streamlit | 내 IP 또는 팀 IP | 필요 시 `0.0.0.0/0` |
| 8080 | Airflow UI | 내 IP 또는 팀 IP | 원칙적으로 공개하지 않음 |

주의:

- 발표가 끝나면 `8000`, `8501` 공개 규칙을 다시 내 IP로 제한한다.
- RDS는 퍼블릭 오픈하지 않고 EC2 보안 그룹에서만 접근하게 한다.
- SSH는 절대 `0.0.0.0/0`로 열지 않는다.

### IAM Role

EC2에는 Access Key를 직접 넣는 것보다 IAM Role을 붙이는 것이 좋다.

최소 권한:

- S3 read/write: 프로젝트 버킷의 `data/*`, `logs/*`, `evals/*`
- Bedrock invoke: 사용하는 Claude 모델 호출
- CloudWatch logs: 선택 사항

발표용 최소 정책 범위 예시:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::youth-law-artifacts-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::youth-law-artifacts-*/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

실운영에서는 `Resource`를 실제 모델 ARN과 실제 버킷 ARN으로 좁힌다.

### EC2 서버 셋업

SSH 접속 후 실행한다.

> ⚠️ Ubuntu 24.04(Noble)는 기본 저장소에 `python3.11`이 없다(기본 Python이 3.12).
> 이 프로젝트는 3.11 고정이므로(Airflow constraints도 3.11 기준) `deadsnakes` PPA로 설치한다.
> 그냥 `apt install python3.11` 하면 `Unable to locate package python3.11`로 실패한다.

```bash
sudo apt update
sudo apt install -y software-properties-common git unzip

# Ubuntu 24.04에는 python3.11이 기본 제공되지 않으므로 deadsnakes PPA 추가
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 설치 확인 (3.11.x 출력되어야 함)
python3.11 --version

git clone <팀_레포_URL>
cd youth_law

python3.11 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
# requirements-ec2.txt = requirements.txt + 실검색(Chroma/임베딩)·RDS·S3 의존성.
# (Airflow는 엄격한 constraints 때문에 4번 가이드에서 별도 설치)
pip install -r requirements-ec2.txt
```

환경변수 구성:

```bash
cp .env.example .env
nano .env
```

필수 값:

```env
LAW_GO_KR_OC=국가법령정보센터_OC
AWS_REGION=us-west-2
BEDROCK_MODEL_MAIN=답변생성용_모델_ID
BEDROCK_MODEL_SMALL=분류_검증용_모델_ID
LANGSMITH_API_KEY=선택
LANGCHAIN_TRACING_V2=true
```

Python 코드에서 `python-dotenv`를 사용하므로 `.env`를 자동 로드한다. 쉘 명령에서 AWS CLI를
바로 쓸 때만 별도 AWS 설정이 필요하다.

### 데이터 구축

```bash
source .venv/bin/activate
python scripts/build_index.py all
```

성공 기준:

- `data/bronze/<domain>/*.xml` 생성
- `data/silver/<domain>.jsonl` 생성
- `data/chroma/` 생성
- `data/manifest.json`에 법령별 시행일 기록

확인:

```bash
ls -al data
cat data/manifest.json
python - <<'PY'
from common.rag import DomainRAG
for d in ["labor", "housing", "consumer", "finance"]:
    rag = DomainRAG(d)
    print(d, "is_real=", rag.is_real)
PY
```

### 앱 실행

FastAPI:

```bash
source .venv/bin/activate
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

확인:

```bash
curl http://localhost:8000/health
```

브라우저:

```text
http://<EC2_PUBLIC_IP>:8000
http://<EC2_PUBLIC_IP>:8000/docs
```

Streamlit:

```bash
source .venv/bin/activate
streamlit run app/ui_streamlit.py --server.port 8501 --server.address 0.0.0.0
```

브라우저:

```text
http://<EC2_PUBLIC_IP>:8501
```

### systemd 서비스 선택 구성

발표 중 터미널이 끊겨도 앱이 유지되게 하려면 systemd를 사용한다.

FastAPI 서비스:

```bash
sudo nano /etc/systemd/system/youth-law-api.service
```

```ini
[Unit]
Description=Youth Law FastAPI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/youth_law
Environment="PYTHONPATH=/home/ubuntu/youth_law"
ExecStart=/home/ubuntu/youth_law/.venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Streamlit 서비스:

```bash
sudo nano /etc/systemd/system/youth-law-streamlit.service
```

```ini
[Unit]
Description=Youth Law Streamlit
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/youth_law
Environment="PYTHONPATH=/home/ubuntu/youth_law"
ExecStart=/home/ubuntu/youth_law/.venv/bin/streamlit run app/ui_streamlit.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

적용:

```bash
sudo systemctl daemon-reload
sudo systemctl enable youth-law-api
sudo systemctl enable youth-law-streamlit
sudo systemctl start youth-law-api
sudo systemctl start youth-law-streamlit
sudo systemctl status youth-law-api
sudo systemctl status youth-law-streamlit
```

### DuckDNS 무료 도메인 설정

발표용 URL을 실제 서비스처럼 보이게 하려면 유료 도메인을 바로 구매하지 않아도 된다.
MVP 발표 기준에서는 DuckDNS 무료 서브도메인을 EC2 public IP에 연결해서 다음처럼 사용할 수 있다.

```text
https://youthlaw-demo.duckdns.org  -> 사용자 상담 서비스, FastAPI/Jinja
https://youthlaw-ops.duckdns.org   -> 엔지니어 대시보드, Streamlit
```

이 방식의 발표 메시지는 다음처럼 잡는다.

> 발표용 MVP는 무료 DDNS인 DuckDNS를 사용해 EC2 public IP에 서비스 URL을 연결했습니다.
> 실제 운영 전환 시에는 `youthlaw.kr` 같은 유료 도메인을 구매하고 Route 53 또는 Cloudflare DNS로
> `demo.youthlaw.kr`, `ops.youthlaw.kr` 구조를 동일하게 옮길 수 있습니다.

#### 왜 DuckDNS를 쓰는가

DuckDNS는 `duckdns.org` 하위 서브도메인을 사용자가 지정한 IP로 연결해주는 무료 Dynamic DNS다.
EC2를 재시작하면 public IP가 바뀔 수 있으므로, 발표 준비 단계에서 고정된 URL을 확보하는 데 적합하다.

장점:

- 무료로 `*.duckdns.org` 주소를 만들 수 있다.
- EC2 public IP가 바뀌어도 DuckDNS 레코드만 갱신하면 발표 URL을 유지할 수 있다.
- ngrok처럼 터널 실행 프로세스에 의존하지 않고, EC2에 직접 연결되는 구조를 보여줄 수 있다.
- Nginx와 Certbot을 붙이면 HTTPS 주소로 발표할 수 있다.

주의점:

- `duckdns.org` 하위 도메인이므로 실제 자사 도메인처럼 보이진 않는다.
- EC2 보안 그룹에서 80, 443 포트를 열어야 HTTPS 발급과 외부 접속이 가능하다.
- 발표 후에는 80, 443 공개 상태를 유지할지 정리할지 결정해야 한다.
- 무료 서비스이므로 장기 운영 SLA를 기대하는 용도는 아니다.

#### 설정 순서

1. DuckDNS 계정 생성

   DuckDNS에 로그인한 뒤 다음 서브도메인을 만든다.

   ```text
   youthlaw-demo
   youthlaw-ops
   ```

   생성 후 각각 EC2 public IP를 바라보게 설정한다.

   ```text
   youthlaw-demo.duckdns.org -> EC2_PUBLIC_IP
   youthlaw-ops.duckdns.org  -> EC2_PUBLIC_IP
   ```

2. EC2 보안 그룹 수정

   HTTPS 인증서 발급과 웹 접속을 위해 다음 inbound 규칙을 추가한다.

   | 포트 | 용도 | Source |
   |---|---|---|
   | 80 | Certbot HTTP 인증, HTTP 접속 | `0.0.0.0/0` |
   | 443 | HTTPS 접속 | `0.0.0.0/0` |

   발표 후에는 8000, 8501을 직접 외부에 열어두지 않고 Nginx를 통해 443만 공개하는 구성이 더 깔끔하다.

3. Nginx 설치

   EC2에서 실행한다.

   ```bash
   sudo apt update
   sudo apt install -y nginx
   sudo systemctl enable nginx
   sudo systemctl start nginx
   ```

4. FastAPI용 Nginx 설정

   ```bash
   sudo nano /etc/nginx/sites-available/youthlaw-demo
   ```

   ```nginx
   server {
       listen 80;
       server_name youthlaw-demo.duckdns.org;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

5. Streamlit용 Nginx 설정

   ```bash
   sudo nano /etc/nginx/sites-available/youthlaw-ops
   ```

   ```nginx
   server {
       listen 80;
       server_name youthlaw-ops.duckdns.org;

       location / {
           proxy_pass http://127.0.0.1:8501;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_read_timeout 86400;
       }
   }
   ```

6. Nginx 설정 활성화

   ```bash
   sudo ln -s /etc/nginx/sites-available/youthlaw-demo /etc/nginx/sites-enabled/youthlaw-demo
   sudo ln -s /etc/nginx/sites-available/youthlaw-ops /etc/nginx/sites-enabled/youthlaw-ops
   sudo nginx -t
   sudo systemctl reload nginx
   ```

7. HTTP 접속 확인

   브라우저에서 먼저 HTTP 주소가 열리는지 확인한다.

   ```text
   http://youthlaw-demo.duckdns.org
   http://youthlaw-ops.duckdns.org
   ```

8. Certbot으로 HTTPS 인증서 발급

   Certbot 공식 가이드는 snap 기반 설치를 권장한다.

   ```bash
   sudo snap install core
   sudo snap refresh core
   sudo snap install --classic certbot
   sudo ln -s /snap/bin/certbot /usr/bin/certbot

   sudo certbot --nginx -d youthlaw-demo.duckdns.org -d youthlaw-ops.duckdns.org
   ```

   발급 과정에서 이메일, 약관 동의, HTTP -> HTTPS 리다이렉트 여부를 묻는다.
   발표용이면 HTTPS 리다이렉트를 선택한다.

9. HTTPS 접속 확인

   ```text
   https://youthlaw-demo.duckdns.org
   https://youthlaw-ops.duckdns.org
   ```

10. 자동 갱신 테스트

   Let's Encrypt 인증서는 주기적으로 갱신되어야 하므로 dry run을 확인한다.

   ```bash
   sudo certbot renew --dry-run
   ```

#### EC2 IP 변경 시 DuckDNS 갱신

Elastic IP를 붙이지 않은 EC2는 중지 후 재시작 시 public IP가 바뀔 수 있다.
IP가 바뀌면 DuckDNS 화면에서 수동으로 IP를 바꾸거나, update URL을 cron으로 등록한다.

DuckDNS update URL 형식:

```text
https://www.duckdns.org/update?domains=<SUBDOMAIN>&token=<TOKEN>&ip=<EC2_PUBLIC_IP>
```

예시:

```bash
curl "https://www.duckdns.org/update?domains=youthlaw-demo,youthlaw-ops&token=YOUR_DUCKDNS_TOKEN&ip="
```

`ip=`를 비워두면 DuckDNS가 요청을 보낸 서버의 public IP를 감지한다.
EC2에서 직접 실행한다면 이 방식이 가장 단순하다.

cron 등록 예시:

```bash
crontab -e
```

```cron
*/5 * * * * curl -fsS "https://www.duckdns.org/update?domains=youthlaw-demo,youthlaw-ops&token=YOUR_DUCKDNS_TOKEN&ip=" >/tmp/duckdns.log 2>&1
```

#### 발표자료에 넣을 문구

```text
MVP 발표 환경
- 사용자 서비스: https://youthlaw-demo.duckdns.org
- 엔지니어 대시보드: https://youthlaw-ops.duckdns.org
- 배포 방식: EC2 단일 서버 + Nginx reverse proxy + DuckDNS 무료 DDNS + HTTPS
- 운영 확장안: 유료 도메인 youthlaw.kr 구매 후 demo.youthlaw.kr / ops.youthlaw.kr로 전환
```

이렇게 말하면 "도메인까지 운영 수준으로 완성했다"가 아니라,
"MVP 발표 환경은 무료 DDNS로 구현했고, 운영 도메인 전환 구조까지 설계했다"로 정직하게 설명할 수 있다.

### EC2 검증 체크리스트

- [ ] `/health`가 `{"status":"ok"}` 반환
- [ ] `/docs` Swagger UI 접속
- [ ] Streamlit UI 접속
- [ ] 대표 질문 1개 응답 성공
- [ ] `data/chroma` 존재
- [ ] `DomainRAG.is_real=True` 확인
- [ ] 보안 그룹에서 발표용 공개 포트가 과하게 열려 있지 않음
- [ ] `https://youthlaw-demo.duckdns.org` 접속
- [ ] `https://youthlaw-ops.duckdns.org` 접속
- [ ] `sudo certbot renew --dry-run` 성공

## 2. S3 구현 가이드

### 역할

S3는 재현성과 백업을 위한 산출물 저장소다.

- Bronze: 국가법령정보센터 원본 XML
- Silver: 조문 단위 JSONL
- Gold: Chroma 벡터DB 디렉터리 백업
- 평가 결과: `evals/results`
- 배치 로그: update/evaluate 실행 로그

### 버킷 설계

버킷 이름 예시:

```text
youth-law-artifacts-<account-or-team>
```

S3 버킷 이름은 전역 유일해야 하므로 팀명, 계정 ID 일부, 날짜 등을 붙인다.

권장 설정:

- Region: `us-west-2`
- Block Public Access: 전체 활성화
- Object Ownership: Bucket owner enforced
- Default encryption: SSE-S3
- Versioning: 선택, 발표용이면 비활성도 가능

### 객체 경로

```text
s3://<bucket>/data/bronze/
s3://<bucket>/data/silver/
s3://<bucket>/data/chroma/
s3://<bucket>/data/manifest.json
s3://<bucket>/evals/results/
s3://<bucket>/logs/update/
s3://<bucket>/logs/evaluate/
```

### AWS CLI 설정 확인

EC2 IAM Role을 사용한다면 별도 access key 없이 동작해야 한다.

```bash
aws sts get-caller-identity
aws s3 ls
```

### 최초 업로드

```bash
BUCKET=<bucket-name>

aws s3 sync data/bronze s3://$BUCKET/data/bronze
aws s3 sync data/silver s3://$BUCKET/data/silver
aws s3 sync data/chroma s3://$BUCKET/data/chroma
aws s3 cp data/manifest.json s3://$BUCKET/data/manifest.json
aws s3 sync evals/results s3://$BUCKET/evals/results
```

### 복원

새 EC2 또는 깨끗한 환경에서 S3 백업을 복원할 수 있어야 한다.

```bash
BUCKET=<bucket-name>

mkdir -p data
aws s3 sync s3://$BUCKET/data/bronze data/bronze
aws s3 sync s3://$BUCKET/data/silver data/silver
aws s3 sync s3://$BUCKET/data/chroma data/chroma
aws s3 cp s3://$BUCKET/data/manifest.json data/manifest.json
```

복원 확인:

```bash
python - <<'PY'
from common.rag import DomainRAG
for d in ["labor", "housing", "consumer", "finance"]:
    print(d, DomainRAG(d).is_real)
PY
```

### 배치 후 자동 백업 스크립트

추가 파일을 만들 경우 예시는 다음과 같다.

```bash
mkdir -p logs
nano scripts/sync_s3.sh
```

```bash
#!/usr/bin/env bash
set -euo pipefail

BUCKET="${S3_BUCKET:?S3_BUCKET is required}"

aws s3 sync data/bronze "s3://${BUCKET}/data/bronze"
aws s3 sync data/silver "s3://${BUCKET}/data/silver"
aws s3 sync data/chroma "s3://${BUCKET}/data/chroma"
aws s3 cp data/manifest.json "s3://${BUCKET}/data/manifest.json"
aws s3 sync evals/results "s3://${BUCKET}/evals/results"
```

실행:

```bash
chmod +x scripts/sync_s3.sh
S3_BUCKET=<bucket-name> scripts/sync_s3.sh
```

### S3 검증 체크리스트

- [ ] 버킷 public access block 활성화
- [ ] EC2 IAM Role로 업로드 가능
- [ ] `data/bronze`, `data/silver`, `data/chroma` 업로드됨
- [ ] 새 환경에서 S3 복원 가능
- [ ] 발표 자료에 S3 객체 목록 캡처 가능

### 발표 포인트

> 법령 API를 매번 재호출하지 않아도, S3 백업본에서 Bronze/Silver/Gold 레이어를 복원할 수
> 있게 했습니다. 데이터 파이프라인 산출물을 클라우드 객체 저장소에 보관해 팀원이 같은
> 인덱스를 재사용할 수 있습니다.

## 3. RDS 구현 가이드

### 역할

RDS PostgreSQL은 운영 로그와 평가 지표 저장소다.

MVP에서 먼저 구현할 것:

- 상담 로그 저장
- 분야 분류 결과 저장
- 검증 리포트 저장
- Bedrock 비용/토큰 사용량 저장
- 평가 스코어카드 저장

확장 설계:

- `pgvector`로 Chroma 벡터 인덱스 통합
- 상담 이력 기반 사용량 분석
- 비용/품질 대시보드 연결

### RDS 생성 권장값

| 항목 | 권장값 |
|---|---|
| Engine | PostgreSQL |
| Version | pgvector 지원 버전 |
| Instance | db.t3.micro 또는 db.t4g.micro |
| Storage | gp3 20GB |
| Public access | No 권장 |
| Subnet | private subnet 권장 |
| Security group | EC2 보안 그룹에서만 5432 허용 |
| Backup retention | 1~7일 |

MVP 시간 절약을 위해 public access를 잠깐 켤 수도 있지만, 발표 전에는 EC2에서만 접근하는
구조로 정리하는 것이 좋다.

### RDS 보안 그룹

RDS inbound:

| 포트 | Source |
|---|---|
| 5432 | EC2 Security Group |

절대 `0.0.0.0/0`로 열지 않는다.

### RDS 접속 테스트

EC2에 PostgreSQL client 설치:

```bash
sudo apt install -y postgresql-client
```

접속:

```bash
psql "host=<rds-endpoint> port=5432 dbname=youthlaw user=<user> password=<password> sslmode=require"
```

### 환경변수

`.env`에 추가:

```env
DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/youthlaw
```

비밀번호가 포함되므로 `.env`는 절대 커밋하지 않는다.

### 최소 테이블

```sql
create table if not exists consultation_logs (
  id bigserial primary key,
  created_at timestamptz default now(),
  question text not null,
  domains text[],
  in_scope boolean,
  final_answer text,
  answer_blocks jsonb,
  verification_report jsonb
);

create table if not exists llm_usage_logs (
  id bigserial primary key,
  created_at timestamptz default now(),
  task text not null,
  tier text,
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric(12,6) default 0
);

create table if not exists eval_scorecards (
  id bigserial primary key,
  created_at timestamptz default now(),
  domain text not null,
  retrieval jsonb,
  grounding jsonb,
  cost jsonb,
  raw_result jsonb
);
```

### pgvector 확장 설계

RDS PostgreSQL이 pgvector를 지원하면 다음을 적용할 수 있다.

```sql
create extension if not exists vector;

create table if not exists law_chunks (
  id text primary key,
  domain text not null,
  law_name text not null,
  article text not null,
  enforced_date text,
  source_url text,
  content text not null,
  embedding vector(768)
);
```

인덱스 예시:

```sql
create index if not exists law_chunks_embedding_hnsw
on law_chunks using hnsw (embedding vector_cosine_ops);
```

주의:

- 현재 코드의 운영 검색은 Chroma다.
- pgvector는 발표에서 "운영 통합 설계" 또는 "확장 구현"으로 설명한다.
- 시간이 부족하면 로그 테이블까지만 실제 구현하고, pgvector는 스키마와 근거를 제시한다.

### 앱 연결 최소 구현 방향

새 파일을 추가한다면 다음 구조를 권장한다.

```text
common/db.py
common/logging_store.py
scripts/init_db.py
```

`common/db.py` 역할:

- `DATABASE_URL` 읽기
- SQLAlchemy engine 생성
- DB 미설정 시 앱이 죽지 않고 로그만 건너뛰게 처리

`common/logging_store.py` 역할:

- `save_consultation(result)`
- `save_usage(record)`
- `save_eval_scorecard(result)`

`scripts/init_db.py` 역할:

- 위 SQL 테이블 생성
- RDS 연결 검증

앱 연결 포인트:

- [app/service.py](../app/service.py)의 `consult()` 끝에서 상담 로그 저장
- [common/cost.py](../common/cost.py)의 `tracker.record()` 또는 평가 종료 시 비용 로그 저장
- [scripts/evaluate.py](../scripts/evaluate.py)의 `run()` 결과를 RDS에 저장

### RDS 검증 쿼리

```sql
select count(*) from consultation_logs;
select created_at, question, domains, in_scope from consultation_logs order by id desc limit 5;

select count(*) from llm_usage_logs;
select task, sum(input_tokens), sum(output_tokens), sum(cost_usd) from llm_usage_logs group by task;

select domain, created_at, retrieval, grounding from eval_scorecards order by id desc limit 5;
```

### RDS 검증 체크리스트

- [ ] EC2에서 RDS 접속 가능
- [ ] 로컬 PC에서는 RDS 접속 차단 또는 제한
- [ ] `consultation_logs`에 상담 1건 이상 저장
- [ ] `eval_scorecards`에 평가 결과 1건 이상 저장
- [ ] `pgvector` 지원 여부 확인
- [ ] 발표에서 Chroma MVP와 pgvector 확장 설계를 분리 설명

### 발표 포인트

> RDS는 이번 MVP에서 상담 로그, 비용 로그, 평가 스코어카드를 저장하는 운영 지표 저장소로
> 붙였습니다. 벡터 검색은 현재 Chroma가 담당하지만, RDS PostgreSQL의 pgvector 확장을
> 사용하면 같은 DB에 법령 청크와 임베딩까지 통합할 수 있도록 스키마를 준비했습니다.

## 4. Airflow 구현 가이드

### 역할

Airflow는 법령 데이터 증분 갱신을 스케줄링한다.

현재 레포에는 이미 DAG가 있다.

```text
airflow/dags/law_update_dag.py
```

DAG 구조:

```text
update_labor
update_housing
update_consumer
update_finance
      ↓
   summary
```

각 분야 task는 [scripts/update_laws.py](../scripts/update_laws.py)의 `update_domain()`을 호출한다.

### 설치

EC2에서 실행:

```bash
cd /home/ubuntu/youth_law
source .venv/bin/activate

pip install "apache-airflow==2.10.*" --constraint \
  "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.0/constraints-3.11.txt"
```

환경변수:

```bash
export AIRFLOW_HOME=/home/ubuntu/airflow
export PYTHONPATH=/home/ubuntu/youth_law
```

영구 적용:

```bash
echo 'export AIRFLOW_HOME=/home/ubuntu/airflow' >> ~/.bashrc
echo 'export PYTHONPATH=/home/ubuntu/youth_law' >> ~/.bashrc
source ~/.bashrc
```

초기화:

```bash
airflow db migrate
airflow users create \
  --username admin \
  --firstname youth \
  --lastname law \
  --role Admin \
  --email admin@example.com
```

### DAG 폴더 설정

`$AIRFLOW_HOME/airflow.cfg`에서 수정:

```text
dags_folder = /home/ubuntu/youth_law/airflow/dags
```

또는 환경변수:

```bash
export AIRFLOW__CORE__DAGS_FOLDER=/home/ubuntu/youth_law/airflow/dags
```

### 실행

터미널 2개에서 각각 실행:

```bash
airflow webserver --port 8080
```

```bash
airflow scheduler
```

간단 데모용으로는 standalone도 가능하다.

```bash
airflow standalone
```

접속:

```text
http://<EC2_PUBLIC_IP>:8080
```

### DAG 확인

```bash
airflow dags list | grep law_incremental_update
airflow tasks list law_incremental_update
```

수동 실행:

```bash
airflow dags trigger law_incremental_update
```

로그 확인:

```bash
airflow dags state law_incremental_update <execution-date>
```

웹 UI에서 확인할 것:

- DAG가 import error 없이 보이는지
- `@weekly` 스케줄인지
- 4개 분야 task가 병렬로 보이는지
- `summary`까지 성공하는지

### cron 대안

Airflow가 무겁거나 시간이 부족하면 cron으로도 충분하다.

```bash
mkdir -p logs
crontab -e
```

```cron
0 6 * * 1 cd /home/ubuntu/youth_law && /home/ubuntu/youth_law/.venv/bin/python scripts/update_laws.py >> logs/update.log 2>&1
```

발표에서는 이렇게 설명한다.

> Airflow DAG를 준비했고, 운영 환경에서는 Airflow로 주간 증분 갱신을 실행합니다. 비용과
> 메모리를 아끼는 MVP 운영에서는 동일 진입점인 `scripts/update_laws.py`를 cron으로도
> 실행할 수 있게 했습니다.

### Airflow 검증 체크리스트

- [ ] Airflow UI 접속 가능
- [ ] `law_incremental_update` DAG 표시
- [ ] DAG import error 없음
- [ ] 수동 trigger 성공
- [ ] 각 분야 task 성공
- [ ] 2회차 실행 시 변경 없음 스킵 확인
- [ ] 배치 후 S3 sync 또는 로그 백업 수행

### 발표 포인트

> 법령은 매일 변하는 데이터가 아니므로 주 1회 증분 갱신으로 충분합니다. Airflow DAG는
> 분야별 갱신 task를 병렬 실행하고, manifest의 시행일을 비교해 변경된 법령만 Bronze,
> Silver, Gold 레이어로 다시 처리합니다.

## 5. Terraform 구현 가이드

### 역할

Terraform은 인프라 재현성과 비용 정리를 위한 IaC다.

발표에서 보여줄 핵심:

- 콘솔 수작업만 한 것이 아니라 리소스를 코드로 정의했다.
- 팀원이 같은 인프라를 재현할 수 있다.
- 발표 후 `terraform destroy`로 비용을 정리할 수 있다.

### 권장 폴더 구조

```text
infra/
  terraform/
    main.tf
    variables.tf
    outputs.tf
    terraform.tfvars.example
    README.md
```

실제 비밀 값이 들어가는 파일은 커밋하지 않는다.

```text
infra/terraform/terraform.tfvars
infra/terraform/*.tfstate
infra/terraform/*.tfstate.backup
infra/terraform/.terraform/
```

위 항목은 `.gitignore`에 포함한다.

### Terraform 대상 리소스

MVP:

- Security Group
- EC2 instance
- IAM role/profile for EC2
- S3 bucket
- RDS PostgreSQL

선택:

- Elastic IP
- 별도 VPC/subnet
- CloudWatch log group

### variables.tf 예시

```hcl
variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "project_name" {
  type    = string
  default = "youth-law"
}

variable "allowed_ip_cidr" {
  type        = string
  description = "SSH/API/Airflow access CIDR, for example 1.2.3.4/32"
}

variable "ec2_key_name" {
  type        = string
  description = "Existing EC2 key pair name"
}

variable "db_username" {
  type    = string
  default = "youthlaw"
}

variable "db_password" {
  type      = string
  sensitive = true
}
```

### main.tf 최소 예시

아래는 개념 예시다. 실제 AMI ID는 Region에 맞게 조회하거나 data source를 사용한다.

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "app" {
  name        = "${var.project_name}-app-sg"
  description = "Youth Law app security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ip_cidr]
  }

  ingress {
    description = "FastAPI"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ip_cidr]
  }

  ingress {
    description = "Streamlit"
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ip_cidr]
  }

  ingress {
    description = "Airflow UI"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Youth Law RDS security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "PostgreSQL from app EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.project_name}-artifacts-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "postgres" {
  identifier             = "${var.project_name}-postgres"
  engine                 = "postgres"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  db_name                = "youthlaw"
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true
  publicly_accessible    = false
}

resource "aws_instance" "app" {
  ami                    = "<ubuntu-24-04-ami-id>"
  instance_type          = "t3.large"
  key_name               = var.ec2_key_name
  vpc_security_group_ids = [aws_security_group.app.id]

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.project_name}-app"
  }
}
```

### outputs.tf 예시

```hcl
output "ec2_public_ip" {
  value = aws_instance.app.public_ip
}

output "fastapi_url" {
  value = "http://${aws_instance.app.public_ip}:8000"
}

output "streamlit_url" {
  value = "http://${aws_instance.app.public_ip}:8501"
}

output "airflow_url" {
  value = "http://${aws_instance.app.public_ip}:8080"
}

output "s3_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "rds_endpoint" {
  value = aws_db_instance.postgres.address
}
```

### terraform.tfvars.example

```hcl
aws_region      = "us-west-2"
project_name    = "youth-law"
allowed_ip_cidr = "YOUR_PUBLIC_IP/32"
ec2_key_name    = "YOUR_KEYPAIR_NAME"
db_username     = "youthlaw"
db_password     = "CHANGE_ME"
```

### 실행 순서

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars

terraform init
terraform fmt
terraform validate
terraform plan
terraform apply
```

삭제:

```bash
terraform destroy
```

### Terraform 검증 체크리스트

- [ ] `terraform fmt` 통과
- [ ] `terraform validate` 통과
- [ ] `terraform plan`에서 예상 리소스만 생성
- [ ] `terraform apply` 후 EC2 public IP 출력
- [ ] S3 bucket 생성 확인
- [ ] RDS endpoint 출력
- [ ] 발표 후 `terraform destroy` 가능

### 발표 포인트

> 인프라를 콘솔에서 한 번 만든 것으로 끝내지 않고 Terraform으로 EC2, S3, RDS, 보안 그룹을
> 정의했습니다. 팀원이 같은 변수를 넣으면 동일한 데모 환경을 재현할 수 있고, 발표 후에는
> destroy로 리소스를 정리해 비용을 통제할 수 있습니다.

## 6. 앱 연결 및 운영 검증 가이드

### 역할

1~5번은 인프라 리소스를 만드는 작업이다. 6번은 실제 앱이 그 리소스를 사용한다는 증거를
만드는 작업이다.

평가자가 물을 수 있는 질문:

- EC2에 앱이 뜨나요?
- S3에 실제 데이터가 올라가나요?
- RDS에 실제 로그가 저장되나요?
- Airflow가 실제 파이프라인을 실행하나요?
- Terraform으로 다시 만들 수 있나요?

6번의 목표는 이 질문에 모두 "예"라고 답할 수 있게 하는 것이다.

### 환경변수 통합

`.env.example`에 추가할 후보:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/youthlaw
S3_BUCKET=youth-law-artifacts-example
ENABLE_RDS_LOGGING=false
ENABLE_S3_SYNC=false
```

실제 `.env`:

```env
DATABASE_URL=postgresql+psycopg://youthlaw:***@youth-law-postgres.xxxxxx.us-west-2.rds.amazonaws.com:5432/youthlaw
S3_BUCKET=youth-law-artifacts-xxxx
ENABLE_RDS_LOGGING=true
ENABLE_S3_SYNC=true
```

### RDS 연결 코드 방향

권장 파일:

```text
common/db.py
common/logging_store.py
scripts/init_db.py
```

`common/db.py` 예시:

```python
import os

from sqlalchemy import create_engine


def get_database_url() -> str | None:
    return os.getenv("DATABASE_URL") or None


def get_engine():
    url = get_database_url()
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True)
```

`common/logging_store.py` 예시:

```python
import json

from common.db import get_engine


def save_consultation(result: dict) -> None:
    engine = get_engine()
    if engine is None:
        return

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            insert into consultation_logs
              (question, domains, in_scope, final_answer, answer_blocks, verification_report)
            values
              (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                result["question"],
                [d["id"] for d in result["domains"]],
                result["in_scope"],
                result["final_answer"],
                json.dumps(result.get("answer_blocks") or [], ensure_ascii=False),
                json.dumps(result.get("verification_report") or [], ensure_ascii=False),
            ),
        )
```

주의:

- DB 저장 실패가 사용자 상담 실패로 이어지면 안 된다.
- `try/except`로 저장 실패를 로그만 남기고 넘기는 것이 MVP에는 안전하다.
- 개인정보가 들어갈 수 있으므로 발표용 데이터에는 실제 주민번호, 계좌번호, 전화번호를 넣지 않는다.

### S3 sync 코드 방향

간단히는 shell script로 충분하다.

```bash
S3_BUCKET=<bucket-name> scripts/sync_s3.sh
```

Python 스크립트로 만들 경우:

```text
scripts/sync_s3.py
```

역할:

- `data/bronze` 업로드
- `data/silver` 업로드
- `data/chroma` 업로드
- `evals/results` 업로드
- 실패 시 exit code 1

### Airflow 후처리 연결

Airflow DAG 마지막 `summary` 뒤에 S3 sync task를 붙이면 발표 그림이 좋아진다.

흐름:

```text
update_labor, update_housing, update_consumer, update_finance
  -> summary
  -> sync_s3
```

선택 구현:

```python
from airflow.operators.bash import BashOperator

sync_s3 = BashOperator(
    task_id="sync_s3",
    bash_command="cd /home/ubuntu/youth_law && S3_BUCKET=$S3_BUCKET scripts/sync_s3.sh",
)

summary >> sync_s3
```

### 운영 검증 시나리오

#### 시나리오 1: 앱 응답

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/consult \
  -H "Content-Type: application/json" \
  -d '{"question":"전세 보증금을 안 돌려줘요"}'
```

기대:

- `in_scope=true`
- `domains`에 `housing`
- `answer_blocks[0].citations` 존재

#### 시나리오 2: RDS 로그

상담 후 RDS에서:

```sql
select id, created_at, question, domains
from consultation_logs
order by id desc
limit 5;
```

기대:

- 방금 질문이 저장됨

#### 시나리오 3: S3 백업

```bash
aws s3 ls s3://$S3_BUCKET/data/bronze/ --recursive | head
aws s3 ls s3://$S3_BUCKET/data/silver/ --recursive
aws s3 ls s3://$S3_BUCKET/evals/results/ --recursive
```

기대:

- XML, JSONL, 평가 결과가 보임

#### 시나리오 4: Airflow 배치

```bash
airflow dags trigger law_incremental_update
```

기대:

- 4개 분야 task 성공
- summary 성공
- 2회차 실행에서 변경 없음 스킵

#### 시나리오 5: Terraform 재현성

```bash
terraform plan
```

기대:

- 현재 인프라와 코드가 크게 drift되지 않음
- 발표 후 destroy 가능

### 최종 평가자용 증거 목록

발표 전에 다음 화면을 캡처한다.

- EC2 인스턴스 화면
- EC2 보안 그룹 inbound rule
- FastAPI `/health`
- Streamlit 데모 UI
- S3 bucket object 목록
- RDS `consultation_logs` 조회 결과
- Airflow DAG 성공 화면
- Terraform `plan` 또는 `apply` output
- 비용 알림 또는 예산 설정 화면

### MVP와 확장 설계 분리 표

| 영역 | MVP 실제 구현 | 운영 확장 설계 |
|---|---|---|
| App | EC2 단일 서버 FastAPI/Streamlit | ALB, Auto Scaling, container 배포 |
| Vector DB | Chroma local persistent storage | RDS PostgreSQL + pgvector |
| Data backup | S3 sync | S3 versioning, lifecycle policy |
| Logs | RDS 상담/비용/평가 로그 | Dashboard, retention policy, PII masking |
| Batch | Airflow standalone 또는 cron | Managed Airflow 또는 분리된 worker |
| IaC | Terraform single env | dev/prod workspace, remote state |

### 최종 체크리스트

- [ ] EC2 URL로 앱 접속 가능
- [ ] 대표 질문 4개 데모 가능
- [ ] RDS에 상담 로그 저장
- [ ] S3에 데이터 산출물 저장
- [ ] Airflow DAG 수동 실행 성공
- [ ] Terraform 코드 존재 및 validate 가능
- [ ] 발표에서 MVP와 확장 설계를 분리 설명
- [ ] 발표 후 보안 그룹 공개 포트 제한
- [ ] 발표 후 필요 없는 리소스 stop 또는 destroy

## 7. CD 자동 배포 가이드

### 목표

현재 저장소에는 `.github/workflows/ci.yml`이 있어 PR/push 시 lint와 테스트를 돌리는 CI 구조는 있다.
다만 EC2 서버에 자동으로 반영하는 CD는 아직 없다.

7번의 목표는 다음 흐름을 만드는 것이다.

```text
main 브랜치 push
-> GitHub Actions 실행
-> lint/test 통과
-> EC2 SSH 접속
-> 최신 코드 pull
-> 의존성 설치
-> FastAPI/Streamlit systemd 서비스 재시작
-> health check
```

발표에서는 다음처럼 설명한다.

> GitHub Actions 기반 CI는 계약 테스트와 lint를 자동 실행하도록 구성했고,
> CD는 main 브랜치 배포 시 EC2에 SSH로 접속해 앱 코드를 갱신하고 systemd 서비스를 재시작하는 방식으로
> 설계했습니다. MVP에서는 단일 EC2 서버 배포이며, 운영 확장 시에는 Blue/Green 배포나 컨테이너 기반 배포로
> 전환할 수 있습니다.

### 현재 상태와 선행 조건

현재 상태:

- CI 파일: `.github/workflows/ci.yml` 존재
- CI 동작: `pip install`, `ruff check`, `pytest`
- CD 파일: 아직 없음
- 배포 방식: EC2 접속 후 수동 `git pull`, `systemctl restart`

CD를 붙이기 전에 확인할 것:

- [ ] `main` 브랜치가 GitHub 원격 저장소와 연결되어 있음
- [ ] EC2에서 저장소를 clone 또는 pull 할 수 있음
- [ ] EC2에서 `youth-law-api.service`, `youth-law-streamlit.service`가 systemd로 등록되어 있음
- [ ] EC2에서 `/home/ubuntu/youth_law/.venv` 가상환경이 준비되어 있음
- [ ] GitHub Actions에서 EC2로 SSH 접속할 전용 key가 있음
- [ ] CI가 안정적으로 통과하도록 RAG 테스트 환경을 stub 또는 fixture 모드로 고정함

주의:

현재 코드의 RAG는 `chromadb`와 `sentence-transformers`가 설치되어 있고 Chroma 컬렉션에 데이터가 있으면
실제 임베딩 검색 모드로 들어간다. CI에서는 외부 모델 다운로드나 실제 벡터DB 의존성을 피해야 하므로
`RAG_MODE=stub` 같은 환경변수로 테스트 모드를 고정하는 개선이 필요하다.

### 배포용 SSH key 준비

GitHub Actions가 EC2에 접속하려면 배포 전용 SSH key를 만든다.
개인 노트북에서 쓰는 SSH key를 재사용하지 말고, 이 프로젝트 전용 key를 권장한다.

로컬에서 생성:

```bash
ssh-keygen -t ed25519 -C "github-actions-youth-law-cd" -f youthlaw_cd
```

생성되는 파일:

```text
youthlaw_cd      -> private key, GitHub Secret에 저장
youthlaw_cd.pub  -> public key, EC2 authorized_keys에 등록
```

EC2에 public key 등록:

```bash
cat youthlaw_cd.pub
```

출력된 public key를 EC2의 배포 사용자 `~/.ssh/authorized_keys`에 추가한다.
예를 들어 EC2 사용자가 `ubuntu`라면:

```bash
nano /home/ubuntu/.ssh/authorized_keys
chmod 700 /home/ubuntu/.ssh
chmod 600 /home/ubuntu/.ssh/authorized_keys
```

### GitHub Secrets 설정

GitHub 저장소에서 다음 경로로 이동한다.

```text
Repository Settings
-> Secrets and variables
-> Actions
-> New repository secret
```

필수 Secrets:

| Secret 이름 | 예시 | 설명 |
|---|---|---|
| `EC2_HOST` | `13.124.xxx.xxx` | EC2 public IP 또는 DuckDNS 주소 |
| `EC2_USER` | `ubuntu` | SSH 접속 사용자 |
| `EC2_SSH_KEY` | `-----BEGIN OPENSSH PRIVATE KEY-----...` | `youthlaw_cd` private key 전체 |
| `APP_DIR` | `/home/ubuntu/youth_law` | EC2의 앱 디렉터리 |

선택 Secrets:

| Secret 이름 | 설명 |
|---|---|
| `DEPLOY_BRANCH` | 기본은 `main`, 필요하면 별도 배포 브랜치 지정 |
| `HEALTHCHECK_URL` | `https://youthlaw-demo.duckdns.org/health` |
| `SLACK_WEBHOOK_URL` | 배포 성공/실패 알림용 |

보안 주의:

- private key는 저장소에 절대 커밋하지 않는다.
- GitHub Secrets 값은 로그에 출력하지 않는다.
- 배포 key는 해당 EC2 접속에만 쓰고, AWS root key나 개인 SSH key와 분리한다.
- 가능하면 EC2 보안 그룹의 22번 포트는 본인 IP와 GitHub Actions runner 접속 정책을 고려해 최소화한다.
  GitHub-hosted runner IP는 고정 관리가 까다로우므로, 발표용 MVP에서는 SSH key 강도를 높이고 배포 후 22번 포트를 닫는 식으로 운영한다.

### deploy.yml 예시

파일 위치:

```text
.github/workflows/deploy.yml
```

예시:

```yaml
name: deploy-ec2

on:
  workflow_dispatch:
  push:
    branches: [main]

concurrency:
  group: youth-law-production
  cancel-in-progress: false

jobs:
  test:
    runs-on: ubuntu-latest
    env:
      RAG_MODE: stub
      PYTHONUTF8: "1"
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Lint
        run: ruff check .

      - name: Test
        run: python -m pytest tests/ -v

  deploy:
    runs-on: ubuntu-latest
    needs: test
    environment: production
    steps:
      - name: Prepare SSH
        env:
          EC2_HOST: ${{ secrets.EC2_HOST }}
          EC2_SSH_KEY: ${{ secrets.EC2_SSH_KEY }}
        run: |
          mkdir -p ~/.ssh
          printf "%s" "$EC2_SSH_KEY" > ~/.ssh/youthlaw_cd
          chmod 600 ~/.ssh/youthlaw_cd
          ssh-keyscan -H "$EC2_HOST" >> ~/.ssh/known_hosts

      - name: Deploy to EC2
        env:
          EC2_HOST: ${{ secrets.EC2_HOST }}
          EC2_USER: ${{ secrets.EC2_USER }}
          APP_DIR: ${{ secrets.APP_DIR }}
        run: |
          ssh -i ~/.ssh/youthlaw_cd "$EC2_USER@$EC2_HOST" "APP_DIR='$APP_DIR' bash -s" <<'REMOTE'
          set -euo pipefail

          cd "$APP_DIR"

          git fetch origin main
          git checkout main
          git pull --ff-only origin main

          source .venv/bin/activate
          python -m pip install --upgrade pip
          pip install -r requirements.txt

          sudo systemctl restart youth-law-api
          sudo systemctl restart youth-law-streamlit
          sudo systemctl status youth-law-api --no-pager
          sudo systemctl status youth-law-streamlit --no-pager
          REMOTE

      - name: Health check
        env:
          HEALTHCHECK_URL: ${{ secrets.HEALTHCHECK_URL }}
        run: |
          if [ -z "$HEALTHCHECK_URL" ]; then
            echo "HEALTHCHECK_URL is not set. Skipping external health check."
            exit 0
          fi

          curl -fsS "$HEALTHCHECK_URL"
```

### EC2 sudo 권한 설정

GitHub Actions 배포 사용자가 systemd 서비스를 재시작하려면 sudo 권한이 필요하다.
비밀번호 입력 없이 필요한 명령만 허용하는 방식이 안전하다.

EC2에서 실행:

```bash
sudo visudo
```

예시:

```text
ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart youth-law-api, /bin/systemctl restart youth-law-streamlit, /bin/systemctl status youth-law-api, /bin/systemctl status youth-law-streamlit
```

배포 전용 사용자를 따로 만들면 더 좋다.

```bash
sudo adduser deploy
sudo usermod -aG www-data deploy
```

이 경우 GitHub Secret의 `EC2_USER`는 `deploy`로 바꾼다.

### EC2 최초 1회 준비 작업

CD는 최초 서버 구축을 대신하지 않는다.
EC2에는 먼저 앱이 수동으로 한 번 동작하는 상태가 만들어져 있어야 한다.

최초 1회:

```bash
cd /home/ubuntu
git clone <REPO_URL> youth_law
cd youth_law

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env

sudo systemctl daemon-reload
sudo systemctl enable youth-law-api
sudo systemctl enable youth-law-streamlit
sudo systemctl start youth-law-api
sudo systemctl start youth-law-streamlit
```

이후부터는 GitHub Actions가 `git pull`, 의존성 갱신, 서비스 재시작만 담당한다.

### 배포 검증

GitHub Actions 화면에서 확인할 것:

- [ ] `test` job 성공
- [ ] `deploy` job 성공
- [ ] SSH 접속 성공
- [ ] `git pull --ff-only` 성공
- [ ] `pip install -r requirements.txt` 성공
- [ ] `systemctl restart youth-law-api` 성공
- [ ] `systemctl restart youth-law-streamlit` 성공
- [ ] `/health` 체크 성공

EC2에서 직접 확인:

```bash
sudo systemctl status youth-law-api --no-pager
sudo systemctl status youth-law-streamlit --no-pager
journalctl -u youth-law-api -n 80 --no-pager
journalctl -u youth-law-streamlit -n 80 --no-pager
```

외부 확인:

```bash
curl -fsS https://youthlaw-demo.duckdns.org/health
```

### Rollback 전략

MVP에서는 복잡한 Blue/Green까지 바로 구현하지 않아도 된다.
대신 최근 정상 commit으로 되돌리는 단순 rollback 절차를 문서화한다.

수동 rollback:

```bash
cd /home/ubuntu/youth_law
git log --oneline -5
git checkout <LAST_GOOD_COMMIT>
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart youth-law-api
sudo systemctl restart youth-law-streamlit
```

주의:

- `git checkout <commit>`은 detached HEAD 상태가 된다.
- 긴급 복구 후에는 원인 수정 PR을 만들고 main 브랜치를 정상 상태로 되돌린다.
- DB migration을 붙인 뒤에는 단순 코드 rollback만으로 복구되지 않을 수 있으므로 migration 전략이 필요하다.

발표용 설명:

> MVP 단계에서는 단일 EC2 서버에 fast-forward 배포하고,
> 장애 시 최근 정상 commit으로 수동 rollback하는 절차를 운영 문서에 포함했습니다.
> 운영 단계에서는 Docker image tag 기반 rollback 또는 Blue/Green 배포로 확장할 계획입니다.

### CI 안정화와 CD의 관계

CD는 CI가 안정적으로 통과한다는 전제가 있어야 의미가 있다.
현재 프로젝트에서 먼저 보강할 부분은 다음이다.

1. RAG 테스트 모드 분리

   CI에서는 실제 Chroma, HuggingFace 모델 다운로드, Bedrock 호출에 의존하지 않아야 한다.
   권장 방향:

   ```text
   RAG_MODE=stub
   ```

   이 값이 있으면 `DomainRAG`가 무조건 stub 검색을 사용하게 한다.

2. Windows/Ubuntu 인코딩 차이 제거

   평가셋을 읽는 코드에서 인코딩을 명시한다.

   ```python
   path.read_text(encoding="utf-8")
   ```

3. LLM 호출 mock 또는 stub 처리

   계약 테스트는 구조 검증이 목적이므로 실제 Bedrock 호출 없이 통과해야 한다.
   실제 LLM 품질 평가는 별도 수동 또는 nightly workflow로 분리한다.

권장 workflow 분리:

| Workflow | Trigger | 역할 |
|---|---|---|
| `ci.yml` | PR, push | 빠른 계약 테스트 |
| `deploy.yml` | main push, manual | CI 통과 후 EC2 배포 |
| `nightly-eval.yml` | schedule, manual | 실제 RAG/LLM 품질 평가 |

### 평가자에게 보여줄 포인트

발표에서 CD를 실제로 보여줄 수 있다면 다음 순서가 좋다.

1. GitHub Actions `deploy-ec2` workflow 화면
2. `test` job 성공 로그
3. `deploy` job에서 EC2 접속 및 systemd restart 로그
4. `https://youthlaw-demo.duckdns.org/health` 성공
5. 실제 UI 접속

짧은 설명 문구:

```text
main 브랜치에 변경사항이 반영되면 GitHub Actions가 계약 테스트를 먼저 실행하고,
성공한 경우에만 EC2에 SSH로 접속해 최신 코드를 배포합니다.
서비스 프로세스는 systemd로 관리하고, 배포 후 health check로 정상 응답을 확인합니다.
```

### CD 최종 체크리스트

- [ ] `deploy.yml` 추가
- [ ] GitHub Secrets 등록
- [ ] EC2 authorized_keys에 배포 public key 등록
- [ ] EC2에서 수동 systemd 실행 성공
- [ ] GitHub Actions에서 SSH 접속 성공
- [ ] CI job 성공 후 deploy job 실행
- [ ] 배포 후 FastAPI `/health` 성공
- [ ] 배포 후 Streamlit URL 접속 성공
- [ ] 실패 시 rollback 절차 문서화
- [ ] 발표 후 SSH 포트와 배포 key 관리 정책 정리
