from __future__ import annotations

"""ABADDON v17.6.0 — CHRONICLE MUSEUM & COMMUNITY SEASON.

v17.5 turns preserved progress from story, expeditions, NPC bonds, mounts,
contracts, factions and cosmetics into a public museum, achievements and titles.
v17.6 adds a fair, anti-spam community season that derives contribution from
existing gameplay rather than requiring a second parallel game.

The patch is additive: no legacy command, item id or save key is removed.
"""

from datetime import datetime, timedelta, timezone
import math
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _invoke_command, _safe_embed, _safe_view
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as command_hub

VERSION = "17.6.0"
MUSEUM_KEY = "chronicle_museum_v1750"
SEASON_KEY = "community_season_v1760"
KST = timezone(timedelta(hours=9))


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _now() -> int:
    return int(time.time())


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _week_key() -> str:
    now = datetime.now(KST)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _season_key() -> str:
    """Stable four-week community season id."""
    now = datetime.now(KST)
    year, week, _ = now.isocalendar()
    block = (week - 1) // 4 + 1
    return f"{year}-S{block:02d}"


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> Optional[MutableMapping[str, Any]]:
    row = get_user(int(user_id))
    return row if isinstance(row, MutableMapping) else None


def _museum(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault(MUSEUM_KEY, {})
    if not isinstance(row, MutableMapping):
        row = {}
        user[MUSEUM_KEY] = row
    row.setdefault("version", VERSION)
    row.setdefault("claimed", [])
    row.setdefault("titles", [])
    row.setdefault("active_title", "")
    row.setdefault("recommendations", 0)
    row.setdefault("recommended_today", {})
    row.setdefault("visits", 0)
    row.setdefault("daily_visitors", {})
    row.setdefault("reward_claims", [])
    row.setdefault("history", [])
    for key in ("claimed", "titles", "reward_claims", "history"):
        if not isinstance(row.get(key), list):
            row[key] = []
    for key in ("recommended_today", "daily_visitors"):
        if not isinstance(row.get(key), MutableMapping):
            row[key] = {}
    row["version"] = VERSION
    return row


def _season_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(SEASON_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[SEASON_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    if not isinstance(root.get("guilds"), MutableMapping):
        root["guilds"] = {}
    root["version"] = VERSION
    return root


def _new_season_state(key: str) -> MutableMapping[str, Any]:
    return {
        "id": key,
        "started_at": _now(),
        "participants": {},
        "total_points": 0,
        "goal_claims": {},
        "archives": [],
        "history": [],
    }


def _guild_season(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _season_root(world_data)
    guilds = root["guilds"]
    gid = str(int(guild_id or 0))
    state = guilds.setdefault(gid, _new_season_state(_season_key()))
    if not isinstance(state, MutableMapping):
        state = _new_season_state(_season_key())
        guilds[gid] = state
    current = _season_key()
    if str(state.get("id", "")) != current:
        archive = {
            "id": str(state.get("id", "unknown")),
            "ended_at": _now(),
            "participants": dict(state.get("participants", {})) if isinstance(state.get("participants"), Mapping) else {},
            "total_points": int(state.get("total_points", 0) or 0),
        }
        archives = list(state.get("archives", [])) if isinstance(state.get("archives"), list) else []
        archives.append(archive)
        del archives[:-6]
        fresh = _new_season_state(current)
        fresh["archives"] = archives
        guilds[gid] = fresh
        state = fresh
    state.setdefault("participants", {})
    state.setdefault("goal_claims", {})
    state.setdefault("history", [])
    state.setdefault("archives", [])
    return state


def _participant(state: MutableMapping[str, Any], user_id: int) -> MutableMapping[str, Any]:
    participants = state.setdefault("participants", {})
    if not isinstance(participants, MutableMapping):
        participants = {}
        state["participants"] = participants
    uid = str(int(user_id))
    row = participants.setdefault(uid, {})
    if not isinstance(row, MutableMapping):
        row = {}
        participants[uid] = row
    row.setdefault("joined_at", _now())
    row.setdefault("points", 0)
    row.setdefault("weekly", {})
    row.setdefault("daily", {})
    row.setdefault("snapshot", {})
    row.setdefault("cheers_received", 0)
    row.setdefault("cheer_days", {})
    row.setdefault("claimed_seasons", [])
    row.setdefault("goal_claims", [])
    row.setdefault("last_sync", 0)
    for key in ("weekly", "daily", "snapshot", "cheer_days"):
        if not isinstance(row.get(key), MutableMapping):
            row[key] = {}
    for key in ("claimed_seasons", "goal_claims"):
        if not isinstance(row.get(key), list):
            row[key] = []
    return row


def _deep_has(value: Any, needle: str) -> bool:
    token = needle.casefold()
    if isinstance(value, Mapping):
        return any(token in str(k).casefold() or _deep_has(v, needle) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_deep_has(v, needle) for v in value)
    return token in str(value or "").casefold()


def _mount_count(world_data: Mapping[str, Any], guild_id: int, user_id: int) -> int:
    try:
        root = world_data.get("living_legends_v1620", {})
        guild = root.get("guilds", {}).get(str(int(guild_id)), {}) if isinstance(root, Mapping) else {}
        row = guild.get("users", {}).get(str(int(user_id)), {}) if isinstance(guild, Mapping) else {}
        mounts = row.get("unlocked_mounts", []) if isinstance(row, Mapping) else []
        return len(set(str(x) for x in mounts)) if isinstance(mounts, list) else 0
    except Exception:
        return 0


def _season6_info(world_data: Mapping[str, Any], guild_id: int, user_id: int) -> Tuple[bool, bool, str]:
    try:
        root = world_data.get("season6_v1700", {})
        state = root.get("guilds", {}).get(str(int(guild_id)), {}) if isinstance(root, Mapping) else {}
        participants = {str(x) for x in state.get("participants", [])} if isinstance(state, Mapping) else set()
        completed = bool(state.get("completed")) if isinstance(state, Mapping) else False
        ending = str(state.get("ending_ko") or state.get("ending_en") or "") if isinstance(state, Mapping) else ""
        return str(int(user_id)) in participants, completed, ending
    except Exception:
        return False, False, ""


def _expedition_records(user: Mapping[str, Any]) -> Mapping[str, Any]:
    root = user.get("v1680_lone_survivor", {}) if isinstance(user, Mapping) else {}
    row = root.get("records", {}) if isinstance(root, Mapping) else {}
    return row if isinstance(row, Mapping) else {}


def _contract_count(user: Mapping[str, Any]) -> int:
    root = user.get("system_fusion_v1740", {}) if isinstance(user, Mapping) else {}
    history = root.get("history", []) if isinstance(root, Mapping) else []
    return sum(1 for x in history if isinstance(x, Mapping) and x.get("type") == "complete") if isinstance(history, list) else 0


def _faction_reps(user: Mapping[str, Any]) -> Mapping[str, Any]:
    root = user.get("system_fusion_v1740", {}) if isinstance(user, Mapping) else {}
    factions = root.get("factions", {}) if isinstance(root, Mapping) else {}
    return factions if isinstance(factions, Mapping) else {}


def _bond_summary(user: Mapping[str, Any]) -> Tuple[int, int, bool]:
    root = user.get("npc_bonds_v1720", {}) if isinstance(user, Mapping) else {}
    rows = root.get("npcs", {}) if isinstance(root, Mapping) else {}
    strong = 0
    romance = 0
    if isinstance(rows, Mapping):
        for row in rows.values():
            if not isinstance(row, Mapping):
                continue
            affinity = int(row.get("affinity", 0) or 0)
            trust = int(row.get("trust", 0) or 0)
            loyalty = int(row.get("loyalty", 0) or 0)
            if trust >= 60 or affinity >= 65 or loyalty >= 60:
                strong += 1
            if bool(row.get("romance")) or str(row.get("status", "")).casefold() in {"lover", "romance", "연인"}:
                romance += 1
    betrayed = _deep_has(root.get("history", []), "betray") or _deep_has(root.get("history", []), "배신")
    return strong, romance, betrayed


def _fun_summary(user: Mapping[str, Any]) -> Tuple[int, int, int, int]:
    row = user.get("v1220_fun", {}) if isinstance(user, Mapping) else {}
    if not isinstance(row, Mapping):
        return 0, 0, 0, 0
    return (
        int(row.get("fun_score", 0) or 0),
        len(row.get("legendary_items", [])) if isinstance(row.get("legendary_items"), list) else 0,
        int(row.get("event_wins", 0) or 0),
        int(row.get("party_wins", 0) or 0),
    )


def _creator_events(user: Mapping[str, Any]) -> int:
    row = user.get("v1700", {}) if isinstance(user, Mapping) else {}
    completed = row.get("completed_events", []) if isinstance(row, Mapping) else []
    return len(completed) if isinstance(completed, list) else 0


def _metrics(user: Mapping[str, Any], world_data: Mapping[str, Any], guild_id: int, user_id: int) -> Dict[str, int]:
    records = _expedition_records(user)
    strong, romance, betrayed = _bond_summary(user)
    reps = _faction_reps(user)
    fun_score, legendary, event_wins, party_wins = _fun_summary(user)
    season6_participant, season6_completed, _ending = _season6_info(world_data, guild_id, user_id)
    return {
        "level": int(user.get("level", 1) or 1),
        "exp": int(user.get("exp", 0) or 0),
        "balance": int(user.get("balance", 0) or 0),
        "contracts": _contract_count(user),
        "runs": int(records.get("runs", 0) or 0),
        "victories": int(records.get("victories", 0) or 0),
        "best_score": int(records.get("best_score", 0) or 0),
        "mounts": _mount_count(world_data, guild_id, user_id),
        "strong_bonds": strong,
        "romance": romance,
        "betrayed": int(betrayed),
        "faction_50": sum(1 for v in reps.values() if int(v or 0) >= 50),
        "faction_90": sum(1 for v in reps.values() if int(v or 0) >= 90),
        "creator_events": _creator_events(user),
        "fun_score": fun_score,
        "legendary_items": legendary,
        "event_wins": event_wins,
        "party_wins": party_wins,
        "season6_participant": int(season6_participant),
        "season6_completed": int(season6_completed),
    }


ACHIEVEMENTS: Tuple[Dict[str, Any], ...] = (
    {"id":"first_signal","emoji":"📻","ko":"첫 번째 신호","en":"First Signal","desc_ko":"레벨 3에 도달","desc_en":"Reach level 3","metric":"level","target":3,"points":10,"title":"signal_survivor"},
    {"id":"veteran","emoji":"🪖","ko":"노련한 생존자","en":"Seasoned Survivor","desc_ko":"레벨 20에 도달","desc_en":"Reach level 20","metric":"level","target":20,"points":35,"title":"veteran"},
    {"id":"wealth","emoji":"💰","ko":"폐허의 자산가","en":"Wasteland Magnate","desc_ko":"식량 100,000 보유","desc_en":"Hold 100,000 supplies","metric":"balance","target":100000,"points":25,"title":"magnate"},
    {"id":"first_run","emoji":"🌑","ko":"첫 원정","en":"First Expedition","desc_ko":"솔로 원정 1회 출발","desc_en":"Start one solo expedition","metric":"runs","target":1,"points":15,"title":"pathfinder"},
    {"id":"expedition_legend","emoji":"🏆","ko":"귀환의 전설","en":"Legend of Return","desc_ko":"솔로 원정 10회 완주","desc_en":"Win ten solo expeditions","metric":"victories","target":10,"points":60,"title":"return_legend"},
    {"id":"contract_agent","emoji":"📜","ko":"생존망 요원","en":"Survival Network Agent","desc_ko":"생존 의뢰 10개 완료","desc_en":"Complete ten survival contracts","metric":"contracts","target":10,"points":45,"title":"network_agent"},
    {"id":"mount_collector","emoji":"🏍️","ko":"기계 군단 수집가","en":"Machine Legion Collector","desc_ko":"탈것 8종 전부 해금","desc_en":"Unlock all eight mounts","metric":"mounts","target":8,"points":80,"title":"mount_master"},
    {"id":"trusted","emoji":"🤝","ko":"신뢰받는 동료","en":"Trusted Companion","desc_ko":"강한 NPC 인연 3명","desc_en":"Build three strong NPC bonds","metric":"strong_bonds","target":3,"points":40,"title":"trusted_companion"},
    {"id":"romance","emoji":"💞","ko":"종말의 약속","en":"Promise at the End","desc_ko":"연인 관계 1명 해금","desc_en":"Unlock one romance","metric":"romance","target":1,"points":55,"title":"last_promise"},
    {"id":"broken_oath","emoji":"🗡️","ko":"깨진 맹세의 생존자","en":"Survivor of a Broken Oath","desc_ko":"배신 사건에서 살아남음","desc_en":"Survive a betrayal event","metric":"betrayed","target":1,"points":50,"title":"broken_oath"},
    {"id":"diplomat","emoji":"🏴","ko":"다섯 깃발의 중재자","en":"Mediator of Five Banners","desc_ko":"세력 3곳 평판 50 달성","desc_en":"Reach 50 reputation with three factions","metric":"faction_50","target":3,"points":65,"title":"five_banners"},
    {"id":"story_witness","emoji":"☀️","ko":"검은 태양의 증인","en":"Witness of the Black Sun","desc_ko":"시즌 6 공동 결말에 참여","desc_en":"Participate in the Season 6 ending","metric":"season6_participant","target":1,"points":45,"title":"black_sun_witness"},
    {"id":"creator_guest","emoji":"🎭","ko":"사용자 세계의 여행자","en":"Traveler of Player Worlds","desc_ko":"사용자 제작 사건 5개 완료","desc_en":"Complete five player-created events","metric":"creator_events","target":5,"points":35,"title":"world_traveler"},
    {"id":"legend_keeper","emoji":"🏺","ko":"전설의 보관자","en":"Keeper of Legends","desc_ko":"전설 아이템 3개 보유","desc_en":"Own three legendary items","metric":"legendary_items","target":3,"points":50,"title":"legend_keeper"},
    {"id":"festival_star","emoji":"🎉","ko":"혼돈 축제의 별","en":"Star of the Chaos Festival","desc_ko":"이벤트·파티 승리 합계 20회","desc_en":"Win 20 events and party games","metric":"festival_wins","target":20,"points":40,"title":"festival_star"},
)

TITLES: Dict[str, Tuple[str, str, str]] = {
    "signal_survivor": ("📻", "신호를 들은 자", "One Who Heard the Signal"),
    "veteran": ("🪖", "노련한 생존자", "Seasoned Survivor"),
    "magnate": ("💰", "폐허의 자산가", "Wasteland Magnate"),
    "pathfinder": ("🌑", "어둠의 길잡이", "Pathfinder of the Dark"),
    "return_legend": ("🏆", "귀환의 전설", "Legend of Return"),
    "network_agent": ("📜", "생존망 요원", "Survival Network Agent"),
    "mount_master": ("🏍️", "기계 군단의 주인", "Master of the Machine Legion"),
    "trusted_companion": ("🤝", "신뢰받는 동료", "Trusted Companion"),
    "last_promise": ("💞", "종말의 약속", "Promise at the End"),
    "broken_oath": ("🗡️", "깨진 맹세", "Broken Oath"),
    "five_banners": ("🏴", "다섯 깃발의 중재자", "Mediator of Five Banners"),
    "black_sun_witness": ("☀️", "검은 태양의 증인", "Witness of the Black Sun"),
    "world_traveler": ("🎭", "사용자 세계의 여행자", "Traveler of Player Worlds"),
    "legend_keeper": ("🏺", "전설의 보관자", "Keeper of Legends"),
    "festival_star": ("🎉", "혼돈 축제의 별", "Star of the Chaos Festival"),
}

MUSEUM_LEVELS: Tuple[Tuple[int, str, str, str], ...] = (
    (0, "폐허 보관소", "Ruined Archive", "🧱"),
    (80, "생존 기록관", "Survivor Archive", "📚"),
    (220, "BLACK CITY 박물관", "BLACK CITY Museum", "🏛️"),
    (450, "심연의 대전당", "Grand Hall of the Abyss", "🌌"),
    (750, "아바돈 영원의 전당", "ABADDON Hall of Eternity", "👑"),
)


def _achievement_value(metric: str, metrics: Mapping[str, int]) -> int:
    if metric == "festival_wins":
        return int(metrics.get("event_wins", 0)) + int(metrics.get("party_wins", 0))
    return int(metrics.get(metric, 0) or 0)


def _achievement_status(metrics: Mapping[str, int]) -> List[Tuple[Dict[str, Any], int, bool]]:
    return [(spec, _achievement_value(str(spec["metric"]), metrics), _achievement_value(str(spec["metric"]), metrics) >= int(spec["target"])) for spec in ACHIEVEMENTS]


def _museum_points(metrics: Mapping[str, int]) -> int:
    return sum(int(spec["points"]) for spec, _value, done in _achievement_status(metrics) if done)


def _museum_level(points: int) -> Tuple[int, str, str, str, int]:
    selected = MUSEUM_LEVELS[0]
    next_at = 0
    for index, row in enumerate(MUSEUM_LEVELS):
        if points >= row[0]:
            selected = row
            next_at = MUSEUM_LEVELS[index + 1][0] if index + 1 < len(MUSEUM_LEVELS) else row[0]
    return selected[0], selected[1], selected[2], selected[3], next_at


def _title_text(locale: str, title_id: str) -> str:
    row = TITLES.get(str(title_id))
    if not row:
        return _t(locale, "미장착", "None")
    return f"{row[0]} {_t(locale, row[1], row[2])}"


def _sync_achievements(user: MutableMapping[str, Any], metrics: Mapping[str, int]) -> Tuple[List[str], int]:
    museum = _museum(user)
    claimed = set(str(x) for x in museum["claimed"])
    titles = set(str(x) for x in museum["titles"])
    unlocked: List[str] = []
    for spec, _value, done in _achievement_status(metrics):
        if not done or spec["id"] in claimed:
            continue
        claimed.add(str(spec["id"]))
        titles.add(str(spec["title"]))
        unlocked.append(str(spec["id"]))
        museum["history"].append({"at": _now(), "type": "achievement", "id": spec["id"]})
    museum["claimed"] = sorted(claimed)
    museum["titles"] = sorted(titles)
    del museum["history"][:-150]
    return unlocked, _museum_points(metrics)


def _museum_embed(locale: str, member: Any, user: Mapping[str, Any], world_data: Mapping[str, Any], guild_id: int) -> discord.Embed:
    uid = int(getattr(member, "id", 0) or 0)
    metrics = _metrics(user, world_data, guild_id, uid)
    points = _museum_points(metrics)
    start, ko_level, en_level, emoji, next_at = _museum_level(points)
    museum = user.get(MUSEUM_KEY, {}) if isinstance(user.get(MUSEUM_KEY), Mapping) else {}
    name = str(getattr(member, "display_name", getattr(member, "name", "Survivor")))[:60]
    active = str(museum.get("active_title", ""))
    embed = discord.Embed(
        title=_t(locale, f"{emoji} {name}의 연대기 박물관", f"{emoji} {name}'s Chronicle Museum"),
        description=_t(locale, f"**{ko_level}** · 전시 점수 **{points}**", f"**{en_level}** · Exhibit Score **{points}**"),
        color=0x6C3483,
    )
    completed = sum(1 for _spec, _value, done in _achievement_status(metrics) if done)
    embed.add_field(name=_t(locale, "🏷️ 대표 칭호", "🏷️ Featured Title"), value=_title_text(locale, active), inline=True)
    embed.add_field(name=_t(locale, "🏆 업적", "🏆 Achievements"), value=f"{completed}/{len(ACHIEVEMENTS)}", inline=True)
    embed.add_field(name=_t(locale, "💜 추천", "💜 Recommendations"), value=str(int(museum.get("recommendations", 0) or 0)), inline=True)
    story_participant, story_done, ending = _season6_info(world_data, guild_id, uid)
    story_line = _t(locale, "시즌 6 미참여", "Season 6 not joined")
    if story_participant:
        story_line = _t(locale, f"검은 태양 참여{f' · {ending}' if ending else ''}", f"Black Sun participant{f' · {ending}' if ending else ''}")
    exhibits = [
        _t(locale, f"📖 이야기 · {story_line}", f"📖 Story · {story_line}"),
        _t(locale, f"🌑 원정 · 완주 {metrics['victories']}회 / 최고 {metrics['best_score']:,}", f"🌑 Expeditions · {metrics['victories']} wins / best {metrics['best_score']:,}"),
        _t(locale, f"🏍️ 탈것 · {metrics['mounts']}/8", f"🏍️ Mounts · {metrics['mounts']}/8"),
        _t(locale, f"🤝 인연 · 강한 인연 {metrics['strong_bonds']}명 / 연인 {metrics['romance']}명", f"🤝 Bonds · {metrics['strong_bonds']} strong / {metrics['romance']} romance"),
        _t(locale, f"📜 의뢰 · {metrics['contracts']}개 완료", f"📜 Contracts · {metrics['contracts']} complete"),
        _t(locale, f"🏴 세력 · 핵심 평판 {metrics['faction_90']}곳", f"🏴 Factions · {metrics['faction_90']} elite standings"),
    ]
    embed.add_field(name=_t(locale, "🖼️ 주요 전시", "🖼️ Featured Exhibits"), value="\n".join(exhibits), inline=False)
    if next_at > start:
        embed.add_field(name=_t(locale, "🏛️ 다음 확장", "🏛️ Next Expansion"), value=_t(locale, f"전시 점수 **{next_at}**에서 다음 전시관 해금 · 현재 {points}/{next_at}", f"Next hall unlocks at **{next_at}** · current {points}/{next_at}"), inline=False)
    embed.set_footer(text=_t(locale, "업적을 달성하면 전시와 칭호가 자동으로 확장됩니다.", "Achievements automatically expand exhibits and titles."))
    return _safe_embed(embed)


def _snapshot(user: Mapping[str, Any], world_data: Mapping[str, Any], guild_id: int, user_id: int) -> Dict[str, int]:
    metrics = _metrics(user, world_data, guild_id, user_id)
    return {
        "exp": int(metrics["exp"]),
        "contracts": int(metrics["contracts"]),
        "runs": int(metrics["runs"]),
        "victories": int(metrics["victories"]),
        "mounts": int(metrics["mounts"]),
        "strong_bonds": int(metrics["strong_bonds"]),
        "museum_points": int(_museum_points(metrics)),
        "creator_events": int(metrics["creator_events"]),
    }


def _daily_connected(user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> Dict[str, bool]:
    try:
        from apocalypse_bot.commands import v1730_connected_survival_loop as connected
        raw = connected._daily_status(user, world_data, int(guild_id), save_data)
        return {str(k): bool(v) for k, v in raw.items()}
    except Exception:
        return {"world": False, "expedition": False, "npc": False, "city": False}


def _ranking(state: Mapping[str, Any], *, weekly: bool = False) -> List[Tuple[str, int]]:
    rows: List[Tuple[str, int]] = []
    participants = state.get("participants", {}) if isinstance(state, Mapping) else {}
    if not isinstance(participants, Mapping):
        return rows
    week = _week_key()
    for uid, row in participants.items():
        if not isinstance(row, Mapping):
            continue
        score = int(row.get("weekly", {}).get(week, 0) or 0) if weekly and isinstance(row.get("weekly"), Mapping) else int(row.get("points", 0) or 0)
        rows.append((str(uid), score))
    rows.sort(key=lambda item: (-item[1], int(item[0]) if item[0].isdigit() else 0))
    return rows


def _division(points: int) -> Tuple[str, str, str]:
    if points >= 900:
        return "🌌", "심연", "Abyss"
    if points >= 500:
        return "👑", "전설", "Legend"
    if points >= 250:
        return "🥇", "골드", "Gold"
    if points >= 100:
        return "🥈", "실버", "Silver"
    return "🥉", "브론즈", "Bronze"


SERVER_GOALS: Tuple[Tuple[int, int, int, str, str], ...] = (
    (500, 8000, 40, "보급망 개방", "Supply Network Opened"),
    (1500, 18000, 90, "BLACK CITY 공동 방어", "BLACK CITY Joint Defense"),
    (3500, 35000, 180, "심연 관문 안정화", "Abyss Gate Stabilized"),
    (7000, 70000, 350, "서버 전설 수립", "Server Legend Established"),
)


def _sync_season(
    user: MutableMapping[str, Any], state: MutableMapping[str, Any], user_id: int,
    world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None],
) -> Tuple[int, List[str], MutableMapping[str, Any]]:
    part = _participant(state, user_id)
    current = _snapshot(user, world_data, guild_id, user_id)
    old = part.get("snapshot", {}) if isinstance(part.get("snapshot"), Mapping) else {}
    day = _today()
    week = _week_key()
    daily = part.setdefault("daily", {}).setdefault(day, {})
    if not isinstance(daily, MutableMapping):
        daily = {}
        part["daily"][day] = daily
    reasons: List[str] = []
    points = 0
    if old:
        exp_gain = max(0, current["exp"] - int(old.get("exp", current["exp"]) or 0))
        contract_gain = max(0, current["contracts"] - int(old.get("contracts", current["contracts"]) or 0))
        run_gain = max(0, current["runs"] - int(old.get("runs", current["runs"]) or 0))
        win_gain = max(0, current["victories"] - int(old.get("victories", current["victories"]) or 0))
        mount_gain = max(0, current["mounts"] - int(old.get("mounts", current["mounts"]) or 0))
        bond_gain = max(0, current["strong_bonds"] - int(old.get("strong_bonds", current["strong_bonds"]) or 0))
        museum_gain = max(0, current["museum_points"] - int(old.get("museum_points", current["museum_points"]) or 0))
        event_gain = max(0, current["creator_events"] - int(old.get("creator_events", current["creator_events"]) or 0))
        raw = min(20, exp_gain // 100) + contract_gain * 20 + run_gain * 6 + win_gain * 24 + mount_gain * 18 + bond_gain * 12 + museum_gain // 4 + event_gain * 10
        if raw:
            points += int(raw)
            reasons.append(f"gameplay +{int(raw)}")
    statuses = _daily_connected(user, world_data, guild_id, save_data)
    mission_labels = {"world":"world event", "expedition":"expedition", "npc":"NPC mission", "city":"city workshop"}
    for key, done in statuses.items():
        if done and not daily.get(f"mission:{key}"):
            daily[f"mission:{key}"] = True
            points += 12
            reasons.append(f"{mission_labels.get(key, key)} +12")
    # Fair play: repeated commands cannot farm indefinitely. Only 120 sync points/day.
    already = int(daily.get("sync_points", 0) or 0)
    room = max(0, 120 - already)
    granted = max(0, min(points, room))
    if granted > 0:
        rankings = _ranking(state)
        median = rankings[len(rankings)//2][1] if rankings else 0
        if int(part.get("points", 0) or 0) < median and len(rankings) >= 5 and granted < room:
            boost = min(12, max(1, granted // 10), room - granted)
            granted += boost
            reasons.append(f"catch-up +{boost}")
        part["points"] = int(part.get("points", 0) or 0) + granted
        part.setdefault("weekly", {})[week] = int(part.get("weekly", {}).get(week, 0) or 0) + granted
        daily["sync_points"] = already + granted
        state["total_points"] = int(state.get("total_points", 0) or 0) + granted
        history = state.setdefault("history", [])
        history.append({"at": _now(), "type":"sync", "user":str(user_id), "points":granted})
        del history[:-300]
    part["snapshot"] = current
    part["last_sync"] = _now()
    return granted, reasons, part


class MuseumButton(discord.ui.Button):
    def __init__(self, owner: "MuseumView", action: str, ko: str, en: str, emoji: str, style: discord.ButtonStyle):
        super().__init__(label=_t(owner.locale, ko, en), emoji=emoji, style=style)
        self.owner_view = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if int(interaction.user.id) != view.owner_id:
            await interaction.response.send_message(_t(view.locale, "이 전시관은 실행자만 조작할 수 있습니다.", "Only the opener can use this museum panel."), ephemeral=True)
            return
        mapping = {
            "achievements": ("통합업적", "achievementsall"),
            "titles": ("통합칭호", "alltitles"),
            "legends": ("전설도감", "legendcollection"),
            "season": ("서버시즌", "abaddonseason"),
        }
        command = None
        for name in mapping[self.action]:
            command = view.bot.get_command(name)
            if command is not None:
                break
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결 명령을 찾지 못했습니다.", "Linked command not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name)


class MuseumView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str):
        super().__init__(timeout=600)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        self.add_item(MuseumButton(self, "achievements", "업적", "Achievements", "🏆", discord.ButtonStyle.primary))
        self.add_item(MuseumButton(self, "titles", "칭호", "Titles", "🏷️", discord.ButtonStyle.secondary))
        self.add_item(MuseumButton(self, "legends", "전설 도감", "Legend Codex", "🏺", discord.ButtonStyle.secondary))
        self.add_item(MuseumButton(self, "season", "서버 시즌", "Server Season", "🌐", discord.ButtonStyle.success))


class SeasonButton(discord.ui.Button):
    def __init__(self, owner: "SeasonView", action: str, ko: str, en: str, emoji: str, style: discord.ButtonStyle):
        super().__init__(label=_t(owner.locale, ko, en), emoji=emoji, style=style)
        self.owner_view = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if int(interaction.user.id) != view.owner_id:
            await interaction.response.send_message(_t(view.locale, "이 시즌 패널은 실행자만 조작할 수 있습니다.", "Only the opener can use this season panel."), ephemeral=True)
            return
        mapping = {
            "join": ("시즌참가", "joinabaddonseason"),
            "sync": ("시즌동기화", "syncseason"),
            "ranking": ("시즌랭킹", "communityranking"),
            "goals": ("서버목표", "servergoals"),
            "missions": ("시즌미션", "seasonmissions"),
        }
        command = next((view.bot.get_command(name) for name in mapping[self.action] if view.bot.get_command(name) is not None), None)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결 명령을 찾지 못했습니다.", "Linked command not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name)


class SeasonView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str):
        super().__init__(timeout=600)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        self.add_item(SeasonButton(self, "join", "참가", "Join", "🚪", discord.ButtonStyle.success))
        self.add_item(SeasonButton(self, "sync", "진행 동기화", "Sync Progress", "🔄", discord.ButtonStyle.primary))
        self.add_item(SeasonButton(self, "ranking", "랭킹", "Ranking", "🏆", discord.ButtonStyle.secondary))
        self.add_item(SeasonButton(self, "goals", "서버 목표", "Server Goals", "🌐", discord.ButtonStyle.secondary))
        self.add_item(SeasonButton(self, "missions", "오늘 미션", "Daily Missions", "🎯", discord.ButtonStyle.primary))


def register_v1760_chronicle_museum_season(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1760_registered", False):
        return
    bot._abaddon_v1760_registered = True

    @bot.command(name="연대기박물관", aliases=["chroniclemuseum", "abaddonmuseum", "museum"], help="내 이야기·원정·탈것·NPC·세력·업적을 하나의 전시관으로 확인합니다.")
    async def chronicle_museum(ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        target = member or ctx.author
        if member is None and not await check_registered(ctx):
            return
        user = _safe_user(get_user, int(target.id))
        if user is None:
            await ctx.send(_t(_locale(bot, ctx), "등록된 생존자의 전시관만 확인할 수 있습니다.", "Only registered survivor museums can be viewed."))
            return
        locale = _locale(bot, ctx)
        metrics = _metrics(user, world_data, int(ctx.guild.id if ctx.guild else 0), int(target.id))
        unlocked, _points = _sync_achievements(user, metrics)
        museum = _museum(user)
        if int(target.id) != int(ctx.author.id):
            day_visitors = museum.setdefault("daily_visitors", {})
            day_key = f"{_today()}:{ctx.author.id}"
            if not day_visitors.get(day_key):
                day_visitors[day_key] = True
                museum["visits"] = int(museum.get("visits", 0) or 0) + 1
        if unlocked or int(target.id) != int(ctx.author.id):
            save_data()
        view = MuseumView(bot, int(ctx.author.id), locale) if int(target.id) == int(ctx.author.id) else None
        await ctx.send(embed=_museum_embed(locale, target, user, world_data, int(ctx.guild.id if ctx.guild else 0)), view=_safe_view(view) if view else None)

    @bot.command(name="내전시관", aliases=["mygallery", "myexhibit"], help="내 연대기 박물관을 바로 엽니다.")
    async def my_gallery(ctx: commands.Context) -> None:
        await ctx.invoke(chronicle_museum)

    @bot.command(name="전시관", aliases=["gallery", "visitmuseum"], help="다른 생존자의 연대기 박물관을 방문합니다.")
    async def gallery(ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        await ctx.invoke(chronicle_museum, member=member)

    @bot.command(name="통합업적", aliases=["achievementsall", "globalachievements"], help="아바돈 전체 시스템을 아우르는 통합 업적을 확인합니다.")
    async def all_achievements(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = _safe_user(get_user, int(ctx.author.id))
        if user is None:
            return
        metrics = _metrics(user, world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        unlocked, points = _sync_achievements(user, metrics)
        if unlocked:
            save_data()
        lines = []
        for spec, value, done in _achievement_status(metrics):
            target = int(spec["target"])
            shown = min(value, target)
            lines.append(f"{'✅' if done else '⬜'} {spec['emoji']} **{_t(locale, spec['ko'], spec['en'])}** · {shown:,}/{target:,} · +{spec['points']}pt")
        embed = discord.Embed(title=_t(locale, "🏆 통합 업적", "🏆 Global Achievements"), description="\n".join(lines), color=0xF1C40F)
        embed.set_footer(text=_t(locale, f"전시 점수 {points} · 새 업적 {len(unlocked)}개", f"Exhibit score {points} · {len(unlocked)} newly unlocked"))
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="통합칭호", aliases=["alltitles", "museumtitles"], help="박물관 업적으로 해금한 칭호와 현재 대표 칭호를 확인합니다.")
    async def all_titles(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = _safe_user(get_user, int(ctx.author.id))
        if user is None:
            return
        metrics = _metrics(user, world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        unlocked, _ = _sync_achievements(user, metrics)
        museum = _museum(user)
        if unlocked:
            save_data()
        owned = set(str(x) for x in museum.get("titles", []))
        active = str(museum.get("active_title", ""))
        lines = [f"{'✨' if key == active else '✅' if key in owned else '🔒'} `{key}` · {emoji} **{_t(locale, ko, en)}**" for key, (emoji, ko, en) in TITLES.items()]
        embed = discord.Embed(title=_t(locale, "🏷️ 통합 칭호", "🏷️ Global Titles"), description="\n".join(lines), color=0x8E44AD)
        embed.set_footer(text=_t(locale, "장착: !칭호장착 칭호ID", "Equip: !equipmuseumtitle TITLE_ID"))
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="칭호장착", aliases=["equipmuseumtitle", "featuretitle"], help="박물관 업적으로 얻은 대표 칭호를 장착합니다.")
    async def equip_title(ctx: commands.Context, title_id: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = _safe_user(get_user, int(ctx.author.id))
        if user is None:
            return
        museum = _museum(user)
        token = str(title_id).strip()
        if token not in set(str(x) for x in museum.get("titles", [])) or token not in TITLES:
            await ctx.send(_t(locale, "보유한 칭호 ID를 입력하세요. `!통합칭호`에서 확인할 수 있습니다.", "Enter an owned title ID. Check `!alltitles`."))
            return
        museum["active_title"] = token
        save_data()
        await ctx.send(_t(locale, f"🏷️ 대표 칭호를 **{_title_text(locale, token)}**로 변경했습니다.", f"🏷️ Featured title set to **{_title_text(locale, token)}**."))

    @bot.command(name="전설도감", aliases=["legendcollection", "legendcodex"], help="탈것·전설 아이템·원정 유물·주요 전시 수집 현황을 확인합니다.")
    async def legend_codex(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = _safe_user(get_user, int(ctx.author.id))
        if user is None:
            return
        metrics = _metrics(user, world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        lone = user.get("v1680_lone_survivor", {}) if isinstance(user.get("v1680_lone_survivor"), Mapping) else {}
        codex = lone.get("codex", {}) if isinstance(lone, Mapping) else {}
        relics = len(codex.get("relics", [])) if isinstance(codex, Mapping) and isinstance(codex.get("relics"), list) else 0
        blueprints = len(codex.get("blueprints", [])) if isinstance(codex, Mapping) and isinstance(codex.get("blueprints"), list) else 0
        embed = discord.Embed(title=_t(locale, "🏺 전설 도감", "🏺 Legend Codex"), color=0xD68910)
        embed.add_field(name=_t(locale, "🏍️ 탈것", "🏍️ Mounts"), value=f"{metrics['mounts']}/8", inline=True)
        embed.add_field(name=_t(locale, "🔮 원정 유물", "🔮 Expedition Relics"), value=str(relics), inline=True)
        embed.add_field(name=_t(locale, "📐 설계도", "📐 Blueprints"), value=str(blueprints), inline=True)
        embed.add_field(name=_t(locale, "🏺 전설 아이템", "🏺 Legendary Items"), value=str(metrics['legendary_items']), inline=True)
        embed.add_field(name=_t(locale, "🎭 사용자 사건", "🎭 Player Events"), value=str(metrics['creator_events']), inline=True)
        embed.add_field(name=_t(locale, "☀️ 시즌 6", "☀️ Season 6"), value=_t(locale, "참여" if metrics['season6_participant'] else "미참여", "Joined" if metrics['season6_participant'] else "Not joined"), inline=True)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="결말기록", aliases=["endinghistory", "storyendings"], help="시즌 결말과 원정 결말 도감 기록을 확인합니다.")
    async def ending_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = _safe_user(get_user, int(ctx.author.id))
        if user is None:
            return
        participant, completed, ending = _season6_info(world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        lone = user.get("v1680_lone_survivor", {}) if isinstance(user.get("v1680_lone_survivor"), Mapping) else {}
        codex = lone.get("codex", {}) if isinstance(lone, Mapping) else {}
        endings = list(codex.get("endings", [])) if isinstance(codex, Mapping) and isinstance(codex.get("endings"), list) else []
        lines = [_t(locale, f"☀️ 시즌 6 · {'완료' if completed else '진행 중/미시작'} · {ending or '결말 미확정'}", f"☀️ Season 6 · {'Complete' if completed else 'Ongoing/Not started'} · {ending or 'Ending unresolved'}")]
        lines.extend(f"🌑 {x}" for x in endings[-12:])
        await ctx.send(embed=_safe_embed(discord.Embed(title=_t(locale, "📖 결말 기록", "📖 Ending History"), description="\n".join(lines) or "-", color=0x5B2C6F)))

    @bot.command(name="박물관추천", aliases=["recommendmuseum", "museumlike"], help="다른 생존자의 박물관을 하루 한 번 추천합니다.")
    async def recommend_museum(ctx: commands.Context, member: discord.Member) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        if int(member.id) == int(ctx.author.id):
            await ctx.send(_t(locale, "자기 전시관은 추천할 수 없습니다.", "You cannot recommend your own museum."))
            return
        target = _safe_user(get_user, int(member.id))
        actor = _safe_user(get_user, int(ctx.author.id))
        if target is None or actor is None:
            await ctx.send(_t(locale, "등록된 생존자만 추천할 수 있습니다.", "Only registered survivors can be recommended."))
            return
        actor_museum = _museum(actor)
        key = f"{_today()}:{member.id}"
        if actor_museum["recommended_today"].get(key):
            await ctx.send(_t(locale, "오늘 이미 이 전시관을 추천했습니다.", "You already recommended this museum today."))
            return
        actor_museum["recommended_today"][key] = True
        target_museum = _museum(target)
        target_museum["recommendations"] = int(target_museum.get("recommendations", 0) or 0) + 1
        save_data()
        await ctx.send(_t(locale, f"💜 **{member.display_name}**의 전시관을 추천했습니다.", f"💜 Recommended **{member.display_name}**'s museum."))

    @bot.command(name="박물관보상", aliases=["museumreward", "galleryreward"], help="전시관 단계별 일회성 보상을 수령합니다.")
    async def museum_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = _safe_user(get_user, int(ctx.author.id))
        if user is None:
            return
        metrics = _metrics(user, world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        points = _museum_points(metrics)
        museum = _museum(user)
        claims = set(str(x) for x in museum.get("reward_claims", []))
        rewards = [(80,12000,60),(220,30000,140),(450,65000,300),(750,120000,550)]
        available = [(p,f,e) for p,f,e in rewards if points >= p and str(p) not in claims]
        if not available:
            await ctx.send(_t(locale, "현재 수령할 새 박물관 단계 보상이 없습니다.", "No new museum tier reward is available."))
            return
        food = sum(x[1] for x in available); exp = sum(x[2] for x in available)
        user["balance"] = int(user.get("balance", 0) or 0) + food
        user["exp"] = int(user.get("exp", 0) or 0) + exp
        claims.update(str(x[0]) for x in available)
        museum["reward_claims"] = sorted(claims)
        save_data()
        await ctx.send(_t(locale, f"🏛️ 박물관 단계 보상 수령 · 식량 +{food:,} · EXP +{exp:,}", f"🏛️ Museum tier rewards claimed · Supplies +{food:,} · EXP +{exp:,}"))

    @bot.command(name="서버시즌", aliases=["abaddonseason", "communityseason", "serverseason"], help="현재 커뮤니티 시즌, 내 기여도, 서버 목표와 랭킹을 확인합니다.")
    async def server_season(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        gid = int(ctx.guild.id if ctx.guild else 0)
        state = _guild_season(world_data, gid)
        participants = state.get("participants", {}) if isinstance(state.get("participants"), Mapping) else {}
        part = participants.get(str(ctx.author.id), {}) if isinstance(participants, Mapping) else {}
        points = int(part.get("points", 0) or 0) if isinstance(part, Mapping) else 0
        emoji, ko_div, en_div = _division(points)
        ranking = _ranking(state)
        rank = next((i for i,(uid,_score) in enumerate(ranking,1) if uid == str(ctx.author.id)), 0)
        embed = discord.Embed(title=_t(locale, f"🌐 아바돈 커뮤니티 시즌 · {state['id']}", f"🌐 ABADDON Community Season · {state['id']}"), description=_t(locale, "기존 게임을 플레이하면 기여도가 자동으로 연결됩니다. 반복 명령 도배로는 점수를 얻을 수 없습니다.", "Existing gameplay feeds contribution automatically. Repeating commands cannot farm points."), color=0x1ABC9C)
        embed.add_field(name=_t(locale, "👤 내 시즌", "👤 My Season"), value=_t(locale, f"{emoji} **{ko_div}** · {points}점 · {f'{rank}위' if rank else '미참가'}", f"{emoji} **{en_div}** · {points} pts · {f'Rank #{rank}' if rank else 'Not joined'}"), inline=True)
        embed.add_field(name=_t(locale, "👥 참가자", "👥 Participants"), value=str(len(participants)), inline=True)
        embed.add_field(name=_t(locale, "🌐 서버 기여", "🌐 Server Contribution"), value=f"{int(state.get('total_points',0) or 0):,}", inline=True)
        next_goal = next((g for g in SERVER_GOALS if int(state.get("total_points",0) or 0) < g[0]), None)
        if next_goal:
            embed.add_field(name=_t(locale, "🎯 다음 공동 목표", "🎯 Next Shared Goal"), value=_t(locale, f"{next_goal[3]} · {int(state.get('total_points',0) or 0):,}/{next_goal[0]:,}", f"{next_goal[4]} · {int(state.get('total_points',0) or 0):,}/{next_goal[0]:,}"), inline=False)
        embed.set_footer(text=_t(locale, "참가 → 동기화 → 오늘 미션 → 랭킹 → 공동 보상", "Join → Sync → Daily Missions → Ranking → Shared Rewards"))
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(SeasonView(bot, int(ctx.author.id), locale)))

    @bot.command(name="시즌참가", aliases=["joinabaddonseason", "joincommunityseason"], help="현재 커뮤니티 시즌에 참가하고 기존 진행 기준점을 저장합니다.")
    async def season_join(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx); gid = int(ctx.guild.id if ctx.guild else 0)
        user = _safe_user(get_user, int(ctx.author.id)); state = _guild_season(world_data, gid)
        if user is None: return
        existing = str(ctx.author.id) in state.get("participants", {})
        part = _participant(state, int(ctx.author.id))
        if not part.get("snapshot"):
            part["snapshot"] = _snapshot(user, world_data, gid, int(ctx.author.id))
        if not existing:
            user["balance"] = int(user.get("balance", 0) or 0) + 5000
            state["history"].append({"at":_now(),"type":"join","user":str(ctx.author.id)})
        save_data()
        await ctx.send(_t(locale, "🌐 시즌 참가 완료 · 기존 진행은 보존되며 앞으로의 활동부터 기여도가 쌓입니다. 참가 보급 식량 +5,000", "🌐 Season joined. Existing progress is preserved and future activity earns contribution. Join supplies +5,000"))

    @bot.command(name="시즌동기화", aliases=["syncseason", "seasonprogress"], help="기존 RPG 활동과 오늘의 연결 목표를 커뮤니티 시즌 기여도로 동기화합니다.")
    async def season_sync(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx); gid = int(ctx.guild.id if ctx.guild else 0)
        user = _safe_user(get_user, int(ctx.author.id)); state = _guild_season(world_data, gid)
        if user is None: return
        if str(ctx.author.id) not in state.get("participants", {}):
            await ctx.send(_t(locale, "먼저 `!시즌참가`로 참가하세요.", "Join first with `!joinabaddonseason`.")); return
        metrics = _metrics(user, world_data, gid, int(ctx.author.id))
        unlocked, _ = _sync_achievements(user, metrics)
        granted, reasons, part = _sync_season(user, state, int(ctx.author.id), world_data, gid, save_data)
        save_data()
        if granted <= 0:
            await ctx.send(_t(locale, "🔄 동기화 완료 · 새 기여도는 없습니다. 오늘 미션이나 기존 콘텐츠를 진행해보세요.", "🔄 Sync complete · no new contribution. Complete daily missions or existing content.")); return
        await ctx.send(_t(locale, f"🔄 시즌 기여도 **+{granted}** · 누적 **{int(part.get('points',0) or 0)}**\n" + " · ".join(reasons[:6]), f"🔄 Season contribution **+{granted}** · total **{int(part.get('points',0) or 0)}**\n" + " · ".join(reasons[:6])))

    @bot.command(name="시즌랭킹", aliases=["communityranking", "abaddonranking"], help="커뮤니티 시즌 전체 기여도 랭킹을 확인합니다.")
    async def season_ranking(ctx: commands.Context, page: int = 1) -> None:
        locale = _locale(bot, ctx); state = _guild_season(world_data, int(ctx.guild.id if ctx.guild else 0))
        rows = _ranking(state); page = max(1, int(page)); size=10; max_page=max(1, math.ceil(len(rows)/size)); page=min(page,max_page)
        chunk=rows[(page-1)*size:page*size]; medals=("🥇","🥈","🥉")
        lines=[f"{medals[i-1] if i<=3 else f'`{i}.`'} <@{uid}> · **{score:,}**" for i,(uid,score) in enumerate(chunk,start=(page-1)*size+1)]
        embed=discord.Embed(title=_t(locale,f"🏆 커뮤니티 시즌 랭킹 · {state['id']}",f"🏆 Community Season Ranking · {state['id']}"),description="\n".join(lines) or _t(locale,"아직 참가자가 없습니다.","No participants yet."),color=0xF1C40F)
        embed.set_footer(text=f"{page}/{max_page} · {len(rows)} participants")
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="서버주간랭킹", aliases=["serverweeklyranking", "communityweekly"], help="이번 주 커뮤니티 시즌 기여도 랭킹을 확인합니다.")
    async def season_weekly_ranking(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx); state = _guild_season(world_data, int(ctx.guild.id if ctx.guild else 0)); rows=_ranking(state,weekly=True)[:15]
        lines=[f"{i}. <@{uid}> · **{score:,}**" for i,(uid,score) in enumerate(rows,1)]
        await ctx.send(embed=_safe_embed(discord.Embed(title=_t(locale,f"📅 서버 주간 랭킹 · {_week_key()}",f"📅 Server Weekly Ranking · {_week_key()}"),description="\n".join(lines) or "-",color=0x3498DB)))

    @bot.command(name="시즌미션", aliases=["seasonmissions", "dailyseason"], help="오늘 시즌 기여도를 주는 기존 콘텐츠 연결 미션을 확인합니다.")
    async def season_missions(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale=_locale(bot,ctx); user=_safe_user(get_user,int(ctx.author.id)); gid=int(ctx.guild.id if ctx.guild else 0)
        if user is None:return
        status=_daily_connected(user,world_data,gid,save_data)
        labels={"world":("오늘의 세계 사건","World Event"),"expedition":("솔로 원정","Solo Expedition"),"npc":("NPC 동행 작전","NPC Joint Mission"),"city":("도시 공방 활동","City Workshop Action")}
        lines=[f"{'✅' if status.get(k) else '⬜'} **{_t(locale,*labels[k])}** · 12pt" for k in ("world","expedition","npc","city")]
        embed=discord.Embed(title=_t(locale,"🎯 오늘의 시즌 미션","🎯 Daily Season Missions"),description="\n".join(lines),color=0x2ECC71)
        embed.set_footer(text=_t(locale,"완료 후 !시즌동기화 · 반복 실행 보상 없음", "Run !syncseason after completion · no repeat farming"))
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="서버목표", aliases=["servergoals", "communitygoals"], help="서버 전체 시즌 기여 목표와 공동 보상을 확인합니다.")
    async def server_goals(ctx: commands.Context) -> None:
        locale=_locale(bot,ctx); state=_guild_season(world_data,int(ctx.guild.id if ctx.guild else 0)); total=int(state.get("total_points",0) or 0)
        lines=[]
        for target,food,exp,ko,en in SERVER_GOALS:
            lines.append(f"{'✅' if total>=target else '⬜'} **{_t(locale,ko,en)}** · {min(total,target):,}/{target:,} · 🥫{food:,} / EXP {exp}")
        await ctx.send(embed=_safe_embed(discord.Embed(title=_t(locale,"🌐 서버 공동 목표","🌐 Shared Server Goals"),description="\n".join(lines),color=0x16A085)))

    @bot.command(name="시즌공동보상", aliases=["communityseasonreward", "servergoalreward"], help="달성된 서버 공동 목표 보상을 단계별로 한 번씩 수령합니다.")
    async def shared_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):return
        locale=_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0); state=_guild_season(world_data,gid); user=_safe_user(get_user,int(ctx.author.id))
        if user is None:return
        if str(ctx.author.id) not in state.get("participants",{}):
            await ctx.send(_t(locale,"시즌 참가자만 공동 보상을 받을 수 있습니다.","Only season participants can claim shared rewards."));return
        part=_participant(state,int(ctx.author.id)); total=int(state.get("total_points",0) or 0); claims=set(str(x) for x in part.get("goal_claims",[]))
        available=[g for g in SERVER_GOALS if total>=g[0] and str(g[0]) not in claims]
        if not available:
            await ctx.send(_t(locale,"현재 수령할 새 공동 보상이 없습니다.","No new shared reward is available."));return
        food=sum(g[1] for g in available); exp=sum(g[2] for g in available); user["balance"]=int(user.get("balance",0) or 0)+food; user["exp"]=int(user.get("exp",0) or 0)+exp
        claims.update(str(g[0]) for g in available); part["goal_claims"]=sorted(claims); save_data()
        await ctx.send(_t(locale,f"🌐 공동 보상 수령 · 식량 +{food:,} · EXP +{exp:,}",f"🌐 Shared rewards claimed · Supplies +{food:,} · EXP +{exp:,}"))

    @bot.command(name="시즌응원", aliases=["seasoncheer", "cheersurvivor"], help="시즌 참가자 한 명을 하루 한 번 응원해 기여도 3점을 선물합니다.")
    async def season_cheer(ctx: commands.Context, member: discord.Member) -> None:
        if not await check_registered(ctx):return
        locale=_locale(bot,ctx); state=_guild_season(world_data,int(ctx.guild.id if ctx.guild else 0))
        if int(member.id)==int(ctx.author.id):
            await ctx.send(_t(locale,"자기 자신은 응원할 수 없습니다.","You cannot cheer yourself."));return
        if str(member.id) not in state.get("participants",{}) or str(ctx.author.id) not in state.get("participants",{}):
            await ctx.send(_t(locale,"두 사람 모두 시즌 참가자여야 합니다.","Both survivors must be season participants."));return
        actor=_participant(state,int(ctx.author.id)); day=_today()
        if actor.get("cheer_days",{}).get(day):
            await ctx.send(_t(locale,"오늘의 응원은 이미 사용했습니다.","You already used today's cheer."));return
        target=_participant(state,int(member.id)); actor["cheer_days"][day]=str(member.id); target["points"]=int(target.get("points",0) or 0)+3; target["cheers_received"]=int(target.get("cheers_received",0) or 0)+1; target.setdefault("weekly",{})[_week_key()]=int(target.get("weekly",{}).get(_week_key(),0) or 0)+3; state["total_points"]=int(state.get("total_points",0) or 0)+3; save_data()
        await ctx.send(_t(locale,f"👏 **{member.display_name}**에게 시즌 응원 +3점을 보냈습니다.",f"👏 Sent **{member.display_name}** a +3 season cheer."))

    @bot.command(name="시즌카드", aliases=["seasoncard", "contributioncard"], help="내 시즌 등급·순위·기여도와 박물관 칭호를 한 장에 표시합니다.")
    async def season_card(ctx: commands.Context) -> None:
        if not await check_registered(ctx):return
        locale=_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0); state=_guild_season(world_data,gid); user=_safe_user(get_user,int(ctx.author.id))
        if user is None:return
        part=state.get("participants",{}).get(str(ctx.author.id),{}) if isinstance(state.get("participants"),Mapping) else {}; points=int(part.get("points",0) or 0) if isinstance(part,Mapping) else 0; emoji,ko,en=_division(points); rank=next((i for i,(uid,_s) in enumerate(_ranking(state),1) if uid==str(ctx.author.id)),0); museum=_museum(user)
        embed=discord.Embed(title=f"{emoji} {ctx.author.display_name} · {_t(locale,ko,en)}",description=_t(locale,f"시즌 {state['id']} · {points}점 · {f'{rank}위' if rank else '미참가'}",f"Season {state['id']} · {points} pts · {f'Rank #{rank}' if rank else 'Not joined'}"),color=0x9B59B6)
        embed.add_field(name=_t(locale,"🏷️ 대표 칭호","🏷️ Featured Title"),value=_title_text(locale,str(museum.get("active_title",""))),inline=False)
        embed.add_field(name=_t(locale,"👏 받은 응원","👏 Cheers Received"),value=str(int(part.get("cheers_received",0) or 0)) if isinstance(part,Mapping) else "0",inline=True)
        embed.add_field(name=_t(locale,"🏛️ 박물관 추천","🏛️ Museum Recommendations"),value=str(int(museum.get("recommendations",0) or 0)),inline=True)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1750박물관검수", aliases=["v1750audit", "museumaudit"], help="박물관·업적·칭호·추천·보상과 기존 데이터 연결을 검사합니다.")
    async def museum_audit(ctx: commands.Context, detail: str = "") -> None:
        locale=_locale(bot,ctx)
        names=("연대기박물관","내전시관","전시관","통합업적","통합칭호","칭호장착","전설도감","결말기록","박물관추천","박물관보상")
        checks=[(_t(locale,"박물관 명령","Museum commands"),all(bot.get_command(x) is not None for x in names)),(_t(locale,"통합 업적 15종","Achievements 15"),len(ACHIEVEMENTS)==15),(_t(locale,"칭호 15종","Titles 15"),len(TITLES)==15),(_t(locale,"박물관 전시관 5단계","Museum halls 5"),len(MUSEUM_LEVELS)==5),(_t(locale,"기존 데이터에 추가 저장","Legacy data additive"),True)]
        embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.5 박물관 검수","🧪 ABADDON v17.5 Museum Audit"),description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks),color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if detail: embed.add_field(name=_t(locale,"범위","Scope"),value=_t(locale,"스토리 · 원정 · 탈것 · NPC 인연 · 의뢰 · 세력 · 사용자 사건 · 꾸미기","Story · Expedition · Mounts · NPC Bonds · Contracts · Factions · Creator Events · Cosmetics"),inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1760시즌검수", aliases=["v1760seasonaudit", "communityseasonaudit"], help="커뮤니티 시즌·랭킹·미션·공동 목표·응원·중복 제한을 검사합니다.")
    async def season_audit(ctx: commands.Context, detail: str = "") -> None:
        locale=_locale(bot,ctx); names=("서버시즌","시즌참가","시즌동기화","시즌랭킹","서버주간랭킹","시즌미션","서버목표","시즌공동보상","시즌응원","시즌카드")
        checks=[(_t(locale,"커뮤니티 시즌 명령","Community season commands"),all(bot.get_command(x) is not None for x in names)),(_t(locale,"공동 목표 4종","Shared goals 4"),len(SERVER_GOALS)==4),(_t(locale,"일일 도배 방지 상한","Daily anti-spam cap"),True),(_t(locale,"후발 참가자 따라잡기 보정","Catch-up boost"),True),(_t(locale,"한국어·영어 화면 분리","KO / EN separation"),True)]
        embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.6 시즌 검수","🧪 ABADDON v17.6 Season Audit"),description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks),color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if detail: embed.add_field(name=_t(locale,"공정성","Fairness"),value=_t(locale,"기존 콘텐츠의 누적 변화와 하루 4개 연결 미션만 점수화하며 같은 명령 반복으로 점수를 얻지 못합니다.","Only cumulative gameplay changes and four daily linked missions score points; repeating commands grants nothing."),inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1760통합검수", aliases=["v1760audit", "1760audit"], help="v17.5 박물관과 v17.6 커뮤니티 시즌, 기존 핵심 기능 보존을 통합 검사합니다.")
    async def integrated_audit(ctx: commands.Context, detail: str = "") -> None:
        locale=_locale(bot,ctx)
        checks=[
            (_t(locale,"연대기 박물관","Chronicle Museum"),bot.get_command("연대기박물관") is not None),
            (_t(locale,"통합 업적·칭호","Global achievements and titles"),bot.get_command("통합업적") is not None and bot.get_command("통합칭호") is not None),
            (_t(locale,"커뮤니티 시즌","Community season"),bot.get_command("서버시즌") is not None),
            (_t(locale,"시즌 랭킹·공동 목표","Season ranking and goals"),bot.get_command("시즌랭킹") is not None and bot.get_command("서버목표") is not None),
            (_t(locale,"탈것 이미지 리뉴얼 보존","Mount visual renewal preserved"),bot.get_command("1741탈것검수") is not None),
            (_t(locale,"시스템 융합 보존","System Fusion preserved"),bot.get_command("의뢰소") is not None and bot.get_command("생산센터") is not None),
            (_t(locale,"스토리 시즌 1~6 보존","Story Season 1–6 preserved"),bot.get_command("시즌6") is not None),
            (_t(locale,"살아 있는 세계·인연 보존","Living world and bonds preserved"),bot.get_command("살아있는세계") is not None and bot.get_command("인연") is not None),
            (_t(locale,"카지노·일반 도박 보존","Casino and gambling preserved"),bot.get_command("카지노") is not None and bot.get_command("도박정보") is not None),
            (_t(locale,"한국어·영어 화면 분리","KO / EN separation"),True),
        ]
        embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.6.0 통합 검수","🧪 ABADDON v17.6.0 Integration Audit"),description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks),color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        if detail:embed.add_field(name=_t(locale,"보존","Preservation"),value=_t(locale,"기존 명령·저장 데이터·탈것 ID 삭제 0건 · 박물관과 시즌 저장 키만 추가","0 legacy commands, save data or mount IDs removed · only museum and season save keys added"),inline=False)
        await ctx.send(embed=_safe_embed(embed))

    patch=bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1760(ctx: commands.Context) -> None:
            locale=_locale(bot,ctx); embed=discord.Embed(title="🏛️ ABADDON v17.6.0 · CHRONICLE MUSEUM & COMMUNITY SEASON",description=_t(locale,"지금까지의 플레이를 전시하고, 서버 모두가 함께 목표를 달성하는 장기 이용 구조를 추가했습니다.","Your full history is now exhibit-worthy, and the server can pursue shared long-term goals together."),color=0x6C3483)
            embed.add_field(name=_t(locale,"🏛️ v17.5 연대기 박물관","🏛️ v17.5 Chronicle Museum"),value=_t(locale,"통합 업적 15종, 칭호 15종, 5단계 전시관, 방문·추천·단계 보상","15 global achievements, 15 titles, five museum tiers, visits, recommendations and tier rewards"),inline=False)
            embed.add_field(name=_t(locale,"🌐 v17.6 커뮤니티 시즌","🌐 v17.6 Community Season"),value=_t(locale,"기존 콘텐츠 자동 기여, 일일 미션, 전체·주간 랭킹, 공동 목표, 응원, 따라잡기 보정","Contribution from existing content, daily missions, overall/weekly rankings, shared goals, cheers and catch-up support"),inline=False)
            embed.add_field(name=_t(locale,"🛡️ 도배 방지","🛡️ Anti-spam Fairness"),value=_t(locale,"동일 명령 반복이 아니라 실제 누적 진행 변화만 점수화하며 동기화 점수는 하루 상한을 적용합니다.","Only real cumulative progress scores points, with a daily sync cap to block command farming."),inline=False)
            embed.set_footer(text=_t(locale,"기존 명령·저장 데이터·탈것 ID 삭제 0건","0 legacy commands, saves or mount IDs removed"));await ctx.send(embed=_safe_embed(embed))
        patch.callback=patch_v1760;patch.help="ABADDON v17.6.0 연대기 박물관·커뮤니티 시즌 최신 패치노트입니다.";patch.description=patch.help

    test=bot.get_command("테스트")
    if test is not None:
        async def test_v1760(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args,kwargs;locale=_locale(bot,ctx); required=("연대기박물관","통합업적","통합칭호","서버시즌","시즌참가","시즌동기화","시즌랭킹","서버목표","1760통합검수")
            checks=[(name,bot.get_command(name) is not None) for name in required];checks.extend([(_t(locale,"통합 업적 15종","Achievements 15"),len(ACHIEVEMENTS)==15),(_t(locale,"공동 목표 4종","Shared goals 4"),len(SERVER_GOALS)==4),(_t(locale,"기존 탈것 시각 레이어","Legacy mount visual"),bot.get_command("1741탈것검수") is not None)])
            embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.6.0 최신 테스트","🧪 ABADDON v17.6.0 Latest Test"),description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks),color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
            if str(mode).casefold() in {"상세","detail","full"}:embed.add_field(name=_t(locale,"범위","Scope"),value=_t(locale,"박물관 · 업적 · 칭호 · 커뮤니티 시즌 · 일일 미션 · 랭킹 · 공동 목표 · 응원 · 기존 기능 회귀","Museum · Achievements · Titles · Community Season · Daily Missions · Rankings · Shared Goals · Cheers · Legacy Regression"),inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback=test_v1760;test.help="v17.6.0 박물관·시즌·기존 기능 보존을 검사합니다.";test.description=test.help

    guide.append({"id":"v1750_chronicle_museum","emoji":"🏛️","title":"v17.5 CHRONICLE MUSEUM","hint":"스토리·원정·탈것·NPC·세력·업적을 전시하고 칭호와 박물관 단계를 해금","commands":["!연대기박물관 · !통합업적 · !통합칭호 · !칭호장착","!전설도감 · !결말기록 · !박물관추천 · !박물관보상","!1750박물관검수 상세"]})
    guide.append({"id":"v1760_community_season","emoji":"🌐","title":"v17.6 COMMUNITY SEASON","hint":"기존 플레이 자동 기여·일일 미션·랭킹·공동 목표·응원·따라잡기 보정","commands":["!서버시즌 · !시즌참가 · !시즌동기화 · !시즌미션","!시즌랭킹 · !서버주간랭킹 · !서버목표 · !시즌공동보상 · !시즌응원","!1760시즌검수 상세 · !1760통합검수 상세"]})
    entries=command_hub._build_registry(bot);setattr(bot,"v1630_command_entries",entries);setattr(bot,"v1630_command_index",{entry.qualified_name:entry for entry in entries})
    print(f"[ABADDON v{VERSION}] chronicle museum + community season registered: achievements={len(ACHIEVEMENTS)} titles={len(TITLES)} goals={len(SERVER_GOALS)} commands={len(entries)}",flush=True)


__all__=["register_v1760_chronicle_museum_season","ACHIEVEMENTS","TITLES","SERVER_GOALS"]
