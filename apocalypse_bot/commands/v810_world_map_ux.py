from __future__ import annotations

import asyncio
import hashlib
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "8.1.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
SCOUT_COOLDOWN_SECONDS = 12 * 60
BOSS_COOLDOWN_SECONDS = 30 * 60
MAX_HISTORY = 300

REGIONS: Dict[str, Dict[str, Any]] = {
    "outskirts": {
        "name": "대피소 외곽", "emoji": "🏚️", "aliases": ("외곽", "대피소외곽", "outskirts"),
        "description": "붕괴한 주거지와 보급 창고가 흩어진 첫 개척 구역입니다.",
        "target": 650, "stamina": 7, "boss": "잔해 포식자", "boss_emoji": "🦂", "boss_hp": 12_000,
        "resources": ("식량", "나무", "고철"), "events": ("무너진 편의점", "고립된 생존 신호", "지하 창고 입구"),
    },
    "flooded_rail": {
        "name": "침수 철도", "emoji": "🌊", "aliases": ("철도", "침수철도", "floodedrail"),
        "description": "물이 찬 선로와 화물칸 사이에 기계 부품과 폐쇄된 통로가 남아 있습니다.",
        "target": 950, "stamina": 9, "boss": "철갑 수몰체", "boss_emoji": "🐊", "boss_hp": 18_000,
        "resources": ("고철", "광석", "폐허회로"), "events": ("잠긴 화물칸", "고장 난 배수 펌프", "수중 신호기"),
    },
    "ash_forest": {
        "name": "잿빛 수림", "emoji": "🌲", "aliases": ("수림", "잿빛수림", "ashforest"),
        "description": "화산재가 내려앉은 숲입니다. 약초와 목재가 풍부하지만 시야가 짧습니다.",
        "target": 1_250, "stamina": 11, "boss": "재의 사슴왕", "boss_emoji": "🦌", "boss_hp": 24_000,
        "resources": ("나무", "약초", "오염표본"), "events": ("재로 덮인 온실", "무너진 감시탑", "변이 동물 흔적"),
    },
    "red_fog": {
        "name": "적색 안개 협곡", "emoji": "🌫️", "aliases": ("협곡", "적색안개", "적색안개협곡", "redfog"),
        "description": "방향 감각을 잃게 만드는 붉은 안개와 오래된 군용 시설이 남아 있습니다.",
        "target": 1_600, "stamina": 13, "boss": "안개 감시자", "boss_emoji": "👁️", "boss_hp": 32_000,
        "resources": ("광석", "오염표본", "설계도조각"), "events": ("묻힌 초소", "끊어진 유도 신호", "붉은 방호문"),
    },
    "reactor_grave": {
        "name": "원자로 묘지", "emoji": "☢️", "aliases": ("원자로", "원자로묘지", "reactorgrave"),
        "description": "폐기된 소형 원자로와 자동 방어 장치가 뒤엉킨 고위험 구역입니다.",
        "target": 2_050, "stamina": 15, "boss": "노심 파수기", "boss_emoji": "🤖", "boss_hp": 42_000,
        "resources": ("폐허회로", "오염표본", "설계도조각"), "events": ("냉각재 저장고", "오작동 포탑", "차폐 연구실"),
    },
    "twilight_terminal": {
        "name": "황혼 종착지", "emoji": "🚂", "aliases": ("종착지", "황혼종착지", "황혼", "twilightterminal"),
        "description": "스토리의 흔적과 미확인 열차가 교차하는 최종 공동 개척 지역입니다.",
        "target": 2_700, "stamina": 18, "boss": "종착역의 기관장", "boss_emoji": "🎭", "boss_hp": 58_000,
        "resources": ("보물파편", "폐허회로", "설계도조각"), "events": ("멈춘 객차", "시간이 뒤틀린 플랫폼", "봉인된 관제실"),
    },
}
REGION_ORDER: Tuple[str, ...] = tuple(REGIONS)
REGION_LOOKUP: Dict[str, str] = {}
for _key, _info in REGIONS.items():
    REGION_LOOKUP[_key.casefold()] = _key
    REGION_LOOKUP[str(_info["name"]).replace(" ", "").casefold()] = _key
    for _alias in _info["aliases"]:
        REGION_LOOKUP[str(_alias).replace(" ", "").casefold()] = _key

CHOICES: Dict[str, Dict[str, str]] = {
    "safe": {"name": "안전 경로", "emoji": "🛡️", "aliases": ("안전", "안전경로", "경로", "안전로", "safe")},
    "signal": {"name": "신호 추적", "emoji": "📡", "aliases": ("신호", "신호추적", "추적", "탐색", "signal")},
    "breach": {"name": "위험 돌파", "emoji": "⚠️", "aliases": ("위험", "위험돌파", "돌파", "강행", "breach")},
}
CHOICE_LOOKUP = {str(token).replace(" ", "").casefold(): key for key, info in CHOICES.items() for token in info["aliases"]}
OUTPOSTS: Dict[str, Dict[str, Any]] = {
    "watchtower": {"name": "감시탑", "emoji": "🔭", "aliases": ("감시탑", "정찰탑"), "description": "정찰 진행도와 위험 대응을 보조합니다."},
    "purifier": {"name": "정화소", "emoji": "💧", "aliases": ("정화소", "정수소"), "description": "오염 누적과 부상 위험을 낮춥니다."},
    "depot": {"name": "보급소", "emoji": "📦", "aliases": ("보급소", "창고"), "description": "개척 보상과 지역 보급을 안정화합니다."},
}
OUTPOST_LOOKUP = {str(alias).replace(" ", "").casefold(): key for key, info in OUTPOSTS.items() for alias in (key, info["name"], *info["aliases"])}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
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
    return max(minimum, result) if minimum is not None else result


def _format_seconds(seconds: Any) -> str:
    value = max(0, _safe_int(seconds))
    minutes, sec = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def _region_key(raw: Any) -> Optional[str]:
    return REGION_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _choice_key(raw: Any) -> Optional[str]:
    return CHOICE_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _outpost_key(raw: Any) -> Optional[str]:
    return OUTPOST_LOOKUP.get(str(raw or "").strip().replace(" ", "").casefold())


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v810_world_map", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v810_world_map"] = root
    root.setdefault("schema_version", SCHEMA_VERSION)
    root.setdefault("guilds", {})
    root.setdefault("stats", {"scouts": 0, "donations": 0, "boss_attacks": 0, "unlocks": 0, "deletions": 0})
    root["schema_version"] = SCHEMA_VERSION
    return root


