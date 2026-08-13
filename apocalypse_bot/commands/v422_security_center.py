from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, Optional, Tuple

import discord
from discord.ext import commands


LOG_TYPES = {
    "보안": "security",
    "보안알림": "security",
    "security": "security",
    "메시지": "message",
    "메시지로그": "message",
    "message": "message",
    "멤버": "member",
    "멤버로그": "member",
    "member": "member",
    "운영": "operation",
    "운영로그": "operation",
    "operation": "operation",
}

LOG_CHANNEL_NAMES = {
    "security": "🚨・보안-알림",
    "message": "📨・메시지-로그",
    "member": "👥・멤버-로그",
    "operation": "🔧・운영-로그",
}

LOG_CHANNEL_TOPICS = {
    "security": "ABADDON 자동관리, 경고, 타임아웃, 레이드 및 보안 이벤트 기록",
    "message": "ABADDON 메시지 삭제 및 수정 기록",
    "member": "ABADDON 멤버 입장, 퇴장, 역할 및 닉네임 변경 기록",
    "operation": "ABADDON 운영 명령어와 서버 설정 변경 기록",
}

ACTION_NAMES = {
    "warning": "경고",
    "timeout": "타임아웃",
    "untimeout": "타임아웃 해제",
    "kick": "추방",
    "ban": "차단",
    "unban": "차단 해제",
    "quarantine": "격리",
    "unquarantine": "격리 해제",
    "softban": "소프트밴",
}

SECURITY_COMMAND_PREFIXES = (
    "운영",
    "관리",
    "경고",
    "타임아웃",
    "추방",
    "차단",
    "소프트밴",
    "격리",
    "레이드",
    "비상",
    "서버잠금",
    "서버해제",
    "자동관리",
    "자동처벌",
    "욕설",
    "초대",
    "예외채널",
    "로그",
    "보안",
    "역할지급",
    "역할회수",
    "닉네임",
    "청소",
    "슬로우",
    "채널잠금",
    "채널해제",
    "대화금지",
    "대화허용",
    "셀프역할",
    "접수",
    "답변",
    "빠른답변",
)


