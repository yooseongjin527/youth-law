"""증분 감지: 법령 시행일을 manifest에 기록해두고, API의 현재 시행일과 비교
→ 바뀐 법령만 재수집·재적재한다. (법령은 거의 안 바뀌므로 대부분 스킵)

manifest 형식 (data/manifest.json):
{
  "laws": {
    "근로기준법": {"domain": "labor", "enforced_date": "20211119",
                   "mst": "...", "bronze_path": "...", "law_name": "근로기준법"},
    ...
  },
  "updated_at": "2026-06-10T09:00:00"
}
"""
import json
from datetime import datetime

from pipeline.config import MANIFEST


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"laws": {}, "updated_at": None}


def save_manifest(manifest: dict):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def diff_laws(manifest: dict, current_metas: list[dict]) -> list[dict]:
    """변경/신규 법령만 골라낸다. (순수 함수 — 테스트 대상)
    current_metas: bronze.fetch_law_meta 결과 리스트
    return: 재처리가 필요한 메타 리스트
    """
    recorded = manifest.get("laws", {})
    changed = []
    for meta in current_metas:
        prev = recorded.get(meta["law_name"])
        if prev is None:                                   # 신규
            changed.append(meta)
        elif prev.get("enforced_date") != meta["enforced_date"]:  # 개정(시행일 변경)
            changed.append(meta)
        # 동일하면 스킵 (대부분 여기)
    return changed


def record_laws(manifest: dict, domain: str, metas: list[dict]):
    """처리 완료한 법령들을 manifest에 기록."""
    for meta in metas:
        manifest["laws"][meta["law_name"]] = {**meta, "domain": domain}
