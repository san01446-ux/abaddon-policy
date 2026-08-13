from __future__ import annotations

"""ABADDON v18.1.3 interaction transport + support + KoreanBots sync.

Goals
-----
1. Legacy prefix commands launched from buttons/selects use one silent component
   acknowledgement and normal channel delivery instead of webhook bursts.
2. Repeated Discord/Cloudflare 1015/429 logs are coalesced.
3. A portable bug-report/support path is available in every guild and DM where
   the bot can be reached; new installers receive support information by DM.
4. KoreanBots server-count stats are pushed through the officially documented
   v2 stats route when a KoreanBots API token is configured.
"""

from typing import Any, Optional
import asyncio
import json
import os
import re
import time
from urllib import request as urllib_request
from urllib import error as urllib_error

import discord
from discord.ext import commands

VERSION = "18.1.3"
KB_STATS_URL = "https://koreanbots.dev/api/v2/bots/{bot_id}/stats"
KB_PERIODIC_SECONDS = 1800  # conservative background check; posts only when changed
STATIC_COMPONENT_CALLBACKS = 431
STATIC_COMPONENT_COVERED = 431
STATIC_BRIDGE_CALLS = 58


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1660_first_survival_live_qa as live1660
        return live1660._locale(bot, ctx)
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


async def _resolve_owner(bot: commands.Bot) -> Optional[discord.abc.User]:
    configured = os.getenv("ABADDON_OWNER_ID", "").strip()
    if configured.isdigit():
        user = bot.get_user(int(configured))
        if user is not None:
            return user
        try:
            return await bot.fetch_user(int(configured))
        except Exception:
            pass
    try:
        info = await bot.application_info()
        team = getattr(info, "team", None)
        if team is not None and getattr(team, "owner", None) is not None:
            return team.owner
        if getattr(info, "owner", None) is not None:
            return info.owner
    except Exception:
        return None
    return None


async def _private_owner(bot: commands.Bot, user: discord.abc.User) -> bool:
    configured = os.getenv("ABADDON_OWNER_ID", "").strip()
    if configured.isdigit():
        return int(user.id) == int(configured)
    try:
        return bool(await bot.is_owner(user))
    except Exception:
        return False


def _support_url() -> str:
    value = os.getenv("ABADDON_SUPPORT_URL", "").strip()
    if value and re.match(r"^https?://", value, re.I):
        return value[:500]
    return ""


def _clean_report(text: str) -> str:
    # Relayed text must not be able to mass-mention the creator's server/DM.
    return str(text or "").replace("@everyone", "＠everyone").replace("@here", "＠here").strip()[:1800]


async def _find_installer(bot: commands.Bot, guild: discord.Guild) -> Optional[discord.abc.User]:
    """Best effort: use the Bot Add audit entry when permission exists.

    Discord does not include the inviter in on_guild_join. If View Audit Log is
    not available, the reliable fallback is the guild owner.
    """
    try:
        me = guild.me
        can_audit = bool(me and me.guild_permissions.view_audit_log)
        if can_audit and bot.user is not None:
            await asyncio.sleep(2.0)  # let Discord write the audit event
            async for entry in guild.audit_logs(limit=8, action=discord.AuditLogAction.bot_add):
                target = getattr(entry, "target", None)
                if int(getattr(target, "id", 0) or 0) == int(bot.user.id):
                    actor = getattr(entry, "user", None)
                    if actor is not None and not getattr(actor, "bot", False):
                        return actor
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    try:
        if guild.owner is not None:
            return guild.owner
    except Exception:
        pass
    try:
        return await bot.fetch_user(int(guild.owner_id))
    except Exception:
        return None


