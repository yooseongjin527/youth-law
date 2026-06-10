"""법령 증분 갱신 DAG — 주 1회 (법령은 거의 안 바뀌므로 충분).

EC2의 Airflow에 이 폴더(airflow/dags)를 dags_folder로 잡으면 인식됨.
셋업 절차: docs/INFRA.md 참고.

구조:
  분야별 update_domain 태스크 4개 병렬 → 완료 요약
  (증분 감지가 내장돼 있어 변경 없으면 각 태스크가 빠르게 스킵)
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# 프로젝트 루트가 PYTHONPATH에 있어야 함 (INFRA.md의 env 설정 참조)
from pipeline.config import LAW_LIST
from scripts.update_laws import update_domain

default_args = {
    "owner": "youth-law",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="law_incremental_update",
    description="국가법령정보센터 증분 갱신 (bronze→silver→gold)",
    schedule="@weekly",              # 주 1회 — 법령 변경 주기에 충분
    start_date=datetime(2026, 6, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["medallion", "law"],
) as dag:

    def _summary(**ctx):
        results = [ctx["ti"].xcom_pull(task_ids=f"update_{d}") for d in LAW_LIST]
        total = sum(r["updated"] for r in results if r)
        print(f"이번 주 갱신: {total}건 (분야별: {results})")

    update_tasks = [
        PythonOperator(
            task_id=f"update_{domain}",
            python_callable=update_domain,
            op_kwargs={"domain": domain},
        )
        for domain in LAW_LIST
    ]

    summary = PythonOperator(task_id="summary", python_callable=_summary)
    update_tasks >> summary
