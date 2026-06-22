"""RDS 로그 테이블 생성 + 연결 검증 — 신규 파일.

EC2(또는 DATABASE_URL이 가리키는 곳)에서 1회 실행:
    python scripts/init_db.py

테이블은 INFRA 가이드 §3와 동일(consultation_logs·llm_usage_logs·eval_scorecards).
멱등(create table if not exists) — 여러 번 돌려도 안전.
"""
import sys

sys.path.insert(0, ".")
from common import db  # noqa: E402

DDL = [
    """
    create table if not exists consultation_logs (
      id bigserial primary key,
      created_at timestamptz default now(),
      question text not null,
      domains text[],
      in_scope boolean,
      final_answer text,
      answer_blocks jsonb,
      verification_report jsonb
    )
    """,
    """
    create table if not exists llm_usage_logs (
      id bigserial primary key,
      created_at timestamptz default now(),
      task text not null,
      tier text,
      input_tokens int default 0,
      output_tokens int default 0,
      cost_usd numeric(12,6) default 0
    )
    """,
    """
    create table if not exists eval_scorecards (
      id bigserial primary key,
      created_at timestamptz default now(),
      domain text not null,
      retrieval jsonb,
      grounding jsonb,
      cost jsonb,
      raw_result jsonb
    )
    """,
]


def main():
    engine = db.get_engine()
    if engine is None:
        sys.exit("DATABASE_URL 이 .env에 없습니다 — RDS 엔드포인트를 먼저 설정하세요.")
    from sqlalchemy import text
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
    print("✓ 테이블 생성/확인 완료: consultation_logs, llm_usage_logs, eval_scorecards")


if __name__ == "__main__":
    main()
