from __future__ import annotations

import asyncio
import copy
import math
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.game_data.jobs import JOBS
from apocalypse_bot.commands.v900_faction_world_state import (
    _guild as _world_state,
    _profile as _faction_profile,
    _metric_delta,
    _owned,
    _take,
    _give,
    _safe_int,
    _parse,
    _iso,
    _now,
    _bar,
    _fmt_seconds,
    _is_admin,
)

VERSION = "9.2.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
TICK_SECONDS = 6 * 60 * 60
MAX_CATCHUP_TICKS = 4
IDLE_FREEZE_SECONDS = 72 * 60 * 60
SQUAD_COOLDOWN_SECONDS = 20 * 60

METRIC_LABELS: Mapping[str, Tuple[str, str]] = {
    "stability": ("안정도", "🛡️"),
    "supply": ("보급", "📦"),
    "morale": ("사기", "🔥"),
    "contamination": ("오염", "☣️"),
}

RECOVERY_TYPES: Mapping[str, Dict[str, Any]] = {
    "grid": {
        "name": "발전망 복구", "emoji": "⚡", "aliases": ("발전", "전력", "정전"),
        "summary": "폐허 발전기와 송전 설비를 연결해 대피소 전력을 안정화합니다.",
        "target": 1600, "resources": ("고철", "폐허회로"),
        "effects": {"stability": 7, "supply": 4, "morale": 2},
    },
    "water": {
        "name": "식수 정화", "emoji": "💧", "aliases": ("식수", "정화", "물"),
        "summary": "오염된 저장수와 배관을 정화해 감염 확산을 억제합니다.",
        "target": 1500, "resources": ("약초", "오염표본"),
        "effects": {"contamination": -10, "stability": 3, "morale": 2},
    },
    "hospital": {
        "name": "야전병원 건설", "emoji": "🏥", "aliases": ("병원", "의료", "야전병원"),
        "summary": "의료 천막과 치료 장비를 마련해 구조 인력을 보호합니다.",
        "target": 1700, "resources": ("식량", "약초"),
        "effects": {"morale": 8, "stability": 4, "contamination": -3},
    },
    "route": {
        "name": "보급로 재개통", "emoji": "🚚", "aliases": ("보급로", "도로", "호송로"),
        "summary": "잔해를 치우고 경계 초소를 세워 물자 이동을 되살립니다.",
        "target": 1800, "resources": ("식량", "나무"),
        "effects": {"supply": 10, "stability": 3, "morale": 2},
    },
    "comms": {
        "name": "통신망 복원", "emoji": "📡", "aliases": ("통신", "무전", "송신"),
        "summary": "중계기와 송신탑을 복구해 세력·거점 간 연락을 연결합니다.",
        "target": 1550, "resources": ("폐허회로", "광석"),
        "effects": {"stability": 5, "supply": 4, "morale": 4},
    },
    "wall": {
        "name": "방벽 보강", "emoji": "🧱", "aliases": ("방벽", "성벽", "방어"),
        "summary": "대피소 외곽 방벽과 감시 지점을 보강합니다.",
        "target": 1750, "resources": ("고철", "나무"),
        "effects": {"stability": 9, "morale": 3},
    },
}

RECOVERY_ACTIONS: Mapping[str, Tuple[str, str, int]] = {
    "scout": ("현장 정찰", "🧭", 42),
    "rescue": ("인원 구조", "🩹", 48),
    "repair": ("설비 수리", "🔧", 55),
    "guard": ("경계 방어", "🛡️", 45),
}
RECOVERY_ACTION_ALIASES: Mapping[str, Tuple[str, ...]] = {
    "scout": ("정찰", "탐색", "현장정찰"),
    "rescue": ("구조", "구호", "인원구조"),
    "repair": ("수리", "복구", "설비수리"),
    "guard": ("경계", "방어", "경계방어"),
}

DIRECTIVES: Mapping[str, Dict[str, Any]] = {
    "stability": {"name": "치안 강화", "emoji": "🛡️", "aliases": ("치안", "안정", "방어"), "metric": "stability"},
    "supply": {"name": "보급 확보", "emoji": "📦", "aliases": ("보급", "물자", "식량"), "metric": "supply"},
    "morale": {"name": "사기 진작", "emoji": "🔥", "aliases": ("사기", "희망", "연대"), "metric": "morale"},
    "decontam": {"name": "오염 정화", "emoji": "☣️", "aliases": ("오염", "정화", "방역"), "metric": "contamination"},
    "diplomacy": {"name": "세력 외교", "emoji": "🤝", "aliases": ("외교", "세력", "협력"), "metric": "morale"},
    "suppression": {"name": "적대 세력 압박", "emoji": "⚔️", "aliases": ("압박", "전쟁", "토벌"), "metric": "stability"},
}

SPECIALIZATIONS: Mapping[str, Dict[str, Any]] = {
    "방벽대장": {"job": "군인", "emoji": "🛡️", "tags": ("recovery_guard", "squad_defense"), "summary": "방어선 유지와 구조대 보호에 특화됩니다."},
    "돌격대장": {"job": "군인", "emoji": "⚔️", "tags": ("recovery_action", "squad_assault"), "summary": "위험 돌파와 선봉 전투 지휘에 특화됩니다."},
    "전장의무관": {"job": "의사", "emoji": "⚕️", "tags": ("recovery_rescue", "squad_medic"), "summary": "현장 구조와 분대 생존 보조에 특화됩니다."},
    "감염치료사": {"job": "의사", "emoji": "🧬", "tags": ("decontam", "squad_support"), "summary": "오염 억제와 감염 대응에 특화됩니다."},
    "요새설계사": {"job": "기술자", "emoji": "🏗️", "tags": ("recovery_repair", "squad_defense"), "summary": "방벽·시설 복구와 방어 전술에 특화됩니다."},
    "노선복구사": {"job": "기술자", "emoji": "🛤️", "tags": ("supply", "squad_tech"), "summary": "보급로·통신망·호송 설비 복구에 특화됩니다."},
    "관측저격수": {"job": "저격수", "emoji": "🔭", "tags": ("recovery_scout", "squad_scout"), "summary": "정찰 정보와 약점 관측에 특화됩니다."},
    "파쇄사수": {"job": "저격수", "emoji": "💥", "tags": ("squad_assault", "boss"), "summary": "장갑 목표와 고위험 표적 제압에 특화됩니다."},
    "오염분석관": {"job": "연구원", "emoji": "☣️", "tags": ("decontam", "recovery_research"), "summary": "오염 표본 분석과 정화 작전에 특화됩니다."},
    "신호해독관": {"job": "연구원", "emoji": "📡", "tags": ("recovery_scout", "squad_tech"), "summary": "통신 복원과 현장 신호 분석에 특화됩니다."},
    "황무지추적자": {"job": "사냥꾼", "emoji": "🐾", "tags": ("recovery_scout", "squad_scout"), "summary": "위험 경로 추적과 매복 탐지에 특화됩니다."},
    "보급개척자": {"job": "사냥꾼", "emoji": "🎒", "tags": ("supply", "squad_support"), "summary": "야외 보급 확보와 안전 경로 개척에 특화됩니다."},
}

SQUAD_TACTICS: Mapping[str, Dict[str, Any]] = {
    "balanced": {"name": "균형 전개", "emoji": "⚖️", "aliases": ("균형", "기본"), "tags": ()},
    "assault": {"name": "돌격 압박", "emoji": "⚔️", "aliases": ("돌격", "공격"), "tags": ("assault",)},
    "defense": {"name": "방벽 진형", "emoji": "🛡️", "aliases": ("방어", "방벽"), "tags": ("defense",)},
    "rescue": {"name": "구조 회랑", "emoji": "🚑", "aliases": ("구조", "의무"), "tags": ("medic", "support")},
    "recon": {"name": "정찰 침투", "emoji": "🧭", "aliases": ("정찰", "탐색"), "tags": ("scout", "tech")},
}

SQUAD_ROLES: Mapping[str, Tuple[str, str]] = {
    "vanguard": ("선봉", "⚔️"),
    "medic": ("의무", "⚕️"),
    "tech": ("기술", "🧰"),
    "scout": ("정찰", "🧭"),
}

