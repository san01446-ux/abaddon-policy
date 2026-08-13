from __future__ import annotations

import asyncio
import io
import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any, Deque, Dict, Iterable, Optional, Tuple

import discord
from discord.ext import commands


INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/[A-Za-z0-9-]+",
    re.IGNORECASE,
)
DURATION_RE = re.compile(r"^\s*(\d+)\s*(초|분|시간|일|s|m|h|d)?\s*$", re.IGNORECASE)
MAX_TIMEOUT_SECONDS = 28 * 24 * 60 * 60
MAX_CASES_PER_GUILD = 5000

MESSAGE_WINDOWS: Dict[Tuple[int, int], Deque[Tuple[float, str]]] = defaultdict(
    lambda: deque(maxlen=20)
)
AUTOMOD_STRIKES: Dict[Tuple[int, int], Deque[float]] = defaultdict(
    lambda: deque(maxlen=20)
)
AUTOMOD_DELETED_MESSAGE_IDS: set[int] = set()


def register_v410_server_management(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    """ABADDON V4.1 server management, moderation, logging, and tickets."""

    if getattr(bot, "_abaddon_v410_management_registered", False):
        return

    root = world_data.setdefault("server_management", {})

    def guild_key(guild_or_id: Any) -> str:
        value = getattr(guild_or_id, "id", guild_or_id)
        return str(value)

    def get_settings(guild_or_id: Any) -> Dict[str, Any]:
        key = guild_key(guild_or_id)
        settings = root.setdefault(key, {})
        settings.setdefault("log_channel_id", 0)
        log_channels = settings.setdefault("log_channels", {})
        log_channels.setdefault("security", 0)
        log_channels.setdefault("message", 0)
        log_channels.setdefault("member", 0)
        log_channels.setdefault("operation", 0)
        settings.setdefault("welcome_channel_id", 0)
        settings.setdefault("welcome_notice_channel_id", 0)
        settings.setdefault("welcome_rules_channel_id", 0)
        settings.setdefault("welcome_register_channel_id", 0)
        settings.setdefault("leave_channel_id", 0)
        settings.setdefault("autorole_id", 0)
        settings.setdefault("mod_role_ids", [])
        settings.setdefault("ticket_category_id", 0)
        settings.setdefault("ticket_log_channel_id", 0)
        settings.setdefault("open_tickets", {})
        settings.setdefault("warnings", {})
        settings.setdefault("cases", [])
        settings.setdefault("next_case_id", 1)
        settings.setdefault("channel_locks", {})
        settings.setdefault("stats", {})
        settings["stats"].setdefault("warnings", 0)
        settings["stats"].setdefault("timeouts", 0)
        settings["stats"].setdefault("kicks", 0)
        settings["stats"].setdefault("bans", 0)
        settings["stats"].setdefault("automod_hits", 0)
        settings["stats"].setdefault("tickets", 0)
        automod = settings.setdefault("automod", {})
        automod.setdefault("enabled", False)
        automod.setdefault("spam", True)
        automod.setdefault("mention_spam", True)
        automod.setdefault("invites", False)
        automod.setdefault("bad_words", False)
        automod.setdefault("bad_word_list", [])
        automod.setdefault("auto_timeout", False)
        automod.setdefault("exempt_channel_ids", [])
        automod.setdefault("spam_count", 6)
        automod.setdefault("spam_seconds", 8)
        automod.setdefault("mention_limit", 5)
        automod.setdefault("strike_limit", 3)
        automod.setdefault("strike_window", 600)
        automod.setdefault("timeout_minutes", 10)
        automod.setdefault("action_mode", "삭제")
        automod.setdefault("invite_exempt_channel_ids", [])
        return settings

    def now_iso() -> str:
        return discord.utils.utcnow().isoformat()

    def trim_cases(settings: Dict[str, Any]) -> None:
        cases = settings.setdefault("cases", [])
        if len(cases) > MAX_CASES_PER_GUILD:
            del cases[:-MAX_CASES_PER_GUILD]

    def operator_role_ids(settings: Dict[str, Any]) -> set[int]:
        result = set()
        for value in settings.get("mod_role_ids", []):
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
        return result

    def is_operator(member: discord.Member) -> bool:
        settings = get_settings(member.guild)
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild or member.id == member.guild.owner_id:
            return True
        configured = operator_role_ids(settings)
        return any(role.id in configured for role in member.roles)

    async def require_operator(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return False
        if not is_operator(ctx.author):
            await ctx.send("❌ 이 명령어는 **서버 운영진**만 사용할 수 있습니다.")
            return False
        return True

    async def require_manager(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return False
        perms = ctx.author.guild_permissions
        if not (perms.administrator or perms.manage_guild or ctx.author.id == ctx.guild.owner_id):
            await ctx.send("❌ 이 설정은 **서버 관리 권한**이 있어야 변경할 수 있습니다.")
            return False
        return True

    def parse_toggle(value: str) -> Optional[bool]:
        text = value.strip().lower()
        if text in {"켜기", "켜", "on", "true", "1", "활성화"}:
            return True
        if text in {"끄기", "꺼", "off", "false", "0", "비활성화"}:
            return False
        return None

    def parse_duration(value: str) -> Optional[int]:
        match = DURATION_RE.match(value)
        if not match:
            return None
        amount = int(match.group(1))
        unit = (match.group(2) or "분").lower()
        multiplier = {
            "초": 1,
            "s": 1,
            "분": 60,
            "m": 60,
            "시간": 3600,
            "h": 3600,
            "일": 86400,
            "d": 86400,
        }[unit]
        seconds = amount * multiplier
        if seconds <= 0 or seconds > MAX_TIMEOUT_SECONDS:
            return None
        return seconds

    def human_duration(seconds: int) -> str:
        if seconds % 86400 == 0:
            return f"{seconds // 86400}일"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}시간"
        if seconds % 60 == 0:
            return f"{seconds // 60}분"
        return f"{seconds}초"

    def can_act_on(
        actor: discord.Member,
        target: discord.Member,
        bot_member: Optional[discord.Member],
    ) -> Tuple[bool, str]:
        if target.id == actor.id:
            return False, "자기 자신에게는 사용할 수 없습니다."
        if target.id == actor.guild.owner_id:
            return False, "서버 소유자에게는 사용할 수 없습니다."
        if target.bot and bot.user and target.id == bot.user.id:
            return False, "아바돈 자신에게는 사용할 수 없습니다."
        if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
            return False, "대상 역할이 실행자의 최고 역할보다 같거나 높습니다."
        if bot_member is not None and target.top_role >= bot_member.top_role:
            return False, "아바돈 역할을 대상 역할보다 위로 올려주세요."
        return True, ""

    def resolve_channel(guild: discord.Guild, channel_id: Any) -> Optional[discord.abc.GuildChannel]:
        try:
            cid = int(channel_id)
        except (TypeError, ValueError):
            return None
        return guild.get_channel(cid)

    def find_text_channel(
        guild: discord.Guild,
        configured_id: Any,
        keywords: Iterable[str],
    ) -> Optional[discord.TextChannel]:
        configured = resolve_channel(guild, configured_id)
        if isinstance(configured, discord.TextChannel):
            return configured

        def normalise(value: str) -> str:
            return re.sub(r"[^0-9a-z가-힣]", "", value.lower())

        wanted = [normalise(keyword) for keyword in keywords]
        best: Optional[discord.TextChannel] = None
        best_score = 0
        for channel in guild.text_channels:
            name = normalise(channel.name)
            score = 0
            for keyword in wanted:
                if not keyword:
                    continue
                if name == keyword:
                    score = max(score, 100)
                elif keyword in name:
                    score = max(score, 70 + min(20, len(keyword)))
            if score > best_score:
                best = channel
                best_score = score
        return best if best_score >= 70 else None

    def welcome_link_channels(
        guild: discord.Guild,
        settings: Dict[str, Any],
    ) -> Tuple[Optional[discord.TextChannel], Optional[discord.TextChannel], Optional[discord.TextChannel]]:
        notice = find_text_channel(
            guild,
            settings.get("welcome_notice_channel_id", 0),
            ("공지사항", "서버공지", "공지", "announcement", "notice"),
        )
        rules = find_text_channel(
            guild,
            settings.get("welcome_rules_channel_id", 0),
            ("서버기본규칙", "기본규칙", "이용규칙", "규칙", "rules"),
        )
        register = find_text_channel(
            guild,
            settings.get("welcome_register_channel_id", 0),
            ("생존자등록", "가입", "등록", "rpg", "봇명령어"),
        )
        return notice, rules, register

    def classify_log_type(title: str) -> str:
        text = title or ""
        if any(token in text for token in ("메시지 삭제", "메시지 수정")):
            return "message"
        if any(token in text for token in ("멤버 입장", "멤버 퇴장", "닉네임", "역할 변경", "차단 이벤트", "차단 해제 이벤트")):
            return "member"
        if any(token in text for token in ("자동 관리", "경고", "타임아웃", "추방", "차단", "격리", "레이드", "비상", "보안")):
            return "security"
        return "operation"

    async def find_log_channel(
        guild: discord.Guild,
        log_type: Optional[str] = None,
    ) -> Optional[discord.TextChannel]:
        settings = get_settings(guild)
        channel_map = settings.get("log_channels", {})
        if log_type in {"security", "message", "member", "operation"}:
            channel = resolve_channel(guild, channel_map.get(log_type, 0))
            if isinstance(channel, discord.TextChannel):
                return channel
        channel = resolve_channel(guild, settings.get("log_channel_id", 0))
        if isinstance(channel, discord.TextChannel):
            return channel
        fallback_names = {
            "security": ("🚨・보안-알림", "📋・관리자-로그", "🚨・신고접수"),
            "message": ("📨・메시지-로그", "📋・관리자-로그", "🤖・봇-로그"),
            "member": ("👥・멤버-로그", "📋・관리자-로그", "🤖・봇-로그"),
            "operation": ("🔧・운영-로그", "📋・관리자-로그", "🤖・봇-로그"),
        }
        for name in fallback_names.get(log_type or "operation", fallback_names["operation"]):
            fallback = discord.utils.get(guild.text_channels, name=name)
            if fallback:
                return fallback
        return None

    async def send_log(
        guild: discord.Guild,
        title: str,
        description: str,
        *,
        color: int = 0x8E44AD,
        fields: Optional[Iterable[Tuple[str, str, bool]]] = None,
        file: Optional[discord.File] = None,
        log_type: Optional[str] = None,
    ) -> None:
        channel = await find_log_channel(guild, log_type or classify_log_type(title))
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
                embed.add_field(name=name[:256], value=value[:1024] or "-", inline=inline)
        embed.set_footer(text=f"서버 ID: {guild.id}")
        try:
            if file is not None:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    def add_case(
        guild: discord.Guild,
        action: str,
        target_id: int,
        moderator_id: int,
        reason: str,
        *,
        duration_seconds: int = 0,
        source: str = "manual",
    ) -> Dict[str, Any]:
        settings = get_settings(guild)
        case_id = int(settings.get("next_case_id", 1))
        settings["next_case_id"] = case_id + 1
        case = {
            "id": case_id,
            "action": action,
            "target_id": int(target_id),
            "moderator_id": int(moderator_id),
            "reason": reason[:1000],
            "duration_seconds": int(duration_seconds),
            "source": source,
            "created_at": now_iso(),
            "active": True,
        }
        settings.setdefault("cases", []).append(case)
        trim_cases(settings)
        return case

    def active_warnings(settings: Dict[str, Any], user_id: int) -> list[Dict[str, Any]]:
        records = settings.setdefault("warnings", {}).setdefault(str(user_id), [])
        return [item for item in records if isinstance(item, dict) and item.get("active", True)]

    async def issue_warning(
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.abc.User,
        reason: str,
        *,
        source: str = "manual",
    ) -> Dict[str, Any]:
        settings = get_settings(guild)
        case = add_case(
            guild,
            "warning",
            target.id,
            moderator.id,
            reason,
            source=source,
        )
        warning = {
            "case_id": case["id"],
            "moderator_id": moderator.id,
            "reason": reason[:1000],
            "created_at": case["created_at"],
            "active": True,
            "source": source,
        }
        settings.setdefault("warnings", {}).setdefault(str(target.id), []).append(warning)
        settings["stats"]["warnings"] = int(settings["stats"].get("warnings", 0)) + 1
        save_data()
        try:
            await target.send(
                f"⚠️ **{guild.name}**에서 경고를 받았습니다.\n"
                f"사유: **{reason}**\n사건 번호: **#{case['id']}**"
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
        return case

    async def maybe_auto_punish(
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.abc.User,
    ) -> Optional[str]:
        settings = get_settings(guild)
        if not settings["automod"].get("auto_timeout", True):
            return None
        count = len(active_warnings(settings, target.id))
        duration = 0
        if count >= 7:
            duration = 24 * 3600
        elif count >= 5:
            duration = 3600
        elif count >= 3:
            duration = 10 * 60
        if duration <= 0:
            return None
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.moderate_members:
            return "자동 처벌 기준에 도달했지만 아바돈에게 `멤버 타임아웃` 권한이 없습니다."
        try:
            await target.timeout(
                discord.utils.utcnow() + timedelta(seconds=duration),
                reason=f"ABADDON 경고 {count}회 자동 처벌",
            )
        except (discord.Forbidden, discord.HTTPException):
            return "자동 처벌 기준에 도달했지만 대상에게 타임아웃을 적용하지 못했습니다."
        add_case(
            guild,
            "timeout",
            target.id,
            moderator.id,
            f"경고 {count}회 누적 자동 처벌",
            duration_seconds=duration,
            source="warning-threshold",
        )
        settings["stats"]["timeouts"] = int(settings["stats"].get("timeouts", 0)) + 1
        save_data()
        return f"누적 경고 **{count}회**로 **{human_duration(duration)} 타임아웃**이 자동 적용됐습니다."

    async def perform_timeout(
        guild: discord.Guild,
        actor: discord.Member,
        target: discord.Member,
        seconds: int,
        reason: str,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        allowed, why = can_act_on(actor, target, guild.me)
        if not allowed:
            return False, why, None
        if not actor.guild_permissions.moderate_members and actor.id != guild.owner_id:
            return False, "실행자에게 `멤버 타임아웃` 권한이 없습니다.", None
        if guild.me is None or not guild.me.guild_permissions.moderate_members:
            return False, "아바돈에게 `멤버 타임아웃` 권한을 부여해주세요.", None
        try:
            await target.timeout(
                discord.utils.utcnow() + timedelta(seconds=seconds),
                reason=f"{actor} | {reason}",
            )
        except discord.Forbidden:
            return False, "권한 또는 역할 순서 때문에 타임아웃하지 못했습니다.", None
        except discord.HTTPException as exc:
            return False, f"Discord 요청 오류: {exc}", None
        case = add_case(
            guild,
            "timeout",
            target.id,
            actor.id,
            reason,
            duration_seconds=seconds,
        )
        settings = get_settings(guild)
        settings["stats"]["timeouts"] = int(settings["stats"].get("timeouts", 0)) + 1
        save_data()
        return True, "", case

    async def transcript_ticket(channel: discord.TextChannel) -> Optional[discord.File]:
        lines = [
            f"ABADDON 문의 기록",
            f"서버: {channel.guild.name} ({channel.guild.id})",
            f"채널: {channel.name} ({channel.id})",
            "=" * 72,
        ]
        try:
            async for message in channel.history(limit=300, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = message.clean_content.replace("\n", " ")
                if message.attachments:
                    links = " ".join(item.url for item in message.attachments)
                    content = f"{content} [첨부: {links}]".strip()
                lines.append(f"[{timestamp}] {message.author} ({message.author.id}): {content}")
        except (discord.Forbidden, discord.HTTPException):
            return None
        data = "\n".join(lines).encode("utf-8")
        return discord.File(io.BytesIO(data), filename=f"ticket-{channel.id}.txt")

    async def close_ticket_channel(
        channel: discord.TextChannel,
        closer: discord.Member,
    ) -> Tuple[bool, str]:
        settings = get_settings(channel.guild)
        owner_id = None
        for uid, cid in list(settings.setdefault("open_tickets", {}).items()):
            try:
                matches = int(cid) == channel.id
            except (TypeError, ValueError):
                matches = False
            if matches:
                owner_id = int(uid)
                break
        if owner_id is None:
            return False, "이 채널은 아바돈 문의 채널로 등록되어 있지 않습니다."
        if closer.id != owner_id and not is_operator(closer):
            return False, "문의 작성자 또는 운영진만 닫을 수 있습니다."

        transcript = await transcript_ticket(channel)
        description = (
            f"문의 채널: **{channel.name}**\n"
            f"작성자: <@{owner_id}> (`{owner_id}`)\n"
            f"종료자: {closer.mention} (`{closer.id}`)"
        )
        await send_log(
            channel.guild,
            "🎫 문의 종료",
            description,
            color=0x95A5A6,
            file=transcript,
        )
        settings["open_tickets"].pop(str(owner_id), None)
        save_data()
        try:
            await channel.send("🔒 문의를 종료합니다. **5초 후 채널이 삭제됩니다.**")
            await asyncio.sleep(5)
            await channel.delete(reason=f"문의 종료: {closer}")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return False, "문의 기록은 저장했지만 채널을 삭제하지 못했습니다."
        return True, "문의가 종료됐습니다."

    class TicketCreateView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(
            label="문의 만들기",
            emoji="🎫",
            style=discord.ButtonStyle.primary,
            custom_id="abaddon:v410:ticket:create",
        )
        async def create_ticket(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button,
        ) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
                return
            guild = interaction.guild
            member = interaction.user
            settings = get_settings(guild)
            existing_id = settings.setdefault("open_tickets", {}).get(str(member.id))
            if existing_id:
                existing = resolve_channel(guild, existing_id)
                if isinstance(existing, discord.TextChannel):
                    await interaction.response.send_message(
                        f"이미 열린 문의가 있습니다: {existing.mention}",
                        ephemeral=True,
                    )
                    return
                settings["open_tickets"].pop(str(member.id), None)

            category = resolve_channel(guild, settings.get("ticket_category_id", 0))
            if not isinstance(category, discord.CategoryChannel):
                category = discord.utils.get(guild.categories, name="🎫・문의센터")
            if category is None:
                try:
                    category = await guild.create_category(
                        "🎫・문의센터",
                        reason="ABADDON 문의 시스템 자동 생성",
                    )
                    settings["ticket_category_id"] = category.id
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        "문의 카테고리를 만들 수 없습니다. 아바돈에게 `채널 관리` 권한을 주세요.",
                        ephemeral=True,
                    )
                    return

            overwrites: Dict[Any, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                ),
            }
            if guild.me is not None:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                    read_message_history=True,
                )
            for role_id in operator_role_ids(settings):
                role = guild.get_role(role_id)
                if role is not None:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_messages=True,
                    )

            safe_name = re.sub(r"[^0-9A-Za-z가-힣-]", "", member.display_name)[:20] or "member"
            channel_name = f"문의-{safe_name}-{str(member.id)[-4:]}"
            try:
                ticket = await guild.create_text_channel(
                    channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=f"ABADDON 문의 | 작성자 ID: {member.id}",
                    reason=f"문의 생성: {member}",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                await interaction.response.send_message(
                    f"문의 채널을 만들지 못했습니다: {exc}",
                    ephemeral=True,
                )
                return

            settings["open_tickets"][str(member.id)] = ticket.id
            settings["stats"]["tickets"] = int(settings["stats"].get("tickets", 0)) + 1
            save_data()
            embed = discord.Embed(
                title="🎫 ABADDON 문의 접수",
                description=(
                    f"{member.mention} 문의 내용을 자세히 남겨주세요.\n"
                    "운영진이 확인하면 이 채널에서 답변합니다.\n\n"
                    "문제가 해결되면 아래 **문의 닫기** 버튼을 눌러주세요."
                ),
                color=0x8E44AD,
            )
            await ticket.send(member.mention, embed=embed, view=TicketCloseView())
            await interaction.response.send_message(
                f"문의 채널을 만들었습니다: {ticket.mention}",
                ephemeral=True,
            )
            await send_log(
                guild,
                "🎫 문의 생성",
                f"작성자: {member.mention} (`{member.id}`)\n채널: {ticket.mention}",
                color=0x3498DB,
            )

    class TicketCloseView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(
            label="문의 닫기",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id="abaddon:v410:ticket:close",
        )
        async def close_ticket(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button,
        ) -> None:
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("문의 채널에서만 사용할 수 있습니다.", ephemeral=True)
                return
            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("서버 멤버 정보를 확인할 수 없습니다.", ephemeral=True)
                return
            settings = get_settings(interaction.guild)
            owner_id = None
            for uid, cid in settings.setdefault("open_tickets", {}).items():
                if str(cid) == str(interaction.channel.id):
                    owner_id = int(uid)
                    break
            if owner_id is None:
                await interaction.response.send_message("등록된 문의 채널이 아닙니다.", ephemeral=True)
                return
            if interaction.user.id != owner_id and not is_operator(interaction.user):
                await interaction.response.send_message("문의 작성자 또는 운영진만 닫을 수 있습니다.", ephemeral=True)
                return
            await interaction.response.send_message("문의 종료를 처리합니다.", ephemeral=True)
            await close_ticket_channel(interaction.channel, interaction.user)

    bot.add_view(TicketCreateView())
    bot.add_view(TicketCloseView())

    @bot.command(name="운영도움말", help="서버 운영 및 관리 명령어를 확인합니다.")
    async def management_help(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        embed = discord.Embed(
            title="🛡 ABADDON SERVER GUARD · 운영 도움말",
            description="서버 운영, 제재, 기록, 자동 관리와 문의 시스템입니다.",
            color=0x8E44AD,
        )
        embed.add_field(
            name="⚖️ 제재",
            value=(
                "`!경고 @유저 사유` · `!경고조회 @유저` · `!경고취소 @유저 사건번호`\n"
                "`!타임아웃 @유저 10분 사유` · `!타임아웃해제 @유저 사유`\n"
                "`!추방 @유저 사유` · `!차단 @유저 사유` · `!차단해제 유저id 사유`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧹 채널·멤버 관리",
            value=(
                "`!청소 20` · `!슬로우 10` · `!채널잠금` · `!채널해제`\n"
                "`!닉네임 @유저 새이름` · `!역할지급 @유저 @역할` · `!역할회수 @유저 @역할`"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ 설정",
            value=(
                "`!운영초기설정` · `!운영설정` · `!로그채널 #채널`\n"
                "`!환영채널 #채널` · `!퇴장채널 #채널` · `!자동역할 @역할`\n"
                "`!관리역할추가 @역할` · `!관리역할제거 @역할`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🤖 자동 관리",
            value=(
                "`!자동관리 ON/OFF` · `!초대차단 ON/OFF`\n"
                "`!욕설차단 ON/OFF` · `!욕설추가 단어` · `!욕설삭제 단어`\n"
                "`!예외채널 #채널` · `!예외채널해제 #채널` · `!자동처벌 ON/OFF`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎫 문의",
            value="`!문의패널` · `!문의닫기` · `!문의추가 @유저` · `!문의제거 @유저`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @bot.command(
        name="운영초기설정",
        aliases=["가드초기설정", "운영설정초기화"],
        help="현재 서버 구조를 감지해 운영 기능을 자동 연결합니다.",
    )
    async def management_quick_setup(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return

        # 처리 전에 즉시 응답해, 권한 확인/카테고리 생성/데이터 저장 중에도
        # 명령어가 무반응처럼 보이지 않도록 합니다.
        progress: Optional[discord.Message] = None
        try:
            progress = await ctx.send(
                "⏳ **SERVER GUARD 초기 연결을 시작합니다.**\n"
                "서버 채널과 역할을 확인하는 중입니다..."
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            progress = None

        guild = ctx.guild
        settings = get_settings(guild)

        async def finish(message: str) -> None:
            if progress is not None:
                try:
                    await progress.edit(content=message)
                    return
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            try:
                await ctx.send(message)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                try:
                    await ctx.author.send(message)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        try:
            def text_by_names(*names: str) -> Optional[discord.TextChannel]:
                for name in names:
                    found = discord.utils.get(guild.text_channels, name=name)
                    if found:
                        return found
                return None

            log_channel = text_by_names("📋・관리자-로그", "🤖・봇-로그", "🚨・신고접수")
            welcome_channel = text_by_names("📜・서버-안내", "💬・생존자-광장")
            leave_channel = text_by_names("💬・생존자-광장", "📋・관리자-로그")
            ticket_log = text_by_names("🚨・신고접수", "📋・관리자-로그")
            autorole = discord.utils.get(guild.roles, name="🆕 신규 생존자")
            mod_roles = [
                role.id
                for role in guild.roles
                if role.name in {"🛡 기지 관리자", "⚙️ 시스템 관리자", "🩸 집행관"}
            ]

            category = discord.utils.get(guild.categories, name="🎫・문의센터")
            category_note = "기존 카테고리 사용"
            if category is None:
                try:
                    category = await asyncio.wait_for(
                        guild.create_category(
                            "🎫・문의센터",
                            reason=f"ABADDON 운영 초기 설정: {ctx.author}",
                        ),
                        timeout=20,
                    )
                    category_note = "새로 생성"
                except asyncio.TimeoutError:
                    category_note = "생성 시간 초과"
                    category = None
                except discord.Forbidden:
                    category_note = "카테고리 관리 권한 부족"
                    category = None
                except discord.HTTPException as exc:
                    category_note = f"생성 실패 ({getattr(exc, 'status', 'HTTP')})"
                    category = None

            if log_channel:
                settings["log_channel_id"] = log_channel.id
            if welcome_channel:
                settings["welcome_channel_id"] = welcome_channel.id
            if leave_channel:
                settings["leave_channel_id"] = leave_channel.id
            if ticket_log:
                settings["ticket_log_channel_id"] = ticket_log.id
            if autorole:
                settings["autorole_id"] = autorole.id
            if mod_roles:
                previous_roles = []
                for value in settings.get("mod_role_ids", []):
                    try:
                        previous_roles.append(int(value))
                    except (TypeError, ValueError):
                        continue
                settings["mod_role_ids"] = sorted(set(previous_roles + mod_roles))
            if category:
                settings["ticket_category_id"] = category.id

            # 디스크 저장으로 이벤트 루프가 멈추지 않도록 별도 스레드에서 처리합니다.
            await asyncio.wait_for(asyncio.to_thread(save_data), timeout=15)

            await finish(
                "✅ **SERVER GUARD 초기 연결 완료**\n"
                f"로그: {getattr(log_channel, 'mention', '미설정')}\n"
                f"환영: {getattr(welcome_channel, 'mention', '미설정')}\n"
                f"퇴장: {getattr(leave_channel, 'mention', '미설정')}\n"
                f"자동 역할: {getattr(autorole, 'mention', '미설정')}\n"
                f"운영 역할: **{len(settings.get('mod_role_ids', []))}개**\n"
                f"문의 카테고리: **{getattr(category, 'name', '미설정')}** ({category_note})\n\n"
                "자동 관리는 안전을 위해 기본적으로 꺼져 있습니다. `!자동관리 켜기`로 활성화하세요.\n"
                "자동 이모지·격리 기능은 `!운영강화설정`으로 연결하세요.\n"
                "전체 상태 확인은 `!운영대시보드`를 사용하세요."
            )
            print(
                f"[운영초기설정 완료] guild={guild.id} user={ctx.author.id} "
                f"log={getattr(log_channel, 'id', 0)} category={getattr(category, 'id', 0)}",
                flush=True,
            )
        except asyncio.TimeoutError:
            await finish(
                "❌ **운영 초기 설정이 시간 초과되었습니다.**\n"
                "잠시 뒤 다시 실행하거나 `!운영진단`으로 상태를 확인해주세요."
            )
            print(f"[운영초기설정 시간초과] guild={guild.id} user={ctx.author.id}", flush=True)
        except Exception as exc:
            await finish(
                "❌ **운영 초기 설정 중 오류가 발생했습니다.**\n"
                f"오류: `{type(exc).__name__}: {str(exc)[:500]}`\n"
                "Render 로그의 `[운영초기설정 오류]` 항목을 확인해주세요."
            )
            print(
                f"[운영초기설정 오류] guild={guild.id} user={ctx.author.id} "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            import traceback as _traceback
            _traceback.print_exc()

    @bot.command(name="운영진단", aliases=["가드진단"], help="SERVER GUARD 명령 등록과 권한 상태를 확인합니다.")
    async def management_diagnostic(ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        me = ctx.guild.me
        command_names = ("운영초기설정", "운영설정", "운영강화설정", "자동이모지", "운영대시보드", "셀프역할패널", "보안초기설정", "보안상태", "접수패널", "접수센터상태")
        registered = [name for name in command_names if bot.get_command(name) is not None]
        missing = [name for name in command_names if bot.get_command(name) is None]
        perms = me.guild_permissions if me is not None else None
        embed = discord.Embed(title="🧪 SERVER GUARD 진단", color=0x3498DB)
        embed.add_field(
            name="명령어 등록",
            value=("✅ " + ", ".join(registered)) if registered else "❌ 확인된 명령어 없음",
            inline=False,
        )
        embed.add_field(
            name="누락",
            value=("⚠️ " + ", ".join(missing)) if missing else "없음",
            inline=False,
        )
        embed.add_field(
            name="봇 권한",
            value=(
                f"관리자: **{'예' if perms and perms.administrator else '아니오'}**\n"
                f"서버 관리: **{'예' if perms and perms.manage_guild else '아니오'}**\n"
                f"채널 관리: **{'예' if perms and perms.manage_channels else '아니오'}**\n"
                f"역할 관리: **{'예' if perms and perms.manage_roles else '아니오'}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="실행자 권한",
            value=(
                f"서버 소유자: **{'예' if ctx.author.id == ctx.guild.owner_id else '아니오'}**\n"
                f"관리자: **{'예' if ctx.author.guild_permissions.administrator else '아니오'}**\n"
                f"서버 관리: **{'예' if ctx.author.guild_permissions.manage_guild else '아니오'}**"
            ),
            inline=True,
        )
        embed.set_footer(text="기본: !운영초기설정 | 보안: !보안초기설정 | 접수: !접수초기설정")
        await ctx.send(embed=embed)

    @bot.command(name="운영설정", help="현재 서버 관리 설정을 확인합니다.")
    async def management_status(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        guild = ctx.guild
        settings = get_settings(guild)
        automod = settings["automod"]
        log_channel = resolve_channel(guild, settings.get("log_channel_id"))
        welcome = resolve_channel(guild, settings.get("welcome_channel_id"))
        leave = resolve_channel(guild, settings.get("leave_channel_id"))
        autorole = guild.get_role(int(settings.get("autorole_id", 0))) if settings.get("autorole_id") else None
        category = resolve_channel(guild, settings.get("ticket_category_id"))
        roles = [guild.get_role(role_id) for role_id in operator_role_ids(settings)]
        roles = [role for role in roles if role is not None]
        active_warning_count = sum(
            len([item for item in records if item.get("active", True)])
            for records in settings.get("warnings", {}).values()
            if isinstance(records, list)
        )
        embed = discord.Embed(title="⚙️ SERVER GUARD 설정", color=0x8E44AD)
        embed.add_field(name="로그 채널", value=getattr(log_channel, "mention", "미설정"), inline=True)
        embed.add_field(name="환영 채널", value=getattr(welcome, "mention", "미설정"), inline=True)
        embed.add_field(name="퇴장 채널", value=getattr(leave, "mention", "미설정"), inline=True)
        embed.add_field(name="자동 역할", value=getattr(autorole, "mention", "미설정"), inline=True)
        embed.add_field(name="문의 카테고리", value=getattr(category, "name", "미설정"), inline=True)
        embed.add_field(name="운영 역할", value=", ".join(role.mention for role in roles) or "미설정", inline=False)
        embed.add_field(
            name="자동 관리",
            value=(
                f"전체: **{'켜짐' if automod['enabled'] else '꺼짐'}**\n"
                f"도배: **{'켜짐' if automod['spam'] else '꺼짐'}** · "
                f"멘션 도배: **{'켜짐' if automod['mention_spam'] else '꺼짐'}**\n"
                f"초대 링크: **{'켜짐' if automod['invites'] else '꺼짐'}** · "
                f"금칙어: **{'켜짐' if automod['bad_words'] else '꺼짐'}**\n"
                f"처리 모드: **{automod.get('action_mode', '삭제')}** · 자동 타임아웃: **{'켜짐' if automod['auto_timeout'] else '꺼짐'}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="운영 현황",
            value=(
                f"활성 경고: **{active_warning_count:,}건**\n"
                f"누적 사건: **{len(settings.get('cases', [])):,}건**\n"
                f"열린 문의: **{len(settings.get('open_tickets', {})):,}개**"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @bot.command(name="경고", help="멤버에게 사유와 함께 경고를 부여합니다.")
    async def warn_member(ctx: commands.Context, 대상: discord.Member, *, 사유: str = "사유 미기재") -> None:
        if not await require_operator(ctx):
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        case = await issue_warning(ctx.guild, 대상, ctx.author, 사유)
        count = len(active_warnings(get_settings(ctx.guild), 대상.id))
        auto_result = await maybe_auto_punish(ctx.guild, 대상, ctx.author)
        await ctx.send(
            f"⚠️ {대상.mention}에게 경고를 부여했습니다. "
            f"현재 **{count}회** · 사건 **#{case['id']}**"
            + (f"\n🕒 {auto_result}" if auto_result else "")
        )
        await send_log(
            ctx.guild,
            "⚠️ 경고 부여",
            f"대상: {대상.mention} (`{대상.id}`)\n운영자: {ctx.author.mention}\n사유: {사유}",
            color=0xF1C40F,
            fields=[("사건 번호", f"#{case['id']}", True), ("활성 경고", f"{count}회", True)],
        )

    @bot.command(name="경고조회", help="멤버의 활성 경고 기록을 확인합니다.")
    async def warning_lookup(ctx: commands.Context, 대상: discord.Member) -> None:
        if not await require_operator(ctx):
            return
        records = active_warnings(get_settings(ctx.guild), 대상.id)
        if not records:
            await ctx.send(f"✅ {대상.mention}의 활성 경고는 없습니다.")
            return
        lines = []
        for item in records[-15:]:
            moderator = ctx.guild.get_member(int(item.get("moderator_id", 0)))
            mod_text = moderator.mention if moderator else f"`{item.get('moderator_id', 0)}`"
            lines.append(
                f"**#{item.get('case_id', '?')}** · {item.get('reason', '사유 없음')}\n"
                f"└ 운영자 {mod_text} · {item.get('created_at', '')[:19].replace('T', ' ')}"
            )
        embed = discord.Embed(
            title=f"⚠️ {대상.display_name} 경고 기록",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        embed.set_footer(text=f"활성 경고 {len(records)}회 · 최근 15건 표시")
        await ctx.send(embed=embed)

    @bot.command(name="경고취소", help="사건 번호로 활성 경고를 취소합니다.")
    async def warning_revoke(ctx: commands.Context, 대상: discord.Member, 사건번호: int) -> None:
        if not await require_operator(ctx):
            return
        settings = get_settings(ctx.guild)
        found = None
        for item in settings.setdefault("warnings", {}).setdefault(str(대상.id), []):
            if int(item.get("case_id", -1)) == 사건번호 and item.get("active", True):
                item["active"] = False
                item["revoked_by"] = ctx.author.id
                item["revoked_at"] = now_iso()
                found = item
                break
        if found is None:
            await ctx.send("⚠️ 해당 사건 번호의 활성 경고를 찾지 못했습니다.")
            return
        for case in settings.setdefault("cases", []):
            if int(case.get("id", -1)) == 사건번호:
                case["active"] = False
                case["revoked_by"] = ctx.author.id
                case["revoked_at"] = now_iso()
                break
        save_data()
        await ctx.send(f"✅ {대상.mention}의 경고 **#{사건번호}**를 취소했습니다.")
        await send_log(
            ctx.guild,
            "♻️ 경고 취소",
            f"대상: {대상.mention}\n운영자: {ctx.author.mention}\n사건 번호: **#{사건번호}**",
            color=0x2ECC71,
        )

    @bot.command(name="타임아웃", help="멤버를 지정한 기간 동안 타임아웃합니다.")
    async def timeout_member(
        ctx: commands.Context,
        대상: discord.Member,
        기간: str,
        *,
        사유: str = "사유 미기재",
    ) -> None:
        if not await require_operator(ctx):
            return
        seconds = parse_duration(기간)
        if seconds is None:
            await ctx.send("⚠️ 기간 예시: `10분`, `2시간`, `1일` · 최대 28일")
            return
        ok, error, case = await perform_timeout(ctx.guild, ctx.author, 대상, seconds, 사유)
        if not ok:
            await ctx.send(f"❌ {error}")
            return
        await ctx.send(
            f"🕒 {대상.mention}에게 **{human_duration(seconds)} 타임아웃**을 적용했습니다. "
            f"사건 **#{case['id']}**"
        )
        await send_log(
            ctx.guild,
            "🕒 타임아웃",
            f"대상: {대상.mention} (`{대상.id}`)\n운영자: {ctx.author.mention}\n사유: {사유}",
            color=0xE67E22,
            fields=[("기간", human_duration(seconds), True), ("사건", f"#{case['id']}", True)],
        )

    @bot.command(name="타임아웃해제", help="멤버의 타임아웃을 즉시 해제합니다.")
    async def timeout_remove(
        ctx: commands.Context,
        대상: discord.Member,
        *,
        사유: str = "관리자 해제",
    ) -> None:
        if not await require_operator(ctx):
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        try:
            await 대상.timeout(None, reason=f"{ctx.author} | {사유}")
        except discord.Forbidden:
            await ctx.send("❌ 권한 또는 역할 순서 때문에 해제하지 못했습니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 요청 오류: {exc}")
            return
        case = add_case(ctx.guild, "untimeout", 대상.id, ctx.author.id, 사유)
        save_data()
        await ctx.send(f"✅ {대상.mention}의 타임아웃을 해제했습니다. 사건 **#{case['id']}**")
        await send_log(
            ctx.guild,
            "✅ 타임아웃 해제",
            f"대상: {대상.mention}\n운영자: {ctx.author.mention}\n사유: {사유}",
            color=0x2ECC71,
        )

    @bot.command(name="추방", help="멤버를 서버에서 추방합니다.")
    async def kick_member(ctx: commands.Context, 대상: discord.Member, *, 사유: str = "사유 미기재") -> None:
        if not await require_operator(ctx):
            return
        if not (ctx.author.guild_permissions.kick_members or ctx.author.id == ctx.guild.owner_id):
            await ctx.send("❌ 실행자에게 `멤버 추방` 권한이 없습니다.")
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        try:
            await 대상.kick(reason=f"{ctx.author} | {사유}")
        except discord.Forbidden:
            await ctx.send("❌ 권한 또는 역할 순서 때문에 추방하지 못했습니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 요청 오류: {exc}")
            return
        case = add_case(ctx.guild, "kick", 대상.id, ctx.author.id, 사유)
        settings = get_settings(ctx.guild)
        settings["stats"]["kicks"] = int(settings["stats"].get("kicks", 0)) + 1
        save_data()
        await ctx.send(f"👢 **{대상}**을(를) 추방했습니다. 사건 **#{case['id']}**")
        await send_log(
            ctx.guild,
            "👢 멤버 추방",
            f"대상: **{대상}** (`{대상.id}`)\n운영자: {ctx.author.mention}\n사유: {사유}",
            color=0xE67E22,
        )

    @bot.command(name="차단", help="멤버를 서버에서 차단합니다.")
    async def ban_member(ctx: commands.Context, 대상: discord.Member, *, 사유: str = "사유 미기재") -> None:
        if not await require_operator(ctx):
            return
        if not (ctx.author.guild_permissions.ban_members or ctx.author.id == ctx.guild.owner_id):
            await ctx.send("❌ 실행자에게 `멤버 차단` 권한이 없습니다.")
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        try:
            await ctx.guild.ban(대상, reason=f"{ctx.author} | {사유}", delete_message_seconds=0)
        except discord.Forbidden:
            await ctx.send("❌ 권한 또는 역할 순서 때문에 차단하지 못했습니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 요청 오류: {exc}")
            return
        case = add_case(ctx.guild, "ban", 대상.id, ctx.author.id, 사유)
        settings = get_settings(ctx.guild)
        settings["stats"]["bans"] = int(settings["stats"].get("bans", 0)) + 1
        save_data()
        await ctx.send(f"🔨 **{대상}**을(를) 차단했습니다. 사건 **#{case['id']}**")
        await send_log(
            ctx.guild,
            "🔨 멤버 차단",
            f"대상: **{대상}** (`{대상.id}`)\n운영자: {ctx.author.mention}\n사유: {사유}",
            color=0xC0392B,
        )

    @bot.command(name="차단해제", help="유저 ID로 서버 차단을 해제합니다.")
    async def unban_member(ctx: commands.Context, 유저id: int, *, 사유: str = "관리자 해제") -> None:
        if not await require_operator(ctx):
            return
        if not (ctx.author.guild_permissions.ban_members or ctx.author.id == ctx.guild.owner_id):
            await ctx.send("❌ 실행자에게 `멤버 차단` 권한이 없습니다.")
            return
        try:
            user = await bot.fetch_user(유저id)
            await ctx.guild.unban(user, reason=f"{ctx.author} | {사유}")
        except discord.NotFound:
            await ctx.send("⚠️ 해당 유저는 차단 목록에 없습니다.")
            return
        except discord.Forbidden:
            await ctx.send("❌ 아바돈에게 차단 해제 권한이 없습니다.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 요청 오류: {exc}")
            return
        case = add_case(ctx.guild, "unban", user.id, ctx.author.id, 사유)
        save_data()
        await ctx.send(f"✅ **{user}** (`{user.id}`)의 차단을 해제했습니다. 사건 **#{case['id']}**")
        await send_log(
            ctx.guild,
            "✅ 차단 해제",
            f"대상: **{user}** (`{user.id}`)\n운영자: {ctx.author.mention}\n사유: {사유}",
            color=0x2ECC71,
        )

    @bot.command(name="청소", help="현재 채널의 최근 메시지를 일괄 삭제합니다.")
    async def purge_messages(ctx: commands.Context, 수량: int) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            await ctx.send("❌ 텍스트 채널에서만 사용할 수 있습니다.")
            return
        if not 1 <= 수량 <= 100:
            await ctx.send("⚠️ 삭제 수량은 **1~100개**입니다.")
            return
        if not ctx.author.guild_permissions.manage_messages and ctx.author.id != ctx.guild.owner_id:
            await ctx.send("❌ 실행자에게 `메시지 관리` 권한이 없습니다.")
            return
        try:
            deleted = await ctx.channel.purge(limit=수량 + 1, reason=f"메시지 청소: {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ 아바돈에게 `메시지 관리` 권한을 주세요.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Discord 요청 오류: {exc}")
            return
        notice = await ctx.channel.send(f"🧹 **{max(0, len(deleted) - 1)}개** 메시지를 정리했습니다.")
        await notice.delete(delay=4)
        await send_log(
            ctx.guild,
            "🧹 메시지 청소",
            f"채널: {ctx.channel.mention}\n운영자: {ctx.author.mention}\n삭제 요청: **{수량}개**",
            color=0x3498DB,
        )

    @bot.command(name="슬로우", help="현재 채널의 느린 모드 시간을 설정합니다.")
    async def set_slowmode(ctx: commands.Context, 초: int) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 일반 텍스트 채널에서만 사용할 수 있습니다.")
            return
        if not 0 <= 초 <= 21600:
            await ctx.send("⚠️ 느린 모드는 **0~21,600초**로 설정하세요. `0`은 해제입니다.")
            return
        try:
            await ctx.channel.edit(slowmode_delay=초, reason=f"슬로우 설정: {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ 아바돈에게 `채널 관리` 권한을 주세요.")
            return
        await ctx.send(f"⏱️ 느린 모드를 **{초}초**로 설정했습니다." if 초 else "✅ 느린 모드를 해제했습니다.")

    @bot.command(name="채널잠금", help="현재 채널에서 일반 멤버의 메시지 전송을 잠급니다.")
    async def lock_channel(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 일반 텍스트 채널에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        key = str(ctx.channel.id)
        if key in settings.setdefault("channel_locks", {}):
            await ctx.send("⚠️ 이미 잠긴 채널입니다.")
            return
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        settings["channel_locks"][key] = {
            "send_messages": overwrite.send_messages,
            "send_messages_in_threads": overwrite.send_messages_in_threads,
        }
        overwrite.send_messages = False
        overwrite.send_messages_in_threads = False
        try:
            await ctx.channel.set_permissions(
                ctx.guild.default_role,
                overwrite=overwrite,
                reason=f"채널 잠금: {ctx.author}",
            )
        except discord.Forbidden:
            settings["channel_locks"].pop(key, None)
            await ctx.send("❌ 아바돈에게 `채널 관리` 권한을 주세요.")
            return
        save_data()
        await ctx.send("🔒 이 채널을 잠갔습니다. 운영진은 계속 대화할 수 있습니다.")
        await send_log(
            ctx.guild,
            "🔒 채널 잠금",
            f"채널: {ctx.channel.mention}\n운영자: {ctx.author.mention}",
            color=0xC0392B,
        )

    @bot.command(name="채널해제", help="현재 채널의 메시지 잠금을 원래 상태로 복원합니다.")
    async def unlock_channel(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 일반 텍스트 채널에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        previous = settings.setdefault("channel_locks", {}).get(str(ctx.channel.id))
        if previous is None:
            await ctx.send("⚠️ 아바돈으로 잠근 기록이 없는 채널입니다.")
            return
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = previous.get("send_messages")
        overwrite.send_messages_in_threads = previous.get("send_messages_in_threads")
        try:
            await ctx.channel.set_permissions(
                ctx.guild.default_role,
                overwrite=overwrite,
                reason=f"채널 잠금 해제: {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.send("❌ 아바돈에게 `채널 관리` 권한을 주세요.")
            return
        settings["channel_locks"].pop(str(ctx.channel.id), None)
        save_data()
        await ctx.send("🔓 채널 잠금을 해제하고 기존 권한으로 복원했습니다.")

    @bot.command(name="닉네임", help="멤버의 서버 닉네임을 변경하거나 초기화합니다.")
    async def set_nickname(
        ctx: commands.Context,
        대상: discord.Member,
        *,
        새이름: str,
    ) -> None:
        if not await require_operator(ctx):
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        name = 새이름.strip()
        if name.lower() in {"초기화", "해제", "없음", "reset"}:
            name = None
        elif not 1 <= len(name) <= 32:
            await ctx.send("⚠️ 닉네임은 **1~32자**여야 합니다.")
            return
        try:
            await 대상.edit(nick=name, reason=f"닉네임 변경: {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ 권한 또는 역할 순서 때문에 닉네임을 변경하지 못했습니다.")
            return
        await ctx.send(f"✅ {대상.mention}의 닉네임을 **{name or '초기화'}**했습니다.")

    @bot.command(name="역할지급", help="멤버에게 지정한 역할을 지급합니다.")
    async def give_role(ctx: commands.Context, 대상: discord.Member, 역할: discord.Role) -> None:
        if not await require_operator(ctx):
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        if 역할.is_default() or 역할.managed:
            await ctx.send("❌ 기본 역할 또는 외부 연동 역할은 지급할 수 없습니다.")
            return
        if ctx.author.id != ctx.guild.owner_id and 역할 >= ctx.author.top_role:
            await ctx.send("❌ 실행자보다 같거나 높은 역할은 지급할 수 없습니다.")
            return
        if ctx.guild.me is None or 역할 >= ctx.guild.me.top_role:
            await ctx.send("❌ 아바돈 역할을 지급할 역할보다 위로 올려주세요.")
            return
        try:
            await 대상.add_roles(역할, reason=f"역할 지급: {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ 역할 관리 권한이 없습니다.")
            return
        await ctx.send(f"✅ {대상.mention}에게 {역할.mention} 역할을 지급했습니다.")

    @bot.command(name="역할회수", help="멤버에게서 지정한 역할을 회수합니다.")
    async def remove_role(ctx: commands.Context, 대상: discord.Member, 역할: discord.Role) -> None:
        if not await require_operator(ctx):
            return
        allowed, why = can_act_on(ctx.author, 대상, ctx.guild.me)
        if not allowed:
            await ctx.send(f"❌ {why}")
            return
        if ctx.author.id != ctx.guild.owner_id and 역할 >= ctx.author.top_role:
            await ctx.send("❌ 실행자보다 같거나 높은 역할은 회수할 수 없습니다.")
            return
        if ctx.guild.me is None or 역할 >= ctx.guild.me.top_role:
            await ctx.send("❌ 아바돈 역할을 회수할 역할보다 위로 올려주세요.")
            return
        try:
            await 대상.remove_roles(역할, reason=f"역할 회수: {ctx.author}")
        except discord.Forbidden:
            await ctx.send("❌ 역할 관리 권한이 없습니다.")
            return
        await ctx.send(f"✅ {대상.mention}에게서 {역할.mention} 역할을 회수했습니다.")

    @bot.command(name="로그채널", help="운영 기록이 전송될 로그 채널을 지정합니다.")
    async def set_log_channel(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        settings["log_channel_id"] = 채널.id
        save_data()
        await ctx.send(f"✅ 운영 로그 채널을 {채널.mention}(으)로 설정했습니다.")

    @bot.command(name="환영채널", help="신규 멤버 환영 메시지 채널을 지정합니다.")
    async def set_welcome_channel(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        settings["welcome_channel_id"] = 채널.id
        sync = getattr(bot, "v720_sync_welcome", None)
        if callable(sync):
            sync(ctx.guild.id, welcome_channel_id=채널.id)
        else:
            save_data()
        await ctx.send(f"✅ 통합 환영 채널을 {채널.mention}(으)로 설정했습니다.")

    @bot.command(
        name="인삿말설정",
        aliases=["인사말설정", "환영안내설정"],
        help="환영 메시지에 표시할 공지·규칙·가입 채널을 지정합니다.",
    )
    async def set_welcome_guide(
        ctx: commands.Context,
        환영채널: discord.TextChannel,
        공지채널: discord.TextChannel,
        규칙채널: discord.TextChannel,
        가입채널: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        settings["welcome_channel_id"] = 환영채널.id
        settings["welcome_notice_channel_id"] = 공지채널.id
        settings["welcome_rules_channel_id"] = 규칙채널.id
        settings["welcome_register_channel_id"] = 가입채널.id if 가입채널 else 0
        sync = getattr(bot, "v720_sync_welcome", None)
        if callable(sync):
            sync(
                ctx.guild.id,
                welcome_channel_id=환영채널.id,
                welcome_notice_channel_id=공지채널.id,
                welcome_rules_channel_id=규칙채널.id,
                welcome_register_channel_id=가입채널.id if 가입채널 else 0,
            )
        else:
            save_data()
        register_text = 가입채널.mention if 가입채널 else "별도 채널 미지정"
        await ctx.send(
            "✅ 신규 멤버 인삿말 구성을 저장했습니다.\n"
            f"환영 메시지: {환영채널.mention}\n"
            f"공지사항: {공지채널.mention}\n"
            f"서버 기본규칙: {규칙채널.mention}\n"
            f"RPG 가입 안내: {register_text}\n\n"
            "신규 멤버는 별도 복잡한 인증 없이 `!가입 생존자`로 바로 시작할 수 있습니다."
        )

    @bot.command(name="인삿말미리보기", aliases=["인사말미리보기", "환영미리보기"])
    async def preview_welcome_guide(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        preview = getattr(bot, "v720_welcome_preview", None)
        if callable(preview):
            await preview(ctx)
            return
        settings = get_settings(ctx.guild)
        notice, rules, register = welcome_link_channels(ctx.guild, settings)
        embed = discord.Embed(
            title="🆕 새로운 생존자가 도착했습니다",
            description=(
                f"{ctx.author.mention} **{ctx.guild.name}**에 온 걸 환영합니다!\n\n"
                f"📢 **서버 공지사항** · {getattr(notice, 'mention', '미설정')}\n"
                f"📕 **서버 기본규칙** · {getattr(rules, 'mention', '미설정')}\n"
                + (f"🪪 **생존자 등록 채널** · {register.mention}\n" if register else "")
                + "\n별도 복잡한 가입 절차는 없습니다. `!가입 생존자`를 입력하면 RPG를 바로 사용할 수 있습니다."
            ),
            color=0x6D2335,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.set_footer(text="통합 환영 시스템 미리보기")
        await ctx.send(embed=embed)

    @bot.command(name="인삿말상태", aliases=["인사말상태"])
    async def welcome_guide_status(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        welcome = resolve_channel(ctx.guild, settings.get("welcome_channel_id", 0))
        notice, rules, register = welcome_link_channels(ctx.guild, settings)
        await ctx.send(
            "🧭 **인삿말 설정 상태**\n"
            f"환영 채널: {getattr(welcome, 'mention', '미설정')}\n"
            f"공지사항: {getattr(notice, 'mention', '자동 감지 실패')}\n"
            f"서버 기본규칙: {getattr(rules, 'mention', '자동 감지 실패')}\n"
            f"가입 안내: {getattr(register, 'mention', '`!가입 생존자` 직접 안내')}"
        )

    @bot.command(name="퇴장채널", help="멤버 퇴장 메시지 채널을 지정합니다.")
    async def set_leave_channel(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        settings["leave_channel_id"] = 채널.id
        save_data()
        await ctx.send(f"✅ 퇴장 채널을 {채널.mention}(으)로 설정했습니다.")

    @bot.command(name="자동역할", help="신규 멤버에게 자동 지급할 역할을 지정합니다.")
    async def set_autorole(ctx: commands.Context, 역할: discord.Role) -> None:
        if not await require_manager(ctx):
            return
        if 역할.is_default() or 역할.managed:
            await ctx.send("❌ 기본 역할 또는 외부 연동 역할은 설정할 수 없습니다.")
            return
        if ctx.guild.me is None or 역할 >= ctx.guild.me.top_role:
            await ctx.send("❌ 아바돈 역할을 자동 역할보다 위로 올려주세요.")
            return
        settings = get_settings(ctx.guild)
        settings["autorole_id"] = 역할.id
        sync = getattr(bot, "v720_sync_welcome", None)
        if callable(sync):
            sync(
                ctx.guild.id,
                role_id=역할.id,
                role_mode="permanent",
                role_enabled=True,
                role_created_by_abaddon=False,
            )
        else:
            save_data()
        await ctx.send(f"✅ 통합 신규 멤버 역할을 {역할.mention}(으)로 설정했습니다. 이 역할은 영구 유지됩니다.")

    @bot.command(name="자동역할해제", help="신규 멤버 자동 역할을 해제합니다.")
    async def clear_autorole(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        get_settings(ctx.guild)["autorole_id"] = 0
        sync = getattr(bot, "v720_sync_welcome", None)
        if callable(sync):
            sync(ctx.guild.id, role_id=0, role_enabled=False)
        else:
            save_data()
        await ctx.send("✅ 통합 신규 멤버 역할 지급을 해제했습니다. 환영 메시지는 설정대로 유지됩니다.")

    @bot.command(name="관리역할추가", help="SERVER GUARD 운영 명령어를 사용할 역할을 추가합니다.")
    async def add_mod_role(ctx: commands.Context, 역할: discord.Role) -> None:
        if not await require_manager(ctx):
            return
        if 역할.is_default() or 역할.managed:
            await ctx.send("❌ 기본 역할 또는 외부 연동 역할은 운영 역할로 등록할 수 없습니다.")
            return
        settings = get_settings(ctx.guild)
        roles = set(int(value) for value in settings.get("mod_role_ids", []))
        roles.add(역할.id)
        settings["mod_role_ids"] = sorted(roles)
        save_data()
        await ctx.send(f"✅ {역할.mention} 역할을 운영진으로 등록했습니다.")

    @bot.command(name="관리역할제거", help="SERVER GUARD 운영 역할 등록을 해제합니다.")
    async def remove_mod_role(ctx: commands.Context, 역할: discord.Role) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        settings["mod_role_ids"] = [
            int(value) for value in settings.get("mod_role_ids", []) if int(value) != 역할.id
        ]
        save_data()
        await ctx.send(f"✅ {역할.mention} 역할의 운영진 등록을 해제했습니다.")

    @bot.command(name="자동관리", help="도배, 멘션 도배 등 자동 관리를 켜거나 끕니다.")
    async def toggle_automod(ctx: commands.Context, 상태: str) -> None:
        if not await require_manager(ctx):
            return
        enabled = parse_toggle(상태)
        if enabled is None:
            await ctx.send("⚠️ 사용법: `!자동관리 ON` 또는 `!자동관리 OFF`")
            return
        get_settings(ctx.guild)["automod"]["enabled"] = enabled
        save_data()
        await ctx.send(f"🤖 자동 관리를 **{'켜짐' if enabled else '꺼짐'}**으로 설정했습니다.")

    @bot.command(name="초대차단", help="Discord 초대 링크 자동 삭제를 켜거나 끕니다.")
    async def toggle_invites(ctx: commands.Context, 상태: str) -> None:
        if not await require_manager(ctx):
            return
        enabled = parse_toggle(상태)
        if enabled is None:
            await ctx.send("⚠️ 사용법: `!초대차단 ON` 또는 `!초대차단 OFF`")
            return
        get_settings(ctx.guild)["automod"]["invites"] = enabled
        save_data()
        await ctx.send(f"🔗 초대 링크 차단을 **{'켜짐' if enabled else '꺼짐'}**으로 설정했습니다.")

    @bot.command(name="욕설차단", help="관리자가 등록한 금칙어 자동 삭제를 켜거나 끕니다.")
    async def toggle_bad_words(ctx: commands.Context, 상태: str) -> None:
        if not await require_manager(ctx):
            return
        enabled = parse_toggle(상태)
        if enabled is None:
            await ctx.send("⚠️ 사용법: `!욕설차단 ON` 또는 `!욕설차단 OFF`")
            return
        get_settings(ctx.guild)["automod"]["bad_words"] = enabled
        save_data()
        await ctx.send(f"🚫 금칙어 차단을 **{'켜짐' if enabled else '꺼짐'}**으로 설정했습니다.")

    @bot.command(name="욕설추가", help="자동 삭제할 금칙어를 추가합니다.")
    async def add_bad_word(ctx: commands.Context, *, 단어: str) -> None:
        if not await require_manager(ctx):
            return
        word = 단어.strip().lower()
        if not 2 <= len(word) <= 40:
            await ctx.send("⚠️ 금칙어는 **2~40자**로 입력하세요.")
            return
        words = get_settings(ctx.guild)["automod"].setdefault("bad_word_list", [])
        if word in words:
            await ctx.send("⚠️ 이미 등록된 금칙어입니다.")
            return
        words.append(word)
        words.sort()
        save_data()
        await ctx.send(f"✅ 금칙어를 추가했습니다. 현재 **{len(words)}개**")

    @bot.command(name="욕설삭제", help="등록된 금칙어를 삭제합니다.")
    async def remove_bad_word(ctx: commands.Context, *, 단어: str) -> None:
        if not await require_manager(ctx):
            return
        word = 단어.strip().lower()
        words = get_settings(ctx.guild)["automod"].setdefault("bad_word_list", [])
        if word not in words:
            await ctx.send("⚠️ 등록되지 않은 금칙어입니다.")
            return
        words.remove(word)
        save_data()
        await ctx.send(f"✅ 금칙어를 삭제했습니다. 현재 **{len(words)}개**")

    @bot.command(name="욕설목록", help="등록된 금칙어 목록을 운영진에게만 표시합니다.")
    async def list_bad_words(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        words = get_settings(ctx.guild)["automod"].setdefault("bad_word_list", [])
        if not words:
            await ctx.send("등록된 금칙어가 없습니다.")
            return
        text = ", ".join(f"`{word}`" for word in words)
        if len(text) > 1800:
            text = text[:1800] + "…"
        await ctx.send(f"🚫 **금칙어 {len(words)}개**\n{text}")

    @bot.command(name="예외채널", help="자동 관리가 작동하지 않을 채널을 추가합니다.")
    async def add_exempt_channel(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        automod = get_settings(ctx.guild)["automod"]
        values = set(int(value) for value in automod.setdefault("exempt_channel_ids", []))
        values.add(채널.id)
        automod["exempt_channel_ids"] = sorted(values)
        save_data()
        await ctx.send(f"✅ {채널.mention}을 자동 관리 예외 채널로 등록했습니다.")

    @bot.command(name="예외채널해제", help="자동 관리 예외 채널 등록을 해제합니다.")
    async def remove_exempt_channel(ctx: commands.Context, 채널: discord.TextChannel) -> None:
        if not await require_manager(ctx):
            return
        automod = get_settings(ctx.guild)["automod"]
        automod["exempt_channel_ids"] = [
            int(value)
            for value in automod.setdefault("exempt_channel_ids", [])
            if int(value) != 채널.id
        ]
        save_data()
        await ctx.send(f"✅ {채널.mention}의 자동 관리 예외를 해제했습니다.")

    @bot.command(name="자동처벌", help="경고 누적 및 자동 관리 타임아웃을 켜거나 끕니다.")
    async def toggle_auto_timeout(ctx: commands.Context, 상태: str) -> None:
        if not await require_manager(ctx):
            return
        enabled = parse_toggle(상태)
        if enabled is None:
            await ctx.send("⚠️ 사용법: `!자동처벌 ON` 또는 `!자동처벌 OFF`")
            return
        get_settings(ctx.guild)["automod"]["auto_timeout"] = enabled
        save_data()
        await ctx.send(f"⚖️ 자동 타임아웃을 **{'켜짐' if enabled else '꺼짐'}**으로 설정했습니다.")

    @bot.command(name="문의패널", help="버튼으로 문의 채널을 만드는 패널을 설치합니다.")
    async def ticket_panel(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        embed = discord.Embed(
            title="🎫 ABADDON 문의 센터",
            description=(
                "신고, 제재 이의 신청, 서버 문의가 있다면 아래 버튼을 눌러주세요.\n"
                "본인과 운영진만 볼 수 있는 비공개 채널이 생성됩니다."
            ),
            color=0x8E44AD,
        )
        embed.set_footer(text="중복 문의 채널은 생성되지 않습니다.")
        await ctx.send(embed=embed, view=TicketCreateView())

    @bot.command(name="문의닫기", help="현재 아바돈 문의 채널을 종료합니다.")
    async def ticket_close_command(ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 문의 채널에서만 사용할 수 있습니다.")
            return
        ok, text = await close_ticket_channel(ctx.channel, ctx.author)
        if not ok:
            await ctx.send(f"❌ {text}")

    @bot.command(name="문의추가", help="현재 문의 채널에 다른 멤버를 추가합니다.")
    async def ticket_add_member(ctx: commands.Context, 대상: discord.Member) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 문의 채널에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        if str(ctx.channel.id) not in {str(value) for value in settings.get("open_tickets", {}).values()}:
            await ctx.send("❌ 등록된 문의 채널이 아닙니다.")
            return
        try:
            await ctx.channel.set_permissions(
                대상,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason=f"문의 참여자 추가: {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.send("❌ 채널 권한을 변경하지 못했습니다.")
            return
        await ctx.send(f"✅ {대상.mention}을 문의 채널에 추가했습니다.")

    @bot.command(name="문의제거", help="현재 문의 채널에서 멤버를 제거합니다.")
    async def ticket_remove_member(ctx: commands.Context, 대상: discord.Member) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 문의 채널에서만 사용할 수 있습니다.")
            return
        settings = get_settings(ctx.guild)
        if str(ctx.channel.id) not in {str(value) for value in settings.get("open_tickets", {}).values()}:
            await ctx.send("❌ 등록된 문의 채널이 아닙니다.")
            return
        try:
            await ctx.channel.set_permissions(
                대상,
                overwrite=None,
                reason=f"문의 참여자 제거: {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.send("❌ 채널 권한을 변경하지 못했습니다.")
            return
        await ctx.send(f"✅ {대상.mention}을 문의 채널에서 제거했습니다.")

    @bot.command(name="서버통계", help="현재 서버의 운영 및 멤버 통계를 확인합니다.")
    async def server_stats(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        guild = ctx.guild
        settings = get_settings(guild)
        humans = sum(1 for member in guild.members if not member.bot)
        bots = sum(1 for member in guild.members if member.bot)
        online = sum(
            1 for member in guild.members
            if not member.bot and member.status is not discord.Status.offline
        )
        stats = settings["stats"]
        embed = discord.Embed(title=f"📊 {guild.name} 서버 통계", color=0x3498DB)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="멤버", value=f"전체 **{guild.member_count or len(guild.members):,}명**\n사람 **{humans:,}명** · 봇 **{bots:,}명**\n접속 **{online:,}명**", inline=True)
        embed.add_field(name="채널", value=f"텍스트 **{len(guild.text_channels)}개**\n음성 **{len(guild.voice_channels)}개**\n카테고리 **{len(guild.categories)}개**", inline=True)
        embed.add_field(name="서버", value=f"역할 **{len(guild.roles)}개**\n부스트 **{guild.premium_subscription_count or 0}개**\n레벨 **{guild.premium_tier}**", inline=True)
        embed.add_field(
            name="SERVER GUARD 누적",
            value=(
                f"경고 **{int(stats.get('warnings', 0)):,}건** · 타임아웃 **{int(stats.get('timeouts', 0)):,}건**\n"
                f"추방 **{int(stats.get('kicks', 0)):,}건** · 차단 **{int(stats.get('bans', 0)):,}건**\n"
                f"자동 관리 적발 **{int(stats.get('automod_hits', 0)):,}건** · 문의 **{int(stats.get('tickets', 0)):,}건**"
            ),
            inline=False,
        )
        embed.set_footer(text=f"서버 생성일: {guild.created_at.strftime('%Y-%m-%d')}")
        await ctx.send(embed=embed)

    async def handle_automod(message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if not message.content or message.content.startswith("!"):
            return
        settings = get_settings(message.guild)
        automod = settings["automod"]
        if not automod.get("enabled", False):
            return
        if is_operator(message.author):
            return
        if message.channel.id in {int(value) for value in automod.get("exempt_channel_ids", [])}:
            return

        now = time.monotonic()
        reason = None
        content_norm = " ".join(message.content.lower().split())
        key = (message.guild.id, message.author.id)
        window = MESSAGE_WINDOWS[key]
        window.append((now, content_norm))

        invite_exempt = {int(value) for value in automod.get("invite_exempt_channel_ids", [])}
        if (
            automod.get("invites", False)
            and message.channel.id not in invite_exempt
            and INVITE_RE.search(message.content)
        ):
            reason = "외부 Discord 초대 링크"

        if reason is None and automod.get("bad_words", False):
            for word in automod.get("bad_word_list", []):
                if word and str(word).lower() in content_norm:
                    reason = "서버 금칙어 사용"
                    break

        if reason is None and automod.get("mention_spam", True):
            mention_count = len({member.id for member in message.mentions}) + len({role.id for role in message.role_mentions})
            if message.mention_everyone or mention_count >= int(automod.get("mention_limit", 5)):
                reason = f"멘션 도배 ({mention_count}개)"

        if reason is None and automod.get("spam", True):
            spam_seconds = max(2, int(automod.get("spam_seconds", 8)))
            spam_count = max(3, int(automod.get("spam_count", 6)))
            recent = [(stamp, text) for stamp, text in window if now - stamp <= spam_seconds]
            duplicate_count = sum(1 for stamp, text in window if now - stamp <= 20 and text == content_norm and text)
            if len(recent) >= spam_count:
                reason = f"도배 ({spam_seconds}초 동안 {len(recent)}개)"
            elif duplicate_count >= 4:
                reason = "같은 내용 반복 도배"

        if reason is None:
            return

        action_mode = str(automod.get("action_mode", "삭제")).strip()
        if action_mode not in {"알림", "삭제", "타임아웃"}:
            action_mode = "삭제"

        deleted = False
        if action_mode in {"삭제", "타임아웃"}:
            AUTOMOD_DELETED_MESSAGE_IDS.add(message.id)
            try:
                await message.delete()
                deleted = True
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                AUTOMOD_DELETED_MESSAGE_IDS.discard(message.id)

        settings["stats"]["automod_hits"] = int(settings["stats"].get("automod_hits", 0)) + 1
        strikes = AUTOMOD_STRIKES[key]
        strike_window = max(60, int(automod.get("strike_window", 600)))
        while strikes and now - strikes[0] > strike_window:
            strikes.popleft()
        strikes.append(now)
        strike_limit = max(2, int(automod.get("strike_limit", 3)))
        timed_out = False
        timeout_minutes = max(1, min(40320, int(automod.get("timeout_minutes", 10))))
        should_timeout = action_mode == "타임아웃" or (
            action_mode == "삭제" and automod.get("auto_timeout", False)
        )
        if should_timeout and len(strikes) >= strike_limit:
            if message.guild.me and message.guild.me.guild_permissions.moderate_members:
                allowed, _ = can_act_on(message.guild.me, message.author, message.guild.me)
                if allowed:
                    try:
                        await message.author.timeout(
                            discord.utils.utcnow() + timedelta(minutes=timeout_minutes),
                            reason=f"ABADDON 자동 관리: {reason}",
                        )
                        timed_out = True
                        add_case(
                            message.guild,
                            "timeout",
                            message.author.id,
                            bot.user.id if bot.user else 0,
                            f"자동 관리 반복 위반: {reason}",
                            duration_seconds=timeout_minutes * 60,
                            source="automod",
                        )
                        settings["stats"]["timeouts"] = int(settings["stats"].get("timeouts", 0)) + 1
                        strikes.clear()
                    except (discord.Forbidden, discord.HTTPException):
                        pass
        save_data()

        action_text = "감지" if action_mode == "알림" else ("삭제" if deleted else "삭제 시도")
        try:
            await message.channel.send(
                f"🛡️ {message.author.mention} 자동 관리 위반이 **{action_text}** 처리됐습니다. "
                f"사유: **{reason}**"
                + (f" · 반복 위반으로 **{timeout_minutes}분 타임아웃**" if timed_out else ""),
                delete_after=6,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        await send_log(
            message.guild,
            "🤖 자동 관리 적발",
            f"멤버: {message.author.mention} (`{message.author.id}`)\n채널: {message.channel.mention}\n사유: **{reason}**",
            color=0xC0392B,
            fields=[("메시지", message.content[:1000] or "(내용 없음)", False), ("처리 모드", action_mode, True), ("타임아웃", "적용" if timed_out else "미적용", True)],
        )

    async def handle_member_join(member: discord.Member) -> None:
        # v7.2.0: 환영 메시지와 신규 역할 처리는 통합 핸들러 한 곳에서만 실행합니다.
        unified = getattr(bot, "v720_unified_member_join", None)
        if callable(unified):
            try:
                await unified(member)
            except Exception as exc:
                print(f"[통합 환영 처리 실패] guild={member.guild.id} member={member.id} {type(exc).__name__}: {exc}", flush=True)
        else:
            settings = get_settings(member.guild)
            role = member.guild.get_role(int(settings.get("autorole_id", 0))) if settings.get("autorole_id") else None
            if role is not None and not role.managed and member.guild.me is not None and role < member.guild.me.top_role:
                try:
                    await member.add_roles(role, reason="ABADDON 신규 멤버 자동 역할")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await send_log(
            member.guild,
            "📥 멤버 입장",
            f"멤버: {member.mention} (`{member.id}`)\n계정 생성: {discord.utils.format_dt(member.created_at, style='R')}",
            color=0x2ECC71,
        )

    async def handle_member_remove(member: discord.Member) -> None:
        settings = get_settings(member.guild)
        channel = resolve_channel(member.guild, settings.get("leave_channel_id", 0))
        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(
                title="📤 생존자가 기지를 떠났습니다",
                description=f"**{member}** (`{member.id}`) 님이 서버를 떠났습니다.",
                color=0x95A5A6,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
        await send_log(
            member.guild,
            "📤 멤버 퇴장",
            f"멤버: **{member}** (`{member.id}`)",
            color=0x95A5A6,
        )

    async def handle_message_delete(message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if message.id in AUTOMOD_DELETED_MESSAGE_IDS:
            AUTOMOD_DELETED_MESSAGE_IDS.discard(message.id)
            return
        content = message.content[:1500] or "(내용 없음 또는 임베드/첨부 메시지)"
        attachments = "\n".join(item.url for item in message.attachments[:5])
        fields = [("삭제된 내용", content, False)]
        if attachments:
            fields.append(("첨부 파일", attachments, False))
        await send_log(
            message.guild,
            "🗑️ 메시지 삭제",
            f"작성자: {message.author.mention} (`{message.author.id}`)\n채널: {message.channel.mention}",
            color=0xE67E22,
            fields=fields,
        )

    async def handle_message_edit(before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        await send_log(
            before.guild,
            "✏️ 메시지 수정",
            f"작성자: {before.author.mention} (`{before.author.id}`)\n채널: {before.channel.mention}\n[원문으로 이동]({after.jump_url})",
            color=0x3498DB,
            fields=[("수정 전", before.content[:1000] or "(없음)", False), ("수정 후", after.content[:1000] or "(없음)", False)],
        )

    async def handle_member_update(before: discord.Member, after: discord.Member) -> None:
        if before.nick != after.nick:
            await send_log(
                after.guild,
                "🪪 닉네임 변경",
                f"멤버: {after.mention} (`{after.id}`)",
                color=0x3498DB,
                fields=[("변경 전", before.nick or before.name, True), ("변경 후", after.nick or after.name, True)],
            )
        before_ids = {role.id for role in before.roles}
        after_ids = {role.id for role in after.roles}
        added = [role.mention for role in after.roles if role.id not in before_ids]
        removed = [role.mention for role in before.roles if role.id not in after_ids]
        if added or removed:
            fields = []
            if added:
                fields.append(("지급 역할", ", ".join(added), False))
            if removed:
                fields.append(("회수 역할", ", ".join(removed), False))
            await send_log(
                after.guild,
                "🎭 멤버 역할 변경",
                f"멤버: {after.mention} (`{after.id}`)",
                color=0x9B59B6,
                fields=fields,
            )

    async def handle_channel_create(channel: discord.abc.GuildChannel) -> None:
        await send_log(
            channel.guild,
            "➕ 채널 생성",
            f"채널: **{channel.name}** (`{channel.id}`)\n종류: **{channel.type}**",
            color=0x2ECC71,
        )

    async def handle_channel_delete(channel: discord.abc.GuildChannel) -> None:
        settings = get_settings(channel.guild)
        if int(settings.get("log_channel_id", 0) or 0) == channel.id:
            settings["log_channel_id"] = 0
        if int(settings.get("welcome_channel_id", 0) or 0) == channel.id:
            settings["welcome_channel_id"] = 0
        for key in ("welcome_notice_channel_id", "welcome_rules_channel_id", "welcome_register_channel_id"):
            if int(settings.get(key, 0) or 0) == channel.id:
                settings[key] = 0
        if int(settings.get("leave_channel_id", 0) or 0) == channel.id:
            settings["leave_channel_id"] = 0
        for uid, cid in list(settings.get("open_tickets", {}).items()):
            if str(cid) == str(channel.id):
                settings["open_tickets"].pop(uid, None)
        save_data()
        await send_log(
            channel.guild,
            "➖ 채널 삭제",
            f"채널: **{channel.name}** (`{channel.id}`)\n종류: **{channel.type}**",
            color=0xC0392B,
        )

    async def handle_member_ban(guild: discord.Guild, user: discord.User) -> None:
        await send_log(
            guild,
            "🔨 차단 이벤트",
            f"유저: **{user}** (`{user.id}`)",
            color=0xC0392B,
        )

    async def handle_member_unban(guild: discord.Guild, user: discord.User) -> None:
        await send_log(
            guild,
            "✅ 차단 해제 이벤트",
            f"유저: **{user}** (`{user.id}`)",
            color=0x2ECC71,
        )

    bot.add_listener(handle_automod, "on_message")
    bot.add_listener(handle_member_join, "on_member_join")
    bot.add_listener(handle_member_remove, "on_member_remove")
    bot.add_listener(handle_message_delete, "on_message_delete")
    bot.add_listener(handle_message_edit, "on_message_edit")
    bot.add_listener(handle_member_update, "on_member_update")
    bot.add_listener(handle_channel_create, "on_guild_channel_create")
    bot.add_listener(handle_channel_delete, "on_guild_channel_delete")
    bot.add_listener(handle_member_ban, "on_member_ban")
    bot.add_listener(handle_member_unban, "on_member_unban")

    bot._abaddon_v410_management_registered = True
    print("[V4.1 SERVER GUARD] 서버 관리 기능 등록 완료", flush=True)