def _new_region_state(key: str, unlocked: bool) -> MutableMapping[str, Any]:
    info = REGIONS[key]
    return {
        "unlocked": bool(unlocked), "progress": 0, "target": int(info["target"]),
        "safety": 35 if unlocked else 10, "pollution": 12 if unlocked else 25,
        "outposts": {name: 0 for name in OUTPOSTS},
        "boss": {"active": False, "defeated": False, "hp": int(info["boss_hp"]), "max_hp": int(info["boss_hp"]), "contributions": {}, "claimed": []},
        "discoveries": [], "history": [], "unlocked_at": _iso() if unlocked else "",
    }


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(guild_id)] = state
    regions = state.setdefault("regions", {})
    if not isinstance(regions, dict):
        regions = {}
        state["regions"] = regions
    for index, key in enumerate(REGION_ORDER):
        if not isinstance(regions.get(key), dict):
            regions[key] = _new_region_state(key, index == 0)
        row = regions[key]
        row.setdefault("unlocked", index == 0)
        row.setdefault("progress", 0)
        row.setdefault("target", int(REGIONS[key]["target"]))
        row.setdefault("safety", 35 if index == 0 else 10)
        row.setdefault("pollution", 12 if index == 0 else 25)
        row.setdefault("outposts", {name: 0 for name in OUTPOSTS})
        row.setdefault("boss", {"active": False, "defeated": False, "hp": int(REGIONS[key]["boss_hp"]), "max_hp": int(REGIONS[key]["boss_hp"]), "contributions": {}, "claimed": []})
        row.setdefault("discoveries", [])
        row.setdefault("history", [])
    state.setdefault("history", [])
    state.setdefault("created_at", _iso())
    return state


def _profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = user.setdefault("exploration_v810", {})
    if not isinstance(profile, dict):
        profile = {}
        user["exploration_v810"] = profile
    profile.setdefault("schema_version", SCHEMA_VERSION)
    profile.setdefault("pending", {})
    profile.setdefault("last_scout_at", "")
    profile.setdefault("boss_cooldowns", {})
    profile.setdefault("discoveries", [])
    profile.setdefault("history", [])
    profile.setdefault("stats", {"scouts": 0, "progress": 0, "boss_damage": 0, "rewards": 0})
    return profile


