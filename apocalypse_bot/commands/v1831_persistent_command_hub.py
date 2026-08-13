from __future__ import annotations

"""ABADDON v18.3.1 persistent command hub.

Replaces the mutation-heavy public !명령어 / !버튼 command centre with a
simpler persistent navigation model:

* a small, stateless persistent root menu;
* top-level category -> feature group -> command, so newcomers are not shown a
  wall of hundreds of commands;
* every persistent button/select has an explicit deterministic custom_id and
  timeout=None;
* page changes replace the View with a fresh deterministic View instead of
  clear_items()/remove_item() mutation;
* the registry is rebuilt from bot.walk_commands() whenever the hub is opened,
  keeping the catalogue aligned with commands added by later patches;
* group/page persistent views are pre-registered at startup so messages created
  by this version keep dispatching after a Render restart/redeploy.

Search result panels and argument modals are intentionally short-lived personal
UI. The permanent navigation surface itself is persistent.
"""

from dataclasses import dataclass
import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _command_requires_input, _invoke_command
from apocalypse_bot.commands.v1630_core_rpg_command_city_overhaul import (
    CommandEntry,
    GROUP_SPECS,
    SECTION_SPECS,
    _build_registry,
    _group_spec,
    _short,
)

VERSION = "18.6.0"
PREFIX = "abaddon:v1831"
PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Registry / catalogue helpers
# ---------------------------------------------------------------------------


def _refresh_registry(bot: commands.Bot) -> List[CommandEntry]:
    """Rebuild the canonical prefix-command registry from the live Bot."""
    rows = list(_build_registry(bot))
    setattr(bot, "v1630_command_entries", rows)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in rows})
    setattr(bot, "v1831_command_entries", rows)
    return rows


def _visible_entries(bot: commands.Bot) -> List[CommandEntry]:
    rows = _refresh_registry(bot)
    visible: List[CommandEntry] = []
    for entry in rows:
        cmd = bot.get_command(entry.qualified_name)
        if cmd is None:
            continue
        # Developer regression/owner diagnostics were intentionally hidden in
        # the production-cleanup patch. Do not leak them into the newcomer UI.
        if bool(getattr(cmd, "hidden", False)):
            continue
        visible.append(entry)
    return visible


def _rows_for(entries: Sequence[CommandEntry], section: str, group: str) -> List[CommandEntry]:
    return [e for e in entries if e.section == section and e.group == group]


def _group_counts(entries: Sequence[CommandEntry], section: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for entry in entries:
        if entry.section == section:
            out[entry.group] = out.get(entry.group, 0) + 1
    return out


def _groups_for(entries: Sequence[CommandEntry], section: str) -> List[Tuple[str, str, str, str, str, str]]:
    counts = _group_counts(entries, section)
    rows: List[Tuple[str, str, str, str, str, str]] = []
    known: set[str] = set()
    for spec in GROUP_SPECS.get(section, ()):
        key = spec[0]
        if counts.get(key, 0) > 0:
            rows.append(spec)
            known.add(key)
    # Keep genuinely preserved/unclassified commands reachable instead of
    # silently disappearing from the complete catalogue.
    leftovers = sorted(k for k, count in counts.items() if count > 0 and k not in known)
    for key in leftovers:
        sec, ko, en, dko, den, emoji = _group_spec(key)
        rows.append((key, ko, en, dko, den, emoji))
    return rows


def _first_group(entries: Sequence[CommandEntry], section: str, preferred: str = "") -> str:
    groups = _groups_for(entries, section)
    keys = [g[0] for g in groups]
    if preferred and preferred in keys:
        return preferred
    if section == "main" and "story1" in keys:
        return "story1"
    return keys[0] if keys else "legacy"


def _section_meta(section: str) -> Tuple[str, str, str, str]:
    for row in SECTION_SPECS:
        if row[0] == section:
            return row
    return (section, section, section, "")


def _public_command_count(entries: Sequence[CommandEntry]) -> int:
    return len(entries)


def _trim_help(entry: CommandEntry, limit: int = 78) -> str:
    text = " ".join(str(entry.help_text or "설명 없음").split())
    return _short(text, limit)


def _page_count(rows: Sequence[Any]) -> int:
    return max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)


def _clamp_page(rows: Sequence[Any], page: int) -> int:
    return max(0, min(int(page), _page_count(rows) - 1))


# ---------------------------------------------------------------------------
# Embeds - deliberately compact for first-time users
# ---------------------------------------------------------------------------


