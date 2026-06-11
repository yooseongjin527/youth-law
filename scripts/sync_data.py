"""S3로 데이터·평가결과를 팀원 간 공유 — 충돌 없는 스코프 동기화.

⚠️ 왜 스코프를 나누나:
  - silver/<분야>.jsonl, bronze/<분야>/, evals/results/<분야>_* 는 '분야별 파일'이라
    각자 올려도 안 겹친다(합쳐짐).
  - 그러나 chroma(벡터DB)·manifest.json 은 4분야가 '한 덩어리'라, 여러 명이 올리면
    서로 덮어쓴다. → chroma+manifest는 '빌더' 한 명(또는 EC2)만 push.

권장 흐름:
  1) 각자:   python scripts/sync_data.py push mine     # 내 분야 silver/bronze/evals만
  2) 빌더:   python scripts/sync_data.py pull          # 모두 받고
             python scripts/build_index.py all         # 4분야 통합 빌드
             python scripts/sync_data.py push corpus   # chroma+manifest 올림
  3) 나머지: python scripts/sync_data.py pull          # 통합 chroma 받기(4분야 다 들어옴)

명령:
  pull                 # S3 → 로컬 (data/ 전체 + evals/results 전체)
  push mine [분야]     # 내 분야 산출물만 올림 (분야 생략 시 .env의 MY_DOMAIN)
  push corpus          # chroma + manifest 올림 (빌더 전용)

사전: aws CLI + 자격증명(aws configure), 버킷 생성, .env 의 S3_DATA_BUCKET.
"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

BUCKET = os.getenv("S3_DATA_BUCKET", "").strip()
REGION = os.getenv("AWS_REGION", "us-west-2")
DOMAINS = ["labor", "housing", "consumer", "finance"]


def _sync(src, dst, filters):
    cmd = ["aws", "s3", "sync", src, dst, "--region", REGION] + filters
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True)


def pull():
    """S3 → 로컬: 전체 받기 (충돌 없음 — 받기는 안전)."""
    _sync(f"s3://{BUCKET}/data/", "data", [])
    _sync(f"s3://{BUCKET}/evals/results/", "evals/results", [])


def push_mine(domain):
    """내 분야 산출물만 올림 (분야별 파일 → 다른 사람과 안 겹침)."""
    print(f"[push mine] 분야={domain} — silver/bronze/evals만 (chroma 안 건드림)")
    _sync("data", f"s3://{BUCKET}/data",
          ["--exclude", "*", "--include", f"silver/{domain}.jsonl",
           "--include", f"bronze/{domain}/*"])
    _sync("evals/results", f"s3://{BUCKET}/evals/results",
          ["--exclude", "*", "--include", f"{domain}_*"])


def push_corpus():
    """chroma + manifest 올림 — ⚠️ 빌더 한 명만(통합 빌드 후)."""
    print("[push corpus] chroma + manifest — 빌더 전용(여러 명이 하면 덮어씀)")
    _sync("data", f"s3://{BUCKET}/data",
          ["--exclude", "*", "--include", "chroma/*", "--include", "manifest.json"])


if __name__ == "__main__":
    if not BUCKET:
        sys.exit("S3_DATA_BUCKET 가 .env에 없습니다. 예: S3_DATA_BUCKET=youth-law-data")
    args = sys.argv[1:]
    if not args or args[0] not in ("pull", "push"):
        sys.exit("사용: python scripts/sync_data.py <pull | push mine [분야] | push corpus>")

    if args[0] == "pull":
        pull()
    else:  # push
        scope = args[1] if len(args) > 1 else ""
        if scope == "corpus":
            push_corpus()
        elif scope == "mine":
            domain = args[2] if len(args) > 2 else os.getenv("MY_DOMAIN", "").strip()
            if domain not in DOMAINS:
                sys.exit(f"분야를 지정하세요: push mine <{'|'.join(DOMAINS)}> "
                         f"(또는 .env에 MY_DOMAIN=)")
            push_mine(domain)
        else:
            sys.exit("push 스코프: 'mine [분야]' 또는 'corpus'")
    print("완료.")
