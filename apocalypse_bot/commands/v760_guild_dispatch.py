from __future__ import annotations

import asyncio
import copy
import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v750_guild_raid import (
    RESOURCE_KEYS,
    _format_seconds,
    _guild_lock,
    _iso,
    _log,
    _now,
    _parse_iso,
    _safe_int,
    _set_vault_balance,
    _vault_balance,
    _vault_log,
    can_manage_guild,
    ensure_guild_state,
    facility_effects,
    guild_for_user,
    sync_guild_food,
)

VERSION = "7.6.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))

ROLE_ALIASES = {
    "선봉": "vanguard", "돌격": "vanguard", "전투": "vanguard", "vanguard": "vanguard",
    "기술": "engineer", "기술자": "engineer", "정비": "engineer", "engineer": "engineer",
    "의무": "medic", "의무병": "medic", "치료": "medic", "medic": "medic",
    "보급": "quartermaster", "지원": "quartermaster", "운반": "quartermaster", "quartermaster": "quartermaster",
}
ROLE_LABELS = {
    "vanguard": "⚔️ 선봉",
    "engineer": "🧰 기술",
    "medic": "🏥 의무",
    "quartermaster": "📦 보급",
}
ROLE_POWER = {"vanguard": 1.10, "engineer": 1.06, "medic": 0.96, "quartermaster": 1.00}

DISPATCH_ROUTES: Dict[str, Dict[str, Any]] = {
    "supply": {
        "name": "폐허 보급로", "emoji": "🚚", "aliases": ("보급로", "폐허보급로", "보급", "supply"),
        "duration": 600, "required_power": 220,
        "cost": {"food": 20_000},
        "guild_reward": {"food": 48_000, "나무": 18, "고철": 12},
        "personal_food": 7_000, "season_points": 6,
        "desc": "낮은 위험도의 식량·건축 자원 회수 작전입니다.",
    },
    "flooded": {
        "name": "침수 산업지대", "emoji": "🌊", "aliases": ("침수", "침수공단", "산업지대", "flooded"),
        "duration": 1_800, "required_power": 650,
        "cost": {"food": 55_000, "고철": 15},
        "guild_reward": {"food": 120_000, "광석": 24, "고철": 42},
        "personal_food": 16_000, "season_points": 12,
        "desc": "침수된 공장 설비를 수색해 광석과 고철을 회수합니다.",
    },
    "lab": {
        "name": "격리연구소 외곽", "emoji": "☣️", "aliases": ("연구소", "격리연구소", "연구소외곽", "lab"),
        "duration": 3_600, "required_power": 1_400,
        "cost": {"food": 110_000, "약초": 25, "고철": 25},
        "guild_reward": {"food": 245_000, "약초": 70, "고철": 55},
        "personal_food": 32_000, "season_points": 22,
        "personal_material": ("전술 데이터", 1),
        "desc": "감염 표본과 전술 기록을 회수하는 고위험 파견입니다.",
    },
    "terminal": {
        "name": "황혼 철도 종착지", "emoji": "🚂", "aliases": ("종착지", "황혼종착지", "황혼철도", "terminal"),
        "duration": 7_200, "required_power": 2_800,
        "cost": {"food": 220_000, "광석": 50, "고철": 60},
        "guild_reward": {"food": 520_000, "광석": 95, "고철": 120, "약초": 45},
        "personal_food": 68_000, "season_points": 40,
        "personal_material": ("길드훈장", 1),
        "desc": "시즌 4 지역을 재수색하는 최상위 협동 파견입니다.",
    },
}

_ROUTE_LOOKUP: Dict[str, str] = {}
for _key, _row in DISPATCH_ROUTES.items():
    _ROUTE_LOOKUP[_key.casefold()] = _key
    _ROUTE_LOOKUP[str(_row["name"]).replace(" ", "").casefold()] = _key
    for _alias in _row["aliases"]:
        _ROUTE_LOOKUP[str(_alias).replace(" ", "").casefold()] = _key


def route_key(value: Any) -> Optional[str]:
    raw = str(value or "").strip().replace(" ", "").casefold()
    return _ROUTE_LOOKUP.get(raw)


def role_key(value: Any) -> Optional[str]:
    return ROLE_ALIASES.get(str(value or "").strip().casefold())


def _dispatch_id(guild_id: Any, created_at: str) -> str:
    digest = hashlib.sha256(f"{guild_id}:{created_at}".encode("utf-8")).hexdigest()[:8].upper()
    return f"D{datetime.now(KST).strftime('%y%m%d')}-{digest}"