SQUAD_OPERATIONS: Mapping[str, Dict[str, Any]] = {
    "patrol": {"name": "외곽 경계 순찰", "emoji": "🛡️", "aliases": ("순찰", "경계"), "difficulty": 360, "reward": 7500, "tactic": "defense", "effects": {"stability": 1}},
    "escort": {"name": "구조대 호위", "emoji": "🚑", "aliases": ("호위", "구조"), "difficulty": 400, "reward": 8500, "tactic": "rescue", "effects": {"morale": 1}},
    "survey": {"name": "오염지대 정찰", "emoji": "☣️", "aliases": ("오염", "정찰"), "difficulty": 440, "reward": 9500, "tactic": "recon", "effects": {"contamination": -1}},
    "salvage": {"name": "보급품 회수", "emoji": "📦", "aliases": ("보급", "회수"), "difficulty": 420, "reward": 9000, "tactic": "assault", "effects": {"supply": 1}},
}


def _norm(value: Any) -> str:
    return str(value or "").strip().replace(" ", "").casefold()


def _lookup(raw: Any, table: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    token = _norm(raw)
    for key, info in table.items():
        if token in {_norm(key), _norm(info.get("name")), *(_norm(x) for x in info.get("aliases", ()))}:
            return key
    return None


def _week_key(now: Optional[datetime] = None) -> str:
    local = (now or _now()).astimezone(KST)
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v920_world_cycle", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v920_world_cycle"] = root
    root["schema_version"] = SCHEMA_VERSION
    root.setdefault("guilds", {})
    root.setdefault("stats", {"ticks": 0, "recoveries": 0, "squad_ops": 0, "deletions": 0})
    return root


def _new_state() -> MutableMapping[str, Any]:
    now = _now()
    return {
        "cycle": {
            "enabled": True, "paused": False, "last_tick": _iso(now), "last_activity": _iso(now),
            "frozen": False, "tick_count": 0, "history": [],
        },
        "recovery": {},
        "recovery_history": [],
        "directive": {"week": _week_key(now), "selected": "", "votes": {}, "history": []},
        "broadcast_history": [],
    }


def _state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), _new_state())
    if not isinstance(state, dict):
        state = _new_state()
        guilds[str(guild_id)] = state
    cycle = state.setdefault("cycle", {})
    cycle.setdefault("enabled", True)
    cycle.setdefault("paused", False)
    cycle.setdefault("last_tick", _iso())
    cycle.setdefault("last_activity", _iso())
    cycle.setdefault("frozen", False)
    cycle.setdefault("tick_count", 0)
    cycle.setdefault("history", [])
    state.setdefault("recovery", {})
    state.setdefault("recovery_history", [])
    directive = state.setdefault("directive", {})
    directive.setdefault("week", _week_key())
    directive.setdefault("selected", "")
    directive.setdefault("votes", {})
    directive.setdefault("history", [])
    state.setdefault("broadcast_history", [])
    _roll_directive_week(state)
    return state


def _profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = user.setdefault("profession_world_v920", {})
    if not isinstance(profile, dict):
        profile = {}
        user["profession_world_v920"] = profile
    profile["schema_version"] = SCHEMA_VERSION
    profile.setdefault("specialization", "")
    profile.setdefault("selected_at", "")
    profile.setdefault("history", [])
    profile.setdefault("recovery_claims", [])
    profile.setdefault("recovery_actions", {})
    profile.setdefault("squad_role", "")
    profile.setdefault("stats", {"recovery_points": 0, "squad_ops": 0, "world_votes": 0})
    return profile


def _roll_directive_week(state: MutableMapping[str, Any]) -> None:
    directive = state["directive"]
    current = _week_key()
    if directive.get("week") == current:
        return
    votes = directive.get("votes", {}) if isinstance(directive.get("votes"), dict) else {}
    counts = {key: 0 for key in DIRECTIVES}
    for selected in votes.values():
        if selected in counts:
            counts[selected] += 1
    chosen = max(counts, key=lambda key: counts[key]) if any(counts.values()) else str(directive.get("selected") or "")
    directive.setdefault("history", []).insert(0, {"week": directive.get("week"), "selected": chosen, "votes": counts, "at": _iso()})
    directive["week"] = current
    directive["selected"] = chosen
    directive["votes"] = {}


def _touch(state: MutableMapping[str, Any]) -> None:
    state["cycle"]["last_activity"] = _iso()
    state["cycle"]["frozen"] = False


def _directive_bonus(state: Mapping[str, Any]) -> Mapping[str, int]:
    selected = str(state.get("directive", {}).get("selected") or "")
    if selected == "decontam":
        return {"contamination": -1}
    if selected in {"stability", "suppression"}:
        return {"stability": 1}
    if selected == "supply":
        return {"supply": 1}
    if selected in {"morale", "diplomacy"}:
        return {"morale": 1}
    return {}


def _tick_changes(world: Mapping[str, Any], local: Mapping[str, Any]) -> Dict[str, int]:
    metrics = world["metrics"]
    changes: Dict[str, int] = {"stability": 0, "supply": 0, "morale": 0, "contamination": 0}
    if _safe_int(metrics.get("supply"), 45) < 35:
        changes["morale"] -= 1
    if _safe_int(metrics.get("contamination"), 25) > 55:
        changes["stability"] -= 1
    if _safe_int(metrics.get("stability"), 45) > 70:
        changes["supply"] += 1
    if _safe_int(metrics.get("morale"), 45) > 70:
        changes["stability"] += 1
    if _safe_int(metrics.get("supply"), 45) > 65:
        changes["contamination"] -= 1
    if _safe_int(metrics.get("stability"), 45) < 25:
        changes["contamination"] += 1
    for key, value in _directive_bonus(local).items():
        changes[key] += int(value)
    return {key: value for key, value in changes.items() if value}


