"""문항별 평가 상세 리포트.

evaluate.py(종합 점수)와 달리, 평가셋 각 문항의 검색·근거·답변·검증 결과를
사람이 읽기 좋은 Markdown으로 남긴다 → 점수와 실제 답변을 한 파일에서 확인.

사용:  python scripts/eval_detail.py housing
출력:  evals/results/<domain>_detail.md  (IDE에서 바로 열람)
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 인코딩
except Exception:
    pass

from agents.consumer import consumer_agent  # noqa: E402
from agents.finance import finance_agent  # noqa: E402
from agents.housing import housing_agent  # noqa: E402
from agents.labor import labor_agent  # noqa: E402
from agents.verifier import verifier_agent  # noqa: E402
from common.rag import DomainRAG  # noqa: E402
from scripts.evaluate import _matches, eval_retrieval, load_eval_set  # noqa: E402

_AGENTS = {"labor": labor_agent, "housing": housing_agent,
           "consumer": consumer_agent, "finance": finance_agent}
_OUT_DIR = Path(__file__).resolve().parent.parent / "evals" / "results"


def _init_state(q: str) -> dict:
    return {"user_query": q, "target_domains": [], "in_scope": True,
            "domain_answers": [], "verified_answers": None,
            "verification_report": None, "answer_blocks": None, "messages": []}


def build_report(domain: str) -> str:
    items = load_eval_set(domain)
    rag = DomainRAG(domain=domain)
    agent = _AGENTS[domain]
    ret = eval_retrieval(domain)

    body = []
    n_hit = n_pass = 0
    for i, it in enumerate(items, 1):
        chunks = rag.search(it["question"], k=3)
        top = " / ".join(c["article"] for c in chunks)
        hit = any(any(_matches(e, c) for e in it["expected_articles"]) for c in chunks)
        n_hit += hit

        st = _init_state(it["question"])
        res = agent(st)
        a = res["domain_answers"][0]
        st["domain_answers"] = res["domain_answers"]
        v = verifier_agent(st)
        passed = bool(v["verified_answers"])
        n_pass += passed
        reason = v["verification_report"][0]["reason"]
        cited = " / ".join(c["article"] for c in a["citations"]) or "(없음)"
        answer = v["verified_answers"][0]["answer"] if passed else a["answer"]

        body += [
            f"## [{i}] {it['question']}",
            f"- 정답조문: {', '.join(it['expected_articles'])}",
            f"- 검색 top-3: {top}  → 정답검색 {'⭕' if hit else '❌'}",
            f"- 근거(가지치기 후): {cited}",
            f"- 검증: {'통과' if passed else '탈락'} ({reason}) | confidence {a['confidence']}",
            "",
            "**답변:**",
            "",
            answer,
            "",
            "---",
            "",
        ]

    n = len(items)
    header = [
        f"# [{domain}] 문항별 평가 상세  ({date.today().isoformat()})",
        "",
        f"종합: hit@3 {ret['hit_at_k']} ({n_hit}/{n}) | "
        f"grounding {round(n_pass / n, 3)} ({n_pass}/{n}) | MRR {ret['mrr']}",
        "",
        "> 검색 top-3 = RAG가 끌어온 조문 / 근거 = 답변이 실제 쓴 조문(가지치기 후) / "
        "검증 = verifier 통과·환각문장 제거 여부.",
        "",
        "---",
        "",
    ]
    return "\n".join(header + body)


if __name__ == "__main__":
    domain = sys.argv[1] if len(sys.argv) > 1 else "housing"
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"{domain}_detail.md"
    path.write_text(build_report(domain), encoding="utf-8")
    print(f"저장: {path}")
