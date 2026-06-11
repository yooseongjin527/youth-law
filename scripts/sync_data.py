"""S3로 빌드 산출물(벡터DB)·평가결과를 팀원 간 공유 — 동기화 도구.

data/ 는 .gitignore라 git으론 못 나눈다. 대신 S3 버킷을 "공용 창고"로 써서
한 명이 빌드한 결과를 나머지가 받아 쓰고(빌드/OC키 불필요), 평가결과도 한 곳에 모은다.

사용:
  python scripts/sync_data.py pull          # S3 → 로컬 (받기, 기본 data+evals)
  python scripts/sync_data.py push          # 로컬 → S3 (올리기)
  python scripts/sync_data.py pull data     # 벡터DB·코퍼스만
  python scripts/sync_data.py push evals    # 평가결과(evals/results)만

사전 준비:
  - aws CLI + 자격증명 (aws configure 또는 환경변수)
  - 버킷 1회 생성(한 명):  aws s3 mb s3://<버킷명> --region us-west-2
  - .env 에  S3_DATA_BUCKET=<버킷명>   (팀 공유)

기본은 '추가(additive)' 동기화 — 로컬에만 있는 파일을 지우지 않는다.
완전 미러(원본에 없는 건 삭제)를 원하면 끝에 --mirror 를 붙인다.
"""
import os
import subprocess
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

BUCKET = os.getenv("S3_DATA_BUCKET", "").strip()
REGION = os.getenv("AWS_REGION", "us-west-2")

# scope: (로컬 경로, S3 prefix)
TARGETS = {
    "data": ("data", "data"),               # bronze/silver/chroma/manifest
    "evals": ("evals/results", "evals/results"),  # 3축 평가 이력
}


def sync(direction: str, scope: str, mirror: bool):
    if not BUCKET:
        sys.exit("S3_DATA_BUCKET 가 .env에 없습니다. 예: S3_DATA_BUCKET=youth-law-data")
    scopes = list(TARGETS) if scope == "all" else [scope]
    for s in scopes:
        local, prefix = TARGETS[s]
        s3 = f"s3://{BUCKET}/{prefix}/"
        os.makedirs(local, exist_ok=True)
        src, dst = (s3, local) if direction == "pull" else (local, s3)
        cmd = ["aws", "s3", "sync", src, dst, "--region", REGION]
        if mirror:
            cmd.append("--delete")
        print(f"[{direction}] {src}  ->  {dst}" + ("  (--delete)" if mirror else ""))
        subprocess.run(cmd, check=True)
    print("완료.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--mirror"]
    mirror = "--mirror" in sys.argv
    if not args or args[0] not in ("pull", "push"):
        sys.exit("사용: python scripts/sync_data.py <pull|push> [data|evals|all] [--mirror]")
    direction = args[0]
    scope = args[1] if len(args) > 1 else "all"
    if scope not in ("data", "evals", "all"):
        sys.exit("scope 는 data | evals | all")
    sync(direction, scope, mirror)
