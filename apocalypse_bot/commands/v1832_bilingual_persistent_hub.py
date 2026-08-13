from __future__ import annotations

"""ABADDON v18.3.2 bilingual persistent command hub sync.

This patch keeps the v18.3.1 Korean simple/persistent hub intact and upgrades
English help to the same live-registry architecture:

* English categories are generated from the live prefix-command registry.
* Every command is re-synchronized with an ASCII execution alias after all
  v18.3.1 modules have loaded.
* English root/category/group/page navigation uses timeout=None and stable
  custom_id values so public navigation survives Render restarts.
* Page changes replace the View instead of mutating the dispatching View.
* Search and argument modals remain personal/temporary by design.
* Korean and English hubs share the same section/group taxonomy, so later
  commands automatically appear under the same hierarchy in both languages.
"""

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Dict, List, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _command_requires_input, _invoke_command
from apocalypse_bot.commands.v652_english_access import synchronize_all_english_aliases
from apocalypse_bot.commands.v1630_core_rpg_command_city_overhaul import (
    CommandEntry,
    GROUP_SPECS,
    SECTION_SPECS,
    _build_registry,
    _group_spec,
    _short,
)
from apocalypse_bot.commands.v1831_persistent_command_hub import (
    _visible_entries as _ko_visible_entries,
    _refresh_registry as _ko_refresh_registry,
)

VERSION = "18.6.0"
PREFIX = "abaddon:v1832:en"
PAGE_SIZE = 25
ASCII_RE = re.compile(r"^[A-Za-z0-9_ .-]+$")
HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")

SECTION_EN_DESC: Dict[str, str] = {
    "main": "Story, growth, onboarding, missions and the core apocalypse RPG.",
    "play": "Life skills, combat, equipment, economy, games, casino and gambling.",
    "world": "BLACK CITY, NEON ABYSS, disasters, factions and living-world systems.",
    "social": "Guilds, companions, NPC bonds, parties, schedules and community features.",
    "system": "Server configuration, help, alerts, security and utility features.",
}


# ---------------------------------------------------------------------------
# Live registry / English display helpers
# ---------------------------------------------------------------------------


def _sync_registry(bot: commands.Bot) -> List[CommandEntry]:
    """Rebuild the same canonical live registry used by the Korean UI.

    English aliases are synchronized once at registration (and by the explicit
    refresh hook), not on every button click. This keeps navigation fast even
    with 1,000+ commands.
    """
    rows = list(_build_registry(bot))
    setattr(bot, "v1630_command_entries", rows)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in rows})
    setattr(bot, "v1832_command_entries", rows)
    return rows


def _entries(bot: commands.Bot, *, refresh: bool = True) -> List[CommandEntry]:
    rows = _sync_registry(bot) if refresh else list(getattr(bot, "v1832_command_entries", ()) or _build_registry(bot))
    visible: List[CommandEntry] = []
    for entry in rows:
        cmd = bot.get_command(entry.qualified_name)
        if cmd is None or bool(getattr(cmd, "hidden", False)):
            continue
        visible.append(entry)
    return visible


def _english_name(bot: commands.Bot, entry: CommandEntry) -> str:
    cmd = bot.get_command(entry.qualified_name)
    candidates: List[str] = []
    if cmd is not None:
        candidates.extend(str(a) for a in getattr(cmd, "aliases", ()) or ())
        candidates.append(str(getattr(cmd, "name", "") or ""))
    candidates.extend(str(a) for a in entry.aliases)
    candidates.append(entry.qualified_name)
    for candidate in candidates:
        text = " ".join(candidate.split()).strip()
        if text and ASCII_RE.fullmatch(text) and any(ch.isalpha() for ch in text):
            return text.lower()
    # synchronize_all_english_aliases should make this unreachable; keep a
    # deterministic last-resort label instead of leaking Korean into English UI.
    digest = hashlib.sha1(entry.qualified_name.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"command_{digest}"


def _english_help(entry: CommandEntry) -> str:
    text = " ".join(str(entry.help_text or "").split())
    if text and not HANGUL_RE.search(text):
        return _short(text, 92)
    _section, _ko, _en, _dko, den, _emoji = _group_spec(entry.group)
    return _short(den or "Open this ABADDON feature.", 92)


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
        if counts.get(key, 0):
            rows.append(spec)
            known.add(key)
    leftovers = sorted(k for k, n in counts.items() if n and k not in known)
    for key in leftovers:
        rows.append(_group_spec(key))
    return rows


def _first_group(entries: Sequence[CommandEntry], section: str, preferred: str = "") -> str:
    keys = [row[0] for row in _groups_for(entries, section)]
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


def _page_count(rows: Sequence[Any]) -> int:
    return max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)