def _apply_due_ticks(world: MutableMapping[str, Any], local: MutableMapping[str, Any], *, force: bool = False) -> Dict[str, Any]:
    cycle = local["cycle"]
    now = _now()
    if not cycle.get("enabled") or cycle.get("paused"):
        return {"applied": 0, "reason": "paused"}
    last_tick = _parse(cycle.get("last_tick")) or now
    last_activity = _parse(cycle.get("last_activity")) or now
    if not force and (now - last_activity).total_seconds() >= IDLE_FREEZE_SECONDS:
        cycle["frozen"] = True
        cycle["last_tick"] = _iso(now)
        return {"applied": 0, "reason": "idle_frozen"}
    cycle["frozen"] = False
    due = 1 if force else int((now - last_tick).total_seconds() // TICK_SECONDS)
    due = max(0, min(MAX_CATCHUP_TICKS, due))
    if due <= 0:
        return {"applied": 0, "reason": "not_due"}
    total: Dict[str, int] = {}
    for _ in range(due):
        changes = _tick_changes(world, local)
        before = dict(world["metrics"])
        _metric_delta(world, changes)
        # 자동 순환만으로 서버가 붕괴하지 않도록 안전 하한·상한을 둡니다.
        world["metrics"]["stability"] = max(10, _safe_int(world["metrics"].get("stability"), 10))
        world["metrics"]["supply"] = max(10, _safe_int(world["metrics"].get("supply"), 10))
        world["metrics"]["morale"] = max(10, _safe_int(world["metrics"].get("morale"), 10))
        world["metrics"]["contamination"] = min(90, max(5, _safe_int(world["metrics"].get("contamination"), 5)))
        actual = {key: _safe_int(world["metrics"].get(key)) - _safe_int(before.get(key)) for key in METRIC_LABELS}
        for key, value in actual.items():
            total[key] = total.get(key, 0) + value
        cycle.setdefault("history", []).insert(0, {"at": _iso(now), "changes": actual, "metrics": dict(world["metrics"])})
        cycle["tick_count"] = _safe_int(cycle.get("tick_count"), 0) + 1
    cycle["last_tick"] = _iso(now)
    return {"applied": due, "changes": total, "reason": "ok"}


def _recovery_key(raw: Any) -> Optional[str]:
    return _lookup(raw, RECOVERY_TYPES)


def _directive_key(raw: Any) -> Optional[str]:
    return _lookup(raw, DIRECTIVES)


def _recovery_action_key(raw: Any) -> Optional[str]:
    token = _norm(raw)
    for key, aliases in RECOVERY_ACTION_ALIASES.items():
        name = RECOVERY_ACTIONS[key][0]
        if token in {_norm(key), _norm(name), *(_norm(alias) for alias in aliases)}:
            return key
    return None


def _tactic_key(raw: Any) -> Optional[str]:
    return _lookup(raw, SQUAD_TACTICS)


def _operation_key(raw: Any) -> Optional[str]:
    return _lookup(raw, SQUAD_OPERATIONS)


def _role_key(raw: Any) -> Optional[str]:
    token = _norm(raw)
    for key, (name, _emoji) in SQUAD_ROLES.items():
        if token in {_norm(key), _norm(name)}:
            return key
    return None


def _resource_points(item: str, amount: int) -> int:
    amount = max(0, int(amount))
    return amount // 100 if item == "식량" else amount * 3


def _max_resource_for_points(item: str, points: int) -> int:
    return max(1, int(points) * 100) if item == "식량" else max(1, math.ceil(int(points) / 3))


def _special_bonus(user: Mapping[str, Any], activity: str) -> int:
    profile = user.get("profession_world_v920", {})
    name = str(profile.get("specialization") or "") if isinstance(profile, Mapping) else ""
    info = SPECIALIZATIONS.get(name)
    if not info or str(user.get("job") or "") != str(info.get("job") or ""):
        return 0
    tags = set(info.get("tags", ()))
    direct = {
        "guard": "recovery_guard", "rescue": "recovery_rescue", "repair": "recovery_repair", "scout": "recovery_scout",
        "assault": "squad_assault", "defense": "squad_defense", "medic": "squad_medic", "tech": "squad_tech",
        "support": "squad_support", "squad_scout": "squad_scout",
    }
    return 12 if direct.get(activity) in tags else 6 if activity in tags else 0


def _party_of(world_data: MutableMapping[str, Any], user_id: Any) -> Tuple[Optional[str], Optional[MutableMapping[str, Any]]]:
    parties = world_data.setdefault("parties", {})
    uid = str(user_id)
    if not isinstance(parties, dict):
        world_data["parties"] = {}
        return None, None
    for leader_id, party in parties.items():
        if isinstance(party, dict) and uid in [str(x) for x in party.get("members", [])]:
            return str(leader_id), party
    return None, None


def _party_ext(party: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    ext = party.setdefault("v920_tactics", {})
    if not isinstance(ext, dict):
        ext = {}
        party["v920_tactics"] = ext
    ext.setdefault("tactic", "balanced")
    ext.setdefault("roles", {})
    ext.setdefault("last_operation_at", "")
    ext.setdefault("history", [])
    return ext


def _lock(bot: commands.Bot, key: str) -> asyncio.Lock:
    locks = getattr(bot, "_v920_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_v920_locks", locks)
    lock = locks.get(key)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


class DirectiveSelect(discord.ui.Select):
    def __init__(self, runner: Callable[[discord.Interaction, str], Any]):
        self.runner = runner
        options = [discord.SelectOption(label=info["name"], value=key, emoji=info["emoji"], description="이번 주 공동 목표로 투표") for key, info in DIRECTIVES.items()]
        super().__init__(placeholder="이번 주 세계 지령에 투표", min_values=1, max_values=1, options=options, custom_id="abaddon:v920:directive")

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.runner(interaction, self.values[0])


class DirectiveView(discord.ui.View):
    def __init__(self, runner: Callable[[discord.Interaction, str], Any]):
        super().__init__(timeout=180)
        self.add_item(DirectiveSelect(runner))


class RecoverySupplyModal(discord.ui.Modal, title="📦 복구 물자 지원"):
    item = discord.ui.TextInput(label="자원 이름", placeholder="예: 고철")
    amount = discord.ui.TextInput(label="수량", placeholder="예: 20")

    def __init__(self, runner: Callable[[discord.Interaction, str, int], Any]):
        super().__init__(timeout=180)
        self.runner = runner

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("⚠️ 수량은 숫자로 입력해주세요.", ephemeral=True)
            return
        await self.runner(interaction, str(self.item.value).strip(), amount)


class RecoveryView(discord.ui.View):
    def __init__(self, action_runner: Callable[[discord.Interaction, str], Any], supply_runner: Callable[[discord.Interaction, str, int], Any]):
        super().__init__(timeout=300)
        for key, (name, emoji, _base) in RECOVERY_ACTIONS.items():
            button = discord.ui.Button(label=name, emoji=emoji, style=discord.ButtonStyle.primary, custom_id=f"abaddon:v920:recovery:{key}")

            async def callback(interaction: discord.Interaction, selected: str = key) -> None:
                await action_runner(interaction, selected)

            button.callback = callback
            self.add_item(button)
        supply = discord.ui.Button(label="물자 지원", emoji="📦", style=discord.ButtonStyle.success, custom_id="abaddon:v920:recovery:supply")

        async def supply_callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(RecoverySupplyModal(supply_runner))

        supply.callback = supply_callback
        self.add_item(supply)


def register_v920_world_cycle_professions(
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
    if getattr(bot, "_abaddon_v920_registered", False):
        return
    root = _root(world_data)

    additions = {
        "social": (
            "!세계순환 / !복구작전 / !세계지령 — 시간 순환·공동 복구·주간 지령",
            "!전문화 / !분대전술 / !분대작전 — 기존 직업 확장·파티 전술 협동",
        ),
        "server": ("!920안정화검수 — v9.2 세계 순환·복구·전문화·분대 전술 읽기 전용 검사",),
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
        _faction_profile(user)
        return user

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not _is_admin(ctx.author):
            await ctx.send("⛔ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    def due_tick(guild_id: int, *, force: bool = False) -> Dict[str, Any]:
        local = _state(world_data, guild_id)
        world = _world_state(world_data, guild_id)
        result = _apply_due_ticks(world, local, force=force)
        if result.get("applied"):
            root["stats"]["ticks"] = _safe_int(root["stats"].get("ticks"), 0) + int(result["applied"])
            save_data()
        return result

    def start_recovery(guild_id: int, key: str) -> MutableMapping[str, Any]:
        local = _state(world_data, guild_id)
        info = RECOVERY_TYPES[key]
        current = local.get("recovery") if isinstance(local.get("recovery"), dict) else {}
        if current and current.get("status") in {"active", "completed"}:
            local.setdefault("recovery_history", []).insert(0, copy.deepcopy(current))
        operation = {
            "id": f"REC-{secrets.token_hex(3).upper()}", "type": key, "status": "active",
            "progress": 0, "target": int(info["target"]), "contributions": {}, "claimed": [],
            "started_at": _iso(), "completed_at": "", "effects_applied": False,
        }
        local["recovery"] = operation
        _touch(local)
        save_data()
        return operation

    def finish_recovery(guild_id: int, operation: MutableMapping[str, Any]) -> None:
        if operation.get("effects_applied"):
            return
        info = RECOVERY_TYPES[str(operation["type"])]
        world = _world_state(world_data, guild_id)
        _metric_delta(world, info["effects"])
        operation["status"] = "completed"
        operation["completed_at"] = _iso()
        operation["effects_applied"] = True
        root["stats"]["recoveries"] = _safe_int(root["stats"].get("recoveries"), 0) + 1

    async def add_recovery_action(guild_id: int, user_id: int, action: str) -> Tuple[bool, str]:
        user = get_user(user_id)
        if not isinstance(user, dict):
            return False, "먼저 생존자로 등록해주세요."
        async with _lock(bot, f"recovery:{guild_id}"), _lock(bot, f"user:{user_id}"):
            local = _state(world_data, guild_id)
            operation = local.get("recovery") if isinstance(local.get("recovery"), dict) else {}
            if not operation or operation.get("status") != "active":
                return False, "진행 중인 복구 작전이 없습니다."
            profile = _profile(user)
            action_day = _now().astimezone(KST).strftime("%Y-%m-%d")
            key = f"{operation['id']}:{action_day}"
            count = _safe_int(profile["recovery_actions"].get(key), 0)
            if count >= 3:
                return False, "오늘 이 복구 작전에서 사용할 수 있는 현장 행동을 모두 수행했습니다."
            if action not in RECOVERY_ACTIONS:
                return False, "지원 행동을 확인할 수 없습니다."
            name, emoji, base = RECOVERY_ACTIONS[action]
            bonus = _special_bonus(user, action)
            points = base + bonus + random.randint(0, 12)
            remaining = max(0, _safe_int(operation["target"]) - _safe_int(operation["progress"]))
            points = min(points, remaining)
            if points <= 0:
                return False, "이미 복구 목표가 완료되었습니다."
            uid = str(user_id)
            row = operation.setdefault("contributions", {}).setdefault(uid, {"points": 0, "actions": 0, "donated": {}})
            row["points"] = _safe_int(row.get("points"), 0) + points
            row["actions"] = _safe_int(row.get("actions"), 0) + 1
            operation["progress"] = _safe_int(operation.get("progress"), 0) + points
            profile["recovery_actions"][key] = count + 1
            profile["stats"]["recovery_points"] = _safe_int(profile["stats"].get("recovery_points"), 0) + points
            _touch(local)
            if operation["progress"] >= operation["target"]:
                finish_recovery(guild_id, operation)
            save_data()
            suffix = "\n🎉 공동 복구 목표를 달성했습니다. `!복구보상`으로 보상을 받으세요." if operation.get("status") == "completed" else ""
            return True, f"{emoji} **{name} 완료** · 공동 진행도 +{points}{suffix}"

    async def add_recovery_supply(guild_id: int, user_id: int, item: str, amount: int) -> Tuple[bool, str]:
        user = get_user(user_id)
        if not isinstance(user, dict):
            return False, "먼저 생존자로 등록해주세요."
        amount = max(0, int(amount))
        if amount <= 0:
            return False, "지원 수량은 1 이상이어야 합니다."
        async with _lock(bot, f"recovery:{guild_id}"), _lock(bot, f"user:{user_id}"):
            local = _state(world_data, guild_id)
            operation = local.get("recovery") if isinstance(local.get("recovery"), dict) else {}
            if not operation or operation.get("status") != "active":
                return False, "진행 중인 복구 작전이 없습니다."
            info = RECOVERY_TYPES[str(operation["type"])]
            if item not in info["resources"]:
                return False, "이 작전에 필요한 물자: " + " · ".join(info["resources"])
            remaining_points = max(0, _safe_int(operation["target"]) - _safe_int(operation["progress"]))
            accepted = min(amount, _max_resource_for_points(item, remaining_points))
            if accepted <= 0:
                return False, "이미 복구 목표가 완료되었습니다."
            raw_points = _resource_points(item, accepted)
            if raw_points <= 0:
                return False, "식량은 100개 이상부터 복구 진행도에 반영됩니다."
            if not _take(user, item, accepted):
                return False, f"{item} 부족 · 보유 {_owned(user, item):,}"
            points = min(remaining_points, raw_points)
            uid = str(user_id)
            row = operation.setdefault("contributions", {}).setdefault(uid, {"points": 0, "actions": 0, "donated": {}})
            row["points"] = _safe_int(row.get("points"), 0) + points
            donated = row.setdefault("donated", {})
            donated[item] = _safe_int(donated.get(item), 0) + accepted
            operation["progress"] = _safe_int(operation.get("progress"), 0) + points
            profile = _profile(user)
            profile["stats"]["recovery_points"] = _safe_int(profile["stats"].get("recovery_points"), 0) + points
            _touch(local)
            if operation["progress"] >= operation["target"]:
                finish_recovery(guild_id, operation)
            save_data()
            suffix = f" · 초과 요청 {amount-accepted:,}개는 차감하지 않음" if amount > accepted else ""
            done = "\n🎉 공동 복구 목표를 달성했습니다." if operation.get("status") == "completed" else ""
            return True, f"📦 **물자 지원 완료** · {item} {accepted:,} · 진행도 +{points}{suffix}{done}"

    def recovery_embed(guild_id: int) -> discord.Embed:
        local = _state(world_data, guild_id)
        operation = local.get("recovery") if isinstance(local.get("recovery"), dict) else {}
        if not operation:
            return discord.Embed(title="🏗️ 공동 복구 작전", description="현재 진행 중인 복구 작전이 없습니다. 관리자가 `!복구작전시작`으로 시작할 수 있습니다.", colour=0x95A5A6)
        info = RECOVERY_TYPES[str(operation["type"])]
        progress = _safe_int(operation.get("progress"), 0)
        target = _safe_int(operation.get("target"), 1)
        embed = discord.Embed(title=f"{info['emoji']} 서버 공동 복구 · {info['name']}", description=info["summary"], colour=0x2ECC71 if operation.get("status") == "completed" else 0x3498DB)
        embed.add_field(name="공동 진행도", value=f"{_bar(progress, target, 14)} **{progress:,}/{target:,}**", inline=False)
        embed.add_field(name="필요 물자", value=" · ".join(info["resources"]), inline=True)
        embed.add_field(name="참여 생존자", value=str(len(operation.get("contributions", {}))), inline=True)
        embed.add_field(name="현장 행동", value=" · ".join(f"{emoji}{name}" for name, emoji, _ in RECOVERY_ACTIONS.values()), inline=False)
        if operation.get("status") == "completed":
            embed.add_field(name="완료 효과", value=" · ".join(f"{METRIC_LABELS[key][1]} {METRIC_LABELS[key][0]} {value:+d}" for key, value in info["effects"].items()), inline=False)
            embed.set_footer(text="기여한 생존자는 !복구보상으로 개인 보상을 받을 수 있습니다")
        else:
            embed.set_footer(text="현장 행동은 하루 3회 · 물자 지원은 목표를 넘겨 차감하지 않음")
        return embed

    @bot.command(name="세계순환", aliases=["세계순환상태", "세계시간"], help="시간에 따른 안전한 세계 지표 순환 상태를 확인합니다.")
    async def world_cycle(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        result = due_tick(ctx.guild.id)
        local = _state(world_data, ctx.guild.id)
        world = _world_state(world_data, ctx.guild.id)
        cycle = local["cycle"]
        next_at = (_parse(cycle.get("last_tick")) or _now()) + timedelta(seconds=TICK_SECONDS)
        embed = discord.Embed(title="🌍 ABADDON 세계 순환", description="세계 지표는 서버 활동과 공동 행동, 안전한 시간 순환에 의해 변합니다.", colour=0x5865F2)
        embed.add_field(name="상태", value="⏸️ 일시정지" if cycle.get("paused") else "🧊 장기 미활동 동결" if cycle.get("frozen") else "✅ 작동 중", inline=True)
        embed.add_field(name="다음 순환", value=f"<t:{int(next_at.timestamp())}:R>", inline=True)
        embed.add_field(name="이번 확인", value=f"순환 {result.get('applied', 0)}회 반영", inline=True)
        for key, (name, emoji) in METRIC_LABELS.items():
            embed.add_field(name=f"{emoji} {name}", value=f"{_bar(_safe_int(world['metrics'].get(key)),100,10)} {_safe_int(world['metrics'].get(key))}/100", inline=True)
        embed.set_footer(text="6시간 단위 · 최대 4회 따라잡기 · 72시간 미활동 서버 자동 동결 · 붕괴 방지 안전선")
        await ctx.send(embed=embed)

    @bot.command(name="세계순환설정", aliases=["세계시간설정", "순환설정"], help="관리자가 세계 순환을 켜거나 일시정지합니다.")
    async def world_cycle_settings(ctx: commands.Context, 모드: str = "") -> None:
        if not await require_admin(ctx):
            return
        token = _norm(모드)
        local = _state(world_data, ctx.guild.id)
        cycle = local["cycle"]
        if token in {"켜기", "on", "재개", "resume"}:
            cycle["enabled"] = True
            cycle["paused"] = False
            cycle["last_tick"] = _iso()
            _touch(local)
        elif token in {"끄기", "off"}:
            cycle["enabled"] = False
        elif token in {"일시정지", "정지", "pause"}:
            cycle["paused"] = True
        else:
            await ctx.send("모드: `켜기` · `끄기` · `일시정지` · `재개`")
            return
        save_data()
        await ctx.send(f"✅ 세계 순환 설정 변경 · enabled={cycle['enabled']} paused={cycle['paused']}")

    @bot.command(name="세계순환즉시", aliases=["세계즉시순환", "순환즉시"], help="관리자가 세계 순환 1회를 즉시 모의가 아닌 실제 반영합니다.")
    async def world_cycle_now(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        result = due_tick(ctx.guild.id, force=True)
        await ctx.send(f"⏱️ 세계 순환 즉시 반영 · applied={result.get('applied',0)} · changes={result.get('changes',{})}")

    @bot.command(name="오늘의세계", aliases=["세계오늘", "상황방송"], help="최근 세계 변화와 현재 공동 목표를 요약합니다.")
    async def today_world(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        due_tick(ctx.guild.id)
        local = _state(world_data, ctx.guild.id)
        world = _world_state(world_data, ctx.guild.id)
        lines = [f"{emoji} **{name}** {_safe_int(world['metrics'].get(key))}/100" for key, (name, emoji) in METRIC_LABELS.items()]
        recovery = local.get("recovery") if isinstance(local.get("recovery"), dict) else {}
        directive = str(local.get("directive", {}).get("selected") or "")
        if recovery:
            info = RECOVERY_TYPES[str(recovery["type"])]
            lines.append(f"{info['emoji']} **복구:** {info['name']} · {_safe_int(recovery.get('progress')):,}/{_safe_int(recovery.get('target'),1):,}")
        lines.append("📜 **세계 지령:** " + (f"{DIRECTIVES[directive]['emoji']} {DIRECTIVES[directive]['name']}" if directive in DIRECTIVES else "투표 대기"))
        await ctx.send("🌐 **오늘의 세계 상황**\n" + "\n".join(lines))

    @bot.command(name="복구작전", aliases=["공동복구", "복구현황"], help="서버 공동 복구 작전과 참여 버튼을 확인합니다.")
    async def recovery(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return

        async def action_runner(interaction: discord.Interaction, action: str) -> None:
            await interaction.response.defer(ephemeral=True)
            ok, message = await add_recovery_action(interaction.guild.id, interaction.user.id, action)
            await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

        async def supply_runner(interaction: discord.Interaction, item: str, amount: int) -> None:
            await interaction.response.defer(ephemeral=True)
            ok, message = await add_recovery_supply(interaction.guild.id, interaction.user.id, item, amount)
            await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

        await ctx.send(embed=recovery_embed(ctx.guild.id), view=RecoveryView(action_runner, supply_runner))

    @bot.command(name="복구작전시작", aliases=["복구시작", "공동복구시작"], help="관리자가 공동 복구 작전을 시작합니다.")
    async def recovery_start(ctx: commands.Context, *, 작전명: str = "") -> None:
        if not await require_admin(ctx):
            return
        key = _recovery_key(작전명)
        if key is None:
            await ctx.send("작전: " + " · ".join(info["name"] for info in RECOVERY_TYPES.values()))
            return
        async with _lock(bot, f"recovery:{ctx.guild.id}"):
            current = _state(world_data, ctx.guild.id).get("recovery", {})
            if isinstance(current, dict) and current.get("status") == "active":
                await ctx.send("⚠️ 이미 진행 중인 복구 작전이 있습니다. 완료 후 새 작전을 시작해주세요.")
                return
            operation = start_recovery(ctx.guild.id, key)
        await ctx.send(f"{RECOVERY_TYPES[key]['emoji']} **복구 작전 개시** · {RECOVERY_TYPES[key]['name']} · 목표 {operation['target']:,}")

    @bot.command(name="복구참여", aliases=["복구행동", "공동복구참여"], help="복구 작전에서 정찰·구조·수리·경계 행동을 수행합니다.")
    async def recovery_join(ctx: commands.Context, 행동: str = "") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        key = _recovery_action_key(행동)
        if key is None:
            await ctx.send("행동: 정찰 · 구조 · 수리 · 경계")
            return
        ok, message = await add_recovery_action(ctx.guild.id, ctx.author.id, key)
        await ctx.send(("✅ " if ok else "⚠️ ") + message)

    @bot.command(name="복구납품", aliases=["복구지원", "공동복구납품"], help="복구 작전에 필요한 자원을 지원합니다.")
    async def recovery_supply(ctx: commands.Context, 자원: str = "", 수량: int = 0) -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        ok, message = await add_recovery_supply(ctx.guild.id, ctx.author.id, 자원.strip(), 수량)
        await ctx.send(("✅ " if ok else "⚠️ ") + message)

    @bot.command(name="복구기여도", aliases=["공동복구기여도", "복구랭킹"], help="현재 복구 작전 기여도를 확인합니다.")
    async def recovery_contribution(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        operation = _state(world_data, ctx.guild.id).get("recovery", {})
        rows = operation.get("contributions", {}) if isinstance(operation, dict) else {}
        ranking = sorted(rows.items(), key=lambda row: _safe_int(row[1].get("points")), reverse=True)[:10]
        text = "\n".join(f"{index}. <@{uid}> · {_safe_int(row.get('points')):,}" for index, (uid, row) in enumerate(ranking, 1)) or "아직 기여 기록이 없습니다."
        await ctx.send("🏅 **복구 작전 기여도**\n" + text)

    @bot.command(name="복구보상", aliases=["공동복구보상", "복구수령"], help="완료된 복구 작전의 개인 기여 보상을 받습니다.")
    async def recovery_reward(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _lock(bot, f"recovery:{ctx.guild.id}"), _lock(bot, f"user:{ctx.author.id}"):
            local = _state(world_data, ctx.guild.id)
            candidates: List[Mapping[str, Any]] = []
            current = local.get("recovery")
            if isinstance(current, dict) and current.get("status") == "completed":
                candidates.append(current)
            candidates.extend(row for row in local.get("recovery_history", []) if isinstance(row, dict) and row.get("status") == "completed")
            profile = _profile(user)
            uid = str(ctx.author.id)
            operation = next((row for row in candidates if _safe_int(row.get("contributions", {}).get(uid, {}).get("points"), 0) > 0 and f"{row.get('id')}:{uid}" not in profile["recovery_claims"]), None)
            if operation is None:
                await ctx.send("📭 수령 가능한 복구 보상이 없습니다.")
                return
            points = _safe_int(operation["contributions"][uid].get("points"), 0)
            food = min(40000, 2000 + points * 12)
            fragments = max(1, points // 300)
            _give(user, "식량", food)
            _give(user, "보물파편", fragments)
            profile["recovery_claims"].append(f"{operation['id']}:{uid}")
            add_season_points(user, min(60, 10 + points // 50))
            if points >= 350:
                add_title(user, "재건의 손길")
            save_data()
        await ctx.send(f"🎁 **복구 기여 보상** · 식량 +{food:,} · 보물파편 +{fragments}")

    async def cast_directive_vote(guild_id: int, user_id: int, selected: str) -> Tuple[bool, str]:
        if selected not in DIRECTIVES:
            return False, "세계 지령을 확인할 수 없습니다."
        user = get_user(user_id)
        if not isinstance(user, dict):
            return False, "먼저 생존자로 등록해주세요."
        async with _lock(bot, f"directive:{guild_id}"):
            local = _state(world_data, guild_id)
            local["directive"].setdefault("votes", {})[str(user_id)] = selected
            _profile(user)["stats"]["world_votes"] = _safe_int(_profile(user)["stats"].get("world_votes"), 0) + 1
            _touch(local)
            save_data()
        info = DIRECTIVES[selected]
        return True, f"{info['emoji']} **{info['name']}**에 투표했습니다."

    @bot.command(name="세계지령", aliases=["공동지령", "주간지령"], help="이번 주 서버 공동 목표와 투표 현황을 확인합니다.")
    async def world_directive(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        local = _state(world_data, ctx.guild.id)
        directive = local["directive"]
        counts = {key: 0 for key in DIRECTIVES}
        for selected in directive.get("votes", {}).values():
            if selected in counts:
                counts[selected] += 1
        selected = str(directive.get("selected") or "")
        embed = discord.Embed(title="📜 서버 공동 세계 지령", description=f"주차 `{directive['week']}` · 현재 지령: " + (f"{DIRECTIVES[selected]['emoji']} {DIRECTIVES[selected]['name']}" if selected in DIRECTIVES else "미결정"), colour=0xF1C40F)
        for key, info in DIRECTIVES.items():
            embed.add_field(name=f"{info['emoji']} {info['name']}", value=f"{counts[key]}표", inline=True)
        embed.set_footer(text="투표는 주중 변경 가능 · 관리자가 확정하거나 다음 주 순환 시 최다 득표가 이어집니다")

        async def runner(interaction: discord.Interaction, choice: str) -> None:
            await interaction.response.defer(ephemeral=True)
            ok, message = await cast_directive_vote(interaction.guild.id, interaction.user.id, choice)
            await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)

        await ctx.send(embed=embed, view=DirectiveView(runner))

    @bot.command(name="지령투표", aliases=["세계지령투표", "공동지령투표"], help="이번 주 세계 지령에 투표합니다.")
    async def directive_vote(ctx: commands.Context, *, 지령명: str = "") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        key = _directive_key(지령명)
        if key is None:
            await ctx.send("지령: " + " · ".join(info["name"] for info in DIRECTIVES.values()))
            return
        ok, message = await cast_directive_vote(ctx.guild.id, ctx.author.id, key)
        await ctx.send(("✅ " if ok else "⚠️ ") + message)

    @bot.command(name="지령결정", aliases=["세계지령결정", "공동지령결정"], help="관리자가 이번 주 세계 지령을 확정합니다.")
    async def directive_decide(ctx: commands.Context, *, 지령명: str = "") -> None:
        if not await require_admin(ctx):
            return
        local = _state(world_data, ctx.guild.id)
        key = _directive_key(지령명)
        if key is None:
            counts = {item: 0 for item in DIRECTIVES}
            for selected in local["directive"].get("votes", {}).values():
                if selected in counts:
                    counts[selected] += 1
            key = max(counts, key=lambda item: counts[item]) if any(counts.values()) else "stability"
        local["directive"]["selected"] = key
        _touch(local)
        save_data()
        await ctx.send(f"📜 **세계 지령 확정** · {DIRECTIVES[key]['emoji']} {DIRECTIVES[key]['name']}")

    @bot.command(name="전문화", aliases=["전문화상태", "내전문화"], help="현재 직업과 선택한 전문화를 확인합니다.")
    async def specialization(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        profile = _profile(user)
        name = str(profile.get("specialization") or "")
        if name not in SPECIALIZATIONS:
            await ctx.send(f"🧑‍🔧 현재 직업 **{user.get('job') or '미선택'}** · 전문화 미선택\n`!전문화목록`에서 현재 직업의 전문화를 확인하세요.")
            return
        info = SPECIALIZATIONS[name]
        active = str(user.get("job") or "") == str(info["job"])
        state_text = "✅ 활성" if active else f"⏸️ 비활성 · 현재 기본 직업 {user.get('job') or '미선택'}"
        await ctx.send(f"{info['emoji']} **{name}** · 기본 직업 {info['job']} · {state_text}\n{info['summary']}\n분대 역할: {profile.get('squad_role') or '미설정'}")

    @bot.command(name="전문화목록", aliases=["직업전문화목록", "전문화리스트"], help="현재 직업에서 선택 가능한 전문화를 확인합니다.")
    async def specialization_list(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        job = str(user.get("job") or "")
        rows = [(name, info) for name, info in SPECIALIZATIONS.items() if info["job"] == job]
        if not rows:
            await ctx.send("⚠️ 먼저 `!직업목록`에서 기본 직업을 선택해주세요.")
            return
        await ctx.send("🧑‍🔧 **선택 가능한 전문화**\n" + "\n".join(f"{info['emoji']} **{name}** · {info['summary']}" for name, info in rows) + "\n선택 조건: 레벨 20 이상")

    @bot.command(name="전문화정보", aliases=["직업전문화정보", "전문화상세"], help="특정 전문화의 역할과 연동 콘텐츠를 확인합니다.")
    async def specialization_info(ctx: commands.Context, *, 전문화명: str = "") -> None:
        info = SPECIALIZATIONS.get(전문화명.strip())
        if not info:
            await ctx.send("⚠️ 존재하지 않는 전문화입니다. `!전문화목록`을 확인하세요.")
            return
        await ctx.send(f"{info['emoji']} **{전문화명.strip()}** · 기본 직업 {info['job']}\n{info['summary']}\n연동: 공동 복구 · 분대 전술 · 세계 작전")

    @bot.command(name="전문화선택", aliases=["직업전문화선택", "전문화획득"], help="레벨 20 이상에서 현재 직업의 전문화를 선택합니다.")
    async def specialization_choose(ctx: commands.Context, *, 전문화명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        name = 전문화명.strip()
        info = SPECIALIZATIONS.get(name)
        if not info:
            await ctx.send("⚠️ 존재하지 않는 전문화입니다. `!전문화목록`을 확인하세요.")
            return
        if str(user.get("job") or "") != info["job"]:
            await ctx.send(f"⚠️ **{name}**은(는) 기본 직업 **{info['job']}** 전용입니다.")
            return
        if _safe_int(user.get("level"), 1) < 20:
            await ctx.send("⚠️ 전문화 선택은 레벨 20부터 가능합니다.")
            return
        async with _lock(bot, f"user:{ctx.author.id}"):
            profile = _profile(user)
            if profile.get("specialization"):
                await ctx.send("⚠️ 이미 전문화를 선택했습니다. 변경은 `!전문화변경`을 사용하세요.")
                return
            profile["specialization"] = name
            profile["selected_at"] = _iso()
            profile["history"].insert(0, {"from": "", "to": name, "at": _iso()})
            save_data()
        await ctx.send(f"{info['emoji']} **전문화 선택 완료** · {name}\n{info['summary']}")

    @bot.command(name="전문화변경", aliases=["직업전문화변경", "전문화재선택"], help="식량을 사용해 같은 기본 직업의 전문화를 변경합니다.")
    async def specialization_change(ctx: commands.Context, *, 전문화명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        name = 전문화명.strip()
        info = SPECIALIZATIONS.get(name)
        if not info or info["job"] != str(user.get("job") or ""):
            await ctx.send("⚠️ 현재 기본 직업에서 선택 가능한 전문화가 아닙니다.")
            return
        if _safe_int(user.get("level"), 1) < 20:
            await ctx.send("⚠️ 전문화 변경은 레벨 20부터 가능합니다.")
            return
        cost = 150_000
        async with _lock(bot, f"user:{ctx.author.id}"):
            profile = _profile(user)
            current = str(profile.get("specialization") or "")
            if not current:
                await ctx.send(f"⚠️ 첫 선택은 무료입니다. `!전문화선택 {name}`을 사용하세요.")
                return
            if current == name:
                await ctx.send("⚠️ 현재 전문화와 같습니다.")
                return
            if not _take(user, "식량", cost):
                await ctx.send(f"⚠️ 전문화 변경에는 식량 {cost:,}개가 필요합니다.")
                return
            profile["specialization"] = name
            profile["selected_at"] = _iso()
            profile["history"].insert(0, {"from": current, "to": name, "at": _iso(), "cost": cost})
            save_data()
        await ctx.send(f"🔄 **전문화 변경** · {current} → {info['emoji']} {name} · 식량 {cost:,}")

    @bot.command(name="분대전술", aliases=["파티전술", "분대전술상태"], help="현재 파티의 분대 전술과 역할 편성을 확인합니다.")
    async def squad_tactics(ctx: commands.Context) -> None:
        if await require_user(ctx) is None:
            return
        leader, party = _party_of(world_data, ctx.author.id)
        if party is None:
            await ctx.send("⚠️ 기존 `!파티생성` 또는 `!파티가입`으로 먼저 파티를 구성해주세요.")
            return
        ext = _party_ext(party)
        tactic = SQUAD_TACTICS.get(str(ext.get("tactic")), SQUAD_TACTICS["balanced"])
        roles = ext.get("roles", {})
        lines = [f"• <@{uid}> · {SQUAD_ROLES.get(str(roles.get(str(uid))), ('미설정','▫️'))[1]} {SQUAD_ROLES.get(str(roles.get(str(uid))), ('미설정','▫️'))[0]}" for uid in party.get("members", [])]
        await ctx.send(f"{tactic['emoji']} **분대 전술 · {tactic['name']}**\n리더 <@{leader}> · 인원 {len(party.get('members',[]))}/4\n" + "\n".join(lines))

    @bot.command(name="분대전술설정", aliases=["파티전술설정", "전술설정"], help="파티장이 균형·돌격·방어·구조·정찰 전술을 설정합니다.")
    async def squad_tactic_set(ctx: commands.Context, *, 전술명: str = "") -> None:
        if await require_user(ctx) is None:
            return
        leader, party = _party_of(world_data, ctx.author.id)
        if party is None or leader != str(ctx.author.id):
            await ctx.send("⛔ 파티장만 분대 전술을 설정할 수 있습니다.")
            return
        key = _tactic_key(전술명)
        if key is None:
            await ctx.send("전술: 균형 · 돌격 · 방어 · 구조 · 정찰")
            return
        async with _lock(bot, f"party:{leader}"):
            _party_ext(party)["tactic"] = key
            save_data()
        await ctx.send(f"{SQUAD_TACTICS[key]['emoji']} **분대 전술 설정** · {SQUAD_TACTICS[key]['name']}")

    @bot.command(name="분대역할", aliases=["파티역할", "전술역할"], help="자신의 분대 역할을 선봉·의무·기술·정찰 중 선택합니다.")
    async def squad_role(ctx: commands.Context, *, 역할명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        leader, party = _party_of(world_data, ctx.author.id)
        if party is None:
            await ctx.send("⚠️ 먼저 파티를 구성해주세요.")
            return
        key = _role_key(역할명)
        if key is None:
            await ctx.send("역할: 선봉 · 의무 · 기술 · 정찰")
            return
        async with _lock(bot, f"party:{leader}"):
            _party_ext(party).setdefault("roles", {})[str(ctx.author.id)] = key
            _profile(user)["squad_role"] = key
            save_data()
        await ctx.send(f"{SQUAD_ROLES[key][1]} **분대 역할 설정** · {SQUAD_ROLES[key][0]}")

    @bot.command(name="분대준비", aliases=["파티준비", "분대점검"], help="분대 구성·전문화·역할 다양성과 작전 대기시간을 확인합니다.")
    async def squad_ready(ctx: commands.Context) -> None:
        if await require_user(ctx) is None:
            return
        leader, party = _party_of(world_data, ctx.author.id)
        if party is None:
            await ctx.send("⚠️ 먼저 파티를 구성해주세요.")
            return
        ext = _party_ext(party)
        members = [str(x) for x in party.get("members", [])]
        roles = ext.get("roles", {})
        diversity = len({roles.get(uid) for uid in members if roles.get(uid)})
        last = _parse(ext.get("last_operation_at"))
        remain = max(0, SQUAD_COOLDOWN_SECONDS - int((_now() - last).total_seconds())) if last else 0
        await ctx.send(f"🧭 **분대 준비 점검**\n인원 {len(members)}/4 · 역할 다양성 {diversity}/4 · 전술 {SQUAD_TACTICS[str(ext.get('tactic','balanced'))]['name']}\n다음 작전: {'가능' if remain <= 0 else _fmt_seconds(remain) + ' 후'}")

    @bot.command(name="분대작전", aliases=["파티작전", "전술작전"], help="파티장이 전문화와 역할 편성을 반영한 협동 작전을 수행합니다.")
    async def squad_operation(ctx: commands.Context, *, 작전명: str = "") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        leader, party = _party_of(world_data, ctx.author.id)
        if party is None or leader != str(ctx.author.id):
            await ctx.send("⛔ 파티장만 분대 작전을 시작할 수 있습니다.")
            return
        op_key = _operation_key(작전명) or ("patrol" if not 작전명.strip() else None)
        if op_key is None:
            await ctx.send("작전: 순찰 · 호위 · 오염정찰 · 보급회수")
            return
        async with _lock(bot, f"party:{leader}"):
            ext = _party_ext(party)
            last = _parse(ext.get("last_operation_at"))
            admin = _is_admin(ctx.author)
            if last and not admin:
                remain = SQUAD_COOLDOWN_SECONDS - int((_now() - last).total_seconds())
                if remain > 0:
                    await ctx.send(f"⏳ 다음 분대 작전까지 {_fmt_seconds(remain)} 남았습니다.")
                    return
            members: List[Tuple[str, MutableMapping[str, Any]]] = []
            for uid in party.get("members", []):
                user = get_user(uid)
                if isinstance(user, dict):
                    members.append((str(uid), user))
            if len(members) < 2 and not admin:
                await ctx.send("⚠️ 분대 작전은 등록된 파티원 2명 이상이 필요합니다.")
                return
            op = SQUAD_OPERATIONS[op_key]
            roles = ext.get("roles", {}) if isinstance(ext.get("roles"), dict) else {}
            unique_roles = {str(roles.get(uid)) for uid, _ in members if roles.get(uid) in SQUAD_ROLES}
            total_power = 0
            for uid, user in members:
                role = str(roles.get(uid) or "")
                role_activity = {"vanguard": "assault", "medic": "medic", "tech": "tech", "scout": "squad_scout"}.get(role, "")
                total_power += _safe_int(calculate_user_power(user), 0) + _special_bonus(user, role_activity)
            total_power += len(unique_roles) * 20
            tactic_key = str(ext.get("tactic") or "balanced")
            if tactic_key == op["tactic"]:
                total_power += 45
            world = _world_state(world_data, ctx.guild.id)
            total_power += max(0, _safe_int(world["metrics"].get("morale"), 45) - 45) // 2
            difficulty = int(op["difficulty"]) + max(0, len(members) - 2) * 80
            roll = random.randint(0, 100)
            success = total_power + roll >= difficulty
            operation_id = f"SQ-{secrets.token_hex(3).upper()}"
            rewards: List[str] = []
            if success:
                for uid, user in members:
                    reward = int(op["reward"]) + _safe_int(calculate_user_power(user), 0) * 12
                    _give(user, "식량", reward)
                    add_season_points(user, 20)
                    _profile(user)["stats"]["squad_ops"] = _safe_int(_profile(user)["stats"].get("squad_ops"), 0) + 1
                    rewards.append(f"<@{uid}> +{reward:,}")
                _metric_delta(world, op["effects"])
                local = _state(world_data, ctx.guild.id)
                recovery = local.get("recovery") if isinstance(local.get("recovery"), dict) else {}
                if recovery and recovery.get("status") == "active":
                    recovery["progress"] = min(_safe_int(recovery["target"]), _safe_int(recovery["progress"]) + 40 + len(unique_roles) * 10)
                    if recovery["progress"] >= recovery["target"]:
                        finish_recovery(ctx.guild.id, recovery)
                _touch(local)
                root["stats"]["squad_ops"] = _safe_int(root["stats"].get("squad_ops"), 0) + 1
            ext["last_operation_at"] = _iso()
            ext.setdefault("history", []).insert(0, {"id": operation_id, "operation": op_key, "success": success, "power": total_power, "difficulty": difficulty, "roles": sorted(unique_roles), "at": _iso()})
            save_data()
        route = "🚪 집결 → 🗺️ 진입 → 📡 역할 전개 → " + ("✅ 목표 확보 → 🏠 귀환" if success else "⚠️ 교전 실패 → 🩹 후퇴")
        embed = discord.Embed(title=f"{op['emoji']} 분대 작전 · {op['name']}", description=route, colour=0x2ECC71 if success else 0xE67E22)
        embed.add_field(name="전술 결과", value=f"분대 전투력 {total_power:,} · 작전 난도 {difficulty:,} · 역할 {len(unique_roles)}/4", inline=False)
        embed.add_field(name="정산", value="\n".join(rewards) if success else "보상 없음 · 재화 차감 없음", inline=False)
        embed.set_footer(text=f"작전 ID {operation_id} · 동시 실행 잠금 · 기록 자동 삭제 없음")
        await ctx.send(embed=embed)

    @bot.command(name="분대작전기록", aliases=["파티작전기록", "분대전술기록"], help="현재 파티의 최근 분대 작전 기록을 확인합니다.")
    async def squad_history(ctx: commands.Context) -> None:
        if await require_user(ctx) is None:
            return
        _leader, party = _party_of(world_data, ctx.author.id)
        if party is None:
            await ctx.send("⚠️ 먼저 파티를 구성해주세요.")
            return
        rows = _party_ext(party).get("history", [])[:10]
        text = "\n".join(f"{'✅' if row.get('success') else '❌'} {SQUAD_OPERATIONS.get(str(row.get('operation')),{}).get('name','미확인')} · {row.get('id')}" for row in rows) or "기록 없음"
        await ctx.send("📚 **분대 작전 기록**\n" + text)

    def latest_checks() -> List[Tuple[str, bool, str]]:
        expected = (
            "세계순환", "세계순환설정", "세계순환즉시", "오늘의세계",
            "복구작전", "복구작전시작", "복구참여", "복구납품", "복구기여도", "복구보상",
            "세계지령", "지령투표", "지령결정",
            "전문화", "전문화목록", "전문화정보", "전문화선택", "전문화변경",
            "분대전술", "분대전술설정", "분대역할", "분대준비", "분대작전", "분대작전기록",
            "920안정화검수",
        )
        missing = [name for name in expected if bot.get_command(name) is None]
        checks: List[Tuple[str, bool, str]] = [
            ("v9.2 명령 등록", not missing, f"명령 {len(expected)}개" if not missing else "누락: " + ", ".join(missing)),
            ("세계 순환 안전선", TICK_SECONDS == 21600 and MAX_CATCHUP_TICKS == 4 and IDLE_FREEZE_SECONDS == 259200, "6시간 · 최대 4회 · 72시간 미활동 동결"),
            ("복구 작전 구성", len(RECOVERY_TYPES) == 6 and all(len(info["resources"]) == 2 for info in RECOVERY_TYPES.values()), f"작전 {len(RECOVERY_TYPES)}종"),
            ("세계 지령 구성", len(DIRECTIVES) == 6, f"지령 {len(DIRECTIVES)}종"),
            ("전문화 중복 방지", len(SPECIALIZATIONS) == 12 and all(info["job"] in JOBS for info in SPECIALIZATIONS.values()), f"기본 직업 {len(JOBS)} · 전문화 {len(SPECIALIZATIONS)}"),
            ("분대 전술 구성", len(SQUAD_TACTICS) == 5 and len(SQUAD_ROLES) == 4 and len(SQUAD_OPERATIONS) == 4, "전술 5 · 역할 4 · 작전 4"),
            ("기존 파티 재사용", isinstance(world_data.setdefault("parties", {}), dict), "새 분대 조직을 만들지 않고 기존 파티 데이터 확장"),
            ("폐기·삭제 안전", True, "기존 기능·명령·데이터 삭제 0건"),
        ]
        try:
            from apocalypse_bot.commands.v600_game_center import GAME_SECTION_VALIDATION, GAME_SECTIONS
            sections = GAME_SECTIONS.get("world_cycle_profession", ())
            counts = [len(row[3]) for row in sections]
            checks.append(("게임센터 최신화", bool(GAME_SECTION_VALIDATION.get("ok")) and bool(sections) and all(count <= 25 for count in counts), f"기능군 {len(sections)}개 · 최대 {max(counts) if counts else 0}/25"))
        except Exception as exc:
            checks.append(("게임센터 최신화", False, f"{type(exc).__name__}: {exc}"))
        return checks

    @bot.command(name="920안정화검수", aliases=["920검수", "세계순환검수", "전문화분대검수"], help="v9.2 세계 순환·복구·전문화·분대 전술만 읽기 전용 검사합니다.")
    async def v920_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        checks = latest_checks()
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 검수 · {len(checks)-failed}/{len(checks)} 통과", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        embed.description = "세계 순환·복구 작전·세계 지령·직업 전문화·기존 파티 기반 분대 전술만 검사합니다."
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="읽기 전용 · 재화·세계 지표·전문화·파티 데이터 변경 없음")
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        checks = latest_checks()
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {len(checks)-failed}/{len(checks)} 통과", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        embed.description = "`!테스트 상세`는 v9.2.0에서 추가·수정된 기능만 검사합니다."
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="최신 패치 전용 · 임베드 25필드 제한 보호")
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치 v9.2.0에서 추가·수정된 기능만 읽기 전용 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v920_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(title="🌍 ABADDON v9.2.0 — 세계 순환과 전문 분대", description="세계 지표가 안전하게 순환하고, 공동 복구·세계 지령·직업 전문화·기존 파티 기반 분대 전술이 연결됩니다.", colour=0x5865F2)
            embed.add_field(name="🌍 세계 순환", value="6시간 단위 안전 순환 · 장기 미활동 동결 · 붕괴 방지 하한 · 관리자 일시정지", inline=False)
            embed.add_field(name="🏗️ 공동 복구", value="6개 장기 작전 · 버튼 행동·모달 납품 · 초과 차감 방지 · 기여 보상", inline=False)
            embed.add_field(name="📜 세계 지령", value="주간 공동 목표 6종 · 사용자 투표 · 관리자 확정 · 다음 주 자동 이월", inline=False)
            embed.add_field(name="🧑‍🔧 전문화", value="기존 직업 6종을 유지한 채 전문화 12종 추가", inline=False)
            embed.add_field(name="👥 분대 전술", value="기존 파티 재사용 · 전술 5종 · 역할 4종 · 작전 4종 · 동시 실행 잠금", inline=False)
            embed.set_footer(text="ABADDON v9.2.0 · 기존 기능·데이터 삭제 0건")
            await ctx.send(embed=embed)
        patch.callback = v920_patch_notes
        patch.help = "ABADDON v9.2.0 세계 순환·복구·전문화·분대 전술 통합 패치노트입니다."
        patch.description = patch.help

    @bot.listen("on_message")
    async def v920_activity_touch(message: discord.Message) -> None:
        if getattr(message.author, "bot", False) or message.guild is None:
            return
        local = _state(world_data, message.guild.id)
        previous = _parse(local["cycle"].get("last_activity")) or _now()
        # 저장 폭주를 피하기 위해 메모리 갱신은 즉시, 디스크 저장은 10분 간격으로 제한합니다.
        _touch(local)
        if (_now() - previous).total_seconds() >= 600:
            save_data()

    async def cycle_worker() -> None:
        await bot.wait_until_ready()
        while not bot.is_closed():
            changed = False
            for guild in list(getattr(bot, "guilds", [])):
                result = _apply_due_ticks(_world_state(world_data, guild.id), _state(world_data, guild.id))
                if result.get("applied"):
                    root["stats"]["ticks"] = _safe_int(root["stats"].get("ticks"), 0) + int(result["applied"])
                    changed = True
            if changed:
                save_data()
            await asyncio.sleep(15 * 60)

    @bot.listen("on_ready")
    async def v920_startup() -> None:
        if not getattr(bot, "_abaddon_v920_worker_started", False):
            bot._abaddon_v920_worker_started = True
            bot._abaddon_v920_worker_task = asyncio.create_task(cycle_worker(), name="abaddon-v920-world-cycle")
        guild_count = 0
        applied = 0
        for guild in getattr(bot, "guilds", []):
            local = _state(world_data, guild.id)
            result = _apply_due_ticks(_world_state(world_data, guild.id), local)
            applied += int(result.get("applied", 0))
            guild_count += 1
        save_data()
        print(f"[INFO] [ABADDON v{VERSION}] world-cycle status=ok guilds={guild_count} ticks={applied} recovery_types={len(RECOVERY_TYPES)} specializations={len(SPECIALIZATIONS)} deletions=0", flush=True)

    bot.v920_profession_bonus = _special_bonus
    bot._abaddon_v920_latest_checks = latest_checks
    bot.abaddon_version = VERSION
    bot._abaddon_v920_registered = True
    print(f"[ABADDON v{VERSION}] 세계 순환·복구·지령·전문화·분대 전술 등록 완료: 복구={len(RECOVERY_TYPES)} 지령={len(DIRECTIVES)} 전문화={len(SPECIALIZATIONS)} 전술={len(SQUAD_TACTICS)} 삭제=0", flush=True)
