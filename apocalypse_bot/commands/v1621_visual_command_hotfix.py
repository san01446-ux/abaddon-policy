from __future__ import annotations

"""ABADDON v16.2.1 visual/accessibility and compact command-center hotfix.

This patch is additive and registered after v16.2.0. It keeps all existing
commands and save data, replaces the affected Pillow renderers with Korean-safe
renderers, and swaps the wide command dropdown for a major-group -> subcategory
flow with short explanations.
"""

import importlib
import io
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from apocalypse_bot.commands.v1094_visual_core import (
    clean_text,
    draw_wrapped,
    fit_font,
    font,
    font_status,
    png,
    rounded,
    text_width,
    wrap_text,
)

VERSION = "16.2.1"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v1621"
PREVIEW_ROOT = ASSET_ROOT / "previews"
ART_ROOT = ASSET_ROOT / "art"

BG = (5, 7, 19)
PANEL = (12, 15, 34)
PANEL_2 = (18, 20, 45)
PURPLE = (148, 82, 255)
PURPLE_SOFT = (192, 151, 255)
CYAN = (80, 214, 255)
WHITE = (246, 242, 255)
MUTED = (180, 177, 205)
GOLD = (245, 188, 77)
GREEN = (78, 225, 162)


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _safe_font(size: int, *args: Any, **kwargs: Any):
    bold = bool(kwargs.get("bold", False))
    if args and isinstance(args[0], bool):
        bold = bool(args[0])
    return font(int(size), bold=bold)


def _load_art(name: str, size: Tuple[int, int], fallback=(11, 12, 30)) -> Image.Image:
    path = ART_ROOT / name
    if path.is_file():
        try:
            image = Image.open(path).convert("RGB")
            return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        except Exception:
            pass
    return Image.new("RGB", size, fallback)


def _gradient(size: Tuple[int, int], start=(5, 7, 20), end=(19, 9, 42)) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    px = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
        for x in range(width):
            px[x, y] = color
    return image


def _glow_border(image: Image.Image, box: Tuple[int, int, int, int], radius: int = 28) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for width, alpha in ((14, 30), (8, 55), (3, 230)):
        draw.rounded_rectangle(box, radius=radius, outline=(*PURPLE, alpha), width=width)
    image.alpha_composite(overlay.filter(ImageFilter.GaussianBlur(1.2)))


def _draw_icon(draw: ImageDraw.ImageDraw, center: Tuple[int, int], kind: str, color=PURPLE_SOFT) -> None:
    x, y = center
    if kind == "target":
        draw.ellipse((x - 21, y - 21, x + 21, y + 21), outline=color, width=4)
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color)
        draw.line((x - 29, y, x - 13, y), fill=color, width=4)
        draw.line((x + 13, y, x + 29, y), fill=color, width=4)
        draw.line((x, y - 29, x, y - 13), fill=color, width=4)
        draw.line((x, y + 13, x, y + 29), fill=color, width=4)
    elif kind == "swirl":
        draw.arc((x - 24, y - 24, x + 24, y + 24), 15, 305, fill=color, width=5)
        draw.arc((x - 14, y - 14, x + 14, y + 14), 190, 520, fill=color, width=5)
    elif kind == "gem":
        points = [(x, y - 27), (x + 20, y - 8), (x + 14, y + 23), (x, y + 31), (x - 14, y + 23), (x - 20, y - 8)]
        draw.polygon(points, fill=(88, 40, 175), outline=color)
        draw.line((x, y - 27, x, y + 31), fill=color, width=3)
        draw.line((x - 20, y - 8, x + 20, y - 8), fill=color, width=3)
    elif kind == "shield":
        points = [(x, y - 27), (x + 23, y - 17), (x + 18, y + 12), (x, y + 30), (x - 18, y + 12), (x - 23, y - 17)]
        draw.polygon(points, fill=(30, 34, 82), outline=color)
        draw.line((x, y - 18, x, y + 18), fill=color, width=3)
    elif kind == "bag":
        draw.rounded_rectangle((x - 22, y - 14, x + 22, y + 26), radius=9, fill=(42, 28, 75), outline=color, width=3)
        draw.rectangle((x - 13, y - 23, x + 13, y - 12), fill=(42, 28, 75), outline=color, width=3)
        draw.arc((x - 13, y - 29, x + 13, y - 6), 180, 360, fill=color, width=3)
    elif kind == "star":
        draw.regular_polygon((x, y, 27), n_sides=8, rotation=22.5, fill=(70, 38, 128), outline=color)
    elif kind == "swords":
        draw.line((x - 20, y - 20, x + 20, y + 20), fill=color, width=6)
        draw.line((x + 20, y - 20, x - 20, y + 20), fill=color, width=6)
    elif kind == "trophy":
        draw.rectangle((x - 14, y - 23, x + 14, y + 8), fill=(69, 38, 120), outline=color, width=3)
        draw.arc((x - 28, y - 22, x - 7, y + 5), 70, 290, fill=color, width=4)
        draw.arc((x + 7, y - 22, x + 28, y + 5), 250, 110, fill=color, width=4)
        draw.line((x, y + 8, x, y + 22), fill=color, width=4)
        draw.line((x - 17, y + 24, x + 17, y + 24), fill=color, width=4)
    elif kind == "chest":
        draw.rounded_rectangle((x - 24, y - 12, x + 24, y + 23), radius=5, fill=(55, 32, 92), outline=color, width=3)
        draw.arc((x - 24, y - 27, x + 24, y + 10), 180, 360, fill=color, width=3)
        draw.rectangle((x - 4, y - 7, x + 4, y + 10), fill=color)
    elif kind == "user":
        draw.ellipse((x - 11, y - 24, x + 11, y - 2), fill=color)
        draw.rounded_rectangle((x - 22, y + 2, x + 22, y + 25), radius=11, fill=color)
    elif kind == "clock":
        draw.ellipse((x - 23, y - 23, x + 23, y + 23), outline=color, width=4)
        draw.line((x, y, x, y - 13), fill=color, width=4)
        draw.line((x, y, x + 12, y + 8), fill=color, width=4)
    elif kind == "crown":
        points = [(x - 24, y + 14), (x - 19, y - 17), (x - 5, y - 3), (x, y - 23), (x + 7, y - 3), (x + 22, y - 17), (x + 24, y + 14)]
        draw.polygon(points, fill=(73, 38, 126), outline=color)
        draw.line((x - 22, y + 20, x + 22, y + 20), fill=color, width=4)
    else:
        draw.ellipse((x - 22, y - 22, x + 22, y + 22), outline=color, width=4)


