from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands


SETUP_PREVIEW_TTL = 600
PENDING_SETUPS: Dict[int, Dict[str, Any]] = {}
SETUP_LOCKS: Dict[int, asyncio.Lock] = {}


ROLE_SPECS: List[Dict[str, Any]] = [
    {"name": "👑 종말의 지배자", "color": 0x8E44AD, "hoist": True},
    {"name": "🛡 기지 관리자", "color": 0xE74C3C, "hoist": True},
    {"name": "⚙️ 시스템 관리자", "color": 0x9B59B6, "hoist": True},
    {"name": "🩸 집행관", "color": 0xC0392B, "hoist": True},
    {"name": "📡 정찰대", "color": 0x2ECC71, "hoist": True},
    {"name": "🧰 기술자", "color": 0x1ABC9C, "hoist": True},
    {"name": "💉 의무병", "color": 0x3498DB, "hoist": True},
    {"name": "🪖 생존자", "color": 0x95A5A6, "hoist": True},
    {"name": "🆕 신규 생존자", "color": 0x7F8C8D, "hoist": False},
]


CATEGORY_SPECS: List[Dict[str, Any]] = [
    {
        "name": "╭─────〔 🚪 입구 〕─────╮",
        "channels": [
            {"name": "📜・서버-안내", "type": "text", "read_only": True, "topic": "ABADDON 서버 이용 안내"},
            {"name": "📢・공지사항", "type": "text", "read_only": True, "topic": "ABADDON 공식 공지 및 업데이트"},
            {"name": "📕・이용규칙", "type": "text", "read_only": True, "topic": "서버 이용 규칙"},
            {"name": "🎭・역할선택", "type": "text", "read_only": True, "allow_reactions": True, "topic": "서버 역할 선택"},
            {"name": "❓・도움말", "type": "text", "read_only": True, "topic": "서버와 아바돈 봇 도움말"},
        ],
    },
    {
        "name": "╭─────〔 🏚 생존기지 〕─────╮",
        "channels": [
            {"name": "💬・생존자-광장", "type": "text", "topic": "생존자 자유 대화"},
            {"name": "🖼・스크린샷", "type": "text", "topic": "게임과 일상 스크린샷 공유"},
            {"name": "🎮・게임이야기", "type": "text", "topic": "게임 관련 대화"},
            {"name": "🐹・일상공유", "type": "text", "topic": "일상, 반려동물, 취미 공유"},
            {"name": "🤖・봇-명령어", "type": "text", "topic": "ABADDON 봇 명령어 전용 채널"},
        ],
    },
    {
        "name": "╭─────〔 ☠️ 아바돈 RPG 〕─────╮",
        "channels": [
            {"name": "🪪・생존자-등록", "type": "text", "topic": "ABADDON RPG 가입 및 생존자 등록"},
            {"name": "⚔️・전투구역", "type": "text", "topic": "훈련, 레이드, PVP 전투"},
            {"name": "🏚・던전", "type": "text", "topic": "던전 및 심층 던전"},
            {"name": "🎰・블랙카지노", "type": "text", "topic": "BLACK CASINO 전용 채널"},
            {"name": "📈・암시장", "type": "text", "topic": "실시간 코인 시세와 암시장 거래"},
            {"name": "🏦・은행", "type": "text", "topic": "예금, 출금, 대출, 신용 관리"},
            {"name": "🕴️・사채시장", "type": "text", "topic": "사채 차입 및 상환"},
            {"name": "🐾・펫-보호소", "type": "text", "topic": "펫 수집, 훈련, 진화"},
            {"name": "🛒・거래소", "type": "text", "topic": "장비 거래소 및 경매"},
            {"name": "🏆・랭킹", "type": "text", "topic": "각종 서버 랭킹 확인"},
        ],
    },
    {
        "name": "╭─────〔 📚 정보실 〕─────╮",
        "channels": [
            {"name": "📖・명령어-목록", "type": "text", "read_only": True, "topic": "ABADDON 전체 명령어 안내"},
            {"name": "🧪・아이템-도감", "type": "text", "read_only": True, "topic": "아이템, 펫, 몬스터 도감 안내"},
            {"name": "🪙・코인-시세", "type": "text", "read_only": True, "topic": "암시장 코인 시세 알림"},
            {"name": "📝・업데이트-내역", "type": "text", "read_only": True, "topic": "ABADDON 업데이트 기록"},
            {"name": "🐛・버그제보", "type": "text", "topic": "오류 화면과 재현 방법 제보"},
            {"name": "💡・건의사항", "type": "text", "topic": "서버 및 봇 기능 건의"},
        ],
    },
    {
        "name": "╭─────〔 🔊 음성구역 〕─────╮",
        "channels": [
            {"name": "🔊・생존자-대기실", "type": "voice"},
            {"name": "🎮・게임방-1", "type": "voice"},
            {"name": "🎮・게임방-2", "type": "voice"},
            {"name": "🎵・음악감상실", "type": "voice"},
            {"name": "🌙・잠수구역", "type": "voice"},
        ],
    },
    {
        "name": "╭─────〔 🛡 관리자구역 〕─────╮",
        "admin_only": True,
        "channels": [
            {"name": "🔒・관리자-회의", "type": "text", "topic": "관리자 전용 회의"},
            {"name": "📋・관리자-로그", "type": "text", "topic": "관리 기록 및 운영 메모"},
            {"name": "🤖・봇-로그", "type": "text", "topic": "ABADDON 봇 로그 확인"},
            {"name": "🚨・신고접수", "type": "text", "topic": "신고 검토 및 처리"},
            {"name": "🧪・테스트실", "type": "text", "topic": "관리자 기능 테스트"},
        ],
    },
]


