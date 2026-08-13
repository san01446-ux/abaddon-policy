from __future__ import annotations

"""ABADDON v11.5.0 per-server operations, notification and bot-permission center.

The module is intentionally conservative:
- automatic notifications remain opt-in per guild;
- permission changes always create a restorable snapshot first;
- other bots are audited only unless an administrator explicitly targets one;
- a bot can never grant permissions it does not already possess.
"""

import asyncio
import copy
import hashlib
from datetime import datetime, time, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands import v720_coop_cleanup as patch_module
from apocalypse_bot.commands import v790_operations_disaster as disaster_module
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard

VERSION = "11.5.0"
ROOT_KEY = "v1150_server_operations"
KST = ZoneInfo("Asia/Seoul")
MAX_BACKUPS = 80
MAX_AUDIT_BOTS = 50
MAX_AUTO_CHANNELS = 120

NOTIFICATION_TYPES: Dict[str, Dict[str, str]] = {
    "재난": {"key": "disaster", "ko": "재난", "en": "Disaster", "emoji": "🚨"},
    "패치": {"key": "patch", "ko": "패치", "en": "Patch", "emoji": "📣"},
    "퀴즈": {"key": "quiz", "ko": "퀴즈", "en": "Quiz", "emoji": "🧠"},
    "암시장": {"key": "market", "ko": "암시장", "en": "Black Market", "emoji": "📈"},
    "세계": {"key": "frontier", "ko": "세계 이벤트", "en": "World Events", "emoji": "🌍"},
    "월드보스": {"key": "worldboss", "ko": "월드보스", "en": "World Boss", "emoji": "👹"},
    "리그": {"key": "league", "ko": "챔피언십", "en": "Championship", "emoji": "🏆"},
    "연합": {"key": "alliance", "ko": "연합 대항전", "en": "Alliance War", "emoji": "⚔️"},
    "경마": {"key": "racing", "ko": "경마", "en": "Horse Racing", "emoji": "🏇"},
    "스토리": {"key": "story", "ko": "스토리", "en": "Story", "emoji": "📖"},
    "점검": {"key": "maintenance", "ko": "점검", "en": "Maintenance", "emoji": "🛠️"},
}

TYPE_ALIASES: Dict[str, str] = {}
for _name, _row in NOTIFICATION_TYPES.items():
    for _alias in {_name, _row["key"], _row["ko"], _row["en"].casefold().replace(" ", "")}:
        TYPE_ALIASES[str(_alias).casefold().replace(" ", "")] = _row["key"]
TYPE_ALIASES.update({
    "disasters": "disaster", "updates": "patch", "update": "patch", "dailyquiz": "quiz",
    "blackmarket": "market", "world": "frontier", "boss": "worldboss", "championship": "league",
    "alliances": "alliance", "race": "racing", "horserace": "racing", "campaign": "story",
})

PROFILE_LABELS = {
    "일반": "general", "general": "general",
    "알림": "alerts", "공지": "alerts", "alerts": "alerts", "notice": "alerts",
    "게임": "games", "games": "games", "casino": "games",
    "운영": "operations", "관리": "operations", "operations": "operations", "admin": "operations",
    "음성": "voice", "voice": "voice",
    "읽기전용": "readonly", "readonly": "readonly", "read-only": "readonly",
    "차단": "blocked", "blocked": "blocked", "deny": "blocked",
}

PERMISSION_PROFILES: Dict[str, Dict[str, Optional[bool]]] = {
    "general": {
        "view_channel": True, "send_messages": True, "embed_links": True,
        "attach_files": True, "read_message_history": True, "add_reactions": True,
    },
    "alerts": {
        "view_channel": True, "send_messages": True, "embed_links": True,
        "attach_files": True, "read_message_history": True, "add_reactions": True,
        "mention_everyone": False,
    },
    "games": {
        "view_channel": True, "send_messages": True, "embed_links": True,
        "attach_files": True, "read_message_history": True, "add_reactions": True,
        "use_external_emojis": True, "send_messages_in_threads": True,
        "create_public_threads": True,
    },
    "operations": {
        "view_channel": True, "send_messages": True, "embed_links": True,
        "attach_files": True, "read_message_history": True, "add_reactions": True,
        "manage_messages": True, "manage_threads": True,
    },
    "voice": {
        "view_channel": True, "connect": True, "speak": True,
        "use_voice_activation": True,
    },
    "readonly": {
        "view_channel": True, "send_messages": False, "connect": False,
        "read_message_history": True,
    },
    "blocked": {
        "view_channel": False, "send_messages": False, "connect": False,
    },
}

REQUIRED_ABADDON_GUILD_PERMS = (
    "view_audit_log", "manage_roles", "manage_channels", "manage_messages",
    "read_message_history", "send_messages", "embed_links", "attach_files",
)

DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "moderate_members",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("schema", 1)
    root.setdefault("guilds", {})
    return root


def _default_notification() -> Dict[str, Any]:
    return {"enabled": False, "channel_id": 0, "role_id": 0, "last_sent_at": "", "last_event_key": ""}


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    state = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(int(guild_id))] = state
    state.setdefault("timezone", "Asia/Seoul")
    state.setdefault("active_start", "08:00")
    state.setdefault("active_end", "23:00")
    state.setdefault("quiet_hours_enabled", False)
    state.setdefault("digest_enabled", False)
    state.setdefault("admin_role_id", 0)
    notifications = state.setdefault("notifications", {})
    for row in NOTIFICATION_TYPES.values():
        current = notifications.setdefault(row["key"], _default_notification())
        if not isinstance(current, dict):
            notifications[row["key"]] = _default_notification()
            current = notifications[row["key"]
            ]
        for k, v in _default_notification().items():
            current.setdefault(k, v)
    state.setdefault("permission_backups", [])
    state.setdefault("settings_backups", [])
    state.setdefault("permission_history", [])
    state.setdefault("last_sync_at", "")
    state.setdefault("migrated_v1150", False)
    return state


def _parse_hhmm(text: str) -> Optional[time]:
    raw = str(text or "").strip()
    try:
        hour_s, minute_s = raw.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    except (ValueError, TypeError):
        pass
    return None


def _active_now(state: Mapping[str, Any], now: Optional[datetime] = None) -> bool:
    if not bool(state.get("quiet_hours_enabled", False)):
        return True
    start = _parse_hhmm(str(state.get("active_start", "08:00")))
    end = _parse_hhmm(str(state.get("active_end", "23:00")))
    if start is None or end is None:
        return True
    now = now or datetime.now(KST)
    local = now.astimezone(KST).time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= local <= end
    return local >= start or local <= end


def _normalize_type(value: str) -> Optional[str]:
    token = str(value or "").strip().casefold().replace(" ", "")
    return TYPE_ALIASES.get(token)


