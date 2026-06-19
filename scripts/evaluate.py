"""3축 개선 루프 — 각자 자기 분야를 평가/비용/환각 측면에서 측정한다.

사용법:
  python scripts/evaluate.py labor      # 담당 A
  python scripts/evaluate.py housing    # 담당 B  (consumer=C, finance=D)
  python scripts/evaluate.py all        # 4분야 전체

무엇을 측정하나:
  [축① 평가]   hit@k, MRR — 평가셋(evals/<분야>.jsonl) 질문으로 검색했을 때
               정답 조문이 top-k에 들어오는 비율
  [축② 비용]   이번 평가 실행 동안의 토큰·비용 (common/cost.py tracker)
  [축③ 환각]   grounding rate — 에이전트 답변이 verifier 검증을 통과하는 비율
               + 평균 인용 수 (근거가 얼마나 붙는가)

결과는 evals/results/<분야>_history.jsonl에 날짜와 함께 누적
→ Day2(단순검색) vs Day5(하이브리드) 비교가 발표 자료가 된다.

개선 루프:
  구현 수정 → evaluate 실행 → 숫자 확인 → 다시 수정 → ...
  (숫자가 안 오르면 그 개선은 개선이 아니다)
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")
from agents.consumer import consumer_agent  # noqa: E402
from agents.finance import finance_agent  # noqa: E402
from agents.housing import housing_agent  # noqa: E402
from agents.labor import labor_agent  # noqa: E402
from agents.verifier import verifier_agent  # noqa: E402
from common.cost import tracker  # noqa: E402
from common.logging_store import save_eval_scorecard  # noqa: E402
from common.rag import DomainRAG  # noqa: E402
from state import DOMAINS  # noqa: E402

_AGENTS = {
    "labor": labor_agent, "housing": housing_agent,
    "consumer": consumer_agent, "finance": finance_agent,
}
_EVAL_DIR = Path(__file__).resolve().parent.parent / "evals"


def load_eval_set(domain: str) -> list[dict]:
    path = _EVAL_DIR / f"{domain}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _matches(expected: str, chunk: dict) -> bool:
    """정답 '법령명 제N조'가 검색 청크의 law_name+article과 일치하는가."""
    got = f"{chunk['law_name']} {chunk['article']}"
    return expected.replace(" ", "") in got.replace(" ", "")


def eval_retrieval(domain: str, k: int = 3) -> dict:
    """[축① 평가] hit@k + MRR."""
    items = load_eval_set(domain)
    if not items:
        return {"n": 0, "hit_at_k": None, "mrr": None}
    rag = DomainRAG(domain=domain)
    hits, rr_sum = 0, 0.0
    for item in items:
        chunks = rag.search(item["question"], k=k)
        rank = None
        for i, c in enumerate(chunks, start=1):
            if any(_matches(exp, c) for exp in item["expected_articles"]):
                rank = i
                break
        if rank:
            hits += 1
            rr_sum += 1.0 / rank
    n = len(items)
    return {"n": n, "k": k, "hit_at_k": round(hits / n, 3), "mrr": round(rr_sum / n, 3)}


def eval_grounding(domain: str) -> dict:
    """[축③ 환각] 에이전트 답변의 verifier 통과율 + 평균 인용 수."""
    items = load_eval_set(domain)
    if not items:
        return {"n": 0, "grounding_rate": None, "avg_citations": None}
    agent = _AGENTS[domain]
    passed, cite_total = 0, 0
    for item in items:
        state = {
            "user_query": item["question"], "target_domains": [domain], "in_scope": True,
            "domain_answers": [], "verified_answers": None,
            "verification_report": None, "answer_blocks": None, "messages": [],
        }
        out = agent(state)
        state["domain_answers"] = out["domain_answers"]
        v = verifier_agent(state)
        if v["verified_answers"]:
            passed += 1
        cite_total += len(out["domain_answers"][0]["citations"])
    n = len(items)
    return {"n": n, "grounding_rate": round(passed / n, 3),
            "avg_citations": round(cite_total / n, 2)}


def run(domain: str) -> dict:
    tracker.reset()  # 이번 평가 실행의 비용만 측정
    retrieval = eval_retrieval(domain)          # 축① 평가
    grounding = eval_grounding(domain)          # 축③ 환각 (LLM 호출 발생)
    cost = tracker.report()                     # 축② 비용 — grounding의 LLM 호출 누적분이라 그 뒤에 측정

    result = {                                  # 표시·저장은 축 번호순(①②③)
        "date": date.today().isoformat(),
        "domain": domain,
        "retrieval": retrieval,   # 축① 평가
        "cost": cost,             # 축② 비용
        "grounding": grounding,   # 축③ 환각
    }

    # 이력 누적 → 개선 추이 (Day2 vs Day5 비교가 발표 자료)
    out_dir = _EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / f"{domain}_history.jsonl", "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    save_eval_scorecard(result)  # RDS 로깅(꺼져 있으면 no-op)
    return result


def print_scorecard(r: dict):
    print(f"\n{'='*52}")
    print(f"  [{r['domain']}] 3축 스코어카드  ({r['date']})")
    print(f"{'='*52}")
    ret, grd, cst = r["retrieval"], r["grounding"], r["cost"]
    print(f"  축① 평가   hit@{ret.get('k','-')}: {ret['hit_at_k']}   MRR: {ret['mrr']}   (n={ret['n']})")
    print(f"  축② 비용   호출 {cst['calls']}회  토큰 {cst['input_tokens']}+{cst['output_tokens']}  ${cst['total_cost_usd']}")
    print(f"  축③ 환각   grounding rate: {grd['grounding_rate']}   평균 인용: {grd['avg_citations']}")
    if cst["calls"] == 0:
        print("            (LLM 호출 0회 — Bedrock 연결 전 stub 상태)")
    print(f"  → 이력 저장: evals/results/{r['domain']}_history.jsonl")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    domains = DOMAINS if target == "all" else [target]
    if any(d not in DOMAINS for d in domains):
        print(f"분야는 {DOMAINS} 또는 all")
        sys.exit(1)
    for d in domains:
        print_scorecard(run(d))
