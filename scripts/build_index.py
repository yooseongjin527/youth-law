"""분야별 벡터DB 인덱싱 — pipeline(medallion)으로 위임하는 래퍼.

사용법:
  python scripts/build_index.py labor    # 한 분야 전체 구축 (bronze→silver→gold)
  python scripts/build_index.py all

증분 갱신은 scripts/update_laws.py (배치/cron/Airflow용) 사용.
"""
import sys

sys.path.insert(0, ".")
from pipeline.config import LAW_LIST  # noqa: E402
from scripts.update_laws import update_domain  # noqa: E402

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    domains = list(LAW_LIST) if target == "all" else [target]
    for d in domains:
        update_domain(d, full=True)   # 최초 구축 = 전체 모드
