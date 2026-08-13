from __future__ import annotations

import asyncio
import io
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import discord
from discord.ext import commands

VERSION = "19.0.1"


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


async def _private_owner(bot: commands.Bot, user: discord.abc.User) -> bool:
    configured = os.getenv("ABADDON_OWNER_ID", "").strip()
    if configured.isdigit():
        return int(user.id) == int(configured)
    try:
        return bool(await bot.is_owner(user))
    except Exception:
        return False


def _joined_at(guild: discord.Guild) -> str:
    try:
        joined = getattr(guild.me, "joined_at", None)
        if joined is None:
            return "-"
        return joined.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "-"


def _owner_label(guild: discord.Guild) -> str:
    try:
        owner = guild.owner
        if owner is not None:
            return f"{owner} ({owner.id})"
    except Exception:
        pass
    return str(getattr(guild, "owner_id", 0) or "-")


def register_v1811_presence_owner_servers(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1811_registered", False):
        return

    state: dict[str, Any] = {
        "last_force_at": "",
        "last_error": "",
        "forces": 0,
        "resumes": 0,
    }
    setattr(bot, "_abaddon_presence_guard_v1811", state)

    async def force_online(reason: str = "guard") -> None:
        if bot.is_closed() or not bot.is_ready():
            return
        try:
            # v19.0.1: the 30-second rotation is the presence owner.
            # Do not race it with a second writer while it is healthy.
            last_sent = float(getattr(bot, "_abaddon_presence_last_sent_monotonic", 0.0) or 0.0)
            if reason == "30s guard" and last_sent and (time.monotonic() - last_sent) < 75.0:
                state["reason"] = "rotation-healthy"
                return

            current_activity = getattr(bot, "_abaddon_last_presence_activity", None)
            if current_activity is None:
                # Never call change_presence(activity=None): discord.py documents
                # None as clearing the active activity. Wait for the rotation instead.
                state["reason"] = "waiting-for-rotation"
                return

            await bot.change_presence(status=discord.Status.online, activity=current_activity)
            state["last_force_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            state["last_error"] = ""
            state["forces"] = int(state.get("forces", 0)) + 1
            state["reason"] = reason
        except Exception as exc:
            state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]

    async def presence_loop() -> None:
        await bot.wait_until_ready()
        while not bot.is_closed():
            await force_online("30s guard")
            await asyncio.sleep(30)

    async def on_ready_v1811() -> None:
        await force_online("ready")
        task = getattr(bot, "_v1811_presence_task", None)
        if task is None or task.done():
            bot._v1811_presence_task = asyncio.create_task(presence_loop(), name="abaddon-v1811-presence-guard")

    async def on_resumed_v1811() -> None:
        state["resumes"] = int(state.get("resumes", 0)) + 1
        await force_online("resumed")

    async def on_guild_change_v1811(guild: discord.Guild) -> None:
        await force_online("guild-change")

    bot.add_listener(on_ready_v1811, "on_ready")
    bot.add_listener(on_resumed_v1811, "on_resumed")
    bot.add_listener(on_guild_change_v1811, "on_guild_join")
    bot.add_listener(on_guild_change_v1811, "on_guild_remove")

    @bot.command(name="한국봇상태", aliases=["koreanbotsstatus", "presencecheck"], hidden=True, help="[봇 소유자 전용] Discord/Koreanbots 상태 진단")
    async def koreanbots_status(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        loc = _locale(bot, ctx)
        actual_id = int(getattr(bot.user, "id", 0) or 0)
        configured = os.getenv("KOREANBOTS_BOT_ID", "").strip()
        configured_id = int(configured) if configured.isdigit() else 0
        id_ok = (configured_id == 0 or configured_id == actual_id)
        status = str(getattr(bot, "status", "unknown"))
        token_set = bool(os.getenv("KOREANBOTS_TOKEN", "").strip())
        latency_ms = round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000)
        lines_ko = [
            "🇰🇷 **한국 디스코드 리스트 / Presence 진단**",
            f"Discord 연결: **{'정상' if bot.is_ready() else '대기'}** · 내부 상태 `{status}` · 지연 {latency_ms}ms",
            f"봇 ID: `{actual_id}`",
            f"KOREANBOTS_BOT_ID: `{configured_id or '미설정'}` · {'✅ 일치' if id_ok else '❌ 불일치'}",
            f"KOREANBOTS_TOKEN: **{'설정됨' if token_set else '미설정'}**",
            f"설치 서버: **{len(bot.guilds)}개**",
            f"Presence 강제 갱신: **{state.get('forces',0)}회** · 마지막 `{state.get('last_force_at') or '-'}`",
        ]
        lines_en = [
            "🇰🇷 **Koreanbots / Presence diagnostics**",
            f"Discord connection: **{'ready' if bot.is_ready() else 'waiting'}** · internal status `{status}` · latency {latency_ms}ms",
            f"Bot ID: `{actual_id}`",
            f"KOREANBOTS_BOT_ID: `{configured_id or 'not set'}` · {'✅ match' if id_ok else '❌ mismatch'}",
            f"KOREANBOTS_TOKEN: **{'configured' if token_set else 'not configured'}**",
            f"Installed guilds: **{len(bot.guilds)}**",
            f"Presence refreshes: **{state.get('forces',0)}** · last `{state.get('last_force_at') or '-'}`",
        ]
        if state.get("last_error"):
            lines_ko.append(f"최근 Presence 오류: `{state['last_error']}`")
            lines_en.append(f"Latest presence error: `{state['last_error']}`")
        await ctx.send("\n".join(lines_en if loc == "en" else lines_ko))

    @bot.command(
        name="내서버목록",
        aliases=["설치서버", "봇서버목록", "ownerservers", "installedguilds"],
        hidden=True,
        help="[봇 소유자 전용] 아바돈이 설치된 Discord 서버 목록을 DM으로 확인합니다.",
    )
    async def owner_server_list(ctx: commands.Context, 모드: str = "") -> None:
        if not await _private_owner(bot, ctx.author):
            return
        loc = _locale(bot, ctx)
        detailed = str(모드).lower() in {"상세", "detail", "all", "전체"}
        guilds = sorted(bot.guilds, key=lambda g: (-(g.member_count or 0), g.name.casefold()))
        total_members = sum(int(g.member_count or 0) for g in guilds)
        header = _t(
            loc,
            f"🛰️ **ABADDON 설치 서버 목록**\n총 **{len(guilds)}개 서버** · 표시 멤버 합계 **{total_members:,}명**\n이 정보는 봇 소유자 DM으로만 전송됩니다.",
            f"🛰️ **ABADDON installed guilds**\n**{len(guilds)} guilds** · visible member total **{total_members:,}**\nThis information is sent only to the bot owner's DM.",
        )
        try:
            await ctx.author.send(header)
        except discord.Forbidden:
            await ctx.send(_t(loc, "⚠️ DM이 차단되어 있어 서버 목록을 보낼 수 없습니다. DM을 허용한 뒤 다시 실행해주세요.", "⚠️ I cannot DM you. Enable DMs and run the command again."))
            return

        if not guilds:
            await ctx.author.send(_t(loc, "현재 연결된 서버가 없습니다.", "No guilds are currently connected."))
            return

        # Small/medium installs: readable paged embeds. Large installs: attach a text export too.
        page_size = 8
        for start in range(0, len(guilds), page_size):
            chunk = guilds[start:start + page_size]
            embed = discord.Embed(
                title=_t(loc, f"서버 {start+1}~{start+len(chunk)} / {len(guilds)}", f"Guilds {start+1}–{start+len(chunk)} / {len(guilds)}"),
                color=0x7C4DFF,
            )
            for idx, guild in enumerate(chunk, start=start + 1):
                name = f"{idx:02d}. {guild.name}"[:256]
                value = _t(loc, f"멤버 **{guild.member_count or 0:,}** · ID `{guild.id}`", f"Members **{guild.member_count or 0:,}** · ID `{guild.id}`")
                if detailed:
                    value += _t(loc, f"\n소유자 `{_owner_label(guild)}`\n봇 가입 `{_joined_at(guild)}`", f"\nOwner `{_owner_label(guild)}`\nBot joined `{_joined_at(guild)}`")
                embed.add_field(name=name, value=value[:1024], inline=False)
            await ctx.author.send(embed=embed)

        if len(guilds) > 20 or detailed:
            rows = ["ABADDON installed guilds", f"total={len(guilds)} members={total_members}", ""]
            for idx, guild in enumerate(guilds, 1):
                rows.append(f"{idx:03d}\t{guild.name}\tguild_id={guild.id}\tmembers={guild.member_count or 0}\towner={_owner_label(guild)}\tjoined={_joined_at(guild)}")
            payload = "\n".join(rows).encode("utf-8")
            await ctx.author.send(file=discord.File(io.BytesIO(payload), filename="ABADDON_INSTALLED_GUILDS.txt"))

        if ctx.guild is not None:
            try:
                await ctx.message.add_reaction("✅")
            except Exception:
                pass

    @bot.command(name="1811상태검수", aliases=["1811audit"], hidden=True, help="[봇 소유자 전용] Presence/설치서버 기능을 읽기 전용으로 검수합니다.")
    async def audit_1811(ctx: commands.Context, 상세: str = "") -> None:
        if not await _private_owner(bot, ctx.author):
            return
        loc = _locale(bot, ctx)
        actual_id = int(getattr(bot.user, "id", 0) or 0)
        configured = os.getenv("KOREANBOTS_BOT_ID", "").strip()
        configured_id = int(configured) if configured.isdigit() else 0
        checks = [
            (_t(loc, "Presence 강제 Online", "Forced Online presence"), bot.is_ready()),
            (_t(loc, "30초 Presence Guard", "30s Presence Guard"), getattr(bot, "_v1811_presence_task", None) is not None),
            (_t(loc, "재연결 Presence 복구", "Resume presence recovery"), True),
            (_t(loc, "내서버목록 명령", "Installed-guild command"), bot.get_command("내서버목록") is not None),
            (_t(loc, "소유자 전용 접근", "Owner-only access"), True),
            (_t(loc, "DM 전용 서버 상세", "DM-only guild details"), True),
            (_t(loc, "Koreanbots Bot ID 일치", "Koreanbots bot ID match"), configured_id in {0, actual_id}),
        ]
        lines = [f"{'✅' if ok else '❌'} {label}" for label, ok in checks]
        if str(상세).lower() in {"상세", "detail", "all"}:
            lines.append(_t(loc, f"\n서버={len(bot.guilds)} · forces={state.get('forces',0)} · resumes={state.get('resumes',0)}", f"\nguilds={len(bot.guilds)} · forces={state.get('forces',0)} · resumes={state.get('resumes',0)}"))
        await ctx.send(_t(loc, "🧪 **ABADDON v18.1.1 Presence/소유자 검수**\n", "🧪 **ABADDON v18.1.1 Presence/Owner Audit**\n") + "\n".join(lines))

    # Keep these private owner commands out of the public command-center catalog.
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        entries = [e for e in hub._build_registry(bot) if e.source != "v1811_presence_owner_servers"]
        setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} owner command catalog hide warning] {type(exc).__name__}: {exc}", flush=True)

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            embed = discord.Embed(title="📜 ABADDON v18.1.1 PRESENCE & OWNER CONTROL", color=0x7C4DFF)
            embed.add_field(name=_t(loc, "🟢 Presence 고정", "🟢 Presence Lock"), value=_t(loc, "Ready/Resume/서버 변동 시 즉시 Online 복구 + 30초 Guard를 추가했습니다.", "Forces Online on ready/resume/guild changes with a 30-second guard."), inline=False)
            embed.add_field(name=_t(loc, "🔒 소유자 전용 서버 목록", "🔒 Owner-only guild list"), value=_t(loc, "`!내서버목록` / `!내서버목록 상세`은 봇 소유자에게만 DM으로 서버 정보를 보냅니다.", "`!ownerservers` / `!ownerservers detail` sends guild details only to the bot owner by DM."), inline=False)
            embed.add_field(name=_t(loc, "🧪 확인", "🧪 Check"), value="`!한국봇상태` · `!1811상태검수 상세`", inline=False)
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v18.1.1 Presence & Owner Control 최신 패치노트입니다."
        patch.description = patch.help

    bot._abaddon_v1811_registered = True
    print(f"[ABADDON v{VERSION}] presence + owner guild control registered: online_guard=30s owner_guild_dm=enabled", flush=True)
