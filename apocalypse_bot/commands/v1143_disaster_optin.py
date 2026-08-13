from __future__ import annotations

"""ABADDON v11.4.3 server-opt-in disaster notification hotfix."""

from datetime import datetime, timezone
from typing import Any, Callable, List, MutableMapping, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v790_operations_disaster as operations
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard

VERSION = "11.4.3"
MIGRATION_KEY = "opt_in_migrated_v1143"

_ORIGINAL_GUILD_STATE = operations._guild_state
_ORIGINAL_FIND_CHANNEL = operations._find_announcement_channel


def _migrate_settings(settings: MutableMapping[str, Any]) -> bool:
    """Migrate legacy all-server defaults to explicit per-server opt-in."""
    changed = False
    if not bool(settings.get(MIGRATION_KEY)):
        settings["subscription_enabled"] = False
        settings["auto_enabled"] = False
        settings["next_auto_at"] = ""
        settings[MIGRATION_KEY] = True
        changed = True
    settings.setdefault("subscription_enabled", False)
    settings.setdefault("auto_enabled", False)
    settings.setdefault("channel_id", 0)
    settings.setdefault("next_auto_at", "")
    return changed


def _guild_state_optin(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    state = _ORIGINAL_GUILD_STATE(world_data, guild_id)
    disaster = state.setdefault("disaster", {})
    if not isinstance(disaster, dict):
        disaster = {}
        state["disaster"] = disaster
    _migrate_settings(disaster)
    return state


def _configured_channel(guild: discord.Guild, state: MutableMapping[str, Any]) -> Optional[discord.TextChannel]:
    settings = state.get("disaster") if isinstance(state.get("disaster"), dict) else {}
    if not bool(settings.get("subscription_enabled", False)):
        return None
    channel_id = operations._safe_int(settings.get("channel_id"), 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    return channel if isinstance(channel, discord.TextChannel) else None


def _is_admin(ctx: commands.Context) -> bool:
    member = ctx.author
    return isinstance(member, discord.Member) and (
        member.guild_permissions.administrator or member.guild_permissions.manage_guild
    )


def _status_lines(guild: discord.Guild, settings: MutableMapping[str, Any]) -> str:
    subscribed = bool(settings.get("subscription_enabled", False))
    enabled = bool(settings.get("auto_enabled", False)) and subscribed
    channel_id = operations._safe_int(settings.get("channel_id"), 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    channel_text = channel.mention if isinstance(channel, discord.TextChannel) else "미설정"
    due = operations._parse(settings.get("next_auto_at"))
    if not enabled:
        due_text = "자동 알림 꺼짐"
    elif due is None:
        due_text = "다음 일정 생성 대기"
    else:
        seconds = max(0, int((due - datetime.now(timezone.utc)).total_seconds()))
        due_text = operations.disaster_core._format_seconds(seconds)
    return (
        f"🔔 서버 재난 알림: **{'구독 중' if subscribed else '구독 안 함'}**\n"
        f"📡 자동 재난: **{'켜짐' if enabled else '꺼짐'}**\n"
        f"📢 알림 채널: **{channel_text}**\n"
        f"⏱️ 다음 감시: **{due_text}**"
    )


def _checks(bot: commands.Bot, world_data: MutableMapping[str, Any]) -> List[Tuple[str, bool, str]]:
    fresh: MutableMapping[str, Any] = {}
    state = _guild_state_optin(fresh, 123)
    settings = state["disaster"]

    legacy: MutableMapping[str, Any] = {
        "v790_operations": {
            "schema_version": 1,
            "guilds": {
                "456": {
                    "disaster": {
                        "auto_enabled": True,
                        "channel_id": 0,
                        "next_auto_at": "2099-01-01T00:00:00+00:00",
                    }
                }
            },
            "intake": [],
            "stats": {},
        }
    }
    legacy_settings = _guild_state_optin(legacy, 456)["disaster"]

    auto_command = bot.get_command("재난자동")
    channel_command = bot.get_command("재난채널")
    subscribe_command = bot.get_command("재난알림")
    clear_command = bot.get_command("재난알림해제")

    return [
        ("신규 서버 기본 꺼짐", not settings.get("subscription_enabled") and not settings.get("auto_enabled"), str(dict(settings))),
        ("기존 전체알림 자동 해제", not legacy_settings.get("subscription_enabled") and not legacy_settings.get("auto_enabled") and not legacy_settings.get("next_auto_at"), str(dict(legacy_settings))),
        ("명시적 채널만 사용", operations._find_announcement_channel is _configured_channel, "키워드·시스템 채널 자동 선택 제거"),
        ("기존 자동 명령 유지", auto_command is not None, "!재난자동 ON/OFF"),
        ("기존 채널 명령 유지", channel_command is not None, "!재난채널 #채널"),
        ("서버별 구독 명령", subscribe_command is not None, "!재난알림 ON/OFF"),
        ("구독 해제 명령", clear_command is not None, "!재난알림해제"),
    ]


def register_v1143_disaster_optin(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[dict[str, Any]],
) -> None:
    # Patch globals used by the already-running v7.9 scheduler closure.
    operations._guild_state = _guild_state_optin
    operations._find_announcement_channel = _configured_channel

    changed = False
    root = operations._root(world_data)
    guilds = root.get("guilds") if isinstance(root.get("guilds"), dict) else {}
    for guild_id, row in list(guilds.items()):
        if not isinstance(row, dict):
            continue
        disaster = row.setdefault("disaster", {})
        if isinstance(disaster, dict) and _migrate_settings(disaster):
            changed = True
    if changed:
        save_data()

    async def ensure_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return False
        if not _is_admin(ctx):
            await ctx.send("⛔ 서버 관리 권한이 필요합니다.")
            return False
        return True

    async def set_subscription(ctx: commands.Context, token: str) -> None:
        if not await ensure_admin(ctx):
            return
        assert ctx.guild is not None
        state = operations._guild_state(world_data, int(ctx.guild.id))
        settings = state["disaster"]
        normalized = str(token or "").strip().casefold()

        if normalized in {"켜기", "켜짐", "on", "true", "1", "구독"}:
            channel_id = operations._safe_int(settings.get("channel_id"), 0)
            channel = ctx.guild.get_channel(channel_id) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
            if channel is None:
                await ctx.send("⚠️ 알림을 게시할 텍스트 채널을 먼저 `!재난채널 #채널`로 지정해주세요.")
                return
            settings["channel_id"] = int(channel.id)
            settings["subscription_enabled"] = True
            settings["auto_enabled"] = True
            if operations._parse(settings.get("next_auto_at")) is None:
                operations._schedule_next(state)
            save_data()
            await ctx.send(f"✅ 이 서버만 재난 자동 알림을 구독합니다.\n📢 게시 채널: {channel.mention}")
            return

        if normalized in {"끄기", "꺼짐", "off", "false", "0", "해제"}:
            settings["subscription_enabled"] = False
            settings["auto_enabled"] = False
            settings["next_auto_at"] = ""
            save_data()
            await ctx.send("✅ 이 서버의 자동 재난 알림을 껐습니다. 수동 `!재난발생`은 계속 사용할 수 있습니다.")
            return

        await ctx.send(
            _status_lines(ctx.guild, settings)
            + "\n\n관리자 사용법: `!재난알림 ON/OFF` · `!재난채널 #채널` · `!재난알림해제`"
        )

    auto_command = bot.get_command("재난자동")
    if auto_command is not None:
        async def disaster_auto_v1143(ctx: commands.Context, 상태: str = "") -> None:
            await set_subscription(ctx, 상태)
        auto_command.callback = disaster_auto_v1143
        auto_command.help = "서버 관리자가 이 서버의 자동 재난 알림을 명시적으로 구독하거나 해제합니다."
        auto_command.description = auto_command.help

    channel_command = bot.get_command("재난채널")
    if channel_command is not None:
        async def disaster_channel_v1143(ctx: commands.Context, 채널: Optional[discord.TextChannel] = None) -> None:
            if not await ensure_admin(ctx):
                return
            assert ctx.guild is not None
            target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
            if target is None:
                await ctx.send("⚠️ 텍스트 채널을 지정해주세요.")
                return
            state = operations._guild_state(world_data, int(ctx.guild.id))
            settings = state["disaster"]
            settings["channel_id"] = int(target.id)
            settings["subscription_enabled"] = True
            settings["auto_enabled"] = True
            if operations._parse(settings.get("next_auto_at")) is None:
                operations._schedule_next(state)
            save_data()
            await ctx.send(f"✅ 이 서버의 재난 알림을 {target.mention}에서만 받습니다. 자동 알림도 켰습니다.")
        channel_command.callback = disaster_channel_v1143
        channel_command.help = "자동 공동 재난을 받을 서버 전용 채널을 지정하고 구독을 켭니다."
        channel_command.description = channel_command.help
        if bot.get_command("disasterchannel") is None:
            bot.all_commands["disasterchannel"] = channel_command
            if "disasterchannel" not in channel_command.aliases:
                channel_command.aliases.append("disasterchannel")

    if auto_command is not None and bot.get_command("disasterauto") is None:
        bot.all_commands["disasterauto"] = auto_command
        if "disasterauto" not in auto_command.aliases:
            auto_command.aliases.append("disasterauto")

    @bot.command(
        name="재난알림",
        aliases=["재난구독", "비상알림", "disasteralerts", "disastersubscribe"],
        help="서버별 자동 재난 알림 구독 상태를 확인하거나 켜고 끕니다.",
    )
    async def disaster_alerts(ctx: commands.Context, 상태: str = "") -> None:
        await set_subscription(ctx, 상태)

    @bot.command(
        name="재난알림해제",
        aliases=["재난채널해제", "비상알림해제", "removedisasteralerts"],
        help="이 서버의 자동 재난 알림 구독과 지정 채널을 모두 해제합니다.",
    )
    async def disaster_alerts_clear(ctx: commands.Context) -> None:
        if not await ensure_admin(ctx):
            return
        assert ctx.guild is not None
        state = operations._guild_state(world_data, int(ctx.guild.id))
        settings = state["disaster"]
        settings["subscription_enabled"] = False
        settings["auto_enabled"] = False
        settings["channel_id"] = 0
        settings["next_auto_at"] = ""
        save_data()
        await ctx.send("✅ 재난 자동 알림 구독과 게시 채널을 모두 해제했습니다.")

    @bot.command(
        name="재난알림검수",
        aliases=["disasteralertaudit", "disasternotificationaudit", "v1143audit"],
        help="v11.4.3 서버별 재난 알림 구독 변경만 검사합니다.",
    )
    async def disaster_alert_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        rows = _checks(bot, world_data)
        passed = sum(1 for _, ok, _ in rows if ok)
        embed = _dashboard(
            bot,
            locale,
            f"🔔 ABADDON v{VERSION} 재난 알림 검수 · {passed}/{len(rows)}",
            f"🔔 ABADDON v{VERSION} Disaster Alert Audit · {passed}/{len(rows)}",
            "자동 재난 알림이 모든 서버가 아닌 명시적으로 구독한 서버에만 게시되는지 검사합니다.",
            "Checks that automatic disaster alerts post only in explicitly subscribed servers.",
            discord.Color.green() if passed == len(rows) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!재난알림검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1143_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await disaster_alert_audit.callback(ctx, 모드)
        test_command.callback = v1143_test
        test_command.help = "v11.4.3에서 변경한 서버별 재난 알림 구독·채널 제한만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1143_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"🔔 ABADDON v{VERSION} — 서버별 재난 알림 구독",
                f"🔔 ABADDON v{VERSION} — Per-Server Disaster Alerts",
                "이번 핫픽스에서 실제로 변경한 항목만 표시합니다.",
                "Shows only the changes made in this hotfix.",
                discord.Color.red(),
            )
            embed.add_field(name=_t(locale, "🔕 기본 꺼짐", "🔕 Off by Default"), value=_t(locale, "새 서버와 기존 서버 모두 자동 재난 알림을 기본 해제합니다.", "Automatic disaster alerts are disabled by default for new and existing servers."), inline=False)
            embed.add_field(name=_t(locale, "✅ 서버별 구독", "✅ Per-Server Opt-In"), value=_t(locale, "관리자가 `!재난알림 켜기` 또는 `!재난채널 #채널`을 실행한 서버에만 표시합니다.", "Alerts appear only after an admin uses `!disasteralerts on` or configures a channel."), inline=False)
            embed.add_field(name=_t(locale, "📢 지정 채널만", "📢 Configured Channel Only"), value=_t(locale, "채널명이 비상·공지와 비슷하다는 이유로 자동 선택하지 않습니다.", "The bot no longer guesses a channel from its name or the system channel."), inline=False)
            embed.add_field(name=_t(locale, "🧹 완전 해제", "🧹 Full Removal"), value=_t(locale, "`!재난알림해제`로 구독·자동 발생·채널 설정을 한 번에 지웁니다.", "`!removedisasteralerts` clears the subscription, scheduler and channel together."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1143_notes
        patch_notes.help = f"ABADDON v{VERSION} 서버별 재난 알림 핫픽스를 확인합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1143_disaster_optin"]
    guide.append({
        "id": "v1143_disaster_optin",
        "emoji": "🔔",
        "title": "v11.4.3 서버별 재난 알림",
        "hint": "기본 꺼짐 · 서버별 관리자 구독 · 지정 채널만 게시 · 완전 해제",
        "commands": [
            "!재난알림 ON/OFF · !재난채널 #채널 · !재난알림해제",
            "!재난알림검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1143_version = VERSION  # type: ignore[attr-defined]
    bot.v1143_checks = lambda: _checks(bot, world_data)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] disaster_alerts=server_opt_in default=off configured_channel_only=true", flush=True)