def _clamp_page(rows: Sequence[Any], page: int) -> int:
    return max(0, min(int(page), _page_count(rows) - 1))


# ---------------------------------------------------------------------------
# English embeds
# ---------------------------------------------------------------------------


def _root_embed(bot: commands.Bot, entries: Sequence[CommandEntry]) -> discord.Embed:
    counts = {key: sum(1 for e in entries if e.section == key) for key, *_ in SECTION_SPECS}
    embed = discord.Embed(
        title="🧭 ABADDON Survival Menu",
        description=(
            "**New here? Start with `🌱 Quick Start`.**\n"
            "Choose one area, then follow **feature group → feature**. You do not need to memorize commands.\n"
            "Selecting a feature runs it immediately; features that need input open a simple input box."
        ),
        color=0x4C8FD4,
    )
    embed.add_field(
        name="🚀 Easiest path",
        value="Register → Daily check-in → Today → Core RPG. Use the menu instead of memorizing hundreds of commands.",
        inline=False,
    )
    embed.add_field(
        name="📚 Live command catalogue",
        value=(
            f"📖 Core RPG **{counts.get('main', 0)}** · ⚔️ Play **{counts.get('play', 0)}** · "
            f"🌌 World **{counts.get('world', 0)}**\n"
            f"🤝 Social **{counts.get('social', 0)}** · 🛠️ Server & Help **{counts.get('system', 0)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔎 Looking for something specific?",
        value="Use `Search` or type `!help mining`, `!help guild`, `!help story`, etc.",
        inline=False,
    )
    embed.add_field(
        name="⭐ Fast return",
        value="`!favorites` · `!recent` · `!recommend` · `!nextaction` — reopen what you use or get the next suggestion.",
        inline=False,
    )
    embed.set_footer(text=f"ABADDON v{VERSION} · {len(entries)} public features · persistent English navigation")
    return embed


def _quick_start_embed(bot: commands.Bot) -> discord.Embed:
    def alias_for(name: str, fallback: str) -> str:
        cmd = bot.get_command(name)
        if cmd:
            for token in [*getattr(cmd, "aliases", ()), getattr(cmd, "name", "")]:
                if ASCII_RE.fullmatch(str(token)) and any(c.isalpha() for c in str(token)):
                    return str(token).lower()
        return fallback

    register = alias_for("가입", "register")
    daily = alias_for("출석", "daily")
    today = alias_for("오늘할일", "today")
    story = alias_for("스토리", "story")
    embed = discord.Embed(
        title="🌱 1-Minute Survival Start",
        description="Follow these four steps and you are ready to play.",
        color=0x57F287,
    )
    embed.add_field(name="1️⃣ Register", value=f"`!{register} survivor`", inline=True)
    embed.add_field(name="2️⃣ Daily reward", value=f"`!{daily}`", inline=True)
    embed.add_field(name="3️⃣ Today", value=f"`!{today}`", inline=True)
    embed.add_field(name="4️⃣ Story", value=f"`!{story} start`", inline=True)
    embed.add_field(
        name="What next?",
        value="Return to the menu and choose **Play / World / Social / Casino / Gambling**. Only open the area you want.",
        inline=False,
    )
    embed.set_footer(text="You can use the menu even if you never memorize a command name.")
    return embed


def _browser_embed(bot: commands.Bot, entries: Sequence[CommandEntry], section: str, group: str, page: int) -> discord.Embed:
    _key, _ko, section_en, _desc = _section_meta(section)
    _sec, _gko, group_en, _dko, group_en_desc, emoji = _group_spec(group)
    rows = _rows_for(entries, section, group)
    page = _clamp_page(rows, page)
    start = page * PAGE_SIZE
    shown = rows[start:start + PAGE_SIZE]
    embed = discord.Embed(
        title=f"{emoji} {group_en}",
        description=(
            f"**{section_en} › {group_en}**\n{group_en_desc}\n\n"
            "Choose a feature below. If it needs arguments, an input box opens automatically."
        ),
        color=0x3498DB,
    )
    if shown:
        lines = []
        for entry in shown:
            lock = " 🔒" if entry.restricted else ""
            lines.append(f"`!{_english_name(bot, entry)}`{lock} — {_english_help(entry)}")
        embed.add_field(name=f"Features {start + 1}-{start + len(shown)} / {len(rows)}", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="Features", value="No public feature is currently available in this group.", inline=False)
    embed.set_footer(text=f"Page {page + 1}/{_page_count(rows)} · {len(entries)} public features · 🔒 permission required")
    return embed


def _all_embed(entries: Sequence[CommandEntry]) -> discord.Embed:
    embed = discord.Embed(
        title="📚 All Feature Categories",
        description="Pick one top-level category. Feature groups and live commands are organized underneath automatically.",
        color=0x4C8FD4,
    )
    for key, _ko, en, _desc in SECTION_SPECS:
        count = sum(1 for e in entries if e.section == key)
        if count:
            embed.add_field(name=f"{en} · {count}", value=SECTION_EN_DESC.get(key, "ABADDON features."), inline=False)
    embed.set_footer(text="The catalogue is rebuilt from commands actually registered in the running bot.")
    return embed


def _search_embed(bot: commands.Bot, query: str, results: Sequence[CommandEntry]) -> discord.Embed:
    embed = discord.Embed(title=f"🔎 Command Search · {query}", color=0xFEE75C)
    if not results:
        embed.description = "No matching command was found. Try a shorter or broader English keyword."
        return embed
    lines = [f"`!{_english_name(bot, e)}` — {_english_help(e)}" for e in results[:25]]
    embed.description = "\n".join(lines)[:3900]
    embed.set_footer(text=(f"Top 25 shown · {len(results)} matches" if len(results) > 25 else f"{len(results)} matches · select below to run"))
    return embed


# ---------------------------------------------------------------------------
# Interaction helpers
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
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.edit_original_response(embed=embed, view=view)
    except discord.NotFound:
        await _notice(interaction, "🫧 This personal menu expired. Open `!help` again.")
    except discord.HTTPException as exc:
        await _notice(interaction, f"⚠️ Menu refresh failed. Please try again shortly. (`{getattr(exc, 'status', '?')}`)")
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] English hub edit error: {type(exc).__name__}: {exc}", flush=True)
        await _notice(interaction, "⚠️ A menu error occurred. Open `!help` again.")