def render_gather_summary_card(title: str, subtitle: str, rows: Sequence[Tuple[str, str]], *, frame: str = "gather_frame") -> io.BytesIO:
    """Korean-safe replacement for the affected v16.2 gathering summary image."""
    width, height = 1400, 820
    image = _gradient((width, height)).convert("RGBA")
    art = _load_art("gather_portal.png", (520, 760))
    art = ImageEnhance.Contrast(art).enhance(1.08)
    mask = Image.new("L", art.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, art.width, art.height), radius=34, fill=255)
    image.paste(art, (840, 30), mask)
    draw = ImageDraw.Draw(image)
    _glow_border(image, (22, 22, width - 22, height - 22), 34)

    title_font = font(48, bold=True)
    sub_font = font(22, bold=False)
    draw.text((62, 48), clean_text(title), font=title_font, fill=WHITE)
    draw.text((64, 108), clean_text(subtitle), font=sub_font, fill=PURPLE_SOFT)

    row_labels = [clean_text(k) for k, _ in rows]
    row_values = [clean_text(v) for _, v in rows]
    icon_types = ["target", "swirl", "gem", "shield", "bag"]
    row_h = 112
    start_y = 168
    for idx in range(5):
        y1 = start_y + idx * (row_h + 10)
        y2 = y1 + row_h
        rounded(draw, (52, y1, 806, y2), 23, fill=(10, 13, 31), outline=(104, 60, 160), width=2)
        _draw_icon(draw, (101, (y1 + y2) // 2), icon_types[idx])
        label = row_labels[idx] if idx < len(row_labels) else ""
        value = row_values[idx] if idx < len(row_values) else ""
        lf = fit_font(draw, label, 190, 25, 17, bold=True)
        vf = fit_font(draw, value, 450, 27, 16, bold=True)
        draw.text((150, y1 + 38), label, font=lf, fill=PURPLE_SOFT)
        draw.line((334, y1 + 27, 334, y2 - 27), fill=(73, 58, 111), width=2)
        draw.text((365, y1 + 35), value, font=vf, fill=WHITE)

    return png(image.convert("RGB"))


def _fun_data(user: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = user.get("v1220_fun", {}) if isinstance(user, Mapping) else {}
    if isinstance(raw, Mapping):
        return raw
    return {}


def render_chaos_profile(locale: str, name: str, user: Mapping[str, Any]) -> io.BytesIO:
    """Dynamic replacement for the broken ABADDON CHAOS PROFILE renderer."""
    fun = _fun_data(user)
    width, height = 1400, 820
    image = _gradient((width, height), (4, 6, 18), (18, 7, 39)).convert("RGBA")
    art = _load_art("profile_city.png", (610, 270))
    art = ImageEnhance.Brightness(art).enhance(0.78)
    image.paste(art, (760, 30))
    draw = ImageDraw.Draw(image)
    _glow_border(image, (20, 20, width - 20, height - 20), 36)

    draw.text((64, 44), "ABADDON CHAOS PROFILE", font=font(51, bold=True), fill=PURPLE_SOFT)
    # Avatar badge is intentionally drawn rather than relying on remote profile images.
    draw.ellipse((70, 126, 202, 258), fill=(17, 76, 118), outline=PURPLE_SOFT, width=5)
    draw.rounded_rectangle((102, 166, 170, 218), radius=18, fill=(217, 245, 255), outline=CYAN, width=3)
    draw.ellipse((119, 185, 128, 194), fill=(16, 42, 66))
    draw.ellipse((145, 185, 154, 194), fill=(16, 42, 66))
    display = clean_text(name)[:24] or _t(locale, "생존자", "Survivor")
    draw.text((236, 147), display, font=fit_font(draw, display, 430, 44, 24, bold=True), fill=WHITE)
    rounded(draw, (234, 210, 525, 260), 18, fill=(20, 15, 45), outline=(111, 70, 171), width=2)
    draw.text((257, 222), "ABADDON v16.2.1", font=font(22, bold=True), fill=PURPLE_SOFT)

    left_box = (55, 300, 790, 760)
    right_box = (820, 300, 1345, 760)
    rounded(draw, left_box, 28, fill=(17, 14, 41), outline=(151, 78, 232), width=3)
    rounded(draw, right_box, 28, fill=(10, 17, 42), outline=(77, 126, 241), width=3)
    draw.text((105, 332), _t(locale, "기본 정보", "Basic Information"), font=font(34, bold=True), fill=WHITE)
    draw.text((870, 332), _t(locale, "현재 상태", "Current Status"), font=font(34, bold=True), fill=WHITE)

    left_rows = [
        (_t(locale, "혼돈 점수", "Chaos Score"), int(fun.get("fun_score", 0)), "star"),
        (_t(locale, "승리 기록", "Win Record"), int(fun.get("party_wins", 0)), "swords"),
        (_t(locale, "이벤트 클리어", "Events Cleared"), int(fun.get("expeditions_complete", 0)), "trophy"),
        (_t(locale, "수집 기록", "Collection Record"), int(fun.get("collection_count", fun.get("business_earnings", 0))), "chest"),
    ]
    for idx, (label, value, icon) in enumerate(left_rows):
        y1 = 395 + idx * 82
        rounded(draw, (85, y1, 760, y1 + 68), 16, fill=(11, 14, 33), outline=(71, 61, 111), width=2)
        _draw_icon(draw, (125, y1 + 34), icon)
        draw.text((175, y1 + 18), label, font=fit_font(draw, label, 360, 25, 16, bold=True), fill=WHITE)
        val = f"{int(value):,}"
        draw.text((690 - int(text_width(draw, val, font(27, bold=True))), y1 + 16), val, font=font(27, bold=True), fill=WHITE)

    profile = fun.get("profile", {}) if isinstance(fun.get("profile"), Mapping) else {}
    title_key = str(profile.get("title", "festival_rookie"))
    title_map = {
        "festival_rookie": (_t(locale, "초보 생존자", "Rookie Survivor")),
        "party_star": (_t(locale, "축제의 별", "Festival Star")),
        "chaos_master": (_t(locale, "혼돈의 지배자", "Chaos Master")),
    }
    right_rows = [
        (_t(locale, "상태", "Status"), _t(locale, "일반 생존자", "Survivor"), "user", CYAN),
        (_t(locale, "최근 기록", "Recent Record"), _t(locale, "기록 없음", "No Record"), "clock", MUTED),
        (_t(locale, "대표 칭호", "Main Title"), title_map.get(title_key, _t(locale, "초보 생존자", "Rookie Survivor")), "crown", CYAN),
    ]
    for idx, (label, value, icon, color) in enumerate(right_rows):
        y1 = 410 + idx * 112
        _draw_icon(draw, (875, y1 + 33), icon)
        draw.text((920, y1 + 15), label, font=fit_font(draw, label, 190, 25, 16, bold=True), fill=WHITE)
        vf = fit_font(draw, value, 250, 26, 16, bold=True)
        w = text_width(draw, value, vf)
        draw.text((1310 - w, y1 + 15), value, font=vf, fill=color)
        if idx < len(right_rows) - 1:
            draw.line((865, y1 + 84, 1310, y1 + 84), fill=(54, 63, 94), width=2)

    return png(image.convert("RGB"))


def render_support_card(
    display_name: str,
    title: str,
    description: str,
    delta: int,
    balance: int,
    remaining: int,
    situation: str,
    tip: str,
    art_path: Optional[Path] = None,
) -> io.BytesIO:
    width, height = 1120, 1400
    image = _gradient((width, height), (4, 6, 16), (18, 8, 33)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    _glow_border(image, (18, 18, width - 18, height - 18), 34)

    # Simple local avatar badge.
    draw.ellipse((55, 45, 140, 130), fill=(21, 65, 103), outline=PURPLE_SOFT, width=4)
    draw.rounded_rectangle((78, 74, 117, 106), radius=10, fill=(220, 245, 255))
    name = clean_text(display_name)[:24] or "생존자"
    draw.text((165, 65), name, font=fit_font(draw, name, 540, 31, 20, bold=True), fill=WHITE)

    draw.text((65, 160), clean_text(title), font=fit_font(draw, clean_text(title), 930, 55, 34, bold=True), fill=PURPLE_SOFT)
    draw_wrapped(draw, (70, 232), description, font(24), 950, fill=MUTED, max_lines=2, spacing=8)

    stats = [
        ("이번 결과" if delta >= 0 else "이번 손실", f"{delta:+,} 식량", GOLD if delta >= 0 else (255, 113, 124)),
        ("현재 잔액", f"{balance:,} 식량", WHITE),
        ("오늘 남은 지원", f"{remaining}회", WHITE),
        ("다음 요청", "1분 후", WHITE),
        ("상황", clean_text(situation), WHITE),
    ]
    boxes = [(55, 320, 360, 480), (385, 320, 745, 480), (770, 320, 1065, 480), (55, 505, 535, 655), (560, 505, 1065, 655)]
    icons = ["bag", "gem", "clock", "clock", "shield"]
    for idx, (label, value, color) in enumerate(stats):
        box = boxes[idx]
        rounded(draw, box, 20, fill=(10, 13, 31), outline=(100, 61, 151), width=2)
        _draw_icon(draw, (box[0] + 55, box[1] + 72), icons[idx], PURPLE_SOFT)
        draw.text((box[0] + 102, box[1] + 35), label, font=fit_font(draw, label, box[2] - box[0] - 120, 23, 16, bold=True), fill=PURPLE_SOFT)
        draw.text((box[0] + 102, box[1] + 82), value, font=fit_font(draw, value, box[2] - box[0] - 120, 28, 17, bold=True), fill=color)

    rounded(draw, (55, 680, 1065, 810), 20, fill=(11, 12, 30), outline=(104, 63, 156), width=2)
    draw.text((95, 708), "TIP", font=font(26, bold=True), fill=PURPLE_SOFT)
    draw_wrapped(draw, (95, 752), tip, font(21), 900, fill=WHITE, max_lines=2, spacing=6)

    if art_path and art_path.is_file():
        try:
            art = Image.open(art_path).convert("RGB")
            art = ImageOps.fit(art, (1010, 450), method=Image.Resampling.LANCZOS)
        except Exception:
            art = _load_art("support_market.png", (1010, 450))
    else:
        art = _load_art("support_market.png", (1010, 450))
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, art.width, art.height), radius=22, fill=255)
    image.paste(art, (55, 835), mask)

    draw.line((65, 1310, 1055, 1310), fill=(100, 58, 147), width=2)
    footer = "ABADDON 긴급 지원 · 하루 50회 · 특별 교섭은 정상 지원 뒤 랜덤 등장"
    draw.text((70, 1330), footer, font=fit_font(draw, footer, 980, 22, 16, bold=True), fill=PURPLE_SOFT)
    return png(image.convert("RGB"))


# ---------------------------------------------------------------------------
# Compact help navigation: major section -> grouped subcategory -> command.
# ---------------------------------------------------------------------------
HELP_SECTIONS = (
    ("start", "시작", "Start"),
    ("play", "플레이", "Play"),
    ("world", "세계", "World"),
    ("social", "소셜", "Social"),
    ("system", "운영", "System"),
)

HELP_GROUPS: Dict[str, Sequence[Tuple[str, str, str, str, str, Sequence[str]]]] = {
    "start": (
        ("onboarding", "가입·정보·기본", "Onboarding & Profile", "봇 시작, 프로필, 기본 안내를 확인합니다.", "Start the bot, profile and basic guides.", ("가입", "정보", "기본", "프로필", "시작", "튜토리얼", "복귀")),
        ("growth", "퀘스트·성장·업적", "Quests & Growth", "퀘스트, 레벨, 업적과 보상을 찾습니다.", "Find quests, levels, achievements and rewards.", ("퀘스트", "성장", "업적", "레벨", "보상", "출석", "미션")),
        ("catalog", "도감·설정·도움말", "Codex & Settings", "도감, 설정, 안내와 검색 기능입니다.", "Codex, settings, guides and search tools.", ("도감", "설정", "안내", "도움", "검색", "언어")),
    ),
    "play": (
        ("life", "생활·채집·보물", "Life, Gather & Treasure", "채집, 자원, 보물 관련 기능으로 이동합니다.", "Gathering, resources and treasure features.", ("생활", "채집", "보물", "땅파기", "낚시", "파밍", "자원", "알바")),
        ("gear", "상점·장비·제작", "Shop, Gear & Craft", "구매, 강화, 제작 기능을 찾습니다.", "Find shopping, enhancement and crafting.", ("상점", "장비", "제작", "강화", "공방", "아이템", "거래")),
        ("combat", "전투·보스·던전", "Combat, Boss & Dungeon", "전투 콘텐츠와 보스 공략 기능입니다.", "Combat, boss and dungeon features.", ("전투", "보스", "던전", "레이드", "공격", "결투", "전쟁")),
        ("games", "카드·카지노·경마", "Cards, Casino & Racing", "포커, 화투, 경마 등 미니게임 모음입니다.", "Poker, hwatu, racing and casino games.", ("카드", "게임", "카지노", "도박", "포커", "화투", "경마", "블랙잭")),
    ),
    "world": (
        ("black_city", "BLACK CITY", "BLACK CITY", "도시 지도, 세력, 경제와 사건 기능입니다.", "City map, factions, economy and incidents.", ("black city", "도시", "세력", "영토", "신문", "범죄", "아지트")),
        ("neon", "NEON ABYSS", "NEON ABYSS", "차원 항해, 크루, 공격대와 탐험 기능입니다.", "Dimension voyages, crews, raids and exploration.", ("neon", "차원", "심연", "항해", "크루", "공격대", "균열")),
        ("story", "스토리·시즌·탐험", "Story, Season & Explore", "스토리, 시즌, 지역 탐험 진행 기능입니다.", "Story, seasons and regional exploration.", ("스토리", "시즌", "탐험", "사건", "연대기", "개척")),
        ("base", "기지·원정·월드", "Base, Expedition & World", "기지 성장, 원정과 공동 세계 기능입니다.", "Base growth, expeditions and shared world.", ("기지", "원정", "월드", "세계", "지역", "재난", "복구")),
    ),
    "social": (
        ("companions", "동료·펫", "Companions & Pets", "동료, 펫, 관계와 육성 기능입니다.", "Companions, pets, relations and growth.", ("동료", "펫", "관계", "인연", "npc")),
        ("guild", "길드·파티·크루", "Guild, Party & Crew", "협동 조직, 파티와 크루 기능입니다.", "Co-op groups, parties and crews.", ("길드", "파티", "크루", "연합", "분대", "협동")),
        ("events", "일정·방송·축제", "Schedule, Broadcast & Festival", "서버 일정, 방송, 축제와 이벤트 기능입니다.", "Server schedules, broadcasts and events.", ("일정", "방송", "축제", "이벤트", "예약", "중계")),
        ("chat", "대화·친목·수집", "Chat, Social & Collection", "대화, 친목, 수집과 하이라이트 기능입니다.", "Chat, social, collection and highlights.", ("대화", "친목", "수집", "하이라이트", "칭찬", "궁합")),
    ),
    "system": (
        ("server", "서버·권한·알림", "Server, Permissions & Alerts", "서버 설정, 권한과 알림 기능입니다.", "Server settings, permissions and alerts.", ("서버", "권한", "알림", "채널", "역할")),
        ("operations", "운영·검수·오류", "Operations, Audit & Errors", "운영 도구, 검수와 오류 진단 기능입니다.", "Operations, audits and error diagnostics.", ("운영", "검수", "오류", "테스트", "진단", "감사")),
        ("recovery", "복구·백업·관리", "Recovery, Backup & Admin", "복구, 백업과 관리자 기능입니다.", "Recovery, backups and admin tools.", ("복구", "백업", "관리", "초기화", "보안")),
        ("access", "언어·접근성·도움말", "Language & Accessibility", "언어, 접근성, 명령 탐색 기능입니다.", "Language, accessibility and command navigation.", ("언어", "접근", "도움", "명령", "영문", "english")),
    ),
}


def _category_blob(category: Mapping[str, Any]) -> str:
    return " ".join([
        str(category.get("id", "")),
        str(category.get("title", "")),
        str(category.get("hint", "")),
        " ".join(str(x) for x in category.get("commands", [])),
    ]).casefold()


def _section_for_category(v1620: Any, category: Mapping[str, Any]) -> str:
    try:
        return str(v1620._category_section(category))
    except Exception:
        return "world"


def _group_for_category(section: str, category: Mapping[str, Any]) -> str:
    blob = _category_blob(category)
    scored: List[Tuple[int, str]] = []
    for gid, _ko, _en, _dko, _den, keywords in HELP_GROUPS.get(section, ()):
        score = sum(1 for keyword in keywords if str(keyword).casefold() in blob)
        scored.append((score, gid))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    groups = HELP_GROUPS.get(section, ())
    return groups[0][0] if groups else "default"


def _group_spec(section: str, group_id: str) -> Tuple[str, str, str, str]:
    for gid, ko, en, dko, den, _keywords in HELP_GROUPS.get(section, ()):
        if gid == group_id:
            return ko, en, dko, den
    return "기타", "Other", "기타 기능입니다.", "Other features."


def _compact_overview(v1620: Any, locale: str, guide: Sequence[Mapping[str, Any]], section: str = "start", group_id: Optional[str] = None) -> discord.Embed:
    groups = HELP_GROUPS.get(section, ())
    selected = group_id or (groups[0][0] if groups else "default")
    section_label = next((_t(locale, ko, en) for key, ko, en in HELP_SECTIONS if key == section), section)
    embed = discord.Embed(
        title=_t(locale, "📚 ABADDON 통합 명령어 센터", "📚 ABADDON Unified Command Center"),
        description=_t(
            locale,
            "처음 보는 분도 헷갈리지 않도록 **큰 영역 → 세부 그룹 → 기능** 순서로 줄였습니다. 각 선택지에는 짧은 설명이 함께 표시됩니다.\n검색은 `!명령어 키워드`로 바로 사용할 수 있습니다.",
            "Navigate in three short steps: **major section → group → feature**. Every option includes a short description. Search directly with `!help keyword`.",
        ),
        color=0x7D3C98,
    )
    embed.add_field(name=_t(locale, "현재 큰 영역", "Current Major Section"), value=f"**{section_label}**", inline=False)
    for gid, ko, en, dko, den, _ in groups:
        cats = [c for c in guide if _section_for_category(v1620, c) == section and _group_for_category(section, c) == gid]
        marker = "▶" if gid == selected else "•"
        embed.add_field(
            name=f"{marker} {_t(locale, ko, en)} · {len(cats)}",
            value=_t(locale, dko, den),
            inline=False,
        )
    embed.set_footer(text=_t(locale, "위 버튼으로 큰 영역을 바꾸고, 아래 드롭다운에서 세부 그룹과 기능을 고르세요.", "Use the buttons for major sections, then choose a group and feature below."))
    return embed


def _compact_category_embed(v1620: Any, locale: str, category: Mapping[str, Any], full: bool = False) -> discord.Embed:
    commands_list = list(category.get("commands", []))
    hint = clean_text(category.get("hint", "")) or _t(locale, "선택한 기능의 명령어를 확인합니다.", "View commands for the selected feature.")
    embed = discord.Embed(
        title=f"{category.get('emoji', '📁')} {category.get('title', 'Category')}",
        description=hint,
        color=0x6C5CE7,
    )
    embed.add_field(name=_t(locale, "💡 이 기능은?", "💡 What is this?"), value=hint[:1024], inline=False)
    featured = commands_list[: min(6, len(commands_list))]
    if featured:
        embed.add_field(name=_t(locale, "⭐ 먼저 써볼 명령", "⭐ Try These First"), value="\n".join(f"• `{x}`" for x in featured)[:1024], inline=False)
    if full:
        chunks = v1620._command_chunks(commands_list)
        for index, chunk in enumerate(chunks, 1):
            embed.add_field(name=_t(locale, "전체 명령어", "All Commands") + (f" {index}" if index > 1 else ""), value=chunk, inline=False)
    else:
        hidden = max(0, len(commands_list) - len(featured))
        embed.add_field(name=_t(locale, "나머지 명령", "Remaining Commands"), value=_t(locale, f"**대표/전체** 버튼으로 {hidden}개를 더 펼칠 수 있습니다.", f"Use **Featured/All** to reveal {hidden} more."), inline=False)
    return embed


class CompactGroupSelect(discord.ui.Select):
    def __init__(self, owner: "CompactLivingHelpView") -> None:
        options = []
        for gid, ko, en, dko, den, _ in HELP_GROUPS.get(owner.section, ()):
            options.append(discord.SelectOption(label=_t(owner.locale, ko, en)[:100], value=gid, description=_t(owner.locale, dko, den)[:100], default=(gid == owner.group_id)))
        if not options:
            options = [discord.SelectOption(label="Other", value="default")]
        super().__init__(placeholder=_t(owner.locale, "1단계 · 세부 그룹 선택", "Step 1 · Select a group"), options=options[:25], row=1)
        self.owner_view = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        view.group_id = self.values[0]
        view.page = 0
        view.category_id = None
        view.full = False
        view.rebuild()
        await interaction.response.edit_message(embed=view.overview_embed(), view=view)


class CompactCategorySelect(discord.ui.Select):
    def __init__(self, owner: "CompactLivingHelpView") -> None:
        categories = owner.page_categories()
        options = []
        for category in categories:
            hint = clean_text(category.get("hint", "")) or _t(owner.locale, "명령과 기능 설명을 확인합니다.", "View commands and feature details.")
            options.append(discord.SelectOption(label=str(category.get("title", "Category"))[:100], value=str(category.get("id", "")), description=hint[:100], default=(str(category.get("id", "")) == owner.category_id)))
        if not options:
            options = [discord.SelectOption(label=_t(owner.locale, "등록된 기능 없음", "No features"), value="__none__")]
        super().__init__(placeholder=_t(owner.locale, "2단계 · 기능 선택", "Step 2 · Select a feature"), options=options[:25], row=2)
        self.owner_view = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "__none__":
            await interaction.response.defer()
            return
        view = self.owner_view
        view.category_id = self.values[0]
        view.full = False
        view.rebuild()
        await interaction.response.edit_message(embed=view.category_embed(), view=view)


class CompactSectionButton(discord.ui.Button):
    def __init__(self, owner: "CompactLivingHelpView", key: str, ko: str, en: str) -> None:
        super().__init__(label=_t(owner.locale, ko, en), style=discord.ButtonStyle.primary if owner.section == key else discord.ButtonStyle.secondary, row=0)
        self.owner_view = owner
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        view.section = self.key
        groups = HELP_GROUPS.get(self.key, ())
        view.group_id = groups[0][0] if groups else "default"
        view.page = 0
        view.category_id = None
        view.full = False
        view.rebuild()
        await interaction.response.edit_message(embed=view.overview_embed(), view=view)


class CompactActionButton(discord.ui.Button):
    def __init__(self, owner: "CompactLivingHelpView", action: str, ko: str, en: str, style=discord.ButtonStyle.secondary) -> None:
        super().__init__(label=_t(owner.locale, ko, en), style=style, row=3)
        self.owner_view = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if self.action == "home":
            view.category_id = None
            view.full = False
            view.rebuild()
            await interaction.response.edit_message(embed=view.overview_embed(), view=view)
            return
        if self.action == "prev":
            view.page = max(0, view.page - 1)
            view.category_id = None
            view.rebuild()
            await interaction.response.edit_message(embed=view.overview_embed(), view=view)
            return
        if self.action == "next":
            view.page = min(view.max_page(), view.page + 1)
            view.category_id = None
            view.rebuild()
            await interaction.response.edit_message(embed=view.overview_embed(), view=view)
            return
        if self.action == "toggle":
            if not view.selected_category():
                await interaction.response.send_message(_t(view.locale, "먼저 기능을 선택하세요.", "Select a feature first."), ephemeral=True)
                return
            view.full = not view.full
            view.rebuild()
            await interaction.response.edit_message(embed=view.category_embed(), view=view)
            return
        if self.action == "search":
            await interaction.response.send_message(_t(view.locale, "검색 예시: `!명령어 채집`, `!명령어 보스`, `!명령어 설정`", "Search examples: `!help gathering`, `!help boss`, `!help settings`"), ephemeral=True)


class CompactLivingHelpView(discord.ui.View):
    PAGE_SIZE = 20

    def __init__(self, owner_id: int, guide: Sequence[Mapping[str, Any]], locale: str, v1620: Any) -> None:
        super().__init__(timeout=600)
        self.owner_id = int(owner_id)
        self.guide = list(guide)
        self.locale = locale
        self.v1620 = v1620
        self.section = "start"
        self.group_id = HELP_GROUPS["start"][0][0]
        self.page = 0
        self.category_id: Optional[str] = None
        self.full = False
        self.rebuild()

    def group_categories(self) -> List[Mapping[str, Any]]:
        return [c for c in self.guide if _section_for_category(self.v1620, c) == self.section and _group_for_category(self.section, c) == self.group_id]

    def max_page(self) -> int:
        return max(0, (len(self.group_categories()) - 1) // self.PAGE_SIZE)

    def page_categories(self) -> List[Mapping[str, Any]]:
        start = self.page * self.PAGE_SIZE
        return self.group_categories()[start:start + self.PAGE_SIZE]

    def selected_category(self) -> Optional[Mapping[str, Any]]:
        return next((c for c in self.guide if str(c.get("id", "")) == self.category_id), None)

    def overview_embed(self) -> discord.Embed:
        embed = _compact_overview(self.v1620, self.locale, self.guide, self.section, self.group_id)
        ko, en, dko, den = _group_spec(self.section, self.group_id)
        cats = self.group_categories()
        names = " · ".join(str(c.get("title", "")) for c in cats[:8]) or _t(self.locale, "등록된 기능 없음", "No features")
        if len(cats) > 8:
            names += _t(self.locale, f" · 외 {len(cats)-8}개", f" · +{len(cats)-8} more")
        embed.add_field(name=f"📂 {_t(self.locale, ko, en)}", value=f"{_t(self.locale, dko, den)}\n{names}", inline=False)
        return embed

    def category_embed(self) -> discord.Embed:
        return _compact_category_embed(self.v1620, self.locale, self.selected_category() or {}, self.full)

    def rebuild(self) -> None:
        self.clear_items()
        for key, ko, en in HELP_SECTIONS:
            self.add_item(CompactSectionButton(self, key, ko, en))
        self.add_item(CompactGroupSelect(self))
        self.add_item(CompactCategorySelect(self))
        home = CompactActionButton(self, "home", "처음", "Home")
        prev = CompactActionButton(self, "prev", "◀ 이전", "◀ Prev")
        nxt = CompactActionButton(self, "next", "다음 ▶", "Next ▶")
        toggle = CompactActionButton(self, "toggle", "대표/전체", "Featured/All", discord.ButtonStyle.primary)
        search = CompactActionButton(self, "search", "검색 안내", "Search Help")
        prev.disabled = self.page <= 0
        nxt.disabled = self.page >= self.max_page()
        toggle.disabled = self.category_id is None
        for item in (home, prev, nxt, toggle, search):
            self.add_item(item)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 메뉴는 실행자만 조작할 수 있습니다. `!명령어`를 따로 실행하세요.", "Only the opener can use this menu. Run `!help` for your own copy."), ephemeral=True)
        return False


def _patch_pillow_font_helpers() -> List[str]:
    patched: List[str] = []
    modules = (
        "apocalypse_bot.commands.v1092_visual_assets",
        "apocalypse_bot.commands.v1190_event_broadcast_collection",
        "apocalypse_bot.commands.v1220_chaos_festival_complete",
        "apocalypse_bot.commands.v1320_black_city_complete",
        "apocalypse_bot.commands.v1500_neon_abyss",
        "apocalypse_bot.commands.v1620_living_legends",
    )
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "_font"):
                setattr(module, "_font", _safe_font)
                patched.append(module_name.rsplit(".", 1)[-1])
        except Exception:
            continue
    return patched


def register_v1621_visual_command_hotfix(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1621_registered", False):
        return
    bot._abaddon_v1621_registered = True

    from apocalypse_bot.commands import v1220_chaos_festival_complete as v1220
    from apocalypse_bot.commands import v1620_living_legends as v1620

    patched_modules = _patch_pillow_font_helpers()
    v1620._render_summary_card = render_gather_summary_card
    v1220._profile_png = render_chaos_profile

    # Replace the v16.2 class/global references used by the already-installed
    # help callbacks. The callbacks resolve globals at interaction time.
    class BoundCompactLivingHelpView(CompactLivingHelpView):
        def __init__(self, owner_id: int, source: Sequence[Mapping[str, Any]], locale: str) -> None:
            super().__init__(owner_id, source, locale, v1620)

    v1620.LivingHelpView = BoundCompactLivingHelpView
    v1620._help_overview = lambda locale, source, section="start": _compact_overview(v1620, locale, source, section)
    v1620._category_embed = lambda locale, category, full=False: _compact_category_embed(v1620, locale, category, full)

    setattr(bot, "v1621_render_support_card", render_support_card)
    setattr(bot, "v1621_visual_patch_modules", patched_modules)

    if not any(str(c.get("id")) == "v1621_visual_command_hotfix" for c in guide):
        guide.append({
            "id": "v1621_visual_command_hotfix",
            "emoji": "🖼️",
            "title": "v16.2.1 이미지·명령어 UI 핫픽스",
            "hint": "한글 폰트 깨짐 방지, 정보 이미지 재렌더링, 3단계 명령어 탐색과 홈페이지 빠른 이동",
            "commands": [
                "!명령어",
                "!이미지검수 상세",
                "!1621통합검수 상세",
                "!채집",
                "!꾸미기센터",
                "!돈주세요",
            ],
        })

    @bot.command(name="이미지검수", aliases=["visualaudit1621", "fontaudit"], help="한글 폰트와 정보 이미지 렌더러 상태를 검사합니다.")
    async def image_audit(ctx: commands.Context, mode: str = "") -> None:
        status = font_status()
        checks = {
            "한글 일반 글꼴": status.get("regular", "missing") != "missing-korean-font",
            "한글 굵은 글꼴": status.get("bold", "missing") != "missing-korean-font",
            "채집 샘플": (PREVIEW_ROOT / "gather_hub_ko.png").is_file(),
            "지원 샘플": (PREVIEW_ROOT / "support_card_ko.png").is_file(),
            "프로필 샘플": (PREVIEW_ROOT / "chaos_profile_ko.png").is_file(),
            "명령어 샘플": (PREVIEW_ROOT / "command_center_ko.png").is_file(),
        }
        try:
            test = render_gather_summary_card("채집 결과", "통합 채집센터", [("현재 선택", "차원 채집"), ("연출", "진입 → 판정"), ("획득", "차원결정 ×2"), ("공통 보호", "1회 정산"), ("바로가기", "가방 · 숙련도")])
            checks["한글 렌더 스모크"] = len(test.getvalue()) > 20_000
        except Exception:
            checks["한글 렌더 스모크"] = False
        ok = all(checks.values())
        embed = discord.Embed(title="🖼️ ABADDON 이미지 검수 v16.2.1", color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        if mode in {"상세", "detail", "detailed"}:
            embed.add_field(name="폰트 경로", value=f"regular: `{status.get('regular')}`\nbold: `{status.get('bold')}`", inline=False)
            embed.add_field(name="공통 폰트 적용 모듈", value=" · ".join(patched_modules) or "없음", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="1621통합검수", aliases=["v1621audit", "1621audit"], help="v16.2.1 이미지·명령어·홈페이지 패치 연결을 검사합니다.")
    async def v1621_audit(ctx: commands.Context, mode: str = "") -> None:
        command = bot.get_command("명령어")
        checks = {
            "명령어 진입점": command is not None,
            "3단계 도움말 뷰": v1620.LivingHelpView is BoundCompactLivingHelpView,
            "채집 렌더러 교체": v1620._render_summary_card is render_gather_summary_card,
            "프로필 렌더러 교체": v1220._profile_png is render_chaos_profile,
            "지원 렌더러 연결": getattr(bot, "v1621_render_support_card", None) is render_support_card,
            "한글 폰트": font_status().get("bold") != "missing-korean-font",
        }
        ok = all(checks.values())
        embed = discord.Embed(title="🧪 ABADDON v16.2.1 통합 검수", color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        if mode in {"상세", "detail", "detailed"}:
            embed.add_field(name="명령어 흐름", value="큰 영역 버튼 → 세부 그룹 드롭다운 → 기능 드롭다운 → 짧은 설명", inline=False)
            embed.add_field(name="기존 기능", value="삭제 0건 · 기존 명령/저장 유지", inline=False)
        await ctx.send(embed=embed)
