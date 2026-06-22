"""멀티턴 상담 세션 저장소 — 후속 질문 맥락 복원용.

메모리(dict) 구현으로 시작한다. 추후 RDS 승격 가능(기획서 RDS 계획과 연결).
세션당 최근 N턴 + TTL만 보관 → 메모리 바운드 + 재작성 프롬프트 비대 방지.

★ 그래프·State는 건드리지 않는다 ★: 대화 history는 LegalState가 아니라 이 서비스
계층에서만 산다. 후속 질문은 contextualize로 '독립형 질문'이 된 뒤 기존 그래프에
단발로 투입되므로, graph/state/agents는 멀티턴을 전혀 몰라도 된다.
"""
import os
import threading
import time
from typing import Optional

_MAX_TURNS = 6  # 세션당 보관 턴 수 — 오래된 맥락은 버림(프롬프트·메모리 바운드)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


_SESSION_TTL_SECONDS = _env_int("SESSION_TTL_SECONDS", 6 * 60 * 60)
_lock = threading.Lock()
_sessions: dict[str, list[dict]] = {}
_last_seen: dict[str, float] = {}


def _now() -> float:
    return time.time()


def _prune_expired_locked(now: float) -> int:
    """만료된 세션을 제거한다. _lock을 잡은 상태에서만 호출."""
    if _SESSION_TTL_SECONDS <= 0:
        return 0
    cutoff = now - _SESSION_TTL_SECONDS
    expired = [sid for sid, ts in _last_seen.items() if ts < cutoff]
    for sid in expired:
        _sessions.pop(sid, None)
        _last_seen.pop(sid, None)
    return len(expired)


def clear_expired() -> int:
    """운영/테스트용: TTL이 지난 세션을 정리하고 제거 건수를 반환."""
    with _lock:
        return _prune_expired_locked(_now())


def get_history(session_id: Optional[str]) -> list[dict]:
    """세션의 대화 턴 목록(오래된→최신). 세션 없거나 id 비면 빈 리스트."""
    if not session_id:
        return []
    with _lock:
        now = _now()
        _prune_expired_locked(now)
        hist = _sessions.get(session_id, [])
        if hist:
            _last_seen[session_id] = now
        return list(hist)


def append_turn(session_id: Optional[str], question: str, answer: str, domains: list[str]) -> None:
    """한 턴(사용자 질문 + 어시스턴트 답변)을 세션에 누적. 최근 N턴만 유지."""
    if not session_id:
        return
    turn = {"question": question, "answer": answer or "", "domains": list(domains or [])}
    with _lock:
        now = _now()
        _prune_expired_locked(now)
        hist = _sessions.setdefault(session_id, [])
        hist.append(turn)
        if len(hist) > _MAX_TURNS:
            del hist[: len(hist) - _MAX_TURNS]
        _last_seen[session_id] = now


def clear(session_id: Optional[str]) -> None:
    """세션 리셋(새 상담 시작 버튼 등)."""
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)
        _last_seen.pop(session_id, None)
