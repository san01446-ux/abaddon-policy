from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

import discord
from discord.ext import commands


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
KEYCAPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
JOIN_WINDOWS: Dict[int, Deque[float]] = defaultdict(lambda: deque(maxlen=100))
STICKY_COUNTERS: Dict[Tuple[int, int], int] = defaultdict(int)

REACTION_PRESETS: Dict[str, List[str]] = {
    "공지": ["📢", "🔥", "✅"],
    "건의": ["👍", "👎", "💬"],
    "버그": ["🐛", "🔍", "✅"],
    "미디어": ["❤️", "🔥", "👀"],
    "이벤트": ["🎉", "🔥", "✅"],
    "거래": ["💰", "👀", "✅"],
    "투표": ["👍", "👎"],
    "일반": ["❤️", "😂", "🔥"],
    "질문": ["❓", "💡", "✅"],
    "창작": ["🎨", "❤️", "🔥"],
    "모집": ["🙋", "✅", "👀"],
    "인증": ["✅", "🛡️", "🎉"],
}

AUTO_CHANNEL_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("공지", ("공지", "업데이트", "패치", "알림")),
    ("건의", ("건의", "아이디어", "제안")),
    ("버그", ("버그", "오류", "신고", "제보")),
    ("미디어", ("스크린샷", "사진", "미디어", "자랑", "영상")),
    ("이벤트", ("이벤트", "행사")),
    ("거래", ("거래", "장터", "거래소", "암시장")),
    ("투표", ("투표", "설문")),
    ("질문", ("질문", "도움", "문의", "qna", "q-and-a")),
    ("창작", ("창작", "그림", "팬아트", "작품")),
    ("모집", ("모집", "파티", "길드원", "구인")),
    ("인증", ("인증", "출석체크", "가입확인")),
)

DEFAULT_KEYWORD_RULES = [
    {"keyword": "안녕", "emojis": ["👋"]},
    {"keyword": "축하", "emojis": ["🎉"]},
    {"keyword": "고마워", "emojis": ["❤️"]},
    {"keyword": "감사", "emojis": ["❤️"]},
    {"keyword": "ㅋㅋ", "emojis": ["😂"]},
    {"keyword": "버그", "emojis": ["🐛"]},
]

LOCK_FIELDS = (
    "send_messages",
    "add_reactions",
    "create_public_threads",
    "create_private_threads",
    "send_messages_in_threads",
)


