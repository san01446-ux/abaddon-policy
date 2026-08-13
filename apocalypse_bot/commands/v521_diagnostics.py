from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v433_voice_sanctuary as voice_system


VERSION = "7.2.0"
DIAGNOSTIC_LOG_LIMIT = 30
DIAGNOSTIC_MENU_TIMEOUT = 300
RECENT_LOGS: Deque[str] = deque(maxlen=DIAGNOSTIC_LOG_LIMIT)


_SECRET_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(token|secret|api[_-]?key|relay[_-]?key)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[^\s]+", re.IGNORECASE),
    re.compile(r"https://discord\.com/api/webhooks/\d+/[^\s]+", re.IGNORECASE),
)


def _sanitize_log_line(value: Any) -> str:
    text = str(value or "").replace("\n", " ").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=[REDACTED]", text)
    return text[:500]


class _DiagnosticLogHandler(logging.Handler):
    _abaddon_v521_diagnostic_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = f"{record.levelname} {record.name}: {record.getMessage()}"
        except Exception:
            return
        RECENT_LOGS.append(_sanitize_log_line(line))


def _install_diagnostic_log_handler() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_abaddon_v521_diagnostic_handler", False) for handler in root.handlers):
        return
    handler = _DiagnosticLogHandler(level=logging.WARNING)
    root.addHandler(handler)


def _yes(value: Any) -> str:
    return "✅" if bool(value) else "❌"


def _on_off(value: Any) -> str:
    return "켜짐" if bool(value) else "꺼짐"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _duration(seconds: Any) -> str:
    total = max(0, _safe_int(seconds))
    if total <= 0:
        return "없음"
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def _timestamp(value: Any) -> str:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return "기록 없음"
    if ts <= 0:
        return "기록 없음"
    return f"<t:{ts}:R>"


def _channel(guild: discord.Guild, value: Any) -> Optional[discord.abc.GuildChannel]:
    channel_id = _safe_int(value)
    if not channel_id:
        return None
    channel = guild.get_channel(channel_id)
    return channel if isinstance(channel, discord.abc.GuildChannel) else None


def _channel_label(guild: discord.Guild, value: Any) -> str:
    channel = _channel(guild, value)
    return getattr(channel, "mention", "미설정") if channel is not None else "미설정"


def _management_settings(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = world_data.setdefault("server_management", {})
    settings = root.setdefault(str(guild_id), {})
    settings.setdefault("log_channel_id", 0)
    settings.setdefault("log_channels", {})
    if not isinstance(settings.get("log_channels"), dict):
        settings["log_channels"] = {}
    for log_type in ("security", "message", "member", "operation"):
        settings["log_channels"].setdefault(log_type, 0)
    settings.setdefault("welcome_channel_id", 0)
    settings.setdefault("welcome_notice_channel_id", 0)
    settings.setdefault("welcome_rules_channel_id", 0)
    settings.setdefault("welcome_register_channel_id", 0)
    settings.setdefault("leave_channel_id", 0)
    settings.setdefault("automod", {})
    settings.setdefault("auto_reactions", {})
    if not isinstance(settings.get("automod"), dict):
        settings["automod"] = {}
    if not isinstance(settings.get("auto_reactions"), dict):
        settings["auto_reactions"] = {}
    settings["automod"].setdefault("enabled", False)
    settings["auto_reactions"].setdefault("enabled", False)
    settings["auto_reactions"].setdefault("channels", {})
    return settings


def _feed_settings(world_data: Dict[str, Any]) -> Dict[str, Any]:
    feed = world_data.setdefault("public_feed_v432", {})
    if not isinstance(feed, dict):
        feed = {}
        world_data["public_feed_v432"] = feed
    feed.setdefault("enabled", True)
    feed.setdefault("events", [])
    feed.setdefault("last_sequence", 0)
    if not isinstance(feed.get("events"), list):
        feed["events"] = []
    return feed


def _data_file_state(data_file: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(data_file)
    result: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "readable": False,
        "writable": False,
        "valid_json": False,
        "size": 0,
        "users": len(user_data),
        "error": "",
    }
    try:
        if path.exists():
            result["size"] = path.stat().st_size
            result["readable"] = os.access(path, os.R_OK)
            result["writable"] = os.access(path, os.W_OK)
            with path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            result["valid_json"] = isinstance(loaded, dict)
        else:
            parent = path.parent if str(path.parent) else Path(".")
            result["writable"] = parent.exists() and os.access(parent, os.W_OK)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return result


def _command_children(command: Any) -> Sequence[Any]:
    children = getattr(command, "commands", None)
    return list(children) if isinstance(children, (list, tuple)) else []


def _slash_state(bot: commands.Bot) -> Dict[str, Any]:
    try:
        top = list(bot.tree.get_commands())
    except Exception:
        top = []
    try:
        walked = list(bot.tree.walk_commands())
    except Exception:
        walked = list(top)

    paths: List[str] = []
    invalid: List[str] = []
    oversized_groups: List[str] = []
    duplicate_paths: List[str] = []
    seen: set[str] = set()

    for command in walked:
        path = str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "?")
        paths.append(path)
        folded = path.casefold()
        if folded in seen:
            duplicate_paths.append(path)
        seen.add(folded)

        name = str(getattr(command, "name", "") or "")
        if not (1 <= len(name) <= 32) or any("A" <= char <= "Z" for char in name):
            invalid.append(path)
        parameters = getattr(command, "parameters", [])
        try:
            iterable_parameters = list(parameters)
        except TypeError:
            iterable_parameters = []
        for parameter in iterable_parameters:
            parameter_name = str(getattr(parameter, "name", "") or "")
            if not (1 <= len(parameter_name) <= 32) or any("A" <= char <= "Z" for char in parameter_name):
                invalid.append(f"{path}:{parameter_name}")

    for command in top:
        children = _command_children(command)
        if len(children) > 25:
            oversized_groups.append(f"{getattr(command, 'name', '?')}={len(children)}")

    return {
        "top": len(top),
        "total": len(walked),
        "invalid": sorted(set(invalid)),
        "duplicates": sorted(set(duplicate_paths)),
        "oversized_groups": oversized_groups,
        "sync_status": str(getattr(bot, "_abaddon_slash_sync_status", "unknown")),
        "sync_error": _sanitize_log_line(getattr(bot, "_abaddon_slash_sync_error", "")),
        "sync_count": _safe_int(getattr(bot, "_abaddon_slash_sync_count", 0)),
        "sync_at": str(getattr(bot, "_abaddon_slash_sync_at", "")),
        "within_top_limit": len(top) <= 100,
    }