def _safe_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def ensure_dispatch_state(guild: MutableMapping[str, Any]) -> Dict[str, Any]:
    state = guild.get("dispatch")
    if not isinstance(state, dict):
        state = {}
        guild["dispatch"] = state
    state["schema_version"] = SCHEMA_VERSION
    planning = state.get("planning")
    if not isinstance(planning, dict):
        planning = {}
    if planning:
        route = route_key(planning.get("route"))
        participants = planning.get("participants") if isinstance(planning.get("participants"), dict) else {}
        cleaned: Dict[str, Dict[str, str]] = {}
        for uid, row in participants.items():
            if not isinstance(row, dict):
                continue
            role = role_key(row.get("role")) or "vanguard"
            cleaned[str(uid)] = {"role": role, "joined_at": str(row.get("joined_at") or _iso())}
        planning["route"] = route or "supply"
        planning["participants"] = cleaned
        planning["opened_at"] = str(planning.get("opened_at") or _iso())
        opened = _parse_iso(planning.get("opened_at"))
        # 24시간 방치된 모집은 비용 차감 없이 안전하게 자동 종료합니다.
        if opened and (_now() - opened).total_seconds() > 86_400:
            planning = {}
    state["planning"] = planning

    active = state.get("active")
    if not isinstance(active, dict):
        active = {}
    if active:
        active["id"] = str(active.get("id") or _dispatch_id("legacy", str(active.get("started_at") or _iso())))
        active["route"] = route_key(active.get("route")) or "supply"
        active["participants"] = active.get("participants") if isinstance(active.get("participants"), dict) else {}
        active["resolved"] = bool(active.get("resolved", False))
    state["active"] = active

    state["history"] = _safe_list(state.get("history"))
    pending = state.get("pending_rewards")
    if not isinstance(pending, dict):
        pending = {}
    for uid, rows in list(pending.items()):
        pending[str(uid)] = _safe_list(rows)
    state["pending_rewards"] = pending
    state["claimed"] = [str(x) for x in state.get("claimed", [])] if isinstance(state.get("claimed"), list) else []
    state["stats"] = state.get("stats") if isinstance(state.get("stats"), dict) else {}
    for key in ("started", "resolved", "success", "failed", "claims"):
        state["stats"][key] = max(0, _safe_int(state["stats"].get(key), 0, 0))
    return state


def _cost_lines(route: Mapping[str, Any]) -> str:
    rows = []
    for currency, amount in route.get("cost", {}).items():
        label = "식량" if currency == "food" else currency
        rows.append(f"{label} {int(amount):,}")
    return " · ".join(rows) or "무료"


def _reward_lines(route: Mapping[str, Any]) -> str:
    rows = []
    for currency, amount in route.get("guild_reward", {}).items():
        label = "식량" if currency == "food" else currency
        rows.append(f"{label} {int(amount):,}")
    return " · ".join(rows)


def _participant_power(user: Mapping[str, Any], role: str, calculate_user_power: Callable[[Mapping[str, Any]], int]) -> int:
    base = max(1, int(calculate_user_power(user)))
    return max(1, int(base * ROLE_POWER.get(role, 1.0)))