STARTER_MESSAGES: Dict[str, Tuple[str, str, int]] = {
    "📜・서버-안내": (
        "☠️ ABADDON | 종말 이후",
        "붕괴한 세계에서 살아남은 생존자들의 기지입니다.\n\n"
        "1. `📕・이용규칙`을 먼저 확인하세요.\n"
        "2. `🪪・생존자-등록`에서 `!가입 생존자`를 입력하세요.\n"
        "3. `🤖・봇-명령어`에서 RPG를 즐기면 됩니다.\n"
        "4. 전체 명령어는 `!명령어` 또는 `!도움말`로 확인할 수 있습니다.",
        0x8E44AD,
    ),
    "📢・공지사항": (
        "📢 ABADDON 공지 채널",
        "서버 공지와 봇 업데이트 내역이 등록되는 채널입니다.\n관리자만 메시지를 작성할 수 있습니다.",
        0xE74C3C,
    ),
    "📕・이용규칙": (
        "📕 생존기지 이용규칙",
        "1. 타인에 대한 욕설, 혐오, 괴롭힘을 금지합니다.\n"
        "2. 도배, 광고, 사칭, 악성 링크를 금지합니다.\n"
        "3. 분쟁은 공개 채널에서 키우지 말고 관리자에게 신고하세요.\n"
        "4. 봇 오류와 악용 가능한 버그는 `🐛・버그제보`에 알려주세요.\n"
        "5. 관리진의 안내와 Discord 이용약관을 준수하세요.",
        0xC0392B,
    ),
    "❓・도움말": (
        "❓ ABADDON 빠른 도움말",
        "`!가입 생존자` — RPG 가입\n"
        "`!튜토리얼` — 초보자 진행 안내\n"
        "`!명령어` — 전체 명령어 목록\n"
        "`!도움말` — 카테고리별 도움말\n"
        "`!서버설정` — 현재 서버의 아바돈 설정 확인",
        0x3498DB,
    ),
    "🪪・생존자-등록": (
        "🪪 생존자 등록소",
        "아래 명령어를 입력하면 ABADDON RPG에 가입됩니다.\n\n`!가입 생존자`",
        0x2ECC71,
    ),
    "🤖・봇-명령어": (
        "🤖 ABADDON 명령어 구역",
        "봇 명령어는 이곳에서 사용하는 것을 권장합니다.\n전체 목록: `!명령어` · 도움말: `!도움말`",
        0x9B59B6,
    ),
    "📖・명령어-목록": (
        "📖 명령어 확인 방법",
        "실시간 전체 명령어 목록은 `!명령어`를 입력해 확인하세요.\n슬래시 명령어는 `/`를 입력하면 카테고리별로 표시됩니다.",
        0x1ABC9C,
    ),
    "🧪・아이템-도감": (
        "🧪 도감 안내",
        "`!도감` · `!도감 장비` · `!도감 펫` · `!도감 몬스터`\n관리자 아이템 검색: `!아이템검색 검색어`",
        0xF1C40F,
    ),
    "🪙・코인-시세": (
        "🪙 암시장 코인 시세",
        "현재 시세는 `!시세`로 확인할 수 있습니다.\n판매는 `!매도` 또는 `!코인판매`를 입력하면 드롭다운이 열립니다.",
        0xF39C12,
    ),
    "📝・업데이트-내역": (
        "📝 업데이트 내역",
        "ABADDON의 신규 기능, 수정 사항, 점검 공지를 기록하는 채널입니다.",
        0x95A5A6,
    ),
    "🐛・버그제보": (
        "🐛 버그 제보 양식",
        "• 사용한 명령어\n• 발생한 오류 화면\n• 오류가 발생한 순서\n• 반복 발생 여부\n\n개인정보와 봇 토큰은 절대 올리지 마세요.",
        0xE67E22,
    ),
    "💡・건의사항": (
        "💡 건의사항 양식",
        "추가했으면 하는 기능과 그 이유를 자유롭게 작성해주세요.\n비슷한 건의가 있다면 새 글 대신 기존 의견에 반응을 남겨주세요.",
        0xF1C40F,
    ),
}


