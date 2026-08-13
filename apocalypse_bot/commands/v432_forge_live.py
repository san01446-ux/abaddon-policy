from __future__ import annotations

import asyncio
import io
import json
import math
import os
import random
import re
import struct
import threading
import time
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request

import discord
from discord.ext import commands


V432_VERSION = "4.3.2.1"
MAX_PUBLIC_EVENTS = 60
PUBLIC_MILESTONE_LEVELS = {5, 7, 10, 12, 15, 18, 20}


def _emoji_progress_bar(value: float, maximum: float, width: int = 10, filled: str = "🟨", empty: str = "⬛") -> str:
    ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, float(value) / float(maximum)))
    count = max(0, min(width, int(round(ratio * width))))
    return filled * count + empty * (width - count)


FORGE_EPITHETS: Tuple[Tuple[int, str], ...] = (
    (20, "공허를 끝낸"),
    (18, "경계 너머의"),
    (15, "아바돈의"),
    (12, "심연을 가르는"),
    (10, "종말의"),
    (7, "광휘의"),
    (5, "단련된"),
)

SUCCESS_QUOTES = (
    "쇠가 네 의지를 받아들였군.",
    "좋아. 이번 불꽃은 거짓말을 하지 않았어.",
    "짧은 순간이었지만, 장비가 살아 움직였다.",
    "이 정도면 폐허도 네 발밑에서 갈라지겠군.",
    "망치 소리가 아주 깨끗했어. 좋은 징조다.",
)
FAIL_QUOTES = (
    "불꽃이 등을 돌렸군. 아직 끝난 건 아니다.",
    "조급함은 금속보다 먼저 부서지는 법이지.",
    "균열은 막았다. 다음 망치가 더 중요해.",
    "쇠가 버텼다. 네 식량만 사라졌을 뿐이지.",
    "실패도 흔적을 남긴다. 장인의 열기는 쌓였어.",
)
DOWN_QUOTES = (
    "균형이 무너졌다. 한 단계 물러났지만 장비는 살아 있다.",
    "불길이 너무 거셌군. 다시 담금질해야겠어.",
    "금속이 비명을 질렀다. 그래도 완전히 잃지는 않았다.",
)

TIER_COLORS = {
    "일반": 0xAAB0BC,
    "고급": 0x5BCB8A,
    "희귀": 0x5B8CFF,
    "영웅": 0x9B66FF,
    "전설": 0xECA646,
    "신화": 0xE34C5E,
    "유일": 0xE9D27D,
}