def _resolve_preview(
    guild: Mapping[str, Any], route: Mapping[str, Any], participants: Mapping[str, Mapping[str, Any]], seed: int,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    role_set = {str(row.get("role")) for row in participants.values() if isinstance(row, Mapping)}
    raw_power = sum(max(1, _safe_int(row.get("power"), 1, 1)) for row in participants.values() if isinstance(row, Mapping))
    diversity_bonus = 1.0 + max(0, len(role_set) - 1) * 0.06
    effects = facility_effects(guild)
    facility_bonus = 1.0 + effects["raid_damage_bonus"] + effects["raid_support_bonus"]
    roll = rng.uniform(0.88, 1.14)
    score = max(1, int(raw_power * diversity_bonus * facility_bonus * roll))
    required = max(1, int(route["required_power"]))
    ratio = score / required
    success = ratio >= 1.0
    critical = success and ratio >= 1.45 and rng.random() < min(0.70, 0.30 + (ratio - 1.45) * 0.25)
    reward_factor = 1.35 if critical else (1.0 if success else 0.25)
    if "quartermaster" in role_set:
        reward_factor += 0.10 if success else 0.03
    if "medic" in role_set and not success:
        reward_factor += 0.10
    reward_factor *= 1.0 + effects["raid_reward_bonus"]
    return {
        "score": score, "required": required, "ratio": ratio, "success": success, "critical": critical,
        "reward_factor": max(0.0, reward_factor), "raw_power": raw_power,
        "roles": sorted(role_set), "roll": roll,
    }


def _deposit_shared_rewards(guild: MutableMapping[str, Any], route: Mapping[str, Any], factor: float, actor: Any, dispatch_id: str) -> Dict[str, Dict[str, int]]:
    effects = facility_effects(guild)
    accepted: Dict[str, int] = {}
    overflow: Dict[str, int] = {}
    for currency, base_amount in route.get("guild_reward", {}).items():
        amount = max(0, int(int(base_amount) * factor))
        capacity = int(effects["food_capacity"] if currency == "food" else effects["resource_capacity"])
        current = _vault_balance(guild, currency)
        take = min(amount, max(0, capacity - current))
        lost = max(0, amount - take)
        if take:
            _set_vault_balance(guild, currency, current + take)
            _vault_log(guild, "dispatch_reward", actor, currency, take, dispatch_id)
        accepted[currency] = take
        overflow[currency] = lost
    sync_guild_food(guild)
    return {"accepted": accepted, "overflow": overflow}


def _personal_reward(route: Mapping[str, Any], result: Mapping[str, Any]) -> Dict[str, Any]:
    factor = float(result.get("reward_factor", 0.0) or 0.0)
    food = max(0, int(int(route.get("personal_food", 0)) * factor))
    season = max(0, int(int(route.get("season_points", 0)) * (1.25 if result.get("critical") else (1.0 if result.get("success") else 0.35))))
    material = route.get("personal_material")
    material_name = ""
    material_amount = 0
    if isinstance(material, (tuple, list)) and len(material) == 2 and result.get("success"):
        material_name = str(material[0])
        material_amount = max(0, int(material[1])) * (2 if result.get("critical") else 1)
    return {"food": food, "season_points": season, "material": material_name, "material_amount": material_amount}


def _format_reward_map(values: Mapping[str, Any]) -> str:
    lines = []
    for currency, amount in values.items():
        amount = _safe_int(amount, 0, 0)
        if amount <= 0:
            continue
        lines.append(f"{'식량' if currency == 'food' else currency} {amount:,}")
    return " · ".join(lines) or "없음"


def register_v760_guild_dispatch(
    bot: commands.Bot,
    get_user: Callable[[Any], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
    add_season_points: Callable[[MutableMapping[str, Any], int], Any],
) -> None:
    if getattr(bot, "_abaddon_v760_registered", False):
        return

    guild_category = next((row for row in guide if row.get("id") == "guild_party"), None)
    if guild_category is not None:
        additions = (
            "!길드파견 — 비동기 협동 파견 상태와 지역 목록",
            "!길드파견모집 지역 · !길드파견참가 역할 · !길드파견출발",
            "!길드파견정산 · !길드파견보상 · !길드파견기록",
            "!길드파견모의 지역 역할 — 데이터 변경 없는 결과 예측",
        )
        existing = "\n".join(map(str, guild_category.get("commands", [])))
        for row in additions:
            token = row.split(" — ", 1)[0].split(" · ", 1)[0]
            if token not in existing:
                guild_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    admin_category = next((row for row in guide if row.get("id") == "server"), None)
    if admin_category is not None:
        row = "!760안정화검수 — 파견 중복 정산·잠금·저장 구조 읽기 전용 검사"
        if row.split(" — ", 1)[0] not in "\n".join(map(str, admin_category.get("commands", []))):
            admin_category.setdefault("commands", []).append(row)

    async def require_guild(ctx: commands.Context) -> Tuple[Optional[MutableMapping[str, Any]], Optional[str], Optional[MutableMapping[str, Any]]]:
        if not await check_registered(ctx):
            return None, None, None
        user = get_user(ctx.author.id)
        gid, guild = guild_for_user(world_data, user)
        if not gid or not guild:
            await ctx.send("⚠️ 소속된 길드가 없습니다. `!길드목록`에서 길드를 찾거나 `!길드생성 이름`을 사용하세요.")
            return None, None, None
        ensured, _repairs = ensure_guild_state(gid, guild)
        world_data.setdefault("guilds", {})[str(gid)] = ensured
        ensure_dispatch_state(ensured)
        return user, str(gid), ensured

    def participant_user(uid: Any) -> Optional[MutableMapping[str, Any]]:
        return get_user(str(uid))

    async def resolve_if_ready(gid: str, guild: MutableMapping[str, Any], actor: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        state = ensure_dispatch_state(guild)
        active = state.get("active") if isinstance(state.get("active"), dict) else {}
        if not active:
            return None, "진행 중인 길드 파견이 없습니다."
        if active.get("resolved"):
            return active.get("result") if isinstance(active.get("result"), dict) else {}, None
        ends_at = _parse_iso(active.get("ends_at"))
        if not ends_at or _now() < ends_at:
            remaining = max(0, (ends_at - _now()).total_seconds()) if ends_at else 0
            return None, f"파견대가 아직 복귀하지 않았습니다. 남은 시간 **{_format_seconds(remaining)}**"
        route = DISPATCH_ROUTES[route_key(active.get("route")) or "supply"]
        seed = _safe_int(active.get("seed"), 1, 1)
        participants = active.get("participants") if isinstance(active.get("participants"), dict) else {}
        result = _resolve_preview(guild, route, participants, seed)
        shared = _deposit_shared_rewards(guild, route, float(result["reward_factor"]), actor, str(active.get("id")))
        result["shared"] = shared
        result["resolved_at"] = _iso()
        active["result"] = result
        active["resolved"] = True
        active["status"] = "critical" if result["critical"] else ("success" if result["success"] else "failed")
        active["resolved_at"] = result["resolved_at"]
        pending = state.setdefault("pending_rewards", {})
        reward = _personal_reward(route, result)
        for uid in participants:
            rows = pending.setdefault(str(uid), [])
            claim_key = f"{active['id']}:{uid}"
            if any(str(row.get("claim_key")) == claim_key for row in rows if isinstance(row, dict)):
                continue
            rows.append({"claim_key": claim_key, "dispatch_id": active["id"], "route": active["route"], **reward, "created_at": _iso()})
        history_row = copy.deepcopy(active)
        state.setdefault("history", []).append(history_row)
        state["active"] = {}
        state["stats"]["resolved"] += 1
        state["stats"]["success" if result["success"] else "failed"] += 1
        guild.setdefault("stats", {})["dispatches_completed"] = max(0, _safe_int(guild.setdefault("stats", {}).get("dispatches_completed"), 0, 0)) + 1
        _log(guild, "dispatch_resolved", actor, f"{active['id']} route={active['route']} status={active['status']} score={result['score']}")
        save_data()
        return result, None

    @bot.command(name="길드파견", aliases=["길드원정", "길드탐사대"], help="길드 협동 파견 상태와 지역을 확인합니다.")
    async def guild_dispatch(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        state = ensure_dispatch_state(guild)
        active = state.get("active") if isinstance(state.get("active"), dict) else {}
        planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
        embed = discord.Embed(title=f"🧭 {guild['name']} 길드 파견 지휘소", colour=discord.Colour.dark_teal())
        route_lines = []
        for key, route in DISPATCH_ROUTES.items():
            route_lines.append(
                f"{route['emoji']} **{route['name']}** · {_format_seconds(route['duration'])}\n"
                f"전투력 {route['required_power']:,} · 비용 {_cost_lines(route)}\n{route['desc']}"
            )
        embed.add_field(name="파견 지역", value="\n\n".join(route_lines), inline=False)
        if active:
            route = DISPATCH_ROUTES[route_key(active.get("route")) or "supply"]
            ends_at = _parse_iso(active.get("ends_at"))
            remaining = max(0, (ends_at - _now()).total_seconds()) if ends_at else 0
            embed.add_field(
                name="🚨 진행 중",
                value=f"{route['emoji']} {route['name']} · 참가 {len(active.get('participants', {}))}명\n복귀까지 **{_format_seconds(remaining)}** · ID `{active.get('id')}`",
                inline=False,
            )
        elif planning:
            route = DISPATCH_ROUTES[route_key(planning.get("route")) or "supply"]
            role_counts: Dict[str, int] = {}
            for row in planning.get("participants", {}).values():
                role = str(row.get("role")) if isinstance(row, dict) else "vanguard"
                role_counts[role] = role_counts.get(role, 0) + 1
            roles = " · ".join(f"{ROLE_LABELS.get(k, k)} {v}명" for k, v in role_counts.items()) or "참가자 없음"
            embed.add_field(name="📣 모집 중", value=f"{route['emoji']} {route['name']} · {len(planning.get('participants', {}))}명\n{roles}", inline=False)
        else:
            embed.add_field(name="현재 상태", value="진행 중인 모집·파견이 없습니다.", inline=False)
        embed.add_field(name="사용법", value="`!길드파견모집 지역` → `!길드파견참가 역할` → `!길드파견출발`\n복귀 후 `!길드파견정산` · 개인 보상 `!길드파견보상`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="길드파견모집", aliases=["길드파견준비", "길드원정모집"], help="길드 파견 참가자를 모집합니다.")
    async def guild_dispatch_open(ctx: commands.Context, *, 지역: str = "") -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        key = route_key(지역)
        if not key:
            await ctx.send("⚠️ 지역은 `보급로 / 침수공단 / 연구소 / 종착지` 중 하나를 입력하세요.")
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🛡️ 길드장·간부 또는 Discord 관리자만 파견 모집을 열 수 있습니다.")
            return
        async with _guild_lock(bot, gid):
            state = ensure_dispatch_state(guild)
            if state.get("active"):
                await ctx.send("⚠️ 이미 진행 중인 길드 파견이 있습니다.")
                return
            if state.get("planning"):
                await ctx.send("⚠️ 이미 모집 중인 길드 파견이 있습니다. `!길드파견취소` 후 다시 열어주세요.")
                return
            now = _iso()
            state["planning"] = {
                "route": key, "opened_by": str(ctx.author.id), "opened_at": now,
                "participants": {str(ctx.author.id): {"role": "vanguard", "joined_at": now}},
            }
            _log(guild, "dispatch_open", ctx.author.id, f"route={key}")
            save_data()
        route = DISPATCH_ROUTES[key]
        await ctx.send(f"📣 **{route['emoji']} {route['name']}** 파견 모집을 시작했습니다.\n참가: `!길드파견참가 선봉/기술/의무/보급` · 출발 비용: **{_cost_lines(route)}**")

    @bot.command(name="길드파견참가", aliases=["길드원정참가", "파견참가"], help="모집 중인 길드 파견에 역할을 선택해 참가합니다.")
    async def guild_dispatch_join(ctx: commands.Context, 역할: str = "선봉") -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        role = role_key(역할)
        if not role:
            await ctx.send("⚠️ 역할은 `선봉 / 기술 / 의무 / 보급` 중 하나를 입력하세요.")
            return
        async with _guild_lock(bot, gid):
            state = ensure_dispatch_state(guild)
            planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
            if not planning:
                await ctx.send("⚠️ 현재 모집 중인 길드 파견이 없습니다.")
                return
            planning.setdefault("participants", {})[str(ctx.author.id)] = {"role": role, "joined_at": _iso()}
            _log(guild, "dispatch_join", ctx.author.id, f"route={planning.get('route')} role={role}")
            save_data()
        await ctx.send(f"✅ 길드 파견에 **{ROLE_LABELS[role]}** 역할로 참가했습니다.")

    @bot.command(name="길드파견이탈", aliases=["길드원정이탈", "파견이탈"], help="출발 전 길드 파견 모집에서 이탈합니다.")
    async def guild_dispatch_leave(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        removed = False
        async with _guild_lock(bot, gid):
            planning = ensure_dispatch_state(guild).get("planning")
            if isinstance(planning, dict):
                removed = planning.get("participants", {}).pop(str(ctx.author.id), None) is not None
                if removed:
                    _log(guild, "dispatch_leave", ctx.author.id, f"route={planning.get('route')}")
                    save_data()
        await ctx.send("✅ 파견 모집에서 이탈했습니다." if removed else "⚠️ 참가 중인 파견 모집이 없습니다.")

    @bot.command(name="길드파견취소", aliases=["길드원정취소", "파견모집취소"], help="출발 전 길드 파견 모집을 취소합니다.")
    async def guild_dispatch_cancel(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🛡️ 길드장·간부 또는 Discord 관리자만 모집을 취소할 수 있습니다.")
            return
        async with _guild_lock(bot, gid):
            state = ensure_dispatch_state(guild)
            if not state.get("planning"):
                await ctx.send("⚠️ 취소할 파견 모집이 없습니다.")
                return
            route = state["planning"].get("route")
            state["planning"] = {}
            _log(guild, "dispatch_cancel", ctx.author.id, f"route={route}")
            save_data()
        await ctx.send("🧹 길드 파견 모집을 취소했습니다. 출발 전이라 비용은 차감되지 않았습니다.")

    @bot.command(name="길드파견출발", aliases=["길드원정출발", "파견출발"], help="모집한 길드 파견대를 출발시킵니다.")
    async def guild_dispatch_start(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🛡️ 길드장·간부 또는 Discord 관리자만 파견대를 출발시킬 수 있습니다.")
            return
        error: Optional[str] = None
        active: Dict[str, Any] = {}
        async with _guild_lock(bot, gid):
            state = ensure_dispatch_state(guild)
            if state.get("active"):
                error = "⚠️ 이미 진행 중인 길드 파견이 있습니다."
            planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
            if not error and not planning:
                error = "⚠️ 먼저 `!길드파견모집 지역`으로 모집을 열어주세요."
            participants = planning.get("participants", {}) if planning else {}
            valid_ids = {str(uid) for uid in guild.get("members", [])}
            participants = {str(uid): row for uid, row in participants.items() if str(uid) in valid_ids and isinstance(row, dict)}
            if not error and not participants:
                error = "⚠️ 출발할 길드원이 없습니다. 최소 1명은 참가해야 합니다."
            key = route_key(planning.get("route")) if planning else None
            route = DISPATCH_ROUTES[key or "supply"]
            if not error:
                missing = []
                for currency, amount in route["cost"].items():
                    have = _vault_balance(guild, currency)
                    if have < int(amount):
                        missing.append(f"{'식량' if currency == 'food' else currency} {int(amount) - have:,}")
                if missing:
                    error = "📦 길드 금고 자원이 부족합니다: " + " · ".join(missing)
            snapshots: Dict[str, Dict[str, Any]] = {}
            if not error:
                for uid, row in participants.items():
                    member_user = participant_user(uid)
                    if not member_user:
                        continue
                    role = role_key(row.get("role")) or "vanguard"
                    snapshots[uid] = {
                        "role": role,
                        "power": _participant_power(member_user, role, calculate_user_power),
                        "base_power": max(1, int(calculate_user_power(member_user))),
                        "joined_at": str(row.get("joined_at") or _iso()),
                    }
                if not snapshots:
                    error = "⚠️ 참가자의 캐릭터 데이터를 확인할 수 없습니다."
            if not error:
                for currency, amount in route["cost"].items():
                    _set_vault_balance(guild, currency, _vault_balance(guild, currency) - int(amount))
                    _vault_log(guild, "dispatch_cost", ctx.author.id, currency, -int(amount), route["name"])
                started_at = _iso()
                dispatch_id = _dispatch_id(gid, started_at)
                ends_at = _iso(_now() + timedelta(seconds=int(route["duration"])))
                seed = int(hashlib.sha256(f"{gid}:{dispatch_id}:{started_at}".encode("utf-8")).hexdigest()[:15], 16)
                active = {
                    "id": dispatch_id, "route": key, "started_by": str(ctx.author.id),
                    "started_at": started_at, "ends_at": ends_at, "seed": seed,
                    "participants": snapshots, "cost": copy.deepcopy(route["cost"]),
                    "status": "active", "resolved": False,
                }
                state["active"] = active
                state["planning"] = {}
                state["stats"]["started"] += 1
                guild.setdefault("stats", {})["dispatches_started"] = max(0, _safe_int(guild.setdefault("stats", {}).get("dispatches_started"), 0, 0)) + 1
                _log(guild, "dispatch_start", ctx.author.id, f"{dispatch_id} route={key} members={len(snapshots)}")
                save_data()
        if error:
            await ctx.send(error)
            return
        route = DISPATCH_ROUTES[str(active["route"])]
        await ctx.send(
            f"🚀 **{route['emoji']} {route['name']}** 파견대가 출발했습니다.\n"
            f"참가 **{len(active['participants'])}명** · 복귀 예정 **{_format_seconds(route['duration'])} 후** · ID `{active['id']}`\n"
            f"복귀 후 `!길드파견정산`을 실행하세요."
        )

    @bot.command(name="길드파견정산", aliases=["길드원정정산", "파견정산"], help="복귀한 길드 파견 결과를 한 번만 정산합니다.")
    async def guild_dispatch_settle(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not gid or not guild:
            return
        async with _guild_lock(bot, gid):
            result, error = await resolve_if_ready(gid, guild, ctx.author.id)
        if error:
            await ctx.send(error)
            return
        assert result is not None
        status = "🌟 대성공" if result.get("critical") else ("✅ 성공" if result.get("success") else "⚠️ 실패")
        shared = result.get("shared", {}) if isinstance(result.get("shared"), dict) else {}
        accepted = shared.get("accepted", {}) if isinstance(shared.get("accepted"), dict) else {}
        overflow = shared.get("overflow", {}) if isinstance(shared.get("overflow"), dict) else {}
        text = (
            f"{status} · 파견 점수 **{_safe_int(result.get('score'), 0):,}/{_safe_int(result.get('required'), 1):,}**\n"
            f"🏦 길드 금고 반영: **{_format_reward_map(accepted)}**\n"
            f"🎁 참가자는 `!길드파견보상`으로 개인 보상을 받을 수 있습니다."
        )
        if any(_safe_int(v, 0) > 0 for v in overflow.values()):
            text += f"\n📦 창고 한도 초과 미적재: **{_format_reward_map(overflow)}**"
        await ctx.send(text)

    @bot.command(name="길드파견보상", aliases=["길드원정보상", "파견보상"], help="완료된 길드 파견 개인 보상을 받습니다.")
    async def guild_dispatch_reward(ctx: commands.Context) -> None:
        user, gid, guild = await require_guild(ctx)
        if not gid or not guild or user is None:
            return
        uid = str(ctx.author.id)
        totals = {"food": 0, "season_points": 0}
        materials: Dict[str, int] = {}
        claimed_count = 0
        async with _guild_lock(bot, gid):
            state = ensure_dispatch_state(guild)
            rows = state.setdefault("pending_rewards", {}).get(uid, [])
            unclaimed = [row for row in rows if isinstance(row, dict) and str(row.get("claim_key")) not in set(state.get("claimed", []))]
            if not unclaimed:
                await ctx.send("📭 수령 가능한 길드 파견 개인 보상이 없습니다.")
                return
            for row in unclaimed:
                claim_key = str(row.get("claim_key"))
                if claim_key in state["claimed"]:
                    continue
                totals["food"] += max(0, _safe_int(row.get("food"), 0, 0))
                totals["season_points"] += max(0, _safe_int(row.get("season_points"), 0, 0))
                material = str(row.get("material") or "")
                amount = max(0, _safe_int(row.get("material_amount"), 0, 0))
                if material and amount:
                    materials[material] = materials.get(material, 0) + amount
                state["claimed"].append(claim_key)
                claimed_count += 1
            user["balance"] = max(0, _safe_int(user.get("balance"), 0, 0)) + totals["food"]
            if totals["season_points"]:
                add_season_points(user, totals["season_points"])
            bag = user.setdefault("materials", {})
            if not isinstance(bag, dict):
                bag = {}
                user["materials"] = bag
            for name, amount in materials.items():
                bag[name] = max(0, _safe_int(bag.get(name), 0, 0)) + amount
            state["stats"]["claims"] += claimed_count
            user_claims = sum(1 for key in state["claimed"] if str(key).endswith(f":{uid}"))
            if user_claims >= 4:
                add_title(user, "파견대 핵심 요원")
            _log(guild, "dispatch_claim", uid, f"count={claimed_count} food={totals['food']} materials={materials}")
            save_data()
        extra = " · ".join(f"{name} {amount}개" for name, amount in materials.items())
        await ctx.send(f"🎁 파견 보상 **{claimed_count}건** 수령 · 식량 **{totals['food']:,}** · 시즌 점수 **{totals['season_points']}**" + (f" · {extra}" if extra else ""))

    @bot.command(name="길드파견기록", aliases=["길드원정기록", "파견기록"], help="길드 파견 기록을 페이지로 확인합니다.")
    async def guild_dispatch_history(ctx: commands.Context, 페이지: int = 1) -> None:
        _user, _gid, guild = await require_guild(ctx)
        if not guild:
            return
        rows = list(reversed(ensure_dispatch_state(guild).get("history", [])))
        if not rows:
            await ctx.send("📜 아직 완료된 길드 파견 기록이 없습니다.")
            return
        per_page = 5
        pages = max(1, (len(rows) + per_page - 1) // per_page)
        page = max(1, min(pages, _safe_int(페이지, 1, 1)))
        selected = rows[(page - 1) * per_page: page * per_page]
        embed = discord.Embed(title=f"📜 {guild['name']} 길드 파견 기록", colour=discord.Colour.blurple())
        for row in selected:
            route = DISPATCH_ROUTES[route_key(row.get("route")) or "supply"]
            result = row.get("result") if isinstance(row.get("result"), dict) else {}
            status = "🌟 대성공" if result.get("critical") else ("✅ 성공" if result.get("success") else "⚠️ 실패")
            embed.add_field(
                name=f"{route['emoji']} {route['name']} · {row.get('id')}",
                value=f"{status} · 점수 {_safe_int(result.get('score'), 0):,}/{_safe_int(result.get('required'), 1):,} · 참가 {len(row.get('participants', {}))}명\n{str(row.get('resolved_at') or row.get('started_at') or '')[:16]}",
                inline=False,
            )
        embed.set_footer(text=f"{page}/{pages} 페이지 · 기록은 자동 삭제하지 않습니다.")
        await ctx.send(embed=embed)

    @bot.command(name="길드파견모의", aliases=["길드원정모의", "파견연습"], help="실제 데이터 변경 없이 1인 길드 파견 결과를 예측합니다.")
    async def guild_dispatch_practice(ctx: commands.Context, 지역: str = "보급로", 역할: str = "선봉") -> None:
        user, _gid, guild = await require_guild(ctx)
        if not guild or user is None:
            return
        key = route_key(지역)
        role = role_key(역할)
        if not key or not role:
            await ctx.send("⚠️ 예: `!길드파견모의 연구소 기술` · 역할은 선봉/기술/의무/보급")
            return
        route = DISPATCH_ROUTES[key]
        participants = {str(ctx.author.id): {"role": role, "power": _participant_power(user, role, calculate_user_power)}}
        seed = int(hashlib.sha256(f"practice:{ctx.author.id}:{key}:{datetime.now(KST).strftime('%Y-%m-%d-%H')}".encode("utf-8")).hexdigest()[:15], 16)
        result = _resolve_preview(copy.deepcopy(guild), route, participants, seed)
        chance_note = "성공권" if result["ratio"] >= 1.0 else ("아슬아슬" if result["ratio"] >= 0.8 else "전력 부족")
        await ctx.send(
            f"🧪 **길드 파견 모의 계산** · 실제 금고·기록 변경 없음\n"
            f"{route['emoji']} {route['name']} · {ROLE_LABELS[role]} · 보정 전투력 **{participants[str(ctx.author.id)]['power']:,}**\n"
            f"예상 점수 **{result['score']:,}/{result['required']:,}** · 판정 **{chance_note}**\n"
            f"여러 역할이 모이면 역할 다양성 보너스가 추가됩니다."
        )

    @bot.command(name="760안정화검수", aliases=["길드파견검수", "v760검수"], help="길드 파견 저장·정산·중복 수령 구조를 읽기 전용으로 검사합니다.")
    @commands.has_permissions(administrator=True)
    async def v760_stability(ctx: commands.Context) -> None:
        guilds = world_data.get("guilds", {}) if isinstance(world_data.get("guilds"), dict) else {}
        issues: List[str] = []
        checked = 0
        for gid, raw in guilds.items():
            if not isinstance(raw, dict):
                issues.append(f"{gid}: 길드 레코드가 객체가 아님")
                continue
            checked += 1
            state = ensure_dispatch_state(raw)
            active = state.get("active") if isinstance(state.get("active"), dict) else {}
            planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
            if active and planning:
                issues.append(f"{gid}: active와 planning이 동시에 존재")
            ids = [str(row.get("id")) for row in state.get("history", []) if isinstance(row, dict) and row.get("id")]
            if len(ids) != len(set(ids)):
                issues.append(f"{gid}: 파견 기록 ID 중복")
            claimed = [str(x) for x in state.get("claimed", [])]
            if len(claimed) != len(set(claimed)):
                issues.append(f"{gid}: 개인 보상 claim key 중복")
            for uid, rows in state.get("pending_rewards", {}).items():
                keys = [str(row.get("claim_key")) for row in rows if isinstance(row, dict)]
                if len(keys) != len(set(keys)):
                    issues.append(f"{gid}/{uid}: 대기 보상 claim key 중복")
        embed = discord.Embed(title="🛡️ ABADDON v7.6.0 길드 파견 안정화 검수", colour=discord.Colour.green() if not issues else discord.Colour.orange())
        embed.add_field(name="검사 길드", value=str(checked), inline=True)
        embed.add_field(name="발견 항목", value=str(len(issues)), inline=True)
        embed.add_field(name="삭제·수정", value="0건 · 읽기 전용", inline=True)
        embed.add_field(name="결과", value="✅ 이상 없음" if not issues else "\n".join(f"• {x}" for x in issues[:15]), inline=False)
        embed.set_footer(text="폐기·삭제는 관리자 승인 전 수행하지 않습니다.")
        await ctx.send(embed=embed)

    @bot.listen("on_ready")
    async def v760_startup_dispatch_audit() -> None:
        if getattr(bot, "_abaddon_v760_startup_done", False):
            return
        bot._abaddon_v760_startup_done = True
        guilds = world_data.get("guilds", {}) if isinstance(world_data.get("guilds"), dict) else {}
        created = 0
        active_count = 0
        planning_count = 0
        for gid, raw in guilds.items():
            if not isinstance(raw, dict):
                continue
            ensured, _repairs = ensure_guild_state(gid, raw)
            if not isinstance(ensured.get("dispatch"), dict):
                created += 1
            state = ensure_dispatch_state(ensured)
            world_data["guilds"][str(gid)] = ensured
            active_count += 1 if state.get("active") else 0
            planning_count += 1 if state.get("planning") else 0
        if created:
            try:
                save_data()
            except Exception as exc:
                print(f"[ABADDON v{VERSION}] dispatch migration save warning={type(exc).__name__}:{exc}", flush=True)
        print(
            f"[ABADDON v{VERSION}] dispatch startup status=ok guilds={len(guilds)} "
            f"created={created} active={active_count} planning={planning_count} deletions=0",
            flush=True,
        )

    bot._abaddon_v760_registered = True
    print(
        f"[ABADDON v{VERSION}] 길드 파견 등록 완료: "
        f"지역={len(DISPATCH_ROUTES)} 역할={len(ROLE_LABELS)} 명령=11 삭제=0"
    )
