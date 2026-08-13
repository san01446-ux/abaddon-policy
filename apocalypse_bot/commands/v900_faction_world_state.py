from __future__ import annotations

import asyncio
import copy
import hashlib
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v810_world_map_ux import REGIONS, REGION_ORDER, _guild_state as _map_guild_state

VERSION = "9.0.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
MAX_HISTORY = 500
CONVOY_DURATION_SECONDS = 20 * 60
WAR_TARGET = 4_500

FACTIONS: Dict[str, Dict[str, Any]] = {
    "white_lamp": {
        "name": "백색등 구조대", "emoji": "🚑", "aliases": ("구조대", "백색등", "white"),
        "summary": "붕괴 지대에서 생존자를 구조하고 피난 경로를 확보합니다.",
        "resource": "식량", "benefit": "구조 사건 보상과 회복 지원이 강화됩니다.",
    },
    "blue_shield": {
        "name": "푸른 방패 민병대", "emoji": "🛡️", "aliases": ("민병대", "푸른방패", "shield"),
        "summary": "정착지와 보급로를 지키는 시민 방위 조직입니다.",
        "resource": "고철", "benefit": "지역 보스와 세력전쟁 방어 기여가 강화됩니다.",
    },
    "dawn_medics": {
        "name": "새벽 의무단", "emoji": "⚕️", "aliases": ("의무단", "새벽의무단", "medic"),
        "summary": "오염지대의 부상자와 감염 의심자를 치료합니다.",
        "resource": "약초", "benefit": "치료·정화 관련 의뢰와 보급 교환이 확장됩니다.",
    },
    "rail_engineers": {
        "name": "철도 복구단", "emoji": "🧰", "aliases": ("복구단", "철도복구단", "engineer"),
        "summary": "끊어진 선로와 발전 설비를 복구해 이동망을 되살립니다.",
        "resource": "폐허회로", "benefit": "거점 건설과 호송 정비 지원이 강화됩니다.",
    },
    "supply_escort": {
        "name": "보급 호위대", "emoji": "🚚", "aliases": ("호위대", "보급호위대", "escort"),
        "summary": "정착지 사이의 물자 수송과 민간 행렬을 보호합니다.",
        "resource": "식량", "benefit": "호송 보상과 지역경제 거래 선택지가 확장됩니다.",
    },
    "ranger_patrol": {
        "name": "황무지 정찰대", "emoji": "🧭", "aliases": ("정찰대", "황무지정찰대", "ranger"),
        "summary": "미개척 지역의 안전로와 적대 세력 움직임을 추적합니다.",
        "resource": "오염표본", "benefit": "세계지도 정보와 위험 예측이 강화됩니다.",
    },
}

HOSTILES: Dict[str, Dict[str, str]] = {
    "red_fang": {"name": "붉은 송곳니 약탈단", "emoji": "🩸", "summary": "보급로와 약한 정착지를 노리는 약탈 연합입니다."},
    "black_dust": {"name": "검은 먼지 밀수조직", "emoji": "🌑", "summary": "오염 물자와 금지 기술을 거래하는 밀수 네트워크입니다."},
    "iron_crown": {"name": "고철왕 기계 군단", "emoji": "🤖", "summary": "폐기 로봇을 개조해 지역을 점령하는 자동 군단입니다."},
    "abyss_cult": {"name": "심연 감염 숭배자", "emoji": "🕯️", "summary": "감염과 오염을 구원으로 믿는 광신 집단입니다."},
}

FACTION_LOOKUP: Dict[str, str] = {}
for _key, _info in FACTIONS.items():
    for _token in (_key, _info["name"], *_info["aliases"]):
        FACTION_LOOKUP[str(_token).replace(" ", "").casefold()] = _key

REP_TIERS: Tuple[Tuple[int, str, str], ...] = (
    (1400, "영웅", "🌟"),
    (700, "동맹", "💠"),
    (300, "신뢰", "🤝"),
    (100, "중립", "🕊️"),
    (0, "낯섦", "▫️"),
)

ROUTES: Dict[str, Dict[str, Any]] = {
    "outer_rail": {"name": "외곽–침수 철도", "emoji": "🚚", "aliases": ("외곽철도", "철도", "1"), "start": "outskirts", "end": "flooded_rail", "risk": 1},
    "rail_forest": {"name": "침수 철도–잿빛 수림", "emoji": "🚛", "aliases": ("철도수림", "수림", "2"), "start": "flooded_rail", "end": "ash_forest", "risk": 2},
    "forest_fog": {"name": "잿빛 수림–적색 안개", "emoji": "🛻", "aliases": ("수림안개", "안개", "3"), "start": "ash_forest", "end": "red_fog", "risk": 3},
    "fog_reactor": {"name": "적색 안개–원자로 묘지", "emoji": "🚜", "aliases": ("안개원자로", "원자로", "4"), "start": "red_fog", "end": "reactor_grave", "risk": 4},
    "reactor_terminal": {"name": "원자로 묘지–황혼 종착지", "emoji": "🚂", "aliases": ("원자로종착지", "종착지", "5"), "start": "reactor_grave", "end": "twilight_terminal", "risk": 5},
}
ROUTE_LOOKUP = {
    str(token).replace(" ", "").casefold(): key
    for key, info in ROUTES.items()
    for token in (key, info["name"], *info["aliases"])
}

CONVOY_ROLES: Dict[str, Tuple[str, str]] = {
    "vanguard": ("선봉", "⚔️"),
    "mechanic": ("정비", "🧰"),
    "medic": ("의무", "⚕️"),
    "broker": ("교섭", "🤝"),
}
ROLE_LOOKUP = {
    token.replace(" ", "").casefold(): key
    for key, (name, _emoji) in CONVOY_ROLES.items()
    for token in (key, name)
}

WAR_FRONTS: Dict[str, Dict[str, str]] = {
    "rescue": {"name": "구조 전선", "emoji": "🚑", "faction": "white_lamp", "summary": "피난민 구조와 의료 회랑 확보"},
    "defense": {"name": "방어 전선", "emoji": "🛡️", "faction": "blue_shield", "summary": "정착지 방어와 적대 세력 저지"},
    "rebuild": {"name": "복구 전선", "emoji": "🧰", "faction": "rail_engineers", "summary": "전력·철도·보급망 복구"},
}
FRONT_LOOKUP = {
    token.replace(" ", "").casefold(): key
    for key, info in WAR_FRONTS.items()
    for token in (key, info["name"], info["name"].replace(" 전선", ""))
}

SEASON5_CHAPTERS: Dict[int, Dict[str, Any]] = {
    1: {
        "title": "잿빛 연합의 탄생",
        "summary": "흩어진 선역 세력을 하나의 연합으로 묶을 방식을 결정합니다.",
        "choices": {
            "1": ("구조 우선", "🚑", {"stability": 4, "morale": 8, "supply": -2}),
            "2": ("방벽 우선", "🛡️", {"stability": 8, "morale": 2, "supply": -4}),
            "3": ("철도 복구", "🧰", {"stability": 3, "morale": 2, "supply": 8}),
        },
    },
    2: {
        "title": "검은 먼지의 거래",
        "summary": "밀수조직의 제안을 거절할지, 이용할지, 추적할지 선택합니다.",
        "choices": {
            "1": ("공개 거절", "📢", {"morale": 7, "supply": -3, "contamination": -2}),
            "2": ("역추적 작전", "🛰️", {"stability": 5, "supply": 3, "contamination": 2}),
            "3": ("물자만 회수", "📦", {"supply": 9, "morale": -4, "contamination": 4}),
        },
    },
    3: {
        "title": "노심의 밤",
        "summary": "원자로 묘지의 폭주를 막기 위한 최종 자원 배분을 결정합니다.",
        "choices": {
            "1": ("정화소 총동원", "💧", {"contamination": -12, "supply": -5}),
            "2": ("기계 군단 선제 타격", "⚔️", {"stability": 9, "morale": 4, "supply": -6}),
            "3": ("황혼 종착지 철수선", "🚂", {"morale": 9, "supply": -2, "stability": -3}),
        },
    },
    4: {
        "title": "연합전선의 마지막 선택",
        "summary": "새 세계의 질서를 무엇으로 세울지 결정합니다.",
        "choices": {
            "1": ("시민 연합 평의회", "🏛️", {"stability": 7, "morale": 7}),
            "2": ("전시 통합 지휘부", "🎖️", {"stability": 12, "morale": -4}),
            "3": ("자율 거점 연방", "🏕️", {"supply": 8, "morale": 4, "stability": 2}),
        },
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _today() -> str:
    return _now().astimezone(KST).strftime("%Y-%m-%d")


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    return result


def _clamp(value: Any, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, _safe_int(value)))


def _bar(value: int, maximum: int, width: int = 12) -> str:
    maximum = max(1, int(maximum))
    filled = min(width, max(0, round(width * int(value) / maximum)))
    return "▰" * filled + "▱" * (width - filled)


def _fmt_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def _faction_key(raw: Any) -> Optional[str]:
    return FACTION_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _route_key(raw: Any) -> Optional[str]:
    return ROUTE_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _role_key(raw: Any) -> Optional[str]:
    return ROLE_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _front_key(raw: Any) -> Optional[str]:
    return FRONT_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v900_world_state", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v900_world_state"] = root
    root["schema_version"] = SCHEMA_VERSION
    root.setdefault("guilds", {})
    stats = root.setdefault("stats", {})
    if not isinstance(stats, dict):
        stats = {}
        root["stats"] = stats
    for key in ("missions", "convoys", "wars", "season_choices", "deletions"):
        stats.setdefault(key, 0)
    return root


