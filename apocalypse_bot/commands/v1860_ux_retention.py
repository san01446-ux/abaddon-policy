from __future__ import annotations

"""ABADDON v18.6.0 UX / retention layer.

This module deliberately upgrades existing convenience data instead of creating
parallel stores.  Favorites and recent command history continue to live in the
v16.2 Living Legends user row, while v18.6 adds:

- button/select execution for favorites and recents;
- context-aware recommendations and a single "next action" surface;
- lightweight global/personal usage telemetry;
- personalized ordering for v18.5.2 smart discovery results;
- a post-deploy checklist that tells the owner exactly what to test.
"""

from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import time
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1620_living_legends as living
from apocalypse_bot.commands import v1831_persistent_command_hub as hub
from apocalypse_bot.commands import v1852_smart_command_discovery as discovery
from apocalypse_bot.commands.v1630_core_rpg_command_city_overhaul import CommandEntry, _group_spec, _short

VERSION = "18.6.0"
DATA_KEY = "ux_retention_v1860"
MAX_FAVORITES = 12
MAX_RECENT = 12
MAX_PANEL_RESULTS = 25
CORE_BUTTONS = 4
KST = timezone(timedelta(hours=9))


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(DATA_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[DATA_KEY] = root
    root.setdefault("schema", 1)
    root.setdefault("command_counts", {})
    root.setdefault("search_counts", {})
    root.setdefault("users", {})
    root.setdefault("started_at", int(time.time()))
    return root


def _ux_user(world_data: MutableMapping[str, Any], user_id: int) -> MutableMapping[str, Any]:
    users = _root(world_data).setdefault("users", {})
    row = users.setdefault(str(int(user_id)), {})
    if not isinstance(row, dict):
        row = {}
        users[str(int(user_id))] = row
    row.setdefault("command_counts", {})
    row.setdefault("search_counts", {})
    row.setdefault("last_command", "")
    row.setdefault("last_command_at", 0)
    row.setdefault("last_search", "")
    row.setdefault("last_search_at", 0)
    return row


def _living_user(world_data: MutableMapping[str, Any], guild_id: int, user_id: int) -> MutableMapping[str, Any]:
    root = living._root(world_data)
    guild = living._guild(root, int(guild_id or 0))
    return living._user(guild, int(user_id))


def _clean_command_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lstrip("!").split())[:100]


def _resolve_command(bot: commands.Bot, value: str) -> Optional[commands.Command]:
    token = _clean_command_name(value)
    if not token:
        return None
    cmd = bot.get_command(token)
    if cmd is not None:
        return cmd
    folded = token.casefold()
    for command in bot.walk_commands():
        if str(getattr(command, "qualified_name", "")).casefold() == folded:
            return command
        if str(getattr(command, "name", "")).casefold() == folded:
            return command
        if any(str(alias).casefold() == folded for alias in getattr(command, "aliases", ())):
            return command
    return None


def _visible_command(bot: commands.Bot, name: str) -> Optional[commands.Command]:
    cmd = _resolve_command(bot, name)
    if cmd is None or getattr(cmd, "hidden", False):
        return None
    return cmd


def _entry_for_command(bot: commands.Bot, name: str) -> Optional[CommandEntry]:
    target = _visible_command(bot, name)
    if target is None:
        return None
    qn = str(target.qualified_name)
    for entry in hub._visible_entries(bot):
        if entry.qualified_name == qn:
            return entry
    return None


def _entries_for_names(bot: commands.Bot, names: Iterable[str]) -> List[CommandEntry]:
    out: List[CommandEntry] = []
    seen: set[str] = set()
    for name in names:
        entry = _entry_for_command(bot, name)
        if entry is None or entry.qualified_name in seen:
            continue
        seen.add(entry.qualified_name)
        out.append(entry)
    return out


def _trim_help(entry: CommandEntry, limit: int = 72) -> str:
    return _short(" ".join(str(entry.help_text or "설명 없음").split()), limit)


def _usage_count(world_data: MutableMapping[str, Any], user_id: int, command_name: str) -> int:
    row = _ux_user(world_data, user_id)
    counts = row.get("command_counts", {}) if isinstance(row.get("command_counts"), Mapping) else {}
    return int(counts.get(command_name, 0) or 0)


