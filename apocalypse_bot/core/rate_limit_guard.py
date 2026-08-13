from __future__ import annotations

"""ABADDON v18.0.4 Discord / Cloudflare rate-limit guard.

The guard is intentionally conservative:
- it never changes gameplay data;
- it does not monkey-patch discord.py HTTP internals;
- it compacts Cloudflare HTML error pages in stdout/stderr;
- it records 1015/429 events and exposes a short quarantine window so
  nonessential schedulers can wait instead of adding more requests;
- normal Discord traffic resumes automatically when the window expires.
"""

from collections import deque
import io
import logging
import re
import sys
import threading
import time
from typing import Any, Deque, Dict, Optional, TextIO

VERSION = "18.1.3"
DEFAULT_1015_BACKOFF = 300
DEFAULT_429_BACKOFF = 90
DEFAULT_5XX_BACKOFF = 30
MAX_BACKOFF = 900

_lock = threading.RLock()
_events: Deque[Dict[str, Any]] = deque(maxlen=30)
_state: Dict[str, Any] = {
    "quarantine_until": 0.0,
    "last_at": 0.0,
    "last_kind": "",
    "last_detail": "",
    "count_1015": 0,
    "count_429": 0,
    "count_5xx": 0,
    "suppressed_html": 0,
    "duplicates_suppressed": 0,
    "last_note_fingerprint": "",
    "last_note_at": 0.0,
    "last_emit_kind": "",
    "last_emit_at": 0.0,
}

_CF_1015_MARKERS = (
    "error 1015",
    "you are being rate limited",
    "banned you temporarily from accessing this website",
    "cloudflare ray id",
)
_RATE_429_MARKERS = (
    "429 too many requests",
    "http 429",
    "status 429",
    "rate limited",
    "rate limit",
)
_CF_5XX_RE = re.compile(r"(?:cloudflare|discord(?:app)?\.com).{0,120}(?:50[0234]|52[0-9])", re.I | re.S)
_HTML_START_RE = re.compile(r"^\s*(?:<!doctype\s+html|<html\b|<head\b|<body\b)", re.I)
_HTML_END_RE = re.compile(r"</html\s*>", re.I)


def _now() -> float:
    return time.time()


def note_rate_limit(kind: str, detail: str = "", retry_after: Optional[float] = None) -> int:
    token = str(kind or "").strip().lower()
    if token == "1015":
        delay = DEFAULT_1015_BACKOFF
        counter = "count_1015"
    elif token == "429":
        delay = DEFAULT_429_BACKOFF
        counter = "count_429"
    else:
        token = "5xx"
        delay = DEFAULT_5XX_BACKOFF
        counter = "count_5xx"
    if retry_after is not None:
        try:
            delay = max(delay, int(float(retry_after)))
        except (TypeError, ValueError):
            pass
    delay = max(5, min(int(delay), MAX_BACKOFF))
    now = _now()
    clean = " ".join(str(detail or "").split())[:300]
    fingerprint = f"{token}:{clean[:180]}"
    with _lock:
        last_fp = str(_state.get("last_note_fingerprint", "") or "")
        last_at = float(_state.get("last_note_at", 0.0) or 0.0)
        duplicate = fingerprint == last_fp and (now - last_at) < 60.0
        if duplicate:
            # The same HTML/error may pass through multiple logging handlers.
            # Count it, but do not restart the 300s quarantine timer each time.
            _state["duplicates_suppressed"] = int(_state.get("duplicates_suppressed", 0) or 0) + 1
        else:
            _state[counter] = int(_state.get(counter, 0) or 0) + 1
            _state["last_at"] = now
            _state["last_kind"] = token
            _state["last_detail"] = clean
            _state["last_note_fingerprint"] = fingerprint
            _state["last_note_at"] = now
            _events.append({"at": int(now), "kind": token, "delay": delay, "detail": clean})
            _state["quarantine_until"] = max(float(_state.get("quarantine_until", 0.0) or 0.0), now + delay)
    return delay


def _claim_emit(kind: str, window: float = 60.0) -> bool:
    now = _now()
    token = str(kind or "")
    with _lock:
        last_kind = str(_state.get("last_emit_kind", "") or "")
        last_at = float(_state.get("last_emit_at", 0.0) or 0.0)
        if token == last_kind and (now - last_at) < float(window):
            _state["duplicates_suppressed"] = int(_state.get("duplicates_suppressed", 0) or 0) + 1
            return False
        _state["last_emit_kind"] = token
        _state["last_emit_at"] = now
        return True


def detect_rate_limit(value: Any) -> str:
    text = str(value or "")
    low = text.casefold()
    if any(marker in low for marker in _CF_1015_MARKERS):
        return "1015"
    if any(marker in low for marker in _RATE_429_MARKERS):
        return "429"
    if _CF_5XX_RE.search(text):
        return "5xx"
    return ""


def note_from_text(value: Any) -> str:
    kind = detect_rate_limit(value)
    if kind:
        note_rate_limit(kind, str(value))
    return kind