def register_v422_security_center(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    """ABADDON V4.2.2 split logging, automod policy, and user-safe records."""

    if getattr(bot, "_abaddon_v422_security_center_registered", False):
        return

    management_root = world_data.setdefault("server_management", {})

    def guild_key(guild_or_id: Any) -> str:
        return str(getattr(guild_or_id, "id", guild_or_id))

    def get_settings(guild_or_id: Any) -> Dict[str, Any]:
        settings = management_root.setdefault(guild_key(guild_or_id), {})
        settings.setdefault("log_channel_id", 0)
        log_channels = settings.setdefault("log_channels", {})
        for key in LOG_CHANNEL_NAMES:
            log_channels.setdefault(key, 0)
        settings.setdefault("mod_role_ids", [])
        settings.setdefault("warnings", {})
        settings.setdefault("cases", [])
        settings.setdefault("stats", {})
        automod = settings.setdefault("automod", {})
        automod.setdefault("enabled", False)
        automod.setdefault("spam", True)
        automod.setdefault("mention_spam", True)
        automod.setdefault("invites", False)
        automod.setdefault("bad_words", False)
        automod.setdefault("auto_timeout", False)
        automod.setdefault("spam_count", 6)
        automod.setdefault("spam_seconds", 8)
        automod.setdefault("mention_limit", 5)
        automod.setdefault("strike_limit", 3)
        automod.setdefault("strike_window", 600)
        automod.setdefault("timeout_minutes", 10)
        automod.setdefault("action_mode", "삭제")
        automod.setdefault("invite_exempt_channel_ids", [])
        alert = settings.setdefault("new_account_alert", {})
        alert.setdefault("enabled", False)
        alert.setdefault("age_days", 7)
        settings.setdefault("operation_command_log", True)
        return settings

    def parse_toggle(value: str) -> Optional[bool]:
        text = value.strip().lower()
        if text in {"켜기", "켜", "on", "true", "1", "활성화"}:
            return True
        if text in {"끄기", "꺼", "off", "false", "0", "비활성화"}:
            return False
        return None

    def operator_role_ids(settings: Dict[str, Any]) -> set[int]:
        result: set[int] = set()
        for value in settings.get("mod_role_ids", []):
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
        return result

    def is_operator(member: discord.Member) -> bool:
        permissions = member.guild_permissions
        if permissions.administrator or permissions.manage_guild or member.id == member.guild.owner_id:
            return True
        configured = operator_role_ids(get_settings(member.guild))
        return any(role.id in configured for role in member.roles)

    async def require_operator(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return False
        if not is_operator(ctx.author):
            await ctx.send("❌ 이 명령어는 서버 운영진만 사용할 수 있습니다.")
            return False
        return True

    async def require_manager(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return False
        permissions = ctx.author.guild_permissions
        if not (permissions.administrator or permissions.manage_guild or ctx.author.id == ctx.guild.owner_id):
            await ctx.send("❌ 서버 관리 권한이 필요합니다.")
            return False
        return True

    def resolve_channel(guild: discord.Guild, value: Any) -> Optional[discord.TextChannel]:
        try:
            channel_id = int(value or 0)
        except (TypeError, ValueError):
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    def get_log_channel(guild: discord.Guild, log_type: str) -> Optional[discord.TextChannel]:
        settings = get_settings(guild)
        channel = resolve_channel(guild, settings.get("log_channels", {}).get(log_type, 0))
        if channel is not None:
            return channel
        channel = resolve_channel(guild, settings.get("log_channel_id", 0))
        if channel is not None:
            return channel
        return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAMES.get(log_type, ""))

    async def send_log(
        guild: discord.Guild,
        log_type: str,
        title: str,
        description: str,
        *,
        color: int = 0x8E44AD,
        fields: Optional[Iterable[Tuple[str, str, bool]]] = None,
    ) -> None:
        channel = get_log_channel(guild, log_type)
        if channel is None:
            return
        embed = discord.Embed(
            title=title,
            description=description[:4000],
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name[:256], value=(value or "-")[:1024], inline=inline)
        embed.set_footer(text=f"ABADDON SECURITY CENTER · 서버 ID {guild.id}")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    def format_case(case: Dict[str, Any]) -> str:
        case_id = int(case.get("id", 0) or 0)
        action = ACTION_NAMES.get(str(case.get("action", "")), str(case.get("action", "알 수 없음")))
        reason = str(case.get("reason", "사유 없음")).replace("\n", " ")[:120]
        active = "활성" if case.get("active", True) else "종료"
        created_at = str(case.get("created_at", ""))[:19].replace("T", " ") or "기록 없음"
        return f"`#{case_id}` **{action}** · {active} · {created_at}\n└ {reason}"

    def safe_id_set(values: Iterable[Any]) -> set[int]:
        result: set[int] = set()
        for value in values:
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
        return result

    def normalize_mode(value: str) -> Optional[str]:
        text = value.strip().lower()
        if text in {"알림", "알림만", "감지", "notify", "notice"}:
            return "알림"
        if text in {"삭제", "삭제만", "delete"}:
            return "삭제"
        if text in {"타임아웃", "처벌", "timeout"}:
            return "타임아웃"
        return None

    @bot.command(name="보안센터도움말", aliases=["보안도움말"], help="현재 보안센터와 분리 로그 명령어를 확인합니다.")
    async def security_help(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        embed = discord.Embed(
            title="🛡️ ABADDON 통합 보안센터",
            description="기존 SERVER GUARD 기능을 유지하며 로그 분리, 자동관리 강도, 사용자 기록 조회를 추가합니다.",
            color=0xC0392B,
        )
        embed.add_field(
            name="📚 로그 센터 · 관리자",
            value=(
                "`!보안초기설정` · `!보안상태` · `!보안테스트`\n"
                "`!로그채널설정 보안/메시지/멤버/운영 #채널`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🤖 자동 관리 · 관리자",
            value=(
                "`!자동관리모드 알림/삭제/타임아웃`\n"
                "`!자동관리기준 [도배개수] [초] [멘션] [누적] [타임아웃분]`\n"
                "`!초대허용채널 #채널` · `!초대허용해제 #채널` · `!초대허용목록`\n"
                "`!신생계정알림 ON/OFF [기준일]`"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚖️ 기록 조회",
            value="일반 사용자: `!내경고` · 운영진: `!제재기록 [@멤버] [개수]`",
            inline=False,
        )
        embed.set_footer(text="모든 신규 명령어는 ! prefix 전용이며 슬래시 명령어 수를 늘리지 않습니다.")
        await ctx.send(embed=embed)

    @bot.command(name="보안초기설정", aliases=["로그초기설정"], help="비공개 보안센터와 분리 로그 채널을 자동 생성합니다.")
    async def security_quick_setup(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        guild = ctx.guild
        progress = await ctx.send("⏳ **보안센터를 구성하는 중입니다.** 기존 채널은 재사용하고 없는 채널만 만듭니다...")
        settings = get_settings(guild)

        overwrites: Dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
            )
        for role_id in operator_role_ids(settings):
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        category = discord.utils.get(guild.categories, name="🛡️・보안센터")
        created: list[str] = []
        reused: list[str] = []
        try:
            if category is None:
                category = await guild.create_category(
                    "🛡️・보안센터",
                    overwrites=overwrites,
                    reason=f"ABADDON 보안센터 초기설정 | {ctx.author}",
                )
                created.append(category.name)
            else:
                reused.append(category.name)

            for log_type, name in LOG_CHANNEL_NAMES.items():
                channel = discord.utils.get(guild.text_channels, name=name)
                if channel is None:
                    channel = await guild.create_text_channel(
                        name,
                        category=category,
                        topic=LOG_CHANNEL_TOPICS[log_type],
                        overwrites=overwrites,
                        reason=f"ABADDON 보안 로그 초기설정 | {ctx.author}",
                    )
                    created.append(name)
                else:
                    reused.append(name)
                    if category is not None and channel.category_id != category.id:
                        try:
                            await channel.edit(category=category, reason="ABADDON 보안 로그 정리")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                try:
                    await channel.set_permissions(
                        guild.default_role,
                        view_channel=False,
                        reason="ABADDON 보안 로그 비공개 설정",
                    )
                    if guild.me is not None:
                        await channel.set_permissions(
                            guild.me,
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                            embed_links=True,
                            attach_files=True,
                            reason="ABADDON 보안 로그 봇 권한 설정",
                        )
                    for role_id in operator_role_ids(settings):
                        role = guild.get_role(role_id)
                        if role is not None:
                            await channel.set_permissions(
                                role,
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                                reason="ABADDON 운영 역할 로그 권한 설정",
                            )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                settings["log_channels"][log_type] = channel.id

            operation_channel = get_log_channel(guild, "operation")
            if operation_channel is not None:
                settings["log_channel_id"] = operation_channel.id
            save_data()
        except discord.Forbidden:
            await progress.edit(content="❌ 채널 관리 권한이 없어 보안센터를 만들지 못했습니다.")
            return
        except discord.HTTPException as exc:
            await progress.edit(content=f"❌ Discord API 오류로 보안센터 설정을 완료하지 못했습니다: `{exc}`")
            return

        await progress.edit(
            content=(
                "✅ **ABADDON 보안센터 설정 완료**\n"
                f"새로 생성: {', '.join(created) if created else '없음'}\n"
                f"기존 재사용: {', '.join(reused) if reused else '없음'}\n"
                "자동 관리는 기존 설정을 유지합니다. 활성화: `!자동관리 켜기` · 처리 선택: `!자동관리모드 삭제`"
            )
        )
        await send_log(
            guild,
            "operation",
            "🛡️ 보안센터 초기설정 완료",
            f"실행자: {ctx.author.mention}\n분리 로그 채널 4개가 연결되었습니다.",
            color=0x2ECC71,
        )

    @bot.command(name="로그채널설정", help="보안/메시지/멤버/운영 로그 채널을 개별 지정합니다.")
    async def set_split_log_channel(ctx: commands.Context, 종류: str, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        log_type = LOG_TYPES.get(종류.strip().lower()) or LOG_TYPES.get(종류.strip())
        if log_type is None:
            await ctx.send("⚠️ 종류는 `보안`, `메시지`, `멤버`, `운영` 중 하나로 입력해주세요.")
            return
        settings = get_settings(ctx.guild)
        settings["log_channels"][log_type] = 채널.id
        if log_type == "operation":
            settings["log_channel_id"] = 채널.id
        save_data()
        await ctx.send(f"✅ **{종류} 로그** 채널을 {채널.mention}(으)로 설정했습니다.")

    @bot.command(name="보안상태", aliases=["보안대시보드"], help="분리 로그와 자동 관리 설정을 한 화면에 표시합니다.")
    async def security_status(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        settings = get_settings(ctx.guild)
        automod = settings["automod"]
        channels = settings["log_channels"]
        invite_exempt = [
            ctx.guild.get_channel(channel_id)
            for channel_id in safe_id_set(automod.get("invite_exempt_channel_ids", []))
        ]
        invite_exempt = [channel for channel in invite_exempt if isinstance(channel, discord.TextChannel)]
        embed = discord.Embed(
            title="🛡️ ABADDON 보안 상태",
            description=f"**{ctx.guild.name}**의 SERVER GUARD 자동 관리 및 로그 연결 상태",
            color=0xC0392B,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="📚 분리 로그",
            value=(
                f"보안: {getattr(get_log_channel(ctx.guild, 'security'), 'mention', '미설정')}\n"
                f"메시지: {getattr(get_log_channel(ctx.guild, 'message'), 'mention', '미설정')}\n"
                f"멤버: {getattr(get_log_channel(ctx.guild, 'member'), 'mention', '미설정')}\n"
                f"운영: {getattr(get_log_channel(ctx.guild, 'operation'), 'mention', '미설정')}"
            ),
            inline=False,
        )
        embed.add_field(
            name="🤖 자동 관리",
            value=(
                f"전체: **{'켜짐' if automod.get('enabled') else '꺼짐'}** · 처리: **{automod.get('action_mode', '삭제')}**\n"
                f"도배: **{automod.get('spam_count', 6)}개/{automod.get('spam_seconds', 8)}초** · "
                f"멘션: **{automod.get('mention_limit', 5)}개**\n"
                f"누적: **{automod.get('strike_limit', 3)}회/{int(automod.get('strike_window', 600)) // 60}분** · "
                f"타임아웃: **{automod.get('timeout_minutes', 10)}분**"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔗 초대 링크",
            value=(
                f"차단: **{'켜짐' if automod.get('invites') else '꺼짐'}**\n"
                f"허용 채널: {', '.join(channel.mention for channel in invite_exempt) or '없음'}"
            ),
            inline=True,
        )
        new_alert = settings["new_account_alert"]
        embed.add_field(
            name="🆕 신생 계정 알림",
            value=f"**{'켜짐' if new_alert.get('enabled') else '꺼짐'}** · 기준 **{new_alert.get('age_days', 7)}일 미만**",
            inline=True,
        )
        embed.set_footer(text="설정 자동 생성: !보안초기설정 · 상세 명령: !보안센터도움말")
        await ctx.send(embed=embed)

    @bot.command(name="보안테스트", help="분리 로그 채널 4곳에 테스트 메시지를 전송합니다.")
    async def security_test(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        results: list[str] = []
        for log_type, display in (("security", "보안"), ("message", "메시지"), ("member", "멤버"), ("operation", "운영")):
            channel = get_log_channel(ctx.guild, log_type)
            if channel is None:
                results.append(f"❌ {display}: 미설정")
                continue
            await send_log(
                ctx.guild,
                log_type,
                f"🧪 {display} 로그 테스트",
                f"실행자: {ctx.author.mention}\n채널 연결 테스트가 정상적으로 전송되었습니다.",
                color=0x3498DB,
            )
            results.append(f"✅ {display}: {channel.mention}")
        await ctx.send("\n".join(results))

    @bot.command(name="자동관리모드", help="자동관리 적발 시 알림만/삭제/타임아웃 처리 중 하나를 선택합니다.")
    async def set_automod_mode(ctx: commands.Context, 모드: str) -> None:
        if not await require_manager(ctx):
            return
        normalized = normalize_mode(모드)
        if normalized is None:
            await ctx.send("⚠️ 사용법: `!자동관리모드 알림`, `!자동관리모드 삭제`, `!자동관리모드 타임아웃`")
            return
        automod = get_settings(ctx.guild)["automod"]
        automod["enabled"] = True
        automod["action_mode"] = normalized
        automod["auto_timeout"] = normalized == "타임아웃"
        save_data()
        descriptions = {
            "알림": "메시지는 유지하고 운영진 로그와 채널 알림만 남깁니다.",
            "삭제": "위반 메시지를 삭제하지만 자동 타임아웃은 하지 않습니다.",
            "타임아웃": "위반 메시지를 삭제하고 누적 기준 도달 시 자동 타임아웃합니다.",
        }
        await ctx.send(f"✅ 자동관리 처리 모드를 **{normalized}**(으)로 설정했습니다.\n{descriptions[normalized]}")

    @bot.command(name="자동관리기준", help="도배, 멘션, 누적 횟수와 자동 타임아웃 기준을 설정하거나 확인합니다.")
    async def automod_thresholds(
        ctx: commands.Context,
        도배개수: int = 0,
        도배초: int = 0,
        멘션개수: int = 0,
        누적횟수: int = 0,
        타임아웃분: int = 0,
    ) -> None:
        if not await require_manager(ctx):
            return
        automod = get_settings(ctx.guild)["automod"]
        values = (도배개수, 도배초, 멘션개수, 누적횟수, 타임아웃분)
        if any(value < 0 for value in values):
            await ctx.send("❌ 기준 값은 음수로 설정할 수 없습니다.")
            return
        if any(values):
            automod["spam_count"] = max(3, min(20, 도배개수 or int(automod.get("spam_count", 6))))
            automod["spam_seconds"] = max(2, min(60, 도배초 or int(automod.get("spam_seconds", 8))))
            automod["mention_limit"] = max(2, min(30, 멘션개수 or int(automod.get("mention_limit", 5))))
            automod["strike_limit"] = max(2, min(10, 누적횟수 or int(automod.get("strike_limit", 3))))
            automod["timeout_minutes"] = max(1, min(40320, 타임아웃분 or int(automod.get("timeout_minutes", 10))))
            save_data()
        await ctx.send(
            "🧮 **현재 자동관리 기준**\n"
            f"도배: **{automod.get('spam_count', 6)}개 / {automod.get('spam_seconds', 8)}초**\n"
            f"멘션 도배: **{automod.get('mention_limit', 5)}개 이상**\n"
            f"반복 위반: **{automod.get('strike_limit', 3)}회 / {int(automod.get('strike_window', 600)) // 60}분**\n"
            f"자동 타임아웃: **{automod.get('timeout_minutes', 10)}분**\n"
            "변경 예시: `!자동관리기준 6 8 5 3 10`"
        )

    @bot.command(name="초대허용채널", help="Discord 초대 링크 차단에서 제외할 채널을 추가합니다.")
    async def invite_exempt_add(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        values = get_settings(ctx.guild)["automod"].setdefault("invite_exempt_channel_ids", [])
        if 채널.id not in safe_id_set(values):
            values.append(채널.id)
            save_data()
        await ctx.send(f"✅ {채널.mention}에서는 Discord 초대 링크를 허용합니다.")

    @bot.command(name="초대허용해제", help="Discord 초대 링크 허용 채널에서 제거합니다.")
    async def invite_exempt_remove(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        values = get_settings(ctx.guild)["automod"].setdefault("invite_exempt_channel_ids", [])
        filtered = [value for value in safe_id_set(values) if value != 채널.id]
        get_settings(ctx.guild)["automod"]["invite_exempt_channel_ids"] = filtered
        save_data()
        await ctx.send(f"✅ {채널.mention}의 초대 링크 허용을 해제했습니다.")

    @bot.command(name="초대허용목록", help="Discord 초대 링크 차단에서 제외된 채널을 확인합니다.")
    async def invite_exempt_list(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        values = get_settings(ctx.guild)["automod"].get("invite_exempt_channel_ids", [])
        channels = [ctx.guild.get_channel(value) for value in safe_id_set(values)]
        channels = [channel for channel in channels if isinstance(channel, discord.TextChannel)]
        await ctx.send("🔗 초대 링크 허용 채널: " + (", ".join(channel.mention for channel in channels) or "없음"))

    @bot.command(name="신생계정알림", help="설정한 일수보다 새 계정이 가입하면 보안 로그로 알립니다.")
    async def new_account_alert(ctx: commands.Context, 상태: str, 기준일: int = 7) -> None:
        if not await require_manager(ctx):
            return
        enabled = parse_toggle(상태)
        if enabled is None:
            await ctx.send("⚠️ 사용법: `!신생계정알림 ON 7` 또는 `!신생계정알림 OFF`")
            return
        alert = get_settings(ctx.guild)["new_account_alert"]
        alert["enabled"] = enabled
        alert["age_days"] = max(0, min(365, 기준일))
        save_data()
        await ctx.send(f"✅ 신생 계정 알림을 **{'켜짐' if enabled else '꺼짐'}**으로 설정했습니다. 기준: **{alert['age_days']}일 미만**")

    @bot.command(name="내경고", aliases=["내제재"], help="자신의 활성 경고와 최근 제재 기록을 확인합니다.")
    async def my_warnings(ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        warnings = [
            item for item in settings.get("warnings", {}).get(str(ctx.author.id), [])
            if isinstance(item, dict) and item.get("active", True)
        ]
        cases = [
            item for item in settings.get("cases", [])
            if isinstance(item, dict) and int(item.get("target_id", 0) or 0) == ctx.author.id
        ][-10:]
        embed = discord.Embed(
            title="⚖️ 내 SERVER GUARD 기록",
            description=f"{ctx.author.mention} · 활성 경고 **{len(warnings)}건**",
            color=0xE67E22 if warnings else 0x2ECC71,
        )
        embed.add_field(
            name="최근 기록",
            value="\n\n".join(format_case(case) for case in reversed(cases))[:4000] if cases else "기록이 없습니다.",
            inline=False,
        )
        embed.set_footer(text="운영진의 제재 조치에 문의가 필요하면 서버 문의 채널을 이용해주세요.")
        try:
            await ctx.author.send(embed=embed)
            await ctx.send("📩 제재 기록을 DM으로 보냈습니다.", delete_after=8)
        except discord.Forbidden:
            await ctx.send("⚠️ DM을 보낼 수 없어 현재 채널에 30초 동안 표시합니다.", delete_after=8)
            await ctx.send(embed=embed, delete_after=30)

    @bot.command(name="제재기록", help="운영진이 전체 또는 특정 멤버의 최근 제재 기록을 확인합니다.")
    async def moderation_history(
        ctx: commands.Context,
        대상: Optional[discord.Member] = None,
        개수: int = 10,
    ) -> None:
        if not await require_operator(ctx):
            return
        limit = max(1, min(30, 개수))
        cases = [item for item in get_settings(ctx.guild).get("cases", []) if isinstance(item, dict)]
        if 대상 is not None:
            cases = [item for item in cases if int(item.get("target_id", 0) or 0) == 대상.id]
        selected = cases[-limit:]
        title = f"⚖️ {대상.display_name} 제재 기록" if 대상 is not None else "⚖️ 서버 최근 제재 기록"
        await ctx.send(embed=discord.Embed(
            title=title,
            description="\n\n".join(format_case(case) for case in reversed(selected))[:4000] if selected else "기록이 없습니다.",
            color=0x8E44AD,
        ))

    async def handle_new_account(member: discord.Member) -> None:
        if member.bot:
            return
        settings = get_settings(member.guild)
        alert = settings["new_account_alert"]
        if not alert.get("enabled", False):
            return
        threshold = max(0, int(alert.get("age_days", 7)))
        account_age = discord.utils.utcnow() - member.created_at
        if account_age >= timedelta(days=threshold):
            return
        age_hours = max(0, int(account_age.total_seconds() // 3600))
        await send_log(
            member.guild,
            "security",
            "🆕 신생 계정 가입 알림",
            f"멤버: {member.mention} (`{member.id}`)\n계정 나이: **약 {age_hours}시간**\n기준: **{threshold}일 미만**",
            color=0xE67E22,
            fields=[("자동 조치", "알림만 전송 · 안티레이드 설정은 별도 적용", False)],
        )

    async def handle_timeout_change(before: discord.Member, after: discord.Member) -> None:
        before_until = before.timed_out_until
        after_until = after.timed_out_until
        if before_until == after_until:
            return
        now = discord.utils.utcnow()
        before_active = before_until is not None and before_until > now
        after_active = after_until is not None and after_until > now
        if before_active == after_active:
            return
        if after_active:
            description = (
                f"멤버: {after.mention} (`{after.id}`)\n"
                f"해제 예정: {discord.utils.format_dt(after_until, style='F')} ({discord.utils.format_dt(after_until, style='R')})"
            )
            title = "⏳ 타임아웃 상태 적용"
            color = 0xC0392B
        else:
            description = f"멤버: {after.mention} (`{after.id}`)"
            title = "✅ 타임아웃 상태 해제"
            color = 0x2ECC71
        await send_log(after.guild, "security", title, description, color=color)

    async def handle_kick_detection(member: discord.Member) -> None:
        me = member.guild.me
        if me is None or not me.guild_permissions.view_audit_log:
            return
        try:
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                target_id = getattr(entry.target, "id", 0)
                if target_id != member.id:
                    continue
                if discord.utils.utcnow() - entry.created_at > timedelta(seconds=15):
                    continue
                actor = getattr(entry.user, "mention", str(entry.user))
                reason = entry.reason or "사유 없음"
                await send_log(
                    member.guild,
                    "security",
                    "👢 감사 로그 추방 감지",
                    f"대상: **{member}** (`{member.id}`)\n실행자: {actor}\n사유: **{reason}**",
                    color=0xC0392B,
                )
                break
        except (discord.Forbidden, discord.HTTPException):
            return

    async def handle_operation_command(ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.command is None or not isinstance(ctx.author, discord.Member):
            return
        settings = get_settings(ctx.guild)
        if not settings.get("operation_command_log", True):
            return
        command_name = ctx.command.qualified_name.split(" ", 1)[0]
        if not command_name.startswith(SECURITY_COMMAND_PREFIXES):
            return
        content = ctx.message.content[:1200]
        await send_log(
            ctx.guild,
            "operation",
            "⌨️ 운영 명령어 실행",
            f"실행자: {ctx.author.mention} (`{ctx.author.id}`)\n채널: {ctx.channel.mention}\n명령어: `{command_name}`",
            color=0x34495E,
            fields=[("입력", content, False)],
        )

    bot.add_listener(handle_new_account, "on_member_join")
    bot.add_listener(handle_timeout_change, "on_member_update")
    bot.add_listener(handle_kick_detection, "on_member_remove")
    bot.add_listener(handle_operation_command, "on_command_completion")

    bot._abaddon_v422_security_center_registered = True
    print("[V4.2.2 SECURITY CENTER] 분리 로그/자동관리 정책/사용자 기록 조회 등록 완료", flush=True)
