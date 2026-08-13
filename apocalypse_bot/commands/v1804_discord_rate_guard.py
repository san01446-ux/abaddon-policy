from __future__ import annotations

"""ABADDON v18.0.4 Discord Rate Limit Guard diagnostics and final hotfix surface."""

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

import discord
from discord.ext import commands

from apocalypse_bot.core import rate_limit_guard as guard
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
from apocalypse_bot.commands import v1660_first_survival_live_qa as live1660

VERSION = "18.0.4"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, actor: Any) -> str:
    try:
        return live1660._locale(bot, actor)
    except Exception:
        return "ko"


def _duration(seconds: int) -> str:
    value = max(0, int(seconds or 0))
    if value < 60:
        return f"{value}초"
    minute, sec = divmod(value, 60)
    return f"{minute}분 {sec}초" if sec else f"{minute}분"


def register_v1804_discord_rate_guard(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del get_user, check_registered, save_data, world_data, user_data
    if getattr(bot, "_abaddon_v1804_registered", False):
        return
    bot._abaddon_v1804_registered = True
    bot.abaddon_version = VERSION

    @bot.command(name="통신상태", aliases=["레이트리밋상태", "ratelimitstatus", "discordguard"], help="Discord/Cloudflare 요청 제한과 자동 대기 상태를 확인합니다.")
    async def communication_status(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        row = guard.snapshot()
        remain = int(row.get("remaining", 0) or 0)
        active = remain > 0
        color = 0xF39C12 if active else 0x2ECC71
        embed = discord.Embed(
            title=_t(locale, "🛡️ Discord 통신 보호 상태", "🛡️ Discord Communication Guard"),
            color=color,
        )
        embed.add_field(
            name=_t(locale, "현재 상태", "Current State"),
            value=_t(locale, f"{'⏸️ 안전 대기 중' if active else '✅ 정상'} · 남은 대기 {_duration(remain)}", f"{'⏸️ Guarded' if active else '✅ Normal'} · remaining {_duration(remain)}"),
            inline=False,
        )
        embed.add_field(
            name=_t(locale, "감지 누계", "Detected"),
            value=f"Cloudflare 1015 **{int(row.get('count_1015', 0) or 0)}** · HTTP 429 **{int(row.get('count_429', 0) or 0)}** · Cloudflare 5xx **{int(row.get('count_5xx', 0) or 0)}**",
            inline=False,
        )
        embed.add_field(
            name=_t(locale, "로그 정리", "Log Compaction"),
            value=_t(locale, f"Cloudflare HTML 본문 억제 **{int(row.get('suppressed_html', 0) or 0)}회**", f"Cloudflare HTML bodies suppressed **{int(row.get('suppressed_html', 0) or 0)}** times"),
            inline=False,
        )
        if row.get("last_kind"):
            embed.add_field(
                name=_t(locale, "최근 감지", "Latest Detection"),
                value=f"`{row.get('last_kind')}` · <t:{int(float(row.get('last_at', 0) or 0))}:R>",
                inline=False,
            )
        embed.set_footer(text=_t(locale, "날씨·세계·퀴즈 자동 시스템은 삭제하지 않으며 제한 시간에만 전송을 잠시 미룹니다.", "Weather/world/quiz systems remain enabled; sends are only deferred during a detected limit."))
        await ctx.send(embed=embed)

    @bot.command(name="1804통신검수", aliases=["1804audit", "v1804audit", "통신보호검수"], help="v18.0.4 요청 제한 보호·자동 시스템 보존 상태를 검사합니다.")
    async def audit_1804(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(bot, ctx)
        checks = [
            (_t(locale, "1015 감지기", "1015 detector"), guard.detect_rate_limit("Error 1015 You are being rate limited") == "1015"),
            (_t(locale, "429 감지기", "429 detector"), guard.detect_rate_limit("HTTP 429 Too Many Requests") == "429"),
            (_t(locale, "HTML 로그 축약", "HTML log compaction"), "1015" in guard.compact_message("<html>Error 1015 You are being rate limited Cloudflare</html>", record=False)),
            (_t(locale, "자동 대기 상태", "Automatic backoff state"), callable(guard.should_pause_nonessential) and callable(guard.remaining)),
            (_t(locale, "일일 퀴즈 자동 알림 보존", "Daily quiz scheduler preserved"), bot.get_command("퀴즈알림상태") is not None),
            (_t(locale, "날씨·재난 시스템 보존", "Weather/disaster preserved"), bot.get_command("재난날씨") is not None and bot.get_command("재난예보") is not None),
            (_t(locale, "살아 있는 세계 방송 보존", "Living-world broadcast preserved"), bot.get_command("세계방송설정") is not None),
            (_t(locale, "상황형 버튼 패치 보존", "Contextual UI preserved"), bot.get_command("1803버튼검수") is not None),
            (_t(locale, "200문제 퀴즈 보존", "200-question quiz preserved"), bot.get_command("1802퀴즈검수") is not None),
        ]
        ok = all(value for _name, value in checks)
        embed = discord.Embed(
            title=_t(locale, "🧪 ABADDON v18.0.4 Discord 통신 보호 검수", "🧪 ABADDON v18.0.4 Discord Guard Audit"),
            description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks),
            color=0x2ECC71 if ok else 0xE74C3C,
        )
        if 상세:
            row = guard.snapshot()
            embed.add_field(
                name=_t(locale, "현재 런타임", "Runtime"),
                value=_t(locale, f"안전 대기 {_duration(int(row.get('remaining', 0) or 0))} · 1015 {row.get('count_1015', 0)}회 · 429 {row.get('count_429', 0)}회", f"guard {_duration(int(row.get('remaining', 0) or 0))} · 1015 {row.get('count_1015', 0)} · 429 {row.get('count_429', 0)}"),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "정책", "Policy"),
                value=_t(locale, "1015 감지 시 5분, 429 감지 시 90초 동안 비필수 자동 게시를 미루며 정상 명령·저장 데이터는 유지합니다.", "Defers nonessential scheduled posts for 5 minutes after 1015 and 90 seconds after 429; commands and save data remain intact."),
                inline=False,
            )
        await ctx.send(embed=embed)

    # Refresh command center without deleting any legacy entries.
    try:
        entries = hub._build_registry(bot)
        setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} 명령 허브 새로고침 경고] {type(exc).__name__}: {exc}", flush=True)

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, "📜 ABADDON v18.0.4 Discord 통신 보호 핫픽스", "📜 ABADDON v18.0.4 Discord Guard Hotfix"), color=0x5865F2)
            embed.add_field(name=_t(locale, "🧹 Cloudflare 로그", "🧹 Cloudflare Logs"), value=_t(locale, "1015 오류 HTML 수백 줄을 한 줄 경고로 축약합니다.", "Compacts giant Cloudflare 1015 HTML pages into one warning line."), inline=False)
            embed.add_field(name=_t(locale, "⏳ 자동 대기", "⏳ Backoff"), value=_t(locale, "1015/429 감지 시 비필수 자동 게시가 잠시 대기했다가 자동으로 재개됩니다.", "Nonessential scheduled posts briefly wait after 1015/429 and resume automatically."), inline=False)
            embed.add_field(name=_t(locale, "🌦️ 자동 콘텐츠 보존", "🌦️ Automation Preserved"), value=_t(locale, "날씨·재난·살아 있는 세계·일일 퀴즈 자동 시스템은 그대로 유지합니다.", "Weather, disasters, living world and daily quiz automation remain enabled."), inline=False)
            embed.add_field(name=_t(locale, "🧪 확인", "🧪 Check"), value="`!통신상태` · `!1804통신검수 상세` · `!현재오류 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 명령·저장 데이터 삭제 0건 · v18.0.x 안정화 핫픽스", "0 legacy command/save-data deletions · v18.0.x stability hotfix"))
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v18.0.4 Discord 요청 제한 보호 최신 핫픽스입니다."
        patch.description = patch.help

    guide.append({
        "id": "v1804_discord_rate_guard",
        "emoji": "🛡️",
        "title": "v18.0.4 Discord Rate Limit Guard",
        "hint": "Cloudflare 1015/Discord 429 로그 축약·비필수 자동 게시 백오프·자동 콘텐츠 보존",
        "commands": ["!통신상태 · !1804통신검수 상세"],
    })

    print(f"[ABADDON v{VERSION}] Discord rate-limit guard registered: 1015=300s 429=90s html_compaction=enabled", flush=True)


__all__ = ["register_v1804_discord_rate_guard"]
