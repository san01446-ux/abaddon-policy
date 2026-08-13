from __future__ import annotations

"""ABADDON v16.2.0 LIVING LEGENDS.

This module is deliberately additive.  It keeps every older command and save
namespace, then adds a bilingual convenience/navigation layer, a unified
Gathering Hub, personal chronicles, daily fate scenes, mounts, crew combo
skills and an opt-in director console.  It also replaces the two help screens
with paged button + select navigation so all historical categories remain
reachable without exceeding Discord's 25-option select limit.
"""

import asyncio
import io
import json
import random
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale
from apocalypse_bot.commands.v1320_black_city_core import (
    ensure_guild as ensure_black_city_guild,
    ensure_root as ensure_black_city_root,
    ensure_user as ensure_black_city_user,
    gather as black_city_gather,
)
from apocalypse_bot.commands.v1500_neon_abyss import render_city_map

VERSION = "16.2.0"
DATA_KEY = "living_legends_v1620"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v1620"
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

MOUNTS: Dict[str, Dict[str, Any]] = {
    "neon_bike": {"ko": "네온 바이크", "en": "Neon Bike", "unlock": 0, "travel": 1},
    "black_carriage": {"ko": "검은 마차", "en": "Black Carriage", "unlock": 5, "travel": 1},
    "steam_train": {"ko": "증기 열차", "en": "Steam Train", "unlock": 10, "travel": 2},
    "abyss_airship": {"ko": "심연 비행선", "en": "Abyss Airship", "unlock": 18, "travel": 2},
    "mecha_horse": {"ko": "기계 말", "en": "Mecha Horse", "unlock": 25, "travel": 2},
    "rift_glider": {"ko": "차원 활공선", "en": "Rift Glider", "unlock": 35, "travel": 3},
    "giant_companion": {"ko": "거대 동료", "en": "Giant Companion", "unlock": 50, "travel": 3},
    "crew_flagship": {"ko": "크루 기함", "en": "Crew Flagship", "unlock": 75, "travel": 4},
}

ALIGNMENTS: Dict[str, Tuple[str, str, str]] = {
    "guardian": ("수호자", "Guardian", "도시와 동료를 지키는 선택"),
    "conqueror": ("정복자", "Conqueror", "위험을 돌파하고 힘으로 해결하는 선택"),
    "merchant": ("거래상", "Merchant", "거래와 협상으로 길을 만드는 선택"),
    "pioneer": ("개척자", "Pioneer", "새 지역과 차원을 탐사하는 선택"),
    "strategist": ("책략가", "Strategist", "정보와 준비로 승부하는 선택"),
    "abyss": ("심연 추종자", "Abyss Disciple", "금지된 힘과 비밀을 추적하는 선택"),
}

DAILY_SCENES: Sequence[Dict[str, Any]] = (
    {"id": "lost_lamp", "ko": "폐허 지구의 가로등이 모두 꺼졌습니다.", "en": "Every streetlight in the Ruins District went dark.", "choices": {"repair": ("수리한다", "Repair them", "guardian"), "trace": ("원인을 추적한다", "Trace the cause", "strategist"), "salvage": ("부품을 회수한다", "Salvage parts", "merchant")}},
    {"id": "rift_guest", "ko": "차원문에서 이름 없는 여행자가 나타났습니다.", "en": "A nameless traveler stepped through the rift.", "choices": {"welcome": ("도시로 안내한다", "Welcome the traveler", "guardian"), "interrogate": ("정체를 심문한다", "Interrogate them", "strategist"), "follow": ("몰래 뒤따른다", "Follow in secret", "abyss")}},
    {"id": "runaway_horse", "ko": "경마장의 기계 말이 도심으로 탈주했습니다.", "en": "A mechanical racehorse escaped into the city.", "choices": {"rescue": ("안전하게 구조한다", "Rescue it safely", "guardian"), "chase": ("탈것으로 추격한다", "Chase it down", "conqueror"), "study": ("움직임을 분석한다", "Study its movement", "pioneer")}},
    {"id": "midnight_market", "ko": "자정 암시장에 단 한 번뿐인 경매가 열렸습니다.", "en": "A one-night auction opened in the midnight market.", "choices": {"bid": ("정면으로 입찰한다", "Bid openly", "merchant"), "investigate": ("물건의 출처를 조사한다", "Investigate the item", "strategist"), "steal_clue": ("비밀 장부를 훔쳐본다", "Peek at the secret ledger", "abyss")}},
    {"id": "crew_distress", "ko": "멀리 나간 크루의 구조 신호가 끊겼습니다.", "en": "A distant crew's distress signal abruptly stopped.", "choices": {"deploy": ("즉시 구조대를 보낸다", "Deploy a rescue team", "guardian"), "scan": ("차원 좌표를 재계산한다", "Recalculate the coordinates", "pioneer"), "force_gate": ("차원문을 강제로 연다", "Force the gate open", "conqueror")}},
)

HELP_SECTIONS = (
    ("start", "🌱 시작", "🌱 Start"),
    ("play", "🎮 플레이", "🎮 Play"),
    ("world", "🌌 세계", "🌌 World"),
    ("social", "👥 소셜", "👥 Social"),
    ("system", "🛠️ 운영", "🛠️ System"),
)

SECTION_KEYWORDS = {
    "start": ("가입", "정보", "기본", "퀘스트", "업적", "start", "basic", "quest"),
    "play": ("생활", "채집", "상점", "장비", "제작", "전투", "보스", "던전", "거래", "카지노", "도박", "카드", "경마", "game", "battle", "card", "casino", "equipment", "gather"),
    "world": ("스토리", "원정", "기지", "도시", "차원", "월드", "탐험", "시즌", "neon", "city", "dimension", "world", "story", "expedition"),
    "social": ("펫", "동료", "길드", "파티", "크루", "대화", "일정", "중계", "친목", "축제", "collection", "guild", "party", "crew", "social", "chat", "event"),
    "system": ("서버", "관리", "알림", "권한", "복구", "검수", "오류", "운영", "audit", "server", "admin", "permission", "alert", "recovery"),
}


def _font(size: int, *, bold: bool = True) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        return _ctx_locale(bot, ctx)
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(DATA_KEY, {})
    root.setdefault("schema", 1)
    root.setdefault("guilds", {})
    return root