async def _send_install_support_dm(bot: commands.Bot, guild: discord.Guild) -> None:
    recipient = await _find_installer(bot, guild)
    if recipient is None:
        return
    creator = await _resolve_owner(bot)
    creator_id = int(getattr(creator, "id", 0) or 0)
    support = _support_url()
    embed = discord.Embed(
        title="🌑 ABADDON 설치가 완료되었습니다",
        description=(
            "ABADDON을 추가해 주셔서 감사합니다. 오류가 생기면 현재 서버에서 "
            "`!버그신고 내용`으로 제작자에게 직접 제보할 수 있습니다.\n"
            "봇과 공통 서버가 없는 사용자는 아래 공식 지원 서버를 이용해주세요."
        ),
        color=0x7C4DFF,
    )
    embed.add_field(name="🐞 어디서든 버그 신고", value="`!버그신고 <문제 내용>`", inline=False)
    embed.add_field(name="🧪 설치 후 1분 점검", value="서버 관리자라면 `!서버진단`으로 메시지·임베드·파일·슬래시/UI 준비 상태를 확인하세요.", inline=False)
    if support:
        embed.add_field(name="🛟 공식 지원/버그 신고 서버", value=support, inline=False)
    else:
        embed.add_field(name="🛟 공식 지원 서버", value="제작자가 `ABADDON_SUPPORT_URL`을 설정하면 여기에 표시됩니다.", inline=False)
    if creator_id:
        embed.add_field(name="👤 제작자 Discord 사용자 ID", value=f"`{creator_id}`", inline=False)
    embed.add_field(name="📮 장애·버그 직접 문의", value="Discord DM **`jjonga0022`** · 또는 `!문의처`", inline=False)
    embed.set_footer(text=f"설치 서버: {guild.name} · ID {guild.id}")
    try:
        await recipient.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        return


async def _relay_bug_report(bot: commands.Bot, ctx: commands.Context, report: str) -> bool:
    owner = await _resolve_owner(bot)
    if owner is None:
        return False
    guild_name = getattr(ctx.guild, "name", "DM") if ctx.guild is not None else "DM"
    guild_id = int(getattr(ctx.guild, "id", 0) or 0)
    channel_name = getattr(ctx.channel, "name", "DM")
    embed = discord.Embed(title="🐞 ABADDON 사용자 버그 신고", color=0xE67E22)
    embed.add_field(name="신고자", value=f"{ctx.author} · `{ctx.author.id}`", inline=False)
    embed.add_field(name="서버", value=f"{guild_name} · `{guild_id or '-'}`", inline=False)
    embed.add_field(name="채널", value=f"{channel_name} · `{getattr(ctx.channel, 'id', 0) or '-'}`", inline=False)
    embed.add_field(name="내용", value=_clean_report(report) or "(첨부파일 신고)", inline=False)
    attachments = list(getattr(ctx.message, "attachments", None) or [])[:3]
    if attachments:
        links = "\n".join(str(getattr(item, "url", "") or "") for item in attachments if getattr(item, "url", None))
        if links:
            embed.add_field(name="첨부파일", value=links[:1024], inline=False)
    try:
        if getattr(ctx.message, "jump_url", None) and ctx.guild is not None:
            embed.add_field(name="원문", value=str(ctx.message.jump_url), inline=False)
    except Exception:
        pass
    try:
        await owner.send(embed=embed)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


def _kb_bot_id(bot: commands.Bot) -> int:
    value = os.getenv("KOREANBOTS_BOT_ID", "").strip()
    if value.isdigit():
        return int(value)
    return int(getattr(getattr(bot, "user", None), "id", 0) or 0)


