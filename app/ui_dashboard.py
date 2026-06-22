"""운영 대시보드 (Streamlit) — RDS 로그를 읽어 운영 지표를 시각화.

청중 분리: 8000=사용자 상담 화면 / 8501=운영자 대시보드.
RDS를 read-only로만 조회하므로 운영 앱·DAG에 영향 없음.

데이터 소스(이미 적재 중):
  - consultation_logs : 상담수·분야분포·범위밖률·검증 통과율
  - llm_usage_logs    : 비용·토큰 (task/tier 분해)
  - eval_scorecards   : 분야별 품질(hit@k·grounding) 추이

실행:  streamlit run app/ui_dashboard.py --server.port 8501 --server.address 0.0.0.0
전제:  .env 의 DATABASE_URL (RDS) — common/db.py 사용. 없으면 안내만 표시.
"""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from common import db  # noqa: E402

st.set_page_config(page_title="청년 법률상담 — 운영 대시보드", page_icon="📊", layout="wide")


@st.cache_data(ttl=30)
def _load(table: str) -> pd.DataFrame:
    """RDS 테이블을 DataFrame으로. 엔진 없거나 실패하면 빈 DF.

    pandas.read_sql(engine)는 pandas 3.0 + SQLAlchemy 조합에서 엔진을 DBAPI로
    오인해 깨진다('Engine' has no attribute 'cursor') → SQLAlchemy로 직접 fetch.
    """
    engine = db.get_engine()
    if engine is None:
        return pd.DataFrame()
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(f"select * from {table}"))
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    except Exception:
        return pd.DataFrame()


st.title("📊 청년 생활법률 상담 — 운영 대시보드")

if db.get_engine() is None:
    st.error("DATABASE_URL이 설정되지 않았습니다(.env). RDS 엔드포인트를 먼저 설정하세요.")
    st.stop()

consult = _load("consultation_logs")
usage = _load("llm_usage_logs")
evals = _load("eval_scorecards")

if consult.empty and usage.empty:
    st.warning("아직 적재된 로그가 없습니다. 상담을 한 번 실행하면 지표가 채워집니다.")
    st.stop()

# ── KPI 행 ────────────────────────────────────────────────────────────────
total_consult = len(consult)
total_cost = float(usage["cost_usd"].sum()) if not usage.empty else 0.0
cost_per = total_cost / total_consult if total_consult else 0.0

# 검증 통과율: verification_report(list[{domain,dropped,reason}])에서 dropped 비율
passed = dropped = 0
if not consult.empty and "verification_report" in consult:
    for vr in consult["verification_report"].dropna():
        items = vr if isinstance(vr, list) else []
        for it in items:
            if isinstance(it, dict):
                dropped += 1 if it.get("dropped") else 0
                passed += 0 if it.get("dropped") else 1
total_ans = passed + dropped
pass_rate = (passed / total_ans * 100) if total_ans else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("총 상담 수", f"{total_consult:,}")
c2.metric("누적 LLM 비용", f"${total_cost:,.4f}")
c3.metric("상담당 평균 비용", f"${cost_per:,.4f}")
c4.metric("검증 통과율 (환각 차단)", f"{pass_rate:.0f}%", help=f"통과 {passed} / 탈락 {dropped}")

st.divider()

# ── ① 운영 개요 ───────────────────────────────────────────────────────────
st.subheader("① 운영 개요")
o1, o2 = st.columns(2)

with o1:
    st.caption("분야 분포")
    if not consult.empty and "domains" in consult:
        flat = []
        for ds in consult["domains"].dropna():
            flat.extend(ds if isinstance(ds, (list, tuple)) else [ds])
        if flat:
            dist = pd.Series(flat).value_counts()
            st.bar_chart(dist)
        else:
            st.info("분야 데이터 없음")
    else:
        st.info("데이터 없음")

with o2:
    st.caption("일별 상담 수")
    if not consult.empty and "created_at" in consult:
        d = consult.copy()
        d["date"] = pd.to_datetime(d["created_at"]).dt.date
        st.line_chart(d.groupby("date").size().rename("상담수"))
    else:
        st.info("데이터 없음")

if not consult.empty and "in_scope" in consult:
    in_rate = consult["in_scope"].fillna(False).mean() * 100
    st.caption(f"범위 내 응답 비율: **{in_rate:.0f}%**  (범위밖 거절 {100 - in_rate:.0f}%)")

st.divider()

# ── ② 비용·토큰 ───────────────────────────────────────────────────────────
st.subheader("② 비용 · 토큰")
if usage.empty:
    st.info("사용량 로그 없음")
