from __future__ import annotations

import asyncio
import io
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

import discord
from discord.ext import commands


MAX_INTAKE_RECORDS = 2000
MAX_TEMPLATES = 30
MAX_NOTES_PER_RECORD = 50

TYPE_INFO: Dict[str, Tuple[str, str, int]] = {
    "문의": ("🎫", "일반 문의", 0x5865F2),
    "신고": ("🚨", "사용자·콘텐츠 신고", 0xED4245),
    "건의": ("💡", "서버 개선 건의", 0xFEE75C),
    "버그": ("🐞", "봇 오류·버그 제보", 0xEB459E),
    "이의": ("⚖️", "제재 이의신청", 0x57F287),
}

STATUS_ALIASES = {
    "접수": "접수",
    "신규": "접수",
    "확인": "확인중",
    "확인중": "확인중",
    "처리": "처리중",
    "처리중": "처리중",
    "대기": "사용자대기",
    "사용자대기": "사용자대기",
    "보류": "보류",
    "해결": "해결",
    "완료": "해결",
    "종료": "종료",
}

PRIORITY_ALIASES = {
    "낮음": "낮음",
    "보통": "보통",
    "중간": "보통",
    "높음": "높음",
    "긴급": "긴급",
}

PRIORITY_WEIGHT = {"긴급": 4, "높음": 3, "보통": 2, "낮음": 1}


