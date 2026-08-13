from __future__ import annotations

"""ABADDON v18.6.0 smart command discovery.

Turns unknown prefix terms such as ``!로그`` or ``!채집`` into a lightweight
feature finder instead of a dead-end CommandNotFound message. Existing commands
still execute normally; this module only handles names Discord.py could not
resolve.
"""

from dataclasses import dataclass
import difflib
import hashlib
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _command_requires_input, _invoke_command
from apocalypse_bot.commands.v1630_core_rpg_command_city_overhaul import CommandEntry, _group_spec, _short
from apocalypse_bot.commands import v1831_persistent_command_hub as hub

VERSION = "18.6.0"
PREFIX = "abaddon:v1852"
MAX_RESULTS = 25
CORE_BUTTONS = 4

# Query expansion is intentionally compact and gameplay-oriented. The generic
# scorer still works for any arbitrary word, while these families improve broad
# user phrases that may not literally exist in a command name.
SYNONYM_FAMILIES: Mapping[str, Tuple[str, ...]] = {
    "로그": ("로그", "기록", "사용", "감사", "오류", "통계", "history", "audit", "usage", "log"),
    "기록": ("기록", "로그", "내역", "history", "record", "log"),
    "채집": ("채집", "벌목", "채광", "낚시", "수렵", "땅파기", "농사", "gather", "mining", "fishing"),
    "장비": ("장비", "무기", "방어구", "강화", "제작", "인벤토리", "equipment", "gear", "weapon"),
    "길드": ("길드", "연합", "파티", "레이드", "guild", "alliance", "party", "raid"),
    "경제": ("경제", "식량", "코인", "시장", "거래", "암시장", "판매", "구매", "economy", "market", "trade"),
    "관리": ("관리", "서버", "운영", "권한", "보안", "로그", "모더레이션", "admin", "server", "moderation"),
    "문의": ("문의", "버그", "신고", "지원", "ticket", "support", "report", "bug"),
    "도박": ("도박", "경마", "룰렛", "지뢰", "배팅", "선물거래", "gambling", "bet", "roulette"),
    "카지노": ("카지노", "블랙잭", "바카라", "포커", "화투", "casino", "blackjack", "poker"),
    "세계": ("세계", "지도", "지역", "도시", "세력", "재난", "world", "map", "city", "faction"),
    "스토리": ("스토리", "시즌", "챕터", "캠페인", "story", "season", "chapter", "campaign"),
    "전투": ("전투", "던전", "보스", "레이드", "pvp", "combat", "battle", "boss"),
    "펫": ("펫", "동료", "친밀도", "훈련", "pet", "companion"),
    "음성": ("음성", "보이스", "임시음성", "voice", "temp voice"),
    "역할": ("역할", "버튼역할", "role", "roles"),
}


def _clean_query(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "").strip())
    return value[:80]


def _query_terms(query: str) -> List[str]:
    q = _clean_query(query).casefold()
    base = [x for x in re.split(r"[\s/_-]+", q) if x]
    expanded: List[str] = list(base)
    for key, values in SYNONYM_FAMILIES.items():
        if key.casefold() in q or any(x.casefold() == q for x in values):
            expanded.extend(x.casefold() for x in values)
    # stable de-duplication
    out: List[str] = []
    seen: set[str] = set()
    for term in expanded:
        if term and term not in seen:
            seen.add(term)
            out.append(term)
    return out


def _entry_blob(entry: CommandEntry) -> str:
    return " ".join(
        (
            entry.qualified_name,
            entry.name,
            " ".join(entry.aliases),
            entry.help_text,
            entry.signature,
            entry.section,
            entry.group,
            entry.search_blob,
        )
    ).casefold()


def _score_entry(query: str, entry: CommandEntry) -> int:
    q = _clean_query(query).casefold()
    if not q:
        return 0
    qname = entry.qualified_name.casefold()
    name = entry.name.casefold()
    aliases = [str(x).casefold() for x in entry.aliases]
    blob = _entry_blob(entry)
    score = 0

    if q == qname or q == name:
        score += 300
    if q in aliases:
        score += 260
    if qname.startswith(q):
        score += 180
    elif q in qname:
        score += 130
    if name.startswith(q):
        score += 120
    elif q in name:
        score += 90
    if any(a.startswith(q) for a in aliases):
        score += 100
    elif any(q in a for a in aliases):
        score += 75
    if q in entry.help_text.casefold():
        score += 65

    # Broad concept words get useful related commands, not just lexical clones.
    for term in _query_terms(q):
        if term == q:
            continue
        if term == qname or term == name or term in aliases:
            score += 80
        elif term in qname or term in name or any(term in a for a in aliases):
            score += 42
        elif term in blob:
            score += 16

    # Typo tolerance for short command-like words.
    if len(q) >= 2:
        ratio = difflib.SequenceMatcher(None, q, qname).ratio()
        if ratio >= 0.82:
            score += int(75 * ratio)
        elif ratio >= 0.68:
            score += int(35 * ratio)

    # Avoid surfacing owner/admin-only diagnostics as the first thing a normal
    # user sees unless the query explicitly asks for admin/audit/error/log work.
    if entry.restricted and not any(k in q for k in ("관리", "로그", "오류", "검수", "admin", "audit", "error", "log")):
        score -= 18
    return max(0, score)