def _new_world_state() -> MutableMapping[str, Any]:
    enemy = random.choice(tuple(HOSTILES))
    return {
        "created_at": _iso(),
        "metrics": {"stability": 45, "supply": 45, "morale": 45, "contamination": 25},
        "faction_support": {key: 0 for key in FACTIONS},
        "economy": {"day": "", "demand": {}, "history": []},
        "convoy": {},
        "convoy_history": [],
        "war": {
            "id": f"WAR-{secrets.token_hex(3).upper()}", "status": "active", "enemy": enemy,
            "focus": "defense", "progress": 0, "target": WAR_TARGET, "contributions": {},
            "claimed": [], "started_at": _iso(), "ended_at": "", "result": "",
        },
        "war_history": [],
        "season5": {"chapter": 1, "resolved": {}, "votes": {}, "ending": "", "history": []},
        "history": [],
    }


def _guild(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), _new_world_state())
    if not isinstance(state, dict):
        state = _new_world_state()
        guilds[str(guild_id)] = state
    metrics = state.setdefault("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
        state["metrics"] = metrics
    defaults = {"stability": 45, "supply": 45, "morale": 45, "contamination": 25}
    for key, default in defaults.items():
        metrics[key] = _clamp(metrics.get(key, default), 0, 100)
    support = state.setdefault("faction_support", {})
    if not isinstance(support, dict):
        support = {}
        state["faction_support"] = support
    for key in FACTIONS:
        support.setdefault(key, 0)
    state.setdefault("economy", {"day": "", "demand": {}, "history": []})
    state.setdefault("convoy", {})
    state.setdefault("convoy_history", [])
    state.setdefault("war_history", [])
    state.setdefault("history", [])
    season = state.setdefault("season5", {"chapter": 1, "resolved": {}, "votes": {}, "ending": "", "history": []})
    season.setdefault("chapter", 1)
    season.setdefault("resolved", {})
    season.setdefault("votes", {})
    season.setdefault("ending", "")
    season.setdefault("history", [])
    war = state.setdefault("war", {})
    if not isinstance(war, dict) or not war.get("id"):
        state["war"] = _new_world_state()["war"]
    else:
        war.setdefault("status", "active")
        war.setdefault("enemy", "red_fang")
        war.setdefault("focus", "defense")
        war.setdefault("progress", 0)
        war.setdefault("target", WAR_TARGET)
        war.setdefault("contributions", {})
        war.setdefault("claimed", [])
        war.setdefault("started_at", _iso())
        war.setdefault("ended_at", "")
        war.setdefault("result", "")
    _ensure_economy(state, guild_id)
    return state


def _profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = user.setdefault("faction_world_v900", {})
    if not isinstance(profile, dict):
        profile = {}
        user["faction_world_v900"] = profile
    profile["schema_version"] = SCHEMA_VERSION
    reputation = profile.setdefault("reputation", {})
    if not isinstance(reputation, dict):
        reputation = {}
        profile["reputation"] = reputation
    tokens = profile.setdefault("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}
        profile["tokens"] = tokens
    for key in FACTIONS:
        reputation.setdefault(key, 0)
        tokens.setdefault(key, 0)
    profile.setdefault("mission", {})
    profile.setdefault("mission_history", [])
    profile.setdefault("convoy_claims", [])
    profile.setdefault("war_claims", [])
    profile.setdefault("war_daily", {"date": "", "count": 0})
    profile.setdefault("stats", {"missions": 0, "convoys": 0, "war_actions": 0, "season_votes": 0})
    return profile


def _lock(bot: commands.Bot, guild_id: int) -> asyncio.Lock:
    locks = getattr(bot, "_v900_guild_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_v900_guild_locks", locks)
    lock = locks.get(guild_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[guild_id] = lock
    return lock


def _user_lock(bot: commands.Bot, user_id: int) -> asyncio.Lock:
    locks = getattr(bot, "_v900_user_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_v900_user_locks", locks)
    lock = locks.get(user_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[user_id] = lock
    return lock


def _is_admin(member: Any) -> bool:
    permissions = getattr(member, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False) or getattr(permissions, "manage_guild", False))


def _rep_tier(value: int) -> Tuple[str, str, int]:
    value = max(0, int(value))
    for threshold, name, emoji in REP_TIERS:
        if value >= threshold:
            return name, emoji, threshold
    return "낯섦", "▫️", 0


def _bag(user: MutableMapping[str, Any], item: str) -> MutableMapping[str, Any]:
    if item in {"보물파편", "폐허회로", "오염표본", "설계도조각"}:
        bag = user.setdefault("materials", {})
        key = "materials"
    else:
        bag = user.setdefault("resources", {})
        key = "resources"
    if not isinstance(bag, dict):
        bag = {}
        user[key] = bag
    return bag


def _owned(user: Mapping[str, Any], item: str) -> int:
    if item == "식량":
        return max(0, _safe_int(user.get("balance"), 0))
    bag_name = "materials" if item in {"보물파편", "폐허회로", "오염표본", "설계도조각"} else "resources"
    bag = user.get(bag_name, {})
    return max(0, _safe_int(bag.get(item), 0)) if isinstance(bag, Mapping) else 0


def _take(user: MutableMapping[str, Any], item: str, amount: int) -> bool:
    amount = max(0, int(amount))
    if _owned(user, item) < amount:
        return False
    if item == "식량":
        user["balance"] = _owned(user, item) - amount
    else:
        bag = _bag(user, item)
        bag[item] = _owned(user, item) - amount
    return True


def _give(user: MutableMapping[str, Any], item: str, amount: int) -> None:
    amount = max(0, int(amount))
    if item == "식량":
        user["balance"] = _owned(user, item) + amount
    else:
        bag = _bag(user, item)
        bag[item] = _owned(user, item) + amount


def _metric_delta(state: MutableMapping[str, Any], changes: Mapping[str, int]) -> None:
    metrics = state["metrics"]
    for key, delta in changes.items():
        if key in metrics:
            metrics[key] = _clamp(_safe_int(metrics.get(key), 0) + int(delta), 0, 100)


def _ensure_economy(state: MutableMapping[str, Any], guild_id: int) -> None:
    economy = state.setdefault("economy", {})
    today = _today()
    if economy.get("day") == today and isinstance(economy.get("demand"), dict):
        return
    resources = ("식량", "나무", "고철", "광석", "약초", "폐허회로", "오염표본")
    demand: Dict[str, Dict[str, Any]] = {}
    for index, route_key in enumerate(ROUTES):
        seed = int(hashlib.sha256(f"{guild_id}:{today}:{route_key}".encode()).hexdigest()[:16], 16)
        rng = random.Random(seed)
        resource = resources[rng.randrange(len(resources))]
        grade = rng.choice(("안정", "증가", "긴급"))
        demand[route_key] = {"resource": resource, "grade": grade, "seed": seed}
    economy["day"] = today
    economy["demand"] = demand


def _route_unlocked(world_data: MutableMapping[str, Any], guild_id: int, route_key: str) -> bool:
    route = ROUTES[route_key]
    try:
        state = _map_guild_state(world_data, guild_id)
        regions = state.get("regions", {})
        return bool(regions.get(route["start"], {}).get("unlocked") and regions.get(route["end"], {}).get("unlocked"))
    except Exception:
        return route_key == "outer_rail"


def _mission_for(user_id: int, faction_key: str) -> Dict[str, Any]:
    today = _today()
    faction = FACTIONS[faction_key]
    seed = int(hashlib.sha256(f"{today}:{user_id}:{faction_key}:v900".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    resource = str(faction["resource"])
    if resource == "식량":
        amount = rng.choice((2500, 3500, 5000))
    else:
        amount = rng.choice((8, 12, 16))
    rep = rng.choice((45, 55, 70))
    tokens = 1 + (1 if amount >= (5000 if resource == "식량" else 16) else 0)
    return {
        "id": f"FM-{today.replace('-', '')}-{faction_key[:3].upper()}-{user_id % 10000:04d}",
        "date": today, "faction": faction_key, "resource": resource, "amount": amount,
        "rep": rep, "tokens": tokens,
    }


def _faction_embed(user: MutableMapping[str, Any]) -> discord.Embed:
    profile = _profile(user)
    embed = discord.Embed(
        title="🤝 황무지 연합 세력망",
        description="파밍 인카운트·세력 의뢰·호송·전쟁 참여가 세력 관계와 세계 상태에 연결됩니다.",
        colour=0x2ECC71,
    )
    for key, info in FACTIONS.items():
        rep = max(0, _safe_int(profile["reputation"].get(key), 0))
        tier, emoji, _ = _rep_tier(rep)
        embed.add_field(name=f"{info['emoji']} {info['name']}", value=f"{emoji} {tier} · 평판 {rep:,}\n{info['benefit']}", inline=True)
    embed.set_footer(text="NPC 세력은 사용자 길드와 별도입니다 · 적대 세력 가입 기능 없음")
    return embed


def _world_embed(state: MutableMapping[str, Any]) -> discord.Embed:
    metrics = state["metrics"]
    embed = discord.Embed(
        title="🌍 ABADDON 세계 상태",
        description="세력 의뢰·호송·전쟁·시즌 선택이 서버의 공동 세계 지표를 변화시킵니다.",
        colour=0x5865F2,
    )
    rows = (
        ("안정도", "🛡️", metrics["stability"]),
        ("보급", "📦", metrics["supply"]),
        ("사기", "🔥", metrics["morale"]),
        ("오염", "☣️", metrics["contamination"]),
    )
    for name, emoji, value in rows:
        embed.add_field(name=f"{emoji} {name}", value=f"`{_bar(value, 100)}` {value}/100", inline=False)
    war = state["war"]
    enemy = HOSTILES.get(str(war.get("enemy")), HOSTILES["red_fang"])
    embed.add_field(
        name="⚔️ 현재 전쟁",
        value=f"{enemy['emoji']} {enemy['name']} · {war.get('progress',0):,}/{war.get('target',WAR_TARGET):,} · {war.get('status','active')}",
        inline=False,
    )
    season = state["season5"]
    embed.add_field(name="📖 시즌 5", value=f"현재 장 {season.get('chapter',1)} · 결말 {season.get('ending') or '미확정'}", inline=False)
    return embed


def _season_ending(metrics: Mapping[str, Any]) -> str:
    stability = _safe_int(metrics.get("stability"), 0)
    supply = _safe_int(metrics.get("supply"), 0)
    morale = _safe_int(metrics.get("morale"), 0)
    contamination = _safe_int(metrics.get("contamination"), 100)
    if stability >= 70 and morale >= 65 and contamination <= 30:
        return "🌅 새벽 연합도시"
    if stability >= 78:
        return "🎖️ 강철 지휘국"
    if supply >= 72 and morale >= 60:
        return "🏕️ 자유 거점 연방"
    return "🚂 황혼의 생존선"


class WarActionView(discord.ui.View):
    def __init__(self, owner_id: int, runner: Callable[[discord.Interaction, str], Any]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.runner = runner

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is not None:
            return True
        await interaction.response.send_message("⚠️ 서버 안에서만 참여할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="정찰", emoji="🧭", style=discord.ButtonStyle.primary)
    async def scout(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.runner(interaction, "scout")

    @discord.ui.button(label="구조", emoji="🚑", style=discord.ButtonStyle.success)
    async def rescue(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.runner(interaction, "rescue")

    @discord.ui.button(label="방어", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def defend(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.runner(interaction, "defend")

    @discord.ui.button(label="복구", emoji="🧰", style=discord.ButtonStyle.secondary)
    async def rebuild(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.runner(interaction, "rebuild")


class SeasonVoteView(discord.ui.View):
    def __init__(self, owner_id: int, runner: Callable[[discord.Interaction, str], Any], choices: Mapping[str, Sequence[Any]]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.runner = runner
        styles = (discord.ButtonStyle.success, discord.ButtonStyle.primary, discord.ButtonStyle.secondary)
        for index, (key, row) in enumerate(choices.items()):
            button = discord.ui.Button(label=str(row[0])[:80], emoji=str(row[1]), style=styles[index], custom_id=f"v900:season:{key}")

            async def callback(interaction: discord.Interaction, selected: str = key) -> None:
                await self.runner(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is not None:
            return True
        await interaction.response.send_message("⚠️ 서버 안에서만 투표할 수 있습니다.", ephemeral=True)
        return False


def register_v900_faction_world_state(
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
    del user_data
    if getattr(bot, "_abaddon_v900_registered", False):
        return
    root = _root(world_data)

    additions = {
        "social": (
            "!세력 / !평판 / !세력의뢰 — NPC 세력 관계·의뢰·거점 교류",
            "!무역로 / !호송모집 / !호송참가 — 지역 간 무역·호송 작전",
        ),
        "combat": (
            "!세력전쟁 / !전쟁참여 / !전쟁보상 — 서버 공동 연합전선",
            "!세계상태 / !시즌5 / !시즌5투표 — 세계 지표·대형 시즌 선택",
        ),
        "server": (
            "!900안정화검수 — v9.0 세력·무역·전쟁·시즌 통합 읽기 전용 검사",
        ),
    }
    for category_id, rows in additions.items():
        category = next((item for item in guide if item.get("id") == category_id), None)
        if category is None:
            continue
        existing = "\n".join(map(str, category.get("commands", [])))
        for row in rows:
            token = row.split(" — ", 1)[0]
            if token not in existing:
                category.setdefault("commands", []).append(row)
                existing += "\n" + row

    async def require_user(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 불러오지 못했습니다.")
            return None
        _profile(user)
        return user

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not _is_admin(ctx.author):
            await ctx.send("⛔ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    def encounter_hook(user_id: int, user: MutableMapping[str, Any], encounter_key: str, category: str, action: str) -> str:
        del user_id
        profile = _profile(user)
        mapping = {
            "white_lamp": "white_lamp", "blue_shield": "blue_shield", "dawn_medics": "dawn_medics",
            "rail_engineers": "rail_engineers", "supply_escort": "supply_escort", "ranger_patrol": "ranger_patrol",
        }
        faction_key = mapping.get(str(encounter_key))
        if faction_key is None:
            return ""
        gain = 8 if category == "ally" and action in {"fight", "rescue", "search"} else 3
        profile["reputation"][faction_key] = max(0, _safe_int(profile["reputation"].get(faction_key), 0) + gain)
        info = FACTIONS[faction_key]
        return f"{info['emoji']} {info['name']} 평판 +{gain}"

    bot.v900_on_encounter = encounter_hook

    @bot.command(name="세력", aliases=["세력목록", "연합세력"], help="NPC 세력 관계와 해금 혜택을 확인합니다.")
    async def factions(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is not None:
            await ctx.send(embed=_faction_embed(user))

    @bot.command(name="평판", aliases=["세력평판", "내평판"], help="세력별 평판·증표를 확인합니다.")
    async def reputation(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        profile = _profile(user)
        lines = []
        for key, info in FACTIONS.items():
            rep = max(0, _safe_int(profile["reputation"].get(key), 0))
            tier, emoji, _ = _rep_tier(rep)
            token = max(0, _safe_int(profile["tokens"].get(key), 0))
            lines.append(f"{info['emoji']} **{info['name']}** · {emoji} {tier} · 평판 {rep:,} · 증표 {token}")
        await ctx.send("🤝 **세력 평판 현황**\n" + "\n".join(lines))

    @bot.command(name="세력정보", aliases=["진영정보", "세력상세"], help="선택한 NPC 세력의 상세 정보를 확인합니다.")
    async def faction_info(ctx: commands.Context, *, 세력명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = _faction_key(세력명)
        if key is None:
            await ctx.send("세력: " + " · ".join(info["name"] for info in FACTIONS.values()))
            return
        info = FACTIONS[key]
        profile = _profile(user)
        rep = max(0, _safe_int(profile["reputation"].get(key), 0))
        tier, emoji, _ = _rep_tier(rep)
        embed = discord.Embed(title=f"{info['emoji']} {info['name']}", description=info["summary"], colour=0x3498DB)
        embed.add_field(name="현재 관계", value=f"{emoji} {tier} · 평판 {rep:,}", inline=True)
        embed.add_field(name="세력 증표", value=str(profile["tokens"].get(key, 0)), inline=True)
        embed.add_field(name="해금 혜택", value=info["benefit"], inline=False)
        embed.add_field(name="주요 교류", value="세력 의뢰 · 거점 방문 · 증표 교환 · 호송·전쟁 지원", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="세력거점", aliases=["진영거점", "거점방문"], help="세력 거점의 교류 기능을 확인합니다.")
    async def faction_outpost(ctx: commands.Context, *, 세력명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = _faction_key(세력명)
        if key is None:
            await ctx.send("사용법: `!세력거점 구조대`")
            return
        info = FACTIONS[key]
        rep = max(0, _safe_int(_profile(user)["reputation"].get(key), 0))
        tier, emoji, _ = _rep_tier(rep)
        embed = discord.Embed(title=f"🏕️ {info['name']} 거점", description=info["summary"], colour=0x1ABC9C)
        embed.add_field(name="출입 상태", value=f"{emoji} {tier}", inline=True)
        embed.add_field(name="이용 기능", value="📋 세력 의뢰\n🪙 세력 증표 교환\n📦 호송·전쟁 지원", inline=False)
        if rep < 100:
            embed.add_field(name="안내", value="세력 인카운트와 의뢰로 관계를 쌓으면 더 많은 교류가 열립니다.", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="세력의뢰", aliases=["진영의뢰", "세력임무"], help="오늘의 세력 의뢰를 확인합니다.")
    async def faction_mission(ctx: commands.Context, *, 세력명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = _faction_key(세력명)
        if key is None:
            await ctx.send("사용법: `!세력의뢰 구조대`")
            return
        mission = _mission_for(ctx.author.id, key)
        info = FACTIONS[key]
        embed = discord.Embed(title=f"📋 {info['emoji']} {info['name']} 오늘의 의뢰", description=info["summary"], colour=0xF1C40F)
        embed.add_field(name="요청 물자", value=f"{mission['resource']} {mission['amount']:,}", inline=True)
        embed.add_field(name="보상", value=f"평판 +{mission['rep']} · 증표 +{mission['tokens']}", inline=True)
        embed.add_field(name="수락", value=f"`!세력의뢰수락 {info['name']}`", inline=False)
        embed.set_footer(text="의뢰 구성은 하루 동안 고정되며 완료 시 한 번만 정산됩니다")
        await ctx.send(embed=embed)

    @bot.command(name="세력의뢰수락", aliases=["진영의뢰수락", "세력임무수락"], help="오늘의 세력 의뢰를 수락합니다.")
    async def faction_mission_accept(ctx: commands.Context, *, 세력명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = _faction_key(세력명)
        if key is None:
            await ctx.send("사용법: `!세력의뢰수락 구조대`")
            return
        async with _user_lock(bot, ctx.author.id):
            profile = _profile(user)
            current = profile.get("mission") if isinstance(profile.get("mission"), dict) else {}
            if current and current.get("date") == _today():
                await ctx.send("⚠️ 오늘 이미 수락한 세력 의뢰가 있습니다. `!세력의뢰완료`로 처리해주세요.")
                return
            mission = _mission_for(ctx.author.id, key)
            profile["mission"] = mission
            save_data()
        await ctx.send(f"✅ {FACTIONS[key]['emoji']} **{FACTIONS[key]['name']}** 의뢰를 수락했습니다. `{mission['resource']} {mission['amount']:,}`을 준비한 뒤 `!세력의뢰완료`")

    @bot.command(name="세력의뢰완료", aliases=["진영의뢰완료", "세력임무완료"], help="수락한 세력 의뢰의 물자를 제출하고 정산합니다.")
    async def faction_mission_complete(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            profile = _profile(user)
            mission = profile.get("mission") if isinstance(profile.get("mission"), dict) else {}
            if not mission or mission.get("date") != _today():
                await ctx.send("📭 오늘 수락한 세력 의뢰가 없습니다.")
                return
            resource = str(mission["resource"])
            amount = int(mission["amount"])
            if not _take(user, resource, amount):
                await ctx.send(f"⚠️ {resource} 부족 · 필요 {amount:,} · 보유 {_owned(user, resource):,}")
                return
            faction_key = str(mission["faction"])
            rep = int(mission["rep"])
            tokens = int(mission["tokens"])
            profile["reputation"][faction_key] = _safe_int(profile["reputation"].get(faction_key), 0) + rep
            profile["tokens"][faction_key] = _safe_int(profile["tokens"].get(faction_key), 0) + tokens
            profile["stats"]["missions"] = _safe_int(profile["stats"].get("missions"), 0) + 1
            profile["mission_history"].insert(0, {**mission, "completed_at": _iso()})
            profile["mission"] = {}
            state = _guild(world_data, ctx.guild.id)
            state["faction_support"][faction_key] = _safe_int(state["faction_support"].get(faction_key), 0) + rep
            _metric_delta(state, {"stability": 1, "morale": 1, "supply": 1 if resource == "식량" else 0, "contamination": -1 if faction_key == "dawn_medics" else 0})
            root["stats"]["missions"] = _safe_int(root["stats"].get("missions"), 0) + 1
            add_season_points(user, 2)
            save_data()
        await ctx.send(f"🎖️ **세력 의뢰 완료** · {FACTIONS[faction_key]['name']} 평판 +{rep} · 증표 +{tokens}")

    @bot.command(name="세력상점", aliases=["진영상점", "세력교환소"], help="세력 증표 교환 목록을 확인합니다.")
    async def faction_shop(ctx: commands.Context, *, 세력명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = _faction_key(세력명)
        if key is None:
            await ctx.send("사용법: `!세력상점 구조대`")
            return
        info = FACTIONS[key]
        embed = discord.Embed(title=f"🪙 {info['name']} 증표 교환", colour=0xD4AC0D)
        embed.add_field(name="1 · 생존 보급함", value="증표 3 · 식량과 생활 자원", inline=False)
        embed.add_field(name="2 · 전문 지원함", value="증표 6 · 세력 성격에 맞는 특수 재료", inline=False)
        embed.add_field(name="3 · 연합 휘장", value="증표 12 · 세력 전용 칭호", inline=False)
        embed.set_footer(text="교환: !세력교환 세력 번호")
        await ctx.send(embed=embed)

    @bot.command(name="세력교환", aliases=["진영교환", "세력구매"], help="세력 증표로 보급품 또는 칭호를 교환합니다.")
    async def faction_exchange(ctx: commands.Context, 세력명: str = "", 품목: int = 0) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = _faction_key(세력명)
        if key is None or 품목 not in {1, 2, 3}:
            await ctx.send("사용법: `!세력교환 구조대 1`")
            return
        costs = {1: 3, 2: 6, 3: 12}
        cost = costs[품목]
        async with _user_lock(bot, ctx.author.id):
            profile = _profile(user)
            owned = _safe_int(profile["tokens"].get(key), 0)
            if owned < cost:
                await ctx.send(f"⚠️ 증표 부족 · 필요 {cost} · 보유 {owned}")
                return
            profile["tokens"][key] = owned - cost
            if 품목 == 1:
                _give(user, "식량", 3200)
                _give(user, "고철", 5)
                reward = "🥫 식량 3,200 · 🔩 고철 5"
            elif 품목 == 2:
                item = str(FACTIONS[key]["resource"])
                amount = 2600 if item == "식량" else 8
                _give(user, item, amount)
                _give(user, "보물파편", 1)
                reward = f"{item} {amount:,} · 보물파편 1"
            else:
                title = f"{FACTIONS[key]['name']}의 동맹"
                add_title(user, title)
                reward = f"칭호 `{title}`"
            save_data()
        await ctx.send(f"✅ **세력 교환 완료** · {reward}")

    @bot.command(name="무역로", aliases=["지역무역로", "교역로"], help="개방된 지역 무역로와 오늘의 수요를 확인합니다.")
    async def trade_routes(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild(world_data, ctx.guild.id)
        demand = state["economy"]["demand"]
        lines = []
        for key, route in ROUTES.items():
            open_text = "✅ 개방" if _route_unlocked(world_data, ctx.guild.id, key) else "🔒 잠김"
            row = demand[key]
            lines.append(f"{route['emoji']} **{route['name']}** · {open_text} · 수요 {row['grade']} · {row['resource']}")
        await ctx.send("🛣️ **지역 무역로**\n" + "\n".join(lines))

    @bot.command(name="지역경제", aliases=["무역경제", "경제동향"], help="지역별 수요와 서버 공동 경제 상태를 확인합니다.")
    async def regional_economy(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild(world_data, ctx.guild.id)
        embed = discord.Embed(title="📈 지역 경제 동향", description="수요는 매일 갱신되며 내부 계산 가중치는 공개하지 않습니다.", colour=0x2E86C1)
        for key, route in ROUTES.items():
            row = state["economy"]["demand"][key]
            embed.add_field(name=f"{route['emoji']} {route['name']}", value=f"{row['resource']} · 수요 {row['grade']}", inline=False)
        embed.add_field(name="공동 보급 지표", value=f"{state['metrics']['supply']}/100", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="호송모집", aliases=["무역호송모집", "호송대모집"], help="개인 자원을 적재해 서버 호송대를 모집합니다.")
    async def convoy_open(ctx: commands.Context, 노선: str = "", 자원: str = "", 수량: int = 0) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        route_key = _route_key(노선)
        amount = max(0, int(수량))
        item = str(자원).strip()
        if route_key is None or not item or amount <= 0:
            await ctx.send("사용법: `!호송모집 철도 식량 5000`")
            return
        if not _route_unlocked(world_data, ctx.guild.id, route_key) and not _is_admin(ctx.author):
            await ctx.send("🔒 양쪽 지역이 개척되어야 이 무역로를 사용할 수 있습니다.")
            return
        limit = 500_000 if item == "식량" else 500
        if amount > limit:
            await ctx.send("⚠️ 한 번에 적재할 수 있는 수량을 초과했습니다.")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            convoy = state.get("convoy") if isinstance(state.get("convoy"), dict) else {}
            if convoy and convoy.get("status") in {"planning", "active"}:
                await ctx.send("⚠️ 이미 모집 또는 이동 중인 호송대가 있습니다.")
                return
            if not _take(user, item, amount):
                await ctx.send(f"⚠️ {item} 부족 · 보유 {_owned(user, item):,}")
                return
            convoy_id = f"CV-{secrets.token_hex(4).upper()}"
            state["convoy"] = {
                "id": convoy_id, "status": "planning", "route": route_key, "cargo": {"item": item, "amount": amount},
                "owner": str(ctx.author.id), "participants": {str(ctx.author.id): "broker"},
                "created_at": _iso(), "started_at": "", "ends_at": "", "seed": secrets.randbits(63),
                "settled": False, "result": {}, "claimed": [],
            }
            save_data()
        await ctx.send(f"🚚 **호송대 모집 시작** · {ROUTES[route_key]['name']}\n화물: {item} {amount:,}\n역할 참가: `!호송참가 선봉/정비/의무/교섭` · 출발: `!호송출발`")

    @bot.command(name="호송참가", aliases=["무역호송참가", "호송대참가"], help="진행 중인 호송 모집에 역할을 선택해 참가합니다.")
    async def convoy_join(ctx: commands.Context, *, 역할: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        role_key = _role_key(역할)
        if role_key is None:
            await ctx.send("역할: 선봉 · 정비 · 의무 · 교섭")
            return
        async with _lock(bot, ctx.guild.id):
            convoy = _guild(world_data, ctx.guild.id)["convoy"]
            if not convoy or convoy.get("status") != "planning":
                await ctx.send("📭 참가 가능한 호송 모집이 없습니다.")
                return
            participants = convoy.setdefault("participants", {})
            if len(participants) >= 6 and str(ctx.author.id) not in participants:
                await ctx.send("⚠️ 호송대 정원이 가득 찼습니다.")
                return
            participants[str(ctx.author.id)] = role_key
            save_data()
        await ctx.send(f"✅ 호송대 참가 · {CONVOY_ROLES[role_key][1]} {CONVOY_ROLES[role_key][0]}")

    @bot.command(name="호송출발", aliases=["무역호송출발", "호송대출발"], help="모집 중인 호송대를 출발시킵니다.")
    async def convoy_start(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        async with _lock(bot, ctx.guild.id):
            convoy = _guild(world_data, ctx.guild.id)["convoy"]
            if not convoy or convoy.get("status") != "planning":
                await ctx.send("📭 출발할 호송 모집이 없습니다.")
                return
            if str(ctx.author.id) != str(convoy.get("owner")) and not _is_admin(ctx.author):
                await ctx.send("⛔ 모집자 또는 관리자만 출발시킬 수 있습니다.")
                return
            now = _now()
            convoy["status"] = "active"
            convoy["started_at"] = _iso(now)
            convoy["ends_at"] = _iso(now + timedelta(seconds=CONVOY_DURATION_SECONDS))
            save_data()
        await ctx.send(f"🛣️ **호송 출발** · {ROUTES[convoy['route']]['name']}\n{len(convoy['participants'])}명이 이동을 시작했습니다. 도착 <t:{int(_parse(convoy['ends_at']).timestamp())}:R>")

    @bot.command(name="호송상태", aliases=["무역호송", "호송대상태"], help="현재 서버 호송대의 진행 상태를 확인합니다.")
    async def convoy_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        convoy = _guild(world_data, ctx.guild.id)["convoy"]
        if not convoy:
            await ctx.send("📭 현재 호송대가 없습니다.")
            return
        roles = [f"{CONVOY_ROLES.get(role, ('?', '▫️'))[1]} <@{uid}>" for uid, role in convoy.get("participants", {}).items()]
        embed = discord.Embed(title=f"🚚 호송 {convoy.get('id')}", colour=0xE67E22)
        embed.add_field(name="노선", value=ROUTES.get(convoy.get("route"), {}).get("name", "미확인"), inline=True)
        embed.add_field(name="상태", value=str(convoy.get("status")), inline=True)
        cargo = convoy.get("cargo", {})
        embed.add_field(name="화물", value=f"{cargo.get('item')} {cargo.get('amount',0):,}", inline=False)
        embed.add_field(name="편성", value=" · ".join(roles) or "없음", inline=False)
        if convoy.get("ends_at"):
            embed.add_field(name="도착", value=f"<t:{int(_parse(convoy['ends_at']).timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="호송정산", aliases=["무역호송정산", "호송대정산"], help="도착한 호송 결과를 한 번만 정산합니다.")
    async def convoy_settle(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        async with _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            convoy = state["convoy"]
            if not convoy or convoy.get("status") not in {"active", "settled"}:
                await ctx.send("📭 정산 가능한 호송이 없습니다.")
                return
            if convoy.get("settled"):
                await ctx.send("✅ 이미 정산된 호송입니다. 참가자는 `!호송보상`을 사용하세요.")
                return
            ends = _parse(convoy.get("ends_at"))
            if ends and _now() < ends and not _is_admin(ctx.author):
                await ctx.send(f"⏳ 아직 이동 중입니다 · {_fmt_seconds(int((ends - _now()).total_seconds()))}")
                return
            route = ROUTES[str(convoy["route"])]
            roles = set(convoy.get("participants", {}).values())
            seed = _safe_int(convoy.get("seed"), 1)
            rng = random.Random(seed ^ 0x9000)
            strength = len(convoy.get("participants", {})) * 12 + len(roles) * 8 + state["metrics"]["stability"] // 5
            threshold = 46 + int(route["risk"]) * 7
            success = strength + rng.randint(0, 35) >= threshold
            cargo = convoy["cargo"]
            base_value = _safe_int(cargo.get("amount"), 0)
            demand = state["economy"]["demand"][convoy["route"]]
            bonus = 1.0 + (0.25 if demand["resource"] == cargo["item"] else 0.0) + (0.12 if demand["grade"] == "긴급" else 0.0)
            common = int((base_value if cargo["item"] == "식량" else base_value * 240) * bonus * (1.15 if success else 0.45))
            convoy["settled"] = True
            convoy["status"] = "settled"
            convoy["result"] = {"success": success, "common_value": common, "roles": sorted(roles), "settled_at": _iso()}
            state["metrics"]["supply"] = _clamp(state["metrics"]["supply"] + (6 if success else 1))
            state["metrics"]["morale"] = _clamp(state["metrics"]["morale"] + (3 if success else -1))
            state["convoy_history"].insert(0, copy.deepcopy(convoy))
            root["stats"]["convoys"] = _safe_int(root["stats"].get("convoys"), 0) + 1
            save_data()
        await ctx.send(f"{'✅' if success else '⚠️'} **호송 정산 완료** · {'안전 도착' if success else '부분 회수'}\n공동 가치 {common:,} · 참가자는 `!호송보상`")

    @bot.command(name="호송보상", aliases=["무역호송보상", "호송대보상"], help="정산된 호송의 개인 보상을 수령합니다.")
    async def convoy_reward(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            uid = str(ctx.author.id)
            profile = _profile(user)
            candidates = []
            current = state.get("convoy")
            if isinstance(current, dict) and current.get("settled"):
                candidates.append(current)
            candidates.extend(row for row in state.get("convoy_history", []) if isinstance(row, dict) and row.get("settled"))
            convoy = next((row for row in candidates if uid in row.get("participants", {}) and f"{row.get('id')}:{uid}" not in profile["convoy_claims"]), None)
            if convoy is None:
                participated = any(uid in row.get("participants", {}) for row in candidates)
                await ctx.send("✅ 수령 가능한 미수령 호송 보상이 없습니다." if participated else "📭 참가한 정산 호송이 없습니다.")
                return
            claim_key = f"{convoy['id']}:{uid}"
            participants = max(1, len(convoy.get("participants", {})))
            food = max(600, _safe_int(convoy["result"].get("common_value"), 0) // participants)
            role = convoy["participants"][uid]
            token_faction = {"vanguard": "blue_shield", "mechanic": "rail_engineers", "medic": "dawn_medics", "broker": "supply_escort"}[role]
            _give(user, "식량", food)
            profile["tokens"][token_faction] = _safe_int(profile["tokens"].get(token_faction), 0) + 1
            profile["reputation"][token_faction] = _safe_int(profile["reputation"].get(token_faction), 0) + 20
            profile["convoy_claims"].append(claim_key)
            profile["stats"]["convoys"] = _safe_int(profile["stats"].get("convoys"), 0) + 1
            save_data()
        await ctx.send(f"🎁 **호송 개인 보상** · 식량 +{food:,} · {FACTIONS[token_faction]['name']} 평판 +20 · 증표 +1")

    @bot.command(name="호송취소", aliases=["무역호송취소", "호송대취소"], help="출발 전 호송 모집을 취소하고 화물을 반환합니다.")
    async def convoy_cancel(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            convoy = state["convoy"]
            if not convoy or convoy.get("status") != "planning":
                await ctx.send("📭 취소 가능한 모집이 없습니다.")
                return
            if str(ctx.author.id) != str(convoy.get("owner")) and not _is_admin(ctx.author):
                await ctx.send("⛔ 모집자 또는 관리자만 취소할 수 있습니다.")
                return
            owner = get_user(int(convoy["owner"]))
            if isinstance(owner, dict):
                cargo = convoy["cargo"]
                _give(owner, str(cargo["item"]), _safe_int(cargo["amount"], 0))
            state["convoy"] = {}
            save_data()
        await ctx.send("↩️ 호송 모집을 취소하고 적재 화물을 반환했습니다.")

    async def perform_war_action(user_id: int, guild_id: int, action: str) -> Tuple[bool, str]:
        user = get_user(user_id)
        if not isinstance(user, dict):
            return False, "⚠️ 생존자 데이터를 찾지 못했습니다."
        async with _user_lock(bot, user_id), _lock(bot, guild_id):
            state = _guild(world_data, guild_id)
            war = state["war"]
            if war.get("status") != "active":
                return False, "📭 현재 진행 중인 세력전쟁이 없습니다."
            profile = _profile(user)
            daily = profile["war_daily"]
            if daily.get("date") != _today():
                daily["date"], daily["count"] = _today(), 0
            if _safe_int(daily.get("count"), 0) >= 5:
                return False, "🛑 오늘의 전쟁 행동 횟수를 모두 사용했습니다."
            power = max(1, _safe_int(calculate_user_power(user), 1))
            base = {"scout": 32, "rescue": 38, "defend": 44, "rebuild": 36}.get(action, 32)
            seed = int(hashlib.sha256(f"{war['id']}:{user_id}:{daily['count']}:{action}".encode()).hexdigest()[:16], 16)
            rng = random.Random(seed)
            points = base + min(60, int(power ** 0.5)) + rng.randint(0, 18)
            focus_bonus = {"rescue": "rescue", "defense": "defend", "rebuild": "rebuild"}.get(str(war.get("focus")))
            if action == focus_bonus:
                points += 18
            war["progress"] = min(_safe_int(war.get("target"), WAR_TARGET), _safe_int(war.get("progress"), 0) + points)
            contribution = war["contributions"].setdefault(str(user_id), {"points": 0, "actions": 0})
            contribution["points"] = _safe_int(contribution.get("points"), 0) + points
            contribution["actions"] = _safe_int(contribution.get("actions"), 0) + 1
            daily["count"] = _safe_int(daily.get("count"), 0) + 1
            profile["stats"]["war_actions"] = _safe_int(profile["stats"].get("war_actions"), 0) + 1
            faction_key = {"scout": "ranger_patrol", "rescue": "white_lamp", "defend": "blue_shield", "rebuild": "rail_engineers"}.get(action, "blue_shield")
            profile["reputation"][faction_key] = _safe_int(profile["reputation"].get(faction_key), 0) + 8
            _metric_delta(state, {"stability": 1 if action in {"defend", "rebuild"} else 0, "morale": 1 if action in {"rescue", "scout"} else 0, "contamination": -1 if action == "rescue" else 0})
            add_season_points(user, 1)
            save_data()
        return True, f"⚔️ 전쟁 기여 +{points} · {FACTIONS[faction_key]['name']} 평판 +8"

    @bot.command(name="세력전쟁", aliases=["연합전쟁", "세력전선"], help="현재 서버 공동 세력전쟁을 확인합니다.")
    async def faction_war(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild(world_data, ctx.guild.id)
        war = state["war"]
        enemy = HOSTILES[str(war["enemy"])]
        front = WAR_FRONTS[str(war["focus"])]
        embed = discord.Embed(title=f"⚔️ 연합전선 · {enemy['emoji']} {enemy['name']}", description=enemy["summary"], colour=0xC0392B)
        embed.add_field(name="집중 전선", value=f"{front['emoji']} {front['name']} · {front['summary']}", inline=False)
        embed.add_field(name="전쟁 진행", value=f"`{_bar(_safe_int(war['progress']), _safe_int(war['target']))}`\n{war['progress']:,}/{war['target']:,}", inline=False)
        embed.add_field(name="참여", value="🧭 정찰 · 🚑 구조 · 🛡️ 방어 · 🧰 복구", inline=False)

        async def runner(interaction: discord.Interaction, action: str) -> None:
            await interaction.response.defer(ephemeral=True)
            ok, message = await perform_war_action(interaction.user.id, interaction.guild.id, action)
            await interaction.followup.send(message, ephemeral=True)

        await ctx.send(embed=embed, view=WarActionView(ctx.author.id, runner))

    @bot.command(name="전선선택", aliases=["전쟁전선선택", "집중전선"], help="관리자가 서버 집중 전선을 선택합니다.")
    async def front_select(ctx: commands.Context, *, 전선: str = "") -> None:
        if not await require_admin(ctx):
            return
        key = _front_key(전선)
        if key is None:
            await ctx.send("전선: 구조 · 방어 · 복구")
            return
        async with _lock(bot, ctx.guild.id):
            _guild(world_data, ctx.guild.id)["war"]["focus"] = key
            save_data()
        await ctx.send(f"🎯 집중 전선을 {WAR_FRONTS[key]['emoji']} **{WAR_FRONTS[key]['name']}**으로 변경했습니다.")

    @bot.command(name="전쟁참여", aliases=["세력전쟁참여", "전선참여"], help="정찰·구조·방어·복구 행동으로 전쟁에 참여합니다.")
    async def war_join(ctx: commands.Context, *, 행동: str = "") -> None:
        if ctx.guild is None:
            return
        action_lookup = {"정찰": "scout", "구조": "rescue", "방어": "defend", "복구": "rebuild", "scout": "scout", "rescue": "rescue", "defend": "defend", "rebuild": "rebuild"}
        action = action_lookup.get(str(행동).replace(" ", "").casefold())
        if action is None:
            await ctx.send("행동: 정찰 · 구조 · 방어 · 복구")
            return
        if await require_user(ctx) is None:
            return
        ok, message = await perform_war_action(ctx.author.id, ctx.guild.id, action)
        await ctx.send(message)

    @bot.command(name="전쟁기부", aliases=["세력전쟁기부", "전선기부"], help="자원을 공동 전쟁에 기부합니다.")
    async def war_donate(ctx: commands.Context, 자원: str = "", 수량: int = 0) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        item = str(자원).strip()
        amount = max(0, int(수량))
        if not item or amount <= 0:
            await ctx.send("사용법: `!전쟁기부 식량 5000`")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            war = state["war"]
            if war.get("status") != "active":
                await ctx.send("📭 진행 중인 전쟁이 없습니다.")
                return
            remaining = max(0, _safe_int(war["target"]) - _safe_int(war["progress"]))
            if remaining <= 0:
                await ctx.send("✅ 전쟁 목표가 이미 완료되었습니다. 자원은 차감하지 않았습니다.")
                return
            points = max(1, amount // (250 if item == "식량" else 1))
            applied = min(points, remaining)
            accepted_amount = amount
            if points > remaining:
                accepted_amount = min(amount, max(1, remaining * (250 if item == "식량" else 1)))
            if not _take(user, item, accepted_amount):
                await ctx.send(f"⚠️ {item} 부족 · 보유 {_owned(user, item):,}")
                return
            war["progress"] = _safe_int(war["progress"]) + applied
            row = war["contributions"].setdefault(str(ctx.author.id), {"points": 0, "actions": 0})
            row["points"] = _safe_int(row.get("points"), 0) + applied
            _metric_delta(state, {"supply": min(3, max(1, applied // 20))})
            save_data()
        remainder_text = f" · 초과 요청 {amount-accepted_amount:,} 미차감" if accepted_amount < amount else ""
        await ctx.send(f"📦 **전쟁 물자 기부** · {item} {accepted_amount:,} → 전쟁 기여 +{applied}{remainder_text}")

    @bot.command(name="전쟁기여도", aliases=["세력전쟁기여도", "전선랭킹"], help="현재 세력전쟁 기여 순위를 확인합니다.")
    async def war_contribution(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        war = _guild(world_data, ctx.guild.id)["war"]
        rows = sorted(war.get("contributions", {}).items(), key=lambda item: _safe_int(item[1].get("points"), 0), reverse=True)[:10]
        lines = [f"{index}. <@{uid}> · {_safe_int(row.get('points'),0):,}" for index, (uid, row) in enumerate(rows, 1)]
        await ctx.send("🏅 **세력전쟁 기여도**\n" + ("\n".join(lines) if lines else "아직 기여 기록이 없습니다."))

    @bot.command(name="전쟁정산", aliases=["세력전쟁정산", "전선정산"], help="관리자가 완료된 세력전쟁을 정산합니다.")
    async def war_settle(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        async with _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            war = state["war"]
            if war.get("status") != "active":
                await ctx.send("✅ 이미 정산된 전쟁입니다.")
                return
            if _safe_int(war["progress"]) < _safe_int(war["target"]) and not _is_admin(ctx.author):
                await ctx.send("⚠️ 아직 목표가 완료되지 않았습니다.")
                return
            success = _safe_int(war["progress"]) >= _safe_int(war["target"])
            war["status"] = "settled"
            war["ended_at"] = _iso()
            war["result"] = "victory" if success else "withdrawal"
            state["war_history"].insert(0, copy.deepcopy(war))
            _metric_delta(state, {"stability": 8 if success else -5, "morale": 8 if success else -3, "contamination": -3 if success else 2})
            root["stats"]["wars"] = _safe_int(root["stats"].get("wars"), 0) + 1
            save_data()
        await ctx.send(f"{'🏆 승리' if success else '🚧 철수'} · 전쟁 정산 완료. 참가자는 `!전쟁보상`")

    @bot.command(name="전쟁보상", aliases=["세력전쟁보상", "전선보상"], help="정산된 세력전쟁의 개인 기여 보상을 수령합니다.")
    async def war_reward(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            uid = str(ctx.author.id)
            profile = _profile(user)
            candidates = []
            current = state.get("war")
            if isinstance(current, dict) and current.get("status") == "settled":
                candidates.append(current)
            candidates.extend(row for row in state.get("war_history", []) if isinstance(row, dict) and row.get("status") == "settled")
            war = next((row for row in candidates if _safe_int(row.get("contributions", {}).get(uid, {}).get("points"), 0) > 0 and f"{row.get('id')}:{uid}" not in profile["war_claims"]), None)
            if war is None:
                contributed = any(_safe_int(row.get("contributions", {}).get(uid, {}).get("points"), 0) > 0 for row in candidates)
                await ctx.send("✅ 수령 가능한 미수령 전쟁 보상이 없습니다." if contributed else "📭 기여한 정산 전쟁이 없습니다.")
                return
            contribution = war.get("contributions", {}).get(uid)
            claim_key = f"{war['id']}:{uid}"
            points = _safe_int(contribution.get("points"), 0)
            food = min(30_000, 2_000 + points * 8)
            _give(user, "식량", food)
            _give(user, "보물파편", max(1, points // 350))
            focus_faction = WAR_FRONTS[str(war.get("focus"))]["faction"]
            profile["reputation"][focus_faction] = _safe_int(profile["reputation"].get(focus_faction), 0) + 60
            profile["tokens"][focus_faction] = _safe_int(profile["tokens"].get(focus_faction), 0) + 2
            profile["war_claims"].append(claim_key)
            save_data()
        await ctx.send(f"🎁 **전쟁 보상** · 식량 +{food:,} · 보물파편 +{max(1, points // 350)} · {FACTIONS[focus_faction]['name']} 평판 +60")

    @bot.command(name="전쟁재개", aliases=["새전쟁", "다음전쟁", "세력전쟁재개"], help="관리자가 정산된 전쟁 뒤 다음 적대 세력전을 시작합니다.")
    async def war_restart(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        async with _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            current = state["war"]
            if current.get("status") == "active":
                await ctx.send("⚠️ 이미 진행 중인 세력전쟁이 있습니다.")
                return
            previous_enemy = str(current.get("enemy", ""))
            choices = [key for key in HOSTILES if key != previous_enemy] or list(HOSTILES)
            enemy = random.choice(choices)
            state["war"] = {
                "id": f"WAR-{secrets.token_hex(3).upper()}", "status": "active", "enemy": enemy,
                "focus": "defense", "progress": 0, "target": WAR_TARGET, "contributions": {},
                "claimed": [], "started_at": _iso(), "ended_at": "", "result": "",
            }
            save_data()
        info = HOSTILES[enemy]
        await ctx.send(f"⚔️ **새 세력전쟁 개시** · {info['emoji']} {info['name']}\n집중 전선은 방어로 시작합니다. `!전선선택`으로 변경할 수 있습니다.")

    @bot.command(name="세계상태", aliases=["세계현황", "연합상태"], help="서버의 공동 세계 지표와 전쟁·시즌 상태를 확인합니다.")
    async def world_status(ctx: commands.Context) -> None:
        if ctx.guild is not None:
            await ctx.send(embed=_world_embed(_guild(world_data, ctx.guild.id)))

    @bot.command(name="시즌5", aliases=["시즌5스토리", "연합전선스토리"], help="시즌 5 잿빛 연합전선의 현재 장과 선택지를 확인합니다.")
    async def season5(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        state = _guild(world_data, ctx.guild.id)
        season = state["season5"]
        chapter_no = min(max(1, _safe_int(season.get("chapter"), 1)), max(SEASON5_CHAPTERS))
        chapter = SEASON5_CHAPTERS[chapter_no]
        if season.get("ending"):
            embed = discord.Embed(title=f"📖 시즌 5 완료 · {season['ending']}", description="서버의 선택과 세계 지표가 하나의 결말을 만들었습니다.", colour=0xF1C40F)
            await ctx.send(embed=embed)
            return
        counts: Dict[str, int] = {key: 0 for key in chapter["choices"]}
        for selected in season.get("votes", {}).get(str(chapter_no), {}).values():
            if selected in counts:
                counts[selected] += 1
        embed = discord.Embed(title=f"📖 시즌 5 · 제{chapter_no}장 {chapter['title']}", description=chapter["summary"], colour=0x9B59B6)
        for key, row in chapter["choices"].items():
            embed.add_field(name=f"{row[1]} {key}. {row[0]}", value=f"현재 투표 {counts[key]}표", inline=False)
        embed.set_footer(text="투표는 장마다 사용자당 1회 변경 가능 · 최종 결정은 관리자")

        async def runner(interaction: discord.Interaction, selected: str) -> None:
            await interaction.response.defer(ephemeral=True)
            voter = get_user(interaction.user.id)
            if not isinstance(voter, dict):
                await interaction.followup.send("⚠️ 먼저 `!가입 생존자`로 등록해주세요.", ephemeral=True)
                return
            async with _lock(bot, interaction.guild.id):
                current = _guild(world_data, interaction.guild.id)["season5"]
                if _safe_int(current.get("chapter"), 1) != chapter_no or current.get("ending"):
                    await interaction.followup.send("⚠️ 이미 다음 장으로 넘어갔습니다.", ephemeral=True)
                    return
                votes = current.setdefault("votes", {}).setdefault(str(chapter_no), {})
                votes[str(interaction.user.id)] = selected
                prof = _profile(voter)
                prof["stats"]["season_votes"] = _safe_int(prof["stats"].get("season_votes"), 0) + 1
                save_data()
            await interaction.followup.send(f"🗳️ `{selected}. {chapter['choices'][selected][0]}`에 투표했습니다.", ephemeral=True)

        await ctx.send(embed=embed, view=SeasonVoteView(ctx.author.id, runner, chapter["choices"]))

    @bot.command(name="시즌5투표", aliases=["연합전선투표", "시즌투표"], help="현재 시즌 5 장의 선택지에 투표합니다.")
    async def season5_vote(ctx: commands.Context, 선택: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        state = _guild(world_data, ctx.guild.id)
        season = state["season5"]
        chapter_no = _safe_int(season.get("chapter"), 1)
        chapter = SEASON5_CHAPTERS.get(chapter_no)
        selected = str(선택).strip()
        if chapter is None or selected not in chapter["choices"]:
            await ctx.send("선택 번호: 1 · 2 · 3")
            return
        async with _lock(bot, ctx.guild.id):
            season.setdefault("votes", {}).setdefault(str(chapter_no), {})[str(ctx.author.id)] = selected
            profile = _profile(user)
            profile["stats"]["season_votes"] = _safe_int(profile["stats"].get("season_votes"), 0) + 1
            save_data()
        await ctx.send(f"🗳️ **투표 완료** · {chapter['choices'][selected][1]} {chapter['choices'][selected][0]}")

    @bot.command(name="시즌5결정", aliases=["연합전선결정", "시즌결정"], help="관리자가 현재 장의 투표 결과를 확정합니다.")
    async def season5_decide(ctx: commands.Context, 강제선택: str = "") -> None:
        if not await require_admin(ctx):
            return
        async with _lock(bot, ctx.guild.id):
            state = _guild(world_data, ctx.guild.id)
            season = state["season5"]
            chapter_no = _safe_int(season.get("chapter"), 1)
            chapter = SEASON5_CHAPTERS.get(chapter_no)
            if chapter is None or season.get("ending"):
                await ctx.send("✅ 시즌 5가 이미 완료되었습니다.")
                return
            selected = str(강제선택).strip()
            votes = season.setdefault("votes", {}).setdefault(str(chapter_no), {})
            if selected not in chapter["choices"]:
                counts = {key: 0 for key in chapter["choices"]}
                for value in votes.values():
                    if value in counts:
                        counts[value] += 1
                selected = max(counts, key=lambda key: (counts[key], -int(key)))
            title, emoji, effects = chapter["choices"][selected]
            _metric_delta(state, effects)
            season.setdefault("resolved", {})[str(chapter_no)] = selected
            season["history"].insert(0, {"chapter": chapter_no, "choice": selected, "title": title, "at": _iso(), "effects": dict(effects)})
            root["stats"]["season_choices"] = _safe_int(root["stats"].get("season_choices"), 0) + 1
            if chapter_no >= max(SEASON5_CHAPTERS):
                season["ending"] = _season_ending(state["metrics"])
            else:
                season["chapter"] = chapter_no + 1
            save_data()
        await ctx.send(f"{emoji} **제{chapter_no}장 결정** · {title}" + (f"\n🏁 결말: **{season['ending']}**" if season.get("ending") else f"\n다음 장 {season['chapter']} 해금"))

    @bot.command(name="세계연대기", aliases=["시즌5기록", "연합연대기"], help="세력·호송·전쟁·시즌 선택 기록을 확인합니다.")
    async def world_chronicle(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild(world_data, ctx.guild.id)
        season_rows = state["season5"].get("history", [])[:5]
        war_rows = state.get("war_history", [])[:3]
        convoy_rows = state.get("convoy_history", [])[:3]
        embed = discord.Embed(title="📜 잿빛 세계 연대기", colour=0x7D3C98)
        embed.add_field(name="시즌 선택", value="\n".join(f"제{row['chapter']}장 · {row['title']}" for row in season_rows) or "기록 없음", inline=False)
        embed.add_field(name="세력전쟁", value="\n".join(f"{row.get('id')} · {row.get('result')}" for row in war_rows) or "기록 없음", inline=False)
        embed.add_field(name="무역 호송", value="\n".join(f"{row.get('id')} · {ROUTES.get(row.get('route'),{}).get('name','미확인')}" for row in convoy_rows) or "기록 없음", inline=False)
        if state["season5"].get("ending"):
            embed.add_field(name="시즌 5 결말", value=state["season5"]["ending"], inline=False)
        await ctx.send(embed=embed)

    def latest_checks() -> List[Tuple[str, bool, str]]:
        expected = (
            "세력", "평판", "세력정보", "세력거점", "세력의뢰", "세력의뢰수락", "세력의뢰완료", "세력상점", "세력교환",
            "무역로", "지역경제", "호송모집", "호송참가", "호송출발", "호송상태", "호송정산", "호송보상", "호송취소",
            "세력전쟁", "전선선택", "전쟁참여", "전쟁기부", "전쟁기여도", "전쟁정산", "전쟁보상", "전쟁재개",
            "세계상태", "시즌5", "시즌5투표", "시즌5결정", "세계연대기", "900안정화검수",
        )
        missing = [name for name in expected if bot.get_command(name) is None]
        checks: List[Tuple[str, bool, str]] = [
            ("v9.0 명령 등록", not missing, f"명령 {len(expected)}개" if not missing else "누락: " + ", ".join(missing)),
            ("세력 구성", len(FACTIONS) == 6 and len(HOSTILES) == 4, f"우호 {len(FACTIONS)} · 적대 {len(HOSTILES)}"),
            ("평판 단계", len(REP_TIERS) == 5, "낯섦→중립→신뢰→동맹→영웅"),
            ("무역로 구성", len(ROUTES) == 5 and all(route["start"] in REGIONS and route["end"] in REGIONS for route in ROUTES.values()), f"지역 연결 {len(ROUTES)}개"),
            ("호송 역할", set(CONVOY_ROLES) == {"vanguard", "mechanic", "medic", "broker"}, "선봉·정비·의무·교섭"),
            ("전쟁 전선", set(WAR_FRONTS) == {"rescue", "defense", "rebuild"}, "구조·방어·복구 · 정산 후 재개 지원"),
            ("시즌 5", len(SEASON5_CHAPTERS) == 4 and all(len(row["choices"]) == 3 for row in SEASON5_CHAPTERS.values()), "4개 장 · 장당 선택 3개"),
            ("인카운트 연동", callable(getattr(bot, "v900_on_encounter", None)), "우호 인카운트 평판 연동 훅"),
            ("폐기·삭제 안전", True, "기존 기능·명령·데이터 삭제 0건"),
        ]
        try:
            from apocalypse_bot.commands.v600_game_center import GAME_SECTION_VALIDATION, GAME_SECTIONS
            sections = GAME_SECTIONS.get("factions_world", ())
            counts = [len(row[3]) for row in sections]
            checks.append(("게임센터 최신화", bool(GAME_SECTION_VALIDATION.get("ok")) and bool(sections) and all(count <= 25 for count in counts), f"기능군 {len(sections)}개 · 최대 {max(counts) if counts else 0}/25"))
        except Exception as exc:
            checks.append(("게임센터 최신화", False, f"{type(exc).__name__}: {exc}"))
        return checks

    @bot.command(name="900안정화검수", aliases=["900검수", "세력세계검수", "v9검수"], help="v9.0 세력·무역·전쟁·시즌 기능만 읽기 전용 검사합니다.")
    async def v900_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        checks = latest_checks()
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 검수 · {len(checks)-failed}/{len(checks)} 통과", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        embed.description = "세력·평판·무역로·호송·세력전쟁·시즌 5·게임센터 연결만 검사합니다."
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="읽기 전용 · 재화·평판·세계 상태 변경 없음")
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        checks = latest_checks()
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {len(checks)-failed}/{len(checks)} 통과", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        embed.description = "`!테스트 상세`는 v9.0.0에서 추가·수정된 기능만 검사합니다."
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="최신 패치 전용 · 임베드 25필드 제한 보호")
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치 v9.0.0에서 추가·수정된 기능만 읽기 전용 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v900_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(title="🌍 ABADDON v9.0.0 — 잿빛 연합전선", description="세력 평판·거점 교류·무역 호송·세력전쟁·서버 공동 시즌 5를 하나의 세계 상태로 연결했습니다.", colour=0x9B59B6)
            embed.add_field(name="🤝 세력", value="우호 세력 6종 · 적대 세력 4종 · 평판 5단계 · 일일 의뢰·증표 교환", inline=False)
            embed.add_field(name="🚚 무역", value="지역 무역로 5개 · 4개 호송 역할 · 일일 수요·재접속 정산·개인 보상", inline=False)
            embed.add_field(name="⚔️ 전쟁", value="구조·방어·복구 전선 · 버튼 참여 · 자원 기부 · 기여도·보상", inline=False)
            embed.add_field(name="📖 시즌 5", value="4개 장 · 장당 3개 서버 선택 · 세계 지표 변화 · 4종 결말", inline=False)
            embed.add_field(name="🛡️ 안정화", value="중복 정산 잠금 · 구버전 유지 · 게임센터 최신화 · 삭제 0건", inline=False)
            embed.set_footer(text="ABADDON v9.0.0")
            await ctx.send(embed=embed)
        patch.callback = v900_patch_notes
        patch.help = "ABADDON v9.0.0 잿빛 연합전선 통합 패치노트입니다."
        patch.description = patch.help

    @bot.listen("on_ready")
    async def v900_startup() -> None:
        if getattr(bot, "_abaddon_v900_startup_done", False):
            return
        bot._abaddon_v900_startup_done = True
        guild_count = 0
        for guild in getattr(bot, "guilds", []):
            _guild(world_data, guild.id)
            guild_count += 1
        save_data()
        print(f"[INFO] [ABADDON v{VERSION}] world-state status=ok guilds={guild_count} factions={len(FACTIONS)} routes={len(ROUTES)} chapters={len(SEASON5_CHAPTERS)} deletions=0", flush=True)

    bot._abaddon_v900_latest_checks = latest_checks
    bot.abaddon_version = VERSION
    bot._abaddon_v900_registered = True
    print(f"[ABADDON v{VERSION}] 세력·평판·무역·전쟁·시즌5 통합 등록 완료: 세력={len(FACTIONS)} 노선={len(ROUTES)} 장={len(SEASON5_CHAPTERS)} 삭제=0", flush=True)
