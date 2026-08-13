from __future__ import annotations

"""ABADDON v17.2.0 — LIVING WORLD & BROKEN OATHS.

Additive release covering:
- v17.0.1 Creator Forge group registration and classification repair;
- v17.1 living world: time, weather, risk, market, faction tension, daily events;
- v17.2 NPC bonds: schedules, dialogue, gifts, missions, romance and betrayal;
- bilingual Korean/English UI separation and command-center integration.
"""

import hashlib
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands.v600_game_center import _safe_embed, _safe_view
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
from apocalypse_bot.core.rate_limit_guard import should_pause_nonessential

VERSION = "17.2.0"
WORLD_KEY = "living_world_v1710"
BOND_KEY = "npc_bonds_v1720"
KST = timezone(timedelta(hours=9))


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, actor: Any, guild_id: int = 0) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(actor.id), int(guild_id))
    except Exception:
        return "ko"


def _ctx_locale(bot: commands.Bot, ctx: commands.Context) -> str:
    return _locale(bot, ctx.author, int(ctx.guild.id if ctx.guild else 0))


def _server_locale(guild_id: int) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root=global_mod._RUNTIME.get("root",{})
        return global_mod._guild_locale(root,int(guild_id))
    except Exception:
        return "ko"


def _now_ts() -> int:
    return int(time.time())


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _phase() -> str:
    hour = datetime.now(KST).hour
    if 5 <= hour < 9:
        return "dawn"
    if 9 <= hour < 18:
        return "day"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> MutableMapping[str, Any]:
    user = get_user(int(user_id))
    return user if isinstance(user, MutableMapping) else {}


def _is_admin(member: Any, guild: Optional[discord.Guild]) -> bool:
    if guild is None:
        return False
    if int(getattr(member, "id", 0)) == int(getattr(guild, "owner_id", 0)):
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)))


WEATHERS: Tuple[Dict[str, Any], ...] = (
    {"id": "ash", "ko": "재의 비", "en": "Ashfall", "emoji": "🌫️", "gather": 0.90, "market": 1.12, "risk": 9},
    {"id": "clear", "ko": "검은 구름 사이의 맑음", "en": "Clear Break", "emoji": "🌤️", "gather": 1.08, "market": 0.96, "risk": -4},
    {"id": "acid", "ko": "산성 폭우", "en": "Acid Downpour", "emoji": "🌧️", "gather": 0.82, "market": 1.18, "risk": 14},
    {"id": "static", "ko": "전자기 폭풍", "en": "Static Storm", "emoji": "⚡", "gather": 1.02, "market": 1.05, "risk": 11},
    {"id": "cold", "ko": "백색 한파", "en": "White Freeze", "emoji": "❄️", "gather": 0.88, "market": 1.14, "risk": 7},
    {"id": "eclipse", "ko": "검은 태양 잔광", "en": "Black-Sun Afterglow", "emoji": "🌑", "gather": 1.20, "market": 1.20, "risk": 18},
)

REGIONS: Tuple[Tuple[str, str, str], ...] = (
    ("ruins", "폐허 외곽", "Ruins Outskirts"),
    ("black_city", "BLACK CITY", "BLACK CITY"),
    ("harbor", "침수 항구", "Flooded Harbor"),
    ("rail", "황혼 철도", "Twilight Rail"),
    ("abyss", "NEON ABYSS", "NEON ABYSS"),
    ("front", "잿빛 전선", "Ashen Front"),
)

FACTION_CONFLICTS: Tuple[Dict[str, str], ...] = (
    {"id":"guard_syndicate","ko":"잿빛 경비대 ↔ 네온 신디케이트","en":"Ash Guard ↔ Neon Syndicate"},
    {"id":"ark_cult","ko":"백색 방주 ↔ 검은 태양 교단","en":"White Ark ↔ Black Sun Cult"},
    {"id":"harbor_raiders","ko":"항구 조합 ↔ 폐허 약탈단","en":"Harbor Union ↔ Ruin Raiders"},
    {"id":"alliance_abyss","ko":"생존 연합 ↔ 심연 추종자","en":"Survivor Alliance ↔ Abyssal Followers"},
)

WORLD_EVENTS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "signal",
        "title_ko": "동부 폐허의 구조 신호",
        "title_en": "Rescue Signal in the Eastern Ruins",
        "desc_ko": "짧은 구조 신호가 반복됩니다. 교단의 미끼일 가능성도 있습니다.",
        "desc_en": "A short rescue signal repeats. It may be a cult trap.",
        "choices": (
            ("구조대를 보낸다", "Send a rescue team", {"hope": 5, "order": -1, "risk": 3, "food": 9000}),
            ("드론으로 확인한다", "Scout with a drone", {"hope": 1, "order": 4, "risk": -2, "food": 5000}),
            ("신호를 차단한다", "Block the signal", {"hope": -3, "order": 3, "risk": -5, "food": 2000}),
        ),
    },
    {
        "id": "convoy",
        "title_ko": "암시장 보급 호송대",
        "title_en": "Black-Market Supply Convoy",
        "desc_ko": "정체불명의 호송대가 식량과 의약품을 싣고 성벽으로 접근합니다.",
        "desc_en": "An unidentified convoy approaches the wall with food and medicine.",
        "choices": (
            ("통행을 허가한다", "Allow passage", {"hope": 2, "order": -2, "market": -5, "food": 12000}),
            ("물자를 징발한다", "Requisition supplies", {"hope": -2, "order": 5, "market": -2, "food": 15000}),
            ("호송대를 추적한다", "Track the convoy", {"hope": 0, "order": 2, "risk": -3, "food": 7000}),
        ),
    },
    {
        "id": "power",
        "title_ko": "중앙 발전소 과부하",
        "title_en": "Central Plant Overload",
        "desc_ko": "전력망이 붕괴 직전입니다. 도시 전체가 한 구역을 포기해야 할 수 있습니다.",
        "desc_en": "The grid is near collapse. The city may have to abandon one district.",
        "choices": (
            ("병원 전력을 지킨다", "Protect hospital power", {"hope": 4, "order": 1, "power": -3, "food": 8000}),
            ("공방 전력을 지킨다", "Protect workshop power", {"hope": 0, "order": 3, "power": 4, "food": 10000}),
            ("카지노 전력을 끊는다", "Cut casino power", {"hope": 2, "order": 4, "market": 3, "food": 6000}),
        ),
    },
    {
        "id": "cult",
        "title_ko": "검은 태양 교단의 행진",
        "title_en": "March of the Black Sun Cult",
        "desc_ko": "교단이 구호 물자를 나누며 시민을 끌어모으고 있습니다.",
        "desc_en": "The cult distributes aid while gathering citizens.",
        "choices": (
            ("공개 토론을 연다", "Hold a public debate", {"hope": 3, "order": -1, "tension": -3, "food": 7000}),
            ("지도자를 체포한다", "Arrest the leader", {"hope": -2, "order": 5, "tension": 4, "food": 9000}),
            ("잠입 요원을 보낸다", "Send an infiltrator", {"hope": 0, "order": 2, "tension": -2, "food": 11000}),
        ),
    },
)