def search_entries(bot: commands.Bot, query: str) -> List[CommandEntry]:
    rows = hub._visible_entries(bot)
    scored = [( _score_entry(query, entry), entry) for entry in rows]
    scored = [row for row in scored if row[0] > 0]
    scored.sort(key=lambda row: (-row[0], row[1].qualified_name.casefold()))
    return [entry for _score, entry in scored[:MAX_RESULTS]]


def _trim_help(entry: CommandEntry, limit: int = 72) -> str:
    text = " ".join(str(entry.help_text or "설명 없음").split())
    return _short(text, limit)


def _result_embed(query: str, results: Sequence[CommandEntry]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔎 ABADDON 기능 탐색 · {query}",
        description=(
            f"`!{query}`는 정확한 명령어가 아니지만 **관련 기능을 찾아봤습니다.**\n"
            "위쪽 **핵심 기능 버튼**을 바로 누르거나, 아래 드롭다운에서 원하는 기능을 골라 실행하세요."
        ),
        color=0x5865F2,
    )
    if not results:
        embed.description = (
            f"`!{query}`와 연결되는 기능을 충분히 찾지 못했습니다.\n"
            "`!명령어`의 검색 버튼이나 `!기능찾기 <검색어>`를 사용해주세요."
        )
        embed.set_footer(text="예: !기능찾기 로그 · !기능찾기 장비 · !기능찾기 길드")
        return embed

    lines: List[str] = []
    for idx, entry in enumerate(results[:10], start=1):
        _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
        lock = " 🔒" if entry.restricted else ""
        lines.append(f"{emoji} **{idx}.** `!{entry.qualified_name}`{lock} — {_trim_help(entry)}")
    embed.add_field(name=f"관련 기능 {len(results)}개", value="\n".join(lines)[:1024], inline=False)
    embed.add_field(
        name="💡 사용법",
        value="버튼 = 상위 핵심 기능 즉시 실행 · 드롭다운 = 관련 기능 전체 선택 · 입력이 필요한 기능은 입력창 자동 표시",
        inline=False,
    )
    embed.set_footer(text="ABADDON v18.6.0 · 개인화 탐색 + 없는 !단어도 검색어로 사용 가능")
    return embed


async def _run_entry(bot: commands.Bot, interaction: discord.Interaction, command_name: str) -> None:
    command = bot.get_command(command_name)
    if command is None:
        await hub._notice(interaction, "현재 버전에서 이 기능을 찾지 못했습니다. 다시 검색해주세요.")
        return
    if _command_requires_input(command):
        try:
            await interaction.response.send_modal(hub.HubArgsModal(bot, command.qualified_name))
        except Exception:
            await hub._notice(interaction, f"입력이 필요한 기능입니다. `!{command.qualified_name} {getattr(command, 'signature', '')}` 형식으로 실행해주세요.")
        return
    await _invoke_command(bot, interaction, command.qualified_name)


class SmartResultButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, entry: CommandEntry, index: int, digest: str) -> None:
        _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
        super().__init__(
            label=_short(entry.qualified_name, 70),
            emoji=emoji,
            style=discord.ButtonStyle.primary if index == 0 else discord.ButtonStyle.secondary,
            custom_id=f"{PREFIX}:quick:{digest}:{index}",
            row=0,
        )
        self.bot = bot
        self.command_name = entry.qualified_name

    async def callback(self, interaction: discord.Interaction) -> None:
        await _run_entry(self.bot, interaction, self.command_name)


class SmartResultSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, query: str, results: Sequence[CommandEntry], digest: str) -> None:
        self.bot = bot
        options: List[discord.SelectOption] = []
        for entry in list(results)[:MAX_RESULTS]:
            _sec, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(
                discord.SelectOption(
                    label=_short(f"!{entry.qualified_name}", 100),
                    value=entry.qualified_name,
                    emoji=emoji,
                    description=_short(_trim_help(entry, 96), 100),
                )
            )
        super().__init__(
            placeholder=f"관련 기능 {len(options)}개 · 선택하면 실행",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{PREFIX}:select:{digest}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _run_entry(self.bot, interaction, str(self.values[0]))


class SmartSearchAgainButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, digest: str) -> None:
        super().__init__(
            label="다른 기능 검색",
            emoji="🔎",
            style=discord.ButtonStyle.success,
            custom_id=f"{PREFIX}:again:{digest}",
            row=2,
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(hub.HubSearchModal(self.bot))


class SmartAllMenuButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, digest: str) -> None:
        super().__init__(
            label="전체 메뉴",
            emoji="☣️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{PREFIX}:all:{digest}",
            row=2,
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        entries = hub._visible_entries(self.bot)
        try:
            await interaction.response.send_message(embed=hub._root_embed(entries), view=hub.PersistentRootHubView(self.bot), ephemeral=True)
        except Exception:
            await hub._notice(interaction, "`!명령어`를 입력해 전체 기능 메뉴를 열어주세요.")


class SmartFavoriteTopButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, entry: CommandEntry, digest: str) -> None:
        super().__init__(
            label="상위 기능 저장",
            emoji="⭐",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{PREFIX}:favorite:{digest}",
            row=2,
        )
        self.bot = bot
        self.command_name = entry.qualified_name

    async def callback(self, interaction: discord.Interaction) -> None:
        hook = getattr(self.bot, "v1860_toggle_favorite", None)
        if not callable(hook):
            await hub._notice(interaction, "즐겨찾기 기능이 아직 준비되지 않았습니다. `!즐겨찾기`를 사용해주세요.")
            return
        guild_id = int(getattr(interaction.guild, "id", 0) or 0)
        _added, message = hook(int(interaction.user.id), guild_id, self.command_name)
        await interaction.response.send_message(message, ephemeral=True)


