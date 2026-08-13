from __future__ import annotations

import io
import json
from typing import Any, Dict, Optional

import discord
from discord.ext import commands


CHANNEL_MUTE_FIELDS = (
    "view_channel",
    "send_messages",
    "add_reactions",
    "create_public_threads",
    "create_private_threads",
    "send_messages_in_threads",
)


def register_v420_ops_center(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    """ABADDON V4.2 operator dashboard, safe exports, notes, and channel tools."""

    if getattr(bot, "_abaddon_v420_ops_center_registered", False):
        return

    management_root = world_data.setdefault("server_management", {})

    def guild_key(guild_or_id: Any) -> str:
        return str(getattr(guild_or_id, "id", guild_or_id))

    def get_settings(guild_or_id: Any) -> Dict[str, Any]:
        settings = management_root.setdefault(guild_key(guild_or_id), {})
        settings.setdefault("mod_role_ids", [])
        settings.setdefault("cases", [])
        settings.setdefault("stats", {})
        settings.setdefault("automod", {})
        settings.setdefault("auto_reactions", {})
        settings.setdefault("anti_raid", {})
        settings.setdefault("open_tickets", {})
        settings.setdefault("sticky_messages", {})
        settings.setdefault("emergency", {})
        settings.setdefault("ops_notes", [])
        settings.setdefault("next_ops_note_id", 1)
        settings.setdefault("channel_mutes", {})
        return settings

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
        perms = ctx.author.guild_permissions
        if not (perms.administrator or perms.manage_guild or ctx.author.id == ctx.guild.owner_id):
            await ctx.send("❌ 서버 관리 권한이 필요합니다.")
            return False
        return True

    def resolve_channel(guild: discord.Guild, value: Any) -> Optional[discord.abc.GuildChannel]:
        try:
            channel_id = int(value or 0)
        except (TypeError, ValueError):
            return None
        return guild.get_channel(channel_id)

    def on_off(value: Any) -> str:
        return "켜짐" if bool(value) else "꺼짐"

    def overwrite_snapshot(overwrite: discord.PermissionOverwrite) -> Dict[str, Optional[bool]]:
        return {field: getattr(overwrite, field) for field in CHANNEL_MUTE_FIELDS}

    def restore_overwrite(
        overwrite: discord.PermissionOverwrite,
        snapshot: Dict[str, Any],
    ) -> discord.PermissionOverwrite:
        for field in CHANNEL_MUTE_FIELDS:
            value = snapshot.get(field)
            if value not in (True, False, None):
                value = None
            setattr(overwrite, field, value)
        return overwrite

    @bot.command(name="운영도구도움말", aliases=["운영센터도움말"], help="현재 운영 보조 명령어를 확인합니다.")
    async def ops_tools_help(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        embed = discord.Embed(
            title="🧰 ABADDON 운영 도구 센터",
            description="기존 SERVER GUARD 설정을 그대로 사용하며, 안전한 점검·기록·내보내기 기능을 추가합니다.",
            color=0x34495E,
        )
        embed.add_field(
            name="📊 점검",
            value="`!운영대시보드` · `!봇권한` · `!채널정보 [#채널]` · `!역할정보 @역할`",
            inline=False,
        )
        embed.add_field(
            name="🗂️ 기록·백업",
            value=(
                "`!운영설정내보내기` · `!운영메모 내용`\n"
                "`!운영메모목록 [개수]` · `!운영메모삭제 번호`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔇 채널 관리",
            value="`!대화금지 @멤버 [사유]` · `!대화허용 @멤버` · `!투표종료 메시지id`",
            inline=False,
        )
        embed.set_footer(text="이 모듈의 새 명령어는 prefix 전용이라 슬래시 100개 제한을 사용하지 않습니다.")
        await ctx.send(embed=embed)

    @bot.command(name="운영대시보드", aliases=["운영센터"], help="SERVER GUARD 주요 설정과 운영 상태를 한 화면에 표시합니다.")
    async def ops_dashboard(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        guild = ctx.guild
        settings = get_settings(guild)
        automod = settings.get("automod", {})
        reactions = settings.get("auto_reactions", {})
        anti_raid = settings.get("anti_raid", {})
        emergency = settings.get("emergency", {})

        log_channel = resolve_channel(guild, settings.get("log_channel_id"))
        welcome_channel = resolve_channel(guild, settings.get("welcome_channel_id"))
        leave_channel = resolve_channel(guild, settings.get("leave_channel_id"))
        autorole = guild.get_role(int(settings.get("autorole_id", 0) or 0))

        prefix_count = len(bot.commands)
        slash_root = int(getattr(bot, "_abaddon_slash_root_count", len(bot.tree.get_commands())))
        slash_total = int(getattr(bot, "_abaddon_slash_total_count", sum(1 for _ in bot.tree.walk_commands())))

        embed = discord.Embed(
            title="📊 ABADDON 운영 대시보드",
            description=f"**{guild.name}** · 멤버 **{guild.member_count or len(guild.members):,}명**",
            color=0x2C3E50,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="🔗 기본 연결",
            value=(
                f"로그: {getattr(log_channel, 'mention', '미설정')}\n"
                f"환영: {getattr(welcome_channel, 'mention', '미설정')}\n"
                f"퇴장: {getattr(leave_channel, 'mention', '미설정')}\n"
                f"자동 역할: {getattr(autorole, 'mention', '미설정')}"
            ),
            inline=True,
        )
        embed.add_field(
            name="🤖 자동 기능",
            value=(
                f"자동 관리: **{on_off(automod.get('enabled'))}**\n"
                f"초대 차단: **{on_off(automod.get('invites'))}**\n"
                f"자동 이모지: **{on_off(reactions.get('enabled'))}**\n"
                f"첨부 반응: **{on_off(reactions.get('smart_attachments'))}**\n"
                f"안티레이드: **{on_off(anti_raid.get('enabled'))}**\n"
                f"자동관리 모드: **{automod.get('action_mode', '삭제')}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🚨 운영 상태",
            value=(
                f"비상모드: **{on_off(emergency.get('active'))}**\n"
                f"열린 문의: **{len(settings.get('open_tickets', {}))}개**\n"
                f"사건 기록: **{len(settings.get('cases', []))}건**\n"
                f"운영 메모: **{len(settings.get('ops_notes', []))}건**\n"
                f"고정 메시지: **{len(settings.get('sticky_messages', {}))}개**\n"
                f"셀프 역할: **{len(settings.get('self_roles', {}).get('items', {}))}개 항목 · {len(settings.get('self_roles', {}).get('panels', {}))}개 패널**\n"
                f"접수 기록: **{len(settings.get('intake_center', {}).get('records', {}))}건 · 답변 양식 {len(settings.get('intake_center', {}).get('templates', {}))}개**"
            ),
            inline=True,
        )
        embed.add_field(
            name="✨ 자동 이모지 상세",
            value=(
                f"채널 규칙 **{len(reactions.get('channels', {}))}개** · "
                f"키워드 규칙 **{len(reactions.get('keyword_rules', []))}개** · "
                f"사용자 프리셋 **{len(reactions.get('custom_presets', {}))}개**\n"
                f"메시지당 최대 반응 **{int(reactions.get('max_per_message', 5) or 5)}개**"
            ),
            inline=False,
        )
        embed.add_field(
            name="⌨️ 명령어 등록",
            value=f"prefix 루트 **{prefix_count}개** · slash 최상위 **{slash_root}/100개** · slash 전체 **{slash_total}개**",
            inline=False,
        )
        embed.set_footer(text="도움말: !운영도구도움말 · !보안센터도움말 · !접수센터도움말 · 권한: !봇권한")
        await ctx.send(embed=embed)

    @bot.command(name="봇권한", aliases=["권한점검"], help="현재 서버와 채널에서 아바돈이 가진 권한을 점검합니다.")
    async def bot_permissions(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        me = ctx.guild.me
        if me is None:
            await ctx.send("❌ 아바돈 서버 멤버 정보를 불러오지 못했습니다.")
            return
        guild_perms = me.guild_permissions
        channel_perms = ctx.channel.permissions_for(me)
        checks = [
            ("관리자", guild_perms.administrator),
            ("서버 관리", guild_perms.manage_guild),
            ("채널 관리", guild_perms.manage_channels),
            ("역할 관리", guild_perms.manage_roles),
            ("멤버 타임아웃", guild_perms.moderate_members),
            ("추방", guild_perms.kick_members),
            ("차단", guild_perms.ban_members),
            ("감사 로그", guild_perms.view_audit_log),
            ("현재 채널 보기", channel_perms.view_channel),
            ("현재 채널 전송", channel_perms.send_messages),
            ("임베드", channel_perms.embed_links),
            ("파일 첨부", channel_perms.attach_files),
            ("반응 추가", channel_perms.add_reactions),
            ("메시지 관리", channel_perms.manage_messages),
        ]
        missing = [name for name, allowed in checks if not allowed]
        lines = [f"{'✅' if allowed else '❌'} {name}" for name, allowed in checks]
        embed = discord.Embed(
            title="🔎 아바돈 권한 점검",
            description="\n".join(lines),
            color=0x2ECC71 if not missing else 0xE67E22,
        )
        if missing:
            embed.add_field(name="부족하거나 비활성인 권한", value=", ".join(missing)[:1024], inline=False)
        embed.set_footer(text="역할 서열 문제는 !서버점검에서 함께 확인할 수 있습니다.")
        await ctx.send(embed=embed)

    @bot.command(name="운영설정내보내기", aliases=["운영백업"], help="현재 서버의 SERVER GUARD 설정만 JSON으로 내보냅니다.")
    async def export_ops_settings(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        payload = {
            "format": "ABADDON_SERVER_GUARD_SETTINGS",
            "version": "4.2.3",
            "guild_id": ctx.guild.id,
            "guild_name": ctx.guild.name,
            "exported_at": discord.utils.utcnow().isoformat(),
            "settings": settings,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        file = discord.File(io.BytesIO(raw), filename=f"abaddon_guard_{ctx.guild.id}.json")
        await ctx.send(
            "🗂️ 현재 서버의 **운영 설정만** 내보냈습니다. 게임 유저 데이터나 `survival_data.json` 전체는 포함하지 않습니다.",
            file=file,
        )

    @bot.command(name="채널정보", help="채널 설정과 주요 권한 상태를 확인합니다.")
    async def channel_info(
        ctx: commands.Context,
        채널: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await require_operator(ctx):
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("❌ 텍스트 채널을 지정해주세요.")
            return
        everyone = target.permissions_for(ctx.guild.default_role)
        me = ctx.guild.me
        mine = target.permissions_for(me) if me is not None else None
        embed = discord.Embed(
            title=f"#️⃣ 채널 정보 · {target.name}",
            description=target.topic or "주제가 설정되지 않았습니다.",
            color=0x3498DB,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="채널 ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="카테고리", value=getattr(target.category, "name", "없음"), inline=True)
        embed.add_field(name="슬로우모드", value=f"{target.slowmode_delay}초", inline=True)
        embed.add_field(name="NSFW", value="예" if target.nsfw else "아니오", inline=True)
        embed.add_field(name="권한 덮어쓰기", value=f"{len(target.overwrites)}개", inline=True)
        embed.add_field(name="생성일", value=discord.utils.format_dt(target.created_at, style="F"), inline=False)
        embed.add_field(
            name="@everyone",
            value=(
                f"보기 {'✅' if everyone.view_channel else '❌'} · "
                f"전송 {'✅' if everyone.send_messages else '❌'} · "
                f"반응 {'✅' if everyone.add_reactions else '❌'}"
            ),
            inline=False,
        )
        if mine is not None:
            embed.add_field(
                name="아바돈",
                value=(
                    f"보기 {'✅' if mine.view_channel else '❌'} · "
                    f"전송 {'✅' if mine.send_messages else '❌'} · "
                    f"관리 {'✅' if mine.manage_channels else '❌'} · "
                    f"반응 {'✅' if mine.add_reactions else '❌'}"
                ),
                inline=False,
            )
        await ctx.send(embed=embed)

    @bot.command(name="역할정보", help="역할의 서열, 인원, 색상과 핵심 권한을 확인합니다.")
    async def role_info(ctx: commands.Context, 역할: discord.Role) -> None:
        if not await require_operator(ctx):
            return
        perms = 역할.permissions
        important = [
            name
            for name, allowed in (
                ("관리자", perms.administrator),
                ("서버관리", perms.manage_guild),
                ("채널관리", perms.manage_channels),
                ("역할관리", perms.manage_roles),
                ("메시지관리", perms.manage_messages),
                ("타임아웃", perms.moderate_members),
                ("추방", perms.kick_members),
                ("차단", perms.ban_members),
            )
            if allowed
        ]
        embed = discord.Embed(
            title=f"🎭 역할 정보 · {역할.name}",
            color=역할.color if 역할.color.value else discord.Color.dark_grey(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="역할 ID", value=f"`{역할.id}`", inline=True)
        embed.add_field(name="서열", value=f"{역할.position}위", inline=True)
        embed.add_field(name="보유 인원", value=f"{len(역할.members)}명", inline=True)
        embed.add_field(name="표시", value="분리 표시" if 역할.hoist else "일반 표시", inline=True)
        embed.add_field(name="멘션 가능", value="예" if 역할.mentionable else "아니오", inline=True)
        embed.add_field(name="봇 관리 역할", value="예" if 역할.managed else "아니오", inline=True)
        embed.add_field(name="핵심 권한", value=", ".join(important) if important else "특수 관리 권한 없음", inline=False)
        if ctx.guild.me is not None:
            embed.add_field(
                name="아바돈이 관리 가능",
                value="✅ 가능" if (not 역할.managed and 역할 < ctx.guild.me.top_role) else "❌ 불가 · 아바돈 역할을 더 위로 올려주세요.",
                inline=False,
            )
        await ctx.send(embed=embed)

    @bot.command(name="대화금지", aliases=["채널뮤트"], help="현재 채널에서 특정 멤버의 전송과 반응을 제한합니다.")
    async def channel_mute(
        ctx: commands.Context,
        멤버: discord.Member,
        *,
        사유: str = "사유 없음",
    ) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 일반 텍스트 채널에서만 사용할 수 있습니다.")
            return
        if 멤버.id == ctx.guild.owner_id:
            await ctx.send("❌ 서버 소유자에게는 사용할 수 없습니다.")
            return
        if ctx.author.id != ctx.guild.owner_id and 멤버.top_role >= ctx.author.top_role:
            await ctx.send("❌ 대상 역할이 실행자의 최고 역할보다 같거나 높습니다.")
            return

        settings = get_settings(ctx.guild)
        channel_mutes = settings.setdefault("channel_mutes", {}).setdefault(str(ctx.channel.id), {})
        key = str(멤버.id)
        overwrite = ctx.channel.overwrites_for(멤버)
        if key not in channel_mutes:
            channel_mutes[key] = overwrite_snapshot(overwrite)
        overwrite.view_channel = True
        overwrite.send_messages = False
        overwrite.add_reactions = False
        overwrite.create_public_threads = False
        overwrite.create_private_threads = False
        overwrite.send_messages_in_threads = False
        try:
            await ctx.channel.set_permissions(
                멤버,
                overwrite=overwrite,
                reason=f"ABADDON 채널 대화 금지: {ctx.author} / {사유[:200]}",
            )
        except discord.Forbidden:
            await ctx.send("❌ 채널 관리 권한이 부족합니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 처리 실패: `{type(exc).__name__}: {str(exc)[:300]}`")
            return
        save_data()
        await ctx.send(f"🔇 {멤버.mention} 님의 {ctx.channel.mention} 대화를 제한했습니다. 사유: **{사유[:500]}**")

    @bot.command(name="대화허용", aliases=["채널언뮤트"], help="대화금지 전에 저장한 채널 권한으로 복구합니다.")
    async def channel_unmute(ctx: commands.Context, 멤버: discord.Member) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 일반 텍스트 채널에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        channel_mutes = settings.setdefault("channel_mutes", {}).setdefault(str(ctx.channel.id), {})
        snapshot = channel_mutes.get(str(멤버.id))
        if not isinstance(snapshot, dict):
            await ctx.send("ℹ️ 이 채널에 저장된 대화금지 기록이 없습니다.")
            return
        overwrite = restore_overwrite(ctx.channel.overwrites_for(멤버), snapshot)
        try:
            await ctx.channel.set_permissions(
                멤버,
                overwrite=overwrite,
                reason=f"ABADDON 채널 대화 허용: {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.send("❌ 채널 관리 권한이 부족합니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 처리 실패: `{type(exc).__name__}: {str(exc)[:300]}`")
            return
        channel_mutes.pop(str(멤버.id), None)
        if not channel_mutes:
            settings["channel_mutes"].pop(str(ctx.channel.id), None)
        save_data()
        await ctx.send(f"🔊 {멤버.mention} 님의 {ctx.channel.mention} 권한을 대화금지 이전 상태로 복구했습니다.")

    @bot.command(name="운영메모", help="관리자 로그용 운영 메모를 저장합니다.")
    async def add_ops_note(ctx: commands.Context, *, 내용: str) -> None:
        if not await require_operator(ctx):
            return
        content = 내용.strip()
        if not content:
            await ctx.send("❌ 메모 내용을 입력해주세요.")
            return
        settings = get_settings(ctx.guild)
        note_id = int(settings.get("next_ops_note_id", 1) or 1)
        settings["next_ops_note_id"] = note_id + 1
        note = {
            "id": note_id,
            "author_id": ctx.author.id,
            "channel_id": ctx.channel.id,
            "content": content[:1500],
            "created_at": discord.utils.utcnow().isoformat(),
        }
        notes = settings.setdefault("ops_notes", [])
        notes.append(note)
        if len(notes) > 300:
            del notes[:-300]
        save_data()

        log_channel = resolve_channel(ctx.guild, settings.get("log_channel_id"))
        if isinstance(log_channel, discord.TextChannel) and log_channel.id != ctx.channel.id:
            embed = discord.Embed(
                title=f"📝 운영 메모 #{note_id}",
                description=content[:4000],
                color=0xF1C40F,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_footer(text=f"작성자 {ctx.author} · {ctx.author.id}")
            try:
                await log_channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
        await ctx.send(f"📝 운영 메모 `#{note_id}`를 저장했습니다.")

    @bot.command(name="운영메모목록", help="최근 운영 메모를 확인합니다.")
    async def list_ops_notes(ctx: commands.Context, 개수: int = 10) -> None:
        if not await require_operator(ctx):
            return
        count = max(1, min(20, 개수))
        notes = get_settings(ctx.guild).get("ops_notes", [])[-count:]
        if not notes:
            await ctx.send("ℹ️ 저장된 운영 메모가 없습니다.")
            return
        lines = []
        for note in reversed(notes):
            author_id = int(note.get("author_id", 0) or 0)
            author = ctx.guild.get_member(author_id)
            author_text = author.mention if author else f"`{author_id}`"
            content = str(note.get("content", "")).replace("\n", " ")[:180]
            lines.append(f"`#{note.get('id', '?')}` {author_text} · {content}")
        await ctx.send(embed=discord.Embed(
            title="📝 최근 운영 메모",
            description="\n".join(lines)[:4000],
            color=0xF1C40F,
        ))

    @bot.command(name="운영메모삭제", help="번호로 운영 메모를 삭제합니다.")
    async def delete_ops_note(ctx: commands.Context, 번호: int) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        notes = settings.setdefault("ops_notes", [])
        target = next((note for note in notes if int(note.get("id", 0) or 0) == 번호), None)
        if target is None:
            await ctx.send("❌ 해당 운영 메모 번호를 찾지 못했습니다.")
            return
        notes.remove(target)
        save_data()
        await ctx.send(f"✅ 운영 메모 `#{번호}`를 삭제했습니다.")

    @bot.command(name="투표종료", help="현재 채널의 아바돈 투표 메시지를 집계합니다.")
    async def close_poll(ctx: commands.Context, 메시지id: int) -> None:
        if not await require_operator(ctx):
            return
        try:
            message = await ctx.channel.fetch_message(메시지id)
        except discord.NotFound:
            await ctx.send("❌ 해당 메시지를 찾지 못했습니다. 현재 채널의 메시지 ID인지 확인해주세요.")
            return
        except discord.Forbidden:
            await ctx.send("❌ 메시지 기록 보기 권한이 부족합니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 처리 실패: `{type(exc).__name__}: {str(exc)[:300]}`")
            return

        if bot.user is None or message.author.id != bot.user.id:
            await ctx.send("❌ 아바돈이 작성한 투표 메시지만 집계할 수 있습니다.")
            return
        results = []
        for reaction in message.reactions:
            count = max(0, int(reaction.count) - (1 if reaction.me else 0))
            results.append((str(reaction.emoji), count))
        if not results:
            await ctx.send("ℹ️ 집계할 반응이 없습니다.")
            return
        highest = max(count for _, count in results)
        winners = [emoji for emoji, count in results if count == highest]
        lines = [f"{emoji} **{count}표**" for emoji, count in sorted(results, key=lambda item: item[1], reverse=True)]
        winner_text = " · ".join(winners) if highest > 0 else "참여 없음"
        embed = discord.Embed(
            title="📊 투표 종료",
            description="\n".join(lines),
            color=0x3498DB,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="최다 득표", value=f"{winner_text} · **{highest}표**", inline=False)
        embed.add_field(name="원본", value=f"[투표 메시지로 이동]({message.jump_url})", inline=False)
        embed.set_footer(text=f"집계자 {ctx.author} · 봇이 추가한 기본 반응은 표에서 제외")
        await ctx.send(embed=embed)

    bot._abaddon_v420_ops_center_registered = True
    print("[V4.2 OPS CENTER] 운영 대시보드/설정 내보내기/메모/채널 도구 등록 완료", flush=True)
