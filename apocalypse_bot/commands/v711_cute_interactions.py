from __future__ import annotations

import random
import re
import uuid
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands.v600_game_center import (
    GameBridgeError,
    _command_requires_input,
    _invoke_command,
)


VERSION = "7.2.0"
MENU_TIMEOUT = 300
PAGE_SIZE = 25
_COMMAND_INDEX_CACHE: Dict[int, Dict[str, Any]] = {}
V1093_COMMAND_CATALOG_FAST_ACK = True
NEWCOMER_ROLE_NAME = "저 새로 들어왔어요, 환영해주세요!"
NEWCOMER_ROLE_EMOJI = "🌱"

WELCOME_THEMES: Dict[str, Dict[str, Any]] = {
    "sprout": {
        "name": "새싹 정원",
        "emoji": "🌱",
        "role_emoji": "🌱",
        "color": (112, 207, 165),
        "aliases": ("새싹", "정원", "기본", "그린", "sprout", "garden"),
        "marks": ("🌱", "🍀", "🪴", "💚", "✨", "૮₍˶ᵔ ᵕ ᵔ˶₎ა"),
        "titles": (
            "🌱 새 생존자가 도착했어요!",
            "🍀 오늘의 행운 같은 생존자 등장!",
            "🪴 조그마한 새싹 신호를 발견했어요!",
        ),
        "lines": (
            "아직 이곳이 낯설 수 있어요. 따뜻하게 인사해 주세요!",
            "처음 며칠 동안은 새싹 표식이 함께해요. 살짝 챙겨주면 좋아해요!",
            "작은 도움 하나가 새 생존자에게는 든든한 보급품이 됩니다.",
        ),
        "guide": "🌿 인사 한마디와 작은 팁 하나면 새싹이 무럭무럭 자라요.",
    },
    "blossom": {
        "name": "벚꽃 피크닉",
        "emoji": "🌸",
        "role_emoji": "🌸",
        "color": (244, 154, 193),
        "aliases": ("벚꽃", "꽃", "핑크", "blossom", "sakura"),
        "marks": ("🌸", "🌷", "🎀", "💗", "🧁", "₍^. .^₎⟆"),
        "titles": (
            "🌸 새로운 꽃잎이 살포시 내려왔어요!",
            "🎀 반짝이는 새 친구가 도착했어요!",
            "🧁 달콤한 생존 신호가 포착됐어요!",
        ),
        "lines": (
            "오늘의 생존 구역이 조금 더 화사해졌어요. 반갑게 맞아주세요!",
            "낯선 폐허에서도 꽃길 안내는 저희가 맡을게요.",
            "아래 버튼을 톡 눌러 첫 모험을 천천히 시작해 보세요.",
        ),
        "guide": "🌷 따뜻한 환영 한마디를 건네면 오늘의 기지가 더 포근해져요.",
    },
    "bubble": {
        "name": "말랑 버블",
        "emoji": "🫧",
        "role_emoji": "🫧",
        "color": (103, 205, 222),
        "aliases": ("말랑", "버블", "거품", "블루", "bubble", "aqua"),
        "marks": ("🫧", "🩵", "🐳", "💧", "🪼", "ʕ•ᴥ•ʔ"),
        "titles": (
            "🫧 말랑한 새 생존 신호 포착!",
            "🩵 파란빛 새 친구가 퐁 하고 나타났어요!",
            "🐳 조용한 물결을 타고 생존자가 도착했어요!",
        ),
        "lines": (
            "긴장하지 않아도 괜찮아요. 이곳에서는 천천히 적응해도 돼요.",
            "버튼을 하나씩 눌러보면 필요한 기능이 말랑하게 이어집니다.",
            "새 친구가 길을 잃지 않도록 부드럽게 안내해 주세요.",
        ),
        "guide": "🫧 서두르지 말고 하나씩 눌러보세요. 잘못 눌러도 괜찮아요.",
    },
    "starlight": {
        "name": "별빛 탐험대",
        "emoji": "🌙",
        "role_emoji": "🌙",
        "color": (132, 126, 222),
        "aliases": ("별빛", "별", "달", "우주", "starlight", "moon"),
        "marks": ("🌙", "⭐", "🌌", "💫", "🔭", "✨"),
        "titles": (
            "🌙 먼 별에서 새로운 신호가 도착했어요!",
            "⭐ 별빛 탐험대에 새 대원이 합류했어요!",
            "🌌 어둠 속에서 반짝이는 생존자를 발견했어요!",
        ),
        "lines": (
            "처음 보는 별자리처럼 낯설어도, 안내선을 따라가면 괜찮아요.",
            "아래 버튼이 첫 탐험을 위한 작은 항법 장치가 되어줄 거예요.",
            "새 대원이 안전하게 착륙할 수 있도록 환영 신호를 보내주세요.",
        ),
        "guide": "💫 함께라면 가장 어두운 밤에도 길을 잃지 않아요.",
    },
    "paw": {
        "name": "동물 친구",
        "emoji": "🐾",
        "role_emoji": "🐾",
        "color": (218, 170, 116),
        "aliases": ("동물", "친구", "발바닥", "냥이", "멍이", "paw", "animal"),
        "marks": ("🐾", "🐈", "🐕", "🐇", "🦊", "ฅ^•ﻌ•^ฅ"),
        "titles": (
            "🐾 조심조심, 새 발자국이 보여요!",
            "🐈 호기심 많은 새 친구가 찾아왔어요!",
            "🦊 폐허 너머에서 귀여운 동료가 나타났어요!",
        ),
        "lines": (
            "낯선 냄새가 가득해도 금방 익숙해질 거예요. 반갑게 인사해 주세요!",
            "첫 발걸음을 안전하게 뗄 수 있도록 아래 버튼을 준비했어요.",
            "새 친구가 놀라지 않도록 살금살금 친절하게 다가가 주세요.",
        ),
        "guide": "🐾 작은 발자국이 멋진 생존 기록으로 이어지도록 함께해 주세요.",
    },
    "apocalypse": {
        "name": "아포칼립스 생존구역",
        "emoji": "☣️",
        "role_emoji": "☣️",
        "color": (214, 86, 63),
        "aliases": ("아포칼립스", "종말", "폐허", "아바돈", "apocalypse", "abaddon"),
        "marks": ("☣️", "🧟", "🔥", "🩸", "📻", "⚠️"),
        "titles": (
            "☣️ 생존 구역에 새로운 신호가 잡혔다!",
            "📻 폐허 너머에서 구조 요청이 수신됐다!",
            "🔥 또 한 명의 생존자가 방벽 안으로 들어왔다!",
        ),
        "lines": (
            "경계는 유지하되 무기는 내려놓으세요. 새로운 생존자는 우리의 동료입니다.",
            "오염 지대는 위험하지만, 아래 보급 절차를 따르면 살아남을 수 있습니다.",
            "통신 상태 양호. 신원 등록 후 오늘의 생존 임무를 확인하세요.",
        ),
        "guide": "⚠️ 기존 생존자는 보급 경로와 안전 수칙을 알려주십시오. 함께 살아남습니다.",
    },
}


