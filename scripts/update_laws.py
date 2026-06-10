"""법령 데이터 배치 갱신 — cron/Airflow가 호출하는 진입점.

사용법:
  python scripts/update_laws.py                 # 전 분야 증분 갱신 (기본)
  python scripts/update_laws.py --domain labor  # 한 분야만
  python scripts/update_laws.py --full          # 증분 무시, 전체 재구축

흐름 (분야별):
  [감지] API 목록에서 현재 시행일 조회 → manifest와 비교 → 변경분만
  [Bronze] 변경 법령 원본 XML 저장
  [Silver] 조문 단위 청킹
  [Gold]   임베딩 → Chroma upsert (같은 id 덮어씀 = 증분과 호환)
  [기록]   manifest 갱신

주기 권장: 주 1회 (법령은 거의 안 바뀜 — docs/INFRA.md 참고)
"""
import argparse
import sys

sys.path.insert(0, ".")
from pipeline import bronze, detect, gold, silver  # noqa: E402
from pipeline.config import LAW_LIST, LAW_OC  # noqa: E402


def update_domain(domain: str, full: bool = False) -> dict:
    print(f"\n[{domain}] 갱신 시작 {'(전체 재구축)' if full else '(증분)'}")
    manifest = detect.load_manifest()

    # 1) 현재 메타 조회 (목록 API — 가벼움)
    current = []
    for law_name in LAW_LIST[domain]:
        meta = bronze.fetch_law_meta(law_name)
        if meta:
            current.append(meta)
        else:
            print(f"  ⚠️ 못 찾음: {law_name}")

    # 2) 변경 감지
    targets = current if full else detect.diff_laws(manifest, current)
    if not targets:
        print(f"  변경 없음 — 스킵 (등록 {len(current)}건 모두 최신)")
        return {"domain": domain, "checked": len(current), "updated": 0}

    # 3) Bronze: 본문 수집 (변경분만)
    for meta in targets:
        xml_body = bronze.fetch_law_body(meta["mst"])
        path = bronze.BRONZE_DIR / domain
        path.mkdir(parents=True, exist_ok=True)
        p = path / f"{meta['law_name']}.xml"
        p.write_text(xml_body, encoding="utf-8")
        meta["bronze_path"] = str(p)
        print(f"  ✓ bronze: {meta['law_name']}")

    # 4) Silver: 해당 분야 전체 재청킹 (jsonl 단위라 분야 통째가 단순·안전)
    detect.record_laws(manifest, domain, targets)
    all_metas = [m for m in manifest["laws"].values() if m.get("domain") == domain]
    n_chunks = silver.build_silver(domain, all_metas)

    # 5) Gold: 임베딩·적재
    n_loaded = gold.load_gold(domain)

    # 6) 기록
    detect.save_manifest(manifest)
    print(f"  완료: 변경 {len(targets)}건 → 청크 {n_chunks} → 적재 {n_loaded}")
    return {"domain": domain, "checked": len(current), "updated": len(targets)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="all")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    if not LAW_OC:
        sys.exit("LAW_GO_KR_OC 가 .env에 없습니다 (docs/API_SETUP.md). "
                 "python-dotenv 사용 시 .env 로드 확인")
    domains = list(LAW_LIST) if args.domain == "all" else [args.domain]
    for d in domains:
        update_domain(d, full=args.full)