def _root_embed(entries: Sequence[CommandEntry]) -> discord.Embed:
    section_counts = {key: sum(1 for e in entries if e.section == key) for key, *_ in SECTION_SPECS}
    embed = discord.Embed(
        title="☣️ ABADDON 생존 지휘본부",
        description=(
            "**처음이면 `🌱 처음 시작`부터 누르세요.**\n"
            "생존자는 분야 하나만 고른 뒤 **작전군 → 기능** 순서로 선택하면 됩니다.\n"
            "기능을 고르면 즉시 실행되고, 입력이 필요한 기능은 아바돈이 입력창을 바로 엽니다."
        ),
        color=0x5865F2,
    )
    embed.add_field(
        name="🚀 생존 프로토콜",
        value="가입 → 출석 → 오늘 할 일 → 메인 RPG. 복잡한 명령어를 외울 필요 없이 버튼만 따라가면 됩니다.",
        inline=False,
    )
    embed.add_field(
        name="🗂️ 현재 작전 분류",
        value=(
            f"📖 메인 RPG **{section_counts.get('main', 0)}** · "
            f"⚔️ 플레이 **{section_counts.get('play', 0)}** · "
            f"🌌 세계 **{section_counts.get('world', 0)}**\n"
            f"🤝 소셜 **{section_counts.get('social', 0)}** · "
            f"🛠️ 지휘/지원 **{section_counts.get('system', 0)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔎 탐색이 필요합니까?",
        value="`🔎 검색` 버튼 또는 `!명령어 벌목`처럼 원하는 기능을 바로 탐색할 수 있습니다.",
        inline=False,
    )
    embed.add_field(
        name="⭐ 빠른 재진입",
        value="`!즐겨찾기` · `!최근` · `!추천` · `!다음할일` — 자주 쓰던 기능과 지금 할 일을 바로 엽니다.",
        inline=False,
    )
    embed.set_footer(text=f"ABADDON v{VERSION} · 공개 기능 {_public_command_count(entries)}개 · 영구 지휘 메뉴")
    return embed


def _beginner_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌱 1분 생존 시작",
        description="처음 보는 사람도 아래 네 단계만 따라가면 바로 시작할 수 있습니다.",
        color=0x57F287,
    )
    embed.add_field(name="1️⃣ 가입", value="`!가입 생존자`", inline=True)
    embed.add_field(name="2️⃣ 기본 보상", value="`!출석`", inline=True)
    embed.add_field(name="3️⃣ 오늘 할 일", value="`!오늘할일`", inline=True)
    embed.add_field(name="4️⃣ 스토리", value="`!스토리 시작`", inline=True)
    embed.add_field(
        name="그 다음에는?",
        value="메인 메뉴에서 **플레이 / 세계 / 소셜 / 카지노 / 도박** 중 하고 싶은 것만 고르면 됩니다.",
        inline=False,
    )
    embed.set_footer(text="명령어를 외우지 않아도 메뉴에서 기능을 선택할 수 있습니다.")
    return embed


def _browser_embed(entries: Sequence[CommandEntry], section: str, group: str, page: int) -> discord.Embed:
    section_key, section_ko, _section_en, section_desc = _section_meta(section)
    _sec, group_ko, _group_en, group_desc, _den, emoji = _group_spec(group)
    rows = _rows_for(entries, section, group)
    page = _clamp_page(rows, page)
    start = page * PAGE_SIZE
    shown = rows[start:start + PAGE_SIZE]
    pages = _page_count(rows)

    embed = discord.Embed(
        title=f"{emoji} {group_ko}",
        description=(
            f"**{section_ko} › {group_ko}**\n{group_desc}\n\n"
            "아래 **기능 선택**에서 원하는 기능을 고르세요. 입력이 필요하면 입력창이 자동으로 열립니다."
        ),
        color=0x3498DB,
    )
    if shown:
        lines = []
        for entry in shown:
            lock = " 🔒" if entry.restricted else ""
            lines.append(f"`!{entry.qualified_name}`{lock} — {_trim_help(entry)}")
        embed.add_field(name=f"기능 {start + 1}-{start + len(shown)} / {len(rows)}", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="기능", value="현재 표시할 공개 기능이 없습니다.", inline=False)
    embed.set_footer(text=f"페이지 {page + 1}/{pages} · 전체 공개 기능 {len(entries)}개 · 🔒 권한이 필요한 기능")
    return embed


def _all_sections_embed(entries: Sequence[CommandEntry]) -> discord.Embed:
    embed = discord.Embed(
        title="📚 전체 기능 카테고리",
        description="큰 분류 하나만 고르면 그 아래 기능군과 실제 명령이 자동으로 정리됩니다.",
        color=0x5865F2,
    )
    for key, ko, _en, desc in SECTION_SPECS:
        count = sum(1 for e in entries if e.section == key)
        if count:
            embed.add_field(name=f"{ko} · {count}개", value=desc, inline=False)
    embed.set_footer(text="새 패치에서 명령이 추가돼도 실행 시 실제 등록 명령을 다시 읽어 갱신합니다.")
    return embed