class SmartDiscoveryView(discord.ui.View):
    def __init__(self, bot: commands.Bot, query: str, results: Sequence[CommandEntry]) -> None:
        super().__init__(timeout=900)
        digest = hashlib.sha1(query.encode("utf-8", errors="ignore")).hexdigest()[:10]
        for idx, entry in enumerate(list(results)[:CORE_BUTTONS]):
            self.add_item(SmartResultButton(bot, entry, idx, digest))
        if results:
            self.add_item(SmartResultSelect(bot, query, results, digest))
        self.add_item(SmartSearchAgainButton(bot, digest))
        self.add_item(SmartAllMenuButton(bot, digest))
        if results:
            self.add_item(SmartFavoriteTopButton(bot, results[0], digest))


async def _send_search(ctx: commands.Context, query: str) -> bool:
    query = _clean_query(query)
    if not query:
        return False
    results = search_entries(ctx.bot, query)
    rank_hook = getattr(ctx.bot, "v1860_rank_search_results", None)
    if callable(rank_hook):
        try:
            results = list(rank_hook(int(ctx.author.id), results))[:MAX_RESULTS]
        except Exception:
            pass
    search_hook = getattr(ctx.bot, "v1860_record_search", None)
    if callable(search_hook):
        try:
            search_hook(int(ctx.author.id), query, results)
        except Exception:
            pass
    await ctx.send(embed=_result_embed(query, results), view=SmartDiscoveryView(ctx.bot, query, results))
    return True


def register_v1852_smart_command_discovery(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1852_registered", False):
        return
    bot._abaddon_v1852_registered = True

    async def unknown_handler(ctx: commands.Context, raw_query: str) -> bool:
        try:
            content = str(getattr(ctx.message, "content", "") or "").strip()
            query = content[1:] if content.startswith("!") else raw_query
            return await _send_search(ctx, query)
        except Exception as exc:
            print(f"[ABADDON v{VERSION}] smart discovery failed: {type(exc).__name__}: {exc}", flush=True)
            return False

    setattr(bot, "v1852_unknown_command_handler", unknown_handler)

    @bot.command(
        name="기능찾기",
        aliases=["기능검색", "명령찾기", "스마트검색", "featurefinder", "findfeature"],
        help="명령어 이름을 몰라도 키워드로 관련 기능의 핵심 버튼과 드롭다운을 찾습니다.",
    )
    async def feature_finder(ctx: commands.Context, *, 검색어: str = "") -> None:
        query = _clean_query(검색어)
        if not query:
            await ctx.send("🔎 사용법: `!기능찾기 로그` · `!기능찾기 장비` · `!기능찾기 길드`")
            return
        await _send_search(ctx, query)

    @bot.command(
        name="1852검수",
        aliases=["1852audit", "smartsearchaudit"],
        hidden=True,
        help="[봇 소유자 전용] 스마트 명령 탐색 패치의 핵심 상태를 확인합니다.",
    )
    @commands.is_owner()
    async def audit(ctx: commands.Context) -> None:
        samples = ["로그", "채집", "장비", "길드", "경제", "관리"]
        lines = []
        for query in samples:
            rows = search_entries(bot, query)
            lines.append(f"{'✅' if rows else '❌'} `{query}` → {len(rows)}개" + (f" · `!{rows[0].qualified_name}`" if rows else ""))
        embed = discord.Embed(title="🧪 ABADDON v18.6.0 스마트 탐색 검수", description="\n".join(lines), color=0x57F287)
        embed.add_field(name="Unknown Command Hook", value="✅" if callable(getattr(bot, "v1852_unknown_command_handler", None)) else "❌", inline=True)
        embed.add_field(name="기능찾기", value="✅" if bot.get_command("기능찾기") else "❌", inline=True)
        await ctx.send(embed=embed)

    print(f"[ABADDON v{VERSION}] smart command discovery registered · unknown-prefix-search=True quick-buttons={CORE_BUTTONS} select={MAX_RESULTS}", flush=True)
