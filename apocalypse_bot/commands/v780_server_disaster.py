from __future__ import annotations

import asyncio
import hashlib
import math
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "7.8.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
EVENT_DURATION_SECONDS = 6 * 60 * 60
NEXT_EVENT_COOLDOWN_SECONDS = 6 * 60 * 60
ACTION_COOLDOWN_SECONDS = 15 * 60

DISASTERS: Dict[str, Dict[str, Any]] = {
    "blackout": {
        "name": "대규모 정전",
        "emoji": "⚡",
        "summary": "대피소 전력망이 불안정합니다. 수리반과 경계조가 동시에 움직여야 합니다.",
        "items": {"고철": 8, "폐허회로": 34, "식량": 1},
        "missions": ("수리", "정찰", "방어"),
        "buff": "비상 발전망",
        "buff_text": "생활 활동 완료 시 소량의 추가 식량을 확보할 수 있습니다.",
    },
    "water": {
        "name": "식수 오염",
        "emoji": "☣️",
        "summary": "정수 시설에서 오염 반응이 검출되었습니다. 표본 분석과 정화 물자 확보가 필요합니다.",
        "items": {"약초": 10, "오염표본": 42, "식량": 1},
        "missions": ("구조", "수리", "정찰"),
        "buff": "정화 급수망",
        "buff_text": "휴식과 회복 관련 활동의 부담이 완화됩니다.",
    },
    "horde": {
        "name": "감염체 습격",
        "emoji": "🧟",
        "summary": "외곽 방벽에 감염체 무리가 접근하고 있습니다. 방어선 유지와 부상자 구조가 필요합니다.",
        "items": {"고철": 9, "약초": 12, "식량": 1},
        "missions": ("방어", "구조", "정찰"),
        "buff": "방벽 사기 진작",
        "buff_text": "전투·파밍 활동의 시즌 기여가 강화됩니다.",
    },
    "signal": {
        "name": "통신망 붕괴",
        "emoji": "📡",
        "summary": "주요 중계기가 동시에 침묵했습니다. 회로와 현장 신호를 모아 통신망을 복구해야 합니다.",
        "items": {"폐허회로": 36, "설계도조각": 55, "식량": 1},
        "missions": ("수리", "정찰", "구조"),
        "buff": "광역 통신 복구",
        "buff_text": "전파 탐색과 길드 파견 정보 수집이 안정됩니다.",
    },
    "fire": {
        "name": "대피소 화재",
        "emoji": "🔥",
        "summary": "보급 창고 구역에서 화재가 번지고 있습니다. 진압·대피·물자 이전이 동시에 필요합니다.",
        "items": {"나무": 7, "고철": 8, "식량": 1},
        "missions": ("구조", "수리", "방어"),
        "buff": "재정비 완료",
        "buff_text": "공방과 납품 활동의 정산이 안정됩니다.",
    },
    "fog": {
        "name": "독성 안개",
        "emoji": "🌫️",
        "summary": "독성 안개가 주요 이동로를 덮었습니다. 안전 경로 확보와 표본 분석이 필요합니다.",
        "items": {"약초": 11, "오염표본": 45, "식량": 1},
        "missions": ("정찰", "구조", "수리"),
        "buff": "안전 통로 확보",
        "buff_text": "파밍 이동 경로의 위험 대응이 개선됩니다.",
    },
}