def _search_embed(query: str, results: Sequence[CommandEntry]) -> discord.Embed:
    embed = discord.Embed(title=f"🔎 명령 검색 · {query}", color=0xFEE75C)
    if not results:
        embed.description = "검색 결과가 없습니다. 더 짧은 단어로 다시 검색해보세요."
        return embed
    lines = [f"`!{e.qualified_name}` — {_trim_help(e, 70)}" for e in results[:25]]
    embed.description = "\n".join(lines)[:3900]
    if len(results) > 25:
        embed.set_footer(text=f"상위 25개 표시 · 전체 결과 {len(results)}개 · 검색어를 더 구체적으로 입력하세요.")
    else:
        embed.set_footer(text=f"검색 결과 {len(results)}개 · 아래 선택에서 바로 실행")
    return embed


# ---------------------------------------------------------------------------
# Interaction utilities
# ---------------------------------------------------------------------------


async def _notice(interaction: discord.Interaction, text: str) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(text, ephemeral=True)
        else:
            await interaction.followup.send(text, ephemeral=True)
    except Exception:
        pass


async def _edit(interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View) -> None:
    """Edit with a fresh View; never mutate the dispatching View in-place."""
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.edit_original_response(embed=embed, view=view)
    except discord.NotFound:
        await _notice(interaction, "🫧 이 개인 메뉴가 만료됐습니다. `!명령어`를 다시 열어주세요.")
    except discord.HTTPException as exc:
        await _notice(interaction, f"⚠️ 메뉴 갱신에 실패했습니다. 잠시 후 다시 눌러주세요. (`{getattr(exc, 'status', '?')}`)")
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] persistent hub edit error: {type(exc).__name__}: {exc}", flush=True)
        await _notice(interaction, "⚠️ 메뉴 처리 중 오류가 발생했습니다. `!명령어`를 다시 열어주세요.")


async def _send_browser(interaction: discord.Interaction, bot: commands.Bot, section: str, preferred_group: str = "") -> None:
    entries = _visible_entries(bot)
    group = _first_group(entries, section, preferred_group)
    rows = _rows_for(entries, section, group)
    if not rows:
        await _notice(interaction, "현재 이 카테고리에 표시할 기능이 없습니다.")
        return
    view = CommandGroupView(bot, section, group, 0)
    embed = _browser_embed(entries, section, group, 0)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] browser send error: {type(exc).__name__}: {exc}", flush=True)
        await _notice(interaction, "⚠️ 세부 메뉴를 열지 못했습니다. 잠시 후 다시 시도해주세요.")


# ---------------------------------------------------------------------------
# Persistent root menu
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RootAction:
    action: str
    label: str
    emoji: str
    style: discord.ButtonStyle
    row: int


ROOT_ACTIONS: Tuple[RootAction, ...] = (
    RootAction("beginner", "처음 시작", "🌱", discord.ButtonStyle.success, 0),
    RootAction("main", "메인 RPG", "📖", discord.ButtonStyle.primary, 0),
    RootAction("play", "플레이", "⚔️", discord.ButtonStyle.primary, 0),
    RootAction("world", "세계", "🌌", discord.ButtonStyle.primary, 0),
    RootAction("social", "소셜", "🤝", discord.ButtonStyle.primary, 0),
    RootAction("casino", "카지노", "🎰", discord.ButtonStyle.secondary, 1),
    RootAction("gambling", "도박", "🎲", discord.ButtonStyle.secondary, 1),
    RootAction("system", "서버·도움", "🛠️", discord.ButtonStyle.secondary, 1),
    RootAction("search", "검색", "🔎", discord.ButtonStyle.secondary, 1),
    RootAction("all", "전체 기능", "📚", discord.ButtonStyle.secondary, 1),
)


class RootActionButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, spec: RootAction) -> None:
        super().__init__(
            label=spec.label,
            emoji=spec.emoji,
            style=spec.style,
            row=spec.row,
            custom_id=f"{PREFIX}:root:{spec.action}",
        )
        self.bot = bot
        self.action = spec.action

    async def callback(self, interaction: discord.Interaction) -> None:
        action = self.action
        if action == "beginner":
            try:
                await interaction.response.send_message(embed=_beginner_embed(), ephemeral=True)
            except Exception:
                await _notice(interaction, "`!가입 생존자` → `!출석` → `!오늘할일` → `!스토리 시작` 순서로 시작하세요.")
            return
        if action == "main":
            await _send_browser(interaction, self.bot, "main", "story1")
            return
        if action == "play":
            await _send_browser(interaction, self.bot, "play", "life")
            return
        if action == "world":
            await _send_browser(interaction, self.bot, "world", "black_city")
            return
        if action == "social":
            await _send_browser(interaction, self.bot, "social", "guild")
            return
        if action == "casino":
            await _send_browser(interaction, self.bot, "play", "casino")
            return
        if action == "gambling":
            await _send_browser(interaction, self.bot, "play", "gambling")
            return
        if action == "system":
            await _send_browser(interaction, self.bot, "system", "help")
            return
        if action == "all":
            entries = _visible_entries(self.bot)
            try:
                await interaction.response.send_message(embed=_all_sections_embed(entries), view=AllSectionsView(self.bot), ephemeral=True)
            except Exception as exc:
                print(f"[ABADDON v{VERSION}] all-sections send error: {type(exc).__name__}: {exc}", flush=True)
                await _notice(interaction, "⚠️ 전체 기능 메뉴를 열지 못했습니다.")
            return
        if action == "search":
            try:
                await interaction.response.send_modal(HubSearchModal(self.bot))
            except Exception as exc:
                print(f"[ABADDON v{VERSION}] search modal error: {type(exc).__name__}: {exc}", flush=True)
                await _notice(interaction, "`!명령어 검색어` 형식으로 검색해주세요. 예: `!명령어 벌목`")
            return


class PersistentRootHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        for spec in ROOT_ACTIONS:
            self.add_item(RootActionButton(bot, spec))


# ---------------------------------------------------------------------------
# All-category picker
# ---------------------------------------------------------------------------


