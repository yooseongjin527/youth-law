"""Silver: Bronze XML → 조문 단위 청크(jsonl).

medallion 2단계 — 법령은 '조문'이 자연스러운 청크 단위.
메타데이터(법령명·조번호·시행일·출처URL)를 청크마다 붙인다
→ 답변의 출처 표시(신뢰성 차별점)가 여기서 만들어진다.

⚠️ 파싱은 국가법령정보센터 표준 응답 구조(조문단위/조문번호/조문내용) 기준.
   Day1 샘플에서 태그가 다르면 _CANDIDATES만 수정하면 된다.
"""
import json
import sys
import xml.etree.ElementTree as ET

from pipeline.config import SILVER_DIR

# 기관 API의 태그명 후보 (버전에 따라 다를 수 있어 복수 대응)
_CANDIDATES = {
    "unit": ["조문단위", "조문"],
    "no": ["조문번호", "조번호"],
    "branch": ["조문가지번호"],   # 제43조의2 의 "2" — 본 조문과 id 충돌 방지에 필수
    "title": ["조문제목", "조제목"],
    "content": ["조문내용", "조내용"],
    "kind": ["조문여부"],          # "전문"=장·절 제목(조문 아님) / "조문"=실제 조
    "subcontent": ["항내용", "호내용", "목내용"],  # 긴 조문 본문은 항·호·목 하위요소에 온다
}


def _find_text(el, keys: list[str]) -> str:
    for k in keys:
        found = el.find(k)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def parse_law_xml(xml_text: str, law_name: str, enforced_date: str, law_id: str = "") -> list[dict]:
    """법령 본문 XML → 조문 청크 리스트. (순수 함수 — 테스트 대상)"""
    root = ET.fromstring(xml_text)
    chunks = []
    units = []
    for tag in _CANDIDATES["unit"]:
        units = list(root.iter(tag))
        if units:
            break
    for u in units:
        # 장·절 제목(전문)은 조번호를 갖지만 실제 조문 아님 → 스킵(실조문과 id 충돌·노이즈 방지)
        if _find_text(u, _CANDIDATES["kind"]) == "전문":
            continue
        no = _find_text(u, _CANDIDATES["no"])
        branch = _find_text(u, _CANDIDATES["branch"])
        title = _find_text(u, _CANDIDATES["title"])
        content = _find_text(u, _CANDIDATES["content"])
        # 긴 조문(제17조 청약철회 등)은 조문내용에 헤더("제17조(청약철회등)")만 오고
        # 실제 본문은 항·호·목 하위요소에 온다. 헤더만 쓰면 핵심 조문이 빈 껍데기가 되므로
        # 항·호·목 본문을 문서 순서대로 헤더에 합친다(없으면 조문내용이 곧 전문).
        sub_texts = [t.text.strip() for t in u.iter()
                     if t.tag in _CANDIDATES["subcontent"] and t.text and t.text.strip()]
        body = " ".join([content, *sub_texts]).strip() if sub_texts else content
        if not (no and body):
            continue
        article = no if no.startswith("제") else f"제{no}조"
        if branch and branch != "0":          # 제43조의2 처럼 가지조항 식별
            article = f"{article}의{branch}"
        chunks.append({
            "law_name": law_name,
            "article": article,
            "title": title,
            "text": f"{title}. {body}" if title else body,
            "enforced_date": enforced_date,
            "source_url": f"https://www.law.go.kr/법령/{law_name}",
        })
    return chunks


def build_silver(domain: str, metas: list[dict]) -> int:
    """분야의 bronze XML들을 청킹해 silver jsonl로 저장. 청크 수 반환."""
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    out = SILVER_DIR / f"{domain}.jsonl"
    total = 0
    with open(out, "w", encoding="utf-8") as f:
        for meta in metas:
            xml_text = open(meta["bronze_path"], encoding="utf-8").read()
            chunks = parse_law_xml(xml_text, meta["law_name"], meta["enforced_date"])
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
            total += len(chunks)
            print(f"  ✓ silver: {meta['law_name']} → {len(chunks)}개 조문")
    return total


if __name__ == "__main__":
    # 단독 실행: bronze에 이미 받아둔 분야를 청킹 (메타는 manifest에서)
    from pipeline.detect import load_manifest
    domain = sys.argv[1] if len(sys.argv) > 1 else "labor"
    manifest = load_manifest()
    metas = [m for m in manifest.get("laws", {}).values() if m.get("domain") == domain]
    print(f"{build_silver(domain, metas)}개 청크 생성")