def _kb_stats_post_sync(bot_id: int, token: str, servers: int, shards: Optional[int]) -> dict[str, Any]:
    body: dict[str, Any] = {"servers": int(servers)}
    if shards is not None and int(shards) > 0:
        body["shards"] = int(shards)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        KB_STATS_URL.format(bot_id=int(bot_id)),
        data=payload,
        method="POST",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "User-Agent": f"ABADDON/{VERSION}",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=12) as res:
            raw = res.read(256_000).decode("utf-8", "replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw[:300]}
            return {"ok": 200 <= int(res.status) < 300, "status": int(res.status), "data": parsed}
    except urllib_error.HTTPError as exc:
        try:
            raw = exc.read(128_000).decode("utf-8", "replace")
        except Exception:
            raw = ""
        return {"ok": False, "status": int(getattr(exc, "code", 0) or 0), "error": raw[:500] or str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"{type(exc).__name__}: {exc}"[:500]}


def register_v1813_interaction_transport_guard(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1813_registered", False):
        return
    bot._abaddon_v1813_registered = True
    bot.abaddon_version = VERSION
    bot.v1813_context_channel_delivery = True
    bot.v1813_global_bridge_delivery = True
    bot.v1813_silent_component_ack = True

    kb_state: dict[str, Any] = {
        "enabled": bool(os.getenv("KOREANBOTS_TOKEN", "").strip()),
        "last_attempt": 0.0,
        "last_success": 0.0,
        "last_servers": None,
        "last_status": 0,
        "last_error": "",
        "successes": 0,
        "failures": 0,
    }
    bot._v1813_koreanbots_sync = kb_state
    kb_lock = asyncio.Lock()

    async def update_koreanbots(*, force: bool = False, reason: str = "periodic") -> bool:
        token = os.getenv("KOREANBOTS_TOKEN", "").strip()
        bot_id = _kb_bot_id(bot)
        if not token or not bot_id or not bot.is_ready():
            kb_state["enabled"] = bool(token)
            return False
        servers = len(bot.guilds)
        if not force and kb_state.get("last_servers") == servers and kb_state.get("last_success"):
            return True
        if kb_lock.locked():
            return False
        async with kb_lock:
            kb_state["last_attempt"] = time.time()
            shard_count = getattr(bot, "shard_count", None)
            result = await asyncio.to_thread(_kb_stats_post_sync, bot_id, token, servers, shard_count)
            kb_state["last_status"] = int(result.get("status", 0) or 0)
            if result.get("ok"):
                kb_state["last_success"] = time.time()
                kb_state["last_servers"] = servers
                kb_state["last_error"] = ""
                kb_state["successes"] = int(kb_state.get("successes", 0) or 0) + 1
                print(f"[ABADDON v{VERSION}] KoreanBots stats synced: servers={servers} reason={reason}", flush=True)
                return True
            kb_state["failures"] = int(kb_state.get("failures", 0) or 0) + 1
            kb_state["last_error"] = str(result.get("error") or f"HTTP {kb_state['last_status']}")[:300]
            print(f"[ABADDON v{VERSION}] KoreanBots stats sync failed: status={kb_state['last_status']} reason={reason}", flush=True)
            return False

    async def koreanbots_loop() -> None:
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await update_koreanbots(reason="periodic")
            except Exception as exc:
                kb_state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            await asyncio.sleep(KB_PERIODIC_SECONDS)

    async def on_ready_v1813() -> None:
        # Presence guard v18.1.1 handles Discord online state. This is a separate
        # official KoreanBots stats sync and does not claim to override site cache.
        await update_koreanbots(force=True, reason="ready")
        task = getattr(bot, "_v1813_koreanbots_task", None)
        if task is None or task.done():
            bot._v1813_koreanbots_task = asyncio.create_task(koreanbots_loop(), name="abaddon-koreanbots-stats")

    async def on_guild_join_v1813(guild: discord.Guild) -> None:
        await asyncio.gather(
            _send_install_support_dm(bot, guild),
            update_koreanbots(force=True, reason="guild_join"),
            return_exceptions=True,
        )

    async def on_guild_remove_v1813(_guild: discord.Guild) -> None:
        await update_koreanbots(force=True, reason="guild_remove")

    bot.add_listener(on_ready_v1813, "on_ready")
    bot.add_listener(on_guild_join_v1813, "on_guild_join")
    bot.add_listener(on_guild_remove_v1813, "on_guild_remove")

    @bot.command(
        name="문의처",
        aliases=["지원서버", "버그문의", "supportcontact", "supportserver"],
        help="ABADDON 공식 지원 서버와 제작자 연락 방법을 확인합니다.",
    )
    async def support_contact(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        owner = await _resolve_owner(bot)
        creator_id = int(getattr(owner, "id", 0) or 0)
        support = _support_url()
        embed = discord.Embed(title=_t(locale, "🛟 ABADDON 지원·버그 신고", "🛟 ABADDON Support & Bug Reports"), color=0x7C4DFF)
        embed.add_field(
            name=_t(locale, "🐞 설치된 어느 서버/DM에서든", "🐞 From any installed guild/DM"),
            value=_t(locale, "`!버그신고 <문제 내용>`을 입력하면 제작자 DM으로 전달됩니다.", "Use `!reportbug <details>` to relay a report to the creator."),
            inline=False,
        )
        if support:
            embed.add_field(name=_t(locale, "공식 지원·버그 신고 서버", "Official support server"), value=support, inline=False)
        if creator_id:
            embed.add_field(name=_t(locale, "제작자 Discord ID", "Creator Discord ID"), value=f"`{creator_id}`", inline=False)
        embed.add_field(
            name=_t(locale, "💬 장애·버그 직접 DM", "💬 Direct outage/bug DM"),
            value=_t(locale, "Discord 사용자명 **`jjonga0022`** 로 DM을 보내주세요.", "Send a Discord DM to **`jjonga0022`**."),
            inline=False,
        )
        embed.set_footer(text=_t(locale, "오류 화면이나 사건 번호가 있다면 함께 보내주세요.", "Include the error screen or incident ID when possible."))
        await ctx.send(embed=embed)

    @bot.command(
        name="버그신고",
        aliases=["버그제보", "reportbug", "bugreport"],
        help="현재 서버/DM에서 발견한 ABADDON 버그를 제작자에게 직접 전달합니다.",
    )
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def bug_report(ctx: commands.Context, *, 내용: str = "") -> None:
        locale = _locale(bot, ctx)
        report = _clean_report(내용)
        attachments = list(getattr(ctx.message, "attachments", None) or [])
        if len(report) < 5 and not attachments:
            await ctx.send(_t(locale, "🐞 사용법: `!버그신고 어떤 기능에서 무엇을 눌렀는데 어떤 문제가 났는지` (스크린샷 첨부 가능)", "🐞 Usage: `!reportbug describe what you did and what went wrong` (screenshots supported)"))
            return
        ok = await _relay_bug_report(bot, ctx, report)
        if ok:
            await ctx.send(_t(locale, "✅ 버그 신고를 제작자에게 전달했습니다. 신고자 ID와 서버/채널 정보도 함께 전달됩니다.", "✅ Your bug report was relayed to the creator with reporter/guild/channel context."))
        else:
            support = _support_url()
            fallback = f"\n🛟 {support}" if support else ""
            await ctx.send(_t(locale, "⚠️ 제작자 DM 전달에 실패했습니다. `!문의처`에서 다른 연락 방법을 확인해주세요.", "⚠️ Creator DM delivery failed. Use `!supportcontact` for alternate support.") + fallback)

    @bot.command(
        name="한국봇동기화",
        aliases=["koreanbotssync", "kbsync"],
        hidden=True,
        help="[봇 소유자 전용] KoreanBots 서버 수를 즉시 동기화합니다.",
    )
    async def koreanbots_sync(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        token = os.getenv("KOREANBOTS_TOKEN", "").strip()
        if not token:
            await ctx.send("⚠️ `KOREANBOTS_TOKEN`이 미설정입니다. Render → Environment에 KoreanBots 개발자 토큰을 추가해주세요.")
            return
        ok = await update_koreanbots(force=True, reason="manual")
        if ok:
            await ctx.send(f"✅ KoreanBots 서버 수 동기화 완료 · **{len(bot.guilds)}개 서버** · HTTP `{kb_state.get('last_status')}`")
        else:
            await ctx.send(f"❌ KoreanBots 동기화 실패 · HTTP `{kb_state.get('last_status')}` · `{kb_state.get('last_error') or 'unknown'}`")

    @bot.command(
        name="상호작용전송상태",
        aliases=["버튼전송상태", "interactiontransport", "buttontransport"],
        help="v18.1.3 전체 명령 브리지의 전송·요청 제한 방어 상태를 확인합니다.",
    )
    async def transport_status(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        try:
            from apocalypse_bot.core import rate_limit_guard as guard
            snap = guard.snapshot()
        except Exception:
            snap = {}
        embed = discord.Embed(title=_t(locale, "🛡️ ABADDON 상호작용 전송 상태", "🛡️ ABADDON Interaction Transport"), color=0x27AE60)
        embed.add_field(name=_t(locale, "🎮 버튼→기존 명령", "🎮 Button→legacy command"), value=_t(locale, "조용히 1회 응답 → 실제 결과는 일반 채널 전송", "One silent ACK → real result through normal channel delivery"), inline=False)
        embed.add_field(name=_t(locale, "🧹 Thinking", "🧹 Thinking"), value=_t(locale, "생성하지 않음 (삭제 요청도 없음)", "Not created (no cleanup webhook)"), inline=True)
        embed.add_field(name=_t(locale, "☁️ 요청 제한", "☁️ Rate limits"), value=_t(locale, f"중복 억제 {int(snap.get('duplicates_suppressed',0) or 0)}회 · 대기 {int(snap.get('remaining',0) or 0)}초", f"{int(snap.get('duplicates_suppressed',0) or 0)} suppressed · {int(snap.get('remaining',0) or 0)}s remaining"), inline=True)
        await ctx.send(embed=embed)

    @bot.command(
        name="1813상호작용검수",
        aliases=["1813버튼검수", "버튼전체검수", "v1813audit", "interactiontransportaudit"],
        help="전체 버튼/드롭다운 브리지·KoreanBots·지원 릴레이 적용 상태를 검사합니다.",
    )
    async def audit_1813(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(bot, ctx)
        try:
            from apocalypse_bot.commands import v600_game_center as bridge
            from apocalypse_bot.core import rate_limit_guard as guard
            bridge_default = bridge._invoke_command.__kwdefaults__.get("prefer_channel_delivery") is True
            dedupe_ok = "duplicates_suppressed" in guard.snapshot()
        except Exception:
            bridge_default = dedupe_ok = False
        token_set = bool(os.getenv("KOREANBOTS_TOKEN", "").strip())
        checks = [
            (_t(locale, "전체 명령 브리지 채널 전송", "Global bridge channel delivery"), bridge_default),
            (_t(locale, "조용한 Interaction ACK", "Silent interaction ACK"), bool(getattr(bot, "v1813_silent_component_ack", False))),
            (_t(locale, "1015/429 로그 병합", "1015/429 log coalescing"), dedupe_ok),
            (_t(locale, "벌목/채집/가방 직접 명령", "Logging/gather/bag direct commands"), bot.get_command("벌목") is not None and bot.get_command("채집") is not None and bot.get_command("가방") is not None),
            (_t(locale, "FINAL ECLIPSE/단말기 브리지", "FINAL ECLIPSE/terminal bridge"), bot.get_command("최종단말기") is not None),
            (_t(locale, "버그신고 릴레이", "Bug report relay"), bot.get_command("버그신고") is not None),
            (_t(locale, "설치자/소유자 지원 DM", "Installer/owner support DM"), True),
            (_t(locale, "KoreanBots 서버수 동기화 코드", "KoreanBots server-count sync"), bot.get_command("한국봇동기화") is not None),
            (_t(locale, "Gateway Presence/Members Intent 요청", "Gateway Presence/Members intents requested"), bool(getattr(bot.intents, "presences", False)) and bool(getattr(bot.intents, "members", False))),
            (_t(locale, "전체 Component 정적 응답 경로", "Static component response coverage"), STATIC_COMPONENT_CALLBACKS == STATIC_COMPONENT_COVERED),
            (_t(locale, "기존 Watchdog 보존", "Legacy watchdog preserved"), bot.get_command("1805버튼검수") is not None),
        ]
        ok = all(flag for _, flag in checks)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v18.1.3 전체 버튼·지원 검수", "🧪 ABADDON v18.1.3 Component & Support Audit"), color=0x27AE60 if ok else 0xE74C3C)
        embed.description = "\n".join(("✅" if flag else "❌") + " " + name for name, flag in checks)
        if str(상세).strip():
            kb_line = f"token={'✅' if token_set else '❌'} · last_http={kb_state.get('last_status',0)} · last_servers={kb_state.get('last_servers','-')}"
            embed.add_field(name=_t(locale, "KoreanBots", "KoreanBots"), value=kb_line, inline=False)
            embed.add_field(name=_t(locale, "Component 전수 감사", "Full component audit"), value=f"callbacks={STATIC_COMPONENT_COVERED}/{STATIC_COMPONENT_CALLBACKS} · legacy_bridges={STATIC_BRIDGE_CALLS} · eager_defer=0", inline=False)
            embed.add_field(name=_t(locale, "환경변수", "Environment"), value=f"`ABADDON_OWNER_ID`={'✅' if os.getenv('ABADDON_OWNER_ID','').strip() else '자동 판정'}\n`ABADDON_SUPPORT_URL`={'✅' if _support_url() else '미설정'}\n`KOREANBOTS_BOT_ID`=`{_kb_bot_id(bot) or '-'}`", inline=False)
            embed.add_field(name=_t(locale, "보존", "Preservation"), value=_t(locale, "기존 명령·저장 데이터 삭제 0건 · 직접 명령 방식 유지", "0 command/save deletions · direct commands preserved"), inline=False)
        await ctx.send(embed=embed)

    # Enrich the existing owner-only KoreanBots diagnostic without exposing token.
    status_cmd = bot.get_command("한국봇상태")
    if status_cmd is not None:
        async def koreanbots_status_v1813(ctx: commands.Context) -> None:
            if not await _private_owner(bot, ctx.author):
                return
            actual_id = int(getattr(bot.user, "id", 0) or 0)
            configured = os.getenv("KOREANBOTS_BOT_ID", "").strip()
            configured_id = int(configured) if configured.isdigit() else 0
            token_set = bool(os.getenv("KOREANBOTS_TOKEN", "").strip())
            status = str(getattr(bot, "status", "unknown"))
            latency_ms = round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000)
            presence_state = getattr(bot, "_abaddon_presence_guard_v1811", {}) or {}
            last_sync = kb_state.get("last_success", 0.0) or 0.0
            last_sync_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_sync)) if last_sync else "-"
            lines = [
                "🇰🇷 **한국 디스코드 리스트 / Presence + API 진단**",
                f"Discord 연결: **{'정상' if bot.is_ready() else '대기'}** · 내부 상태 `{status}` · 지연 {latency_ms}ms",
                f"봇 ID: `{actual_id}`",
                f"KOREANBOTS_BOT_ID: `{configured_id or '미설정'}` · {'✅ 일치' if configured_id in {0, actual_id} else '❌ 불일치'}",
                f"KOREANBOTS_TOKEN: **{'설정됨' if token_set else '미설정'}**",
                f"Gateway Intent 요청: Presence **{'ON' if bool(getattr(bot.intents, 'presences', False)) else 'OFF'}** · Members **{'ON' if bool(getattr(bot.intents, 'members', False)) else 'OFF'}**",
                f"설치 서버: **{len(bot.guilds)}개**",
                f"Presence 강제 갱신: **{presence_state.get('forces',0)}회** · 마지막 `{presence_state.get('last_force_at') or '-'}`",
                f"서버수 API 동기화: **{kb_state.get('successes',0)}회 성공 / {kb_state.get('failures',0)}회 실패** · 마지막 `{last_sync_text}` · HTTP `{kb_state.get('last_status',0)}`",
            ]
            if kb_state.get("last_error"):
                lines.append(f"최근 API 오류: `{kb_state['last_error']}`")
            if not token_set:
                lines.append("⚠️ KoreanBots 공식 서버수 API 동기화를 쓰려면 Render에 `KOREANBOTS_TOKEN`을 추가하세요.")
            await ctx.send("\n".join(lines))
        status_cmd.callback = koreanbots_status_v1813
        status_cmd.help = "[봇 소유자 전용] Discord Presence와 KoreanBots 서버수 API 동기화 상태를 진단합니다."
        status_cmd.description = status_cmd.help


    # Keep the public latest patch/test entrypoints aligned with v18.1.3.
    patch_cmd = bot.get_command("패치노트")
    if patch_cmd is not None:
        async def patch_v1813(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(
                title=_t(locale, "📜 ABADDON v18.1.3 · INTERACTION TRANSPORT GUARD", "📜 ABADDON v18.1.3 · INTERACTION TRANSPORT GUARD"),
                description=_t(locale, "버튼·드롭다운 전송 구조를 전수 점검하고 지원/버그 신고와 KoreanBots 서버수 동기화를 추가했습니다.", "Audits component transport, adds support/bug reporting, and KoreanBots server-count sync."),
                color=0x6C4DDB,
            )
            embed.add_field(name=_t(locale, "🎮 단일 응답 버튼", "🎮 Single-response buttons"), value=_t(locale, "빠른 버튼 명령은 defer/followup 없이 첫 Interaction 응답으로 바로 결과를 전송합니다. 느린 명령만 1.8초 후 조용히 ACK합니다.", "Fast bridged commands answer in the first interaction response; only slow commands receive a delayed silent ACK."), inline=False)
            embed.add_field(name=_t(locale, "🧹 중복 UI 억제", "🧹 Duplicate UI suppression"), value=_t(locale, "버튼으로 실행한 명령 뒤에는 기존 결과 요약/다음 행동 패널과 시네마틱 프리메시지를 다시 붙이지 않아 요청 폭주를 줄였습니다.", "Button-origin commands no longer append duplicate result/next-action panels or cinematic pre-messages."), inline=False)
            embed.add_field(name=_t(locale, "🐞 버그 신고", "🐞 Bug reports"), value=_t(locale, "`!문의처` · `!버그신고 <내용>` · 스크린샷 첨부 지원 · 신규 설치자/서버 소유자 지원 DM", "`!supportcontact` · `!reportbug <details>` · screenshot relay · installer/owner support DM"), inline=False)
            embed.add_field(name="🇰🇷 KoreanBots", value=_t(locale, "`KOREANBOTS_TOKEN` 설정 시 서버 수를 Ready/가입/이탈/변경 시 동기화하며, `!한국봇동기화`로 즉시 시험할 수 있습니다.", "With `KOREANBOTS_TOKEN`, server counts sync on ready/join/remove/change; test with `!koreanbotssync`."), inline=False)
            embed.add_field(name=_t(locale, "🧪 검수", "🧪 Audit"), value="`!1813상호작용검수 상세` · `!상호작용전송상태` · `!현재오류 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 명령·저장 데이터 삭제 0건 · 직접 !명령 방식 보존", "0 legacy command/save deletions · direct prefix commands preserved"))
            await ctx.send(embed=embed)
        patch_cmd.callback = patch_v1813
        patch_cmd.help = "ABADDON v18.1.3 버튼·드롭다운 전송/지원/KoreanBots 최신 패치노트입니다."
        patch_cmd.description = patch_cmd.help

    test_cmd = bot.get_command("테스트")
    if test_cmd is not None:
        async def test_v1813(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            mode = " ".join(str(x) for x in args) if args else str(kwargs.get("상세", kwargs.get("mode", "")))
            audit = bot.get_command("1813상호작용검수")
            if audit is None:
                await ctx.send(_t(_locale(bot, ctx), "❌ v18.1.3 검수 명령을 찾지 못했습니다.", "❌ v18.1.3 audit command was not found."))
                return
            await ctx.invoke(audit, 상세="상세" if mode.strip().casefold() in {"상세", "detail", "full", "detailed"} else "")
        test_cmd.callback = test_v1813
        test_cmd.help = "가장 최근 v18.1.3 버튼·지원·KoreanBots 범위를 읽기 전용으로 검사합니다."
        test_cmd.description = test_cmd.help

    # Refresh the public command catalog so support/report commands are discoverable.
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        entries = hub._build_registry(bot)
        setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} command catalog refresh warning] {type(exc).__name__}: {exc}", flush=True)

    print(
        f"[ABADDON v{VERSION}] interaction/support/KoreanBots guard registered: "
        "component_response=single-fast-path delayed_ack=1.8s rate_log_dedupe=60s "
        "bug_relay=owner_dm install_support_dm=enabled koreanbots_stats=v2",
        flush=True,
    )
