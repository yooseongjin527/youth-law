# evals/ — 분야별 평가셋

각자 자기 분야 jsonl을 **10~20문항으로 확장**하세요 (Day 1~2, 리스크 ⑤).
형식: {"question": 평어 질문, "expected_articles": [정답 조문들], "note": 메모}
선택 필드: `category`(예: voice_phishing/debt_restructuring/collection/loan), `difficulty`

- 질문은 실제 사용자처럼 평어로 (법률 용어 없이)
- expected_articles는 "법령명 제N조" 형식 — 검색 결과의 law_name+article과 대조됨
- 좋은 평가셋 = 쉬운 것·어려운 것·애매한 것 섞기
- finance smoke: `evals/finance.jsonl` (회귀/스모크용)
- finance benchmark: `evals/finance_benchmark.jsonl` (확장 평가용)
- finance는 하위 법군이 많아 category별 리포트를 같이 보는 걸 권장
- consumer는 3법(전자상거래·방문판매·할부) 라우팅을 쓰므로 법별 균형 평가셋 권장 — 현재 법당 20문항(총 60). evaluate.py가 agents.consumer._route_law로 검색 시 법을 라우팅한다(프로덕션 경로 일치)

실행: `python scripts/evaluate.py labor`
금융 benchmark 실행: `python scripts/evaluate.py finance benchmark`
결과는 results/<분야>_history.jsonl에 날짜와 함께 누적.
benchmark는 results/<분야>_benchmark_history.jsonl로 따로 쌓인다.
