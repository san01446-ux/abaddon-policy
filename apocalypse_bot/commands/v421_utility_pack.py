from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Dict, Optional

import discord
from discord.ext import commands


CUSTOM_EMOJI_RE = re.compile(r"^<a?:[A-Za-z0-9_]+:(\d+)>$")
MAX_SELF_ROLES = 20
MAX_SELF_ROLE_PANELS = 20


def register_v421_utility_pack(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    """ABADDON V4.2.1 self-role panels, member checks, and public utilities."""

    if getattr(bot, "_abaddon_v421_utility_pack_registered", False):
        return

    management_root = world_data.setdefault("server_management", {})

    def guild_key(guild_or_id: Any) -> str:
        return str(getattr(guild_or_id, "id", guild_or_id))

    def get_settings(guild_or_id: Any) -> Dict[str, Any]:
        settings = management_root.setdefault(guild_key(guild_or_id), {})
        settings.setdefault("mod_role_ids", [])
        self_roles = settings.setdefault("self_roles", {})
        self_roles.setdefault("items", {})
        self_roles.setdefault("panels", {})
        self_roles.setdefault("grants", {})
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
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild or member.id == member.guild.owner_id:
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

    def emoji_key(value: Any) -> str:
        if isinstance(value, discord.PartialEmoji):
            if value.id:
                return f"custom:{value.id}"
            return f"unicode:{value.name or ''}"
        text = str(value).strip()
        match = CUSTOM_EMOJI_RE.fullmatch(text)
        if match:
            return f"custom:{match.group(1)}"
        return f"unicode:{text}"

    def clean_description(value: str) -> str:
        return " ".join(value.strip().split())[:160]

    def can_manage_role(guild: discord.Guild, role: discord.Role) -> tuple[bool, str]:
        me = guild.me
        if role.is_default():
            return False, "@everyone 역할은 셀프 역할로 사용할 수 없습니다."
        if role.managed:
            return False, "봇 연동 역할은 직접 지급할 수 없습니다."
        if me is None or not me.guild_permissions.manage_roles:
            return False, "아바돈에 `역할 관리` 권한이 필요합니다."
        if role >= me.top_role:
            return False, "아바돈 역할을 대상 역할보다 위로 올려주세요."
        return True, ""

    def panel_store(guild_or_id: Any) -> Dict[str, Any]:
        return get_settings(guild_or_id)["self_roles"].setdefault("panels", {})

    def item_store(guild_or_id: Any) -> Dict[str, Any]:
        return get_settings(guild_or_id)["self_roles"].setdefault("items", {})

    def grant_store(guild_or_id: Any) -> Dict[str, Any]:
        return get_settings(guild_or_id)["self_roles"].setdefault("grants", {})

    def role_item_lines(guild: discord.Guild, items: Dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for item in items.values():
            role = guild.get_role(int(item.get("role_id", 0) or 0))
            if role is None:
                role_text = f"삭제된 역할 (`{item.get('role_id', 0)}`)"
            else:
                role_text = role.mention
            emoji = str(item.get("emoji", "❔"))
            description = str(item.get("description", "")).strip()
            suffix = f" — {description}" if description else ""
            lines.append(f"{emoji} {role_text}{suffix}")
        return lines

    async def get_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def find_panel(payload: discord.RawReactionActionEvent) -> tuple[Optional[discord.Guild], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if payload.guild_id is None:
            return None, None, None
        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return None, None, None
        panel = panel_store(guild).get(str(payload.message_id))
        if not isinstance(panel, dict):
            return guild, None, None
        item = panel.get("items", {}).get(emoji_key(payload.emoji))
        if not isinstance(item, dict):
            return guild, panel, None
        return guild, panel, item

    @bot.command(name="운영편의도움말", aliases=["편의도움말"], help="현재 셀프 역할과 편의 명령어를 확인합니다.")
    async def utility_help(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        embed = discord.Embed(
            title="🧩 ABADDON 운영 편의 팩",
            description="셀프 역할 패널과 가입자 점검, 일반 조회 기능을 제공합니다.",
            color=0x5865F2,
        )
        embed.add_field(
            name="🎭 셀프 역할 · 관리자",
            value=(
                "`!셀프역할추가 이모지 @역할 [설명]`\n"
                "`!셀프역할삭제 이모지` · `!셀프역할목록`\n"
                "`!셀프역할패널 [제목]` · `!셀프역할패널목록`\n"
                "`!셀프역할패널삭제 메시지id`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔎 운영 점검",
            value="`!최근가입 [개수]` · `!의심계정 [계정나이일수] [개수]` · `!역할멤버 @역할 [개수]`",
            inline=False,
        )
        embed.add_field(
            name="✨ 일반 편의",
            value="`!아바타 [@멤버]` · `!서버아이콘` · `!가입일 [@멤버]` · `!핑`",
            inline=False,
        )
        embed.set_footer(text="모든 신규 명령어는 prefix 전용이며 슬래시 명령어 수를 늘리지 않습니다.")
        await ctx.send(embed=embed)

    @bot.command(name="셀프역할추가", help="셀프 역할 패널에 사용할 이모지와 역할을 등록합니다.")
    async def self_role_add(
        ctx: commands.Context,
        이모지: str,
        역할: discord.Role,
        *,
        설명: str = "",
    ) -> None:
        if not await require_manager(ctx):
            return
        allowed, why = can_manage_role(ctx.guild, 역할)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        if ctx.author.id != ctx.guild.owner_id and 역할 >= ctx.author.top_role:
            await ctx.send("❌ 실행자의 최고 역할보다 같거나 높은 역할은 등록할 수 없습니다.")
            return
        key = emoji_key(이모지)
        if key == "unicode:":
            await ctx.send("❌ 이모지를 입력해주세요.")
            return
        items = item_store(ctx.guild)
        duplicate = next((item for item_key, item in items.items() if item_key != key and int(item.get("role_id", 0) or 0) == 역할.id), None)
        if duplicate is not None:
            await ctx.send(f"❌ {역할.mention} 역할은 이미 {duplicate.get('emoji', '다른 이모지')}에 연결되어 있습니다.")
            return
        if key not in items and len(items) >= MAX_SELF_ROLES:
            await ctx.send(f"❌ 셀프 역할은 최대 {MAX_SELF_ROLES}개까지 등록할 수 있습니다.")
            return
        items[key] = {
            "emoji": 이모지,
            "role_id": 역할.id,
            "description": clean_description(설명),
            "updated_by": ctx.author.id,
            "updated_at": discord.utils.utcnow().isoformat(),
        }
        save_data()
        await ctx.send(
            f"✅ 셀프 역할을 등록했습니다: {이모지} → {역할.mention}"
            + (f" · {clean_description(설명)}" if 설명.strip() else "")
            + "\n새 설정을 표시하려면 `!셀프역할패널`을 실행하세요."
        )

    @bot.command(name="셀프역할삭제", help="등록된 셀프 역할 항목을 이모지로 삭제합니다.")
    async def self_role_remove(ctx: commands.Context, 이모지: str) -> None:
        if not await require_manager(ctx):
            return
        items = item_store(ctx.guild)
        removed = items.pop(emoji_key(이모지), None)
        if removed is None:
            await ctx.send("❌ 해당 이모지로 등록된 셀프 역할이 없습니다.")
            return
        save_data()
        await ctx.send(
            f"✅ 셀프 역할 항목 {이모지}을(를) 삭제했습니다.\n"
            "이미 만들어진 패널은 당시 설정을 유지하므로 필요하면 패널을 다시 만들어주세요."
        )

    @bot.command(name="셀프역할목록", help="현재 등록된 셀프 역할 항목을 확인합니다.")
    async def self_role_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        items = item_store(ctx.guild)
        if not items:
            await ctx.send("ℹ️ 등록된 셀프 역할이 없습니다. 관리자 명령: `!셀프역할추가 이모지 @역할 설명`")
            return
        lines = role_item_lines(ctx.guild, items)
        await ctx.send(embed=discord.Embed(
            title=f"🎭 셀프 역할 목록 · {len(items)}개",
            description="\n".join(lines)[:4000],
            color=0x5865F2,
        ))

    @bot.command(name="셀프역할패널", help="현재 채널에 반응형 셀프 역할 패널을 만듭니다.")
    async def self_role_panel(ctx: commands.Context, *, 제목: str = "원하는 역할을 선택하세요") -> None:
        if not await require_manager(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 일반 텍스트 채널에서만 패널을 만들 수 있습니다.")
            return
        panels = panel_store(ctx.guild)
        if len(panels) >= MAX_SELF_ROLE_PANELS:
            await ctx.send(f"❌ 서버당 셀프 역할 패널은 최대 {MAX_SELF_ROLE_PANELS}개까지 저장할 수 있습니다.")
            return
        source_items = item_store(ctx.guild)
        if not source_items:
            await ctx.send("❌ 먼저 `!셀프역할추가 이모지 @역할 설명`으로 항목을 등록해주세요.")
            return

        usable: Dict[str, Dict[str, Any]] = {}
        skipped: list[str] = []
        for key, item in source_items.items():
            role = ctx.guild.get_role(int(item.get("role_id", 0) or 0))
            if role is None:
                skipped.append(str(item.get("emoji", "❔")))
                continue
            allowed, _ = can_manage_role(ctx.guild, role)
            if not allowed:
                skipped.append(str(item.get("emoji", "❔")))
                continue
            usable[key] = dict(item)
        if not usable:
            await ctx.send("❌ 현재 아바돈이 지급할 수 있는 셀프 역할이 없습니다. 역할 서열과 `역할 관리` 권한을 확인해주세요.")
            return

        lines = role_item_lines(ctx.guild, usable)
        embed = discord.Embed(
            title=f"🎭 {제목.strip()[:200] or '원하는 역할을 선택하세요'}",
            description=(
                "아래 이모지에 반응하면 역할이 지급되고, 반응을 취소하면 역할이 회수됩니다.\n\n"
                + "\n".join(lines)
            )[:4000],
            color=0x5865F2,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="ABADDON SELF ROLE · 역할 지급이 안 되면 봇 역할 서열을 확인해주세요.")
        message = await ctx.send(embed=embed)

        successful: Dict[str, Dict[str, Any]] = {}
        failed: list[str] = []
        for key, item in usable.items():
            emoji = str(item.get("emoji", ""))
            try:
                await message.add_reaction(emoji)
                successful[key] = item
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                failed.append(emoji)

        if not successful:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            await ctx.send("❌ 등록된 이모지를 사용할 수 없어 패널을 만들지 못했습니다. 커스텀 이모지가 현재 서버에 있는지 확인해주세요.")
            return

        panels[str(message.id)] = {
            "channel_id": ctx.channel.id,
            "title": 제목.strip()[:200],
            "items": successful,
            "created_by": ctx.author.id,
            "created_at": discord.utils.utcnow().isoformat(),
        }
        save_data()
        notes: list[str] = [f"✅ 셀프 역할 패널을 만들었습니다. 메시지 ID: `{message.id}`"]
        all_skipped = skipped + failed
        if all_skipped:
            notes.append("⚠️ 사용할 수 없어 제외된 이모지: " + " ".join(all_skipped[:15]))
        await ctx.send("\n".join(notes), delete_after=20)

    @bot.command(name="셀프역할패널목록", help="저장된 셀프 역할 패널의 채널과 메시지 ID를 확인합니다.")
    async def self_role_panel_list(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        panels = panel_store(ctx.guild)
        if not panels:
            await ctx.send("ℹ️ 저장된 셀프 역할 패널이 없습니다.")
            return
        lines: list[str] = []
        for message_id, panel in list(panels.items())[-20:]:
            channel = ctx.guild.get_channel(int(panel.get("channel_id", 0) or 0))
            channel_text = channel.mention if isinstance(channel, discord.TextChannel) else "삭제된 채널"
            item_count = len(panel.get("items", {}))
            title = str(panel.get("title", "셀프 역할"))[:80]
            lines.append(f"`{message_id}` · {channel_text} · **{item_count}개** · {title}")
        await ctx.send(embed=discord.Embed(
            title="🎭 셀프 역할 패널 목록",
            description="\n".join(lines)[:4000],
            color=0x5865F2,
        ))

    @bot.command(name="셀프역할패널삭제", help="메시지 ID로 셀프 역할 패널 등록과 메시지를 삭제합니다.")
    async def self_role_panel_delete(ctx: commands.Context, 메시지id: int) -> None:
        if not await require_manager(ctx):
            return
        panels = panel_store(ctx.guild)
        panel = panels.pop(str(메시지id), None)
        if not isinstance(panel, dict):
            await ctx.send("❌ 저장된 셀프 역할 패널을 찾지 못했습니다.")
            return
        channel = ctx.guild.get_channel(int(panel.get("channel_id", 0) or 0))
        deleted_message = False
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(메시지id)
                await message.delete(reason=f"ABADDON 셀프 역할 패널 삭제: {ctx.author}")
                deleted_message = True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        grants = grant_store(ctx.guild)
        panel_source = str(메시지id)
        for user_id, role_map in list(grants.items()):
            if not isinstance(role_map, dict):
                grants.pop(user_id, None)
                continue
            for role_id, sources in list(role_map.items()):
                if not isinstance(sources, list):
                    role_map.pop(role_id, None)
                    continue
                role_map[role_id] = [source for source in sources if str(source) != panel_source]
                if not role_map[role_id]:
                    role_map.pop(role_id, None)
            if not role_map:
                grants.pop(user_id, None)
        save_data()
        await ctx.send(
            f"✅ 셀프 역할 패널 `{메시지id}` 등록을 삭제했습니다."
            + (" 메시지도 삭제했습니다." if deleted_message else " 메시지는 찾지 못했거나 삭제 권한이 없었습니다.")
            + " 기존에 지급된 역할은 유지됩니다."
        )

    @bot.command(name="최근가입", help="최근 서버에 들어온 멤버를 가입 순서대로 확인합니다.")
    async def recent_joins(ctx: commands.Context, 개수: int = 10) -> None:
        if not await require_operator(ctx):
            return
        count = max(1, min(30, 개수))
        members = sorted(
            (member for member in ctx.guild.members if member.joined_at is not None),
            key=lambda member: member.joined_at,
            reverse=True,
        )[:count]
        if not members:
            await ctx.send("ℹ️ 가입일 정보를 불러올 수 있는 멤버가 없습니다.")
            return
        now = discord.utils.utcnow()
        lines: list[str] = []
        for member in members:
            account_days = max(0, (now - member.created_at).days)
            joined = discord.utils.format_dt(member.joined_at, style="R")
            marker = "🤖" if member.bot else ("⚠️" if account_days <= 7 else "👤")
            lines.append(f"{marker} {member.mention} · 가입 {joined} · 계정 {account_days}일")
        await ctx.send(embed=discord.Embed(
            title=f"🆕 최근 가입 멤버 · {len(members)}명",
            description="\n".join(lines)[:4000],
            color=0x3498DB,
        ))

    @bot.command(name="의심계정", help="생성된 지 얼마 안 된 계정을 운영 점검용으로 표시합니다.")
    async def suspicious_accounts(ctx: commands.Context, 계정나이일수: int = 7, 개수: int = 20) -> None:
        if not await require_operator(ctx):
            return
        days = max(1, min(365, 계정나이일수))
        count = max(1, min(30, 개수))
        threshold = discord.utils.utcnow() - timedelta(days=days)
        members = [
            member
            for member in ctx.guild.members
            if not member.bot and member.created_at >= threshold
        ]
        members.sort(key=lambda member: member.created_at, reverse=True)
        members = members[:count]
        if not members:
            await ctx.send(f"✅ 생성된 지 **{days}일 이하**인 일반 멤버가 없습니다.")
            return
        lines: list[str] = []
        for member in members:
            joined = discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "가입일 미확인"
            created = discord.utils.format_dt(member.created_at, style="R")
            lines.append(f"⚠️ {member.mention} · 생성 {created} · 서버 가입 {joined} · `{member.id}`")
        embed = discord.Embed(
            title=f"🔎 신생 계정 점검 · {days}일 이하",
            description="\n".join(lines)[:4000],
            color=0xE67E22,
        )
        embed.set_footer(text="계정이 새롭다는 이유만으로 제재하지 말고 활동과 로그를 함께 확인하세요.")
        await ctx.send(embed=embed)

    @bot.command(name="역할멤버", help="특정 역할을 가진 멤버를 확인합니다.")
    async def role_members(ctx: commands.Context, 역할: discord.Role, 개수: int = 30) -> None:
        if not await require_operator(ctx):
            return
        count = max(1, min(50, 개수))
        members = sorted(역할.members, key=lambda member: member.display_name.lower())
        shown = members[:count]
        if not shown:
            await ctx.send(f"ℹ️ {역할.mention} 역할을 가진 멤버가 없습니다.")
            return
        lines = [f"• {member.mention} · `{member.id}`" for member in shown]
        embed = discord.Embed(
            title=f"🎭 {역할.name} · {len(members)}명",
            description="\n".join(lines)[:4000],
            color=역할.color if 역할.color.value else discord.Color.dark_grey(),
        )
        if len(members) > len(shown):
            embed.set_footer(text=f"상위 {len(shown)}명만 표시 · 명령어에서 개수를 최대 50까지 지정할 수 있습니다.")
        await ctx.send(embed=embed)

    @bot.command(name="아바타", help="자신 또는 멘션한 멤버의 프로필 이미지를 표시합니다.")
    async def avatar(ctx: commands.Context, 멤버: Optional[discord.Member] = None) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        target = 멤버 or ctx.author
        embed = discord.Embed(title=f"🖼️ {target.display_name} 아바타", color=target.color)
        embed.set_image(url=target.display_avatar.url)
        embed.add_field(name="원본 이미지", value=f"[열기]({target.display_avatar.url})", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="서버아이콘", help="현재 서버의 아이콘 원본을 표시합니다.")
    async def server_icon(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        if ctx.guild.icon is None:
            await ctx.send("ℹ️ 현재 서버에는 아이콘이 설정되어 있지 않습니다.")
            return
        embed = discord.Embed(title=f"🖼️ {ctx.guild.name} 서버 아이콘", color=0x5865F2)
        embed.set_image(url=ctx.guild.icon.url)
        embed.add_field(name="원본 이미지", value=f"[열기]({ctx.guild.icon.url})", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="가입일", help="자신 또는 멘션한 멤버의 계정 생성일과 서버 가입일을 표시합니다.")
    async def join_date(ctx: commands.Context, 멤버: Optional[discord.Member] = None) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        target = 멤버 or ctx.author
        embed = discord.Embed(
            title=f"📅 {target.display_name} 가입 정보",
            color=target.color,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="Discord 계정 생성",
            value=(
                f"{discord.utils.format_dt(target.created_at, style='F')}\n"
                f"({discord.utils.format_dt(target.created_at, style='R')})"
            ),
            inline=False,
        )
        if target.joined_at is not None:
            joined_text = (
                f"{discord.utils.format_dt(target.joined_at, style='F')}\n"
                f"({discord.utils.format_dt(target.joined_at, style='R')})"
            )
        else:
            joined_text = "가입일 정보를 불러오지 못했습니다."
        embed.add_field(name="현재 서버 가입", value=joined_text, inline=False)
        embed.set_footer(text=f"사용자 ID: {target.id}")
        await ctx.send(embed=embed)

    @bot.command(name="핑", aliases=["지연시간"], help="아바돈의 Discord 연결 지연시간을 표시합니다.")
    async def ping(ctx: commands.Context) -> None:
        latency_ms = max(0, round(bot.latency * 1000))
        if latency_ms < 150:
            mark = "🟢"
        elif latency_ms < 300:
            mark = "🟡"
        else:
            mark = "🔴"
        await ctx.send(f"{mark} **ABADDON 연결 지연시간: {latency_ms}ms**")

    @bot.listen("on_raw_reaction_add")
    async def self_role_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if bot.user is None or payload.user_id == bot.user.id:
            return
        guild, panel, item = await find_panel(payload)
        if guild is None or panel is None or item is None:
            return
        member = payload.member or await get_member(guild, payload.user_id)
        if member is None or member.bot:
            return
        role = guild.get_role(int(item.get("role_id", 0) or 0))
        if role is None:
            return
        allowed, _ = can_manage_role(guild, role)
        if not allowed:
            return

        grants = grant_store(guild)
        user_grants = grants.setdefault(str(member.id), {})
        sources = user_grants.setdefault(str(role.id), [])
        source_id = str(payload.message_id)
        if source_id in sources:
            return

        # 이미 수동으로 보유한 역할은 패널이 소유권을 가져가지 않습니다.
        if role in member.roles and not sources:
            user_grants.pop(str(role.id), None)
            if not user_grants:
                grants.pop(str(member.id), None)
            return
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="ABADDON 셀프 역할 반응 추가")
            except (discord.Forbidden, discord.HTTPException):
                if not sources:
                    user_grants.pop(str(role.id), None)
                if not user_grants:
                    grants.pop(str(member.id), None)
                return
        sources.append(source_id)
        save_data()

    @bot.listen("on_raw_reaction_remove")
    async def self_role_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
        if bot.user is None or payload.user_id == bot.user.id:
            return
        guild, panel, item = await find_panel(payload)
        if guild is None or panel is None or item is None:
            return
        member = await get_member(guild, payload.user_id)
        if member is None or member.bot:
            return
        role = guild.get_role(int(item.get("role_id", 0) or 0))
        if role is None:
            return

        grants = grant_store(guild)
        user_grants = grants.get(str(member.id))
        if not isinstance(user_grants, dict):
            return
        sources = user_grants.get(str(role.id))
        if not isinstance(sources, list):
            return
        source_id = str(payload.message_id)
        if source_id not in sources:
            return
        sources[:] = [source for source in sources if str(source) != source_id]
        if sources:
            save_data()
            return

        allowed, _ = can_manage_role(guild, role)
        if allowed and role in member.roles:
            try:
                await member.remove_roles(role, reason="ABADDON 셀프 역할 반응 취소")
            except (discord.Forbidden, discord.HTTPException):
                sources.append(source_id)
                save_data()
                return
        user_grants.pop(str(role.id), None)
        if not user_grants:
            grants.pop(str(member.id), None)
        save_data()

    bot._abaddon_v421_utility_pack_registered = True
    print("[V4.2.1 UTILITY PACK] 셀프 역할/가입자 점검/일반 편의 명령 등록 완료", flush=True)
