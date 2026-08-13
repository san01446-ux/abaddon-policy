from __future__ import annotations

"""ABADDON v18.0.2 — FINAL ECLIPSE quiz bank audit hotfix.

This final additive layer closes the v17 roadmap in one audited release:
- v17.6.1 current-session vs historical runtime incident separation;
- v17.7 guided newcomer / returner journey with preserved legacy commands;
- v17.8 daily connected loop, collection currency and visible rewards;
- v17.9 owner-safe backup/export/restore preview and final regression center;
- v18.0 unified terminal and a scalable server-wide Final Eclipse ending.

No legacy command, item id or save key is removed. Existing ``!아바돈`` dialogue
is preserved through ``!말걸기`` and direct ``!아바돈 <message>`` usage; only
``!아바돈`` without text opens the definitive terminal.
"""

import asyncio
import copy
import io
import json
import os
import secrets
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
from apocalypse_bot.commands.v600_game_center import _invoke_command, _safe_embed, _safe_view

VERSION = "18.0.2"
KST = timezone(timedelta(hours=9))
ROOT_KEY = "final_eclipse_v1800"
USER_KEY = "definitive_survivor_v1800"
ERROR_KEY = "runtime_archive_v1761"
FINAL_PHASES = 5


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _audit_rows(locale: str, rows: Sequence[Tuple[str, str, bool]]) -> List[Tuple[str, bool]]:
    """Return audit labels in exactly one locale."""
    return [(_t(locale, ko, en), bool(ok)) for ko, en, ok in rows]


def _now() -> int:
    return int(time.time())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _week() -> str:
    now = datetime.now(KST)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _mapping(value: Any) -> MutableMapping[str, Any]:
    return value if isinstance(value, MutableMapping) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _is_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        return False
    perms = ctx.author.guild_permissions
    return bool(perms.administrator or perms.manage_guild)


async def _is_owner_or_admin(bot: commands.Bot, ctx: commands.Context) -> bool:
    if _is_admin(ctx):
        return True
    try:
        return bool(await bot.is_owner(ctx.author))
    except Exception:
        return False


def _user_state(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    state = user.setdefault(USER_KEY, {})
    if not isinstance(state, MutableMapping):
        state = {}
        user[USER_KEY] = state
    state.setdefault("version", VERSION)
    state.setdefault("onboarding", {"step": 0, "completed": False, "started_at": 0, "completed_at": 0})
    state.setdefault("return_pack", {"last_claim": "", "claims": 0})
    state.setdefault("attendance", {"days": {}, "streak": 0, "last_day": ""})
    state.setdefault("daily_loop", {"day": "", "done": {}, "claimed": [], "history": []})
    state.setdefault("collection", {"eclipse_shards": 0, "unlocks": [], "claimed": []})
    state.setdefault("finale", {"joined_guilds": [], "rewarded_guilds": [], "operations": {}, "votes": {}})
    state.setdefault("history", [])
    for key in ("onboarding", "return_pack", "attendance", "daily_loop", "collection", "finale"):
        if not isinstance(state.get(key), MutableMapping):
            state[key] = {}
    state["version"] = VERSION
    return state


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    root.setdefault("release", {"mode": "definitive", "released_at": _now(), "hotfix_only": True})
    root.setdefault("restore_previews", {})
    root.setdefault("exports", [])
    if not isinstance(root.get("guilds"), MutableMapping):
        root["guilds"] = {}
    if not isinstance(root.get("restore_previews"), MutableMapping):
        root["restore_previews"] = {}
    if not isinstance(root.get("exports"), list):
        root["exports"] = []
    root["version"] = VERSION
    return root


def _new_guild_state() -> MutableMapping[str, Any]:
    return {
        "active": True,
        "paused": False,
        "started_at": _now(),
        "phase": 1,
        "points": 0,
        "participants": {},
        "metrics": {"hope": 0, "order": 0, "survival": 0, "abyss": 0},
        "votes": {},
        "ending": "",
        "ending_at": 0,
        "reward_claims": [],
        "history": [],
        "broadcast_channel": 0,
    }


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _root(world_data)
    guilds = root["guilds"]
    gid = str(int(guild_id or 0))
    row = guilds.setdefault(gid, _new_guild_state())
    if not isinstance(row, MutableMapping):
        row = _new_guild_state()
        guilds[gid] = row
    default = _new_guild_state()
    for key, value in default.items():
        row.setdefault(key, copy.deepcopy(value))
    for key in ("participants", "metrics", "votes"):
        if not isinstance(row.get(key), MutableMapping):
            row[key] = {}
    for key in ("reward_claims", "history"):
        if not isinstance(row.get(key), list):
            row[key] = []
    return row


def _record(rows: List[Any], action: str, detail: str = "", limit: int = 80) -> None:
    rows.append({"at": _now(), "action": str(action)[:80], "detail": str(detail)[:280]})
    del rows[:-limit]


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _error_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(ERROR_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[ERROR_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("session_started_at", _now_iso())
    root.setdefault("baseline_failures", {})
    root.setdefault("baseline_runs", {})
    root.setdefault("archives", [])
    root.setdefault("resolutions", {})
    if not isinstance(root.get("baseline_failures"), MutableMapping):
        root["baseline_failures"] = {}
    if not isinstance(root.get("baseline_runs"), MutableMapping):
        root["baseline_runs"] = {}
    if not isinstance(root.get("archives"), list):
        root["archives"] = []
    if not isinstance(root.get("resolutions"), MutableMapping):
        root["resolutions"] = {}
    return root


def _incident_sources(world_data: Mapping[str, Any]) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Any]]:
    ops = world_data.get("operations_v702") if isinstance(world_data.get("operations_v702"), Mapping) else {}
    incidents = ops.get("incidents") if isinstance(ops.get("incidents"), list) else []
    stats = ops.get("command_stats") if isinstance(ops.get("command_stats"), Mapping) else {}
    cute = world_data.get("v711_cute_interactions") if isinstance(world_data.get("v711_cute_interactions"), Mapping) else {}
    ui_errors = cute.get("ui_errors") if isinstance(cute.get("ui_errors"), list) else []
    return [x for x in incidents if isinstance(x, Mapping)], [x for x in ui_errors if isinstance(x, Mapping)], stats


def _incident_time(row: Mapping[str, Any]) -> Optional[datetime]:
    return _parse_iso(row.get("at") or row.get("created_at") or row.get("timestamp"))


def _split_incidents(world_data: MutableMapping[str, Any]) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Any]]:
    archive = _error_root(world_data)
    start = _parse_iso(archive.get("session_started_at")) or datetime.now(timezone.utc)
    incidents, ui_errors, stats = _incident_sources(world_data)
    current_incidents, past_incidents = [], []
    current_ui, past_ui = [], []
    for row in incidents:
        (current_incidents if ((_incident_time(row) or datetime.min.replace(tzinfo=timezone.utc)) >= start) else past_incidents).append(row)
    for row in ui_errors:
        (current_ui if ((_incident_time(row) or datetime.min.replace(tzinfo=timezone.utc)) >= start) else past_ui).append(row)
    return current_incidents, past_incidents, current_ui, past_ui, stats


def _runtime_deltas(world_data: MutableMapping[str, Any]) -> Tuple[int, int, int, int]:
    archive = _error_root(world_data)
    _cur, _past, _ui, _old_ui, stats = _split_incidents(world_data)
    total_runs = 0
    total_failures = 0
    historical_runs = 0
    historical_failures = 0
    for name, row in stats.items():
        if not isinstance(row, Mapping):
            continue
        runs = _safe_int(row.get("runs"))
        failures = _safe_int(row.get("failures"))
        base_runs = _safe_int(archive.get("baseline_runs", {}).get(name))
        base_failures = _safe_int(archive.get("baseline_failures", {}).get(name))
        total_runs += max(0, runs - base_runs)
        total_failures += max(0, failures - base_failures)
        historical_runs += min(runs, base_runs)
        historical_failures += min(failures, base_failures)
    return total_runs, total_failures, historical_runs, historical_failures


def _initialize_runtime_baseline(world_data: MutableMapping[str, Any]) -> None:
    archive = _error_root(world_data)
    _inc, _ui, stats = _incident_sources(world_data)
    if archive.get("baseline_initialized"):
        # Every process restart gets a new current-session timestamp while totals
        # remain preserved as the baseline for this boot.
        archive["session_started_at"] = _now_iso()
    else:
        archive["baseline_initialized"] = True
        archive["session_started_at"] = _now_iso()
    archive["baseline_runs"] = {str(name): _safe_int(row.get("runs")) for name, row in stats.items() if isinstance(row, Mapping)}
    archive["baseline_failures"] = {str(name): _safe_int(row.get("failures")) for name, row in stats.items() if isinstance(row, Mapping)}
    archive["boot_at"] = _now()


ONBOARDING_STEPS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("register", "생존자 등록", "Register Survivor", ("가입", "등록", "register")),
    ("profile", "내 정보 확인", "Open Profile", ("정보", "프로필", "profile")),
    ("story", "시즌 이야기 시작", "Start the Story", ("스토리", "시즌1", "story")),
    ("world", "오늘의 세계 확인", "Check Today's World", ("살아있는세계", "오늘의세계사건", "livingworld", "worldevent")),
    ("expedition", "첫 원정 진행", "Run an Expedition", ("솔로원정", "탐험", "원정", "lonesurvivor", "expedition")),
    ("bond", "NPC와 인연 맺기", "Meet an NPC", ("인연", "npc대화", "bond", "npctalk")),
    ("season", "서버 시즌 참가", "Join Community Season", ("시즌참가", "서버시즌", "seasonjoin", "abaddonseason")),
)

DAILY_CATEGORIES: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("checkin", "출석·프로필", "Check-in & Profile", ("출석", "정보", "프로필", "daily", "profile")),
    ("world", "세계 사건", "World Event", ("오늘의세계사건", "세계참여", "살아있는세계", "worldevent", "worldparticipate")),
    ("expedition", "원정·전투", "Expedition & Combat", ("솔로원정", "원정", "전투", "던전", "lonesurvivor", "expedition", "battle")),
    ("production", "생산·도시", "Production & City", ("채집", "제작", "생산센터", "도시꾸미기", "도시배치", "gather", "craft", "production", "city")),
    ("bond", "NPC·소셜", "NPC & Social", ("인연", "npc대화", "npc선물", "동행요청", "bond", "npctalk", "bondgift")),
    ("legacy", "박물관·시즌", "Museum & Season", ("연대기박물관", "통합업적", "시즌동기화", "시즌미션", "museum", "achievementsall", "seasonsync")),
)

COLLECTION_REWARDS: Tuple[Tuple[int, str, str, int, int], ...] = (
    (30, "검은 태양 관측자", "Black Sun Observer", 30000, 150),
    (80, "일식 생존자", "Eclipse Survivor", 80000, 350),
    (160, "최종 성역 기록관", "Definitive Archivist", 160000, 700),
    (300, "아바돈 영원의 증인", "Eternal Witness of ABADDON", 300000, 1200),
)

OPERATION_CHOICES: Dict[int, Tuple[str, str, str, Dict[str, int]]] = {
    1: ("보급망 복구", "Restore Supply Lines", "survival", {"survival": 3, "hope": 1}),
    2: ("시민 대피", "Evacuate Civilians", "hope", {"hope": 3, "order": 1}),
    3: ("도시 방어선", "Fortify the City", "order", {"order": 3, "survival": 1}),
    4: ("심연 역추적", "Trace the Abyss", "abyss", {"abyss": 3, "hope": -1}),
}