async def _send_browser(interaction: discord.Interaction, bot: commands.Bot, section: str, preferred_group: str = "") -> None:
    entries = _entries(bot, refresh=True)
    group = _first_group(entries, section, preferred_group)
    if not _rows_for(entries, section, group):
        await _notice(interaction, "There are no public features in this category right now.")
        return
    view = EnglishCommandGroupView(bot, section, group, 0)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=_browser_embed(bot, entries, section, group, 0), view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=_browser_embed(bot, entries, section, group, 0), view=view, ephemeral=True)
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] English browser send error: {type(exc).__name__}: {exc}", flush=True)
        await _notice(interaction, "⚠️ Could not open the submenu. Please try again shortly.")


# ---------------------------------------------------------------------------
# Persistent English root
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RootAction:
    action: str
    label: str
    emoji: str
    style: discord.ButtonStyle
    row: int


ROOT_ACTIONS: Tuple[RootAction, ...] = (
    RootAction("quick", "Quick Start", "🌱", discord.ButtonStyle.success, 0),
    RootAction("main", "Core RPG", "📖", discord.ButtonStyle.primary, 0),
    RootAction("play", "Play", "⚔️", discord.ButtonStyle.primary, 0),
    RootAction("world", "World", "🌌", discord.ButtonStyle.primary, 0),
    RootAction("social", "Social", "🤝", discord.ButtonStyle.primary, 0),
    RootAction("casino", "Casino", "🎰", discord.ButtonStyle.secondary, 1),
    RootAction("gambling", "Gambling", "🎲", discord.ButtonStyle.secondary, 1),
    RootAction("system", "Server & Help", "🛠️", discord.ButtonStyle.secondary, 1),
    RootAction("search", "Search", "🔎", discord.ButtonStyle.secondary, 1),
    RootAction("all", "All Features", "📚", discord.ButtonStyle.secondary, 1),
)


class EnglishRootButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, spec: RootAction) -> None:
        super().__init__(label=spec.label, emoji=spec.emoji, style=spec.style, row=spec.row, custom_id=f"{PREFIX}:root:{spec.action}")
        self.bot = bot
        self.action = spec.action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.action == "quick":
            await interaction.response.send_message(embed=_quick_start_embed(self.bot), ephemeral=True)
        elif self.action == "main":
            await _send_browser(interaction, self.bot, "main", "story1")
        elif self.action == "play":
            await _send_browser(interaction, self.bot, "play", "life")
        elif self.action == "world":
            await _send_browser(interaction, self.bot, "world", "black_city")
        elif self.action == "social":
            await _send_browser(interaction, self.bot, "social", "guild")
        elif self.action == "casino":
            await _send_browser(interaction, self.bot, "play", "casino")
        elif self.action == "gambling":
            await _send_browser(interaction, self.bot, "play", "gambling")
        elif self.action == "system":
            await _send_browser(interaction, self.bot, "system", "help")
        elif self.action == "all":
            entries = _entries(self.bot, refresh=True)
            await interaction.response.send_message(embed=_all_embed(entries), view=EnglishAllSectionsView(self.bot), ephemeral=True)
        elif self.action == "search":
            await interaction.response.send_modal(EnglishSearchModal(self.bot))


class EnglishRootView(discord.ui.View):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        for spec in ROOT_ACTIONS:
            self.add_item(EnglishRootButton(bot, spec))


# ---------------------------------------------------------------------------
# Category / group / command browser
# ---------------------------------------------------------------------------


class EnglishSectionPicker(discord.ui.Select):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        entries = _entries(bot, refresh=False)
        options: List[discord.SelectOption] = []
        for key, _ko, en, _desc in SECTION_SPECS:
            count = sum(1 for e in entries if e.section == key)
            if count:
                options.append(discord.SelectOption(label=_short(en, 100), value=key, description=_short(f"{count} features · {SECTION_EN_DESC.get(key, '')}", 100)))
        super().__init__(placeholder="Choose a top-level category", min_values=1, max_values=1, options=options[:25], custom_id=f"{PREFIX}:all:section", row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = _entries(self.bot, refresh=True)
        section = str(self.values[0])
        group = _first_group(entries, section)
        view = EnglishCommandGroupView(self.bot, section, group, 0)
        await _edit(interaction, embed=_browser_embed(self.bot, entries, section, group, 0), view=view)


class EnglishHomeButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, custom_suffix: str, row: int = 1) -> None:
        super().__init__(label="Home", emoji="🏠", style=discord.ButtonStyle.secondary, custom_id=f"{PREFIX}:{custom_suffix}:home", row=row)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = _entries(self.bot, refresh=True)
        await _edit(interaction, embed=_root_embed(self.bot, entries), view=EnglishRootView(self.bot))


class EnglishAllSectionsView(discord.ui.View):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.add_item(EnglishSectionPicker(bot))
        self.add_item(EnglishHomeButton(bot, "all", 1))


