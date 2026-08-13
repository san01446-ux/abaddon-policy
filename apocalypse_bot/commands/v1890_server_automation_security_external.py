from __future__ import annotations

"""ABADDON v18.9.0 server automation + security + external alert integration.

This layer intentionally reuses mature ABADDON features instead of duplicating them:
- welcome/autorole/newcomer: v4.1 / v7.1
- suggestions/polls: v7.9 / v4.1+
- calendar/reminders: v11.9
- automod/anti-raid/emergency lock: v4.1/v4.2

New in this layer:
- persistent giveaway system;
- free-form scheduled announcements;
- destructive-action burst watch (alert-first, existing emergency tools remain authoritative);
- YouTube upload alerts using YouTube Data API v3;
- Twitch live alerts using Helix with app access tokens;
- compact automation/security/external-alert hubs;
- latest post-deploy checklist and owner audit.
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import os
import random
import re
import secrets
import time
from typing import Any, Deque, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib import error as urllib_error

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands import v1831_persistent_command_hub as command_hub
from apocalypse_bot.commands import v1852_smart_command_discovery as discovery

VERSION = "18.9.0"
DATA_KEY = "server_ops_v1890"
KST = timezone(timedelta(hours=9))
MAX_GIVEAWAYS = 40
MAX_SCHEDULED_ANNOUNCEMENTS = 50
MAX_EXTERNAL_SUBS = 10
GIVEAWAY_JOIN_ID = "abaddon:v1890:giveaway:join"
AUTOMATION_IDS = {
    "welcome": "abaddon:v1890:auto:welcome",
    "autorole": "abaddon:v1890:auto:autorole",
    "giveaway": "abaddon:v1890:auto:giveaway",
    "poll": "abaddon:v1890:auto:poll",
    "suggest": "abaddon:v1890:auto:suggest",
    "schedule": "abaddon:v1890:auto:schedule",
}
SECURITY_IDS = {
    "automod": "abaddon:v1890:sec:automod",
    "antiraid": "abaddon:v1890:sec:antiraid",
    "emergency": "abaddon:v1890:sec:emergency",
    "audit": "abaddon:v1890:sec:audit",
    "destructive": "abaddon:v1890:sec:destructive",
}
EXTERNAL_IDS = {
    "youtube": "abaddon:v1890:ext:youtube",
    "twitch": "abaddon:v1890:ext:twitch",
    "status": "abaddon:v1890:ext:status",
}

_TWITCH_TOKEN: Dict[str, Any] = {"value": "", "expires_at": 0}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(DATA_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[DATA_KEY] = root
    root.setdefault("schema", 1)
    root.setdefault("guilds", {})
    root.setdefault("started_at", int(time.time()))
    root.setdefault("stats", {"giveaways": 0, "scheduled_posts": 0, "security_alerts": 0, "youtube_alerts": 0, "twitch_alerts": 0})
    return root


def _guild(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _root(world_data)
    guilds = root.setdefault("guilds", {})
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("giveaways", {})
    row.setdefault("scheduled_announcements", {})
    external = row.setdefault("external", {})
    if not isinstance(external, dict):
        external = {}
        row["external"] = external
    external.setdefault("youtube", {})
    external.setdefault("twitch", {})
    security = row.setdefault("security", {})
    if not isinstance(security, dict):
        security = {}
        row["security"] = security
    security.setdefault("destructive_watch_enabled", True)
    security.setdefault("threshold", 3)
    security.setdefault("window_seconds", 20)
    security.setdefault("last_alert_at", 0)
    security.setdefault("events", [])
    return row


def _management(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault("server_management", {})
    row = root.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        root[str(int(guild_id))] = row
    row.setdefault("welcome_channel_id", 0)
    row.setdefault("leave_channel_id", 0)
    row.setdefault("autorole_id", 0)
    row.setdefault("log_channel_id", 0)
    logs = row.setdefault("log_channels", {})
    if not isinstance(logs, dict):
        logs = {}
        row["log_channels"] = logs
    logs.setdefault("security", 0)
    auto = row.setdefault("automod", {})
    if not isinstance(auto, dict):
        auto = {}
        row["automod"] = auto
    auto.setdefault("enabled", False)
    anti = row.setdefault("anti_raid", {})
    if not isinstance(anti, dict):
        anti = {}
        row["anti_raid"] = anti
    anti.setdefault("enabled", False)
    anti.setdefault("auto_lockdown", False)
    anti.setdefault("raid_active", False)
    emergency = row.setdefault("emergency", {})
    if not isinstance(emergency, dict):
        emergency = {}
        row["emergency"] = emergency
    emergency.setdefault("active", False)
    return row


def _manager(member: Any) -> bool:
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    return bool(member.id == member.guild.owner_id or perms.administrator or perms.manage_guild)


async def _require_manager_ctx(ctx: commands.Context) -> bool:
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ 서버에서 사용해주세요.")
        return False
    if not _manager(ctx.author):
        await ctx.send("❌ 서버 관리 권한이 필요합니다.")
        return False
    return True


def _parse_toggle(value: str) -> Optional[bool]:
    token = str(value or "").strip().casefold()
    if token in {"켜기", "켜", "on", "true", "1", "활성화"}:
        return True
    if token in {"끄기", "꺼", "off", "false", "0", "비활성화"}:
        return False
    return None


def _parse_kst(date_text: str, time_text: str) -> int:
    try:
        dt = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except ValueError as exc:
        raise ValueError("날짜/시간 형식은 `YYYY-MM-DD HH:MM`입니다.") from exc
    return int(dt.timestamp())


def _short(value: Any, limit: int = 100) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3).upper()}"


def _resolve_text_channel(guild: discord.Guild, raw: Any) -> Optional[discord.TextChannel]:
    channel = guild.get_channel(_safe_int(raw, 0))
    return channel if isinstance(channel, discord.TextChannel) else None


def _security_log_channel(world_data: MutableMapping[str, Any], guild: discord.Guild) -> Optional[discord.TextChannel]:
    settings = _management(world_data, guild.id)
    split = _safe_int(settings.get("log_channels", {}).get("security"), 0)
    return _resolve_text_channel(guild, split) or _resolve_text_channel(guild, settings.get("log_channel_id", 0)) or guild.system_channel


async def _run_feature(bot: commands.Bot, interaction: discord.Interaction, command_name: str) -> None:
    await discovery._run_entry(bot, interaction, command_name)


class AutomationHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="환영", emoji="👋", style=discord.ButtonStyle.primary, custom_id=AUTOMATION_IDS["welcome"], row=0)
    async def welcome(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "환영채널")

    @discord.ui.button(label="자동 역할", emoji="🎭", style=discord.ButtonStyle.secondary, custom_id=AUTOMATION_IDS["autorole"], row=0)
    async def autorole(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "자동역할")

    @discord.ui.button(label="경품", emoji="🎁", style=discord.ButtonStyle.success, custom_id=AUTOMATION_IDS["giveaway"], row=0)
    async def giveaway(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "경품")

    @discord.ui.button(label="투표", emoji="📊", style=discord.ButtonStyle.secondary, custom_id=AUTOMATION_IDS["poll"], row=1)
    async def poll(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "투표")

    @discord.ui.button(label="건의", emoji="💡", style=discord.ButtonStyle.secondary, custom_id=AUTOMATION_IDS["suggest"], row=1)
    async def suggest(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "건의")

    @discord.ui.button(label="예약 공지", emoji="⏰", style=discord.ButtonStyle.primary, custom_id=AUTOMATION_IDS["schedule"], row=1)
    async def schedule(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "예약공지")


class SecurityHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="AutoMod", emoji="🛡️", style=discord.ButtonStyle.primary, custom_id=SECURITY_IDS["automod"])
    async def automod(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "자동관리")

    @discord.ui.button(label="안티레이드", emoji="🚨", style=discord.ButtonStyle.danger, custom_id=SECURITY_IDS["antiraid"])
    async def antiraid(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "안티레이드")

    @discord.ui.button(label="비상 모드", emoji="🔒", style=discord.ButtonStyle.danger, custom_id=SECURITY_IDS["emergency"])
    async def emergency(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "비상모드")

    @discord.ui.button(label="서버 점검", emoji="🧪", style=discord.ButtonStyle.secondary, custom_id=SECURITY_IDS["audit"])
    async def audit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "서버점검")

    @discord.ui.button(label="파괴 감시", emoji="🧯", style=discord.ButtonStyle.secondary, custom_id=SECURITY_IDS["destructive"])
    async def destructive(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "파괴감시")


class ExternalHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="YouTube", emoji="📺", style=discord.ButtonStyle.danger, custom_id=EXTERNAL_IDS["youtube"])
    async def youtube(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "유튜브알림목록")

    @discord.ui.button(label="Twitch", emoji="🟣", style=discord.ButtonStyle.primary, custom_id=EXTERNAL_IDS["twitch"])
    async def twitch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "트위치알림목록")

    @discord.ui.button(label="환경 상태", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id=EXTERNAL_IDS["status"])
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await _run_feature(self.bot, interaction, "외부알림상태")


class GiveawayPersistentView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any], save_data: Any):
        super().__init__(timeout=None)
        self.world_data = world_data
        self.save_data = save_data

    @discord.ui.button(label="참가 / 취소", emoji="🎟️", style=discord.ButtonStyle.success, custom_id=GIVEAWAY_JOIN_ID)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message("서버 경품 메시지에서 사용해주세요.", ephemeral=True)
            return
        row = _guild(self.world_data, interaction.guild.id)
        giveaway = row.setdefault("giveaways", {}).get(str(interaction.message.id))
        if not isinstance(giveaway, dict):
            await interaction.response.send_message("이 경품은 현재 버전에서 찾을 수 없습니다.", ephemeral=True)
            return
        if giveaway.get("ended") or int(giveaway.get("ends_at", 0) or 0) <= int(time.time()):
            await interaction.response.send_message("이미 종료된 경품입니다.", ephemeral=True)
            return
        uid = int(interaction.user.id)
        participants = giveaway.setdefault("participants", [])
        if uid in participants:
            participants.remove(uid)
            text = f"🎟️ 참가를 취소했습니다. 현재 **{len(participants)}명** 참가 중입니다."
        else:
            participants.append(uid)
            text = f"✅ 경품에 참가했습니다. 현재 **{len(participants)}명** 참가 중입니다."
        self.save_data()
        await interaction.response.send_message(text, ephemeral=True)


def _giveaway_embed(giveaway: Mapping[str, Any], *, ended: bool = False, winners: Sequence[int] = ()) -> discord.Embed:
    prize = str(giveaway.get("prize", "경품"))
    color = 0x95A5A6 if ended else 0xF1C40F
    embed = discord.Embed(title=f"🎁 ABADDON 경품 · {prize}", color=color)
    if ended:
        if winners:
            embed.description = "🏆 당첨: " + ", ".join(f"<@{uid}>" for uid in winners)
        else:
            embed.description = "참가자가 없어 당첨자 없이 종료되었습니다."
    else:
        embed.description = "아래 **참가 / 취소** 버튼으로 응모하세요. 재시작 후에도 참가 버튼은 유지됩니다."
    embed.add_field(name="종료", value=f"<t:{int(giveaway.get('ends_at', 0) or 0)}:R>", inline=True)
    embed.add_field(name="당첨 인원", value=f"**{int(giveaway.get('winner_count', 1) or 1)}명**", inline=True)
    embed.add_field(name="참가자", value=f"**{len(giveaway.get('participants', []) or [])}명**", inline=True)
    embed.set_footer(text=f"ID {giveaway.get('id', '-')} · ABADDON v{VERSION}")
    return embed


def _pick_winners(giveaway: Mapping[str, Any]) -> List[int]:
    participants = [int(x) for x in giveaway.get("participants", []) if str(x).isdigit()]
    count = max(1, min(int(giveaway.get("winner_count", 1) or 1), len(participants))) if participants else 0
    return secrets.SystemRandom().sample(participants, count) if count else []


def _announce_embed(content: str, repeat: str, schedule_id: str) -> discord.Embed:
    embed = discord.Embed(title="📡 ABADDON 예약 방송", description=str(content)[:3900], color=0x8E44AD)
    embed.set_footer(text=f"예약 {schedule_id} · 반복 {repeat}")
    return embed


def _http_json(method: str, url: str, *, headers: Optional[Mapping[str, str]] = None, data: Optional[bytes] = None, timeout: int = 12) -> Dict[str, Any]:
    req = urllib_request.Request(url, data=data, method=method, headers=dict(headers or {}))
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            raw = response.read(512_000).decode("utf-8", "replace")
            return {"ok": True, "status": int(response.status), "data": json.loads(raw) if raw else {}}
    except urllib_error.HTTPError as exc:
        try:
            raw = exc.read(128_000).decode("utf-8", "replace")
        except Exception:
            raw = ""
        return {"ok": False, "status": int(getattr(exc, "code", 0) or 0), "error": raw[:1000] or str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"{type(exc).__name__}: {exc}"[:1000]}


async def _youtube_channel_info(identifier: str) -> Dict[str, Any]:
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "YOUTUBE_API_KEY 환경변수가 없습니다."}
    token = str(identifier or "").strip()
    params: Dict[str, Any] = {"part": "snippet,contentDetails", "key": key}
    if token.startswith("UC"):
        params["id"] = token
    else:
        params["forHandle"] = token if token.startswith("@") else f"@{token}"
    query = urllib_parse.urlencode(params)
    result = await asyncio.to_thread(_http_json, "GET", f"https://www.googleapis.com/youtube/v3/channels?{query}")
    if not result.get("ok"):
        return result
    items = result.get("data", {}).get("items", [])
    if not items:
        return {"ok": False, "error": "YouTube 채널을 찾지 못했습니다. 채널 ID(UC...) 또는 @핸들을 확인해주세요."}
    item = items[0]
    uploads = (((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or "")
    canonical_id = str(item.get("id", token))
    return {"ok": bool(uploads), "channel_id": canonical_id, "title": (item.get("snippet") or {}).get("title", canonical_id), "uploads": uploads, "error": "업로드 재생목록을 찾지 못했습니다." if not uploads else ""}


async def _youtube_latest(uploads_playlist_id: str) -> Dict[str, Any]:
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "YOUTUBE_API_KEY 환경변수가 없습니다."}
    query = urllib_parse.urlencode({"part": "snippet,contentDetails", "playlistId": uploads_playlist_id, "maxResults": 1, "key": key})
    result = await asyncio.to_thread(_http_json, "GET", f"https://www.googleapis.com/youtube/v3/playlistItems?{query}")
    if not result.get("ok"):
        return result
    items = result.get("data", {}).get("items", [])
    if not items:
        return {"ok": True, "video": None}
    item = items[0]
    snippet = item.get("snippet") or {}
    details = item.get("contentDetails") or {}
    vid = str(details.get("videoId") or ((snippet.get("resourceId") or {}).get("videoId") or ""))
    return {"ok": True, "video": {"id": vid, "title": snippet.get("title", "새 영상"), "published_at": snippet.get("publishedAt", ""), "channel_title": snippet.get("channelTitle", "")}}


async def _twitch_token() -> Dict[str, Any]:
    now = int(time.time())
    if _TWITCH_TOKEN.get("value") and int(_TWITCH_TOKEN.get("expires_at", 0)) > now + 60:
        return {"ok": True, "token": _TWITCH_TOKEN["value"]}
    client_id = os.getenv("TWITCH_CLIENT_ID", "").strip()
    secret = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        return {"ok": False, "error": "TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET 환경변수가 없습니다."}
    data = urllib_parse.urlencode({"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"}).encode("utf-8")
    result = await asyncio.to_thread(_http_json, "POST", "https://id.twitch.tv/oauth2/token", headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data)
    if not result.get("ok"):
        return result
    payload = result.get("data", {})
    token = str(payload.get("access_token", ""))
    if not token:
        return {"ok": False, "error": "Twitch app access token을 받지 못했습니다."}
    _TWITCH_TOKEN["value"] = token
    _TWITCH_TOKEN["expires_at"] = now + int(payload.get("expires_in", 3600) or 3600)
    return {"ok": True, "token": token}


async def _twitch_get(path: str, params: Mapping[str, Any]) -> Dict[str, Any]:
    auth = await _twitch_token()
    if not auth.get("ok"):
        return auth
    client_id = os.getenv("TWITCH_CLIENT_ID", "").strip()
    query = urllib_parse.urlencode(params, doseq=True)
    return await asyncio.to_thread(
        _http_json,
        "GET",
        f"https://api.twitch.tv/helix/{path}?{query}",
        headers={"Authorization": f"Bearer {auth['token']}", "Client-Id": client_id},
    )


async def _twitch_user(login: str) -> Dict[str, Any]:
    result = await _twitch_get("users", {"login": login})
    if not result.get("ok"):
        return result
    rows = result.get("data", {}).get("data", [])
    if not rows:
        return {"ok": False, "error": "Twitch 채널을 찾지 못했습니다."}
    row = rows[0]
    return {"ok": True, "id": str(row.get("id", "")), "login": str(row.get("login", login)), "display_name": str(row.get("display_name", login))}


async def _twitch_stream(login: str) -> Dict[str, Any]:
    result = await _twitch_get("streams", {"user_login": login, "first": 1})
    if not result.get("ok"):
        return result
    rows = result.get("data", {}).get("data", [])
    return {"ok": True, "stream": rows[0] if rows else None}


def _clean_youtube_id(value: str) -> str:
    token = str(value or "").strip()
    match = re.search(r"(?:youtube\.com/channel/)?(UC[A-Za-z0-9_-]{20,})", token)
    if match:
        return match.group(1)
    handle = re.search(r"youtube\.com/@([A-Za-z0-9._-]+)", token)
    if handle:
        return "@" + handle.group(1)
    return token


def _clean_twitch_login(value: str) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"^https?://(?:www\.)?twitch\.tv/", "", token)
    return token.split("/")[0].strip()


def _external_status_embed(world_data: MutableMapping[str, Any], guild: discord.Guild) -> discord.Embed:
    row = _guild(world_data, guild.id)
    ext = row.get("external", {})
    yt = ext.get("youtube", {}) if isinstance(ext, Mapping) else {}
    tw = ext.get("twitch", {}) if isinstance(ext, Mapping) else {}
    youtube_ready = bool(os.getenv("YOUTUBE_API_KEY", "").strip())
    twitch_ready = bool(os.getenv("TWITCH_CLIENT_ID", "").strip() and os.getenv("TWITCH_CLIENT_SECRET", "").strip())
    embed = discord.Embed(title="📡 ABADDON 외부 알림 센터", color=0x9146FF)
    embed.add_field(name="📺 YouTube", value=f"환경 {'✅' if youtube_ready else '❌'} · 등록 **{len(yt)}개**\n`YOUTUBE_API_KEY` = Google Cloud API Key (유튜브 URL 아님)\n`!유튜브알림등록 <채널ID 또는 @핸들> [#알림채널]`", inline=False)
    embed.add_field(name="🟣 Twitch", value=f"환경 {'✅' if twitch_ready else '❌'} · 등록 **{len(tw)}개**\n`!트위치알림등록 <로그인명> [#알림채널]`", inline=False)
    embed.add_field(name="🔐 비밀값", value="API Key / Client Secret은 Discord나 홈페이지에 표시하지 않고 Render 환경변수에서만 읽습니다.", inline=False)
    embed.set_footer(text=f"ABADDON v{VERSION} · 최대 플랫폼별 서버당 {MAX_EXTERNAL_SUBS}개")
    return embed


def register_v1890_server_automation_security_external(
    bot: commands.Bot,
    world_data: MutableMapping[str, Any],
    save_data: Any,
) -> None:
    if getattr(bot, "_abaddon_v1890_registered", False):
        return
    bot._abaddon_v1890_registered = True
    bot.abaddon_version = VERSION
    _root(world_data)

    try:
        bot.add_view(GiveawayPersistentView(world_data, save_data))
        bot.add_view(AutomationHubView(bot))
        bot.add_view(SecurityHubView(bot))
        bot.add_view(ExternalHubView(bot))
    except ValueError:
        pass

    @bot.command(name="자동화센터", aliases=["automationcenter", "serverautomation"], help="환영·역할·경품·투표·건의·예약 공지를 한 화면에서 관리합니다.")
    async def automation_center(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("서버에서 사용해주세요.")
            return
        mgmt = _management(world_data, ctx.guild.id)
        row = _guild(world_data, ctx.guild.id)
        embed = discord.Embed(title="⚙️ ABADDON 서버 자동화 센터", description="이미 검증된 기존 기능은 그대로 재사용하고, 필요한 기능만 한 화면에 모았습니다.", color=0x57F287)
        embed.add_field(name="👋 환영·자동 역할", value=f"환영채널 {'✅' if _safe_int(mgmt.get('welcome_channel_id')) else '➖'} · 자동역할 {'✅' if _safe_int(mgmt.get('autorole_id')) else '➖'}\n`!환영채널` · `!자동역할` · `!새싹설정` · `!환영테마`", inline=False)
        embed.add_field(name="🎁 경품", value=f"진행/기록 **{len(row.get('giveaways', {}))}개** · `!경품시작` · `!경품목록` · `!경품재추첨`", inline=False)
        embed.add_field(name="📊 투표·건의", value="기존 `!투표` · `!건의` · `!건의목록` · `!건의상태` 그대로 연결", inline=False)
        embed.add_field(name="🗓️ 일정·예약 방송", value=f"기존 `!일정`/`!일정등록` + 자유문구 `!예약공지` · 저장 **{len(row.get('scheduled_announcements', {}))}개**", inline=False)
        embed.set_footer(text=f"ABADDON v{VERSION} · 중복 구현 대신 기존 데이터 재사용")
        await ctx.send(embed=embed, view=AutomationHubView(bot))

    @bot.command(name="경품", aliases=["giveaway", "raffle"], help="경품 시스템 사용법과 현재 진행 경품을 확인합니다.")
    async def giveaway_center(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        active = [g for g in _guild(world_data, ctx.guild.id).get("giveaways", {}).values() if isinstance(g, Mapping) and not g.get("ended")]
        embed = discord.Embed(title="🎁 ABADDON 경품 센터", description="버튼형 경품 추첨 · 참가/취소 · 자동 종료 · 재추첨을 지원합니다.", color=0xF1C40F)
        embed.add_field(name="진행 중", value=f"**{len(active)}개**", inline=True)
        embed.add_field(name="시작", value="`!경품시작 60 1 상품명`\n(60분 · 당첨 1명)", inline=False)
        embed.add_field(name="관리", value="`!경품목록` · `!경품종료 <ID>` · `!경품재추첨 <ID>`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="경품시작", aliases=["giveawaystart", "startraffle"], help="버튼 경품을 시작합니다. `!경품시작 60 1 상품명`")
    async def giveaway_start(ctx: commands.Context, 분: int, 당첨인원: int = 1, *, 상품: str = "ABADDON 경품") -> None:
        if not await _require_manager_ctx(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("텍스트 채널에서 실행해주세요.")
            return
        if not 1 <= int(분) <= 10080 or not 1 <= int(당첨인원) <= 20:
            await ctx.send("❌ 범위: 1~10080분 · 당첨 1~20명")
            return
        giveaways = _guild(world_data, ctx.guild.id).setdefault("giveaways", {})
        active = [g for g in giveaways.values() if isinstance(g, Mapping) and not g.get("ended")]
        if len(active) >= MAX_GIVEAWAYS:
            await ctx.send("❌ 진행 경품 저장 한도에 도달했습니다.")
            return
        row: Dict[str, Any] = {
            "id": _id("GW"), "guild_id": ctx.guild.id, "channel_id": ctx.channel.id, "message_id": 0,
            "creator_id": ctx.author.id, "prize": _short(상품, 200), "ends_at": int(time.time()) + int(분) * 60,
            "winner_count": int(당첨인원), "participants": [], "ended": False, "winners": [], "created_at": int(time.time()),
        }
        message = await ctx.send(embed=_giveaway_embed(row), view=GiveawayPersistentView(world_data, save_data))
        row["message_id"] = message.id
        giveaways[str(message.id)] = row
        _root(world_data)["stats"]["giveaways"] = int(_root(world_data)["stats"].get("giveaways", 0)) + 1
        save_data()

    async def finish_giveaway(guild: discord.Guild, giveaway: MutableMapping[str, Any], *, forced_by: Optional[discord.abc.User] = None) -> List[int]:
        if giveaway.get("ended"):
            return [int(x) for x in giveaway.get("winners", []) if str(x).isdigit()]
        winners = _pick_winners(giveaway)
        giveaway["ended"] = True
        giveaway["ended_at"] = int(time.time())
        giveaway["winners"] = winners
        if forced_by is not None:
            giveaway["forced_by"] = int(forced_by.id)
        save_data()
        channel = guild.get_channel(_safe_int(giveaway.get("channel_id"), 0))
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(_safe_int(giveaway.get("message_id"), 0))
                await message.edit(embed=_giveaway_embed(giveaway, ended=True, winners=winners), view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            try:
                result = "🏆 당첨자: " + ", ".join(f"<@{uid}>" for uid in winners) if winners else "참가자가 없어 당첨자 없이 종료되었습니다."
                await channel.send(f"🎁 **{giveaway.get('prize', '경품')}** 경품 종료 · {result}")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return winners

    @bot.command(name="경품목록", aliases=["giveawaylist", "rafflelist"], help="현재 서버 경품 목록을 확인합니다.")
    async def giveaway_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        rows = list(_guild(world_data, ctx.guild.id).get("giveaways", {}).values())
        rows = [g for g in rows if isinstance(g, Mapping)][-20:]
        if not rows:
            await ctx.send("등록된 경품이 없습니다.")
            return
        lines = []
        for g in reversed(rows):
            state = "종료" if g.get("ended") else "진행"
            lines.append(f"`{g.get('id')}` · **{_short(g.get('prize'), 50)}** · {state} · 참가 {len(g.get('participants', []) or [])}명 · <t:{int(g.get('ends_at',0) or 0)}:R>")
        await ctx.send("🎁 **경품 목록**\n" + "\n".join(lines))

    def find_giveaway(guild_id: int, giveaway_id: str) -> Optional[MutableMapping[str, Any]]:
        token = str(giveaway_id or "").strip().upper()
        for row in _guild(world_data, guild_id).get("giveaways", {}).values():
            if isinstance(row, dict) and str(row.get("id", "")).upper() == token:
                return row
        return None

    @bot.command(name="경품종료", aliases=["giveawayend", "endraffle"], help="경품을 즉시 종료합니다.")
    async def giveaway_end(ctx: commands.Context, 경품ID: str) -> None:
        if not await _require_manager_ctx(ctx):
            return
        row = find_giveaway(ctx.guild.id, 경품ID)
        if row is None:
            await ctx.send("경품 ID를 찾지 못했습니다.")
            return
        winners = await finish_giveaway(ctx.guild, row, forced_by=ctx.author)
        await ctx.send("✅ 경품을 종료했습니다." + (" 당첨: " + ", ".join(f"<@{x}>" for x in winners) if winners else ""))

    @bot.command(name="경품재추첨", aliases=["giveawayreroll", "rafflereroll"], help="종료된 경품 참가자 중 다시 당첨자를 뽑습니다.")
    async def giveaway_reroll(ctx: commands.Context, 경품ID: str) -> None:
        if not await _require_manager_ctx(ctx):
            return
        row = find_giveaway(ctx.guild.id, 경품ID)
        if row is None or not row.get("ended"):
            await ctx.send("종료된 경품 ID를 입력해주세요.")
            return
        winners = _pick_winners(row)
        row.setdefault("rerolls", []).append({"at": int(time.time()), "by": ctx.author.id, "winners": winners})
        save_data()
        await ctx.send("🎲 **재추첨 결과**\n" + (", ".join(f"<@{x}>" for x in winners) if winners else "참가자 없음"))

    @bot.command(name="예약공지", aliases=["scheduledannouncement", "schedulepost"], help="자유문구 공지를 예약합니다. `!예약공지 2026-08-13 20:00 1회 내용`")
    async def schedule_announcement(ctx: commands.Context, 날짜: str, 시간: str, 반복: str = "1회", *, 내용: str) -> None:
        if not await _require_manager_ctx(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("텍스트 채널에서 실행해주세요.")
            return
        try:
            starts = _parse_kst(날짜, 시간)
        except ValueError as exc:
            await ctx.send(f"❌ {exc}")
            return
        if starts < int(time.time()) + 30:
            await ctx.send("현재보다 최소 30초 뒤로 예약해주세요.")
            return
        repeat_map = {"1회": "once", "한번": "once", "once": "once", "매일": "daily", "daily": "daily", "매주": "weekly", "weekly": "weekly"}
        repeat = repeat_map.get(str(반복).casefold())
        if repeat is None:
            await ctx.send("반복은 `1회`, `매일`, `매주` 중 하나입니다.")
            return
        schedules = _guild(world_data, ctx.guild.id).setdefault("scheduled_announcements", {})
        active = [x for x in schedules.values() if isinstance(x, Mapping) and x.get("active")]
        if len(active) >= MAX_SCHEDULED_ANNOUNCEMENTS:
            await ctx.send("예약 공지 저장 한도에 도달했습니다.")
            return
        sid = _id("AN")
        schedules[sid] = {"id": sid, "channel_id": ctx.channel.id, "creator_id": ctx.author.id, "content": str(내용)[:1800], "next_at": starts, "repeat": repeat, "active": True, "created_at": int(time.time()), "sent_count": 0}
        save_data()
        await ctx.send(f"✅ 예약 공지 `{sid}` · <t:{starts}:F> · 반복 **{repeat}**")

    @bot.command(name="예약공지목록", aliases=["scheduledannouncementlist", "schedulepostlist"], help="예약된 자유문구 공지를 확인합니다.")
    async def scheduled_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        rows = [x for x in _guild(world_data, ctx.guild.id).get("scheduled_announcements", {}).values() if isinstance(x, Mapping) and x.get("active")]
        rows.sort(key=lambda x: int(x.get("next_at", 0) or 0))
        if not rows:
            await ctx.send("활성 예약 공지가 없습니다.")
            return
        await ctx.send("⏰ **예약 공지 목록**\n" + "\n".join(f"`{x.get('id')}` · <t:{int(x.get('next_at',0))}:F> · **{x.get('repeat')}** · {_short(x.get('content'), 70)}" for x in rows[:20]))

    @bot.command(name="예약공지취소", aliases=["scheduledannouncementcancel", "cancelschedulepost"], help="예약 공지를 취소합니다.")
    async def scheduled_cancel(ctx: commands.Context, 예약ID: str) -> None:
        if not await _require_manager_ctx(ctx):
            return
        row = _guild(world_data, ctx.guild.id).get("scheduled_announcements", {}).get(str(예약ID).upper())
        if not isinstance(row, dict):
            await ctx.send("예약 ID를 찾지 못했습니다.")
            return
        row["active"] = False
        row["cancelled_at"] = int(time.time())
        save_data()
        await ctx.send(f"✅ 예약 공지 `{예약ID}`를 취소했습니다.")

    @bot.command(name="보안센터", aliases=["securitycenter", "serversecurity"], help="AutoMod·안티레이드·비상모드·파괴 감시를 한 화면에서 확인합니다.")
    async def security_center(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        mgmt = _management(world_data, ctx.guild.id)
        anti = mgmt.get("anti_raid", {})
        auto = mgmt.get("automod", {})
        emergency = mgmt.get("emergency", {})
        security = _guild(world_data, ctx.guild.id).get("security", {})
        embed = discord.Embed(title="🛡️ ABADDON 보안 지휘센터", description="기존 SERVER GUARD를 새로 만들지 않고 한 화면에서 연결합니다.", color=0xED4245)
        embed.add_field(name="AutoMod", value=f"**{'켜짐' if auto.get('enabled') else '꺼짐'}** · `!자동관리`", inline=True)
        embed.add_field(name="안티레이드", value=f"**{'켜짐' if anti.get('enabled') else '꺼짐'}** · 자동잠금 {'ON' if anti.get('auto_lockdown') else 'OFF'}", inline=True)
        embed.add_field(name="비상모드", value=f"**{'활성' if emergency.get('active') else '정상'}** · `!비상모드`", inline=True)
        embed.add_field(name="🧯 파괴행위 감시", value=f"**{'켜짐' if security.get('destructive_watch_enabled') else '꺼짐'}** · {security.get('window_seconds',20)}초/{security.get('threshold',3)}건 경고\n채널/역할 삭제·웹훅 변화를 묶어서 보안 로그로 경고", inline=False)
        embed.set_footer(text="자동 파괴행위 차단은 기본 OFF · 감지 후 기존 !비상모드/!서버잠금 사용")
        await ctx.send(embed=embed, view=SecurityHubView(bot))

    @bot.command(name="파괴감시", aliases=["destructivewatch", "destructionwatch"], help="채널/역할 삭제·웹훅 변경 폭주 감시를 켜거나 끕니다.")
    async def destructive_watch(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await _require_manager_ctx(ctx):
            return
        sec = _guild(world_data, ctx.guild.id)["security"]
        if str(상태).casefold() in {"상태", "status"}:
            await ctx.send(f"🧯 파괴 감시 **{'켜짐' if sec.get('destructive_watch_enabled') else '꺼짐'}** · {sec.get('window_seconds')}초/{sec.get('threshold')}건")
            return
        value = _parse_toggle(상태)
        if value is None:
            await ctx.send("`!파괴감시 켜기` 또는 `!파괴감시 끄기`")
            return
        sec["destructive_watch_enabled"] = value
        save_data()
        await ctx.send(f"🧯 파괴 감시를 **{'켰습니다' if value else '껐습니다'}**.")

    @bot.command(name="파괴감시설정", aliases=["destructivewatchset"], help="파괴행위 경고 기준을 설정합니다. `!파괴감시설정 3 20`")
    async def destructive_watch_set(ctx: commands.Context, 건수: int = 3, 초: int = 20) -> None:
        if not await _require_manager_ctx(ctx):
            return
        if not 2 <= 건수 <= 20 or not 5 <= 초 <= 300:
            await ctx.send("범위: 2~20건 · 5~300초")
            return
        sec = _guild(world_data, ctx.guild.id)["security"]
        sec["threshold"] = int(건수)
        sec["window_seconds"] = int(초)
        save_data()
        await ctx.send(f"✅ 파괴 감시 기준을 **{초}초/{건수}건**으로 설정했습니다.")

    async def record_destructive(guild: discord.Guild, kind: str, detail: str) -> None:
        sec = _guild(world_data, guild.id)["security"]
        if not sec.get("destructive_watch_enabled", True):
            return
        now = int(time.time())
        window = max(5, int(sec.get("window_seconds", 20) or 20))
        events = sec.setdefault("events", [])
        events.append({"at": now, "kind": kind, "detail": _short(detail, 160)})
        events[:] = [x for x in events[-50:] if now - int(x.get("at", 0) or 0) <= max(window, 300)]
        recent = [x for x in events if now - int(x.get("at", 0) or 0) <= window]
        threshold = max(2, int(sec.get("threshold", 3) or 3))
        if len(recent) < threshold or now - int(sec.get("last_alert_at", 0) or 0) < 120:
            return
        sec["last_alert_at"] = now
        _root(world_data)["stats"]["security_alerts"] = int(_root(world_data)["stats"].get("security_alerts", 0)) + 1
        save_data()
        channel = _security_log_channel(world_data, guild)
        if channel is None:
            return
        embed = discord.Embed(title="🚨 ABADDON 파괴행위 폭주 감지", description=f"최근 **{window}초** 동안 서버 구조 변경이 **{len(recent)}건** 감지됐습니다.", color=0xED4245)
        embed.add_field(name="최근 이벤트", value="\n".join(f"• {x.get('kind')} · {x.get('detail')}" for x in recent[-8:])[:1024], inline=False)
        embed.add_field(name="권장 조치", value="`!보안센터` → 상황 확인 · 필요하면 `!비상모드 켜기` 또는 `!서버잠금 사유`", inline=False)
        embed.set_footer(text="오탐 방지를 위해 파괴감시는 기본적으로 자동 밴/삭제를 하지 않고 경고부터 전송합니다.")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @bot.listen("on_guild_channel_delete")
    async def v1890_channel_delete(channel: discord.abc.GuildChannel) -> None:
        await record_destructive(channel.guild, "채널 삭제", getattr(channel, "name", str(channel.id)))

    @bot.listen("on_guild_role_delete")
    async def v1890_role_delete(role: discord.Role) -> None:
        await record_destructive(role.guild, "역할 삭제", role.name)

    @bot.listen("on_webhooks_update")
    async def v1890_webhook_update(channel: discord.abc.GuildChannel) -> None:
        await record_destructive(channel.guild, "웹훅 변경", getattr(channel, "name", str(channel.id)))

    @bot.command(name="외부알림센터", aliases=["externalalerts", "streamalerts"], help="YouTube 새 영상과 Twitch 방송 시작 알림을 관리합니다.")
    async def external_center(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        await ctx.send(embed=_external_status_embed(world_data, ctx.guild), view=ExternalHubView(bot))

    @bot.command(name="외부알림상태", aliases=["externalalertstatus"], help="외부 알림 환경변수와 등록 수를 확인합니다.")
    async def external_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        await ctx.send(embed=_external_status_embed(world_data, ctx.guild))

    @bot.command(name="유튜브알림등록", aliases=["youtubealertadd", "youtubeadd"], help="YouTube 채널의 새 영상 알림을 등록합니다. 채널 ID(UC...) 또는 @핸들을 사용할 수 있습니다.")
    async def youtube_add(ctx: commands.Context, 채널ID: str, 알림채널: Optional[discord.TextChannel] = None) -> None:
        if not await _require_manager_ctx(ctx):
            return
        target = 알림채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("알림 텍스트 채널을 지정해주세요.")
            return
        requested = _clean_youtube_id(채널ID)
        ext = _guild(world_data, ctx.guild.id)["external"]["youtube"]
        await ctx.send("📺 YouTube 채널 정보를 확인하고 있습니다...")
        info = await _youtube_channel_info(requested)
        if not info.get("ok"):
            await ctx.send(f"❌ {info.get('error', 'YouTube API 오류')}")
            return
        channel_id = str(info.get("channel_id", requested))
        if channel_id not in ext and len(ext) >= MAX_EXTERNAL_SUBS:
            await ctx.send("YouTube 등록 한도에 도달했습니다.")
            return
        latest = await _youtube_latest(str(info["uploads"]))
        if not latest.get("ok"):
            await ctx.send(f"❌ 최신 영상 기준점을 확인하지 못했습니다: {latest.get('error', 'YouTube API 오류')}")
            return
        last_id = str((latest.get("video") or {}).get("id", ""))
        ext[channel_id] = {"channel_id": channel_id, "title": info["title"], "uploads_playlist_id": info["uploads"], "notify_channel_id": target.id, "last_video_id": last_id, "baseline_ready": True, "added_by": ctx.author.id, "added_at": int(time.time())}
        save_data()
        await ctx.send(f"✅ **{info['title']}** 새 영상 알림 → {target.mention}\n현재 최신 영상은 기준점으로 저장해 과거 영상은 다시 알리지 않습니다.")

    @bot.command(name="유튜브알림삭제", aliases=["youtubealertremove", "youtuberemove"], help="YouTube 새 영상 알림 등록을 삭제합니다.")
    async def youtube_remove(ctx: commands.Context, 채널ID: str) -> None:
        if not await _require_manager_ctx(ctx):
            return
        token = _clean_youtube_id(채널ID)
        ext = _guild(world_data, ctx.guild.id)["external"]["youtube"]
        removed = ext.pop(token, None)
        save_data()
        await ctx.send("✅ 삭제했습니다." if removed else "등록된 YouTube 채널을 찾지 못했습니다.")

    @bot.command(name="유튜브알림목록", aliases=["youtubealerts", "youtubelist"], help="등록된 YouTube 새 영상 알림을 확인합니다.")
    async def youtube_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        ext = _guild(world_data, ctx.guild.id)["external"]["youtube"]
        if not ext:
            await ctx.send("📺 등록된 YouTube 알림 없음 · `!유튜브알림등록 UC채널ID #채널`")
            return
        await ctx.send("📺 **YouTube 알림**\n" + "\n".join(f"• **{x.get('title', cid)}** · <#{x.get('notify_channel_id')}> · `{cid}`" for cid, x in list(ext.items())[:20]))

    @bot.command(name="트위치알림등록", aliases=["twitchalertadd", "twitchadd"], help="Twitch 채널 방송 시작 알림을 등록합니다.")
    async def twitch_add(ctx: commands.Context, 로그인명: str, 알림채널: Optional[discord.TextChannel] = None) -> None:
        if not await _require_manager_ctx(ctx):
            return
        target = 알림채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("알림 텍스트 채널을 지정해주세요.")
            return
        login = _clean_twitch_login(로그인명)
        ext = _guild(world_data, ctx.guild.id)["external"]["twitch"]
        if login not in ext and len(ext) >= MAX_EXTERNAL_SUBS:
            await ctx.send("Twitch 등록 한도에 도달했습니다.")
            return
        await ctx.send("🟣 Twitch 채널 정보를 확인하고 있습니다...")
        info = await _twitch_user(login)
        if not info.get("ok"):
            await ctx.send(f"❌ {info.get('error', 'Twitch API 오류')}")
            return
        live = await _twitch_stream(str(info["login"]))
        if not live.get("ok"):
            await ctx.send(f"❌ 방송 상태 기준점을 확인하지 못했습니다: {live.get('error', 'Twitch API 오류')}")
            return
        stream = live.get("stream")
        ext[str(info["login"])] = {"login": info["login"], "display_name": info["display_name"], "user_id": info["id"], "notify_channel_id": target.id, "last_live_id": str((stream or {}).get("id", "")), "was_live": bool(stream), "added_by": ctx.author.id, "added_at": int(time.time())}
        save_data()
        await ctx.send(f"✅ **{info['display_name']}** 방송 시작 알림 → {target.mention}")

    @bot.command(name="트위치알림삭제", aliases=["twitchalertremove", "twitchremove"], help="Twitch 방송 시작 알림 등록을 삭제합니다.")
    async def twitch_remove(ctx: commands.Context, 로그인명: str) -> None:
        if not await _require_manager_ctx(ctx):
            return
        token = _clean_twitch_login(로그인명)
        ext = _guild(world_data, ctx.guild.id)["external"]["twitch"]
        removed = ext.pop(token, None)
        save_data()
        await ctx.send("✅ 삭제했습니다." if removed else "등록된 Twitch 채널을 찾지 못했습니다.")

    @bot.command(name="트위치알림목록", aliases=["twitchalerts", "twitchlist"], help="등록된 Twitch 방송 시작 알림을 확인합니다.")
    async def twitch_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        ext = _guild(world_data, ctx.guild.id)["external"]["twitch"]
        if not ext:
            await ctx.send("🟣 등록된 Twitch 알림 없음 · `!트위치알림등록 채널명 #채널`")
            return
        await ctx.send("🟣 **Twitch 알림**\n" + "\n".join(f"• **{x.get('display_name', login)}** · <#{x.get('notify_channel_id')}> · `{login}`" for login, x in list(ext.items())[:20]))

    @tasks.loop(seconds=15)
    async def giveaway_loop() -> None:
        now = int(time.time())
        dirty = False
        for guild in list(bot.guilds):
            for giveaway in list(_guild(world_data, guild.id).get("giveaways", {}).values()):
                if isinstance(giveaway, dict) and not giveaway.get("ended") and int(giveaway.get("ends_at", 0) or 0) <= now:
                    await finish_giveaway(guild, giveaway)
                    dirty = True
        if dirty:
            save_data()

    @giveaway_loop.before_loop
    async def before_giveaway_loop() -> None:
        await bot.wait_until_ready()

    @tasks.loop(seconds=20)
    async def scheduled_announcement_loop() -> None:
        now = int(time.time())
        dirty = False
        for guild in list(bot.guilds):
            schedules = _guild(world_data, guild.id).get("scheduled_announcements", {})
            for row in list(schedules.values()):
                if not isinstance(row, dict) or not row.get("active") or int(row.get("next_at", 0) or 0) > now:
                    continue
                channel = guild.get_channel(_safe_int(row.get("channel_id"), 0))
                repeat = str(row.get("repeat", "once"))
                if repeat == "daily":
                    row["next_at"] = int(row.get("next_at", now)) + 86400
                elif repeat == "weekly":
                    row["next_at"] = int(row.get("next_at", now)) + 604800
                else:
                    row["active"] = False
                row["sent_count"] = int(row.get("sent_count", 0) or 0) + 1
                row["last_sent_at"] = now
                _root(world_data)["stats"]["scheduled_posts"] = int(_root(world_data)["stats"].get("scheduled_posts", 0)) + 1
                dirty = True
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(embed=_announce_embed(str(row.get("content", "")), repeat, str(row.get("id", "-"))))
                    except (discord.Forbidden, discord.HTTPException):
                        row["last_error"] = "send_failed"
        if dirty:
            save_data()

    @scheduled_announcement_loop.before_loop
    async def before_scheduled_loop() -> None:
        await bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def external_alert_loop() -> None:
        dirty = False
        for guild in list(bot.guilds):
            ext = _guild(world_data, guild.id).get("external", {})
            youtube = ext.get("youtube", {}) if isinstance(ext, Mapping) else {}
            for channel_id, sub in list(youtube.items())[:MAX_EXTERNAL_SUBS]:
                if not isinstance(sub, dict):
                    continue
                latest = await _youtube_latest(str(sub.get("uploads_playlist_id", "")))
                video = latest.get("video") if latest.get("ok") else None
                if not isinstance(video, Mapping) or not video.get("id"):
                    continue
                vid = str(video.get("id"))
                previous = str(sub.get("last_video_id", ""))
                if previous == vid:
                    continue
                sub["last_video_id"] = vid
                sub["last_checked_at"] = int(time.time())
                dirty = True
                target = guild.get_channel(_safe_int(sub.get("notify_channel_id"), 0))
                if isinstance(target, discord.TextChannel):
                    embed = discord.Embed(title="📺 새 YouTube 영상", description=f"**{video.get('title', '새 영상')}**", url=f"https://www.youtube.com/watch?v={vid}", color=0xFF0000)
                    embed.add_field(name="채널", value=str(sub.get("title", channel_id)), inline=True)
                    embed.set_footer(text="ABADDON 외부 알림")
                    try:
                        await target.send(embed=embed)
                        _root(world_data)["stats"]["youtube_alerts"] = int(_root(world_data)["stats"].get("youtube_alerts", 0)) + 1
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            twitch = ext.get("twitch", {}) if isinstance(ext, Mapping) else {}
            for login, sub in list(twitch.items())[:MAX_EXTERNAL_SUBS]:
                if not isinstance(sub, dict):
                    continue
                result = await _twitch_stream(str(login))
                stream = result.get("stream") if result.get("ok") else None
                if not isinstance(stream, Mapping):
                    sub["was_live"] = False
                    continue
                live_id = str(stream.get("id", ""))
                previous = str(sub.get("last_live_id", ""))
                was_live = bool(sub.get("was_live", False))
                sub["was_live"] = True
                sub["last_checked_at"] = int(time.time())
                if live_id and live_id != previous:
                    sub["last_live_id"] = live_id
                    dirty = True
                    should_send = bool(previous) or not was_live
                    if should_send:
                        target = guild.get_channel(_safe_int(sub.get("notify_channel_id"), 0))
                        if isinstance(target, discord.TextChannel):
                            embed = discord.Embed(title=f"🟣 {stream.get('user_name', login)} 방송 시작", description=str(stream.get("title", "방송이 시작됐습니다."))[:3900], url=f"https://www.twitch.tv/{login}", color=0x9146FF)
                            embed.add_field(name="카테고리", value=str(stream.get("game_name", "-")), inline=True)
                            embed.add_field(name="시청자", value=f"{_safe_int(stream.get('viewer_count'),0):,}명", inline=True)
                            thumb = str(stream.get("thumbnail_url", "")).replace("{width}", "640").replace("{height}", "360")
                            if thumb:
                                embed.set_image(url=thumb)
                            try:
                                await target.send(embed=embed)
                                _root(world_data)["stats"]["twitch_alerts"] = int(_root(world_data)["stats"].get("twitch_alerts", 0)) + 1
                            except (discord.Forbidden, discord.HTTPException):
                                pass
        if dirty:
            save_data()

    @external_alert_loop.before_loop
    async def before_external_loop() -> None:
        await bot.wait_until_ready()

    @bot.listen("on_ready")
    async def v1890_start_loops() -> None:
        for loop in (giveaway_loop, scheduled_announcement_loop, external_alert_loop):
            if not loop.is_running():
                try:
                    loop.start()
                except RuntimeError:
                    pass

    patch_check = bot.get_command("패치점검")
    if patch_check is not None:
        previous = patch_check.callback

        async def patch_check_v1890(ctx: commands.Context) -> None:
            embed = discord.Embed(title="🧪 ABADDON v18.9.0 통합 점검 목록", description="18.7~18.9를 한 번에 합친 뒤 직접 확인해야 할 핵심 항목입니다.", color=0xFEE75C)
            checks = [
                ("1) !자동화센터", "환영/자동역할/경품/투표/건의/예약공지 버튼 확인"),
                ("2) !경품시작 2 1 테스트경품", "참가 버튼 → 참가/취소 → 자동/수동 종료 확인"),
                ("3) !예약공지목록", "예약 저장/목록/취소 확인"),
                ("4) !보안센터", "AutoMod/안티레이드/비상모드/서버점검 버튼 확인"),
                ("5) !파괴감시", "상태 출력과 설정 저장 확인"),
                ("6) !외부알림상태", "YouTube/Twitch 환경변수 준비 여부 확인"),
                ("7) !명령어 / !로그", "스마트 검색/영구 메뉴 회귀"),
                ("8) !커뮤니티센터", "문의 모달 → 제작자 DM 회귀"),
                ("9) !웹대시보드", "자동화/보안 설정 항목 표시와 저장 확인"),
            ]
            for name, value in checks:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text="소유자 최종검수: !1890검수")
            await ctx.send(embed=embed)

        patch_check.callback = patch_check_v1890
        patch_check.help = "v18.9.0 통합 배포 후 직접 확인할 기능 목록입니다."
        patch_check.description = patch_check.help
        patch_check.extras = dict(getattr(patch_check, "extras", {}) or {})
        patch_check.extras["v1890_previous_callback"] = previous

    @bot.command(name="1890검수", aliases=["1890audit", "serverpackaudit"], hidden=True, help="[소유자 전용] v18.9 통합 기능과 중복 재사용 상태를 검사합니다.")
    @commands.is_owner()
    async def audit_1890(ctx: commands.Context) -> None:
        required = ["자동화센터", "경품", "경품시작", "예약공지", "보안센터", "파괴감시", "외부알림센터", "유튜브알림등록", "트위치알림등록", "패치점검"]
        reused = ["환영채널", "자동역할", "새싹설정", "환영테마", "투표", "건의", "건의목록", "일정", "일정등록", "자동관리", "안티레이드", "비상모드", "서버잠금"]
        rows = [(name, bot.get_command(name) is not None) for name in required]
        reuse_rows = [(name, bot.get_command(name) is not None) for name in reused]
        dup_ids: Dict[str, int] = {}
        for view in (GiveawayPersistentView(world_data, save_data), AutomationHubView(bot), SecurityHubView(bot), ExternalHubView(bot)):
            for child in view.children:
                cid = getattr(child, "custom_id", None)
                if cid:
                    dup_ids[cid] = dup_ids.get(cid, 0) + 1
        embed = discord.Embed(title="🧪 ABADDON v18.9.0 통합 검수", color=0x57F287 if all(ok for _, ok in rows + reuse_rows) and max(dup_ids.values(), default=0) <= 1 else 0xFEE75C)
        embed.add_field(name="신규/통합 기능", value="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in rows), inline=False)
        embed.add_field(name="중복 대신 재사용", value=" · ".join(f"{'✅' if ok else '❌'}{name}" for name, ok in reuse_rows), inline=False)
        embed.add_field(name="Persistent custom_id", value=f"검사 {len(dup_ids)}개 · 중복 {sum(1 for x in dup_ids.values() if x > 1)}개", inline=True)
        embed.add_field(name="외부 환경", value=f"YouTube {'✅' if os.getenv('YOUTUBE_API_KEY','').strip() else '➖'} · Twitch {'✅' if os.getenv('TWITCH_CLIENT_ID','').strip() and os.getenv('TWITCH_CLIENT_SECRET','').strip() else '➖'}", inline=True)
        stats = _root(world_data).get("stats", {})
        embed.add_field(name="v18.9 통계", value=" · ".join(f"{k}={v}" for k, v in stats.items()), inline=False)
        await ctx.send(embed=embed)

    # Refresh dynamic command registries after every new command is registered.
    try:
        command_hub._refresh_registry(bot)
    except Exception:
        pass
    try:
        from apocalypse_bot.commands.v1832_bilingual_persistent_hub import _sync_registry
        _sync_registry(bot)
    except Exception:
        pass

    print(
        f"[ABADDON v{VERSION}] automation/security/external registered · reuse=welcome,poll,suggestion,schedule,guard "
        f"new=giveaway,scheduled-announcement,destructive-watch,youtube,twitch",
        flush=True,
    )


def finalize_v1890_surfaces(bot: commands.Bot) -> None:
    bot.abaddon_version = VERSION
    intro = bot.get_command("봇소개")
    if intro is not None:
        async def intro_v1890(ctx: commands.Context) -> None:
            embed = discord.Embed(title="☣️ ABADDON · 종말 생존 + 서버 운영 플랫폼", description="RPG 기능과 서버 자동화·보안·외부 알림을 한 봇에서 연결합니다. 기능을 외우지 않아도 스마트 탐색과 통합 센터로 찾을 수 있습니다.", color=0xC8AA62)
            for name, value in [
                ("🎮 생존 RPG", "스토리·전투·채집·경제·길드·세계 이벤트"),
                ("🔎 UX", "`!로그` 같은 스마트 탐색 · `!즐겨찾기` · `!최근` · `!추천`"),
                ("⚙️ 서버 자동화", "`!자동화센터` · 환영/역할/경품/투표/건의/예약공지"),
                ("🛡️ 보안", "`!보안센터` · AutoMod · 안티레이드 · 비상모드 · 파괴감시"),
                ("📡 외부 알림", "`!외부알림센터` · YouTube 새 영상 · Twitch 방송 시작"),
                ("🌐 웹", "`!웹대시보드` · Discord OAuth 서버 설정"),
                ("🛟 장애 문의", "Discord DM `jjonga0022`"),
            ]:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=f"ABADDON v{VERSION} · support @jjonga0022")
            await ctx.send(embed=embed)
        intro.callback = intro_v1890
        intro.help = "ABADDON v18.9 최신 RPG·자동화·보안·외부 알림 기능을 확인합니다."
        intro.description = intro.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1890(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            embed = discord.Embed(title="🛰️ ABADDON v18.9.0 — SERVER AUTOMATION / SECURITY / EXTERNAL", color=0x5865F2)
            embed.description = "v18.7~18.9 계획을 한 번에 통합하면서 **이미 있는 기능은 중복 제작하지 않고 재사용**했습니다."
            embed.add_field(name="⚙️ v18.7 자동화", value="기존 환영·자동역할·투표·건의·일정 재사용 + 새 경품/자유문구 예약공지", inline=False)
            embed.add_field(name="🛡️ v18.8 보안", value="기존 AutoMod·안티레이드·서버잠금·비상모드 재사용 + 파괴행위 폭주 감시", inline=False)
            embed.add_field(name="📡 v18.9 외부 알림", value="YouTube 새 영상 · Twitch 방송 시작 알림 (환경변수 설정 시 활성)", inline=False)
            embed.add_field(name="🌐 대시보드", value="환영/자동역할/안티레이드/파괴감시 상태를 웹 설정에 추가", inline=False)
            embed.add_field(name="🧪 점검", value="`!패치점검` → 소유자 `!1890검수`", inline=False)
            embed.set_footer(text="기존 /var/data 유지 · 기존 명령/영문판/스마트 탐색 유지")
            await ctx.send(embed=embed)
        patch.callback = patch_v1890
        patch.help = "ABADDON v18.9.0 통합 자동화/보안/외부알림 패치노트입니다."
        patch.description = patch.help

    print(f"[ABADDON v{VERSION}] final public automation/security/external surfaces active", flush=True)