class SectionPicker(discord.ui.Select):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        entries = _visible_entries(bot)
        options: List[discord.SelectOption] = []
        for key, ko, _en, desc in SECTION_SPECS:
            count = sum(1 for e in entries if e.section == key)
            if not count:
                continue
            options.append(discord.SelectOption(label=_short(ko, 100), value=key, description=_short(f"{count}개 · {desc}", 100)))
        super().__init__(
            placeholder="큰 카테고리를 선택하세요",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id=f"{PREFIX}:all:section",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        section = str(self.values[0])
        entries = _visible_entries(self.bot)
        group = _first_group(entries, section)
        view = CommandGroupView(self.bot, section, group, 0)
        await _edit(interaction, embed=_browser_embed(entries, section, group, 0), view=view)


class AllHomeButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(label="처음 메뉴", emoji="🏠", style=discord.ButtonStyle.secondary, custom_id=f"{PREFIX}:all:home", row=1)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = _visible_entries(self.bot)
        await _edit(interaction, embed=_root_embed(entries), view=PersistentRootHubView(self.bot))


class AllSectionsView(discord.ui.View):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.add_item(SectionPicker(bot))
        self.add_item(AllHomeButton(bot))


# ---------------------------------------------------------------------------
# Persistent section/group/page browser
# ---------------------------------------------------------------------------


class GroupPicker(discord.ui.Select):
    def __init__(self, owner: "CommandGroupView", entries: Sequence[CommandEntry]) -> None:
        self.owner = owner
        counts = _group_counts(entries, owner.section)
        options: List[discord.SelectOption] = []
        for key, ko, _en, desc, _den, emoji in _groups_for(entries, owner.section):
            count = counts.get(key, 0)
            if not count:
                continue
            options.append(discord.SelectOption(
                label=_short(ko, 100),
                value=key,
                emoji=emoji,
                description=_short(f"{count}개 · {desc}", 100),
                default=(key == owner.group),
            ))
        super().__init__(
            placeholder="1단계 · 기능군 선택",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id=f"{PREFIX}:group:{owner.section}:{owner.group}:{owner.page}",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        target_group = str(self.values[0])
        entries = _visible_entries(self.owner.bot)
        view = CommandGroupView(self.owner.bot, self.owner.section, target_group, 0)
        await _edit(interaction, embed=_browser_embed(entries, self.owner.section, target_group, 0), view=view)


class CommandPicker(discord.ui.Select):
    def __init__(self, owner: "CommandGroupView", entries: Sequence[CommandEntry]) -> None:
        self.owner = owner
        rows = _rows_for(entries, owner.section, owner.group)
        page = _clamp_page(rows, owner.page)
        start = page * PAGE_SIZE
        shown = rows[start:start + PAGE_SIZE]
        options: List[discord.SelectOption] = []
        for entry in shown:
            _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(discord.SelectOption(
                label=_short(f"!{entry.qualified_name}", 100),
                value=entry.qualified_name,
                emoji=emoji,
                description=_short(_trim_help(entry, 96), 100),
            ))
        if not options:
            options = [discord.SelectOption(label="표시할 기능 없음", value="__none__", description="다른 기능군을 선택하세요")]
        super().__init__(
            placeholder=f"2단계 · 기능 선택 → 실행 ({start + 1}-{start + len(shown)}/{len(rows)})",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id=f"{PREFIX}:cmd:{owner.section}:{owner.group}:{owner.page}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        name = str(self.values[0])
        if name == "__none__":
            await _notice(interaction, "다른 기능군을 선택해주세요.")
            return
        command = self.owner.bot.get_command(name)
        if command is None:
            # The message may predate a deployment that removed/renamed a command.
            await _notice(interaction, "이 기능은 현재 버전에서 이름이 바뀌었거나 제거됐습니다. `!명령어`를 새로 열어주세요.")
            return
        if _command_requires_input(command):
            try:
                await interaction.response.send_modal(HubArgsModal(self.owner.bot, command.qualified_name))
            except Exception as exc:
                print(f"[ABADDON v{VERSION}] args modal error: {type(exc).__name__}: {exc}", flush=True)
                await _notice(interaction, f"입력이 필요한 기능입니다. 직접 `!{command.qualified_name} {getattr(command, 'signature', '')}` 형식으로 실행해주세요.")
            return
        await _invoke_command(self.owner.bot, interaction, command.qualified_name)


class BrowserNavButton(discord.ui.Button):
    def __init__(self, owner: "CommandGroupView", action: str, *, disabled: bool = False) -> None:
        self.owner = owner
        labels = {
            "prev": ("이전", "◀️"),
            "next": ("다음", "▶️"),
            "categories": ("다른 카테고리", "🧭"),
            "home": ("처음 메뉴", "🏠"),
        }
        label, emoji = labels[action]
        style = discord.ButtonStyle.primary if action in {"prev", "next"} else discord.ButtonStyle.secondary
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            disabled=disabled,
            custom_id=f"{PREFIX}:nav:{owner.section}:{owner.group}:{owner.page}:{action}",
            row=2,
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = _visible_entries(self.owner.bot)
        if self.action == "home":
            await _edit(interaction, embed=_root_embed(entries), view=PersistentRootHubView(self.owner.bot))
            return
        if self.action == "categories":
            await _edit(interaction, embed=_all_sections_embed(entries), view=AllSectionsView(self.owner.bot))
            return
        rows = _rows_for(entries, self.owner.section, self.owner.group)
        current = _clamp_page(rows, self.owner.page)
        target = current - 1 if self.action == "prev" else current + 1
        target = _clamp_page(rows, target)
        view = CommandGroupView(self.owner.bot, self.owner.section, self.owner.group, target)
        await _edit(interaction, embed=_browser_embed(entries, self.owner.section, self.owner.group, target), view=view)


class CommandGroupView(discord.ui.View):
    def __init__(self, bot: commands.Bot, section: str, group: str, page: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.section = str(section)
        self.group = str(group)
        entries = _visible_entries(bot)
        rows = _rows_for(entries, self.section, self.group)
        self.page = _clamp_page(rows, int(page))
        pages = _page_count(rows)
        self.add_item(GroupPicker(self, entries))
        self.add_item(CommandPicker(self, entries))
        self.add_item(BrowserNavButton(self, "prev", disabled=self.page <= 0))
        self.add_item(BrowserNavButton(self, "next", disabled=self.page >= pages - 1))
        self.add_item(BrowserNavButton(self, "categories"))
        self.add_item(BrowserNavButton(self, "home"))


# ---------------------------------------------------------------------------
# Search and argument modals
# ---------------------------------------------------------------------------


class HubArgsModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, command_name: str) -> None:
        self.bot = bot
        self.command_name = str(command_name)
        command = bot.get_command(self.command_name)
        signature = str(getattr(command, "signature", "") or "입력값") if command is not None else "입력값"
        super().__init__(title=_short(f"!{self.command_name} 입력", 45), timeout=300)
        self.raw = discord.ui.TextInput(
            label="필요한 입력값",
            placeholder=_short(signature, 100),
            required=True,
            max_length=400,
        )
        self.add_item(self.raw)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        command = self.bot.get_command(self.command_name)
        if command is None:
            await _notice(interaction, "현재 버전에서 이 명령을 찾지 못했습니다.")
            return
        await _invoke_command(self.bot, interaction, command.qualified_name, str(self.raw.value).strip())


class SearchResultPicker(discord.ui.Select):
    def __init__(self, bot: commands.Bot, query: str, results: Sequence[CommandEntry]) -> None:
        self.bot = bot
        self.query = query
        options: List[discord.SelectOption] = []
        for entry in list(results)[:25]:
            _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(discord.SelectOption(
                label=_short(f"!{entry.qualified_name}", 100),
                value=entry.qualified_name,
                emoji=emoji,
                description=_short(_trim_help(entry, 96), 100),
            ))
        digest = hashlib.sha1(query.encode("utf-8", errors="ignore")).hexdigest()[:10]
        super().__init__(
            placeholder="검색 결과 선택 → 실행",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{PREFIX}:search:{digest}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        name = str(self.values[0])
        command = self.bot.get_command(name)
        if command is None:
            await _notice(interaction, "현재 버전에서 이 기능을 찾지 못했습니다. 검색을 다시 해주세요.")
            return
        if _command_requires_input(command):
            await interaction.response.send_modal(HubArgsModal(self.bot, command.qualified_name))
            return
        await _invoke_command(self.bot, interaction, command.qualified_name)


class SearchResultsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, query: str, results: Sequence[CommandEntry]) -> None:
        # Search panels are deliberately temporary; the persistent root/group
        # navigation is always one click away and survives restarts.
        super().__init__(timeout=900)
        if results:
            self.add_item(SearchResultPicker(bot, query, results))


class HubSearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__(title="전체 기능 검색", timeout=300)
        self.query = discord.ui.TextInput(
            label="찾을 기능",
            placeholder="예: 벌목, 장비, 경마, 길드, 스토리",
            required=True,
            max_length=80,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = str(self.query.value).strip()
        entries = _visible_entries(self.bot)
        terms = [x.casefold() for x in query.split() if x.strip()]
        scored: List[Tuple[int, CommandEntry]] = []
        for entry in entries:
            blob = " ".join((entry.qualified_name, " ".join(entry.aliases), entry.help_text, entry.group, entry.section)).casefold()
            if terms and all(term in blob for term in terms):
                qname = entry.qualified_name.casefold()
                score = sum(20 if qname == t else 10 if qname.startswith(t) else 5 if t in qname else 1 for t in terms)
                scored.append((score, entry))
        scored.sort(key=lambda row: (-row[0], row[1].qualified_name.casefold()))
        results = [entry for _score, entry in scored]
        await interaction.response.send_message(embed=_search_embed(query, results), view=(SearchResultsView(self.bot, query, results) if results else None), ephemeral=True)


# ---------------------------------------------------------------------------
# Persistent registration / audit
# ---------------------------------------------------------------------------


def _view_custom_ids(view: discord.ui.View) -> List[str]:
    return [str(getattr(child, "custom_id", "") or "") for child in view.children if getattr(child, "custom_id", None)]


def _build_persistent_views(bot: commands.Bot) -> List[discord.ui.View]:
    entries = _visible_entries(bot)
    views: List[discord.ui.View] = [PersistentRootHubView(bot), AllSectionsView(bot)]
    for section, *_ in SECTION_SPECS:
        for group, *_rest in _groups_for(entries, section):
            rows = _rows_for(entries, section, group)
            for page in range(_page_count(rows)):
                views.append(CommandGroupView(bot, section, group, page))
    return views


def _register_persistent_views(bot: commands.Bot) -> Tuple[int, int]:
    views = _build_persistent_views(bot)
    seen: set[str] = set()
    duplicate = 0
    registered = 0
    for view in views:
        ids = _view_custom_ids(view)
        # All children in a persistent View must carry a stable custom_id.
        if getattr(view, "timeout", None) is not None or not ids or len(ids) != len(view.children):
            continue
        for cid in ids:
            if cid in seen:
                duplicate += 1
            seen.add(cid)
        try:
            bot.add_view(view)
            registered += 1
        except Exception as exc:
            print(f"[ABADDON v{VERSION}] add_view warning · {type(view).__name__}: {type(exc).__name__}: {exc}", flush=True)
    setattr(bot, "v1831_persistent_view_count", registered)
    setattr(bot, "v1831_persistent_custom_ids", tuple(sorted(seen)))
    setattr(bot, "v1831_persistent_duplicate_ids", duplicate)
    return registered, duplicate


async def _owner_only(bot: commands.Bot, ctx: commands.Context) -> bool:
    try:
        ok = bool(await bot.is_owner(ctx.author))
    except Exception:
        ok = False
    if not ok:
        await ctx.send("⛔ 이 명령은 ABADDON 제작자만 사용할 수 있습니다.")
    return ok


def register_v1831_persistent_command_hub(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1831_registered", False):
        return
    bot._abaddon_v1831_registered = True
    bot.abaddon_version = VERSION

    # Add owner diagnostics first so a fresh registry sees the final command set.
    @bot.command(
        name="1831메뉴검수",
        aliases=["1831버튼검수", "영구메뉴검수"],
        hidden=True,
        help="제작자 전용: 영구 메뉴, 전체 명령 분류, 페이지, custom_id 충돌을 점검합니다.",
    )
    async def audit_1831(ctx: commands.Context, mode: str = "") -> None:
        if not await _owner_only(bot, ctx):
            return
        entries = _visible_entries(bot)
        views = _build_persistent_views(bot)
        ids: List[str] = []
        invalid: List[str] = []
        page_issues: List[str] = []
        for view in views:
            child_ids = _view_custom_ids(view)
            ids.extend(child_ids)
            if getattr(view, "timeout", None) is not None or len(child_ids) != len(view.children):
                invalid.append(type(view).__name__)
            if isinstance(view, CommandGroupView):
                rows = _rows_for(entries, view.section, view.group)
                pages = _page_count(rows)
                if not (0 <= view.page < pages):
                    page_issues.append(f"{view.section}/{view.group}/{view.page}")
        duplicate = sorted({cid for cid in ids if ids.count(cid) > 1})
        sections = {key: sum(1 for e in entries if e.section == key) for key, *_ in SECTION_SPECS}
        fallback = [e for e in entries if e.group == "legacy"]
        checks = [
            ("영구 View 등록", int(getattr(bot, "v1831_persistent_view_count", 0) or 0) > 0),
            ("모든 영구 컴포넌트 custom_id 보유", not invalid),
            ("custom_id 중복 0", not duplicate),
            ("페이지 범위 오류 0", not page_issues),
            ("실시간 명령 레지스트리 연결", bool(entries)),
            ("!명령어 / !버튼 존재", bot.get_command("명령어") is not None and bot.get_command("버튼") is not None),
        ]
        ok = all(flag for _, flag in checks)
        embed = discord.Embed(title=f"🧭 ABADDON v{VERSION} 영구 메뉴 검수", color=0x57F287 if ok else 0xFEE75C)
        embed.description = "\n".join(f"{'✅' if flag else '❌'} {label}" for label, flag in checks)
        embed.add_field(name="공개 명령", value=f"**{len(entries)}개** · 메인 {sections.get('main',0)} / 플레이 {sections.get('play',0)} / 세계 {sections.get('world',0)} / 소셜 {sections.get('social',0)} / 시스템 {sections.get('system',0)}", inline=False)
        embed.add_field(name="영구 UI", value=f"View **{int(getattr(bot, 'v1831_persistent_view_count', 0) or 0)}개** · custom_id **{len(set(ids))}개** · 중복 **{len(duplicate)}**", inline=False)
        embed.add_field(name="분류 보존", value=f"기타/legacy **{len(fallback)}개** · 새 명령도 누락시키지 않고 보존", inline=False)
        if str(mode).casefold() in {"상세", "detail", "full", "전체"} or not ok:
            embed.add_field(name="비영구/ID 누락", value="\n".join(invalid[:20]) or "없음", inline=False)
            embed.add_field(name="중복 custom_id", value="\n".join(duplicate[:20]) or "없음", inline=False)
            embed.add_field(name="페이지 오류", value="\n".join(page_issues[:20]) or "없음", inline=False)
            embed.add_field(name="기타 분류 예시", value=" · ".join(f"`!{e.qualified_name}`" for e in fallback[:16]) or "없음", inline=False)
        embed.set_footer(text="읽기 전용 검수 · 사용자 데이터 변경 없음")
        await ctx.send(embed=embed)

    # Replace the public !명령어 callback with the new simple persistent hub.
    korean = bot.get_command("명령어")
    if korean is not None:
        previous = korean.callback

        async def v1831_help(ctx: commands.Context, *, 검색어: str = "") -> None:
            entries = _visible_entries(bot)
            query = str(검색어 or "").strip()
            if query:
                terms = [x.casefold() for x in query.split() if x.strip()]
                results = [
                    e for e in entries
                    if terms and all(t in " ".join((e.qualified_name, " ".join(e.aliases), e.help_text, e.group, e.section)).casefold() for t in terms)
                ]
                await ctx.send(embed=_search_embed(query, results), view=(SearchResultsView(bot, query, results) if results else None))
                return
            await ctx.send(embed=_root_embed(entries), view=PersistentRootHubView(bot))

        korean.callback = v1831_help
        korean.help = "처음 보는 사람도 쉽게 쓰는 영구 버튼형 전체 기능 메뉴. 실제 등록 명령을 매번 다시 읽어 자동 최신화합니다."
        korean.description = korean.help
        korean.extras = dict(getattr(korean, "extras", {}) or {})
        korean.extras["v1831_previous_callback"] = previous

    english = bot.get_command("help")
    if english is not None:
        previous = english.callback

        async def v1831_help_en(ctx: commands.Context, *, keyword: str = "") -> None:
            # Keep the interaction architecture identical. The canonical Korean
            # labels are intentionally retained here until the next bilingual UI
            # copy pass; English command aliases remain available.
            entries = _visible_entries(bot)
            query = str(keyword or "").strip()
            if query:
                terms = [x.casefold() for x in query.split() if x.strip()]
                results = [
                    e for e in entries
                    if terms and all(t in " ".join((e.qualified_name, " ".join(e.aliases), e.help_text, e.group, e.section)).casefold() for t in terms)
                ]
                await ctx.send(embed=_search_embed(query, results), view=(SearchResultsView(bot, query, results) if results else None))
                return
            await ctx.send(embed=_root_embed(entries), view=PersistentRootHubView(bot))

        english.callback = v1831_help_en
        english.extras = dict(getattr(english, "extras", {}) or {})
        english.extras["v1831_previous_callback"] = previous

    # !버튼 must be a first-class public alias of the same hub, not a second
    # independent UI implementation.
    button = bot.get_command("버튼")
    if button is not None:
        previous = button.callback

        async def v1831_button(ctx: commands.Context, *, 검색어: str = "") -> None:
            target = bot.get_command("명령어")
            if target is None:
                await ctx.send("⚠️ 명령어 메뉴를 찾지 못했습니다.")
                return
            await ctx.invoke(target, 검색어=str(검색어 or ""))

        button.callback = v1831_button
        button.hidden = False
        button.help = "간단한 영구 버튼형 전체 기능 메뉴를 엽니다. `!명령어`와 같은 화면입니다."
        button.description = button.help
        button.extras = dict(getattr(button, "extras", {}) or {})
        button.extras["v1831_previous_callback"] = previous

    # Build final runtime registry after all new owner commands above are present,
    # then register every deterministic group/page view for restart persistence.
    _refresh_registry(bot)
    registered, duplicates = _register_persistent_views(bot)
    print(f"[ABADDON v{VERSION}] persistent command hub ready · views={registered} duplicate_ids={duplicates}", flush=True)

    # Expose a refresh hook for later patches. A future version can call this
    # after adding commands so the catalogue remains complete without copying
    # another hard-coded command list.
    def refresh_v1831_views() -> Tuple[int, int]:
        _refresh_registry(bot)
        return _register_persistent_views(bot)

    bot.v1831_refresh_persistent_views = refresh_v1831_views

    patch = bot.get_command("패치노트")
    if patch is not None:
        previous_patch = patch.callback

        async def patch_v1831(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            entries = _visible_entries(bot)
            embed = discord.Embed(title="🧭 ABADDON v18.3.1 — PERSISTENT SIMPLE UI", color=0x5865F2)
            embed.description = "버튼 오류를 줄이는 것과 동시에 처음 보는 사용자도 바로 이해하도록 전체 명령어 메뉴를 다시 설계했습니다."
            embed.add_field(name="🛡️ 영구 메뉴", value="`!명령어` / `!버튼` 핵심 네비게이션을 timeout=None + 고정 custom_id로 전환하고 재시작 시 자동 재등록", inline=False)
            embed.add_field(name="🧩 단순한 구조", value="큰 카테고리 → 기능군 → 기능 선택. 수백 개 명령을 첫 화면에 한꺼번에 보여주지 않음", inline=False)
            embed.add_field(name="◀️▶️ 페이지 안정화", value="기존 View를 clear/remove로 재조립하지 않고 매번 새 View로 교체해 이전/다음 무반응 경로 제거", inline=False)
            embed.add_field(name="🔄 자동 최신화", value=f"현재 공개 명령 **{len(entries)}개**를 실제 등록 상태에서 다시 읽어 자동 분류", inline=False)
            embed.add_field(name="🧪 제작자 검수", value="`!1831메뉴검수 상세` · 기존 `!1830버튼검수 상세`도 보존", inline=False)
            embed.set_footer(text="사용자 게임 데이터/가입 데이터 변경 없음 · /var/data 유지")
            await ctx.send(embed=embed)

        patch.callback = patch_v1831
        patch.help = "ABADDON v18.3.1 영구·단순 전체 명령어 UI 최신 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1831_previous_callback"] = previous_patch
