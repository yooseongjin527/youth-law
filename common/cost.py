"""비용 추적 + 모델 티어링 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

★ 개선 축 ② 비용 ★
- 모델 티어링: 작업 난이도에 맞는 모델 사용. 분류(짧은 출력)는 Haiku,
  답변 생성만 Sonnet → 같은 품질, 더 싸게.
- 토큰 추적: 모든 Bedrock 호출의 입출력 토큰을 기록 → 쿼리당 비용 산출.

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day3] ① 모델 ID를 팀이 결정한 실제 ID로 (.env)
  [공용/Day3] ② PRICING을 해당 모델 실제 단가로 갱신
  [공용/Day5] ③ "Supervisor Haiku 전환으로 N% 절감" 비교 측정 (발표용)
────────────────────────────────────────────────────────
"""
import os

from dotenv import load_dotenv

load_dotenv()  # .env 로드 — MODEL_TIERS가 임포트 순서와 무관하게 실제 모델 ID를 읽도록

# 작업별 모델 티어 — 비싼 모델을 모든 곳에 쓰지 않는다
MODEL_TIERS = {
    "classify": os.getenv("BEDROCK_MODEL_SMALL", "anthropic.claude-haiku(예시)"),
    "verify":   os.getenv("BEDROCK_MODEL_SMALL", "anthropic.claude-haiku(예시)"),
    "answer":   os.getenv("BEDROCK_MODEL_MAIN", "anthropic.claude-sonnet(예시)"),
    "draft":    os.getenv("BEDROCK_MODEL_MAIN", "anthropic.claude-sonnet(예시)"),
}

# USD / 1K tokens (input, output) — TODO(공용/Day3): 실제 단가로
PRICING = {
    "small": (0.0008, 0.004),   # Haiku급 예시 단가
    "main":  (0.003, 0.015),    # Sonnet급 예시 단가
}


def _tier_of(task: str) -> str:
    return "small" if task in ("classify", "verify") else "main"


class UsageTracker:
    """토큰 사용량 누적. llm.py가 모든 호출에서 record()를 부른다."""

    def __init__(self):
        self.records: list[dict] = []

    def record(self, task: str, input_tokens: int, output_tokens: int):
        tier = _tier_of(task)
        in_p, out_p = PRICING[tier]
        cost = input_tokens / 1000 * in_p + output_tokens / 1000 * out_p
        self.records.append({
            "task": task, "tier": tier,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        })

    def report(self) -> dict:
        total_in = sum(r["input_tokens"] for r in self.records)
        total_out = sum(r["output_tokens"] for r in self.records)
        total_cost = sum(r["cost_usd"] for r in self.records)
        by_task: dict = {}
        for r in self.records:
            t = by_task.setdefault(r["task"], {"calls": 0, "cost_usd": 0.0})
            t["calls"] += 1
            t["cost_usd"] = round(t["cost_usd"] + r["cost_usd"], 6)
        return {
            "calls": len(self.records),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_cost_usd": round(total_cost, 6),
            "by_task": by_task,
        }

    def reset(self):
        self.records = []


# 전역 트래커 — llm.py와 evaluate.py가 공유
tracker = UsageTracker()
