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
    """RDS 테이블을 DataFrame으로. 엔진 없거나 실패하면 빈 DF."""
    engine = db.get_engine()
    if engine is None:
        return pd.DataFrame()
    try:
        return pd.read_sql(f"select * from {table}", engine)
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

# ── ④ 최근 상담 ───────────────────────────────────────────────────────────
st.subheader("④ 최근 상담 로그")
if not consult.empty:
    cols = [c for c in ["created_at", "question", "domains", "in_scope"] if c in consult]
    recent = consult.sort_values("id", ascending=False).head(20)[cols]
    st.dataframe(recent, use_container_width=True, hide_index=True)

st.caption("RDS read-only · 30초 캐시 · 새로고침으로 갱신")