_EVENT_LOCK = threading.RLock()
_ENHANCE_LOCKS: Dict[Tuple[int, str], asyncio.Lock] = {}
_HTTP_SERVER: Optional[ThreadingHTTPServer] = None
_HTTP_THREAD: Optional[threading.Thread] = None
_HTTP_STARTED_AT = time.time()
_RELAY_LOCK = threading.RLock()
_RELAY_STATE: Dict[str, Any] = {
    "configured": False,
    "last_event_ok": None,
    "last_event_at": None,
    "last_status_ok": None,
    "last_status_at": None,
    "last_error": "",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_public_text(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("@everyone", "everyone").replace("@here", "here")
    return text[:limit]


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def ensure_public_feed(world_data: Dict[str, Any]) -> Dict[str, Any]:
    feed = world_data.setdefault("public_feed_v432", {})
    if not isinstance(feed, dict):
        feed = {}
        world_data["public_feed_v432"] = feed
    feed.setdefault("enabled", True)
    feed.setdefault("events", [])
    feed.setdefault("last_sequence", 0)
    if not isinstance(feed.get("events"), list):
        feed["events"] = []
    return feed


def ensure_user_forge(user: Dict[str, Any]) -> Dict[str, Any]:
    forge = user.setdefault("forge_v432", {})
    if not isinstance(forge, dict):
        forge = {}
        user["forge_v432"] = forge
    forge.setdefault("fail_streaks", {})
    forge.setdefault("history", [])
    forge.setdefault("shares", {})
    if not isinstance(forge.get("fail_streaks"), dict):
        forge["fail_streaks"] = {}
    if not isinstance(forge.get("history"), list):
        forge["history"] = []
    if not isinstance(forge.get("shares"), dict):
        forge["shares"] = {}
    return forge


def forge_display_name(item_name: str, level: int) -> str:
    for minimum, epithet in FORGE_EPITHETS:
        if level >= minimum:
            return f"{epithet} {item_name}"
    return item_name


def enhancement_profile(item_price: int, current: int, fail_streak: int) -> Dict[str, int]:
    cost = max(100, int(item_price * (0.12 + current * 0.04)))
    base_rate = max(15, 90 - current * 4)
    heat_bonus = min(15, max(0, fail_streak) * 2)
    success_rate = min(95, base_rate + heat_bonus)
    return {
        "cost": cost,
        "base_rate": base_rate,
        "heat_bonus": heat_bonus,
        "success_rate": success_rate,
    }


def _draw_rect(pixels: bytearray, width: int, height: int, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int]) -> None:
    x0, x1 = sorted((max(0, x0), min(width, x1)))
    y0, y1 = sorted((max(0, y0), min(height, y1)))
    r, g, b = color
    for y in range(y0, y1):
        offset = (y * width + x0) * 3
        for _ in range(x0, x1):
            pixels[offset:offset + 3] = bytes((r, g, b))
            offset += 3


def _blend_pixel(pixels: bytearray, width: int, height: int, x: int, y: int, color: Tuple[int, int, int], alpha: float = 1.0) -> None:
    if not (0 <= x < width and 0 <= y < height):
        return
    idx = (y * width + x) * 3
    alpha = max(0.0, min(1.0, alpha))
    for i, channel in enumerate(color):
        pixels[idx + i] = int(pixels[idx + i] * (1 - alpha) + channel * alpha)


def _draw_line(pixels: bytearray, width: int, height: int, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int], thickness: int = 1, alpha: float = 1.0) -> None:
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    radius = max(0, thickness // 2)
    while True:
        for oy in range(-radius, radius + 1):
            for ox in range(-radius, radius + 1):
                if ox * ox + oy * oy <= radius * radius + 1:
                    _blend_pixel(pixels, width, height, x0 + ox, y0 + oy, color, alpha)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _draw_circle(pixels: bytearray, width: int, height: int, cx: int, cy: int, radius: int, color: Tuple[int, int, int], fill: bool = False, thickness: int = 2, alpha: float = 1.0) -> None:
    r2 = radius * radius
    inner = max(0, radius - thickness)
    inner2 = inner * inner
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 <= r2 and (fill or d2 >= inner2):
                _blend_pixel(pixels, width, height, x, y, color, alpha)


def _fill_polygon(pixels: bytearray, width: int, height: int, points: List[Tuple[int, int]], color: Tuple[int, int, int], alpha: float = 1.0) -> None:
    if not points:
        return
    min_y = max(0, min(y for _, y in points))
    max_y = min(height - 1, max(y for _, y in points))
    for y in range(min_y, max_y + 1):
        intersections: List[float] = []
        for i, (x1, y1) in enumerate(points):
            x2, y2 = points[(i + 1) % len(points)]
            if y1 == y2:
                continue
            if min(y1, y2) <= y < max(y1, y2):
                intersections.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        intersections.sort()
        for i in range(0, len(intersections) - 1, 2):
            for x in range(max(0, math.ceil(intersections[i])), min(width, math.floor(intersections[i + 1]) + 1)):
                _blend_pixel(pixels, width, height, x, y, color, alpha)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _encode_png(width: int, height: int, pixels: bytearray) -> bytes:
    raw = bytearray()
    row_size = width * 3
    for y in range(height):
        raw.append(0)
        start = y * row_size
        raw.extend(pixels[start:start + row_size])
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return header + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _png_chunk(b"IEND", b"")


def build_forge_card_png(tier: str, slot: str, success: bool, level: int) -> bytes:
    width, height = 960, 420
    pixels = bytearray(width * height * 3)
    accent_hex = TIER_COLORS.get(tier, 0xAAB0BC)
    accent = ((accent_hex >> 16) & 255, (accent_hex >> 8) & 255, accent_hex & 255)
    outcome = (225, 198, 112) if success else (164, 30, 52)

    for y in range(height):
        for x in range(width):
            radial = max(0.0, 1.0 - math.hypot(x - width * 0.55, y - height * 0.45) / 560)
            stripe = 7 if ((x + y) // 22) % 2 == 0 else 0
            idx = (y * width + x) * 3
            pixels[idx] = min(255, int(8 + radial * outcome[0] * 0.16 + stripe))
            pixels[idx + 1] = min(255, int(7 + radial * outcome[1] * 0.10 + stripe // 2))
            pixels[idx + 2] = min(255, int(11 + radial * accent[2] * 0.14 + stripe))

    # Gothic frame and cathedral arch.
    _draw_rect(pixels, width, height, 24, 24, width - 24, height - 24, (18, 15, 22))
    _draw_rect(pixels, width, height, 30, 30, width - 30, height - 30, (8, 8, 13))
    _draw_line(pixels, width, height, 42, 365, 918, 365, accent, 3, 0.7)
    _draw_line(pixels, width, height, 42, 72, 918, 72, outcome, 2, 0.75)
    for x in (110, 850):
        _draw_line(pixels, width, height, x, 92, x, 344, accent, 3, 0.45)
        _draw_circle(pixels, width, height, x, 92, 24, accent, False, 3, 0.55)

    cx, cy = 500, 220
    for radius, alpha in ((120, 0.06), (90, 0.10), (62, 0.16)):
        _draw_circle(pixels, width, height, cx, cy, radius, accent, True, alpha=alpha)
    _draw_circle(pixels, width, height, cx, cy, 130, outcome, False, 3, 0.65)
    _draw_circle(pixels, width, height, cx, cy, 111, accent, False, 2, 0.55)

    # Slot silhouette.
    metal = (222, 224, 232)
    shadow = (65, 68, 78)
    glow = outcome if success else (180, 34, 48)
    if slot == "무기":
        _draw_line(pixels, width, height, 390, 292, 596, 115, shadow, 24, 0.95)
        _draw_line(pixels, width, height, 397, 284, 594, 116, metal, 12, 1.0)
        _fill_polygon(pixels, width, height, [(585, 111), (625, 91), (604, 132)], glow, 0.95)
        _draw_line(pixels, width, height, 378, 305, 427, 321, glow, 12, 0.9)
        _draw_line(pixels, width, height, 385, 300, 354, 333, metal, 10, 0.9)
    elif slot in {"방어구", "머리"}:
        _fill_polygon(pixels, width, height, [(500, 116), (594, 151), (575, 278), (500, 326), (425, 278), (406, 151)], shadow, 1.0)
        _fill_polygon(pixels, width, height, [(500, 128), (575, 158), (559, 266), (500, 307), (441, 266), (425, 158)], metal, 0.88)
        _draw_line(pixels, width, height, 500, 143, 500, 286, glow, 12, 0.85)
        _draw_line(pixels, width, height, 455, 200, 545, 200, glow, 8, 0.75)
    elif slot == "반지":
        _draw_circle(pixels, width, height, 500, 230, 88, metal, False, 23, 0.95)
        _fill_polygon(pixels, width, height, [(500, 105), (548, 158), (500, 195), (452, 158)], glow, 0.95)
        _draw_circle(pixels, width, height, 500, 150, 34, accent, True, alpha=0.55)
    elif slot == "목걸이":
        for angle in range(205, 336, 3):
            rad = math.radians(angle)
            x = int(500 + math.cos(rad) * 112)
            y = int(170 + math.sin(rad) * 112)
            _draw_circle(pixels, width, height, x, y, 5, metal, True, alpha=0.95)
        _fill_polygon(pixels, width, height, [(500, 215), (552, 267), (500, 325), (448, 267)], glow, 0.95)
        _draw_circle(pixels, width, height, 500, 267, 24, accent, True, alpha=0.65)
    elif slot == "장갑":
        _fill_polygon(pixels, width, height, [(430, 153), (474, 134), (505, 180), (528, 132), (555, 156), (545, 216), (575, 175), (598, 202), (551, 302), (456, 312), (410, 235)], metal, 0.9)
        _draw_line(pixels, width, height, 445, 260, 553, 243, glow, 14, 0.75)
    elif slot == "신발":
        _fill_polygon(pixels, width, height, [(410, 144), (500, 135), (528, 242), (610, 275), (603, 314), (447, 314), (409, 261)], metal, 0.9)
        _draw_line(pixels, width, height, 438, 251, 580, 283, glow, 13, 0.75)
    else:
        _draw_circle(pixels, width, height, 500, 220, 75, metal, False, 18, 0.9)
        _draw_line(pixels, width, height, 447, 273, 553, 167, glow, 12, 0.85)

    # Rune sparks scale with level.
    rng = random.Random(f"{tier}:{slot}:{success}:{level}")
    for _ in range(20 + level * 2):
        angle = rng.random() * math.tau
        radius = rng.randint(90, 175)
        x = int(cx + math.cos(angle) * radius)
        y = int(cy + math.sin(angle) * radius * 0.66)
        _draw_circle(pixels, width, height, x, y, rng.randint(1, 4), glow, True, alpha=rng.uniform(0.35, 0.9))

    # v6.3.3 visual evolution: higher enhancement levels visibly change silhouette and aura.
    stage = 0
    for threshold in (5, 7, 10, 12, 15, 18, 20):
        if level >= threshold:
            stage += 1
    if success and stage:
        for ring in range(stage):
            radius = 142 + ring * 12
            _draw_circle(pixels, width, height, cx, cy, radius, accent, False, 1 + ring // 3, 0.18 + ring * 0.05)
        # Expanding side fins / wings make the silhouette richer at high stages.
        if level >= 7:
            _fill_polygon(pixels, width, height, [(400, 215), (320, 170), (350, 238), (305, 285), (420, 260)], accent, 0.28)
            _fill_polygon(pixels, width, height, [(600, 215), (680, 170), (650, 238), (695, 285), (580, 260)], accent, 0.28)
        if level >= 10:
            for offset in (-92, -58, 58, 92):
                _draw_line(pixels, width, height, cx + offset, 112, cx + int(offset * 0.68), 322, glow, 3, 0.42)
        if level >= 12:
            for angle in range(0, 360, 30):
                rad = math.radians(angle)
                x0 = int(cx + math.cos(rad) * 142)
                y0 = int(cy + math.sin(rad) * 92)
                x1 = int(cx + math.cos(rad) * 184)
                y1 = int(cy + math.sin(rad) * 122)
                _draw_line(pixels, width, height, x0, y0, x1, y1, accent, 4, 0.55)
        if level >= 15:
            _fill_polygon(pixels, width, height, [(500, 75), (474, 112), (490, 108), (500, 128), (510, 108), (526, 112)], glow, 0.9)
            _draw_circle(pixels, width, height, cx, 82, 34, glow, False, 4, 0.68)
        if level >= 18:
            for _ in range(7):
                sx = rng.randint(320, 680)
                sy = rng.randint(90, 330)
                ex = sx + rng.randint(-55, 55)
                ey = sy + rng.randint(-35, 35)
                _draw_line(pixels, width, height, sx, sy, ex, ey, glow, 3, 0.65)
        if level >= 20:
            for radius in (190, 205, 220):
                _draw_circle(pixels, width, height, cx, cy, radius, outcome, False, 2, 0.35)
            for angle in range(0, 360, 15):
                rad = math.radians(angle)
                x0 = int(cx + math.cos(rad) * 175)
                y0 = int(cy + math.sin(rad) * 118)
                x1 = int(cx + math.cos(rad) * 224)
                y1 = int(cy + math.sin(rad) * 148)
                _draw_line(pixels, width, height, x0, y0, x1, y1, glow, 2, 0.65)
    elif not success:
        # Failure cards show visible cracks instead of the success aura.
        for _ in range(5 + min(10, level // 2)):
            x = rng.randint(395, 605)
            y = rng.randint(125, 310)
            _draw_line(pixels, width, height, x, y, x + rng.randint(-28, 28), y + rng.randint(12, 42), (196, 40, 58), 2, 0.72)

    return _encode_png(width, height, pixels)


def _event_accent(event_type: str) -> str:
    return {
        "enhance": "#d6b45f",
        "announcement": "#a51f36",
        "system": "#7c6ee6",
    }.get(event_type, "#8e8899")


def _sanitize_public_metadata(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {"item", "level", "tier", "protected", "version"}
    cleaned: Dict[str, Any] = {}
    for key in allowed:
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, bool):
            cleaned[key] = item
        elif isinstance(item, int):
            cleaned[key] = max(-1_000_000, min(1_000_000, item))
        elif isinstance(item, (float, str)):
            cleaned[key] = _clean_public_text(item, 80)
    return cleaned


def _relay_config() -> Tuple[str, str]:
    base = os.getenv("PUBLIC_FEED_RELAY_URL", "").strip().rstrip("/")
    secret = os.getenv("PUBLIC_FEED_RELAY_KEY", "").strip()
    with _RELAY_LOCK:
        _RELAY_STATE["configured"] = bool(base and secret)
    return base, secret


def _relay_state_snapshot() -> Dict[str, Any]:
    with _RELAY_LOCK:
        return dict(_RELAY_STATE)


def _relay_post_sync(path: str, payload: Dict[str, Any], *, kind: str) -> Dict[str, Any]:
    base, secret = _relay_config()
    if not base or not secret:
        return {"ok": False, "error": "relay_not_configured"}

    url = f"{base}/{path.lstrip('/')}"
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=raw,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"ABADDON-Worker/{V432_VERSION}",
        },
    )
    now = _utc_iso()
    try:
        with urllib_request.urlopen(req, timeout=8) as response:
            body = response.read(65536)
            result = json.loads(body.decode("utf-8")) if body else {"ok": True}
            if not isinstance(result, dict):
                result = {"ok": True}
            ok = bool(result.get("ok", True))
    except urllib_error.HTTPError as exc:
        try:
            detail = exc.read(2048).decode("utf-8", "replace")
        except Exception:
            detail = ""
        result = {"ok": False, "error": f"HTTP {exc.code} {detail[:160]}".strip()}
        ok = False
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}
        ok = False

    with _RELAY_LOCK:
        if kind == "event":
            _RELAY_STATE["last_event_ok"] = ok
            _RELAY_STATE["last_event_at"] = now
        else:
            _RELAY_STATE["last_status_ok"] = ok
            _RELAY_STATE["last_status_at"] = now
        _RELAY_STATE["last_error"] = "" if ok else str(result.get("error", "relay_error"))[:220]
    return result


async def _relay_post(path: str, payload: Dict[str, Any], *, kind: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_relay_post_sync, path, payload, kind=kind)


def _schedule_relay_event(event: Dict[str, Any]) -> None:
    base, secret = _relay_config()
    if not base or not secret:
        return
    payload = {
        "id": _clean_public_text(event.get("id"), 72),
        "type": _clean_public_text(event.get("type"), 24),
        "title": _clean_public_text(event.get("title"), 80),
        "message": _clean_public_text(event.get("message"), 220),
        "actor": _clean_public_text(event.get("actor"), 48),
        "guild": _clean_public_text(event.get("guild"), 48),
        "accent": _clean_public_text(event.get("accent"), 16),
        "created_at": _clean_public_text(event.get("created_at"), 48),
        "metadata": _sanitize_public_metadata(event.get("metadata")),
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(
            target=_relay_post_sync,
            args=("/api/ingest/event", payload),
            kwargs={"kind": "event"},
            name="abaddon-feed-event",
            daemon=True,
        ).start()
    else:
        loop.create_task(_relay_post("/api/ingest/event", payload, kind="event"))


def publish_public_event(
    world_data: Dict[str, Any],
    save_data: Callable[[], None],
    *,
    event_type: str,
    title: str,
    message: str,
    actor: str = "",
    guild: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    relay: bool = True,
) -> Optional[Dict[str, Any]]:
    with _EVENT_LOCK:
        feed = ensure_public_feed(world_data)
        if not feed.get("enabled", True) and event_type != "system":
            return None
        feed["last_sequence"] = _safe_int(feed.get("last_sequence"), 0, minimum=0) + 1
        event = {
            "id": f"evt-{feed['last_sequence']}",
            "type": _clean_public_text(event_type, 24) or "system",
            "title": _clean_public_text(title, 80),
            "message": _clean_public_text(message, 220),
            "actor": _clean_public_text(actor, 48),
            "guild": _clean_public_text(guild, 48) if os.getenv("PUBLIC_FEED_SHOW_GUILD", "").strip().lower() in {"1", "true", "yes", "on"} else "",
            "accent": _event_accent(event_type),
            "created_at": _utc_iso(),
            "metadata": _sanitize_public_metadata(metadata),
        }
        events = feed["events"]
        events.insert(0, event)
        del events[MAX_PUBLIC_EVENTS:]
        save_data()
    if relay:
        _schedule_relay_event(event)
    return event

def _public_status(bot: commands.Bot, world_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        ready = bool(bot.is_ready())
    except Exception:
        ready = False
    guilds = list(getattr(bot, "guilds", []) or [])
    members = 0
    for guild in guilds:
        count = getattr(guild, "member_count", 0)
        if isinstance(count, int):
            members += max(0, count)
    try:
        latency_ms = round(float(getattr(bot, "latency", 0.0)) * 1000)
    except (TypeError, ValueError):
        latency_ms = 0
    feed = ensure_public_feed(world_data)
    events = feed.get("events", [])
    return {
        "ok": True,
        "online": ready,
        "version": f"v{V432_VERSION}",
        "bot": _clean_public_text(getattr(bot, "user", "ABADDON"), 48),
        "guilds": len(guilds),
        "members": members,
        "latency_ms": latency_ms,
        "feed_enabled": bool(feed.get("enabled", True)),
        "event_count": len(events),
        "last_event_at": events[0].get("created_at") if events else None,
        "uptime_seconds": max(0, int(time.time() - _HTTP_STARTED_AT)),
        "generated_at": _utc_iso(),
    }


async def _send_relay_status(bot: commands.Bot, world_data: Dict[str, Any]) -> Dict[str, Any]:
    payload = _public_status(bot, world_data)
    payload["heartbeat_at"] = _utc_iso()
    return await _relay_post("/api/ingest/status", payload, kind="status")


async def _relay_heartbeat_loop(bot: commands.Bot, world_data: Dict[str, Any]) -> None:
    interval = _safe_int(os.getenv("PUBLIC_FEED_HEARTBEAT_SECONDS") or 45, 45, minimum=15, maximum=300)
    while True:
        try:
            await _send_relay_status(bot, world_data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with _RELAY_LOCK:
                _RELAY_STATE["last_status_ok"] = False
                _RELAY_STATE["last_status_at"] = _utc_iso()
                _RELAY_STATE["last_error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        await asyncio.sleep(interval)


def start_public_feed_server(bot: commands.Bot, world_data: Dict[str, Any]) -> Dict[str, Any]:
    global _HTTP_SERVER, _HTTP_THREAD
    if _HTTP_SERVER is not None:
        return {"started": True, "port": _HTTP_SERVER.server_port, "reason": "already_running"}

    mode = os.getenv("PUBLIC_FEED_HTTP_MODE", "").strip().lower()
    relay_base, _relay_secret = _relay_config()
    if os.getenv("ABADDON_DISABLE_HTTP", "").strip() == "1" or mode in {"off", "disabled", "relay"}:
        enabled = False
    elif mode in {"embedded", "on", "true", "1"}:
        enabled = True
    else:
        # Backward compatibility: only auto-start inside an actual web process.
        # A Background Worker normally has no PORT, and relay mode must not open a useless local server.
        enabled = bool(os.getenv("PORT") or os.getenv("PUBLIC_FEED_PORT")) and not bool(relay_base)
    if not enabled:
        return {"started": False, "port": None, "reason": "relay_or_disabled"}

    port = _safe_int(os.getenv("PORT") or os.getenv("PUBLIC_FEED_PORT") or 10000, 10000, minimum=1, maximum=65535)
    allowed_origin = os.getenv("PUBLIC_FEED_ALLOWED_ORIGIN", "*").strip() or "*"

    class FeedHandler(BaseHTTPRequestHandler):
        server_version = "ABADDONFeed/4.3.2.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send_json(200, {"ok": True})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            custom_hook = getattr(bot, "_abaddon_public_http_post_hook", None)
            if callable(custom_hook):
                try:
                    if bool(custom_hook(self, parsed)):
                        return
                except Exception as hook_exc:
                    self._send_json(500, {"ok": False, "error": "public_post_hook_error", "detail": f"{type(hook_exc).__name__}: {str(hook_exc)[:160]}"})
                    return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            custom_hook = getattr(bot, "_abaddon_public_http_get_hook", None)
            if callable(custom_hook):
                try:
                    if bool(custom_hook(self, parsed)):
                        return
                except Exception as hook_exc:
                    self._send_json(500, {"ok": False, "error": "public_hook_error", "detail": f"{type(hook_exc).__name__}: {str(hook_exc)[:160]}"})
                    return
            if parsed.path in {"/", "/health", "/healthz"}:
                self._send_json(200, {"ok": True, "service": "ABADDON embedded public feed", "version": f"v{V432_VERSION}"})
                return
            if parsed.path == "/api/status":
                self._send_json(200, _public_status(bot, world_data))
                return
            if parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                limit = _safe_int((query.get("limit") or [10])[0], 10, minimum=1, maximum=50)
                with _EVENT_LOCK:
                    feed = ensure_public_feed(world_data)
                    events = [dict(event) for event in feed.get("events", [])[:limit] if isinstance(event, dict)]
                self._send_json(200, {
                    "ok": True,
                    "version": f"v{V432_VERSION}",
                    "feed_enabled": bool(feed.get("enabled", True)),
                    "events": events,
                    "generated_at": _utc_iso(),
                })
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

    try:
        _HTTP_SERVER = ThreadingHTTPServer(("0.0.0.0", port), FeedHandler)
    except OSError as exc:
        print(f"[V4.3.2.1 실시간 피드] HTTP 서버 시작 실패: {exc}", flush=True)
        _HTTP_SERVER = None
        return {"started": False, "port": port, "reason": str(exc)}

    _HTTP_THREAD = threading.Thread(target=_HTTP_SERVER.serve_forever, name="abaddon-public-feed", daemon=True)
    _HTTP_THREAD.start()
    print(f"[V4.3.2.1 실시간 피드] embedded 0.0.0.0:{port} 시작", flush=True)
    return {"started": True, "port": port, "reason": "embedded"}


class ForgeResultView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        item_name: str,
        result: Dict[str, Any],
        retry_callback: Callable[[discord.Interaction, int, str], Any],
        share_callback: Callable[[discord.Interaction, Dict[str, Any]], Any],
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.item_name = item_name
        self.result = result
        self.retry_callback = retry_callback
        self.share_callback = share_callback
        self.shared = False
        if not result.get("success"):
            for child in self.children:
                if getattr(child, "label", "") == "자랑하기":
                    child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⚠️ 이 강화 패널은 명령을 실행한 생존자만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="다시 강화", emoji="⚒️", style=discord.ButtonStyle.danger)
    async def retry(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.retry_callback(interaction, self.owner_id, self.item_name)

    @discord.ui.button(label="자랑하기", emoji="📣", style=discord.ButtonStyle.secondary)
    async def share(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.shared:
            await interaction.response.send_message("이미 이 결과를 자랑했습니다.", ephemeral=True)
            return
        self.shared = True
        button.disabled = True
        await self.share_callback(interaction, self.result)


async def _send_interaction_error(interaction: discord.Interaction, text: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


def register_v432_forge_live(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    find_item: Callable[[str], Tuple[Optional[str], Optional[Dict[str, Any]]]],
    get_item_slot: Callable[[str], str],
    progress_quest: Callable[..., Any],
    check_achievements: Callable[[Dict[str, Any]], List[Tuple[str, str]]],
) -> None:
    ensure_public_feed(world_data)
    server_state = start_public_feed_server(bot, world_data)

    def public_event(**kwargs: Any) -> Optional[Dict[str, Any]]:
        return publish_public_event(world_data, save_data, **kwargs)

    setattr(bot, "abaddon_publish_public_event", public_event)
    setattr(bot, "abaddon_public_feed_server", server_state)

    async def execute_enhancement(user_id: int, actor_name: str, guild_name: str, item_name: str) -> Dict[str, Any]:
        lock_key = (user_id, item_name)
        lock = _ENHANCE_LOCKS.setdefault(lock_key, asyncio.Lock())
        async with lock:
            user = get_user(user_id)
            if item_name not in user.get("inventory", []):
                return {"ok": False, "error": "해당 장비를 보유하고 있지 않습니다."}

            current = _safe_int(user.get("enhancements", {}).get(item_name), 0, minimum=0)
            if current >= 20:
                return {"ok": False, "error": "이미 최대 강화 수치 +20입니다."}

            tier, info = find_item(item_name)
            if not info:
                return {"ok": False, "error": "장비 정보를 찾지 못했습니다. 운영진에게 알려주세요."}

            forge = ensure_user_forge(user)
            fail_streak = _safe_int(forge["fail_streaks"].get(item_name), 0, minimum=0)
            profile = enhancement_profile(_safe_int(info.get("price"), 1000, minimum=1), current, fail_streak)
            cost = profile["cost"]
            balance = _safe_int(user.get("balance"), 0, minimum=0)
            if balance < cost:
                return {"ok": False, "error": f"강화 비용 식량 **{cost:,}개**가 필요합니다."}

            user["balance"] = balance - cost
            roll = random.randint(1, 100)
            success = roll <= profile["success_rate"]
            down = False
            new_level = current
            if success:
                new_level = current + 1
                user.setdefault("enhancements", {})[item_name] = new_level
                user.setdefault("stats", {}).setdefault("enhance_success", 0)
                user["stats"]["enhance_success"] += 1
                forge["fail_streaks"][item_name] = 0
                progress_quest(user, "강화 성공")
                quote = random.choice(SUCCESS_QUOTES)
            else:
                forge["fail_streaks"][item_name] = min(99, fail_streak + 1)
                if current >= 10 and random.random() < 0.35:
                    new_level = current - 1
                    user.setdefault("enhancements", {})[item_name] = new_level
                    down = True
                    quote = random.choice(DOWN_QUOTES)
                else:
                    quote = random.choice(FAIL_QUOTES)

            unlocked = check_achievements(user)
            display_name = forge_display_name(item_name, new_level)
            slot = get_item_slot(item_name)
            history_record = {
                "created_at": _utc_iso(),
                "item": item_name,
                "display_name": display_name,
                "tier": tier or "일반",
                "slot": slot,
                "from": current,
                "to": new_level,
                "success": success,
                "down": down,
                "cost": cost,
                "rate": profile["success_rate"],
                "roll": roll,
            }
            forge["history"].insert(0, history_record)
            del forge["history"][20:]
            save_data()

            published = None
            if success and new_level in PUBLIC_MILESTONE_LEVELS:
                published = public_event(
                    event_type="enhance",
                    title=f"+{new_level} 강화 성공",
                    message=f"{display_name}이(가) 새로운 경지에 도달했습니다.",
                    actor=actor_name,
                    guild=guild_name,
                    metadata={"item": item_name, "level": new_level, "tier": tier or "일반"},
                )

            return {
                "ok": True,
                "user_id": user_id,
                "actor": actor_name,
                "guild": guild_name,
                "item": item_name,
                "display_name": display_name,
                "tier": tier or "일반",
                "slot": slot,
                "from": current,
                "to": new_level,
                "success": success,
                "down": down,
                "cost": cost,
                "balance": _safe_int(user.get("balance"), 0),
                "rate": profile["success_rate"],
                "heat_before": fail_streak,
                "heat_after": _safe_int(forge["fail_streaks"].get(item_name), 0),
                "heat_bonus": profile["heat_bonus"],
                "quote": quote,
                "unlocked": unlocked,
                "published": bool(published),
            }

    async def build_result_embed(result: Dict[str, Any]) -> Tuple[discord.Embed, discord.File]:
        success = bool(result["success"])
        level = _safe_int(result["to"])
        tier = str(result["tier"])
        color = TIER_COLORS.get(tier, 0xAAB0BC)
        if not success:
            color = 0x8C1D32
        if success:
            headline = f"✨ 강화 성공 · +{result['from']} → +{level}"
            summary = f"**[+{level}] {result['display_name']}**"
        elif result["down"]:
            headline = f"💥 강화 실패 · +{result['from']} → +{level}"
            summary = f"장비의 강화 수치가 **+{level}**로 하락했습니다."
        else:
            headline = f"🕯️ 강화 실패 · +{result['from']} 유지"
            summary = f"**{result['item']} +{level}**의 강화 수치는 유지됩니다."

        embed = discord.Embed(title=headline, description=summary, color=color)
        embed.add_field(name="대장장이", value=f"“{result['quote']}”", inline=False)
        embed.add_field(name="사용 식량", value=f"{result['cost']:,}개", inline=True)
        embed.add_field(name="보유 식량", value=f"{result['balance']:,}개", inline=True)
        embed.add_field(name="성공 확률", value=f"{_emoji_progress_bar(result['rate'], 100, filled='🟩')} **{result['rate']}%**", inline=False)
        embed.add_field(name="✨ 강화 진행", value=f"{_emoji_progress_bar(level, 20)} **+{level}/+20**", inline=False)
        heat_text = f"연속 실패 {result['heat_after']}회"
        if result["heat_after"]:
            heat_text += f" · 다음 확률 +{min(15, result['heat_after'] * 2)}%"
        else:
            heat_text += " · 열기 초기화"
        embed.add_field(name="장인의 열기", value=f"{_emoji_progress_bar(min(result['heat_after'], 8), 8, filled='🔥', empty='▫️')}\n{heat_text}", inline=False)
        if result.get("unlocked"):
            embed.add_field(name="업적 달성", value=", ".join(name for name, _title in result["unlocked"]), inline=False)
        if result.get("published"):
            embed.set_footer(text="공식 홈페이지 실시간 기록에 등록됨 · 버튼은 3분 동안 사용 가능")
        else:
            embed.set_footer(text="강화 표시 이름은 연출용이며 기존 인벤토리 데이터는 그대로 유지됩니다.")

        named_builder = getattr(bot, "v633_build_named_equipment_file", None)
        if named_builder is not None:
            file = await named_builder(
                str(result["item"]),
                tier,
                str(result["slot"]),
                success,
                level,
                "forge_result",
            )
        else:
            image = await asyncio.to_thread(build_forge_card_png, tier, str(result["slot"]), success, level)
            file = discord.File(io.BytesIO(image), filename="abaddon_forge.png")
        embed.set_image(url=f"attachment://{file.filename}")
        return embed, file

    async def share_result(interaction: discord.Interaction, result: Dict[str, Any]) -> None:
        if not result.get("success"):
            await _send_interaction_error(interaction, "성공한 강화 결과만 자랑할 수 있습니다.")
            return
        user = get_user(interaction.user.id)
        forge = ensure_user_forge(user)
        key = f"{result['item']}:{result['to']}"
        if forge["shares"].get(key):
            await _send_interaction_error(interaction, "이 강화 결과는 이미 자랑했습니다.")
            return
        forge["shares"][key] = _utc_iso()
        save_data()

        embed = discord.Embed(
            title=f"⚔️ {interaction.user.display_name}의 강화 전리품",
            description=f"**[+{result['to']}] {result['display_name']}**\n{result['tier']} · {result['slot']}",
            color=TIER_COLORS.get(str(result["tier"]), 0xAAB0BC),
        )
        embed.add_field(name="대장장이의 증언", value=f"“{result['quote']}”", inline=False)
        embed.set_footer(text="ABADDON FORGE · v4.3.2.1")
        await interaction.response.send_message(embed=embed)

        if not result.get("published"):
            public_event(
                event_type="enhance",
                title=f"+{result['to']} 강화 전리품",
                message=f"{result['display_name']} 강화 결과가 공개되었습니다.",
                actor=interaction.user.display_name,
                guild=getattr(interaction.guild, "name", "") if interaction.guild else "",
                metadata={"item": result["item"], "level": result["to"], "tier": result["tier"]},
            )

    async def send_result_from_interaction(interaction: discord.Interaction, owner_id: int, item_name: str) -> None:
        if interaction.user.id != owner_id:
            await _send_interaction_error(interaction, "이 강화 패널의 소유자가 아닙니다.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        result = await execute_enhancement(
            owner_id,
            interaction.user.display_name,
            getattr(interaction.guild, "name", "") if interaction.guild else "",
            item_name,
        )
        if not result.get("ok"):
            await interaction.followup.send(f"⚠️ {result['error']}", ephemeral=True)
            return
        embed, file = await build_result_embed(result)
        view = ForgeResultView(
            owner_id=owner_id,
            item_name=item_name,
            result=result,
            retry_callback=send_result_from_interaction,
            share_callback=share_result,
        )
        await interaction.followup.send(embed=embed, file=file, view=view)

    async def enhanced_callback(ctx: commands.Context, *, 아이템이름: str) -> None:
        if not await check_registered(ctx):
            return
        result = await execute_enhancement(
            ctx.author.id,
            ctx.author.display_name,
            getattr(ctx.guild, "name", "") if ctx.guild else "",
            아이템이름,
        )
        if not result.get("ok"):
            await ctx.send(f"⚠️ {result['error']}")
            return
        embed, file = await build_result_embed(result)
        view = ForgeResultView(
            owner_id=ctx.author.id,
            item_name=아이템이름,
            result=result,
            retry_callback=send_result_from_interaction,
            share_callback=share_result,
        )
        await ctx.send(embed=embed, file=file, view=view)

    existing_enhance = bot.get_command("강화")
    if existing_enhance is None:
        raise RuntimeError("기존 강화 명령어를 찾지 못했습니다.")
    # 동일한 HybridCommand 인스턴스를 유지해 기존 /장비 강화 라우트와 옵션을 보존합니다.
    existing_enhance.callback = enhanced_callback
    existing_enhance.help = "장비를 강화하고 대장장이 카드, 재강화 및 자랑하기 버튼을 표시합니다."
    existing_enhance.description = existing_enhance.help

    async def enhanced_info_callback(ctx: commands.Context, *, item_name: str) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if item_name not in user.get("inventory", []):
            await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
            return
        tier, info = find_item(item_name)
        if not info:
            await ctx.send("⚠️ 장비 정보를 찾지 못했습니다.")
            return
        current = _safe_int(user.get("enhancements", {}).get(item_name), 0, minimum=0)
        forge = ensure_user_forge(user)
        fail_streak = _safe_int(forge["fail_streaks"].get(item_name), 0, minimum=0)
        profile = enhancement_profile(_safe_int(info.get("price"), 1000, minimum=1), current, fail_streak)
        protected_cost = int(_safe_int(info.get("price"), 1000, minimum=1) * (0.18 + current * 0.05))
        stone_need = 1 + current // 5
        await ctx.send(
            f"⚒️ **[{forge_display_name(item_name, current)} 강화 정보]**\n"
            f"등급·슬롯: **{tier or '일반'} · {get_item_slot(item_name)}**\n"
            f"현재 단계: **+{current}** / 다음 표시 이름: **{forge_display_name(item_name, min(20, current + 1))}**\n"
            f"기본 성공률: **{profile['base_rate']}%** + 장인의 열기 **{profile['heat_bonus']}%** = **{profile['success_rate']}%**\n"
            f"일반 강화 비용: **식량 {profile['cost']:,}개**\n"
            f"보호 강화 비용: **식량 {protected_cost:,}개 + 강화석 {stone_need}개 + 보호권 1개**\n"
            f"연속 실패: **{fail_streak}회** · +10 이상 일반 강화 실패 시 단계 하락 가능\n"
            f"실행: `!강화 {item_name}` / 보호: `!보호강화 {item_name}`"
        )

    existing_info = bot.get_command("강화정보")
    if existing_info is None:
        raise RuntimeError("기존 강화정보 명령어를 찾지 못했습니다.")
    existing_info.callback = enhanced_info_callback
    existing_info.help = "현재 강화 단계, 장인의 열기, 실제 성공률과 비용을 확인합니다."
    existing_info.description = existing_info.help

    existing_protected = bot.get_command("보호강화")
    if existing_protected is not None:
        original_protected_callback = existing_protected.callback

        async def protected_live_wrapper(ctx: commands.Context, *, item_name: str) -> None:
            if not await check_registered(ctx):
                return
            before_user = get_user(ctx.author.id)
            before = _safe_int(before_user.get("enhancements", {}).get(item_name), 0, minimum=0)
            await original_protected_callback(ctx, item_name=item_name)
            after_user = get_user(ctx.author.id)
            after = _safe_int(after_user.get("enhancements", {}).get(item_name), 0, minimum=0)
            if after > before and after in PUBLIC_MILESTONE_LEVELS:
                tier, _info = find_item(item_name)
                public_event(
                    event_type="enhance",
                    title=f"+{after} 보호 강화 성공",
                    message=f"{forge_display_name(item_name, after)}이(가) 보호의 불꽃 속에서 완성되었습니다.",
                    actor=ctx.author.display_name,
                    guild=getattr(ctx.guild, "name", "") if ctx.guild else "",
                    metadata={"item": item_name, "level": after, "tier": tier or "일반", "protected": True},
                )

        existing_protected.callback = protected_live_wrapper

    existing_patch_notes = bot.get_command("패치노트")
    if existing_patch_notes is not None:
        async def latest_patch_notes(ctx: commands.Context) -> None:
            await ctx.send(
                "🕯️ **ABADDON v4.3.2.1 — Background Worker 실시간 피드 핫픽스**\n"
                "• Background Worker는 그대로 유지하고 별도 Web Service로 공개 이벤트만 전송\n"
                "• 비밀키 인증 이벤트 수신, 45초 상태 심박, 150초 무응답 시 OFFLINE 판정\n"
                "• 강화 이정표·공개 공지만 허용하고 경고·문의·DM·유저 데이터는 전송하지 않음\n"
                "• `!실시간피드상태`·`!실시간피드테스트`로 배포 상태 점검\n"
                "• 고딕 강화 카드·장인의 열기·단계별 표시 이름과 v4.3.2 전체 기능 유지"
            )
        existing_patch_notes.callback = latest_patch_notes
        existing_patch_notes.help = "아바돈 최신 통합 패치 내용을 확인합니다."
        existing_patch_notes.description = existing_patch_notes.help

    @bot.command(name="강화기록", help="최근 강화 결과 10개를 확인합니다.")
    async def forge_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        history = ensure_user_forge(user)["history"][:10]
        if not history:
            await ctx.send("🔨 아직 강화 기록이 없습니다.")
            return
        lines = ["🔨 **[최근 강화 기록]**"]
        for record in history:
            mark = "✨" if record.get("success") else ("💥" if record.get("down") else "🕯️")
            lines.append(
                f"{mark} **{record.get('item')}** +{record.get('from', 0)} → +{record.get('to', 0)} "
                f"· 식량 {record.get('cost', 0):,}개 · {record.get('rate', 0)}%"
            )
        await ctx.send("\n".join(lines))

    @bot.command(name="강화연출", help="강화 단계별 장비 표시 이름과 장인의 열기를 안내합니다.")
    async def forge_guide(ctx: commands.Context) -> None:
        await ctx.send(
            "🕯️ **[ABADDON FORGE v4.3.2.1]**\n"
            "강화 결과는 고딕 대장간 카드와 `다시 강화`·`자랑하기` 버튼으로 표시됩니다.\n"
            "표시 이름 진화: **+5 단련된 · +7 광휘의 · +10 종말의 · +12 심연을 가르는 · +15 아바돈의 · +18 경계 너머의 · +20 공허를 끝낸**\n"
            "연속 실패마다 **장인의 열기 +2%**가 쌓이며 최대 +15%까지 다음 강화 확률을 보정합니다. 성공하면 초기화됩니다.\n"
            "표시 이름은 연출용이므로 기존 인벤토리·장착·거래 데이터는 바뀌지 않습니다."
        )

    @bot.command(name="실시간피드상태", help="Background Worker와 홈페이지 실시간 피드 릴레이 상태를 확인합니다.")
    @commands.has_permissions(administrator=True)
    async def live_feed_status(ctx: commands.Context) -> None:
        status = _public_status(bot, world_data)
        relay_base, relay_secret = _relay_config()
        relay_state = _relay_state_snapshot()
        server_info = getattr(bot, "abaddon_public_feed_server", {})
        endpoint = f"{relay_base}/api/events" if relay_base else "PUBLIC_FEED_RELAY_URL 환경변수 미설정"
        local_http = "실행 중" if server_info.get("started") else "꺼짐(Background Worker 권장)"
        event_result = "대기"
        if relay_state.get("last_event_ok") is True:
            event_result = "성공"
        elif relay_state.get("last_event_ok") is False:
            event_result = "실패"
        heartbeat_result = "대기"
        if relay_state.get("last_status_ok") is True:
            heartbeat_result = "성공"
        elif relay_state.get("last_status_ok") is False:
            heartbeat_result = "실패"
        error_line = f"\n최근 오류: `{relay_state.get('last_error')}`" if relay_state.get("last_error") else ""
        await ctx.send(
            "🕯️ **[홈페이지 실시간 피드 v4.3.2.1]**\n"
            f"전송 방식: **별도 Web Service 릴레이** · 설정 **{'완료' if relay_base and relay_secret else '미완료'}**\n"
            f"릴레이 주소: `{endpoint}`\n"
            f"이벤트 전송: **{event_result}** · 상태 심박: **{heartbeat_result}**\n"
            f"내장 HTTP: **{local_http}**\n"
            f"공개 이벤트: **{'켜짐' if status['feed_enabled'] else '꺼짐'}** · 로컬 보관 {status['event_count']}/{MAX_PUBLIC_EVENTS}개\n"
            f"봇 연결: **{'ONLINE' if status['online'] else 'STARTING'}** · 서버 {status['guilds']}개 · 멤버 {status['members']:,}명"
            f"{error_line}\n"
            "설정 후 `!실시간피드테스트`로 실제 전송을 확인하세요."
        )

    @bot.command(name="실시간피드", help="홈페이지 공개 이벤트 피드를 켜거나 끕니다.")
    @commands.has_permissions(administrator=True)
    async def live_feed_toggle(ctx: commands.Context, 상태: str = "상태") -> None:
        feed = ensure_public_feed(world_data)
        normalized = 상태.strip().lower()
        if normalized in {"켜기", "on", "true", "1"}:
            feed["enabled"] = True
            save_data()
            await ctx.send("🟢 홈페이지 공개 이벤트 피드를 켰습니다.")
        elif normalized in {"끄기", "off", "false", "0"}:
            feed["enabled"] = False
            save_data()
            await ctx.send("⚫ 홈페이지 공개 이벤트 피드를 껐습니다. 상태 심박은 유지됩니다.")
        else:
            await ctx.send(f"🕯️ 현재 홈페이지 공개 이벤트 피드: **{'켜짐' if feed.get('enabled', True) else '꺼짐'}**")

    @bot.command(name="실시간공지", help="공식 홈페이지 실시간 피드에 공개 공지를 등록합니다.")
    @commands.has_permissions(administrator=True)
    async def live_announcement(ctx: commands.Context, *, 내용: str) -> None:
        if len(내용.strip()) < 2:
            await ctx.send("⚠️ 공지 내용을 입력하세요.")
            return
        event = public_event(
            event_type="announcement",
            title="운영진 공지",
            message=내용,
            actor=ctx.author.display_name,
            guild=getattr(ctx.guild, "name", "") if ctx.guild else "",
        )
        if event is None:
            await ctx.send("⚠️ 공개 이벤트 피드가 꺼져 있습니다. `!실시간피드 켜기` 후 다시 시도하세요.")
            return
        await ctx.send(f"📡 홈페이지 실시간 피드 전송을 요청했습니다. `{event['id']}`")

    @bot.command(name="실시간피드테스트", help="별도 Web Service로 테스트 이벤트와 상태 심박을 직접 전송합니다.")
    @commands.has_permissions(administrator=True)
    async def live_feed_test(ctx: commands.Context) -> None:
        relay_base, relay_secret = _relay_config()
        if not relay_base or not relay_secret:
            await ctx.send(
                "⚠️ 릴레이 설정이 없습니다. Background Worker 환경변수에 "
                "`PUBLIC_FEED_RELAY_URL`과 `PUBLIC_FEED_RELAY_KEY`를 추가하세요."
            )
            return
        event = publish_public_event(
            world_data,
            save_data,
            event_type="system",
            title="실시간 피드 연결 시험",
            message="Background Worker에서 공개 피드 Web Service로 신호를 전송했습니다.",
            actor="ABADDON",
            metadata={"version": f"v{V432_VERSION}"},
            relay=False,
        )
        if event is None:
            await ctx.send("⚠️ 테스트 이벤트를 만들지 못했습니다.")
            return
        event_result, status_result = await asyncio.gather(
            _relay_post("/api/ingest/event", event, kind="event"),
            _send_relay_status(bot, world_data),
        )
        if event_result.get("ok") and status_result.get("ok"):
            await ctx.send(
                "✅ **실시간 피드 연결 성공**\n"
                f"이벤트·상태 심박이 모두 전송됐습니다. `{relay_base}/api/events`에서 확인할 수 있습니다."
            )
        else:
            detail = event_result.get("error") or status_result.get("error") or "알 수 없는 오류"
            await ctx.send(f"❌ 실시간 피드 전송 실패: `{str(detail)[:300]}`")

    @bot.listen("on_ready")
    async def v432_public_ready_event() -> None:
        relay_base, relay_secret = _relay_config()
        task = getattr(bot, "_v4321_relay_heartbeat_task", None)
        if relay_base and relay_secret and (task is None or task.done()):
            bot._v4321_relay_heartbeat_task = asyncio.create_task(
                _relay_heartbeat_loop(bot, world_data),
                name="abaddon-public-feed-heartbeat",
            )
        if getattr(bot, "_v432_ready_event_published", False):
            return
        bot._v432_ready_event_published = True
        public_event(
            event_type="system",
            title="ABADDON ONLINE",
            message="ABADDON이 종말 네트워크에 연결되었습니다.",
            actor="ABADDON",
            metadata={"version": f"v{V432_VERSION}"},
        )

    print(
        "[V4.3.2.1 등록 확인] "
        f"강화교체={bot.get_command('강화') is existing_enhance} "
        f"강화기록={bot.get_command('강화기록') is not None} "
        f"실시간피드={bot.get_command('실시간피드상태') is not None} "
        f"피드테스트={bot.get_command('실시간피드테스트') is not None} "
        f"HTTP={server_state}",
        flush=True,
    )