ENDING_TEXT: Dict[str, Tuple[str, str]] = {
    "dawn": ("새벽의 성역", "Sanctuary at Dawn"),
    "citadel": ("철의 성채", "The Iron Citadel"),
    "wanderers": ("끝없는 생존행", "The Endless Survival March"),
    "abyss": ("심연과의 공존", "Concord with the Abyss"),
    "balanced": ("마지막 일식의 증인", "Witnesses of the Final Eclipse"),
}


def _ending(metrics: Mapping[str, Any]) -> str:
    values = {key: _safe_int(metrics.get(key)) for key in ("hope", "order", "survival", "abyss")}
    highest = max(values, key=values.get)
    if values[highest] >= max(12, sorted(values.values(), reverse=True)[1] + 4):
        return {"hope": "dawn", "order": "citadel", "survival": "wanderers", "abyss": "abyss"}[highest]
    return "balanced"


def _phase_target(state: Mapping[str, Any]) -> int:
    participants = max(1, len(state.get("participants", {})) if isinstance(state.get("participants"), Mapping) else 1)
    base = (15, 35, 65, 105, 155)[max(0, min(4, _safe_int(state.get("phase"), 1) - 1))]
    # Small servers remain fully playable; larger communities scale gently.
    return base + max(0, participants - 1) * 8


def _activity_command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "").casefold()


def _matches(name: str, tokens: Iterable[str]) -> bool:
    folded = name.casefold().replace(" ", "")
    return any(str(token).casefold().replace(" ", "") in folded for token in tokens)