def _rank_personal(world_data: MutableMapping[str, Any], user_id: int, rows: Sequence[CommandEntry]) -> List[CommandEntry]:
    # Preserve the lexical search order as the primary signal. Personal use is
    # a small stable boost, enough to surface familiar commands inside close
    # matches without making unrelated commands jump to the top.
    indexed = list(enumerate(rows))
    def personal_key(pair: Tuple[int, CommandEntry]) -> Tuple[int, int]:
        index, entry = pair
        uses = _usage_count(world_data, user_id, entry.qualified_name)
        boost = min(3, uses // 3)  # at most three positions of personal boost
        return (max(0, index - boost), index)
    indexed.sort(key=personal_key)
    return [entry for _, entry in indexed]


def _record_command(world_data: MutableMapping[str, Any], user_id: int, command_name: str) -> None:
    if not command_name or command_name.startswith(("18", "17", "16", "15", "14", "13", "12", "11", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1")):
        # Owner regression commands are intentionally excluded from retention
        # ranking so real user features remain representative.
        return
    root = _root(world_data)
    global_counts = root.setdefault("command_counts", {})
    global_counts[command_name] = int(global_counts.get(command_name, 0) or 0) + 1
    row = _ux_user(world_data, user_id)
    counts = row.setdefault("command_counts", {})
    counts[command_name] = int(counts.get(command_name, 0) or 0) + 1
    row["last_command"] = command_name
    row["last_command_at"] = int(time.time())


def _record_search(world_data: MutableMapping[str, Any], user_id: int, query: str, results: Sequence[CommandEntry]) -> None:
    query = " ".join(str(query or "").strip().casefold().split())[:80]
    if not query:
        return
    root = _root(world_data)
    searches = root.setdefault("search_counts", {})
    searches[query] = int(searches.get(query, 0) or 0) + 1
    row = _ux_user(world_data, user_id)
    mine = row.setdefault("search_counts", {})
    mine[query] = int(mine.get(query, 0) or 0) + 1
    row["last_search"] = query
    row["last_search_at"] = int(time.time())
    row["last_search_results"] = [entry.qualified_name for entry in list(results)[:5]]


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        return living._locale(bot, ctx)
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _favorite_names(world_data: MutableMapping[str, Any], guild_id: int, user_id: int) -> List[str]:
    row = _living_user(world_data, guild_id, user_id)
    favs = row.setdefault("favorites", [])
    if not isinstance(favs, list):
        favs = []
        row["favorites"] = favs
    # Preserve order while dropping stale duplicates.
    seen: set[str] = set()
    cleaned: List[str] = []
    for value in favs:
        name = _clean_command_name(value)
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            cleaned.append(name)
    row["favorites"] = cleaned[-MAX_FAVORITES:]
    return row["favorites"]


def _toggle_favorite(bot: commands.Bot, world_data: MutableMapping[str, Any], save_data: Any, guild_id: int, user_id: int, command_name: str) -> Tuple[bool, str]:
    cmd = _visible_command(bot, command_name)
    if cmd is None:
        return False, "현재 버전에서 이 기능을 찾지 못했습니다."
    canonical = str(cmd.qualified_name)
    favs = _favorite_names(world_data, guild_id, user_id)
    matched = next((name for name in favs if name.casefold() == canonical.casefold()), None)
    if matched is not None:
        favs.remove(matched)
        save_data()
        return False, f"☆ `!{canonical}`을 즐겨찾기에서 제거했습니다."
    favs.append(canonical)
    del favs[:-MAX_FAVORITES]
    save_data()
    return True, f"⭐ `!{canonical}`을 즐겨찾기에 저장했습니다."


def _recent_names(world_data: MutableMapping[str, Any], guild_id: int, user_id: int) -> List[str]:
    row = _living_user(world_data, guild_id, user_id)
    recent = row.get("recent", []) if isinstance(row.get("recent"), list) else []
    out: List[str] = []
    seen: set[str] = set()
    for item in reversed(recent[-MAX_RECENT:]):
        if not isinstance(item, Mapping):
            continue
        name = _clean_command_name(item.get("name"))
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out


def _recommendation_rows(bot: commands.Bot, user_data: Mapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, user_id: int) -> List[Tuple[CommandEntry, str]]:
    user = user_data.get(str(user_id)) if isinstance(user_data, Mapping) else None
    candidates: List[Tuple[str, str]] = []

    if not isinstance(user, Mapping):
        candidates.extend([
            ("가입", "생존자 등록부터 시작"),
            ("첫10분", "처음 10분 동선을 한눈에 확인"),
            ("명령어", "전체 생존 지휘 메뉴 열기"),
        ])
    else:
        today = datetime.now(KST).date().isoformat()
        last_attendance = str(user.get("last_attendance", "") or "")[:10]
        tutorial = user.get("tutorial", {}) if isinstance(user.get("tutorial"), Mapping) else {}
        story = user.get("story", {}) if isinstance(user.get("story"), Mapping) else {}
        daily = user.get("daily_quest", {}) if isinstance(user.get("daily_quest"), Mapping) else {}
        equipment = user.get("equipment", {}) if isinstance(user.get("equipment"), Mapping) else {}
        stamina = int(user.get("stamina", 100) or 0)
        level = int(user.get("level", 1) or 1)

        if last_attendance != today:
            candidates.append(("출석", "오늘 출석 보상을 아직 받지 않음"))
        if not bool(tutorial.get("completed", False)):
            candidates.append(("첫10분", "초보 생존 동선이 아직 진행 중"))
        if not bool(story.get("started", False)):
            candidates.append(("스토리나침반", "메인 스토리 첫 진행 추천"))
        elif not bool(story.get("completed", False)):
            candidates.append(("스토리나침반", "현재 스토리에서 다음 목표 확인"))
        if not bool(daily.get("claimed", False)):
            candidates.append(("오늘할일", "오늘 받을 수 있는 보상/퀘스트 확인"))
        if not any(equipment.values()):
            candidates.append(("장비목록", "아직 장착 장비가 없어 장비 확인 추천"))
        if stamina < 35:
            candidates.append(("휴식", "스태미나가 낮아 회복 추천"))
        if level <= 5:
            candidates.append(("채집센터", "초반 자원 확보에 가장 쉬운 루트"))
            candidates.append(("던전", "초반 전투 진행과 성장 확인"))
        else:
            candidates.append(("오늘의세계", "현재 세계 변화와 공동 목표 확인"))
            candidates.append(("생존허브", "스토리·상태·경제·다음 행동 통합 확인"))

        # Personal habits fill the tail, not the first recommendation.
        favs = _favorite_names(world_data, guild_id, user_id)
        for name in favs:
            candidates.append((name, "내 즐겨찾기에서 빠른 재실행"))
        mine = _ux_user(world_data, user_id)
        counts = mine.get("command_counts", {}) if isinstance(mine.get("command_counts"), Mapping) else {}
        for name, _count in sorted(counts.items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0])))[:5]:
            candidates.append((str(name), "내가 자주 사용하는 기능"))

    rows: List[Tuple[CommandEntry, str]] = []
    seen: set[str] = set()
    for name, reason in candidates:
        entry = _entry_for_command(bot, name)
        if entry is None or entry.qualified_name in seen:
            continue
        seen.add(entry.qualified_name)
        rows.append((entry, reason))
        if len(rows) >= 8:
            break
    return rows


