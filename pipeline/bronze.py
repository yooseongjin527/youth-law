"""Bronze: 국가법령정보센터 API → 원본 XML 저장.

medallion 1단계 — 원본을 가공 없이 그대로 보존한다.
(나중에 청킹 전략을 바꿔도 재호출 없이 Silver만 다시 돌리면 됨)

API (open.law.go.kr 공동활용):
  목록: /DRF/lawSearch.do?OC={OC}&target=law&type=XML&query={법령명}
  본문: /DRF/lawService.do?OC={OC}&target=law&type=XML&MST={MST}

⚠️ Day1: 키 수령 후 실제 응답의 태그명이 아래 파싱과 일치하는지
   샘플 1건으로 확인 (python -m pipeline.bronze labor 근로기준법)
"""
import sys
import time
import xml.etree.ElementTree as ET
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pipeline.config import BRONZE_DIR, LAW_LIST, LAW_OC

# https 권장 + UA 필수: 법령API가 기본 파이썬 UA를 막고 간헐적으로 연결을 리셋한다.
_BASE = "https://www.law.go.kr/DRF"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, retries: int = 4) -> str:
    last = None
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=_HEADERS), timeout=30) as r:
                return r.read().decode("utf-8")
        except (URLError, ConnectionResetError, TimeoutError) as e:
            last = e
            time.sleep(2 * (i + 1))  # 백오프 — 정부 API 리셋 대비
    raise RuntimeError(f"law.go.kr 호출 실패({retries}회): {url}") from last


def fetch_law_meta(law_name: str) -> dict | None:
    """법령 목록 API에서 법령의 MST·시행일자 등 메타 조회."""
    url = f"{_BASE}/lawSearch.do?OC={LAW_OC}&target=law&type=XML&query={quote(law_name)}"
    root = ET.fromstring(_get(url))
    # 검색 결과 중 법령명이 정확히 일치하는 첫 건
    for law in root.iter("law"):
        name_el = law.find("법령명한글")
        if name_el is not None and name_el.text and name_el.text.strip() == law_name:
            def _t(tag):
                el = law.find(tag)
                return el.text.strip() if el is not None and el.text else ""
            return {
                "law_name": law_name,
                "mst": _t("법령일련번호") or _t("MST"),
                "law_id": _t("법령ID"),
                "enforced_date": _t("시행일자"),
                "promulgated_date": _t("공포일자"),
            }
    return None


def fetch_law_body(mst: str) -> str:
    """법령 본문 XML 원문."""
    url = f"{_BASE}/lawService.do?OC={LAW_OC}&target=law&type=XML&MST={mst}"
    return _get(url)


def collect_domain(domain: str) -> list[dict]:
    """분야의 모든 법령을 수집해 bronze에 저장. 메타 리스트 반환."""
    out_dir = BRONZE_DIR / domain
    out_dir.mkdir(parents=True, exist_ok=True)
    metas = []
    for law_name in LAW_LIST[domain]:
        meta = fetch_law_meta(law_name)
        if not meta:
            print(f"  ⚠️ 목록에서 못 찾음: {law_name} (config.py 법령명 확인)")
            continue
        xml_body = fetch_law_body(meta["mst"])
        path = out_dir / f"{law_name}.xml"
        path.write_text(xml_body, encoding="utf-8")
        meta["bronze_path"] = str(path)
        metas.append(meta)
        print(f"  ✓ bronze: {law_name} (시행 {meta['enforced_date']})")
    return metas


if __name__ == "__main__":
    domain = sys.argv[1] if len(sys.argv) > 1 else "labor"
    if not LAW_OC:
        sys.exit("LAW_GO_KR_OC 가 .env에 없습니다 (docs/API_SETUP.md)")
    collect_domain(domain)
