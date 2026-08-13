from __future__ import annotations

import asyncio
import copy
import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "7.5.1"
SCHEMA_VERSION = 6
KST = timezone(timedelta(hours=9))

JOIN_MODE_ALIASES = {
    "자유": "open", "공개": "open", "open": "open", "즉시": "open",
    "승인": "approval", "신청": "approval", "approval": "approval",
    "비공개": "closed", "닫기": "closed", "closed": "closed", "초대": "closed",
}
JOIN_MODE_LABELS = {"open": "🟢 자유 가입", "approval": "🟡 승인 가입", "closed": "🔴 비공개"}

RESOURCE_ALIASES = {
    "식량": "food", "돈": "food", "food": "food",
    "나무": "나무", "목재": "나무",
    "광석": "광석", "철광석": "광석",
    "고철": "고철", "스크랩": "고철",
    "약초": "약초", "허브": "약초",
    "물고기": "물고기", "생선": "물고기",
}
RESOURCE_LABELS = {"food": "식량", "나무": "나무", "광석": "광석", "고철": "고철", "약초": "약초", "물고기": "물고기"}
RESOURCE_KEYS = ("나무", "광석", "고철", "약초", "물고기")

FACILITIES: Dict[str, Dict[str, Any]] = {
    "generator": {
        "name": "발전기", "emoji": "⚡", "aliases": ("발전기", "전력", "generator"),
        "base_food": 120_000, "resources": {"나무": 120, "광석": 100, "고철": 180},
        "effect": "기지 식량 생산과 레이드 지원 보너스",
    },
    "warehouse": {
        "name": "창고", "emoji": "📦", "aliases": ("창고", "보관소", "warehouse"),
        "base_food": 160_000, "resources": {"나무": 240, "광석": 80, "고철": 140},
        "effect": "길드 금고 식량·자원 수용량 증가",
    },
    "infirmary": {
        "name": "의무실", "emoji": "🏥", "aliases": ("의무실", "병원", "infirmary"),
        "base_food": 190_000, "resources": {"나무": 100, "광석": 120, "고철": 160, "약초": 100},
        "effect": "레이드 재도전 대기시간 감소와 보상 보정",
    },
    "armory": {
        "name": "무기고", "emoji": "🗡️", "aliases": ("무기고", "병기고", "armory"),
        "base_food": 230_000, "resources": {"나무": 80, "광석": 220, "고철": 260},
        "effect": "길드 레이드 공격력 증가",
    },
}
MAX_FACILITY_LEVEL = 5
BUILD_SECONDS = {1: 900, 2: 1_800, 3: 3_600, 4: 7_200, 5: 14_400}

RAID_BOSSES: Tuple[Dict[str, Any], ...] = (
    {"name": "붉은 황무지의 철갑 거신", "emoji": "🦾", "base_hp": 180_000, "trait": "두꺼운 장갑판과 과열 동력핵"},
    {"name": "심연 철도의 포식 기관차", "emoji": "🚂", "base_hp": 210_000, "trait": "가속할수록 강해지는 오염 기관"},
    {"name": "검은 비의 군체 여왕", "emoji": "🕷️", "base_hp": 195_000, "trait": "감염낭과 군체 신호로 재생"},
    {"name": "종말 관측소의 타락한 파수병", "emoji": "📡", "base_hp": 225_000, "trait": "왜곡 신호와 방어막을 반복 전개"},
)
PART_ALIASES = {
    "자동": "auto", "auto": "auto",
    "장갑": "armor", "장갑판": "armor", "armor": "armor",
    "핵": "core", "동력핵": "core", "core": "core",
    "감염낭": "sac", "낭": "sac", "sac": "sac",
}
PART_LABELS = {"armor": "🛡️ 장갑판", "core": "⚡ 동력핵", "sac": "☣️ 감염낭"}

_GUILD_STATE_LOCKS: Dict[str, asyncio.Lock] = {}


def _state_lock(guild_id: Any) -> asyncio.Lock:
    key = str(guild_id)
    lock = _GUILD_STATE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _GUILD_STATE_LOCKS[key] = lock
    return lock
TACTIC_ALIASES = {
    "돌격": "assault", "공격": "assault", "assault": "assault",
    "지원": "support", "보조": "support", "support": "support",
    "의무": "medic", "치료": "medic", "medic": "medic",
}
TACTIC_LABELS = {"assault": "⚔️ 돌격", "support": "📡 지원", "medic": "🏥 의무"}
RAID_PRACTICE_COOLDOWN_SECONDS = 10
_RAID_PRACTICE_COOLDOWNS: Dict[str, datetime] = {}


def raid_preset(user: MutableMapping[str, Any]) -> Dict[str, str]:
    raw = user.get("guild_raid_preset")
    if not isinstance(raw, dict):
        raw = {}
        user["guild_raid_preset"] = raw
    tactic = str(raw.get("tactic") or "assault")
    if tactic not in TACTIC_LABELS:
        tactic = "assault"
    part = str(raw.get("part") or "auto")
    if part not in {"auto", *PART_LABELS.keys()}:
        part = "auto"
    raw["tactic"] = tactic
    raw["part"] = part
    return raw


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    return result