def _permission_state(guild: discord.Guild, channel: discord.abc.GuildChannel) -> Dict[str, Any]:
    me = guild.me
    if me is None:
        return {"missing": ["봇 멤버 객체"], "voice_ok": False, "channel_ok": False}
    guild_perms = me.guild_permissions
    required_guild = {
        "채널 관리": guild_perms.manage_channels,
        "역할 관리": guild_perms.manage_roles,
        "서버 관리": guild_perms.manage_guild,
        "감사 로그 보기": guild_perms.view_audit_log,
        "멤버 추방": guild_perms.kick_members,
        "멤버 차단": guild_perms.ban_members,
    }
    missing = [name for name, allowed in required_guild.items() if not allowed]
    channel_perms = channel.permissions_for(me)
    channel_ok = bool(channel_perms.view_channel and channel_perms.send_messages and channel_perms.embed_links)
    if not channel_ok:
        missing.append("현재 채널 보기·메시지·임베드")

    voice_channels = list(guild.voice_channels)
    voice_ok = False
    if voice_channels:
        voice_ok = any(
            voice_channel.permissions_for(me).connect and voice_channel.permissions_for(me).speak
            for voice_channel in voice_channels
        )
    else:
        voice_ok = True
    if not voice_ok:
        missing.append("음성 채널 연결·말하기")
    return {"missing": missing, "voice_ok": voice_ok, "channel_ok": channel_ok}


