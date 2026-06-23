"""배포/로컬 API E2E 스모크 — 데모 핵심 케이스를 고정 검증한다.

사용:
  python scripts/e2e_smoke.py
  python scripts/e2e_smoke.py --base-url https://youthlaw-demo.duckdns.org
  python scripts/e2e_smoke.py --multidomain     # 멀티도메인 회귀 게이트 추가(느림·라이브 LLM)

검증 범위(기본 — 가벼운 CI 스모크):
  - health
  - 단일 분야 상담
  - 복수 분야 라우팅(분류)
  - 범위 밖 질문
  - 문서 초안 생성

--multidomain 추가(옵트인):
  - 2/3/4개 분야 혼합 질문에서 '분류된 모든 분야가 카드로 렌더되는지' 검증.
    (분류만 맞고 한 분야가 verifier에서 조용히 탈락하는 silent-drop 회귀 차단 —
     기본 multi-domain 케이스는 카드 1장만 떠도 통과하므로 이 사각지대를 못 잡는다.)
    분해(supervisor 서브쿼리)+검증 통과까지 타므로 케이스당 LLM 다수 호출 = 느림.
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


def _rendered_domains(data: dict[str, Any]) -> set[str]:
    return {block.get("domain", "") for block in data.get("answer_blocks", [])}


def _require_all_domains_render(data: dict[str, Any], expected: set[str]) -> None:
    """기대 분야가 ① 전부 분류되고 ② 전부 카드로 렌더되는지(=silent drop 없음) 검증.

    핵심: 분류(domains)만이 아니라 answer_blocks(렌더 카드)까지 본다. 한 분야가
    verifier에서 탈락하면 분류는 맞아도 카드가 빠지는데, 그 사각지대를 여기서 막는다."""
    classified = _domain_ids(data)
    rendered = _rendered_domains(data)
    _require(
        expected <= classified,
        f"분류 누락: 기대 {sorted(expected)}, 실제 {sorted(classified)}",
    )
    _require(
        expected <= rendered,
        f"카드 누락(silent drop): 기대 {sorted(expected)}, 렌더 {sorted(rendered)}",
    )


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


# ── 멀티도메인 회귀 게이트(옵트인) ──────────────────────────────────
# 분해+검증이 다수 LLM 호출을 타므로 per-case 타임아웃을 넉넉히(특히 4-domain).
_MULTI_MIN_TIMEOUT = 120.0


# 라이브 LLM 1회 재시도: 딜루션 회귀는 '항상' 같은 분야를 떨궈 두 번 다 실패한다.
# 반면 verifier confidence가 경계(≈0.5)에 걸친 일시적 LLM 노이즈는 재시도로 흡수한다
# (회귀는 못 가리고, 비결정성만 완화 — 라이브 LLM 게이트의 표준 처리).
_MULTI_RETRIES = 1


def _multidomain_case(question: str, expected: set[str]):
    """'기대 분야 전부 렌더' 검증 케이스 팩토리(silent-drop 회귀 차단)."""
    def case(base_url: str, timeout: float) -> None:
        last: SmokeFailure | None = None
        for _ in range(_MULTI_RETRIES + 1):
            data = _post(
                base_url, "/api/consult", {"question": question},
                max(timeout, _MULTI_MIN_TIMEOUT),
            )
            try:
                _require_answer_contract(data)
                _require_all_domains_render(data, expected)
                return
            except SmokeFailure as exc:
                last = exc
        raise last  # 재시도 소진 — 일관된 실패 = 진짜 회귀
    return case


# 분야 수별 대표 케이스(2/3/4). finance 포함 조합 위주 — 이번 silent-drop의 발생 표면.
MULTIDOMAIN_CASES = [
    ("multi2-finance-labor",
     _multidomain_case(
         "알바비도 떼였는데 사채 빚 독촉 전화까지 매일 받고 있어요",
         {"finance", "labor"})),
    ("multi2-finance-housing",
     _multidomain_case(
         "전세 보증금을 집주인이 안 돌려주는데 빚이 많아 개인회생까지 알아보고 있어요",
         {"finance", "housing"})),
    ("multi2-finance-consumer",
     _multidomain_case(
         "인터넷으로 산 옷 환불을 판매자가 거부하는데, 사채 빚 독촉까지 받고 있어요",
         {"finance", "consumer"})),
    ("multi3-labor-housing-finance",
     _multidomain_case(
         "회사가 망해서 월급도 못 받고 해고됐는데, 사채 빚 독촉에 시달리고 "
         "기숙사 보증금도 못 받았어요",
         {"labor", "housing", "finance"})),
    ("multi4-all",
     _multidomain_case(
         "알바비도 못 받고(해고됨), 전세 보증금도 못 돌려받고, 인터넷으로 산 옷 환불도 "
         "안 되고, 사채 빚 독촉까지 받고 있어요",
         {"labor", "housing", "consumer", "finance"})),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Youth-law API E2E smoke test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--multidomain", action="store_true",
        help="2/3/4개 분야 혼합 질문의 '전부 렌더' 회귀 게이트 추가(느림·라이브 LLM)",
    )
    args = parser.parse_args()

    cases = CASES + MULTIDOMAIN_CASES if args.multidomain else CASES
    failures: list[str] = []
    for name, fn in cases:
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