def _get_setup_lock(guild_id: int) -> asyncio.Lock:
    lock = SETUP_LOCKS.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        SETUP_LOCKS[guild_id] = lock
    return lock


def _find_role(guild: discord.Guild, name: str) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=name)


def _find_category(guild: discord.Guild, name: str) -> Optional[discord.CategoryChannel]:
    return discord.utils.get(guild.categories, name=name)


def _find_channel(guild: discord.Guild, name: str, channel_type: str):
    if channel_type == "voice":
        return discord.utils.get(guild.voice_channels, name=name)
    return discord.utils.get(guild.text_channels, name=name)


async def _safe_progress_update(
    ctx: commands.Context,
    progress: discord.Message,
    content: str,
) -> discord.Message:
    """진행 메시지의 원래 채널이 사라져도 다른 채널이나 DM으로 상태를 전달합니다."""
    try:
        await progress.edit(content=content)
        return progress
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        print(
            f"[서버세팅 진행메시지 복구] guild={getattr(ctx.guild, 'id', None)} "
            f"channel={getattr(getattr(progress, 'channel', None), 'id', None)} "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    guild = ctx.guild
    if guild is not None:
        bot_member = guild.me
        preferred_names = (
            "🤖・봇-명령어",
            "📋・관리자-로그",
            "🧪・테스트실",
            "💬・생존자-광장",
        )
        candidates: List[discord.TextChannel] = []
        seen_ids = set()

        for name in preferred_names:
            channel = discord.utils.get(guild.text_channels, name=name)
            if channel is not None and channel.id not in seen_ids:
                candidates.append(channel)
                seen_ids.add(channel.id)

        for channel in guild.text_channels:
            if channel.id not in seen_ids:
                candidates.append(channel)
                seen_ids.add(channel.id)

        for channel in candidates:
            if bot_member is not None:
                permissions = channel.permissions_for(bot_member)
                if not (permissions.view_channel and permissions.send_messages):
                    continue
            try:
                return await channel.send(content)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

    try:
        return await ctx.author.send(
            "서버 세팅을 실행한 채널이 삭제되었거나 접근할 수 없어 DM으로 결과를 보냅니다.\n\n"
            + content
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        print(
            f"[서버세팅 진행메시지 전달 실패] guild={getattr(ctx.guild, 'id', None)} "
            f"user={getattr(ctx.author, 'id', None)}",
            flush=True,
        )
        return progress


def _build_plan(guild: discord.Guild) -> Dict[str, Any]:
    missing_roles = [spec["name"] for spec in ROLE_SPECS if _find_role(guild, spec["name"]) is None]
    missing_categories: List[str] = []
    missing_text: List[str] = []
    missing_voice: List[str] = []
    category_lines: List[str] = []

    for category_spec in CATEGORY_SPECS:
        category_name = category_spec["name"]
        category_missing = _find_category(guild, category_name) is None
        if category_missing:
            missing_categories.append(category_name)

        category_missing_channels = 0
        for channel_spec in category_spec["channels"]:
            if _find_channel(guild, channel_spec["name"], channel_spec["type"]) is None:
                category_missing_channels += 1
                if channel_spec["type"] == "voice":
                    missing_voice.append(channel_spec["name"])
                else:
                    missing_text.append(channel_spec["name"])

        category_lines.append(
            f"• {category_name}: 카테고리 {'생성' if category_missing else '유지'} · "
            f"채널 {category_missing_channels}개 생성"
        )

    return {
        "missing_roles": missing_roles,
        "missing_categories": missing_categories,
        "missing_text": missing_text,
        "missing_voice": missing_voice,
        "category_lines": category_lines,
        "total_missing": len(missing_roles) + len(missing_categories) + len(missing_text) + len(missing_voice),
    }


def _bot_member(guild: discord.Guild, bot: commands.Bot) -> Optional[discord.Member]:
    if guild.me is not None:
        return guild.me
    if bot.user is None:
        return None
    return guild.get_member(bot.user.id)


def _public_read_only_overwrites(
    guild: discord.Guild,
    author: discord.Member,
    bot_member: discord.Member,
    allow_reactions: bool,
) -> Dict[Any, discord.PermissionOverwrite]:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=allow_reactions,
        ),
        author: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_messages=True,
            add_reactions=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            manage_messages=True,
            add_reactions=True,
        ),
    }