async def _run(bot: commands.Bot, interaction: discord.Interaction, command_name: str) -> None:
    await discovery._run_entry(bot, interaction, command_name)


class _CommandButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, entry: CommandEntry, index: int, digest: str, row: int = 0) -> None:
        _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
        super().__init__(
            label=_short(entry.qualified_name, 70),
            emoji=emoji,
            style=discord.ButtonStyle.primary if index == 0 else discord.ButtonStyle.secondary,
            custom_id=f"abaddon:v1860:run:{digest}:{index}",
            row=row,
        )
        self.bot = bot
        self.command_name = entry.qualified_name

    async def callback(self, interaction: discord.Interaction) -> None:
        await _run(self.bot, interaction, self.command_name)


class _CommandSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, rows: Sequence[CommandEntry], digest: str) -> None:
        self.bot = bot
        options: List[discord.SelectOption] = []
        for entry in list(rows)[:MAX_PANEL_RESULTS]:
            _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(discord.SelectOption(
                label=_short(f"!{entry.qualified_name}", 100),
                value=entry.qualified_name,
                emoji=emoji,
                description=_short(_trim_help(entry, 96), 100),
            ))
        super().__init__(
            placeholder=f"기능 {len(options)}개 · 선택하면 바로 실행",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"abaddon:v1860:select:{digest}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _run(self.bot, interaction, str(self.values[0]))


class PersonalCommandView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, rows: Sequence[CommandEntry], key: str) -> None:
        super().__init__(timeout=900)
        self.owner_id = int(owner_id)
        digest = hashlib.sha1(f"{key}:{owner_id}".encode("utf-8", errors="ignore")).hexdigest()[:10]
        for idx, entry in enumerate(list(rows)[:CORE_BUTTONS]):
            self.add_item(_CommandButton(bot, entry, idx, digest))
        if rows:
            self.add_item(_CommandSelect(bot, rows, digest))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message("이 패널은 패널을 연 생존자 전용입니다. `!추천` 또는 `!최근`을 직접 실행해주세요.", ephemeral=True)
        return False


