"""RAG 빠른 점검 — 실데이터(벡터DB) 연결·검색이 되는지 확인.

사용:
  python scripts/check_rag.py                 # consumer 기본 질의
  python scripts/check_rag.py labor           # 분야 지정
  python scripts/check_rag.py labor 야근수당 못 받았어   # 분야 + 질의

(셸 따옴표 문제 없이 어디서나 동작 — bash/PowerShell/cmd 동일)
"""
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 크래시 방지
except Exception:
    pass

from common.rag import DomainRAG  # noqa: E402

domain = sys.argv[1] if len(sys.argv) > 1 else "consumer"
query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "인터넷 쇼핑 환불 청약철회"

rag = DomainRAG(domain=domain)
count = rag.collection.count() if rag.collection else 0
print(f"[{domain}] 실모드: {rag.is_real} | 조문수: {count}")
if not rag.is_real:
    print("  ⚠️ stub 모드입니다 — 데이터 미구축 또는 chromadb 미설치.")
    print("     pip install chromadb sentence-transformers 후 build_index.py 실행.")
print(f"질의: {query}")
for c in rag.search(query, k=3):
    print(f"  [{c['score']}] {c['law_name']} {c['article']} (시행 {c['enforced_date']})")
