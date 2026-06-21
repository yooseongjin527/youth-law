"""finance 쿼리확장(_expand_query) 회귀 가드 — 담당 D(mason) 전용.

'보이스피싱' 트리거가 방향(피해자 송금 vs 명의인 이의제기 vs 전화번호)을 구분 못해
Q4(제7조 이의제기)·Q5(제13조의3 전화번호 이용중지)에 피해자용 '피해구제 신청/지급정지'
노이즈를 주던 문제를 박제한다.

_expand_query는 순수 문자열 함수라 chromadb·임베딩 없이 로컬에서 검증 가능.
(라이브 hit@k는 EC2에서 scripts/evaluate.py finance로 측정)
질문 문자열은 evals/finance.jsonl 원문 그대로.
"""
from agents.finance import _expand_query

Q1 = "보이스피싱으로 돈을 보냈는데 돌려받을 수 있나요"           # 피해자 송금→환급 (제3·4조)
# 명의인 이의제기 (제7조)
Q4 = "제 계좌가 보이스피싱에 쓰였다고 갑자기 정지됐어요. 억울한데 어떻게 풀어요"
Q5 = "보이스피싱에 쓰인 전화번호를 정지시킬 수 있나요"          # 전화번호 이용중지 (제13조의3)


def test_q4_명의인_이의제기에_피해자_지급정지_노이즈_안붙음():
    out = _expand_query(Q4)
    assert "지급정지 이의제기" in out      # 이의제기(제7조) 신호는 유지돼야
    assert "피해구제 신청" not in out       # 피해자(제3조) 방향 노이즈는 제거돼야


def test_q5_전화번호정지에_피해자_지급정지_노이즈_안붙음():
    out = _expand_query(Q5)
    assert "전화번호 이용중지" in out       # 제13조의3 신호 유지
    assert "피해구제 신청" not in out        # 피해자 방향 노이즈 제거


def test_q1_피해자_송금질문엔_피해구제_지급정지_유지():
    # 회귀 가드: 노이즈 줄이다 진짜 피해자(제3·4조) 커버리지를 잃으면 안 된다.
    out = _expand_query(Q1)
    assert "피해구제 신청" in out
    assert "지급정지" in out


def test_송금_보냈_평어가_피해자_용어로_확장된다():
    # '보이스피싱' 없이도 송금 방향 평어 단독으로 피해자 용어를 받아야 한다.
    # (보이스피싱 단어를 빼서, 트리거가 실제로 동작하는지 검증)
    assert "피해구제 신청" in _expand_query("모르는 사람한테 송금해버렸어요")  # '송금'
    assert "피해구제 신청" in _expand_query("계좌로 돈을 보냈어요")            # '보냈'


def test_보이스피싱은_방향무관_전기통신금융사기_우산용어를_항상_붙인다():
    # 통신사기피해환급법 본문 적중을 돕는 중립 용어 — 세 방향 모두에 필요.
    for q in (Q1, Q4, Q5):
        assert "전기통신금융사기" in _expand_query(q)
