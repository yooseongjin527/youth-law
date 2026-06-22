"""배포/로컬 API E2E 스모크 — 데모 핵심 4케이스를 고정 검증한다.

사용:
  python scripts/e2e_smoke.py
  python scripts/e2e_smoke.py --base-url https://youthlaw-demo.duckdns.org

검증 범위:
  - health
  - 단일 분야 상담
  - 복수 분야 라우팅
  - 범위 밖 질문
  - 문서 초안 생성
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")


class SmokeFailure(AssertionError):
    """스모크 검증 실패."""


def _json_request(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(f"{method} {path} HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"{method} {path} 연결 실패: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{method} {path} JSON 파싱 실패: {body[:300]}") from exc


def _get(base_url: str, path: str, timeout: float) -> dict[str, Any]:
    return _json_request("GET", base_url, path, None, timeout)


def _post(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    return _json_request("POST", base_url, path, payload, timeout)


def _domain_ids(data: dict[str, Any]) -> set[str]:
    return {item.get("id", "") for item in data.get("domains", [])}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _require_answer_contract(data: dict[str, Any], expected_domain: str | None = None) -> None:
    _require(data.get("in_scope") is True, "in_scope=true 여야 함")
    _require(bool(data.get("final_answer")), "final_answer가 비어 있음")
    _require(bool(data.get("answer_blocks")), "answer_blocks가 비어 있음")
    if expected_domain:
        _require(expected_domain in _domain_ids(data), f"{expected_domain} 라우팅 누락")
    has_citation = any(block.get("citations") for block in data.get("answer_blocks", []))
    _require(has_citation, "answer_blocks 안에 citations가 없음")


def case_health(base_url: str, timeout: float) -> None:
    data = _get(base_url, "/health", timeout)
    _require(data.get("status") == "ok", f"health status 이상: {data}")


def case_single_housing(base_url: str, timeout: float) -> None:
    data = _post(
        base_url,
        "/api/consult",
        {"question": "전세 보증금을 안 돌려줘요"},
        timeout,
    )
    _require_answer_contract(data, expected_domain="housing")


def case_multi_domain(base_url: str, timeout: float) -> None:
    data = _post(
        base_url,
        "/api/consult",
        {"question": "월급도 안 주고 기숙사 보증금도 안 줘요"},
        timeout,
    )
    _require_answer_contract(data)
    domains = _domain_ids(data)
    _require({"labor", "housing"}.issubset(domains), f"복수 분야 라우팅 실패: {domains}")


def case_out_of_scope(base_url: str, timeout: float) -> None:
    data = _post(
        base_url,
        "/api/consult",
        {"question": "친구가 때려서 고소하고 싶어요"},
        timeout,
    )
    _require(data.get("in_scope") is False, "범위 밖 질문은 in_scope=false 여야 함")
    _require(data.get("domains") == [], f"범위 밖 질문 domains가 비어 있지 않음: {data}")
    _require(data.get("answer_blocks") == [], "범위 밖 질문 answer_blocks가 비어 있지 않음")
    _require(bool(data.get("final_answer")), "범위 밖 안내 final_answer가 비어 있음")


def case_draft_labor(base_url: str, timeout: float) -> None:
    data = _post(
        base_url,
        "/api/draft",
        {"question": "월급을 못 받았어요", "domain": "labor"},
        timeout,
    )
    _require(data.get("domain") == "labor", f"초안 domain 이상: {data}")
    _require(bool(data.get("title")), "초안 title이 비어 있음")
    _require(bool(data.get("body")), "초안 body가 비어 있음")
    _require(bool(data.get("based_on")), "초안 based_on이 비어 있음")
    _require("초안" in data.get("guide", ""), "초안 안내문에 '초안' 문구가 없음")


CASES = [
    ("health", case_health),
    ("single-housing", case_single_housing),
    ("multi-domain", case_multi_domain),
    ("out-of-scope", case_out_of_scope),
    ("draft-labor", case_draft_labor),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Youth-law API E2E smoke test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    failures: list[str] = []
    for name, fn in CASES:
        try:
            fn(args.base_url, args.timeout)
        except SmokeFailure as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAIL {name}: {exc}")
        else:
            print(f"PASS {name}")

    if failures:
        print("\nE2E smoke failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"\nE2E smoke passed: {args.base_url.rstrip('/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