else:
    u1, u2, u3 = st.columns(3)
    with u1:
        st.caption("task별 비용 ($)")
        st.bar_chart(usage.groupby("task")["cost_usd"].sum())
    with u2:
        st.caption("tier별 토큰 (입력+출력)")
        u = usage.copy()
        u["tokens"] = u["input_tokens"].fillna(0) + u["output_tokens"].fillna(0)
        st.bar_chart(u.groupby("tier")["tokens"].sum())
    with u3:
        st.caption("일별 비용 ($)")
        u = usage.copy()
        u["date"] = pd.to_datetime(u["created_at"]).dt.date
        st.line_chart(u.groupby("date")["cost_usd"].sum())

st.divider()

# ── ③ 품질 (eval_scorecards) ──────────────────────────────────────────────
st.subheader("③ 품질 지표 (평가)")
if evals.empty:
    st.info("평가 로그 없음 — EC2에서 `python scripts/evaluate.py all` 실행 시 채워집니다.")
else:
    rows = []
    for _, r in evals.iterrows():
        ret = r.get("retrieval") or {}
        grd = r.get("grounding") or {}
        rows.append({
            "분야": r.get("domain"),
            "hit@k": (ret or {}).get("hit_at_k"),
            "MRR": (ret or {}).get("mrr"),
            "grounding": (grd or {}).get("grounding_rate"),
            "일시": r.get("created_at"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()

# ── ④ 실행 성능 (LangSmith 트레이스) ──────────────────────────────────────
# RDS가 "무엇이 저장됐나"라면 LangSmith는 "어떻게/얼마나 빨리 실행됐나"를 본다.
# 노드별 레이턴시·LLM 호출·에러율을 LangSmith API로 끌어와 같은 화면에서 관측.
st.subheader("④ 실행 성능 (LangSmith 트레이스)")


@st.cache_data(ttl=60)
def _load_langsmith_runs(limit: int = 100):
    """LangSmith(youth-law 프로젝트) 최근 run을 DataFrame으로.
    키/엔드포인트/워크스페이스ID는 .env(load_dotenv)에서 Client()가 자동으로 읽는다.
    미설정·미설치·실패 시 빈 DF + 사유 문자열(대시보드는 안 죽음).
    ※ AWS 호스팅 인스턴스는 list_runs limit 상한이 100 (초과 시 400)."""
    if not (os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")):
        return pd.DataFrame(), "LANGSMITH_API_KEY 미설정"
    try:
        from langsmith import Client
        client = Client()  # api_key/api_url/workspace_id 모두 env에서
        project = os.getenv("LANGCHAIN_PROJECT", "youth-law")
        rows = []
        for r in client.list_runs(project_name=project, limit=limit):
            lat = (r.end_time - r.start_time).total_seconds() if r.end_time else None
            rows.append({
                "name": r.name,
                "run_type": r.run_type,
                "latency": lat,
                "error": bool(r.error),
                "start_time": r.start_time,
                "is_root": r.parent_run_id is None,
            })
        return pd.DataFrame(rows), None
    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}: {e}"


ls_df, ls_err = _load_langsmith_runs()
if ls_df.empty:
    st.info(f"LangSmith 트레이스 없음 — {ls_err or '아직 트레이스가 없습니다'}")
else:
    roots = ls_df[ls_df["is_root"]]
    root_lat = roots["latency"].dropna()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("트레이스(요청) 수", f"{len(roots):,}")
    k2.metric("전체 응답 p50", f"{root_lat.median():.1f}s" if not root_lat.empty else "—")
    k3.metric("전체 응답 p95", f"{root_lat.quantile(0.95):.1f}s" if not root_lat.empty else "—")
    k4.metric("에러율", f"{ls_df['error'].mean() * 100:.0f}%")

    detail = ls_df[~ls_df["is_root"]].copy()  # 루트(전체 LangGraph) 제외 → 노드별만
    if not detail.empty:
        by_node = detail.groupby("name").agg(
            호출수=("name", "size"),
            평균초=("latency", "mean"),
            최대초=("latency", "max"),
            에러=("error", "sum"),
        ).sort_values("평균초", ascending=False)
        ls1, ls2 = st.columns([2, 3])
        with ls1:
            st.caption("노드별 평균 레이턴시 (초) — 병목 진단")
            st.bar_chart(by_node["평균초"])
        with ls2:
            st.caption("노드별 상세 (호출수·평균·최대·에러)")
            show = by_node.copy()
            show["평균초"] = show["평균초"].round(2)
            show["최대초"] = show["최대초"].round(2)
            st.dataframe(show, use_container_width=True)

    _endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://smith.langchain.com")
    st.caption(f"개별 트레이스(호출 트리·프롬프트·토큰)는 LangSmith에서 → {_endpoint}")

st.divider()

# ── ⑤ 최근 상담 ───────────────────────────────────────────────────────────
st.subheader("⑤ 최근 상담 로그")
if not consult.empty:
    cols = [c for c in ["created_at", "question", "domains", "in_scope"] if c in consult]
    recent = consult.sort_values("id", ascending=False).head(20)[cols]
    st.dataframe(recent, use_container_width=True, hide_index=True)

st.caption("RDS read-only · 30초 캐시 · 새로고침으로 갱신")