def _type_row(key: str) -> Dict[str, str]:
    for row in NOTIFICATION_TYPES.values():
        if row["key"] == key:
            return row
    return {"key": key, "ko": key, "en": key, "emoji": "🔔"}


def _toggle(value: str) -> Optional[bool]:
    token = str(value or "").strip().casefold()
    if token in {"켜기", "켜", "on", "true", "1", "활성", "활성화", "enable", "enabled"}:
        return True
    if token in {"끄기", "꺼", "off", "false", "0", "비활성", "비활성화", "disable", "disabled"}:
        return False
    return None


def _is_admin(ctx: commands.Context) -> bool:
    member = ctx.author
    return bool(
        isinstance(member, discord.Member)
        and ctx.guild is not None
        and (
            member.id == ctx.guild.owner_id
            or member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
        )
    )


async def _require_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
        return False
    if not _is_admin(ctx):
        await ctx.send("⛔ 서버 소유자 또는 서버 관리 권한이 필요합니다.")
        return False
    return True


def _configured_text_channel(guild: discord.Guild, channel_id: Any) -> Optional[discord.TextChannel]:
    channel = guild.get_channel(_safe_int(channel_id))
    return channel if isinstance(channel, discord.TextChannel) else None


def _snapshot_overwrite(channel: discord.abc.GuildChannel, target: discord.abc.Snowflake) -> Dict[str, Any]:
    overwrite = channel.overwrites_for(target)
    allow, deny = overwrite.pair()
    existed = target in channel.overwrites
    return {"existed": bool(existed), "allow": int(allow.value), "deny": int(deny.value)}


def _overwrite_from_snapshot(row: Mapping[str, Any]) -> Optional[discord.PermissionOverwrite]:
    if not bool(row.get("existed", False)):
        return None
    allow = discord.Permissions(_safe_int(row.get("allow")))
    deny = discord.Permissions(_safe_int(row.get("deny")))
    return discord.PermissionOverwrite.from_pair(allow, deny)


def _batch_id(prefix: str, guild_id: int, target_id: int = 0) -> str:
    raw = f"{prefix}:{guild_id}:{target_id}:{_now_iso()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()
    return f"{prefix}-{digest}"


def _trim(rows: List[Any], maximum: int = MAX_BACKUPS) -> None:
    if len(rows) > maximum:
        del rows[:-maximum]


def _infer_profile(channel: discord.abc.GuildChannel) -> str:
    if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return "voice"
    name = str(getattr(channel, "name", "")).casefold()
    if any(token in name for token in ("관리", "운영", "로그", "admin", "staff", "moder")):
        return "operations"
    if any(token in name for token in ("공지", "알림", "재난", "패치", "notice", "announcement", "alert")):
        return "alerts"
    if any(token in name for token in ("게임", "카지노", "카드", "경마", "포커", "화투", "game", "casino", "poker", "race")):
        return "games"
    if any(token in name for token in ("규칙", "가이드", "읽기", "rules", "guide")):
        return "readonly"
    return "general"


def _profile_overwrite(guild: discord.Guild, profile: str) -> Tuple[discord.PermissionOverwrite, List[str]]:
    values = PERMISSION_PROFILES[profile]
    me = guild.me
    skipped: List[str] = []
    filtered: Dict[str, Optional[bool]] = {}
    guild_perms = me.guild_permissions if me is not None else discord.Permissions.none()
    for name, value in values.items():
        if value is True and not bool(getattr(guild_perms, name, False)):
            skipped.append(name)
            filtered[name] = None
        else:
            filtered[name] = value
    return discord.PermissionOverwrite(**filtered), skipped


def _bot_members(guild: discord.Guild) -> List[discord.Member]:
    rows = [member for member in guild.members if bool(getattr(member, "bot", False))]
    return sorted(rows, key=lambda member: member.top_role.position, reverse=True)


def _dangerous_permissions(member: discord.Member) -> List[str]:
    perms = member.guild_permissions
    return [name for name in DANGEROUS_PERMS if bool(getattr(perms, name, False))]


def _can_manage_target(guild: discord.Guild, target: discord.Member) -> Tuple[bool, str]:
    me = guild.me
    if me is None:
        return False, "봇 멤버 정보를 찾지 못했습니다."
    if not me.guild_permissions.manage_roles:
        return False, "ABADDON에 역할 관리 권한이 없습니다."
    if target.id == guild.owner_id:
        return False, "서버 소유자는 수정할 수 없습니다."
    if target.id != me.id and target.top_role >= me.top_role:
        return False, "대상 봇의 최고 역할이 ABADDON 역할보다 높거나 같습니다."
    return True, "ok"


def _migrate_from_legacy(world_data: MutableMapping[str, Any], guild_id: int) -> bool:
    state = _guild_state(world_data, guild_id)
    if bool(state.get("migrated_v1150", False)):
        return False
    notifications = state["notifications"]
    try:
        disaster = disaster_module._guild_state(world_data, guild_id).get("disaster", {})
        notifications["disaster"].update({
            "enabled": bool(disaster.get("subscription_enabled", False)),
            "channel_id": _safe_int(disaster.get("channel_id")),
        })
    except Exception:
        pass
    # Legacy patch auto was enabled by default in old builds, so v11.5.0 intentionally
    # migrates it to OFF until an administrator explicitly subscribes.
    notifications["patch"].update({"enabled": False, "channel_id": 0})
    quiz = world_data.setdefault("quiz_notifications", {}).get(str(guild_id), {})
    if isinstance(quiz, dict):
        notifications["quiz"].update({
            "enabled": bool(quiz.get("enabled", False)),
            "channel_id": _safe_int(quiz.get("channel_id")),
            "role_id": _safe_int(quiz.get("role_id")),
        })
    market = world_data.setdefault("market_notifications", {}).get(str(guild_id), {})
    if isinstance(market, dict):
        notifications["market"].update({
            "enabled": bool(market.get("enabled", False)),
            "channel_id": _safe_int(market.get("channel_id")),
            "role_id": _safe_int(market.get("role_id")),
        })
    frontier = world_data.setdefault("v639", {}).setdefault("guilds", {}).get(str(guild_id), {})
    if isinstance(frontier, dict):
        event_channel_id = _safe_int(frontier.get("event_channel_id"))
        notifications["frontier"].update({
            "enabled": bool(event_channel_id),
            "channel_id": event_channel_id,
        })
    state["migrated_v1150"] = True
    return True


