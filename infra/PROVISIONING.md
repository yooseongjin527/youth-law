# EC2 프로비저닝 (코드화)

Terraform이 만든 EC2 위에 **앱 + Airflow를 systemd 서비스로** 올리는 절차를 코드로 고정한다.
수동 SSH로 한 번 검증한 단계를 그대로 스크립트/유닛 파일로 남겨 재현 가능하게 한다.

```
infra/
  systemd/
    youth-law-api.service        # FastAPI(8000) — 앱 venv(.venv)
    youth-law-airflow.service    # Airflow standalone(8080) — 격리 venv(~/airflow-venv)
  scripts/
    setup_airflow.sh             # Airflow 격리 venv + db migrate + systemd + DAG 활성화
```

## EC2 최초 셋업 순서 (SSH)

```bash
# 0) OS·python3.11 (Ubuntu 24.04는 deadsnakes 필요) — docs/INFRA_IMPLEMENTATION_GUIDE.md §1
# 1) 레포 + 앱 venv
git clone <repo> ~/youth_law && cd ~/youth_law
python3.11 -m venv .venv && . .venv/bin/activate && pip install -r requirements-ec2.txt
cp .env.example .env && nano .env          # 키 채우기 (RAG_BACKEND, DATABASE_URL 등)

# 2) 데이터 (S3에서 받기 or 빌드)
python scripts/sync_data.py pull           # 또는 build_index.py all

# 3) 앱 서비스
sudo cp infra/systemd/youth-law-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now youth-law-api

# 4) (RDS 로깅 쓰면) 로그 테이블
python -c "from dotenv import load_dotenv; load_dotenv('.env'); from scripts.init_db import main; main()"

# 5) Airflow 배치 (격리 venv + systemd) — 한 방
bash infra/scripts/setup_airflow.sh
```

## Terraform user_data로 자동화 (선택)

`infra/scripts/setup_airflow.sh`(+ 앱 셋업)를 EC2 `user_data`에 넣으면 `terraform apply` 시
새 인스턴스가 자동 부트스트랩된다. 단:

- ⚠️ **이미 떠 있는 인스턴스에 user_data를 추가하면 terraform이 인스턴스를 교체(파괴·재생성)한다.**
  운영 중 데모를 날리지 않으려면 `aws_instance`에 `lifecycle { ignore_changes = [user_data] }`를
  먼저 넣거나, **새 인스턴스부터** 적용한다.
- 시크릿(`LAW_GO_KR_OC`, `db_password`)은 user_data에 평문으로 넣지 말 것 — `.env`는 수동/SSM
  파라미터스토어로 주입한다.

> 현재 운영 인스턴스는 위 단계로 **수동 검증 완료**(앱·pgvector·RDS 로깅·Airflow DAG 성공).
> 이 파일들은 그 절차를 코드로 남긴 것이며, 라이브 인스턴스는 건드리지 않는다.
