# evals/ — 분야별 평가셋

각자 자기 분야 jsonl을 **10~20문항으로 확장**하세요 (Day 1~2, 리스크 ⑤).
형식: {"question": 평어 질문, "expected_articles": [정답 조문들], "note": 메모}

- 질문은 실제 사용자처럼 평어로 (법률 용어 없이)
- expected_articles는 "법령명 제N조" 형식 — 검색 결과의 law_name+article과 대조됨
- 좋은 평가셋 = 쉬운 것·어려운 것·애매한 것 섞기

실행: `python scripts/evaluate.py labor`
결과는 results/<분야>_history.jsonl에 날짜와 함께 누적 → 개선 추이가 발표 자료가 됨.
