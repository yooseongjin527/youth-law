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


def _traced(fn):
    """모든 Bedrock 호출을 LangSmith LLM 트레이스로 감싼다.

    ★ 왜 명시적 래핑인가 ★: 이 프로젝트는 LangChain LLM 래퍼가 아니라 raw Bedrock
    (boto3 invoke_model)을 쓴다 → LangSmith 자동추적이 안 잡힌다. call_bedrock 하나만
    감싸면 모든 호출(classify/answer/verify/draft, 재시도 포함)이 트레이스에 잡히고,
    LangGraph 노드 실행(tracing on 시 자동) 아래로 자연히 nesting된다.

    안전장치: langsmith 미설치면 원함수 그대로(무비용). 설치돼 있어도
    LANGCHAIN_TRACING_V2=true + LANGSMITH_API_KEY일 때만 실제 전송된다(off면 거의 무비용).
    """
    try:
        from langsmith import traceable
    except Exception:
        return fn
    return traceable(run_type="llm", name="bedrock_call")(fn)


def _timeout(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_client():
    global _client
    if _client is None:
        import boto3  # 지연 임포트 — CI/오프라인에서 임포트만으로 실패하지 않게
        from botocore.config import Config

        config = Config(
            connect_timeout=_timeout("BEDROCK_CONNECT_TIMEOUT", 3.0),
            read_timeout=_timeout("BEDROCK_READ_TIMEOUT", 12.0),
            retries={
                "max_attempts": int(_timeout("BEDROCK_MAX_ATTEMPTS", 2.0)),
                "mode": "standard",
            },
        )
        _client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-west-2"),
            config=config,
        )
    return _client


@_traced
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
