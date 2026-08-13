from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from discord.ext import commands

STORY_GATE_VERSION = 1

SEASON_META: Dict[int, Dict[str, Any]] = {
    1: {"name": "검은 주파수", "command": "!스토리 시작", "emoji": "📡", "total_endings": 3},
    2: {"name": "백색 방주", "command": "!시즌2 시작", "emoji": "⚪", "total_endings": 4},
    3: {"name": "종말의 왕좌", "command": "!시즌3 시작", "emoji": "👑", "total_endings": 4},
    4: {"name": "황혼의 종착역", "command": "!시즌4 시작", "emoji": "🚂", "total_endings": 4},
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def season_state(user: Mapping[str, Any], season: int) -> Mapping[str, Any]:
    """Return the existing season state without creating or deleting user data."""
    if season == 1:
        return _mapping(user.get("story"))
    if season == 2:
        return _mapping(_mapping(user.get("v430")).get("season2"))
    if season == 3:
        return _mapping(_mapping(user.get("v600")).get("season3"))
    if season == 4:
        return _mapping(_mapping(user.get("v730")).get("season4"))
    return {}


def season_completed(user: Mapping[str, Any], season: int) -> bool:
    return bool(season_state(user, season).get("completed"))


def season_started(user: Mapping[str, Any], season: int) -> bool:
    state = season_state(user, season)
    return bool(state.get("started") or state.get("completed"))


def prerequisite_season(season: int) -> Optional[int]:
    return season - 1 if season > 1 else None


def progression_status(user: Mapping[str, Any], season: int) -> Tuple[bool, str]:
    """
    Return access before administrator override.

    Existing later-season progress is grandfathered so this patch never destroys or
    strands progress created before sequential locking was introduced.
    """
    if season <= 1:
        return True, "first_season"
    if season_started(user, season):
        return True, "legacy_or_active_progress"
    previous = season - 1
    if season_completed(user, previous):
        return True, "prerequisite_complete"
    return False, "prerequisite_incomplete"


async def is_story_admin(ctx: commands.Context, bot: commands.Bot) -> bool:
    author = getattr(ctx, "author", None)
    guild = getattr(ctx, "guild", None)
    if author is None:
        return False
    if guild is not None:
        if int(getattr(guild, "owner_id", 0) or 0) == int(getattr(author, "id", -1)):
            return True
        permissions = getattr(author, "guild_permissions", None)
        if bool(getattr(permissions, "administrator", False)):
            return True
    try:
        return bool(await bot.is_owner(author))
    except Exception:
        return False


async def can_access_season(
    ctx: commands.Context,
    bot: commands.Bot,
    user: Mapping[str, Any],
    season: int,
) -> Tuple[bool, str]:
    if await is_story_admin(ctx, bot):
        return True, "administrator_override"
    return progression_status(user, season)


def locked_text(season: int) -> str:
    previous = max(1, season - 1)
    previous_meta = SEASON_META[previous]
    target_meta = SEASON_META[season]
    return (
        f"🔒 **스토리 시즌 {season} · {target_meta['name']}**은 아직 잠겨 있습니다.\n"
        f"먼저 시즌 {previous} **{previous_meta['name']}**의 엔딩을 1회 완료해주세요.\n"
        f"시작 명령: `{previous_meta['command']}`\n\n"
        "🛡️ 서버 관리자와 봇 소유자는 점검을 위해 잠금을 우회할 수 있습니다."
    )


def season_display_status(user: Mapping[str, Any], season: int, *, admin: bool = False) -> str:
    state = season_state(user, season)
    if state.get("completed"):
        return "✅"
    if state.get("started"):
        return "🟨"
    accessible, _reason = progression_status(user, season)
    if accessible:
        return "⬜"
    return "🛡️" if admin else "🔒"