def _favorites_embed(locale: str, entries: Sequence[CommandEntry], max_count: int = MAX_FAVORITES) -> discord.Embed:
    embed = discord.Embed(
        title=_t(locale, "⭐ 내 생존 즐겨찾기", "⭐ My Survival Favorites"),
        description=_t(locale, "자주 쓰는 기능을 버튼이나 드롭다운에서 바로 다시 실행할 수 있습니다.", "Run your saved features again from buttons or the dropdown."),
        color=0xF39C12,
    )
    if entries:
        embed.add_field(name=_t(locale, "저장된 기능", "Saved features"), value="\n".join(f"• `!{e.qualified_name}` — {_trim_help(e)}" for e in entries[:12])[:1024], inline=False)
    else:
        embed.add_field(name=_t(locale, "아직 비어 있습니다", "Nothing saved yet"), value=_t(locale, "`!즐겨찾기 추가 채집` 또는 스마트 탐색 결과의 **⭐ 상위 기능 저장** 버튼을 사용하세요.", "Use `!favorites add gather` or the **Save top feature** button in smart search."), inline=False)
    embed.set_footer(text=_t(locale, f"최대 {max_count}개 · 추가/삭제: !즐겨찾기 추가|삭제 <명령어>", f"Up to {max_count} · add/remove with !favorites add|remove <command>"))
    return embed


def _recent_embed(locale: str, entries: Sequence[CommandEntry]) -> discord.Embed:
    embed = discord.Embed(
        title=_t(locale, "🕘 최근 사용 기능", "🕘 Recently Used"),
        description=_t(locale, "방금 쓰던 기능으로 바로 돌아갈 수 있습니다.", "Jump straight back to what you were using."),
        color=0x566573,
    )
    if entries:
        embed.add_field(name=_t(locale, "최근 기록", "Recent"), value="\n".join(f"• `!{e.qualified_name}` — {_trim_help(e)}" for e in entries[:12])[:1024], inline=False)
    else:
        embed.description = _t(locale, "아직 최근 명령 기록이 없습니다.", "No recent command history yet.")
    embed.set_footer(text=_t(locale, "상위 버튼 또는 드롭다운을 누르면 바로 다시 실행됩니다.", "Use a quick button or dropdown to run it again."))
    return embed


def _recommend_embed(locale: str, rows: Sequence[Tuple[CommandEntry, str]], title: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(
        title=title or _t(locale, "🎯 지금 할 만한 것", "🎯 Recommended Now"),
        description=_t(locale, "현재 생존 상태 + 최근 사용 습관을 보고 다음 행동을 골랐습니다.", "Picked from your current survival state and recent usage habits."),
        color=0x57F287,
    )
    if rows:
        lines = [f"**{idx}.** `!{entry.qualified_name}` — {reason}" for idx, (entry, reason) in enumerate(rows, 1)]
        embed.add_field(name=_t(locale, "추천 순서", "Suggested order"), value="\n".join(lines)[:1024], inline=False)
    else:
        embed.description = _t(locale, "추천할 공개 기능을 찾지 못했습니다. `!명령어`를 이용해주세요.", "No public recommendation is available. Use `!commands`.")
    embed.set_footer(text=_t(locale, "첫 버튼이 현재 가장 우선순위가 높은 추천입니다.", "The first button is the highest-priority suggestion."))
    return embed


def _popular_entries(bot: commands.Bot, world_data: MutableMapping[str, Any], limit: int = 12) -> List[CommandEntry]:
    counts = _root(world_data).get("command_counts", {})
    if not isinstance(counts, Mapping):
        return []
    names = [name for name, _count in sorted(counts.items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0])))[:50]]
    rows = _entries_for_names(bot, names)
    return rows[:limit]