def register_v423_intake_center(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    """ABADDON V4.2.3 categorized intake, assignment, workflow, and quick replies."""

    if getattr(bot, "_abaddon_v423_intake_center_registered", False):
        return

    management_root = world_data.setdefault("server_management", {})

    def guild_key(guild_or_id: Any) -> str:
        return str(getattr(guild_or_id, "id", guild_or_id))

    def get_settings(guild_or_id: Any) -> Dict[str, Any]:
        settings = management_root.setdefault(guild_key(guild_or_id), {})
        settings.setdefault("mod_role_ids", [])
        settings.setdefault("ticket_category_id", 0)
        settings.setdefault("ticket_log_channel_id", 0)
        settings.setdefault("open_tickets", {})
        settings.setdefault("log_channels", {})
        center = settings.setdefault("intake_center", {})
        center.setdefault("next_id", 1)
        center.setdefault("records", {})
        center.setdefault("templates", {})
        center.setdefault("panel_message_ids", [])
        center.setdefault("stats", {})
        for key in ("created", "closed", "claimed", "reopened"):
            center["stats"].setdefault(key, 0)
        return settings

    def center_store(guild_or_id: Any) -> Dict[str, Any]:
        return get_settings(guild_or_id)["intake_center"]

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

    def now_iso() -> str:
        return discord.utils.utcnow().isoformat()

    def parse_iso(value: Any) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    def clean_text(value: str, limit: int) -> str:
        return " ".join(str(value).replace("\x00", "").strip().split())[:limit]

    def resolve_channel(guild: discord.Guild, value: Any) -> Optional[discord.abc.GuildChannel]:
        try:
            return guild.get_channel(int(value))
        except (TypeError, ValueError):
            return None

    def record_for_channel(guild_or_id: Any, channel_id: int) -> Optional[Dict[str, Any]]:
        record = center_store(guild_or_id).setdefault("records", {}).get(str(channel_id))
        return record if isinstance(record, dict) else None

    def next_case_id(guild_or_id: Any) -> int:
        center = center_store(guild_or_id)
        current = max(1, int(center.get("next_id", 1) or 1))
        center["next_id"] = current + 1
        return current

    def trim_records(guild_or_id: Any) -> None:
        center = center_store(guild_or_id)
        records = center.setdefault("records", {})
        if len(records) <= MAX_INTAKE_RECORDS:
            return
        closed = sorted(
            (
                (key, item)
                for key, item in records.items()
                if isinstance(item, dict) and item.get("status") in {"해결", "종료"}
            ),
            key=lambda pair: str(pair[1].get("closed_at") or pair[1].get("created_at") or ""),
        )
        remove_count = len(records) - MAX_INTAKE_RECORDS
        for key, _ in closed[:remove_count]:
            records.pop(key, None)

    def format_timestamp(value: Any) -> str:
        parsed = parse_iso(value)
        if parsed is None:
            return "알 수 없음"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=discord.utils.utcnow().tzinfo)
        return discord.utils.format_dt(parsed, style="R")

    def type_info(type_name: str) -> Tuple[str, str, int]:
        return TYPE_INFO.get(type_name, ("🎫", type_name or "문의", 0x5865F2))

    def status_symbol(status: str) -> str:
        return {
            "접수": "🆕",
            "확인중": "👀",
            "처리중": "🛠️",
            "사용자대기": "⏳",
            "보류": "⏸️",
            "해결": "✅",
            "종료": "🔒",
        }.get(status, "•")

    def priority_symbol(priority: str) -> str:
        return {"긴급": "🔴", "높음": "🟠", "보통": "🟡", "낮음": "🟢"}.get(priority, "⚪")

    async def find_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
        settings = get_settings(guild)
        for value in (
            settings.get("ticket_log_channel_id", 0),
            settings.get("log_channels", {}).get("operation", 0),
            settings.get("log_channels", {}).get("security", 0),
            settings.get("log_channel_id", 0),
        ):
            channel = resolve_channel(guild, value)
            if isinstance(channel, discord.TextChannel):
                return channel
        for name in ("🚨・신고접수", "🔧・운영-로그", "🚨・보안-알림", "📋・관리자-로그"):
            channel = discord.utils.get(guild.text_channels, name=name)
            if channel is not None:
                return channel
        return None

    async def send_intake_log(
        guild: discord.Guild,
        title: str,
        description: str,
        *,
        color: int = 0x5865F2,
        file: Optional[discord.File] = None,
    ) -> None:
        channel = await find_log_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(
            title=title,
            description=description[:4000],
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"서버 ID: {guild.id}")
        try:
            await channel.send(embed=embed, file=file)
        except (discord.Forbidden, discord.HTTPException):
            return

    async def ensure_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        settings = get_settings(guild)
        category = resolve_channel(guild, settings.get("ticket_category_id", 0))
        if isinstance(category, discord.CategoryChannel):
            return category
        category = discord.utils.get(guild.categories, name="🎫・문의센터")
        if category is not None:
            settings["ticket_category_id"] = category.id
            return category
        try:
            category = await guild.create_category(
                "🎫・문의센터",
                reason="ABADDON V4.2.3 접수센터 자동 생성",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None
        settings["ticket_category_id"] = category.id
        save_data()
        return category

    def operator_roles(guild: discord.Guild) -> list[discord.Role]:
        configured = operator_role_ids(get_settings(guild))
        roles: list[discord.Role] = []
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            if role.id in configured or role.permissions.administrator or role.permissions.manage_guild:
                roles.append(role)
        return roles

    def channel_overwrites(guild: discord.Guild, member: discord.Member) -> Dict[Any, discord.PermissionOverwrite]:
        overwrites: Dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )
        for role in operator_roles(guild):
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )
        return overwrites

    async def transcript(channel: discord.TextChannel, case_id: int) -> Optional[discord.File]:
        lines = [
            "ABADDON 접수 처리 기록",
            f"접수번호: #{case_id}",
            f"서버: {channel.guild.name} ({channel.guild.id})",
            f"채널: {channel.name} ({channel.id})",
            "=" * 76,
        ]
        try:
            async for message in channel.history(limit=500, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = message.clean_content.replace("\n", " ")
                if message.attachments:
                    links = " ".join(item.url for item in message.attachments)
                    content = f"{content} [첨부: {links}]".strip()
                lines.append(f"[{timestamp}] {message.author} ({message.author.id}): {content}")
        except (discord.Forbidden, discord.HTTPException):
            return None
        payload = "\n".join(lines).encode("utf-8")
        return discord.File(io.BytesIO(payload), filename=f"intake-{case_id}-{channel.id}.txt")

    def sync_open_ticket(settings: Dict[str, Any], owner_id: int, channel_id: Optional[int]) -> None:
        open_tickets = settings.setdefault("open_tickets", {})
        if channel_id is None:
            if str(open_tickets.get(str(owner_id), "")):
                open_tickets.pop(str(owner_id), None)
            return
        open_tickets[str(owner_id)] = channel_id

    async def create_intake(
        interaction: discord.Interaction,
        type_name: str,
        subject: str,
        details: str,
        reference: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("서버 안에서만 접수할 수 있습니다.", ephemeral=True)
            return
        guild = interaction.guild
        member = interaction.user
        settings = get_settings(guild)
        existing_id = settings.setdefault("open_tickets", {}).get(str(member.id))
        if existing_id:
            existing = resolve_channel(guild, existing_id)
            if isinstance(existing, discord.TextChannel):
                await interaction.followup.send(
                    f"이미 처리 중인 접수가 있습니다: {existing.mention}\n기존 접수를 종료한 뒤 새로 접수해주세요.",
                    ephemeral=True,
                )
                return
            settings["open_tickets"].pop(str(member.id), None)

        category = await ensure_category(guild)
        if category is None:
            await interaction.followup.send(
                "접수 카테고리를 만들 수 없습니다. 아바돈에게 `채널 관리` 권한이 있는지 확인해주세요.",
                ephemeral=True,
            )
            return

        case_id = next_case_id(guild)
        emoji, label, color = type_info(type_name)
        safe_name = re.sub(r"[^0-9A-Za-z가-힣-]", "", member.display_name)[:16] or "member"
        type_slug = {"문의": "ask", "신고": "report", "건의": "idea", "버그": "bug", "이의": "appeal"}.get(type_name, "ticket")
        channel_name = f"{type_slug}-{case_id:04d}-{safe_name}"[:100]
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=channel_overwrites(guild, member),
                topic=f"ABADDON 접수 #{case_id} | 유형: {type_name} | 작성자 ID: {member.id}",
                reason=f"ABADDON 접수 #{case_id} 생성: {member}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.followup.send(f"접수 채널을 만들지 못했습니다: {exc}", ephemeral=True)
            return

        created_at = now_iso()
        record = {
            "case_id": case_id,
            "channel_id": channel.id,
            "owner_id": member.id,
            "type": type_name,
            "subject": clean_text(subject, 100),
            "details": str(details).strip()[:2000],
            "reference": str(reference).strip()[:1000],
            "status": "접수",
            "priority": "보통",
            "assignee_id": 0,
            "created_at": created_at,
            "updated_at": created_at,
            "closed_at": "",
            "closed_by": 0,
            "close_reason": "",
            "notes": [],
        }
        center = center_store(guild)
        center.setdefault("records", {})[str(channel.id)] = record
        center.setdefault("stats", {})["created"] = int(center["stats"].get("created", 0)) + 1
        sync_open_ticket(settings, member.id, channel.id)
        settings.setdefault("stats", {})["tickets"] = int(settings.setdefault("stats", {}).get("tickets", 0)) + 1
        trim_records(guild)
        save_data()

        embed = discord.Embed(
            title=f"{emoji} 접수 #{case_id} · {label}",
            description=(
                f"**제목**\n{record['subject']}\n\n"
                f"**상세 내용**\n{record['details']}"
            )[:4000],
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        if record["reference"]:
            embed.add_field(name="🔗 참고 정보", value=record["reference"][:1024], inline=False)
        embed.add_field(name="상태", value="🆕 접수", inline=True)
        embed.add_field(name="우선순위", value="🟡 보통", inline=True)
        embed.add_field(name="담당자", value="미배정", inline=True)
        embed.set_footer(text="작성자와 운영진만 이 채널을 볼 수 있습니다.")
        await channel.send(member.mention, embed=embed, view=IntakeControlView())
        await interaction.followup.send(
            f"{emoji} **{label} #{case_id}** 접수가 완료됐습니다: {channel.mention}",
            ephemeral=True,
        )
        await send_intake_log(
            guild,
            f"{emoji} 새 접수 #{case_id} · {label}",
            (
                f"작성자: {member.mention} (`{member.id}`)\n"
                f"채널: {channel.mention}\n"
                f"제목: **{record['subject']}**"
            ),
            color=color,
        )

    async def close_intake(
        channel: discord.TextChannel,
        closer: discord.Member,
        reason: str,
    ) -> Tuple[bool, str]:
        record = record_for_channel(channel.guild, channel.id)
        if record is None:
            return False, "이 채널은 v4.2.3 접수 기록으로 등록되어 있지 않습니다."
        owner_id = int(record.get("owner_id", 0) or 0)
        if closer.id != owner_id and not is_operator(closer):
            return False, "접수 작성자 또는 운영진만 종료할 수 있습니다."
        if record.get("status") in {"해결", "종료"}:
            return False, "이미 종료된 접수입니다."

        reason_text = clean_text(reason, 300) or "처리 완료"
        record["status"] = "해결" if is_operator(closer) else "종료"
        record["closed_at"] = now_iso()
        record["closed_by"] = closer.id
        record["close_reason"] = reason_text
        record["updated_at"] = record["closed_at"]
        settings = get_settings(channel.guild)
        sync_open_ticket(settings, owner_id, None)
        center_store(channel.guild)["stats"]["closed"] = int(center_store(channel.guild)["stats"].get("closed", 0)) + 1
        save_data()

        file = await transcript(channel, int(record.get("case_id", 0) or 0))
        assignee_id = int(record.get("assignee_id", 0) or 0)
        await send_intake_log(
            channel.guild,
            f"🔒 접수 #{record.get('case_id', '?')} 종료",
            (
                f"유형: **{record.get('type', '문의')}**\n"
                f"작성자: <@{owner_id}> (`{owner_id}`)\n"
                f"담당자: {f'<@{assignee_id}>' if assignee_id else '미배정'}\n"
                f"종료자: {closer.mention} (`{closer.id}`)\n"
                f"사유: {reason_text}"
            ),
            color=0x95A5A6,
            file=file,
        )
        try:
            await channel.send(f"🔒 접수 처리가 종료됐습니다. 사유: **{reason_text}**\n5초 후 채널이 삭제됩니다.")
            await asyncio.sleep(5)
            await channel.delete(reason=f"ABADDON 접수 종료: {closer} / {reason_text}")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return False, "기록은 저장했지만 채널을 삭제하지 못했습니다."
        return True, "접수가 종료됐습니다."

    def make_record_embed(guild: discord.Guild, record: Dict[str, Any]) -> discord.Embed:
        case_id = int(record.get("case_id", 0) or 0)
        type_name = str(record.get("type", "문의"))
        emoji, label, color = type_info(type_name)
        status = str(record.get("status", "접수"))
        priority = str(record.get("priority", "보통"))
        owner_id = int(record.get("owner_id", 0) or 0)
        assignee_id = int(record.get("assignee_id", 0) or 0)
        embed = discord.Embed(
            title=f"{emoji} 접수 #{case_id} · {label}",
            description=f"**{record.get('subject', '제목 없음')}**",
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="상태", value=f"{status_symbol(status)} {status}", inline=True)
        embed.add_field(name="우선순위", value=f"{priority_symbol(priority)} {priority}", inline=True)
        embed.add_field(name="담당자", value=f"<@{assignee_id}>" if assignee_id else "미배정", inline=True)
        embed.add_field(name="작성자", value=f"<@{owner_id}> (`{owner_id}`)", inline=False)
        embed.add_field(name="생성", value=format_timestamp(record.get("created_at")), inline=True)
        embed.add_field(name="최근 변경", value=format_timestamp(record.get("updated_at")), inline=True)
        notes = record.get("notes", [])
        embed.add_field(name="운영 메모", value=f"{len(notes) if isinstance(notes, list) else 0}개", inline=True)
        if record.get("close_reason"):
            embed.add_field(name="종료 사유", value=str(record.get("close_reason"))[:1024], inline=False)
        return embed

    async def show_record(target: discord.abc.Messageable, guild: discord.Guild, record: Dict[str, Any]) -> None:
        await target.send(embed=make_record_embed(guild, record))

    class IntakeModal(discord.ui.Modal):
        def __init__(self, type_name: str) -> None:
            emoji, label, _ = type_info(type_name)
            super().__init__(title=f"{emoji} {label} 접수", timeout=300)
            self.type_name = type_name
            self.subject = discord.ui.TextInput(
                label="제목",
                placeholder="핵심 내용을 한 줄로 적어주세요.",
                min_length=2,
                max_length=100,
            )
            self.details = discord.ui.TextInput(
                label="상세 내용",
                placeholder="언제, 어디서, 무엇이 있었는지 자세히 적어주세요.",
                style=discord.TextStyle.paragraph,
                min_length=10,
                max_length=2000,
            )
            self.reference = discord.ui.TextInput(
                label="참고 정보 (선택)",
                placeholder="메시지 링크, 사용자 ID, 오류 문구 등을 적어주세요.",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=1000,
            )
            self.add_item(self.subject)
            self.add_item(self.details)
            self.add_item(self.reference)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await create_intake(
                interaction,
                self.type_name,
                str(self.subject.value),
                str(self.details.value),
                str(self.reference.value or ""),
            )

        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            message = "접수 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except discord.HTTPException:
                pass
            print(f"[V4.2.3 IntakeModal 오류] {type(error).__name__}: {error}", flush=True)

    class IntakePanelView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(label="문의", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="abaddon:v423:intake:ask")
        async def ask(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await interaction.response.send_modal(IntakeModal("문의"))

        @discord.ui.button(label="신고", emoji="🚨", style=discord.ButtonStyle.danger, custom_id="abaddon:v423:intake:report")
        async def report(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await interaction.response.send_modal(IntakeModal("신고"))

        @discord.ui.button(label="건의", emoji="💡", style=discord.ButtonStyle.success, custom_id="abaddon:v423:intake:idea")
        async def idea(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await interaction.response.send_modal(IntakeModal("건의"))

        @discord.ui.button(label="버그", emoji="🐞", style=discord.ButtonStyle.secondary, custom_id="abaddon:v423:intake:bug")
        async def bug(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await interaction.response.send_modal(IntakeModal("버그"))

        @discord.ui.button(label="이의신청", emoji="⚖️", style=discord.ButtonStyle.secondary, custom_id="abaddon:v423:intake:appeal")
        async def appeal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await interaction.response.send_modal(IntakeModal("이의"))

    class IntakeControlView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(label="담당하기", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="abaddon:v423:intake:claim")
        async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("접수 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            if not is_operator(interaction.user):
                await interaction.response.send_message("운영진만 담당자로 등록할 수 있습니다.", ephemeral=True)
                return
            record = record_for_channel(interaction.guild, interaction.channel.id)
            if record is None:
                await interaction.response.send_message("접수 기록을 찾을 수 없습니다.", ephemeral=True)
                return
            record["assignee_id"] = interaction.user.id
            if record.get("status") == "접수":
                record["status"] = "확인중"
            record["updated_at"] = now_iso()
            center = center_store(interaction.guild)
            center["stats"]["claimed"] = int(center["stats"].get("claimed", 0)) + 1
            save_data()
            await interaction.response.send_message(f"🙋 {interaction.user.mention}님이 담당자로 등록됐습니다.")

        @discord.ui.button(label="접수 정보", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="abaddon:v423:intake:info")
        async def info(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("접수 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            record = record_for_channel(interaction.guild, interaction.channel.id)
            if record is None:
                await interaction.response.send_message("접수 기록을 찾을 수 없습니다.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(embed=make_record_embed(interaction.guild, record), ephemeral=True)

        @discord.ui.button(label="종료", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="abaddon:v423:intake:close")
        async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("접수 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            record = record_for_channel(interaction.guild, interaction.channel.id)
            if record is None:
                await interaction.response.send_message("접수 기록을 찾을 수 없습니다.", ephemeral=True)
                return
            owner_id = int(record.get("owner_id", 0) or 0)
            if interaction.user.id != owner_id and not is_operator(interaction.user):
                await interaction.response.send_message("작성자 또는 운영진만 종료할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.send_message("접수 종료를 처리합니다.", ephemeral=True)
            await close_intake(interaction.channel, interaction.user, "버튼으로 종료")

    bot.add_view(IntakePanelView())
    bot.add_view(IntakeControlView())

    @bot.command(name="접수센터도움말", aliases=["접수도움말"], help="현재 문의·신고·건의 처리센터 명령어를 확인합니다.")
    async def intake_help(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        embed = discord.Embed(
            title="🎫 ABADDON 접수 처리 센터",
            description="문의·신고·건의·버그·이의신청을 비공개 채널로 접수하고 처리합니다.",
            color=0x5865F2,
        )
        embed.add_field(name="설치", value="`!접수초기설정` · `!접수패널` · `!접수센터상태`", inline=False)
        embed.add_field(
            name="처리",
            value=(
                "`!접수현황 [상태]` · `!접수정보` · `!접수담당 [@운영자]`\n"
                "`!접수담당해제` · `!접수상태 상태` · `!접수우선순위 등급`\n"
                "`!접수메모 내용` · `!접수종료 [사유]`"
            ),
            inline=False,
        )
        embed.add_field(
            name="빠른 답변",
            value="`!답변양식추가 이름 | 내용` · `!답변양식삭제 이름` · `!답변양식목록` · `!빠른답변 이름`",
            inline=False,
        )
        embed.add_field(name="사용자", value="패널 버튼으로 접수 · `!내접수`로 현재 상태를 DM 확인", inline=False)
        embed.set_footer(text="신규 기능은 prefix 전용이며 슬래시 명령어 수를 늘리지 않습니다.")
        await ctx.send(embed=embed)

    async def send_intake_panel(channel: discord.abc.Messageable, guild: discord.Guild) -> discord.Message:
        embed = discord.Embed(
            title="📨 ABADDON 문의·신고 접수 센터",
            description=(
                "아래에서 접수 유형을 선택하면 작성 양식이 열립니다.\n"
                "접수 내용은 **작성자와 서버 운영진만** 확인할 수 있습니다.\n\n"
                "🎫 일반 문의 · 🚨 사용자/콘텐츠 신고 · 💡 개선 건의\n"
                "🐞 봇 오류 제보 · ⚖️ 제재 이의신청"
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="한 사람당 동시에 하나의 접수만 열 수 있습니다.")
        message = await channel.send(embed=embed, view=IntakePanelView())
        panel_ids = center_store(guild).setdefault("panel_message_ids", [])
        if message.id not in panel_ids:
            panel_ids.append(message.id)
            del panel_ids[:-20]
            save_data()
        return message

    @bot.command(name="접수초기설정", help="접수 카테고리와 처리 로그를 연결하고 현재 채널에 패널을 설치합니다.")
    async def intake_setup(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        progress = await ctx.send("⏳ 접수센터 구조를 확인하고 있습니다...")
        category = await ensure_category(ctx.guild)
        if category is None:
            await progress.edit(content="❌ 문의 카테고리를 만들 수 없습니다. 아바돈의 `채널 관리` 권한을 확인해주세요.")
            return
        settings = get_settings(ctx.guild)
        log_channel = await find_log_channel(ctx.guild)
        if log_channel is None:
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            }
            if ctx.guild.me is not None:
                overwrites[ctx.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            for role in operator_roles(ctx.guild):
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            try:
                log_channel = await ctx.guild.create_text_channel(
                    "🚨・신고접수",
                    overwrites=overwrites,
                    reason="ABADDON V4.2.3 접수 로그 자동 생성",
                )
                settings["ticket_log_channel_id"] = log_channel.id
            except (discord.Forbidden, discord.HTTPException):
                log_channel = None
        elif isinstance(log_channel, discord.TextChannel):
            settings["ticket_log_channel_id"] = log_channel.id
        save_data()
        await progress.edit(
            content=(
                "✅ **접수센터 초기 연결 완료**\n"
                f"카테고리: **{category.name}**\n"
                f"처리 로그: **{getattr(log_channel, 'name', '미연결')}**\n"
                "아래 패널에서 유형별 접수를 테스트할 수 있습니다."
            )
        )
        await send_intake_panel(ctx.channel, ctx.guild)

    @bot.command(name="접수패널", help="현재 채널에 유형별 문의·신고·건의 접수 패널을 설치합니다.")
    async def intake_panel(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        await send_intake_panel(ctx.channel, ctx.guild)

    @bot.command(name="접수센터상태", help="접수센터 채널 연결과 처리 통계를 확인합니다.")
    async def intake_center_status(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        settings = get_settings(ctx.guild)
        center = center_store(ctx.guild)
        records = [item for item in center.get("records", {}).values() if isinstance(item, dict)]
        open_records = [item for item in records if item.get("status") not in {"해결", "종료"}]
        category = resolve_channel(ctx.guild, settings.get("ticket_category_id", 0))
        log_channel = await find_log_channel(ctx.guild)
        stats = center.get("stats", {})
        embed = discord.Embed(title="🎫 접수센터 상태", color=0x5865F2)
        embed.add_field(name="문의 카테고리", value=getattr(category, "mention", "미연결"), inline=True)
        embed.add_field(name="처리 로그", value=getattr(log_channel, "mention", "미연결"), inline=True)
        embed.add_field(name="열린 접수", value=f"{len(open_records)}개", inline=True)
        embed.add_field(name="누적 접수", value=f"{int(stats.get('created', 0))}건", inline=True)
        embed.add_field(name="누적 종료", value=f"{int(stats.get('closed', 0))}건", inline=True)
        embed.add_field(name="답변 양식", value=f"{len(center.get('templates', {}))}개", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="접수현황", help="열린 접수 대기열을 상태별로 확인합니다.")
    async def intake_queue(ctx: commands.Context, 상태: str = "전체") -> None:
        if not await require_operator(ctx):
            return
        wanted = None if 상태 in {"전체", "all"} else STATUS_ALIASES.get(상태)
        if wanted is None and 상태 not in {"전체", "all"}:
            await ctx.send("❌ 상태는 `전체/접수/확인중/처리중/사용자대기/보류` 중에서 선택해주세요.")
            return
        rows = []
        for record in center_store(ctx.guild).get("records", {}).values():
            if not isinstance(record, dict):
                continue
            status = str(record.get("status", "접수"))
            if status in {"해결", "종료"}:
                continue
            if wanted is not None and status != wanted:
                continue
            rows.append(record)
        rows.sort(
            key=lambda item: (
                -PRIORITY_WEIGHT.get(str(item.get("priority", "보통")), 2),
                str(item.get("created_at", "")),
            )
        )
        if not rows:
            await ctx.send("ℹ️ 조건에 맞는 열린 접수가 없습니다.")
            return
        lines = []
        for record in rows[:30]:
            cid = int(record.get("channel_id", 0) or 0)
            channel = ctx.guild.get_channel(cid)
            channel_text = channel.mention if isinstance(channel, discord.TextChannel) else "삭제된 채널"
            assignee = int(record.get("assignee_id", 0) or 0)
            lines.append(
                f"{priority_symbol(str(record.get('priority', '보통')))} "
                f"`#{int(record.get('case_id', 0) or 0)}` "
                f"{status_symbol(str(record.get('status', '접수')))} **{record.get('type', '문의')}** "
                f"{channel_text} · 담당 {f'<@{assignee}>' if assignee else '미배정'}\n"
                f"└ {str(record.get('subject', '제목 없음'))[:80]}"
            )
        embed = discord.Embed(
            title=f"📋 접수 대기열 · {len(rows)}건",
            description="\n".join(lines)[:4000],
            color=0x5865F2,
        )
        if len(rows) > 30:
            embed.set_footer(text=f"상위 30건만 표시 · 나머지 {len(rows) - 30}건")
        await ctx.send(embed=embed)

    @bot.command(name="접수정보", help="현재 접수 채널의 처리 정보를 확인합니다.")
    async def intake_info(ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel) or ctx.guild is None:
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        if record is None:
            await ctx.send("❌ 이 채널의 v4.2.3 접수 기록이 없습니다.")
            return
        owner_id = int(record.get("owner_id", 0) or 0)
        if ctx.author.id != owner_id and (not isinstance(ctx.author, discord.Member) or not is_operator(ctx.author)):
            await ctx.send("❌ 작성자 또는 운영진만 확인할 수 있습니다.")
            return
        await show_record(ctx.channel, ctx.guild, record)

    @bot.command(name="접수담당", help="현재 접수의 담당 운영자를 지정합니다.")
    async def intake_assign(ctx: commands.Context, 담당자: Optional[discord.Member] = None) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        if record is None:
            await ctx.send("❌ 접수 기록이 없습니다.")
            return
        target = 담당자 or ctx.author
        if not is_operator(target):
            await ctx.send("❌ 담당자는 서버 운영진이어야 합니다.")
            return
        record["assignee_id"] = target.id
        if record.get("status") == "접수":
            record["status"] = "확인중"
        record["updated_at"] = now_iso()
        center = center_store(ctx.guild)
        center["stats"]["claimed"] = int(center["stats"].get("claimed", 0)) + 1
        save_data()
        await ctx.send(f"🙋 접수 #{record.get('case_id')} 담당자를 {target.mention}(으)로 지정했습니다.")

    @bot.command(name="접수담당해제", help="현재 접수의 담당자 배정을 해제합니다.")
    async def intake_unassign(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        if record is None:
            await ctx.send("❌ 접수 기록이 없습니다.")
            return
        record["assignee_id"] = 0
        record["updated_at"] = now_iso()
        save_data()
        await ctx.send("✅ 담당자 배정을 해제했습니다.")

    @bot.command(name="접수상태", help="현재 접수의 처리 상태를 변경합니다.")
    async def intake_status(ctx: commands.Context, 상태: str) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        normalized = STATUS_ALIASES.get(상태)
        if normalized is None or normalized in {"해결", "종료"}:
            await ctx.send("❌ 상태는 `접수/확인중/처리중/사용자대기/보류` 중에서 선택해주세요. 종료는 `!접수종료`를 사용하세요.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        if record is None:
            await ctx.send("❌ 접수 기록이 없습니다.")
            return
        before = str(record.get("status", "접수"))
        record["status"] = normalized
        record["updated_at"] = now_iso()
        save_data()
        await ctx.send(f"✅ 처리 상태를 **{before} → {normalized}**으로 변경했습니다.")

    @bot.command(name="접수우선순위", aliases=["접수우선도"], help="현재 접수의 우선순위를 변경합니다.")
    async def intake_priority(ctx: commands.Context, 등급: str) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        normalized = PRIORITY_ALIASES.get(등급)
        if normalized is None:
            await ctx.send("❌ 우선순위는 `낮음/보통/높음/긴급` 중에서 선택해주세요.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        if record is None:
            await ctx.send("❌ 접수 기록이 없습니다.")
            return
        before = str(record.get("priority", "보통"))
        record["priority"] = normalized
        record["updated_at"] = now_iso()
        save_data()
        await ctx.send(f"✅ 우선순위를 **{before} → {priority_symbol(normalized)} {normalized}**으로 변경했습니다.")

    @bot.command(name="접수메모", help="현재 접수에 운영진 전용 처리 메모를 저장합니다.")
    async def intake_note(ctx: commands.Context, *, 내용: str) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        if record is None:
            await ctx.send("❌ 접수 기록이 없습니다.")
            return
        note = clean_text(내용, 500)
        if not note:
            await ctx.send("❌ 메모 내용을 입력해주세요.")
            return
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            await ctx.send(
                "❌ 명령 메시지를 삭제할 수 없어 메모 저장을 중단했습니다. 아바돈의 `메시지 관리` 권한을 확인해주세요.",
                delete_after=15,
            )
            return
        notes = record.setdefault("notes", [])
        if not isinstance(notes, list):
            notes = []
            record["notes"] = notes
        notes.append({"author_id": ctx.author.id, "content": note, "created_at": now_iso()})
        del notes[:-MAX_NOTES_PER_RECORD]
        record["updated_at"] = now_iso()
        save_data()
        await ctx.send("📝 운영진 메모를 저장했습니다. 메모 내용은 처리 로그에만 남습니다.", delete_after=8)
        await send_intake_log(
            ctx.guild,
            f"📝 접수 #{record.get('case_id')} 운영 메모",
            f"작성자: {ctx.author.mention}\n채널: {ctx.channel.mention}\n메모: {note}",
            color=0xF1C40F,
        )

    @bot.command(name="답변양식추가", help="접수 채널에서 사용할 빠른 답변 양식을 등록합니다. 이름 | 내용")
    async def template_add(ctx: commands.Context, *, 입력: str) -> None:
        if not await require_manager(ctx):
            return
        if "|" not in 입력:
            await ctx.send("❌ 사용법: `!답변양식추가 이름 | 답변 내용`")
            return
        raw_name, raw_content = 입력.split("|", 1)
        name = clean_text(raw_name, 30)
        content = str(raw_content).strip()[:1800]
        if not name or not content:
            await ctx.send("❌ 이름과 답변 내용을 모두 입력해주세요.")
            return
        templates = center_store(ctx.guild).setdefault("templates", {})
        if name not in templates and len(templates) >= MAX_TEMPLATES:
            await ctx.send(f"❌ 답변 양식은 최대 {MAX_TEMPLATES}개까지 등록할 수 있습니다.")
            return
        templates[name] = {"content": content, "updated_by": ctx.author.id, "updated_at": now_iso()}
        save_data()
        await ctx.send(f"✅ 빠른 답변 양식 **{name}**을 저장했습니다.")

    @bot.command(name="답변양식삭제", help="등록된 빠른 답변 양식을 삭제합니다.")
    async def template_remove(ctx: commands.Context, *, 이름: str) -> None:
        if not await require_manager(ctx):
            return
        name = clean_text(이름, 30)
        templates = center_store(ctx.guild).setdefault("templates", {})
        if templates.pop(name, None) is None:
            await ctx.send("❌ 해당 이름의 답변 양식이 없습니다.")
            return
        save_data()
        await ctx.send(f"✅ 답변 양식 **{name}**을 삭제했습니다.")

    @bot.command(name="답변양식목록", help="등록된 빠른 답변 양식 목록을 확인합니다.")
    async def template_list(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        templates = center_store(ctx.guild).setdefault("templates", {})
        if not templates:
            await ctx.send("ℹ️ 등록된 답변 양식이 없습니다. `!답변양식추가 이름 | 내용`")
            return
        lines = [f"• **{name}** — {str(item.get('content', ''))[:80]}" for name, item in sorted(templates.items())]
        await ctx.send(embed=discord.Embed(title=f"💬 빠른 답변 양식 · {len(lines)}개", description="\n".join(lines)[:4000], color=0x5865F2))

    @bot.command(name="빠른답변", help="현재 접수 채널에 등록된 답변 양식을 전송합니다.")
    async def quick_reply(ctx: commands.Context, *, 이름: str) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel) or record_for_channel(ctx.guild, ctx.channel.id) is None:
            await ctx.send("❌ v4.2.3 접수 채널에서만 사용할 수 있습니다.")
            return
        name = clean_text(이름, 30)
        item = center_store(ctx.guild).setdefault("templates", {}).get(name)
        if not isinstance(item, dict):
            await ctx.send("❌ 해당 이름의 답변 양식이 없습니다. `!답변양식목록`을 확인해주세요.")
            return
        record = record_for_channel(ctx.guild, ctx.channel.id)
        owner_id = int(record.get("owner_id", 0) or 0)
        content = str(item.get("content", ""))[:1800]
        record["updated_at"] = now_iso()
        if record.get("status") in {"접수", "확인중"}:
            record["status"] = "처리중"
        save_data()
        await ctx.send(
            f"<@{owner_id}>\n{content}\n\n— 담당 운영진 {ctx.author.mention}",
            allowed_mentions=discord.AllowedMentions(
                users=[discord.Object(id=owner_id)],
                roles=False,
                everyone=False,
            ),
        )

    @bot.command(name="내접수", help="현재 열린 접수 상태를 DM으로 확인합니다.")
    async def my_intake(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        channel_id = settings.setdefault("open_tickets", {}).get(str(ctx.author.id))
        if not channel_id:
            await ctx.send("ℹ️ 현재 열린 접수가 없습니다.", delete_after=12)
            return
        record = record_for_channel(ctx.guild, int(channel_id))
        if record is None:
            channel = resolve_channel(ctx.guild, channel_id)
            await ctx.send(f"ℹ️ 기존 문의 채널이 열려 있습니다: {getattr(channel, 'mention', '채널 확인 불가')}", delete_after=20)
            return
        try:
            await show_record(ctx.author, ctx.guild, record)
            await ctx.send("📬 현재 접수 상태를 DM으로 보냈습니다.", delete_after=10)
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ DM을 보낼 수 없습니다. 개인 메시지 수신 설정을 확인해주세요.", delete_after=15)

    @bot.command(name="접수종료", help="현재 접수를 기록과 함께 종료합니다.")
    async def intake_close(ctx: commands.Context, *, 사유: str = "처리 완료") -> None:
        if not isinstance(ctx.channel, discord.TextChannel) or ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 접수 채널에서만 사용할 수 있습니다.")
            return
        ok, message = await close_intake(ctx.channel, ctx.author, 사유)
        if not ok:
            await ctx.send(f"❌ {message}")

    @bot.listen("on_guild_channel_delete")
    async def reconcile_deleted_intake(channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, discord.TextChannel):
            return
        record = record_for_channel(channel.guild, channel.id)
        if record is None or record.get("status") in {"해결", "종료"}:
            return
        record["status"] = "종료"
        record["closed_at"] = now_iso()
        record["updated_at"] = record["closed_at"]
        record["close_reason"] = "채널 삭제 감지"
        owner_id = int(record.get("owner_id", 0) or 0)
        sync_open_ticket(get_settings(channel.guild), owner_id, None)
        center = center_store(channel.guild)
        center["stats"]["closed"] = int(center["stats"].get("closed", 0)) + 1
        save_data()

    bot._abaddon_v423_intake_center_registered = True