def _renewal_summary(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    layout = voice_system._layout_settings(world_data, guild_id)["layout"]
    plan = layout.get("renewal_plan") if isinstance(layout.get("renewal_plan"), dict) else None
    recovery = layout.get("recovery_plan") if isinstance(layout.get("recovery_plan"), dict) else None
    active_plan = recovery or plan
    actions = list(active_plan.get("actions", [])) if active_plan else []
    index = _safe_int(active_plan.get("index", 0)) if active_plan else 0
    autopilot = layout.get("autopilot") if isinstance(layout.get("autopilot"), dict) else {}
    auto_task = voice_system.RENEWAL_AUTOPILOT_TASKS.get(guild_id)
    return {
        "plan_kind": "복구" if recovery else ("리뉴얼" if plan else "없음"),
        "plan_status": str(active_plan.get("status", "없음")) if active_plan else "없음",
        "index": min(index, len(actions)),
        "total": len(actions),
        "next_run_at": _safe_int(active_plan.get("next_run_at", 0)) if active_plan else 0,
        "backups": len(voice_system._backup_candidates(layout)),
        "autopilot_enabled": bool(autopilot.get("enabled")),
        "autopilot_running": bool(auto_task and not auto_task.done()),
        "autopilot_reason": str(autopilot.get("last_reason") or "기록 없음"),
        "quarantine": voice_system._renewal_quarantine_remaining(),
    }


def _tts_summary(world_data: Dict[str, Any], guild: discord.Guild) -> Dict[str, Any]:
    settings = voice_system._layout_settings(world_data, guild.id)["tts"]
    has_nacl, has_davey, has_edge = voice_system._dependency_state()
    ffmpeg = shutil.which("ffmpeg") is not None
    queue = voice_system.VOICE_RUNTIME.queue_for(guild.id)
    quarantined: List[str] = []
    for edge_voice, display_name in voice_system.EDGE_VOICE_TO_NAME.items():
        remaining = voice_system._edge_voice_quarantine_remaining(edge_voice)
        if remaining > 0:
            quarantined.append(f"{display_name}({_duration(remaining)})")
    return {
        "enabled": bool(settings.get("enabled")),
        "text_channel": _channel_label(guild, settings.get("text_channel_id")),
        "mode": "작성자 음성방 자동" if settings.get("mode") == "author_voice" else "고정 음성방",
        "engine": str(settings.get("engine", "auto")),
        "voice": str(settings.get("voice", "선히")),
        "queue": queue.qsize(),
        "speaking": bool(voice_system.VOICE_RUNTIME.speaking.get(guild.id)),
        "provider": str(settings.get("last_provider") or "재생 기록 없음"),
        "dependencies_ok": bool(has_nacl and has_davey and ffmpeg),
        "dependency_lines": [
            f"PyNaCl {_yes(has_nacl)}",
            f"davey {_yes(has_davey)}",
            f"edge-tts {_yes(has_edge)}",
            f"FFmpeg {_yes(ffmpeg)}",
        ],
        "quarantined": quarantined,
    }


def _feed_summary(world_data: Dict[str, Any], bot: commands.Bot) -> Dict[str, Any]:
    feed = _feed_settings(world_data)
    events = feed.get("events", [])
    latest = events[0] if events and isinstance(events[0], dict) else {}
    relay_url = os.getenv("PUBLIC_FEED_RELAY_URL", "").strip()
    relay_key = os.getenv("PUBLIC_FEED_RELAY_KEY", "").strip()
    heartbeat = _safe_int(os.getenv("PUBLIC_FEED_HEARTBEAT_SECONDS", "45"), 45)
    server_info = getattr(bot, "abaddon_public_feed_server", {})
    return {
        "enabled": bool(feed.get("enabled", True)),
        "events": len(events),
        "last_event": str(latest.get("created_at") or "기록 없음"),
        "relay_url": bool(relay_url),
        "relay_key": bool(relay_key),
        "heartbeat": heartbeat,
        "embedded_server": bool(isinstance(server_info, dict) and server_info.get("enabled")),
    }


def _overall_embed(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    data_file: str,
    guild: discord.Guild,
    channel: discord.abc.GuildChannel,
) -> discord.Embed:
    data_state = _data_file_state(data_file, user_data)
    slash = _slash_state(bot)
    tts = _tts_summary(world_data, guild)
    renewal = _renewal_summary(world_data, guild.id)
    feed = _feed_summary(world_data, bot)
    management = _management_settings(world_data, guild.id)
    perms = _permission_state(guild, channel)

    issues: List[str] = []
    if not bot.is_ready():
        issues.append("Discord 연결 대기")
    if not data_state["valid_json"] and data_state["exists"]:
        issues.append("데이터 JSON 점검 필요")
    if not slash["within_top_limit"] or slash["invalid"] or slash["duplicates"] or slash["oversized_groups"]:
        issues.append("슬래시 점검 필요")
    if not tts["dependencies_ok"]:
        issues.append("TTS 의존성 점검 필요")
    if renewal["quarantine"]:
        issues.append("리뉴얼 429 격리 중")
    if perms["missing"]:
        issues.append("봇 권한 부족")

    color = 0x57F287 if not issues else 0xFEE75C
    embed = discord.Embed(
        title=f"🩺 ABADDON v{VERSION} 통합 진단",
        description=("✅ 주요 시스템이 정상 범위입니다." if not issues else "⚠️ " + " · ".join(issues[:5])),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    latency_ms = max(0, int(float(getattr(bot, "latency", 0.0) or 0.0) * 1000))
    embed.add_field(
        name="Discord",
        value=f"연결 {_yes(bot.is_ready())} · 지연 {latency_ms}ms\n서버 {len(bot.guilds)}개",
        inline=True,
    )
    embed.add_field(
        name="데이터",
        value=(
            f"파일 {_yes(data_state['exists'])} · JSON {_yes(data_state['valid_json'])}\n"
            f"생존자 {data_state['users']:,}명 · {data_state['size'] / 1024:.1f}KB"
        ),
        inline=True,
    )
    embed.add_field(
        name="슬래시",
        value=f"최상위 {slash['top']}/100 · 전체 {slash['total']}\n동기화 {slash['sync_status']}",
        inline=True,
    )
    embed.add_field(
        name="TTS",
        value=(
            f"{_on_off(tts['enabled'])} · {tts['engine']} · {tts['voice']}\n"
            f"대기열 {tts['queue']} · {'재생 중' if tts['speaking'] else '대기'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="서버 리뉴얼",
        value=(
            f"{renewal['plan_kind']} {renewal['index']}/{renewal['total']} · 자동 {_on_off(renewal['autopilot_running'])}\n"
            f"429 격리 {_duration(renewal['quarantine'])}"
        ),
        inline=True,
    )
    embed.add_field(
        name="홈페이지 피드",
        value=f"공개 {_on_off(feed['enabled'])} · 릴레이 {_yes(feed['relay_url'] and feed['relay_key'])}\n이벤트 {feed['events']}개",
        inline=True,
    )
    embed.add_field(
        name="운영 설정",
        value=(
            f"로그 {_channel_label(guild, management.get('log_channel_id'))}\n"
            f"환영 {_channel_label(guild, management.get('welcome_channel_id'))}\n"
            f"자동 이모지 {_on_off(management['auto_reactions'].get('enabled'))}"
        ),
        inline=False,
    )
    if perms["missing"]:
        embed.add_field(name="부족한 권한", value=" · ".join(perms["missing"][:8]), inline=False)
    embed.set_footer(text="아래 드롭다운에서 세부 진단 또는 복사용 보고서를 선택하세요.")
    return embed


def _tts_embed(world_data: Dict[str, Any], guild: discord.Guild) -> discord.Embed:
    tts = _tts_summary(world_data, guild)
    settings = voice_system._layout_settings(world_data, guild.id)["tts"]
    embed = discord.Embed(title="🎙️ TTS 진단", color=0x5865F2, timestamp=discord.utils.utcnow())
    embed.add_field(name="자동 낭독", value=f"{_on_off(tts['enabled'])}\n채널 {tts['text_channel']}\n대상 {tts['mode']}", inline=True)
    embed.add_field(name="합성 설정", value=f"엔진 **{tts['engine']}**\n기본 목소리 **{tts['voice']}**\n속도 {settings.get('speed', 1.0)}배", inline=True)
    embed.add_field(name="실행 환경", value="\n".join(tts["dependency_lines"]), inline=True)
    embed.add_field(name="재생", value=f"상태 {'재생 중' if tts['speaking'] else '대기'}\n대기열 {tts['queue']}/{voice_system.TTS_QUEUE_LIMIT}\n최근 {tts['provider'][:80]}", inline=False)
    if tts["quarantined"]:
        embed.add_field(name="Edge 임시 격리", value="\n".join(tts["quarantined"][:10]), inline=False)
    return embed


def _renewal_embed(world_data: Dict[str, Any], guild: discord.Guild) -> discord.Embed:
    state = _renewal_summary(world_data, guild.id)
    embed = discord.Embed(title="🛰️ 서버 리뉴얼 진단", color=0x6D2335, timestamp=discord.utils.utcnow())
    embed.add_field(name="현재 계획", value=f"종류 **{state['plan_kind']}**\n상태 **{state['plan_status']}**\n진행 {state['index']}/{state['total']}", inline=True)
    embed.add_field(name="자동 진행", value=f"저장 설정 {_on_off(state['autopilot_enabled'])}\n실행 작업 {_on_off(state['autopilot_running'])}\n{state['autopilot_reason'][:120]}", inline=True)
    embed.add_field(name="안전 상태", value=f"429 격리 {_duration(state['quarantine'])}\n다음 가능 {_timestamp(state['next_run_at'])}\n백업 {state['backups']}개", inline=False)
    embed.add_field(name="안전 고정값", value=f"단계 간격 {voice_system.RENEWAL_STEP_COOLDOWN // 60}분 · 429 격리 {voice_system.RENEWAL_429_QUARANTINE // 60}분 · API 제한 {int(voice_system.RENEWAL_API_TIMEOUT)}초", inline=False)
    return embed


def _slash_embed(bot: commands.Bot) -> discord.Embed:
    state = _slash_state(bot)
    color = 0x57F287 if state["within_top_limit"] and not state["invalid"] and not state["duplicates"] and not state["oversized_groups"] else 0xED4245
    embed = discord.Embed(title="⌨️ 슬래시 명령 진단", color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="등록 개수", value=f"최상위 **{state['top']}/100**\n전체 경로 **{state['total']}**", inline=True)
    embed.add_field(name="마지막 동기화", value=f"상태 **{state['sync_status']}**\n개수 {state['sync_count']}\n{state['sync_at'] or '시간 기록 없음'}", inline=True)
    problems: List[str] = []
    if state["invalid"]:
        problems.append("잘못된 이름: " + ", ".join(state["invalid"][:8]))
    if state["duplicates"]:
        problems.append("중복 경로: " + ", ".join(state["duplicates"][:8]))
    if state["oversized_groups"]:
        problems.append("25개 초과 그룹: " + ", ".join(state["oversized_groups"][:8]))
    if state["sync_error"]:
        problems.append("동기화 오류: " + state["sync_error"][:300])
    embed.add_field(name="검사 결과", value="\n".join(problems) if problems else "✅ 이름·중복·그룹 개수 검사 통과", inline=False)
    return embed


def _feed_embed(world_data: Dict[str, Any], bot: commands.Bot) -> discord.Embed:
    feed = _feed_summary(world_data, bot)
    embed = discord.Embed(title="🌐 홈페이지 실시간 피드 진단", color=0x9B59B6, timestamp=discord.utils.utcnow())
    embed.add_field(name="공개 상태", value=f"피드 {_on_off(feed['enabled'])}\n로컬 이벤트 {feed['events']}개\n마지막 {feed['last_event']}", inline=True)
    embed.add_field(name="Render 릴레이", value=f"URL {_yes(feed['relay_url'])}\n비밀키 {_yes(feed['relay_key'])}\n심박 {feed['heartbeat']}초", inline=True)
    embed.add_field(name="내장 HTTP", value=_on_off(feed["embedded_server"]), inline=True)
    embed.set_footer(text="비밀키 값은 진단 화면과 보고서에 표시하지 않습니다.")
    return embed


def _permission_embed(guild: discord.Guild, channel: discord.abc.GuildChannel) -> discord.Embed:
    state = _permission_state(guild, channel)
    color = 0x57F287 if not state["missing"] else 0xFEE75C
    embed = discord.Embed(title="🛡️ 봇 권한 진단", color=color, timestamp=discord.utils.utcnow())
    me = guild.me
    if me is None:
        embed.description = "❌ 봇 멤버 객체를 확인하지 못했습니다."
        return embed
    perms = me.guild_permissions
    checks = [
        ("관리자", perms.administrator),
        ("채널 관리", perms.manage_channels),
        ("역할 관리", perms.manage_roles),
        ("서버 관리", perms.manage_guild),
        ("감사 로그", perms.view_audit_log),
        ("멤버 추방", perms.kick_members),
        ("멤버 차단", perms.ban_members),
        ("음성 연결·말하기", state["voice_ok"]),
        ("현재 채널 메시지·임베드", state["channel_ok"]),
    ]
    embed.description = "\n".join(f"{_yes(ok)} {name}" for name, ok in checks)
    if state["missing"]:
        embed.add_field(name="점검 필요", value=" · ".join(state["missing"][:10]), inline=False)
    return embed


def _settings_embed(world_data: Dict[str, Any], guild: discord.Guild) -> discord.Embed:
    management = _management_settings(world_data, guild.id)
    tts = voice_system._layout_settings(world_data, guild.id)["tts"]
    feed = _feed_settings(world_data)
    renewal = _renewal_summary(world_data, guild.id)
    embed = discord.Embed(
        title="⚙️ ABADDON 서버 설정 제어실",
        description="아래 드롭다운에서 바꿀 항목을 선택하세요. 채널 설정은 별도 채널 선택창이 열립니다.",
        color=0x5865F2,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="TTS",
        value=(
            f"채널 {_channel_label(guild, tts.get('text_channel_id'))}\n"
            f"엔진 **{tts.get('engine', 'auto')}** · 기본 **{tts.get('voice', '선히')}** · {_on_off(tts.get('enabled'))}"
        ),
        inline=False,
    )
    embed.add_field(
        name="신규 멤버 안내",
        value=(
            f"환영 {_channel_label(guild, management.get('welcome_channel_id'))}\n"
            f"공지 {_channel_label(guild, management.get('welcome_notice_channel_id'))} · "
            f"규칙 {_channel_label(guild, management.get('welcome_rules_channel_id'))} · "
            f"가입 {_channel_label(guild, management.get('welcome_register_channel_id'))}"
        ),
        inline=False,
    )
    embed.add_field(
        name="운영",
        value=(
            f"로그 {_channel_label(guild, management.get('log_channel_id'))}\n"
            f"자동 이모지 {_on_off(management['auto_reactions'].get('enabled'))} · "
            f"홈페이지 피드 {_on_off(feed.get('enabled', True))}"
        ),
        inline=False,
    )
    embed.add_field(
        name="리뉴얼 안전",
        value=f"자동 진행 {_on_off(renewal['autopilot_running'])} · 429 격리 {_duration(renewal['quarantine'])}",
        inline=False,
    )
    return embed


def _report_text(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    data_file: str,
    guild: discord.Guild,
    channel: discord.abc.GuildChannel,
) -> Tuple[str, str]:
    data_state = _data_file_state(data_file, user_data)
    slash = _slash_state(bot)
    tts = _tts_summary(world_data, guild)
    renewal = _renewal_summary(world_data, guild.id)
    feed = _feed_summary(world_data, bot)
    management = _management_settings(world_data, guild.id)
    perms = _permission_state(guild, channel)
    now = datetime.now(timezone.utc).isoformat()
    report_seed = f"{VERSION}|{guild.id}|{now}|{slash['top']}|{renewal['index']}|{tts['engine']}"
    report_code = hashlib.sha256(report_seed.encode("utf-8")).hexdigest()[:12].upper()
    lines = [
        f"ABADDON v{VERSION} DIAGNOSTIC REPORT",
        f"REPORT CODE: {report_code}",
        f"UTC: {now}",
        f"GUILD: {guild.name} ({guild.id})",
        "",
        "[DISCORD]",
        f"ready={bot.is_ready()} latency_ms={int(float(getattr(bot, 'latency', 0.0) or 0.0) * 1000)} guilds={len(bot.guilds)}",
        "",
        "[DATA]",
        f"exists={data_state['exists']} readable={data_state['readable']} writable={data_state['writable']} valid_json={data_state['valid_json']} size={data_state['size']} users={data_state['users']}",
        f"error={data_state['error'] or 'none'}",
        "",
        "[SLASH]",
        f"top={slash['top']}/100 total={slash['total']} sync={slash['sync_status']} sync_count={slash['sync_count']}",
        f"invalid={slash['invalid'] or 'none'}",
        f"duplicates={slash['duplicates'] or 'none'}",
        f"oversized_groups={slash['oversized_groups'] or 'none'}",
        f"sync_error={slash['sync_error'] or 'none'}",
        "",
        "[TTS]",
        f"enabled={tts['enabled']} channel={tts['text_channel']} mode={tts['mode']} engine={tts['engine']} default_voice={tts['voice']}",
        f"dependencies_ok={tts['dependencies_ok']} queue={tts['queue']} speaking={tts['speaking']} provider={tts['provider']}",
        f"quarantined={tts['quarantined'] or 'none'}",
        "",
        "[RENEWAL]",
        f"kind={renewal['plan_kind']} status={renewal['plan_status']} progress={renewal['index']}/{renewal['total']}",
        f"autopilot_enabled={renewal['autopilot_enabled']} autopilot_running={renewal['autopilot_running']} backups={renewal['backups']} quarantine_seconds={renewal['quarantine']}",
        "",
        "[OPERATIONS]",
        f"log_channel={_channel_label(guild, management.get('log_channel_id'))}",
        f"welcome_channel={_channel_label(guild, management.get('welcome_channel_id'))}",
        f"auto_reactions={management['auto_reactions'].get('enabled', False)} automod={management['automod'].get('enabled', False)}",
        "",
        "[PUBLIC FEED]",
        f"enabled={feed['enabled']} relay_url_configured={feed['relay_url']} relay_key_configured={feed['relay_key']} events={feed['events']} last_event={feed['last_event']}",
        "",
        "[PERMISSIONS]",
        f"missing={perms['missing'] or 'none'}",
        "",
        "[RECENT WARNING/ERROR LOGS]",
    ]
    if RECENT_LOGS:
        lines.extend(f"- {line}" for line in list(RECENT_LOGS)[-10:])
    else:
        lines.append("- none captured since v6.1.0 startup")
    lines.append("")
    lines.append("Secrets and token values are intentionally excluded.")
    return report_code, "\n".join(lines)


def register_v521_diagnostics(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
    *,
    data_file: str,
    user_data: Dict[str, Any],
) -> None:
    if getattr(bot, "_abaddon_v521_diagnostics_registered", False):
        return
    setattr(bot, "_abaddon_v521_diagnostics_registered", True)
    setattr(bot, "abaddon_version", VERSION)
    _install_diagnostic_log_handler()

    async def require_admin(ctx: commands.Context) -> Optional[discord.Guild]:
        guild = ctx.guild
        if guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return None
        if not (ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_guild):
            await ctx.send("❌ 서버 관리자만 사용할 수 있습니다.")
            return None
        return guild

    def interaction_allowed(interaction: discord.Interaction, owner_id: int, guild_id: int) -> bool:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        return bool(
            getattr(interaction.guild, "id", None) == guild_id
            and member is not None
            and member.id == owner_id
            and (member.guild_permissions.administrator or member.guild_permissions.manage_guild)
        )

    class DiagnosticSelect(discord.ui.Select):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            self.owner_id = owner_id
            self.guild_id = guild_id
            options = [
                discord.SelectOption(label="전체 진단 새로고침", value="overall", emoji="🩺", description="주요 시스템을 한 화면에서 다시 확인"),
                discord.SelectOption(label="TTS 진단", value="tts", emoji="🎙️", description="음성 의존성·대기열·합성 경로"),
                discord.SelectOption(label="서버 리뉴얼 진단", value="renewal", emoji="🛰️", description="계획·백업·자동 진행·429 상태"),
                discord.SelectOption(label="슬래시 명령 진단", value="slash", emoji="⌨️", description="100개 제한·이름·중복·동기화"),
                discord.SelectOption(label="홈페이지 피드 진단", value="feed", emoji="🌐", description="릴레이 환경과 최근 공개 이벤트"),
                discord.SelectOption(label="봇 권한 진단", value="permissions", emoji="🛡️", description="채널·역할·음성·운영 권한"),
                discord.SelectOption(label="오류 보고서 생성", value="report", emoji="📄", description="비밀값을 제외한 복사용 진단 파일"),
            ]
            super().__init__(placeholder="확인할 진단 항목을 선택하세요", min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            if not interaction_allowed(interaction, self.owner_id, self.guild_id):
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            guild = interaction.guild
            channel = interaction.channel
            if guild is None or not isinstance(channel, discord.abc.GuildChannel):
                await interaction.response.send_message("❌ 서버 채널 정보를 확인하지 못했습니다.", ephemeral=True)
                return
            choice = self.values[0]
            if choice == "overall":
                embed = _overall_embed(bot, world_data, user_data, data_file, guild, channel)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            if choice == "tts":
                await interaction.response.send_message(embed=_tts_embed(world_data, guild), ephemeral=True)
                return
            if choice == "renewal":
                await interaction.response.send_message(embed=_renewal_embed(world_data, guild), ephemeral=True)
                return
            if choice == "slash":
                await interaction.response.send_message(embed=_slash_embed(bot), ephemeral=True)
                return
            if choice == "feed":
                await interaction.response.send_message(embed=_feed_embed(world_data, bot), ephemeral=True)
                return
            if choice == "permissions":
                await interaction.response.send_message(embed=_permission_embed(guild, channel), ephemeral=True)
                return
            code, report = _report_text(bot, world_data, user_data, data_file, guild, channel)
            payload = io.BytesIO(report.encode("utf-8"))
            file = discord.File(payload, filename=f"ABADDON_DIAGNOSTIC_{code}.txt")
            await interaction.response.send_message(
                f"📄 진단 보고서를 생성했습니다. 보고 코드: `{code}`\n토큰·비밀키 값은 포함하지 않았습니다.",
                file=file,
                ephemeral=True,
            )

    class DiagnosticView(discord.ui.View):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            super().__init__(timeout=DIAGNOSTIC_MENU_TIMEOUT)
            self.add_item(DiagnosticSelect(owner_id, guild_id))

    class ConfigChannelSelect(discord.ui.ChannelSelect):
        def __init__(self, owner_id: int, guild_id: int, kind: str) -> None:
            self.owner_id = owner_id
            self.guild_id = guild_id
            self.kind = kind
            labels = {
                "tts": "TTS 텍스트 채널",
                "welcome": "환영 메시지 채널",
                "notice": "환영문 공지 링크 채널",
                "rules": "환영문 규칙 링크 채널",
                "register": "환영문 가입 링크 채널",
                "log": "운영 통합 로그 채널",
            }
            super().__init__(
                placeholder=f"{labels.get(kind, '설정 채널')}을 선택하세요",
                min_values=1,
                max_values=1,
                channel_types=[discord.ChannelType.text],
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if not interaction_allowed(interaction, self.owner_id, self.guild_id):
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("❌ 서버 정보를 확인하지 못했습니다.", ephemeral=True)
                return
            selected = self.values[0]
            channel_id = _safe_int(getattr(selected, "id", 0))
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("❌ 텍스트 채널만 선택할 수 있습니다.", ephemeral=True)
                return
            management = _management_settings(world_data, guild.id)
            if self.kind == "tts":
                tts = voice_system._layout_settings(world_data, guild.id)["tts"]
                tts.update({
                    "text_channel_id": channel.id,
                    "enabled": True,
                    "auto_join": True,
                    "require_author_in_voice": True,
                    "mode": "author_voice",
                })
                message = f"✅ TTS 채널을 {channel.mention}로 지정했습니다. 작성자의 현재 음성방을 자동 감지합니다."
            elif self.kind == "welcome":
                management["welcome_channel_id"] = channel.id
                message = f"✅ 환영 메시지 채널을 {channel.mention}로 지정했습니다."
            elif self.kind == "notice":
                management["welcome_notice_channel_id"] = channel.id
                message = f"✅ 환영문 공지 링크 채널을 {channel.mention}로 지정했습니다."
            elif self.kind == "rules":
                management["welcome_rules_channel_id"] = channel.id
                message = f"✅ 환영문 규칙 링크 채널을 {channel.mention}로 지정했습니다."
            elif self.kind == "register":
                management["welcome_register_channel_id"] = channel.id
                message = f"✅ 환영문 가입 링크 채널을 {channel.mention}로 지정했습니다."
            else:
                management["log_channel_id"] = channel.id
                management.setdefault("log_channels", {})["operation"] = channel.id
                message = f"✅ 운영 통합 로그 채널을 {channel.mention}로 지정했습니다."
            save_data()
            await interaction.response.send_message(message, ephemeral=True)

    class ConfigChannelView(discord.ui.View):
        def __init__(self, owner_id: int, guild_id: int, kind: str) -> None:
            super().__init__(timeout=DIAGNOSTIC_MENU_TIMEOUT)
            self.add_item(ConfigChannelSelect(owner_id, guild_id, kind))

    class EngineSelect(discord.ui.Select):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            self.owner_id = owner_id
            self.guild_id = guild_id
            options = [
                discord.SelectOption(label="자동", value="auto", emoji="🔁", description="Edge 실패 시 Google 자동 우회"),
                discord.SelectOption(label="Edge 전용", value="edge", emoji="🟦", description="개인 목소리를 우선하지만 실패 시 메시지 중단"),
                discord.SelectOption(label="Google 전용", value="google", emoji="🟨", description="목소리 구분보다 안정성을 우선"),
            ]
            super().__init__(placeholder="TTS 엔진을 선택하세요", min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            if not interaction_allowed(interaction, self.owner_id, self.guild_id):
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            settings = voice_system._layout_settings(world_data, self.guild_id)["tts"]
            settings["engine"] = self.values[0]
            save_data()
            await interaction.response.send_message(f"✅ TTS 엔진을 **{self.values[0]}**으로 저장했습니다.", ephemeral=True)

    class EngineView(discord.ui.View):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            super().__init__(timeout=DIAGNOSTIC_MENU_TIMEOUT)
            self.add_item(EngineSelect(owner_id, guild_id))

    class VoiceSelect(discord.ui.Select):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            self.owner_id = owner_id
            self.guild_id = guild_id
            options = [
                discord.SelectOption(
                    label=name,
                    value=name,
                    description=data["label"][:100],
                    emoji="👩" if data["gender"] == "여성" else "👨",
                )
                for name, data in voice_system.VOICE_PRESETS.items()
            ]
            super().__init__(placeholder="서버 기본 TTS 목소리를 선택하세요", min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            if not interaction_allowed(interaction, self.owner_id, self.guild_id):
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            settings = voice_system._layout_settings(world_data, self.guild_id)["tts"]
            settings["voice"] = self.values[0]
            save_data()
            await interaction.response.send_message(f"✅ 서버 기본 TTS 목소리를 **{self.values[0]}**으로 저장했습니다.", ephemeral=True)

    class VoiceView(discord.ui.View):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            super().__init__(timeout=DIAGNOSTIC_MENU_TIMEOUT)
            self.add_item(VoiceSelect(owner_id, guild_id))

    class SettingsSelect(discord.ui.Select):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            self.owner_id = owner_id
            self.guild_id = guild_id
            options = [
                discord.SelectOption(label="현재 설정 새로고침", value="summary", emoji="📋", description="저장된 서버 설정을 다시 확인"),
                discord.SelectOption(label="TTS 채널 지정", value="tts_channel", emoji="🎙️", description="텍스트 채널을 선택하고 자동 음성방 감지 켜기"),
                discord.SelectOption(label="TTS 엔진 변경", value="tts_engine", emoji="🔁", description="자동·Edge·Google 선택"),
                discord.SelectOption(label="TTS 기본 목소리", value="tts_voice", emoji="🗣️", description="개인 설정이 없는 사용자의 기본 음성"),
                discord.SelectOption(label="환영 메시지 채널", value="welcome", emoji="👋", description="신규 멤버 인사말이 올라갈 채널"),
                discord.SelectOption(label="환영문 공지 채널", value="notice", emoji="📢", description="인사말에 연결할 공지 채널"),
                discord.SelectOption(label="환영문 규칙 채널", value="rules", emoji="📕", description="인사말에 연결할 규칙 채널"),
                discord.SelectOption(label="환영문 가입 채널", value="register", emoji="🪪", description="간단 가입 안내를 연결할 채널"),
                discord.SelectOption(label="운영 로그 채널", value="log", emoji="📋", description="통합 운영 기록 채널"),
                discord.SelectOption(label="자동 이모지 켜기·끄기", value="auto_emoji", emoji="✨", description="현재 상태를 반대로 전환"),
                discord.SelectOption(label="홈페이지 공개 피드 켜기·끄기", value="feed", emoji="🌐", description="공개 이벤트 피드 상태 전환"),
                discord.SelectOption(label="리뉴얼 자동 진행 중지", value="renewal_stop", emoji="⏸️", description="계획은 보존하고 자동 실행만 중지"),
            ]
            super().__init__(placeholder="변경할 서버 설정을 선택하세요", min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            if not interaction_allowed(interaction, self.owner_id, self.guild_id):
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("❌ 서버 정보를 확인하지 못했습니다.", ephemeral=True)
                return
            choice = self.values[0]
            if choice == "summary":
                await interaction.response.send_message(embed=_settings_embed(world_data, guild), ephemeral=True)
                return
            if choice in {"tts_channel", "welcome", "notice", "rules", "register", "log"}:
                kind = "tts" if choice == "tts_channel" else choice
                await interaction.response.send_message(
                    "설정할 텍스트 채널을 선택하세요.",
                    view=ConfigChannelView(self.owner_id, self.guild_id, kind),
                    ephemeral=True,
                )
                return
            if choice == "tts_engine":
                await interaction.response.send_message("사용할 TTS 엔진을 선택하세요.", view=EngineView(self.owner_id, self.guild_id), ephemeral=True)
                return
            if choice == "tts_voice":
                await interaction.response.send_message("서버 기본 목소리를 선택하세요.", view=VoiceView(self.owner_id, self.guild_id), ephemeral=True)
                return
            if choice == "auto_emoji":
                settings = _management_settings(world_data, guild.id)["auto_reactions"]
                settings["enabled"] = not bool(settings.get("enabled"))
                save_data()
                await interaction.response.send_message(f"✅ 자동 이모지를 **{_on_off(settings['enabled'])}**으로 변경했습니다.", ephemeral=True)
                return
            if choice == "feed":
                feed = _feed_settings(world_data)
                feed["enabled"] = not bool(feed.get("enabled", True))
                save_data()
                await interaction.response.send_message(f"✅ 홈페이지 공개 이벤트 피드를 **{_on_off(feed['enabled'])}**으로 변경했습니다.", ephemeral=True)
                return
            layout = voice_system._layout_settings(world_data, guild.id)["layout"]
            autopilot = layout.setdefault("autopilot", {})
            autopilot["enabled"] = False
            autopilot["next_run_at"] = 0
            autopilot["last_reason"] = "v6.1.0 설정 제어실에서 관리자가 중지"
            task = voice_system.RENEWAL_AUTOPILOT_TASKS.get(guild.id)
            if task and not task.done():
                task.cancel()
            save_data()
            await interaction.response.send_message("✅ 서버 리뉴얼 자동 진행을 중지했습니다. 현재 계획과 진행률은 보존됩니다.", ephemeral=True)

    class SettingsView(discord.ui.View):
        def __init__(self, owner_id: int, guild_id: int) -> None:
            super().__init__(timeout=DIAGNOSTIC_MENU_TIMEOUT)
            self.add_item(SettingsSelect(owner_id, guild_id))

    @bot.command(name="아바돈진단", aliases=["진단센터", "통합진단"], help="ABADDON 주요 시스템을 드롭다운으로 통합 진단합니다.")
    async def abaddon_diagnostic(ctx: commands.Context) -> None:
        guild = await require_admin(ctx)
        if guild is None:
            return
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            await ctx.send("❌ 서버 채널 정보를 확인하지 못했습니다.")
            return
        await ctx.send(
            embed=_overall_embed(bot, world_data, user_data, data_file, guild, ctx.channel),
            view=DiagnosticView(ctx.author.id, guild.id),
        )

    @bot.command(name="설정", aliases=["아바돈설정", "설정센터"], help="서버 주요 설정을 드롭다운에서 관리합니다.")
    async def abaddon_settings(ctx: commands.Context) -> None:
        guild = await require_admin(ctx)
        if guild is None:
            return
        await ctx.send(
            embed=_settings_embed(world_data, guild),
            view=SettingsView(ctx.author.id, guild.id),
        )
