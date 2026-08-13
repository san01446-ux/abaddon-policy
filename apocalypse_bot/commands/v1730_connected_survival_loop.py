from __future__ import annotations

"""ABADDON v17.3.0 — CONNECTED SURVIVAL LOOP.

This additive layer connects the existing story, living world, solo expedition,
NPC bonds, crafting materials, city workshop and survivor hub into one guided
play loop.  It never replaces legacy saves or commands.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _safe_embed, _safe_view
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub

VERSION = "17.3.0"
ROOT_KEY = "connected_survival_v1730"
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


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> MutableMapping[str, Any]:
    row = get_user(int(user_id))
    return row if isinstance(row, MutableMapping) else {}


def _root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault(ROOT_KEY, {})
    if not isinstance(row, MutableMapping):
        row = {}
        user[ROOT_KEY] = row
    row.setdefault("version", VERSION)
    row.setdefault("daily", {})
    row.setdefault("history", [])
    row.setdefault("recent_changes", [])
    row.setdefault("city_effects", {})
    row.setdefault("last_sync", 0)
    if not isinstance(row.get("daily"), MutableMapping):
        row["daily"] = {}
    if not isinstance(row.get("history"), list):
        row["history"] = []
    if not isinstance(row.get("recent_changes"), list):
        row["recent_changes"] = []
    if not isinstance(row.get("city_effects"), MutableMapping):
        row["city_effects"] = {}
    row["version"] = VERSION
    return row


def _guild_root(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    guilds = root["guilds"]
    if not isinstance(guilds, MutableMapping):
        guilds = {}
        root["guilds"] = guilds
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, MutableMapping):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("history", [])
    row.setdefault("season_echo", {})
    row.setdefault("last_chain_day", "")
    root["version"] = VERSION
    return row


MATERIAL_USES: Dict[str, Tuple[str, str, Tuple[Tuple[str, str, str], ...]]] = {
    "고철": ("고철", "Scrap", (("장비 수리·강화", "Repair and enhance gear", "!강화"), ("감시탑·바리케이드", "Watchtowers and barricades", "!도시꾸미기"), ("공방 제작", "Workshop crafting", "!제작"))),
    "약초": ("약초", "Herbs", (("회복제·응급 치료", "Medicine and emergency healing", "!회복"), ("의무소 보급", "Infirmary supplies", "!기지"), ("윤서 의뢰·선물", "Yoonseo requests and gifts", "!NPC선물 윤서 의약품"))),
    "나무": ("나무", "Wood", (("대피소·기지 확장", "Shelter and base upgrades", "!기지"), ("도시 가구·공방", "City furniture and workshop", "!도시꾸미기"), ("원정 보급품", "Expedition supplies", "!솔로원정"))),
    "광석": ("광석", "Ore", (("방어구·중장비 제작", "Armor and heavy gear", "!제작"), ("발전기·차원 시설", "Generators and rift facilities", "!도시꾸미기"), ("세라 기술 의뢰", "Sera engineering requests", "!NPC대화 세라"))),
    "전자부품": ("전자부품", "Electronic Parts", (("전자 장비 제작", "Electronic equipment", "!제작"), ("감시 비행선·네온 열차", "Watch airship and neon train", "!도시꾸미기"), ("세라 선호 선물", "Sera's preferred gift", "!NPC선물 세라 전자부품"))),
    "네온결정": ("네온결정", "Neon Crystal", (("NEON ABYSS 장비", "NEON ABYSS gear", "!차원탐사"), ("차원문·네온 관문", "Rift and neon gates", "!도시꾸미기"), ("이브 선호 선물", "Eve's preferred gift", "!NPC선물 이브 네온결정"))),
    "차원결정": ("차원결정", "Rift Crystal", (("차원 관문 제작", "Rift gate crafting", "!도시꾸미기"), ("심연 장비 강화", "Abyss gear enhancement", "!강화"), ("차원 원정 준비", "Abyss expedition prep", "!솔로원정"))),
}

MATERIAL_ALIASES = {
    "scrap": "고철", "herbs": "약초", "wood": "나무", "ore": "광석",
    "parts": "전자부품", "electronicparts": "전자부품", "neoncrystal": "네온결정",
    "riftcrystal": "차원결정", "dimensioncrystal": "차원결정",
}

CITY_EFFECT_RULES: Dict[str, Tuple[str, str, str, int]] = {
    "fountain": ("recovery", "회복 비용 감소", "Recovery discount", 2),
    "ruin_ward": ("recovery", "회복 비용 감소", "Recovery discount", 2),
    "airship": ("expedition", "원정 탐지 보정", "Expedition detection", 3),
    "street_lamp": ("expedition", "원정 탐지 보정", "Expedition detection", 1),
    "neon_gate": ("abyss", "차원 원정 보상", "Rift expedition reward", 3),
    "rift_portal": ("abyss", "차원 원정 보상", "Rift expedition reward", 5),
    "central_casino": ("casino", "카지노 이벤트 보정", "Casino event bonus", 3),
    "hwatu_street": ("casino", "카드 이벤트 보정", "Card event bonus", 2),
    "racetrack": ("casino", "경마 이벤트 보정", "Racing event bonus", 2),
    "demon_market": ("market", "세계 시장 할인", "World market discount", 4),
    "harbor": ("market", "세계 시장 할인", "World market discount", 2),
    "neon_train": ("market", "세계 시장 할인", "World market discount", 2),
    "faction_banner": ("bonds", "NPC 충성 보정", "NPC loyalty bonus", 2),
    "gold_statue": ("hope", "연결 보상 보정", "Connected reward bonus", 2),
    "legend_trophy": ("hope", "연결 보상 보정", "Connected reward bonus", 3),
    "bench": ("bonds", "NPC 호감 보정", "NPC affinity bonus", 1),
    "flowerbed": ("bonds", "NPC 호감 보정", "NPC affinity bonus", 1),
    "fireworks": ("hope", "도시 희망 보정", "City hope bonus", 2),
    "prison": ("order", "도시 질서 보정", "City order bonus", 3),
}


def _city_row(world_data: Mapping[str, Any], guild_id: int) -> Mapping[str, Any]:
    root = world_data.get("neon_abyss_v1500", {}) if isinstance(world_data, Mapping) else {}
    guilds = root.get("guilds", {}) if isinstance(root, Mapping) else {}
    row = guilds.get(str(int(guild_id)), {}) if isinstance(guilds, Mapping) else {}
    return row if isinstance(row, Mapping) else {}


def _city_effects(world_data: Mapping[str, Any], guild_id: int) -> Dict[str, int]:
    effects = {"recovery": 0, "expedition": 0, "abyss": 0, "casino": 0, "market": 0, "bonds": 0, "hope": 0, "order": 0}
    decorations = _city_row(world_data, guild_id).get("decorations", [])
    if not isinstance(decorations, Sequence) or isinstance(decorations, (str, bytes)):
        return effects
    for item in decorations:
        if not isinstance(item, Mapping):
            continue
        rule = CITY_EFFECT_RULES.get(str(item.get("id", "")))
        if rule:
            effects[rule[0]] = min(20, int(effects.get(rule[0], 0)) + int(rule[3]))
    return effects


def _resource_amount(user: Mapping[str, Any], material: str) -> int:
    resources = user.get("resources", {}) if isinstance(user.get("resources"), Mapping) else {}
    amount = int(resources.get(material, 0) or 0)
    inventory = user.get("inventory")
    if isinstance(inventory, Mapping):
        amount += int(inventory.get(material, 0) or 0)
    elif isinstance(inventory, list):
        amount += sum(1 for item in inventory if str(item) == material)
    return amount


def _story_line(locale: str, user: Mapping[str, Any]) -> Tuple[str, str]:
    try:
        from apocalypse_bot.commands import v1650_survivor_core_complete as core
        target, label, season, state = core._story_target(user)
        node = str(state.get("node") or state.get("current") or state.get("chapter") or "-") if isinstance(state, Mapping) else "-"
        return target, _t(locale, f"시즌 {season} · {label} · 현재 {node}", f"Season {season} · {label} · Current {node}")
    except Exception:
        return "스토리나침반", _t(locale, "스토리 나침반에서 현재 진행 확인", "Review current progress in Story Compass")


def _world_state(world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> MutableMapping[str, Any]:
    try:
        from apocalypse_bot.commands import v1720_living_world_bonds as living
        return living._world_state(world_data, int(guild_id), save_data)
    except Exception:
        return {}


def _season6_state(world_data: MutableMapping[str, Any], guild_id: int) -> Mapping[str, Any]:
    try:
        from apocalypse_bot.commands import v1700_creator_forge_season6 as season
        return season._season_state(world_data, int(guild_id))
    except Exception:
        return {}


def _city_action_today(world_data: Mapping[str, Any], guild_id: int) -> bool:
    history = _city_row(world_data, guild_id).get("decor_history", [])
    if not isinstance(history, list) or not history:
        return False
    timestamp = int(history[-1].get("at", 0) or 0) if isinstance(history[-1], Mapping) else 0
    if timestamp <= 0:
        return False
    return datetime.fromtimestamp(timestamp, KST).strftime("%Y-%m-%d") == _today()


def _daily_status(user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> Dict[str, bool]:
    day = _today()
    connected = _root(user)
    daily = connected.setdefault("daily", {})
    action_days = user.get("living_world_action_days_v1710", {}) if isinstance(user.get("living_world_action_days_v1710"), Mapping) else {}
    bonds = user.get("npc_bonds_v1720", {}) if isinstance(user.get("npc_bonds_v1720"), Mapping) else {}
    history = bonds.get("history", []) if isinstance(bonds, Mapping) else []
    npc_today = False
    if isinstance(history, list):
        for item in reversed(history[-20:]):
            if not isinstance(item, Mapping) or item.get("type") != "mission":
                continue
            at = int(item.get("at", 0) or 0)
            if at and datetime.fromtimestamp(at, KST).strftime("%Y-%m-%d") == day:
                npc_today = True
                break
    status = {
        "world": day in action_days or str(daily.get("world_event_day", "")) == day,
        "expedition": str(daily.get("expedition_day", "")) == day,
        "npc": npc_today or str(daily.get("npc_mission_day", "")) == day,
        "city": _city_action_today(world_data, guild_id),
    }
    daily["status_day"] = day
    daily["status"] = dict(status)
    return status


def _sync(user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> MutableMapping[str, Any]:
    row = _root(user)
    effects = _city_effects(world_data, guild_id)
    row["city_effects"] = effects
    row["last_sync"] = int(datetime.now().timestamp())
    status = _daily_status(user, world_data, guild_id, save_data)
    world = _world_state(world_data, guild_id, save_data)
    season = _season6_state(world_data, guild_id)
    target, story = _story_line("ko", user)
    row["snapshot"] = {
        "day": _today(), "story_target": target, "story": story,
        "world_event": str(world.get("event", {}).get("id", "")) if isinstance(world, Mapping) else "",
        "market_index": int(world.get("market_index", 100) or 100) if isinstance(world, Mapping) else 100,
        "season6_chapter": int(season.get("chapter", 0) or 0) if isinstance(season, Mapping) else 0,
        "season6_completed": bool(season.get("completed")) if isinstance(season, Mapping) else False,
        "daily_complete": sum(1 for value in status.values() if value),
    }
    return row


def _material_key(text: str) -> Optional[str]:
    token = str(text or "").strip().casefold().replace(" ", "")
    if token in MATERIAL_USES:
        return token
    return MATERIAL_ALIASES.get(token)


def _objective_lines(locale: str, status: Mapping[str, bool]) -> List[str]:
    rows = (
        ("world", "📻 오늘의 세계 사건 참여", "📻 Join today's world event"),
        ("expedition", "🌑 솔로 원정 귀환·철수·구조", "🌑 Finish, retreat from, or be rescued from a solo expedition"),
        ("npc", "💞 NPC 동행 작전 1회", "💞 Complete one NPC bond mission"),
        ("city", "🎨 도시 공방 배치·삭제·복구 1회", "🎨 Place, remove, or restore one city decoration"),
    )
    return [f"{'✅' if status.get(key) else '⬜'} {_t(locale, ko, en)}" for key, ko, en in rows]


def _best_bond(locale: str, user: MutableMapping[str, Any], world: Mapping[str, Any]) -> str:
    try:
        from apocalypse_bot.commands import v1720_living_world_bonds as living
        candidates = []
        for npc in living.NPCS:
            row = living._bond(user, str(npc["id"]))
            score = int(row.get("affinity", 0)) + int(row.get("trust", 0))
            risk = living._betrayal_risk(row, world)
            candidates.append((score, risk, npc, row))
        candidates.sort(key=lambda x: x[0], reverse=True)
        _score, risk, npc, row = candidates[0]
        name = str(npc.get("en" if locale == "en" else "ko"))
        return _t(locale, f"{name} · 호감 {row.get('affinity',0)} · 신뢰 {row.get('trust',0)} · 배신 {risk}%", f"{name} · Affinity {row.get('affinity',0)} · Trust {row.get('trust',0)} · Betrayal {risk}%")
    except Exception:
        return _t(locale, "아직 인연 정보 없음", "No bond data yet")


def _connected_embed(locale: str, user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> discord.Embed:
    row = _sync(user, world_data, guild_id, save_data)
    status = _daily_status(user, world_data, guild_id, save_data)
    world = _world_state(world_data, guild_id, save_data)
    target, story = _story_line(locale, user)
    event = world.get("event", {}) if isinstance(world, Mapping) else {}
    title = str(event.get("title_en" if locale == "en" else "title_ko", "-")) if isinstance(event, Mapping) else "-"
    risks = world.get("risks", {}) if isinstance(world, Mapping) else {}
    max_region, max_risk = ("-", 0)
    if isinstance(risks, Mapping) and risks:
        max_region, max_risk = max(((str(k), int(v or 0)) for k, v in risks.items()), key=lambda x: x[1])
    effects = row.get("city_effects", {}) if isinstance(row.get("city_effects"), Mapping) else {}
    done = sum(1 for value in status.values() if value)
    embed = discord.Embed(
        title=_t(locale, "🔗 ABADDON 연결 생존 루프", "🔗 ABADDON Connected Survival Loop"),
        description=_t(locale, "하나의 행동이 스토리·세계·원정·NPC·제작·도시로 이어집니다.", "Each action now feeds story, world, expedition, NPC, crafting and city progress."),
        color=0x5E35B1,
    )
    embed.add_field(name=_t(locale, "📖 현재 스토리", "📖 Current Story"), value=f"{story}\n`!{target}`", inline=False)
    embed.add_field(name=_t(locale, "🌍 오늘의 세계", "🌍 Today's World"), value=_t(locale, f"사건 **{title}** · 최고 위험 `{max_region}` {max_risk}% · 시장 {int(world.get('market_index',100) or 100)}", f"Event **{title}** · Highest risk `{max_region}` {max_risk}% · Market {int(world.get('market_index',100) or 100)}"), inline=False)
    embed.add_field(name=_t(locale, "🎯 연결 목표", "🎯 Connected Objectives"), value="\n".join(_objective_lines(locale, status)), inline=False)
    embed.add_field(name=_t(locale, "💞 가장 가까운 인연", "💞 Closest Bond"), value=_best_bond(locale, user, world), inline=False)
    active_effects = [f"{key} +{value}%" for key, value in effects.items() if int(value or 0) > 0]
    embed.add_field(name=_t(locale, "🏙️ 도시 연동 효과", "🏙️ Linked City Effects"), value=" · ".join(active_effects) or _t(locale, "배치된 효과 부품 없음", "No effect-bearing decorations placed"), inline=False)
    embed.add_field(name=_t(locale, "🏁 오늘의 연결 진척", "🏁 Today's Chain Progress"), value=_t(locale, f"**{done}/4** · 3개 완료 시 `!연결보상`", f"**{done}/4** · Claim with `!connectedreward` after 3"), inline=False)
    embed.set_footer(text=_t(locale, "한국어/English 화면은 선택 언어 하나만 표시 · 기존 저장 삭제 0건", "Single-language UI · 0 legacy saves removed"))
    return _safe_embed(embed)


def _action_view(bot: commands.Bot, owner_id: int, locale: str) -> Optional[discord.ui.View]:
    try:
        from apocalypse_bot.commands.v1650_survivor_core_complete import ActionView
        actions = (
            ("스토리나침반", "스토리", "Story", "📖", discord.ButtonStyle.success),
            ("오늘의세계사건", "세계 사건", "World Event", "📻", discord.ButtonStyle.primary),
            ("솔로원정", "솔로 원정", "Solo Expedition", "🌑", discord.ButtonStyle.primary),
            ("인연", "NPC 인연", "NPC Bonds", "💞", discord.ButtonStyle.secondary),
            ("도시꾸미기", "도시 공방", "City Workshop", "🎨", discord.ButtonStyle.secondary),
        )
        return ActionView(bot, owner_id, locale, actions)
    except Exception:
        return None


def register_v1730_connected_survival_loop(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del user_data

    @bot.command(name="연결허브", aliases=["connectedhub", "survivalloop", "connectedloop"], help="스토리·세계·원정·NPC·제작·도시를 한 화면에서 연결해 다음 행동을 안내합니다.")
    async def connected_hub(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        _sync(user, world_data, gid, save_data)
        save_data()
        await ctx.send(embed=_connected_embed(locale, user, world_data, gid, save_data), view=_safe_view(_action_view(bot, ctx.author.id, locale)))

    @bot.command(name="연결목표", aliases=["connectedobjectives", "loopgoals", "chainobjectives"], help="오늘의 세계·원정·NPC·도시 연결 목표와 완료 상태를 확인합니다.")
    async def connected_objectives(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        status = _daily_status(user, world_data, int(ctx.guild.id if ctx.guild else 0), save_data)
        done = sum(1 for value in status.values() if value)
        embed = discord.Embed(title=_t(locale, "🎯 오늘의 연결 목표", "🎯 Today's Connected Objectives"), description="\n".join(_objective_lines(locale, status)), color=0x6C5CE7)
        embed.add_field(name=_t(locale, "진척", "Progress"), value=f"**{done}/4**", inline=True)
        embed.add_field(name=_t(locale, "보상 조건", "Reward Requirement"), value=_t(locale, "3개 이상 완료", "Complete at least 3"), inline=True)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="연결보상", aliases=["connectedreward", "loopreward", "chainreward"], help="오늘의 연결 목표 4개 중 3개 이상 완료하면 일일 연결 보상을 한 번 수령합니다.")
    async def connected_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        row = _sync(user, world_data, gid, save_data)
        status = _daily_status(user, world_data, gid, save_data)
        done = sum(1 for value in status.values() if value)
        daily = row.setdefault("daily", {})
        if str(daily.get("claimed_day", "")) == _today():
            await ctx.send(_t(locale, "오늘의 연결 보상은 이미 수령했습니다.", "Today's connected reward has already been claimed.")); return
        if done < 3:
            await ctx.send(_t(locale, f"연결 목표가 부족합니다. 현재 {done}/4 · 3개 이상 필요", f"Not enough connected objectives. Current {done}/4 · need at least 3")); return
        effects = row.get("city_effects", {}) if isinstance(row.get("city_effects"), Mapping) else {}
        food = 35_000 + (10_000 if done == 4 else 0) + int(effects.get("hope", 0) or 0) * 500
        exp = 120 + (30 if done == 4 else 0)
        before = int(user.get("balance", 0) or 0); exp_before = int(user.get("exp", 0) or 0)
        user["balance"] = before + food; user["exp"] = exp_before + exp
        daily["claimed_day"] = _today(); daily["claimed_count"] = int(daily.get("claimed_count", 0) or 0) + 1
        history = row.setdefault("history", [])
        history.append({"at": int(datetime.now().timestamp()), "type": "daily_chain_reward", "day": _today(), "completed": done, "food": food, "exp": exp})
        row["history"] = history[-100:]
        world = _world_state(world_data, gid, save_data)
        metrics = world.get("metrics") if isinstance(world, MutableMapping) else None
        if isinstance(metrics, MutableMapping):
            metrics["hope"] = min(100, int(metrics.get("hope", 50) or 50) + 1)
            metrics["power"] = min(100, int(metrics.get("power", 50) or 50) + (1 if done == 4 else 0))
        save_data()
        embed = discord.Embed(title=_t(locale, "🏁 연결 생존 루프 완료", "🏁 Connected Survival Loop Complete"), color=0x2ECC71)
        embed.add_field(name=_t(locale, "🎁 획득", "🎁 Gained"), value=_t(locale, f"식량 +{food:,} · EXP +{exp}", f"Supplies +{food:,} · EXP +{exp}"), inline=False)
        embed.add_field(name=_t(locale, "📊 변화", "📊 Changes"), value=f"{before:,} → {int(user['balance']):,}\nEXP {exp_before:,} → {int(user['exp']):,}", inline=False)
        embed.add_field(name=_t(locale, "🌍 세계 반영", "🌍 World Effect"), value=_t(locale, "희망 +1" + (" · 전력 +1" if done == 4 else ""), "Hope +1" + (" · Power +1" if done == 4 else "")), inline=False)
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(_action_view(bot, ctx.author.id, locale)))

    @bot.command(name="재료용도", aliases=["materialuses", "craftuses", "whereuse"], help="보유 재료가 제작·도시·NPC·원정 중 어디에 쓰이는지 표시합니다.")
    async def material_uses(ctx: commands.Context, *, material: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        key = _material_key(material)
        if not key:
            lines = []
            for mid, (ko, en, _uses) in MATERIAL_USES.items():
                lines.append(f"• **{_t(locale, ko, en)}** ×{_resource_amount(user, mid)}")
            embed = discord.Embed(title=_t(locale, "🧰 재료 사용처 안내", "🧰 Material Use Guide"), description="\n".join(lines), color=0x8D6E63)
            embed.add_field(name=_t(locale, "사용법", "Usage"), value=_t(locale, "`!재료용도 고철`처럼 입력하세요.", "Use `!materialuses scrap`."), inline=False)
            await ctx.send(embed=_safe_embed(embed)); return
        ko, en, uses = MATERIAL_USES[key]
        amount = _resource_amount(user, key)
        lines = [f"• **{_t(locale, uko, uen)}** · `{command}`" for uko, uen, command in uses]
        embed = discord.Embed(title=f"🧰 {_t(locale, ko, en)} ×{amount}", description="\n".join(lines), color=0x8D6E63)
        embed.set_footer(text=_t(locale, "실제 제작 가능 여부는 해당 제작·도시 화면에서 재료와 해금 조건을 함께 검사합니다.", "The target crafting or city screen also checks costs and unlock requirements."))
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="도시효과", aliases=["cityeffects", "citybonuses", "linkedcity"], help="현재 도시 부품이 회복·시장·원정·NPC·카지노에 제공하는 연결 효과를 확인합니다.")
    async def city_effects(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx); gid = int(ctx.guild.id if ctx.guild else 0)
        effects = _city_effects(world_data, gid); row = _city_row(world_data, gid)
        decorations = row.get("decorations", []) if isinstance(row, Mapping) else []
        labels = {
            "recovery": ("❤️ 회복 비용", "❤️ Recovery cost"), "expedition": ("🧭 원정 탐지", "🧭 Expedition detection"),
            "abyss": ("🌀 차원 보상", "🌀 Rift reward"), "casino": ("🎰 게임 이벤트", "🎰 Game events"),
            "market": ("🛒 세계 시장 할인", "🛒 World market discount"), "bonds": ("💞 NPC 관계", "💞 NPC relations"),
            "hope": ("🌟 연결 보상", "🌟 Connected reward"), "order": ("🛡️ 도시 질서", "🛡️ City order"),
        }
        lines = [f"{_t(locale, *labels[key])} **+{value}%**" for key, value in effects.items() if int(value or 0) > 0]
        embed = discord.Embed(title=_t(locale, "🏙️ 도시 연결 효과", "🏙️ Linked City Effects"), description="\n".join(lines) or _t(locale, "효과를 제공하는 도시 부품이 아직 없습니다.", "No effect-bearing city parts are placed yet."), color=0x00A8CC)
        embed.add_field(name=_t(locale, "현재 배치", "Current Placements"), value=f"**{len(decorations) if isinstance(decorations, list) else 0}/40**", inline=True)
        embed.add_field(name=_t(locale, "실제 적용", "Live Application"), value=_t(locale, "세계 시장 할인·연결 보상에 즉시 반영, 나머지는 연결 허브와 추천 루트에 표시", "Market discount and connected rewards apply immediately; other bonuses guide recommendations"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="연결기록", aliases=["connectedhistory", "loophistory", "chainhistory"], help="세계 사건·원정·NPC·시즌 결정·연결 보상의 최근 연동 기록을 확인합니다.")
    async def connected_history(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx); user = _safe_user(get_user, ctx.author.id); row = _root(user)
        history = row.get("history", []) if isinstance(row.get("history"), list) else []
        lines = []
        type_labels = {
            "world_event": ("세계 사건", "World event"), "expedition": ("솔로 원정", "Solo expedition"),
            "npc_mission": ("NPC 동행", "NPC mission"), "season6_echo": ("시즌 6 반영", "Season 6 echo"),
            "daily_chain_reward": ("연결 보상", "Connected reward"),
        }
        for item in reversed(history[-15:]):
            if not isinstance(item, Mapping):
                continue
            at = int(item.get("at", 0) or 0)
            stamp = datetime.fromtimestamp(at, KST).strftime("%m-%d %H:%M") if at else "-"
            labels = type_labels.get(str(item.get("type")), (str(item.get("type", "update")), str(item.get("type", "update"))))
            detail = str(item.get("detail") or item.get("result") or item.get("day") or "")
            lines.append(f"• `{stamp}` **{_t(locale, *labels)}** {detail}".rstrip())
        embed = discord.Embed(title=_t(locale, "📜 연결 생존 연대기", "📜 Connected Survival Chronicle"), description="\n".join(lines) or _t(locale, "아직 연결 기록이 없습니다.", "No connected history yet."), color=0x7E57C2)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="연결동기화", aliases=["syncsurvivalloop", "linksync", "connectedsync"], help="현재 스토리·세계·NPC·도시 상태를 연결 허브에 다시 동기화합니다.")
    async def connected_sync(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); user = _safe_user(get_user, ctx.author.id); gid = int(ctx.guild.id if ctx.guild else 0)
        _sync(user, world_data, gid, save_data); save_data()
        await ctx.send(_t(locale, "🔄 현재 스토리·세계·NPC·도시 상태를 다시 연결했습니다.", "🔄 Re-synced current story, world, NPC and city state."), embed=_connected_embed(locale, user, world_data, gid, save_data))

    @bot.command(name="1730연결검수", aliases=["v1730linkaudit", "connectedloopaudit"], help="v17.3 스토리·세계·원정·NPC·재료·도시 연결 훅을 검사합니다.")
    async def connected_audit(ctx: commands.Context, detail: str = "") -> None:
        locale = _ctx_locale(bot, ctx)
        required = ["연결허브", "연결목표", "연결보상", "재료용도", "도시효과", "연결기록", "연결동기화"]
        checks = [(name, bot.get_command(name) is not None) for name in required]
        checks.extend([
            ("Season 6 command group", isinstance(bot.get_command("시즌6"), commands.Group)),
            ("NPC bond category", hub._classify(bot.get_command("인연")) == ("social", "npc") if bot.get_command("인연") else False),
            ("Connected hub category", hub._classify(bot.get_command("연결허브")) == ("main", "connections") if bot.get_command("연결허브") else False),
            ("Four daily objectives", len(_objective_lines("ko", {})) == 4),
            ("City effect rules", len(CITY_EFFECT_RULES) >= 15),
            ("Material use map", len(MATERIAL_USES) >= 7),
        ])
        ok = all(value for _name, value in checks)
        embed = discord.Embed(title=_t(locale, "🔗 ABADDON v17.3 연결 검수", "🔗 ABADDON v17.3 Connected Audit"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if ok else 0xE74C3C)
        if detail:
            embed.add_field(name=_t(locale, "연결 범위", "Connected Scope"), value="Story → Living World → Expedition → NPC Bonds → Materials/Crafting → City Effects → Survivor Hub", inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1730통합검수", aliases=["v1730audit", "1730audit"], help="v17.2.1 마감과 v17.3 연결 생존 루프 전체를 통합 검사합니다.")
    async def audit_1730(ctx: commands.Context, detail: str = "") -> None:
        locale = _ctx_locale(bot, ctx); entries = hub._build_registry(bot)
        required = ["시즌6", "콘텐츠공방", "살아있는세계", "인연", "연결허브", "연결목표", "연결보상", "재료용도", "도시효과"]
        checks = [(name, bot.get_command(name) is not None) for name in required]
        checks.extend([
            ("Season 6 command group", isinstance(bot.get_command("시즌6"), commands.Group)),
            ("Creator Forge command group", isinstance(bot.get_command("콘텐츠공방"), commands.Group)),
            ("NPC bond category", any(e.group == "npc" and e.name == "인연" for e in entries)),
            ("Connected Survival category", any(e.group == "connections" and e.name == "연결허브" for e in entries)),
            ("Korean / English separation", bot.get_command("명령어") is not None and bot.get_command("help") is not None),
            ("Legacy systems preserved", all(bot.get_command(name) is not None for name in ("솔로원정", "도시꾸미기", "카지노", "도박정보"))),
        ])
        ok = all(value for _name, value in checks)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.3.0 통합 검수", "🧪 ABADDON v17.3.0 Integration Audit"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if ok else 0xE74C3C)
        if detail:
            embed.add_field(name=_t(locale, "보존", "Preservation"), value=_t(locale, "기존 명령·저장 데이터 삭제 0건 · 연결 기록과 일일 목표만 추가", "0 legacy commands or saves removed · only connected history and daily objectives added"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    # Replace the previous audits with corrected runtime checks so old red X rows do not survive.
    old_1700 = bot.get_command("1700통합검수")
    if old_1700 is not None:
        async def audit_1700_v1730(ctx: commands.Context, detail: str = "") -> None:
            locale = _ctx_locale(bot, ctx); entries = hub._build_registry(bot)
            checks = [
                ("명령어", bot.get_command("명령어") is not None), ("help", bot.get_command("help") is not None),
                ("콘텐츠공방", isinstance(bot.get_command("콘텐츠공방"), commands.Group)),
                ("사용자사건", bot.get_command("사용자사건") is not None),
                ("시즌6", isinstance(bot.get_command("시즌6"), commands.Group)),
                ("Creator Forge category", any(e.group == "creator" and e.name == "콘텐츠공방" for e in entries)),
                ("Season 6 category", any(e.group == "story6" and e.name == "시즌6" for e in entries)),
            ]
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.0.1 마감 검수", "🧪 ABADDON v17.0.1 Final Audit"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if all(v for _, v in checks) else 0xE74C3C)
            if detail:
                embed.add_field(name=_t(locale, "수정", "Fix"), value=_t(locale, "콘텐츠 공방과 시즌 6을 실제 상위 그룹으로 유지하고 최신 런타임 분류로 검사합니다.", "Validates Creator Forge and Season 6 as real command groups using current runtime classification."), inline=False)
            await ctx.send(embed=_safe_embed(embed))
        old_1700.callback = audit_1700_v1730

    old_1720 = bot.get_command("1720통합검수")
    if old_1720 is not None:
        async def audit_1720_v1730(ctx: commands.Context, detail: str = "") -> None:
            locale = _ctx_locale(bot, ctx); entries = hub._build_registry(bot)
            checks = [
                ("콘텐츠공방", isinstance(bot.get_command("콘텐츠공방"), commands.Group)),
                ("살아있는세계", bot.get_command("살아있는세계") is not None),
                ("오늘의세계사건", bot.get_command("오늘의세계사건") is not None),
                ("인연", bot.get_command("인연") is not None),
                ("NPC목록", bot.get_command("NPC목록") is not None),
                ("Creator Forge category", any(e.group == "creator" and e.name == "콘텐츠공방" for e in entries)),
                ("Living world category", any(e.group == "world_misc" and e.name == "살아있는세계" for e in entries)),
                ("NPC bond category", any(e.group == "npc" and e.name == "인연" for e in entries)),
                ("Korean / English separation", bot.get_command("명령어") is not None and bot.get_command("help") is not None),
                ("Legacy Season 6 preserved", isinstance(bot.get_command("시즌6"), commands.Group)),
            ]
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.2.1 마감 검수", "🧪 ABADDON v17.2.1 Final Audit"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if all(v for _, v in checks) else 0xE74C3C)
            if detail:
                embed.add_field(name=_t(locale, "수정", "Fix"), value=_t(locale, "Season 6 그룹과 NPC 인연 카테고리를 실제 런타임 기준으로 다시 연결했습니다.", "Re-linked the Season 6 group and NPC bond category using live runtime classification."), inline=False)
            await ctx.send(embed=_safe_embed(embed))
        old_1720.callback = audit_1720_v1730

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1730(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, "🔗 ABADDON v17.3.0 · CONNECTED SURVIVAL LOOP", "🔗 ABADDON v17.3.0 · CONNECTED SURVIVAL LOOP"), description=_t(locale, "스토리·세계·원정·NPC·제작·도시를 하나의 플레이 흐름으로 연결했습니다.", "Connected story, world, expedition, NPC, crafting and city systems into one play loop."), color=0x5E35B1)
            embed.add_field(name=_t(locale, "🩹 v17.2.1 마감", "🩹 v17.2.1 Finalization"), value=_t(locale, "시즌 6 상위 그룹과 NPC 인연 카테고리 검수의 잘못된 빨간 X를 실제 구조 기준으로 수정했습니다.", "Fixed false red X results for the Season 6 group and NPC bond category using the actual runtime structure."), inline=False)
            embed.add_field(name=_t(locale, "🔗 연결 생존 허브", "🔗 Connected Survival Hub"), value=_t(locale, "현재 스토리·세계 사건·위험 지역·NPC 인연·도시 효과·오늘 목표를 한 화면에 표시합니다.", "Shows story, world event, risky region, NPC bonds, city effects and daily goals in one screen."), inline=False)
            embed.add_field(name=_t(locale, "🎯 일일 연결 목표", "🎯 Daily Connected Objectives"), value=_t(locale, "세계 사건·솔로 원정·NPC 동행·도시 공방 중 3개를 완료해 연결 보상을 받습니다.", "Complete 3 of 4: world event, solo expedition, NPC mission and city workshop."), inline=False)
            embed.add_field(name=_t(locale, "🧰 재료·도시 효과", "🧰 Materials & City Effects"), value=_t(locale, "재료 사용처를 안내하고 도시 부품이 세계 시장 할인과 연결 보상에 실제 반영됩니다.", "Explains material uses and applies city decorations to world-market discounts and connected rewards."), inline=False)
            embed.add_field(name=_t(locale, "🧪 점검", "🧪 Checks"), value="`!1730연결검수 상세` · `!1730통합검수 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건", "0 legacy features or save data removed"))
            await ctx.send(embed=_safe_embed(embed))
        patch.callback = patch_v1730; patch.help = "ABADDON v17.3.0 최신 패치노트입니다."; patch.description = patch.help

    test = bot.get_command("테스트")
    if test is not None:
        async def test_v1730(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            locale = _ctx_locale(bot, ctx)
            required = ["연결허브", "연결목표", "연결보상", "재료용도", "도시효과", "1730통합검수"]
            checks = [(name, bot.get_command(name) is not None) for name in required]
            checks.extend([("Season 6 Group", isinstance(bot.get_command("시즌6"), commands.Group)), ("NPC Category", hub._classify(bot.get_command("인연")) == ("social", "npc") if bot.get_command("인연") else False)])
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.3 최신 테스트", "🧪 ABADDON v17.3 Latest Test"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if all(v for _, v in checks) else 0xE74C3C)
            if str(mode).casefold() in {"상세", "detail", "full"}:
                embed.add_field(name=_t(locale, "범위", "Scope"), value="Story · Living World · Expedition · NPC Bonds · Material Uses · City Effects · KO/EN split", inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback = test_v1730; test.help = "v17.3 연결 생존 루프 최신 범위를 검사합니다."; test.description = test.help

    entries = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {entry.qualified_name: entry for entry in entries})
    guide.append({
        "id": "v1730_connected_survival_loop", "emoji": "🔗", "title": "v17.3 CONNECTED SURVIVAL LOOP",
        "hint": "스토리→세계→원정→NPC→재료·제작→도시를 일일 목표와 결과 변화로 연결",
        "commands": [
            "!연결허브 · !연결목표 · !연결보상 · !연결기록",
            "!재료용도 · !도시효과 · !연결동기화",
            "!1730연결검수 상세 · !1730통합검수 상세",
        ],
    })
    print(f"[ABADDON v{VERSION}] connected survival loop registered: commands={len(entries)} materials={len(MATERIAL_USES)} city_rules={len(CITY_EFFECT_RULES)}", flush=True)


__all__ = ["register_v1730_connected_survival_loop", "_root", "_city_effects", "_daily_status", "MATERIAL_USES", "CITY_EFFECT_RULES"]