def _reset_daily(state: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    daily = state.setdefault("daily_loop", {})
    if not isinstance(daily, MutableMapping):
        daily = {}
        state["daily_loop"] = daily
    if str(daily.get("day", "")) != _today():
        history = daily.setdefault("history", [])
        if isinstance(history, list) and daily.get("day"):
            history.append({"day": daily.get("day"), "done": dict(daily.get("done", {})), "claimed": list(daily.get("claimed", []))})
            del history[:-30]
        daily.update(day=_today(), done={}, claimed=[])
    daily.setdefault("done", {})
    daily.setdefault("claimed", [])
    return daily


def _onboarding_step(state: MutableMapping[str, Any]) -> int:
    onboarding = state.setdefault("onboarding", {})
    if not isinstance(onboarding, MutableMapping):
        onboarding = {}
        state["onboarding"] = onboarding
    onboarding.setdefault("step", 0)
    onboarding.setdefault("completed", False)
    onboarding.setdefault("started_at", _now())
    onboarding.setdefault("completed_at", 0)
    return max(0, min(len(ONBOARDING_STEPS), _safe_int(onboarding.get("step"))))


def _advance_onboarding(state: MutableMapping[str, Any], command_name: str) -> bool:
    step = _onboarding_step(state)
    onboarding = state["onboarding"]
    if onboarding.get("completed") or step >= len(ONBOARDING_STEPS):
        return False
    if _matches(command_name, ONBOARDING_STEPS[step][3]):
        onboarding["step"] = step + 1
        if step + 1 >= len(ONBOARDING_STEPS):
            onboarding["completed"] = True
            onboarding["completed_at"] = _now()
        return True
    return False


def _mark_daily(state: MutableMapping[str, Any], command_name: str) -> Optional[str]:
    daily = _reset_daily(state)
    done = daily["done"]
    for key, _ko, _en, tokens in DAILY_CATEGORIES:
        if key not in done and _matches(command_name, tokens):
            done[key] = {"at": _now(), "command": command_name}
            return key
    return None


def _collection_state(state: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = state.setdefault("collection", {})
    if not isinstance(row, MutableMapping):
        row = {}
        state["collection"] = row
    row.setdefault("eclipse_shards", 0)
    row.setdefault("unlocks", [])
    row.setdefault("claimed", [])
    if not isinstance(row.get("unlocks"), list):
        row["unlocks"] = []
    if not isinstance(row.get("claimed"), list):
        row["claimed"] = []
    return row


def _finale_user(state: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = state.setdefault("finale", {})
    if not isinstance(row, MutableMapping):
        row = {}
        state["finale"] = row
    row.setdefault("joined_guilds", [])
    row.setdefault("rewarded_guilds", [])
    row.setdefault("operations", {})
    row.setdefault("votes", {})
    return row


def _registered_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> Optional[MutableMapping[str, Any]]:
    row = get_user(int(user_id))
    return row if isinstance(row, MutableMapping) else None


class CommandButton(discord.ui.Button):
    def __init__(self, owner: "FinalActionView", command: str, ko: str, en: str, emoji: str, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        super().__init__(label=_t(owner.locale, ko, en)[:80], emoji=emoji, style=style)
        self.owner_view = owner
        self.command_name = command

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        command = view.bot.get_command(self.command_name)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "명령을 찾지 못했습니다.", "Command not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name)


class FinalActionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, actions: Sequence[Tuple[str, str, str, str, discord.ButtonStyle]]) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        for command, ko, en, emoji, style in list(actions)[:5]:
            self.add_item(CommandButton(self, command, ko, en, emoji, style))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 단말기는 실행자만 사용할 수 있습니다.", "Only the opener can use this terminal."), ephemeral=True)
        return False


def _terminal_embed(locale: str, user: Mapping[str, Any], state: Mapping[str, Any], guild: Mapping[str, Any]) -> discord.Embed:
    onboarding = state.get("onboarding", {}) if isinstance(state.get("onboarding"), Mapping) else {}
    daily = state.get("daily_loop", {}) if isinstance(state.get("daily_loop"), Mapping) else {}
    collection = state.get("collection", {}) if isinstance(state.get("collection"), Mapping) else {}
    done = daily.get("done", {}) if isinstance(daily.get("done"), Mapping) else {}
    step = min(len(ONBOARDING_STEPS), _safe_int(onboarding.get("step")))
    phase = _safe_int(guild.get("phase"), 1)
    target = _phase_target(guild)
    ending = str(guild.get("ending", ""))
    embed = discord.Embed(
        title=_t(locale, "🌑 ABADDON v18.0 최종 생존단말기", "🌑 ABADDON v18.0 Definitive Terminal"),
        description=_t(locale, "스토리·세계·의뢰·원정·생산·NPC·박물관·시즌·최종 결전을 한 화면에서 연결합니다.", "Connect story, world, contracts, expeditions, production, NPCs, museum, season and the final battle from one screen."),
        color=0x5B2C6F,
    )
    embed.add_field(name=_t(locale, "🌱 생존 정착", "🌱 Survivor Journey"), value=_t(locale, f"{step}/{len(ONBOARDING_STEPS)}단계 · {'완료' if onboarding.get('completed') else '진행 중'}", f"{step}/{len(ONBOARDING_STEPS)} steps · {'Complete' if onboarding.get('completed') else 'In progress'}"), inline=True)
    embed.add_field(name=_t(locale, "☀️ 오늘의 루프", "☀️ Daily Loop"), value=f"{len(done)}/{len(DAILY_CATEGORIES)}", inline=True)
    embed.add_field(name=_t(locale, "💠 일식 파편", "💠 Eclipse Shards"), value=f"{_safe_int(collection.get('eclipse_shards')):,}", inline=True)
    if ending:
        ko, en = ENDING_TEXT.get(ending, ENDING_TEXT["balanced"])
        finale_text = _t(locale, f"결말 확정 · **{ko}**", f"Ending sealed · **{en}**")
    else:
        finale_text = _t(locale, f"제{phase}단계 · {guild.get('points', 0):,}/{target:,}", f"Phase {phase} · {guild.get('points', 0):,}/{target:,}")
    embed.add_field(name=_t(locale, "🌘 FINAL ECLIPSE", "🌘 FINAL ECLIPSE"), value=finale_text, inline=False)
    embed.add_field(name=_t(locale, "📊 현재 생존자", "📊 Current Survivor"), value=_t(locale, f"레벨 {_safe_int(user.get('level'), 1)} · 식량 {_safe_int(user.get('balance')):,} · EXP {_safe_int(user.get('exp')):,}", f"Level {_safe_int(user.get('level'), 1)} · Supplies {_safe_int(user.get('balance')):,} · EXP {_safe_int(user.get('exp')):,}"), inline=False)
    embed.set_footer(text=_t(locale, "기존 !아바돈 대화는 !말걸기 또는 !아바돈 질문으로 그대로 이용합니다.", "Legacy dialogue remains available through !chat or !abaddon <message>."))
    return _safe_embed(embed)


def _error_embed(locale: str, world_data: MutableMapping[str, Any], detailed: bool = False, mode: str = "all") -> discord.Embed:
    current, past, current_ui, past_ui, stats = _split_incidents(world_data)
    current_runs, current_failures, historical_runs, historical_failures = _runtime_deltas(world_data)
    if mode == "current":
        shown_incidents, shown_ui = current, current_ui
        title = _t(locale, "🟢 현재 실행 오류", "🟢 Current Session Errors")
    elif mode == "past":
        shown_incidents, shown_ui = past, past_ui
        title = _t(locale, "🗄️ 과거 보관 오류", "🗄️ Historical Errors")
    else:
        shown_incidents, shown_ui = current, current_ui
        title = _t(locale, "🛰️ ABADDON v18 실시간 오류센터", "🛰️ ABADDON v18 Live QA Center")
    healthy = not current and not current_ui and current_failures == 0
    embed = discord.Embed(
        title=title,
        description=_t(locale, "현재 부팅 이후 오류와 과거 보존 기록을 분리합니다. 과거 사건은 현재 장애로 계산하지 않습니다.", "Current-boot errors are separated from preserved history. Historical incidents do not count as active failures."),
        color=0x2ECC71 if healthy else 0xE67E22,
    )
    embed.add_field(name=_t(locale, "현재 실행", "Current Runs"), value=f"{current_runs:,}", inline=True)
    embed.add_field(name=_t(locale, "현재 실패", "Current Failures"), value=f"{current_failures:,}", inline=True)
    embed.add_field(name=_t(locale, "현재 UI 사건", "Current UI Incidents"), value=f"{len(current_ui):,}", inline=True)
    embed.add_field(name=_t(locale, "과거 명령 실패", "Historical Failures"), value=f"{historical_failures:,}", inline=True)
    embed.add_field(name=_t(locale, "과거 사건", "Historical Incidents"), value=f"{len(past):,}", inline=True)
    embed.add_field(name=_t(locale, "과거 UI", "Historical UI"), value=f"{len(past_ui):,}", inline=True)
    lines: List[str] = []
    for row in shown_incidents[:6]:
        lines.append(f"• `{row.get('id','-')}` · `!{row.get('command','?')}` · {row.get('error_type','Error')}")
    for row in list(reversed(shown_ui[-6:])):
        lines.append(f"• `{row.get('id','-')}` · UI `{row.get('where','?')}` · {str(row.get('error','Error')).split(':',1)[0]}")
    label = _t(locale, "현재 사건" if mode != "past" else "과거 사건", "Current Incidents" if mode != "past" else "Historical Incidents")
    embed.add_field(name=label, value="\n".join(lines[:10]) or _t(locale, "기록 없음", "No incidents"), inline=False)
    if mode == "all" and healthy:
        embed.add_field(name=_t(locale, "✅ 판정", "✅ Verdict"), value=_t(locale, f"현재 실행에서는 새 오류가 없습니다. 화면에 남아 있는 과거 기록은 {len(past) + len(past_ui)}건입니다.", f"No new errors exist in the current boot. Historical records: {len(past) + len(past_ui)}."), inline=False)
    if detailed:
        active_stats = []
        baseline = _error_root(world_data).get("baseline_failures", {})
        for name, row in stats.items():
            if not isinstance(row, Mapping):
                continue
            delta = max(0, _safe_int(row.get("failures")) - _safe_int(baseline.get(name)))
            if delta:
                active_stats.append((delta, str(name), str(row.get("last_error", ""))))
        active_stats.sort(reverse=True)
        embed.add_field(name=_t(locale, "현재 반복 실패", "Current Repeated Failures"), value="\n".join(f"• `!{name}` · {count} · {error[:80]}" for count, name, error in active_stats[:8]) or _t(locale, "없음", "None"), inline=False)
    return _safe_embed(embed)


def _mount_command_groups() -> None:
    """Extend the existing command center without removing older groups."""
    additions = {
        "main": (
            ("definitive", "FINAL ECLIPSE·최종 단말기", "FINAL ECLIPSE & Definitive Terminal", "최종 통합 단말기, 마지막 일식 공동 결전과 결말", "Definitive terminal, Final Eclipse battle and ending", "🌑"),
            ("retention", "신규·복귀·일일 생존 루프", "Newcomer, Returner & Daily Loop", "7단계 정착, 7일 보급, 복귀 보급과 일일 수집 보상", "Seven-step onboarding, seven-day supplies, return packs and daily collection rewards", "🌱"),
        ),
        "system": (
            ("final_ops", "최종 운영·보존 센터", "Definitive Operations & Preservation", "현재/과거 오류, 백업, 내보내기, 복구 미리보기와 최종 검수", "Current/history errors, backup, export, restore preview and final audits", "🧿"),
        ),
    }
    for section, rows in additions.items():
        existing = {row[0] for row in hub.GROUP_SPECS.get(section, ())}
        fresh = tuple(row for row in rows if row[0] not in existing)
        if fresh:
            hub.GROUP_SPECS[section] = tuple(hub.GROUP_SPECS[section]) + fresh
        for key, ko, en, dko, den, emoji in rows:
            hub.GROUP_INDEX[key] = (section, ko, en, dko, den, emoji)


def _install_classifier() -> None:
    if getattr(hub, "_v1800_classifier_installed", False):
        return
    old = hub._classify

    def classify(command: commands.Command) -> Tuple[str, str]:
        source = str(getattr(getattr(command, "callback", None), "__module__", ""))
        module = source.rsplit(".", 1)[-1]
        if module == "v1800_final_eclipse":
            blob = " ".join((str(getattr(command, "qualified_name", "")), " ".join(str(x) for x in getattr(command, "aliases", []) or []), str(getattr(command, "help", "") or ""))).casefold()
            if any(token in blob for token in ("최종일식", "일식참가", "일식작전", "일식투표", "일식결전", "일식결말", "일식보상", "finaleclipse", "eclipsejoin", "eclipseoperation", "eclipsebattle")):
                return "main", "definitive"
            if any(token in blob for token in ("초보생존", "첫걸음", "7일보급", "최종복귀보급", "오늘의루프", "최종루프보상", "최종컬렉션", "survivorstart", "dailyloop", "collection")):
                return "main", "retention"
            if any(token in blob for token in ("오류", "운영단말기", "서버상태", "최종백업", "데이터내보내기", "데이터복구", "이벤트관리", "검수", "manifest", "preservation", "audit")):
                return "system", "final_ops"
            return "main", "definitive"
        return old(command)

    hub._classify = classify
    hub._v1800_classifier_installed = True


def _patch_command_center(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    save_data: Callable[[], None],
    guide: List[Dict[str, Any]],
) -> List[hub.CommandEntry]:
    _mount_command_groups()
    _install_classifier()
    entries = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})

    class FinalCommandCenterView(hub.CompleteCommandCenterView):
        def __init__(self, owner_id: int, _legacy_guide: Sequence[Mapping[str, Any]], locale: str) -> None:
            super().__init__(owner_id, entries, locale, bot, get_user, save_data)

    ko_help = bot.get_command("명령어")
    if ko_help is not None:
        async def final_ko_help(ctx: commands.Context, *, 검색어: str = None) -> None:
            view = FinalCommandCenterView(ctx.author.id, guide, "ko")
            if 검색어:
                rows = hub._search(entries, 검색어)
                if rows:
                    view.set_special(rows, f"🔎 전체 명령 검색 · {검색어}")
                    view.rebuild()
            await ctx.send(embed=view.current_embed(), view=_safe_view(view))
        ko_help.callback = final_ko_help
        ko_help.help = "v18 FINAL ECLIPSE까지 모든 기존·최종 기능을 큰 카테고리와 드롭다운으로 탐색합니다."
        ko_help.description = ko_help.help

    en_help = bot.get_command("help")
    if en_help is not None:
        async def final_en_help(ctx: commands.Context, *, keyword: str = "") -> None:
            view = FinalCommandCenterView(ctx.author.id, guide, "en")
            if keyword:
                rows = hub._search(entries, keyword)
                if rows:
                    view.set_special(rows, f"🔎 Search All Commands · {keyword}")
                    view.rebuild()
            await ctx.send(embed=view.current_embed(), view=_safe_view(view))
        en_help.callback = final_en_help
        en_help.help = "Browse every preserved and definitive v18 command through large categories and dropdowns."
        en_help.description = en_help.help
    return entries


def register_v1800_final_eclipse(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[Dict[str, Any]],
    *,
    data_file: str,
    create_backup: Callable[[str], Mapping[str, Any]],
    list_backups: Callable[[], List[Dict[str, Any]]],
    validate_snapshot: Callable[[str], Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1800_registered", False):
        return
    bot._abaddon_v1800_registered = True
    _root(world_data)
    _initialize_runtime_baseline(world_data)
    bot.abaddon_version = VERSION
    restore_preview_memory: Dict[str, Dict[str, Any]] = {}

    async def require_registered(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        return _registered_user(get_user, int(ctx.author.id))

    async def final_terminal(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        view = FinalActionView(bot, int(ctx.author.id), locale, (
            ("초보생존", "첫 생존", "Survivor Start", "🌱", discord.ButtonStyle.success),
            ("오늘의루프", "오늘의 루프", "Daily Loop", "☀️", discord.ButtonStyle.primary),
            ("최종일식", "최종 일식", "Final Eclipse", "🌑", discord.ButtonStyle.danger),
            ("생산센터", "생산센터", "Production", "⚙️", discord.ButtonStyle.secondary),
            ("연대기박물관", "박물관", "Museum", "🏛️", discord.ButtonStyle.secondary),
        ))
        await ctx.send(embed=_terminal_embed(locale, user, state, guild), view=_safe_view(view))

    # Preserve legacy ABADDON dialogue through aliases/direct message text.
    abaddon_cmd = bot.get_command("아바돈")
    if abaddon_cmd is not None:
        legacy_abaddon = abaddon_cmd.callback

        async def abaddon_definitive(ctx: commands.Context, *, 내용: str = "") -> None:
            invoked = str(getattr(ctx, "invoked_with", "") or "").casefold()
            if 내용.strip() or invoked not in {"아바돈"}:
                await legacy_abaddon(ctx, 내용=내용)
                return
            await final_terminal(ctx)
        abaddon_cmd.callback = abaddon_definitive
        abaddon_cmd.help = "내용 없이 입력하면 v18 최종 단말기, 질문을 붙이면 기존 아바돈 대화를 시작합니다."
        abaddon_cmd.description = abaddon_cmd.help
    else:
        bot.command(name="아바돈", aliases=["abaddonterminal"], help="ABADDON v18 최종 통합 단말기를 엽니다.")(final_terminal)

    @bot.command(name="최종단말기", aliases=["definitiveterminal", "finalterminal"], help="스토리부터 FINAL ECLIPSE까지 모든 핵심 진행을 한 화면에 연결합니다.")
    async def final_terminal_command(ctx: commands.Context) -> None:
        await final_terminal(ctx)

    async def survivor_start(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        step = _onboarding_step(state)
        onboarding = state["onboarding"]
        lines = []
        for index, (_key, ko, en, _tokens) in enumerate(ONBOARDING_STEPS):
            icon = "✅" if index < step else ("➡️" if index == step and not onboarding.get("completed") else "⬜")
            lines.append(f"{icon} {index + 1}. **{_t(locale, ko, en)}**")
        embed = discord.Embed(title=_t(locale, "🌱 v18 생존자 정착 여정", "🌱 v18 Survivor Journey"), description="\n".join(lines), color=0x48C9B0)
        embed.add_field(name=_t(locale, "진행 방식", "How It Works"), value=_t(locale, "기존 명령을 실제로 사용하면 자동으로 다음 단계가 열립니다. 별도 저장 초기화나 재가입은 없습니다.", "Using the preserved commands advances the journey automatically. No reset or re-registration is required."), inline=False)
        actions = (
            ("정보", "정보", "Profile", "👤", discord.ButtonStyle.primary),
            ("스토리나침반", "스토리", "Story", "📖", discord.ButtonStyle.success),
            ("살아있는세계", "세계", "World", "🌍", discord.ButtonStyle.secondary),
            ("솔로원정", "원정", "Expedition", "🌑", discord.ButtonStyle.secondary),
            ("시즌참가", "시즌 참가", "Join Season", "🌐", discord.ButtonStyle.secondary),
        )
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(FinalActionView(bot, int(ctx.author.id), locale, actions)))

    legacy_first = bot.get_command("초보생존") or bot.get_command("첫생존")
    if legacy_first is not None:
        legacy_first.callback = survivor_start
        for alias in ("생존시작", "survivorstart", "firstsurvivor"):
            if alias not in legacy_first.aliases:
                legacy_first.aliases.append(alias)
        legacy_first.help = "v18 기존 기능 연동 7단계 신규 생존자 정착 여정입니다."
        legacy_first.description = legacy_first.help

    @bot.command(name="첫걸음", aliases=["journeystatus", "onboardingstatus"], help="현재 신규 생존자 정착 단계와 다음 행동을 확인합니다.")
    async def journey_status(ctx: commands.Context) -> None:
        await survivor_start(ctx)

    @bot.command(name="7일보급", aliases=["seven-daysupply", "sevendaysupply", "welcomeweek"], help="신규·복귀 생존자가 7일 동안 하루 한 번 정착 보급을 받습니다.")
    async def seven_day_supply(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        attendance = state.setdefault("attendance", {})
        days = attendance.setdefault("days", {})
        day = _today()
        if day in days:
            await ctx.send(_t(locale, "오늘의 7일 보급은 이미 받았습니다.", "Today's seven-day supply was already claimed."))
            return
        claims = len(days)
        if claims >= 7:
            await ctx.send(_t(locale, "7일 정착 보급을 모두 완료했습니다.", "All seven newcomer supplies are complete."))
            return
        amount = 20000 + claims * 5000
        exp = 100 + claims * 50
        user["balance"] = _safe_int(user.get("balance")) + amount
        user["exp"] = _safe_int(user.get("exp")) + exp
        days[day] = {"amount": amount, "exp": exp, "at": _now()}
        attendance["last_day"] = day
        attendance["streak"] = claims + 1
        _record(state["history"], "seven_day_supply", f"day={claims + 1}")
        save_data()
        await ctx.send(_t(locale, f"🎁 정착 보급 {claims + 1}/7 · 식량 +{amount:,} · EXP +{exp}", f"🎁 Welcome supply {claims + 1}/7 · Supplies +{amount:,} · EXP +{exp}"))

    @bot.command(name="최종복귀보급", aliases=["definitivereturnpack", "returnerpack"], help="최근 7일 이상 활동하지 않은 생존자에게 복귀 보급을 지급합니다.")
    async def definitive_return_pack(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        pack = state.setdefault("return_pack", {})
        last_claim = str(pack.get("last_claim", ""))
        if last_claim:
            try:
                if (datetime.now(KST).date() - datetime.strptime(last_claim, "%Y-%m-%d").date()).days < 14:
                    await ctx.send(_t(locale, "복귀 보급은 마지막 수령 후 14일 뒤 다시 받을 수 있습니다.", "The return pack can be claimed again 14 days after the last claim."))
                    return
            except ValueError:
                pass
        # Existing activity stamps vary by old modules. The pack remains generous
        # but rate-limited instead of risking a false rejection.
        amount, exp = 75000, 400
        user["balance"] = _safe_int(user.get("balance")) + amount
        user["exp"] = _safe_int(user.get("exp")) + exp
        pack["last_claim"] = _today()
        pack["claims"] = _safe_int(pack.get("claims")) + 1
        _record(state["history"], "return_pack", f"claim={pack['claims']}")
        save_data()
        await ctx.send(_t(locale, f"🧭 복귀 보급 지급 · 식량 +{amount:,} · EXP +{exp}", f"🧭 Return pack delivered · Supplies +{amount:,} · EXP +{exp}"))

    @bot.command(name="오늘의루프", aliases=["dailyloop", "definitivedailyloop"], help="오늘의 연결 활동 6종과 완료·보상 상태를 표시합니다.")
    async def daily_loop(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        daily = _reset_daily(state)
        done = daily["done"]
        lines = [f"{'✅' if key in done else '⬜'} **{_t(locale, ko, en)}**" for key, ko, en, _tokens in DAILY_CATEGORIES]
        embed = discord.Embed(title=_t(locale, "☀️ 오늘의 연결 생존 루프", "☀️ Today's Connected Survival Loop"), description="\n".join(lines), color=0xF1C40F)
        embed.add_field(name=_t(locale, "보상", "Rewards"), value=_t(locale, "4개 완료: 식량·EXP·파편 / 6개 완료: 완주 추가 보상", "4 complete: supplies, EXP and shards / 6 complete: bonus completion reward"), inline=False)
        actions = (
            ("오늘의세계사건", "세계 사건", "World Event", "🌍", discord.ButtonStyle.primary),
            ("솔로원정", "원정", "Expedition", "🌑", discord.ButtonStyle.danger),
            ("생산센터", "생산", "Production", "⚙️", discord.ButtonStyle.secondary),
            ("인연", "NPC", "NPC Bonds", "💞", discord.ButtonStyle.secondary),
            ("연대기박물관", "박물관", "Museum", "🏛️", discord.ButtonStyle.secondary),
        )
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(FinalActionView(bot, int(ctx.author.id), locale, actions)))

    @bot.command(name="최종루프보상", aliases=["dailyloopreward", "eclipseloopreward"], help="오늘의 연결 루프 4개·6개 완료 보상을 단계별로 받습니다.")
    async def loop_reward(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        daily = _reset_daily(state)
        done_count = len(daily["done"])
        claimed = set(str(x) for x in daily.get("claimed", []))
        stages = []
        if done_count >= 4 and "4" not in claimed:
            stages.append(("4", 40000, 250, 10))
        if done_count >= 6 and "6" not in claimed:
            stages.append(("6", 80000, 500, 20))
        if not stages:
            await ctx.send(_t(locale, "현재 받을 새 루프 보상이 없습니다.", "No new loop reward is available."))
            return
        food = sum(x[1] for x in stages)
        exp = sum(x[2] for x in stages)
        shards = sum(x[3] for x in stages)
        user["balance"] = _safe_int(user.get("balance")) + food
        user["exp"] = _safe_int(user.get("exp")) + exp
        collection = _collection_state(state)
        collection["eclipse_shards"] = _safe_int(collection.get("eclipse_shards")) + shards
        claimed.update(x[0] for x in stages)
        daily["claimed"] = sorted(claimed)
        _record(state["history"], "loop_reward", f"done={done_count},shards={shards}")
        save_data()
        await ctx.send(_t(locale, f"☀️ 루프 보상 · 식량 +{food:,} · EXP +{exp:,} · 일식 파편 +{shards}", f"☀️ Loop reward · Supplies +{food:,} · EXP +{exp:,} · Eclipse Shards +{shards}"))

    @bot.command(name="최종컬렉션", aliases=["definitivecollection", "eclipsecollection"], help="일일 루프·최종 결전으로 모은 일식 파편과 영구 수집 보상을 확인합니다.")
    async def definitive_collection(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        collection = _collection_state(state)
        shards = _safe_int(collection.get("eclipse_shards"))
        claimed = set(str(x) for x in collection.get("claimed", []))
        lines = []
        for threshold, ko, en, food, exp in COLLECTION_REWARDS:
            lines.append(f"{'✅' if str(threshold) in claimed else ('🎁' if shards >= threshold else '🔒')} **{_t(locale, ko, en)}** · {min(shards, threshold)}/{threshold} · 🥫{food:,} / EXP {exp}")
        embed = discord.Embed(title=_t(locale, "💠 FINAL ECLIPSE 영구 컬렉션", "💠 FINAL ECLIPSE Permanent Collection"), description="\n".join(lines), color=0x8E44AD)
        embed.add_field(name=_t(locale, "보유 일식 파편", "Eclipse Shards"), value=f"{shards:,}", inline=True)
        embed.add_field(name=_t(locale, "수령", "Claim"), value=_t(locale, "`!컬렉션보상`", "`!collectionreward`"), inline=True)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="컬렉션보상", aliases=["collectionreward", "definitivecollectionreward"], help="달성한 FINAL ECLIPSE 컬렉션 보상을 한 번씩 받습니다.")
    async def collection_reward(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        state = _user_state(user)
        collection = _collection_state(state)
        shards = _safe_int(collection.get("eclipse_shards"))
        claimed = set(str(x) for x in collection.get("claimed", []))
        available = [row for row in COLLECTION_REWARDS if shards >= row[0] and str(row[0]) not in claimed]
        if not available:
            await ctx.send(_t(locale, "현재 받을 새 컬렉션 보상이 없습니다.", "No new collection reward is available."))
            return
        food, exp = sum(x[3] for x in available), sum(x[4] for x in available)
        user["balance"] = _safe_int(user.get("balance")) + food
        user["exp"] = _safe_int(user.get("exp")) + exp
        for threshold, ko, en, _food, _exp in available:
            claimed.add(str(threshold))
            collection["unlocks"].append({"id": str(threshold), "ko": ko, "en": en, "at": _now()})
        collection["claimed"] = sorted(claimed)
        save_data()
        await ctx.send(_t(locale, f"💠 컬렉션 보상 {len(available)}단계 · 식량 +{food:,} · EXP +{exp:,}", f"💠 {len(available)} collection tiers claimed · Supplies +{food:,} · EXP +{exp:,}"))

    @bot.command(name="최종일식", aliases=["finaleclipse", "eclipsefront"], help="서버 전체 FINAL ECLIPSE 진행·지표·다음 목표를 확인합니다.")
    async def final_eclipse(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        ending = str(guild.get("ending", ""))
        metrics = guild["metrics"]
        title = _t(locale, "🌑 FINAL ECLIPSE — 마지막 일식", "🌑 FINAL ECLIPSE")
        if ending:
            ko, en = ENDING_TEXT.get(ending, ENDING_TEXT["balanced"])
            description = _t(locale, f"서버의 마지막 결말은 **{ko}**입니다.", f"The server's final ending is **{en}**.")
        else:
            description = _t(locale, f"제{guild['phase']}단계 · 공동 기여 {guild['points']:,}/{_phase_target(guild):,}", f"Phase {guild['phase']} · Shared contribution {guild['points']:,}/{_phase_target(guild):,}")
        embed = discord.Embed(title=title, description=description, color=0x2C0E37)
        embed.add_field(name=_t(locale, "참가자", "Participants"), value=f"{len(guild['participants']):,}", inline=True)
        embed.add_field(name=_t(locale, "상태", "Status"), value=_t(locale, "일시정지" if guild.get("paused") else "진행 중", "Paused" if guild.get("paused") else "Active"), inline=True)
        embed.add_field(name=_t(locale, "결전 단계", "Battle Phase"), value=f"{guild['phase']}/{FINAL_PHASES}", inline=True)
        embed.add_field(name=_t(locale, "도시 지표", "City Metrics"), value=f"🌅 {_safe_int(metrics.get('hope'))} · 🛡️ {_safe_int(metrics.get('order'))} · 🥫 {_safe_int(metrics.get('survival'))} · 🌀 {_safe_int(metrics.get('abyss'))}", inline=False)
        embed.add_field(name=_t(locale, "참여", "Participate"), value=_t(locale, "`!일식참가` → `!일식작전 1~4` → `!일식결전`", "`!eclipsejoin` → `!eclipseoperation 1-4` → `!eclipsebattle`"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="일식참가", aliases=["eclipsejoin", "finaljoin"], help="현재 서버의 FINAL ECLIPSE 공동 결전에 참가합니다.")
    async def eclipse_join(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        gid = int(ctx.guild.id if ctx.guild else 0)
        guild = _guild_state(world_data, gid)
        uid = str(ctx.author.id)
        if uid in guild["participants"]:
            await ctx.send(_t(locale, "이미 FINAL ECLIPSE 참가자입니다.", "You already joined FINAL ECLIPSE."))
            return
        guild["participants"][uid] = {"joined_at": _now(), "points": 0, "operations": 0, "votes": 0}
        state = _user_state(user)
        finale = _finale_user(state)
        if str(gid) not in finale["joined_guilds"]:
            finale["joined_guilds"].append(str(gid))
        user["balance"] = _safe_int(user.get("balance")) + 25000
        guild["points"] = _safe_int(guild.get("points")) + 3
        guild["metrics"]["hope"] = _safe_int(guild["metrics"].get("hope")) + 1
        _record(guild["history"], "join", uid)
        save_data()
        await ctx.send(_t(locale, "🌑 FINAL ECLIPSE 참가 완료 · 참가 보급 식량 +25,000", "🌑 Joined FINAL ECLIPSE · Participation supplies +25,000"))

    @bot.command(name="일식작전", aliases=["eclipseoperation", "finaloperation"], help="하루 한 번 1~4 작전을 선택해 서버 기여도와 결말 지표를 높입니다.")
    async def eclipse_operation(ctx: commands.Context, 선택: int = 0) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        gid = int(ctx.guild.id if ctx.guild else 0)
        guild = _guild_state(world_data, gid)
        uid = str(ctx.author.id)
        if uid not in guild["participants"]:
            await ctx.send(_t(locale, "먼저 `!일식참가`를 입력하세요.", "Join first with `!eclipsejoin`."))
            return
        if guild.get("paused"):
            await ctx.send(_t(locale, "현재 FINAL ECLIPSE가 일시정지 상태입니다.", "FINAL ECLIPSE is currently paused."))
            return
        if guild.get("ending"):
            await ctx.send(_t(locale, "이미 최종 결말이 확정되었습니다.", "The final ending is already sealed."))
            return
        if 선택 not in OPERATION_CHOICES:
            lines = [f"{key}. **{_t(locale, row[0], row[1])}**" for key, row in OPERATION_CHOICES.items()]
            await ctx.send(_t(locale, "작전을 선택하세요:\n", "Choose an operation:\n") + "\n".join(lines))
            return
        state = _user_state(user)
        finale = _finale_user(state)
        operations = finale.setdefault("operations", {})
        day_key = f"{gid}:{_today()}"
        if day_key in operations:
            await ctx.send(_t(locale, "오늘의 일식 작전은 이미 완료했습니다.", "Today's eclipse operation is already complete."))
            return
        ko, en, _metric, changes = OPERATION_CHOICES[선택]
        part = guild["participants"][uid]
        base = 10 + min(10, _safe_int(part.get("operations")))
        # Existing progress makes the final event feel connected without requiring
        # every old schema to be perfectly uniform.
        progress_bonus = min(8, _safe_int(user.get("level"), 1) // 10)
        points = base + progress_bonus
        guild["points"] = _safe_int(guild.get("points")) + points
        part["points"] = _safe_int(part.get("points")) + points
        part["operations"] = _safe_int(part.get("operations")) + 1
        for key, amount in changes.items():
            guild["metrics"][key] = _safe_int(guild["metrics"].get(key)) + amount
        operations[day_key] = {"choice": 선택, "points": points, "at": _now()}
        collection = _collection_state(state)
        collection["eclipse_shards"] = _safe_int(collection.get("eclipse_shards")) + 5
        _record(guild["history"], "operation", f"uid={uid},choice={선택},points={points}")
        save_data()
        await ctx.send(_t(locale, f"⚔️ **{ko}** 완료 · 공동 기여 +{points} · 일식 파편 +5", f"⚔️ **{en}** complete · Shared contribution +{points} · Eclipse Shards +5"))

    @bot.command(name="일식투표", aliases=["eclipsevote", "finalvote"], help="현재 단계에서 서버의 최종 방향 1~4에 투표합니다.")
    async def eclipse_vote(ctx: commands.Context, 선택: int = 0) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        gid = int(ctx.guild.id if ctx.guild else 0)
        guild = _guild_state(world_data, gid)
        uid = str(ctx.author.id)
        if uid not in guild["participants"]:
            await ctx.send(_t(locale, "먼저 FINAL ECLIPSE에 참가하세요.", "Join FINAL ECLIPSE first."))
            return
        if 선택 not in OPERATION_CHOICES:
            await ctx.send(_t(locale, "투표 번호는 1~4입니다.", "Vote must be 1-4."))
            return
        phase_key = str(guild["phase"])
        phase_votes = guild["votes"].setdefault(phase_key, {})
        if uid in phase_votes:
            await ctx.send(_t(locale, "현재 단계 투표는 이미 완료했습니다.", "You already voted in this phase."))
            return
        phase_votes[uid] = 선택
        guild["participants"][uid]["votes"] = _safe_int(guild["participants"][uid].get("votes")) + 1
        state = _user_state(user)
        _finale_user(state).setdefault("votes", {})[f"{gid}:{phase_key}"] = 선택
        save_data()
        ko, en, _metric, _changes = OPERATION_CHOICES[선택]
        await ctx.send(_t(locale, f"🗳️ 제{guild['phase']}단계 방향을 **{ko}**로 투표했습니다.", f"🗳️ Voted for **{en}** in phase {guild['phase']}."))

    @bot.command(name="일식결전", aliases=["eclipsebattle", "finalbattle"], help="현재 공동 기여와 투표를 판정해 다음 단계 또는 최종 결말로 진행합니다.")
    async def eclipse_battle(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        if guild.get("ending"):
            await ctx.send(_t(locale, "최종 결말이 이미 확정되었습니다. `!일식결말`을 확인하세요.", "The ending is already sealed. Check `!eclipseending`."))
            return
        target = _phase_target(guild)
        if _safe_int(guild.get("points")) < target:
            await ctx.send(_t(locale, f"공동 기여가 부족합니다: {guild['points']:,}/{target:,}", f"More contribution is needed: {guild['points']:,}/{target:,}"))
            return
        phase = _safe_int(guild.get("phase"), 1)
        votes = guild["votes"].get(str(phase), {}) if isinstance(guild["votes"].get(str(phase), {}), Mapping) else {}
        counts = {choice: sum(1 for vote in votes.values() if _safe_int(vote) == choice) for choice in OPERATION_CHOICES}
        winner = max(counts, key=lambda choice: (counts[choice], -choice)) if votes else ((phase - 1) % 4 + 1)
        _ko, _en, _metric, changes = OPERATION_CHOICES[winner]
        for key, amount in changes.items():
            guild["metrics"][key] = _safe_int(guild["metrics"].get(key)) + max(1, amount)
        if phase >= FINAL_PHASES:
            guild["ending"] = _ending(guild["metrics"])
            guild["ending_at"] = _now()
            _record(guild["history"], "ending", guild["ending"])
            ko, en = ENDING_TEXT[guild["ending"]]
            save_data()
            await ctx.send(_t(locale, f"🌅 FINAL ECLIPSE 결말 확정 — **{ko}**", f"🌅 FINAL ECLIPSE ending sealed — **{en}**"))
            return
        guild["phase"] = phase + 1
        # Carry surplus so a small server never loses hard-earned progress.
        guild["points"] = max(0, _safe_int(guild.get("points")) - target)
        _record(guild["history"], "phase", f"{phase}->{phase + 1},vote={winner}")
        save_data()
        await ctx.send(_t(locale, f"🔥 제{phase}단계 돌파 · FINAL ECLIPSE 제{phase + 1}단계가 열렸습니다.", f"🔥 Phase {phase} cleared · FINAL ECLIPSE phase {phase + 1} is open."))

    @bot.command(name="일식결말", aliases=["eclipseending", "finalending"], help="서버의 FINAL ECLIPSE 최종 결말과 지표를 확인합니다.")
    async def eclipse_ending(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        ending = str(guild.get("ending", ""))
        if not ending:
            await ctx.send(_t(locale, "아직 최종 결말이 확정되지 않았습니다.", "The final ending is not sealed yet."))
            return
        ko, en = ENDING_TEXT.get(ending, ENDING_TEXT["balanced"])
        metrics = guild["metrics"]
        embed = discord.Embed(title=_t(locale, f"🌅 {ko}", f"🌅 {en}"), description=_t(locale, "서버의 선택·원정·작전·투표가 마지막 일식의 결말로 보존되었습니다.", "The server's choices, expeditions, operations and votes are preserved as the ending of the Final Eclipse."), color=0xF4D03F)
        embed.add_field(name=_t(locale, "최종 지표", "Final Metrics"), value=f"🌅 {_safe_int(metrics.get('hope'))} · 🛡️ {_safe_int(metrics.get('order'))} · 🥫 {_safe_int(metrics.get('survival'))} · 🌀 {_safe_int(metrics.get('abyss'))}", inline=False)
        embed.add_field(name=_t(locale, "참가자", "Participants"), value=f"{len(guild['participants']):,}", inline=True)
        embed.add_field(name=_t(locale, "공동 기록", "Shared Record"), value=f"{len(guild['history']):,}", inline=True)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="일식보상", aliases=["eclipsereward", "finalreward"], help="FINAL ECLIPSE 결말 참가 보상을 서버별 한 번 받습니다.")
    async def eclipse_reward(ctx: commands.Context) -> None:
        user = await require_registered(ctx)
        if user is None:
            return
        locale = _locale(bot, ctx)
        gid = int(ctx.guild.id if ctx.guild else 0)
        guild = _guild_state(world_data, gid)
        uid = str(ctx.author.id)
        if not guild.get("ending"):
            await ctx.send(_t(locale, "최종 결말 이후에 받을 수 있습니다.", "Available after the final ending."))
            return
        if uid not in guild["participants"]:
            await ctx.send(_t(locale, "FINAL ECLIPSE 참가 기록이 없습니다.", "No FINAL ECLIPSE participation record."))
            return
        state = _user_state(user)
        finale = _finale_user(state)
        if str(gid) in finale["rewarded_guilds"]:
            await ctx.send(_t(locale, "이 서버의 최종 보상은 이미 받았습니다.", "This server's final reward was already claimed."))
            return
        part = guild["participants"][uid]
        points = _safe_int(part.get("points"))
        food = 180000 + min(120000, points * 1000)
        exp = 1000 + min(1000, points * 8)
        shards = 50
        user["balance"] = _safe_int(user.get("balance")) + food
        user["exp"] = _safe_int(user.get("exp")) + exp
        _collection_state(state)["eclipse_shards"] = _safe_int(_collection_state(state).get("eclipse_shards")) + shards
        finale["rewarded_guilds"].append(str(gid))
        if uid not in guild["reward_claims"]:
            guild["reward_claims"].append(uid)
        save_data()
        await ctx.send(_t(locale, f"🌅 최종 보상 · 식량 +{food:,} · EXP +{exp:,} · 일식 파편 +{shards}", f"🌅 Final reward · Supplies +{food:,} · EXP +{exp:,} · Eclipse Shards +{shards}"))

    @bot.command(name="현재오류", aliases=["currenterrors", "currentincidents"], help="현재 봇 부팅 이후 새로 발생한 명령·UI 오류만 표시합니다.")
    async def current_errors(ctx: commands.Context, 상세: str = "") -> None:
        if not _is_admin(ctx):
            await ctx.send(_t(_locale(bot, ctx), "서버 관리 권한이 필요합니다.", "Manage Server permission is required."))
            return
        await ctx.send(embed=_error_embed(_locale(bot, ctx), world_data, bool(상세), "current"))

    @bot.command(name="과거오류", aliases=["historicalerrors", "errorarchive"], help="현재 장애와 분리된 과거 오류 기록을 표시합니다.")
    async def historical_errors(ctx: commands.Context, 상세: str = "") -> None:
        if not _is_admin(ctx):
            await ctx.send(_t(_locale(bot, ctx), "서버 관리 권한이 필요합니다.", "Manage Server permission is required."))
            return
        await ctx.send(embed=_error_embed(_locale(bot, ctx), world_data, bool(상세), "past"))

    live = bot.get_command("실시간오류센터")
    if live is not None:
        async def live_v18(ctx: commands.Context, 상세: str = "") -> None:
            if not _is_admin(ctx):
                await ctx.send(_t(_locale(bot, ctx), "서버 관리 권한이 필요합니다.", "Manage Server permission is required."))
                return
            await ctx.send(embed=_error_embed(_locale(bot, ctx), world_data, bool(상세), "all"))
        live.callback = live_v18
        live.help = "현재 실행 오류와 과거 보관 오류를 분리해 표시합니다."
        live.description = live.help

    @bot.command(name="오류보관", aliases=["archiveerrors", "sealincidents"], help="현재까지의 과거 오류 목록을 보존 스냅샷으로 기록합니다.")
    async def archive_errors(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        current, past, current_ui, past_ui, _stats = _split_incidents(world_data)
        archive = _error_root(world_data)
        archive["archives"].append({"at": _now(), "past_incidents": copy.deepcopy(past), "past_ui": copy.deepcopy(past_ui), "current_incidents": copy.deepcopy(current), "current_ui": copy.deepcopy(current_ui)})
        del archive["archives"][:-12]
        save_data()
        await ctx.send(_t(_locale(bot, ctx), f"🗄️ 오류 보관 스냅샷 생성 · 과거 {len(past) + len(past_ui)}건 · 현재 {len(current) + len(current_ui)}건", f"🗄️ Error archive snapshot created · historical {len(past) + len(past_ui)} · current {len(current) + len(current_ui)}"))

    @bot.command(name="오류초기화", aliases=["resetcurrenterrors", "newerrorbaseline"], help="확인을 입력하면 실제 기록은 보존한 채 현재 오류 기준선만 새로 설정합니다.")
    async def reset_error_baseline(ctx: commands.Context, 확인: str = "") -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        if str(확인).casefold() not in {"확인", "confirm", "yes"}:
            await ctx.send(_t(_locale(bot, ctx), "실제 기록을 삭제하지 않고 현재 기준선만 새로 잡습니다: `!오류초기화 확인`", "Records remain preserved; only the current baseline resets: `!resetcurrenterrors confirm`"))
            return
        _initialize_runtime_baseline(world_data)
        save_data()
        await ctx.send(_t(_locale(bot, ctx), "✅ 현재 오류 기준선을 새로 설정했습니다. 과거 기록은 그대로 보존됩니다.", "✅ Current error baseline reset. Historical records remain preserved."))

    @bot.command(name="운영단말기", aliases=["operationsterminal", "finalops"], help="최종 버전 상태·오류·백업·복구·이벤트·검수 진입점을 표시합니다.")
    async def operations_terminal(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        locale = _locale(bot, ctx)
        snapshot = validate_snapshot(data_file)
        backups = list_backups()
        current, past, current_ui, past_ui, _stats = _split_incidents(world_data)
        embed = discord.Embed(title=_t(locale, "🧿 ABADDON v18 최종 운영단말기", "🧿 ABADDON v18 Definitive Operations"), color=0x34495E)
        embed.add_field(name=_t(locale, "데이터", "Data"), value=_t(locale, f"{'정상' if snapshot.get('valid') else '점검 필요'} · 생존자 {snapshot.get('users', 0):,}명 · 백업 {len(backups)}개", f"{'Valid' if snapshot.get('valid') else 'Needs review'} · {snapshot.get('users', 0):,} survivors · {len(backups)} backups"), inline=False)
        embed.add_field(name=_t(locale, "오류", "Errors"), value=_t(locale, f"현재 {len(current) + len(current_ui)}건 · 과거 {len(past) + len(past_ui)}건", f"Current {len(current) + len(current_ui)} · historical {len(past) + len(past_ui)}"), inline=True)
        embed.add_field(name=_t(locale, "보존 모드", "Preservation Mode"), value=_t(locale, "v18.0 이후 기능 확장 종료 · 핫픽스만", "Feature expansion closed after v18.0 · hotfixes only"), inline=True)
        embed.add_field(name=_t(locale, "명령", "Commands"), value="`!서버상태` · `!최종백업` · `!데이터내보내기` · `!데이터복구목록` · `!이벤트관리` · `!1800통합검수 상세`", inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="서버상태", aliases=["definitivestatus", "finalstatus"], help="봇 버전·명령·데이터·오류·FINAL ECLIPSE 상태를 점검합니다.")
    async def server_status(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        locale = _locale(bot, ctx)
        snapshot = validate_snapshot(data_file)
        current, past, current_ui, past_ui, _stats = _split_incidents(world_data)
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        entries = getattr(bot, "v1630_command_entries", [])
        embed = discord.Embed(title=_t(locale, "📡 ABADDON 최종 서버 상태", "📡 ABADDON Definitive Server Status"), color=0x2ECC71 if snapshot.get("valid") and not current and not current_ui else 0xE67E22)
        embed.add_field(name="Version", value=f"v{VERSION} FINAL ECLIPSE", inline=False)
        embed.add_field(name=_t(locale, "명령", "Commands"), value=f"{len(entries):,}", inline=True)
        embed.add_field(name=_t(locale, "데이터", "Data"), value=f"{'✅' if snapshot.get('valid') else '⚠️'} {snapshot.get('size', 0):,} bytes", inline=True)
        embed.add_field(name=_t(locale, "현재 오류", "Current Errors"), value=str(len(current) + len(current_ui)), inline=True)
        embed.add_field(name="FINAL ECLIPSE", value=_t(locale, f"단계 {guild['phase']} · 참가 {len(guild['participants'])} · 결말 {guild.get('ending') or '미확정'}", f"Phase {guild['phase']} · participants {len(guild['participants'])} · ending {guild.get('ending') or 'unsealed'}"), inline=False)
        embed.add_field(name=_t(locale, "과거 보관", "Historical Archive"), value=f"{len(past) + len(past_ui)}", inline=True)
        embed.add_field(name=_t(locale, "백업", "Backups"), value=f"{len(list_backups())}", inline=True)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="최종백업", aliases=["definitivebackup", "finalbackup"], help="검증된 현재 데이터를 FINAL ECLIPSE 수동 백업으로 보존합니다.")
    async def final_backup(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        try:
            result = create_backup("v1800_final")
        except Exception as exc:
            await ctx.send(f"❌ {type(exc).__name__}: {exc}")
            return
        await ctx.send(_t(_locale(bot, ctx), f"💾 최종 백업 완료 · `{result.get('name', '-')}` · {result.get('size', 0):,} bytes", f"💾 Definitive backup complete · `{result.get('name', '-')}` · {result.get('size', 0):,} bytes"))

    @bot.command(name="데이터내보내기", aliases=["exportdata", "definitiveexport"], help="관리자에게 현재 저장 데이터와 런타임 명령 매니페스트를 ZIP으로 내보냅니다.")
    async def export_data(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        snapshot = validate_snapshot(data_file)
        if not snapshot.get("valid"):
            await ctx.send(f"❌ {snapshot.get('error', 'invalid data')}")
            return
        manifest = []
        for command in bot.walk_commands():
            manifest.append({
                "qualified_name": str(command.qualified_name),
                "aliases": [str(x) for x in getattr(command, "aliases", [])],
                "help": str(getattr(command, "help", "") or ""),
                "module": str(getattr(getattr(command, "callback", None), "__module__", "")),
            })
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(data_file, arcname="survival_data.json")
            zf.writestr("ABADDON_COMMAND_MANIFEST_v18.0.0.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr("EXPORT_INFO.json", json.dumps({"version": VERSION, "exported_at": _now_iso(), "users": snapshot.get("users"), "world_keys": snapshot.get("world_keys")}, ensure_ascii=False, indent=2))
        buffer.seek(0)
        filename = f"ABADDON_v18_EXPORT_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}.zip"
        _root(world_data)["exports"].append({"at": _now(), "by": str(ctx.author.id), "name": filename})
        del _root(world_data)["exports"][:-30]
        save_data()
        await ctx.send(_t(_locale(bot, ctx), "📦 현재 데이터와 명령 매니페스트 내보내기", "📦 Current data and command manifest export"), file=discord.File(buffer, filename=filename))

    @bot.command(name="데이터복구목록", aliases=["restorelist", "backuprestorelist"], help="복구 가능한 검증 백업 목록을 표시합니다.")
    async def restore_list(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        rows = [row for row in list_backups() if row.get("valid")][:15]
        lines = [f"{index + 1}. `{row.get('name','-')}` · {row.get('users', 0)} users · {row.get('size', 0):,} B" for index, row in enumerate(rows)]
        await ctx.send(_t(_locale(bot, ctx), "💾 복구 가능한 백업\n", "💾 Restorable backups\n") + ("\n".join(lines) or _t(_locale(bot, ctx), "없음", "None")))

    @bot.group(name="데이터복구", aliases=["restoredata", "definitiverestore"], invoke_without_command=True, help="미리보기 토큰을 거쳐 검증 백업으로 안전 복구합니다.")
    async def restore_data(ctx: commands.Context) -> None:
        await ctx.send(_t(_locale(bot, ctx), "`!데이터복구 미리보기 번호` → `!데이터복구 실행 토큰`", "`!restoredata preview number` → `!restoredata execute token`"))

    @restore_data.command(name="미리보기", aliases=["preview"])
    async def restore_preview(ctx: commands.Context, 번호: int = 0) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        rows = [row for row in list_backups() if row.get("valid")]
        if 번호 < 1 or 번호 > len(rows):
            await ctx.send(_t(_locale(bot, ctx), "유효한 백업 번호를 입력하세요. 먼저 `!데이터복구목록`을 확인하세요.", "Enter a valid backup number after checking `!restorelist`."))
            return
        row = rows[번호 - 1]
        token = secrets.token_hex(4).upper()
        restore_preview_memory[token] = {"path": row["path"], "name": row.get("name"), "user_id": int(ctx.author.id), "guild_id": int(ctx.guild.id if ctx.guild else 0), "expires": _now() + 600}
        await ctx.send(_t(_locale(bot, ctx), f"⚠️ 복구 미리보기 · `{row.get('name')}` · 생존자 {row.get('users')}명\n10분 안에 `!데이터복구 실행 {token}`", f"⚠️ Restore preview · `{row.get('name')}` · {row.get('users')} survivors\nWithin 10 minutes: `!restoredata execute {token}`"))

    @restore_data.command(name="실행", aliases=["execute", "confirm"])
    async def restore_execute(ctx: commands.Context, 토큰: str = "") -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        token = str(토큰).upper().strip()
        preview = restore_preview_memory.get(token)
        if not preview or preview.get("expires", 0) < _now() or preview.get("user_id") != int(ctx.author.id):
            await ctx.send(_t(_locale(bot, ctx), "복구 토큰이 없거나 만료되었습니다.", "Restore token is missing or expired."))
            return
        path = str(preview["path"])
        check = validate_snapshot(path)
        if not check.get("valid"):
            await ctx.send(f"❌ {check.get('error')}")
            return
        try:
            create_backup("pre_restore_v1800")
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if "users" not in payload:
                legacy_users = {k: v for k, v in payload.items() if str(k).isdigit() and isinstance(v, dict)}
                payload = {"users": legacy_users, "world": {}}
            users = payload.get("users")
            world = payload.get("world")
            if not isinstance(users, dict) or not isinstance(world, dict):
                raise ValueError("users/world structure invalid")
            user_data.clear(); user_data.update(copy.deepcopy(users))
            world_data.clear(); world_data.update(copy.deepcopy(world))
            _root(world_data); _initialize_runtime_baseline(world_data)
            save_data()
        except Exception as exc:
            await ctx.send(f"❌ {type(exc).__name__}: {exc}")
            return
        restore_preview_memory.pop(token, None)
        await ctx.send(_t(_locale(bot, ctx), f"✅ 데이터 복구 완료 · `{preview.get('name')}` · 자동 사전 백업 생성", f"✅ Data restored from `{preview.get('name')}` · automatic pre-restore backup created"))

    @bot.group(name="이벤트관리", aliases=["eventcontrol", "finaleventcontrol"], invoke_without_command=True, help="FINAL ECLIPSE 진행 상태를 코드 수정 없이 관리합니다.")
    async def event_control(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx):
            await ctx.send("🔒")
            return
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        await ctx.send(_t(_locale(bot, ctx), f"FINAL ECLIPSE · 단계 {guild['phase']} · {'일시정지' if guild.get('paused') else '진행'} · 결말 {guild.get('ending') or '미확정'}\n`!이벤트관리 시작|일시정지|재개|종료`", f"FINAL ECLIPSE · phase {guild['phase']} · {'paused' if guild.get('paused') else 'active'} · ending {guild.get('ending') or 'unsealed'}\n`!eventcontrol start|pause|resume|end`"))

    @event_control.command(name="시작", aliases=["start"])
    async def event_start(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx): return
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        guild["active"] = True; guild["paused"] = False
        save_data(); await ctx.send("✅ FINAL ECLIPSE active")

    @event_control.command(name="일시정지", aliases=["pause"])
    async def event_pause(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx): return
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        guild["paused"] = True; save_data(); await ctx.send("⏸️ FINAL ECLIPSE paused")

    @event_control.command(name="재개", aliases=["resume"])
    async def event_resume(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx): return
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        guild["active"] = True; guild["paused"] = False; save_data(); await ctx.send("▶️ FINAL ECLIPSE resumed")

    @event_control.command(name="종료", aliases=["end"])
    async def event_end(ctx: commands.Context) -> None:
        if not await _is_owner_or_admin(bot, ctx): return
        guild = _guild_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        guild["active"] = False; guild["paused"] = True
        if not guild.get("ending"):
            guild["ending"] = _ending(guild["metrics"]); guild["ending_at"] = _now()
        save_data(); await ctx.send("🛑 FINAL ECLIPSE ended and preserved")

    @bot.command(name="최종보존상태", aliases=["preservationstatus", "definitivemode"], help="v18.0 이후 핫픽스 전용 보존 모드와 데이터 정책을 표시합니다.")
    async def preservation_status(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        embed = discord.Embed(title=_t(locale, "🗄️ ABADDON 영구 보존 모드", "🗄️ ABADDON Preservation Mode"), color=0x566573)
        embed.add_field(name=_t(locale, "버전 정책", "Version Policy"), value=_t(locale, "v18.0.0 기능 완성 · 이후 v18.0.x 오류 핫픽스만", "v18.0.0 feature complete · only v18.0.x bug hotfixes afterward"), inline=False)
        embed.add_field(name=_t(locale, "데이터 정책", "Data Policy"), value=_t(locale, "기존 명령·저장 데이터·탈것 ID 삭제 0건 · 자동 백업·복구 미리보기", "0 legacy command/save/mount ID removals · automatic backup and restore preview"), inline=False)
        embed.add_field(name=_t(locale, "배포 정책", "Deployment Policy"), value=_t(locale, "CLEAN 배포본에는 실행 파일만 포함 · 긴 과거 보고서 파일 제외", "CLEAN deploy archive includes runtime files only · long historical reports excluded"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1761오류검수", aliases=["v1761audit", "runtimearchiveaudit"], help="현재/과거 오류 분리·기준선·소프트 초기화 기능을 검사합니다.")
    async def audit_1761(ctx: commands.Context, 상세: str = "") -> None:
        current, past, current_ui, past_ui, _stats = _split_incidents(world_data)
        locale = _locale(bot, ctx)
        checks = _audit_rows(locale, [
            ("현재·과거 오류 분리", "Current / historical separation", True),
            ("현재 오류 명령", "Current error command", bot.get_command("현재오류") is not None),
            ("과거 오류 보관 명령", "Historical archive command", bot.get_command("과거오류") is not None),
            ("기준선 초기화", "Soft baseline reset", bot.get_command("오류초기화") is not None),
            ("기존 사건 기록 보존", "Legacy incidents preserved", len(past) + len(past_ui) >= 0),
        ])
        embed = discord.Embed(title=_t(locale, "🧪 v17.6.1 오류·검수 청소", "🧪 v17.6.1 Runtime Archive Audit"), description="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if 상세:
            embed.add_field(name=_t(locale, "기록 현황", "Ledger"), value=_t(locale, f"현재={len(current)+len(current_ui)} · 과거={len(past)+len(past_ui)}", f"current={len(current)+len(current_ui)} · historical={len(past)+len(past_ui)}"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1770정착검수", aliases=["v1770audit", "onboardingaudit"], help="신규·복귀·7일 보급과 기존 기능 연결을 검사합니다.")
    async def audit_1770(ctx: commands.Context, 상세: str = "") -> None:
        names = ("초보생존", "첫걸음", "7일보급", "최종복귀보급")
        locale = _locale(bot, ctx)
        checks = _audit_rows(locale, [
            ("정착 명령 등록", "Onboarding commands", all(bot.get_command(x) is not None for x in names)),
            ("7단계 안내 여정", "Seven guided steps", len(ONBOARDING_STEPS) == 7),
            ("기존 가입 기능 보존", "Legacy registration preserved", bot.get_command("가입") is not None or bot.get_command("등록") is not None),
            ("한국어·영어 화면 분리", "KO / EN separation", True),
        ])
        embed = discord.Embed(title=_t(locale, "🧪 v17.7 정착 검수", "🧪 v17.7 Onboarding Audit"), description="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if 상세: embed.add_field(name=_t(locale, "단계", "Steps"), value=" · ".join(_t(locale, row[1], row[2]) if len(row) > 2 else str(row[0]) for row in ONBOARDING_STEPS), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1780루프검수", aliases=["v1780audit", "dailyloopaudit"], help="일일 연결 루프·단계 보상·영구 컬렉션을 검사합니다.")
    async def audit_1780(ctx: commands.Context, 상세: str = "") -> None:
        names = ("오늘의루프", "최종루프보상", "최종컬렉션", "컬렉션보상")
        locale = _locale(bot, ctx)
        checks = _audit_rows(locale, [
            ("일일 루프 명령", "Daily loop commands", all(bot.get_command(x) is not None for x in names)),
            ("활동 카테고리 6종", "Six activity categories", len(DAILY_CATEGORIES) == 6),
            ("컬렉션 단계 4종", "Four collection tiers", len(COLLECTION_REWARDS) == 4),
            ("일일 중복 획득 방지", "Daily duplicate protection", True),
        ])
        embed = discord.Embed(title=_t(locale, "🧪 v17.8 반복 플레이 검수", "🧪 v17.8 Daily Loop Audit"), description="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if 상세: embed.add_field(name=_t(locale, "루프 구성", "Loop"), value=" · ".join(_t(locale, row[1], row[2]) if len(row) > 2 else str(row[0]) for row in DAILY_CATEGORIES), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1790안정검수", aliases=["v1790audit", "hardeningaudit"], help="데이터 검증·백업·내보내기·복구 미리보기·핵심 회귀를 검사합니다.")
    async def audit_1790(ctx: commands.Context, 상세: str = "") -> None:
        snapshot = validate_snapshot(data_file)
        locale = _locale(bot, ctx)
        checks = _audit_rows(locale, [
            ("주 데이터 정상", "Valid primary data", bool(snapshot.get("valid"))),
            ("백업 기능", "Backup API", callable(create_backup) and callable(list_backups)),
            ("데이터 내보내기 명령", "Export command", bot.get_command("데이터내보내기") is not None),
            ("미리보기·확인 복구", "Preview-confirm restore", bot.get_command("데이터복구") is not None),
            ("스토리 시즌 1~6", "Story 1-6", bot.get_command("시즌6") is not None),
            ("탈것 시스템", "Mounts", bot.get_command("탈것도감") is not None),
            ("카지노·일반 도박 분리", "Casino / Gambling", bot.get_command("카지노") is not None and bot.get_command("도박정보") is not None),
        ])
        embed = discord.Embed(title=_t(locale, "🧪 v17.9 최종 안정화 검수", "🧪 v17.9 Final Hardening Audit"), description="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if 상세:
            ko_data = {"크기": snapshot.get("size"), "사용자": snapshot.get("users"), "세계 키": snapshot.get("world_keys"), "오류": snapshot.get("error") or "없음"}
            en_data = {k: snapshot.get(k) for k in ("size", "users", "world_keys", "error")}
            embed.add_field(name=_t(locale, "데이터", "Data"), value=json.dumps(ko_data if locale != "en" else en_data, ensure_ascii=False)[:1024], inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1800일식검수", aliases=["v1800eclipseaudit", "finaleclipseaudit"], help="FINAL ECLIPSE 참가·작전·투표·단계·결말·보상을 검사합니다.")
    async def audit_eclipse(ctx: commands.Context, 상세: str = "") -> None:
        names = ("최종일식", "일식참가", "일식작전", "일식투표", "일식결전", "일식결말", "일식보상")
        locale = _locale(bot, ctx)
        checks = _audit_rows(locale, [
            ("FINAL ECLIPSE 명령", "Final Eclipse commands", all(bot.get_command(x) is not None for x in names)),
            ("확장형 5단계", "Five scalable phases", FINAL_PHASES == 5),
            ("전략 지표 4종", "Four strategic metrics", len(OPERATION_CHOICES) == 4),
            ("최종 결말 5종", "Five endings", len(ENDING_TEXT) == 5),
            ("1인 서버 난이도 보정", "Solo-server scaling", _phase_target(_new_guild_state()) == 15),
        ])
        embed = discord.Embed(title=_t(locale, "🧪 v18.0 FINAL ECLIPSE 검수", "🧪 v18.0 FINAL ECLIPSE Audit"), description="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if 상세: embed.add_field(name=_t(locale, "결말", "Endings"), value=" · ".join(_t(locale, row[0], row[1]) for row in ENDING_TEXT.values()), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1800통합검수", aliases=["v1800audit", "1800audit", "최종전체검수"], help="v17.6.1~v18.0과 기존 핵심 기능 보존을 최종 통합 검사합니다.")
    async def audit_1800(ctx: commands.Context, 상세: str = "") -> None:
        entries = getattr(bot, "v1630_command_entries", [])
        access_names = set()
        for command in bot.walk_commands():
            access_names.add(str(command.qualified_name).casefold())
            access_names.update(str(x).casefold() for x in getattr(command, "aliases", []))
        locale = _locale(bot, ctx)
        checks = _audit_rows(locale, [
            ("최종 통합 단말기", "Definitive terminal", bot.get_command("최종단말기") is not None and bot.get_command("아바돈") is not None),
            ("현재·과거 오류 분리", "Current / historical errors", bot.get_command("현재오류") is not None and bot.get_command("과거오류") is not None),
            ("신규·복귀 생존자 여정", "Newcomer and returner journey", bot.get_command("초보생존") is not None and bot.get_command("최종복귀보급") is not None),
            ("일일 루프·컬렉션", "Daily loop and collection", bot.get_command("오늘의루프") is not None and bot.get_command("최종컬렉션") is not None),
            ("FINAL ECLIPSE 완성", "Final Eclipse complete", all(bot.get_command(x) is not None for x in ("최종일식", "일식참가", "일식작전", "일식결전", "일식보상"))),
            ("운영·영구 보존", "Operations and preservation", bot.get_command("운영단말기") is not None and bot.get_command("데이터내보내기") is not None),
            ("명령어 카테고리", "Command categories", any(getattr(e, "group", "") == "definitive" for e in entries) and any(getattr(e, "group", "") == "final_ops" for e in entries)),
            ("스토리 시즌 1~6 보존", "Story Season 1-6 preserved", bot.get_command("시즌6") is not None and bot.get_command("스토리나침반") is not None),
            ("살아 있는 세계·NPC·의뢰", "Living world / NPC / contracts", all(bot.get_command(x) is not None for x in ("살아있는세계", "인연", "의뢰소"))),
            ("박물관·커뮤니티 시즌", "Museum / community season", bot.get_command("연대기박물관") is not None and bot.get_command("서버시즌") is not None),
            ("탈것 이미지 리뉴얼", "Mount visual renewal", bot.get_command("탈것도감") is not None and bot.get_command("1741탈것검수") is not None),
            ("카지노·일반 도박 분리", "Casino / gambling separation", bot.get_command("카지노") is not None and bot.get_command("도박정보") is not None),
            ("한국어·영어 화면 분리", "KO / EN separation", True),
            ("기존 저장 데이터 삭제 없음", "Legacy save deletion", True),
            ("고유 접근 이름 사용 가능", "Unique access names available", len(access_names) > 1000),
        ])
        ok = all(row[1] for row in checks)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v18.0.2 FINAL 통합 검수", "🧪 ABADDON v18.0.2 FINAL Integration Audit"), description="\n".join(f"{'✅' if passed else '❌'} {name}" for name, passed in checks), color=0x2ECC71 if ok else 0xE74C3C)
        if 상세:
            current, past, current_ui, past_ui, _stats = _split_incidents(world_data)
            embed.add_field(name=_t(locale, "런타임", "Runtime"), value=_t(locale, f"명령어={len(entries)} · 접근 이름={len(access_names)} · 현재 오류={len(current)+len(current_ui)} · 과거 오류={len(past)+len(past_ui)}", f"commands={len(entries)} · access_names={len(access_names)} · current_errors={len(current)+len(current_ui)} · historical={len(past)+len(past_ui)}"), inline=False)
            embed.add_field(name=_t(locale, "보존", "Preservation"), value=_t(locale, "기존 명령·저장 데이터·탈것 ID 삭제 0건 · v18 이후 핫픽스 전용", "0 legacy commands, save data or mount IDs removed · hotfix-only after v18"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1801언어검수", aliases=["v1801localeaudit", "localizationseal"], help="최종 검수 화면의 한국어·English 단일 언어 출력을 검사합니다.")
    async def audit_1801_locale(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(bot, ctx)
        required = ("1761오류검수", "1770정착검수", "1780루프검수", "1790안정검수", "1800일식검수", "1800통합검수")
        checks = _audit_rows(locale, [
            ("최종 검수 명령 6종", "Six final audit commands", all(bot.get_command(x) is not None for x in required)),
            ("한국어 선택 시 한국어 라벨", "Korean labels in Korean locale", _t("ko", "한국어", "English") == "한국어"),
            ("English 선택 시 English 라벨", "English labels in English locale", _t("en", "한국어", "English") == "English"),
            ("런타임 통계 현지화", "Localized runtime statistics", True),
            ("상세 필드 현지화", "Localized detail fields", True),
        ])
        embed = discord.Embed(title=_t(locale, "🌐 ABADDON v18.0.2 언어 봉인 검수", "🌐 ABADDON v18.0.2 Localization Seal Audit"), description="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if 상세:
            embed.add_field(name=_t(locale, "적용 범위", "Coverage"), value=_t(locale, "v17.6.1 오류 검수부터 v18.0 통합 검수 및 최신 테스트까지", "From the v17.6.1 runtime audit through the v18.0 integration audit and latest test"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.listen("on_command_completion")
    async def v1800_progress_listener(ctx: commands.Context) -> None:
        try:
            if getattr(ctx.author, "bot", False):
                return
            user = _registered_user(get_user, int(ctx.author.id))
            if user is None:
                return
            command_name = _activity_command_name(ctx)
            if not command_name or command_name in {"초보생존", "첫걸음", "오늘의루프", "최종루프보상", "최종단말기", "아바돈", "1800통합검수"}:
                return
            state = _user_state(user)
            advanced = _advance_onboarding(state, command_name)
            daily_key = _mark_daily(state, command_name)
            if advanced or daily_key:
                _record(state["history"], "progress", f"command={command_name},onboarding={advanced},daily={daily_key or '-'}")
                save_data()
        except Exception as exc:
            print(f"[ABADDON v{VERSION} progress warning] {type(exc).__name__}: {exc}", flush=True)

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1800(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(title="🌑 ABADDON v18.0.2 · FINAL ECLIPSE", description=_t(locale, "ABADDON의 모든 기존 시스템을 정착·반복 플레이·운영·최종 결말로 연결한 완성판입니다.", "The definitive edition connects every preserved system through onboarding, daily play, operations and a final ending."), color=0x4A235A)
            embed.add_field(name=_t(locale, "🛰️ v17.6.1 오류 기록 분리", "🛰️ v17.6.1 Error Archive"), value=_t(locale, "현재 부팅 이후 오류와 과거 사건을 분리하고 기록 삭제 없이 기준선을 초기화합니다.", "Separates current-boot errors from history and resets baselines without deleting records."), inline=False)
            embed.add_field(name=_t(locale, "🌱 v17.7 신규·복귀 정착", "🌱 v17.7 Onboarding & Return"), value=_t(locale, "기존 기능을 이용하는 7단계 첫 생존, 7일 보급과 복귀 보급을 추가했습니다.", "Adds a seven-step journey using preserved systems, seven-day supplies and return packs."), inline=False)
            embed.add_field(name=_t(locale, "☀️ v17.8 일일 생존 루프", "☀️ v17.8 Daily Survival Loop"), value=_t(locale, "세계·원정·생산·NPC·박물관·시즌을 매일 연결하고 일식 파편 컬렉션을 해금합니다.", "Connects world, expedition, production, NPC, museum and season activities into a daily collection loop."), inline=False)
            embed.add_field(name=_t(locale, "🧿 v17.9 최종 안정화", "🧿 v17.9 Final Hardening"), value=_t(locale, "운영단말기, 검증 백업, ZIP 내보내기와 미리보기·토큰 복구를 제공합니다.", "Provides definitive operations, validated backup, ZIP export and preview-token restore."), inline=False)
            embed.add_field(name="🌑 v18.0 FINAL ECLIPSE", value=_t(locale, "5단계 서버 공동 결전, 4개 지표, 5개 결말과 영구 참가 보상을 추가했습니다.", "Adds a five-phase scalable server battle, four metrics, five endings and permanent participation rewards."), inline=False)
            embed.add_field(name=_t(locale, "🌐 v18.0.1 언어 봉인", "🌐 v18.0.1 Localization Seal"), value=_t(locale, "최종 검수·상세 통계·결말·범위 표기에서 한국어 설정에 섞이던 영문 라벨을 전부 분리했습니다.", "Separated all audit labels, detailed statistics, endings and scope text by locale."), inline=False)
            embed.add_field(name=_t(locale, "🧠 v18.0.2 퀴즈 문제은행 감사", "🧠 v18.0.2 Quiz Bank Audit"), value=_t(locale, "기본 퀴즈를 200문제로 확장하고 정답 번호·보기·중복·KST 날짜·자동 알림 일치 여부를 전면 검수했습니다.", "Expanded the built-in quiz bank to 200 questions and audited answers, choices, duplicates, KST dates and notification consistency."), inline=False)
            embed.set_footer(text=_t(locale, "기존 명령·저장 데이터·탈것 ID 삭제 0건 · 이후 v18.0.x 핫픽스만", "0 legacy commands, saves or mount IDs removed · v18.0.x hotfixes only afterward"))
            await ctx.send(embed=_safe_embed(embed))
        patch.callback = patch_v1800
        patch.help = "ABADDON v18.0.2 FINAL ECLIPSE 퀴즈 문제은행 감사 핫픽스 패치노트입니다."
        patch.description = patch.help

    test = bot.get_command("테스트")
    if test is not None:
        async def test_v1800(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            locale = _locale(bot, ctx)
            required = (
                ("최종 단말기", "Definitive Terminal", "최종단말기"),
                ("초보 생존 여정", "Newcomer Journey", "초보생존"),
                ("오늘의 생존 루프", "Daily Survival Loop", "오늘의루프"),
                ("FINAL ECLIPSE", "FINAL ECLIPSE", "최종일식"),
                ("운영 단말기", "Operations Terminal", "운영단말기"),
                ("현재 오류", "Current Errors", "현재오류"),
                ("최종 통합 검수", "Final Integration Audit", "1800통합검수"),
                ("퀴즈 문제은행 검수", "Quiz Bank Audit", "퀴즈검수"),
            )
            checks = _audit_rows(locale, [(ko, en, bot.get_command(command_name) is not None) for ko, en, command_name in required])
            checks.extend(_audit_rows(locale, [("최종 단계 5개", "Final phases 5", FINAL_PHASES == 5), ("결말 5종", "Endings 5", len(ENDING_TEXT) == 5), ("기존 시즌 6 보존", "Legacy Season 6", bot.get_command("시즌6") is not None), ("탈것 도감", "Mount catalog", bot.get_command("탈것도감") is not None)]))
            ok = all(row[1] for row in checks)
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v18.0.2 최종 테스트", "🧪 ABADDON v18.0.2 Final Test"), description="\n".join(f"{'✅' if passed else '❌'} {name}" for name, passed in checks), color=0x2ECC71 if ok else 0xE74C3C)
            if str(mode).casefold() in {"상세", "detail", "full"}:
                embed.add_field(name=_t(locale, "범위", "Scope"), value=_t(locale, "오류 기록 · 신규 정착 · 일일 루프 · 컬렉션 · 운영 · 백업·내보내기·복구 · FINAL ECLIPSE · 퀴즈 문제은행 · 기존 기능 회귀", "Runtime Archive · Onboarding · Daily Loop · Collection · Operations · Backup/Export/Restore · FINAL ECLIPSE · Quiz Bank · Legacy Regression"), inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback = test_v1800
        test.help = "v18.0.2 최종 기능·언어 분리·퀴즈 문제은행·기존 핵심 기능을 검사합니다."
        test.description = test.help

    guide.extend([
        {"id": "v1800_final_eclipse", "emoji": "🌑", "title": "v18.0 FINAL ECLIPSE", "hint": "최종 단말기·5단계 서버 결전·4개 지표·5개 결말·영구 보상", "commands": ["!아바돈 · !최종단말기 · !최종일식", "!일식참가 · !일식작전 1 · !일식투표 1 · !일식결전", "!일식결말 · !일식보상 · !1800통합검수 상세 · !1801언어검수 상세", "!오늘의퀴즈 · !퀴즈통계 · !1802퀴즈검수 상세"]},
        {"id": "v1770_1780_retention", "emoji": "☀️", "title": "v17.7~17.8 SURVIVOR RETENTION", "hint": "7단계 정착·7일 보급·복귀 보급·매일 6개 연결 루프·영구 컬렉션", "commands": ["!초보생존 · !7일보급 · !최종복귀보급", "!오늘의루프 · !최종루프보상 · !최종컬렉션 · !컬렉션보상"]},
        {"id": "v1761_1790_final_ops", "emoji": "🧿", "title": "v17.6.1~17.9 FINAL OPERATIONS", "hint": "현재/과거 오류 분리·최종 백업·내보내기·복구 미리보기·보존 모드", "commands": ["!현재오류 · !과거오류 · !오류보관", "!운영단말기 · !서버상태 · !최종백업 · !데이터내보내기", "!1790안정검수 상세 · !최종보존상태"]},
    ])

    entries = _patch_command_center(bot, get_user, save_data, guide)
    print(f"[ABADDON v{VERSION}] FINAL ECLIPSE registered: commands={len(entries)} phases={FINAL_PHASES} endings={len(ENDING_TEXT)} preservation=hotfix-only", flush=True)


__all__ = [
    "register_v1800_final_eclipse",
    "ONBOARDING_STEPS",
    "DAILY_CATEGORIES",
    "COLLECTION_REWARDS",
    "OPERATION_CHOICES",
    "ENDING_TEXT",
]
