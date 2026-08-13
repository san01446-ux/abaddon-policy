from __future__ import annotations

"""Pillow-based visual dashboard renderers for ABADDON v10.9.2.

The functions return in-memory PNG files and never persist user-specific images.
"""

from io import BytesIO
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from apocalypse_bot.commands.v1094_visual_core import (
    font as _core_font, font_status as _core_font_status, truncate as _core_truncate,
    rounded as _core_rounded, png as _core_png, draw_wrapped as _core_draw_wrapped,
)

BG = (18, 17, 22)
PANEL = (37, 35, 42)
PANEL_2 = (48, 46, 54)
BORDER = (151, 145, 159)
TEXT = (243, 241, 236)
MUTED = (190, 185, 197)
GOLD = (233, 191, 92)
GREEN = (86, 225, 165)
RED = (240, 94, 112)
BLUE = (102, 176, 255)
PURPLE = (180, 112, 255)

FONT_REGULAR = _core_font_status().get("regular")
FONT_BOLD = _core_font_status().get("bold")

def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    return _core_font(size, bold)

def dashboard_font_status() -> Mapping[str, str]:
    return _core_font_status()

def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    return _core_truncate(draw, str(text), font, width)

def _rounded(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], radius: int = 24, *, fill=PANEL, outline=BORDER, width: int = 2) -> None:
    _core_rounded(draw, box, radius, fill=fill, outline=outline, width=width)

