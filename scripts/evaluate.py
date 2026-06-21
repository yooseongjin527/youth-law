"""3축 개선 루프 — 각자 자기 분야를 평가/비용/환각 측면에서 측정한다.

사용법:
  python scripts/evaluate.py labor               # 담당 A
  python scripts/evaluate.py housing             # 담당 B  (consumer=C, finance=D)
  python scripts/evaluate.py all                 # 4분야 전체
  python scripts/evaluate.py finance smoke       # 금융 smoke
  python scripts/evaluate.py finance benchmark   # 금융 benchmark
  python scripts/evaluate.py finance benchmark retrieval  # 검색축만(Bedrock 호출 없음)

무엇을 측정하나:
  [축① 평가]   hit@k, MRR — 평가셋(evals/<분야>.jsonl 또는 evals/<분야>_<split>.jsonl)
               질문으로 검색했을 때 정답 조문이 top-k에 들어오는 비율
  [축② 비용]   이번 평가 실행 동안의 토큰·비용 (common/cost.py tracker)
  [축③ 환각]   grounding rate — 에이전트 답변이 verifier 검증을 통과하는 비율
               + 평균 인용 수 (근거가 얼마나 붙는가)

결과는 evals/results/<분야>_history.jsonl에 날짜와 함께 누적
금융 benchmark는 evals/results/<분야>_benchmark_history.jsonl에 따로 누적
→ Day2(단순검색) vs Day5(하이브리드) 비교가 발표 자료가 된다.

개선 루프:
  구현 수정 → evaluate 실행 → 숫자 확인 → 다시 수정 → ...
  (숫자가 안 오르면 그 개선은 개선이 아니다)
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")
from agents.consumer import consumer_agent  # noqa: E402
from agents.finance import finance_agent  # noqa: E402
from agents.housing import housing_agent  # noqa: E402
from agents.labor import labor_agent  # noqa: E402
from agents.verifier import verifier_agent  # noqa: E402
from common.cost import tracker  # noqa: E402
from state import DOMAINS  # noqa: E402

_AGENTS = {
    "labor": labor_agent, "housing": housing_agent,
    "consumer": consumer_agent, "finance": finance_agent,
}
_FINANCE_CATEGORY_BY_LAW = {
    "전기통신금융사기 피해 방지 및 피해금 환급에 관한 특별법": "voice_phishing",
    "채무자 회생 및 파산에 관한 법률": "debt_restructuring",
    "채권의 공정한 추심에 관한 법률": "collection",
    "대부업 등의 등록 및 금융이용자 보호에 관한 법률": "loan",
}
_FINANCE_CATEGORY_LABELS = {
    "voice_phishing": "보이스피싱",
    "debt_restructuring": "개인회생·파산",
    "collection": "채권추심",
    "loan": "대부업",
}
_EVAL_DIR = Path(__file__).resolve().parent.parent / "evals"


def _load_rag_class():
    """Retrieval backend for evaluation — common.rag (하이브리드 승격 완료, 4분야 공통)."""
    from common.rag import DomainRAG
    return DomainRAG


def load_eval_set(domain: str, split: str = "smoke") -> list[dict]:
    path = _EVAL_DIR / (
        f"{domain}.jsonl" if split == "smoke" else f"{domain}_{split}.jsonl"
    )
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _matches(expected: str, chunk: dict) -> bool:
    """정답 '법령명 제N조'가 검색 청크의 law_name+article과 일치하는가."""
    got = f"{chunk['law_name']} {chunk['article']}"
    return expected.replace(" ", "") in got.replace(" ", "")


def _item_category(item: dict) -> str:
    """평가 문항의 카테고리를 구한다. 없으면 expected_articles로 추론한다."""
    category = item.get("category")
    if category:
        return category
    laws = {
        exp.rsplit(" 제", 1)[0]
        for exp in item.get("expected_articles", [])
    }
    for law, inferred in _FINANCE_CATEGORY_BY_LAW.items():
        if law in laws:
            return inferred
    return "uncategorized"


def eval_retrieval(domain: str, k: int = 3, split: str = "smoke", recall_k: int = 8) -> dict:
    """[축① 평가] hit@k + MRR, plus recall@recall_k as a candidate-set probe."""
    items = load_eval_set(domain, split=split)
    if not items:
        return {
            "n": 0, "hit_at_k": None, "mrr": None,
            "recall_k": recall_k, "recall_at_k": None, "by_category": {},
        }
    rag = _load_rag_class()(domain=domain)
    hits, recall_hits, rr_sum = 0, 0, 0.0
    by_category = defaultdict(lambda: {"n": 0, "hits": 0, "recall_hits": 0, "rr_sum": 0.0})
    for item in items:
        category = _item_category(item)
        chunks = rag.search(item["question"], k=k)
        rank = None
        for i, c in enumerate(chunks, start=1):
            if any(_matches(exp, c) for exp in item["expected_articles"]):
                rank = i
                break
        recall_rank = rank
        if recall_k > k:
            candidate_chunks = rag.search(item["question"], k=recall_k)
            recall_rank = next(
                (
                    i for i, c in enumerate(candidate_chunks, start=1)
                    if any(_matches(exp, c) for exp in item["expected_articles"])
                ),
                None,
            )
        bucket = by_category[category]
        bucket["n"] += 1
        if rank:
            hits += 1
            rr_sum += 1.0 / rank
            bucket["hits"] += 1
            bucket["rr_sum"] += 1.0 / rank
        if recall_rank:
            recall_hits += 1
            bucket["recall_hits"] += 1
    n = len(items)
    return {
        "n": n,
        "k": k,
        "hit_at_k": round(hits / n, 3),
        "mrr": round(rr_sum / n, 3),
        "recall_k": recall_k,
        "recall_at_k": round(recall_hits / n, 3),
        "rag_backend": os.getenv("EVALUATE_RAG", "base").lower() or "base",
        "by_category": {
            cat: {
                "n": bucket["n"],
                "hit_at_k": round(bucket["hits"] / bucket["n"], 3),
                "mrr": round(bucket["rr_sum"] / bucket["n"], 3),
                "recall_at_k": round(bucket["recall_hits"] / bucket["n"], 3),
            }
            for cat, bucket in by_category.items()
        },
    }


def eval_grounding(domain: str, split: str = "smoke") -> dict:
    """[축③ 환각] 에이전트 답변의 verifier 통과율 + 평균 인용 수."""
    items = load_eval_set(domain, split=split)
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


def _empty_grounding(n: int) -> dict:
    return {"n": n, "grounding_rate": None, "avg_citations": None}


def run(domain: str, split: str = "smoke", include_grounding: bool = True) -> dict:
    tracker.reset()  # 이번 평가 실행의 비용만 측정
    retrieval = eval_retrieval(domain, split=split)  # 축① 평가
    grounding = (
        eval_grounding(domain, split=split)  # 축③ 환각 (LLM 호출 발생)
        if include_grounding
        else _empty_grounding(retrieval["n"])
    )
    cost = tracker.report()                     # 축② 비용 — grounding의 LLM
                                               # 호출 누적분이라 그 뒤에 측정

    result = {                                  # 표시·저장은 축 번호순(①②③)
        "date": date.today().isoformat(),
        "domain": domain,
        "split": split,
        "mode": "full" if include_grounding else "retrieval",
        "retrieval": retrieval,   # 축① 평가
        "cost": cost,             # 축② 비용
        "grounding": grounding,   # 축③ 환각
    }

    # 이력 누적 → 개선 추이 (Day2 vs Day5 비교가 발표 자료)
    out_dir = _EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    history_name = (
        f"{domain}_history.jsonl"
        if split == "smoke"
        else f"{domain}_{split}_history.jsonl"
    )
    with open(out_dir / history_name, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def print_scorecard(r: dict):
    print(f"\n{'='*52}")
    title = r["domain"] if r.get("split", "smoke") == "smoke" else f"{r['domain']}[{r['split']}]"
    print(f"  [{title}] 3축 스코어카드  ({r['date']})")
    print(f"{'='*52}")
    ret, grd, cst = r["retrieval"], r["grounding"], r["cost"]
    print(
        f"  축① 평가   hit@{ret.get('k','-')}: {ret['hit_at_k']}   "
        f"MRR: {ret['mrr']}   "
        f"recall@{ret.get('recall_k','-')}: {ret.get('recall_at_k')}   "
        f"backend: {ret.get('rag_backend', 'base')}   (n={ret['n']})"
    )
    if ret.get("by_category"):
        print("  축① 분야별")
        for cat in sorted(ret["by_category"]):
            stat = ret["by_category"][cat]
            label = _FINANCE_CATEGORY_LABELS.get(cat, cat)
            print(
                f"    - {label:<14} hit@{ret.get('k','-')}: {stat['hit_at_k']}   "
                f"MRR: {stat['mrr']}   "
                f"recall@{ret.get('recall_k','-')}: {stat.get('recall_at_k')}   "
                f"(n={stat['n']})"
            )
    print(
        f"  축② 비용   호출 {cst['calls']}회  토큰 "
        f"{cst['input_tokens']}+{cst['output_tokens']}  ${cst['total_cost_usd']}"
    )
    print(
        f"  축③ 환각   grounding rate: {grd['grounding_rate']}   "
        f"평균 인용: {grd['avg_citations']}"
    )
    if cst["calls"] == 0:
        print("            (LLM 호출 0회 — retrieval-only 또는 Bedrock 연결 전 stub 상태)")
    history_name = (
        f"{r['domain']}_history.jsonl"
        if r.get("split", "smoke") == "smoke"
        else f"{r['domain']}_{r['split']}_history.jsonl"
    )
    print(f"  → 이력 저장: evals/results/{history_name}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    split = sys.argv[2] if len(sys.argv) > 2 else "smoke"
    mode = sys.argv[3] if len(sys.argv) > 3 else "full"
    if target == "all" and split != "smoke":
        print("all 모드에서는 split을 지정하지 마세요")
        sys.exit(1)
    if target != "finance" and split != "smoke":
        print("benchmark split은 finance에서만 사용하세요")
        sys.exit(1)
    if mode not in ("full", "retrieval"):
        print("mode는 full 또는 retrieval")
        sys.exit(1)
    domains = DOMAINS if target == "all" else [target]
    if any(d not in DOMAINS for d in domains):
        print(f"분야는 {DOMAINS} 또는 all")
        sys.exit(1)
    for d in domains:
        print_scorecard(
            run(
                d,
                split=split if d == "finance" else "smoke",
                include_grounding=mode == "full",
            )
        )
