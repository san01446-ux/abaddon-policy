from __future__ import annotations

"""Shared visual rendering helpers for ABADDON v11.5.2.

No user image is persisted. Korean fonts are discovered from the host first. If
Render does not provide one, Noto Sans CJK KR is cached in /tmp on first use.
"""

from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
import re
import urllib.request
import json
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

from apocalypse_bot.commands.v1152_hwatu_assets import hwatu_visual_slot as _mapped_hwatu_slot

VERSION = "11.5.2"
FONT_CACHE = Path(os.getenv("ABADDON_FONT_CACHE", "/tmp/abaddon-fonts"))
FONT_URLS = {
    "regular": os.getenv(
        "ABADDON_FONT_DOWNLOAD_URL",
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf",
    ),
    "bold": os.getenv(
        "ABADDON_FONT_BOLD_DOWNLOAD_URL",
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Bold.otf",
    ),
}
FONT_NAMES = {"regular": "NotoSansCJKkr-Regular.otf", "bold": "NotoSansCJKkr-Bold.otf"}

HWATU_ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "hwatu_v1152"
HWATU_MANIFEST_PATH = HWATU_ASSET_ROOT / "manifest.json"

@lru_cache(maxsize=1)
def _hwatu_manifest() -> dict[str, dict[str, str]]:
    try:
        raw = json.loads(HWATU_MANIFEST_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def _hwatu_slot(card: object) -> int:
    """Resolve the exact traditional artwork slot for live hwatu and Seotda cards."""
    return _mapped_hwatu_slot(
        int(getattr(card, "month", 0) or 0),
        str(getattr(card, "category", getattr(card, "kind", "junk"))),
        junk=int(getattr(card, "junk", 0) or 0),
        uid=int(getattr(card, "uid", 0) or 0),
    )

@lru_cache(maxsize=64)
def _hwatu_asset(month: int, slot: int) -> Image.Image | None:
    try:
        rel = _hwatu_manifest().get(str(int(month)), {}).get(str(int(slot)))
        if not rel:
            return None
        path = HWATU_ASSET_ROOT / rel
        if not path.is_file():
            return None
        return Image.open(path).convert("RGB")
    except Exception:
        return None


_FONT_CANDIDATES = {
    "regular": (
        os.getenv("ABADDON_DASHBOARD_FONT", ""),
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/local/share/fonts/NotoSansCJK-Regular.ttc",
    ),
    "bold": (
        os.getenv("ABADDON_DASHBOARD_FONT_BOLD", ""),
        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/unfonts-core/UnDotumBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf",
        "/usr/share/truetype/noto/NotoSansKR-Bold.ttf",
        "/usr/local/share/fonts/NotoSansCJK-Bold.ttc",
    ),
}


def _download_font(kind: str) -> str | None:
    if os.getenv("ABADDON_DISABLE_FONT_DOWNLOAD", "").lower() in {"1", "true", "yes"}:
        return None
    try:
        FONT_CACHE.mkdir(parents=True, exist_ok=True)
        target = FONT_CACHE / FONT_NAMES[kind]
        if target.is_file() and target.stat().st_size > 100_000:
            return str(target)
        req = urllib.request.Request(FONT_URLS[kind], headers={"User-Agent": "ABADDON/10.9.5"})
        with urllib.request.urlopen(req, timeout=12) as response:
            data = response.read()
        if len(data) < 100_000:
            return None
        target.write_bytes(data)
        return str(target)
    except Exception:
        return None


@lru_cache(maxsize=2)
def resolve_font_path(kind: str = "regular") -> str | None:
    kind = "bold" if kind == "bold" else "regular"
    for candidate in _FONT_CANDIDATES[kind]:
        if candidate and Path(candidate).is_file():
            return candidate
    return _download_font(kind)


@lru_cache(maxsize=128)
def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = resolve_font_path("bold" if bold else "regular")
    if path:
        try:
            return ImageFont.truetype(path, size=max(8, int(size)))
        except OSError:
            pass
    # DejaVu is intentionally the last fallback. It will render English and
    # numbers, while the audit clearly reports that a Korean font is missing.
    fallback = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(fallback, size=max(8, int(size)))
    except OSError:
        return ImageFont.load_default()


def font_status() -> dict[str, str]:
    return {
        "regular": resolve_font_path("regular") or "missing-korean-font",
        "bold": resolve_font_path("bold") or "missing-korean-font",
        "cache": str(FONT_CACHE),
    }


def clean_text(value: object) -> str:
    text = str(value if value is not None else "")
    text = re.sub(r"<a?:\w+:\d+>", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = text.replace("\ufe0f", "")
    return " ".join(text.split())


def text_width(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont) -> float:
    try:
        return float(draw.textlength(text, font=f))
    except Exception:
        box = draw.textbbox((0, 0), text, font=f)
        return float(box[2] - box[0])


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, minimum: int = 13, *, bold: bool = False) -> ImageFont.ImageFont:
    value = clean_text(text)
    for size in range(int(start), int(minimum) - 1, -1):
        candidate = font(size, bold)
        if text_width(draw, value, candidate) <= max_width:
            return candidate
    return font(minimum, bold)


def truncate(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, max_width: int) -> str:
    value = clean_text(text)
    if text_width(draw, value, f) <= max_width:
        return value
    suffix = "…"
    while value and text_width(draw, value + suffix, f) > max_width:
        value = value[:-1]
    return value.rstrip() + suffix


def wrap_text(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> list[str]:
    source = clean_text(text)
    if not source:
        return [""]
    lines: list[str] = []
    current = ""
    # Korean text often has long chunks without useful whitespace. Split each
    # token by characters when a whole token does not fit.
    tokens = source.split(" ")
    for token in tokens:
        candidate = token if not current else f"{current} {token}"
        if text_width(draw, candidate, f) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                break
        part = ""
        for char in token:
            if text_width(draw, part + char, f) <= max_width:
                part += char
            else:
                if part:
                    lines.append(part)
                    if len(lines) >= max_lines:
                        break
                part = char
        if len(lines) >= max_lines:
            break
        current = part
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines:
        reconstructed = " ".join(lines)
        if len(reconstructed.replace(" ", "")) < len(source.replace(" ", "")):
            lines[-1] = truncate(draw, lines[-1] + "…", f, max_width)
    return lines or [""]


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, f: ImageFont.ImageFont, max_width: int, *, fill=(243, 241, 236), max_lines: int = 3, spacing: int = 6) -> int:
    x, y = xy
    lines = wrap_text(draw, text, f, max_width, max_lines)
    box = draw.textbbox((0, 0), "가Ag", font=f)
    line_h = max(12, box[3] - box[1]) + spacing
    for line in lines:
        draw.text((x, y), line, font=f, fill=fill)
        y += line_h
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 20, *, fill=(37, 35, 42), outline=(112, 108, 121), width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def png(image: Image.Image) -> BytesIO:
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


def card_rank(rank: object) -> str:
    try:
        r = int(rank)
    except Exception:
        return str(rank)
    return {0: "JOKER", 11: "J", 12: "Q", 13: "K", 14: "A"}.get(r, str(r))


def suit_text(suit: object) -> str:
    return str(suit).replace("\ufe0f", "")


def card_label(card: object) -> str:
    if isinstance(card, (tuple, list)) and len(card) >= 2:
        return f"{suit_text(card[1])}{card_rank(card[0])}"
    label = getattr(card, "label", None)
    if label:
        return clean_text(label)
    month = getattr(card, "month", None)
    name = getattr(card, "name", None) or getattr(card, "ko", None)
    if month is not None:
        return f"{month}월 {name or ''}".strip()
    return clean_text(card)


def draw_playing_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], card: object | None, *, hidden: bool = False, accent=(112, 79, 180)) -> None:
    x1, y1, x2, y2 = box
    if hidden or card is None:
        rounded(draw, box, 12, fill=(48, 30, 73), outline=accent, width=3)
        for x in range(x1 + 12, x2 - 6, 14):
            draw.line((x, y1 + 8, x - 28, y2 - 8), fill=(95, 63, 132), width=3)
        draw.text(((x1 + x2) // 2, (y1 + y2) // 2), "A", font=font(max(18, (y2-y1)//3), True), fill=(220, 198, 255), anchor="mm")
        return
    rounded(draw, box, 12, fill=(248, 247, 244), outline=(190, 188, 195), width=2)
    label = card_label(card)
    red = any(s in label for s in ("♥", "♦"))
    color = (205, 51, 72) if red else (33, 32, 38)
    f = fit_font(draw, label, x2-x1-14, min(30, (y2-y1)//3), 15, bold=True)
    draw.text((x1 + 8, y1 + 7), label, font=f, fill=color)
    if len(label) >= 2:
        draw.text(((x1+x2)//2, (y1+y2)//2 + 10), label[0], font=font(min(42, (y2-y1)//2), True), fill=color, anchor="mm")


def draw_hwatu_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], card: object, *, hidden: bool = False) -> None:
    if hidden:
        draw_playing_card(draw, box, None, hidden=True, accent=(214, 71, 86))
        return
    x1, y1, x2, y2 = box
    month = int(getattr(card, "month", 0) or 0)
    category = str(getattr(card, "category", getattr(card, "kind", "junk")))
    palette = {
        "bright": (245, 202, 71), "bright_rain": (111, 172, 226),
        "animal": (97, 185, 128), "animal_godori": (97, 185, 128), "animal_doublejunk": (97, 185, 128),
        "ribbon_blue": (80, 137, 221), "ribbon_red_poetry": (225, 75, 89), "ribbon_red_plain": (225, 75, 89), "ribbon": (203, 106, 136),
        "junk": (170, 143, 96),
    }
    color = palette.get(category, (170, 143, 96))
    asset = _hwatu_asset(month, _hwatu_slot(card))
    if asset is not None:
        target_w, target_h = max(1, x2-x1), max(1, y2-y1)
        rendered = ImageOps.contain(asset, (max(1, target_w-4), max(1, target_h-4)), Image.Resampling.LANCZOS)
        draw.rounded_rectangle(box, radius=10, fill=(247, 244, 235), outline=color, width=max(2, target_w//30))
        px = x1 + (target_w-rendered.width)//2
        py = y1 + (target_h-rendered.height)//2
        draw._image.paste(rendered, (px, py))
        rounded(draw, box, 10, fill=None, outline=color, width=max(2, target_w//30))
    else:
        rounded(draw, box, 10, fill=(248, 240, 219), outline=color, width=3)
        draw.rectangle((x1+5, y1+5, x2-5, y1+24), fill=color)
        draw.text(((x1+x2)//2, y1+37), f"{month}월", font=font(18, True), fill=(36, 31, 28), anchor="ma")
    short = {
        "bright": "광", "bright_rain": "비광", "animal": "열끗", "animal_godori": "고도리",
        "animal_doublejunk": "쌍피", "ribbon_blue": "청단", "ribbon_red_poetry": "홍단",
        "ribbon_red_plain": "초단", "ribbon": "띠", "junk": "쌍피" if int(getattr(card, "junk", 0) or 0) >= 2 else "피",
    }.get(category, "패")
    badge_w = max(30, int((x2-x1)*0.58))
    badge_h = max(18, int((y2-y1)*0.17))
    bx1=(x1+x2-badge_w)//2; by2=y2-5; by1=by2-badge_h
    draw.rounded_rectangle((bx1,by1,bx1+badge_w,by2),radius=max(4,badge_h//3),fill=(20,18,23,225),outline=color,width=2)
    draw.text(((x1+x2)//2,(by1+by2)//2),short,font=fit_font(draw,short,badge_w-8,max(12,badge_h-5),9,bold=True),fill=color,anchor="mm")