def _admin_category_overwrites(
    guild: discord.Guild,
    author: discord.Member,
    bot_member: discord.Member,
) -> Dict[Any, discord.PermissionOverwrite]:
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            manage_channels=True,
            manage_messages=True,
        ),
    }


async def _send_starter_embed(channel: discord.TextChannel) -> bool:
    payload = STARTER_MESSAGES.get(channel.name)
    if payload is None:
        return False
    title, description, color = payload
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="ABADDON 자동 서버 세팅")
    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    return True


def register_v403_server_builder(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    def current_theme(guild_id: int) -> Dict[str, Any]:
        try:
            from apocalypse_bot.commands.v641_stabilization import DEFAULT_THEME, THEMES
            root = world_data.get("v641", {})
            guilds = root.get("guilds", {}) if isinstance(root, dict) else {}
            state = guilds.get(str(guild_id), {}) if isinstance(guilds, dict) else {}
            key = str(state.get("theme", DEFAULT_THEME)) if isinstance(state, dict) else DEFAULT_THEME
            return dict(THEMES.get(key, THEMES[DEFAULT_THEME]))
        except Exception:
            return {"emoji": "🕯️", "title": "검은 성당", "color": 0x6C3B73, "tagline": "ABADDON 기본 생존 성역"}

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return False
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.")
            return False
        return True

    async def require_bot_permissions(ctx: commands.Context) -> Optional[discord.Member]:
        guild = ctx.guild
        if guild is None:
            return None
        member = _bot_member(guild, bot)
        if member is None:
            await ctx.send("❌ 서버에서 봇 권한 정보를 확인하지 못했습니다.")
            return None

        permissions = member.guild_permissions
        missing = []
        if not permissions.manage_channels:
            missing.append("채널 관리")
        if not permissions.manage_roles:
            missing.append("역할 관리")
        if not permissions.send_messages:
            missing.append("메시지 보내기")
        if not permissions.embed_links:
            missing.append("링크 첨부")

        if missing:
            await ctx.send(
                "❌ 자동 세팅에 필요한 봇 권한이 부족합니다.\n"
                f"필요 권한: **{', '.join(missing)}**\n"
                "봇 역할에 권한을 추가한 뒤 다시 실행하세요."
            )
            return None
        return member

    def setup_help_embed(guild_id: int = 0) -> discord.Embed:
        embed = discord.Embed(
            title="🏗️ ABADDON 서버 자동 세팅",
            description=(
                "카테고리, 채널, 장식용 역할을 자동으로 생성합니다.\n"
                "기존 채널과 역할은 **삭제하거나 이름을 바꾸지 않습니다.**"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="사용 순서",
            value=(
                "`!서버세팅 미리보기`\n"
                "`!서버세팅 실행`\n"
                "`!서버세팅 취소`\n"
                "`!서버세팅 상태`"
            ),
            inline=False,
        )
        embed.add_field(
            name="자동 생성",
            value="역할 9개 · 카테고리 6개 · 텍스트 31개 · 음성 5개 · 기본 안내 임베드",
            inline=False,
        )
        theme = current_theme(guild_id)
        embed.add_field(
            name="현재 텍스트 테마",
            value=f"{theme.get('emoji', '🕯️')} **{theme.get('title', '검은 성당')}** · {theme.get('tagline', '')}\n변경: `!서버테마설정 테마명`",
            inline=False,
        )
        embed.set_footer(text="미리보기 승인 유효시간: 10분")
        return embed

    @bot.group(
        name="서버세팅",
        aliases=["서버꾸미기"],
        invoke_without_command=True,
        case_insensitive=True,
    )
    async def server_builder(ctx: commands.Context):
        if not await require_admin(ctx):
            return
        await ctx.send(embed=setup_help_embed(ctx.guild.id if ctx.guild else 0))

    @server_builder.command(name="미리보기", aliases=["preview", "확인"])
    async def server_builder_preview(ctx: commands.Context):
        if not await require_admin(ctx):
            return
        if await require_bot_permissions(ctx) is None:
            return

        guild = ctx.guild
        assert guild is not None
        plan = _build_plan(guild)
        PENDING_SETUPS[guild.id] = {
            "author_id": ctx.author.id,
            "expires_at": time.monotonic() + SETUP_PREVIEW_TTL,
        }

        embed = discord.Embed(
            title="🔎 ABADDON 서버 세팅 미리보기",
            description=(
                f"서버: **{guild.name}**\n"
                "기존 항목은 유지하고, 없는 항목만 생성합니다.\n"
                "현재 기본 채널도 자동으로 삭제되지 않습니다."
            ),
            color=0x3498DB,
        )
        embed.add_field(
            name="새로 생성할 항목",
            value=(
                f"역할 **{len(plan['missing_roles'])}개**\n"
                f"카테고리 **{len(plan['missing_categories'])}개**\n"
                f"텍스트 채널 **{len(plan['missing_text'])}개**\n"
                f"음성 채널 **{len(plan['missing_voice'])}개**"
            ),
            inline=True,
        )
        embed.add_field(
            name="완료 후 자동 연결",
            value="공지 채널 → `📢・공지사항`\nRPG 권장 채널 → `🤖・봇-명령어`",
            inline=True,
        )
        embed.add_field(
            name="카테고리별 계획",
            value="\n".join(plan["category_lines"])[:1024],
            inline=False,
        )
        if plan["total_missing"] == 0:
            embed.add_field(name="상태", value="✅ 이미 모든 자동 세팅 항목이 존재합니다.", inline=False)
        else:
            embed.add_field(
                name="실행",
                value="10분 안에 `!서버세팅 실행`을 입력하면 생성이 시작됩니다.",
                inline=False,
            )
        await ctx.send(embed=embed)

    @server_builder.command(name="상태", aliases=["status"])
    async def server_builder_status(ctx: commands.Context):
        if not await require_admin(ctx):
            return
        guild = ctx.guild
        assert guild is not None
        plan = _build_plan(guild)
        total_expected = len(ROLE_SPECS) + len(CATEGORY_SPECS) + sum(
            len(category["channels"]) for category in CATEGORY_SPECS
        )
        completed = total_expected - plan["total_missing"]
        percent = int((completed / total_expected) * 100) if total_expected else 100
        await ctx.send(
            "📊 **[ABADDON 서버 세팅 상태]**\n"
            f"완성도: **{completed}/{total_expected} ({percent}%)**\n"
            f"남은 역할: **{len(plan['missing_roles'])}개**\n"
            f"남은 카테고리: **{len(plan['missing_categories'])}개**\n"
            f"남은 텍스트 채널: **{len(plan['missing_text'])}개**\n"
            f"남은 음성 채널: **{len(plan['missing_voice'])}개**"
        )

    @server_builder.command(name="취소", aliases=["cancel"])
    async def server_builder_cancel(ctx: commands.Context):
        if not await require_admin(ctx):
            return
        guild = ctx.guild
        assert guild is not None
        pending = PENDING_SETUPS.get(guild.id)
        if pending is None:
            await ctx.send("⚠️ 취소할 서버 세팅 미리보기가 없습니다.")
            return
        if pending["author_id"] != ctx.author.id and ctx.author.id != guild.owner_id:
            await ctx.send("❌ 미리보기를 승인한 관리자 또는 서버 소유자만 취소할 수 있습니다.")
            return
        PENDING_SETUPS.pop(guild.id, None)
        await ctx.send("✅ ABADDON 서버 자동 세팅을 취소했습니다.")

    @server_builder.command(name="실행", aliases=["start", "적용"])
    async def server_builder_execute(ctx: commands.Context):
        if not await require_admin(ctx):
            return
        bot_member = await require_bot_permissions(ctx)
        if bot_member is None:
            return

        guild = ctx.guild
        assert guild is not None
        pending = PENDING_SETUPS.get(guild.id)
        if pending is None:
            await ctx.send("⚠️ 먼저 `!서버세팅 미리보기`를 실행하세요.")
            return
        if pending["expires_at"] < time.monotonic():
            PENDING_SETUPS.pop(guild.id, None)
            await ctx.send("⌛ 미리보기 승인 시간이 만료되었습니다. 다시 미리보기를 실행하세요.")
            return
        if pending["author_id"] != ctx.author.id and ctx.author.id != guild.owner_id:
            await ctx.send("❌ 미리보기를 승인한 관리자 또는 서버 소유자만 실행할 수 있습니다.")
            return

        lock = _get_setup_lock(guild.id)
        if lock.locked():
            await ctx.send("⏳ 이 서버의 자동 세팅이 이미 진행 중입니다.")
            return

        async with lock:
            progress = await ctx.send("🏗️ **ABADDON 서버 자동 세팅을 시작합니다...**")
            created_roles = 0
            created_categories = 0
            created_text = 0
            created_voice = 0
            starter_embeds = 0
            created_text_channels: List[discord.TextChannel] = []
            reason = f"ABADDON V4.0.5 자동 서버 세팅 / 실행자 {ctx.author} ({ctx.author.id})"

            try:
                for spec in ROLE_SPECS:
                    if _find_role(guild, spec["name"]) is not None:
                        continue
                    await guild.create_role(
                        name=spec["name"],
                        colour=discord.Colour(spec["color"]),
                        permissions=discord.Permissions.none(),
                        hoist=bool(spec.get("hoist", False)),
                        mentionable=False,
                        reason=reason,
                    )
                    created_roles += 1

                for category_spec in CATEGORY_SPECS:
                    category = _find_category(guild, category_spec["name"])
                    if category is None:
                        overwrites = None
                        if category_spec.get("admin_only"):
                            overwrites = _admin_category_overwrites(guild, ctx.author, bot_member)
                        category_kwargs: Dict[str, Any] = {"reason": reason}
                        if overwrites is not None:
                            category_kwargs["overwrites"] = overwrites
                        category = await guild.create_category(
                            category_spec["name"],
                            **category_kwargs,
                        )
                        created_categories += 1

                    for channel_spec in category_spec["channels"]:
                        existing = _find_channel(guild, channel_spec["name"], channel_spec["type"])
                        if existing is not None:
                            continue

                        if channel_spec["type"] == "voice":
                            await guild.create_voice_channel(
                                channel_spec["name"],
                                category=category,
                                reason=reason,
                            )
                            created_voice += 1
                            continue

                        overwrites = None
                        if channel_spec.get("read_only") and not category_spec.get("admin_only"):
                            overwrites = _public_read_only_overwrites(
                                guild,
                                ctx.author,
                                bot_member,
                                bool(channel_spec.get("allow_reactions", False)),
                            )
                        channel_kwargs: Dict[str, Any] = {
                            "category": category,
                            "topic": channel_spec.get("topic"),
                            "reason": reason,
                        }
                        if overwrites is not None:
                            channel_kwargs["overwrites"] = overwrites
                        new_channel = await guild.create_text_channel(
                            channel_spec["name"],
                            **channel_kwargs,
                        )
                        created_text_channels.append(new_channel)
                        created_text += 1

                    progress = await _safe_progress_update(
                        ctx,
                        progress,
                        content=(
                            "🏗️ **ABADDON 서버 자동 세팅 진행 중...**\n"
                            f"현재 처리: {category_spec['name']}\n"
                            f"역할 {created_roles} · 카테고리 {created_categories} · "
                            f"텍스트 {created_text} · 음성 {created_voice}"
                        )
                    )

                for channel in created_text_channels:
                    try:
                        if await _send_starter_embed(channel):
                            starter_embeds += 1
                    except (discord.Forbidden, discord.HTTPException):
                        # 채널 생성은 성공했으므로 안내 메시지만 건너뜁니다.
                        pass

                announcement = _find_channel(guild, "📢・공지사항", "text")
                rpg_channel = _find_channel(guild, "🤖・봇-명령어", "text")
                guild_settings = world_data.setdefault("guild_settings", {}).setdefault(
                    str(guild.id),
                    {
                        "announcement_channel_id": None,
                        "rpg_channel_id": None,
                        "codex_notifications": True,
                        "tutorial_notifications": True,
                        "story_enabled": True,
                    },
                )
                if announcement is not None:
                    guild_settings["announcement_channel_id"] = announcement.id
                if rpg_channel is not None:
                    guild_settings["rpg_channel_id"] = rpg_channel.id

                world_data.setdefault("server_builder", {})[str(guild.id)] = {
                    "version": "4.0.5",
                    "completed_at": int(time.time()),
                    "completed_by": ctx.author.id,
                }
                save_data()
                PENDING_SETUPS.pop(guild.id, None)

                progress = await _safe_progress_update(
                    ctx,
                    progress,
                    content=(
                        "✅ **ABADDON 서버 자동 세팅 완료!**\n"
                        f"새 역할: **{created_roles}개**\n"
                        f"새 카테고리: **{created_categories}개**\n"
                        f"새 텍스트 채널: **{created_text}개**\n"
                        f"새 음성 채널: **{created_voice}개**\n"
                        f"기본 안내 임베드: **{starter_embeds}개**\n\n"
                        "기존 채널과 역할은 삭제하지 않았습니다.\n"
                        "서버 아이콘·배너·커뮤니티 온보딩 화면은 Discord 서버 설정에서 직접 지정하면 됩니다."
                    )
                )

            except discord.Forbidden:
                PENDING_SETUPS.pop(guild.id, None)
                progress = await _safe_progress_update(
                    ctx,
                    progress,
                    content=(
                        "❌ **권한 부족으로 자동 세팅이 중단되었습니다.**\n"
                        "봇 역할에 `채널 관리`, `역할 관리`, `메시지 보내기`, `링크 첨부` 권한을 부여하세요.\n"
                        "이미 생성된 항목은 유지되며, 권한 수정 후 다시 미리보기부터 실행하면 나머지만 생성됩니다."
                    )
                )
            except discord.HTTPException as exc:
                PENDING_SETUPS.pop(guild.id, None)
                progress = await _safe_progress_update(
                    ctx,
                    progress,
                    content=(
                        "❌ **Discord API 오류로 자동 세팅이 중단되었습니다.**\n"
                        f"오류: `{type(exc).__name__}: {str(exc)[:300]}`\n"
                        "이미 생성된 항목은 유지됩니다. 잠시 후 다시 미리보기부터 실행하세요."
                    )
                )
            except Exception as exc:
                PENDING_SETUPS.pop(guild.id, None)
                print(
                    f"[서버세팅 오류] guild={guild.id} user={ctx.author.id} "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                progress = await _safe_progress_update(
                    ctx,
                    progress,
                    content=(
                        "❌ **예상하지 못한 오류로 자동 세팅이 중단되었습니다.**\n"
                        f"오류: `{type(exc).__name__}: {str(exc)[:300]}`\n"
                        "이미 생성된 항목은 유지됩니다. Render 로그와 이 메시지를 확인해주세요."
                    )
                )