def register_v1860_ux_retention(
    bot: commands.Bot,
    user_data: Mapping[str, Any],
    world_data: MutableMapping[str, Any],
    save_data: Any,
) -> None:
    if getattr(bot, "_abaddon_v1860_registered", False):
        return
    bot._abaddon_v1860_registered = True
    bot.abaddon_version = VERSION
    _root(world_data)

    # Hooks consumed by v18.5.2 smart discovery.
    def rank_hook(user_id: int, rows: Sequence[CommandEntry]) -> List[CommandEntry]:
        return _rank_personal(world_data, int(user_id), rows)

    def search_hook(user_id: int, query: str, rows: Sequence[CommandEntry]) -> None:
        _record_search(world_data, int(user_id), query, rows)

    def favorite_hook(user_id: int, guild_id: int, command_name: str) -> Tuple[bool, str]:
        return _toggle_favorite(bot, world_data, save_data, int(guild_id or 0), int(user_id), command_name)

    bot.v1860_rank_search_results = rank_hook
    bot.v1860_record_search = search_hook
    bot.v1860_toggle_favorite = favorite_hook

    @bot.listen("on_command_completion")
    async def v1860_track_completion(ctx: commands.Context) -> None:
        if ctx.command is None or getattr(ctx.author, "bot", False):
            return
        name = str(ctx.command.qualified_name)
        _record_command(world_data, int(ctx.author.id), name)
        # The existing v16.2 listener also saves after completion. This explicit
        # periodic flush guarantees telemetry persists even if listener order
        # changes in a future discord.py build.
        row = _root(world_data)
        ticks = int(row.get("dirty_ticks", 0) or 0) + 1
        row["dirty_ticks"] = ticks
        if ticks % 10 == 0:
            save_data()

    # Upgrade the old text-only favorites command in place so all old aliases
    # and saved data remain valid.
    favorites = bot.get_command("즐겨찾기")
    if favorites is not None:
        previous_favorites = favorites.callback

        async def favorites_v1860(ctx: commands.Context, 동작: str = "목록", *, 명령: str = "") -> None:
            loc = _locale(bot, ctx)
            guild_id = int(getattr(ctx.guild, "id", 0) or 0)
            action = str(동작 or "목록").strip().casefold()
            raw = _clean_command_name(명령)
            if action in {"추가", "add", "+"} and raw:
                cmd = _visible_command(bot, raw)
                if cmd is None:
                    await ctx.send(_t(loc, f"❌ `!{raw}`는 정확한 명령이 아닙니다. 대신 관련 기능을 찾아드릴게요.", f"❌ `!{raw}` is not an exact command. Here are related features instead."))
                    await discovery._send_search(ctx, raw)
                    return
                added, message = _toggle_favorite(bot, world_data, save_data, guild_id, int(ctx.author.id), cmd.qualified_name)
                if not added and message.startswith("☆"):
                    # Explicit add should remain add: toggling an existing entry
                    # above removes it, so restore it for predictable semantics.
                    _toggle_favorite(bot, world_data, save_data, guild_id, int(ctx.author.id), cmd.qualified_name)
                    message = f"⭐ `!{cmd.qualified_name}`은 이미 즐겨찾기에 있습니다."
                await ctx.send(message)
            elif action in {"삭제", "제거", "remove", "delete", "-"} and raw:
                cmd = _visible_command(bot, raw)
                canonical = str(cmd.qualified_name) if cmd else raw
                favs = _favorite_names(world_data, guild_id, int(ctx.author.id))
                before = len(favs)
                favs[:] = [name for name in favs if name.casefold() != canonical.casefold()]
                if len(favs) != before:
                    save_data()
                    await ctx.send(f"☆ `!{canonical}`을 즐겨찾기에서 제거했습니다.")
                else:
                    await ctx.send(f"⚠️ `!{canonical}`은 즐겨찾기에 없습니다.")
            names = _favorite_names(world_data, guild_id, int(ctx.author.id))
            entries = _entries_for_names(bot, names)
            await ctx.send(embed=_favorites_embed(loc, entries), view=PersonalCommandView(bot, ctx.author.id, entries, "favorites") if entries else None)

        favorites.callback = favorites_v1860
        favorites.help = "자주 쓰는 기능을 최대 12개 저장하고 버튼/드롭다운으로 바로 실행합니다."
        favorites.description = favorites.help
        favorites.extras = dict(getattr(favorites, "extras", {}) or {})
        favorites.extras["v1860_previous_callback"] = previous_favorites

    recent = bot.get_command("최근명령")
    if recent is not None:
        previous_recent = recent.callback

        async def recent_v1860(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            guild_id = int(getattr(ctx.guild, "id", 0) or 0)
            names = _recent_names(world_data, guild_id, int(ctx.author.id))
            entries = _entries_for_names(bot, names)
            await ctx.send(embed=_recent_embed(loc, entries), view=PersonalCommandView(bot, ctx.author.id, entries, "recent") if entries else None)

        recent.callback = recent_v1860
        recent.help = "최근 사용한 기능을 버튼/드롭다운으로 다시 실행합니다."
        recent.description = recent.help
        recent.extras = dict(getattr(recent, "extras", {}) or {})
        recent.extras["v1860_previous_callback"] = previous_recent

    @bot.command(name="최근", aliases=["최근기능", "recent"], help="최근 사용 기능을 버튼/드롭다운으로 다시 실행합니다.")
    async def recent_shortcut(ctx: commands.Context) -> None:
        command = bot.get_command("최근명령")
        if command is not None:
            await ctx.invoke(command)

    @bot.command(name="추천", aliases=["추천기능", "recommend", "recommendme"], help="현재 생존 상태와 사용 습관에 맞춰 할 만한 기능을 추천합니다.")
    async def recommend(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        rows = _recommendation_rows(bot, user_data, world_data, guild_id, int(ctx.author.id))
        entries = [entry for entry, _reason in rows]
        await ctx.send(embed=_recommend_embed(loc, rows), view=PersonalCommandView(bot, ctx.author.id, entries, "recommend") if entries else None)

    @bot.command(name="다음할일", aliases=["다음추천", "nextaction", "whatnext"], help="지금 가장 우선순위가 높은 다음 행동 하나를 추천합니다.")
    async def next_action(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        rows = _recommendation_rows(bot, user_data, world_data, guild_id, int(ctx.author.id))[:1]
        entries = [entry for entry, _reason in rows]
        await ctx.send(embed=_recommend_embed(loc, rows, _t(loc, "🧭 지금 이거부터", "🧭 Do This Next")), view=PersonalCommandView(bot, ctx.author.id, entries, "next") if entries else None)

    @bot.command(name="인기기능", aliases=["인기명령", "popularfeatures", "popularcommands"], help="v18.6 이후 실제 사용량이 많은 공개 기능을 보여줍니다.")
    async def popular_features(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        entries = _popular_entries(bot, world_data)
        counts = _root(world_data).get("command_counts", {}) if isinstance(_root(world_data).get("command_counts"), Mapping) else {}
        embed = discord.Embed(title=_t(loc, "🔥 지금 많이 쓰는 기능", "🔥 Popular Features"), color=0xED4245)
        if entries:
            embed.description = "\n".join(f"**{i}.** `!{e.qualified_name}` · {int(counts.get(e.qualified_name, 0) or 0):,}회" for i, e in enumerate(entries, 1))
            embed.set_footer(text=_t(loc, "v18.6.0 배포 이후 실제 완료된 명령 기준", "Based on completed commands since v18.6.0 deployment"))
        else:
            embed.description = _t(loc, "아직 충분한 사용 기록이 없습니다. 조금 사용하면 자동으로 채워집니다.", "Not enough usage data yet. It will fill automatically as people use the bot.")
        await ctx.send(embed=embed, view=PersonalCommandView(bot, ctx.author.id, entries, "popular") if entries else None)

    @bot.command(name="UX통계", aliases=["uxstats", "retentionstats"], hidden=True, help="[소유자 전용] 명령/검색 사용 통계를 확인합니다.")
    @commands.is_owner()
    async def ux_stats(ctx: commands.Context) -> None:
        root = _root(world_data)
        commands_top = sorted((root.get("command_counts") or {}).items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0])))[:10]
        searches_top = sorted((root.get("search_counts") or {}).items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0])))[:10]
        embed = discord.Embed(title="📊 ABADDON UX 사용 통계", color=0x5865F2)
        embed.add_field(name="명령 TOP", value="\n".join(f"`!{name}` · {int(count):,}회" for name, count in commands_top) or "기록 없음", inline=False)
        embed.add_field(name="검색 TOP", value="\n".join(f"`{query}` · {int(count):,}회" for query, count in searches_top) or "기록 없음", inline=False)
        embed.add_field(name="개인화 사용자", value=f"**{len(root.get('users', {})):,}명**", inline=True)
        await ctx.send(embed=embed)

    # Update the owner checklist from v18.5.1 so each future deploy has one
    # obvious first command to run.
    patch_check = bot.get_command("패치점검")
    if patch_check is not None:
        previous_patch_check = patch_check.callback

        async def patch_check_v1860(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            embed = discord.Embed(
                title=_t(loc, "🧪 ABADDON v18.6.0 점검 목록", "🧪 ABADDON v18.6.0 test checklist"),
                description=_t(loc, "이번 배포 후 아래 순서만 확인하면 UX 패치 핵심을 빠르게 검수할 수 있습니다.", "Run these in order after deployment to verify the UX update."),
                color=0xFEE75C,
            )
            checks = [
                ("1) !로그", "없는 명령어 → 스마트 관련기능 버튼/드롭다운"),
                ("2) !즐겨찾기 추가 채집 → !즐겨찾기", "저장 후 버튼/드롭다운 즉시 실행"),
                ("3) !최근", "최근 사용 기능 패널 재실행"),
                ("4) !추천 → !다음할일", "상태 기반 추천과 첫 추천 버튼"),
                ("5) !인기기능", "실사용 집계 패널"),
                ("6) !명령어 / !help", "한글·영문 영구 메뉴 및 검색 회귀"),
                ("7) !커뮤니티센터", "문의 모달 → 제작자 DM 전달"),
                ("8) !웹대시보드", "홈페이지/대시보드 주소 연결"),
            ]
            for name, value in checks:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=_t(loc, "소유자 최종 정적검수: !1860검수", "Owner static/runtime audit: !1860audit"))
            await ctx.send(embed=embed)

        patch_check.callback = patch_check_v1860
        patch_check.help = "현재 v18.6.0 배포 후 직접 확인해야 할 핵심 테스트 목록입니다."
        patch_check.description = patch_check.help
        patch_check.extras = dict(getattr(patch_check, "extras", {}) or {})
        patch_check.extras["v1860_previous_callback"] = previous_patch_check

    @bot.command(name="1860검수", aliases=["1860audit", "uxaudit"], hidden=True, help="[봇 소유자 전용] v18.6 UX/Retention 기능 연결 상태를 검사합니다.")
    @commands.is_owner()
    async def audit(ctx: commands.Context) -> None:
        required = ["즐겨찾기", "최근명령", "최근", "추천", "다음할일", "인기기능", "기능찾기", "패치점검"]
        rows = [(name, bot.get_command(name) is not None) for name in required]
        hooks = [
            ("search rank", callable(getattr(bot, "v1860_rank_search_results", None))),
            ("search telemetry", callable(getattr(bot, "v1860_record_search", None))),
            ("favorite hook", callable(getattr(bot, "v1860_toggle_favorite", None))),
        ]
        samples = []
        for query in ("로그", "채집", "길드"):
            found = discovery.search_entries(bot, query)
            samples.append((query, len(found)))
        embed = discord.Embed(title="🧪 ABADDON v18.6.0 UX/RETENTION 검수", color=0x57F287 if all(ok for _, ok in rows + hooks) else 0xFEE75C)
        embed.description = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in rows + hooks)
        embed.add_field(name="스마트 검색 샘플", value=" · ".join(f"`{q}` {n}개" for q, n in samples), inline=False)
        embed.add_field(name="Telemetry", value=f"commands={sum(int(x or 0) for x in (_root(world_data).get('command_counts') or {}).values())} · searches={sum(int(x or 0) for x in (_root(world_data).get('search_counts') or {}).values())}", inline=False)
        await ctx.send(embed=embed)

    # Refresh public help registries after new commands are present.
    try:
        hub._refresh_registry(bot)
    except Exception:
        pass
    try:
        from apocalypse_bot.commands.v1832_bilingual_persistent_hub import _sync_registry
        _sync_registry(bot)
    except Exception:
        pass

    print(
        f"[ABADDON v{VERSION}] UX/retention registered · favorites=buttons recent=buttons recommendations=contextual "
        f"smart-ranking=personalized telemetry=commands+searches",
        flush=True,
    )


