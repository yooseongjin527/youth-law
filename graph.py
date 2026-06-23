"""그래프 조립 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).
Supervisor 자동분류 → 전문가들 fan-out → Verifier(근거 검증, 하네스) → Planner 종합 → END
범위 밖이면 Supervisor → Planner(거절) → END

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day2] ① LangSmith 트레이싱 — .env 설정만으로 켜짐 (README 참조)
  [공용/Day5] ② 전체 파이프라인 응답시간 측정
────────────────────────────────────────────────────────
"""
from langgraph.graph import END, START, StateGraph

from agents.consumer import consumer_agent
from agents.finance import finance_agent
from agents.housing import housing_agent
from agents.labor import labor_agent
from agents.planner import planner_agent
from agents.supervisor import route, supervisor_agent
from agents.verifier import verifier_agent
from state import LegalState


def build_graph():
    g = StateGraph(LegalState)
    g.add_node("supervisor", supervisor_agent)
    g.add_node("labor", labor_agent)
    g.add_node("housing", housing_agent)
    g.add_node("consumer", consumer_agent)
    g.add_node("finance", finance_agent)
    g.add_node("verifier", verifier_agent)
    g.add_node("planner", planner_agent)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor", route,
        ["labor", "housing", "consumer", "finance", "planner"],
    )
    g.add_edge("labor", "verifier")
    g.add_edge("housing", "verifier")
    g.add_edge("consumer", "verifier")
    g.add_edge("finance", "verifier")
    g.add_edge("verifier", "planner")   # 검증 통과분만 planner로 (하네스)
    g.add_edge("planner", END)
    return g.compile()


if __name__ == "__main__":
    app = build_graph()

    def run(q):
        return app.invoke({
            "user_query": q, "target_domains": [], "in_scope": True,
            "domain_queries": None,
            "domain_answers": [], "verified_answers": None,
            "verification_report": None, "answer_blocks": None, "messages": [],
        })

    print("=== 케이스 1: 단일 분야 (주택) ===")
    r = run("집주인이 보증금을 안 돌려줘요")
    print(r["final_answer"])
    print("→", r["messages"][0])

    print("\n=== 케이스 2: 복수 분야 (노동+주택) ===")
    r = run("회사 그만두는데 월급도 안 주고 기숙사 보증금도 안 줘요")
    print(r["final_answer"])
    print("→", r["messages"][0])

    print("\n=== 케이스 3: 범위 밖 ===")
    r = run("친구가 때려서 고소하고 싶어요")
    print(r["final_answer"])
    print("→", r["messages"][0])
