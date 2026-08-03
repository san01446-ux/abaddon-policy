from __future__ import annotations

"""Minimal ABADDON public-feed relay for Render or another Python web service.

No third-party package is required. The bot sends authenticated heartbeats/events;
the static website reads public status and event endpoints with CORS enabled.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

PORT = int(os.getenv("PORT", "10000"))
SECRET = os.getenv("PUBLIC_FEED_RELAY_KEY", "").strip()
ALLOWED_ORIGIN = os.getenv("PUBLIC_FEED_ALLOWED_ORIGIN", "*").strip() or "*"
OFFLINE_AFTER = max(45, int(os.getenv("PUBLIC_FEED_OFFLINE_SECONDS", "150")))
MAX_EVENTS = max(10, min(100, int(os.getenv("PUBLIC_FEED_MAX_EVENTS", "40"))))
LOCK = threading.RLock()
STATUS: Dict[str, Any] = {
    "online": False,
    "version": "ABADDON",
    "guilds": 0,
    "members": 0,
    "latency_ms": 0,
    "feed_enabled": True,
    "heartbeat_at": None,
    "generated_at": None,
}
EVENTS: List[Dict[str, Any]] = []
STARTED_AT = time.time()


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def authorized(headers: Any) -> bool:
    if not SECRET:
        return False
    return headers.get("Authorization", "") == f"Bearer {SECRET}"


class Handler(BaseHTTPRequestHandler):
    server_version = "ABADDONPublicFeed/10.9.2"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[feed] {self.address_string()} {fmt % args}", flush=True)

    def send_json(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> Dict[str, Any]:
        try:
            length = min(65536, max(0, int(self.headers.get("Content-Length", "0"))))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/health", "/healthz"}:
            self.send_json(200, {"ok": True, "service": "ABADDON public feed", "version": "v10.9.2"})
            return
        if parsed.path == "/api/status":
            with LOCK:
                snapshot = dict(STATUS)
            heartbeat = snapshot.get("heartbeat_at")
            age = 10**9
            if heartbeat:
                try:
                    age = time.time() - datetime.fromisoformat(str(heartbeat)).timestamp()
                except Exception:
                    pass
            snapshot["online"] = bool(snapshot.get("online")) and age <= OFFLINE_AFTER
            snapshot["heartbeat_age_seconds"] = None if age >= 10**8 else int(max(0, age))
            snapshot["uptime_seconds"] = int(time.time() - STARTED_AT)
            snapshot["generated_at"] = utc_iso()
            snapshot["ok"] = True
            self.send_json(200, snapshot)
            return
        if parsed.path == "/api/events":
            limit = 8
            try:
                limit = max(1, min(50, int((parse_qs(parsed.query).get("limit") or [8])[0])))
            except Exception:
                pass
            with LOCK:
                events = [dict(row) for row in EVENTS[:limit]]
                enabled = bool(STATUS.get("feed_enabled", True))
            self.send_json(200, {"ok": True, "version": "v10.9.2", "feed_enabled": enabled, "events": events, "generated_at": utc_iso()})
            return
        self.send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not authorized(self.headers):
            self.send_json(401, {"ok": False, "error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        data = self.read_json()
        if parsed.path == "/api/ingest/status":
            with LOCK:
                STATUS.update({
                    "online": bool(data.get("online", True)),
                    "version": clean_text(data.get("version") or "ABADDON", 32),
                    "bot": clean_text(data.get("bot") or "ABADDON", 48),
                    "guilds": max(0, int(data.get("guilds", 0) or 0)),
                    "members": max(0, int(data.get("members", 0) or 0)),
                    "latency_ms": max(0, int(data.get("latency_ms", 0) or 0)),
                    "feed_enabled": bool(data.get("feed_enabled", True)),
                    "heartbeat_at": clean_text(data.get("heartbeat_at") or utc_iso(), 64),
                    "generated_at": utc_iso(),
                })
            self.send_json(200, {"ok": True})
            return
        if parsed.path == "/api/ingest/event":
            event = {
                "id": clean_text(data.get("id") or f"evt-{int(time.time()*1000)}", 72),
                "type": clean_text(data.get("type") or "system", 24),
                "title": clean_text(data.get("title") or "ABADDON", 80),
                "message": clean_text(data.get("message"), 220),
                "actor": clean_text(data.get("actor"), 48),
                "guild": clean_text(data.get("guild"), 48),
                "accent": clean_text(data.get("accent") or "#a51f36", 16),
                "created_at": clean_text(data.get("created_at") or utc_iso(), 64),
                "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            }
            with LOCK:
                if not any(row.get("id") == event["id"] for row in EVENTS):
                    EVENTS.insert(0, event)
                    del EVENTS[MAX_EVENTS:]
            self.send_json(200, {"ok": True, "id": event["id"]})
            return
        self.send_json(404, {"ok": False, "error": "not_found"})


if __name__ == "__main__":
    print(f"[ABADDON v10.9.2 feed] listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