def _bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, value: float, maximum: float, *, fill=GREEN) -> None:
    ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, float(value) / float(maximum)))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(73, 70, 79))
    if ratio > 0:
        draw.rounded_rectangle((x, y, x + max(h, int(w * ratio)), y + h), radius=h // 2, fill=fill)

def _png(image: Image.Image) -> BytesIO:
    return _core_png(image)

def build_profile_card(*, locale: str, display_name: str, title: str, job: str, level: int, hp: int, max_hp: int,
                       stamina: int, max_stamina: int, infection: int, condition: str, power: int,
                       food: int, chips: int, inventory_count: int, pet: str, dungeon_wins: int,
                       avatar_bytes: bytes | None = None) -> BytesIO:
    ko = locale == "ko"
    image = Image.new("RGB", (1280, 720), BG)
    draw = ImageDraw.Draw(image)
    _rounded(draw, (24, 24, 1256, 696), 32, fill=(43, 42, 47), outline=(197, 194, 202), width=5)

    # Avatar block.
    draw.rounded_rectangle((64, 70, 266, 272), radius=28, fill=(73, 197, 205), outline=(230, 230, 235), width=3)
    if avatar_bytes:
        try:
            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGB").resize((184, 184))
            mask = Image.new("L", (184, 184), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle((0, 0, 183, 183), radius=26, fill=255)
            image.paste(avatar, (73, 79), mask)
        except Exception:
            avatar_bytes = None
    if not avatar_bytes:
        initials = (display_name[:2] or "A").upper()
        f = _font(70, bold=True)
        bbox = draw.textbbox((0, 0), initials, font=f)
        draw.text((165 - (bbox[2]-bbox[0])/2, 171 - (bbox[3]-bbox[1])/2), initials, font=f, fill=(16, 42, 45))

    draw.text((300, 72), _fit(draw, display_name, _font(40, bold=True), 830), font=_font(40, bold=True), fill=TEXT)
    draw.text((302, 124), _fit(draw, title, _font(25, bold=True), 800), font=_font(25, bold=True), fill=GOLD)
    draw.text((302, 169), f"{'직업' if ko else 'Job'}  {job}", font=_font(26, bold=True), fill=GREEN)
    draw.text((302, 212), f"{'레벨' if ko else 'Level'}  Lv.{level}", font=_font(25, bold=True), fill=BLUE)

    # Vitals.
    draw.text((64, 320), f"HP  {hp:,} / {max_hp:,}", font=_font(24, bold=True), fill=TEXT)
    _bar(draw, 64, 355, 520, 22, hp, max_hp, fill=RED)
    draw.text((64, 402), f"{'스태미나' if ko else 'Stamina'}  {stamina:,} / {max_stamina:,}", font=_font(24, bold=True), fill=TEXT)
    _bar(draw, 64, 437, 520, 22, stamina, max_stamina, fill=GOLD)
    draw.text((64, 484), f"{'감염도' if ko else 'Infection'}  {infection}%", font=_font(24, bold=True), fill=TEXT)
    _bar(draw, 64, 519, 520, 22, infection, 100, fill=PURPLE)
    draw.text((64, 565), f"{'상태' if ko else 'Condition'}  {condition}", font=_font(24, bold=True), fill=GREEN if infection < 50 else RED)

    # Information grid.
    labels = [
        ((650, 307), "전투력" if ko else "Power", f"{power:,}", BLUE),
        ((930, 307), "식량" if ko else "Food", f"{food:,}", GREEN),
        ((650, 425), "카지노 칩" if ko else "Casino Chips", f"{chips:,}", GOLD if chips >= 0 else RED),
        ((930, 425), "장비" if ko else "Inventory", f"{inventory_count:,}", PURPLE),
        ((650, 543), "펫" if ko else "Pet", pet, TEXT),
        ((930, 543), "던전 승리" if ko else "Dungeon Wins", f"{dungeon_wins:,}", GOLD),
    ]
    for (x, y), label, value, color in labels:
        _rounded(draw, (x, y, x + 244, y + 96), 18, fill=PANEL_2, outline=(96, 92, 104), width=2)
        draw.text((x + 18, y + 13), label, font=_font(18, bold=True), fill=MUTED)
        draw.text((x + 18, y + 46), _fit(draw, value, _font(24, bold=True), 205), font=_font(24, bold=True), fill=color)

    footer = "ABADDON v10.9.5 · 실시간 생존자 이미지 대시보드" if ko else "ABADDON v10.9.5 · Live survivor image dashboard"
    draw.text((64, 651), footer, font=_font(17), fill=MUTED)
    return _png(image)


def build_world_map_card(*, locale: str, guild_name: str, weather: str, risk: str,
                         regions: Sequence[Mapping[str, Any]]) -> BytesIO:
    ko = locale == "ko"
    image = Image.new("RGB", (1400, 820), BG)
    draw = ImageDraw.Draw(image)
    _rounded(draw, (24, 24, 1376, 796), 32, fill=(34, 32, 38), outline=(113, 126, 150), width=4)
    draw.text((64, 58), "ABADDON 공동 탐험 지도" if ko else "ABADDON Shared Expedition Map", font=_font(42, bold=True), fill=TEXT)
    draw.text((66, 116), _fit(draw, guild_name, _font(24, bold=True), 650), font=_font(24, bold=True), fill=BLUE)
    draw.text((760, 116), f"{'현재 환경' if ko else 'Environment'}  {weather} · {'위험' if ko else 'Risk'} {risk}", font=_font(22, bold=True), fill=GOLD)

    positions = [(120, 245), (510, 205), (900, 245), (900, 520), (510, 560), (120, 520)]
    for i in range(len(positions) - 1):
        x1, y1 = positions[i]
        x2, y2 = positions[i + 1]
        draw.line((x1 + 150, y1 + 76, x2 + 150, y2 + 76), fill=(88, 96, 113), width=8)

    for idx, row in enumerate(regions[:6]):
        x, y = positions[idx]
        unlocked = bool(row.get("unlocked"))
        defeated = bool(row.get("boss_defeated"))
        progress = int(row.get("progress", 0))
        target = max(1, int(row.get("target", 1)))
        color = GREEN if defeated else (BLUE if unlocked else (86, 83, 91))
        outline = (170, 214, 199) if unlocked else (100, 96, 106)
        _rounded(draw, (x, y, x + 300, y + 152), 22, fill=(45, 44, 50), outline=outline, width=3)
        order = str(idx + 1)
        draw.ellipse((x + 18, y + 18, x + 62, y + 62), fill=color)
        draw.text((x + 35, y + 21), order, font=_font(24, bold=True), fill=BG, anchor="ma")
        name = str(row.get("name", "?"))
        draw.text((x + 78, y + 19), _fit(draw, name, _font(24, bold=True), 200), font=_font(24, bold=True), fill=TEXT if unlocked else MUTED)
        status = ("보스 격파" if ko else "Boss Cleared") if defeated else (("개척 중" if ko else "In Progress") if unlocked else ("잠김" if ko else "Locked"))
        draw.text((x + 78, y + 57), status, font=_font(18, bold=True), fill=color)
        _bar(draw, x + 20, y + 102, 260, 18, progress, target, fill=color)
        pct = min(100, int(progress / target * 100))
        draw.text((x + 20, y + 125), f"{progress:,}/{target:,} · {pct}%", font=_font(15), fill=MUTED)

    draw.text((64, 750), "!지역정찰 지역 → !지역선택 행동 → !개척기부 / !거점건설 / !지역보스공격" if ko else "!regionscout region → !regionchoice action → donate / build / attack boss", font=_font(17), fill=MUTED)
    return _png(image)


def build_card_catalog(*, locale: str, categories: Sequence[Tuple[str, str, Sequence[str]]], game_en: Mapping[str, str]) -> BytesIO:
    ko = locale == "ko"
    image = Image.new("RGB", (1500, 940), BG)
    draw = ImageDraw.Draw(image)
    _rounded(draw, (24, 24, 1476, 916), 32, fill=(34, 32, 39), outline=(173, 128, 215), width=4)
    draw.text((64, 56), "ABADDON 카드게임 도감 · 25종" if ko else "ABADDON Card-Game Catalogue · 25 Modes", font=_font(42, bold=True), fill=TEXT)
    draw.text((66, 112), "종목을 선택하면 규칙·인원·아바돈 대전·판돈 정보를 확인할 수 있습니다." if ko else "Choose a mode for rules, players, ABADDON play and stake details.", font=_font(21), fill=MUTED)

    boxes = [(58, 170, 725, 485), (775, 170, 1442, 485), (58, 520, 725, 870), (775, 520, 1442, 870)]
    accents = [BLUE, GOLD, RED, PURPLE]
    for index, ((ko_title, en_title, games), box, accent) in enumerate(zip(categories, boxes, accents)):
        _rounded(draw, box, 24, fill=PANEL, outline=accent, width=3)
        x1, y1, x2, y2 = box
        draw.text((x1 + 24, y1 + 20), ko_title if ko else en_title, font=_font(26, bold=True), fill=accent)
        y = y1 + 72
        two_col = len(games) > 6
        for gi, game in enumerate(games):
            col = gi % 2 if two_col else 0
            row = gi // 2 if two_col else gi
            gx = x1 + 24 + col * 315
            gy = y + row * 46
            label = game if ko else game_en.get(game, game)
            draw.text((gx, gy), f"{gi + 1:02d}. {_fit(draw, label, _font(19, bold=True), 270)}", font=_font(19, bold=True), fill=TEXT)
    draw.text((64, 886), "음수 잔액 · 자유 레이즈 안전 한도 · 정산 상한 없음 · 모든 종목 ABADDON 지원" if ko else "Negative balances · free-raise safety limit · uncapped settlement · ABADDON in every mode", font=_font(18, bold=True), fill=GREEN)
    return _png(image)


def build_card_detail(*, locale: str, name: str, rule: str, players: str, flow: str, start: str, ai_start: str) -> BytesIO:
    ko = locale == "ko"
    image = Image.new("RGB", (1280, 720), BG)
    draw = ImageDraw.Draw(image)
    _rounded(draw, (24, 24, 1256, 696), 32, fill=(39, 37, 44), outline=(200, 164, 90), width=4)
    draw.text((64, 58), _fit(draw, name, _font(42, bold=True), 1120), font=_font(42, bold=True), fill=GOLD)
    draw.text((66, 118), "실전 진행 카드" if ko else "Authentic Play Card", font=_font(22, bold=True), fill=GREEN)

    sections = [
        ("규칙" if ko else "Rules", rule, 175),
        ("참가 인원" if ko else "Players", players, 295),
        ("진행 방식" if ko else "Flow", flow, 395),
        ("일반 방" if ko else "Public Table", start, 515),
        ("아바돈 대전" if ko else "Play ABADDON", ai_start, 595),
    ]
    for label, value, y in sections:
        draw.text((68, y), label, font=_font(19, bold=True), fill=MUTED)
        _core_draw_wrapped(draw, (255, y - 3), value, _font(22, bold=True), 930, fill=TEXT if y < 500 else BLUE, max_lines=2, spacing=3)
    return _png(image)