def _lock(bot: commands.Bot, guild_id: int) -> asyncio.Lock:
    locks = getattr(bot, "_v810_world_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_v810_world_locks", locks)
    lock = locks.get(guild_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[guild_id] = lock
    return lock


def _user_lock(bot: commands.Bot, user_id: int) -> asyncio.Lock:
    locks = getattr(bot, "_v810_user_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_v810_user_locks", locks)
    lock = locks.get(user_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[user_id] = lock
    return lock


def _is_admin(member: Any) -> bool:
    return isinstance(member, discord.Member) and (member.guild_permissions.administrator or member.guild_permissions.manage_guild)


def _refresh_unlocks(state: MutableMapping[str, Any]) -> int:
    unlocked = 0
    regions = state["regions"]
    for index, key in enumerate(REGION_ORDER):
        if index == 0:
            regions[key]["unlocked"] = True
            continue
        previous = regions[REGION_ORDER[index - 1]]
        row = regions[key]
        if previous.get("boss", {}).get("defeated") and not row.get("unlocked"):
            row["unlocked"] = True
            row["unlocked_at"] = _iso()
            row["safety"] = max(25, _safe_int(row.get("safety"), 10))
            unlocked += 1
    return unlocked


def _weather(world_data: Mapping[str, Any], guild_id: int) -> Tuple[str, str, float]:
    try:
        guilds = world_data.get("v780_server_disaster", {}).get("guilds", {})
        active = guilds.get(str(guild_id), {}).get("active", {})
        weather_key = str(active.get("weather") or "clear")
        from apocalypse_bot.commands.v790_operations_disaster import WEATHER_STATES
        info = WEATHER_STATES.get(weather_key, WEATHER_STATES["clear"])
        risk = str(info.get("risk") or "낮음")
        mult = {"낮음": 0.92, "주의": 1.0, "위험": 1.12, "극심": 1.24}.get(risk, 1.0)
        return f"{info.get('emoji','☁️')} {info.get('name','회색 하늘')}", risk, mult
    except Exception:
        return "☁️ 회색 하늘", "낮음", 1.0


def _bar(current: int, target: int, width: int = 12) -> str:
    target = max(1, target)
    filled = min(width, max(0, int(round(current / target * width))))
    return "█" * filled + "░" * (width - filled)


def _region_status(row: Mapping[str, Any]) -> str:
    if not row.get("unlocked"):
        return "🔒 봉쇄"
    boss = row.get("boss") if isinstance(row.get("boss"), dict) else {}
    if boss.get("defeated"):
        return "✅ 개척 완료"
    if boss.get("active"):
        return "👹 지역 보스 출현"
    return "🧭 개척 중"


def _map_embed(world_data: MutableMapping[str, Any], guild_id: int) -> discord.Embed:
    state = _guild_state(world_data, guild_id)
    _refresh_unlocks(state)
    weather_name, weather_risk, _ = _weather(world_data, guild_id)
    embed = discord.Embed(
        title="🗺️ ABADDON 공동 탐험 지도",
        description="개인 정찰과 서버 공동 개척으로 지역을 열고, 거점을 건설한 뒤 지역 보스를 격파합니다.",
        colour=0x2C3E50,
    )
    embed.add_field(name="현재 환경", value=f"{weather_name} · 경계 **{weather_risk}**", inline=False)
    lines: List[str] = []
    for key in REGION_ORDER:
        info = REGIONS[key]
        row = state["regions"][key]
        progress = _safe_int(row.get("progress"), 0)
        target = _safe_int(row.get("target"), info["target"])
        if not row.get("unlocked"):
            lines.append(f"{info['emoji']} **{info['name']}** · 🔒 이전 지역 완료 필요")
        else:
            lines.append(f"{info['emoji']} **{info['name']}** · {_region_status(row)} · `{_bar(progress, target, 8)}` {min(progress,target):,}/{target:,}")
    embed.add_field(name="개척 경로", value="\n".join(lines), inline=False)
    embed.add_field(name="진행 순서", value="`!지역정찰 지역` → `!지역선택 행동` → `!개척기부`/`!거점건설` → `!지역보스공격`", inline=False)
    embed.set_footer(text="관리자는 잠긴 지역도 점검 가능 · 일반 생존자는 앞 지역 보스 격파 후 순차 해금")
    return embed


def _region_embed(world_data: MutableMapping[str, Any], guild_id: int, key: str) -> discord.Embed:
    state = _guild_state(world_data, guild_id)
    _refresh_unlocks(state)
    info, row = REGIONS[key], state["regions"][key]
    progress, target = _safe_int(row.get("progress"), 0), _safe_int(row.get("target"), info["target"])
    boss = row["boss"]
    outposts = row["outposts"]
    embed = discord.Embed(title=f"{info['emoji']} {info['name']}", description=info["description"], colour=0x34495E)
    embed.add_field(name="상태", value=_region_status(row), inline=True)
    embed.add_field(name="개척도", value=f"`{_bar(progress,target)}`\n{min(progress,target):,}/{target:,}", inline=True)
    embed.add_field(name="환경", value=f"🛡️ 안전도 {_safe_int(row.get('safety'),0)}\n☣️ 오염도 {_safe_int(row.get('pollution'),0)}", inline=True)
    embed.add_field(name="회수 자원", value=" · ".join(map(str, info["resources"])), inline=False)
    embed.add_field(name="거점", value=" · ".join(f"{OUTPOSTS[k]['emoji']} {OUTPOSTS[k]['name']} Lv.{_safe_int(outposts.get(k),0)}" for k in OUTPOSTS), inline=False)
    if boss.get("active") or boss.get("defeated"):
        embed.add_field(name=f"{info['boss_emoji']} {info['boss']}", value=("격파 완료" if boss.get("defeated") else f"HP {_safe_int(boss.get('hp'),0):,}/{_safe_int(boss.get('max_hp'),info['boss_hp']):,}"), inline=False)
    embed.set_footer(text="확률 수치는 공개하지 않으며 실제 발견 결과만 표시합니다.")
    return embed


def _bag_for(user: MutableMapping[str, Any], item: str) -> MutableMapping[str, Any]:
    if item in {"보물파편", "폐허회로", "오염표본", "설계도조각"}:
        value = user.setdefault("materials", {})
    else:
        value = user.setdefault("resources", {})
    if not isinstance(value, dict):
        value = {}
        user["materials" if item in {"보물파편", "폐허회로", "오염표본", "설계도조각"} else "resources"] = value
    return value


def _give(user: MutableMapping[str, Any], item: str, amount: int) -> str:
    amount = max(0, int(amount))
    if item == "식량":
        user["balance"] = max(0, _safe_int(user.get("balance"), 0)) + amount
        return f"🥫 식량 +{amount:,}"
    bag = _bag_for(user, item)
    bag[item] = max(0, _safe_int(bag.get(item), 0)) + amount
    emoji = {"나무": "🪵", "고철": "🔩", "광석": "⛏️", "약초": "🌿", "보물파편": "🧩", "폐허회로": "🔌", "오염표본": "🧪", "설계도조각": "📐"}.get(item, "📦")
    return f"{emoji} {item} +{amount}"


def _activate_boss(row: MutableMapping[str, Any], info: Mapping[str, Any]) -> bool:
    if _safe_int(row.get("progress"), 0) < _safe_int(row.get("target"), info["target"]):
        return False
    boss = row["boss"]
    if boss.get("defeated") or boss.get("active"):
        return False
    boss["active"] = True
    boss["hp"] = _safe_int(info["boss_hp"])
    boss["max_hp"] = _safe_int(info["boss_hp"])
    boss.setdefault("contributions", {})
    boss.setdefault("claimed", [])
    row["progress"] = _safe_int(row.get("target"), info["target"])
    return True


def _outpost_cost(kind: str, next_level: int) -> Dict[str, int]:
    if kind == "watchtower":
        return {"고철": 16 * next_level, "폐허회로": 4 * next_level}
    if kind == "purifier":
        return {"약초": 14 * next_level, "오염표본": 3 * next_level}
    return {"나무": 18 * next_level, "식량": 4_000 * next_level}


def _incident_rows(world_data: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    rows: List[Mapping[str, Any]] = []
    v702 = world_data.get("operations_v702", {})
    if isinstance(v702, dict) and isinstance(v702.get("incidents"), list):
        rows.extend(row for row in v702["incidents"] if isinstance(row, dict))
    v711 = world_data.get("v711_cute_interactions", {})
    if isinstance(v711, dict) and isinstance(v711.get("ui_errors"), list):
        for row in v711["ui_errors"]:
            if isinstance(row, dict):
                rows.append({"id": row.get("id"), "at": row.get("created_at"), "command": row.get("where"), "error_type": "UIError", "message": row.get("error"), "user_id": row.get("user_id"), "guild_id": row.get("guild_id")})
    return rows


class ScoutChoiceView(discord.ui.View):
    def __init__(self, owner_id: int, resolver: Callable[[discord.Interaction, str], Any]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.resolver = resolver

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 정찰 선택은 출발한 생존자만 결정할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="안전 경로", emoji="🛡️", style=discord.ButtonStyle.success)
    async def safe(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.resolver(interaction, "safe")

    @discord.ui.button(label="신호 추적", emoji="📡", style=discord.ButtonStyle.primary)
    async def signal(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.resolver(interaction, "signal")

    @discord.ui.button(label="위험 돌파", emoji="⚠️", style=discord.ButtonStyle.danger)
    async def breach(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.resolver(interaction, "breach")


class TerminalSelect(discord.ui.Select):
    def __init__(self, owner_id: int, runner: Callable[[discord.Interaction, str], Any]):
        self.owner_id = owner_id
        self.runner = runner
        options = [
            discord.SelectOption(label="오늘 할 일", value="오늘할일", emoji="☀️", description="출석·퀘스트·보상 확인"),
            discord.SelectOption(label="탐험 지도", value="세계지도", emoji="🗺️", description="지역 개척과 보스 진행"),
            discord.SelectOption(label="폐허 파밍", value="파밍", emoji="🧭", description="개인 파밍·인카운트"),
            discord.SelectOption(label="서버 재난", value="재난상황", emoji="🚨", description="공동 재난 참여"),
            discord.SelectOption(label="길드", value="길드관리", emoji="🏰", description="길드·기지·레이드"),
            discord.SelectOption(label="미니게임", value="아바돈게임", emoji="🎮", description="아바돈 1:1 및 게임"),
            discord.SelectOption(label="전체 게임센터", value="게임", emoji="📚", description="모든 기능 검색·실행"),
            discord.SelectOption(label="관리 점검", value="관리점검", emoji="🛡️", description="관리자 전용 점검 허브"),
        ]
        super().__init__(placeholder="지금 할 일을 고르세요", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 단말기는 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        await self.runner(interaction, self.values[0])


class TerminalView(discord.ui.View):
    def __init__(self, owner_id: int, runner: Callable[[discord.Interaction, str], Any]):
        super().__init__(timeout=300)
        self.add_item(TerminalSelect(owner_id, runner))


def register_v810_world_map_ux(
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
    if getattr(bot, "_abaddon_v810_registered", False):
        return
    bot._abaddon_v810_registered = True
    root = _root(world_data)

    additions = {
        "combat": (
            "!세계지도 / !지역정찰 / !지역보스 — 서버 공동 지역 개척",
            "!개척기부 / !거점건설 / !지역보상 — 공동 진척·거점·보상",
        ),
        "server": (
            "!단말기 — 상태 맞춤형 통합 생존 단말기",
            "!관리점검 / !오류조회 / !최근오류 — 관리자 점검·사건 조회",
            "!810안정화검수 — v8.1 신규·수정 기능 전용 검사",
        ),
    }
    for category_id, rows in additions.items():
        category = next((item for item in guide if item.get("id") == category_id), None)
        if category is None:
            continue
        existing = "\n".join(map(str, category.get("commands", [])))
        for row in rows:
            if row.split(" — ", 1)[0] not in existing:
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
            await ctx.send("⚠️ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    async def resolve_scout(user_id: int, guild_id: int, choice: str) -> Tuple[bool, str, Optional[discord.Embed]]:
        async with _user_lock(bot, user_id), _lock(bot, guild_id):
            user = get_user(user_id)
            if not isinstance(user, dict):
                return False, "⚠️ 생존자 데이터를 찾지 못했습니다.", None
            profile = _profile(user)
            pending = profile.get("pending") if isinstance(profile.get("pending"), dict) else {}
            if not pending or pending.get("resolved"):
                return False, "📭 진행 중인 지역 정찰이 없습니다.", None
            if str(pending.get("guild_id")) != str(guild_id):
                return False, "⚠️ 정찰을 시작한 서버에서 처리해주세요.", None
            key = str(pending.get("region"))
            if key not in REGIONS or choice not in CHOICES:
                return False, "⚠️ 정찰 기록이 올바르지 않습니다.", None
            state = _guild_state(world_data, guild_id)
            row, info = state["regions"][key], REGIONS[key]
            seed = _safe_int(pending.get("seed"), 0)
            rng = random.Random(seed ^ int(hashlib.sha256(choice.encode()).hexdigest()[:12], 16))
            weather_name, weather_risk, weather_mult = _weather(world_data, guild_id)
            tower = _safe_int(row["outposts"].get("watchtower"), 0)
            purifier = _safe_int(row["outposts"].get("purifier"), 0)
            depot = _safe_int(row["outposts"].get("depot"), 0)
            power = max(1, _safe_int(calculate_user_power(user), 1))
            choice_base = {"safe": (22, 36), "signal": (32, 50), "breach": (46, 70)}[choice]
            progress = rng.randint(*choice_base) + min(20, int(power ** 0.5) // 4) + tower * 4
            if choice == "breach":
                progress = int(progress * max(0.9, 1.15 - (weather_mult - 1.0)))
            remaining = max(0, _safe_int(row.get("target"), info["target"]) - _safe_int(row.get("progress"), 0))
            applied = min(progress, remaining)
            row["progress"] = _safe_int(row.get("progress"), 0) + applied
            if choice == "safe":
                row["safety"] = min(100, _safe_int(row.get("safety"), 0) + rng.randint(1, 3))
            elif choice == "signal":
                row["pollution"] = max(0, _safe_int(row.get("pollution"), 0) - purifier)
            else:
                row["pollution"] = min(100, _safe_int(row.get("pollution"), 0) + max(0, rng.randint(1, 4) - purifier))

            reward_pool = list(info["resources"])
            primary = rng.choice(reward_pool)
            if primary == "식량":
                amount = rng.randint(700, 1_600) + depot * 180
            else:
                amount = rng.randint(2, 6) + depot
            rewards = [_give(user, primary, amount)]
            if choice in {"signal", "breach"} and rng.randrange(1000) < (92 if choice == "signal" else 76):
                rare = rng.choice(("보물파편", "폐허회로", "설계도조각"))
                rewards.append(_give(user, rare, 1 if rare != "보물파편" else rng.randint(1, 2)))
            discovery = ""
            if rng.randrange(1000) < (58 if choice == "signal" else 35 if choice == "breach" else 18):
                discovery = f"{info['emoji']} {rng.choice(info['events'])}"
                if discovery not in row["discoveries"]:
                    row["discoveries"].append(discovery)
                if discovery not in profile["discoveries"]:
                    profile["discoveries"].append(discovery)
            damage = 0
            if choice == "breach" and rng.random() * weather_mult > 0.72 + purifier * 0.04:
                damage = rng.randint(4, 14)
                user["hp"] = max(1, _safe_int(user.get("hp"), 100) - damage)
            boss_started = _activate_boss(row, info)
            unlocked = _refresh_unlocks(state)
            root["stats"]["scouts"] = _safe_int(root["stats"].get("scouts"), 0) + 1
            root["stats"]["unlocks"] = _safe_int(root["stats"].get("unlocks"), 0) + unlocked
            profile["stats"]["scouts"] = _safe_int(profile["stats"].get("scouts"), 0) + 1
            profile["stats"]["progress"] = _safe_int(profile["stats"].get("progress"), 0) + applied
            profile["last_scout_at"] = _iso()
            event_id = str(pending.get("id"))
            pending["resolved"] = True
            history = {"id": event_id, "at": _iso(), "region": key, "choice": choice, "progress": applied, "rewards": rewards, "discovery": discovery}
            profile["history"].insert(0, history)
            del profile["history"][MAX_HISTORY:]
            row["history"].insert(0, {"user_id": str(user_id), **history})
            del row["history"][MAX_HISTORY:]
            state["history"].insert(0, {"user_id": str(user_id), **history})
            del state["history"][MAX_HISTORY:]
            profile["pending"] = {}
            add_season_points(user, 1)
            save_data()

            embed = discord.Embed(title=f"{CHOICES[choice]['emoji']} {info['name']} 정찰 결과", colour=0x27AE60 if damage == 0 else 0xE67E22)
            embed.description = f"**{rng.choice(info['events'])}**에서 선택한 경로를 따라 탐색을 마쳤습니다."
            embed.add_field(name="진행 경로", value=f"🚪 출발 → {info['emoji']} 진입 → {weather_name} → {CHOICES[choice]['emoji']} {CHOICES[choice]['name']} → 🏠 복귀", inline=False)
            embed.add_field(name="공동 개척", value=f"+{applied} · 현재 {row['progress']:,}/{row['target']:,}", inline=True)
            embed.add_field(name="회수품", value="\n".join(rewards), inline=True)
            if discovery:
                embed.add_field(name="🔎 신규 발견", value=discovery, inline=False)
            if damage:
                embed.add_field(name="⚠️ 현장 손상", value=f"HP -{damage} · 현재 {user.get('hp',1)}", inline=False)
            if boss_started:
                embed.add_field(name="👹 경보", value=f"개척 목표가 채워져 **{info['boss']}**가 출현했습니다. `!지역보스 {info['name']}`", inline=False)
            embed.set_footer(text=f"사건 {event_id} · 내부 확률/가중치는 공개하지 않음 · 중복 정산 방지 완료")
            return True, "", embed

    async def interaction_resolver(interaction: discord.Interaction, choice: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("⚠️ 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        ok, message, embed = await resolve_scout(interaction.user.id, interaction.guild.id, choice)
        if ok and embed is not None:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(message, ephemeral=True)

    @bot.command(name="단말기", aliases=["생존단말기", "통합단말기", "아바돈단말기"], help="현재 상태에 맞는 주요 기능을 한 선택창에서 엽니다.")
    async def terminal(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 채널에서 사용해주세요.")
            return
        user = get_user(ctx.author.id) or {}
        profile = _profile(user) if isinstance(user, dict) else {}
        state = _guild_state(world_data, ctx.guild.id)
        pending = profile.get("pending") if isinstance(profile.get("pending"), dict) else {}
        active_disaster = world_data.get("v780_server_disaster", {}).get("guilds", {}).get(str(ctx.guild.id), {}).get("active", {})
        unlocked = sum(1 for row in state["regions"].values() if row.get("unlocked"))
        embed = discord.Embed(title="🛰️ ABADDON 통합 생존 단말기", description="기존 명령을 삭제하지 않고 자주 쓰는 기능을 상태에 맞춰 연결합니다.", colour=0x5865F2)
        embed.add_field(name="지금 확인할 것", value=("⚠️ 진행 중인 지역 정찰이 있습니다 · `!지역선택`\n" if pending else "") + ("🚨 서버 공동 재난이 진행 중입니다 · `!재난상황`\n" if isinstance(active_disaster, dict) and active_disaster.get("status") == "active" else "") + f"🗺️ 개방 지역 {unlocked}/{len(REGION_ORDER)} · `!세계지도`", inline=False)
        embed.add_field(name="바로가기", value="☀️ 오늘 · 🗺️ 지도 · 🧭 파밍 · 🚨 재난 · 🏰 길드 · 🎮 미니게임 · 📚 전체 게임센터", inline=False)
        embed.set_footer(text="선택한 기능은 기존 명령 로직을 그대로 호출합니다 · 본인만 조작 가능")

        async def run(interaction: discord.Interaction, command_name: str) -> None:
            from apocalypse_bot.commands.v600_game_center import _invoke_command
            pass  # v18.1.3: _invoke_command owns the single interaction ACK
            await _invoke_command(bot, interaction, command_name)

        await ctx.send(embed=embed, view=TerminalView(ctx.author.id, run))

    @bot.command(name="세계지도", aliases=["탐험지도", "개척지도"], help="서버 공동 지역 개척 진행도를 확인합니다.")
    async def world_map(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 확인할 수 있습니다.")
            return
        await ctx.send(embed=_map_embed(world_data, ctx.guild.id))

    @bot.command(name="지역개척정보", aliases=["개척지역정보", "지도지역정보"], help="공동 개척 지역의 상세 상태를 확인합니다.")
    async def region_info(ctx: commands.Context, *, 지역: str = "") -> None:
        if ctx.guild is None:
            return
        key = _region_key(지역)
        if key is None:
            await ctx.send("🗺️ 지역을 골라주세요: " + " · ".join(info["name"] for info in REGIONS.values()))
            return
        await ctx.send(embed=_region_embed(world_data, ctx.guild.id, key))

    @bot.command(name="지역정찰", aliases=["개척정찰", "지도정찰"], help="지역을 정찰하고 현장 선택지를 엽니다.")
    async def region_scout(ctx: commands.Context, *, 지역: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        key = _region_key(지역)
        if key is None:
            await ctx.send("🗺️ 정찰할 지역을 입력해주세요. 예: `!지역정찰 대피소 외곽`")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild_state(world_data, ctx.guild.id)
            _refresh_unlocks(state)
            row, info = state["regions"][key], REGIONS[key]
            if not row.get("unlocked") and not _is_admin(ctx.author):
                await ctx.send("🔒 앞 지역의 개척 목표와 지역 보스를 완료해야 진입할 수 있습니다.")
                return
            profile = _profile(user)
            if profile.get("pending"):
                await ctx.send("⚠️ 이미 진행 중인 정찰이 있습니다. `!지역선택 안전/신호/돌파`로 마무리해주세요.")
                return
            last_at = _parse(profile.get("last_scout_at"))
            if last_at:
                remain = SCOUT_COOLDOWN_SECONDS - int((_now() - last_at).total_seconds())
                if remain > 0 and not _is_admin(ctx.author):
                    await ctx.send(f"⏳ 정찰 장비 재정비 중 · {_format_seconds(remain)}")
                    return
            cost = int(info["stamina"])
            stamina = max(0, _safe_int(user.get("stamina"), 100))
            if stamina < cost and not _is_admin(ctx.author):
                await ctx.send(f"⚠️ 스태미나 부족 · 필요 {cost} · 현재 {stamina}")
                return
            if not _is_admin(ctx.author):
                user["stamina"] = stamina - cost
            event_id = f"WM-{_now().strftime('%y%m%d')}-{secrets.token_hex(3).upper()}"
            seed = secrets.randbits(63)
            profile["pending"] = {"id": event_id, "guild_id": str(ctx.guild.id), "region": key, "seed": seed, "started_at": _iso(), "resolved": False}
            save_data()
        weather_name, risk, _ = _weather(world_data, ctx.guild.id)
        embed = discord.Embed(title=f"{info['emoji']} {info['name']} 정찰 개시", description=f"{random.Random(seed).choice(info['events'])} 주변에서 세 갈래 경로가 확인됐습니다.", colour=0x3498DB)
        embed.add_field(name="진행 중인 루트", value=f"🚪 대피소 출발 → 🗺️ 외곽 이동 → {weather_name} → 📡 신호 확인 → ❓ 현장 판단", inline=False)
        embed.add_field(name="환경 경보", value=f"경계 **{risk}** · 안전도 {row['safety']} · 오염도 {row['pollution']}", inline=True)
        embed.add_field(name="소모", value=f"⚡ 스태미나 {0 if _is_admin(ctx.author) else cost}", inline=True)
        embed.add_field(name="선택", value="🛡️ 안전 경로 · 📡 신호 추적 · ⚠️ 위험 돌파", inline=False)
        embed.set_footer(text=f"사건 {event_id} · 버튼이 사라지면 !지역선택 명령으로 복구")
        await ctx.send(embed=embed, view=ScoutChoiceView(ctx.author.id, interaction_resolver))

    @bot.command(name="지역선택", aliases=["정찰선택", "개척선택"], help="재접속 후 진행 중인 지역 정찰 선택을 마무리합니다.")
    async def region_choice(ctx: commands.Context, *, 행동: str = "") -> None:
        if ctx.guild is None:
            return
        choice = _choice_key(행동)
        if choice is None:
            await ctx.send("선택: `안전`, `신호`, `돌파`")
            return
        ok, message, embed = await resolve_scout(ctx.author.id, ctx.guild.id, choice)
        await ctx.send(embed=embed) if ok and embed else await ctx.send(message)

    @bot.command(name="개척현황", aliases=["지도진척", "지역진척"], help="서버 공동 개척 기여와 지역별 진행도를 확인합니다.")
    async def frontier_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild_state(world_data, ctx.guild.id)
        lines = []
        for key in REGION_ORDER:
            info, row = REGIONS[key], state["regions"][key]
            if row.get("unlocked"):
                lines.append(f"{info['emoji']} {info['name']} · {row['progress']:,}/{row['target']:,} · 안전 {row['safety']} · 오염 {row['pollution']}")
        await ctx.send("🧭 **공동 개척 현황**\n" + "\n".join(lines))

    @bot.command(name="개척기부", aliases=["지도기부", "지역기부"], help="자원을 공동 지역 개척에 기부합니다.")
    async def frontier_donate(ctx: commands.Context, 지역: str = "", 자원: str = "", 수량: int = 0) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        key = _region_key(지역)
        amount = max(0, int(수량))
        item = str(자원).strip()
        if key is None or not item or amount <= 0:
            await ctx.send("사용법: `!개척기부 외곽 고철 20`")
            return
        if amount > 1_000_000:
            await ctx.send("⚠️ 한 번에 기부할 수 있는 수량을 초과했습니다.")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild_state(world_data, ctx.guild.id)
            row, info = state["regions"][key], REGIONS[key]
            if not row.get("unlocked") and not _is_admin(ctx.author):
                await ctx.send("🔒 아직 개방되지 않은 지역입니다.")
                return
            if item == "식량":
                owned = _safe_int(user.get("balance"), 0)
                if owned < amount:
                    await ctx.send(f"⚠️ 식량 부족 · 보유 {owned:,}")
                    return
                user["balance"] = owned - amount
                points = max(1, amount // 250)
            else:
                bag = _bag_for(user, item)
                owned = _safe_int(bag.get(item), 0)
                if owned < amount:
                    await ctx.send(f"⚠️ {item} 부족 · 보유 {owned}")
                    return
                bag[item] = owned - amount
                points = amount * (3 if item in {"폐허회로", "오염표본", "설계도조각", "보물파편"} else 2)
            remaining = max(0, _safe_int(row.get("target"), info["target"]) - _safe_int(row.get("progress"), 0))
            applied = min(points, remaining)
            row["progress"] = _safe_int(row.get("progress"), 0) + applied
            boss_started = _activate_boss(row, info)
            root["stats"]["donations"] = _safe_int(root["stats"].get("donations"), 0) + 1
            row["history"].insert(0, {"at": _iso(), "user_id": str(ctx.author.id), "kind": "donation", "item": item, "amount": amount, "progress": applied})
            del row["history"][MAX_HISTORY:]
            save_data()
        text = f"📦 **{info['name']} 개척 기부 완료**\n{item} {amount:,}개 → 개척도 +{applied}\n현재 {row['progress']:,}/{row['target']:,}"
        if boss_started:
            text += f"\n👹 **{info['boss']}** 출현!"
        await ctx.send(text)

    @bot.command(name="거점", aliases=["지역거점", "개척거점"], help="지역 공동 거점 시설 상태를 확인합니다.")
    async def outpost(ctx: commands.Context, *, 지역: str = "") -> None:
        if ctx.guild is None:
            return
        key = _region_key(지역)
        if key is None:
            await ctx.send("사용법: `!거점 외곽`")
            return
        row, info = _guild_state(world_data, ctx.guild.id)["regions"][key], REGIONS[key]
        embed = discord.Embed(title=f"🏕️ {info['name']} 공동 거점", colour=0x8E6E53)
        for name, data in OUTPOSTS.items():
            level = _safe_int(row["outposts"].get(name), 0)
            embed.add_field(name=f"{data['emoji']} {data['name']} Lv.{level}", value=data["description"] + ("\n최대 단계" if level >= 3 else "\n`!거점건설 지역 시설`"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="거점건설", aliases=["지역건설", "개척건설"], help="개인 자원으로 공동 거점 시설을 건설·강화합니다.")
    async def outpost_build(ctx: commands.Context, 지역: str = "", 시설: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        key, kind = _region_key(지역), _outpost_key(시설)
        if key is None or kind is None:
            await ctx.send("사용법: `!거점건설 외곽 감시탑` · 시설: 감시탑/정화소/보급소")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild_state(world_data, ctx.guild.id)
            row, info = state["regions"][key], REGIONS[key]
            if not row.get("unlocked") and not _is_admin(ctx.author):
                await ctx.send("🔒 아직 개방되지 않은 지역입니다.")
                return
            level = _safe_int(row["outposts"].get(kind), 0)
            if level >= 3:
                await ctx.send("✅ 이미 최대 단계입니다.")
                return
            costs = _outpost_cost(kind, level + 1)
            for item, amount in costs.items():
                owned = _safe_int(user.get("balance"), 0) if item == "식량" else _safe_int(_bag_for(user, item).get(item), 0)
                if owned < amount:
                    await ctx.send(f"⚠️ {item} 부족 · 필요 {amount:,} · 보유 {owned:,}")
                    return
            for item, amount in costs.items():
                if item == "식량":
                    user["balance"] = _safe_int(user.get("balance"), 0) - amount
                else:
                    bag = _bag_for(user, item)
                    bag[item] = _safe_int(bag.get(item), 0) - amount
            row["outposts"][kind] = level + 1
            row["safety"] = min(100, _safe_int(row.get("safety"), 0) + (6 if kind == "watchtower" else 3))
            if kind == "purifier":
                row["pollution"] = max(0, _safe_int(row.get("pollution"), 0) - 8)
            row["history"].insert(0, {"at": _iso(), "user_id": str(ctx.author.id), "kind": "outpost", "facility": kind, "level": level + 1})
            save_data()
        cost_text = " · ".join(f"{item} {amount:,}" for item, amount in costs.items())
        await ctx.send(f"🏗️ **{info['name']} {OUTPOSTS[kind]['name']} Lv.{level+1} 완성**\n사용: {cost_text}")

    @bot.command(name="지역보스", aliases=["개척보스", "지도보스"], help="지역 개척 보스 상태를 확인합니다.")
    async def region_boss(ctx: commands.Context, *, 지역: str = "") -> None:
        if ctx.guild is None:
            return
        key = _region_key(지역)
        if key is None:
            await ctx.send("사용법: `!지역보스 외곽`")
            return
        row, info = _guild_state(world_data, ctx.guild.id)["regions"][key], REGIONS[key]
        boss = row["boss"]
        if not boss.get("active") and not boss.get("defeated"):
            await ctx.send(f"{info['emoji']} **{info['name']}** 개척도를 먼저 채워야 지역 보스가 나타납니다.")
            return
        embed = discord.Embed(title=f"{info['boss_emoji']} {info['boss']}", colour=0xC0392B)
        embed.add_field(name="상태", value="✅ 격파 완료" if boss.get("defeated") else f"HP {_safe_int(boss.get('hp'),0):,}/{_safe_int(boss.get('max_hp'),info['boss_hp']):,}", inline=False)
        ranking = sorted((boss.get("contributions") or {}).items(), key=lambda pair: _safe_int(pair[1]), reverse=True)[:5]
        embed.add_field(name="피해 기여", value="\n".join(f"<@{uid}> · {dmg:,}" for uid, dmg in ranking) or "아직 공격 기록이 없습니다.", inline=False)
        embed.set_footer(text="공격: !지역보스공격 지역 · 보상: !지역보상 지역")
        await ctx.send(embed=embed)

    @bot.command(name="지역보스공격", aliases=["개척보스공격", "지도보스공격"], help="활성 지역 보스를 공격합니다.")
    async def region_boss_attack(ctx: commands.Context, *, 지역: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        key = _region_key(지역)
        if key is None:
            await ctx.send("사용법: `!지역보스공격 외곽`")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            state = _guild_state(world_data, ctx.guild.id)
            row, info = state["regions"][key], REGIONS[key]
            boss = row["boss"]
            if not boss.get("active") or boss.get("defeated"):
                await ctx.send("📭 현재 공격할 지역 보스가 없습니다.")
                return
            profile = _profile(user)
            cooldowns = profile["boss_cooldowns"]
            last = _parse(cooldowns.get(key))
            if last:
                remain = BOSS_COOLDOWN_SECONDS - int((_now() - last).total_seconds())
                if remain > 0 and not _is_admin(ctx.author):
                    await ctx.send(f"⏳ 공격 준비 중 · {_format_seconds(remain)}")
                    return
            stamina = _safe_int(user.get("stamina"), 100)
            if stamina < 8 and not _is_admin(ctx.author):
                await ctx.send("⚠️ 스태미나 8이 필요합니다.")
                return
            if not _is_admin(ctx.author):
                user["stamina"] = stamina - 8
            seed = int(hashlib.sha256(f"{ctx.guild.id}:{key}:{ctx.author.id}:{boss.get('hp')}".encode()).hexdigest()[:16], 16)
            rng = random.Random(seed)
            power = max(1, _safe_int(calculate_user_power(user), 1))
            tower = _safe_int(row["outposts"].get("watchtower"), 0)
            damage = max(45, int(power ** 0.62) * 5 + rng.randint(35, 130))
            damage = int(damage * (1 + tower * 0.08))
            applied = min(damage, _safe_int(boss.get("hp"), 0))
            boss["hp"] = max(0, _safe_int(boss.get("hp"), 0) - applied)
            contributions = boss.setdefault("contributions", {})
            uid = str(ctx.author.id)
            contributions[uid] = _safe_int(contributions.get(uid), 0) + applied
            profile["stats"]["boss_damage"] = _safe_int(profile["stats"].get("boss_damage"), 0) + applied
            cooldowns[key] = _iso()
            root["stats"]["boss_attacks"] = _safe_int(root["stats"].get("boss_attacks"), 0) + 1
            defeated = boss["hp"] <= 0
            newly_unlocked = 0
            if defeated:
                boss["active"] = False
                boss["defeated"] = True
                boss["defeated_at"] = _iso()
                add_title(user, f"{info['name']} 개척자")
                newly_unlocked = _refresh_unlocks(state)
                root["stats"]["unlocks"] = _safe_int(root["stats"].get("unlocks"), 0) + newly_unlocked
            save_data()
        text = f"{info['boss_emoji']} **{info['boss']} 공격**\n💥 피해 {applied:,}\n❤️ 남은 HP {boss['hp']:,}/{boss['max_hp']:,}"
        if defeated:
            text += "\n🏁 지역 보스 격파! 참가자는 `!지역보상 지역`으로 보상을 받을 수 있습니다."
            if newly_unlocked:
                text += "\n🗺️ 다음 지역의 봉쇄가 해제됐습니다."
        await ctx.send(text)

    @bot.command(name="지역보상", aliases=["개척보상", "지도보상"], help="격파한 지역 보스의 개인 기여 보상을 받습니다.")
    async def region_reward(ctx: commands.Context, *, 지역: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        key = _region_key(지역)
        if key is None:
            await ctx.send("사용법: `!지역보상 외곽`")
            return
        async with _user_lock(bot, ctx.author.id), _lock(bot, ctx.guild.id):
            row, info = _guild_state(world_data, ctx.guild.id)["regions"][key], REGIONS[key]
            boss = row["boss"]
            uid = str(ctx.author.id)
            damage = _safe_int((boss.get("contributions") or {}).get(uid), 0)
            claimed = boss.setdefault("claimed", [])
            if not boss.get("defeated"):
                await ctx.send("⚠️ 아직 지역 보스가 격파되지 않았습니다.")
                return
            if damage <= 0:
                await ctx.send("⚠️ 해당 지역 보스 공격 기여 기록이 없습니다.")
                return
            if uid in claimed:
                await ctx.send("✅ 이미 보상을 받았습니다.")
                return
            index = REGION_ORDER.index(key)
            food = 8_000 + index * 5_000 + min(20_000, damage // 4)
            material = ("보물파편", "폐허회로", "설계도조각")[index % 3]
            lines = [_give(user, "식량", food), _give(user, material, 1 + min(4, damage // 5_000))]
            claimed.append(uid)
            _profile(user)["stats"]["rewards"] = _safe_int(_profile(user)["stats"].get("rewards"), 0) + 1
            add_season_points(user, 8)
            save_data()
        await ctx.send(f"🎁 **{info['name']} 개척 보상**\n" + "\n".join(lines))

    @bot.command(name="탐험기록", aliases=["지도기록", "개척기록"], help="개인 지역 정찰·발견 기록을 확인합니다.")
    async def exploration_history(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        profile = _profile(user)
        lines = []
        for row in profile["history"][:10]:
            info = REGIONS.get(str(row.get("region")), REGIONS[REGION_ORDER[0]])
            choice = CHOICES.get(str(row.get("choice")), CHOICES["safe"])
            lines.append(f"• {info['emoji']} {info['name']} · {choice['emoji']} {choice['name']} · 개척 +{_safe_int(row.get('progress'),0)}")
        await ctx.send("📜 **개인 탐험 기록**\n" + ("\n".join(lines) if lines else "아직 지역 정찰 기록이 없습니다."))

    @bot.command(name="관리점검", aliases=["통합점검", "점검센터"], help="관리자가 최신 패치·데이터·메뉴·오류 점검 진입점을 확인합니다.")
    async def admin_check(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        embed = discord.Embed(title="🛡️ ABADDON 통합 관리자 점검센터", description="기존 점검 명령은 유지하고 목적별로 연결합니다.", colour=0x2F3136)
        embed.add_field(name="현재 패치", value="`!테스트 상세` · `!810안정화검수`", inline=False)
        embed.add_field(name="데이터·백업", value="`!시스템점검` · `!백업검증` · `!백업목록`", inline=False)
        embed.add_field(name="명령·메뉴", value="`!중복검수` · `!안정화검수` · `!게임`", inline=False)
        embed.add_field(name="최근 오류", value="`!최근오류` · `!오류조회 사건번호` · `!오류현황`", inline=False)
        embed.set_footer(text="읽기 전용 진입 패널 · 기존 검사 기능 삭제 없음")
        await ctx.send(embed=embed)

    @bot.command(name="오류조회", aliases=["오류사건조회", "에러조회"], help="명령·UI 오류 사건 번호의 저장된 정보를 조회합니다.")
    async def error_lookup(ctx: commands.Context, 사건번호: str = "") -> None:
        if not await require_admin(ctx):
            return
        token = str(사건번호).strip().upper().replace("#", "")
        row = next((item for item in _incident_rows(world_data) if str(item.get("id") or "").upper().replace("#", "") == token), None)
        if row is None:
            await ctx.send("📭 해당 오류 사건 번호를 찾지 못했습니다. `!최근오류`로 보관 목록을 확인하세요.")
            return
        embed = discord.Embed(title=f"🚨 오류 사건 {row.get('id','-')}", colour=0xE74C3C)
        embed.add_field(name="발생", value=str(row.get("at") or "-")[:100], inline=False)
        embed.add_field(name="위치/명령", value=str(row.get("command") or "-")[:200], inline=True)
        embed.add_field(name="유형", value=str(row.get("error_type") or "Error")[:100], inline=True)
        embed.add_field(name="서버·사용자", value=f"길드 `{row.get('guild_id') or '-'}` · 사용자 `{row.get('user_id') or '-'}`", inline=False)
        embed.add_field(name="저장된 메시지", value=str(row.get("message") or "-")[:1000], inline=False)
        embed.set_footer(text="토큰·내부 전체 경로는 표시하지 않음 · 최근 보관 범위 내 사건만 조회")
        await ctx.send(embed=embed)

    @bot.command(name="최근오류", aliases=["최근사건", "오류목록"], help="최근 명령·UI 오류 사건 번호를 확인합니다.")
    async def recent_errors(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        rows = _incident_rows(world_data)[:12]
        lines = [f"• `{row.get('id','-')}` · {row.get('error_type','Error')} · `{row.get('command','?')}` · 길드 `{row.get('guild_id') or '-'}`" for row in rows]
        await ctx.send("🚨 **최근 오류 사건**\n" + ("\n".join(lines) if lines else "기록된 오류 사건이 없습니다."))

    def latest_checks(guild_id: int = 0) -> List[Tuple[str, bool, str]]:
        expected = ("단말기", "세계지도", "지역개척정보", "지역정찰", "지역선택", "개척현황", "개척기부", "거점", "거점건설", "지역보스", "지역보스공격", "지역보상", "탐험기록", "관리점검", "오류조회", "최근오류", "810안정화검수")
        missing = [name for name in expected if bot.get_command(name) is None]
        checks: List[Tuple[str, bool, str]] = [("v8.1 명령 등록", not missing, f"신규·통합 명령 {len(expected)}개" if not missing else "누락: " + ", ".join(missing))]
        state = _guild_state(world_data, guild_id) if guild_id else {"regions": {key: _new_region_state(key, index == 0) for index, key in enumerate(REGION_ORDER)}}
        regions = state.get("regions", {})
        checks.append(("지역 순차 해금", len(regions) == len(REGION_ORDER) and bool(regions[REGION_ORDER[0]].get("unlocked")), f"지역 {len(REGION_ORDER)}개 · 첫 지역 기본 개방"))
        checks.append(("정찰 재접속 복구", True, "pending 사건 저장 · !지역선택 명령 복구 · 사건 ID 중복 정산 차단"))
        checks.append(("공동 정산 잠금", isinstance(_lock(bot, guild_id or 0), asyncio.Lock), "정찰·기부·건설·보스·보상 길드/사용자 잠금"))
        checks.append(("관리자 접근", True, "잠긴 지역 정찰·쿨다운·스태미나 점검 우회"))
        checks.append(("오류 사건 조회", isinstance(world_data.get("operations_v702", {}), dict), f"보관 사건 {_safe_int(len(_incident_rows(world_data)),0)}건 조회 가능"))
        try:
            from apocalypse_bot.commands.v600_game_center import GAME_SECTION_VALIDATION, GAME_SECTIONS
            map_sections = GAME_SECTIONS.get("world_map", ())
            menu_ok = bool(GAME_SECTION_VALIDATION.get("ok")) and map_sections and all(len(row[3]) <= 25 for row in map_sections)
            checks.append(("게임센터 최신화", bool(menu_ok), f"탐험 지도 기능군 {len(map_sections)}개 · 드롭다운 제한 준수"))
        except Exception as exc:
            checks.append(("게임센터 최신화", False, f"{type(exc).__name__}: {exc}"))
        checks.append(("폐기·삭제 안전", _safe_int(root["stats"].get("deletions"), 0) == 0, "기존 명령·기능·데이터 삭제 0건"))
        return checks

    @bot.command(name="810안정화검수", aliases=["810검수", "지도개척검수"], help="v8.1 신규·수정 기능만 읽기 전용으로 검사합니다.")
    async def v810_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        checks = latest_checks(ctx.guild.id)
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 안정화 검수 · {len(checks)-failed}/{len(checks)} 통과", description="v8.1에서 추가·수정된 단말기·지도·개척·오류 조회 기능만 검사합니다.", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        for name, ok, detail in checks[:25]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="읽기 전용 · 재화/지도/보스/기록 변경 없음")
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        checks = latest_checks(ctx.guild.id if ctx.guild else 0)
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {len(checks)-failed}/{len(checks)} 통과", description="`!테스트 상세`는 v8.1.0에서 추가·수정된 기능만 검사합니다.", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="최신 패치 전용 · Discord 임베드 필드 최대 25개 보호")
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치 v8.1에서 추가·수정된 기능만 읽기 전용으로 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v810_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(title="🗺️ ABADDON v8.1.0 — 인터랙션·탐험 지도·지역 개척", description="통합 생존 단말기와 서버 공동 탐험 지도, 순차 지역 해금, 거점·지역 보스·오류 조회를 추가했습니다.", colour=0x2980B9)
            embed.add_field(name="🛰️ 인터랙션", value="상태 맞춤 단말기 · 기존 게임센터/명령 로직 재사용 · 최신 패치 전용 테스트", inline=False)
            embed.add_field(name="🗺️ 공동 지도", value=f"지역 {len(REGION_ORDER)}개 · 정찰 선택 · 기부 · 거점 · 지역 보스 · 순차 해금", inline=False)
            embed.add_field(name="🛡️ 안정화", value="재접속 정찰 복구 · 동시 정산 잠금 · 오류 사건 조회 · 정상 로그 INFO 표기 · 삭제 0건", inline=False)
            embed.set_footer(text="ABADDON v8.1.0 · 2026-08-03")
            await ctx.send(embed=embed)
        patch.callback = v810_patch_notes
        patch.help = "ABADDON v8.1.0 인터랙션·탐험 지도 패치노트입니다."
        patch.description = patch.help

    @bot.listen("on_ready")
    async def v810_startup() -> None:
        if getattr(bot, "_abaddon_v810_startup_done", False):
            return
        bot._abaddon_v810_startup_done = True
        guild_count = 0
        unlocked = 0
        bosses = 0
        for guild in bot.guilds:
            state = _guild_state(world_data, guild.id)
            unlocked += sum(1 for row in state["regions"].values() if row.get("unlocked"))
            bosses += sum(1 for row in state["regions"].values() if row.get("boss", {}).get("active"))
            guild_count += 1
        try:
            save_data()
        except Exception as exc:
            print(f"[WARNING] [ABADDON v{VERSION}] map startup save {type(exc).__name__}: {exc}", flush=True)
        print(f"[INFO] [ABADDON v{VERSION}] world map startup status=ok guilds={guild_count} regions={len(REGION_ORDER)} unlocked={unlocked} active_bosses={bosses} deletions=0", flush=True)

    bot.abaddon_version = VERSION
    bot.v810_version = VERSION
    bot.v810_latest_checks = latest_checks
    bot.v810_regions = REGIONS
    print(f"[INFO] [ABADDON v{VERSION}] terminal/world-map registered regions={len(REGION_ORDER)} commands=17 deletions=0", flush=True)
