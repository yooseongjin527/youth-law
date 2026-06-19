"""상담/비용/평가 로그를 RDS에 적재 — 신규 파일.

세 함수 모두 동일 계약:
- 로깅이 꺼져 있으면(ENABLE_RDS_LOGGING/DATABASE_URL 미설정) 조용히 False.
- DB 쓰기 실패도 삼키고 False — 저장 실패가 상담/평가를 절대 죽이지 않는다.
- 성공 시 True.

테이블 스키마는 scripts/init_db.py (INFRA 가이드 §3와 동일).
호출 지점: app/service.py(consult) · common/cost.py(record) · scripts/evaluate.py(run).
"""
import json

from common import db


def _jsonb(value) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def save_consultation(payload: dict) -> bool:
    """consult() 반환 dict를 consultation_logs에 1건 적재."""
    if not db.logging_enabled():
        return False
    try:
        from sqlalchemy import text
        engine = db.get_engine()
        if engine is None:
            return False
        domains = [
            d["id"] if isinstance(d, dict) else d
            for d in payload.get("domains", [])
        ]
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into consultation_logs "
                    "(question, domains, in_scope, final_answer, answer_blocks, verification_report) "
                    "values (:q, :domains, :in_scope, :final, "
                    "cast(:blocks as jsonb), cast(:vr as jsonb))"
                ),
                {
                    "q": payload.get("question", ""),
                    "domains": domains,
                    "in_scope": payload.get("in_scope"),
                    "final": payload.get("final_answer", ""),
                    "blocks": _jsonb(payload.get("answer_blocks")),
                    "vr": _jsonb(payload.get("verification_report")),
                },
            )
        return True
    except Exception:
        return False


def save_usage(record: dict) -> bool:
    """cost.UsageTracker.record()의 1건을 llm_usage_logs에 적재."""
    if not db.logging_enabled():
        return False
    try:
        from sqlalchemy import text
        engine = db.get_engine()
        if engine is None:
            return False
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into llm_usage_logs "
                    "(task, tier, input_tokens, output_tokens, cost_usd) "
                    "values (:task, :tier, :in_tok, :out_tok, :cost)"
                ),
                {
                    "task": record.get("task", ""),
                    "tier": record.get("tier"),
                    "in_tok": record.get("input_tokens", 0),
                    "out_tok": record.get("output_tokens", 0),
                    "cost": record.get("cost_usd", 0),
                },
            )
        return True
    except Exception:
        return False


def save_eval_scorecard(result: dict) -> bool:
    """evaluate.run()의 3축 결과를 eval_scorecards에 적재."""
    if not db.logging_enabled():
        return False
    try:
        from sqlalchemy import text
        engine = db.get_engine()
        if engine is None:
            return False
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into eval_scorecards "
                    "(domain, retrieval, grounding, cost, raw_result) "
                    "values (:domain, cast(:retrieval as jsonb), cast(:grounding as jsonb), "
                    "cast(:cost as jsonb), cast(:raw as jsonb))"
                ),
                {
                    "domain": result.get("domain", ""),
                    "retrieval": _jsonb(result.get("retrieval")),
                    "grounding": _jsonb(result.get("grounding")),
                    "cost": _jsonb(result.get("cost")),
                    "raw": _jsonb(result),
                },
            )
        return True
    except Exception:
        return False
