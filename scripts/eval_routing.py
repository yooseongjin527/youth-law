"""라우팅(분야 분류) 평가 — supervisor.py 키워드 vs Bedrock few-shot 비교.

PR #20(feat/supervisor-bedrock-routing) 근거 측정용.
evals/<분야>.jsonl 의 평어 질문을 정답 분야(=파일명)로 라벨링해, 입구 분류기가
올바른 전문가로 보내는지를 3가지 경로로 비교한다:
  1) keyword      — 키워드 substring 매칭만 (Bedrock 꺼졌을 때의 바닥)
  2) bedrock-raw  — Bedrock few-shot 단독 (백스톱 없음, 순수 LLM 분류 품질)
  3) full         — Bedrock + 키워드 백스톱 (실제 supervisor_agent가 배포하는 동작)

지표:
  [recall]       정답 분야가 예측에 포함되는 비율 (= 올바른 전문가로 보냈는가)
  [false-OOS]    진짜 법률 질문을 빈 배열(범위 밖)로 오판 — 최악 케이스(신뢰성↓)
  [over-fanout]  정답 외 분야까지 같이 예측 — 불필요한 fan-out(다운스트림 Sonnet 낭비).
                 ※ 평가셋은 단일 분야 라벨이라, 일부 추가 분야는 실제로 타당할 수 있음
                   → over-fanout은 '거짓 fan-out의 상한'으로 해석한다.

비용 효율: 질문당 Bedrock classify 1콜만. 'full'의 백스톱은 결정적 로직이라
          raw 결과로 로컬 재현(추가 호출 없음).

사용법:
  python scripts/eval_routing.py            # 4분야 전체
  python scripts/eval_routing.py labor      # 한 분야만
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agents.supervisor import _classify_bedrock, _classify_keyword  # noqa: E402
from common.cost import tracker  # noqa: E402
from state import DOMAINS  # noqa: E402

_EVAL_DIR = Path(__file__).resolve().parent.parent / "evals"


def load_eval_set(domain: str) -> list[str]:
    path = _EVAL_DIR / f"{domain}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["question"] for line in path.read_text().splitlines() if line.strip()]


def classify_all(domains: list[str]) -> list[dict]:
    """각 질문을 3경로로 분류. Bedrock은 질문당 1콜(예외 시 키워드 폴백)."""
    rows: list[dict] = []
    for gold in domains:
        for q in load_eval_set(gold):
            kw = _classify_keyword(q)
            try:
                braw, conf = _classify_bedrock(q)
                bfailed = False
            except Exception:
                braw, conf, bfailed = [], 0.0, True
            # full: supervisor_agent 배포 로직 재현 —
            #   Bedrock 성공+비어있지 않으면 그대로, 비었거나 실패면 키워드 백스톱.
            full = braw if (not bfailed and braw) else kw
            rows.append({
                "gold": gold, "q": q,
                "keyword": kw, "bedrock": braw, "full": full,
                "conf": conf, "bfailed": bfailed,
            })
    return rows


def _score(rows: list[dict], key: str) -> dict:
    """한 경로(key)의 지표 집계."""
    n = len(rows)
    hit = sum(1 for r in rows if r["gold"] in r[key])
    false_oos = sum(1 for r in rows if not r[key])
    over = sum(1 for r in rows if set(r[key]) - {r["gold"]})  # 정답 외 분야 포함 건수
    pred_slots = sum(len(r[key]) for r in rows)
    return {
        "recall": round(hit / n, 3),
        "miss": n - hit,
        "false_oos": false_oos,
        "over_fanout": over,
        "avg_domains": round(pred_slots / n, 2),
    }


def _per_domain_recall(rows: list[dict], key: str, domains: list[str]) -> dict:
    out = {}
    for d in domains:
        sub = [r for r in rows if r["gold"] == d]
        if sub:
            out[d] = round(sum(1 for r in sub if d in r[key]) / len(sub), 2)
    return out


def print_report(rows: list[dict], domains: list[str]):
    paths = [("keyword", "키워드 단독"), ("bedrock", "Bedrock raw"), ("full", "Bedrock+백스톱")]
    n = len(rows)

    print(f"\n{'='*64}")
    print(f"  라우팅 평가 — {n}문항 ({', '.join(domains)})")
    print(f"{'='*64}")

    # 경로별 종합 지표
    header = (
        f"  {'경로':<16}{'recall':>8}{'미스':>6}"
        f"{'거짓OOS':>8}{'과잉fanout':>11}{'평균분야':>9}"
    )
    print(header)
    print(f"  {'-'*58}")
    for key, label in paths:
        s = _score(rows, key)
        print(f"  {label:<16}{s['recall']:>8}{s['miss']:>6}{s['false_oos']:>8}"
              f"{s['over_fanout']:>11}{s['avg_domains']:>9}")

    # 분야별 recall (어디가 약한지)
    print("\n  분야별 recall")
    print(f"  {'경로':<16}" + "".join(f"{d:>10}" for d in domains))
    print(f"  {'-'*58}")
    for key, label in paths:
        pr = _per_domain_recall(rows, key, domains)
        print(f"  {label:<16}" + "".join(f"{pr.get(d, '-'):>10}" for d in domains))

    # 정성 근거: 키워드는 놓쳤지만 Bedrock이 구제한 사례
    rescued = [r for r in rows if r["gold"] not in r["keyword"] and r["gold"] in r["bedrock"]]
    print(f"\n  [키워드 미스 → Bedrock 구제] {len(rescued)}건" + (" (상위 6)" if rescued else ""))
    for r in rescued[:6]:
        print(
            f"    ({r['gold']}) {r['q'][:46]}  kw={r['keyword'] or '[]'} "
            f"→ bedrock={r['bedrock']}"
        )

    # 정성 근거: Bedrock 과잉 fan-out 사례 (precision 리스크)
    overs = [r for r in rows if set(r["bedrock"]) - {r["gold"]}]
    print(f"\n  [Bedrock 과잉 fan-out] {len(overs)}건" + (" (상위 6)" if overs else ""))
    for r in overs[:6]:
        print(f"    ({r['gold']}) {r['q'][:46]}  bedrock={r['bedrock']}")

    # Bedrock 호출 실패(폴백 발동)
    failed = [r for r in rows if r["bfailed"]]
    if failed:
        print(f"\n  ⚠️ Bedrock 호출 실패(키워드 폴백) {len(failed)}건")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    domains = DOMAINS if target == "all" else [target]
    if any(d not in DOMAINS for d in domains):
        print(f"분야는 {DOMAINS} 또는 all")
        sys.exit(1)

    tracker.reset()
    rows = classify_all(domains)
    print_report(rows, domains)

    cost = tracker.report()
    print(f"\n  [축② 비용] 호출 {cost['calls']}회  "
          f"토큰 {cost['input_tokens']}+{cost['output_tokens']}  ${cost['total_cost_usd']}")


if __name__ == "__main__":
    main()