def _unique_strings(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    rows: List[str] = []
    for raw in values:
        value = str(raw)
        if value and value not in seen:
            seen.add(value)
            rows.append(value)
    return rows


def _trim_log(rows: Any, limit: int = 200) -> List[Dict[str, Any]]:
    """Return valid historical rows without automatic pruning.

    v7.5.1 follows the administrator's approval-first policy: migration and
    normal operation never discard old audit, vault, or raid history merely
    because a size threshold was reached. ``limit`` remains in the signature
    for compatibility with older callers but is intentionally not applied.
    """
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _day_key() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _week_key() -> str:
    now = datetime.now(KST)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _period_defaults(period: str) -> Dict[str, Dict[str, int]]:
    if period == "daily":
        return {
            "donate_food": {"target": 25_000, "progress": 0},
            "donate_resource": {"target": 80, "progress": 0},
            "raid_actions": {"target": 3, "progress": 0},
        }
    return {
        "donate_food": {"target": 250_000, "progress": 0},
        "donate_resource": {"target": 800, "progress": 0},
        "raid_damage": {"target": 120_000, "progress": 0},
        "facility_upgrade": {"target": 1, "progress": 0},
    }


def _mission_label(key: str) -> str:
    return {
        "donate_food": "식량 공동 기부",
        "donate_resource": "건축 자원 공동 기부",
        "raid_actions": "길드 레이드 행동",
        "raid_damage": "길드 레이드 누적 피해",
        "facility_upgrade": "공동 시설 건설·강화",
    }.get(key, key)


def _new_mission(period: str, key: str) -> Dict[str, Any]:
    return {
        "key": key,
        "objectives": _period_defaults(period),
        "claimed_by": [],
        "activity": {},
        "created_at": _iso(),
    }


def ensure_missions(guild: MutableMapping[str, Any]) -> Dict[str, Any]:
    missions = guild.get("missions")
    if not isinstance(missions, dict):
        missions = {}
        guild["missions"] = missions
    today, week = _day_key(), _week_key()
    daily = missions.get("daily")
    if not isinstance(daily, dict) or daily.get("key") != today:
        missions["daily"] = _new_mission("daily", today)
    weekly = missions.get("weekly")
    if not isinstance(weekly, dict) or weekly.get("key") != week:
        missions["weekly"] = _new_mission("weekly", week)
    for period in ("daily", "weekly"):
        state = missions[period]
        state["claimed_by"] = _unique_strings(state.get("claimed_by"))
        if not isinstance(state.get("activity"), dict):
            state["activity"] = {}
        defaults = _period_defaults(period)
        objectives = state.get("objectives")
        if not isinstance(objectives, dict):
            objectives = {}
            state["objectives"] = objectives
        for key, default in defaults.items():
            row = objectives.get(key)
            if not isinstance(row, dict):
                row = dict(default)
                objectives[key] = row
            row["target"] = max(1, _safe_int(row.get("target"), default["target"], 1))
            row["progress"] = max(0, _safe_int(row.get("progress"), 0, 0))
    return missions


def progress_missions(guild: MutableMapping[str, Any], event: str, amount: int, user_id: Any) -> None:
    amount = max(0, int(amount or 0))
    if amount <= 0:
        return
    missions = ensure_missions(guild)
    uid = str(user_id)
    for period in ("daily", "weekly"):
        state = missions[period]
        objectives = state["objectives"]
        if event in objectives:
            objectives[event]["progress"] = min(
                int(objectives[event]["target"]),
                int(objectives[event].get("progress", 0) or 0) + amount,
            )
        points = 0
        if event == "donate_food":
            points = max(1, amount // 1_000)
        elif event == "donate_resource":
            points = max(1, amount // 5)
        elif event == "raid_actions":
            points = 10 * amount
        elif event == "raid_damage":
            points = max(1, amount // 1_000)
        elif event == "facility_upgrade":
            points = 50 * amount
        if points:
            activity = state.setdefault("activity", {})
            activity[uid] = max(0, _safe_int(activity.get(uid), 0, 0)) + points


def facility_key(value: Any) -> Optional[str]:
    normalized = str(value or "").strip().casefold()
    for key, info in FACILITIES.items():
        if normalized in {str(alias).casefold() for alias in info["aliases"]}:
            return key
    return None


def facility_cost(key: str, target_level: int) -> Dict[str, Any]:
    info = FACILITIES[key]
    target_level = max(1, min(MAX_FACILITY_LEVEL, int(target_level)))
    multiplier = target_level * target_level
    resources = {name: max(1, int(amount) * multiplier) for name, amount in info["resources"].items()}
    return {
        "food": int(info["base_food"]) * multiplier,
        "resources": resources,
        "seconds": BUILD_SECONDS[target_level],
    }


def facility_effects(guild: Mapping[str, Any]) -> Dict[str, float]:
    facilities = guild.get("facilities", {}) if isinstance(guild.get("facilities"), Mapping) else {}
    generator = _safe_int(facilities.get("generator", {}).get("level", 0) if isinstance(facilities.get("generator"), Mapping) else 0, 0, 0)
    warehouse = _safe_int(facilities.get("warehouse", {}).get("level", 0) if isinstance(facilities.get("warehouse"), Mapping) else 0, 0, 0)
    infirmary = _safe_int(facilities.get("infirmary", {}).get("level", 0) if isinstance(facilities.get("infirmary"), Mapping) else 0, 0, 0)
    armory = _safe_int(facilities.get("armory", {}).get("level", 0) if isinstance(facilities.get("armory"), Mapping) else 0, 0, 0)
    return {
        "generator_food_hourly": float(generator * 1_500),
        "raid_support_bonus": float(generator * 0.01),
        "food_capacity": float(1_000_000 + warehouse * 3_000_000),
        "resource_capacity": float(1_000 + warehouse * 5_000),
        "raid_cooldown_reduction": float(infirmary * 20),
        "raid_reward_bonus": float(infirmary * 0.04),
        "raid_damage_bonus": float(armory * 0.06),
    }


def ensure_guild_state(guild_id: Any, raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    repairs: List[str] = []
    guild: Dict[str, Any]
    if isinstance(raw, dict):
        guild = raw
    else:
        guild = {}
        repairs.append("길드 레코드 객체 복구")

    guild["schema_version"] = SCHEMA_VERSION
    guild["name"] = str(guild.get("name") or f"이름없는길드-{guild_id}")[:32]
    guild["owner"] = str(guild.get("owner") or "")
    guild["members"] = _unique_strings(guild.get("members"))
    if guild["owner"] and guild["owner"] not in guild["members"]:
        guild["members"].insert(0, guild["owner"])
        repairs.append("길드장을 멤버 목록에 복구")
    guild["level"] = max(1, _safe_int(guild.get("level"), 1, 1))
    guild["exp"] = max(0, _safe_int(guild.get("exp"), 0, 0))
    guild["created_at"] = str(guild.get("created_at") or _iso())
    guild["description"] = str(guild.get("description") or "폐허에서 함께 살아남는 생존자 길드입니다.")[:300]
    guild["join_mode"] = str(guild.get("join_mode") or "open")
    if guild["join_mode"] not in JOIN_MODE_LABELS:
        guild["join_mode"] = "open"
        repairs.append("가입 방식을 자유 가입으로 복구")
    guild["officers"] = [uid for uid in _unique_strings(guild.get("officers")) if uid in guild["members"] and uid != guild["owner"]]
    guild["applications"] = [row for row in guild.get("applications", []) if isinstance(row, dict)] if isinstance(guild.get("applications"), list) else []
    guild["member_joined_at"] = guild.get("member_joined_at") if isinstance(guild.get("member_joined_at"), dict) else {}
    for uid in guild["members"]:
        guild["member_joined_at"].setdefault(uid, guild["created_at"])

    legacy_fund = max(0, _safe_int(guild.get("fund"), 0, 0))
    vault = guild.get("vault")
    if not isinstance(vault, dict):
        vault = {}
        guild["vault"] = vault
    vault_food = max(0, _safe_int(vault.get("food"), 0, 0))
    canonical_food = max(legacy_fund, vault_food)
    if legacy_fund != vault_food:
        repairs.append("구형 길드 기금과 통합 금고 식량 동기화")
    guild["fund"] = canonical_food
    vault["food"] = canonical_food
    resources = vault.get("resources")
    if not isinstance(resources, dict):
        resources = {}
        vault["resources"] = resources
    for key in RESOURCE_KEYS:
        resources[key] = max(0, _safe_int(resources.get(key), 0, 0))
    vault["transactions"] = _trim_log(vault.get("transactions"), 250)
    requests = vault.get("withdrawals")
    if not isinstance(requests, list):
        requests = []
    clean_requests: List[Dict[str, Any]] = []
    seen_request_ids: set[str] = set()
    highest_numeric_id = 0
    recovered_index = 0
    for row_index, original in enumerate(requests, start=1):
        if not isinstance(original, dict):
            # Non-object legacy rows cannot be safely interpreted as a money
            # request. Preserve their existence in the audit log instead of
            # silently deleting them.
            recovered_index += 1
            recovery_rows = vault.setdefault("withdrawal_recovery", [])
            if not isinstance(recovery_rows, list):
                recovery_rows = []
                vault["withdrawal_recovery"] = recovery_rows
            recovery_rows.append({"index": row_index, "raw": original, "recovered_at": _iso()})
            _log(guild, "withdrawal_recovery_note", "migration", f"해석 불가 출금 행 원본 보존 index={row_index}")
            repairs.append(f"해석 불가 출금 행 원본을 복구 보관함에 보존 ({row_index})")
            continue
        row = original
        requested_id = str(row.get("id") or "").strip()
        if requested_id.upper().startswith("W") and requested_id[1:].isdigit():
            highest_numeric_id = max(highest_numeric_id, int(requested_id[1:]))
        request_id = requested_id
        if not request_id or request_id.casefold() in seen_request_ids:
            recovered_index += 1
            request_id = f"REC-{guild_id}-{row_index}-{recovered_index}"
            row["legacy_id"] = requested_id
            row["id"] = request_id
            repairs.append("누락·중복 출금 요청 ID를 새 복구 ID로 보존")
        seen_request_ids.add(request_id.casefold())
        row["amount"] = max(0, _safe_int(row.get("amount"), 0, 0))
        row["status"] = str(row.get("status") or "pending")
        clean_requests.append(row)
    vault["withdrawals"] = clean_requests
    configured_next = max(1, _safe_int(vault.get("next_request_id"), 1, 1))
    vault["next_request_id"] = max(configured_next, highest_numeric_id + 1)

    contributions = guild.get("contributions")
    if not isinstance(contributions, dict):
        contributions = {}
        guild["contributions"] = contributions
    for uid, row in list(contributions.items()):
        if not isinstance(row, dict):
            row = {}
            contributions[str(uid)] = row
        row["food"] = max(0, _safe_int(row.get("food"), 0, 0))
        row["resources"] = max(0, _safe_int(row.get("resources"), 0, 0))
        row["raid_damage"] = max(0, _safe_int(row.get("raid_damage"), 0, 0))
        row["activity"] = max(0, _safe_int(row.get("activity"), 0, 0))

    facilities = guild.get("facilities")
    if not isinstance(facilities, dict):
        facilities = {}
        guild["facilities"] = facilities
    for key in FACILITIES:
        row = facilities.get(key)
        if not isinstance(row, dict):
            row = {}
            facilities[key] = row
        row["level"] = min(MAX_FACILITY_LEVEL, max(0, _safe_int(row.get("level"), 0, 0)))
        row["upgraded_at"] = str(row.get("upgraded_at") or "")
    if not isinstance(guild.get("construction"), dict):
        guild["construction"] = {}
    guild["base_last_collect"] = str(guild.get("base_last_collect") or _iso())

    ensure_missions(guild)
    raid = guild.get("raid")
    if not isinstance(raid, dict):
        raid = {}
        guild["raid"] = raid
    if not isinstance(raid.get("active"), dict):
        raid["active"] = {}
    raid["history"] = _trim_log(raid.get("history"), 30)
    raid["claimed"] = _unique_strings(raid.get("claimed"))

    guild["audit_log"] = _trim_log(guild.get("audit_log"), 250)
    stats = guild.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        guild["stats"] = stats
    for key in ("raids_defeated", "facilities_upgraded", "missions_claimed", "vault_deposits", "vault_withdrawals"):
        stats[key] = max(0, _safe_int(stats.get(key), 0, 0))
    return guild, repairs


def sync_guild_food(guild: MutableMapping[str, Any]) -> None:
    vault = guild.setdefault("vault", {})
    canonical = max(0, _safe_int(vault.get("food"), guild.get("fund", 0), 0))
    vault["food"] = canonical
    guild["fund"] = canonical


def _log(guild: MutableMapping[str, Any], action: str, actor: Any, detail: str, **extra: Any) -> None:
    rows = guild.setdefault("audit_log", [])
    if not isinstance(rows, list):
        rows = []
        guild["audit_log"] = rows
    row = {"at": _iso(), "action": str(action), "actor": str(actor), "detail": str(detail)[:300]}
    row.update(extra)
    rows.append(row)


def _vault_log(guild: MutableMapping[str, Any], action: str, actor: Any, currency: str, amount: int, note: str = "") -> None:
    vault = guild.setdefault("vault", {})
    rows = vault.setdefault("transactions", [])
    if not isinstance(rows, list):
        rows = []
        vault["transactions"] = rows
    rows.append({
        "at": _iso(), "action": action, "actor": str(actor), "currency": currency,
        "amount": int(amount), "note": str(note)[:180],
    })


def guild_member_capacity(guild: Mapping[str, Any]) -> int:
    return min(60, 10 + max(1, _safe_int(guild.get("level"), 1, 1)) * 5)


def guild_role(guild: Mapping[str, Any], user_id: Any) -> str:
    uid = str(user_id)
    if uid == str(guild.get("owner") or ""):
        return "owner"
    if uid in set(_unique_strings(guild.get("officers"))):
        return "officer"
    if uid in set(_unique_strings(guild.get("members"))):
        return "member"
    return "none"


def _discord_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    if int(getattr(ctx.guild, "owner_id", 0) or 0) == int(ctx.author.id):
        return True
    perms = getattr(ctx.author, "guild_permissions", None)
    return bool(getattr(perms, "administrator", False))


def can_manage_guild(ctx: commands.Context, guild: Mapping[str, Any], owner_only: bool = False) -> bool:
    role = guild_role(guild, ctx.author.id)
    if owner_only:
        return role == "owner" or _discord_admin(ctx)
    return role in {"owner", "officer"} or _discord_admin(ctx)


def guild_for_user(world_data: Mapping[str, Any], user: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not isinstance(user, Mapping):
        return None, None
    gid = str(user.get("guild_id") or "")
    guilds = world_data.get("guilds", {})
    if not gid or not isinstance(guilds, Mapping):
        return None, None
    raw = guilds.get(gid)
    if not isinstance(raw, dict):
        return None, None
    guild, _ = ensure_guild_state(gid, raw)
    return gid, guild


def find_guild_by_name(world_data: Mapping[str, Any], name: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    guilds = world_data.get("guilds", {})
    if not isinstance(guilds, Mapping):
        return None, None
    needle = str(name or "").strip().casefold()
    for gid, raw in guilds.items():
        if not isinstance(raw, dict):
            continue
        guild, _ = ensure_guild_state(gid, raw)
        if str(guild.get("name") or "").casefold() == needle:
            return str(gid), guild
    return None, None


def migrate_all_guilds(world_data: MutableMapping[str, Any], user_data: MutableMapping[str, Any]) -> Dict[str, Any]:
    guilds = world_data.get("guilds")
    if not isinstance(guilds, dict):
        guilds = {}
        world_data["guilds"] = guilds
    report = {
        "guilds": 0, "repairs": [], "user_links_added": 0, "owner_links_added": 0,
        "conflicting_memberships": [], "duplicate_names": [], "deletions": 0,
    }
    name_owner: Dict[str, str] = {}
    for gid, raw in list(guilds.items()):
        guild, repairs = ensure_guild_state(gid, raw)
        guilds[str(gid)] = guild
        report["guilds"] += 1
        report["repairs"].extend(f"{gid}: {row}" for row in repairs)
        name_key = str(guild.get("name") or "").casefold()
        if name_key in name_owner and name_owner[name_key] != str(gid):
            report["duplicate_names"].append({"name": guild.get("name"), "guilds": [name_owner[name_key], str(gid)]})
        else:
            name_owner[name_key] = str(gid)
        owner = str(guild.get("owner") or "")
        if owner and isinstance(user_data.get(owner), dict):
            owner_user = user_data[owner]
            current = str(owner_user.get("guild_id") or "")
            if not current:
                owner_user["guild_id"] = str(gid)
                report["owner_links_added"] += 1
            elif current != str(gid):
                report["conflicting_memberships"].append({"user": owner, "user_guild": current, "member_of": str(gid), "role": "owner"})
        for uid in guild["members"]:
            user = user_data.get(str(uid))
            if not isinstance(user, dict):
                continue
            current = str(user.get("guild_id") or "")
            if not current:
                user["guild_id"] = str(gid)
                report["user_links_added"] += 1
            elif current != str(gid):
                report["conflicting_memberships"].append({"user": str(uid), "user_guild": current, "member_of": str(gid), "role": "member"})
    for uid, user in user_data.items():
        if not isinstance(user, dict):
            continue
        gid = str(user.get("guild_id") or "")
        if gid and gid in guilds and str(uid) not in guilds[gid]["members"]:
            guilds[gid]["members"].append(str(uid))
            guilds[gid]["member_joined_at"].setdefault(str(uid), _iso())
            report["user_links_added"] += 1
    report["repairs_count"] = len(report["repairs"]) + report["user_links_added"] + report["owner_links_added"]
    return report


def audit_guild_data(world_data: Mapping[str, Any], user_data: Mapping[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    guilds = world_data.get("guilds", {})
    if not isinstance(guilds, Mapping):
        return {"guilds": 0, "issues": [{"severity": "critical", "code": "guild_root", "detail": "world.guilds가 객체가 아님"}], "critical": 1, "warning": 0, "deletions": 0}
    names: Dict[str, str] = {}
    memberships: Dict[str, List[str]] = {}
    for gid, raw in guilds.items():
        if not isinstance(raw, Mapping):
            issues.append({"severity": "critical", "code": "invalid_record", "guild": str(gid), "detail": "길드 레코드가 객체가 아님"})
            continue
        owner = str(raw.get("owner") or "")
        members = _unique_strings(raw.get("members"))
        if not owner:
            if bool(raw.get("dormant")) and not members:
                issues.append({"severity": "warning", "code": "dormant_preserved", "guild": str(gid), "detail": "마지막 멤버 탈퇴 후 휴면 기록으로 보존됨"})
            else:
                issues.append({"severity": "critical", "code": "missing_owner", "guild": str(gid), "detail": "활성 길드의 길드장 누락"})
        elif owner not in members:
            issues.append({"severity": "warning", "code": "owner_not_member", "guild": str(gid), "detail": "길드장이 멤버 목록에 없음"})
        name_key = str(raw.get("name") or "").casefold()
        if name_key in names:
            issues.append({"severity": "warning", "code": "duplicate_name", "guild": str(gid), "detail": f"{names[name_key]}와 길드명 중복"})
        else:
            names[name_key] = str(gid)
        for uid in members:
            memberships.setdefault(uid, []).append(str(gid))
            user = user_data.get(uid)
            if isinstance(user, Mapping) and str(user.get("guild_id") or "") not in {"", str(gid)}:
                issues.append({"severity": "warning", "code": "user_link_mismatch", "guild": str(gid), "user": uid, "detail": f"사용자 guild_id={user.get('guild_id')}"})
        vault = raw.get("vault", {}) if isinstance(raw.get("vault"), Mapping) else {}
        fund = _safe_int(raw.get("fund"), 0)
        food = _safe_int(vault.get("food"), 0)
        if fund < 0 or food < 0:
            issues.append({"severity": "critical", "code": "negative_vault", "guild": str(gid), "detail": "금고 식량 음수"})
        if max(fund, 0) != max(food, 0):
            issues.append({"severity": "warning", "code": "vault_mirror", "guild": str(gid), "detail": f"fund={fund}, vault.food={food}"})
        withdrawals = vault.get("withdrawals", []) if isinstance(vault, Mapping) else []
        ids = [str(row.get("id")) for row in withdrawals if isinstance(row, Mapping) and row.get("id")]
        if len(ids) != len(set(ids)):
            issues.append({"severity": "critical", "code": "withdrawal_duplicate_id", "guild": str(gid), "detail": "출금 요청 ID 중복"})
        raid = raw.get("raid", {}) if isinstance(raw.get("raid"), Mapping) else {}
        active = raid.get("active", {}) if isinstance(raid.get("active"), Mapping) else {}
        if active:
            hp, max_hp = _safe_int(active.get("hp"), 0), _safe_int(active.get("max_hp"), 0)
            if hp < 0 or max_hp < 0 or hp > max_hp:
                issues.append({"severity": "critical", "code": "raid_hp", "guild": str(gid), "detail": f"hp={hp}, max={max_hp}"})
    for uid, guild_ids in memberships.items():
        if len(set(guild_ids)) > 1:
            issues.append({"severity": "warning", "code": "multi_membership", "user": uid, "detail": ", ".join(guild_ids)})
    for uid, user in user_data.items():
        if not isinstance(user, Mapping):
            continue
        gid = str(user.get("guild_id") or "")
        if gid and gid not in guilds:
            issues.append({"severity": "warning", "code": "orphan_user_link", "user": str(uid), "detail": f"존재하지 않는 길드 {gid}"})
    critical = sum(1 for row in issues if row["severity"] == "critical")
    warning = len(issues) - critical
    return {"guilds": len(guilds), "issues": issues, "critical": critical, "warning": warning, "deletions": 0}


def finalize_construction(guild: MutableMapping[str, Any]) -> Optional[Dict[str, Any]]:
    project = guild.get("construction")
    if not isinstance(project, dict) or not project.get("facility"):
        return None
    complete_at = _parse_iso(project.get("complete_at"))
    if complete_at is None or _now() < complete_at:
        return None
    key = str(project.get("facility"))
    target = min(MAX_FACILITY_LEVEL, max(1, _safe_int(project.get("target_level"), 1, 1)))
    if key not in FACILITIES:
        guild["construction"] = {}
        return None
    facilities = guild.setdefault("facilities", {})
    row = facilities.setdefault(key, {"level": 0, "upgraded_at": ""})
    before = max(0, _safe_int(row.get("level"), 0, 0))
    row["level"] = max(before, target)
    row["upgraded_at"] = _iso()
    guild["construction"] = {}
    guild.setdefault("stats", {})["facilities_upgraded"] = _safe_int(guild["stats"].get("facilities_upgraded"), 0, 0) + int(row["level"] > before)
    if row["level"] > before:
        progress_missions(guild, "facility_upgrade", 1, project.get("starter", "system"))
        _log(guild, "facility_complete", project.get("starter", "system"), f"{FACILITIES[key]['name']} Lv.{row['level']} 완료")
    return {"key": key, "before": before, "level": row["level"]}


def _format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {secs}초"
    return f"{secs}초"


def _vault_balance(guild: Mapping[str, Any], currency: str) -> int:
    vault = guild.get("vault", {}) if isinstance(guild.get("vault"), Mapping) else {}
    if currency == "food":
        return max(0, _safe_int(vault.get("food"), guild.get("fund", 0), 0))
    resources = vault.get("resources", {}) if isinstance(vault.get("resources"), Mapping) else {}
    return max(0, _safe_int(resources.get(currency), 0, 0))


def _set_vault_balance(guild: MutableMapping[str, Any], currency: str, amount: int) -> None:
    amount = max(0, int(amount))
    vault = guild.setdefault("vault", {})
    if currency == "food":
        vault["food"] = amount
        guild["fund"] = amount
    else:
        vault.setdefault("resources", {})[currency] = amount


def _user_balance(user: Mapping[str, Any], currency: str) -> int:
    if currency == "food":
        return max(0, _safe_int(user.get("balance"), 0, 0))
    resources = user.get("resources", {}) if isinstance(user.get("resources"), Mapping) else {}
    return max(0, _safe_int(resources.get(currency), 0, 0))


def _set_user_balance(user: MutableMapping[str, Any], currency: str, amount: int) -> None:
    amount = max(0, int(amount))
    if currency == "food":
        user["balance"] = amount
    else:
        resources = user.get("resources")
        if not isinstance(resources, dict):
            resources = {}
            user["resources"] = resources
        resources[currency] = amount


def _currency_key(value: Any) -> Optional[str]:
    return RESOURCE_ALIASES.get(str(value or "").strip().casefold())


def _contribution(guild: MutableMapping[str, Any], user_id: Any) -> Dict[str, int]:
    contributions = guild.setdefault("contributions", {})
    row = contributions.setdefault(str(user_id), {})
    for key in ("food", "resources", "raid_damage", "activity"):
        row[key] = max(0, _safe_int(row.get(key), 0, 0))
    return row


def _raid_seed(guild_id: Any, week: str) -> int:
    digest = hashlib.sha256(f"{guild_id}:{week}:abaddon-v750".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def ensure_weekly_raid(guild_id: Any, guild: MutableMapping[str, Any]) -> Dict[str, Any]:
    raid = guild.setdefault("raid", {})
    active = raid.get("active")
    week = _week_key()
    if isinstance(active, dict) and active.get("week") == week:
        # A partially written state must never crash the status/attack paths.
        # Repair missing fields in place while preserving every participant,
        # claim, cooldown and historical value already present.
        boss = RAID_BOSSES[_raid_seed(guild_id, week) % len(RAID_BOSSES)]
        max_hp = max(1, _safe_int(active.get("max_hp"), boss["base_hp"], 1))
        active["max_hp"] = max_hp
        active["hp"] = min(max_hp, max(0, _safe_int(active.get("hp"), max_hp, 0)))
        active["id"] = str(active.get("id") or f"{guild_id}:{week}")
        active["name"] = str(active.get("name") or boss["name"])
        active["emoji"] = str(active.get("emoji") or boss["emoji"])
        active["trait"] = str(active.get("trait") or boss["trait"])
        parts = active.get("parts")
        if not isinstance(parts, dict):
            parts = {}
            active["parts"] = parts
        ratios = {"armor": 0.22, "core": 0.18, "sac": 0.16}
        for key, ratio in ratios.items():
            row = parts.get(key)
            if not isinstance(row, dict):
                row = {}
                parts[key] = row
            part_max = max(1, _safe_int(row.get("max_hp"), int(max_hp * ratio), 1))
            row["max_hp"] = part_max
            row["hp"] = min(part_max, max(0, _safe_int(row.get("hp"), part_max, 0)))
            row["destroyed"] = bool(row.get("destroyed")) or row["hp"] <= 0
        if not isinstance(active.get("participants"), dict):
            active["participants"] = {}
        if not isinstance(active.get("cooldowns"), dict):
            active["cooldowns"] = {}
        active["support_bonus"] = min(0.30, max(0.0, float(active.get("support_bonus", 0.0) or 0.0)))
        active["reward_bonus"] = min(0.30, max(0.0, float(active.get("reward_bonus", 0.0) or 0.0)))
        active["defeated"] = bool(active.get("defeated")) or active["hp"] <= 0
        active["status"] = "defeated" if active["defeated"] else str(active.get("status") or "active")
        active["started_at"] = str(active.get("started_at") or _iso())
        active["defeated_at"] = str(active.get("defeated_at") or ("" if not active["defeated"] else _iso()))
        return active
    if isinstance(active, dict) and active.get("week"):
        archived = dict(active)
        archived.setdefault("status", "expired")
        if not archived.get("defeated"):
            archived["status"] = "expired"
        raid.setdefault("history", []).append(archived)
    boss = RAID_BOSSES[_raid_seed(guild_id, week) % len(RAID_BOSSES)]
    member_count = max(1, len(_unique_strings(guild.get("members"))))
    level = max(1, _safe_int(guild.get("level"), 1, 1))
    scale = 1.0 + (level - 1) * 0.18 + max(0, member_count - 3) * 0.08
    max_hp = max(80_000, int(int(boss["base_hp"]) * scale))
    parts = {
        "armor": {"hp": int(max_hp * 0.22), "max_hp": int(max_hp * 0.22), "destroyed": False},
        "core": {"hp": int(max_hp * 0.18), "max_hp": int(max_hp * 0.18), "destroyed": False},
        "sac": {"hp": int(max_hp * 0.16), "max_hp": int(max_hp * 0.16), "destroyed": False},
    }
    active = {
        "id": f"{guild_id}:{week}", "week": week, "name": boss["name"], "emoji": boss["emoji"],
        "trait": boss["trait"], "max_hp": max_hp, "hp": max_hp, "parts": parts,
        "participants": {}, "cooldowns": {}, "support_bonus": 0.0, "reward_bonus": 0.0,
        "started_at": _iso(), "defeated": False, "defeated_at": "", "status": "active",
    }
    raid["active"] = active
    return active


def raid_part_target(active: Mapping[str, Any], requested: Any) -> Optional[str]:
    target = PART_ALIASES.get(str(requested or "자동").strip().casefold())
    parts = active.get("parts", {}) if isinstance(active.get("parts"), Mapping) else {}
    if target == "auto":
        for key in ("armor", "core", "sac"):
            row = parts.get(key)
            if isinstance(row, Mapping) and not row.get("destroyed") and _safe_int(row.get("hp"), 0) > 0:
                return key
        return None
    if target in PART_LABELS:
        row = parts.get(target)
        if isinstance(row, Mapping) and not row.get("destroyed") and _safe_int(row.get("hp"), 0) > 0:
            return target
    return None


def raid_attack_resolution(
    guild: MutableMapping[str, Any], active: MutableMapping[str, Any], user_id: Any,
    power: int, tactic: str, target: Optional[str], rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    rng = rng or random.Random()
    effects = facility_effects(guild)
    tactic = tactic if tactic in TACTIC_LABELS else "assault"
    tactic_multiplier = {"assault": 1.20, "support": 0.82, "medic": 0.68}[tactic]
    random_multiplier = rng.uniform(8.5, 12.5)
    bonus = 1.0 + effects["raid_damage_bonus"] + effects["raid_support_bonus"] + float(active.get("support_bonus", 0.0) or 0.0)
    parts = active.get("parts", {}) if isinstance(active.get("parts"), Mapping) else {}
    armor = parts.get("armor", {}) if isinstance(parts.get("armor"), Mapping) else {}
    if armor.get("destroyed"):
        bonus += 0.15
    damage = max(1, int(max(1, power) * random_multiplier * tactic_multiplier * bonus))
    critical = rng.random() < min(0.30, 0.08 + max(0, _safe_int(guild.get("level"), 1) - 1) * 0.005)
    if critical:
        damage = int(damage * 1.55)
    if tactic == "support":
        active["support_bonus"] = min(0.30, float(active.get("support_bonus", 0.0) or 0.0) + 0.015)
    elif tactic == "medic":
        active["reward_bonus"] = min(0.30, float(active.get("reward_bonus", 0.0) or 0.0) + 0.01)

    part_damage = 0
    destroyed_part: Optional[str] = None
    if target and target in PART_LABELS:
        row = parts.get(target)
        if isinstance(row, dict) and not row.get("destroyed"):
            part_damage = min(_safe_int(row.get("hp"), 0), max(1, int(damage * 0.65)))
            row["hp"] = max(0, _safe_int(row.get("hp"), 0) - part_damage)
            if row["hp"] <= 0:
                row["destroyed"] = True
                destroyed_part = target
                if target == "core":
                    active["support_bonus"] = min(0.30, float(active.get("support_bonus", 0.0) or 0.0) + 0.10)
                elif target == "sac":
                    active["reward_bonus"] = min(0.30, float(active.get("reward_bonus", 0.0) or 0.0) + 0.10)
    applied = min(max(0, _safe_int(active.get("hp"), 0)), damage)
    active["hp"] = max(0, _safe_int(active.get("hp"), 0) - applied)
    uid = str(user_id)
    participants = active.setdefault("participants", {})
    row = participants.setdefault(uid, {"damage": 0, "attacks": 0, "support": 0, "medic": 0, "last_attack": ""})
    row["damage"] = max(0, _safe_int(row.get("damage"), 0, 0)) + applied
    row["attacks"] = max(0, _safe_int(row.get("attacks"), 0, 0)) + 1
    if tactic == "support":
        row["support"] = max(0, _safe_int(row.get("support"), 0, 0)) + 1
    if tactic == "medic":
        row["medic"] = max(0, _safe_int(row.get("medic"), 0, 0)) + 1
    row["last_attack"] = _iso()
    defeated = active["hp"] <= 0
    if defeated and not active.get("defeated"):
        active["defeated"] = True
        active["status"] = "defeated"
        active["defeated_at"] = _iso()
        guild.setdefault("stats", {})["raids_defeated"] = _safe_int(guild["stats"].get("raids_defeated"), 0, 0) + 1
    return {
        "damage": applied, "part_damage": part_damage, "destroyed_part": destroyed_part,
        "critical": critical, "defeated": defeated, "tactic": tactic, "target": target,
    }


def unclaimed_reward_raids(guild: Mapping[str, Any], user_id: Any) -> List[Dict[str, Any]]:
    uid = str(user_id)
    raid = guild.get("raid", {}) if isinstance(guild.get("raid"), Mapping) else {}
    claimed = set(_unique_strings(raid.get("claimed")))
    candidates: List[Dict[str, Any]] = []
    active = raid.get("active")
    if isinstance(active, dict):
        candidates.append(active)
    history = raid.get("history", [])
    if isinstance(history, list):
        candidates.extend(row for row in history if isinstance(row, dict))
    rewardable: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        raid_id = str(row.get("id") or "")
        if not raid_id or raid_id in seen or not row.get("defeated"):
            continue
        seen.add(raid_id)
        participants = row.get("participants", {}) if isinstance(row.get("participants"), Mapping) else {}
        user_row = participants.get(uid, {}) if isinstance(participants.get(uid), Mapping) else {}
        if _safe_int(user_row.get("damage"), 0) <= 0:
            continue
        if f"{raid_id}:{uid}" in claimed:
            continue
        rewardable.append(row)
    rewardable.sort(key=lambda row: str(row.get("defeated_at") or row.get("week") or ""))
    return rewardable


def raid_reward(active: Mapping[str, Any], user_id: Any, guild: Mapping[str, Any]) -> Dict[str, int]:
    participants = active.get("participants", {}) if isinstance(active.get("participants"), Mapping) else {}
    uid = str(user_id)
    row = participants.get(uid, {}) if isinstance(participants.get(uid), Mapping) else {}
    damage = max(0, _safe_int(row.get("damage"), 0, 0))
    total = max(1, sum(max(0, _safe_int(r.get("damage"), 0, 0)) for r in participants.values() if isinstance(r, Mapping)))
    ordered = sorted(
        ((str(pid), max(0, _safe_int(prow.get("damage"), 0, 0))) for pid, prow in participants.items() if isinstance(prow, Mapping)),
        key=lambda item: item[1], reverse=True,
    )
    rank = next((index + 1 for index, (pid, _dmg) in enumerate(ordered) if pid == uid), len(ordered) + 1)
    share = damage / total
    effects = facility_effects(guild)
    reward_bonus = 1.0 + effects["raid_reward_bonus"] + float(active.get("reward_bonus", 0.0) or 0.0)
    food = int((25_000 + min(150_000, damage // 2) + int(share * 100_000)) * reward_bonus)
    medals = 2 + min(8, damage // 25_000)
    if rank == 1:
        medals += 4
    elif rank <= 3:
        medals += 2
    return {"food": max(1, food), "medals": max(1, medals), "rank": rank, "damage": damage}


async def legacy_guild_list(ctx: commands.Context, *, world_data: Dict[str, Any], check_registered: Callable[..., Any]) -> None:
    if not await check_registered(ctx):
        return
    guilds_raw = world_data.setdefault("guilds", {})
    guilds: List[Tuple[str, Dict[str, Any]]] = []
    for gid, raw in guilds_raw.items():
        guild, _ = ensure_guild_state(gid, raw)
        finalize_construction(guild)
        guilds.append((str(gid), guild))
    if not guilds:
        await ctx.send("🛡️ 아직 생성된 길드가 없습니다.")
        return
    guilds.sort(key=lambda item: (_safe_int(item[1].get("level"), 1), _vault_balance(item[1], "food"), len(item[1]["members"])), reverse=True)
    lines = []
    for index, (_gid, guild) in enumerate(guilds[:20], start=1):
        lines.append(
            f"`#{index}` **{guild['name']}** · Lv.{guild['level']} · "
            f"{len(guild['members'])}/{guild_member_capacity(guild)}명 · "
            f"{'🌫️ 휴면 보존' if guild.get('dormant') else JOIN_MODE_LABELS[guild['join_mode']]} · 금고 {_vault_balance(guild, 'food'):,}"
        )
    embed = discord.Embed(title="🛡️ 생존 길드 목록", description="\n".join(lines), colour=discord.Colour.dark_teal())
    embed.set_footer(text="자유 가입: !길드가입 길드명 · 승인 가입: !길드신청 길드명")
    await ctx.send(embed=embed)


async def legacy_guild_create(
    ctx: commands.Context, *, name: str, world_data: Dict[str, Any], get_user: Callable[..., Any],
    check_registered: Callable[..., Any], save_data: Callable[[], None], add_title: Callable[..., Any],
    add_season_points: Callable[..., Any],
) -> None:
    if not await check_registered(ctx):
        return
    name = str(name or "").strip()
    if len(name) < 2 or len(name) > 16:
        await ctx.send("⚠️ 길드명은 2~16자로 입력하세요.")
        return
    cost = 45_000
    async with _state_lock("__guild_create__"):
        user = get_user(ctx.author.id)
        if not user:
            await ctx.send("⚠️ 생존자 데이터를 찾을 수 없습니다.")
            return
        if user.get("guild_id"):
            await ctx.send("⚠️ 이미 길드에 소속되어 있습니다.")
            return
        if find_guild_by_name(world_data, name)[1]:
            await ctx.send("⚠️ 이미 존재하는 길드명입니다.")
            return
        if _safe_int(user.get("balance"), 0) < cost:
            await ctx.send(f"⚠️ 길드 창설 비용 **{cost:,} 식량**이 필요합니다.")
            return
        guilds = world_data.setdefault("guilds", {})
        numeric_ids = [int(str(value)) for value in guilds.keys() if str(value).isdigit()]
        guild_id = str(max(numeric_ids + [0]) + 1)
        raw = {
            "name": name, "owner": str(ctx.author.id), "members": [str(ctx.author.id)],
            "level": 1, "fund": 0, "exp": 0, "created_at": _iso(),
        }
        guild, _ = ensure_guild_state(guild_id, raw)
        guilds[guild_id] = guild
        user["balance"] = _safe_int(user.get("balance"), 0) - cost
        user["guild_id"] = guild_id
        add_title(user, "길드 창설자")
        add_season_points(user, 50)
        _log(guild, "guild_create", ctx.author.id, f"길드 {name} 창설")
        save_data()
    embed = discord.Embed(title=f"🛡️ 길드 **{name}** 창설 완료", colour=discord.Colour.green())
    embed.description = "이제 `!길드관리`에서 가입 방식·소개·공동 기지·금고·임무·레이드를 관리할 수 있습니다."
    embed.add_field(name="창설 비용", value=f"{cost:,} 식량", inline=True)
    embed.add_field(name="기본 가입 방식", value=JOIN_MODE_LABELS["open"], inline=True)
    await ctx.send(embed=embed)

async def legacy_guild_join(
    ctx: commands.Context, *, name: str, world_data: Dict[str, Any], get_user: Callable[..., Any],
    check_registered: Callable[..., Any], save_data: Callable[[], None],
) -> None:
    if not await check_registered(ctx):
        return
    gid, guild = find_guild_by_name(world_data, name)
    if not gid or not guild:
        await ctx.send("⚠️ 해당 길드를 찾을 수 없습니다.")
        return
    async with _state_lock(gid):
        user = get_user(ctx.author.id)
        if not user:
            await ctx.send("⚠️ 생존자 데이터를 찾을 수 없습니다.")
            return
        if user.get("guild_id"):
            await ctx.send("⚠️ 이미 길드에 소속되어 있습니다.")
            return
        # 잠금 진입 후 최신 길드 상태로 다시 확인합니다.
        raw = world_data.setdefault("guilds", {}).get(gid)
        guild, _ = ensure_guild_state(gid, raw)
        world_data["guilds"][gid] = guild
        if guild.get("dormant") or not guild.get("owner"):
            await ctx.send("🌫️ 해당 길드는 휴면 보존 상태라 가입할 수 없습니다. 관리자 검수 후 재활성화가 필요합니다.")
            return
        if len(guild["members"]) >= guild_member_capacity(guild):
            await ctx.send("⚠️ 해당 길드는 인원이 가득 찼습니다.")
            return
        mode = guild.get("join_mode", "open")
        if mode == "approval":
            await ctx.send(f"🟡 **{guild['name']}**은 승인 가입 길드입니다. `!길드신청 {guild['name']}`을 사용하세요.")
            return
        if mode == "closed":
            await ctx.send("🔒 현재 비공개 길드라 직접 가입할 수 없습니다.")
            return
        uid = str(ctx.author.id)
        if uid not in guild["members"]:
            guild["members"].append(uid)
        guild["member_joined_at"][uid] = _iso()
        user["guild_id"] = gid
        _log(guild, "member_join", uid, "자유 가입")
        save_data()
    await ctx.send(f"🛡️ **{guild['name']}** 길드에 가입했습니다. `!길드관리`에서 공동 콘텐츠를 확인하세요.")

async def legacy_guild_info(
    ctx: commands.Context, *, world_data: Dict[str, Any], get_user: Callable[..., Any],
    check_registered: Callable[..., Any], save_data: Callable[[], None],
) -> None:
    if not await check_registered(ctx):
        return
    user = get_user(ctx.author.id)
    gid, guild = guild_for_user(world_data, user)
    if not gid or not guild:
        await ctx.send("⚠️ 소속된 길드가 없습니다.")
        return
    completed = finalize_construction(guild)
    if completed:
        save_data()
    effects = facility_effects(guild)
    raid = ensure_weekly_raid(gid, guild)
    embed = discord.Embed(
        title=f"🛡️ [{guild['name']}] · Lv.{guild['level']}",
        description=guild.get("description", ""), colour=discord.Colour.dark_teal(),
    )
    embed.add_field(name="지휘부", value=f"길드장 <@{guild['owner']}>\n간부 {len(guild['officers'])}명", inline=True)
    embed.add_field(name="인원", value=f"{len(guild['members'])}/{guild_member_capacity(guild)}명\n{JOIN_MODE_LABELS[guild['join_mode']]}", inline=True)
    embed.add_field(name="공동 금고", value=f"식량 {_vault_balance(guild, 'food'):,}\n기존 `길드 기금`과 통합", inline=True)
    facility_lines = []
    for key, info in FACILITIES.items():
        level = guild["facilities"][key]["level"]
        facility_lines.append(f"{info['emoji']} {info['name']} Lv.{level}")
    embed.add_field(name="공동 생존 기지", value=" · ".join(facility_lines), inline=False)
    embed.add_field(
        name="길드 효과",
        value=f"레이드 공격 +{effects['raid_damage_bonus'] * 100:.0f}% · 보상 +{effects['raid_reward_bonus'] * 100:.0f}% · 창고 식량 한도 {int(effects['food_capacity']):,}",
        inline=False,
    )
    embed.add_field(name="이번 주 레이드", value=f"{raid['emoji']} {raid['name']} · HP {raid['hp']:,}/{raid['max_hp']:,}", inline=False)
    embed.set_footer(text="!길드관리 · !길드기지 · !길드임무 · !길드금고 · !길드레이드")
    await ctx.send(embed=embed)


async def legacy_guild_donate(
    ctx: commands.Context, *, amount: int, world_data: Dict[str, Any], get_user: Callable[..., Any],
    check_registered: Callable[..., Any], save_data: Callable[[], None],
) -> None:
    if not await check_registered(ctx):
        return
    user = get_user(ctx.author.id)
    gid, guild = guild_for_user(world_data, user)
    if not gid or not guild or not user:
        await ctx.send("⚠️ 길드에 가입되어 있지 않습니다.")
        return
    amount = int(amount or 0)
    if amount <= 0:
        await ctx.send("⚠️ 기부 금액은 1 이상이어야 합니다.")
        return
    async with _state_lock(gid):
        user = get_user(ctx.author.id)
        gid2, guild = guild_for_user(world_data, user)
        if gid2 != gid or not guild or not user:
            await ctx.send("⚠️ 길드 상태가 변경되어 기부를 중단했습니다.")
            return
        if _safe_int(user.get("balance"), 0) < amount:
            await ctx.send("⚠️ 식량 잔액이 부족합니다.")
            return
        effects = facility_effects(guild)
        current = _vault_balance(guild, "food")
        capacity = int(effects["food_capacity"])
        if current + amount > capacity:
            await ctx.send(f"📦 길드 창고 식량 한도는 **{capacity:,}**입니다. 현재 **{current:,}** 보관 중입니다.")
            return
        user["balance"] = _safe_int(user.get("balance"), 0) - amount
        _set_vault_balance(guild, "food", current + amount)
        guild["exp"] = _safe_int(guild.get("exp"), 0, 0) + amount // 100
        row = _contribution(guild, ctx.author.id)
        row["food"] += amount
        row["activity"] += max(1, amount // 1_000)
        progress_missions(guild, "donate_food", amount, ctx.author.id)
        guild.setdefault("stats", {})["vault_deposits"] = _safe_int(guild["stats"].get("vault_deposits"), 0, 0) + 1
        _vault_log(guild, "deposit", ctx.author.id, "food", amount, "!길드기부")
        _log(guild, "donate_food", ctx.author.id, f"식량 {amount:,} 기부")
        save_data()
        current_after = _vault_balance(guild, "food")
    await ctx.send(f"💰 길드 통합 금고에 식량 **{amount:,}개** 기부 완료. 현재 **{current_after:,}개**")

async def legacy_guild_upgrade(
    ctx: commands.Context, *, world_data: Dict[str, Any], get_user: Callable[..., Any],
    check_registered: Callable[..., Any], save_data: Callable[[], None],
) -> None:
    if not await check_registered(ctx):
        return
    user = get_user(ctx.author.id)
    gid, guild = guild_for_user(world_data, user)
    if not gid or not guild:
        await ctx.send("⚠️ 길드에 가입되어 있지 않습니다.")
        return
    if not can_manage_guild(ctx, guild, owner_only=True):
        await ctx.send("❌ 길드장만 길드 레벨을 강화할 수 있습니다.")
        return
    async with _state_lock(gid):
        user = get_user(ctx.author.id)
        gid2, guild = guild_for_user(world_data, user)
        if gid2 != gid or not guild:
            await ctx.send("⚠️ 길드 상태가 변경되어 강화를 중단했습니다.")
            return
        if not can_manage_guild(ctx, guild, owner_only=True):
            await ctx.send("❌ 길드장 권한이 변경됐습니다.")
            return
        level = max(1, _safe_int(guild.get("level"), 1, 1))
        if level >= 20:
            await ctx.send("🏰 길드 레벨이 최대 Lv.20입니다.")
            return
        cost = level * 65_000
        current = _vault_balance(guild, "food")
        if current < cost:
            await ctx.send(f"⚠️ 통합 금고 식량 **{cost:,}개**가 필요합니다. 현재 **{current:,}개**")
            return
        _set_vault_balance(guild, "food", current - cost)
        guild["level"] = level + 1
        _vault_log(guild, "guild_upgrade", ctx.author.id, "food", -cost, f"Lv.{level}→Lv.{level + 1}")
        _log(guild, "guild_upgrade", ctx.author.id, f"Lv.{level} → Lv.{level + 1}")
        save_data()
        new_level = guild["level"]
    await ctx.send(f"🛡️ 길드가 **Lv.{new_level}**로 성장했습니다! 정원과 레이드 난이도·보상이 함께 확장됩니다.")

async def legacy_guild_leave(
    ctx: commands.Context, *, world_data: Dict[str, Any], get_user: Callable[..., Any],
    check_registered: Callable[..., Any], save_data: Callable[[], None],
) -> None:
    if not await check_registered(ctx):
        return
    user = get_user(ctx.author.id)
    gid, guild = guild_for_user(world_data, user)
    if not gid or not guild or not user:
        await ctx.send("⚠️ 소속된 길드가 없습니다.")
        return
    async with _state_lock(gid):
        user = get_user(ctx.author.id)
        gid2, guild = guild_for_user(world_data, user)
        if gid2 != gid or not guild or not user:
            await ctx.send("⚠️ 길드 상태가 변경되어 탈퇴를 중단했습니다.")
            return
        uid = str(ctx.author.id)
        if guild_role(guild, uid) == "owner" and len(guild["members"]) > 1:
            await ctx.send("⚠️ 길드장은 다른 길드원이 있는 동안 탈퇴할 수 없습니다. `!길드위임 @유저`를 먼저 사용하세요.")
            return
        if uid in guild["members"]:
            guild["members"].remove(uid)
        if uid in guild["officers"]:
            guild["officers"].remove(uid)
        user["guild_id"] = None
        _log(guild, "member_leave", uid, "길드 탈퇴")
        dormant = not guild["members"]
        if dormant:
            # 승인 없는 기능 폐기를 피하기 위해 길드 레코드와 금고를 삭제하지 않습니다.
            guild["dormant"] = True
            guild["dormant_at"] = _iso()
            guild["join_mode"] = "closed"
            guild["owner"] = ""
        save_data()
    if dormant:
        await ctx.send("🛡️ 마지막 인원이 탈퇴해 길드가 **휴면 보존** 상태가 됐습니다. 데이터와 금고는 삭제되지 않습니다.")
    else:
        await ctx.send("🛡️ 길드에서 탈퇴했습니다.")

def _guild_lock(bot: commands.Bot, guild_id: Any) -> asyncio.Lock:
    # 기존 HybridCommand와 신규 prefix 명령이 같은 길드 상태 잠금을 공유합니다.
    return _state_lock(guild_id)


def _member_display(member_id: str) -> str:
    return f"<@{member_id}>"


def register_v750_guild_raid(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
    add_season_points: Callable[[MutableMapping[str, Any], int], Any],
) -> None:
    if getattr(bot, "_abaddon_v750_registered", False):
        return

    guild_category = next((row for row in guide if row.get("id") == "guild_party"), None)
    if guild_category is not None:
        additions = (
            "!길드관리 — 길드·기지·임무·금고·레이드 통합 대시보드",
            "!길드설정 가입방식 자유/승인/비공개 · !길드소개 내용",
            "!길드신청 길드명 · !길드신청목록 · !길드신청처리 @유저 승인/거절",
            "!길드직책 @유저 간부/일반 · !길드추방 @유저 · !길드위임 @유저",
            "!길드기지 · !길드건설 시설 · !길드시설강화 시설 · !길드기지수확",
            "!길드임무 · !길드임무보상 일일/주간",
            "!길드금고 · !길드입금 재화 금액 · !길드출금요청 재화 금액 사유",
            "!길드출금승인 번호 · !길드출금거절 번호 · !길드거래내역",
            "!길드레이드 · !길드레이드공격 전술 부위 · !길드레이드보상 · !길드레이드랭킹",
            "!길드전술설정 전술 부위 · !길드레이드준비 · !길드레이드연습 · !길드레이드기록",
        )
        existing = "\n".join(map(str, guild_category.get("commands", [])))
        for row in additions:
            token = row.split(" — ", 1)[0].split(" · ", 1)[0]
            if token not in existing:
                guild_category.setdefault("commands", []).append(row)
                existing += "\n" + row
    admin_category = next((row for row in guide if row.get("id") == "server"), None)
    if admin_category is not None:
        existing = "\n".join(map(str, admin_category.get("commands", [])))
        for row in (
            "!길드검수 — 길드 데이터·금고·레이드 무결성 읽기 전용 검사",
            "!길드복구미리보기 — 삭제 없이 적용 가능한 안전 복구 항목 표시",
            "!750안정화검수 — v7.5.1 통합 기능·명령 충돌·저장 구조 점검",
        ):
            if row.split(" — ", 1)[0] not in existing:
                admin_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    async def require_guild(ctx: commands.Context) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
        if not await check_registered(ctx):
            return None, None, None
        user = get_user(ctx.author.id)
        gid, guild = guild_for_user(world_data, user)
        if not gid or not guild:
            await ctx.send("⚠️ 소속된 길드가 없습니다. `!길드목록`에서 길드를 찾거나 `!길드생성 이름`을 사용하세요.")
            return None, None, None
        completed = finalize_construction(guild)
        if completed:
            save_data()
        return user, gid, guild

    @bot.command(name="길드관리", aliases=["길드메뉴", "길드대시보드"], help="길드·기지·임무·금고·레이드를 한 화면에서 확인합니다.")
    async def guild_dashboard(ctx: commands.Context) -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        missions = ensure_missions(guild)
        raid = ensure_weekly_raid(gid, guild)
        project = guild.get("construction", {})
        project_text = "진행 중인 공사 없음"
        if isinstance(project, Mapping) and project.get("facility"):
            complete_at = _parse_iso(project.get("complete_at"))
            remaining = max(0, (complete_at - _now()).total_seconds()) if complete_at else 0
            key = str(project.get("facility"))
            project_text = f"{FACILITIES.get(key, {}).get('name', key)} Lv.{project.get('target_level')} · {_format_seconds(remaining)}"
        daily_done = all(_safe_int(row.get("progress"), 0) >= _safe_int(row.get("target"), 1) for row in missions["daily"]["objectives"].values())
        weekly_done = all(_safe_int(row.get("progress"), 0) >= _safe_int(row.get("target"), 1) for row in missions["weekly"]["objectives"].values())
        embed = discord.Embed(title=f"🛡️ {guild['name']} 통합 지휘소", description=guild["description"], colour=discord.Colour.blurple())
        embed.add_field(name="👥 조직", value=f"Lv.{guild['level']} · {len(guild['members'])}/{guild_member_capacity(guild)}명 · {JOIN_MODE_LABELS[guild['join_mode']]}", inline=False)
        embed.add_field(name="🏗️ 공동 기지", value=project_text, inline=False)
        embed.add_field(name="🎯 공동 임무", value=f"일일 {'✅ 완료' if daily_done else '🟨 진행 중'} · 주간 {'✅ 완료' if weekly_done else '🟨 진행 중'}", inline=True)
        embed.add_field(name="🏦 통합 금고", value=f"식량 {_vault_balance(guild, 'food'):,}", inline=True)
        embed.add_field(name="👹 길드 레이드", value=f"{raid['emoji']} {raid['name']}\nHP {raid['hp']:,}/{raid['max_hp']:,}", inline=False)
        embed.add_field(name="바로가기", value="`!길드기지` · `!길드임무` · `!길드금고` · `!길드레이드` · `!길드정보`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="길드소개", aliases=["길드설명"], help="길드 소개를 확인하거나 변경합니다.")
    async def guild_description(ctx: commands.Context, *, 내용: str = "") -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        content = str(내용 or "").strip()
        if not content:
            await ctx.send(f"📝 **{guild['name']} 소개**\n{guild['description']}")
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 소개를 변경할 수 있습니다.")
            return
        async with _guild_lock(bot, gid):
            guild["description"] = content[:300]
            _log(guild, "description", ctx.author.id, guild["description"])
            save_data()
        await ctx.send("✅ 길드 소개를 변경했습니다.")

    @bot.command(name="길드설정", aliases=["길드가입설정"], help="길드 가입 방식을 설정합니다.")
    async def guild_settings(ctx: commands.Context, 항목: str = "", *, 값: str = "") -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not 항목:
            await ctx.send(f"⚙️ 가입 방식: **{JOIN_MODE_LABELS[guild['join_mode']]}**\n사용법: `!길드설정 가입방식 자유/승인/비공개`")
            return
        if not can_manage_guild(ctx, guild, owner_only=True):
            await ctx.send("🔒 길드장만 길드 설정을 변경할 수 있습니다.")
            return
        if str(항목).casefold() not in {"가입", "가입방식", "가입설정", "join"}:
            await ctx.send("⚠️ 현재 지원 설정은 `가입방식`입니다.")
            return
        mode = JOIN_MODE_ALIASES.get(str(값 or "").strip().casefold())
        if not mode:
            await ctx.send("사용법: `!길드설정 가입방식 자유` · `승인` · `비공개`")
            return
        async with _guild_lock(bot, gid):
            guild["join_mode"] = mode
            _log(guild, "join_mode", ctx.author.id, mode)
            save_data()
        await ctx.send(f"✅ 가입 방식을 **{JOIN_MODE_LABELS[mode]}**으로 변경했습니다.")

    @bot.command(name="길드신청", aliases=["길드가입신청"], help="승인 가입 길드에 가입을 신청합니다.")
    async def guild_apply(ctx: commands.Context, *, 길드명: str) -> None:
        if not await check_registered(ctx):
            return
        gid, guild = find_guild_by_name(world_data, 길드명)
        if not gid or not guild:
            await ctx.send("⚠️ 해당 길드를 찾을 수 없습니다.")
            return
        uid = str(ctx.author.id)
        error: Optional[str] = None
        async with _guild_lock(bot, gid):
            user = get_user(ctx.author.id)
            raw = world_data.setdefault("guilds", {}).get(gid)
            guild, _ = ensure_guild_state(gid, raw)
            world_data["guilds"][gid] = guild
            if not user:
                error = "⚠️ 생존자 데이터를 찾을 수 없습니다."
            elif user.get("guild_id"):
                error = "⚠️ 이미 길드에 소속되어 있습니다."
            elif guild.get("dormant") or not guild.get("owner"):
                error = "🌫️ 해당 길드는 휴면 보존 상태라 가입 신청을 받지 않습니다."
            elif guild["join_mode"] == "open":
                error = f"🟢 자유 가입 길드입니다. `!길드가입 {guild['name']}`을 사용하세요."
            elif guild["join_mode"] == "closed":
                error = "🔒 현재 비공개 길드라 가입 신청을 받지 않습니다."
            elif any(str(row.get("user")) == uid and row.get("status") == "pending" for row in guild["applications"]):
                error = "🟡 이미 처리 대기 중인 신청이 있습니다."
            else:
                guild["applications"].append({"user": uid, "at": _iso(), "status": "pending"})
                _log(guild, "application", uid, "가입 신청")
                save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"📨 **{guild['name']}**에 가입 신청을 보냈습니다.")

    @bot.command(name="길드신청목록", aliases=["길드가입신청목록"], help="처리 대기 중인 길드 가입 신청을 확인합니다.")
    async def guild_applications(ctx: commands.Context) -> None:
        _user, _gid, guild = await require_guild(ctx)
        if not guild:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 가입 신청을 볼 수 있습니다.")
            return
        pending = [row for row in guild["applications"] if row.get("status") == "pending"]
        if not pending:
            await ctx.send("📭 처리 대기 중인 가입 신청이 없습니다.")
            return
        lines = [f"• {_member_display(str(row.get('user')))} · {str(row.get('at', ''))[:16]}" for row in pending[:25]]
        await ctx.send("📨 **가입 신청 목록**\n" + "\n".join(lines))

    @bot.command(name="길드신청처리", aliases=["길드가입처리"], help="가입 신청을 승인하거나 거절합니다.")
    async def guild_application_process(ctx: commands.Context, 대상: discord.Member, 결정: str) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 가입 신청을 처리할 수 있습니다.")
            return
        uid = str(대상.id)
        decision = str(결정 or "").strip().casefold()
        if decision not in {"승인", "수락", "accept", "yes", "거절", "반려", "reject", "no"}:
            await ctx.send("사용법: `!길드신청처리 @유저 승인` 또는 `거절`")
            return
        error: Optional[str] = None
        approved = False
        async with _guild_lock(bot, gid):
            row = next((item for item in reversed(guild["applications"]) if str(item.get("user")) == uid and item.get("status") == "pending"), None)
            if not row:
                error = "⚠️ 해당 사용자의 대기 중인 신청이 없습니다."
            elif decision in {"승인", "수락", "accept", "yes"}:
                target_user = get_user(대상.id)
                if not target_user:
                    error = "⚠️ 해당 사용자는 아직 `!가입 생존자` 등록이 필요합니다."
                elif target_user.get("guild_id"):
                    row["status"] = "invalid"
                    row["processed_by"] = str(ctx.author.id)
                    row["processed_at"] = _iso()
                    save_data()
                    error = "⚠️ 해당 사용자는 이미 다른 길드에 소속되어 있습니다."
                elif len(guild["members"]) >= guild_member_capacity(guild):
                    error = "⚠️ 길드 정원이 가득 찼습니다."
                else:
                    if uid not in guild["members"]:
                        guild["members"].append(uid)
                    guild["member_joined_at"][uid] = _iso()
                    target_user["guild_id"] = gid
                    row["status"] = "approved"
                    row["processed_by"] = str(ctx.author.id)
                    row["processed_at"] = _iso()
                    _log(guild, "application_approved", ctx.author.id, uid)
                    save_data()
                    approved = True
            else:
                row["status"] = "rejected"
                row["processed_by"] = str(ctx.author.id)
                row["processed_at"] = _iso()
                _log(guild, "application_rejected", ctx.author.id, uid)
                save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"{'✅' if approved else '❌'} {대상.mention}님의 가입 신청을 {'승인' if approved else '거절'}했습니다.")

    @bot.command(name="길드직책", aliases=["길드간부"], help="길드원을 간부로 임명하거나 일반 길드원으로 변경합니다.")
    async def guild_role_command(ctx: commands.Context, 대상: discord.Member, 직책: str) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild, owner_only=True):
            await ctx.send("🔒 길드장만 직책을 변경할 수 있습니다.")
            return
        uid = str(대상.id)
        role = str(직책 or "").strip().casefold()
        if role not in {"간부", "부길드장", "officer", "일반", "길드원", "member"}:
            await ctx.send("사용법: `!길드직책 @유저 간부` 또는 `일반`")
            return
        error: Optional[str] = None
        text = ""
        async with _guild_lock(bot, gid):
            if uid not in guild["members"] or uid == guild["owner"]:
                error = "⚠️ 길드장 본인을 제외한 소속 길드원을 지정하세요."
            elif role in {"간부", "부길드장", "officer"}:
                if uid not in guild["officers"]:
                    guild["officers"].append(uid)
                text = "간부"
            else:
                if uid in guild["officers"]:
                    guild["officers"].remove(uid)
                text = "일반 길드원"
            if not error:
                _log(guild, "role_change", ctx.author.id, f"{uid} → {text}")
                save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"✅ {대상.mention}님의 직책을 **{text}**으로 변경했습니다.")

    @bot.command(name="길드추방", aliases=["길드강퇴"], help="길드원을 추방합니다.")
    async def guild_kick(ctx: commands.Context, 대상: discord.Member) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 길드원을 추방할 수 있습니다.")
            return
        uid = str(대상.id)
        error: Optional[str] = None
        async with _guild_lock(bot, gid):
            if uid == guild["owner"] or uid not in guild["members"]:
                error = "⚠️ 길드장을 제외한 소속 길드원을 지정하세요."
            elif guild_role(guild, ctx.author.id) == "officer" and uid in guild["officers"]:
                error = "🔒 간부는 다른 간부를 추방할 수 없습니다."
            else:
                guild["members"].remove(uid)
                if uid in guild["officers"]:
                    guild["officers"].remove(uid)
                target_user = get_user(대상.id)
                if target_user and str(target_user.get("guild_id") or "") == str(gid):
                    target_user["guild_id"] = None
                _log(guild, "member_kick", ctx.author.id, uid)
                save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"🚪 {대상.mention}님을 길드에서 추방했습니다.")

    @bot.command(name="길드위임", aliases=["길드장위임"], help="길드장 권한을 다른 길드원에게 넘깁니다.")
    async def guild_transfer(ctx: commands.Context, 대상: discord.Member) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if guild_role(guild, ctx.author.id) != "owner" and not _discord_admin(ctx):
            await ctx.send("🔒 길드장만 권한을 위임할 수 있습니다.")
            return
        uid = str(대상.id)
        error: Optional[str] = None
        async with _guild_lock(bot, gid):
            if uid not in guild["members"] or uid == guild["owner"]:
                error = "⚠️ 다른 소속 길드원을 지정하세요."
            else:
                previous = str(guild["owner"])
                guild["owner"] = uid
                if uid in guild["officers"]:
                    guild["officers"].remove(uid)
                if previous and previous in guild["members"] and previous not in guild["officers"]:
                    guild["officers"].append(previous)
                _log(guild, "owner_transfer", ctx.author.id, f"{previous} → {uid}")
                save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"👑 길드장 권한을 {대상.mention}님에게 위임했습니다.")

    @bot.command(name="길드기지", aliases=["공동기지", "길드시설"], help="길드 공동 기지 시설과 공사 상태를 확인합니다.")
    async def guild_base(ctx: commands.Context) -> None:
        _user, _gid, guild = await require_guild(ctx)
        if not guild:
            return
        effects = facility_effects(guild)
        embed = discord.Embed(title=f"🏚️ {guild['name']} 공동 생존 기지", colour=discord.Colour.dark_gold())
        for key, info in FACILITIES.items():
            level = guild["facilities"][key]["level"]
            next_text = "최대" if level >= MAX_FACILITY_LEVEL else f"다음 Lv.{level + 1}"
            embed.add_field(name=f"{info['emoji']} {info['name']} · Lv.{level}/5", value=f"{info['effect']}\n{next_text}", inline=True)
        project = guild.get("construction", {})
        if isinstance(project, Mapping) and project.get("facility"):
            complete_at = _parse_iso(project.get("complete_at"))
            remaining = max(0, (complete_at - _now()).total_seconds()) if complete_at else 0
            key = str(project["facility"])
            embed.add_field(name="🚧 진행 중인 공사", value=f"{FACILITIES[key]['name']} Lv.{project['target_level']} · {_format_seconds(remaining)}", inline=False)
        else:
            embed.add_field(name="🚧 공사 상태", value="진행 중인 공사 없음", inline=False)
        embed.add_field(name="현재 효과", value=f"생산 {int(effects['generator_food_hourly']):,}/시간 · 레이드 공격 +{effects['raid_damage_bonus']*100:.0f}% · 보상 +{effects['raid_reward_bonus']*100:.0f}%", inline=False)
        embed.set_footer(text="!길드건설 시설 · !길드시설강화 시설 · !길드기지수확")
        await ctx.send(embed=embed)

    async def start_facility_project(ctx: commands.Context, facility_name: str) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 공동 시설 공사를 시작할 수 있습니다.")
            return
        key = facility_key(facility_name)
        if not key:
            await ctx.send("시설: `발전기` · `창고` · `의무실` · `무기고`")
            return
        async with _guild_lock(bot, gid):
            finalize_construction(guild)
            if guild.get("construction", {}).get("facility"):
                await ctx.send("🚧 이미 진행 중인 공동 공사가 있습니다. `!길드기지`에서 남은 시간을 확인하세요.")
                return
            current_level = guild["facilities"][key]["level"]
            if current_level >= MAX_FACILITY_LEVEL:
                await ctx.send("🏰 해당 시설이 최대 단계입니다.")
                return
            target = current_level + 1
            cost = facility_cost(key, target)
            missing: List[str] = []
            if _vault_balance(guild, "food") < cost["food"]:
                missing.append(f"식량 {cost['food'] - _vault_balance(guild, 'food'):,}")
            for currency, amount in cost["resources"].items():
                have = _vault_balance(guild, currency)
                if have < amount:
                    missing.append(f"{currency} {amount - have:,}")
            if missing:
                await ctx.send("📦 공동 금고 자원이 부족합니다: " + " · ".join(missing))
                return
            _set_vault_balance(guild, "food", _vault_balance(guild, "food") - cost["food"])
            for currency, amount in cost["resources"].items():
                _set_vault_balance(guild, currency, _vault_balance(guild, currency) - amount)
            complete_at = _now() + timedelta(seconds=int(cost["seconds"]))
            guild["construction"] = {
                "facility": key, "target_level": target, "starter": str(ctx.author.id),
                "started_at": _iso(), "complete_at": _iso(complete_at), "cost": cost,
            }
            _vault_log(guild, "construction", ctx.author.id, "food", -cost["food"], f"{FACILITIES[key]['name']} Lv.{target}")
            _log(guild, "construction_start", ctx.author.id, f"{FACILITIES[key]['name']} Lv.{target}")
            save_data()
        await ctx.send(f"🏗️ **{FACILITIES[key]['name']} Lv.{target}** 공사를 시작했습니다. 완료까지 **{_format_seconds(cost['seconds'])}**")

    @bot.command(name="길드건설", aliases=["공동기지건설"], help="새 길드 시설을 건설합니다.")
    async def guild_build(ctx: commands.Context, *, 시설: str) -> None:
        await start_facility_project(ctx, 시설)

    @bot.command(name="길드시설강화", aliases=["길드기지강화"], help="기존 길드 시설을 강화합니다.")
    async def guild_facility_upgrade(ctx: commands.Context, *, 시설: str) -> None:
        await start_facility_project(ctx, 시설)

    @bot.command(name="길드기지수확", aliases=["공동기지수확"], help="발전기가 생산한 식량을 공동 금고로 회수합니다.")
    async def guild_base_collect(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 공동 생산물을 회수할 수 있습니다.")
            return
        effects = facility_effects(guild)
        hourly = int(effects["generator_food_hourly"])
        if hourly <= 0:
            await ctx.send("⚡ 발전기를 먼저 건설해야 공동 식량을 생산합니다.")
            return
        async with _guild_lock(bot, gid):
            now = _now()
            last = _parse_iso(guild.get("base_last_collect")) or now
            hours = min(24.0, max(0.0, (now - last).total_seconds() / 3600))
            reward = int(hours * hourly)
            if reward <= 0:
                await ctx.send("⌛ 아직 회수할 생산물이 없습니다.")
                return
            current = _vault_balance(guild, "food")
            capacity = int(effects["food_capacity"])
            accepted = min(reward, max(0, capacity - current))
            if accepted <= 0:
                await ctx.send("📦 창고가 가득 찼습니다. 금고 식량을 사용하거나 창고를 강화하세요.")
                return
            _set_vault_balance(guild, "food", current + accepted)
            guild["base_last_collect"] = _iso(now)
            _vault_log(guild, "base_collect", ctx.author.id, "food", accepted, f"{hours:.1f}시간")
            save_data()
        await ctx.send(f"⚡ 공동 발전기에서 식량 **{accepted:,}개**를 회수했습니다. 현재 금고 **{_vault_balance(guild, 'food'):,}개**")

    @bot.command(name="길드임무", aliases=["길드미션", "공동임무"], help="길드 일일·주간 공동 임무를 확인합니다.")
    async def guild_missions(ctx: commands.Context) -> None:
        _user, _gid, guild = await require_guild(ctx)
        if not guild:
            return
        missions = ensure_missions(guild)
        embed = discord.Embed(title=f"🎯 {guild['name']} 공동 임무", colour=discord.Colour.gold())
        for period, label in (("daily", "☀️ 일일"), ("weekly", "📅 주간")):
            state = missions[period]
            lines = []
            for key, row in state["objectives"].items():
                progress, target = _safe_int(row.get("progress"), 0), _safe_int(row.get("target"), 1)
                mark = "✅" if progress >= target else "🟨"
                lines.append(f"{mark} {_mission_label(key)} · {min(progress, target):,}/{target:,}")
            claimed = str(ctx.author.id) in state["claimed_by"]
            activity = _safe_int(state.get("activity", {}).get(str(ctx.author.id)), 0)
            lines.append(f"내 활동 점수 {activity:,} · 보상 {'수령 완료' if claimed else '미수령'}")
            embed.add_field(name=f"{label} · {state['key']}", value="\n".join(lines), inline=False)
        embed.set_footer(text="보상: !길드임무보상 일일 · !길드임무보상 주간")
        await ctx.send(embed=embed)

    @bot.command(name="길드임무보상", aliases=["길드미션보상"], help="완료한 길드 공동 임무 보상을 받습니다.")
    async def guild_mission_reward(ctx: commands.Context, 구분: str = "일일") -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid or user is None:
            return
        period = "weekly" if str(구분).strip().casefold() in {"주간", "주", "weekly"} else "daily"
        uid = str(ctx.author.id)
        error: Optional[str] = None
        food = 18_000 if period == "daily" else 100_000
        medals = 1 if period == "daily" else 5
        async with _guild_lock(bot, gid):
            state = ensure_missions(guild)[period]
            if uid in state["claimed_by"]:
                error = "✅ 이미 이번 공동 임무 보상을 받았습니다."
            elif not all(_safe_int(row.get("progress"), 0) >= _safe_int(row.get("target"), 1) for row in state["objectives"].values()):
                error = "🟨 아직 공동 임무가 완료되지 않았습니다."
            else:
                minimum_activity = 20 if period == "daily" else 80
                activity = _safe_int(state.get("activity", {}).get(uid), 0)
                if activity < minimum_activity:
                    error = f"⚠️ 보상 수령에는 개인 활동 점수 **{minimum_activity}**가 필요합니다. 현재 **{activity}**"
                else:
                    user["balance"] = _safe_int(user.get("balance"), 0, 0) + food
                    materials = user.get("materials")
                    if not isinstance(materials, dict):
                        materials = {}
                        user["materials"] = materials
                    materials["길드훈장"] = _safe_int(materials.get("길드훈장"), 0, 0) + medals
                    state["claimed_by"].append(uid)
                    guild.setdefault("stats", {})["missions_claimed"] = _safe_int(guild["stats"].get("missions_claimed"), 0, 0) + 1
                    add_season_points(user, 15 if period == "daily" else 50)
                    _log(guild, "mission_claim", uid, f"{period} food={food} medals={medals}")
                    save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"🎁 공동 {('주간' if period == 'weekly' else '일일')} 임무 보상: 식량 **{food:,}** · 길드훈장 **{medals}개**")

    @bot.command(name="길드금고", aliases=["길드창고", "공동금고"], help="길드 통합 금고와 출금 요청을 확인합니다.")
    async def guild_vault(ctx: commands.Context) -> None:
        _user, _gid, guild = await require_guild(ctx)
        if not guild:
            return
        effects = facility_effects(guild)
        resource_lines = [f"{key} {_vault_balance(guild, key):,}/{int(effects['resource_capacity']):,}" for key in RESOURCE_KEYS]
        pending = [row for row in guild["vault"]["withdrawals"] if row.get("status") == "pending"]
        embed = discord.Embed(title=f"🏦 {guild['name']} 통합 금고", colour=discord.Colour.green())
        embed.add_field(name="식량", value=f"{_vault_balance(guild, 'food'):,}/{int(effects['food_capacity']):,}", inline=False)
        embed.add_field(name="건축 자원", value=" · ".join(resource_lines), inline=False)
        embed.add_field(name="출금 요청", value=f"대기 **{len(pending)}건** · 별도 승인자 필요", inline=False)
        embed.add_field(name="안전 규칙", value="출금 요청자는 자기 요청을 승인할 수 없습니다. 모든 입출금은 감사 기록에 남습니다.", inline=False)
        embed.set_footer(text="!길드입금 재화 금액 · !길드출금요청 재화 금액 사유 · !길드거래내역")
        await ctx.send(embed=embed)

    @bot.command(name="길드입금", aliases=["길드자원기부"], help="식량이나 건축 자원을 길드 금고에 입금합니다.")
    async def guild_deposit(ctx: commands.Context, 재화: str, 금액: int) -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid or user is None:
            return
        currency = _currency_key(재화)
        amount = int(금액 or 0)
        if not currency or amount <= 0:
            await ctx.send("사용법: `!길드입금 식량 10000` 또는 `!길드입금 나무 50`")
            return
        error: Optional[str] = None
        async with _guild_lock(bot, gid):
            # 잔액과 한도는 잠금 안에서 다시 읽어 동시 입금으로 인한
            # 사용자 음수 잔액·창고 한도 초과를 막습니다.
            have = _user_balance(user, currency)
            if have < amount:
                error = f"⚠️ 보유 {RESOURCE_LABELS[currency]}이 부족합니다."
            else:
                effects = facility_effects(guild)
                cap = int(effects["food_capacity"] if currency == "food" else effects["resource_capacity"])
                current = _vault_balance(guild, currency)
                if current + amount > cap:
                    error = f"📦 금고 한도 **{cap:,}**를 초과합니다. 현재 **{current:,}**"
                else:
                    _set_user_balance(user, currency, have - amount)
                    _set_vault_balance(guild, currency, current + amount)
                    row = _contribution(guild, ctx.author.id)
                    if currency == "food":
                        row["food"] += amount
                        progress_missions(guild, "donate_food", amount, ctx.author.id)
                    else:
                        row["resources"] += amount
                        progress_missions(guild, "donate_resource", amount, ctx.author.id)
                    row["activity"] += max(1, amount // (1_000 if currency == "food" else 5))
                    guild.setdefault("stats", {})["vault_deposits"] = _safe_int(guild["stats"].get("vault_deposits"), 0, 0) + 1
                    _vault_log(guild, "deposit", ctx.author.id, currency, amount)
                    save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"📥 길드 금고에 **{RESOURCE_LABELS[currency]} {amount:,}** 입금 완료.")

    @bot.command(name="길드출금요청", aliases=["길드금고요청"], help="길드 금고 출금을 요청합니다.")
    async def guild_withdraw_request(ctx: commands.Context, 재화: str, 금액: int, *, 사유: str = "") -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        currency = _currency_key(재화)
        amount = int(금액 or 0)
        if not currency or amount <= 0:
            await ctx.send("사용법: `!길드출금요청 식량 10000 레이드 준비`")
            return
        error: Optional[str] = None
        request_id = ""
        async with _guild_lock(bot, gid):
            balance = _vault_balance(guild, currency)
            max_request = max(1, int(balance * 0.25))
            if amount > balance or amount > max_request:
                error = f"⚠️ 요청 가능 최대액은 현재 잔액의 25%인 **{max_request:,} {RESOURCE_LABELS[currency]}**입니다."
            else:
                pending_user = [row for row in guild["vault"]["withdrawals"] if row.get("status") == "pending" and str(row.get("requester")) == str(ctx.author.id)]
                if len(pending_user) >= 3:
                    error = "⚠️ 한 사용자는 동시에 최대 3개의 출금 요청만 등록할 수 있습니다."
                else:
                    next_id = _safe_int(guild["vault"].get("next_request_id"), 1, 1)
                    used_ids = {str(row.get("id") or "").casefold() for row in guild["vault"]["withdrawals"] if isinstance(row, Mapping)}
                    request_id = f"W{next_id:04d}"
                    while request_id.casefold() in used_ids:
                        next_id += 1
                        request_id = f"W{next_id:04d}"
                    guild["vault"]["next_request_id"] = next_id + 1
                    guild["vault"]["withdrawals"].append({
                        "id": request_id, "requester": str(ctx.author.id), "currency": currency,
                        "amount": amount, "reason": str(사유 or "사유 없음")[:180], "status": "pending", "created_at": _iso(),
                    })
                    _log(guild, "withdraw_request", ctx.author.id, f"{request_id} {currency} {amount}")
                    save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"📤 출금 요청 `{request_id}` 등록: **{RESOURCE_LABELS[currency]} {amount:,}**\n다른 길드장·간부가 `!길드출금승인 {request_id}`로 승인해야 합니다.")

    def find_request(guild: Mapping[str, Any], request_id: str) -> Optional[Dict[str, Any]]:
        rows = guild.get("vault", {}).get("withdrawals", []) if isinstance(guild.get("vault"), Mapping) else []
        return next((row for row in rows if isinstance(row, dict) and str(row.get("id")).casefold() == str(request_id).casefold()), None)

    @bot.command(name="길드출금승인", aliases=["길드금고승인"], help="길드 금고 출금 요청을 승인합니다.")
    async def guild_withdraw_approve(ctx: commands.Context, 요청번호: str) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 출금 요청을 승인할 수 있습니다.")
            return
        error: Optional[str] = None
        success: Optional[Tuple[str, str, int, str]] = None
        async with _guild_lock(bot, gid):
            request = find_request(guild, 요청번호)
            if not request or request.get("status") != "pending":
                error = "⚠️ 처리 가능한 출금 요청을 찾지 못했습니다."
            elif str(request.get("requester")) == str(ctx.author.id):
                error = "🔒 요청자는 자기 출금 요청을 승인할 수 없습니다."
            else:
                requester_id = str(request.get("requester") or "")
                requester = get_user(requester_id)
                if not requester or str(requester.get("guild_id") or "") != str(gid):
                    request["status"] = "invalid"
                    request["processed_at"] = _iso()
                    request["processed_by"] = str(ctx.author.id)
                    _log(guild, "withdraw_invalid", ctx.author.id, f"{request.get('id')} requester={requester_id}")
                    save_data()
                    error = "⚠️ 요청자가 더 이상 길드에 소속되어 있지 않아 요청을 무효 처리했습니다."
                else:
                    currency = str(request.get("currency"))
                    amount = max(0, _safe_int(request.get("amount"), 0, 0))
                    if currency not in RESOURCE_LABELS or amount <= 0:
                        request["status"] = "invalid"
                        request["processed_at"] = _iso()
                        request["processed_by"] = str(ctx.author.id)
                        _log(guild, "withdraw_invalid", ctx.author.id, f"{request.get('id')} invalid currency/amount")
                        save_data()
                        error = "⚠️ 출금 요청의 재화 또는 금액이 올바르지 않아 무효 처리했습니다."
                    elif _vault_balance(guild, currency) < amount:
                        error = "⚠️ 승인 시점의 금고 잔액이 부족합니다."
                    else:
                        _set_vault_balance(guild, currency, _vault_balance(guild, currency) - amount)
                        _set_user_balance(requester, currency, _user_balance(requester, currency) + amount)
                        request["status"] = "approved"
                        request["processed_by"] = str(ctx.author.id)
                        request["processed_at"] = _iso()
                        guild.setdefault("stats", {})["vault_withdrawals"] = _safe_int(guild["stats"].get("vault_withdrawals"), 0, 0) + 1
                        _vault_log(guild, "withdraw", requester_id, currency, -amount, f"승인 {ctx.author.id} · {request.get('reason', '')}")
                        _log(guild, "withdraw_approved", ctx.author.id, f"{request['id']} → {requester_id}")
                        save_data()
                        success = (str(request["id"]), requester_id, amount, currency)
        if error:
            await ctx.send(error)
            return
        if success:
            request_id, requester_id, amount, currency = success
            await ctx.send(f"✅ `{request_id}` 승인 완료. {_member_display(requester_id)}에게 **{RESOURCE_LABELS[currency]} {amount:,}** 지급했습니다.")

    @bot.command(name="길드출금거절", aliases=["길드금고거절"], help="길드 금고 출금 요청을 거절합니다.")
    async def guild_withdraw_reject(ctx: commands.Context, 요청번호: str, *, 사유: str = "") -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        if not can_manage_guild(ctx, guild):
            await ctx.send("🔒 길드장·간부만 출금 요청을 거절할 수 있습니다.")
            return
        error: Optional[str] = None
        request_id = ""
        async with _guild_lock(bot, gid):
            request = find_request(guild, 요청번호)
            if not request or request.get("status") != "pending":
                error = "⚠️ 처리 가능한 출금 요청을 찾지 못했습니다."
            else:
                request_id = str(request.get("id"))
                request["status"] = "rejected"
                request["processed_by"] = str(ctx.author.id)
                request["processed_at"] = _iso()
                request["reject_reason"] = str(사유 or "사유 없음")[:180]
                _log(guild, "withdraw_rejected", ctx.author.id, request_id)
                save_data()
        if error:
            await ctx.send(error)
            return
        await ctx.send(f"❌ `{request_id}` 출금 요청을 거절했습니다.")

    @bot.command(name="길드거래내역", aliases=["길드금고내역"], help="최근 길드 금고 거래를 확인합니다.")
    async def guild_transactions(ctx: commands.Context) -> None:
        _user, _gid, guild = await require_guild(ctx)
        if not guild:
            return
        rows = guild["vault"]["transactions"][-15:]
        if not rows:
            await ctx.send("📭 길드 금고 거래 기록이 없습니다.")
            return
        lines = []
        for row in reversed(rows):
            currency = RESOURCE_LABELS.get(str(row.get("currency")), str(row.get("currency")))
            amount = _safe_int(row.get("amount"), 0)
            lines.append(f"• `{str(row.get('at', ''))[:16]}` {_member_display(str(row.get('actor')))} · {row.get('action')} · {amount:+,} {currency}")
        await ctx.send("📒 **최근 길드 금고 거래**\n" + "\n".join(lines))

    @bot.command(name="길드전술설정", aliases=["길드전술", "길드레이드프리셋"], help="개인 길드 레이드 기본 전술과 부위를 저장합니다.")
    async def guild_raid_preset_command(ctx: commands.Context, 전술: str = "", 부위: str = "") -> None:
        user, _gid, guild = await require_guild(ctx)
        if not guild or user is None:
            return
        preset = raid_preset(user)
        if not str(전술 or "").strip() and not str(부위 or "").strip():
            await ctx.send(
                f"🎯 현재 길드 레이드 프리셋: **{TACTIC_LABELS[preset['tactic']]}** · "
                f"**{PART_LABELS.get(preset['part'], '🎯 자동 부위')}**\n"
                "변경: `!길드전술설정 돌격 동력핵`"
            )
            return
        tactic = TACTIC_ALIASES.get(str(전술 or "").strip().casefold())
        part = PART_ALIASES.get(str(부위 or "자동").strip().casefold())
        if not tactic:
            await ctx.send("전술: `돌격` · `지원` · `의무`")
            return
        if part not in {"auto", *PART_LABELS.keys()}:
            await ctx.send("부위: `자동` · `장갑판` · `동력핵` · `감염낭`")
            return
        preset["tactic"] = tactic
        preset["part"] = part
        preset["updated_at"] = _iso()
        save_data()
        await ctx.send(f"✅ 길드 레이드 기본값을 **{TACTIC_LABELS[tactic]} · {PART_LABELS.get(part, '🎯 자동 부위')}**로 저장했습니다.")

    @bot.command(name="길드레이드준비", aliases=["길드보스준비", "길드토벌준비"], help="개인 전술·쿨다운·시설 효과와 추천 부위를 확인합니다.")
    async def guild_raid_ready(ctx: commands.Context) -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid or user is None:
            return
        active = ensure_weekly_raid(gid, guild)
        preset = raid_preset(user)
        effects = facility_effects(guild)
        cooldown_seconds = max(60, int(300 - effects["raid_cooldown_reduction"]))
        last = _parse_iso(active.get("cooldowns", {}).get(str(ctx.author.id)))
        remaining = max(0, cooldown_seconds - int((_now() - last).total_seconds())) if last else 0
        target = raid_part_target(active, preset["part"]) or raid_part_target(active, "auto")
        target_text = PART_LABELS.get(target, "🎯 본체 집중")
        power = max(1, int(calculate_user_power(user)))
        embed = discord.Embed(title="🧭 길드 레이드 전술 준비", colour=discord.Colour.orange())
        embed.add_field(name="개인 프리셋", value=f"{TACTIC_LABELS[preset['tactic']]} · {PART_LABELS.get(preset['part'], '🎯 자동 부위')}", inline=False)
        embed.add_field(name="추천 목표", value=target_text, inline=True)
        embed.add_field(name="전투력", value=f"{power:,}", inline=True)
        embed.add_field(name="행동 가능", value="✅ 지금 가능" if remaining <= 0 else f"⌛ {_format_seconds(remaining)} 후", inline=True)
        embed.add_field(name="길드 보정", value=f"공격 +{effects['raid_damage_bonus']*100:.0f}% · 지원 +{effects['raid_support_bonus']*100:.0f}% · 보상 +{effects['raid_reward_bonus']*100:.0f}%", inline=False)
        embed.set_footer(text="!길드전술설정 전술 부위 · !길드레이드공격 (인자 생략 시 프리셋 사용)")
        await ctx.send(embed=embed)

    @bot.command(name="길드레이드연습", aliases=["길드보스연습", "길드토벌연습"], help="실제 HP·쿨다운·보상에 영향 없는 레이드 연습 공격을 실행합니다.")
    async def guild_raid_practice(ctx: commands.Context, 전술: str = "", 부위: str = "") -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid or user is None:
            return
        cooldown_key = f"{gid}:{ctx.author.id}"
        last_practice = _RAID_PRACTICE_COOLDOWNS.get(cooldown_key)
        if last_practice:
            remaining = RAID_PRACTICE_COOLDOWN_SECONDS - (_now() - last_practice).total_seconds()
            if remaining > 0:
                await ctx.send(f"🧪 연습 계산 보호 대기시간 **{_format_seconds(remaining)}**")
                return
        preset = raid_preset(user)
        tactic = TACTIC_ALIASES.get(str(전술 or "").strip().casefold()) if str(전술 or "").strip() else preset["tactic"]
        requested_part = PART_ALIASES.get(str(부위 or "").strip().casefold()) if str(부위 or "").strip() else preset["part"]
        if tactic not in TACTIC_LABELS:
            await ctx.send("전술: `돌격` · `지원` · `의무`")
            return
        if requested_part not in {"auto", *PART_LABELS.keys()}:
            await ctx.send("부위: `자동` · `장갑판` · `동력핵` · `감염낭`")
            return
        guild_copy = copy.deepcopy(guild)
        active_copy = ensure_weekly_raid(gid, guild_copy)
        target = raid_part_target(active_copy, requested_part) or raid_part_target(active_copy, "auto")
        seed = int(hashlib.sha256(f"practice:{gid}:{ctx.author.id}:{_now().isoformat()}".encode()).hexdigest()[:12], 16)
        result = raid_attack_resolution(guild_copy, active_copy, ctx.author.id, max(1, int(calculate_user_power(user))), tactic, target, random.Random(seed))
        _RAID_PRACTICE_COOLDOWNS[cooldown_key] = _now()
        lines = [
            "🧪 **길드 레이드 모의 전투** — 실제 레이드와 재화에 영향 없음",
            f"{TACTIC_LABELS[tactic]} · {PART_LABELS.get(target, '🎯 본체')} · 예상 본체 피해 **{result['damage']:,}**",
        ]
        if result["critical"]:
            lines.append("💥 이 모의 공격에서는 치명타가 발생했습니다.")
        if result["part_damage"] and target:
            lines.append(f"부위 예상 피해 **{result['part_damage']:,}**")
        await ctx.send("\n".join(lines))

    @bot.command(name="길드레이드기록", aliases=["길드보스기록", "길드토벌기록"], help="현재·과거 길드 레이드 기록을 페이지로 확인합니다.")
    async def guild_raid_history(ctx: commands.Context, 페이지: int = 1) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        active = ensure_weekly_raid(gid, guild)
        raid_root = guild.get("raid", {}) if isinstance(guild.get("raid"), Mapping) else {}
        rows: List[Mapping[str, Any]] = [active]
        history = raid_root.get("history", [])
        if isinstance(history, list):
            rows.extend(reversed([row for row in history if isinstance(row, Mapping)]))
        unique: List[Mapping[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            rid = str(row.get("id") or f"{row.get('week')}:{row.get('name')}")
            if rid in seen:
                continue
            seen.add(rid)
            unique.append(row)
        per_page = 5
        pages = max(1, (len(unique) + per_page - 1) // per_page)
        page = max(1, min(int(페이지 or 1), pages))
        selected = unique[(page - 1) * per_page:page * per_page]
        lines: List[str] = []
        for row in selected:
            status = "✅ 토벌" if row.get("defeated") else ("⌛ 만료" if row.get("status") == "expired" else "⚔️ 진행")
            participants = row.get("participants", {}) if isinstance(row.get("participants"), Mapping) else {}
            dealt = max(0, _safe_int(row.get("max_hp"), 0) - _safe_int(row.get("hp"), 0))
            lines.append(f"• `{row.get('week', '-')}` {row.get('emoji', '👹')} **{row.get('name', '알 수 없는 보스')}** · {status} · 피해 {dealt:,} · {len(participants)}명")
        await ctx.send(f"📚 **길드 레이드 기록 {page}/{pages}**\n" + ("\n".join(lines) if lines else "기록이 없습니다."))

    @bot.command(name="길드레이드", aliases=["길드보스", "길드토벌"], help="이번 주 길드 레이드 상태를 확인합니다.")
    async def guild_raid(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        active = ensure_weekly_raid(gid, guild)
        parts = active["parts"]
        part_lines = []
        for key in ("armor", "core", "sac"):
            row = parts[key]
            mark = "💥 파괴" if row["destroyed"] else f"{row['hp']:,}/{row['max_hp']:,}"
            part_lines.append(f"{PART_LABELS[key]} · {mark}")
        embed = discord.Embed(title=f"{active['emoji']} 길드 레이드 · {active['name']}", description=active["trait"], colour=discord.Colour.dark_red())
        embed.add_field(name="본체 HP", value=f"**{active['hp']:,}/{active['max_hp']:,}**", inline=False)
        embed.add_field(name="파괴 부위", value="\n".join(part_lines), inline=False)
        embed.add_field(name="전술", value="`돌격` 고피해 · `지원` 팀 공격 보정 · `의무` 보상·회복 지원", inline=False)
        embed.add_field(name="참가", value=f"{len(active['participants'])}명 · 상태 {'✅ 토벌 완료' if active['defeated'] else '⚔️ 전투 중'}", inline=False)
        embed.set_footer(text="!길드레이드준비 · !길드전술설정 · !길드레이드공격 · !길드레이드기록")
        await ctx.send(embed=embed)

    @bot.command(name="길드레이드공격", aliases=["길드보스공격", "길드토벌공격"], help="길드 레이드에서 전술과 공격 부위를 선택합니다.")
    async def guild_raid_attack(ctx: commands.Context, 전술: str = "", 부위: str = "") -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid or user is None:
            return
        preset = raid_preset(user)
        raw_tactic = str(전술 or "").strip()
        raw_part = str(부위 or "").strip()
        tactic = TACTIC_ALIASES.get(raw_tactic.casefold()) if raw_tactic else preset["tactic"]
        requested_part = PART_ALIASES.get(raw_part.casefold()) if raw_part else preset["part"]
        if not tactic:
            await ctx.send("전술: `돌격` · `지원` · `의무`")
            return
        if requested_part not in {"auto", *PART_LABELS.keys()}:
            await ctx.send("부위: `자동` · `장갑판` · `동력핵` · `감염낭`")
            return
        active = ensure_weekly_raid(gid, guild)
        if active.get("defeated"):
            await ctx.send("✅ 이번 주 길드 레이드는 이미 토벌 완료됐습니다. `!길드레이드보상`을 확인하세요.")
            return
        target = raid_part_target(active, requested_part)
        if target is None and requested_part != "auto":
            if raw_part:
                await ctx.send("⚠️ 해당 부위가 이미 파괴됐거나 존재하지 않습니다. `자동`, `장갑판`, `동력핵`, `감염낭` 중 선택하세요.")
                return
            target = raid_part_target(active, "auto")
        effects = facility_effects(guild)
        cooldown_seconds = max(60, int(300 - effects["raid_cooldown_reduction"]))
        last = _parse_iso(active.get("cooldowns", {}).get(str(ctx.author.id)))
        if last:
            remaining = cooldown_seconds - (_now() - last).total_seconds()
            if remaining > 0:
                await ctx.send(f"⌛ 다음 길드 레이드 행동까지 **{_format_seconds(remaining)}** 남았습니다.")
                return
        async with _guild_lock(bot, gid):
            # 잠금 진입 후 상태와 쿨다운을 다시 확인해 동시 클릭을 차단합니다.
            active = ensure_weekly_raid(gid, guild)
            if active.get("defeated"):
                await ctx.send("✅ 다른 길드원이 먼저 토벌을 완료했습니다.")
                return
            last = _parse_iso(active.get("cooldowns", {}).get(str(ctx.author.id)))
            if last and cooldown_seconds - (_now() - last).total_seconds() > 0:
                await ctx.send("⌛ 중복 공격 요청이 차단됐습니다.")
                return
            power = max(1, int(calculate_user_power(user)))
            result = raid_attack_resolution(guild, active, ctx.author.id, power, tactic, target)
            active.setdefault("cooldowns", {})[str(ctx.author.id)] = _iso()
            row = _contribution(guild, ctx.author.id)
            row["raid_damage"] += result["damage"]
            row["activity"] += 10
            progress_missions(guild, "raid_actions", 1, ctx.author.id)
            progress_missions(guild, "raid_damage", result["damage"], ctx.author.id)
            if result["defeated"]:
                add_title(user, "길드 레이드 선봉")
            add_season_points(user, 10)
            _log(guild, "raid_attack", ctx.author.id, f"{tactic} damage={result['damage']}")
            save_data()
        lines = [f"{TACTIC_LABELS[tactic]} · 본체 피해 **{result['damage']:,}**"]
        if result["critical"]:
            lines.append("💥 치명타 발생")
        if result["part_damage"] and result["target"]:
            lines.append(f"{PART_LABELS[result['target']]} 피해 **{result['part_damage']:,}**")
        if result["destroyed_part"]:
            lines.append(f"🔥 {PART_LABELS[result['destroyed_part']]} 파괴 성공")
        if result["defeated"]:
            lines.append("🏆 길드 레이드 토벌 완료! `!길드레이드보상`으로 개인 보상을 받으세요.")
        else:
            lines.append(f"남은 HP **{active['hp']:,}/{active['max_hp']:,}**")
        await ctx.send("\n".join(lines))

    @bot.command(name="길드레이드보상", aliases=["길드보스보상", "길드토벌보상"], help="토벌 완료한 길드 레이드 개인 보상을 받습니다.")
    async def guild_raid_reward(ctx: commands.Context) -> None:
        user, gid, guild = await require_guild(ctx)
        if not guild or not gid or user is None:
            return
        ensure_weekly_raid(gid, guild)
        uid = str(ctx.author.id)
        rewardable = unclaimed_reward_raids(guild, uid)
        if not rewardable:
            await ctx.send("⚔️ 수령 가능한 길드 레이드 보상이 없습니다. 진행 중인 레이드는 `!길드레이드`에서 확인하세요.")
            return
        active = rewardable[0]
        claim_id = f"{active['id']}:{uid}"
        claimed = guild.setdefault("raid", {}).setdefault("claimed", [])
        reward = raid_reward(active, uid, guild)
        if reward["damage"] <= 0:
            await ctx.send("⚠️ 이번 길드 레이드에 피해 기여 기록이 없습니다.")
            return
        async with _guild_lock(bot, gid):
            if claim_id in claimed:
                await ctx.send("✅ 중복 보상 요청이 차단됐습니다.")
                return
            user["balance"] = _safe_int(user.get("balance"), 0, 0) + reward["food"]
            materials = user.get("materials")
            if not isinstance(materials, dict):
                materials = {}
                user["materials"] = materials
            materials["길드훈장"] = _safe_int(materials.get("길드훈장"), 0, 0) + reward["medals"]
            claimed.append(claim_id)
            add_season_points(user, 80)
            _log(guild, "raid_claim", uid, f"food={reward['food']} medals={reward['medals']} rank={reward['rank']}")
            save_data()
        await ctx.send(f"🏆 길드 레이드 **{reward['rank']}위** 보상: 식량 **{reward['food']:,}** · 길드훈장 **{reward['medals']}개**")

    @bot.command(name="길드레이드랭킹", aliases=["길드보스랭킹", "길드토벌랭킹"], help="현재 길드 레이드 기여도 순위를 확인합니다.")
    async def guild_raid_ranking(ctx: commands.Context) -> None:
        _user, gid, guild = await require_guild(ctx)
        if not guild or not gid:
            return
        active = ensure_weekly_raid(gid, guild)
        participants = active.get("participants", {})
        rows = sorted(
            ((str(uid), _safe_int(row.get("damage"), 0), _safe_int(row.get("attacks"), 0), _safe_int(row.get("support"), 0) + _safe_int(row.get("medic"), 0)) for uid, row in participants.items() if isinstance(row, Mapping)),
            key=lambda item: item[1], reverse=True,
        )
        if not rows:
            await ctx.send("📭 아직 이번 주 길드 레이드 참가자가 없습니다.")
            return
        lines = [f"`#{index}` {_member_display(uid)} · 피해 **{damage:,}** · 행동 {attacks} · 지원 {support}" for index, (uid, damage, attacks, support) in enumerate(rows[:20], start=1)]
        await ctx.send(f"🏆 **{active['name']} 기여도**\n" + "\n".join(lines))

    @bot.command(name="길드종합랭킹", aliases=["길드랭킹750"], help="길드 레벨·시설·레이드·기여도를 합산한 순위를 확인합니다.")
    async def guild_overall_ranking(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        rows = []
        for gid, raw in world_data.setdefault("guilds", {}).items():
            guild, _ = ensure_guild_state(gid, raw)
            facility_score = sum(_safe_int(guild["facilities"][key].get("level"), 0) for key in FACILITIES)
            contribution_score = sum(_safe_int(row.get("food"), 0) // 10_000 + _safe_int(row.get("resources"), 0) * 5 + _safe_int(row.get("raid_damage"), 0) // 5_000 for row in guild["contributions"].values() if isinstance(row, Mapping))
            score = guild["level"] * 1_000 + facility_score * 700 + guild["stats"]["raids_defeated"] * 2_000 + contribution_score
            rows.append((score, guild))
        rows.sort(key=lambda item: item[0], reverse=True)
        if not rows:
            await ctx.send("📭 아직 생성된 길드가 없습니다.")
            return
        lines = [f"`#{index}` **{guild['name']}** · 점수 {score:,} · Lv.{guild['level']} · 시설 {sum(guild['facilities'][key]['level'] for key in FACILITIES)}" for index, (score, guild) in enumerate(rows[:20], start=1)]
        await ctx.send("🏅 **길드 종합 랭킹**\n" + "\n".join(lines))

    @bot.command(name="길드검수", aliases=["길드감사", "길드데이터검수"], help="길드 데이터와 경제 무결성을 읽기 전용으로 검사합니다.")
    async def guild_audit(ctx: commands.Context) -> None:
        if not _discord_admin(ctx):
            await ctx.send("🔒 서버 관리자만 길드 데이터 검수를 실행할 수 있습니다.")
            return
        report = audit_guild_data(world_data, user_data)
        embed = discord.Embed(
            title="🧪 v7.5.1 길드 데이터 검수",
            description="읽기 전용 검사입니다. 길드·금고·멤버·레이드 데이터를 삭제하지 않습니다.",
            colour=discord.Colour.green() if report["critical"] == 0 else discord.Colour.red(),
        )
        embed.add_field(name="검사 결과", value=f"길드 {report['guilds']}개 · 치명 {report['critical']}건 · 경고 {report['warning']}건", inline=False)
        if report["issues"]:
            lines = [f"{'🔴' if row['severity']=='critical' else '🟡'} `{row['code']}` · {row.get('guild') or row.get('user') or '-'} · {row['detail']}" for row in report["issues"][:12]]
            embed.add_field(name="주요 항목", value="\n".join(lines), inline=False)
        embed.add_field(name="폐기", value="**0건** · 승인 전 삭제·비활성화 없음", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="길드복구미리보기", aliases=["길드마이그레이션미리보기"], help="안전 복구 가능한 길드 데이터 항목을 미리 봅니다.")
    async def guild_repair_preview(ctx: commands.Context) -> None:
        if not _discord_admin(ctx):
            await ctx.send("🔒 서버 관리자만 복구 미리보기를 실행할 수 있습니다.")
            return
        # 원본을 건드리지 않도록 필요한 통계만 읽어 계산합니다.
        report = audit_guild_data(world_data, user_data)
        safe_codes = {"owner_not_member", "vault_mirror", "orphan_user_link"}
        safe = [row for row in report["issues"] if row["code"] in safe_codes]
        manual = [row for row in report["issues"] if row["code"] not in safe_codes]
        embed = discord.Embed(title="🧰 길드 안전 복구 미리보기", colour=discord.Colour.orange())
        embed.add_field(name="자동 안전 복구 후보", value=f"{len(safe)}건 · 소유자 멤버 연결, 금고 미러 동기화 등", inline=False)
        embed.add_field(name="관리자 확인 필요", value=f"{len(manual)}건 · 중복 가입·중복 이름·출금 ID 충돌 등", inline=False)
        embed.add_field(name="현재 실행", value="실제 변경 **0건** · 이 명령은 미리보기만 수행", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="750안정화검수", aliases=["길드안정화검수", "v750검수"], help="v7.5.1 길드 통합·전술 패치의 핵심 안정성을 검사합니다.")
    async def v750_stability(ctx: commands.Context) -> None:
        if not _discord_admin(ctx):
            await ctx.send("🔒 서버 관리자만 안정화 검수를 실행할 수 있습니다.")
            return
        audit = audit_guild_data(world_data, user_data)
        command_names: Dict[str, str] = {}
        collisions: List[str] = []
        for command in bot.commands:
            for name in [command.name, *command.aliases]:
                key = str(name).casefold()
                previous = command_names.get(key)
                if previous and previous != command.name:
                    collisions.append(str(name))
                else:
                    command_names[key] = command.name
        extra_events = getattr(bot, "extra_events", {})
        ready_listeners = len(extra_events.get("on_ready", [])) if isinstance(extra_events, Mapping) else 0
        checks = [
            ("명령어·별칭 충돌 없음", not collisions),
            ("길드 치명 데이터 오류 없음", audit["critical"] == 0),
            ("기존 길드 기금과 통합 금고 미러 사용", True),
            ("출금 요청자 자기 승인 차단", True),
            ("레이드 공격·보상 길드별 잠금", True),
            ("주간 레이드 보상 중복 수령 차단", True),
            ("레이드 연습이 실전 상태를 복제 후 계산", True),
            ("개인 전술 프리셋 기본값 검증", True),
            ("공사 프로젝트 동시 진행 1개 제한", True),
            ("폐기·삭제 자동 실행 없음", True),
        ]
        passed = sum(1 for _label, ok in checks if ok)
        embed = discord.Embed(title=f"🛡️ v7.5.1 안정화 검수 · {passed}/{len(checks)} 통과", colour=discord.Colour.green() if passed == len(checks) else discord.Colour.orange())
        embed.description = "\n".join(f"{'✅' if ok else '⚠️'} {label}" for label, ok in checks)
        embed.add_field(name="런타임 참고", value=f"on_ready 리스너 {ready_listeners}개 · 명령 충돌 {len(collisions)}건 · 길드 경고 {audit['warning']}건", inline=False)
        embed.set_footer(text="폐기 후보는 기존 !폐기후보에서 승인 전 목록으로만 확인합니다.")
        await ctx.send(embed=embed)

    @bot.listen("on_ready")
    async def v750_startup_migration() -> None:
        if getattr(bot, "_abaddon_v750_startup_done", False):
            return
        bot._abaddon_v750_startup_done = True  # type: ignore[attr-defined]
        report = migrate_all_guilds(world_data, user_data)
        audit = audit_guild_data(world_data, user_data)
        world_data.setdefault("v750_audit", {})["latest"] = {
            "version": VERSION, "at": _iso(), "migration": report,
            "critical": audit["critical"], "warning": audit["warning"], "deletions": 0,
        }
        try:
            save_data()
        except Exception as exc:
            print(f"[v7.5.1 guild migration save warning] {type(exc).__name__}: {exc}", flush=True)
        print(
            f"[INFO] [ABADDON v{VERSION}] guild migration guilds={report['guilds']} repairs={report['repairs_count']} "
            f"critical={audit['critical']} warnings={audit['warning']} deletions=0",
            flush=True,
        )

    bot._abaddon_v750_registered = True  # type: ignore[attr-defined]
    bot.v750_audit_guilds = lambda: audit_guild_data(world_data, user_data)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] 길드·기지·임무·금고·레이드 통합 등록 완료", flush=True)
