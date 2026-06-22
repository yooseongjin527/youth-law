#!/usr/bin/env bash
# Airflow 배치를 '격리 venv + systemd'로 재현 가능하게 구축 (앱 venv 무손상).
# EC2에서 1회 실행. 멱등에 가깝게 작성(venv 있으면 재생성 생략).
#
# 전제:
#   - 레포 클론됨: /home/ubuntu/youth_law
#   - 앱 venv 구축됨: /home/ubuntu/youth_law/.venv (requirements-ec2.txt)
#   - .env 작성됨(LAW_GO_KR_OC 등) — DAG의 update_domain이 법령 API를 폴링하므로 필요
#   - python3.11 설치됨(Ubuntu 24.04는 deadsnakes PPA 필요)
#
# 왜 격리 venv인가:
#   apache-airflow의 엄격한 constraints가 typing-extensions를 깎아 chromadb를 깨뜨린다.
#   앱 venv를 보호하려고 airflow는 별도 venv(~/airflow-venv)에 두고, 그 안에서만
#   typing-extensions를 복구한다. DAG가 PythonOperator로 pipeline을 직접 import하므로
#   이 venv에도 프로젝트 의존성(requirements-ec2.txt)을 깐다.
set -euo pipefail

REPO=/home/ubuntu/youth_law
AF_VENV=/home/ubuntu/airflow-venv
export AIRFLOW_HOME=/home/ubuntu/airflow

echo "[1/4] 격리 venv + 의존성"
[ -d "$AF_VENV" ] || python3.11 -m venv "$AF_VENV"
"$AF_VENV/bin/pip" install -q -U pip wheel
"$AF_VENV/bin/pip" install -q -r "$REPO/requirements-ec2.txt"
"$AF_VENV/bin/pip" install -q "apache-airflow==2.10.*" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.0/constraints-3.11.txt"
# airflow가 깎은 typing-extensions 복구 → chromadb 호환(이 venv 한정)
"$AF_VENV/bin/pip" install -q -U "typing-extensions>=4.14.1"

echo "[2/4] 메타DB 초기화 (SQLite, AIRFLOW_HOME=$AIRFLOW_HOME)"
AIRFLOW__CORE__LOAD_EXAMPLES=False \
AIRFLOW__CORE__DAGS_FOLDER="$REPO/airflow/dags" \
PYTHONPATH="$REPO" "$AF_VENV/bin/airflow" db migrate

echo "[3/4] systemd 서비스 설치·기동"
sudo cp "$REPO/infra/systemd/youth-law-airflow.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now youth-law-airflow

echo "[4/4] DAG 활성화 (law_incremental_update, @weekly)"
sleep 20  # 웹서버·스케줄러 기동 대기
AIRFLOW_HOME=$AIRFLOW_HOME PYTHONPATH="$REPO" \
  "$AF_VENV/bin/airflow" dags unpause law_incremental_update || true

echo "✓ 완료"
echo "  UI    : http://<EIP>:8080"
echo "  로그인: admin / \$(cat $AIRFLOW_HOME/standalone_admin_password.txt)"
echo "  수동실행: AIRFLOW_HOME=$AIRFLOW_HOME PYTHONPATH=$REPO $AF_VENV/bin/airflow dags trigger law_incremental_update"