def _world_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(WORLD_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[WORLD_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    root.setdefault("broadcast_channels", {})
    root.setdefault("broadcast_days", {})
    if not isinstance(root.get("guilds"), MutableMapping):
        root["guilds"] = {}
    if not isinstance(root.get("broadcast_channels"), MutableMapping):
        root["broadcast_channels"] = {}
    if not isinstance(root.get("broadcast_days"), MutableMapping):
        root["broadcast_days"] = {}
    root["version"] = VERSION
    return root


def _daily_rng(guild_id: int, day: str) -> random.Random:
    digest = hashlib.sha256(f"ABADDON-LIVING-WORLD:{guild_id}:{day}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _new_daily_state(guild_id: int, day: str, previous: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    rng = _daily_rng(guild_id, day)
    weather = dict(rng.choice(WEATHERS))
    event = dict(rng.choice(WORLD_EVENTS))
    conflict = dict(rng.choice(FACTION_CONFLICTS))
    old_metrics = previous.get("metrics", {}) if isinstance(previous, Mapping) else {}
    metrics = {
        "hope": max(0, min(100, int(old_metrics.get("hope", 52)) + rng.randint(-4, 4))),
        "order": max(0, min(100, int(old_metrics.get("order", 55)) + rng.randint(-4, 4))),
        "power": max(0, min(100, int(old_metrics.get("power", 68)) + rng.randint(-5, 4))),
        "tension": max(0, min(100, int(old_metrics.get("tension", 38)) + rng.randint(-4, 6))),
    }
    risks: Dict[str, int] = {}
    for rid, _ko, _en in REGIONS:
        base = rng.randint(22, 72)
        if rid == "abyss":
            base += 10
        risks[rid] = max(5, min(99, base + int(weather["risk"])))
    return {
        "day": day,
        "weather": weather,
        "event": event,
        "conflict": conflict,
        "metrics": metrics,
        "risks": risks,
        "market_index": max(70, min(145, 100 + rng.randint(-12, 16) + round((float(weather["market"]) - 1.0) * 100))),
        "participants": {},
        "event_totals": [0, 0, 0],
        "history": list(previous.get("history", []))[-29:] if isinstance(previous, Mapping) else [],
        "generated_at": _now_ts(),
    }


def _apply_season6_echo(world_data: Mapping[str, Any], guild_id: int, state: MutableMapping[str, Any]) -> None:
    """Carry the server's Season 6 ending/metrics into each new living-world day."""
    root = world_data.get("season6_v1700", {}) if isinstance(world_data, Mapping) else {}
    guilds = root.get("guilds", {}) if isinstance(root, Mapping) else {}
    season = guilds.get(str(int(guild_id)), {}) if isinstance(guilds, Mapping) else {}
    stats = season.get("stats", {}) if isinstance(season, Mapping) else {}
    if not isinstance(stats, Mapping):
        return
    metrics = state.get("metrics")
    if not isinstance(metrics, MutableMapping):
        return
    hope = int(stats.get("hope", 0) or 0)
    order = int(stats.get("order", 0) or 0)
    survival = int(stats.get("survival", 0) or 0)
    abyss = int(stats.get("abyss", 0) or 0)
    metrics["hope"] = max(0, min(100, int(metrics.get("hope", 50)) + min(12, hope * 2)))
    metrics["order"] = max(0, min(100, int(metrics.get("order", 50)) + min(12, order * 2)))
    metrics["power"] = max(0, min(100, int(metrics.get("power", 50)) + min(10, survival * 2)))
    metrics["tension"] = max(0, min(100, int(metrics.get("tension", 40)) + min(14, abyss * 2) - min(6, hope)))
    state["season6_echo"] = {"completed": bool(season.get("completed")), "stats": {"hope":hope,"order":order,"survival":survival,"abyss":abyss}}


def _world_state(world_data: MutableMapping[str, Any], guild_id: int, save_data: Optional[Callable[[], None]] = None, *, force: bool = False) -> MutableMapping[str, Any]:
    root = _world_root(world_data)
    guilds = root["guilds"]
    key = str(int(guild_id))
    state = guilds.get(key)
    day = _today()
    if force or not isinstance(state, MutableMapping) or state.get("day") != day:
        previous = state if isinstance(state, Mapping) else None
        if isinstance(previous, Mapping) and previous.get("day"):
            history = list(previous.get("history", []))
            history.append({
                "day": previous.get("day"),
                "weather": previous.get("weather", {}).get("id"),
                "metrics": dict(previous.get("metrics", {})),
                "event_totals": list(previous.get("event_totals", [0, 0, 0])),
            })
            previous = dict(previous)
            previous["history"] = history[-30:]
        state = _new_daily_state(int(guild_id), day, previous)
        _apply_season6_echo(world_data, int(guild_id), state)
        guilds[key] = state
        if save_data:
            save_data()
    return state


def _phase_text(locale: str) -> str:
    phase = _phase()
    rows = {
        "dawn": ("새벽", "Dawn", "🌅"),
        "day": ("낮", "Day", "☀️"),
        "evening": ("저녁", "Evening", "🌆"),
        "night": ("밤", "Night", "🌙"),
    }
    ko, en, emoji = rows[phase]
    return f"{emoji} {_t(locale, ko, en)}"


def _world_embed(locale: str, state: Mapping[str, Any]) -> discord.Embed:
    weather = state.get("weather", {})
    metrics = state.get("metrics", {})
    event = state.get("event", {})
    embed = discord.Embed(
        title=_t(locale, "🌍 ABADDON 살아 있는 세계", "🌍 ABADDON Living World"),
        description=_t(locale, "시간·날씨·위험도·경제·세력 긴장이 매일 변화합니다.", "Time, weather, risk, economy and faction tension change every day."),
        color=0x4A5AE8,
    )
    embed.add_field(name=_t(locale, "🕰️ 현재 시간대", "🕰️ Time Phase"), value=_phase_text(locale), inline=True)
    embed.add_field(name=_t(locale, "🌦️ 날씨", "🌦️ Weather"), value=f"{weather.get('emoji','🌫️')} {_t(locale,str(weather.get('ko','-')),str(weather.get('en','-')))}", inline=True)
    embed.add_field(name=_t(locale, "📈 시장 지수", "📈 Market Index"), value=f"**{int(state.get('market_index',100))}%**", inline=True)
    embed.add_field(
        name=_t(locale, "🏙️ 도시 지표", "🏙️ City Metrics"),
        value=(
            f"🌟 {_t(locale,'희망','Hope')} **{int(metrics.get('hope',0))}** · "
            f"🛡️ {_t(locale,'질서','Order')} **{int(metrics.get('order',0))}**\n"
            f"⚡ {_t(locale,'전력','Power')} **{int(metrics.get('power',0))}** · "
            f"⚔️ {_t(locale,'긴장','Tension')} **{int(metrics.get('tension',0))}**"
        ),
        inline=False,
    )
    embed.add_field(name=_t(locale, "⚔️ 세력 충돌", "⚔️ Faction Conflict"), value=_t(locale,str(state.get("conflict",{}).get("ko","-")),str(state.get("conflict",{}).get("en","-"))), inline=False)
    embed.add_field(name=_t(locale, "📻 오늘의 사건", "📻 Daily Event"), value=f"**{_t(locale,str(event.get('title_ko','-')),str(event.get('title_en','-')))}**\n{_t(locale,str(event.get('desc_ko','')),str(event.get('desc_en','')))}", inline=False)
    echo=state.get("season6_echo",{})
    if isinstance(echo,Mapping) and echo.get("completed"):
        embed.add_field(name=_t(locale,"☀️ 시즌 6의 여파","☀️ Season 6 Echo"),value=_t(locale,"서버의 검은 태양 결말이 오늘의 도시 지표에 반영되었습니다.","The server's Black Sun ending shapes today's city metrics."),inline=False)
    embed.set_footer(text=_t(locale, "세계 상태는 KST 날짜 기준으로 하루 한 번 갱신됩니다.", "World state refreshes once per KST day."))
    return _safe_embed(embed)


def _risk_embed(locale: str, state: Mapping[str, Any]) -> discord.Embed:
    risks = state.get("risks", {})
    lines = []
    for rid, ko, en in sorted(REGIONS, key=lambda row: int(risks.get(row[0], 0)), reverse=True):
        risk = int(risks.get(rid, 0))
        icon = "☠️" if risk >= 80 else "🔴" if risk >= 65 else "🟠" if risk >= 45 else "🟢"
        lines.append(f"{icon} **{_t(locale,ko,en)}** · {risk}%")
    embed = discord.Embed(title=_t(locale,"🗺️ 지역 위험도","🗺️ Region Risk"), description="\n".join(lines), color=0xD35400)
    embed.set_footer(text=_t(locale,"위험도는 오늘의 날씨와 세계 사건에 따라 달라집니다.","Risk changes with weather and world events."))
    return _safe_embed(embed)


def _market_embed(locale: str, state: Mapping[str, Any]) -> discord.Embed:
    index = int(state.get("market_index", 100))
    items = (("통조림 상자", "Canned Food Crate", 4500), ("응급 의약품", "Emergency Medicine", 7200), ("전자 부품", "Electronic Parts", 9800))
    lines = []
    for ko, en, base in items:
        price = max(100, round(base * index / 100 / 100) * 100)
        lines.append(f"• **{_t(locale,ko,en)}** · {price:,}")
    embed = discord.Embed(title=_t(locale,"🛒 오늘의 세계 시장","🛒 Daily World Market"), description="\n".join(lines), color=0xF39C12)
    embed.add_field(name=_t(locale,"시장 지수","Market Index"), value=f"{index}%", inline=True)
    embed.add_field(name=_t(locale,"거래 명령","Trade Command"), value=_t(locale,"`!세계시장 구매 품목`","`!worldmarket buy item`"), inline=True)
    return _safe_embed(embed)


def _event_embed(locale: str, state: Mapping[str, Any], user_id: int = 0) -> discord.Embed:
    event = state.get("event", {})
    choices = event.get("choices", ())
    totals = state.get("event_totals", [0, 0, 0])
    lines = []
    for idx, choice in enumerate(choices, 1):
        lines.append(f"**{idx}.** {_t(locale,str(choice[0]),str(choice[1]))} · {int(totals[idx-1]) if idx-1 < len(totals) else 0}")
    embed = discord.Embed(title=f"📻 {_t(locale,str(event.get('title_ko','-')),str(event.get('title_en','-')))}", description=_t(locale,str(event.get('desc_ko','')),str(event.get('desc_en',''))), color=0x8E44AD)
    embed.add_field(name=_t(locale,"선택지","Choices"), value="\n".join(lines), inline=False)
    if user_id and str(user_id) in state.get("participants", {}):
        choice = int(state["participants"][str(user_id)]) + 1
        embed.add_field(name=_t(locale,"내 참여","My Action"), value=_t(locale,f"오늘 **{choice}번** 행동 완료",f"Completed option **{choice}** today"), inline=False)
    return _safe_embed(embed)


def _apply_world_choice(state: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, option: int) -> Tuple[bool, Dict[str, int]]:
    if option not in {1, 2, 3}:
        return False, {}
    participants = state.setdefault("participants", {})
    uid = str(int(user_id))
    action_days = user.setdefault("living_world_action_days_v1710", {})
    if not isinstance(action_days, MutableMapping):
        action_days = {}
        user["living_world_action_days_v1710"] = action_days
    day = str(state.get("day") or _today())
    if uid in participants or day in action_days:
        return False, {}
    event = state.get("event", {})
    choices = event.get("choices", ())
    if len(choices) < option:
        return False, {}
    effects = dict(choices[option - 1][2])
    metrics = state.setdefault("metrics", {})
    for key in ("hope", "order", "power", "tension"):
        if key in effects:
            metrics[key] = max(0, min(100, int(metrics.get(key, 50)) + int(effects[key])))
    if "market" in effects:
        state["market_index"] = max(70, min(145, int(state.get("market_index", 100)) + int(effects["market"])))
    if "risk" in effects:
        delta = int(effects["risk"])
        for key in list(state.get("risks", {})):
            state["risks"][key] = max(5, min(99, int(state["risks"][key]) + delta))
    reward = max(0, int(effects.get("food", 0)))
    before = int(user.get("balance", 0) or 0)
    user["balance"] = before + reward
    participants[uid] = option - 1
    action_days[day] = option - 1
    # Keep only recent dates so this anti-duplicate record cannot grow forever.
    for old_day in sorted(action_days)[:-35]:
        action_days.pop(old_day, None)
    totals = state.setdefault("event_totals", [0, 0, 0])
    while len(totals) < 3:
        totals.append(0)
    totals[option - 1] = int(totals[option - 1]) + 1
    linked = user.setdefault("connected_survival_v1730", {})
    daily = linked.setdefault("daily", {})
    daily["world_event_day"] = day
    linked.setdefault("history", []).append({"at": _now_ts(), "type": "world_event", "day": day, "option": option, "detail": str(event.get("id", "world"))})
    linked["history"] = linked["history"][-100:]
    return True, {"balance_before": before, "balance_after": int(user["balance"]), "reward": reward}


class WorldEventView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any], save_data: Callable[[], None], get_user: Callable[[int], Optional[MutableMapping[str, Any]]], guild_id: int, owner_id: int, locale: str):
        super().__init__(timeout=300)
        self.world_data = world_data
        self.save_data = save_data
        self.get_user = get_user
        self.guild_id = int(guild_id)
        self.owner_id = int(owner_id)
        self.locale = locale
        for idx in range(1, 4):
            button = discord.ui.Button(label=_t(locale, f"{idx}번 선택", f"Choose {idx}"), emoji=("🛟","🛰️","🛡️")[idx-1], style=discord.ButtonStyle.primary, row=0)
            button.callback = self._make_callback(idx)
            self.add_item(button)

    def _make_callback(self, option: int):
        async def callback(interaction: discord.Interaction) -> None:
            if int(interaction.user.id) != self.owner_id:
                await interaction.response.send_message(_t(self.locale,"이 선택지는 패널을 연 사용자만 사용할 수 있습니다.","Only the opener can use this choice."), ephemeral=True)
                return
            state = _world_state(self.world_data, self.guild_id, self.save_data)
            user = _safe_user(self.get_user, interaction.user.id)
            if not user:
                await interaction.response.send_message(_t(self.locale,"먼저 `!가입`으로 생존자를 등록해주세요.","Register a survivor with `!register` first."), ephemeral=True)
                return
            ok, result = _apply_world_choice(state, user, interaction.user.id, option)
            if not ok:
                await interaction.response.send_message(_t(self.locale,"오늘은 이미 세계 사건에 참여했거나 선택지가 유효하지 않습니다.","You already acted today or the choice is invalid."), ephemeral=True)
                return
            self.save_data()
            event = state.get("event", {})
            choice = event.get("choices", ())[option-1]
            embed = discord.Embed(title=_t(self.locale,"✅ 세계 사건 참여 완료","✅ World Event Action Complete"), description=_t(self.locale,str(choice[0]),str(choice[1])), color=0x2ECC71)
            embed.add_field(name=_t(self.locale,"🎁 획득","🎁 Gained"), value=f"{int(result['reward']):,}", inline=True)
            embed.add_field(name=_t(self.locale,"💰 잔액 변화","💰 Balance Change"), value=f"{int(result['balance_before']):,} → {int(result['balance_after']):,}", inline=True)
            embed.add_field(name=_t(self.locale,"🌍 세계 변화","🌍 World Change"), value=_t(self.locale,"도시 지표·시장·위험도에 선택 효과가 반영되었습니다.","Your choice changed city metrics, market or regional risk."), inline=False)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(embed=_safe_embed(embed), view=self)
        return callback


class WorldDashboardView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any], save_data: Callable[[], None], get_user: Callable[[int], Optional[MutableMapping[str, Any]]], guild_id: int, owner_id: int, locale: str):
        super().__init__(timeout=300)
        self.world_data = world_data
        self.save_data = save_data
        self.get_user = get_user
        self.guild_id = int(guild_id)
        self.owner_id = int(owner_id)
        self.locale = locale
        labels = (("속보", "Bulletin"), ("위험도", "Risk"), ("오늘 사건", "Daily Event"), ("세계 시장", "World Market"))
        for child, (ko, en) in zip(self.children, labels):
            if isinstance(child, discord.ui.Button):
                child.label = _t(locale, ko, en)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale,"패널을 연 사용자만 조작할 수 있습니다.","Only the opener can use this panel."), ephemeral=True)
        return False

    @discord.ui.button(label="속보", emoji="📻", style=discord.ButtonStyle.primary)
    async def bulletin(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        state = _world_state(self.world_data, self.guild_id, self.save_data)
        await interaction.response.send_message(embed=_world_embed(self.locale, state), ephemeral=True)

    @discord.ui.button(label="위험도", emoji="🗺️", style=discord.ButtonStyle.secondary)
    async def risk(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        state = _world_state(self.world_data, self.guild_id, self.save_data)
        await interaction.response.send_message(embed=_risk_embed(self.locale, state), ephemeral=True)

    @discord.ui.button(label="오늘 사건", emoji="⚠️", style=discord.ButtonStyle.success)
    async def event(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        state = _world_state(self.world_data, self.guild_id, self.save_data)
        await interaction.response.send_message(embed=_event_embed(self.locale, state, interaction.user.id), view=WorldEventView(self.world_data,self.save_data,self.get_user,self.guild_id,interaction.user.id,self.locale), ephemeral=True)

    @discord.ui.button(label="세계 시장", emoji="🛒", style=discord.ButtonStyle.secondary)
    async def market(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        state = _world_state(self.world_data, self.guild_id, self.save_data)
        await interaction.response.send_message(embed=_market_embed(self.locale, state), ephemeral=True)


NPCS: Tuple[Dict[str, Any], ...] = (
    {"id":"yoonseo","ko":"윤서","en":"Yoonseo","aliases":("의무병","medic"),"role_ko":"의무병","role_en":"Medic","favorite":"의약품","gift_en":"medicine","temper":"warm","schedule":{"dawn":"병원","day":"병원","evening":"중앙광장","night":"대피소"}},
    {"id":"doyun","ko":"도윤","en":"Doyun","aliases":("정찰병","scout"),"role_ko":"정찰병","role_en":"Scout","favorite":"오래된책","gift_en":"oldbook","temper":"quiet","schedule":{"dawn":"성벽","day":"폐허 외곽","evening":"감시탑","night":"성벽"}},
    {"id":"sera","ko":"세라","en":"Sera","aliases":("기술자","engineer"),"role_ko":"기술자","role_en":"Engineer","favorite":"전자부품","gift_en":"parts","temper":"sharp","schedule":{"dawn":"공방","day":"공방","evening":"발전소","night":"공방"}},
    {"id":"ren","ko":"렌","en":"Ren","aliases":("교섭가","negotiator"),"role_ko":"교섭가","role_en":"Negotiator","favorite":"커피","gift_en":"coffee","temper":"playful","schedule":{"dawn":"대피소","day":"중앙광장","evening":"암시장","night":"카지노 거리"}},
    {"id":"kane","ko":"케인","en":"Kane","aliases":("중화기병","gunner"),"role_ko":"중화기병","role_en":"Heavy Gunner","favorite":"통조림","gift_en":"cannedfood","temper":"loyal","schedule":{"dawn":"훈련장","day":"성벽","evening":"훈련장","night":"경비초소"}},
    {"id":"eve","ko":"이브","en":"Eve","aliases":("정보상","broker"),"role_ko":"정보상","role_en":"Information Broker","favorite":"네온결정","gift_en":"neoncrystal","temper":"secretive","schedule":{"dawn":"지하역","day":"암시장","evening":"암시장","night":"NEON 관문"}},
    {"id":"nox","ko":"녹스","en":"Nox","aliases":("교단탈주자","defector"),"role_ko":"교단 탈주자","role_en":"Cult Defector","favorite":"오래된책","gift_en":"oldbook","temper":"unstable","schedule":{"dawn":"폐허 성당","day":"지하역","evening":"폐허 성당","night":"불명"}},
    {"id":"mira","ko":"미라","en":"Mira","aliases":("기록관","archivist"),"role_ko":"기록관","role_en":"Archivist","favorite":"오래된책","gift_en":"oldbook","temper":"curious","schedule":{"dawn":"기록실","day":"기록실","evening":"중앙광장","night":"기록실"}},
)

LOCATION_EN: Dict[str, str] = {
    "병원": "Hospital", "중앙광장": "Central Plaza", "대피소": "Shelter",
    "성벽": "City Wall", "폐허 외곽": "Ruins Outskirts", "감시탑": "Watchtower",
    "공방": "Workshop", "발전소": "Power Plant", "암시장": "Black Market",
    "카지노 거리": "Casino Street", "훈련장": "Training Yard", "경비초소": "Guard Post",
    "지하역": "Underground Station", "NEON 관문": "NEON Gate", "폐허 성당": "Ruined Cathedral",
    "기록실": "Archive", "불명": "Unknown",
}


def _location(locale: str, raw: str) -> str:
    return LOCATION_EN.get(raw, raw) if locale == "en" else raw


GIFT_COSTS: Dict[str, Tuple[int, str, str]] = {
    "통조림": (3000, "통조림", "cannedfood"), "cannedfood": (3000, "통조림", "cannedfood"),
    "의약품": (7000, "의약품", "medicine"), "medicine": (7000, "의약품", "medicine"),
    "전자부품": (8000, "전자부품", "parts"), "parts": (8000, "전자부품", "parts"),
    "오래된책": (5000, "오래된책", "oldbook"), "oldbook": (5000, "오래된책", "oldbook"),
    "커피": (4000, "커피", "coffee"), "coffee": (4000, "커피", "coffee"),
    "네온결정": (12000, "네온결정", "neoncrystal"), "neoncrystal": (12000, "네온결정", "neoncrystal"),
}


def _resolve_npc(text: str) -> Optional[Dict[str, Any]]:
    token = str(text or "").strip().casefold().replace(" ", "")
    if not token:
        return None
    for npc in NPCS:
        names = {str(npc["id"]).casefold(), str(npc["ko"]).casefold(), str(npc["en"]).casefold()}
        names.update(str(x).casefold().replace(" ", "") for x in npc.get("aliases", ()))
        if token in names:
            return npc
    return None


def _bond_root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = user.setdefault(BOND_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        user[BOND_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("npcs", {})
    root.setdefault("romance", "")
    root.setdefault("history", [])
    if not isinstance(root.get("npcs"), MutableMapping):
        root["npcs"] = {}
    if not isinstance(root.get("history"), list):
        root["history"] = []
    root["version"] = VERSION
    return root


def _bond(user: MutableMapping[str, Any], npc_id: str) -> MutableMapping[str, Any]:
    root = _bond_root(user)
    row = root["npcs"].setdefault(npc_id, {})
    if not isinstance(row, MutableMapping):
        row = {}
        root["npcs"][npc_id] = row
    row.setdefault("affinity", 0)
    row.setdefault("trust", 10)
    row.setdefault("loyalty", 20)
    row.setdefault("fear", 0)
    row.setdefault("gifts", 0)
    row.setdefault("talks", 0)
    row.setdefault("missions", 0)
    row.setdefault("betrayals", 0)
    row.setdefault("last_talk", 0)
    row.setdefault("last_mission", 0)
    row.setdefault("route", "neutral")
    return row


def _clamp_bond(row: MutableMapping[str, Any]) -> None:
    for key in ("affinity", "trust", "loyalty", "fear"):
        row[key] = max(0, min(100, int(row.get(key, 0))))


def _npc_available(npc: Mapping[str, Any]) -> Tuple[bool, str]:
    phase = _phase()
    location = str(npc.get("schedule", {}).get(phase, "불명"))
    return location != "불명", location


def _npc_name(locale: str, npc: Mapping[str, Any]) -> str:
    return str(npc.get("en" if locale == "en" else "ko"))


def _bond_rank(locale: str, row: Mapping[str, Any]) -> str:
    score = int(row.get("affinity", 0)) + int(row.get("trust", 0))
    if row.get("route") == "romance":
        return _t(locale,"연인","Partner")
    if score >= 150:
        return _t(locale,"운명을 맡긴 동료","Oathbound")
    if score >= 100:
        return _t(locale,"신뢰하는 동료","Trusted Ally")
    if score >= 55:
        return _t(locale,"친한 생존자","Close Survivor")
    if score >= 20:
        return _t(locale,"아는 사이","Acquaintance")
    return _t(locale,"낯선 사람","Stranger")


def _betrayal_risk(row: Mapping[str, Any], state: Mapping[str, Any]) -> int:
    tension = int(state.get("metrics", {}).get("tension", 40))
    risk = 26 - int(row.get("loyalty", 20)) // 3 - int(row.get("trust", 10)) // 5 + int(row.get("fear", 0)) // 3 + tension // 8
    if row.get("route") == "romance":
        risk -= 8
    return max(1, min(65, risk))


def _bond_embed(locale: str, npc: Mapping[str, Any], row: Mapping[str, Any], state: Mapping[str, Any]) -> discord.Embed:
    available, location = _npc_available(npc)
    embed = discord.Embed(title=f"💞 {_npc_name(locale,npc)} · {_t(locale,str(npc['role_ko']),str(npc['role_en']))}", description=_bond_rank(locale,row), color=0xD252B9)
    embed.add_field(name=_t(locale,"💗 호감","💗 Affinity"), value=str(int(row.get("affinity",0))), inline=True)
    embed.add_field(name=_t(locale,"🤝 신뢰","🤝 Trust"), value=str(int(row.get("trust",0))), inline=True)
    embed.add_field(name=_t(locale,"🛡️ 충성","🛡️ Loyalty"), value=str(int(row.get("loyalty",0))), inline=True)
    embed.add_field(name=_t(locale,"😨 두려움","😨 Fear"), value=str(int(row.get("fear",0))), inline=True)
    embed.add_field(name=_t(locale,"📍 현재 위치","📍 Current Location"), value=f"{'🟢' if available else '⚫'} {_location(locale, location)}", inline=True)
    embed.add_field(name=_t(locale,"⚠️ 배신 위험","⚠️ Betrayal Risk"), value=f"{_betrayal_risk(row,state)}%", inline=True)
    embed.add_field(name=_t(locale,"📜 기록","📜 Records"), value=_t(locale,f"대화 {int(row.get('talks',0))} · 선물 {int(row.get('gifts',0))} · 동행 {int(row.get('missions',0))}",f"Talks {int(row.get('talks',0))} · Gifts {int(row.get('gifts',0))} · Missions {int(row.get('missions',0))}"), inline=False)
    return _safe_embed(embed)


def _bonds_overview(locale: str, user: MutableMapping[str, Any], state: Mapping[str, Any]) -> discord.Embed:
    rows = []
    for npc in NPCS:
        bond = _bond(user, str(npc["id"]))
        score = int(bond.get("affinity",0)) + int(bond.get("trust",0))
        rows.append((score,npc,bond))
    rows.sort(key=lambda item:item[0], reverse=True)
    lines = []
    for _score,npc,bond in rows[:8]:
        risk = _betrayal_risk(bond,state)
        lines.append(f"{'💘' if bond.get('route')=='romance' else '🤝'} **{_npc_name(locale,npc)}** · {_bond_rank(locale,bond)} · {int(bond.get('affinity',0))}/{int(bond.get('trust',0))} · ⚠️ {risk}%")
    embed = discord.Embed(title=_t(locale,"💞 ABADDON 인연망","💞 ABADDON Bond Network"), description="\n".join(lines), color=0xB54CE3)
    embed.add_field(name=_t(locale,"사용법","Commands"), value=_t(locale,"`!NPC대화 이름` · `!NPC선물 이름 선물` · `!동행요청 이름` · `!고백 이름`","`!bondtalk name` · `!bondgift name gift` · `!bondmission name` · `!confess name`"), inline=False)
    return _safe_embed(embed)


class GiftModal(discord.ui.Modal):
    def __init__(self, parent: "NPCBondView"):
        super().__init__(title=_t(parent.locale,"NPC 선물","NPC Gift"), timeout=300)
        self.parent_view = parent
        self.gift = discord.ui.TextInput(label=_t(parent.locale,"선물 이름","Gift name"), placeholder=_t(parent.locale,"통조림 / 의약품 / 전자부품 / 오래된책 / 커피 / 네온결정","cannedfood / medicine / parts / oldbook / coffee / neoncrystal"), max_length=30)
        self.add_item(self.gift)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.parent_view.give_gift(interaction, str(self.gift.value))


class NPCBondView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any], save_data: Callable[[], None], get_user: Callable[[int], Optional[MutableMapping[str, Any]]], guild_id: int, owner_id: int, locale: str, npc: Mapping[str, Any]):
        super().__init__(timeout=300)
        self.world_data = world_data
        self.save_data = save_data
        self.get_user = get_user
        self.guild_id = int(guild_id)
        self.owner_id = int(owner_id)
        self.locale = locale
        self.npc = npc
        labels = (("대화", "Talk"), ("선물", "Gift"), ("동행", "Mission"), ("고백", "Confess"))
        for child, (ko, en) in zip(self.children, labels):
            if isinstance(child, discord.ui.Button):
                child.label = _t(locale, ko, en)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale,"패널을 연 사용자만 조작할 수 있습니다.","Only the opener can use this panel."), ephemeral=True)
        return False

    async def give_gift(self, interaction: discord.Interaction, gift_text: str) -> None:
        key = gift_text.strip().casefold().replace(" ", "")
        gift = GIFT_COSTS.get(key)
        if not gift:
            await interaction.response.send_message(_t(self.locale,"지원하지 않는 선물입니다.","Unsupported gift."), ephemeral=True)
            return
        cost, ko_name, code = gift
        user = _safe_user(self.get_user, interaction.user.id)
        if not user:
            await interaction.response.send_message(_t(self.locale,"먼저 생존자를 등록해주세요.","Register a survivor first."), ephemeral=True)
            return
        balance = int(user.get("balance",0) or 0)
        if balance < cost:
            await interaction.response.send_message(_t(self.locale,f"식량이 부족합니다. 필요 {cost:,}",f"Not enough food. Required {cost:,}"), ephemeral=True)
            return
        row = _bond(user, str(self.npc["id"]))
        favorite = code == str(self.npc.get("gift_en")) or ko_name == str(self.npc.get("favorite"))
        before = (int(row["affinity"]), int(row["trust"]), balance)
        user["balance"] = balance - cost
        row["affinity"] += 12 if favorite else 5
        row["trust"] += 4 if favorite else 1
        row["gifts"] += 1
        _clamp_bond(row)
        _bond_root(user)["history"].append({"at":_now_ts(),"npc":self.npc["id"],"type":"gift","gift":code,"favorite":favorite})
        _bond_root(user)["history"] = _bond_root(user)["history"][-100:]
        self.save_data()
        embed = discord.Embed(title=_t(self.locale,"🎁 선물 전달 완료","🎁 Gift Delivered"), description=_t(self.locale,f"{self.npc['ko']}에게 **{ko_name}**을 건넸습니다.",f"You gave **{code}** to {self.npc['en']}."), color=0xE91E63)
        embed.add_field(name=_t(self.locale,"관계 변화","Relationship Change"), value=f"💗 {before[0]} → {row['affinity']}\n🤝 {before[1]} → {row['trust']}", inline=True)
        embed.add_field(name=_t(self.locale,"잔액 변화","Balance Change"), value=f"{before[2]:,} → {int(user['balance']):,}", inline=True)
        embed.set_footer(text=_t(self.locale,"아주 좋아하는 선물입니다." if favorite else "무난한 선물입니다.","A favorite gift." if favorite else "A decent gift."))
        await interaction.response.send_message(embed=_safe_embed(embed), ephemeral=True)

    @discord.ui.button(label="대화", emoji="💬", style=discord.ButtonStyle.primary)
    async def talk(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        user = _safe_user(self.get_user, interaction.user.id)
        if not user:
            await interaction.response.send_message(_t(self.locale,"먼저 생존자를 등록해주세요.","Register a survivor first."), ephemeral=True)
            return
        row = _bond(user, str(self.npc["id"]))
        available, location = _npc_available(self.npc)
        if not available:
            await interaction.response.send_message(_t(self.locale,"지금은 NPC의 위치를 확인할 수 없습니다.","The NPC cannot be located right now."), ephemeral=True)
            return
        now = _now_ts()
        remain = 1800 - (now - int(row.get("last_talk",0)))
        if remain > 0:
            await interaction.response.send_message(_t(self.locale,f"다음 대화까지 약 {max(1,remain//60)}분 남았습니다.",f"About {max(1,remain//60)} minutes until the next talk."), ephemeral=True)
            return
        world = _world_state(self.world_data,self.guild_id,self.save_data)
        gain = 5 if int(world.get("metrics",{}).get("hope",50)) >= 45 else 3
        before = (int(row["affinity"]),int(row["trust"]))
        row["affinity"] += gain
        row["trust"] += 2
        row["talks"] += 1
        row["last_talk"] = now
        _clamp_bond(row)
        _bond_root(user)["history"].append({"at":now,"npc":self.npc["id"],"type":"talk","location":location})
        self.save_data()
        lines = {
            "warm": ("오늘도 살아 있어서 다행이에요.", "I'm glad you made it through another day."),
            "quiet": ("말보다 발자국이 더 많은 걸 알려주지.", "Footprints tell more than words."),
            "sharp": ("고장 난 건 고치면 돼. 사람도 가끔은 그렇고.", "Broken things can be fixed. Sometimes people can too."),
            "playful": ("세상이 끝나도 웃을 이유 하나쯤은 남겨둬야지.", "Even at the end, keep one reason to laugh."),
            "loyal": ("등은 내가 맡지. 넌 앞만 봐.", "I'll watch your back. Keep looking forward."),
            "secretive": ("정보는 공짜가 아니지만, 오늘은 예외로 해둘게.", "Information isn't free, but today is an exception."),
            "unstable": ("검은 태양이 또 꿈에서 나를 불렀어.", "The Black Sun called me again in my dreams."),
            "curious": ("네 선택은 기록보다 먼저 역사가 되고 있어.", "Your choices become history before they become records."),
        }
        ko,en = lines.get(str(self.npc.get("temper")),("...","..."))
        embed = discord.Embed(title=f"💬 {_npc_name(self.locale,self.npc)}", description=f"“{_t(self.locale,ko,en)}”", color=0x3498DB)
        embed.add_field(name=_t(self.locale,"관계 변화","Relationship Change"), value=f"💗 {before[0]} → {row['affinity']} · 🤝 {before[1]} → {row['trust']}", inline=False)
        await interaction.response.send_message(embed=_safe_embed(embed), ephemeral=True)

    @discord.ui.button(label="선물", emoji="🎁", style=discord.ButtonStyle.secondary)
    async def gift(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(GiftModal(self))

    @discord.ui.button(label="동행", emoji="⚔️", style=discord.ButtonStyle.success)
    async def mission(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._mission(interaction)

    async def _mission(self, interaction: discord.Interaction) -> None:
        user = _safe_user(self.get_user, interaction.user.id)
        if not user:
            await interaction.response.send_message(_t(self.locale,"먼저 생존자를 등록해주세요.","Register a survivor first."), ephemeral=True)
            return
        row = _bond(user, str(self.npc["id"]))
        now = _now_ts()
        remain = 21600 - (now - int(row.get("last_mission",0)))
        if remain > 0:
            await interaction.response.send_message(_t(self.locale,f"다음 동행까지 약 {max(1,remain//3600)}시간 남았습니다.",f"About {max(1,remain//3600)} hours until the next mission."), ephemeral=True)
            return
        state = _world_state(self.world_data,self.guild_id,self.save_data)
        risk = _betrayal_risk(row,state)
        digest = hashlib.sha256(f"{interaction.user.id}:{self.npc['id']}:{_today()}:{row.get('missions',0)}".encode()).hexdigest()
        roll = int(digest[:8],16) % 100
        balance = int(user.get("balance",0) or 0)
        row["last_mission"] = now
        row["missions"] += 1
        if roll < risk:
            loss = min(max(1000,abs(balance)//25),20000)
            user["balance"] = balance - loss
            row["trust"] -= 10
            row["loyalty"] -= 12
            row["fear"] += 6
            row["betrayals"] += 1
            result = "betrayal"
            embed = discord.Embed(title=_t(self.locale,"🗡️ 동행 중 배신 발생","🗡️ Betrayal During Mission"), description=_t(self.locale,f"{self.npc['ko']}가 보급품을 챙겨 사라졌습니다. 관계를 회복하거나 거리를 둘 수 있습니다.",f"{self.npc['en']} vanished with supplies. You can rebuild the bond or keep your distance."), color=0xC0392B)
            embed.add_field(name=_t(self.locale,"손실","Loss"), value=f"{loss:,}", inline=True)
        else:
            base = 12000 + int(row.get("trust",0))*120 + int(row.get("loyalty",0))*80
            reward = max(10000,min(40000,base))
            user["balance"] = balance + reward
            row["affinity"] += 5
            row["trust"] += 5
            row["loyalty"] += 4
            row["fear"] -= 2
            result = "success"
            embed = discord.Embed(title=_t(self.locale,"🏁 동행 작전 성공","🏁 Companion Mission Success"), description=_t(self.locale,f"{self.npc['ko']}와 함께 위험 구역에서 귀환했습니다.",f"You returned from the danger zone with {self.npc['en']}."), color=0x2ECC71)
            embed.add_field(name=_t(self.locale,"획득","Gained"), value=f"{reward:,}", inline=True)
        _clamp_bond(row)
        _bond_root(user)["history"].append({"at":now,"npc":self.npc["id"],"type":"mission","result":result,"risk":risk})
        linked=user.setdefault("connected_survival_v1730",{}); linked.setdefault("daily",{})["npc_mission_day"]=_today(); linked.setdefault("history",[]).append({"at":now,"type":"npc_mission","result":result,"detail":str(self.npc["id"])}); linked["history"]=linked["history"][-100:]
        _bond_root(user)["history"] = _bond_root(user)["history"][-100:]
        self.save_data()
        embed.add_field(name=_t(self.locale,"잔액 변화","Balance Change"), value=f"{balance:,} → {int(user['balance']):,}", inline=True)
        embed.add_field(name=_t(self.locale,"현재 배신 위험","Current Betrayal Risk"), value=f"{_betrayal_risk(row,state)}%", inline=True)
        await interaction.response.send_message(embed=_safe_embed(embed), ephemeral=True)

    @discord.ui.button(label="고백", emoji="💘", style=discord.ButtonStyle.danger)
    async def confess(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        user = _safe_user(self.get_user, interaction.user.id)
        if not user:
            await interaction.response.send_message(_t(self.locale,"먼저 생존자를 등록해주세요.","Register a survivor first."), ephemeral=True)
            return
        root = _bond_root(user)
        row = _bond(user, str(self.npc["id"]))
        if root.get("romance") and root.get("romance") != self.npc["id"]:
            await interaction.response.send_message(_t(self.locale,"이미 다른 NPC와 연인 관계입니다. 관계를 먼저 정리해야 합니다.","You already have another romance route. End it first."), ephemeral=True)
            return
        if int(row.get("affinity",0)) < 70 or int(row.get("trust",0)) < 65 or int(row.get("loyalty",0)) < 55:
            await interaction.response.send_message(_t(self.locale,"고백 조건: 호감 70 · 신뢰 65 · 충성 55 이상입니다.","Confession requires Affinity 70, Trust 65 and Loyalty 55."), ephemeral=True)
            return
        root["romance"] = self.npc["id"]
        row["route"] = "romance"
        row["loyalty"] = min(100,int(row["loyalty"])+8)
        root["history"].append({"at":_now_ts(),"npc":self.npc["id"],"type":"romance"})
        self.save_data()
        await interaction.response.send_message(_t(self.locale,f"💘 {self.npc['ko']}가 당신의 마음을 받아들였습니다.",f"💘 {self.npc['en']} accepted your feelings."), ephemeral=True)


class NPCRosterSelect(discord.ui.Select):
    def __init__(self, view: "NPCRosterView"):
        self.owner_view = view
        options = []
        for npc in NPCS:
            available, location = _npc_available(npc)
            options.append(discord.SelectOption(label=_npc_name(view.locale,npc), value=str(npc["id"]), emoji="🟢" if available else "⚫", description=f"{_t(view.locale,str(npc['role_ko']),str(npc['role_en']))} · {_location(view.locale, location)}"[:100]))
        super().__init__(placeholder=_t(view.locale,"NPC를 선택하세요","Choose an NPC"), options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        npc = _resolve_npc(self.values[0])
        user = _safe_user(view.get_user, interaction.user.id)
        state = _world_state(view.world_data,view.guild_id,view.save_data)
        if not user:
            await interaction.response.send_message(_t(view.locale,"먼저 생존자를 등록해주세요.","Register a survivor first."), ephemeral=True)
            return
        if not npc:
            await interaction.response.send_message(_t(view.locale,"NPC를 찾지 못했습니다.","NPC not found."), ephemeral=True)
            return
        row = _bond(user,str(npc["id"]))
        await interaction.response.send_message(embed=_bond_embed(view.locale,npc,row,state), view=NPCBondView(view.world_data,view.save_data,view.get_user,view.guild_id,interaction.user.id,view.locale,npc), ephemeral=True)


class NPCRosterView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any], save_data: Callable[[], None], get_user: Callable[[int], Optional[MutableMapping[str, Any]]], guild_id: int, owner_id: int, locale: str):
        super().__init__(timeout=300)
        self.world_data=world_data; self.save_data=save_data; self.get_user=get_user
        self.guild_id=int(guild_id); self.owner_id=int(owner_id); self.locale=locale
        self.add_item(NPCRosterSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id)==self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale,"패널을 연 사용자만 사용할 수 있습니다.","Only the opener can use this panel."),ephemeral=True)
        return False


def _install_creator_group(bot: commands.Bot) -> bool:
    existing = bot.get_command("콘텐츠공방")
    if isinstance(existing, commands.Group):
        return True
    old = bot.remove_command("콘텐츠공방")
    if old is None:
        return False
    aliases = list(dict.fromkeys(list(getattr(old,"aliases",[]) or []) + ["creatorforge","eventforge","사건공방"]))

    @bot.group(name="콘텐츠공방", aliases=aliases, invoke_without_command=True, help="관리자가 한국어·English 선택형 사건을 제작·테스트·공개하는 콘텐츠 공방 그룹입니다.")
    async def creator_group(ctx: commands.Context) -> None:
        await old.callback(ctx)

    @creator_group.command(name="목록", aliases=["list","library"], help="서버의 공개 사용자 사건 목록을 엽니다.")
    async def creator_list(ctx: commands.Context) -> None:
        cmd = bot.get_command("콘텐츠목록")
        if cmd is not None:
            await cmd.callback(ctx)

    @creator_group.command(name="플레이", aliases=["play","event"], help="공개 사용자 사건을 플레이합니다.")
    async def creator_play(ctx: commands.Context, event_id: str = "") -> None:
        cmd = bot.get_command("사용자사건")
        if cmd is not None:
            await cmd.callback(ctx,event_id)

    @creator_group.command(name="비공개", aliases=["unpublish","disable"], help="공개 사건을 비공개로 전환합니다.")
    async def creator_unpublish(ctx: commands.Context, event_id: str) -> None:
        cmd = bot.get_command("콘텐츠비공개")
        if cmd is not None:
            await cmd.callback(ctx,event_id)

    return isinstance(bot.get_command("콘텐츠공방"),commands.Group)


def register_v1720_living_world_bonds(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del check_registered, user_data
    if getattr(bot,"_abaddon_v1720_registered",False):
        return
    bot._abaddon_v1720_registered=True
    bot.abaddon_version=VERSION
    creator_group_ok = _install_creator_group(bot)

    @bot.command(name="살아있는세계", aliases=["livingworld","worldnow"], help="오늘의 시간·날씨·시장·도시 지표와 세계 사건을 한 화면에서 확인합니다.")
    async def living_world(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0)
        state=_world_state(world_data,gid,save_data)
        await ctx.send(embed=_world_embed(locale,state),view=_safe_view(WorldDashboardView(world_data,save_data,get_user,gid,ctx.author.id,locale)))

    @bot.command(name="세계속보", aliases=["worldbulletin","worldnews"], help="오늘의 날씨·전력·세력 긴장과 주요 사건 속보를 확인합니다.")
    async def world_bulletin(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data)
        await ctx.send(embed=_world_embed(locale,state))

    @bot.command(name="지역위험도", aliases=["regionrisk","dangermap"], help="오늘의 지역별 위험도를 높은 순서로 확인합니다.")
    async def region_risk(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data)
        await ctx.send(embed=_risk_embed(locale,state))

    @bot.command(name="오늘의세계사건", aliases=["worldevent","dailyevent"], help="오늘의 서버 공동 세계 사건을 확인하고 버튼으로 한 번 참여합니다.")
    async def world_event(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0); state=_world_state(world_data,gid,save_data)
        await ctx.send(embed=_event_embed(locale,state,ctx.author.id),view=_safe_view(WorldEventView(world_data,save_data,get_user,gid,ctx.author.id,locale)))

    @bot.command(name="세계참여", aliases=["worldaction","worldparticipate"], help="오늘의 세계 사건 선택지 1~3에 참여합니다.")
    async def world_action(ctx: commands.Context, option: int) -> None:
        locale=_ctx_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0); state=_world_state(world_data,gid,save_data); user=_safe_user(get_user,ctx.author.id)
        if not user:
            await ctx.send(_t(locale,"먼저 `!가입`으로 생존자를 등록해주세요.","Register with `!register` first.")); return
        ok,result=_apply_world_choice(state,user,ctx.author.id,option)
        if not ok:
            await ctx.send(_t(locale,"오늘은 이미 참여했거나 선택 번호가 올바르지 않습니다.","You already acted today or the option is invalid.")); return
        save_data()
        await ctx.send(_t(locale,f"✅ 세계 사건 {option}번 행동 완료 · 획득 {result['reward']:,} · 잔액 {result['balance_before']:,} → {result['balance_after']:,}",f"✅ World event option {option} complete · gained {result['reward']:,} · balance {result['balance_before']:,} → {result['balance_after']:,}"))

    @bot.command(name="세계시장", aliases=["worldmarket","dailymarket"], help="오늘의 변동 시장 가격을 확인하거나 보급품을 구매합니다.")
    async def world_market(ctx: commands.Context, action: str = "", *, item: str = "") -> None:
        locale=_ctx_locale(bot,ctx); state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data)
        if str(action).casefold() not in {"구매","buy"}:
            await ctx.send(embed=_market_embed(locale,state)); return
        lookup={
            "통조림":("통조림 상자","Canned Food Crate",4500), "canned":("통조림 상자","Canned Food Crate",4500),
            "의약품":("응급 의약품","Emergency Medicine",7200), "medicine":("응급 의약품","Emergency Medicine",7200),
            "전자부품":("전자 부품","Electronic Parts",9800), "parts":("전자 부품","Electronic Parts",9800),
        }
        key=item.strip().casefold().replace(" ","")
        found=lookup.get(key)
        if not found:
            await ctx.send(_t(locale,"품목: 통조림 / 의약품 / 전자부품","Items: canned / medicine / parts")); return
        ko_name,en_name,base=found; name=_t(locale,ko_name,en_name)
        city_root=world_data.get("neon_abyss_v1500",{}) if isinstance(world_data,Mapping) else {}
        city_guilds=city_root.get("guilds",{}) if isinstance(city_root,Mapping) else {}
        city_row=city_guilds.get(str(int(ctx.guild.id if ctx.guild else 0)),{}) if isinstance(city_guilds,Mapping) else {}
        decors=city_row.get("decorations",[]) if isinstance(city_row,Mapping) else []
        market_parts={"demon_market":4,"harbor":2,"neon_train":2}
        city_discount=min(12,sum(market_parts.get(str(d.get("id","")),0) for d in decors if isinstance(d,Mapping))) if isinstance(decors,list) else 0
        price=max(100,round((base*int(state.get('market_index',100))/100)*(100-city_discount)/100/100)*100); user=_safe_user(get_user,ctx.author.id)
        before=int(user.get("balance",0) or 0)
        if before<price:
            await ctx.send(_t(locale,f"식량이 부족합니다. 필요 {price:,}",f"Not enough food. Required {price:,}")); return
        user["balance"] = before - price
        inv = user.get("inventory")
        if not isinstance(inv, MutableMapping):
            inv = {}
            user["inventory"] = inv
        inv[name] = int(inv.get(name, 0) or 0) + 1
        save_data()
        await ctx.send(_t(locale,f"🛒 {name} ×1 구매 · 도시 할인 {city_discount}% · {before:,} → {int(user['balance']):,}",f"🛒 Purchased {name} ×1 · city discount {city_discount}% · {before:,} → {int(user['balance']):,}"))

    @bot.command(name="세계갱신", aliases=["refreshworld","worldrefresh"], help="관리자가 오늘의 살아 있는 세계 상태를 강제로 다시 생성합니다.")
    async def world_refresh(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx)
        if not _is_admin(ctx.author,ctx.guild):
            await ctx.send(_t(locale,"🔒 서버 관리자만 사용할 수 있습니다.","🔒 Server admins only.")); return
        state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data,force=True)
        await ctx.send(embed=_world_embed(locale,state))

    @bot.command(name="세계방송설정", aliases=["worldbroadcast","livingworldchannel"], help="관리자가 현재 채널의 일일 세계 속보 자동 방송을 켜거나 끕니다.")
    async def world_broadcast_setting(ctx: commands.Context, mode: str = "상태") -> None:
        locale=_ctx_locale(bot,ctx)
        if not _is_admin(ctx.author,ctx.guild):
            await ctx.send(_t(locale,"🔒 서버 관리자만 사용할 수 있습니다.","🔒 Server admins only.")); return
        root=_world_root(world_data); gid=str(int(ctx.guild.id if ctx.guild else 0)); token=str(mode or "").casefold()
        if token in {"끄기","off","disable","0"}:
            root["broadcast_channels"].pop(gid,None); root["broadcast_days"].pop(gid,None); save_data()
            await ctx.send(_t(locale,"📴 일일 세계 속보 방송을 껐습니다.","📴 Daily world broadcasts disabled.")); return
        if token in {"켜기","on","enable","1"}:
            root["broadcast_channels"][gid]=int(ctx.channel.id); root["broadcast_days"].pop(gid,None); save_data()
            await ctx.send(_t(locale,"📡 이 채널에 일일 세계 속보를 방송합니다.","📡 Daily world bulletins will be sent to this channel.")); return
        channel_id=root["broadcast_channels"].get(gid)
        await ctx.send(_t(locale,f"📡 방송 채널: {f'<#{channel_id}>' if channel_id else '설정 안 됨'} · `!세계방송설정 ON/OFF`",f"📡 Broadcast channel: {f'<#{channel_id}>' if channel_id else 'not set'} · `!worldbroadcast on/off`"))

    @bot.command(name="인연", aliases=["bonds","bondnetwork"], help="모든 NPC의 호감·신뢰·충성·배신 위험을 한 화면에서 확인합니다.")
    async def bonds(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0); user=_safe_user(get_user,ctx.author.id)
        if not user:
            await ctx.send(_t(locale,"먼저 생존자를 등록해주세요.","Register a survivor first.")); return
        state=_world_state(world_data,gid,save_data)
        await ctx.send(embed=_bonds_overview(locale,user,state),view=_safe_view(NPCRosterView(world_data,save_data,get_user,gid,ctx.author.id,locale)))

    @bot.command(name="NPC목록", aliases=["npclist","npcroster"], help="NPC 역할·현재 위치·시간대별 활동을 확인하고 관계 화면을 엽니다.")
    async def npc_list(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0)
        lines=[]
        for npc in NPCS:
            available,location=_npc_available(npc)
            lines.append(f"{'🟢' if available else '⚫'} **{_npc_name(locale,npc)}** · {_t(locale,str(npc['role_ko']),str(npc['role_en']))} · {_location(locale, location)}")
        embed=discord.Embed(title=_t(locale,"🧑‍🤝‍🧑 NPC 생존자 명단","🧑‍🤝‍🧑 NPC Survivor Roster"),description="\n".join(lines),color=0x8E44AD)
        await ctx.send(embed=_safe_embed(embed),view=_safe_view(NPCRosterView(world_data,save_data,get_user,gid,ctx.author.id,locale)))

    @bot.command(name="NPC대화", aliases=["bondtalk","talkbondnpc"], help="NPC와 대화해 호감과 신뢰를 쌓습니다. 30분 재사용 대기시간이 있습니다.")
    async def npc_talk(ctx: commands.Context, *, name: str) -> None:
        locale=_ctx_locale(bot,ctx); npc=_resolve_npc(name)
        if not npc:
            await ctx.send(_t(locale,"NPC를 찾지 못했습니다. `!NPC목록`을 확인하세요.","NPC not found. Check `!npclist`.")); return
        user = _safe_user(get_user, ctx.author.id)
        if not user:
            await ctx.send(_t(locale, "먼저 생존자를 등록해주세요.", "Register a survivor first.")); return
        state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data); row=_bond(user,str(npc["id"]))
        await ctx.send(embed=_bond_embed(locale,npc,row,state),view=_safe_view(NPCBondView(world_data,save_data,get_user,int(ctx.guild.id if ctx.guild else 0),ctx.author.id,locale,npc)))

    @bot.command(name="NPC선물", aliases=["bondgift","giftbondnpc"], help="NPC에게 선물을 주고 호감·신뢰 변화를 확인합니다.")
    async def npc_gift(ctx: commands.Context, name: str, *, gift: str) -> None:
        locale=_ctx_locale(bot,ctx); npc=_resolve_npc(name)
        if not npc:
            await ctx.send(_t(locale,"NPC를 찾지 못했습니다.","NPC not found.")); return
        key=gift.strip().casefold().replace(" ",""); item=GIFT_COSTS.get(key)
        if not item:
            await ctx.send(_t(locale,"선물: 통조림·의약품·전자부품·오래된책·커피·네온결정","Gifts: cannedfood, medicine, parts, oldbook, coffee, neoncrystal")); return
        user=_safe_user(get_user,ctx.author.id)
        if not user:
            await ctx.send(_t(locale,"먼저 생존자를 등록해주세요.","Register a survivor first.")); return
        cost,ko_name,code=item; before=int(user.get("balance",0) or 0)
        if before<cost:
            await ctx.send(_t(locale,f"식량이 부족합니다. 필요 {cost:,}",f"Not enough food. Required {cost:,}")); return
        row=_bond(user,str(npc["id"])); affinity_before=int(row["affinity"]); trust_before=int(row["trust"]); favorite=code==npc.get("gift_en")
        user["balance"]=before-cost; row["affinity"]+=12 if favorite else 5; row["trust"]+=4 if favorite else 1; row["gifts"]+=1; _clamp_bond(row)
        root=_bond_root(user); root["history"].append({"at":_now_ts(),"npc":npc["id"],"type":"gift","gift":code,"favorite":favorite}); root["history"]=root["history"][-100:]
        save_data()
        await ctx.send(_t(locale,f"🎁 {npc['ko']}에게 {ko_name} 전달 · 호감 {affinity_before}→{row['affinity']} · 신뢰 {trust_before}→{row['trust']} · 잔액 {before:,}→{int(user['balance']):,}",f"🎁 Gifted {code} to {npc['en']} · affinity {affinity_before}→{row['affinity']} · trust {trust_before}→{row['trust']} · balance {before:,}→{int(user['balance']):,}"))

    @bot.command(name="동행요청", aliases=["bondmission","askbondcompanion"], help="NPC와 6시간마다 동행 작전을 진행합니다. 관계에 따라 성공 또는 배신이 발생합니다.")
    async def companion_mission(ctx: commands.Context, *, name: str) -> None:
        locale=_ctx_locale(bot,ctx); npc=_resolve_npc(name)
        if not npc:
            await ctx.send(_t(locale,"NPC를 찾지 못했습니다.","NPC not found.")); return
        # Reuse the same settlement rules without fabricating a Discord interaction.
        user=_safe_user(get_user,ctx.author.id)
        if not user:
            await ctx.send(_t(locale,"먼저 생존자를 등록해주세요.","Register a survivor first.")); return
        row=_bond(user,str(npc["id"])); now=_now_ts(); remain=21600-(now-int(row.get("last_mission",0)))
        if remain>0:
            await ctx.send(_t(locale,f"다음 동행까지 약 {max(1,remain//3600)}시간 남았습니다.",f"About {max(1,remain//3600)} hours until the next mission.")); return
        state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data); risk=_betrayal_risk(row,state); roll=int(hashlib.sha256(f"{ctx.author.id}:{npc['id']}:{_today()}:{row.get('missions',0)}".encode()).hexdigest()[:8],16)%100; balance=int(user.get("balance",0) or 0)
        row["last_mission"]=now; row["missions"]+=1
        if roll<risk:
            loss=min(max(1000,abs(balance)//25),20000); user["balance"]=balance-loss; row["trust"]-=10; row["loyalty"]-=12; row["fear"]+=6; row["betrayals"]+=1; result=_t(locale,f"🗡️ {npc['ko']}의 배신 · 손실 {loss:,}",f"🗡️ Betrayed by {npc['en']} · loss {loss:,}")
        else:
            reward=max(10000,min(40000,12000+int(row.get('trust',0))*120+int(row.get('loyalty',0))*80)); user["balance"]=balance+reward; row["affinity"]+=5; row["trust"]+=5; row["loyalty"]+=4; row["fear"]-=2; result=_t(locale,f"🏁 {npc['ko']}와 동행 성공 · 획득 {reward:,}",f"🏁 Mission success with {npc['en']} · gained {reward:,}")
        _clamp_bond(row)
        root=_bond_root(user); root["history"].append({"at":now,"npc":npc["id"],"type":"mission","result":"betrayal" if roll<risk else "success","risk":risk}); root["history"]=root["history"][-100:]
        linked=user.setdefault("connected_survival_v1730",{}); linked.setdefault("daily",{})["npc_mission_day"]=_today(); linked.setdefault("history",[]).append({"at":now,"type":"npc_mission","result":"betrayal" if roll<risk else "success","detail":str(npc["id"])}); linked["history"]=linked["history"][-100:]
        save_data(); await ctx.send(f"{result}\n💰 {balance:,} → {int(user['balance']):,} · ⚠️ {_betrayal_risk(row,state)}%")

    @bot.command(name="고백", aliases=["confess","romancenpc"], help="관계 조건을 충족한 NPC에게 고백해 연인 루트를 시작합니다.")
    async def confess(ctx: commands.Context, *, name: str) -> None:
        locale=_ctx_locale(bot,ctx); npc=_resolve_npc(name)
        if not npc:
            await ctx.send(_t(locale,"NPC를 찾지 못했습니다.","NPC not found.")); return
        user=_safe_user(get_user,ctx.author.id)
        if not user:
            await ctx.send(_t(locale,"먼저 생존자를 등록해주세요.","Register a survivor first.")); return
        root=_bond_root(user); row=_bond(user,str(npc["id"]))
        if root.get("romance") and root.get("romance")!=npc["id"]:
            await ctx.send(_t(locale,"이미 다른 NPC와 연인 관계입니다.","You already have another romance route.")); return
        if int(row.get("affinity",0))<70 or int(row.get("trust",0))<65 or int(row.get("loyalty",0))<55:
            await ctx.send(_t(locale,"조건: 호감 70 · 신뢰 65 · 충성 55 이상","Requires Affinity 70 · Trust 65 · Loyalty 55")); return
        root["romance"]=npc["id"]; row["route"]="romance"; row["loyalty"]=min(100,int(row["loyalty"])+8); root["history"].append({"at":_now_ts(),"npc":npc["id"],"type":"romance"}); root["history"]=root["history"][-100:]; save_data(); await ctx.send(_t(locale,f"💘 {npc['ko']}가 당신의 마음을 받아들였습니다.",f"💘 {npc['en']} accepted your feelings."))

    @bot.command(name="배신경보", aliases=["betrayalalert","betrayalrisk"], help="모든 NPC의 현재 배신 위험과 원인을 확인합니다.")
    async def betrayal_alert(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); user=_safe_user(get_user,ctx.author.id); state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data)
        rows=[]
        for npc in NPCS:
            row=_bond(user,str(npc["id"])); rows.append((_betrayal_risk(row,state),npc,row))
        rows.sort(reverse=True,key=lambda x:x[0]); lines=[f"{'🔴' if risk>=35 else '🟠' if risk>=20 else '🟢'} **{_npc_name(locale,npc)}** · {risk}% · {_t(locale,'신뢰','Trust')} {int(row['trust'])} · {_t(locale,'충성','Loyalty')} {int(row['loyalty'])}" for risk,npc,row in rows]
        await ctx.send(embed=_safe_embed(discord.Embed(title=_t(locale,"⚠️ NPC 배신 경보","⚠️ NPC Betrayal Alert"),description="\n".join(lines),color=0xC0392B)))

    @bot.command(name="인연기록", aliases=["bondhistory","relationshiphistory"], help="특정 NPC 또는 전체 인연 사건 기록을 확인합니다.")
    async def bond_history(ctx: commands.Context, *, name: str = "") -> None:
        locale=_ctx_locale(bot,ctx); user=_safe_user(get_user,ctx.author.id); root=_bond_root(user); npc=_resolve_npc(name) if name else None; rows=list(root.get("history",[]));
        if npc: rows=[row for row in rows if row.get("npc")==npc["id"]]
        if not rows:
            await ctx.send(_t(locale,"아직 인연 기록이 없습니다.","No bond history yet.")); return
        labels={"talk":("대화","Talk"),"gift":("선물","Gift"),"mission":("동행","Mission"),"romance":("고백","Romance")}; lines=[]
        for row in rows[-15:]:
            target=next((n for n in NPCS if n["id"]==row.get("npc")),None); ko,en=labels.get(str(row.get("type")),("기록","Record")); lines.append(f"• **{_npc_name(locale,target) if target else row.get('npc')}** · {_t(locale,ko,en)} · <t:{int(row.get('at',0))}:R>")
        await ctx.send(embed=_safe_embed(discord.Embed(title=_t(locale,"📜 인연 연대기","📜 Bond Chronicle"),description="\n".join(lines),color=0x7D3C98)))

    @bot.command(name="1710세계검수", aliases=["v1710audit","livingworldaudit"], help="살아 있는 세계의 일일 갱신·날씨·위험·시장·사건 연결을 검사합니다.")
    async def audit_1710(ctx: commands.Context, detail: str = "") -> None:
        locale=_ctx_locale(bot,ctx); state=_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data)
        checks=[("Daily state",state.get("day")==_today()),("Weather",state.get("weather",{}).get("id") is not None),("Six region risks",len(state.get("risks",{}))==len(REGIONS)),("Market index",70<=int(state.get("market_index",0))<=145),("Faction conflict",state.get("conflict",{}).get("id") is not None),("Three event choices",len(state.get("event",{}).get("choices",()))==3),("KO/EN text",all(state.get("event",{}).get(k) for k in ("title_ko","title_en","desc_ko","desc_en")))]
        embed=discord.Embed(title=_t(locale,"🌍 v17.1 살아 있는 세계 검수","🌍 v17.1 Living World Audit"),description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks),color=0x2ECC71 if all(v for _,v in checks) else 0xE74C3C)
        if detail: embed.add_field(name=_t(locale,"범위","Scope"),value="Time · Weather · Risk · Market · Faction conflict · Daily event · Season 6 echo · Broadcast · Persistence",inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1720인연검수", aliases=["v1720bondsaudit","bondsaudit"], help="NPC 명단·일정·선물·동행·고백·배신 위험 저장 구조를 검사합니다.")
    async def audit_bonds(ctx: commands.Context, detail: str = "") -> None:
        locale=_ctx_locale(bot,ctx); user=_safe_user(get_user,ctx.author.id); root=_bond_root(user)
        checks=[("Eight NPCs",len(NPCS)==8),("Unique NPC ids",len({n['id'] for n in NPCS})==len(NPCS)),("Four schedules",all(len(n.get('schedule',{}))==4 for n in NPCS)),("Gift catalog",len(GIFT_COSTS)>=12),("Bond storage",isinstance(root.get('npcs'),MutableMapping)),("Romance route",'romance' in root),("Betrayal formula",all(1<=_betrayal_risk(_bond(user,n['id']),_world_state(world_data,int(ctx.guild.id if ctx.guild else 0),save_data))<=65 for n in NPCS))]
        embed=discord.Embed(title=_t(locale,"💞 v17.2 NPC 인연 검수","💞 v17.2 NPC Bonds Audit"),description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks),color=0x2ECC71 if all(v for _,v in checks) else 0xE74C3C)
        if detail: embed.add_field(name=_t(locale,"범위","Scope"),value="Roster · Schedules · Dialogue · Gifts · Missions · Romance · Betrayal · Persistence",inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1720통합검수", aliases=["v1720audit","1720audit"], help="v17.0.1 공방 그룹·v17.1 살아 있는 세계·v17.2 NPC 인연을 통합 검사합니다.")
    async def audit_1720(ctx: commands.Context, detail: str = "") -> None:
        locale=_ctx_locale(bot,ctx); entries=hub._build_registry(bot); required=["콘텐츠공방","살아있는세계","세계속보","지역위험도","오늘의세계사건","세계시장","세계방송설정","인연","NPC목록","NPC대화","NPC선물","동행요청","고백","배신경보","1710세계검수","1720인연검수"]
        checks=[(name,bot.get_command(name) is not None) for name in required]
        checks.extend([("Creator Forge command group",isinstance(bot.get_command("콘텐츠공방"),commands.Group)),("Creator commands classified",any(e.group=="creator" for e in entries if "v1700" in e.source or "v1720" in e.source)),("Living world category",any(e.group=="world_misc" and e.name=="살아있는세계" for e in entries)),("NPC bond category",any(e.group=="npc" and e.name=="인연" for e in entries)),("Korean / English separation",bot.get_command("명령어") is not None and bot.get_command("help") is not None),("Legacy Season 6 preserved",bot.get_command("시즌6") is not None)])
        ok=all(v for _,v in checks); embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.2.0 통합 검수","🧪 ABADDON v17.2.0 Integration Audit"),description="\n".join(f"{'✅' if v else '❌'} {n}" for n,v in checks),color=0x2ECC71 if ok else 0xE74C3C)
        if detail: embed.add_field(name=_t(locale,"보존","Preservation"),value=_t(locale,"기존 명령·저장 데이터 삭제 0건 · 추가 계층만 등록","0 legacy commands or save data removed · additive layer only"),inline=False)
        await ctx.send(embed=_safe_embed(embed))

    # Correct and extend the v17.0 audit surface.
    old_audit=bot.get_command("1700통합검수")
    if old_audit is not None:
        async def audit_1700_fixed(ctx: commands.Context, detail: str = "") -> None:
            locale=_ctx_locale(bot,ctx); entries=hub._build_registry(bot); checks=[("명령어",bot.get_command("명령어") is not None),("help",bot.get_command("help") is not None),("콘텐츠공방",bot.get_command("콘텐츠공방") is not None),("사용자사건",bot.get_command("사용자사건") is not None),("시즌6",bot.get_command("시즌6") is not None),("Creator Forge command group",isinstance(bot.get_command("콘텐츠공방"),commands.Group)),("Creator Forge category",any(e.group=="creator" for e in entries if e.name in {"콘텐츠공방","콘텐츠목록","사용자사건","콘텐츠비공개"})),("Season 6 command group",any(e.group=="story6" for e in entries if e.name.startswith("시즌6")))]
            embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.0.1 마감 검수","🧪 ABADDON v17.0.1 Final Audit"),description="\n".join(f"{'✅' if v else '❌'} {n}" for n,v in checks),color=0x2ECC71 if all(v for _,v in checks) else 0xE74C3C)
            if detail: embed.add_field(name=_t(locale,"수정","Fix"),value=_t(locale,"공방 명령이 시즌 6으로 잘못 분류되던 소스 파일명 키워드 충돌을 제거했습니다.","Removed the source-filename keyword collision that classified Creator Forge as Season 6."),inline=False)
            await ctx.send(embed=_safe_embed(embed))
        old_audit.callback=audit_1700_fixed; old_audit.help="v17.0.1 콘텐츠 공방 그룹과 시즌 6 분류를 다시 검사합니다."; old_audit.description=old_audit.help

    patch=bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1720(ctx: commands.Context) -> None:
            locale=_ctx_locale(bot,ctx); embed=discord.Embed(title=_t(locale,"🌍 ABADDON v17.2.0 · LIVING WORLD & BROKEN OATHS","🌍 ABADDON v17.2.0 · LIVING WORLD & BROKEN OATHS"),description=_t(locale,"콘텐츠 공방 분류를 마감하고, 매일 변하는 세계와 NPC 인연·연애·배신 시스템을 연결했습니다.","Finalized Creator Forge grouping and added a daily living world plus NPC bonds, romance and betrayal."),color=0x512DA8)
            embed.add_field(name=_t(locale,"🧩 v17.0.1 공방 마감","🧩 v17.0.1 Forge Finalization"),value=_t(locale,"`!콘텐츠공방`을 실제 상위 그룹으로 전환하고 목록·플레이·비공개 하위 명령을 연결했습니다.","Converted `!creatorforge` into a real command group with list, play and unpublish subcommands."),inline=False)
            embed.add_field(name=_t(locale,"🌍 v17.1 살아 있는 세계","🌍 v17.1 Living World"),value=_t(locale,"KST 일일 갱신, 시간대, 날씨, 6개 지역 위험도, 시장 지수, 도시 지표와 공동 사건을 추가했습니다.","Added KST daily refresh, time phases, weather, six region risks, market index, city metrics and shared events."),inline=False)
            embed.add_field(name=_t(locale,"💞 v17.2 NPC 인연","💞 v17.2 NPC Bonds"),value=_t(locale,"NPC 8명, 일정, 대화, 선물, 동행, 고백, 관계 기록과 관계 기반 배신 위험을 추가했습니다.","Added eight NPCs, schedules, dialogue, gifts, missions, romance, bond history and relationship-based betrayal risk."),inline=False)
            embed.add_field(name=_t(locale,"📚 명령어 허브","📚 Command Hub"),value=_t(locale,"빠른 버튼 5페이지에 살아 있는 세계·오늘의 사건·NPC 인연·NPC 목록을 연결했습니다.","Added Living World, Daily Event, NPC Bonds and NPC Roster to quick page five."),inline=False)
            embed.add_field(name=_t(locale,"🧪 점검","🧪 Checks"),value="`!1700통합검수 상세` · `!1710세계검수 상세` · `!1720인연검수 상세` · `!1720통합검수 상세`",inline=False)
            embed.set_footer(text=_t(locale,"기존 기능·저장 데이터 삭제 0건","0 legacy features or save data removed")); await ctx.send(embed=_safe_embed(embed))
        patch.callback=patch_v1720; patch.help="ABADDON v17.2.0 최신 패치노트입니다."; patch.description=patch.help

    test=bot.get_command("테스트")
    if test is not None:
        async def test_v1720(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args,kwargs
            locale=_ctx_locale(bot,ctx); required=["콘텐츠공방","살아있는세계","오늘의세계사건","인연","NPC목록","동행요청","1720통합검수"]; checks=[(name,bot.get_command(name) is not None) for name in required]; checks.append(("Creator Group",isinstance(bot.get_command("콘텐츠공방"),commands.Group))); checks.append(("8 NPCs",len(NPCS)==8)); embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.2 최신 테스트","🧪 ABADDON v17.2 Latest Test"),description="\n".join(f"{'✅' if v else '❌'} {n}" for n,v in checks),color=0x2ECC71 if all(v for _,v in checks) else 0xE74C3C)
            if str(mode).casefold() in {"상세","detail","full"}: embed.add_field(name=_t(locale,"범위","Scope"),value="Creator Forge Group · Living World · Daily Events · Market · NPC Bonds · Romance · Betrayal · KO/EN split",inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback=test_v1720; test.help="v17.2 공방·살아 있는 세계·NPC 인연 최신 범위를 검사합니다."; test.description=test.help

    @tasks.loop(hours=1)
    async def living_world_broadcast_loop() -> None:
        if should_pause_nonessential():
            return
        root=_world_root(world_data); channels=root.get("broadcast_channels",{}); days=root.get("broadcast_days",{})
        if not isinstance(channels,Mapping) or not isinstance(days,MutableMapping):
            return
        today=_today()
        for guild in list(getattr(bot,"guilds",[]) or []):
            gid=str(int(guild.id)); channel_id=channels.get(gid)
            if not channel_id or days.get(gid)==today:
                continue
            channel=bot.get_channel(int(channel_id))
            if channel is None or not hasattr(channel,"send"):
                continue
            try:
                state=_world_state(world_data,int(gid),save_data)
                await channel.send(embed=_world_embed(_server_locale(int(gid)),state))
                days[gid]=today; save_data()
            except Exception as exc:
                print(f"[ABADDON v{VERSION}] living-world broadcast failed guild={gid}: {type(exc).__name__}: {exc}",flush=True)

    @living_world_broadcast_loop.before_loop
    async def before_living_world_broadcast() -> None:
        await bot.wait_until_ready()

    @bot.listen("on_ready")
    async def v1720_living_world_ready() -> None:
        if not living_world_broadcast_loop.is_running():
            living_world_broadcast_loop.start()

    bot.v1720_living_world_broadcast_loop=living_world_broadcast_loop

    entries=hub._build_registry(bot); setattr(bot,"v1630_command_entries",entries); setattr(bot,"v1630_command_index",{e.qualified_name:e for e in entries})
    guide.append({"id":"v1720_living_world_bonds","emoji":"🌍","title":"v17.2 LIVING WORLD & BROKEN OATHS","hint":"공방 그룹 마감·일일 세계 변화·공동 사건·NPC 일정·인연·고백·배신","commands":["!살아있는세계 · !세계속보 · !오늘의세계사건 · !세계시장 · !세계방송설정","!인연 · !NPC목록 · !NPC대화 · !NPC선물 · !동행요청 · !고백 · !배신경보","!1700통합검수 상세 · !1710세계검수 상세 · !1720인연검수 상세 · !1720통합검수 상세"]})
    print(f"[ABADDON v{VERSION}] living world + NPC bonds registered: creator_group={creator_group_ok} npcs={len(NPCS)} commands={len(entries)}",flush=True)


__all__=["register_v1720_living_world_bonds","_world_state","_bond_root","NPCS"]