def _normalise_theme_token(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").casefold())


def _resolve_theme_key(value: str) -> Optional[str]:
    token = _normalise_theme_token(value)
    if not token:
        return None
    for key, theme in WELCOME_THEMES.items():
        candidates = (key, theme.get("name", ""), *theme.get("aliases", ()))
        if token in {_normalise_theme_token(item) for item in candidates}:
            return key
    return None


def _welcome_theme(settings_or_key: Any) -> Dict[str, Any]:
    if isinstance(settings_or_key, dict):
        key = str(settings_or_key.get("theme", "sprout"))
    else:
        key = str(settings_or_key or "sprout")
    return WELCOME_THEMES.get(key, WELCOME_THEMES["sprout"])


def _theme_name(settings_or_key: Any) -> str:
    theme = _welcome_theme(settings_or_key)
    return f"{theme['emoji']} {theme['name']}"


CATEGORY_FALLBACKS = {
    "start": ("가입", "정보", "상태", "출석", "튜토리얼", "처음", "명령어", "게임"),
    "life": ("채집", "낚시", "벌목", "광산", "알바", "땅파기", "감정", "운세", "무전"),
    "shop": ("상점", "구매", "장비", "강화", "제작", "인벤토리", "내구도", "수리", "개조"),
    "battle": ("전투", "던전", "레이드", "월드보스", "지역", "좀비", "PVP", "침공"),
    "trade": ("거래", "판매", "경매", "은행", "대출", "사채", "암시장", "시장", "송금"),
    "casino": ("카지노", "블랙잭", "슬롯", "다이스", "바카라", "룰렛", "코인플립", "올인"),
    "story": ("스토리", "시즌2", "시즌3", "원정", "유물", "도감"),
    "pet": ("펫",),
    "guild_party": ("길드", "파티"),
    "quest": ("퀘스트", "시즌패스", "업적", "성장보드", "오늘할일", "미션보상", "누적보상"),
    "base": ("기지", "병원", "의약품", "약품", "자원", "날씨", "위험구역"),
    "talk": ("대화", "아바돈", "지식", "질문", "응원", "교감", "한마디"),
    "server": ("서버", "운영", "관리", "설정", "백업", "복구", "오류", "보안", "알림", "규칙", "새싹"),
}


def _root(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault("v711_cute_interactions", {})
    root.setdefault("guilds", {})
    root.setdefault("ui_errors", [])
    return root


def _guild_settings(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    settings = _root(world_data)["guilds"].setdefault(str(guild_id), {})
    settings.setdefault("enabled", True)
    settings.setdefault("days", 7)
    settings.setdefault("role_id", 0)
    settings.setdefault("role_mode", "temporary")
    settings.setdefault("role_created_by_abaddon", False)
    settings.setdefault("role_enabled", True)
    settings.setdefault("welcome_channel_id", 0)
    settings.setdefault("welcome_notice_channel_id", 0)
    settings.setdefault("welcome_rules_channel_id", 0)
    settings.setdefault("welcome_register_channel_id", 0)
    settings.setdefault("welcome_message", True)
    settings.setdefault("role_icon", True)
    settings.setdefault("theme", "sprout")
    legacy = world_data.setdefault("server_management", {}).setdefault(str(guild_id), {})
    # v7.2.0: 기존 환영/자동 역할 설정을 하나의 소스로 자동 이관합니다.
    for key in ("welcome_channel_id", "welcome_notice_channel_id", "welcome_rules_channel_id", "welcome_register_channel_id"):
        if not settings.get(key) and legacy.get(key):
            settings[key] = legacy.get(key)
        elif settings.get(key):
            legacy[key] = settings.get(key)
    if not settings.get("role_id") and legacy.get("autorole_id"):
        settings["role_id"] = legacy.get("autorole_id")
        settings["role_mode"] = "permanent"
        settings["role_created_by_abaddon"] = False
    elif settings.get("role_id"):
        legacy["autorole_id"] = settings.get("role_id")
    if settings.get("theme") not in WELCOME_THEMES:
        settings["theme"] = "sprout"
    return settings


def _record_ui_error(
    world_data: Dict[str, Any],
    save_data: Any,
    interaction: Optional[discord.Interaction],
    error: BaseException,
    where: str,
) -> str:
    incident = uuid.uuid4().hex[:8].upper()
    rows = _root(world_data).setdefault("ui_errors", [])
    rows.append(
        {
            "id": incident,
            "where": str(where)[:100],
            "error": f"{type(error).__name__}: {error}"[:500],
            "user_id": getattr(getattr(interaction, "user", None), "id", 0),
            "guild_id": getattr(getattr(interaction, "guild", None), "id", 0),
            "created_at": discord.utils.utcnow().isoformat(),
        }
    )
    del rows[:-50]
    try:
        save_data()
    except Exception:
        pass
    print(f"[귀여운 UI 오류:{incident}] {where} {type(error).__name__}: {error}", flush=True)
    return incident


async def _safe_interaction_message(
    interaction: discord.Interaction,
    content: str,
    *,
    ephemeral: bool = True,
    view: Optional[discord.ui.View] = None,
    embed: Optional[discord.Embed] = None,
) -> None:
    kwargs: Dict[str, Any] = {"ephemeral": ephemeral}
    if view is not None:
        kwargs["view"] = view
    if embed is not None:
        kwargs["embed"] = embed
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content or None, **kwargs)
        else:
            await interaction.response.send_message(content=content or None, **kwargs)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return


async def _ack_component(interaction: discord.Interaction) -> bool:
    """Acknowledge UI input before rebuilding the large command catalogue."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def _edit_component(interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View) -> None:
    if not await _ack_component(interaction):
        return
    try:
        await interaction.edit_original_response(embed=embed, view=view)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return


def _can_manage_guild(member: Any) -> bool:
    return isinstance(member, discord.Member) and (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or member.id == member.guild.owner_id
    )


def _can_send(channel: Any, guild: discord.Guild) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    me = guild.me
    if me is None:
        return False
    permissions = channel.permissions_for(me)
    return permissions.view_channel and permissions.send_messages and permissions.embed_links


def _find_welcome_channel(guild: discord.Guild, settings: Dict[str, Any]) -> Optional[discord.TextChannel]:
    configured = settings.get("welcome_channel_id", 0)
    try:
        channel = guild.get_channel(int(configured)) if configured else None
    except (TypeError, ValueError):
        channel = None
    if _can_send(channel, guild):
        return channel  # type: ignore[return-value]
    if _can_send(guild.system_channel, guild):
        return guild.system_channel
    keywords = ("환영", "입장", "가입", "welcome", "일반", "general", "로비")
    for text_channel in guild.text_channels:
        lowered = text_channel.name.casefold()
        if any(keyword in lowered for keyword in keywords) and _can_send(text_channel, guild):
            return text_channel
    return next((channel for channel in guild.text_channels if _can_send(channel, guild)), None)


async def _ensure_newcomer_role(
    guild: discord.Guild,
    settings: Dict[str, Any],
    *,
    force_recreate: bool = False,
) -> Optional[discord.Role]:
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        return None

    role: Optional[discord.Role] = None
    if not force_recreate:
        try:
            role = guild.get_role(int(settings.get("role_id", 0) or 0))
        except (TypeError, ValueError):
            role = None
        if role is None:
            role = discord.utils.get(guild.roles, name=NEWCOMER_ROLE_NAME)

    theme = _welcome_theme(settings)
    colour = discord.Colour.from_rgb(*theme["color"])
    if role is None:
        role = await guild.create_role(
            name=NEWCOMER_ROLE_NAME,
            permissions=discord.Permissions.none(),
            colour=colour,
            hoist=False,
            mentionable=False,
            reason="ABADDON v7.2.0 통합 신규 생존자 역할",
        )
        settings["role_created_by_abaddon"] = True
        settings["role_mode"] = "temporary"

    settings["role_id"] = role.id
    edit_kwargs: Dict[str, Any] = {}
    managed_style = bool(settings.get("role_created_by_abaddon")) or str(settings.get("role_mode")) == "temporary"
    if managed_style and role.name != NEWCOMER_ROLE_NAME:
        edit_kwargs["name"] = NEWCOMER_ROLE_NAME
    if managed_style and role.colour != colour:
        edit_kwargs["colour"] = colour
    if managed_style and "ROLE_ICONS" in getattr(guild, "features", []):
        if settings.get("role_icon", True):
            selected_emoji = str(theme.get("role_emoji", "🌱"))
            if getattr(role, "unicode_emoji", None) != selected_emoji:
                edit_kwargs["unicode_emoji"] = selected_emoji
        elif getattr(role, "unicode_emoji", None):
            edit_kwargs["unicode_emoji"] = None
    if edit_kwargs:
        try:
            role = await role.edit(
                **edit_kwargs,
                reason="ABADDON v7.2.0 통합 환영 역할 반영",
            )
        except (TypeError, discord.Forbidden, discord.HTTPException):
            pass
    return role


def _welcome_embed(
    member: discord.Member,
    days: int,
    theme_key: str = "sprout",
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> discord.Embed:
    theme = _welcome_theme(theme_key)
    mark = random.choice(tuple(theme["marks"]))
    settings = settings or {}
    role_mode = str(settings.get("role_mode", "temporary"))
    if not settings.get("role_enabled", True):
        role_text = "신규 역할 표식은 사용하지 않습니다."
    elif role_mode == "permanent":
        role_text = "서버 기본 신규 역할이 자동으로 지급됩니다."
    else:
        role_text = f"신규 생존자 표식은 약 {days}일 동안 유지됩니다."
    embed = discord.Embed(
        title=random.choice(tuple(theme["titles"])),
        description=(
            f"{member.mention} 님, **{member.guild.name}**에 온 걸 환영해요! {mark}\n"
            f"{random.choice(tuple(theme['lines']))}\n\n"
            f"{theme['emoji']} **{role_text}**"
        ),
        colour=discord.Colour.from_rgb(*theme["color"]),
        timestamp=discord.utils.utcnow(),
    )
    def channel_mention(key: str, fallback: str) -> str:
        try:
            channel = member.guild.get_channel(int(settings.get(key, 0) or 0))
        except (TypeError, ValueError):
            channel = None
        return getattr(channel, "mention", fallback)
    notice = channel_mention("welcome_notice_channel_id", "채널 준비 중")
    rules = channel_mention("welcome_rules_channel_id", "채널 준비 중")
    register = channel_mention("welcome_register_channel_id", "`!가입 생존자`")
    embed.add_field(
        name="📌 먼저 확인해주세요",
        value=f"📢 공지 · {notice}\n📕 규칙 · {rules}\n🪪 생존자 등록 · {register}",
        inline=False,
    )
    embed.add_field(
        name="🧭 처음이라면 이 순서로",
        value="`가입하기` → `처음 시작` → `오늘 할 일` → `게임 열기`",
        inline=False,
    )
    embed.add_field(name="💬 기존 생존자에게", value=str(theme["guide"]), inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ABADDON v{VERSION} · {_theme_name(theme_key)} · 통합 환영 시스템")
    return embed


def _theme_control_embed(settings: Dict[str, Any]) -> discord.Embed:
    current_key = str(settings.get("theme", "sprout"))
    current = _welcome_theme(current_key)
    lines = [
        f"{theme['emoji']} **{theme['name']}** — `!환영테마 {theme['name']}`"
        for theme in WELCOME_THEMES.values()
    ]
    embed = discord.Embed(
        title="🎨 신규 멤버 환영 테마",
        description=(
            f"현재 테마는 **{current['emoji']} {current['name']}**입니다.\n"
            "아래 드롭다운에서 고르면 이후 신규 멤버는 선택한 테마 안의 문구와 색상만 사용합니다."
        ),
        colour=discord.Colour.from_rgb(*current["color"]),
    )
    embed.add_field(name="✨ 선택 가능한 테마", value="\n".join(lines), inline=False)
    embed.add_field(
        name="🧪 미리보기",
        value="`!환영테마 미리보기` 또는 아래 **현재 테마 미리보기** 버튼",
        inline=False,
    )
    embed.set_footer(text="테마를 바꾸면 지원 서버에서는 신규 멤버 역할 아이콘과 색상도 함께 갱신됩니다.")
    return embed


def _beginner_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌱 처음 만난 생존자를 위한 말랑 가이드",
        description=(
            "명령어를 외우지 않아도 괜찮아요! 아래 버튼을 누르면 바로 실행되고, "
            "입력값이 필요한 기능은 작은 입력창이 열립니다. ૮₍˶ᵔ ᵕ ᵔ˶₎ა"
        ),
        colour=discord.Colour.from_rgb(137, 215, 176),
    )
    steps = (
        ("🪪", "가입하기", "생존자 등록과 초기 보급 수령"),
        ("📊", "정보 보기", "내 레벨·직업·식량 확인"),
        ("🎁", "출석하기", "오늘의 기본 보상 수령"),
        ("☀️", "오늘 할 일", "진행률과 다음 추천 행동 확인"),
        ("🎮", "게임 열기", "전체 기능을 카테고리로 탐색"),
    )
    embed.add_field(
        name="✨ 30초 시작 루트",
        value="\n".join(f"{emoji} **{title}** — {description}" for emoji, title, description in steps),
        inline=False,
    )
    embed.add_field(
        name="🫧 명령어 전체를 보고 싶다면",
        value="아래 **명령어 도감** 버튼을 누르세요. 모든 기존 명령을 페이지별로 고르고 바로 실행할 수 있어요.",
        inline=False,
    )
    embed.set_footer(text="잘못 눌러도 괜찮아요. 위험한 기능은 실행 전에 입력값과 권한을 다시 확인합니다.")
    return embed


def _command_description(command: commands.Command) -> str:
    text = str(getattr(command, "help", "") or getattr(command, "description", "") or "설명이 아직 등록되지 않은 명령어입니다.")
    return " ".join(text.split())[:300]


def _signature(command: commands.Command) -> str:
    suffix = str(getattr(command, "signature", "") or "").strip()
    return f"!{command.qualified_name}{(' ' + suffix) if suffix else ''}"


def _is_visible_command(command: commands.Command) -> bool:
    if getattr(command, "hidden", False):
        return False
    name = str(getattr(command, "qualified_name", "") or "").strip()
    return bool(name and not name.startswith("_"))


def _walk_commands(bot: commands.Bot) -> List[commands.Command]:
    result: List[commands.Command] = []
    seen = set()
    for command in bot.walk_commands():
        if not _is_visible_command(command):
            continue
        key = command.qualified_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(command)
    result.sort(key=lambda item: item.qualified_name.casefold())
    return result


def _guide_blob(category: Dict[str, Any]) -> str:
    return "\n".join(str(item) for item in category.get("commands", []))


def _command_category_id(command: commands.Command, guide: Sequence[Dict[str, Any]]) -> str:
    qualified = command.qualified_name
    names = [qualified, command.name, *getattr(command, "aliases", [])]
    for category in guide:
        blob = _guide_blob(category)
        if any(f"!{name}" in blob for name in names if name):
            return str(category.get("id", "server"))
    lowered = qualified.casefold()
    for category_id, keywords in CATEGORY_FALLBACKS.items():
        if any(keyword.casefold() in lowered for keyword in keywords):
            return category_id
    module_name = str(getattr(command.callback, "__module__", ""))
    if any(token in module_name for token in ("admin", "server", "security", "ops", "stability")):
        return "server"
    return "start"


def _category_meta(guide: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows = [{"id": "all", "emoji": "✨", "title": "전체 명령어", "hint": "등록된 모든 명령을 가나다순으로 확인"}]
    for category in guide:
        rows.append(
            {
                "id": str(category.get("id", "server")),
                "emoji": str(category.get("emoji", "📦")),
                "title": str(category.get("title", "기타")),
                "hint": str(category.get("hint", "관련 기능")),
            }
        )
    return rows[:25]



def _command_index(bot: commands.Bot, guide: Sequence[Dict[str, Any]]) -> Dict[str, List[commands.Command]]:
    """Build the expensive command/category map once per running bot."""
    key = id(bot)
    cached = _COMMAND_INDEX_CACHE.get(key)
    if cached is not None:
        return cached["buckets"]
    commands_list = _walk_commands(bot)
    buckets: Dict[str, List[commands.Command]] = {"all": commands_list}
    for row in _category_meta(guide):
        buckets.setdefault(row["id"], [])
    for command in commands_list:
        buckets.setdefault(_command_category_id(command, guide), []).append(command)
    _COMMAND_INDEX_CACHE[key] = {"buckets": buckets, "count": len(commands_list)}
    return buckets


def invalidate_command_catalog_cache(bot: commands.Bot) -> None:
    _COMMAND_INDEX_CACHE.pop(id(bot), None)

def _commands_for_category(
    bot: commands.Bot,
    guide: Sequence[Dict[str, Any]],
    category_id: str,
    *,
    query: str = "",
) -> List[commands.Command]:
    buckets = _command_index(bot, guide)
    commands_list = list(buckets.get(category_id, buckets.get("all", [])))
    token = "".join(str(query or "").casefold().split()).lstrip("!/")
    if token:
        filtered = []
        for command in commands_list:
            haystack = "".join(
                (
                    command.qualified_name,
                    " ".join(getattr(command, "aliases", [])),
                    _command_description(command),
                    str(getattr(command, "signature", "")),
                )
            ).casefold().replace(" ", "")
            if token in haystack:
                filtered.append(command)
        commands_list = filtered
    return commands_list


def _catalog_embed(
    bot: commands.Bot,
    guide: Sequence[Dict[str, Any]],
    category_id: str,
    page: int,
    *,
    query: str = "",
) -> discord.Embed:
    categories = {row["id"]: row for row in _category_meta(guide)}
    category = categories.get(category_id, categories["all"])
    commands_list = _commands_for_category(bot, guide, category_id, query=query)
    page_count = max(1, (len(commands_list) - 1) // PAGE_SIZE + 1)
    page = max(0, min(page, page_count - 1))
    start = page * PAGE_SIZE
    visible = commands_list[start:start + PAGE_SIZE]
    title = f"{category['emoji']} {category['title']}"
    if query:
        title = f"🔎 검색 결과 · {query}"
    embed = discord.Embed(
        title=title,
        description=(
            "명령어를 선택하면 사용법과 **바로 실행** 버튼이 열려요. "
            "입력값이 필요한 명령은 예쁜 입력창으로 이어집니다. 🫧"
        ),
        colour=discord.Colour.from_rgb(99, 196, 180),
    )
    embed.add_field(name="📚 명령어 수", value=f"**{len(commands_list)}개**", inline=True)
    embed.add_field(name="📄 페이지", value=f"**{page + 1}/{page_count}**", inline=True)
    if visible:
        lines = [f"{start + index + 1}. `{_signature(command)}`" for index, command in enumerate(visible[:12])]
        if len(visible) > 12:
            lines.append(f"… 이 페이지에 {len(visible) - 12}개 더 있어요")
        embed.add_field(name="🌸 현재 페이지 미리보기", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="🍃 결과 없음", value="다른 카테고리나 검색어를 골라보세요.", inline=False)
    embed.add_field(
        name="💡 이용 방법",
        value="카테고리 선택 → 명령어 선택 → 바로 실행 또는 입력하고 실행",
        inline=False,
    )
    embed.set_footer(text=f"ABADDON v{VERSION} · 모든 기존 명령어는 직접 입력 방식도 그대로 유지")
    return embed


def _command_detail_embed(command: commands.Command) -> discord.Embed:
    params = list(command.clean_params.values())
    requires_input = _command_requires_input(command)
    aliases = [f"!{alias}" for alias in getattr(command, "aliases", [])[:10]]
    embed = discord.Embed(
        title=f"✨ {command.qualified_name}",
        description=_command_description(command),
        colour=discord.Colour.from_rgb(154, 128, 219),
    )
    embed.add_field(name="🧾 사용법", value=f"`{_signature(command)}`", inline=False)
    embed.add_field(
        name="🫧 실행 방식",
        value="입력창을 작성하면 실행돼요." if requires_input else "버튼 한 번으로 바로 실행할 수 있어요.",
        inline=True,
    )
    embed.add_field(name="🔧 입력 항목", value=f"{len(params)}개", inline=True)
    if aliases:
        embed.add_field(name="🌿 같은 기능의 별칭", value=" · ".join(f"`{alias}`" for alias in aliases), inline=False)
    embed.add_field(
        name="⚠️ 안전 안내",
        value="권한·재화·쿨타임 조건은 기존 명령과 똑같이 검사합니다.",
        inline=False,
    )
    return embed


class CuteOwnedView(discord.ui.View):
    def __init__(self, owner_id: int, world_data: Dict[str, Any], save_data: Any, *, timeout: float = MENU_TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)
        self.world_data = world_data
        self.save_data = save_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await _safe_interaction_message(interaction, "🌱 이 메뉴는 처음 연 생존자만 조작할 수 있어요. 본인 메뉴는 `!명령어`로 열어주세요!")
        return False

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]) -> None:
        if isinstance(error, discord.NotFound) and int(getattr(error, "code", 0) or 0) == 10062:
            return
        incident = _record_ui_error(self.world_data, self.save_data, interaction, error, type(item).__name__)
        await _safe_interaction_message(
            interaction,
            f"🫧 버튼이 잠깐 꼬였어요. 다시 눌러보고 계속되면 사건 번호 `{incident}`를 관리자에게 알려주세요.",
        )


class UniversalCommandModal(discord.ui.Modal):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        command: commands.Command,
        world_data: Dict[str, Any],
        save_data: Any,
    ) -> None:
        super().__init__(title=f"{command.qualified_name} 실행"[:45], timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.command = command
        self.world_data = world_data
        self.save_data = save_data
        self.value_input = discord.ui.TextInput(
            label="명령어 뒤에 들어갈 값",
            placeholder=_signature(command)[:100],
            required=_command_requires_input(command),
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await _safe_interaction_message(interaction, "🌱 본인이 연 입력창만 사용할 수 있어요.")
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, self.command.qualified_name, str(self.value_input.value).strip())

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        incident = _record_ui_error(self.world_data, self.save_data, interaction, error, "UniversalCommandModal")
        await _safe_interaction_message(interaction, f"🫧 입력 처리 중 문제가 생겼어요. 사건 번호 `{incident}`")


class CommandDetailView(CuteOwnedView):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        command: commands.Command,
        world_data: Dict[str, Any],
        save_data: Any,
        guide: Sequence[Dict[str, Any]],
        category_id: str,
        page: int,
        *,
        query: str = "",
    ) -> None:
        super().__init__(owner_id, world_data, save_data)
        self.bot = bot
        self.command = command
        self.guide = guide
        self.category_id = category_id
        self.page = page
        self.query = query
        params = list(command.clean_params.values())
        self.direct.disabled = _command_requires_input(command)
        self.input_run.disabled = not params
        self.direct.label = "입력 없이 실행" if params else "바로 실행"

    @discord.ui.button(label="바로 실행", emoji="✨", style=discord.ButtonStyle.success, row=0)
    async def direct(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, self.command.qualified_name)

    @discord.ui.button(label="입력하고 실행", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def input_run(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            UniversalCommandModal(self.bot, self.owner_id, self.command, self.world_data, self.save_data)
        )

    @discord.ui.button(label="명령어 목록", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _edit_component(
            interaction,
            embed=_catalog_embed(self.bot, self.guide, self.category_id, self.page, query=self.query),
            view=CommandCatalogView(
                self.bot,
                self.owner_id,
                self.world_data,
                self.save_data,
                self.guide,
                category_id=self.category_id,
                page=self.page,
                query=self.query,
            ),
        )

    @discord.ui.button(label="게임센터", emoji="🎮", style=discord.ButtonStyle.secondary, row=1)
    async def game(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, "게임")


class CategorySelect(discord.ui.Select):
    def __init__(self, parent: "CommandCatalogView") -> None:
        self.parent_view = parent
        options = []
        counts = {
            row["id"]: len(_commands_for_category(parent.bot, parent.guide, row["id"]))
            for row in _category_meta(parent.guide)
        }
        for row in _category_meta(parent.guide):
            options.append(
                discord.SelectOption(
                    label=row["title"][:100],
                    value=row["id"],
                    description=f"{row['hint']} · {counts.get(row['id'], 0)}개"[:100],
                    emoji=row["emoji"],
                    default=row["id"] == parent.category_id and not parent.query,
                )
            )
        super().__init__(placeholder="🌸 먼저 분야를 골라주세요", options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _ack_component(interaction):
            return
        category_id = self.values[0]
        await _edit_component(
            interaction,
            embed=_catalog_embed(self.parent_view.bot, self.parent_view.guide, category_id, 0),
            view=CommandCatalogView(
                self.parent_view.bot,
                self.parent_view.owner_id,
                self.parent_view.world_data,
                self.parent_view.save_data,
                self.parent_view.guide,
                category_id=category_id,
                page=0,
            ),
        )


class CommandSelect(discord.ui.Select):
    def __init__(self, parent: "CommandCatalogView") -> None:
        self.parent_view = parent
        commands_list = _commands_for_category(parent.bot, parent.guide, parent.category_id, query=parent.query)
        start = parent.page * PAGE_SIZE
        visible = commands_list[start:start + PAGE_SIZE]
        # Select 값은 짧은 페이지 인덱스를 사용해 긴 하위 명령 이름도 잘리지 않게 합니다.
        self.command_names = {str(index): command for index, command in enumerate(visible)}
        if visible:
            options = [
                discord.SelectOption(
                    label=command.qualified_name[:100],
                    value=str(index),
                    description=f"{_signature(command)} · {_command_description(command)}"[:100],
                    emoji="✨" if not _command_requires_input(command) else "📝",
                )
                for index, command in enumerate(visible)
            ]
            placeholder = "🫧 실행할 명령어를 선택하세요"
            disabled = False
        else:
            options = [discord.SelectOption(label="결과가 없어요", value="__none__", emoji="🍃")]
            placeholder = "다른 카테고리를 골라주세요"
            disabled = True
        super().__init__(placeholder=placeholder, options=options, row=1, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        command = self.command_names.get(self.values[0])
        if command is None:
            await _safe_interaction_message(interaction, "🍃 명령어를 찾지 못했어요. 목록을 새로 열어주세요.")
            return
        if not await _ack_component(interaction):
            return
        await _edit_component(
            interaction,
            embed=_command_detail_embed(command),
            view=CommandDetailView(
                self.parent_view.bot,
                self.parent_view.owner_id,
                command,
                self.parent_view.world_data,
                self.parent_view.save_data,
                self.parent_view.guide,
                self.parent_view.category_id,
                self.parent_view.page,
                query=self.parent_view.query,
            ),
        )


class SearchModal(discord.ui.Modal, title="🔎 말랑 명령어 검색"):
    query_input = discord.ui.TextInput(
        label="무엇을 하고 싶나요?",
        placeholder="예: 강화, 월드보스 보상, 길드 가입, 백업",
        min_length=1,
        max_length=50,
    )

    def __init__(self, parent: "CommandCatalogView") -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.parent_view = parent

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = str(self.query_input.value).strip()
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        await interaction.followup.send(
            embed=_catalog_embed(self.parent_view.bot, self.parent_view.guide, "all", 0, query=query),
            view=CommandCatalogView(
                self.parent_view.bot,
                interaction.user.id,
                self.parent_view.world_data,
                self.parent_view.save_data,
                self.parent_view.guide,
                category_id="all",
                page=0,
                query=query,
            ),
            ephemeral=True,
        )


class CommandCatalogView(CuteOwnedView):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        world_data: Dict[str, Any],
        save_data: Any,
        guide: Sequence[Dict[str, Any]],
        *,
        category_id: str = "all",
        page: int = 0,
        query: str = "",
    ) -> None:
        super().__init__(owner_id, world_data, save_data)
        self.bot = bot
        self.guide = guide
        self.category_id = category_id
        self.query = query
        commands_list = _commands_for_category(bot, guide, category_id, query=query)
        self.page_count = max(1, (len(commands_list) - 1) // PAGE_SIZE + 1)
        self.page = max(0, min(page, self.page_count - 1))
        self.add_item(CategorySelect(self))
        self.add_item(CommandSelect(self))
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.page_count - 1

    @discord.ui.button(label="이전", emoji="🌿", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        page = max(0, self.page - 1)
        await _edit_component(
            interaction,
            embed=_catalog_embed(self.bot, self.guide, self.category_id, page, query=self.query),
            view=CommandCatalogView(
                self.bot, self.owner_id, self.world_data, self.save_data, self.guide,
                category_id=self.category_id, page=page, query=self.query,
            ),
        )

    @discord.ui.button(label="다음", emoji="🍀", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        page = min(self.page_count - 1, self.page + 1)
        await _edit_component(
            interaction,
            embed=_catalog_embed(self.bot, self.guide, self.category_id, page, query=self.query),
            view=CommandCatalogView(
                self.bot, self.owner_id, self.world_data, self.save_data, self.guide,
                category_id=self.category_id, page=page, query=self.query,
            ),
        )

    @discord.ui.button(label="검색", emoji="🔎", style=discord.ButtonStyle.primary, row=2)
    async def search(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(label="처음 가이드", emoji="🌱", style=discord.ButtonStyle.success, row=2)
    async def beginner(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _edit_component(
            interaction,
            embed=_beginner_embed(),
            view=BeginnerQuickView(self.bot, self.owner_id, self.world_data, self.save_data, self.guide),
        )

    @discord.ui.button(label="오늘 할 일", emoji="☀️", style=discord.ButtonStyle.secondary, row=3)
    async def today(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, "오늘할일")

    @discord.ui.button(label="게임센터", emoji="🎮", style=discord.ButtonStyle.secondary, row=3)
    async def game(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, "게임")


class BeginnerQuickView(CuteOwnedView):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        world_data: Dict[str, Any],
        save_data: Any,
        guide: Sequence[Dict[str, Any]],
    ) -> None:
        super().__init__(owner_id, world_data, save_data)
        self.bot = bot
        self.guide = guide

    async def _run(self, interaction: discord.Interaction, command_name: str, raw: str = "") -> None:
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, command_name, raw)

    @discord.ui.button(label="가입하기", emoji="🪪", style=discord.ButtonStyle.success, row=0)
    async def register(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._run(interaction, "가입", "생존자")

    @discord.ui.button(label="정보 보기", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def info(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._run(interaction, "정보")

    @discord.ui.button(label="출석하기", emoji="🎁", style=discord.ButtonStyle.primary, row=0)
    async def attendance(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._run(interaction, "출석")

    @discord.ui.button(label="오늘 할 일", emoji="☀️", style=discord.ButtonStyle.secondary, row=1)
    async def today(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._run(interaction, "오늘할일")

    @discord.ui.button(label="게임 열기", emoji="🎮", style=discord.ButtonStyle.secondary, row=1)
    async def game(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._run(interaction, "게임")

    @discord.ui.button(label="명령어 도감", emoji="📚", style=discord.ButtonStyle.secondary, row=1)
    async def catalog(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await _edit_component(
            interaction,
            embed=_catalog_embed(self.bot, self.guide, "all", 0),
            view=CommandCatalogView(
                self.bot, self.owner_id, self.world_data, self.save_data, self.guide,
                category_id="all", page=0,
            ),
        )


class WelcomeQuickView(BeginnerQuickView):
    pass


class WelcomeThemeSelect(discord.ui.Select):
    def __init__(self, parent: "WelcomeThemeView", current_key: str) -> None:
        self.parent_view = parent
        options = []
        for key, theme in WELCOME_THEMES.items():
            options.append(
                discord.SelectOption(
                    label=str(theme["name"]),
                    value=key,
                    emoji=str(theme["emoji"]),
                    description=f"{theme['emoji']} 분위기의 환영 문구·색상·역할 아이콘",
                    default=key == current_key,
                )
            )
        super().__init__(placeholder="환영 테마를 골라주세요", options=options, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        theme_key = self.values[0]
        settings = _guild_settings(self.parent_view.world_data, self.parent_view.guild_id)
        settings["theme"] = theme_key
        self.parent_view.save_data()
        guild = interaction.guild
        if guild is not None:
            try:
                role = guild.get_role(int(settings.get("role_id", 0) or 0))
            except (TypeError, ValueError):
                role = None
            if role is not None:
                try:
                    await _ensure_newcomer_role(guild, settings)
                    self.parent_view.save_data()
                except (discord.Forbidden, discord.HTTPException, TypeError):
                    pass
        refreshed = WelcomeThemeView(
            self.parent_view.owner_id,
            self.parent_view.guild_id,
            self.parent_view.world_data,
            self.parent_view.save_data,
            theme_key,
        )
        await interaction.response.edit_message(embed=_theme_control_embed(settings), view=refreshed)


class WelcomeThemeView(CuteOwnedView):
    def __init__(
        self,
        owner_id: int,
        guild_id: int,
        world_data: Dict[str, Any],
        save_data: Any,
        current_key: str,
    ) -> None:
        super().__init__(owner_id, world_data, save_data, timeout=300)
        self.guild_id = int(guild_id)
        self.add_item(WelcomeThemeSelect(self, current_key))

    @discord.ui.button(label="현재 테마 미리보기", emoji="🪄", style=discord.ButtonStyle.primary, row=1)
    async def preview(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await _safe_interaction_message(interaction, "🌱 서버 안에서만 미리볼 수 있어요.")
            return
        settings = _guild_settings(self.world_data, self.guild_id)
        await interaction.response.send_message(
            embed=_welcome_embed(
                interaction.user,
                int(settings.get("days", 7) or 7),
                str(settings.get("theme", "sprout")),
                settings=settings,
            ),
            ephemeral=True,
        )


class ErrorRecoveryView(CuteOwnedView):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        world_data: Dict[str, Any],
        save_data: Any,
        guide: Sequence[Dict[str, Any]],
        command: Optional[commands.Command] = None,
    ) -> None:
        super().__init__(owner_id, world_data, save_data, timeout=180)
        self.bot = bot
        self.guide = guide
        self.command = command
        self.retry_input.disabled = command is None

    @discord.ui.button(label="입력해서 다시 실행", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def retry_input(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.command is None:
            await _safe_interaction_message(interaction, "🍃 다시 실행할 명령을 찾지 못했어요.")
            return
        await interaction.response.send_modal(
            UniversalCommandModal(self.bot, self.owner_id, self.command, self.world_data, self.save_data)
        )

    @discord.ui.button(label="명령어 찾기", emoji="🔎", style=discord.ButtonStyle.secondary, row=0)
    async def catalog(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=_catalog_embed(self.bot, self.guide, "all", 0),
            view=CommandCatalogView(
                self.bot, interaction.user.id, self.world_data, self.save_data, self.guide,
                category_id="all", page=0,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="게임센터", emoji="🎮", style=discord.ButtonStyle.secondary, row=0)
    async def game(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, "게임")


async def _cleanup_newcomers_for_guild(
    guild: discord.Guild,
    world_data: Dict[str, Any],
    save_data: Any,
) -> int:
    settings = _guild_settings(world_data, guild.id)
    try:
        role = guild.get_role(int(settings.get("role_id", 0) or 0))
    except (TypeError, ValueError):
        role = None
    if role is None or str(settings.get("role_mode", "temporary")) != "temporary":
        return 0
    cutoff = discord.utils.utcnow() - timedelta(days=max(1, min(30, int(settings.get("days", 7) or 7))))
    removed = 0
    for member in list(role.members):
        if member.bot:
            continue
        joined_at = member.joined_at
        if joined_at is None or joined_at > cutoff:
            continue
        try:
            await member.remove_roles(role, reason="ABADDON 새싹 기간 종료")
            removed += 1
        except (discord.Forbidden, discord.HTTPException):
            continue
    if removed:
        save_data()
    return removed


def register_v711_cute_interactions(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data: Any,
    command_guide_categories: List[Dict[str, Any]],
) -> None:
    """새싹 역할·환영 패널·전체 명령어 버튼 실행 UI를 등록합니다."""

    server_category = next((item for item in command_guide_categories if item.get("id") == "server"), None)
    if server_category is not None:
        rows = server_category.setdefault("commands", [])
        for row in (
            "!귀여운메뉴 / !명령패널",
            "!새싹설정 [ON/OFF/기간 숫자/환영채널/아이콘 켜기/아이콘 끄기/테마 이름]",
            "!환영테마 [목록/미리보기/테마 이름]",
            "!새싹역할설치",
            "!새싹정리",
        ):
            if row not in rows:
                rows.append(row)

    async def cute_help_callback(ctx: commands.Context, *, 검색어: str = None) -> None:
        query = str(검색어 or "").strip()
        category_id = "all"
        embed = _catalog_embed(bot, command_guide_categories, category_id, 0, query=query)
        view = CommandCatalogView(
            bot,
            ctx.author.id,
            world_data,
            save_data,
            command_guide_categories,
            category_id=category_id,
            page=0,
            query=query,
        )
        await ctx.send(embed=embed, view=view)

    async def cute_beginner_callback(ctx: commands.Context) -> None:
        await ctx.send(
            embed=_beginner_embed(),
            view=BeginnerQuickView(bot, ctx.author.id, world_data, save_data, command_guide_categories),
        )

    help_command = bot.get_command("명령어")
    if help_command is not None:
        help_command.callback = cute_help_callback
        help_command.help = "모든 기존 명령을 카테고리·검색·버튼 실행으로 이용합니다."

    beginner_command = bot.get_command("처음")
    if beginner_command is not None:
        beginner_command.callback = cute_beginner_callback
        beginner_command.help = "귀여운 버튼형 초보자 시작 패널을 엽니다."

    @bot.command(name="귀여운메뉴", aliases=["명령패널", "말랑메뉴", "버튼명령어"], help="귀여운 전체 명령어 실행 패널을 엽니다.")
    async def cute_menu(ctx: commands.Context) -> None:
        await cute_help_callback(ctx)

    @bot.command(name="새싹설정", aliases=["신입설정"], help="신규 멤버 새싹 역할과 환영 메시지를 설정합니다.")
    async def newcomer_settings(ctx: commands.Context, *, 옵션: str = "") -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("🌱 이 설정은 서버 안에서만 사용할 수 있어요.")
            return
        if not _can_manage_guild(ctx.author):
            await ctx.send("🔒 서버 관리 권한이 있는 생존자만 새싹 설정을 바꿀 수 있어요.")
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        raw = str(옵션 or "").strip()
        if raw:
            tokens = raw.split()
            action = tokens[0].casefold()
            if action in {"켜기", "on", "활성화"}:
                settings["enabled"] = True
            elif action in {"끄기", "off", "비활성화"}:
                settings["enabled"] = False
            elif action == "기간" and len(tokens) >= 2:
                try:
                    settings["days"] = max(1, min(30, int(tokens[1])))
                except ValueError:
                    await ctx.send("🫧 기간은 `!새싹설정 기간 7`처럼 1~30 사이 숫자로 적어주세요.")
                    return
            elif action in {"환영채널", "채널"}:
                settings["welcome_channel_id"] = ctx.channel.id
            elif action == "아이콘" and len(tokens) >= 2:
                settings["role_icon"] = tokens[1].casefold() in {"켜기", "on", "활성화"}
            elif action in {"역할", "역할지급"} and len(tokens) >= 2:
                settings["role_enabled"] = tokens[1].casefold() in {"켜기", "on", "활성화"}
            elif action in {"역할모드", "모드"} and len(tokens) >= 2:
                mode = tokens[1].casefold()
                settings["role_mode"] = "permanent" if mode in {"영구", "permanent", "자동"} else "temporary"
            elif action == "메시지" and len(tokens) >= 2:
                settings["welcome_message"] = tokens[1].casefold() in {"켜기", "on", "활성화"}
            elif action in {"테마", "theme"} and len(tokens) >= 2:
                theme_key = _resolve_theme_key(" ".join(tokens[1:]))
                if theme_key is None:
                    await ctx.send("🎨 알 수 없는 테마예요. `!환영테마 목록`에서 이름을 확인해주세요.")
                    return
                settings["theme"] = theme_key
            else:
                await ctx.send(
                    "🌿 사용법: `!새싹설정 ON`, `!새싹설정 OFF`, `!새싹설정 기간 7`, "
                    "`!새싹설정 환영채널`, `!새싹설정 아이콘 켜기`, `!새싹설정 역할 켜기`, "
                    "`!새싹설정 역할모드 임시/영구`, `!새싹설정 메시지 끄기`, `!새싹설정 테마 아포칼립스`"
                )
                return
            save_data()

        role = None
        try:
            role = ctx.guild.get_role(int(settings.get("role_id", 0) or 0))
        except (TypeError, ValueError):
            role = None
        embed = discord.Embed(
            title="🌱 새싹 환영 설정",
            description="신규 멤버에게 귀여운 새싹 역할과 버튼형 시작 안내를 제공합니다.",
            colour=discord.Colour.from_rgb(124, 209, 154),
        )
        embed.add_field(name="상태", value="✅ 켜짐" if settings["enabled"] else "⏸️ 꺼짐", inline=True)
        embed.add_field(name="유지 기간", value=f"**{settings['days']}일**", inline=True)
        embed.add_field(name="역할", value=role.mention if role else "아직 설치되지 않음", inline=True)
        embed.add_field(name="역할 지급", value="✅ 사용" if settings.get("role_enabled", True) else "⏸️ 미사용", inline=True)
        embed.add_field(name="역할 모드", value="영구 자동 역할" if settings.get("role_mode") == "permanent" else f"임시 {settings['days']}일", inline=True)
        channel = _find_welcome_channel(ctx.guild, settings)
        embed.add_field(name="환영 채널", value=channel.mention if channel else "사용 가능한 채널 없음", inline=True)
        selected_theme = _welcome_theme(settings)
        embed.add_field(
            name="역할 아이콘",
            value=f"{selected_theme['role_emoji']} 사용" if settings["role_icon"] else "사용 안 함",
            inline=True,
        )
        embed.add_field(name="환영 메시지", value="💌 전송" if settings["welcome_message"] else "전송 안 함", inline=True)
        embed.add_field(name="환영 테마", value=_theme_name(settings), inline=True)
        embed.add_field(
            name="관리 명령",
            value="`!환영테마` · `!새싹역할설치` · `!새싹정리` · `!새싹설정 기간 7` · `!새싹설정 환영채널`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @bot.command(name="환영테마", aliases=["새싹테마", "신입테마"], help="신규 멤버 환영 패널 테마를 고르고 미리봅니다.")
    async def welcome_theme(ctx: commands.Context, *, 선택: str = "") -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("🎨 환영 테마는 서버 안에서만 설정할 수 있어요.")
            return
        if not _can_manage_guild(ctx.author):
            await ctx.send("🔒 서버 관리 권한이 있는 생존자만 환영 테마를 바꿀 수 있어요.")
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        raw = str(선택 or "").strip()
        lowered = raw.casefold()
        if lowered.startswith("미리보기") or lowered.startswith("preview"):
            requested = raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1)) > 1 else str(settings.get("theme", "sprout"))
            theme_key = _resolve_theme_key(requested) or str(settings.get("theme", "sprout"))
            await ctx.send(embed=_welcome_embed(ctx.author, int(settings.get("days", 7) or 7), theme_key, settings=settings))
            return
        if raw and lowered not in {"목록", "list", "설정", "선택"}:
            theme_key = _resolve_theme_key(raw)
            if theme_key is None:
                await ctx.send("🎨 알 수 없는 테마예요. `!환영테마 목록`에서 고를 수 있는 이름을 확인해주세요.")
                return
            settings["theme"] = theme_key
            save_data()
            try:
                role = ctx.guild.get_role(int(settings.get("role_id", 0) or 0))
            except (TypeError, ValueError):
                role = None
            if role is not None:
                try:
                    await _ensure_newcomer_role(ctx.guild, settings)
                    save_data()
                except (discord.Forbidden, discord.HTTPException, TypeError):
                    pass
        await ctx.send(
            embed=_theme_control_embed(settings),
            view=WelcomeThemeView(ctx.author.id, ctx.guild.id, world_data, save_data, str(settings.get("theme", "sprout"))),
        )

    @bot.command(name="새싹역할설치", aliases=["신입역할설치"], help="신규 멤버용 새싹 역할과 역할 아이콘을 설치합니다.")
    async def install_newcomer_role(ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("🌱 서버 안에서만 설치할 수 있어요.")
            return
        if not _can_manage_guild(ctx.author):
            await ctx.send("🔒 서버 관리 권한이 필요해요.")
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        settings["role_mode"] = "temporary"
        settings["role_enabled"] = True
        settings["role_created_by_abaddon"] = True
        settings["role_id"] = 0
        try:
            role = await _ensure_newcomer_role(ctx.guild, settings, force_recreate=True)
        except (discord.Forbidden, discord.HTTPException) as exc:
            await ctx.send(f"🫧 역할을 만들지 못했어요. 봇의 **역할 관리** 권한과 역할 순서를 확인해주세요. `{type(exc).__name__}`")
            return
        if role is None:
            await ctx.send("🫧 봇에게 **역할 관리** 권한이 없거나 봇 역할이 너무 아래에 있어요.")
            return
        save_data()
        await ctx.send(
            f"🌱 새싹 역할 설치 완료! {role.mention}\n"
            "역할 아이콘 기능을 지원하는 서버에서는 이름 옆에 🌱 아이콘이 표시됩니다."
        )

    @bot.command(name="새싹정리", aliases=["신입정리"], help="유지 기간이 지난 새싹 역할을 즉시 정리합니다.")
    async def cleanup_newcomer_command(ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("🌱 서버 안에서만 사용할 수 있어요.")
            return
        if not _can_manage_guild(ctx.author):
            await ctx.send("🔒 서버 관리 권한이 필요해요.")
            return
        removed = await _cleanup_newcomers_for_guild(ctx.guild, world_data, save_data)
        await ctx.send(f"🧹 새싹 정리 완료! 기간이 지난 역할 **{removed}개**를 정리했어요. ✨")

    async def handle_member_join(member: discord.Member) -> None:
        if member.bot:
            return
        settings = _guild_settings(world_data, member.guild.id)
        if not settings.get("enabled", True):
            return
        role = None
        try:
            if settings.get("role_enabled", True):
                role = await _ensure_newcomer_role(member.guild, settings)
                if role is not None and role not in member.roles:
                    await member.add_roles(role, reason="ABADDON v7.2.0 통합 신규 생존자 역할")
            legacy = world_data.setdefault("server_management", {}).setdefault(str(member.guild.id), {})
            legacy["autorole_id"] = int(settings.get("role_id", 0) or 0) if settings.get("role_enabled", True) else 0
            save_data()
        except (discord.Forbidden, discord.HTTPException, TypeError) as exc:
            print(f"[새싹 역할 부여 실패] guild={member.guild.id} member={member.id} {type(exc).__name__}: {exc}", flush=True)

        if not settings.get("welcome_message", True):
            return
        channel = _find_welcome_channel(member.guild, settings)
        if channel is None:
            return
        try:
            await channel.send(
                content=member.mention,
                embed=_welcome_embed(
                    member,
                    int(settings.get("days", 7) or 7),
                    str(settings.get("theme", "sprout")),
                    settings=settings,
                ),
                view=WelcomeQuickView(bot, member.id, world_data, save_data, command_guide_categories),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[새싹 환영 전송 실패] guild={member.guild.id} channel={getattr(channel, 'id', 0)} {type(exc).__name__}: {exc}", flush=True)

    # v7.2.0: 기존 SERVER GUARD 입장 리스너 하나에서만 호출하여 메시지/역할 중복을 방지합니다.
    bot.v720_unified_member_join = handle_member_join  # type: ignore[attr-defined]

    @tasks.loop(hours=1)
    async def cleanup_loop() -> None:
        for guild in list(bot.guilds):
            settings = _guild_settings(world_data, guild.id)
            if not settings.get("enabled", True):
                continue
            try:
                await _cleanup_newcomers_for_guild(guild, world_data, save_data)
            except Exception as exc:
                print(f"[새싹 자동 정리 실패] guild={guild.id} {type(exc).__name__}: {exc}", flush=True)

    @cleanup_loop.before_loop
    async def before_cleanup_loop() -> None:
        await bot.wait_until_ready()

    async def start_cleanup_loop() -> None:
        if not cleanup_loop.is_running():
            cleanup_loop.start()

    if not hasattr(bot, "_v711_cleanup_loop"):
        bot._v711_cleanup_loop = cleanup_loop  # type: ignore[attr-defined]
        bot.add_listener(start_cleanup_loop, "on_ready")

    def error_view_factory(owner_id: int, command: Optional[commands.Command] = None) -> ErrorRecoveryView:
        return ErrorRecoveryView(bot, owner_id, world_data, save_data, command_guide_categories, command)

    def sync_legacy_welcome(guild_id: int, **changes: Any) -> Dict[str, Any]:
        settings = _guild_settings(world_data, guild_id)
        legacy = world_data.setdefault("server_management", {}).setdefault(str(guild_id), {})
        for key, value in changes.items():
            settings[key] = value
            if key in {"welcome_channel_id", "welcome_notice_channel_id", "welcome_rules_channel_id", "welcome_register_channel_id"}:
                legacy[key] = value
            elif key == "role_id":
                legacy["autorole_id"] = value
        save_data()
        return settings

    async def unified_preview(ctx: commands.Context) -> None:
        settings = _guild_settings(world_data, ctx.guild.id)
        await ctx.send(
            embed=_welcome_embed(ctx.author, int(settings.get("days", 7) or 7), str(settings.get("theme", "sprout")), settings=settings),
            view=WelcomeQuickView(bot, ctx.author.id, world_data, save_data, command_guide_categories),
        )

    bot.v720_sync_welcome = sync_legacy_welcome  # type: ignore[attr-defined]
    bot.v720_welcome_preview = unified_preview  # type: ignore[attr-defined]
    bot.v711_error_view_factory = error_view_factory  # type: ignore[attr-defined]
    bot.v711_command_catalog_count = lambda: len(_walk_commands(bot))  # type: ignore[attr-defined]
    bot.v711_newcomer_settings = lambda guild_id: _guild_settings(world_data, guild_id)  # type: ignore[attr-defined]