def finalize_v1860_surfaces(bot: commands.Bot) -> None:
    """Keep bot info and patch notes aligned with the latest public version."""
    bot.abaddon_version = VERSION

    intro = bot.get_command("봇소개")
    if intro is not None:
        async def intro_v1860(ctx: commands.Context) -> None:
            locale = "ko"
            try:
                locale = living._locale(bot, ctx)
            except Exception:
                pass
            embed = discord.Embed(
                title=_t(locale, "☣️ ABADDON · 종말 생존 플랫폼", "☣️ ABADDON · Apocalypse Survival Platform"),
                description=_t(locale, "1,400개가 넘는 기능을 외우지 않아도 됩니다. 검색·즐겨찾기·최근·추천이 다음 행동까지 이어줍니다.", "You do not need to memorize 1,400+ features. Search, favorites, recents and recommendations lead you to the next action."),
                color=0xC8AA62,
            )
            fields = [
                ("🔎 스마트 탐색", "`!로그`처럼 정확한 명령이 아니어도 관련 기능 자동 탐색"),
                ("⭐ 빠른 재진입", "`!즐겨찾기` · `!최근`"),
                ("🎯 개인 추천", "`!추천` · `!다음할일`"),
                ("🔥 실사용 인기", "`!인기기능`"),
                ("🏠 서버/커뮤니티", "`!서버설정` · `!커뮤니티센터` · `!웹대시보드`"),
                ("🛟 장애 문의", "Discord DM `jjonga0022`"),
            ]
            for name, value in fields:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=f"ABADDON v{VERSION} · UX/RETENTION · support @jjonga0022")
            await ctx.send(embed=embed)
        intro.callback = intro_v1860
        intro.help = "ABADDON v18.6 최신 탐색·추천·즐겨찾기·커뮤니티 기능을 확인합니다."
        intro.description = intro.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1860(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            embed = discord.Embed(title="🎯 ABADDON v18.6.0 — UX / RETENTION", color=0x5865F2)
            embed.description = "기능을 더 늘리기보다 **찾기 → 저장 → 다시 실행 → 다음 추천** 흐름을 빠르게 만든 사용성 패치입니다."
            embed.add_field(name="🔎 스마트 탐색 개인화", value="`!로그` 같은 넓은 검색어 결과에 개인 사용 습관을 가볍게 반영", inline=False)
            embed.add_field(name="⭐ 즐겨찾기", value="최대 12개 · 버튼/드롭다운 실행 · 스마트 탐색에서 상위 기능 저장", inline=False)
            embed.add_field(name="🕘 최근", value="최근 사용 기능을 버튼/드롭다운으로 즉시 재실행", inline=False)
            embed.add_field(name="🎯 추천 / 다음할일", value="가입·출석·튜토리얼·스토리·장비·스태미나·사용 습관 기반", inline=False)
            embed.add_field(name="📊 사용성 통계", value="완료 명령/검색어를 집계해 `!인기기능`과 소유자 `!UX통계`에 반영", inline=False)
            embed.add_field(name="🧪 배포 후 검수", value="`!패치점검` → 소유자 `!1860검수`", inline=False)
            embed.set_footer(text="기존 유저 데이터/즐겨찾기/최근기록 유지 · /var/data 유지")
            await ctx.send(embed=embed)
        patch.callback = patch_v1860
        patch.help = "ABADDON v18.6.0 UX/Retention 패치노트입니다."
        patch.description = patch.help

    print(f"[ABADDON v{VERSION}] final public UX surfaces active", flush=True)