class EnglishGroupPicker(discord.ui.Select):
    def __init__(self, owner: "EnglishCommandGroupView", entries: Sequence[CommandEntry]) -> None:
        self.owner = owner
        counts = _group_counts(entries, owner.section)
        options: List[discord.SelectOption] = []
        for key, _ko, en, _dko, den, emoji in _groups_for(entries, owner.section):
            count = counts.get(key, 0)
            if count:
                options.append(discord.SelectOption(label=_short(en, 100), value=key, emoji=emoji, description=_short(f"{count} features · {den}", 100), default=(key == owner.group)))
        super().__init__(placeholder="Step 1 · Choose a feature group", min_values=1, max_values=1, options=options[:25], custom_id=f"{PREFIX}:group:{owner.section}:{owner.group}:{owner.page}", row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = _entries(self.owner.bot, refresh=True)
        group = str(self.values[0])
        view = EnglishCommandGroupView(self.owner.bot, self.owner.section, group, 0)
        await _edit(interaction, embed=_browser_embed(self.owner.bot, entries, self.owner.section, group, 0), view=view)


class EnglishCommandPicker(discord.ui.Select):
    def __init__(self, owner: "EnglishCommandGroupView", entries: Sequence[CommandEntry]) -> None:
        self.owner = owner
        rows = _rows_for(entries, owner.section, owner.group)
        page = _clamp_page(rows, owner.page)
        start = page * PAGE_SIZE
        shown = rows[start:start + PAGE_SIZE]
        options: List[discord.SelectOption] = []
        for entry in shown:
            _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(discord.SelectOption(label=_short(f"!{_english_name(owner.bot, entry)}", 100), value=entry.qualified_name, emoji=emoji, description=_short(_english_help(entry), 100)))
        if not options:
            options = [discord.SelectOption(label="No feature available", value="__none__", description="Choose another feature group")]
        super().__init__(placeholder=f"Step 2 · Choose a feature ({start + 1}-{start + len(shown)}/{len(rows)})", min_values=1, max_values=1, options=options[:25], custom_id=f"{PREFIX}:cmd:{owner.section}:{owner.group}:{owner.page}", row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        name = str(self.values[0])
        if name == "__none__":
            await _notice(interaction, "Choose another feature group.")
            return
        command = self.owner.bot.get_command(name)
        if command is None:
            await _notice(interaction, "This feature was renamed or removed. Open `!help` again.")
            return
        if _command_requires_input(command):
            entry = next((e for e in _entries(self.owner.bot, refresh=False) if e.qualified_name == name), None)
            display_name = _english_name(self.owner.bot, entry) if entry is not None else str(command.name)
            await interaction.response.send_modal(EnglishArgsModal(self.owner.bot, command.qualified_name, display_name))
            return
        await _invoke_command(self.owner.bot, interaction, command.qualified_name)


class EnglishNavButton(discord.ui.Button):
    def __init__(self, owner: "EnglishCommandGroupView", action: str, *, disabled: bool = False) -> None:
        self.owner = owner
        labels = {"prev": ("Previous", "◀️"), "next": ("Next", "▶️"), "categories": ("Categories", "🧭"), "home": ("Home", "🏠")}
        label, emoji = labels[action]
        style = discord.ButtonStyle.primary if action in {"prev", "next"} else discord.ButtonStyle.secondary
        super().__init__(label=label, emoji=emoji, style=style, disabled=disabled, custom_id=f"{PREFIX}:nav:{owner.section}:{owner.group}:{owner.page}:{action}", row=2)
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = _entries(self.owner.bot, refresh=True)
        if self.action == "home":
            await _edit(interaction, embed=_root_embed(self.owner.bot, entries), view=EnglishRootView(self.owner.bot))
            return
        if self.action == "categories":
            await _edit(interaction, embed=_all_embed(entries), view=EnglishAllSectionsView(self.owner.bot))
            return
        rows = _rows_for(entries, self.owner.section, self.owner.group)
        current = _clamp_page(rows, self.owner.page)
        target = current - 1 if self.action == "prev" else current + 1
        target = _clamp_page(rows, target)
        view = EnglishCommandGroupView(self.owner.bot, self.owner.section, self.owner.group, target)
        await _edit(interaction, embed=_browser_embed(self.owner.bot, entries, self.owner.section, self.owner.group, target), view=view)


class EnglishCommandGroupView(discord.ui.View):
    def __init__(self, bot: commands.Bot, section: str, group: str, page: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.section = str(section)
        self.group = str(group)
        entries = _entries(bot, refresh=False)
        rows = _rows_for(entries, self.section, self.group)
        self.page = _clamp_page(rows, int(page))
        pages = _page_count(rows)
        self.add_item(EnglishGroupPicker(self, entries))
        self.add_item(EnglishCommandPicker(self, entries))
        self.add_item(EnglishNavButton(self, "prev", disabled=self.page <= 0))
        self.add_item(EnglishNavButton(self, "next", disabled=self.page >= pages - 1))
        self.add_item(EnglishNavButton(self, "categories"))
        self.add_item(EnglishNavButton(self, "home"))


# ---------------------------------------------------------------------------
# Search / arguments
# ---------------------------------------------------------------------------


class EnglishArgsModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, command_name: str, display_name: str) -> None:
        self.bot = bot
        self.command_name = command_name
        command = bot.get_command(command_name)
        signature = str(getattr(command, "signature", "") or "arguments") if command is not None else "arguments"
        if HANGUL_RE.search(signature):
            signature = "arguments"
        super().__init__(title=_short(f"!{display_name} · Input", 45), timeout=300)
        self.raw = discord.ui.TextInput(label="Required input", placeholder=_short(signature, 100), required=True, max_length=400)
        self.add_item(self.raw)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        command = self.bot.get_command(self.command_name)
        if command is None:
            await _notice(interaction, "This command is not available in the current version.")
            return
        await _invoke_command(self.bot, interaction, command.qualified_name, str(self.raw.value).strip())


class EnglishSearchResultPicker(discord.ui.Select):
    def __init__(self, bot: commands.Bot, query: str, results: Sequence[CommandEntry]) -> None:
        self.bot = bot
        self.results_map = {e.qualified_name: e for e in results[:25]}
        options = []
        for entry in results[:25]:
            _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(discord.SelectOption(label=_short(f"!{_english_name(bot, entry)}", 100), value=entry.qualified_name, emoji=emoji, description=_short(_english_help(entry), 100)))
        digest = hashlib.sha1(query.encode("utf-8", errors="ignore")).hexdigest()[:10]
        super().__init__(placeholder="Choose a search result → run", min_values=1, max_values=1, options=options, custom_id=f"{PREFIX}:search:{digest}")

    async def callback(self, interaction: discord.Interaction) -> None:
        name = str(self.values[0])
        command = self.bot.get_command(name)
        entry = self.results_map.get(name)
        if command is None or entry is None:
            await _notice(interaction, "This result is no longer available. Search again.")
            return
        if _command_requires_input(command):
            await interaction.response.send_modal(EnglishArgsModal(self.bot, command.qualified_name, _english_name(self.bot, entry)))
            return
        await _invoke_command(self.bot, interaction, command.qualified_name)


class EnglishSearchResultsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, query: str, results: Sequence[CommandEntry]) -> None:
        super().__init__(timeout=900)
        if results:
            self.add_item(EnglishSearchResultPicker(bot, query, results))


class EnglishSearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__(title="Search ABADDON Features", timeout=300)
        self.query = discord.ui.TextInput(label="Feature or keyword", placeholder="Examples: mining, gear, guild, story, casino", required=True, max_length=80)
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = str(self.query.value).strip()
        results = _search(self.bot, query)
        await interaction.response.send_message(embed=_search_embed(self.bot, query, results), view=(EnglishSearchResultsView(self.bot, query, results) if results else None), ephemeral=True)


def _search(bot: commands.Bot, query: str) -> List[CommandEntry]:
    terms = [t.casefold() for t in query.split() if t.strip()]
    if not terms:
        return []
    scored: List[Tuple[int, CommandEntry]] = []
    for entry in _entries(bot, refresh=True):
        alias = _english_name(bot, entry)
        blob = " ".join((alias, " ".join(entry.aliases), _english_help(entry), entry.group, entry.section)).casefold()
        if all(term in blob for term in terms):
            qname = alias.casefold()
            score = sum(30 if qname == t else 15 if qname.startswith(t) else 7 if t in qname else 1 for t in terms)
            scored.append((score, entry))
    scored.sort(key=lambda row: (-row[0], _english_name(bot, row[1])))
    return [entry for _score, entry in scored]


# ---------------------------------------------------------------------------
# Persistence / audit / registration
# ---------------------------------------------------------------------------


def _custom_ids(view: discord.ui.View) -> List[str]:
    return [str(getattr(child, "custom_id", "") or "") for child in view.children if getattr(child, "custom_id", None)]


def _build_views(bot: commands.Bot) -> List[discord.ui.View]:
    entries = _entries(bot, refresh=False)
    views: List[discord.ui.View] = [EnglishRootView(bot), EnglishAllSectionsView(bot)]
    for section, *_ in SECTION_SPECS:
        for group, *_ in _groups_for(entries, section):
            rows = _rows_for(entries, section, group)
            for page in range(_page_count(rows)):
                views.append(EnglishCommandGroupView(bot, section, group, page))
    return views


def _register_views(bot: commands.Bot) -> Tuple[int, int]:
    views = _build_views(bot)
    seen: set[str] = set()
    duplicate = 0
    registered = 0
    for view in views:
        ids = _custom_ids(view)
        if view.timeout is not None or not ids or len(ids) != len(view.children):
            continue
        duplicate += sum(1 for cid in ids if cid in seen)
        seen.update(ids)
        try:
            bot.add_view(view)
            registered += 1
        except Exception as exc:
            print(f"[ABADDON v{VERSION}] English add_view warning · {type(view).__name__}: {type(exc).__name__}: {exc}", flush=True)
    bot.v1832_persistent_view_count = registered
    bot.v1832_persistent_custom_ids = tuple(sorted(seen))
    bot.v1832_persistent_duplicate_ids = duplicate
    return registered, duplicate


async def _owner_only(bot: commands.Bot, ctx: commands.Context) -> bool:
    try:
        ok = bool(await bot.is_owner(ctx.author))
    except Exception:
        ok = False
    if not ok:
        await ctx.send("⛔ This command is restricted to the ABADDON creator.")
    return ok


def register_v1832_bilingual_persistent_hub(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1832_registered", False):
        return
    bot._abaddon_v1832_registered = True
    bot.abaddon_version = VERSION

    # Run the alias sync after v18.3.1 so commands added by later historical
    # modules also receive an English execution name.
    report = synchronize_all_english_aliases(bot)
    bot.v1832_english_sync_report = report
    _sync_registry(bot)

    @bot.command(name="1832언어UI검수", aliases=["1832영어검수", "bilingualuiaudit"], hidden=True, help="제작자 전용: 한영 명령 허브 동기화와 영문 별칭/영구 UI를 검수합니다.")
    async def audit_1832(ctx: commands.Context, mode: str = "") -> None:
        if not await _owner_only(bot, ctx):
            return
        entries = _entries(bot, refresh=True)
        english_missing = []
        for entry in entries:
            name = _english_name(bot, entry)
            if not name or HANGUL_RE.search(name):
                english_missing.append(entry.qualified_name)
        views = _build_views(bot)
        ids: List[str] = []
        invalid = []
        for view in views:
            child_ids = _custom_ids(view)
            ids.extend(child_ids)
            if view.timeout is not None or len(child_ids) != len(view.children):
                invalid.append(type(view).__name__)
        duplicate = sorted({cid for cid in ids if ids.count(cid) > 1})
        ko_entries = _ko_visible_entries(bot)
        checks = [
            ("Korean/English live catalogue count matches", len(entries) == len(ko_entries)),
            ("All public commands have English execution names", not english_missing),
            ("English persistent views registered", int(getattr(bot, "v1832_persistent_view_count", 0) or 0) > 0),
            ("All English persistent components have custom_id", not invalid),
            ("English custom_id collisions = 0", not duplicate),
            ("!help / !commands / !english available", all(bot.get_command(name) is not None for name in ("help", "commands", "english"))),
        ]
        ok = all(flag for _, flag in checks)
        embed = discord.Embed(title=f"🌐 ABADDON v{VERSION} Bilingual UI Audit", color=0x57F287 if ok else 0xFEE75C)
        embed.description = "\n".join(f"{'✅' if flag else '❌'} {label}" for label, flag in checks)
        embed.add_field(name="Catalogue", value=f"Korean **{len(ko_entries)}** · English **{len(entries)}**", inline=True)
        embed.add_field(name="English aliases", value=f"Missing **{len(english_missing)}** · sync fallback **{int((getattr(bot, 'v1832_english_sync_report', {}) or {}).get('fallback', 0))}**", inline=True)
        embed.add_field(name="Persistent English UI", value=f"Views **{int(getattr(bot, 'v1832_persistent_view_count', 0) or 0)}** · IDs **{len(set(ids))}** · duplicates **{len(duplicate)}**", inline=False)
        if str(mode).casefold() in {"상세", "detail", "full", "전체"} or not ok:
            embed.add_field(name="Missing English names", value="\n".join(f"`!{x}`" for x in english_missing[:20]) or "None", inline=False)
            embed.add_field(name="Invalid persistent views", value="\n".join(invalid[:20]) or "None", inline=False)
            embed.add_field(name="Duplicate custom_id", value="\n".join(duplicate[:20]) or "None", inline=False)
        embed.set_footer(text="Read-only audit · no player data changes")
        await ctx.send(embed=embed)

    # Replace the legacy fixed English guide with the same live hierarchy used
    # by the v18.3.1 Korean hub.
    english = bot.get_command("help")
    if english is not None:
        previous = english.callback

        async def v1832_help_en(ctx: commands.Context, *, keyword: str = "") -> None:
            query = str(keyword or "").strip()
            if query:
                results = _search(bot, query)
                await ctx.send(embed=_search_embed(bot, query, results), view=(EnglishSearchResultsView(bot, query, results) if results else None))
                return
            entries = _entries(bot, refresh=True)
            await ctx.send(embed=_root_embed(bot, entries), view=EnglishRootView(bot))

        english.callback = v1832_help_en
        english.help = "Open the simple persistent English ABADDON menu. The live command catalogue is rebuilt automatically."
        english.description = english.help
        english.extras = dict(getattr(english, "extras", {}) or {})
        english.extras["v1832_previous_callback"] = previous

    # English aliases are already aliases of !help; make their help metadata
    # explicit for downstream catalogue renderers.
    for alias in ("commands", "english", "enhelp", "englishhelp", "guide"):
        cmd = bot.get_command(alias)
        if cmd is english and english is not None:
            english.help = "Open the live English command menu and search all current ABADDON features."

    # Refresh both catalogues after adding the v18.3.2 audit command. Hidden
    # diagnostics remain excluded from public lists.
    _sync_registry(bot)
    try:
        _ko_refresh_registry(bot)
    except Exception:
        pass
    registered, duplicates = _register_views(bot)

    def refresh_v1832_views() -> Tuple[int, int]:
        synchronize_all_english_aliases(bot)
        _sync_registry(bot)
        return _register_views(bot)

    bot.v1832_refresh_persistent_views = refresh_v1832_views

    patch = bot.get_command("패치노트")
    if patch is not None:
        previous_patch = patch.callback

        async def patch_v1832(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            entries = _entries(bot, refresh=True)
            sync = getattr(bot, "v1832_english_sync_report", {}) or {}
            embed = discord.Embed(title="🌐 ABADDON v18.3.2 — BILINGUAL LIVE MENU SYNC", color=0x4C8FD4)
            embed.description = "v18.3.1의 단순·영구 메뉴 구조를 영어판에도 동일하게 적용하고, 영어 도움말이 새 기능보다 뒤처지던 고정 목록 구조를 제거했습니다."
            embed.add_field(name="🇬🇧 English UI", value="`!help` / `!commands` / `!english` → Quick Start / Core RPG / Play / World / Social / Casino / Gambling / Server & Help / Search / All Features", inline=False)
            embed.add_field(name="🔄 Live catalogue", value=f"현재 공개 기능 **{len(entries)}개**를 실제 실행 중인 명령에서 다시 읽어 한·영 동일 계층으로 자동 분류", inline=False)
            embed.add_field(name="🔤 English execution names", value=f"전체 prefix 명령 영어 별칭 재동기화 · 누락 **{int(sync.get('commands_without_ascii', 0))}개** · fallback **{int(sync.get('fallback', 0))}개**", inline=False)
            embed.add_field(name="🛡️ Persistent English navigation", value="영문 메인/카테고리/기능군/페이지 View도 timeout=None + 고정 custom_id + 시작 시 재등록", inline=False)
            embed.add_field(name="◀️▶️ Stable paging", value="영어판도 View를 clear/remove로 뜯지 않고 새 View로 교체하여 이전/다음 메뉴 구조를 한국어판과 통일", inline=False)
            embed.add_field(name="🧪 Owner audit", value="`!1832언어UI검수 상세`", inline=False)
            embed.set_footer(text="사용자 게임 데이터/경제/가입 데이터 변경 없음 · /var/data 유지")
            await ctx.send(embed=embed)

        patch.callback = patch_v1832
        patch.help = "ABADDON v18.3.2 한·영 실시간 명령 메뉴 동기화 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1832_previous_callback"] = previous_patch

    print(
        f"[ABADDON v{VERSION}] bilingual persistent hub ready · english_views={registered} "
        f"duplicate_ids={duplicates} commands={len(_entries(bot, refresh=False))} "
        f"english_missing={int((getattr(bot, 'v1832_english_sync_report', {}) or {}).get('commands_without_ascii', 0))}",
        flush=True,
    )
