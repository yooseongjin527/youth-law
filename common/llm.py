"""LLM 호출 헬퍼 — 공용 파일 ⚠️ (변경은 PR + 전원 합의).

★ 하네스: 구조화 출력 강제 + 재시도 루프 (docs/HARNESS.md A-3) ★
★ 비용: 작업별 모델 티어링 + 사용량 자동 기록 (common/cost.py) ★

모든 Bedrock 호출은 이 파일을 거친다 — 그래야 비용 추적이 빠짐없이 된다.

────────────────────────────────────────────────────────
TODO 우선순위
  [공용/Day3] ① call_bedrock 실제 구현 (boto3 invoke_model)
       - task로 MODEL_TIERS에서 모델 선택 (classify=Haiku, answer=Sonnet)
       - 응답의 usage(input/output tokens)를 tracker.record()로 기록
  [공용/Day3] ② 전문가들이 call_bedrock_json(task="answer")으로 형식 강제
────────────────────────────────────────────────────────
"""
import json
import os

from common.cost import MODEL_TIERS, tracker

_client = None  # bedrock-runtime 클라이언트 싱글톤 (임포트 시 AWS 의존 안 하도록 지연 생성)


def _get_client():
    global _client
    if _client is None:
        import boto3  # 지연 임포트 — CI/오프라인에서 임포트만으로 실패하지 않게
        _client = boto3.client(
            "bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-west-2")
        )
    return _client


def call_bedrock(prompt: str, task: str = "answer", max_tokens: int = 1024) -> str:
    """Bedrock Claude 호출(boto3 invoke_model). task에 따라 모델 티어 자동 선택.
    task: classify(분류, Haiku급) / verify(검증) / answer(답변, Sonnet급) / draft(초안)

    모델 ID는 .env의 inference profile(us.anthropic.…). Sonnet 4.6/Haiku 4.5는
    sampling 파라미터·thinking을 생략(보내면 400 위험) — 단순 메시지 호출만 한다.
    사용량(input/output 토큰)은 tracker.record로 기록 → 비용 축 추적.
    """
    model_id = MODEL_TIERS[task]  # 잘못된 task면 KeyError로 즉시 실패
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    resp = _get_client().invoke_model(modelId=model_id, body=body)
    data = json.loads(resp["body"].read())

    usage = data.get("usage", {})
    tracker.record(task, usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def call_bedrock_json(
    prompt: str, required_keys: list[str], task: str = "answer", max_retries: int = 2
) -> dict:
    """JSON 형식을 '강제'하는 호출 — 하네스 패턴.
    1) JSON-only 지시 + 필수 키 명시
    2) 파싱 실패/키 누락 시 오류를 알려주며 자동 재시도
    3) 재시도 소진 시 예외 → 호출자가 안전 폴백 (그 답변은 verifier에서 탈락)
    """
    json_prompt = (
        prompt
        + "\n\n반드시 JSON만 출력하세요. 마크다운 코드블록·설명 금지."
        + f"\n필수 키: {required_keys}"
    )
    last_err = ""
    for _ in range(max_retries + 1):
        raw = call_bedrock(
            json_prompt + (f"\n(이전 오류: {last_err})" if last_err else ""), task=task
        )
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            missing = [k for k in required_keys if k not in data]
            if missing:
                last_err = f"누락된 키: {missing}"
                continue
            return data
        except json.JSONDecodeError as e:
            last_err = f"JSON 파싱 실패: {e}"
            continue
    raise ValueError(f"구조화 출력 실패 (재시도 소진): {last_err}")