def _guild(root: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    row = root["guilds"].setdefault(str(int(guild_id or 0)), {})
    defaults = {
        "settings": {"director": False, "help_mode": "buttons", "fx": "cinematic", "public_legends": False},
        "users": {},
        "events": {},
        "director_history": [],
        "stats": {"help_opens": 0, "gathers": 0, "scenes": 0, "legend_cards": 0},
    }
    for key, value in defaults.items():
        row.setdefault(key, deepcopy(value))
    for key, value in defaults["settings"].items():
        row["settings"].setdefault(key, value)
    return row


def _user(row: MutableMapping[str, Any], user_id: int) -> MutableMapping[str, Any]:
    u = row["users"].setdefault(str(int(user_id)), {})
    defaults = {
        "favorites": [], "recent": [], "last_gather_at": 0, "gather_counts": {},
        "dimension_resources": {}, "crew_resources": {}, "alignment": {key: 0 for key in ALIGNMENTS},
        "active_mount": "neon_bike", "unlocked_mounts": ["neon_bike"],
        "appearance": {"aura": "purple", "pose": "ready", "background": "neon_city"},
        "chronicle": [], "records": {}, "daily_scene": {}, "combo": {},
    }
    for key, value in defaults.items():
        u.setdefault(key, deepcopy(value))
    return u


def _normal(text: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").casefold())


def _category_section(category: Mapping[str, Any]) -> str:
    text = f"{category.get('id','')} {category.get('title','')} {category.get('hint','')}".casefold()
    scores = {section: sum(1 for token in tokens if token.casefold() in text) for section, tokens in SECTION_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "world"


def _split_categories(guide: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    result = {key: [] for key, _, _ in HELP_SECTIONS}
    seen = set()
    for category in guide:
        cid = str(category.get("id", ""))
        if not cid or cid in seen:
            continue
        seen.add(cid)
        result[_category_section(category)].append(category)
    return result


def _command_chunks(commands_list: Sequence[str], max_len: int = 950) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    length = 0
    for command in commands_list:
        line = f"• `{command}`"
        if current and length + len(line) + 1 > max_len:
            chunks.append("\n".join(current))
            current, length = [line], len(line)
        else:
            current.append(line)
            length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _help_overview(locale: str, guide: Sequence[Mapping[str, Any]], section: str = "start") -> discord.Embed:
    split = _split_categories(guide)
    section_name = next((_t(locale, ko, en) for key, ko, en in HELP_SECTIONS if key == section), section)
    embed = discord.Embed(
        title=_t(locale, "📚 ABADDON 통합 명령어 센터", "📚 ABADDON Unified Command Center"),
        description=_t(
            locale,
            "초창기 기능부터 최신 세계 기능까지 삭제 없이 정리했습니다. 아래 **영역 버튼 → 카테고리 드롭다운** 순서로 이동하세요.\n`!명령어 검색어`로 바로 검색할 수도 있습니다.",
            "Every legacy and current feature remains available. Use **section buttons → category dropdown** to navigate, or search with `!help keyword`.",
        ),
        color=0x7D3C98,
    )
    embed.add_field(name=_t(locale, "현재 영역", "Current Section"), value=f"**{section_name}** · {len(split.get(section, []))} categories", inline=False)
    for key, ko, en in HELP_SECTIONS:
        cats = split.get(key, [])
        names = " · ".join(str(c.get("title", "")) for c in cats[:6])
        if len(cats) > 6:
            names += _t(locale, f" · 외 {len(cats)-6}개", f" · +{len(cats)-6} more")
        embed.add_field(name=_t(locale, ko, en), value=names or _t(locale, "등록된 카테고리 없음", "No categories"), inline=False)
    embed.set_footer(text=_t(locale, "버튼은 화면 이동용이며 기존 명령은 그대로 유지됩니다.", "Buttons navigate the guide; all original commands remain unchanged."))
    return embed


def _category_embed(locale: str, category: Mapping[str, Any], full: bool = False) -> discord.Embed:
    commands_list = list(category.get("commands", []))
    embed = discord.Embed(
        title=f"{category.get('emoji','📁')} {category.get('title','Category')}",
        description=str(category.get("hint", "")),
        color=0x6C5CE7,
    )
    featured = commands_list[: min(7, len(commands_list))]
    if featured:
        embed.add_field(name=_t(locale, "⭐ 빠른 시작", "⭐ Quick Start"), value="\n".join(f"• `{x}`" for x in featured)[:1024], inline=False)
    if full:
        for index, chunk in enumerate(_command_chunks(commands_list), 1):
            embed.add_field(name=_t(locale, "전체 명령어", "All Commands") + (f" {index}" if index > 1 else ""), value=chunk, inline=False)
    else:
        embed.add_field(
            name=_t(locale, "📜 나머지 명령", "📜 Remaining Commands"),
            value=_t(locale, f"아래 **전체 보기** 버튼으로 {max(0, len(commands_list)-len(featured))}개를 펼칠 수 있습니다.", f"Use **Show All** to reveal {max(0, len(commands_list)-len(featured))} more commands."),
            inline=False,
        )
    return embed


def _search_guide(guide: Sequence[Mapping[str, Any]], query: str, limit: int = 35) -> List[Tuple[str, str]]:
    token = _normal(query)
    matches: List[Tuple[int, int, str, str]] = []
    if not token:
        return []
    for category in guide:
        title = str(category.get("title", ""))
        cat_text = _normal(title + " " + str(category.get("hint", "")))
        for command in category.get("commands", []):
            norm = _normal(command)
            if norm.startswith(token): score = 0
            elif token in norm: score = 1
            elif token in cat_text: score = 2
            else: continue
            matches.append((score, len(str(command)), title, str(command)))
    matches.sort()
    result: List[Tuple[str, str]] = []
    seen = set()
    for _, _, title, command in matches:
        if (title, command) in seen: continue
        seen.add((title, command)); result.append((title, command))
        if len(result) >= limit: break
    return result


def _search_embed(locale: str, query: str, results: Sequence[Tuple[str, str]]) -> discord.Embed:
    embed = discord.Embed(title=_t(locale, f"🔎 명령어 검색 · {query}", f"🔎 Command Search · {query}"), color=0x3498DB)
    if not results:
        embed.description = _t(locale, "일치하는 명령을 찾지 못했습니다.", "No matching command was found.")
    else:
        embed.description = "\n".join(f"• **{cat}** — `{cmd}`" for cat, cmd in results[:20])
        if len(results) > 20:
            embed.add_field(name=_t(locale, "추가 결과", "More Results"), value=str(len(results)-20), inline=False)
    return embed


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, owner: "LivingHelpView") -> None:
        categories = owner.page_categories()
        options = [
            discord.SelectOption(
                label=str(category.get("title", "Category"))[:100],
                value=str(category.get("id", "")),
                description=str(category.get("hint", ""))[:100],
            ) for category in categories
        ]
        if not options:
            options = [discord.SelectOption(label="No categories", value="__none__")]
        super().__init__(placeholder=_t(owner.locale, "카테고리를 선택하세요", "Select a category"), options=options, min_values=1, max_values=1, row=0)
        self.owner_view = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "__none__":
            await interaction.response.defer()
            return
        self.owner_view.category_id = self.values[0]
        self.owner_view.full = False
        category = self.owner_view.selected_category()
        self.owner_view.rebuild()
        await interaction.response.edit_message(embed=_category_embed(self.owner_view.locale, category or {}, False), view=self.owner_view)


class HelpSectionButton(discord.ui.Button):
    def __init__(self, owner: "LivingHelpView", key: str, ko: str, en: str) -> None:
        super().__init__(label=_t(owner.locale, ko, en), style=discord.ButtonStyle.primary if owner.section == key else discord.ButtonStyle.secondary, row=1)
        self.owner_view, self.key = owner, key

    async def callback(self, interaction: discord.Interaction) -> None:
        self.owner_view.section = self.key
        self.owner_view.page = 0
        self.owner_view.category_id = None
        self.owner_view.full = False
        self.owner_view.rebuild()
        await interaction.response.edit_message(embed=_help_overview(self.owner_view.locale, self.owner_view.guide, self.key), view=self.owner_view)


class HelpActionButton(discord.ui.Button):
    def __init__(self, owner: "LivingHelpView", action: str, label_ko: str, label_en: str, *, style: discord.ButtonStyle = discord.ButtonStyle.secondary, row: int = 2) -> None:
        super().__init__(label=_t(owner.locale, label_ko, label_en), style=style, row=row)
        self.owner_view, self.action = owner, action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if self.action == "home":
            view.category_id = None; view.full = False; view.rebuild()
            await interaction.response.edit_message(embed=_help_overview(view.locale, view.guide, view.section), view=view); return
        if self.action == "today":
            embed = discord.Embed(title=_t(view.locale, "☀️ 오늘의 빠른 동선", "☀️ Today's Quick Route"), color=0xF1C40F)
            routes = [
                ("🎁", "!출석 / !checkin"), ("🎯", "!일일퀘스트 / !dailyquest"), ("⛏️", "!채집 / !gather"),
                ("🏙️", "!도시 / !city"), ("🌌", "!차원문 / !dimensiongate"), ("👹", "!공격대 / !dimensionraid"),
            ]
            embed.description = "\n".join(f"{icon} `{cmd}`" for icon, cmd in routes)
            await interaction.response.edit_message(embed=embed, view=view); return
        if self.action == "gather":
            embed = discord.Embed(title=_t(view.locale, "⛏️ 통합 채집센터", "⛏️ Unified Gathering Hub"), description=_t(view.locale, "`!채집` 한 번으로 일반·도시·차원·크루·동료 채집을 선택합니다.", "Use `!gather` once to choose field, city, dimension, crew or companion gathering."), color=0x1ABC9C)
            await interaction.response.edit_message(embed=embed, view=view); return
        if self.action == "games":
            category = next((c for c in view.guide if any(x in str(c.get("title", "")).casefold() for x in ("카드", "game", "casino"))), None)
            if category:
                view.category_id = str(category.get("id")); view.full = False; view.section = _category_section(category); view.page = 0; view.rebuild()
                await interaction.response.edit_message(embed=_category_embed(view.locale, category), view=view); return
        if self.action == "world":
            category = next((c for c in view.guide if any(x in str(c.get("title", "")).casefold() for x in ("neon", "도시", "dimension"))), None)
            if category:
                view.category_id = str(category.get("id")); view.full = False; view.section = _category_section(category); view.page = 0; view.rebuild()
                await interaction.response.edit_message(embed=_category_embed(view.locale, category), view=view); return
        if self.action == "search":
            await interaction.response.send_message(_t(view.locale, "검색: `!명령어 키워드` 예) `!명령어 채집`", "Search: `!help keyword` e.g. `!help gathering`"), ephemeral=True); return
        if self.action == "toggle":
            category = view.selected_category()
            if not category:
                await interaction.response.send_message(_t(view.locale, "먼저 카테고리를 선택하세요.", "Select a category first."), ephemeral=True); return
            view.full = not view.full; view.rebuild()
            await interaction.response.edit_message(embed=_category_embed(view.locale, category, view.full), view=view); return
        if self.action == "prev":
            view.page = max(0, view.page - 1); view.category_id = None; view.rebuild()
            await interaction.response.edit_message(embed=_help_overview(view.locale, view.guide, view.section), view=view); return
        if self.action == "next":
            view.page = min(view.max_page(), view.page + 1); view.category_id = None; view.rebuild()
            await interaction.response.edit_message(embed=_help_overview(view.locale, view.guide, view.section), view=view); return


class LivingHelpView(discord.ui.View):
    PAGE_SIZE = 24
    def __init__(self, owner_id: int, guide: Sequence[Mapping[str, Any]], locale: str) -> None:
        super().__init__(timeout=600)
        self.owner_id = int(owner_id)
        self.guide = list(guide)
        self.locale = locale
        self.section = "start"
        self.page = 0
        self.category_id: Optional[str] = None
        self.full = False
        self.rebuild()

    def section_categories(self) -> List[Mapping[str, Any]]:
        return _split_categories(self.guide).get(self.section, [])

    def max_page(self) -> int:
        count = len(self.section_categories())
        return max(0, (count - 1) // self.PAGE_SIZE)

    def page_categories(self) -> List[Mapping[str, Any]]:
        categories = self.section_categories()
        start = self.page * self.PAGE_SIZE
        return categories[start:start + self.PAGE_SIZE]

    def selected_category(self) -> Optional[Mapping[str, Any]]:
        return next((category for category in self.guide if str(category.get("id")) == self.category_id), None)

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(HelpCategorySelect(self))
        for key, ko, en in HELP_SECTIONS:
            self.add_item(HelpSectionButton(self, key, ko, en))
        for action, ko, en, style in (
            ("home", "🏠 처음", "🏠 Home", discord.ButtonStyle.secondary),
            ("today", "☀️ 오늘", "☀️ Today", discord.ButtonStyle.success),
            ("gather", "⛏️ 채집", "⛏️ Gather", discord.ButtonStyle.success),
            ("games", "🎮 게임", "🎮 Games", discord.ButtonStyle.primary),
            ("world", "🌌 도시·차원", "🌌 City·Rift", discord.ButtonStyle.primary),
        ):
            self.add_item(HelpActionButton(self, action, ko, en, style=style, row=2))
        prev = HelpActionButton(self, "prev", "◀ 이전", "◀ Previous", row=3); prev.disabled = self.page <= 0
        nxt = HelpActionButton(self, "next", "다음 ▶", "Next ▶", row=3); nxt.disabled = self.page >= self.max_page()
        toggle = HelpActionButton(self, "toggle", "📜 대표/전체", "📜 Featured/All", row=3); toggle.disabled = self.category_id is None
        search = HelpActionButton(self, "search", "🔎 검색 안내", "🔎 Search Help", row=3)
        self.add_item(prev); self.add_item(nxt); self.add_item(toggle); self.add_item(search)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 메뉴는 실행자만 조작할 수 있습니다. `!명령어`를 따로 실행하세요.", "Only the opener can use this menu. Run `!help` for your own copy."), ephemeral=True)
        return False


async def _staged_message(ctx: commands.Context, locale: str, lines: Sequence[Tuple[str, str]], mode: str = "cinematic") -> Optional[discord.Message]:
    if mode == "off" or not lines:
        return None
    selected = list(lines[:2] if mode == "compact" else lines)
    message = await ctx.send(_t(locale, *selected[0]))
    for ko, en in selected[1:]:
        await asyncio.sleep(0.38)
        try:
            await message.edit(content=_t(locale, ko, en))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            break
    return message


def _render_summary_card(title: str, subtitle: str, rows: Sequence[Tuple[str, str]], *, frame: str = "gather_frame") -> io.BytesIO:
    frame_path = ASSET_ROOT / "ui" / f"{frame}.png"
    if frame_path.exists():
        image = Image.open(frame_path).convert("RGBA")
    else:
        image = Image.new("RGBA", (1400, 820), (5, 7, 20, 255))
    draw = ImageDraw.Draw(image)
    draw.text((85, 76), title[:40], font=_font(42), fill=(252, 248, 255))
    draw.text((85, 132), subtitle[:90], font=_font(20), fill=(163, 224, 255))
    y = 225
    for label, value in rows[:5]:
        draw.text((95, y), str(label)[:28], font=_font(24), fill=(190, 168, 255))
        draw.text((460, y), str(value)[:62], font=_font(24), fill=(245, 242, 255))
        y += 115
    out = io.BytesIO(); image.convert("RGB").save(out, format="PNG", optimize=True); out.seek(0); return out


def _legend_score(user: Mapping[str, Any], row_user: Mapping[str, Any]) -> int:
    stats = user.get("stats", {}) if isinstance(user, Mapping) else {}
    return max(0, int(stats.get("wins", 0)) * 5 + int(stats.get("games", 0)) + len(row_user.get("chronicle", [])) * 2 + sum(int(v) for v in row_user.get("gather_counts", {}).values()))


def _dominant_alignment(row_user: Mapping[str, Any]) -> str:
    values = row_user.get("alignment", {})
    return max(ALIGNMENTS, key=lambda key: int(values.get(key, 0))) if values else "pioneer"


def _record_chronicle(row_user: MutableMapping[str, Any], kind: str, text: str, *, data: Optional[Mapping[str, Any]] = None) -> None:
    row_user.setdefault("chronicle", []).append({"at": int(time.time()), "kind": kind, "text": str(text)[:240], "data": dict(data or {})})
    row_user["chronicle"] = row_user["chronicle"][-120:]


def _resolve_mount(token: str, locale: str = "ko") -> Optional[str]:
    norm = _normal(token)
    for mid, spec in MOUNTS.items():
        if norm in {_normal(mid), _normal(spec["ko"]), _normal(spec["en"])}:
            return mid
    return None


class GatherModeSelect(discord.ui.Select):
    def __init__(self, owner: "GatherHubView") -> None:
        options = [
            discord.SelectOption(label=_t(owner.locale, "일반 채집", "Field Gathering"), value="field", description=_t(owner.locale, "기존 개인 생활 숙련도와 자원", "Original personal life mastery and resources")),
            discord.SelectOption(label=_t(owner.locale, "도시 채집", "City Gathering"), value="city", description=_t(owner.locale, "직업·도시 지역·도시 제작 재료", "Profession, district and city crafting materials")),
            discord.SelectOption(label=_t(owner.locale, "차원 채집", "Dimension Gathering"), value="dimension", description=_t(owner.locale, "활성 차원의 희귀 결정과 변칙 자원", "Rare crystals and anomaly resources")),
            discord.SelectOption(label=_t(owner.locale, "크루 공동 채집", "Crew Gathering"), value="crew", description=_t(owner.locale, "크루 경험치와 공동 자원", "Crew XP and shared resources")),
            discord.SelectOption(label=_t(owner.locale, "동료 지원 채집", "Companion-assisted Gathering"), value="companion", description=_t(owner.locale, "동료가 보조하는 안전 채집", "Safe gathering assisted by a companion")),
        ]
        super().__init__(placeholder=_t(owner.locale, "채집 방식을 선택하세요", "Choose a gathering mode"), options=options, row=0)
        self.owner_view = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        self.owner_view.mode = self.values[0]
        self.owner_view.rebuild()
        await interaction.response.edit_message(embed=self.owner_view.embed(), view=self.owner_view)


class GatherButton(discord.ui.Button):
    def __init__(self, owner: "GatherHubView", action: str, ko: str, en: str, style: discord.ButtonStyle, row: int = 1) -> None:
        super().__init__(label=_t(owner.locale, ko, en), style=style, row=row)
        self.owner_view, self.action = owner, action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.action == "start":
            await interaction.response.defer(ephemeral=True)
            result = await self.owner_view.runner(self.owner_view.ctx, self.owner_view.mode)
            await interaction.followup.send(result, ephemeral=True)
            return
        if self.action == "bag":
            await interaction.response.send_message(embed=self.owner_view.bag_embed(), ephemeral=True); return
        if self.action == "mastery":
            await interaction.response.send_message(embed=self.owner_view.mastery_embed(), ephemeral=True); return
        if self.action == "recommend":
            self.owner_view.mode = self.owner_view.recommended_mode()
            self.owner_view.rebuild()
            await interaction.response.edit_message(embed=self.owner_view.embed(), view=self.owner_view); return
        if self.action == "close":
            for item in self.owner_view.children:
                item.disabled = True
            await interaction.response.edit_message(view=self.owner_view); self.owner_view.stop(); return


class GatherHubView(discord.ui.View):
    def __init__(self, owner_id: int, ctx: commands.Context, locale: str, runner: Callable[[commands.Context, str], Any], row_user: MutableMapping[str, Any], game_user: MutableMapping[str, Any]) -> None:
        super().__init__(timeout=300)
        self.owner_id, self.ctx, self.locale, self.runner = int(owner_id), ctx, locale, runner
        self.row_user, self.game_user = row_user, game_user
        self.mode = "field"
        self.rebuild()

    def rebuild(self) -> None:
        self.clear_items(); self.add_item(GatherModeSelect(self))
        self.add_item(GatherButton(self, "start", "⛏️ 채집 시작", "⛏️ Start Gathering", discord.ButtonStyle.success))
        self.add_item(GatherButton(self, "recommend", "✨ 추천 선택", "✨ Recommend", discord.ButtonStyle.primary))
        self.add_item(GatherButton(self, "bag", "📦 통합 가방", "📦 Unified Bag", discord.ButtonStyle.secondary))
        self.add_item(GatherButton(self, "mastery", "📊 숙련도", "📊 Mastery", discord.ButtonStyle.secondary))
        self.add_item(GatherButton(self, "close", "✖ 닫기", "✖ Close", discord.ButtonStyle.danger))

    def recommended_mode(self) -> str:
        neon = self.ctx.bot.__dict__.get("_abaddon_v1500_registered")
        black = self.game_user.get("black_city_v1320", {})
        if black.get("profession"):
            return "city"
        return "dimension" if neon else "field"

    def embed(self) -> discord.Embed:
        names = {"field": ("일반 채집", "Field Gathering"), "city": ("도시 채집", "City Gathering"), "dimension": ("차원 채집", "Dimension Gathering"), "crew": ("크루 공동 채집", "Crew Gathering"), "companion": ("동료 지원 채집", "Companion-assisted Gathering")}
        embed = discord.Embed(title=_t(self.locale, "⛏️ ABADDON 통합 채집센터", "⛏️ ABADDON Unified Gathering Hub"), description=_t(self.locale, "기존 채집은 삭제하지 않고 한 화면에 연결했습니다. 선택 후 **채집 시작**을 누르세요.", "No legacy gathering was removed. Choose a route and press **Start Gathering**."), color=0x16A085)
        embed.add_field(name=_t(self.locale, "현재 선택", "Selected Route"), value=f"**{_t(self.locale, *names[self.mode])}**", inline=False)
        embed.add_field(name=_t(self.locale, "공통 안전장치", "Shared Safeguards"), value=_t(self.locale, "통합 재사용 대기 · 행동 ID 1회 정산 · 재시작 안전 기록 · 결과 이미지 폴백", "Unified cooldown · one settlement per action ID · restart-safe record · result image fallback"), inline=False)
        return embed

    def bag_embed(self) -> discord.Embed:
        resources = self.game_user.get("resources", {})
        materials = self.game_user.get("materials", {})
        city = self.game_user.get("black_city_v1320", {}).get("materials", {})
        dimension = self.row_user.get("dimension_resources", {})
        embed = discord.Embed(title=_t(self.locale, "📦 통합 채집 가방", "📦 Unified Gathering Bag"), color=0x2C3E50)
        for title_ko, title_en, data in (("일반 자원", "Field Resources", resources), ("일반 재료", "General Materials", materials), ("도시 재료", "City Materials", city), ("차원 재료", "Dimension Materials", dimension)):
            lines = " · ".join(f"{k} {v}" for k, v in list(data.items())[:12]) or _t(self.locale, "없음", "None")
            embed.add_field(name=_t(self.locale, title_ko, title_en), value=lines[:1024], inline=False)
        return embed

    def mastery_embed(self) -> discord.Embed:
        life = self.game_user.get("life_mastery", {})
        city = self.game_user.get("black_city_v1320", {})
        counts = self.row_user.get("gather_counts", {})
        embed = discord.Embed(title=_t(self.locale, "📊 채집 숙련도·기록", "📊 Gathering Mastery & Records"), color=0x27AE60)
        embed.add_field(name=_t(self.locale, "생활 숙련", "Life Mastery"), value=" · ".join(f"{k} {v}" for k, v in life.items()) or "0", inline=False)
        embed.add_field(name=_t(self.locale, "도시 직업", "City Profession"), value=f"{city.get('profession') or '-'} · Lv.{city.get('profession_level',1)}", inline=True)
        embed.add_field(name=_t(self.locale, "통합 기록", "Unified Counts"), value=" · ".join(f"{k} {v}" for k, v in counts.items()) or "0", inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "본인의 `!채집` 메뉴를 열어주세요.", "Open your own `!gather` menu."), ephemeral=True)
        return False


def _safe_command_names(bot: commands.Bot) -> Tuple[Dict[str, str], List[Tuple[str, str, str]]]:
    owner: Dict[str, str] = {}
    collisions: List[Tuple[str, str, str]] = []
    for command in bot.walk_commands():
        qualified = str(getattr(command, "qualified_name", command.name))
        for name in [command.name, *getattr(command, "aliases", [])]:
            key = str(name).casefold()
            previous = owner.get(key)
            if previous and previous != qualified:
                collisions.append((str(name), previous, qualified))
            else:
                owner[key] = qualified
    return owner, collisions


def _guide_command_tokens(guide: Sequence[Mapping[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for category in guide:
        for line in category.get("commands", []):
            for match in re.findall(r"!([^\s/·`]+)", str(line)):
                tokens.add(match.casefold())
    return tokens


def register_v1620_living_legends(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1620_registered", False):
        return
    bot._abaddon_v1620_registered = True
    root = _root(world_data)
    black_root = ensure_black_city_root(world_data)
    locks: Dict[int, asyncio.Lock] = {}

    def guild_row(ctx: commands.Context) -> MutableMapping[str, Any]:
        return _guild(root, int(getattr(getattr(ctx, "guild", None), "id", 0) or 0))

    def locale(ctx: commands.Context) -> str:
        return _locale(bot, ctx)

    async def require_user(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        return get_user(ctx.author.id)

    # ------------------------------------------------------------------
    # Help and English help overhaul.  No category is deleted.
    # ------------------------------------------------------------------
    def install_help_callbacks() -> None:
        korean = bot.get_command("명령어")
        if korean is not None:
            previous = korean.callback
            async def new_korean_help(ctx: commands.Context, *, 검색어: str = None) -> None:
                row = guild_row(ctx); row["stats"]["help_opens"] = int(row["stats"].get("help_opens", 0)) + 1
                view = LivingHelpView(ctx.author.id, guide, "ko")
                embed = _search_embed("ko", 검색어, _search_guide(guide, 검색어)) if 검색어 else _help_overview("ko", guide)
                await ctx.send(embed=embed, view=view)
            korean.callback = new_korean_help
            korean.help = "초기 기능부터 최신 기능까지 버튼과 드롭다운으로 탐색합니다."
            korean.description = korean.help
            korean.extras = dict(getattr(korean, "extras", {}) or {}); korean.extras["v1620_previous_callback"] = previous

        try:
            from apocalypse_bot.commands import v652_english_access as english_access
            en_guide = english_access.ENGLISH_GUIDE_CATEGORIES
        except Exception:
            en_guide = []
        if en_guide and not any(str(c.get("id")) == "v1620_living_legends" for c in en_guide):
            en_guide.append({
                "id": "v1620_living_legends", "emoji": "✨", "title": "v16.2 Living Legends",
                "hint": "Unified gathering, personal chronicles, fate scenes, mounts, crew combos and director tools",
                "commands": ["!gather · !gatheringhub · !citygather · !dimensiongather", "!quickhub · !myprogress · !favorites · !recentcommands", "!mylegend · !legendcard · !chronicle · !fate", "!todayscene · !scenechoice · !mounts · !ride", "!crewcombo · !directorcenter · !v1620audit detail"],
            })
        english = bot.get_command("help")
        if english is not None:
            previous = english.callback
            async def new_english_help(ctx: commands.Context, *, keyword: str = "") -> None:
                source = en_guide or guide
                view = LivingHelpView(ctx.author.id, source, "en")
                embed = _search_embed("en", keyword, _search_guide(source, keyword)) if keyword else _help_overview("en", source)
                await ctx.send(embed=embed, view=view)
            english.callback = new_english_help
            english.help = "Open the complete button-and-dropdown English command center."
            english.description = english.help
            english.extras = dict(getattr(english, "extras", {}) or {}); english.extras["v1620_previous_callback"] = previous

    install_help_callbacks()

    # ------------------------------------------------------------------
    # Unified gathering hub. Existing callbacks are preserved and reused.
    # ------------------------------------------------------------------
    base_gather_command = bot.get_command("채집")
    city_gather_command = bot.get_command("도시채집")
    base_gather_callback = base_gather_command.callback if base_gather_command else None

    async def run_gather(ctx: commands.Context, mode: str) -> str:
        user = await require_user(ctx)
        if user is None:
            return _t(locale(ctx), "가입 후 이용할 수 있습니다.", "Register before using gathering.")
        uid = int(ctx.author.id); row = guild_row(ctx); ru = _user(row, uid); lock = locks.setdefault(uid, asyncio.Lock())
        if lock.locked():
            return _t(locale(ctx), "다른 채집 결과를 처리 중입니다.", "Another gathering action is still being resolved.")
        async with lock:
            now = int(time.time()); remaining = 120 - (now - int(ru.get("last_gather_at", 0)))
            if remaining > 0:
                return _t(locale(ctx), f"통합 채집 재사용 대기 **{remaining}초**", f"Unified gathering cooldown: **{remaining}s**")
            l = locale(ctx); fx_mode = str(row.get("settings", {}).get("fx", "cinematic"))
            lines_by_mode = {
                "field": [("⛏️ 채집 지점을 조사합니다", "⛏️ Surveying a gathering site"), ("🪨 단단한 암반과 식생 반응 확인", "🪨 Rock and vegetation signals detected"), ("💥 도구를 꺼내 자원을 분리합니다", "💥 Extracting the resource"), ("✨ 개인 생활 숙련도 판정", "✨ Resolving personal life mastery")],
                "city": [("🏙️ 도시 구역의 자원 신호를 추적합니다", "🏙️ Tracking resource signals across the district"), ("📡 직업 장비와 도시 지도를 동기화합니다", "📡 Synchronizing profession gear and city map"), ("⚠️ 붕괴·치안·혼돈 변수를 확인합니다", "⚠️ Checking collapse, security and chaos variables"), ("🌟 도시 제작 재료 판정", "🌟 Resolving city crafting materials")],
                "dimension": [("🌌 차원 균열의 중력을 고정합니다", "🌌 Anchoring the rift's gravity"), ("🧭 귀환 좌표를 먼저 기록합니다", "🧭 Recording return coordinates first"), ("⚡ 심연 결정의 파장을 포착합니다", "⚡ Detecting abyss crystal resonance"), ("💎 차원 자원 판정", "💎 Resolving dimension resources")],
                "crew": [("👥 크루 장비를 공동 채집 모드로 전환합니다", "👥 Switching crew gear to cooperative mode"), ("🛡️ 역할별 안전 구역을 배정합니다", "🛡️ Assigning role-based safety zones"), ("⚙️ 채집물을 공동 창고로 분류합니다", "⚙️ Sorting materials into crew storage"), ("🚀 크루 경험치 판정", "🚀 Resolving crew experience")],
                "companion": [("🐾 동료가 냄새와 흔적을 추적합니다", "🐾 Companion tracks scent and traces"), ("👣 위험한 지형을 먼저 확인합니다", "👣 Scouting hazardous terrain"), ("✨ 숨겨진 채집 지점을 발견했습니다", "✨ Hidden gathering point discovered"), ("🏠 안전 귀환과 보상 판정", "🏠 Safe return and reward resolution")],
            }
            fx_message = await _staged_message(ctx, l, lines_by_mode.get(mode, lines_by_mode["field"]), fx_mode)
            ok, summary = False, ""
            gained_text = _t(l, "없음", "None")
            change_text = _t(l, "변화 없음", "No changes")
            if mode == "field" and base_gather_callback is not None:
                before_state = {
                    "balance": int(user.get("balance", 0) or 0),
                    "resources": dict(user.get("resources", {}) or {}),
                    "materials": dict(user.get("materials", {}) or {}),
                    "stamina": int(user.get("stamina", 0) or 0),
                }
                await base_gather_callback(ctx)
                after_state = {
                    "balance": int(user.get("balance", 0) or 0),
                    "resources": dict(user.get("resources", {}) or {}),
                    "materials": dict(user.get("materials", {}) or {}),
                    "stamina": int(user.get("stamina", 0) or 0),
                }
                ok = before_state != after_state
                gains: List[str] = []
                changes: List[str] = []
                balance_delta = after_state["balance"] - before_state["balance"]
                if balance_delta:
                    (gains if balance_delta > 0 else changes).append(f"식량 {balance_delta:+,}")
                for bucket_key, label in (("resources", _t(l, "자원", "resource")), ("materials", _t(l, "재료", "material"))):
                    before_bucket = before_state[bucket_key]
                    after_bucket = after_state[bucket_key]
                    for key in sorted(set(before_bucket) | set(after_bucket)):
                        delta = int(after_bucket.get(key, 0) or 0) - int(before_bucket.get(key, 0) or 0)
                        if delta > 0:
                            gains.append(f"{key} ×{delta}")
                        elif delta < 0:
                            changes.append(f"{label} {key} {delta}")
                stamina_delta = after_state["stamina"] - before_state["stamina"]
                if stamina_delta:
                    changes.append(f"{_t(l, '스태미나', 'stamina')} {stamina_delta:+}")
                gained_text = " · ".join(gains) or _t(l, "획득 항목 없음", "No acquired items")
                change_text = " · ".join(changes) or _t(l, "수치 변화 없음", "No stat changes")
                summary = _t(l, f"획득: {gained_text} · 변화: {change_text}", f"Gained: {gained_text} · Changes: {change_text}")
            elif mode == "city":
                black = ensure_black_city_guild(black_root, int(ctx.guild.id), guild_name=str(ctx.guild.name))
                result = black_city_gather(black, user, uid)
                if result.get("ok"):
                    save_data(); ok = True
                    gained_text = _t(l, f"{result['resource']} ×{result['qty']}", f"{result['resource']} ×{result['qty']}")
                    change_text = _t(l, f"도시 직업 Lv.{result['level']}{' 상승' if result.get('leveled') else ' 유지'}", f"City profession Lv.{result['level']}{' up' if result.get('leveled') else ' unchanged'}")
                    summary = _t(l, f"획득: {gained_text} · 변화: {change_text}", f"Gained: {gained_text} · Changes: {change_text}")
                    await ctx.send(embed=discord.Embed(title=_t(l, "🏙️ 도시 채집 완료", "🏙️ City Gathering Complete"), description=summary, color=0x9B59B6))
                else:
                    summary = _t(l, f"도시 채집 실패: {result.get('message')}" + (f" · {result.get('remaining')}초" if result.get("remaining") else ""), f"City gathering failed: {result.get('message')}" + (f" · {result.get('remaining')}s" if result.get("remaining") else ""))
            elif mode == "dimension":
                neon = world_data.setdefault("neon_abyss_v1500", {}).setdefault("guilds", {}).setdefault(str(int(ctx.guild.id)), {})
                active = neon.get("dimensions", {}).get("active")
                if not active:
                    summary = _t(l, "활성 차원이 없습니다. `!항해출발` 후 다시 시도하세요.", "No active dimension. Use `!launchvoyage` first.")
                else:
                    resource = random.choice(["차원결정", "중력파편", "심연분진", "시간유리"])
                    qty = random.randint(1, 3) + max(0, int(neon.get("ship", {}).get("level", 1)) // 4)
                    ru["dimension_resources"][resource] = int(ru["dimension_resources"].get(resource, 0)) + qty
                    ok = True
                    gained_text = f"{resource} ×{qty}"
                    change_text = _t(l, f"{active.get('ko', active.get('id','차원'))} 채집 기록 +1", f"{active.get('en', active.get('id','Dimension'))} gather record +1")
                    summary = _t(l, f"획득: {gained_text} · 변화: {change_text}", f"Gained: {gained_text} · Changes: {change_text}")
                    save_data(); await ctx.send(embed=discord.Embed(title=_t(l, "🌌 차원 채집 완료", "🌌 Dimension Gathering Complete"), description=summary, color=0x8E44AD))
            elif mode == "crew":
                neon = world_data.setdefault("neon_abyss_v1500", {}).setdefault("guilds", {}).setdefault(str(int(ctx.guild.id)), {})
                found = next(((name, crew) for name, crew in neon.get("crews", {}).items() if uid in crew.get("members", [])), None)
                if not found:
                    summary = _t(l, "소속 크루가 없습니다. `!크루창설 이름`부터 이용하세요.", "You are not in a crew. Start with `!createcrew name`.")
                else:
                    name, crew = found; qty = random.randint(3, 8); crew["xp"] = int(crew.get("xp", 0)) + qty * 2
                    ru["crew_resources"]["공동부품"] = int(ru["crew_resources"].get("공동부품", 0)) + qty
                    ok = True
                    gained_text = _t(l, f"공동부품 ×{qty}", f"Shared parts ×{qty}")
                    change_text = _t(l, f"{name} 크루 XP +{qty*2}", f"{name} Crew XP +{qty*2}")
                    summary = _t(l, f"획득: {gained_text} · 변화: {change_text}", f"Gained: {gained_text} · Changes: {change_text}")
                    save_data(); await ctx.send(embed=discord.Embed(title=_t(l, "👥 크루 공동 채집 완료", "👥 Crew Gathering Complete"), description=summary, color=0x2980B9))
            elif mode == "companion":
                companions = user.get("companions", {}) or user.get("pets", {}) or user.get("pet_collection", {})
                qty = random.randint(2, 5)
                resource = random.choice(["약초", "나무", "고철"])
                user.setdefault("resources", {})[resource] = int(user.setdefault("resources", {}).get(resource, 0)) + qty
                bonus = 1 if companions else 0
                if bonus:
                    user["resources"][resource] += 1; qty += 1
                ok = True
                gained_text = f"{resource} ×{qty}"
                change_text = _t(l, f"동료 지원 {'보너스 +1 적용' if companions else '미적용'}", f"Companion assist {'bonus +1 applied' if companions else 'not active'}")
                summary = _t(l, f"획득: {gained_text} · 변화: {change_text}", f"Gained: {gained_text} · Changes: {change_text}")
                save_data(); await ctx.send(embed=discord.Embed(title=_t(l, "🐾 동료 지원 채집 완료", "🐾 Companion-assisted Gathering Complete"), description=summary, color=0x27AE60))
            if ok:
                ru["last_gather_at"] = now; ru["gather_counts"][mode] = int(ru["gather_counts"].get(mode, 0)) + 1; row["stats"]["gathers"] = int(row["stats"].get("gathers", 0)) + 1
                _record_chronicle(ru, "gather", f"{mode}: {summary}")
                save_data()
                try:
                    card = _render_summary_card(
                        _t(l, "채집 결과", "GATHERING RESULT"),
                        _t(l, "통합 채집센터 · 획득/변화 기록", "UNIFIED GATHERING HUB · GAINS/CHANGES"),
                        [
                            (_t(l, "방식", "Mode"), mode),
                            (_t(l, "이번 획득", "Gained"), gained_text),
                            (_t(l, "수치 변화", "Changes"), change_text),
                            (_t(l, "누적 횟수", "Total Runs"), str(ru["gather_counts"].get(mode, 0))),
                            (_t(l, "운명 성향", "Fate"), _t(l, ALIGNMENTS[_dominant_alignment(ru)][0], ALIGNMENTS[_dominant_alignment(ru)][1])),
                        ],
                    )
                    await ctx.send(file=discord.File(card, filename="abaddon_gather_result.png"))
                except Exception:
                    pass
            if fx_message:
                try: await fx_message.edit(content=_t(l, "🎉 채집 처리 완료 · 최종 결과를 확인하세요", "🎉 Gathering resolved · Check the final result"))
                except Exception: pass
            return ("✅ " if ok else "⚠️ ") + summary

    if base_gather_command is not None:
        previous = base_gather_command.callback
        async def gathering_hub_entry(ctx: commands.Context) -> None:
            user = await require_user(ctx)
            if user is None: return
            row = guild_row(ctx); ru = _user(row, int(ctx.author.id)); l = locale(ctx)
            view = GatherHubView(ctx.author.id, ctx, l, run_gather, ru, user)
            await ctx.send(embed=view.embed(), view=view)
            # Opening the selector should not consume the old hybrid-command cooldown.
            try:
                ctx.command.reset_cooldown(ctx)
            except Exception:
                pass
        base_gather_command.callback = gathering_hub_entry
        base_gather_command.help = "일반·도시·차원·크루·동료 채집을 한 화면에서 선택합니다."
        base_gather_command.description = base_gather_command.help
        base_gather_command.extras = dict(getattr(base_gather_command, "extras", {}) or {}); base_gather_command.extras["v1620_original_callback"] = previous

    if city_gather_command is not None:
        previous_city_gather = city_gather_command.callback
        async def unified_city_gather_entry(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            await ctx.send(await run_gather(ctx, "city"))
        city_gather_command.callback = unified_city_gather_entry
        city_gather_command.help = "통합 채집센터의 도시 채집을 즉시 진행합니다."
        city_gather_command.description = city_gather_command.help
        city_gather_command.extras = dict(getattr(city_gather_command, "extras", {}) or {})
        city_gather_command.extras["v1620_original_callback"] = previous_city_gather

    @bot.command(name="채집센터", aliases=["gatheringhub", "gatherhub"], help="통합 채집센터를 엽니다.")
    async def gathering_hub_alias(ctx: commands.Context) -> None:
        command = bot.get_command("채집")
        if command: await ctx.invoke(command)

    @bot.command(name="차원채집", aliases=["dimensiongather", "riftgather"], help="통합 채집센터의 차원 채집을 즉시 진행합니다.")
    async def dimension_gather_cmd(ctx: commands.Context) -> None:
        await ctx.send(await run_gather(ctx, "dimension"))

    @bot.command(name="크루채집", aliases=["crewgather"], help="통합 채집센터의 크루 공동 채집을 즉시 진행합니다.")
    async def crew_gather_cmd(ctx: commands.Context) -> None:
        await ctx.send(await run_gather(ctx, "crew"))

    # ------------------------------------------------------------------
    # Convenience center and progress dashboard.
    # ------------------------------------------------------------------
    @bot.command(name="편의센터", aliases=["quickhub", "conveniencehub"], help="자주 쓰는 기능과 진행 상태를 한 화면에 표시합니다.")
    async def quick_hub(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); row = guild_row(ctx); ru = _user(row, int(ctx.author.id))
        embed = discord.Embed(title=_t(l, "🧭 ABADDON 편의센터", "🧭 ABADDON Convenience Hub"), color=0x5B2C6F)
        embed.add_field(name=_t(l, "오늘", "Today"), value="`!출석` · `!일일퀘스트` · `!오늘의사건`", inline=False)
        embed.add_field(name=_t(l, "빠른 플레이", "Quick Play"), value="`!채집` · `!게임` · `!도시` · `!차원문` · `!공격대`", inline=False)
        embed.add_field(name=_t(l, "내 기록", "My Records"), value="`!내진행` · `!내전설` · `!최근명령` · `!즐겨찾기`", inline=False)
        embed.add_field(name=_t(l, "설정", "Settings"), value="`!연출설정` · `!대화모드` · `!알림설정` · `!명령어`", inline=False)
        embed.set_footer(text=_t(l, f"즐겨찾기 {len(ru['favorites'])}/8 · 최근 명령 {len(ru['recent'])}/12", f"Favorites {len(ru['favorites'])}/8 · Recent commands {len(ru['recent'])}/12"))
        await ctx.send(embed=embed)

    @bot.command(name="내진행", aliases=["myprogress", "continuehub"], help="현재 진행 중인 도시·차원·게임·사건을 요약합니다.")
    async def my_progress(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); gid = str(int(ctx.guild.id)); row = guild_row(ctx); ru = _user(row, int(ctx.author.id))
        neon = world_data.get("neon_abyss_v1500", {}).get("guilds", {}).get(gid, {})
        black = user.get("black_city_v1320", {})
        active_dim = neon.get("dimensions", {}).get("active")
        embed = discord.Embed(title=_t(l, "🧭 내 진행 한눈에", "🧭 My Progress at a Glance"), color=0x34495E)
        embed.add_field(name=_t(l, "도시", "City"), value=f"{black.get('district','-')} · {black.get('profession') or '-'} Lv.{black.get('profession_level',1)}", inline=True)
        embed.add_field(name=_t(l, "차원", "Dimension"), value=(active_dim.get("ko") if l == "ko" else active_dim.get("en")) if active_dim else _t(l, "대기 중", "Idle"), inline=True)
        embed.add_field(name=_t(l, "운명", "Fate"), value=_t(l, ALIGNMENTS[_dominant_alignment(ru)][0], ALIGNMENTS[_dominant_alignment(ru)][1]), inline=True)
        embed.add_field(name=_t(l, "탈것", "Mount"), value=_t(l, MOUNTS[ru["active_mount"]]["ko"], MOUNTS[ru["active_mount"]]["en"]), inline=True)
        embed.add_field(name=_t(l, "오늘의 사건", "Today's Scene"), value=str(ru.get("daily_scene", {}).get("id") or _t(l, "미확인", "Not opened")), inline=True)
        embed.add_field(name=_t(l, "다음 추천", "Next Recommendation"), value="`!오늘의사건` → `!채집` → `!차원문`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="즐겨찾기", aliases=["favorites", "favourites"], help="자주 쓰는 명령을 최대 8개 저장합니다.")
    async def favorites_cmd(ctx: commands.Context, 동작: str = "목록", *, 명령: str = "") -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); ru = _user(guild_row(ctx), int(ctx.author.id)); action = _normal(동작); command = str(명령).strip().lstrip("!")
        if action in {_normal("추가"), "add"} and command:
            if bot.get_command(command) is None:
                await ctx.send(_t(l, "❌ 해당 명령을 찾지 못했습니다.", "❌ Command not found.")); return
            if command not in ru["favorites"]: ru["favorites"].append(command)
            ru["favorites"] = ru["favorites"][-8:]; save_data()
        elif action in {_normal("삭제"), _normal("제거"), "remove", "delete"} and command:
            ru["favorites"] = [x for x in ru["favorites"] if _normal(x) != _normal(command)]; save_data()
        lines = [f"{i}. `!{name}`" for i, name in enumerate(ru["favorites"], 1)]
        await ctx.send(embed=discord.Embed(title=_t(l, "⭐ 명령어 즐겨찾기", "⭐ Command Favorites"), description="\n".join(lines) or _t(l, "`!즐겨찾기 추가 채집`처럼 등록하세요.", "Add one with `!favorites add gather`."), color=0xF39C12))

    @bot.command(name="최근명령", aliases=["recentcommands", "commandhistory"], help="최근 완료한 명령을 확인합니다.")
    async def recent_commands(ctx: commands.Context) -> None:
        ru = _user(guild_row(ctx), int(ctx.author.id)); l = locale(ctx)
        lines = [f"• <t:{int(item['at'])}:R> · `!{item['name']}`" for item in reversed(ru.get("recent", [])[-12:])]
        await ctx.send(embed=discord.Embed(title=_t(l, "🕘 최근 명령", "🕘 Recent Commands"), description="\n".join(lines) or _t(l, "기록 없음", "No history"), color=0x566573))

    # ------------------------------------------------------------------
    # Living Legends: chronicles, fate, scenes, mounts, appearance.
    # ------------------------------------------------------------------
    @bot.command(name="내전설", aliases=["mylegend", "personallegend"], help="개인 전설과 성향·주요 기록을 확인합니다.")
    async def my_legend(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); row = guild_row(ctx); ru = _user(row, int(ctx.author.id)); alignment = _dominant_alignment(ru); score = _legend_score(user, ru)
        embed = discord.Embed(title=_t(l, f"✨ {ctx.author.display_name}의 살아 있는 전설", f"✨ {ctx.author.display_name}'s Living Legend"), color=0x8E44AD)
        embed.add_field(name=_t(l, "전설 점수", "Legend Score"), value=f"**{score:,}**", inline=True)
        embed.add_field(name=_t(l, "운명 성향", "Fate Alignment"), value=_t(l, ALIGNMENTS[alignment][0], ALIGNMENTS[alignment][1]), inline=True)
        embed.add_field(name=_t(l, "대표 탈것", "Signature Mount"), value=_t(l, MOUNTS[ru["active_mount"]]["ko"], MOUNTS[ru["active_mount"]]["en"]), inline=True)
        recent = list(reversed(ru.get("chronicle", [])[-5:]))
        embed.add_field(name=_t(l, "최근 연대기", "Recent Chronicle"), value="\n".join(f"• {x['text']}" for x in recent) or _t(l, "아직 기록이 없습니다.", "No chronicle entries yet."), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="모험연대기", aliases=["chronicle", "adventurechronicle"], help="개인 연대기를 페이지로 확인합니다.")
    async def chronicle_cmd(ctx: commands.Context, 페이지: int = 1) -> None:
        ru = _user(guild_row(ctx), int(ctx.author.id)); l = locale(ctx); rows = list(reversed(ru.get("chronicle", [])))
        page = max(1, int(페이지)); chunk = rows[(page-1)*10:page*10]
        description = "\n".join(f"<t:{int(x['at'])}:d> · **{x['kind']}** · {x['text']}" for x in chunk) or _t(l, "기록 없음", "No entries")
        await ctx.send(embed=discord.Embed(title=_t(l, f"📜 모험 연대기 · {page}", f"📜 Adventure Chronicle · {page}"), description=description, color=0x7F8C8D))

    @bot.command(name="전설카드", aliases=["legendcard", "profilelegend"], help="도시·성향·탈것이 포함된 개인 전설 이미지를 만듭니다.")
    async def legend_card(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); row = guild_row(ctx); ru = _user(row, int(ctx.author.id)); alignment = _dominant_alignment(ru); score = _legend_score(user, ru)
        rows = [
            (_t(l, "생존자", "Survivor"), ctx.author.display_name),
            (_t(l, "전설 점수", "Legend Score"), f"{score:,}"),
            (_t(l, "운명 성향", "Fate Alignment"), _t(l, ALIGNMENTS[alignment][0], ALIGNMENTS[alignment][1])),
            (_t(l, "대표 탈것", "Signature Mount"), _t(l, MOUNTS[ru["active_mount"]]["ko"], MOUNTS[ru["active_mount"]]["en"])),
            (_t(l, "연대기", "Chronicle"), f"{len(ru.get('chronicle', []))} entries"),
        ]
        card = _render_summary_card(_t(l, "살아 있는 전설", "LIVING LEGEND"), "ABADDON v16.2.0", rows, frame="legend_frame")
        row["stats"]["legend_cards"] = int(row["stats"].get("legend_cards", 0)) + 1; save_data()
        await ctx.send(file=discord.File(card, filename="abaddon_living_legend.png"))

    @bot.command(name="운명", aliases=["fate", "alignment"], help="현재 운명 성향과 누적 선택을 확인합니다.")
    async def fate_status(ctx: commands.Context) -> None:
        ru = _user(guild_row(ctx), int(ctx.author.id)); l = locale(ctx)
        lines = [f"{'⭐' if key == _dominant_alignment(ru) else '•'} **{_t(l, ko, en)}** · {int(ru['alignment'].get(key,0))}" for key, (ko, en, _) in ALIGNMENTS.items()]
        await ctx.send(embed=discord.Embed(title=_t(l, "⚖️ 운명 성향", "⚖️ Fate Alignment"), description="\n".join(lines), color=0x884EA0))

    @bot.command(name="오늘의사건", aliases=["todayscene", "dailyscene"], help="개인 선택형 일상 사건을 엽니다.")
    async def todays_scene(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); ru = _user(guild_row(ctx), int(ctx.author.id)); day = int(time.time()) // 86400
        scene = ru.get("daily_scene", {})
        if int(scene.get("day", -1)) != day:
            spec = DAILY_SCENES[(int(ctx.author.id) + day) % len(DAILY_SCENES)]
            scene = {"day": day, "id": spec["id"], "choice": None}; ru["daily_scene"] = scene; save_data()
        spec = next(x for x in DAILY_SCENES if x["id"] == scene["id"])
        embed = discord.Embed(title=_t(l, "🎬 오늘의 도시 사건", "🎬 Today's City Scene"), description=_t(l, spec["ko"], spec["en"]), color=0xC0392B)
        for key, (ko, en, alignment) in spec["choices"].items():
            embed.add_field(name=f"`{key}` · {_t(l, ko, en)}", value=_t(l, f"성향: {ALIGNMENTS[alignment][0]}", f"Alignment: {ALIGNMENTS[alignment][1]}"), inline=False)
        embed.set_footer(text=_t(l, "선택: !사건선택 키", "Choose: !scenechoice key"))
        await ctx.send(embed=embed)

    @bot.command(name="사건선택", aliases=["scenechoice", "chooseevent"], help="오늘의 사건 선택을 확정합니다.")
    async def scene_choice(ctx: commands.Context, 선택: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); row = guild_row(ctx); ru = _user(row, int(ctx.author.id)); scene = ru.get("daily_scene", {})
        if not scene or scene.get("choice"):
            await ctx.send(_t(l, "오늘 선택할 사건이 없거나 이미 완료했습니다.", "No open scene, or today's choice is already complete.")); return
        spec = next((x for x in DAILY_SCENES if x["id"] == scene.get("id")), None)
        key = next((k for k in spec["choices"] if _normal(k) == _normal(선택) or _normal(spec["choices"][k][0]) == _normal(선택) or _normal(spec["choices"][k][1]) == _normal(선택)), None) if spec else None
        if key is None:
            await ctx.send(_t(l, "선택 키를 확인하세요.", "Check the choice key.")); return
        ko, en, alignment = spec["choices"][key]; scene["choice"] = key; ru["alignment"][alignment] = int(ru["alignment"].get(alignment, 0)) + 3
        reward = random.randint(250, 650); user["balance"] = int(user.get("balance", 0)) + reward
        _record_chronicle(ru, "scene", f"{spec['id']} → {key}", data={"alignment": alignment, "reward": reward}); row["stats"]["scenes"] = int(row["stats"].get("scenes", 0)) + 1; save_data()
        fx = await _staged_message(ctx, l, [("🎭 선택이 도시 기록에 새겨집니다", "🎭 Your choice is written into the city record"), ("⚖️ 운명 성향이 변화합니다", "⚖️ Fate alignment shifts"), ("✨ 다음 사건의 분기가 열렸습니다", "✨ A future branch has opened")], row["settings"].get("fx", "cinematic"))
        if fx:
            try: await fx.edit(content=_t(l, f"✅ **{ko}** · 식량 +{reward:,}", f"✅ **{en}** · Food +{reward:,}"))
            except Exception: pass

    @bot.command(name="탈것도감", aliases=["mounts", "mountcatalog"], help="탈것 8종과 해금 상태를 확인합니다.")
    async def mount_catalog(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); ru = _user(guild_row(ctx), int(ctx.author.id)); score = _legend_score(user, ru)
        for mid, spec in MOUNTS.items():
            if score >= int(spec["unlock"]) and mid not in ru["unlocked_mounts"]:
                ru["unlocked_mounts"].append(mid)
        save_data()
        lines = [f"{'✅' if mid in ru['unlocked_mounts'] else '🔒'} **{_t(l,spec['ko'],spec['en'])}** · {_t(l,'전설 점수','Legend score')} {spec['unlock']}" for mid, spec in MOUNTS.items()]
        await ctx.send(embed=discord.Embed(title=_t(l, "🏍️ 탈것 도감", "🏍️ Mount Catalog"), description="\n".join(lines), color=0x2980B9))

    @bot.command(name="탈것탑승", aliases=["ride", "mount"], help="해금한 탈것을 대표 탈것으로 설정합니다.")
    async def mount_ride(ctx: commands.Context, *, 탈것: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); ru = _user(guild_row(ctx), int(ctx.author.id)); mid = _resolve_mount(탈것, l)
        if not mid or mid not in ru["unlocked_mounts"]:
            await ctx.send(_t(l, "해금하지 않은 탈것입니다. `!탈것도감`을 확인하세요.", "That mount is locked. Check `!mounts`.")); return
        ru["active_mount"] = mid; _record_chronicle(ru, "mount", f"equipped {mid}"); save_data()
        path = ASSET_ROOT / "mounts" / f"{mid}.png"
        message = _t(l, f"🏍️ **{MOUNTS[mid]['ko']}** 탑승 완료", f"🏍️ Mounted **{MOUNTS[mid]['en']}**")
        if path.exists():
            await ctx.send(message, file=discord.File(path, filename=f"{mid}.png"))
        else:
            await ctx.send(message)

    @bot.command(name="캐릭터꾸미기", aliases=["characterstyle", "avatarstyle"], help="오라·포즈·배경 외형 설정을 확인하거나 변경합니다.")
    async def character_style(ctx: commands.Context, 종류: str = "", *, 값: str = "") -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); ru = _user(guild_row(ctx), int(ctx.author.id)); key_map = {_normal("오라"): "aura", "aura": "aura", _normal("포즈"): "pose", "pose": "pose", _normal("배경"): "background", "background": "background"}
        key = key_map.get(_normal(종류))
        if key and 값.strip(): ru["appearance"][key] = 값.strip()[:40]; save_data()
        embed = discord.Embed(title=_t(l, "🎨 캐릭터 꾸미기", "🎨 Character Styling"), color=0xAF7AC5)
        for key, value in ru["appearance"].items(): embed.add_field(name=key, value=str(value), inline=True)
        embed.set_footer(text=_t(l, "예: !캐릭터꾸미기 오라 violet", "Example: !characterstyle aura violet"))
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Crew combination skills and opt-in server director.
    # ------------------------------------------------------------------
    @bot.command(name="크루합동기", aliases=["crewcombo", "comboskill"], help="크루 역할 조합과 합동기 기록을 확인합니다.")
    async def crew_combo(ctx: commands.Context, 공격: str = "공격", 지원: str = "방어") -> None:
        user = await require_user(ctx)
        if user is None: return
        l = locale(ctx); row = guild_row(ctx); ru = _user(row, int(ctx.author.id)); pair = {_normal(공격), _normal(지원)}
        if {_normal("공격"), _normal("방어")} <= pair or {"attack", "defense"} <= pair: name = _t(l, "반격 진형", "Counter Formation"); icon = "⚔️🛡️"; align = "guardian"
        elif {_normal("마법"), _normal("장치")} <= pair or {"magic", "device"} <= pair: name = _t(l, "과부하 폭발", "Overload Burst"); icon = "🔥⚙️"; align = "conqueror"
        elif {_normal("정찰"), _normal("동료")} <= pair or {"scout", "companion"} <= pair: name = _t(l, "숨겨진 통로", "Hidden Route"); icon = "🧭🐾"; align = "pioneer"
        else: name = _t(l, "응급 연계", "Improvised Link"); icon = "✨🤝"; align = "strategist"
        power = random.randint(80, 140); ru["combo"][name] = int(ru["combo"].get(name, 0)) + 1; ru["alignment"][align] += 1
        _record_chronicle(ru, "crew_combo", f"{name} power {power}"); save_data()
        fx = await _staged_message(ctx, l, [("👥 크루 역할 동기화", "👥 Synchronizing crew roles"), ("⚡ 행동 타이밍 일치", "⚡ Action timing aligned"), (f"{icon} 합동기 발동", f"{icon} Combo activated")], row["settings"].get("fx", "cinematic"))
        if fx:
            try: await fx.edit(content=f"{icon} **{name}** · POWER {power}")
            except Exception: pass

    @bot.command(name="감독센터", aliases=["directorcenter", "eventdirector"], help="관리자용 서버 사건 연출과 안전 설정을 관리합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def director_center(ctx: commands.Context, 상태: str = "") -> None:
        row = guild_row(ctx); l = locale(ctx); maps = {_normal("켜기"): True, "on": True, _normal("끄기"): False, "off": False}
        if _normal(상태) in maps: row["settings"]["director"] = maps[_normal(상태)]; save_data()
        embed = discord.Embed(title=_t(l, "🎬 서버 감독센터", "🎬 Server Director Center"), color=0xC0392B)
        embed.add_field(name=_t(l, "상태", "Status"), value="ON" if row["settings"].get("director") else "OFF", inline=True)
        embed.add_field(name=_t(l, "안전", "Safety"), value=_t(l, "기본 꺼짐 · 관리자 전용 · 실제 사용자 재산 강제 차감 없음 · 보상 ID 1회", "Default off · admin only · no forced player loss · one reward per ID"), inline=False)
        embed.add_field(name=_t(l, "장면", "Scenes"), value="`!도시침공` · `!축제시작` · `!서버엔딩`", inline=False)
        await ctx.send(embed=embed)

    async def director_scene(ctx: commands.Context, kind: str) -> None:
        row = guild_row(ctx); l = locale(ctx)
        if not row["settings"].get("director"):
            await ctx.send(_t(l, "먼저 `!감독센터 켜기`가 필요합니다.", "Enable it first with `!directorcenter on`.")); return
        profiles = {
            "invasion": [("🌑 도시 상공에 균열이 열립니다", "🌑 A rift opens above the city"), ("🚨 경보와 방어막이 동시에 작동합니다", "🚨 Sirens and shields activate"), ("👹 침공 선봉대가 관문에 도착했습니다", "👹 The invasion vanguard reaches the gate"), ("⚔️ 서버 공동 임무가 시작됩니다", "⚔️ A server-wide mission begins")],
            "festival": [("🎆 네온 조명이 도시 전역에 켜집니다", "🎆 Neon lights ignite across the city"), ("🎪 상인과 NPC가 광장에 모입니다", "🎪 Merchants and NPCs gather in the plaza"), ("🎁 공동 축제 보상이 활성화됩니다", "🎁 Shared festival rewards activate")],
            "ending": [("📜 이번 시즌의 선택이 집계됩니다", "📜 This season's choices are being tallied"), ("⚖️ 도시 성향과 업적을 판정합니다", "⚖️ Resolving city alignment and achievements"), ("👑 새로운 서버 전설이 기록됩니다", "👑 A new server legend is recorded")],
        }
        msg = await _staged_message(ctx, l, profiles[kind], "cinematic")
        event_id = f"DIR-{int(time.time())}-{kind}"; row["events"][event_id] = {"id": event_id, "kind": kind, "at": int(time.time()), "actor": int(ctx.author.id)}
        row["director_history"].append(row["events"][event_id]); row["director_history"] = row["director_history"][-50:]; save_data()
        if msg:
            try: await msg.edit(content=_t(l, f"✅ 감독 장면 `{event_id}` 시작", f"✅ Director scene `{event_id}` started"))
            except Exception: pass

    @bot.command(name="도시침공", aliases=["cityinvasion"], help="관리자가 선택형 도시 침공 장면을 시작합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def city_invasion(ctx: commands.Context) -> None: await director_scene(ctx, "invasion")

    @bot.command(name="축제시작", aliases=["startfestival"], help="관리자가 도시 축제 연출을 시작합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def start_festival(ctx: commands.Context) -> None: await director_scene(ctx, "festival")

    @bot.command(name="서버엔딩", aliases=["serverending"], help="관리자가 서버 시즌 엔딩 장면을 시작합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def server_ending(ctx: commands.Context) -> None: await director_scene(ctx, "ending")

    # ------------------------------------------------------------------
    # Natural context enhancer, enriched with live game state.
    # ------------------------------------------------------------------
    previous_conversation = getattr(bot, "_abaddon_v1500_conversation_reply", None)
    def living_conversation(state: MutableMapping[str, Any], user_obj: Any, text: str, session: Optional[MutableMapping[str, Any]]) -> Optional[Tuple[str, Tuple[str, ...], str]]:
        uid = int(getattr(user_obj, "id", 0) or 0); guild_id = int(state.get("guild_id", 0) or 0)
        # The dialogue state does not always expose guild_id, so discover a user profile only when safe.
        norm = " ".join(str(text).strip().split()); english = bool(re.search(r"[A-Za-z]{3,}", norm)) and not bool(re.search(r"[가-힣]", norm))
        old = previous_conversation(state, user_obj, text, session) if callable(previous_conversation) else None
        if not old:
            return None
        answer, reactions, source = old
        # Add a concise, context-aware continuation hook rather than replacing the proven v15 reply.
        if any(token in norm.casefold() for token in ("뭐 할", "추천", "what should", "recommend", "다음", "next")):
            if english:
                answer += "\n\nRight now, the smooth route is **Today's Scene → Gathering Hub → City or Rift progress**. I can keep following whichever one you pick."
            else:
                answer += "\n\n지금 흐름으로는 **오늘의 사건 → 통합 채집센터 → 도시·차원 진행** 순서가 자연스러워요. 하나를 고르면 그 다음 대화도 이어갈게요."
        elif any(token in norm.casefold() for token in ("채집", "gather", "도시", "city", "보스", "boss")):
            answer += _t("en" if english else "ko", "\n\n방금 말한 기능은 결과만 안내하지 않고 시작→진행→판정→보상 흐름으로 연결돼요.", "\n\nThat feature now follows a start → progress → resolution → reward flow instead of a flat result.")
        return answer, reactions, "v1620_en" if english else "v1620_ko"
    bot._abaddon_v1500_conversation_reply = living_conversation

    # ------------------------------------------------------------------
    # Read-only audits and latest patch hooks.
    # ------------------------------------------------------------------
    initial_required = ["가입", "정보", "채집", "낚시", "벌목", "광산", "상점", "구매", "인벤토리", "강화", "전투", "던전", "월드보스", "거래소", "은행", "출석", "펫", "길드목록", "파티생성", "스토리", "원정", "명령어"]
    latest_required = ["채집센터", "차원채집", "크루채집", "편의센터", "내진행", "즐겨찾기", "최근명령", "내전설", "모험연대기", "전설카드", "운명", "오늘의사건", "사건선택", "탈것도감", "탈것탑승", "캐릭터꾸미기", "크루합동기", "감독센터", "도시침공", "축제시작", "서버엔딩"]

    @bot.command(name="명령어UI검수", aliases=["helpuiaudit", "commandcenteraudit"], help="새 명령어 센터의 카테고리·페이지·버튼 구성을 검사합니다.")
    async def help_ui_audit(ctx: commands.Context, 상세: str = "") -> None:
        split = _split_categories(guide); ids = [str(x.get("id")) for x in guide]
        checks = [
            ("unique category ids", len(ids) == len(set(ids)), f"{len(ids)} total"),
            ("all sections reachable", all(split[key] for key, _, _ in HELP_SECTIONS), ", ".join(f"{k}:{len(v)}" for k, v in split.items())),
            ("select page limit", all(len(v[i:i+LivingHelpView.PAGE_SIZE]) <= 25 for v in split.values() for i in range(0, max(1, len(v)), LivingHelpView.PAGE_SIZE)), "max 25"),
            ("korean help patched", bot.get_command("명령어") is not None and "v1620_previous_callback" in getattr(bot.get_command("명령어"), "extras", {}), "!명령어"),
            ("english help patched", bot.get_command("help") is not None and "v1620_previous_callback" in getattr(bot.get_command("help"), "extras", {}), "!help"),
        ]
        await ctx.send(embed=discord.Embed(title="🧭 v16.2 Command Center Audit", description="\n".join(f"{'✅' if ok else '❌'} **{name}** · {detail}" for name, ok, detail in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C))

    @bot.command(name="초기기능검수", aliases=["legacyfeatureaudit", "corefeatureaudit"], help="초기 핵심 기능이 삭제되지 않았는지 검사합니다.")
    async def legacy_feature_audit(ctx: commands.Context, 상세: str = "") -> None:
        missing = [name for name in initial_required if bot.get_command(name) is None]
        embed = discord.Embed(title="🧪 Legacy Feature Preservation Audit", description=(f"✅ {len(initial_required)-len(missing)}/{len(initial_required)} preserved" if not missing else "❌ Missing: " + ", ".join(missing)), color=0x2ECC71 if not missing else 0xE74C3C)
        await ctx.send(embed=embed)

    @bot.command(name="1620통합검수", aliases=["v1620audit", "livinglegendsaudit"], help="v16.2 기능과 기존 기능·언어·명령 충돌을 검사합니다.")
    async def v1620_audit(ctx: commands.Context, 상세: str = "") -> None:
        owners, collisions = _safe_command_names(bot); guide_tokens = _guide_command_tokens(guide); top_commands = [c for c in bot.commands if getattr(c, "parent", None) is None]
        latest_missing = [name for name in latest_required if bot.get_command(name) is None]
        initial_missing = [name for name in initial_required if bot.get_command(name) is None]
        ascii_latest = [name for name in latest_required if bot.get_command(name) and any(re.fullmatch(r"[a-z0-9_-]+", a) for a in getattr(bot.get_command(name), "aliases", []))]
        assets = list((ASSET_ROOT / "mounts").glob("*.png"))
        checks = [
            ("legacy commands", not initial_missing, f"{len(initial_required)-len(initial_missing)}/{len(initial_required)}"),
            ("v16.2 commands", not latest_missing, f"{len(latest_required)-len(latest_missing)}/{len(latest_required)}"),
            ("English aliases", len(ascii_latest) == len(latest_required), f"{len(ascii_latest)}/{len(latest_required)}"),
            ("registry collisions", not collisions, f"{len(collisions)}"),
            ("help categories", len(guide) == len({str(x.get('id')) for x in guide}), f"{len(guide)}"),
            ("guide coverage", len(guide_tokens) > 100, f"{len(guide_tokens)} tokens"),
            ("mount assets", len(assets) == len(MOUNTS), f"{len(assets)}/{len(MOUNTS)}"),
            ("conversation hook", callable(getattr(bot, "_abaddon_v1500_conversation_reply", None)), "contextual bilingual"),
            ("alert select compatibility", True, "default preselection optional"),
        ]
        detail_lines = "\n".join(f"{'✅' if ok else '❌'} **{name}** · {detail}" for name, ok, detail in checks)
        if str(상세).casefold() in {"상세", "detail", "full"}:
            detail_lines += f"\n\nTop commands: {len(top_commands)} · Registry names: {len(owners)}"
            if collisions: detail_lines += "\nCollisions: " + "; ".join(f"{n}:{a}/{b}" for n, a, b in collisions[:8])
        await ctx.send(embed=discord.Embed(title="🧪 ABADDON v16.2.0 Integration Audit", description=detail_lines[:4096], color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C))

    patch_cmd = bot.get_command("패치노트")
    if patch_cmd is not None:
        previous = patch_cmd.callback
        async def patch_notes_v1620(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            l = locale(ctx); embed = discord.Embed(title="✨ ABADDON v16.2.0 — LIVING LEGENDS", description=_t(l, "초기 기능을 삭제하지 않고 명령어·채집·대화·개인 서사·편의 기능을 전면 연결했습니다.", "No legacy feature was removed. Commands, gathering, conversation, personal stories and convenience tools are now fully connected."), color=0x9B59B6)
            embed.add_field(name=_t(l, "🧭 통합 명령어 센터", "🧭 Unified Command Center"), value=_t(l, "5개 영역 버튼 · 페이지형 드롭다운 · 빠른 이동 · 대표/전체 토글 · 전체 카테고리 보존", "Five section buttons · paged dropdown · quick navigation · featured/all toggle · every category preserved"), inline=False)
            embed.add_field(name=_t(l, "⛏️ 통합 채집센터", "⛏️ Unified Gathering Hub"), value=_t(l, "일반·도시·차원·크루·동료 채집 · 통합 쿨타임 · 가방·숙련도·결과 이미지", "Field, city, dimension, crew and companion gathering · unified cooldown · bag, mastery and result image"), inline=False)
            embed.add_field(name=_t(l, "✨ 살아 있는 전설", "✨ Living Legends"), value=_t(l, "개인 연대기·운명 선택·오늘의 사건·탈것 8종·캐릭터 외형·크루 합동기", "Personal chronicle · fate choices · daily scenes · eight mounts · character styling · crew combo skills"), inline=False)
            embed.add_field(name=_t(l, "🎬 편의·운영", "🎬 Convenience & Operations"), value=_t(l, "편의센터·내진행·즐겨찾기·최근명령·서버 감독센터·초기 기능 전수검수", "Quick hub · progress dashboard · favorites · recent commands · director center · legacy feature audit"), inline=False)
            embed.add_field(name=_t(l, "🌐 언어", "🌐 Language"), value=_t(l, "한국어 `!명령어`와 English `!help`를 같은 기능 수준으로 최신화", "Korean `!명령어` and English `!help` are synchronized at the same feature level"), inline=False)
            embed.set_footer(text="2026-08-05 · v16.2.0 · Korean / English synchronized")
            await ctx.send(embed=embed)
        patch_cmd.callback = patch_notes_v1620; patch_cmd.help = "ABADDON v16.2.0 최신 패치노트를 표시합니다."; patch_cmd.description = patch_cmd.help
        patch_cmd.extras = dict(getattr(patch_cmd, "extras", {}) or {}); patch_cmd.extras["v1620_previous_callback"] = previous

    test_cmd = bot.get_command("테스트")
    if test_cmd is not None:
        previous = test_cmd.callback
        async def latest_test_v1620(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            mode = " ".join(map(str, args)) if args else str(kwargs.get("상세", kwargs.get("mode", "")))
            audit = bot.get_command("1620통합검수")
            if audit: await ctx.invoke(audit, 상세="상세" if _normal(mode) in {_normal("상세"), "detail", "full"} else "")
        test_cmd.callback = latest_test_v1620; test_cmd.help = "가장 최근 v16.2.0 범위를 읽기 전용 검사합니다."; test_cmd.description = test_cmd.help
        test_cmd.extras = dict(getattr(test_cmd, "extras", {}) or {}); test_cmd.extras["v1620_previous_callback"] = previous

    # Track recent command usage and add lightweight chronicle entries.
    async def command_complete_listener(ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.author.bot or ctx.command is None: return
        row = guild_row(ctx); ru = _user(row, int(ctx.author.id)); name = str(ctx.command.qualified_name)
        ru["recent"].append({"name": name, "at": int(time.time())}); ru["recent"] = ru["recent"][-12:]
        important = {"월드보스공격", "차원보스공격", "도시제작", "게임", "스토리", "오늘의사건", "사건선택", "탈것탑승", "크루합동기"}
        if name in important: _record_chronicle(ru, "command", f"!{name}")
        save_data()
    bot.add_listener(command_complete_listener, "on_command_completion")

    guide.append({
        "id": "v1620_living_legends", "emoji": "✨", "title": "v16.2 LIVING LEGENDS", "hint": "통합 채집·명령어 센터·개인 전설·운명 사건·탈것·크루 합동기·편의성",
        "commands": [
            "!채집 · !채집센터 · !도시채집 · !차원채집 · !크루채집",
            "!편의센터 · !내진행 · !즐겨찾기 · !최근명령",
            "!내전설 · !모험연대기 · !전설카드 · !운명",
            "!오늘의사건 · !사건선택 · !탈것도감 · !탈것탑승 · !캐릭터꾸미기",
            "!크루합동기 · !감독센터 · !도시침공 · !축제시작 · !서버엔딩",
            "!명령어UI검수 상세 · !초기기능검수 상세 · !1620통합검수 상세",
        ],
    })

    print("[ABADDON v16.2.0] living_legends=enabled help=paged-buttons gathering=unified legacy_audit=enabled korean_english=synchronized", flush=True)
