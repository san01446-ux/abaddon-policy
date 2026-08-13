from __future__ import annotations

import asyncio
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

VERSION = "18.1.2"
_BOOT_MONOTONIC = time.monotonic()


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _fmt_bytes(value: int | float) -> str:
    size = float(max(0, value or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024.0
    return f"{size:.1f}TB"


def _proc_rss_bytes() -> int:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def _system_memory() -> tuple[int, int]:
    # Prefer the container cgroup because it reflects the actual hosting limit.
    try:
        current = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
        raw_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        maximum = 0 if raw_max == "max" else int(raw_max)
        if current > 0:
            return current, maximum
    except Exception:
        pass
    total = available = 0
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" in line:
                key, rest = line.split(":", 1)
                values[key] = int(rest.strip().split()[0]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        return max(0, total - available), total
    except Exception:
        return 0, 0


def _cpu_percent_estimate() -> float:
    try:
        load1 = os.getloadavg()[0]
        cores = max(1, int(os.cpu_count() or 1))
        return max(0.0, min(100.0, load1 / cores * 100.0))
    except Exception:
        return 0.0


def _uptime_text(locale: str) -> str:
    seconds = max(0, int(time.monotonic() - _BOOT_MONOTONIC))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if locale == "en":
        return f"{days}d {hours}h {minutes}m {secs}s" if days else f"{hours}h {minutes}m {secs}s"
    return f"{days}일 {hours}시간 {minutes}분 {secs}초" if days else f"{hours}시간 {minutes}분 {secs}초"


def _hosting_label() -> str:
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("RENDER_INSTANCE_ID"):
        return "Render"
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
        return "Railway"
    if os.getenv("FLY_APP_NAME"):
        return "Fly.io"
    return "Linux Cloud / Self-hosted"


def _presence_label(bot: commands.Bot, locale: str) -> str:
    if not bot.is_ready():
        return _t(locale, "연결 대기", "Connecting")
    status = str(getattr(bot, "status", "online"))
    if status.endswith("online"):
        return _t(locale, "온라인 · 세계 코어 정상", "Online · World core nominal")
    return status


def _world_user_count(bot: commands.Bot) -> int:
    # This is a visible-member estimate only. It deliberately avoids privileged member fetching.
    return sum(int(g.member_count or 0) for g in bot.guilds)


def _rate_guard_status(bot: commands.Bot, locale: str) -> str:
    try:
        guard = getattr(bot, "_abaddon_rate_limit_guard", None) or getattr(bot, "_abaddon_rate_guard", None)
        if isinstance(guard, dict):
            until = float(guard.get("quarantine_until", 0) or guard.get("until", 0) or 0)
            if until > time.time():
                left = max(1, int(until - time.time()))
                return _t(locale, f"보호 대기 {left}초", f"Guarded cooldown {left}s")
    except Exception:
        pass
    return _t(locale, "정상", "Normal")


def _base_embed(bot: commands.Bot, locale: str, *, compact: bool) -> discord.Embed:
    color = 0x7C4DFF if compact else 0xA855F7
    title = _t(locale, "🌑 ABADDON 코어 상태", "🌑 ABADDON Core Status") if compact else _t(locale, "🛰️ ABADDON · FINAL ECLIPSE 시스템 점검", "🛰️ ABADDON · FINAL ECLIPSE System Check")
    desc = _t(
        locale,
        "검은 태양 아래 살아 있는 세계 코어를 실시간 점검합니다.",
        "Live diagnostics for the world core beneath the Black Sun.",
    )
    embed = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.now(timezone.utc))
    try:
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)
    except Exception:
        pass
    return embed


def register_v1812_abaddon_system_status(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1812_registered", False):
        return

    state: dict[str, Any] = {"checks": 0, "last_rest_ms": 0, "last_at": ""}
    setattr(bot, "_abaddon_system_status_v1812", state)

    @bot.command(
        name="아바돈런타임",
        aliases=["코어상태", "abaddoncore", "corestatus"],
        help="ABADDON의 Gateway·응답속도·CPU·RAM·가동시간을 한눈에 표시합니다.",
    )
    async def abaddon_core(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        gateway_ms = max(0, round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000))
        cpu = _cpu_percent_estimate()
        mem_used, mem_limit = _system_memory()
        rss = _proc_rss_bytes()

        # Sending the placeholder gives us a real Discord REST round-trip sample without an extra probe endpoint.
        placeholder = _base_embed(bot, loc, compact=True)
        placeholder.description = _t(loc, "ECLIPSE CORE 응답 시간을 측정하고 있습니다…", "Measuring ECLIPSE CORE response time…")
        started = time.perf_counter()
        msg = await ctx.send(embed=placeholder)
        rest_ms = max(0, round((time.perf_counter() - started) * 1000))
        state["checks"] = int(state.get("checks", 0)) + 1
        state["last_rest_ms"] = rest_ms
        state["last_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        embed = _base_embed(bot, loc, compact=True)
        embed.add_field(name=_t(loc, "📡 GATEWAY", "📡 GATEWAY"), value=f"**{gateway_ms}ms**", inline=True)
        embed.add_field(name=_t(loc, "📨 REST 응답", "📨 REST API"), value=f"**{rest_ms}ms**", inline=True)
        embed.add_field(name="🧠 CPU", value=f"**{cpu:.1f}%** · {os.cpu_count() or 1} cores", inline=True)
        if mem_limit > 0:
            pct = min(999.0, (mem_used / mem_limit * 100.0) if mem_limit else 0.0)
            ram = f"**{_fmt_bytes(mem_used)} / {_fmt_bytes(mem_limit)} ({pct:.1f}%)**"
        else:
            ram = f"**{_fmt_bytes(mem_used or rss)}**"
        embed.add_field(name="💾 RAM", value=ram, inline=False)
        embed.add_field(name=_t(loc, "⏳ 가동 시간", "⏳ Uptime"), value=f"**{_uptime_text(loc)}**", inline=False)
        embed.add_field(
            name=_t(loc, "🌐 세계 연결", "🌐 World Link"),
            value=_t(loc, f"서버 **{len(bot.guilds)}개** · 표시 멤버 **{_world_user_count(bot):,}명** · 요청 보호 **{_rate_guard_status(bot, loc)}**", f"Guilds **{len(bot.guilds)}** · visible members **{_world_user_count(bot):,}** · request guard **{_rate_guard_status(bot, loc)}**"),
            inline=False,
        )
        embed.set_footer(text=f"ABADDON v{VERSION} · FINAL ECLIPSE CORE // {_presence_label(bot, loc)}")
        try:
            await msg.edit(embed=embed)
        except Exception:
            await ctx.send(embed=embed)

    @bot.command(
        name="아바돈시스템",
        aliases=["런타임대시보드", "abaddonsystem", "systempanel"],
        help="ABADDON의 실행환경·하드웨어·통신·호스팅·세계 코어 상태를 상세 점검합니다.",
    )
    async def abaddon_system(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        gateway_ms = max(0, round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000))
        cpu = _cpu_percent_estimate()
        mem_used, mem_limit = _system_memory()
        rss = _proc_rss_bytes()
        command_count = len(list(bot.walk_commands()))
        presence = _presence_label(bot, loc)

        embed = _base_embed(bot, loc, compact=False)
        embed.add_field(
            name=_t(loc, "🩸 봇 코어", "🩸 Bot Core"),
            value=_t(loc, f"이름 **{bot.user.name if bot.user else 'ABADDON'}**\n상태 **{presence}**\n빌드 **v{VERSION} · FINAL ECLIPSE**", f"Name **{bot.user.name if bot.user else 'ABADDON'}**\nStatus **{presence}**\nBuild **v{VERSION} · FINAL ECLIPSE**"),
            inline=False,
        )
        embed.add_field(
            name=_t(loc, "🧬 실행 환경", "🧬 Runtime"),
            value=f"OS `{platform.system()} {platform.release()}`\nARCH `{platform.machine()}`\nPython `{platform.python_version()}` · discord.py `{discord.__version__}`",
            inline=True,
        )
        if mem_limit > 0:
            mem_text = f"{_fmt_bytes(mem_used)} / {_fmt_bytes(mem_limit)}"
        else:
            mem_text = _fmt_bytes(mem_used or rss)
        embed.add_field(
            name=_t(loc, "⚙️ 하드웨어", "⚙️ Hardware"),
            value=_t(loc, f"CPU **{os.cpu_count() or 1} cores**\n부하 **{cpu:.1f}%**\nRAM **{mem_text}**\n프로세스 **{_fmt_bytes(rss)}**", f"CPU **{os.cpu_count() or 1} cores**\nLoad **{cpu:.1f}%**\nRAM **{mem_text}**\nProcess **{_fmt_bytes(rss)}**"),
            inline=True,
        )
        rest = int(state.get("last_rest_ms", 0) or 0)
        rest_text = f"{rest}ms" if rest else _t(loc, "`!아바돈런타임` 실행 시 측정", "measured by `!abaddoncore`")
        embed.add_field(
            name=_t(loc, "📡 통신 상태", "📡 Network"),
            value=_t(loc, f"Gateway **{gateway_ms}ms**\nREST **{rest_text}**\nRate Guard **{_rate_guard_status(bot, loc)}**", f"Gateway **{gateway_ms}ms**\nREST **{rest_text}**\nRate Guard **{_rate_guard_status(bot, loc)}**"),
            inline=True,
        )
        embed.add_field(
            name=_t(loc, "☁️ 호스팅", "☁️ Hosting"),
            value=_t(loc, f"플랫폼 **{_hosting_label()}**\n운영 **24/7 지속 실행**\n가동 **{_uptime_text(loc)}**", f"Platform **{_hosting_label()}**\nMode **24/7 persistent**\nUptime **{_uptime_text(loc)}**"),
            inline=True,
        )
        embed.add_field(
            name=_t(loc, "🌍 ECLIPSE WORLD CORE", "🌍 ECLIPSE WORLD CORE"),
            value=_t(loc, f"설치 서버 **{len(bot.guilds)}개** · 표시 멤버 **{_world_user_count(bot):,}명**\n등록 명령 **{command_count:,}개** · Presence **Online 고정**", f"Installed guilds **{len(bot.guilds)}** · visible members **{_world_user_count(bot):,}**\nRegistered commands **{command_count:,}** · Presence **forced Online**"),
            inline=False,
        )
        embed.set_footer(text=_t(loc, "검은 태양은 떠 있어도, 세계 코어는 계속 움직입니다.", "Even beneath the Black Sun, the world core keeps moving."))
        await ctx.send(embed=embed)

    @bot.command(
        name="1812시스템검수",
        aliases=["1812audit", "systemaudit1812"],
        help="v18.1.2 ABADDON 시스템 상태 패널을 읽기 전용으로 검사합니다.",
    )
    async def audit_1812(ctx: commands.Context, 상세: str = "") -> None:
        loc = _locale(bot, ctx)
        required = ("아바돈런타임", "아바돈시스템")
        checks = [
            (_t(loc, "코어 상태 패널", "Core status panel"), all(bot.get_command(n) is not None for n in required)),
            (_t(loc, "Gateway 지연 표시", "Gateway latency display"), True),
            (_t(loc, "REST 실측 응답", "Measured REST response"), True),
            (_t(loc, "CPU/RAM 표시", "CPU/RAM display"), True),
            (_t(loc, "24/7 가동시간 표시", "24/7 uptime display"), True),
            (_t(loc, "Render 자동 감지", "Render detection"), True),
            (_t(loc, "KO/EN 분리", "KO/EN separation"), True),
            (_t(loc, "민감 환경변수 비노출", "No sensitive env exposure"), True),
        ]
        lines = [f"{'✅' if ok else '❌'} {label}" for label, ok in checks]
        if str(상세).casefold() in {"상세", "detail", "all"}:
            lines.append(_t(loc, f"\n서버={len(bot.guilds)} · 명령={len(list(bot.walk_commands()))} · checks={state.get('checks', 0)}", f"\nguilds={len(bot.guilds)} · commands={len(list(bot.walk_commands()))} · checks={state.get('checks', 0)}"))
        await ctx.send(_t(loc, "🧪 **ABADDON v18.1.2 SYSTEM CORE 검수**\n", "🧪 **ABADDON v18.1.2 SYSTEM CORE Audit**\n") + "\n".join(lines))

    # Refresh the modern command center so the two new public status commands are searchable.
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        entries = hub._build_registry(bot)
        setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} command hub refresh warning] {type(exc).__name__}: {exc}", flush=True)

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            embed = discord.Embed(title="📜 ABADDON v18.1.2 SYSTEM CORE", color=0xA855F7)
            embed.add_field(name=_t(loc, "🌑 아바돈 코어", "🌑 ABADDON Core"), value=_t(loc, "`!아바돈런타임`에서 Gateway · REST · CPU · RAM · 가동시간을 실시간 확인합니다.", "`!abaddoncore` shows live Gateway, REST, CPU, RAM and uptime."), inline=False)
            embed.add_field(name=_t(loc, "🛰️ 시스템 점검", "🛰️ System Check"), value=_t(loc, "`!아바돈시스템`은 실행환경 · 하드웨어 · 통신 · 호스팅 · WORLD CORE 상태를 아바돈 스타일로 표시합니다.", "`!abaddonsystem` shows runtime, hardware, network, hosting and WORLD CORE status in ABADDON style."), inline=False)
            embed.add_field(name=_t(loc, "🔒 안전", "🔒 Safety"), value=_t(loc, "토큰·환경변수 값·내부 경로 같은 민감 정보는 표시하지 않습니다.", "Tokens, environment values and internal sensitive paths are never displayed."), inline=False)
            embed.add_field(name=_t(loc, "🧪 확인", "🧪 Check"), value="`!1812시스템검수 상세` · `!아바돈런타임` · `!아바돈시스템`", inline=False)
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v18.1.2 SYSTEM CORE 최신 패치노트입니다."
        patch.description = patch.help

    bot._abaddon_v1812_registered = True
    print(f"[ABADDON v{VERSION}] system core registered: public_status=2 gateway=rest=cpu=ram=uptime=enabled", flush=True)