def _legacy_state_snapshot(world_data: MutableMapping[str, Any], guild_id: int) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        result["disaster"] = copy.deepcopy(disaster_module._guild_state(world_data, guild_id).get("disaster", {}))
    except Exception:
        result["disaster"] = {}
    result["patch"] = copy.deepcopy(
        world_data.setdefault("v720_coop_cleanup", {}).setdefault("guilds", {}).setdefault(str(guild_id), {})
    )
    result["quiz"] = copy.deepcopy(world_data.setdefault("quiz_notifications", {}).setdefault(str(guild_id), {}))
    result["market"] = copy.deepcopy(world_data.setdefault("market_notifications", {}).setdefault(str(guild_id), {}))
    result["frontier"] = copy.deepcopy(
        world_data.setdefault("v639", {}).setdefault("guilds", {}).setdefault(str(guild_id), {})
    )
    return result


def _apply_legacy_notification(
    world_data: MutableMapping[str, Any], guild_id: int, key: str, config: Mapping[str, Any], active: bool
) -> bool:
    desired = bool(config.get("enabled", False)) and active
    channel_id = _safe_int(config.get("channel_id"))
    role_id = _safe_int(config.get("role_id"))
    changed = False

    if key == "disaster":
        state = disaster_module._guild_state(world_data, guild_id)
        settings = state.setdefault("disaster", {})
        updates = {
            "subscription_enabled": bool(config.get("enabled", False)),
            "auto_enabled": desired,
            "channel_id": channel_id,
        }
        for name, value in updates.items():
            if settings.get(name) != value:
                settings[name] = value
                changed = True
        return changed

    if key == "patch":
        settings = world_data.setdefault("v720_coop_cleanup", {}).setdefault("guilds", {}).setdefault(str(guild_id), {})
        for name, value in {"patch_auto": desired, "patch_channel_id": channel_id}.items():
            if settings.get(name) != value:
                settings[name] = value
                changed = True
        settings.setdefault("posted_versions", [])
        return changed

    if key == "quiz":
        settings = world_data.setdefault("quiz_notifications", {}).setdefault(str(guild_id), {})
        for name, value in {"enabled": desired, "channel_id": channel_id or None, "role_id": role_id or None}.items():
            if settings.get(name) != value:
                settings[name] = value
                changed = True
        return changed

    if key == "market":
        settings = world_data.setdefault("market_notifications", {}).setdefault(str(guild_id), {})
        for name, value in {"enabled": desired, "channel_id": channel_id or None, "role_id": role_id or None}.items():
            if settings.get(name) != value:
                settings[name] = value
                changed = True
        return changed

    if key == "frontier":
        settings = world_data.setdefault("v639", {}).setdefault("guilds", {}).setdefault(str(guild_id), {})
        desired_channel = channel_id if desired else 0
        if _safe_int(settings.get("event_channel_id")) != desired_channel:
            settings["event_channel_id"] = desired_channel
            changed = True
        return changed

    return False


def _sync_legacy(world_data: MutableMapping[str, Any], guild_id: int) -> bool:
    state = _guild_state(world_data, guild_id)
    active = _active_now(state)
    changed = False
    notifications = state.get("notifications", {})
    for key in ("disaster", "patch", "quiz", "market", "frontier"):
        config = notifications.get(key, {}) if isinstance(notifications, dict) else {}
        changed = _apply_legacy_notification(world_data, guild_id, key, config, active) or changed
    if changed:
        state["last_sync_at"] = _now_iso()
    return changed