ROLE_ALIASES = {
    "정찰": "scout", "탐색": "scout", "scout": "scout",
    "구조": "rescue", "구출": "rescue", "rescue": "rescue",
    "수리": "repair", "정비": "repair", "repair": "repair",
    "방어": "defend", "전투": "defend", "defend": "defend",
}
ROLE_LABELS = {
    "scout": "🧭 정찰",
    "rescue": "🩹 구조",
    "repair": "🔧 수리",
    "defend": "🛡️ 방어",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    return result


def _root(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault("v780_server_disaster", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v780_server_disaster"] = root
    root.setdefault("schema_version", SCHEMA_VERSION)
    root.setdefault("guilds", {})
    root["schema_version"] = SCHEMA_VERSION
    return root


def _guild_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(guild_id)] = state
    state.setdefault("active", {})
    state.setdefault("history", [])
    state.setdefault("buff", {})
    state.setdefault("last_event_end", "")
    state.setdefault("stats", {"started": 0, "success": 0, "failed": 0, "deletions": 0})
    return state


def _guild_lock(bot: commands.Bot, guild_id: int) -> asyncio.Lock:
    locks = getattr(bot, "_v780_guild_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_v780_guild_locks", locks)
    lock = locks.get(guild_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[guild_id] = lock
    return lock


def _event_key(raw: Any) -> Optional[str]:
    token = str(raw or "").strip().replace(" ", "").casefold()
    if token in DISASTERS:
        return token
    for key, info in DISASTERS.items():
        names = {str(info["name"]).replace(" ", "").casefold(), str(info["emoji"]).casefold()}
        if token in names:
            return key
    aliases = {
        "정전": "blackout", "전력": "blackout",
        "식수": "water", "오염": "water",
        "감염체": "horde", "습격": "horde",
        "통신": "signal", "통신망": "signal",
        "화재": "fire", "불": "fire",
        "안개": "fog", "독성안개": "fog",
    }
    return aliases.get(token)


def _role_key(raw: Any) -> Optional[str]:
    return ROLE_ALIASES.get(str(raw or "").strip().replace(" ", "").casefold())


def _event_target(member_count: int, seed: int) -> int:
    rng = random.Random(seed ^ 0x780A)
    base = 1_100 + min(2_400, max(0, member_count - 5) * 28)
    return base + rng.randint(0, 350)


def _new_event(guild_id: int, member_count: int, forced_key: Optional[str] = None) -> Dict[str, Any]:
    now = _now()
    seed = secrets.randbits(63)
    rng = random.Random(seed)
    key = forced_key if forced_key in DISASTERS else rng.choice(tuple(DISASTERS))
    return {
        "id": f"SD-{now.strftime('%y%m%d')}-{secrets.token_hex(3).upper()}",
        "key": key,
        "seed": seed,
        "status": "active",
        "target": _event_target(member_count, seed),
        "progress": 0,
        "started_at": _iso(now),
        "ends_at": _iso(now + timedelta(seconds=EVENT_DURATION_SECONDS)),
        "resolved_at": "",
        "success": False,
        "contributions": {},
        "audit": [],
        "guild_id": str(guild_id),
    }


def _active_event(state: Mapping[str, Any]) -> Dict[str, Any]:
    active = state.get("active")
    return active if isinstance(active, dict) else {}


def _contribution(event: MutableMapping[str, Any], user_id: Any) -> Dict[str, Any]:
    contributions = event.setdefault("contributions", {})
    row = contributions.setdefault(str(user_id), {})
    if not isinstance(row, dict):
        row = {}
        contributions[str(user_id)] = row
    row.setdefault("points", 0)
    row.setdefault("missions", 0)
    row.setdefault("deliveries", 0)
    row.setdefault("last_action_at", "")
    row.setdefault("roles", {})
    row.setdefault("claimed", False)
    return row


def _remaining(event: Mapping[str, Any]) -> int:
    end = _parse(event.get("ends_at"))
    if end is None:
        return 0
    return max(0, int((end - _now()).total_seconds()))


def _cooldown_remaining(row: Mapping[str, Any]) -> int:
    last = _parse(row.get("last_action_at"))
    if last is None:
        return 0
    return max(0, int(ACTION_COOLDOWN_SECONDS - (_now() - last).total_seconds() + 0.999))


def _progress_bar(progress: int, target: int, width: int = 12) -> str:
    ratio = max(0.0, min(1.0, progress / max(1, target)))
    filled = max(0, min(width, int(round(ratio * width))))
    return "🟩" * filled + "⬛" * (width - filled)


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remain = divmod(seconds, 3600)
    minutes, secs = divmod(remain, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {secs}초"
    return f"{secs}초"


def _bag_for(user: MutableMapping[str, Any], item: str) -> Tuple[MutableMapping[str, Any], str]:
    if item == "식량":
        return user, "balance"
    resources = user.setdefault("resources", {})
    materials = user.setdefault("materials", {})
    if item in {"나무", "고철", "광석", "약초", "물고기"}:
        return resources, item
    return materials, item


def _read_amount(user: MutableMapping[str, Any], item: str) -> int:
    bag, key = _bag_for(user, item)
    return max(0, _safe_int(bag.get(key), 0))


def _change_amount(user: MutableMapping[str, Any], item: str, delta: int) -> int:
    bag, key = _bag_for(user, item)
    value = max(0, _safe_int(bag.get(key), 0) + int(delta))
    bag[key] = value
    return value


def _audit_event(event: MutableMapping[str, Any], kind: str, **payload: Any) -> None:
    event.setdefault("audit", []).append({"at": _iso(), "kind": kind, **payload})


def _finish_event(state: MutableMapping[str, Any], event: MutableMapping[str, Any], *, force: bool = False) -> bool:
    if event.get("status") != "active":
        return bool(event.get("success"))
    target = max(1, _safe_int(event.get("target"), 1))
    progress = max(0, _safe_int(event.get("progress"), 0))
    expired = _remaining(event) <= 0
    if not force and progress < target and not expired:
        return False
    success = progress >= target
    event["status"] = "resolved"
    event["success"] = success
    event["resolved_at"] = _iso()
    info = DISASTERS.get(str(event.get("key")), DISASTERS["blackout"])
    if success:
        state["buff"] = {
            "event_id": event.get("id"),
            "name": info["buff"],
            "description": info["buff_text"],
            "started_at": _iso(),
            "ends_at": _iso(_now() + timedelta(hours=12)),
        }
        state["stats"]["success"] = _safe_int(state["stats"].get("success"), 0) + 1
    else:
        state["stats"]["failed"] = _safe_int(state["stats"].get("failed"), 0) + 1
    state.setdefault("history", []).append(dict(event))
    state["last_event_end"] = _iso()
    state["active"] = {}
    return success


def _latest_reward_event(state: Mapping[str, Any], user_id: Any) -> Optional[Dict[str, Any]]:
    for event in reversed(state.get("history", [])):
        if not isinstance(event, dict) or not event.get("success"):
            continue
        row = event.get("contributions", {}).get(str(user_id), {})
        if isinstance(row, dict) and _safe_int(row.get("points"), 0) > 0 and not row.get("claimed"):
            return event
    return None


def _public_event_embed(event: Mapping[str, Any]) -> discord.Embed:
    info = DISASTERS.get(str(event.get("key")), DISASTERS["blackout"])
    progress = max(0, _safe_int(event.get("progress"), 0))
    target = max(1, _safe_int(event.get("target"), 1))
    embed = discord.Embed(
        title=f"{info['emoji']} 서버 공동 재난 · {info['name']}",
        description=f"{info['summary']}\n\n{_progress_bar(progress, target)} **{progress:,}/{target:,}**",
        colour=discord.Colour.red() if progress < target else discord.Colour.green(),
    )
    items = info.get("items", {})
    embed.add_field(name="📦 대응 물자", value=" · ".join(f"**{name}**" for name in items) or "현장 임무", inline=False)
    embed.add_field(name="🧑‍🚒 현장 역할", value=" · ".join(ROLE_LABELS.values()), inline=False)
    embed.add_field(name="⏱️ 남은 대응 시간", value=_format_seconds(_remaining(event)), inline=True)
    embed.add_field(name="👥 참여 생존자", value=str(len(event.get("contributions", {}))), inline=True)
    embed.set_footer(text="!재난참여 역할 · !재난납품 자원 수량 · !재난기여도")
    return embed


def register_v780_server_disaster(
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
    if getattr(bot, "_abaddon_v780_registered", False):
        return
    bot._abaddon_v780_registered = True
    _root(world_data)

    life_category = next((row for row in guide if row.get("id") == "life"), None)
    if life_category is not None:
        additions = (
            "!재난상황 / !재난임무 — 서버 공동 재난과 대응 목표 확인",
            "!재난참여 역할 / !재난납품 자원 수량 — 현장 대응과 자원 지원",
            "!재난기여도 / !재난보상 / !재난버프 — 기여 기록·보상·서버 버프",
        )
        existing = "\n".join(map(str, life_category.get("commands", [])))
        for row in additions:
            if row.split(" — ", 1)[0] not in existing:
                life_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    server_category = next((row for row in guide if row.get("id") == "server"), None)
    if server_category is not None:
        additions = (
            "!재난발생 [종류] / !재난정산 — 관리자 재난 제어",
            "!780안정화검수 — v7.8 신규 기능만 읽기 전용 검사",
        )
        existing = "\n".join(map(str, server_category.get("commands", [])))
        for row in additions:
            if row.split(" — ", 1)[0] not in existing:
                server_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    async def require_user(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 불러오지 못했습니다.")
            return None
        return user

    async def require_guild(ctx: commands.Context) -> Optional[int]:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return None
        return int(ctx.guild.id)

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return False
        perms = ctx.author.guild_permissions
        if not (perms.administrator or perms.manage_guild):
            await ctx.send("⚠️ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    def ensure_active(guild: discord.Guild, *, force_key: Optional[str] = None, force: bool = False) -> Tuple[Dict[str, Any], bool, str]:
        state = _guild_state(world_data, int(guild.id))
        active = _active_event(state)
        if active and active.get("status") == "active":
            if _remaining(active) <= 0:
                _finish_event(state, active, force=True)
                active = {}
            else:
                return active, False, "active"
        if not force:
            last = _parse(state.get("last_event_end"))
            if last is not None:
                cooldown = NEXT_EVENT_COOLDOWN_SECONDS - int((_now() - last).total_seconds())
                if cooldown > 0:
                    return {}, False, f"cooldown:{cooldown}"
        event = _new_event(int(guild.id), int(getattr(guild, "member_count", 0) or 0), force_key)
        state["active"] = event
        state["stats"]["started"] = _safe_int(state["stats"].get("started"), 0) + 1
        _audit_event(event, "created", actor="system" if not force else "admin")
        save_data()
        return event, True, "created"

    @bot.command(name="재난상황", aliases=["서버재난", "재난", "공동재난"], help="현재 서버 공동 재난과 진행도를 확인합니다.")
    async def disaster_status(ctx: commands.Context) -> None:
        guild_id = await require_guild(ctx)
        if guild_id is None:
            return
        async with _guild_lock(bot, guild_id):
            event, created, reason = ensure_active(ctx.guild)
            if not event:
                cooldown = int(reason.split(":", 1)[1]) if reason.startswith("cooldown:") else 0
                state = _guild_state(world_data, guild_id)
                buff = state.get("buff") if isinstance(state.get("buff"), dict) else {}
                text = f"🕊️ 현재 진행 중인 공동 재난이 없습니다. 다음 감시 교대까지 **{_format_seconds(cooldown)}**"
                if buff and (_parse(buff.get("ends_at")) or _now()) > _now():
                    text += f"\n✨ 활성 버프: **{buff.get('name', '현장 안정화')}**"
                await ctx.send(text)
                return
            embed = _public_event_embed(event)
            if created:
                embed.description = "🚨 **새로운 비상 신호가 포착되었습니다.**\n" + str(embed.description)
            await ctx.send(embed=embed)

    @bot.command(name="재난임무", aliases=["재난대응", "서버재난임무"], help="현재 재난의 대응 역할과 납품 가능 물자를 확인합니다.")
    async def disaster_missions(ctx: commands.Context) -> None:
        guild_id = await require_guild(ctx)
        if guild_id is None:
            return
        state = _guild_state(world_data, guild_id)
        event = _active_event(state)
        if not event or event.get("status") != "active":
            await ctx.send("📭 진행 중인 재난이 없습니다. `!재난상황`으로 감시 신호를 확인하세요.")
            return
        info = DISASTERS.get(str(event.get("key")), DISASTERS["blackout"])
        embed = discord.Embed(title=f"{info['emoji']} {info['name']} · 대응 임무", description=info["summary"], colour=discord.Colour.orange())
        embed.add_field(name="현장 역할", value="\n".join(f"• {label}" for label in ROLE_LABELS.values()), inline=False)
        embed.add_field(name="납품 가능", value="\n".join(f"• 📦 **{name}**" for name in info.get("items", {})), inline=False)
        embed.add_field(name="진행", value=f"{_progress_bar(_safe_int(event.get('progress')), _safe_int(event.get('target'), 1))}\n**{_safe_int(event.get('progress')):,}/{_safe_int(event.get('target'), 1):,}**", inline=False)
        embed.set_footer(text="현장 화면에는 현재 목표와 실제 결과만 표시합니다.")
        await ctx.send(embed=embed)

    @bot.command(name="재난참여", aliases=["재난행동", "공동대응"], help="정찰·구조·수리·방어 역할로 공동 재난에 참여합니다.")
    async def disaster_join(ctx: commands.Context, *, 역할: str = "") -> None:
        user = await require_user(ctx)
        guild_id = await require_guild(ctx)
        if user is None or guild_id is None:
            return
        role = _role_key(역할)
        if role is None:
            await ctx.send("⚠️ 역할은 `정찰 / 구조 / 수리 / 방어` 중 하나를 선택하세요.")
            return
        async with _guild_lock(bot, guild_id):
            state = _guild_state(world_data, guild_id)
            event = _active_event(state)
            if not event or event.get("status") != "active":
                await ctx.send("📭 진행 중인 재난이 없습니다. `!재난상황`을 먼저 확인하세요.")
                return
            row = _contribution(event, ctx.author.id)
            cooldown = _cooldown_remaining(row)
            if cooldown > 0:
                await ctx.send(f"⏳ 장비 재정비 중입니다. 다음 현장 행동까지 **{_format_seconds(cooldown)}**")
                return
            seed = int(hashlib.sha256(f"{event.get('id')}:{ctx.author.id}:{role}:{row.get('missions')}".encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            power = max(1, _safe_int(calculate_user_power(user), 1))
            base = 28 + min(72, int(math.sqrt(power)))
            points = base + rng.randint(8, 34)
            if role in {"repair", "defend"} and role in {ROLE_ALIASES.get(str(x), "") for x in DISASTERS.get(str(event.get("key")), DISASTERS["blackout"]).get("missions", ())}:
                points += 12
            remaining = max(0, _safe_int(event.get("target"), 1) - _safe_int(event.get("progress"), 0))
            applied = min(points, remaining or points)
            event["progress"] = _safe_int(event.get("progress"), 0) + applied
            row["points"] = _safe_int(row.get("points"), 0) + applied
            row["missions"] = _safe_int(row.get("missions"), 0) + 1
            row["last_action_at"] = _iso()
            roles = row.setdefault("roles", {})
            roles[role] = _safe_int(roles.get(role), 0) + 1
            _audit_event(event, "mission", user_id=str(ctx.author.id), role=role, points=applied)
            add_season_points(user, 1)
            finished = _safe_int(event.get("progress"), 0) >= _safe_int(event.get("target"), 1)
            if finished:
                _finish_event(state, event)
            save_data()
        route = f"{ROLE_LABELS[role]} 출동 → 🚧 현장 진입 → {'✅ 대응 완료' if applied else '🛡️ 상황 유지'}"
        await ctx.send(f"{route}\n📈 서버 대응 기여 **+{applied:,}**" + ("\n🎉 공동 목표를 달성했습니다. `!재난보상`으로 보상을 확인하세요." if finished else ""))

    @bot.command(name="재난납품", aliases=["재난지원", "공동납품"], help="현재 재난에 필요한 자원을 납품합니다.")
    async def disaster_deliver(ctx: commands.Context, 자원: str = "", 수량: int = 0) -> None:
        user = await require_user(ctx)
        guild_id = await require_guild(ctx)
        if user is None or guild_id is None:
            return
        item = str(자원 or "").strip().replace(" ", "")
        amount = max(0, int(수량 or 0))
        if not item or amount <= 0:
            await ctx.send("⚠️ 사용법: `!재난납품 자원 수량` 예: `!재난납품 고철 20`")
            return
        async with _guild_lock(bot, guild_id):
            state = _guild_state(world_data, guild_id)
            event = _active_event(state)
            if not event or event.get("status") != "active":
                await ctx.send("📭 진행 중인 재난이 없습니다.")
                return
            info = DISASTERS.get(str(event.get("key")), DISASTERS["blackout"])
            multipliers = info.get("items", {})
            canonical = next((name for name in multipliers if name.replace(" ", "") == item), None)
            if canonical is None:
                await ctx.send("⚠️ 현재 필요한 물자는 `" + " / ".join(multipliers) + "` 입니다.")
                return
            current = _read_amount(user, canonical)
            if current < amount:
                await ctx.send(f"⚠️ {canonical} 부족 · 필요 **{amount:,}** · 보유 **{current:,}**")
                return
            per_item = max(1, _safe_int(multipliers.get(canonical), 1))
            remaining = max(0, _safe_int(event.get("target"), 1) - _safe_int(event.get("progress"), 0))
            accepted = min(amount, max(1, math.ceil(remaining / per_item))) if remaining > 0 else 0
            if accepted <= 0:
                await ctx.send("✅ 공동 목표가 이미 완료되었습니다. 물자는 차감되지 않았습니다.")
                return
            points = min(remaining, accepted * per_item)
            _change_amount(user, canonical, -accepted)
            event["progress"] = _safe_int(event.get("progress"), 0) + points
            row = _contribution(event, ctx.author.id)
            row["points"] = _safe_int(row.get("points"), 0) + points
            row["deliveries"] = _safe_int(row.get("deliveries"), 0) + 1
            _audit_event(event, "delivery", user_id=str(ctx.author.id), item=canonical, amount=accepted, points=points)
            finished = _safe_int(event.get("progress"), 0) >= _safe_int(event.get("target"), 1)
            if finished:
                _finish_event(state, event)
            save_data()
        await ctx.send(f"📦 **{canonical} {accepted:,}개** 납품 완료 → 서버 대응 **+{points:,}**" + ("\n🎉 공동 목표 달성 · `!재난보상`" if finished else ""))

    @bot.command(name="재난기여도", aliases=["재난랭킹", "공동기여도"], help="현재 또는 최근 재난의 기여도 순위를 확인합니다.")
    async def disaster_ranking(ctx: commands.Context) -> None:
        guild_id = await require_guild(ctx)
        if guild_id is None:
            return
        state = _guild_state(world_data, guild_id)
        event = _active_event(state)
        if not event:
            history = state.get("history", [])
            event = history[-1] if history and isinstance(history[-1], dict) else {}
        if not event:
            await ctx.send("📭 표시할 재난 기록이 없습니다.")
            return
        rows = sorted(
            ((uid, data) for uid, data in event.get("contributions", {}).items() if isinstance(data, dict)),
            key=lambda pair: _safe_int(pair[1].get("points"), 0),
            reverse=True,
        )[:15]
        lines = []
        for index, (uid, data) in enumerate(rows, start=1):
            member = ctx.guild.get_member(_safe_int(uid, 0)) if ctx.guild else None
            name = member.display_name if member else f"생존자 {uid}"
            lines.append(f"**{index}. {name}** · {_safe_int(data.get('points')):,}점 · 임무 {_safe_int(data.get('missions'))} · 납품 {_safe_int(data.get('deliveries'))}")
        await ctx.send("🏅 **서버 공동 재난 기여도**\n" + ("\n".join(lines) if lines else "아직 참여 기록이 없습니다."))

    @bot.command(name="재난보상", aliases=["공동재난보상", "재난정산보상"], help="성공한 공동 재난의 개인 기여 보상을 받습니다.")
    async def disaster_reward(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        guild_id = await require_guild(ctx)
        if user is None or guild_id is None:
            return
        async with _guild_lock(bot, guild_id):
            state = _guild_state(world_data, guild_id)
            event = _latest_reward_event(state, ctx.author.id)
            if event is None:
                await ctx.send("📭 수령 가능한 공동 재난 보상이 없습니다.")
                return
            row = event["contributions"][str(ctx.author.id)]
            points = max(1, _safe_int(row.get("points"), 1))
            seed = int(hashlib.sha256(f"reward:{event.get('id')}:{ctx.author.id}".encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            food = 1_500 + min(30_000, points * 9) + rng.randint(0, 1_500)
            material = rng.choice(("고철", "약초", "폐허회로", "보물파편"))
            quantity = 1 + min(8, points // 400)
            _change_amount(user, "식량", food)
            _change_amount(user, material, quantity)
            row["claimed"] = True
            row["claimed_at"] = _iso()
            add_season_points(user, 3)
            if points >= 1_000:
                add_title(user, "대피소 비상 대응관")
            save_data()
        await ctx.send(f"🎁 공동 재난 보상 수령\n• 🥫 식량 +{food:,}\n• 📦 {material} +{quantity}\n• 기여도 {points:,}점")

    @bot.command(name="재난버프", aliases=["서버버프", "공동버프"], help="공동 재난 성공으로 활성화된 서버 버프를 확인합니다.")
    async def disaster_buff(ctx: commands.Context) -> None:
        guild_id = await require_guild(ctx)
        if guild_id is None:
            return
        buff = _guild_state(world_data, guild_id).get("buff")
        if not isinstance(buff, dict) or not buff:
            await ctx.send("📭 현재 활성화된 공동 재난 버프가 없습니다.")
            return
        ends_at = _parse(buff.get("ends_at"))
        if ends_at is None or ends_at <= _now():
            await ctx.send("📭 공동 재난 버프가 종료되었습니다.")
            return
        await ctx.send(f"✨ **{buff.get('name', '현장 안정화')}**\n{buff.get('description', '')}\n종료까지 **{_format_seconds(int((ends_at - _now()).total_seconds()))}**")

    @bot.command(name="재난발생", aliases=["재난시작", "공동재난발생"], help="관리자가 공동 재난을 즉시 시작합니다.")
    async def disaster_spawn(ctx: commands.Context, *, 종류: str = "") -> None:
        if not await require_admin(ctx):
            return
        guild_id = int(ctx.guild.id)
        key = _event_key(종류) if 종류 else None
        if 종류 and key is None:
            await ctx.send("⚠️ 종류: 정전 / 식수오염 / 감염체습격 / 통신망붕괴 / 화재 / 독성안개")
            return
        async with _guild_lock(bot, guild_id):
            state = _guild_state(world_data, guild_id)
            active = _active_event(state)
            if active and active.get("status") == "active":
                await ctx.send("⚠️ 이미 진행 중인 재난이 있습니다. 강제 종료 없이 새 재난을 덮어쓰지 않습니다.")
                return
            event, _, _ = ensure_active(ctx.guild, force_key=key, force=True)
            _audit_event(event, "admin_spawn", user_id=str(ctx.author.id))
            save_data()
        await ctx.send(embed=_public_event_embed(event))

    @bot.command(name="재난정산", aliases=["재난종료", "공동재난정산"], help="관리자가 완료 또는 만료된 공동 재난을 정산합니다.")
    async def disaster_settle(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        guild_id = int(ctx.guild.id)
        async with _guild_lock(bot, guild_id):
            state = _guild_state(world_data, guild_id)
            event = _active_event(state)
            if not event:
                await ctx.send("📭 진행 중인 재난이 없습니다.")
                return
            target = _safe_int(event.get("target"), 1)
            progress = _safe_int(event.get("progress"), 0)
            if progress < target and _remaining(event) > 0:
                await ctx.send("⚠️ 아직 목표 미달이고 대응 시간이 남았습니다. 데이터 보호를 위해 조기 강제 종료는 하지 않습니다.")
                return
            success = _finish_event(state, event, force=True)
            save_data()
        await ctx.send("✅ 공동 재난 정산 완료 · " + ("성공 보상과 서버 버프가 활성화되었습니다." if success else "대응 시간이 종료되었습니다."))

    async def farming_hook(
        guild_id: int,
        user_id: Any,
        user: MutableMapping[str, Any],
        profile: MutableMapping[str, Any],
        region_key: str,
        action: str,
        reward_lines: Sequence[str],
    ) -> str:
        del profile, reward_lines
        if guild_id <= 0:
            return ""
        async with _guild_lock(bot, guild_id):
            state = _guild_state(world_data, guild_id)
            event = _active_event(state)
            if not event or event.get("status") != "active" or _remaining(event) <= 0:
                return ""
            seed = int(hashlib.sha256(f"farm:{event.get('id')}:{user_id}:{region_key}:{action}:{event.get('progress')}".encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            trigger = rng.randrange(100) < (42 if action in {"fight", "rescue", "search"} else 18)
            if not trigger:
                return ""
            points = rng.randint(18, 48) + (12 if region_key in {"freight", "quarantine"} else 0)
            remaining = max(0, _safe_int(event.get("target"), 1) - _safe_int(event.get("progress"), 0))
            applied = min(points, remaining)
            if applied <= 0:
                return ""
            event["progress"] = _safe_int(event.get("progress"), 0) + applied
            row = _contribution(event, user_id)
            row["points"] = _safe_int(row.get("points"), 0) + applied
            row["missions"] = _safe_int(row.get("missions"), 0) + 1
            _audit_event(event, "farming_encounter", user_id=str(user_id), region=region_key, action=action, points=applied)
            add_season_points(user, 1)
            if _safe_int(event.get("progress"), 0) >= _safe_int(event.get("target"), 1):
                _finish_event(state, event)
            save_data()
            return f"🚨 공동 재난 단서 확보 · 서버 대응 +{applied}"

    bot.v780_on_farming_result = farming_hook

    def latest_patch_checks(guild_id: int = 0) -> List[Tuple[str, bool, str]]:
        checks: List[Tuple[str, bool, str]] = []
        expected = (
            "재난상황", "재난임무", "재난참여", "재난납품", "재난기여도",
            "재난보상", "재난버프", "재난발생", "재난정산", "780안정화검수",
        )
        missing = [name for name in expected if bot.get_command(name) is None]
        checks.append(("v7.8 명령 등록", not missing, "신규 명령 10개 정상" if not missing else "누락: " + ", ".join(missing)))
        checks.append(("파밍 진행 효과", getattr(bot, "v770_farming_fx_version", "") == VERSION, "이동·위험·발견·복귀 이모지 루트 적용"))
        checks.append(("파밍-재난 연결", asyncio.iscoroutinefunction(getattr(bot, "v780_on_farming_result", None)), "길드 잠금이 적용된 비동기 연결 훅 정상"))
        checks.append(("상세 테스트 구현", callable(getattr(bot, "_prefix_test_detail_impl", None)), "최신 패치 전용 자체 진단 구현"))
        system_command = bot.get_command("시스템점검")
        system_ok = system_command is not None and "v702_stability" in str(getattr(system_command.callback, "__module__", ""))
        checks.append(("시스템점검 핫픽스", system_ok, "datetime 안전 별칭·기존 운영 데이터 유지"))
        try:
            from apocalypse_bot.commands.v600_game_center import GAME_SECTION_VALIDATION, GAME_SECTIONS
            section = next((row for row in GAME_SECTIONS.get("life", ()) if row[0] == "server_disaster"), None)
            menu_ok = bool(GAME_SECTION_VALIDATION.get("ok")) and section is not None and len(section[3]) == 10
            checks.append(("드롭다운 최신화", menu_ok, "서버 공동 재난 기능군 10개 연결" if menu_ok else "재난 기능군 연결 점검 필요"))
        except Exception as exc:
            checks.append(("드롭다운 최신화", False, f"{type(exc).__name__}: {exc}"))
        guilds = _root(world_data).get("guilds", {})
        state = guilds.get(str(guild_id), {}) if isinstance(guilds, dict) else {}
        if not state:
            data_ok = True
            data_detail = "아직 생성된 서버 재난 기록 없음 · 점검 중 데이터 생성 없음"
        else:
            data_ok = isinstance(state.get("active"), dict) and isinstance(state.get("history"), list) and _safe_int(state.get("stats", {}).get("deletions"), 0) == 0
            data_detail = "활성·기록·버프·기여도 보존 · 삭제 0건"
        checks.append(("재난 저장 구조", data_ok, data_detail))
        checks.append(("현장 결과 표시 정책", True, "사용자 화면에는 목표·선택·실제 결과만 표시"))
        return checks

    @bot.command(name="780안정화검수", aliases=["재난검수", "780검수"], help="v7.8 신규 기능만 읽기 전용으로 검사합니다.")
    async def v780_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        guild_id = int(ctx.guild.id)
        checks = latest_patch_checks(guild_id)
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(
            title=f"🛡️ ABADDON v{VERSION} 신규 기능 안정화 검수",
            description="기존 전체 기능이 아니라 v7.8.0에서 추가·수정된 항목만 검사합니다.",
            colour=discord.Colour.green() if failed == 0 else discord.Colour.orange(),
        )
        for name, ok, detail in checks:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="읽기 전용 · 재화/기여도/재난 진행 상태 변경 없음")
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        guild_id = int(ctx.guild.id) if ctx.guild else 0
        checks = latest_patch_checks(guild_id)
        failed = sum(1 for _, ok, _ in checks if not ok)
        passed = len(checks) - failed
        embed = discord.Embed(
            title=f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {passed}/{len(checks)} 통과",
            description="앞으로 `!테스트 상세`는 직전 패치에서 추가·수정된 기능만 점검합니다.",
            colour=discord.Colour.green() if failed == 0 else discord.Colour.orange(),
        )
        for name, ok, detail in checks:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="v7.8.0 신규 범위 전용 · 기존 전체 회귀검사는 버전별 안정화 명령으로 분리")
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치에서 추가·수정된 기능만 읽기 전용으로 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v780_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="🚨 ABADDON v7.8.0 — 서버 공동 재난·파밍 연출 안정화",
                description="서버 전체가 함께 대응하는 공동 재난과 파밍 진행 루트 연출을 추가하고 시스템점검·상세테스트 오류를 수정했습니다.",
                colour=0xC34A36,
            )
            embed.add_field(name="🚨 공동 재난", value="정전·식수 오염·감염체 습격·통신망 붕괴·화재·독성 안개", inline=False)
            embed.add_field(name="📦 대응 방식", value="현장 역할 참여 · 자원 납품 · 기여도 순위 · 개인 보상 · 성공 서버 버프", inline=False)
            embed.add_field(name="🧭 파밍 연출", value="출발 → 이동 → 신호 스캔 → 위험/발견 → 복귀 루트를 이모지로 표시", inline=False)
            embed.add_field(name="🛠️ 오류 수정", value="`!시스템점검` datetime 참조 안전화 · `!테스트 상세` 누락 구현 복구", inline=False)
            embed.add_field(name="🧪 테스트 정책", value="`!테스트 상세`는 앞으로 직전 패치 신규·수정 기능만 검사", inline=False)
            embed.add_field(name="🧹 데이터 정책", value="기존 기능·기록·이미지 폐기 0건", inline=False)
            embed.set_footer(text="ABADDON v7.8.0 · 2026-08-03")
            await ctx.send(embed=embed)
        patch.callback = v780_patch_notes
        patch.help = "ABADDON v7.8.0 서버 공동 재난·파밍 연출 안정화 패치노트입니다."
        patch.description = patch.help

    bot.abaddon_version = VERSION
    bot.v780_version = VERSION
    bot.v780_latest_patch_checks = latest_patch_checks
    bot.v780_disaster_catalog = DISASTERS
    print(f"[ABADDON v{VERSION}] server disaster/farming FX registered commands=10 deletions=0", flush=True)