def remaining() -> int:
    with _lock:
        return max(0, int(float(_state.get("quarantine_until", 0.0) or 0.0) - _now()))


def should_pause_nonessential() -> bool:
    return remaining() > 0


def snapshot() -> Dict[str, Any]:
    with _lock:
        out = dict(_state)
        out["remaining"] = remaining()
        out["events"] = list(_events)
        return out


def mark_html_suppressed() -> None:
    with _lock:
        _state["suppressed_html"] = int(_state.get("suppressed_html", 0) or 0) + 1


def compact_message(value: Any, *, record: bool = True) -> str:
    text = str(value or "")
    kind = detect_rate_limit(text)
    if not kind:
        return text
    delay = note_rate_limit(kind, text) if record else (DEFAULT_1015_BACKOFF if kind == "1015" else DEFAULT_429_BACKOFF if kind == "429" else DEFAULT_5XX_BACKOFF)
    if kind == "1015":
        return f"[ABADDON v{VERSION}] Discord/Cloudflare 1015 요청 제한 감지 · 비필수 자동 전송 {delay}초 대기"
    if kind == "429":
        return f"[ABADDON v{VERSION}] Discord HTTP 429 요청 제한 감지 · 비필수 자동 전송 {delay}초 대기"
    return f"[ABADDON v{VERSION}] Discord/Cloudflare 일시 오류 감지 · 비필수 자동 전송 {delay}초 대기"


class RateLimitLogFilter(logging.Filter):
    """Collapse a multiline Cloudflare/429 log record into one readable line."""

    _abaddon_rate_limit_filter = True

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            raw = record.getMessage()
            kind = detect_rate_limit(raw)
            if not kind:
                return True
            note_rate_limit(kind, raw)
            if not _claim_emit(kind):
                return False
            record.msg = compact_message(raw, record=False)
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        except Exception:
            return True
        return True


class GuardedTextStream(io.TextIOBase):
    """Suppress giant Cloudflare HTML bodies while keeping ordinary logs intact."""

    def __init__(self, wrapped: TextIO) -> None:
        self.wrapped = wrapped
        self._buffer = ""
        self._html_mode = False
        self._max_buffer = 256_000

    @property
    def encoding(self):  # type: ignore[override]
        return getattr(self.wrapped, "encoding", "utf-8")

    def isatty(self) -> bool:
        try:
            return bool(self.wrapped.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        return self.wrapped.fileno()

    def flush(self) -> None:
        if self._html_mode and self._buffer and len(self._buffer) > self._max_buffer:
            self._flush_buffer(force=True)
        self.wrapped.flush()

    def writable(self) -> bool:
        return True

    def _flush_buffer(self, force: bool = False) -> None:
        if not self._buffer:
            self._html_mode = False
            return
        kind = detect_rate_limit(self._buffer)
        if kind:
            mark_html_suppressed()
            note_rate_limit(kind, self._buffer)
            if _claim_emit(kind):
                line = compact_message(self._buffer, record=False)
                self.wrapped.write(line.rstrip() + "\n")
        elif force or _HTML_END_RE.search(self._buffer):
            self.wrapped.write(self._buffer)
        self._buffer = ""
        self._html_mode = False

    def write(self, value: str) -> int:
        text = str(value)
        # Most logging handlers write the entire multiline exception in one call.
        kind = detect_rate_limit(text)
        if kind and ("<html" in text.casefold() or "<!doctype" in text.casefold() or "cloudflare" in text.casefold()):
            mark_html_suppressed()
            note_rate_limit(kind, text)
            if _claim_emit(kind):
                self.wrapped.write(compact_message(text, record=False).rstrip() + "\n")
            return len(text)

        if self._html_mode:
            self._buffer += text
            if detect_rate_limit(self._buffer) or _HTML_END_RE.search(self._buffer) or len(self._buffer) >= self._max_buffer:
                self._flush_buffer(force=len(self._buffer) >= self._max_buffer)
            return len(text)

        if _HTML_START_RE.search(text):
            self._html_mode = True
            self._buffer = text
            if _HTML_END_RE.search(text):
                self._flush_buffer()
            return len(text)

        self.wrapped.write(text)
        return len(text)


def install_stream_guard() -> None:
    if not isinstance(sys.stdout, GuardedTextStream):
        sys.stdout = GuardedTextStream(sys.stdout)  # type: ignore[assignment]
    if not isinstance(sys.stderr, GuardedTextStream):
        sys.stderr = GuardedTextStream(sys.stderr)  # type: ignore[assignment]


def make_log_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.addFilter(RateLimitLogFilter())
    return handler


__all__ = [
    "VERSION",
    "RateLimitLogFilter",
    "GuardedTextStream",
    "install_stream_guard",
    "make_log_handler",
    "detect_rate_limit",
    "note_rate_limit",
    "note_from_text",
    "remaining",
    "should_pause_nonessential",
    "snapshot",
]
