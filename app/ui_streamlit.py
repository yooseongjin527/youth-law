"""Streamlit 데모 UI — 발표용.

실행: streamlit run app/ui_streamlit.py --server.port 8501
FastAPI를 거치지 않고 service 레이어를 직접 호출 (같은 로직 공유).

화면 구성 = 확정된 UX:
  입력창 하나(분야 선택 X) → 자동 분류 태그 → 분야별 카드
  (요약 + '자세히' 펼침 + 근거법령 조문원문·시행일 + 공식 연락처) + 문서초안 버튼
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import service  # noqa: E402

st.set_page_config(page_title="청년 생활법률 상담 AI", page_icon="⚖️", layout="centered")

st.title("⚖️ 청년 생활법률 상담 AI")
st.caption("노동 · 주택 · 소비자 · 금융 — 현행 법령 근거로, 출처와 연락처까지")

question = st.text_input(
    "어떤 상황인지 편하게 적어주세요 (법을 잘 몰라도 괜찮아요)",
    placeholder="예: 알바비를 못 받았어요 / 전세 보증금을 안 돌려줘요",
    max_chars=500,
)

if st.button("상담", type="primary") and len(question.strip()) >= 2:
    with st.spinner("분야 분석 및 법령 검색 중..."):
        result = service.consult(question)

    if not result["in_scope"]:
        st.warning(result["final_answer"])
    else:
        st.info("이 질문을 다음 분야로 분석했습니다: "
                + " ".join(f"`{d['name']}`" for d in result["domains"]))

        for b in result["answer_blocks"]:
            with st.container(border=True):
                st.subheader(f"【{b['domain_kr']} 분야】")
                st.write(b["answer"])

                for c in b["citations"]:
                    with st.expander(
                        f"📖 {c['law_name']} {c['article']} (시행 {c['enforced_date']})"
                    ):
                        st.markdown(f"_{c['text']}_")
                        st.link_button("전문 보기", c["source_url"])

                for ct in b["contacts"]:
                    st.markdown(f"☎ **{ct['org']} {ct['phone']}** — {ct['note']}")

                if st.button(f"📄 {b['domain_kr']} 문서 초안 생성", key=f"draft_{b['domain']}"):
                    draft = service.make_draft(question, b["domain"])
                    st.code(draft["body"], language=None)
                    st.caption(draft["guide"])

        # 하네스 리포트 (발표 포인트: 환각 차단이 보임)
        with st.expander("🛡️ 검증 리포트 (verifier)"):
            st.json(result["verification_report"])

st.divider()
st.caption("국가법령정보센터 현행 법령 기반 일반 정보 안내입니다. 구체적 사건은 전문가와 상담하세요.")