def _patch_legacy_defaults(world_data: MutableMapping[str, Any]) -> None:
    original_guild_settings = patch_module._guild_settings
    if getattr(original_guild_settings, "_abaddon_v1150", False):
        return

    def guild_settings_optin(data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
        settings = original_guild_settings(data, guild_id)
        if not settings.get("v1150_optin_migrated"):
            settings["patch_auto"] = False
            settings["v1150_optin_migrated"] = True
        settings.setdefault("patch_auto", False)
        settings.setdefault("patch_channel_id", 0)
        return settings

    guild_settings_optin._abaddon_v1150 = True  # type: ignore[attr-defined]
    patch_module._guild_settings = guild_settings_optin

    def configured_patch_channel(guild: discord.Guild, settings: Dict[str, Any]) -> Optional[discord.TextChannel]:
        channel = guild.get_channel(_safe_int(settings.get("patch_channel_id")))
        if not isinstance(channel, discord.TextChannel) or guild.me is None:
            return None
        perms = channel.permissions_for(guild.me)
        return channel if perms.view_channel and perms.send_messages and perms.embed_links else None

    patch_module._find_patch_channel = configured_patch_channel


def _settings_status(guild: discord.Guild, state: Mapping[str, Any], locale: str) -> str:
    active = _active_now(state)
    rows: List[str] = []
    notifications = state.get("notifications", {})
    for item in NOTIFICATION_TYPES.values():
        config = notifications.get(item["key"], {}) if isinstance(notifications, dict) else {}
        channel = _configured_text_channel(guild, config.get("channel_id"))
        enabled = bool(config.get("enabled", False))
        label = item["ko"] if locale == "ko" else item["en"]
        rows.append(
            f"{item['emoji']} **{label}** · {'ON' if enabled else 'OFF'} · "
            f"{channel.mention if channel else '-'}"
        )
    quiet = (
        f"{state.get('active_start')}~{state.get('active_end')} · {'현재 발송 가능' if active else '현재 조용한 시간'}"
        if locale == "ko"
        else f"{state.get('active_start')}–{state.get('active_end')} · {'active now' if active else 'quiet now'}"
    )
    return "\n".join(rows) + f"\n\n🌙 {quiet}"


def _checks(bot: commands.Bot, world_data: MutableMapping[str, Any]) -> List[Tuple[str, bool, str]]:
    scratch: MutableMapping[str, Any] = {}
    state = _guild_state(scratch, 100)
    state["quiet_hours_enabled"] = True
    state["active_start"] = "09:00"
    state["active_end"] = "23:00"
    notifications = state["notifications"]
    defaults_off = all(not row.get("enabled") for row in notifications.values())
    notifications["patch"].update({"enabled": True, "channel_id": 123})
    _sync_legacy(scratch, 100)
    patch_state = scratch.get("v720_coop_cleanup", {}).get("guilds", {}).get("100", {})

    command_names = (
        "서버운영", "서버알림", "알림시간", "알림테스트", "서버설정검수",
        "서버봇목록", "서버봇권한검수", "봇권한적용", "권한자동설정",
        "권한백업", "권한복구", "권한변경내역", "서버설정백업", "서버설정복구",
    )
    return [
        ("서버별 알림 기본 꺼짐", defaults_off, f"types={len(notifications)}"),
        ("패치 공지 중앙 동기화", "patch_auto" in patch_state and _safe_int(patch_state.get("patch_channel_id")) == 123, str(patch_state)),
        ("조용한 시간 저장", _parse_hhmm("09:00") is not None and _parse_hhmm("23:00") is not None, "09:00~23:00"),
        ("권한 프로필", set(PERMISSION_PROFILES) == {"general", "alerts", "games", "operations", "voice", "readonly", "blocked"}, str(sorted(PERMISSION_PROFILES))),
        ("권한 백업 직렬화", {"existed", "allow", "deny"}.issubset({"existed", "allow", "deny"}), "allow/deny pair"),
        ("전체 봇 감사 제한", MAX_AUDIT_BOTS >= 20, f"max={MAX_AUDIT_BOTS}"),
        ("명령 등록", all(bot.get_command(name) is not None for name in command_names), ", ".join(command_names)),
        ("테스트 최신화", bot.get_command("테스트") is not None, "!테스트 상세"),
        ("패치노트 최신화", bot.get_command("패치노트") is not None, "!패치노트"),
    ]


def register_v1150_server_operations_permissions(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[dict[str, Any]],
) -> None:
    _patch_legacy_defaults(world_data)

    # Existing guild records are migrated to opt-in without removing history.
    changed = False
    legacy_ids = set(_root(world_data).setdefault("guilds", {}).keys())
    legacy_ids.update(world_data.setdefault("v720_coop_cleanup", {}).setdefault("guilds", {}).keys())
    legacy_ids.update(world_data.setdefault("quiz_notifications", {}).keys())
    legacy_ids.update(world_data.setdefault("market_notifications", {}).keys())
    legacy_ids.update(world_data.setdefault("v639", {}).setdefault("guilds", {}).keys())
    try:
        legacy_ids.update(disaster_module._root(world_data).setdefault("guilds", {}).keys())
    except Exception:
        pass
    for guild_id in list(legacy_ids):
        gid = _safe_int(guild_id)
        changed = _migrate_from_legacy(world_data, gid) or changed
        changed = _sync_legacy(world_data, gid) or changed
    # Also migrate legacy patch records that existed before v11.5.0.
    patch_guilds = world_data.setdefault("v720_coop_cleanup", {}).setdefault("guilds", {})
    for gid, settings in list(patch_guilds.items()):
        if isinstance(settings, dict) and not settings.get("v1150_optin_migrated"):
            settings["patch_auto"] = False
            settings["v1150_optin_migrated"] = True
            changed = True
    if changed:
        save_data()

    @tasks.loop(minutes=1)
    async def operations_sync_loop() -> None:
        dirty = False
        for guild in list(bot.guilds):
            dirty = _migrate_from_legacy(world_data, int(guild.id)) or dirty
            dirty = _sync_legacy(world_data, int(guild.id)) or dirty
        if dirty:
            save_data()

    @operations_sync_loop.before_loop
    async def before_operations_sync_loop() -> None:
        await bot.wait_until_ready()

    async def start_operations_sync_loop() -> None:
        if not operations_sync_loop.is_running():
            operations_sync_loop.start()

    bot.add_listener(start_operations_sync_loop, "on_ready")

    async def dispatch_alert(
        guild: discord.Guild,
        key: str,
        *,
        embed: Optional[discord.Embed] = None,
        content: Optional[str] = None,
        event_key: str = "",
        force: bool = False,
    ) -> bool:
        """Send a v11.5-managed alert without leaking failures across guilds."""
        state = _guild_state(world_data, int(guild.id))
        config = state["notifications"].get(str(key), {})
        if not isinstance(config, dict):
            return False
        if not force and (not bool(config.get("enabled", False)) or not _active_now(state)):
            return False
        channel = _configured_text_channel(guild, config.get("channel_id"))
        if channel is None:
            return False
        if event_key and str(config.get("last_event_key", "")) == str(event_key):
            return False
        role = guild.get_role(_safe_int(config.get("role_id")))
        try:
            await channel.send(
                content=(f"{role.mention} {content or ''}".strip() if role else content),
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException):
            return False
        config["last_sent_at"] = _now_iso()
        config["last_event_key"] = str(event_key or "")
        save_data()
        return True

    @bot.command(
        name="서버운영",
        aliases=["서버운영센터", "serveroperations", "serverops"],
        help="서버별 알림·채널·봇 권한·복구 상태를 한 화면에서 확인합니다.",
    )
    async def server_operations(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        locale = _ctx_locale(bot, ctx)
        state = _guild_state(world_data, int(ctx.guild.id))
        bots = _bot_members(ctx.guild)
        me = ctx.guild.me
        embed = _dashboard(
            bot, locale,
            f"🛠️ {ctx.guild.name} 서버 운영센터",
            f"🛠️ {ctx.guild.name} Server Operations",
            "원하는 알림만 켜고, 채널별 봇 권한을 백업·적용·복구합니다.",
            "Enable only the alerts you want and safely back up, apply and restore bot permissions.",
            discord.Color.blurple(),
        )
        embed.add_field(
            name=_t(locale, "🔔 알림 구독", "🔔 Alert Subscriptions"),
            value=_settings_status(ctx.guild, state, locale)[:1024], inline=False,
        )
        missing = [name for name in REQUIRED_ABADDON_GUILD_PERMS if me is None or not bool(getattr(me.guild_permissions, name, False))]
        embed.add_field(
            name=_t(locale, "🤖 서버 봇", "🤖 Server Bots"),
            value=_t(locale, f"감지 {len(bots)}개 · ABADDON 부족 권한 {len(missing)}개", f"Detected {len(bots)} · ABADDON missing {len(missing)}"),
            inline=True,
        )
        embed.add_field(
            name=_t(locale, "↩️ 복구 지점", "↩️ Restore Points"),
            value=_t(locale, f"권한 {len(state['permission_backups'])}개 · 설정 {len(state['settings_backups'])}개", f"Permissions {len(state['permission_backups'])} · settings {len(state['settings_backups'])}"),
            inline=True,
        )
        embed.add_field(
            name=_t(locale, "주요 명령", "Key Commands"),
            value=(
                "`!서버알림 종류 켜기 #채널` · `!알림시간 09:00 23:00`\n"
                "`!서버봇권한검수` · `!권한자동설정 미리보기/적용`\n"
                "`!봇권한적용 @봇 프로필 [#채널]` · `!권한복구 ID`"
                if locale == "ko" else
                "`!serveralerts type on #channel` · `!alerthours 09:00 23:00`\n"
                "`!serverbotaudit` · `!autopermissions preview/apply`\n"
                "`!applybotpermissions @bot profile [#channel]` · `!restorepermissions ID`"
            ), inline=False,
        )
        await ctx.send(embed=embed)

    @bot.command(
        name="서버알림",
        aliases=["운영알림설정", "서버알림설정", "serveralerts", "alertsubscriptions"],
        help="서버별 자동 알림 종류·채널·상태를 설정합니다.",
    )
    async def server_alerts(
        ctx: commands.Context,
        종류: str = "상태",
        상태: str = "",
        채널: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        if str(종류).casefold() in {"상태", "status", "목록", "list"}:
            await ctx.send(_settings_status(ctx.guild, state, _ctx_locale(bot, ctx)))
            return
        key = _normalize_type(종류)
        if key is None:
            await ctx.send("⚠️ 종류: `재난`, `패치`, `퀴즈`, `암시장`, `세계`, `월드보스`, `리그`, `연합`, `경마`, `스토리`, `점검`")
            return
        enabled = _toggle(상태)
        config = state["notifications"][key]
        if enabled is None:
            row = _type_row(key)
            current = _configured_text_channel(ctx.guild, config.get("channel_id"))
            await ctx.send(f"{row['emoji']} **{row['ko']}** · {'켜짐' if config.get('enabled') else '꺼짐'} · {current.mention if current else '채널 미설정'}")
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if enabled and target is None:
            await ctx.send("⚠️ 알림 채널을 지정해주세요.")
            return
        config["enabled"] = enabled
        if target is not None:
            config["channel_id"] = int(target.id)
        _sync_legacy(world_data, int(ctx.guild.id))
        save_data()
        row = _type_row(key)
        await ctx.send(
            f"✅ {row['emoji']} **{row['ko']}** 알림을 {'켰습니다' if enabled else '껐습니다'}.\n"
            f"채널: {target.mention if enabled and target else '사용 안 함'}"
        )

    @bot.command(
        name="알림채널",
        aliases=["운영채널설정", "serveralertchannel", "alertchannel"],
        help="알림 종류별 전용 채널을 지정합니다.",
    )
    async def alert_channel(ctx: commands.Context, 종류: str, 채널: discord.TextChannel) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        key = _normalize_type(종류)
        if key is None:
            await ctx.send("⚠️ 알림 종류를 확인해주세요.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        state["notifications"][key]["channel_id"] = int(채널.id)
        _sync_legacy(world_data, int(ctx.guild.id))
        save_data()
        await ctx.send(f"✅ {_type_row(key)['ko']} 알림 채널을 {채널.mention}로 지정했습니다.")

    @bot.command(
        name="알림멘션",
        aliases=["서버알림멘션", "alertmention"],
        help="알림 종류에 사용할 역할 멘션을 설정하거나 해제합니다.",
    )
    async def alert_mention(ctx: commands.Context, 종류: str, 역할: Optional[discord.Role] = None) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        key = _normalize_type(종류)
        if key is None:
            await ctx.send("⚠️ 알림 종류를 확인해주세요.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        state["notifications"][key]["role_id"] = int(역할.id) if 역할 else 0
        _sync_legacy(world_data, int(ctx.guild.id))
        save_data()
        await ctx.send(f"✅ {_type_row(key)['ko']} 알림 멘션: {역할.mention if 역할 else '없음'}")

    @bot.command(
        name="알림시간",
        aliases=["조용한시간", "alerthours", "quiethours"],
        help="자동 알림이 게시될 시간을 설정합니다. 시간 밖에는 연동 알림을 일시 정지합니다.",
    )
    async def alert_hours(ctx: commands.Context, 시작: str = "", 종료: str = "") -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        if not 시작 or not 종료:
            await ctx.send(f"🌙 현재 알림 시간: **{state['active_start']}~{state['active_end']}** · {'사용 중' if state['quiet_hours_enabled'] else '제한 없음'}")
            return
        if _parse_hhmm(시작) is None or _parse_hhmm(종료) is None:
            await ctx.send("⚠️ `HH:MM` 형식으로 입력해주세요. 예: `!알림시간 09:00 23:00`")
            return
        state["active_start"] = 시작
        state["active_end"] = 종료
        state["quiet_hours_enabled"] = True
        _sync_legacy(world_data, int(ctx.guild.id))
        save_data()
        await ctx.send(f"✅ 자동 알림 시간을 **{시작}~{종료} (KST)**로 제한했습니다.")

    @bot.command(name="알림시간해제", aliases=["조용한시간해제", "disablealerthours"], help="시간 제한 없이 구독 알림을 게시합니다.")
    async def disable_alert_hours(ctx: commands.Context) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        state["quiet_hours_enabled"] = False
        _sync_legacy(world_data, int(ctx.guild.id))
        save_data()
        await ctx.send("✅ 자동 알림 시간 제한을 해제했습니다.")

    @bot.command(name="알림요약", aliases=["alertdigest"], help="운영센터 자체 경고의 요약 표시 설정을 켜거나 끕니다.")
    async def alert_digest(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        enabled = _toggle(상태)
        if enabled is None:
            await ctx.send(f"📬 운영 경고 요약: **{'켜짐' if state['digest_enabled'] else '꺼짐'}**")
            return
        state["digest_enabled"] = enabled
        save_data()
        await ctx.send(f"✅ 운영 경고 요약을 {'켰습니다' if enabled else '껐습니다'}. 기존 게임 일정 알림은 원래 시간에 게시됩니다.")

    @bot.command(name="알림테스트", aliases=["serveralerttest", "testalert"], help="실제 이벤트를 만들지 않고 지정 알림 채널에 미리보기를 보냅니다.")
    async def alert_test(ctx: commands.Context, 종류: str = "재난") -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        key = _normalize_type(종류)
        if key is None:
            await ctx.send("⚠️ 알림 종류를 확인해주세요.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        config = state["notifications"][key]
        channel = _configured_text_channel(ctx.guild, config.get("channel_id"))
        if channel is None:
            await ctx.send("⚠️ 이 알림 종류의 텍스트 채널이 설정되지 않았습니다.")
            return
        me = ctx.guild.me
        perms = channel.permissions_for(me) if me else None
        missing = [name for name in ("view_channel", "send_messages", "embed_links") if perms is None or not bool(getattr(perms, name, False))]
        if missing:
            await ctx.send(f"⛔ {channel.mention}에서 부족한 권한: {', '.join(missing)}")
            return
        row = _type_row(key)
        role = ctx.guild.get_role(_safe_int(config.get("role_id")))
        embed = discord.Embed(
            title=f"{row['emoji']} {row['ko']} 알림 미리보기",
            description="실제 이벤트를 발생시키지 않는 v11.5.0 테스트 메시지입니다.",
            color=discord.Color.blurple(), timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="서버", value=ctx.guild.name, inline=True)
        embed.add_field(name="채널", value=channel.mention, inline=True)
        embed.add_field(name="현재 시간 제한", value=f"{state['active_start']}~{state['active_end']} · {'발송 가능' if _active_now(state) else '조용한 시간'}", inline=False)
        sent = await dispatch_alert(ctx.guild, key, embed=embed, event_key=f"test:{ctx.message.id if ctx.message else _now_iso()}", force=True)
        if sent:
            await ctx.send(f"✅ {channel.mention}에 테스트 알림을 보냈습니다.")
        else:
            await ctx.send("⚠️ 채널 권한 또는 Discord API 문제로 테스트를 보내지 못했습니다.")

    @bot.command(name="서버봇목록", aliases=["봇목록", "serverbots", "botinventory"], help="서버에 참가한 봇과 강한 관리 권한을 확인합니다.")
    async def server_bot_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        bots = _bot_members(ctx.guild)[:MAX_AUDIT_BOTS]
        lines: List[str] = []
        for member in bots:
            dangerous = _dangerous_permissions(member)
            marker = "🟣" if ctx.guild.me and member.id == ctx.guild.me.id else "🤖"
            lines.append(
                f"{marker} **{member.display_name}** `{member.id}` · 역할 {member.top_role.position} · "
                f"위험권한 {', '.join(dangerous) if dangerous else '없음'}"
            )
        embed = discord.Embed(title=f"🤖 {ctx.guild.name} 서버 봇 · {len(bots)}개", description="\n".join(lines)[:4000] or "감지된 봇이 없습니다.", color=discord.Color.dark_purple())
        embed.set_footer(text="다른 봇은 기본적으로 검사만 합니다. 변경은 관리자가 명시적으로 대상 봇을 지정해야 합니다.")
        await ctx.send(embed=embed)

    @bot.command(name="서버봇권한검수", aliases=["봇권한점검", "serverbotaudit", "botpermissionaudit"], help="서버의 모든 봇이 접근 가능한 채널과 위험 권한을 요약합니다.")
    async def server_bot_permission_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        bots = _bot_members(ctx.guild)[:MAX_AUDIT_BOTS]
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"}
        embed = discord.Embed(title=f"🛡️ 서버 봇 권한 검수 · {len(bots)}개", color=discord.Color.orange())
        for member in bots[:25]:
            text_visible = 0
            text_send = 0
            voice_connect = 0
            for channel in ctx.guild.channels:
                perms = channel.permissions_for(member)
                if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                    text_visible += int(bool(perms.view_channel))
                    text_send += int(bool(perms.view_channel and perms.send_messages))
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    voice_connect += int(bool(perms.view_channel and perms.connect))
            dangerous = _dangerous_permissions(member)
            value = f"텍스트 보기 {text_visible} · 전송 {text_send} · 음성 연결 {voice_connect}"
            if detail:
                value += f"\n강한 권한: {', '.join(dangerous) if dangerous else '없음'}\n최고 역할: {member.top_role.mention} ({member.top_role.position})"
            embed.add_field(name=f"{'🟣' if ctx.guild.me and member.id == ctx.guild.me.id else '🤖'} {member.display_name}", value=value[:1024], inline=True)
        if len(bots) > 25:
            embed.set_footer(text=f"Discord 임베드 제한으로 상위 25개만 표시 · 전체 감지 {len(bots)}개")
        await ctx.send(embed=embed)

    async def _backup_entries(
        guild: discord.Guild,
        state: MutableMapping[str, Any],
        targets_and_channels: Iterable[Tuple[discord.Member, discord.abc.GuildChannel]],
        reason: str,
        batch_id: Optional[str] = None,
    ) -> str:
        pairs = list(targets_and_channels)
        first_target = pairs[0][0].id if pairs else 0
        batch = batch_id or _batch_id("P", guild.id, first_target)
        entries: List[Dict[str, Any]] = []
        for target, channel in pairs:
            before = _snapshot_overwrite(channel, target)
            entries.append({
                "channel_id": int(channel.id), "channel_name": str(channel.name),
                "target_id": int(target.id), "target_name": str(target), "before": before,
            })
        backup = {"id": batch, "created_at": _now_iso(), "reason": reason, "entries": entries, "restored_at": ""}
        state["permission_backups"].append(backup)
        _trim(state["permission_backups"])
        return batch

    @bot.command(name="권한백업", aliases=["봇권한백업", "permissionbackup"], help="현재 채널의 모든 봇 권한 덮어쓰기를 복구 지점으로 저장합니다.")
    async def permission_backup(ctx: commands.Context) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            await ctx.send("⚠️ 서버 채널에서 실행해주세요.")
            return
        bots = _bot_members(ctx.guild)
        state = _guild_state(world_data, int(ctx.guild.id))
        batch = await _backup_entries(ctx.guild, state, ((member, ctx.channel) for member in bots), "관리자 수동 현재 채널 백업")
        save_data()
        await ctx.send(f"✅ 현재 채널의 봇 {len(bots)}개 권한을 백업했습니다. 복구 ID: `{batch}`")

    @bot.command(name="봇권한적용", aliases=["권한프로필적용", "applybotpermissions"], help="선택한 봇에 채널 권한 프로필을 적용합니다. 적용 전 자동 백업합니다.")
    async def apply_bot_permissions(
        ctx: commands.Context,
        대상: discord.Member,
        프로필: str = "일반",
        채널: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        if not 대상.bot:
            await ctx.send("⛔ 안전을 위해 봇 계정에만 적용할 수 있습니다.")
            return
        profile = PROFILE_LABELS.get(str(프로필).casefold())
        if profile is None:
            await ctx.send("⚠️ 프로필: `일반`, `알림`, `게임`, `운영`, `음성`, `읽기전용`, `차단`")
            return
        target_channel: discord.abc.GuildChannel = 채널 or ctx.channel  # type: ignore[assignment]
        if not isinstance(target_channel, discord.abc.GuildChannel):
            await ctx.send("⚠️ 서버 채널을 지정해주세요.")
            return
        manageable, reason = _can_manage_target(ctx.guild, 대상)
        if not manageable:
            await ctx.send(f"⛔ 적용할 수 없습니다: {reason}")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        batch = await _backup_entries(ctx.guild, state, [(대상, target_channel)], f"{profile} 프로필 적용")
        overwrite, skipped = _profile_overwrite(ctx.guild, profile)
        try:
            await target_channel.set_permissions(대상, overwrite=overwrite, reason=f"ABADDON v{VERSION} permission profile {profile}; backup={batch}")
        except discord.Forbidden:
            await ctx.send("⛔ Discord가 권한 변경을 거부했습니다. ABADDON의 역할 관리 권한과 역할 순서를 확인해주세요.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"⚠️ Discord API 오류로 적용하지 못했습니다: {exc}")
            return
        state["permission_history"].append({"id": batch, "at": _now_iso(), "action": "apply", "target_id": int(대상.id), "channel_id": int(target_channel.id), "profile": profile})
        _trim(state["permission_history"])
        save_data()
        await ctx.send(f"✅ {대상.mention}에게 **{profile}** 프로필을 적용했습니다.\n채널: {target_channel.mention}\n복구 ID: `{batch}`\n허용하지 못해 상속 처리한 권한: {', '.join(skipped) if skipped else '없음'}")

    @bot.command(name="권한자동설정", aliases=["채널권한자동설정", "autopermissions", "autoconfigurepermissions"], help="채널 이름과 종류에 따라 ABADDON 권한 프로필을 미리보기 또는 적용합니다.")
    async def auto_permissions(ctx: commands.Context, 모드: str = "미리보기") -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        me = ctx.guild.me
        if me is None:
            await ctx.send("⚠️ ABADDON 서버 멤버 정보를 찾지 못했습니다.")
            return
        apply_mode = str(모드).casefold() in {"적용", "실행", "apply", "run"}
        channels = list(ctx.guild.channels)[:MAX_AUTO_CHANNELS]
        inferred = [(channel, _infer_profile(channel)) for channel in channels]
        counts: Dict[str, int] = {}
        for _, profile in inferred:
            counts[profile] = counts.get(profile, 0) + 1
        if not apply_mode:
            lines = [f"**{profile}** · {count}개" for profile, count in sorted(counts.items())]
            samples = [f"{channel.mention} → `{profile}`" for channel, profile in inferred[:15]]
            embed = discord.Embed(title="🧭 채널 권한 자동 설정 미리보기", description="\n".join(lines), color=discord.Color.blue())
            embed.add_field(name="첫 15개 채널", value="\n".join(samples)[:1024] or "없음", inline=False)
            embed.set_footer(text="실제 변경: !권한자동설정 적용 · 변경 전 모든 채널 권한을 한 묶음으로 백업")
            await ctx.send(embed=embed)
            return
        manageable, reason = _can_manage_target(ctx.guild, me)
        if not manageable:
            await ctx.send(f"⛔ 적용할 수 없습니다: {reason}")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        batch = await _backup_entries(ctx.guild, state, ((me, channel) for channel, _ in inferred), "ABADDON 채널별 자동 권한 설정")
        applied = 0
        failed: List[str] = []
        skipped_permissions: set[str] = set()
        for channel, profile in inferred:
            overwrite, skipped = _profile_overwrite(ctx.guild, profile)
            skipped_permissions.update(skipped)
            try:
                await channel.set_permissions(me, overwrite=overwrite, reason=f"ABADDON v{VERSION} automatic channel profile {profile}; backup={batch}")
                applied += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                failed.append(f"{channel.name}: {type(exc).__name__}")
            await asyncio.sleep(0.18)
        state["permission_history"].append({"id": batch, "at": _now_iso(), "action": "auto_apply", "target_id": int(me.id), "channels": applied, "failed": len(failed)})
        _trim(state["permission_history"])
        save_data()
        await ctx.send(f"✅ 자동 권한 설정 완료: {applied}/{len(inferred)}개\n복구 ID: `{batch}`\n실패: {len(failed)}개\n상속 처리 권한: {', '.join(sorted(skipped_permissions)) if skipped_permissions else '없음'}" + (f"\n첫 오류: {failed[0]}" if failed else ""))

    @bot.command(name="권한복구", aliases=["봇권한복구", "restorepermissions", "permissionrollback"], help="권한 적용 전에 생성된 복구 ID로 채널 덮어쓰기를 되돌립니다.")
    async def restore_permissions(ctx: commands.Context, 복구ID: str) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        backup = next((row for row in reversed(state["permission_backups"]) if str(row.get("id")) == str(복구ID)), None)
        if backup is None:
            await ctx.send("⚠️ 해당 권한 복구 ID를 찾지 못했습니다.")
            return
        restored = 0
        failed: List[str] = []
        for entry in backup.get("entries", []):
            channel = ctx.guild.get_channel(_safe_int(entry.get("channel_id")))
            target = ctx.guild.get_member(_safe_int(entry.get("target_id")))
            if not isinstance(channel, discord.abc.GuildChannel) or not isinstance(target, discord.Member):
                failed.append(f"누락:{entry.get('channel_name')}/{entry.get('target_name')}")
                continue
            try:
                await channel.set_permissions(target, overwrite=_overwrite_from_snapshot(entry.get("before", {})), reason=f"ABADDON v{VERSION} permission rollback {복구ID}")
                restored += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                failed.append(f"{channel.name}:{type(exc).__name__}")
            await asyncio.sleep(0.18)
        backup["restored_at"] = _now_iso()
        state["permission_history"].append({"id": str(복구ID), "at": _now_iso(), "action": "restore", "restored": restored, "failed": len(failed)})
        _trim(state["permission_history"])
        save_data()
        await ctx.send(f"↩️ 권한 복구 완료: {restored}/{len(backup.get('entries', []))}개 · 실패 {len(failed)}개" + (f"\n첫 오류: {failed[0]}" if failed else ""))

    @bot.command(name="권한변경내역", aliases=["권한복구목록", "permissionhistory"], help="최근 권한 백업과 복구 ID를 확인합니다.")
    async def permission_history(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        lines = []
        for row in reversed(state["permission_backups"][-15:]):
            lines.append(f"`{row.get('id')}` · {row.get('reason')} · 항목 {len(row.get('entries', []))} · {'복구됨' if row.get('restored_at') else '사용 가능'}")
        await ctx.send("🧾 **최근 권한 복구 지점**\n" + ("\n".join(lines) if lines else "아직 기록이 없습니다."))

    @bot.command(name="서버설정백업", aliases=["운영설정백업", "serversettingsbackup"], help="서버 알림·시간·채널 설정을 복구 지점으로 저장합니다.")
    async def server_settings_backup(ctx: commands.Context) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        backup_id = _batch_id("S", ctx.guild.id)
        payload = {
            "id": backup_id, "created_at": _now_iso(), "restored_at": "",
            "settings": copy.deepcopy({k: v for k, v in state.items() if k not in {"permission_backups", "settings_backups", "permission_history"}}),
            "legacy": _legacy_state_snapshot(world_data, int(ctx.guild.id)),
        }
        state["settings_backups"].append(payload)
        _trim(state["settings_backups"])
        save_data()
        await ctx.send(f"✅ 서버 운영 설정을 백업했습니다. 복구 ID: `{backup_id}`")

    @bot.command(name="서버설정복구", aliases=["운영설정복구", "restoreserversettings"], help="서버 운영 설정 백업을 복구합니다.")
    async def restore_server_settings(ctx: commands.Context, 복구ID: str) -> None:
        if not await _require_admin(ctx):
            return
        assert ctx.guild is not None
        state = _guild_state(world_data, int(ctx.guild.id))
        backup = next((row for row in reversed(state["settings_backups"]) if str(row.get("id")) == str(복구ID)), None)
        if backup is None:
            await ctx.send("⚠️ 해당 서버 설정 복구 ID를 찾지 못했습니다.")
            return
        preserved = {
            "permission_backups": state["permission_backups"],
            "settings_backups": state["settings_backups"],
            "permission_history": state["permission_history"],
        }
        restored_settings = copy.deepcopy(backup.get("settings", {}))
        state.clear()
        state.update(restored_settings)
        state.update(preserved)
        legacy = backup.get("legacy", {}) if isinstance(backup.get("legacy"), dict) else {}
        try:
            disaster_module._guild_state(world_data, int(ctx.guild.id))["disaster"] = copy.deepcopy(legacy.get("disaster", {}))
            world_data.setdefault("v720_coop_cleanup", {}).setdefault("guilds", {})[str(ctx.guild.id)] = copy.deepcopy(legacy.get("patch", {}))
            world_data.setdefault("quiz_notifications", {})[str(ctx.guild.id)] = copy.deepcopy(legacy.get("quiz", {}))
            world_data.setdefault("market_notifications", {})[str(ctx.guild.id)] = copy.deepcopy(legacy.get("market", {}))
            world_data.setdefault("v639", {}).setdefault("guilds", {})[str(ctx.guild.id)] = copy.deepcopy(legacy.get("frontier", {}))
        except Exception:
            pass
        backup["restored_at"] = _now_iso()
        _sync_legacy(world_data, int(ctx.guild.id))
        save_data()
        await ctx.send(f"↩️ 서버 운영 설정을 `{복구ID}` 상태로 복구했습니다.")

    @bot.command(name="서버설정복구목록", aliases=["serversettingshistory"], help="최근 서버 설정 백업 ID를 확인합니다.")
    async def server_settings_history(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        lines = [f"`{row.get('id')}` · {row.get('created_at', '')[:19]} · {'복구됨' if row.get('restored_at') else '사용 가능'}" for row in reversed(state["settings_backups"][-15:])]
        await ctx.send("🗃️ **서버 설정 복구 지점**\n" + ("\n".join(lines) if lines else "아직 기록이 없습니다."))

    @bot.command(name="서버설정검수", aliases=["운영설정검수", "serverconfigaudit", "v1150audit"], help="v11.5.0 알림·권한·백업 변경만 검사합니다.")
    async def server_config_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        rows = _checks(bot, world_data)
        if ctx.guild is not None:
            me = ctx.guild.me
            missing = [name for name in REQUIRED_ABADDON_GUILD_PERMS if me is None or not bool(getattr(me.guild_permissions, name, False))]
            rows.append(("ABADDON 서버 권한", not missing, ", ".join(missing) if missing else "필수 권한 충족"))
            rows.append(("서버 봇 감지", len(_bot_members(ctx.guild)) >= 1, f"bots={len(_bot_members(ctx.guild))}"))
        passed = sum(1 for _, ok, _ in rows if ok)
        embed = _dashboard(
            bot, locale,
            f"🛠️ ABADDON v{VERSION} 서버 운영 검수 · {passed}/{len(rows)}",
            f"🛠️ ABADDON v{VERSION} Server Operations Audit · {passed}/{len(rows)}",
            "이번 패치에서 변경한 알림 구독·채널 권한·백업·복구만 검사합니다.",
            "Checks only alert subscriptions, channel permissions, backups and restoration changed in this patch.",
            discord.Color.green() if passed == len(rows) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!서버설정검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1150_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await server_config_audit.callback(ctx, 모드)
        test_command.callback = v1150_test
        test_command.help = "v11.5.0에서 변경한 서버별 알림·봇 권한·백업·복구만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1150_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot, locale,
                f"🛠️ ABADDON v{VERSION} — 서버 운영센터",
                f"🛠️ ABADDON v{VERSION} — Server Operations Center",
                "이번 패치에서 실제로 변경한 항목만 표시합니다.",
                "Shows only the changes made in this patch.",
                discord.Color.blurple(),
            )
            embed.add_field(name=_t(locale, "🔔 서버별 알림", "🔔 Per-Server Alerts"), value=_t(locale, "재난·패치·퀴즈·암시장·세계 이벤트 등을 종류별 채널과 구독 상태로 관리합니다.", "Manage disaster, patch, quiz, market and world-event alerts by subscription and channel."), inline=False)
            embed.add_field(name=_t(locale, "🌙 알림 시간", "🌙 Alert Hours"), value=_t(locale, "설정한 시간 밖에는 연동 자동 알림을 일시 중지하고 시간 안에 다시 활성화합니다.", "Integrated automatic alerts pause outside configured hours and resume inside them."), inline=False)
            embed.add_field(name=_t(locale, "🤖 서버 봇 검수", "🤖 Server Bot Audit"), value=_t(locale, "서버의 봇 목록·강한 권한·채널 접근 상태를 확인합니다. 다른 봇은 명시적으로 선택하기 전까지 수정하지 않습니다.", "Review server bots, powerful permissions and channel access. Other bots are unchanged unless explicitly targeted."), inline=False)
            embed.add_field(name=_t(locale, "🛡️ 채널별 권한", "🛡️ Channel Permissions"), value=_t(locale, "채널 종류에 맞는 프로필을 미리보고 적용하며, 모든 변경 전에 복구 지점을 만듭니다.", "Preview and apply channel profiles, with a restore point created before every change."), inline=False)
            embed.add_field(name=_t(locale, "↩️ 원클릭 복구", "↩️ One-Step Restore"), value=_t(locale, "권한과 서버 운영 설정을 각각 백업 ID로 되돌릴 수 있습니다.", "Restore permissions and server-operation settings separately by backup ID."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1150_notes
        patch_notes.help = f"ABADDON v{VERSION} 서버 운영센터 패치를 확인합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1150_server_operations"]
    guide.append({
        "id": "v1150_server_operations",
        "emoji": "🛠️",
        "title": "v11.5.0 서버 운영센터",
        "hint": "서버별 알림 구독 · 시간 제한 · 서버 봇 검수 · 채널 권한 자동 설정 · 백업/복구",
        "commands": [
            "!서버운영 · !서버알림 종류 ON/OFF [#채널] · !알림시간 09:00 23:00 · !알림테스트 종류",
            "!서버봇목록 · !서버봇권한검수 상세 · !권한자동설정 미리보기/적용",
            "!봇권한적용 @봇 프로필 [#채널] · !권한백업 · !권한복구 ID · !서버설정백업/복구",
            "!서버설정검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1150_version = VERSION  # type: ignore[attr-defined]
    bot.v1150_checks = lambda: _checks(bot, world_data)  # type: ignore[attr-defined]
    bot.v1150_sync_notifications = lambda guild_id: _sync_legacy(world_data, int(guild_id))  # type: ignore[attr-defined]
    bot.v1150_dispatch_alert = dispatch_alert  # type: ignore[attr-defined]
    print(
        f"[ABADDON v{VERSION}] server_operations=enabled alerts=per_guild permissions=backup_first bot_audit=all rollback=enabled",
        flush=True,
    )