def register_v411_server_guard_plus(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    """ABADDON V4.2 automatic reactions and expanded server administration."""

    if getattr(bot, "_abaddon_v411_guard_plus_registered", False):
        return

    management_root = world_data.setdefault("server_management", {})

    def guild_key(guild_or_id: Any) -> str:
        return str(getattr(guild_or_id, "id", guild_or_id))

    def get_settings(guild_or_id: Any) -> Dict[str, Any]:
        settings = management_root.setdefault(guild_key(guild_or_id), {})
        settings.setdefault("log_channel_id", 0)
        log_channels = settings.setdefault("log_channels", {})
        log_channels.setdefault("security", 0)
        log_channels.setdefault("message", 0)
        log_channels.setdefault("member", 0)
        log_channels.setdefault("operation", 0)
        settings.setdefault("mod_role_ids", [])
        settings.setdefault("cases", [])
        settings.setdefault("next_case_id", 1)
        settings.setdefault("stats", {})
        settings["stats"].setdefault("softbans", 0)
        settings["stats"].setdefault("quarantines", 0)
        settings["stats"].setdefault("raid_triggers", 0)
        settings["stats"].setdefault("reaction_messages", 0)
        settings["stats"].setdefault("purged_messages", 0)

        reactions = settings.setdefault("auto_reactions", {})
        reactions.setdefault("enabled", False)
        reactions.setdefault("channels", {})
        reactions.setdefault("keyword_rules", [])
        reactions.setdefault("max_per_message", 5)
        reactions.setdefault("react_to_webhooks", False)
        reactions.setdefault("smart_attachments", False)
        reactions.setdefault("custom_presets", {})
        if not isinstance(reactions.get("channels"), dict):
            reactions["channels"] = {}
        if not isinstance(reactions.get("keyword_rules"), list):
            reactions["keyword_rules"] = []
        if not isinstance(reactions.get("custom_presets"), dict):
            reactions["custom_presets"] = {}

        anti_raid = settings.setdefault("anti_raid", {})
        anti_raid.setdefault("enabled", False)
        anti_raid.setdefault("join_limit", 6)
        anti_raid.setdefault("join_window_seconds", 25)
        anti_raid.setdefault("min_account_age_days", 3)
        anti_raid.setdefault("quarantine_role_id", 0)
        anti_raid.setdefault("auto_lockdown", False)
        anti_raid.setdefault("raid_active", False)
        anti_raid.setdefault("raid_started_at", "")

        settings.setdefault("server_locks", {})
        emergency = settings.setdefault("emergency", {})
        emergency.setdefault("active", False)
        emergency.setdefault("previous_verification_level", None)

        sticky = settings.setdefault("sticky_messages", {})
        # channel id -> {content, message_id, every}
        return settings

    def parse_toggle(value: str) -> Optional[bool]:
        normalized = value.strip().lower()
        if normalized in {"켜기", "켜", "on", "true", "1", "활성화"}:
            return True
        if normalized in {"끄기", "꺼", "off", "false", "0", "비활성화"}:
            return False
        return None

    def operator_role_ids(settings: Dict[str, Any]) -> set[int]:
        result: set[int] = set()
        for value in settings.get("mod_role_ids", []):
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                pass
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

    def classify_log_type(title: str) -> str:
        if any(token in title for token in ("격리", "소프트밴", "서버 잠금", "비상", "레이드")):
            return "security"
        return "operation"

    def resolve_log_channel(
        guild: discord.Guild,
        log_type: str = "security",
    ) -> Optional[discord.TextChannel]:
        settings = get_settings(guild)
        try:
            split_id = int(settings.get("log_channels", {}).get(log_type, 0) or 0)
        except (TypeError, ValueError):
            split_id = 0
        split_channel = guild.get_channel(split_id)
        if isinstance(split_channel, discord.TextChannel):
            return split_channel
        try:
            configured_id = int(settings.get("log_channel_id", 0))
        except (TypeError, ValueError):
            configured_id = 0
        channel = guild.get_channel(configured_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        fallback_names = (
            ("🚨・보안-알림", "📋・관리자-로그", "🚨・신고접수")
            if log_type == "security"
            else ("🔧・운영-로그", "📋・관리자-로그", "🤖・봇-로그")
        )
        for name in fallback_names:
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
    ) -> None:
        channel = resolve_log_channel(guild, classify_log_type(title))
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
        embed.set_footer(text=f"서버 ID: {guild.id}")
        try:
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
            "duration_seconds": 0,
            "source": source,
            "created_at": discord.utils.utcnow().isoformat(),
            "active": True,
        }
        settings.setdefault("cases", []).append(case)
        if len(settings["cases"]) > 5000:
            del settings["cases"][:-5000]
        return case

    def can_act_on(actor: discord.Member, target: discord.Member) -> Tuple[bool, str]:
        guild = actor.guild
        if target.id == actor.id:
            return False, "자기 자신에게 사용할 수 없습니다."
        if target.id == guild.owner_id:
            return False, "서버 소유자에게 사용할 수 없습니다."
        if actor.id != guild.owner_id and target.top_role >= actor.top_role:
            return False, "대상 역할이 실행자의 최고 역할보다 같거나 높습니다."
        bot_member = guild.me
        if bot_member is None:
            return False, "아바돈 서버 멤버 정보를 불러오지 못했습니다."
        if target.top_role >= bot_member.top_role:
            return False, "아바돈 역할을 대상 역할보다 위로 올려주세요."
        return True, ""

    async def apply_reactions(message: discord.Message, emojis: Iterable[str]) -> int:
        added = 0
        seen: set[str] = set()
        settings = get_settings(message.guild) if message.guild else {}
        maximum = max(1, min(10, int(settings.get("auto_reactions", {}).get("max_per_message", 5))))
        for raw_emoji in emojis:
            emoji = str(raw_emoji).strip()
            if not emoji or emoji in seen:
                continue
            seen.add(emoji)
            try:
                await message.add_reaction(emoji)
                added += 1
            except (discord.Forbidden, discord.NotFound, discord.HTTPException, TypeError):
                continue
            if added >= maximum:
                break
        return added

    def channel_preset_for_name(channel_name: str) -> Optional[str]:
        lowered = channel_name.lower()
        for preset, keywords in AUTO_CHANNEL_KEYWORDS:
            if any(keyword in lowered for keyword in keywords):
                return preset
        return None

    def available_reaction_presets(settings: Dict[str, Any]) -> Dict[str, List[str]]:
        presets = {name: list(emojis) for name, emojis in REACTION_PRESETS.items()}
        custom = settings.get("auto_reactions", {}).get("custom_presets", {})
        if isinstance(custom, dict):
            for name, emojis in custom.items():
                clean_name = str(name).strip()[:30]
                if not clean_name or not isinstance(emojis, list):
                    continue
                cleaned = [str(item).strip() for item in emojis if str(item).strip()][:10]
                if cleaned:
                    presets[clean_name] = cleaned
        return presets

    def smart_attachment_emojis(message: discord.Message) -> List[str]:
        if not message.attachments:
            return []
        result: List[str] = []
        for attachment in message.attachments[:5]:
            content_type = (attachment.content_type or "").lower()
            filename = attachment.filename.lower()
            if content_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                result.extend(["📸", "❤️", "👀"])
            elif content_type.startswith("video/") or filename.endswith((".mp4", ".mov", ".webm", ".mkv")):
                result.extend(["🎬", "🔥", "👀"])
            elif content_type.startswith("audio/") or filename.endswith((".mp3", ".wav", ".ogg", ".m4a")):
                result.extend(["🎵", "🎧", "🔥"])
            else:
                result.extend(["📎", "✅", "👀"])
        return result

    async def auto_configure_reaction_channels(guild: discord.Guild) -> Dict[str, str]:
        settings = get_settings(guild)
        mappings = settings["auto_reactions"].setdefault("channels", {})
        configured: Dict[str, str] = {}
        for channel in guild.text_channels:
            preset = channel_preset_for_name(channel.name)
            if preset:
                mappings[str(channel.id)] = preset
                configured[channel.name] = preset
        return configured

    async def create_quarantine_role(guild: discord.Guild) -> Optional[discord.Role]:
        settings = get_settings(guild)
        anti_raid = settings["anti_raid"]
        try:
            role_id = int(anti_raid.get("quarantine_role_id", 0))
        except (TypeError, ValueError):
            role_id = 0
        role = guild.get_role(role_id)
        if role is None:
            role = discord.utils.get(guild.roles, name="🔒 격리")
        if role is None:
            try:
                role = await guild.create_role(
                    name="🔒 격리",
                    color=discord.Color.dark_grey(),
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=False,
                    reason="ABADDON SERVER GUARD 격리 역할 생성",
                )
            except (discord.Forbidden, discord.HTTPException):
                return None
        anti_raid["quarantine_role_id"] = role.id

        for channel in guild.channels:
            try:
                if isinstance(channel, discord.TextChannel):
                    allow_report = any(word in channel.name for word in ("신고", "문의", "인증"))
                    overwrite = channel.overwrites_for(role)
                    overwrite.view_channel = True
                    overwrite.send_messages = True if allow_report else False
                    overwrite.add_reactions = False
                    overwrite.create_public_threads = False
                    overwrite.create_private_threads = False
                    overwrite.send_messages_in_threads = False
                    await channel.set_permissions(role, overwrite=overwrite, reason="ABADDON 격리 권한 설정")
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    overwrite = channel.overwrites_for(role)
                    overwrite.connect = False
                    overwrite.speak = False
                    await channel.set_permissions(role, overwrite=overwrite, reason="ABADDON 격리 권한 설정")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                continue
        save_data()
        return role

    async def quarantine_member(
        member: discord.Member,
        *,
        reason: str,
        moderator_id: int,
        source: str,
    ) -> bool:
        role = await create_quarantine_role(member.guild)
        if role is None or member.guild.me is None or role >= member.guild.me.top_role:
            return False
        try:
            await member.add_roles(role, reason=reason)
        except (discord.Forbidden, discord.HTTPException):
            return False
        settings = get_settings(member.guild)
        settings["stats"]["quarantines"] = int(settings["stats"].get("quarantines", 0)) + 1
        case = add_case(member.guild, "quarantine", member.id, moderator_id, reason, source=source)
        save_data()
        await send_log(
            member.guild,
            "🔒 멤버 격리",
            f"대상: {member.mention} (`{member.id}`)\n사유: **{reason}**\n사건 번호: `#{case['id']}`",
            color=0xE67E22,
        )
        return True

    def snapshot_overwrite(overwrite: discord.PermissionOverwrite) -> Dict[str, Optional[bool]]:
        return {field: getattr(overwrite, field) for field in LOCK_FIELDS}

    def restore_snapshot(overwrite: discord.PermissionOverwrite, snapshot: Dict[str, Any]) -> None:
        for field in LOCK_FIELDS:
            value = snapshot.get(field)
            if value not in (True, False, None):
                value = None
            setattr(overwrite, field, value)

    async def lock_server(guild: discord.Guild, *, reason: str) -> Tuple[int, int]:
        settings = get_settings(guild)
        locks = settings.setdefault("server_locks", {})
        success = 0
        failed = 0
        for channel in guild.text_channels:
            if str(channel.id) not in locks:
                locks[str(channel.id)] = snapshot_overwrite(channel.overwrites_for(guild.default_role))
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.send_messages = False
            overwrite.add_reactions = False
            overwrite.create_public_threads = False
            overwrite.create_private_threads = False
            overwrite.send_messages_in_threads = False
            try:
                await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=reason)
                success += 1
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                failed += 1
        save_data()
        return success, failed

    async def unlock_server(guild: discord.Guild, *, reason: str) -> Tuple[int, int]:
        settings = get_settings(guild)
        locks = settings.setdefault("server_locks", {})
        success = 0
        failed = 0
        for channel_id, snapshot in list(locks.items()):
            try:
                channel = guild.get_channel(int(channel_id))
            except (TypeError, ValueError):
                channel = None
            if not isinstance(channel, discord.TextChannel):
                locks.pop(channel_id, None)
                continue
            overwrite = channel.overwrites_for(guild.default_role)
            restore_snapshot(overwrite, snapshot if isinstance(snapshot, dict) else {})
            try:
                await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=reason)
                success += 1
                locks.pop(channel_id, None)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                failed += 1
        save_data()
        return success, failed

    def verification_level_from_value(value: Any) -> discord.VerificationLevel:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            integer = 0
        for level in discord.VerificationLevel:
            if level.value == integer:
                return level
        return discord.VerificationLevel.low

    # ------------------------------------------------------------------
    # Help and initial setup
    # ------------------------------------------------------------------

    @bot.command(name="관리확장도움말", aliases=["운영강화도움말"], help="자동 이모지 및 확장 관리 명령어를 확인합니다.")
    async def guard_plus_help(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        embed = discord.Embed(
            title="🛡️ ABADDON SERVER GUARD PLUS",
            description="자동 반응부터 안티레이드·비상 잠금까지 확장된 서버 관리 도구입니다.",
            color=0x7D3C98,
        )
        embed.add_field(
            name="✨ 자동 이모지",
            value=(
                "`!자동이모지 ON/OFF/상태`\n"
                "`!이모지자동설정` · `!이모지채널추가 모드 #채널`\n"
                "`!이모지채널삭제 #채널` · `!이모지채널목록`\n"
                "`!이모지규칙추가 키워드 | 😀 🔥`\n"
                "`!이모지규칙삭제 번호` · `!이모지규칙목록`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🚨 안티레이드·격리",
            value=(
                "`!안티레이드 ON/OFF/상태`\n"
                "`!레이드설정 가입수 감지초 계정최소일`\n"
                "`!레이드자동잠금 ON/OFF` · `!레이드해제`\n"
                "`!격리역할생성` · `!격리 @멤버 사유` · `!격리해제 @멤버`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔨 확장 제재·청소",
            value=(
                "`!소프트밴 @멤버 사유` · `!사건조회 번호` · `!사건목록 [@멤버]`\n"
                "`!청소유저 @멤버 개수` · `!청소봇 개수`\n"
                "`!청소링크 개수` · `!청소첨부 개수` · `!멤버정보 @멤버`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔐 서버 운영",
            value=(
                "`!서버잠금 [사유]` · `!서버해제`\n"
                "`!비상모드 ON/OFF` · `!서버점검`\n"
                "`!공지전송 #채널 제목 | 내용` · `!투표 질문 | 선택지...`\n"
                "`!고정메시지 설정 내용` · `!고정메시지 해제` · `!고정간격 숫자`\n"
                "`!채널복제 [이름]` · `!역할복제 @역할 [이름]`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧰 운영 도구 센터",
            value=(
                "`!운영대시보드` · `!봇권한` · `!운영설정내보내기`\n"
                "`!운영메모 내용` · `!채널정보` · `!역할정보 @역할`\n"
                "`!대화금지 @멤버 사유` · `!대화허용 @멤버` · `!투표종료 메시지id`\n"
                "전체 목록: `!운영도구도움말`"
            ),
            inline=False,
        )
        embed.set_footer(text="봇에 관리자 권한이 있어도 아바돈 역할은 관리 대상 역할보다 위에 있어야 합니다.")
        await ctx.send(embed=embed)

    @bot.command(name="운영강화설정", aliases=["관리확장초기설정"], help="자동 이모지 채널과 격리 역할을 자동 준비합니다.")
    async def guard_plus_setup(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        reactions = settings["auto_reactions"]
        reactions["enabled"] = True
        reactions["smart_attachments"] = True
        if not reactions.get("keyword_rules"):
            reactions["keyword_rules"] = [dict(rule) for rule in DEFAULT_KEYWORD_RULES]
        configured = await auto_configure_reaction_channels(ctx.guild)
        role = await create_quarantine_role(ctx.guild)
        save_data()
        lines = [
            "✅ 자동 이모지 **활성화**",
            "✅ 사진·영상·음성·파일 스마트 반응 **활성화**",
            f"✅ 자동 감지 채널 **{len(configured)}개**",
        ]
        lines.append(f"✅ 격리 역할: {role.mention}" if role else "⚠️ 격리 역할 생성 실패")
        if configured:
            preview = "\n".join(f"• `{name}` → **{preset}**" for name, preset in list(configured.items())[:12])
            lines.append("\n**자동 연결 결과**\n" + preview)
        await ctx.send(embed=discord.Embed(title="🛡️ 운영 강화 설정 완료", description="\n".join(lines), color=0x2ECC71))

    # ------------------------------------------------------------------
    # Automatic reactions
    # ------------------------------------------------------------------

    @bot.command(name="자동이모지", help="자동 이모지 반응 기능을 켜거나 끕니다.")
    async def auto_reaction_toggle(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await require_manager(ctx):
            return
        settings = get_settings(ctx.guild)
        reactions = settings["auto_reactions"]
        if 상태.strip().lower() in {"상태", "status"}:
            await ctx.send(
                f"✨ 자동 이모지: **{'켜짐' if reactions.get('enabled') else '꺼짐'}**\n"
                f"채널 규칙 **{len(reactions.get('channels', {}))}개** · 키워드 규칙 **{len(reactions.get('keyword_rules', []))}개**"
            )
            return
        value = parse_toggle(상태)
        if value is None:
            await ctx.send("❌ `!자동이모지 켜기` 또는 `!자동이모지 끄기`로 입력하세요.")
            return
        reactions["enabled"] = value
        save_data()
        await ctx.send(f"✨ 자동 이모지를 **{'켰습니다' if value else '껐습니다'}**.")

    @bot.command(name="이모지자동설정", help="채널 이름을 보고 적절한 자동 반응 모드를 연결합니다.")
    async def auto_reaction_scan(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        configured = await auto_configure_reaction_channels(ctx.guild)
        save_data()
        if not configured:
            await ctx.send("ℹ️ 자동으로 연결할 수 있는 채널 이름을 찾지 못했습니다.")
            return
        text = "\n".join(f"• {discord.utils.escape_markdown(name)} → **{preset}**" for name, preset in configured.items())
        await ctx.send(embed=discord.Embed(title="✨ 이모지 채널 자동 설정", description=text[:4000], color=0x9B59B6))

    @bot.command(name="이모지채널추가", help="특정 채널에 자동 반응 프리셋을 연결합니다.")
    async def add_reaction_channel(
        ctx: commands.Context,
        모드: str,
        채널: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await require_manager(ctx):
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("❌ 텍스트 채널을 지정해주세요.")
            return
        settings = get_settings(ctx.guild)
        normalized = 모드.strip()[:30]
        presets = available_reaction_presets(settings)
        if normalized not in presets:
            await ctx.send("❌ 존재하지 않는 모드입니다. `!이모지프리셋목록`으로 사용할 수 있는 프리셋을 확인하세요.")
            return
        settings["auto_reactions"]["channels"][str(target.id)] = normalized
        save_data()
        await ctx.send(f"✅ {target.mention}에 **{normalized}** 반응 {''.join(presets[normalized])}을 연결했습니다.")

    @bot.command(name="이모지채널삭제", help="채널의 자동 이모지 규칙을 제거합니다.")
    async def remove_reaction_channel(
        ctx: commands.Context,
        채널: Optional[discord.TextChannel] = None,
    ) -> None:
        if not await require_manager(ctx):
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("❌ 텍스트 채널을 지정해주세요.")
            return
        mappings = get_settings(ctx.guild)["auto_reactions"]["channels"]
        removed = mappings.pop(str(target.id), None)
        save_data()
        await ctx.send(f"✅ {target.mention} 자동 반응을 제거했습니다." if removed else "ℹ️ 해당 채널에는 자동 반응이 설정되어 있지 않습니다.")

    @bot.command(name="이모지채널목록", help="자동 반응이 연결된 채널 목록을 확인합니다.")
    async def list_reaction_channels(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        settings = get_settings(ctx.guild)
        mappings = settings["auto_reactions"].get("channels", {})
        presets = available_reaction_presets(settings)
        lines = []
        for channel_id, preset in mappings.items():
            try:
                channel = ctx.guild.get_channel(int(channel_id))
            except (TypeError, ValueError):
                channel = None
            label = channel.mention if isinstance(channel, discord.TextChannel) else f"삭제된 채널 `{channel_id}`"
            lines.append(f"• {label} → **{preset}** {''.join(presets.get(str(preset), []))}")
        await ctx.send(embed=discord.Embed(title="✨ 자동 이모지 채널", description="\n".join(lines)[:4000] if lines else "설정된 채널이 없습니다.", color=0x9B59B6))

    @bot.command(name="이모지규칙추가", help="키워드가 포함된 메시지에 자동 반응할 이모지를 추가합니다.")
    async def add_keyword_reaction(ctx: commands.Context, *, 규칙: str) -> None:
        if not await require_manager(ctx):
            return
        if "|" not in 규칙:
            await ctx.send("❌ 예시: `!이모지규칙추가 축하 | 🎉 🔥`")
            return
        keyword, emoji_text = (part.strip() for part in 규칙.split("|", 1))
        emojis = [item.strip() for item in re.split(r"[\s,]+", emoji_text) if item.strip()][:5]
        if not keyword or not emojis:
            await ctx.send("❌ 키워드와 이모지를 모두 입력해주세요.")
            return
        rules = get_settings(ctx.guild)["auto_reactions"].setdefault("keyword_rules", [])
        rules.append({"keyword": keyword[:100], "emojis": emojis})
        if len(rules) > 100:
            del rules[:-100]
        save_data()
        await ctx.send(f"✅ **{keyword}** → {' '.join(emojis)} 규칙을 추가했습니다.")

    @bot.command(name="이모지규칙삭제", help="번호로 키워드 자동 반응 규칙을 삭제합니다.")
    async def remove_keyword_reaction(ctx: commands.Context, 번호: int) -> None:
        if not await require_manager(ctx):
            return
        rules = get_settings(ctx.guild)["auto_reactions"].setdefault("keyword_rules", [])
        if 번호 < 1 or 번호 > len(rules):
            await ctx.send("❌ 존재하지 않는 규칙 번호입니다.")
            return
        removed = rules.pop(번호 - 1)
        save_data()
        await ctx.send(f"✅ **{removed.get('keyword', '?')}** 규칙을 삭제했습니다.")

    @bot.command(name="이모지규칙목록", help="키워드 자동 반응 규칙을 확인합니다.")
    async def list_keyword_reactions(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        rules = get_settings(ctx.guild)["auto_reactions"].get("keyword_rules", [])
        lines = [f"`{index}.` **{rule.get('keyword', '?')}** → {' '.join(map(str, rule.get('emojis', [])))}" for index, rule in enumerate(rules, 1)]
        await ctx.send(embed=discord.Embed(title="🔑 키워드 이모지 규칙", description="\n".join(lines)[:4000] if lines else "등록된 규칙이 없습니다.", color=0x9B59B6))

    @bot.command(name="이모지프리셋목록", help="기본 및 사용자 자동 반응 프리셋을 확인합니다.")
    async def list_reaction_presets(ctx: commands.Context) -> None:
        if not await require_operator(ctx):
            return
        settings = get_settings(ctx.guild)
        presets = available_reaction_presets(settings)
        custom_names = set(settings["auto_reactions"].get("custom_presets", {}).keys())
        lines = [
            f"• **{name}** {'(사용자)' if name in custom_names else '(기본)'} → {' '.join(emojis)}"
            for name, emojis in presets.items()
        ]
        await ctx.send(embed=discord.Embed(
            title="✨ 자동 이모지 프리셋",
            description="\n".join(lines)[:4000],
            color=0x9B59B6,
        ))

    @bot.command(name="이모지프리셋추가", help="사용자 자동 반응 프리셋을 추가하거나 갱신합니다.")
    async def add_reaction_preset(ctx: commands.Context, *, 설정: str) -> None:
        if not await require_manager(ctx):
            return
        if "|" not in 설정:
            await ctx.send("❌ 예시: `!이모지프리셋추가 응원 | 🔥 💪 ❤️`")
            return
        name, emoji_text = (part.strip() for part in 설정.split("|", 1))
        name = name[:30]
        emojis = [item.strip() for item in re.split(r"[\s,]+", emoji_text) if item.strip()][:10]
        if not name or not emojis:
            await ctx.send("❌ 프리셋 이름과 이모지를 모두 입력해주세요.")
            return
        if name in REACTION_PRESETS:
            await ctx.send("❌ 기본 프리셋 이름은 덮어쓸 수 없습니다. 다른 이름을 사용해주세요.")
            return
        settings = get_settings(ctx.guild)
        custom = settings["auto_reactions"].setdefault("custom_presets", {})
        if name not in custom and len(custom) >= 30:
            await ctx.send("❌ 사용자 프리셋은 서버당 최대 30개까지 만들 수 있습니다.")
            return
        custom[name] = emojis
        save_data()
        await ctx.send(f"✅ 사용자 프리셋 **{name}** → {' '.join(emojis)}를 저장했습니다.")

    @bot.command(name="이모지프리셋삭제", help="사용자 자동 반응 프리셋을 삭제합니다.")
    async def remove_reaction_preset(ctx: commands.Context, *, 이름: str) -> None:
        if not await require_manager(ctx):
            return
        name = 이름.strip()[:30]
        settings = get_settings(ctx.guild)
        custom = settings["auto_reactions"].setdefault("custom_presets", {})
        if name not in custom:
            await ctx.send("❌ 해당 사용자 프리셋을 찾지 못했습니다.")
            return
        custom.pop(name, None)
        mappings = settings["auto_reactions"].setdefault("channels", {})
        removed_channels = [channel_id for channel_id, preset in mappings.items() if preset == name]
        for channel_id in removed_channels:
            mappings.pop(channel_id, None)
        save_data()
        await ctx.send(f"✅ **{name}** 프리셋을 삭제했습니다. 연결 해제 채널: **{len(removed_channels)}개**")

    @bot.command(name="이모지첨부반응", help="사진·영상·음성·파일 첨부 스마트 반응을 설정합니다.")
    async def attachment_reaction_toggle(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await require_manager(ctx):
            return
        reactions = get_settings(ctx.guild)["auto_reactions"]
        if 상태.strip().lower() in {"상태", "status"}:
            await ctx.send(f"📎 첨부 스마트 반응: **{'켜짐' if reactions.get('smart_attachments') else '꺼짐'}**")
            return
        value = parse_toggle(상태)
        if value is None:
            await ctx.send("❌ `!이모지첨부반응 켜기` 또는 `!이모지첨부반응 끄기`로 입력하세요.")
            return
        reactions["smart_attachments"] = value
        save_data()
        await ctx.send(f"📎 첨부 스마트 반응을 **{'켰습니다' if value else '껐습니다'}**.")

    @bot.command(name="이모지최대개수", help="메시지 하나에 자동으로 추가할 반응 개수를 설정합니다.")
    async def set_reaction_maximum(ctx: commands.Context, 개수: int) -> None:
        if not await require_manager(ctx):
            return
        if 개수 < 1 or 개수 > 10:
            await ctx.send("❌ 자동 반응 개수는 1~10 사이로 설정해주세요.")
            return
        get_settings(ctx.guild)["auto_reactions"]["max_per_message"] = 개수
        save_data()
        await ctx.send(f"✅ 메시지당 자동 반응 최대 개수를 **{개수}개**로 설정했습니다.")

    @bot.command(name="이모지웹훅", help="웹훅 메시지에도 자동 반응할지 설정합니다.")
    async def webhook_reaction_toggle(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await require_manager(ctx):
            return
        reactions = get_settings(ctx.guild)["auto_reactions"]
        if 상태.strip().lower() in {"상태", "status"}:
            await ctx.send(f"🪝 웹훅 자동 반응: **{'켜짐' if reactions.get('react_to_webhooks') else '꺼짐'}**")
            return
        value = parse_toggle(상태)
        if value is None:
            await ctx.send("❌ `!이모지웹훅 켜기` 또는 `!이모지웹훅 끄기`로 입력하세요.")
            return
        reactions["react_to_webhooks"] = value
        save_data()
        await ctx.send(f"🪝 웹훅 자동 반응을 **{'켰습니다' if value else '껐습니다'}**.")

    # ------------------------------------------------------------------
    # Anti raid and quarantine
    # ------------------------------------------------------------------

    @bot.command(name="격리역할생성", help="격리 역할과 채널 권한을 생성 또는 갱신합니다.")
    async def quarantine_role_create(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        progress = await ctx.send("🔧 격리 역할과 채널 권한을 설정하고 있습니다...")
        role = await create_quarantine_role(ctx.guild)
        if role is None:
            await progress.edit(content="❌ 격리 역할을 만들지 못했습니다. 아바돈 역할과 권한을 확인해주세요.")
            return
        await progress.edit(content=f"✅ 격리 역할 {role.mention}과 채널 권한 설정을 완료했습니다.")

    @bot.command(name="안티레이드", help="가입 폭주 및 신규 계정 격리 기능을 설정합니다.")
    async def anti_raid_toggle(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await require_manager(ctx):
            return
        anti = get_settings(ctx.guild)["anti_raid"]
        if 상태.strip().lower() in {"상태", "status"}:
            await ctx.send(
                f"🚨 안티레이드: **{'켜짐' if anti.get('enabled') else '꺼짐'}**\n"
                f"감지: **{anti.get('join_window_seconds')}초 동안 {anti.get('join_limit')}명**\n"
                f"신규 계정: **{anti.get('min_account_age_days')}일 미만 격리**\n"
                f"레이드 상태: **{'감지됨' if anti.get('raid_active') else '정상'}** · 자동 잠금: **{'켜짐' if anti.get('auto_lockdown') else '꺼짐'}**"
            )
            return
        value = parse_toggle(상태)
        if value is None:
            await ctx.send("❌ `!안티레이드 켜기` 또는 `!안티레이드 끄기`로 입력하세요.")
            return
        anti["enabled"] = value
        if not value:
            anti["raid_active"] = False
        save_data()
        await ctx.send(f"🚨 안티레이드를 **{'켰습니다' if value else '껐습니다'}**.")

    @bot.command(name="레이드설정", help="가입 폭주 기준과 최소 계정 나이를 설정합니다.")
    async def anti_raid_settings(ctx: commands.Context, 가입수: int, 감지초: int, 계정최소일: int) -> None:
        if not await require_manager(ctx):
            return
        if not (3 <= 가입수 <= 50 and 5 <= 감지초 <= 300 and 0 <= 계정최소일 <= 365):
            await ctx.send("❌ 범위: 가입수 3~50, 감지초 5~300, 계정최소일 0~365")
            return
        anti = get_settings(ctx.guild)["anti_raid"]
        anti["join_limit"] = 가입수
        anti["join_window_seconds"] = 감지초
        anti["min_account_age_days"] = 계정최소일
        save_data()
        await ctx.send(f"✅ 레이드 기준을 **{감지초}초/{가입수}명**, 신규 계정 기준을 **{계정최소일}일 미만**으로 설정했습니다.")

    @bot.command(name="레이드자동잠금", help="레이드 감지 시 서버 전체 잠금 여부를 설정합니다.")
    async def anti_raid_auto_lock(ctx: commands.Context, 상태: str) -> None:
        if not await require_manager(ctx):
            return
        value = parse_toggle(상태)
        if value is None:
            await ctx.send("❌ `!레이드자동잠금 ON/OFF`로 입력하세요.")
            return
        get_settings(ctx.guild)["anti_raid"]["auto_lockdown"] = value
        save_data()
        await ctx.send(f"🔐 레이드 자동 잠금을 **{'켰습니다' if value else '껐습니다'}**.")

    @bot.command(name="레이드해제", help="현재 레이드 감지 상태를 수동 해제합니다.")
    async def anti_raid_clear(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        anti = get_settings(ctx.guild)["anti_raid"]
        anti["raid_active"] = False
        anti["raid_started_at"] = ""
        JOIN_WINDOWS[ctx.guild.id].clear()
        save_data()
        await ctx.send("✅ 레이드 감지 상태를 해제했습니다. 서버가 잠겨 있다면 `!서버해제`를 사용하세요.")

    @bot.command(name="격리", help="멤버를 격리 역할로 제한합니다.")
    async def quarantine_command(ctx: commands.Context, 대상: discord.Member, *, 사유: str = "운영진 수동 격리") -> None:
        if not await require_operator(ctx):
            return
        allowed, reason = can_act_on(ctx.author, 대상)
        if not allowed:
            await ctx.send(f"❌ {reason}")
            return
        success = await quarantine_member(대상, reason=사유, moderator_id=ctx.author.id, source="manual")
        await ctx.send(f"🔒 {대상.mention}을 격리했습니다." if success else "❌ 격리하지 못했습니다. 역할 순서와 권한을 확인해주세요.")

    @bot.command(name="격리해제", help="멤버의 격리 역할을 제거합니다.")
    async def unquarantine_command(ctx: commands.Context, 대상: discord.Member, *, 사유: str = "격리 해제") -> None:
        if not await require_operator(ctx):
            return
        settings = get_settings(ctx.guild)
        try:
            role = ctx.guild.get_role(int(settings["anti_raid"].get("quarantine_role_id", 0)))
        except (TypeError, ValueError):
            role = None
        if role is None or role not in 대상.roles:
            await ctx.send("ℹ️ 대상에게 격리 역할이 없습니다.")
            return
        try:
            await 대상.remove_roles(role, reason=f"{사유} | {ctx.author}")
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ 격리 역할을 제거하지 못했습니다.")
            return
        case = add_case(ctx.guild, "unquarantine", 대상.id, ctx.author.id, 사유)
        save_data()
        await ctx.send(f"✅ {대상.mention}의 격리를 해제했습니다. 사건 `#{case['id']}`")
        await send_log(ctx.guild, "🔓 격리 해제", f"대상: {대상.mention}\n운영진: {ctx.author.mention}\n사유: **{사유}**", color=0x2ECC71)

    # ------------------------------------------------------------------
    # Extended moderation and cleanup
    # ------------------------------------------------------------------

    @bot.command(name="소프트밴", help="메시지를 정리한 뒤 즉시 차단 해제합니다.")
    async def softban_command(ctx: commands.Context, 대상: discord.Member, *, 사유: str = "사유 없음") -> None:
        if not await require_operator(ctx):
            return
        allowed, reason = can_act_on(ctx.author, 대상)
        if not allowed:
            await ctx.send(f"❌ {reason}")
            return
        try:
            await ctx.guild.ban(대상, reason=f"소프트밴: {사유} | {ctx.author}", delete_message_seconds=86400)
            await ctx.guild.unban(대상, reason=f"소프트밴 즉시 해제 | {ctx.author}")
        except (discord.Forbidden, discord.HTTPException) as exc:
            await ctx.send(f"❌ 소프트밴 실패: `{type(exc).__name__}`")
            return
        settings = get_settings(ctx.guild)
        settings["stats"]["softbans"] = int(settings["stats"].get("softbans", 0)) + 1
        case = add_case(ctx.guild, "softban", 대상.id, ctx.author.id, 사유)
        save_data()
        await ctx.send(f"🧹 **{대상}** 소프트밴 완료 · 사건 `#{case['id']}`")
        await send_log(ctx.guild, "🧹 소프트밴", f"대상: **{대상}** (`{대상.id}`)\n운영진: {ctx.author.mention}\n사유: **{사유}**", color=0xE67E22)

    async def filtered_purge(ctx: commands.Context, limit: int, check, label: str) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 텍스트 채널에서만 사용할 수 있습니다.")
            return
        amount = max(1, min(500, limit))
        try:
            deleted = await ctx.channel.purge(limit=amount + 1, check=check, reason=f"ABADDON {label}: {ctx.author}")
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ 메시지를 삭제하지 못했습니다.")
            return
        count = len(deleted)
        settings = get_settings(ctx.guild)
        settings["stats"]["purged_messages"] = int(settings["stats"].get("purged_messages", 0)) + count
        save_data()
        await ctx.send(f"🧹 {label} 메시지 **{count}개**를 정리했습니다.", delete_after=5)

    @bot.command(name="청소유저", help="특정 멤버의 최근 메시지만 삭제합니다.")
    async def purge_member(ctx: commands.Context, 대상: discord.Member, 개수: int = 100) -> None:
        if not await require_operator(ctx):
            return
        await filtered_purge(ctx, 개수, lambda message: message.author.id == 대상.id, f"{대상} 사용자")

    @bot.command(name="청소봇", help="최근 봇 메시지만 삭제합니다.")
    async def purge_bots(ctx: commands.Context, 개수: int = 100) -> None:
        if not await require_operator(ctx):
            return
        await filtered_purge(ctx, 개수, lambda message: message.author.bot, "봇")

    @bot.command(name="청소링크", help="최근 링크 포함 메시지만 삭제합니다.")
    async def purge_links(ctx: commands.Context, 개수: int = 100) -> None:
        if not await require_operator(ctx):
            return
        await filtered_purge(ctx, 개수, lambda message: bool(URL_RE.search(message.content or "")), "링크")

    @bot.command(name="청소첨부", help="최근 첨부 파일 메시지만 삭제합니다.")
    async def purge_attachments(ctx: commands.Context, 개수: int = 100) -> None:
        if not await require_operator(ctx):
            return
        await filtered_purge(ctx, 개수, lambda message: bool(message.attachments), "첨부 파일")

    @bot.command(name="사건조회", help="SERVER GUARD 사건 번호의 상세 기록을 확인합니다.")
    async def case_lookup(ctx: commands.Context, 번호: int) -> None:
        if not await require_operator(ctx):
            return
        case = next((item for item in get_settings(ctx.guild).get("cases", []) if int(item.get("id", 0)) == 번호), None)
        if case is None:
            await ctx.send("❌ 해당 사건 번호를 찾지 못했습니다.")
            return
        target = ctx.guild.get_member(int(case.get("target_id", 0)))
        moderator = ctx.guild.get_member(int(case.get("moderator_id", 0)))
        embed = discord.Embed(title=f"📁 사건 #{번호}", color=0x3498DB)
        embed.add_field(name="조치", value=str(case.get("action", "?")), inline=True)
        embed.add_field(name="상태", value="활성" if case.get("active", True) else "종료", inline=True)
        embed.add_field(name="출처", value=str(case.get("source", "manual")), inline=True)
        embed.add_field(name="대상", value=target.mention if target else f"`{case.get('target_id', 0)}`", inline=True)
        embed.add_field(name="운영진", value=moderator.mention if moderator else f"`{case.get('moderator_id', 0)}`", inline=True)
        embed.add_field(name="일시", value=str(case.get("created_at", "?"))[:25], inline=True)
        embed.add_field(name="사유", value=str(case.get("reason", "사유 없음"))[:1024], inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="사건목록", help="최근 사건 또는 특정 멤버의 사건 기록을 확인합니다.")
    async def case_list(ctx: commands.Context, 대상: Optional[discord.Member] = None, 개수: int = 15) -> None:
        if not await require_operator(ctx):
            return
        cases = list(get_settings(ctx.guild).get("cases", []))
        if 대상 is not None:
            cases = [item for item in cases if int(item.get("target_id", 0)) == 대상.id]
        cases = cases[-max(1, min(30, 개수)):]
        lines = []
        for case in reversed(cases):
            target_id = int(case.get("target_id", 0))
            target = ctx.guild.get_member(target_id)
            target_label = target.mention if target else f"`{target_id}`"
            lines.append(f"`#{case.get('id', '?')}` **{case.get('action', '?')}** · {target_label} · {str(case.get('reason', ''))[:60]}")
        title = f"📁 {대상} 사건 기록" if 대상 else "📁 최근 사건 기록"
        await ctx.send(embed=discord.Embed(title=title, description="\n".join(lines)[:4000] if lines else "기록이 없습니다.", color=0x3498DB))

    @bot.command(name="멤버정보", aliases=["운영유저정보"], help="멤버의 계정, 역할, 경고, 타임아웃 정보를 확인합니다.")
    async def user_info(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        if not await require_operator(ctx):
            return
        member = 대상 or ctx.author
        settings = get_settings(ctx.guild)
        warnings = settings.get("warnings", {}).get(str(member.id), [])
        active_warnings = sum(1 for warning in warnings if warning.get("active", True))
        roles = [role.mention for role in member.roles[1:] if not role.managed]
        embed = discord.Embed(title=f"👤 {member} 정보", color=member.color if member.color.value else 0x5865F2)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="계정 생성", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
        embed.add_field(name="서버 참가", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "알 수 없음", inline=True)
        embed.add_field(name="활성 경고", value=f"**{active_warnings}개**", inline=True)
        embed.add_field(name="타임아웃", value=discord.utils.format_dt(member.timed_out_until, style="R") if member.timed_out_until else "없음", inline=True)
        embed.add_field(name="최고 역할", value=member.top_role.mention, inline=True)
        embed.add_field(name=f"역할 {len(roles)}개", value=(", ".join(roles)[:1024] if roles else "없음"), inline=False)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Server locks, emergency, announcements, polls, sticky, cloning
    # ------------------------------------------------------------------

    @bot.command(name="서버잠금", help="모든 텍스트 채널의 일반 멤버 전송을 잠급니다.")
    async def server_lock_command(ctx: commands.Context, *, 사유: str = "운영진 서버 잠금") -> None:
        if not await require_manager(ctx):
            return
        progress = await ctx.send("🔐 서버 채널을 잠그고 있습니다...")
        success, failed = await lock_server(ctx.guild, reason=f"{사유} | {ctx.author}")
        try:
            await progress.edit(content=f"🔐 서버 잠금 완료: 성공 **{success}개**, 실패 **{failed}개**")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await send_log(ctx.guild, "🔐 서버 잠금", f"운영진: {ctx.author.mention}\n사유: **{사유}**\n성공 {success} · 실패 {failed}", color=0xC0392B)

    @bot.command(name="서버해제", help="서버잠금으로 변경한 채널 권한을 원래대로 복원합니다.")
    async def server_unlock_command(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        progress = await ctx.send("🔓 저장된 채널 권한을 복원하고 있습니다...")
        success, failed = await unlock_server(ctx.guild, reason=f"ABADDON 서버 잠금 해제 | {ctx.author}")
        try:
            await progress.edit(content=f"🔓 서버 잠금 해제: 성공 **{success}개**, 실패 **{failed}개**")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await send_log(ctx.guild, "🔓 서버 잠금 해제", f"운영진: {ctx.author.mention}\n성공 {success} · 실패 {failed}", color=0x2ECC71)

    @bot.command(name="비상모드", help="안티레이드, 높은 인증 수준, 서버 잠금을 한 번에 설정합니다.")
    async def emergency_mode(ctx: commands.Context, 상태: str) -> None:
        if not await require_manager(ctx):
            return
        value = parse_toggle(상태)
        if value is None:
            await ctx.send("❌ `!비상모드 켜기` 또는 `!비상모드 끄기`로 입력하세요.")
            return
        settings = get_settings(ctx.guild)
        emergency = settings["emergency"]
        anti = settings["anti_raid"]
        if value:
            if emergency.get("active"):
                await ctx.send("ℹ️ 이미 비상모드가 켜져 있습니다.")
                return
            emergency["previous_verification_level"] = ctx.guild.verification_level.value
            emergency["active"] = True
            anti["enabled"] = True
            anti["raid_active"] = True
            try:
                await ctx.guild.edit(verification_level=discord.VerificationLevel.high, reason=f"ABADDON 비상모드 | {ctx.author}")
            except (discord.Forbidden, discord.HTTPException):
                pass
            success, failed = await lock_server(ctx.guild, reason=f"ABADDON 비상모드 | {ctx.author}")
            save_data()
            await ctx.send(f"🚨 **비상모드 활성화** · 채널 잠금 성공 {success}, 실패 {failed}")
            await send_log(ctx.guild, "🚨 비상모드 활성화", f"운영진: {ctx.author.mention}", color=0xC0392B)
        else:
            anti["raid_active"] = False
            previous = verification_level_from_value(emergency.get("previous_verification_level"))
            try:
                await ctx.guild.edit(verification_level=previous, reason=f"ABADDON 비상모드 해제 | {ctx.author}")
            except (discord.Forbidden, discord.HTTPException):
                pass
            success, failed = await unlock_server(ctx.guild, reason=f"ABADDON 비상모드 해제 | {ctx.author}")
            emergency["active"] = False
            emergency["previous_verification_level"] = None
            save_data()
            await ctx.send(f"✅ **비상모드 해제** · 권한 복원 성공 {success}, 실패 {failed}")
            await send_log(ctx.guild, "✅ 비상모드 해제", f"운영진: {ctx.author.mention}", color=0x2ECC71)

    @bot.command(name="공지전송", help="지정 채널에 운영진 공지 임베드를 전송합니다.")
    async def send_announcement(ctx: commands.Context, 채널: discord.TextChannel, *, 내용: str) -> None:
        if not await require_operator(ctx):
            return
        if "|" not in 내용:
            await ctx.send("❌ 예시: `!공지전송 #공지 제목 | 공지 내용`")
            return
        title, body = (part.strip() for part in 내용.split("|", 1))
        if not title or not body:
            await ctx.send("❌ 제목과 내용을 모두 입력해주세요.")
            return
        embed = discord.Embed(title=f"📢 {title[:240]}", description=body[:4000], color=0x8E44AD, timestamp=discord.utils.utcnow())
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_footer(text=f"{ctx.guild.name} 공식 공지")
        try:
            message = await 채널.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ 해당 채널에 공지를 보낼 수 없습니다.")
            return
        await apply_reactions(message, REACTION_PRESETS["공지"])
        await ctx.send(f"✅ {채널.mention}에 공지를 전송했습니다. {message.jump_url}")
        await send_log(ctx.guild, "📢 공지 전송", f"채널: {채널.mention}\n운영진: {ctx.author.mention}\n제목: **{title}**", color=0x8E44AD)

    @bot.command(name="투표", help="현재 채널에 2~10개 선택지 투표를 만듭니다.")
    async def create_poll(ctx: commands.Context, *, 내용: str) -> None:
        if not await require_operator(ctx):
            return
        parts = [part.strip() for part in 내용.split("|") if part.strip()]
        if len(parts) < 3:
            await ctx.send("❌ 예시: `!투표 오늘 할 게임? | 배너로드 | 마인크래프트 | 롤`")
            return
        question, options = parts[0], parts[1:11]
        description = "\n".join(f"{KEYCAPS[index]} **{option[:100]}**" for index, option in enumerate(options))
        embed = discord.Embed(title=f"📊 {question[:240]}", description=description, color=0x3498DB, timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"투표 생성: {ctx.author}")
        message = await ctx.send(embed=embed)
        await apply_reactions(message, KEYCAPS[:len(options)])

    @bot.command(name="고정메시지", help="현재 채널에 자동 재게시되는 고정 안내를 설정합니다.")
    async def sticky_message(ctx: commands.Context, 동작: str = "상태", *, 내용: str = "") -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ 텍스트 채널에서만 사용할 수 있습니다.")
            return
        sticky_map = get_settings(ctx.guild).setdefault("sticky_messages", {})
        key = str(ctx.channel.id)
        action = 동작.strip().lower()
        if action in {"설정", "set"}:
            if not 내용.strip():
                await ctx.send("❌ 예시: `!고정메시지 설정 이 채널의 이용 안내입니다.`")
                return
            old = sticky_map.get(key, {})
            sticky_map[key] = {
                "content": 내용[:1800],
                "message_id": int(old.get("message_id", 0)),
                "every": max(3, min(50, int(old.get("every", 8)))),
            }
            save_data()
            await ctx.send("📌 이 채널의 고정 메시지를 설정했습니다. 이후 메시지가 쌓이면 아래로 자동 재게시됩니다.")
        elif action in {"해제", "삭제", "off"}:
            data = sticky_map.pop(key, None)
            save_data()
            if data and data.get("message_id"):
                try:
                    old_message = await ctx.channel.fetch_message(int(data["message_id"]))
                    await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                    pass
            await ctx.send("✅ 이 채널의 고정 메시지를 해제했습니다.")
        else:
            data = sticky_map.get(key)
            if not data:
                await ctx.send("📌 이 채널에는 고정 메시지가 없습니다.")
            else:
                await ctx.send(f"📌 고정 메시지 활성 · 간격 **{data.get('every', 8)}개**\n내용: {str(data.get('content', ''))[:500]}")

    @bot.command(name="고정간격", help="현재 채널 고정 메시지 재게시 간격을 설정합니다.")
    async def sticky_interval(ctx: commands.Context, 메시지수: int) -> None:
        if not await require_operator(ctx):
            return
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        if not 3 <= 메시지수 <= 50:
            await ctx.send("❌ 3~50 사이로 입력하세요.")
            return
        sticky_map = get_settings(ctx.guild).setdefault("sticky_messages", {})
        data = sticky_map.get(str(ctx.channel.id))
        if not data:
            await ctx.send("❌ 먼저 `!고정메시지 설정 내용`으로 설정해주세요.")
            return
        data["every"] = 메시지수
        save_data()
        await ctx.send(f"✅ 고정 메시지 재게시 간격을 **{메시지수}개**로 설정했습니다.")

    @bot.command(name="채널복제", help="현재 채널의 권한과 설정을 복제합니다.")
    async def clone_channel(ctx: commands.Context, *, 이름: str = "") -> None:
        if not await require_manager(ctx):
            return
        if ctx.guild is None or not hasattr(ctx.channel, "clone"):
            await ctx.send("❌ 서버 채널에서만 사용할 수 있습니다.")
            return
        try:
            cloned = await ctx.channel.clone(name=이름[:100] if 이름 else None, reason=f"ABADDON 채널 복제 | {ctx.author}")
            await cloned.edit(position=ctx.channel.position + 1, category=ctx.channel.category)
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ 채널을 복제하지 못했습니다.")
            return
        await ctx.send(f"✅ 채널을 복제했습니다: {cloned.mention if hasattr(cloned, 'mention') else cloned.name}")

    @bot.command(name="역할복제", help="역할의 이름, 색상, 권한을 복제합니다.")
    async def clone_role(ctx: commands.Context, 역할: discord.Role, *, 이름: str = "") -> None:
        if not await require_manager(ctx):
            return
        if 역할.is_default() or 역할.managed:
            await ctx.send("❌ 기본 역할 또는 봇 연동 역할은 복제할 수 없습니다.")
            return
        try:
            cloned = await ctx.guild.create_role(
                name=(이름[:100] if 이름 else f"{역할.name} 복사본"),
                permissions=역할.permissions,
                color=역할.color,
                hoist=역할.hoist,
                mentionable=역할.mentionable,
                reason=f"ABADDON 역할 복제 | {ctx.author}",
            )
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ 역할을 복제하지 못했습니다.")
            return
        await ctx.send(f"✅ 역할을 복제했습니다: {cloned.mention}")

    @bot.command(name="서버점검", help="아바돈의 권한, 역할 순서, 관리 설정을 점검합니다.")
    async def server_audit(ctx: commands.Context) -> None:
        if not await require_manager(ctx):
            return
        me = ctx.guild.me
        if me is None:
            await ctx.send("❌ 아바돈 멤버 정보를 불러오지 못했습니다.")
            return
        perms = me.guild_permissions
        checks = [
            ("관리자", perms.administrator),
            ("메시지 관리", perms.manage_messages),
            ("멤버 관리", perms.moderate_members),
            ("역할 관리", perms.manage_roles),
            ("채널 관리", perms.manage_channels),
            ("차단", perms.ban_members),
            ("추방", perms.kick_members),
            ("로그 보기", perms.view_audit_log),
            ("반응 추가", perms.add_reactions),
        ]
        settings = get_settings(ctx.guild)
        role_above = sum(1 for member in ctx.guild.members if not member.bot and member.top_role >= me.top_role)
        lines = [f"{'✅' if ok else '❌'} {name}" for name, ok in checks]
        lines.append(f"{'✅' if role_above == 0 else '⚠️'} 아바돈보다 같거나 높은 일반 멤버: **{role_above}명**")
        lines.append(f"{'✅' if resolve_log_channel(ctx.guild) else '⚠️'} 로그 채널")
        lines.append(f"{'✅' if settings['auto_reactions'].get('enabled') else 'ℹ️'} 자동 이모지")
        lines.append(f"{'✅' if settings['anti_raid'].get('enabled') else 'ℹ️'} 안티레이드")
        await ctx.send(embed=discord.Embed(title="🔎 SERVER GUARD 점검 결과", description="\n".join(lines), color=0x2ECC71 if all(ok for _, ok in checks) else 0xE67E22))

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    async def handle_auto_reactions(message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.channel, discord.TextChannel):
            return
        if message.author.bot and message.webhook_id is None:
            return
        if message.webhook_id and not get_settings(message.guild)["auto_reactions"].get("react_to_webhooks", False):
            return
        if (message.content or "").startswith("!"):
            return
        settings = get_settings(message.guild)
        reactions = settings["auto_reactions"]
        if not reactions.get("enabled", False):
            return
        emojis: List[str] = []
        presets = available_reaction_presets(settings)
        preset = reactions.get("channels", {}).get(str(message.channel.id))
        if preset in presets:
            emojis.extend(presets[preset])
        if reactions.get("smart_attachments", False):
            emojis.extend(smart_attachment_emojis(message))
        normalized = (message.content or "").lower()
        for rule in reactions.get("keyword_rules", []):
            keyword = str(rule.get("keyword", "")).lower().strip()
            if keyword and keyword in normalized:
                emojis.extend(str(item) for item in rule.get("emojis", []))
        if not emojis:
            return
        added = await apply_reactions(message, emojis)
        if added:
            settings["stats"]["reaction_messages"] = int(settings["stats"].get("reaction_messages", 0)) + 1
            # 자동 반응이 많은 서버에서 매 메시지마다 디스크를 쓰지 않도록 주기적으로 저장합니다.
            if int(settings["stats"]["reaction_messages"]) % 25 == 0:
                save_data()

    async def handle_anti_raid_join(member: discord.Member) -> None:
        if member.bot:
            return
        settings = get_settings(member.guild)
        anti = settings["anti_raid"]
        if not anti.get("enabled", False):
            return
        now_monotonic = time.monotonic()
        window = JOIN_WINDOWS[member.guild.id]
        join_window = max(5, min(300, int(anti.get("join_window_seconds", 25))))
        while window and now_monotonic - window[0] > join_window:
            window.popleft()
        window.append(now_monotonic)

        account_age = discord.utils.utcnow() - member.created_at
        min_age_days = max(0, int(anti.get("min_account_age_days", 3)))
        young_account = account_age < timedelta(days=min_age_days)
        join_limit = max(3, int(anti.get("join_limit", 6)))
        triggered_now = len(window) >= join_limit and not anti.get("raid_active", False)
        if triggered_now:
            anti["raid_active"] = True
            anti["raid_started_at"] = discord.utils.utcnow().isoformat()
            settings["stats"]["raid_triggers"] = int(settings["stats"].get("raid_triggers", 0)) + 1
            save_data()
            await send_log(
                member.guild,
                "🚨 레이드 가입 폭주 감지",
                f"**{join_window}초 동안 {len(window)}명**이 가입했습니다.\n이후 가입자는 자동 격리됩니다.",
                color=0xC0392B,
            )
            if anti.get("auto_lockdown", False):
                success, failed = await lock_server(member.guild, reason="ABADDON 안티레이드 자동 잠금")
                await send_log(member.guild, "🔐 레이드 자동 잠금", f"성공 {success}개 · 실패 {failed}개", color=0xC0392B)

        if young_account or anti.get("raid_active", False):
            reason = "레이드 감지 중 신규 가입" if anti.get("raid_active", False) else f"계정 생성 {min_age_days}일 미만"
            await quarantine_member(
                member,
                reason=f"ABADDON 안티레이드: {reason}",
                moderator_id=bot.user.id if bot.user else 0,
                source="anti_raid",
            )

    async def handle_sticky_message(message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return
        sticky_map = get_settings(message.guild).setdefault("sticky_messages", {})
        data = sticky_map.get(str(message.channel.id))
        if not isinstance(data, dict) or not data.get("content"):
            return
        key = (message.guild.id, message.channel.id)
        STICKY_COUNTERS[key] += 1
        every = max(3, min(50, int(data.get("every", 8))))
        if STICKY_COUNTERS[key] < every:
            return
        STICKY_COUNTERS[key] = 0
        old_id = int(data.get("message_id", 0) or 0)
        if old_id:
            try:
                old_message = await message.channel.fetch_message(old_id)
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        embed = discord.Embed(title="📌 채널 고정 안내", description=str(data.get("content", ""))[:4000], color=0xF1C40F)
        try:
            sticky_message = await message.channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return
        data["message_id"] = sticky_message.id
        save_data()

    bot.add_listener(handle_auto_reactions, "on_message")
    bot.add_listener(handle_sticky_message, "on_message")
    bot.add_listener(handle_anti_raid_join, "on_member_join")

    bot._abaddon_v411_guard_plus_registered = True
    print("[V4.2 SERVER GUARD PLUS] 스마트 자동 이모지/안티레이드/확장 관리 등록 완료", flush=True)
