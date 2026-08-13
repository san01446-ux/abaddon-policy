from __future__ import annotations

import asyncio
import hashlib
import random
import re
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks

from apocalypse_bot.commands import v780_server_disaster as disaster_core
from apocalypse_bot.core.rate_limit_guard import should_pause_nonessential

VERSION = "7.9.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
AUTO_CHECK_MINUTES = 3
AUTO_DELAY_MIN_SECONDS = 3 * 60 * 60
AUTO_DELAY_MAX_SECONDS = 8 * 60 * 60
DISASTER_DURATION_SECONDS = 6 * 60 * 60
MAX_CONTEXT_ROWS = 5000

WEATHER_STATES: Dict[str, Dict[str, Any]] = {
    "clear": {"name": "잔잔한 회색 하늘", "emoji": "☁️", "risk": "낮음", "text": "시야와 이동로가 비교적 안정적입니다.", "target_mult": 0.94},
    "rain": {"name": "산성비 전선", "emoji": "🌧️", "risk": "주의", "text": "금속 장비와 노출된 보급품이 빠르게 손상됩니다.", "target_mult": 1.05},
    "storm": {"name": "번개 폭풍", "emoji": "⛈️", "risk": "위험", "text": "통신과 전력망이 불규칙하게 끊어집니다.", "target_mult": 1.13},
    "dust": {"name": "검은 모래폭풍", "emoji": "🌪️", "risk": "위험", "text": "시야가 짧아지고 외곽 이동로가 사라집니다.", "target_mult": 1.12},
    "freeze": {"name": "빙결 한파", "emoji": "❄️", "risk": "위험", "text": "배관과 이동 장비가 얼어붙고 체온 유지가 어려워집니다.", "target_mult": 1.11},
    "heat": {"name": "폐열 폭염", "emoji": "🌡️", "risk": "주의", "text": "발전 시설 과열과 탈수 위험이 증가합니다.", "target_mult": 1.07},
    "ash": {"name": "화산재 낙진", "emoji": "🌋", "risk": "위험", "text": "호흡기와 정수 설비에 재가 쌓입니다.", "target_mult": 1.12},
    "radiation": {"name": "방사성 비구름", "emoji": "☢️", "risk": "극심", "text": "야외 체류와 오염 표본 취급에 강한 보호가 필요합니다.", "target_mult": 1.20},
    "fog": {"name": "적색 안개", "emoji": "🌫️", "risk": "위험", "text": "센서 오작동과 방향 상실 보고가 이어집니다.", "target_mult": 1.10},
    "magnetic": {"name": "전자기 폭주", "emoji": "🧲", "risk": "극심", "text": "무전기와 자동화 장치가 불안정하게 재부팅됩니다.", "target_mult": 1.18},
}

EXTRA_DISASTERS: Dict[str, Dict[str, Any]] = {
    "supply_blockade": {
        "name": "보급로 봉쇄", "emoji": "🚧",
        "summary": "주요 보급로가 잔해와 적대 세력에 막혔습니다. 정찰과 방어, 우회로 수리가 필요합니다.",
        "items": {"고철": 8, "나무": 6, "식량": 1}, "missions": ("정찰", "수리", "방어"),
        "buff": "보급로 재개통", "buff_text": "납품과 파밍 복귀 동선이 안정됩니다.",
    },
    "quarantine_breach": {
        "name": "격리벽 붕괴", "emoji": "🧱",
        "summary": "오염 격리벽 일부가 무너졌습니다. 틈을 봉쇄하고 잔류 생존자를 구조해야 합니다.",
        "items": {"고철": 10, "오염표본": 38, "약초": 9}, "missions": ("수리", "구조", "방어"),
        "buff": "격리선 복구", "buff_text": "오염 구역 탐색의 안전 보정이 강화됩니다.",
    },
    "food_spoilage": {
        "name": "식량 저장고 부패", "emoji": "🥫",
        "summary": "저장고 온도 제어가 무너지며 식량이 상하기 시작했습니다. 분류와 냉각, 대체 보급이 필요합니다.",
        "items": {"식량": 1, "약초": 7, "폐허회로": 28}, "missions": ("수리", "구조", "정찰"),
        "buff": "저장 체계 개선", "buff_text": "생활 보급품 정산과 보관이 안정됩니다.",
    },
    "drone_swarm": {
        "name": "오작동 드론 군집", "emoji": "🤖",
        "summary": "폐기된 경비 드론이 대피소를 적으로 식별했습니다. 통신 교란과 방어 사격이 필요합니다.",
        "items": {"폐허회로": 32, "고철": 9, "설계도조각": 48}, "missions": ("방어", "수리", "정찰"),
        "buff": "드론 식별망", "buff_text": "전파 탐색과 현장 정찰 정보가 개선됩니다.",
    },
    "tunnel_collapse": {
        "name": "지하 통로 붕괴", "emoji": "🪨",
        "summary": "지하 연결 통로가 무너져 구조 신호가 고립됐습니다. 잔해 제거와 생존자 탐색이 필요합니다.",
        "items": {"광석": 7, "고철": 8, "식량": 1}, "missions": ("구조", "수리", "정찰"),
        "buff": "지하 통로 확보", "buff_text": "광산과 화물역 이동이 안정됩니다.",
    },
    "plague": {
        "name": "변이 감염병 확산", "emoji": "🦠",
        "summary": "원인 불명의 변이성 감염이 퍼지고 있습니다. 격리, 표본 분석, 치료 물자 확보가 필요합니다.",
        "items": {"약초": 12, "오염표본": 44, "식량": 1}, "missions": ("구조", "정찰", "수리"),
        "buff": "의료 대응 체계", "buff_text": "회복과 구조 활동의 안정성이 높아집니다.",
    },
    "reactor_leak": {
        "name": "소형 원자로 누출", "emoji": "☢️",
        "summary": "보조 발전 구역에서 방사선 누출이 감지됐습니다. 냉각 회로와 차폐판을 동시에 복구해야 합니다.",
        "items": {"폐허회로": 38, "고철": 11, "광석": 8}, "missions": ("수리", "방어", "정찰"),
        "buff": "안정화 전력", "buff_text": "기지와 공방의 전력 공급이 안정됩니다.",
    },
    "refugee_wave": {
        "name": "대규모 피난민 유입", "emoji": "🧳",
        "summary": "외곽 거점이 붕괴하며 피난민이 몰려왔습니다. 등록, 치료, 식량 배급이 필요합니다.",
        "items": {"식량": 1, "약초": 8, "나무": 6}, "missions": ("구조", "정찰", "방어"),
        "buff": "공동체 결속", "buff_text": "서버 공동 활동의 참여 보정이 강화됩니다.",
    },
}

disaster_core.DISASTERS.update(EXTRA_DISASTERS)

NOTIFICATION_TOPICS: Dict[str, Tuple[str, str]] = {
    "patch": ("📣", "패치 공지"), "disaster": ("🚨", "서버 재난"), "weather": ("🌦️", "재난 기상"),
    "worldboss": ("🌋", "월드보스"), "guild": ("🏰", "길드 모집"), "raid": ("👹", "길드 레이드"),
    "market": ("📈", "거래·시장"), "quiz": ("🧠", "퀴즈"), "event": ("🎉", "서버 이벤트"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    return disaster_core._parse(value)


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    return disaster_core._safe_int(value, default, minimum)


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v790_operations", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v790_operations"] = root
    root.setdefault("schema_version", SCHEMA_VERSION)
    root.setdefault("guilds", {})
    root.setdefault("intake", [])
    root.setdefault("stats", {"context_actions": 0, "suggestions": 0, "highlights": 0, "temp_rooms": 0, "deletions": 0})
    root["schema_version"] = SCHEMA_VERSION
    return root


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(guild_id)] = state
    state.setdefault("disaster", {"auto_enabled": True, "channel_id": 0, "next_auto_at": "", "last_announcement_id": 0})
    state.setdefault("temp_voice", {"enabled": False, "lobby_id": 0, "category_id": 0, "rooms": {}})
    state.setdefault("suggestions", [])
    state.setdefault("roadmap", {})
    state.setdefault("highlight", {"enabled": False, "channel_id": 0, "emoji": "⭐", "threshold": 3, "posts": {}})
    state.setdefault("context_evidence", [])
    return state


def _schedule_next(state: MutableMapping[str, Any], *, base: Optional[datetime] = None) -> datetime:
    rng = secrets.SystemRandom()
    seconds = rng.randint(AUTO_DELAY_MIN_SECONDS, AUTO_DELAY_MAX_SECONDS)
    due = (base or _now()) + timedelta(seconds=seconds)
    disaster_settings = state.setdefault("disaster", {})
    disaster_settings["next_auto_at"] = _iso(due)
    return due


def _weather_key_for(seed: int, disaster_key: str) -> str:
    rng = random.Random(seed ^ int(hashlib.sha256(disaster_key.encode("utf-8")).hexdigest()[:12], 16))
    keys = list(WEATHER_STATES)
    weights = [20, 14, 11, 9, 8, 9, 7, 4, 10, 8]
    return rng.choices(keys, weights=weights, k=1)[0]


def _new_event_with_weather(guild_id: int, member_count: int, forced_key: Optional[str] = None) -> Dict[str, Any]:
    event = _ORIGINAL_NEW_EVENT(guild_id, member_count, forced_key)
    event["weather"] = _weather_key_for(_safe_int(event.get("seed"), secrets.randbits(32)), str(event.get("key")))
    weather = WEATHER_STATES[event["weather"]]
    event["target"] = max(1, int(round(_safe_int(event.get("target"), 1) * float(weather.get("target_mult", 1.0)))))
    event["ends_at"] = _iso(_now() + timedelta(seconds=DISASTER_DURATION_SECONDS))
    return event


_ORIGINAL_NEW_EVENT = disaster_core._new_event
disaster_core._new_event = _new_event_with_weather


def _disaster_embed(event: Mapping[str, Any], *, auto: bool = False) -> discord.Embed:
    base = disaster_core._public_event_embed(event)
    weather_key = str(event.get("weather") or "clear")
    weather = WEATHER_STATES.get(weather_key, WEATHER_STATES["clear"])
    base.title = f"{base.title} · {weather['emoji']} {weather['name']}"
    base.add_field(name="🌦️ 재난 기상", value=f"**{weather['risk']}** · {weather['text']}", inline=False)
    base.set_footer(text="아래 버튼으로 현장 역할 참여 또는 물자 지원 · 같은 행동은 잠금으로 한 번만 정산")
    if auto:
        base.description = "📡 **자동 감시망이 새로운 비상 신호를 포착했습니다.**\n" + str(base.description or "")
    return base


def _active_event(world_data: MutableMapping[str, Any], guild_id: int) -> Tuple[MutableMapping[str, Any], MutableMapping[str, Any]]:
    state = disaster_core._guild_state(world_data, guild_id)
    event = disaster_core._active_event(state)
    return state, event


def _find_announcement_channel(guild: discord.Guild, state: Mapping[str, Any]) -> Optional[discord.TextChannel]:
    settings = state.get("disaster") if isinstance(state.get("disaster"), dict) else {}
    channel_id = _safe_int(settings.get("channel_id"), 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        return channel
    keywords = ("비상", "방송", "재난", "공지", "업데이트", "작전")
    for row in guild.text_channels:
        if any(key in row.name for key in keywords):
            return row
    return guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)


def _user_notifications(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    prefs = user.setdefault("notification_center", {})
    if not isinstance(prefs, dict):
        prefs = {}
        user["notification_center"] = prefs
    prefs.setdefault("topics", {key: False for key in NOTIFICATION_TOPICS})
    prefs.setdefault("mode", "channel")
    topics = prefs.get("topics")
    if not isinstance(topics, dict):
        topics = {key: False for key in NOTIFICATION_TOPICS}
        prefs["topics"] = topics
    for key in NOTIFICATION_TOPICS:
        topics.setdefault(key, False)
    return prefs


def _has_manage_guild(member: discord.abc.User) -> bool:
    return isinstance(member, discord.Member) and (member.guild_permissions.administrator or member.guild_permissions.manage_guild)


def _format_remaining(value: Any) -> str:
    due = _parse(value)
    if due is None:
        return "미정"
    return disaster_core._format_seconds(max(0, int((due - _now()).total_seconds())))


class DisasterDonationModal(discord.ui.Modal, title="📦 공동 재난 물자 지원"):
    item = discord.ui.TextInput(label="자원 이름", placeholder="예: 고철, 식량, 약초", max_length=30)
    amount = discord.ui.TextInput(label="수량", placeholder="예: 20", max_length=12)

    def __init__(self, handler: Callable[[discord.Interaction, str, int], Any]):
        super().__init__(timeout=300)
        self.handler = handler

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("⚠️ 수량은 숫자로 입력해주세요.", ephemeral=True)
            return
        await self.handler(interaction, str(self.item.value).strip(), amount)


class DisasterPanelView(discord.ui.View):
    def __init__(self, role_handler: Callable[[discord.Interaction, str], Any], delivery_handler: Callable[[discord.Interaction, str, int], Any]):
        super().__init__(timeout=None)
        self.role_handler = role_handler
        self.delivery_handler = delivery_handler

    async def _role(self, interaction: discord.Interaction, role: str) -> None:
        await self.role_handler(interaction, role)

    @discord.ui.button(label="정찰", emoji="🧭", style=discord.ButtonStyle.primary, custom_id="abaddon:v790:disaster:scout")
    async def scout(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._role(interaction, "scout")

    @discord.ui.button(label="구조", emoji="🩹", style=discord.ButtonStyle.success, custom_id="abaddon:v790:disaster:rescue")
    async def rescue(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._role(interaction, "rescue")

    @discord.ui.button(label="수리", emoji="🔧", style=discord.ButtonStyle.secondary, custom_id="abaddon:v790:disaster:repair")
    async def repair(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._role(interaction, "repair")

    @discord.ui.button(label="방어", emoji="🛡️", style=discord.ButtonStyle.danger, custom_id="abaddon:v790:disaster:defend")
    async def defend(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._role(interaction, "defend")

    @discord.ui.button(label="물자 지원", emoji="📦", style=discord.ButtonStyle.success, custom_id="abaddon:v790:disaster:donate")
    async def donate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(DisasterDonationModal(self.delivery_handler))


class NotificationSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, owner_id: int, user: MutableMapping[str, Any], save_data: Callable[[], None]):
        self.bot = bot
        self.owner_id = int(owner_id)
        self.user = user
        self.save_data = save_data
        prefs = _user_notifications(user)
        topics = prefs["topics"]
        options = [
            discord.SelectOption(label=label, value=key, emoji=emoji, default=bool(topics.get(key)), description="선택하면 알림을 켜거나 끕니다.")
            for key, (emoji, label) in NOTIFICATION_TOPICS.items()
        ]
        super().__init__(placeholder="받을 알림을 선택하세요", min_values=0, max_values=len(options), options=options, custom_id="abaddon:v790:notifications")

    async def callback(self, interaction: discord.Interaction) -> None:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("⚠️ 이 알림 메뉴는 명령을 실행한 사용자만 변경할 수 있습니다.", ephemeral=True)
            return
        prefs = _user_notifications(self.user)
        selected = set(self.values)
        for key in NOTIFICATION_TOPICS:
            prefs["topics"][key] = key in selected
        # 기존 개인 세계 이벤트 알림 설정을 복제하지 않고 같은 선택값으로 연결합니다.
        legacy = self.user.setdefault("v639", {})
        if isinstance(legacy, dict):
            alerts = legacy.setdefault("alerts", {})
            if isinstance(alerts, dict):
                alerts["weather"] = bool(prefs["topics"].get("weather"))
                alerts["supply"] = bool(prefs["topics"].get("event"))
                alerts["smuggle"] = bool(prefs["topics"].get("event"))
                alerts.setdefault("mode", "dm")
        self.save_data()
        lines = [f"{emoji} {label}" for key, (emoji, label) in NOTIFICATION_TOPICS.items() if prefs["topics"].get(key)]
        await interaction.response.send_message("✅ 알림 설정 저장\n" + (" · ".join(lines) if lines else "모든 선택 알림이 꺼졌습니다."), ephemeral=True)


class NotificationView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, user: MutableMapping[str, Any], save_data: Callable[[], None]):
        super().__init__(timeout=300)
        self.add_item(NotificationSelect(bot, owner_id, user, save_data))


class SuggestionModal(discord.ui.Modal, title="💡 공개 건의 등록"):
    subject = discord.ui.TextInput(label="제목", max_length=80, placeholder="추가하거나 개선할 기능")
    body = discord.ui.TextInput(label="내용", style=discord.TextStyle.paragraph, max_length=1000, placeholder="필요한 이유와 기대하는 동작을 적어주세요.")

    def __init__(self, handler: Callable[[discord.Interaction, str, str], Any]):
        super().__init__(timeout=600)
        self.handler = handler

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.handler(interaction, str(self.subject.value), str(self.body.value))


class SuggestionOpenView(discord.ui.View):
    def __init__(self, handler: Callable[[discord.Interaction, str, str], Any]):
        super().__init__(timeout=300)
        self.handler = handler

    @discord.ui.button(label="건의 작성", emoji="💡", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(SuggestionModal(self.handler))


class SuggestionVoteView(discord.ui.View):
    def __init__(self, suggestion_id: str, vote_handler: Callable[[discord.Interaction, str, str], Any]):
        super().__init__(timeout=900)
        self.suggestion_id = suggestion_id
        self.vote_handler = vote_handler

    @discord.ui.button(label="찬성", emoji="👍", style=discord.ButtonStyle.success)
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.vote_handler(interaction, self.suggestion_id, "up")

    @discord.ui.button(label="보류", emoji="🤔", style=discord.ButtonStyle.secondary)
    async def hold(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.vote_handler(interaction, self.suggestion_id, "hold")

    @discord.ui.button(label="반대", emoji="👎", style=discord.ButtonStyle.danger)
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.vote_handler(interaction, self.suggestion_id, "down")


class OperationsHubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _show(self, interaction: discord.Interaction, title: str, text: str) -> None:
        await interaction.response.send_message(f"**{title}**\n{text}", ephemeral=True)

    @discord.ui.button(label="문의·신고", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="abaddon:v1850:ops:tickets")
    async def tickets(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show(interaction, "🎫 통합 접수", "간편 문의: `!문의패널`\n고급 접수: `!접수패널`\n공개 건의: `!건의`")

    @discord.ui.button(label="점검", emoji="🧪", style=discord.ButtonStyle.secondary, custom_id="abaddon:v1850:ops:tests")
    async def tests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show(interaction, "🧪 점검센터", "최신 패치: `!테스트 상세`\n시스템: `!시스템점검`\n운영: `!안정화검수`\nv7.9: `!790안정화검수`")

    @discord.ui.button(label="통계", emoji="📊", style=discord.ButtonStyle.success, custom_id="abaddon:v1850:ops:stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show(interaction, "📊 운영 분석", "기존 통계: `!서버통계`, `!운영대시보드`\n경제·콘텐츠 통합: `!운영분석`")

    @discord.ui.button(label="알림", emoji="🔔", style=discord.ButtonStyle.primary, custom_id="abaddon:v1850:ops:alerts")
    async def alerts(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show(interaction, "🔔 알림센터", "개인 통합 알림: `!알림센터`\n현재 설정: `!내알림`")

    @discord.ui.button(label="재난", emoji="🚨", style=discord.ButtonStyle.danger, custom_id="abaddon:v1850:ops:disaster")
    async def disaster(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._show(interaction, "🚨 자동 재난", "현황: `!재난상황`\n예보: `!재난예보`\n관리자 설정: `!재난자동`, `!재난채널`")


class TempVoiceControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="방 잠금", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="abaddon:v1850:voice:lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("현재 임시 분대방에서 `!분대방잠금`을 실행하세요.", ephemeral=True)

    @discord.ui.button(label="이름 변경", emoji="✏️", style=discord.ButtonStyle.primary, custom_id="abaddon:v1850:voice:rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("`!분대방이름 새 이름`으로 변경할 수 있습니다.", ephemeral=True)

    @discord.ui.button(label="인원 제한", emoji="👥", style=discord.ButtonStyle.success, custom_id="abaddon:v1850:voice:limit")
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("`!분대방인원 2~99`로 설정할 수 있습니다.", ephemeral=True)


def register_v790_operations_disaster(
    bot: commands.Bot,
    get_user: Callable[[Any], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
    add_season_points: Callable[[MutableMapping[str, Any], int], Any],
) -> None:
    if getattr(bot, "_abaddon_v790_registered", False):
        return
    bot._abaddon_v790_registered = True
    root = _root(world_data)

    # v18.5: public operations/temp-voice helper panels survive process restarts.
    # These views carry no per-message state, so stable custom IDs are safe globally.
    try:
        bot.add_view(OperationsHubView())
        bot.add_view(TempVoiceControlView())
    except ValueError:
        # Already registered by a hot reload / duplicate-safe boot path.
        pass

    for category_id, additions in {
        "life": (
            "!재난예보 / !재난날씨 / !재난기록 — 자동 재난 일정·기상·기록",
            "!알림센터 / !내알림 — 패치·재난·시장·길드 알림 통합 설정",
        ),
        "server": (
            "!운영통합센터 / !운영분석 — 문의·점검·통계·알림 통합",
            "!분대음성설정 / !하이라이트설정 — 임시 음성방·하이라이트 보드",
            "!건의 / !건의목록 / !로드맵 — 공개 건의와 개발 상태",
            "!790안정화검수 — v7.9 신규·수정 기능 전용 검사",
        ),
    }.items():
        category = next((row for row in guide if row.get("id") == category_id), None)
        if category is None:
            continue
        existing = "\n".join(map(str, category.get("commands", [])))
        for row in additions:
            if row.split(" — ", 1)[0] not in existing:
                category.setdefault("commands", []).append(row)
                existing += "\n" + row

    async def require_user_ctx(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 불러오지 못했습니다.")
            return None
        return user

    async def require_admin_ctx(ctx: commands.Context) -> bool:
        if ctx.guild is None or not _has_manage_guild(ctx.author):
            await ctx.send("⚠️ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    def current_event(guild_id: int) -> Tuple[MutableMapping[str, Any], MutableMapping[str, Any]]:
        return _active_event(world_data, guild_id)

    async def apply_role_interaction(interaction: discord.Interaction, role: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("⚠️ 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        user = get_user(interaction.user.id)
        if not isinstance(user, dict):
            await interaction.response.send_message("⚠️ 먼저 `!가입 생존자`로 등록해주세요.", ephemeral=True)
            return
        guild_id = int(interaction.guild.id)
        async with disaster_core._guild_lock(bot, guild_id):
            state, event = current_event(guild_id)
            if not event or event.get("status") != "active" or disaster_core._remaining(event) <= 0:
                await interaction.response.send_message("📭 현재 참여할 재난이 없습니다.", ephemeral=True)
                return
            row = disaster_core._contribution(event, interaction.user.id)
            cooldown = disaster_core._cooldown_remaining(row)
            if cooldown > 0:
                await interaction.response.send_message(f"⏳ 재정비 중 · {_format_remaining(_now() + timedelta(seconds=cooldown))}", ephemeral=True)
                return
            seed = int(hashlib.sha256(f"{event.get('id')}:{interaction.user.id}:{role}:{row.get('missions')}".encode()).hexdigest()[:16], 16)
            rng = random.Random(seed)
            power = max(1, _safe_int(calculate_user_power(user), 1))
            points = 28 + min(72, int(power ** 0.5)) + rng.randint(8, 34)
            info = disaster_core.DISASTERS.get(str(event.get("key")), disaster_core.DISASTERS["blackout"])
            preferred = {disaster_core.ROLE_ALIASES.get(str(raw), "") for raw in info.get("missions", ())}
            if role in preferred:
                points += 12
            remaining = max(0, _safe_int(event.get("target"), 1) - _safe_int(event.get("progress"), 0))
            applied = min(points, remaining)
            if applied <= 0:
                await interaction.response.send_message("✅ 공동 목표가 이미 완료되었습니다.", ephemeral=True)
                return
            event["progress"] = _safe_int(event.get("progress"), 0) + applied
            row["points"] = _safe_int(row.get("points"), 0) + applied
            row["missions"] = _safe_int(row.get("missions"), 0) + 1
            row["last_action_at"] = _iso()
            roles = row.setdefault("roles", {})
            roles[role] = _safe_int(roles.get(role), 0) + 1
            disaster_core._audit_event(event, "button_mission", user_id=str(interaction.user.id), role=role, points=applied)
            add_season_points(user, 1)
            finished = _safe_int(event.get("progress"), 0) >= _safe_int(event.get("target"), 1)
            if finished:
                disaster_core._finish_event(state, event)
                _schedule_next(_guild_state(world_data, guild_id), base=_now())
            save_data()
        route = f"{disaster_core.ROLE_LABELS.get(role, role)} → 🚧 진입 → 📡 상황 확인 → ✅ 기여 +{applied:,}"
        await interaction.response.send_message(route + ("\n🎉 공동 목표 달성 · `!재난보상`" if finished else ""), ephemeral=True)

    async def apply_delivery_interaction(interaction: discord.Interaction, item_raw: str, amount: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("⚠️ 서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        user = get_user(interaction.user.id)
        if not isinstance(user, dict):
            await interaction.response.send_message("⚠️ 먼저 `!가입 생존자`로 등록해주세요.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.response.send_message("⚠️ 1개 이상 입력해주세요.", ephemeral=True)
            return
        guild_id = int(interaction.guild.id)
        async with disaster_core._guild_lock(bot, guild_id):
            state, event = current_event(guild_id)
            if not event or event.get("status") != "active":
                await interaction.response.send_message("📭 현재 진행 중인 재난이 없습니다.", ephemeral=True)
                return
            info = disaster_core.DISASTERS.get(str(event.get("key")), disaster_core.DISASTERS["blackout"])
            multipliers = info.get("items", {})
            compact = str(item_raw).replace(" ", "")
            canonical = next((name for name in multipliers if name.replace(" ", "") == compact), None)
            if canonical is None:
                await interaction.response.send_message("⚠️ 현재 필요한 물자: " + " / ".join(multipliers), ephemeral=True)
                return
            current = disaster_core._read_amount(user, canonical)
            if current < amount:
                await interaction.response.send_message(f"⚠️ {canonical} 부족 · 보유 {current:,}", ephemeral=True)
                return
            per_item = max(1, _safe_int(multipliers.get(canonical), 1))
            remaining = max(0, _safe_int(event.get("target"), 1) - _safe_int(event.get("progress"), 0))
            accepted = min(amount, max(1, (remaining + per_item - 1) // per_item)) if remaining > 0 else 0
            if accepted <= 0:
                await interaction.response.send_message("✅ 목표가 이미 완료되어 물자를 차감하지 않았습니다.", ephemeral=True)
                return
            points = min(remaining, accepted * per_item)
            disaster_core._change_amount(user, canonical, -accepted)
            event["progress"] = _safe_int(event.get("progress"), 0) + points
            row = disaster_core._contribution(event, interaction.user.id)
            row["points"] = _safe_int(row.get("points"), 0) + points
            row["deliveries"] = _safe_int(row.get("deliveries"), 0) + 1
            disaster_core._audit_event(event, "button_delivery", user_id=str(interaction.user.id), item=canonical, amount=accepted, points=points)
            finished = _safe_int(event.get("progress"), 0) >= _safe_int(event.get("target"), 1)
            if finished:
                disaster_core._finish_event(state, event)
                _schedule_next(_guild_state(world_data, guild_id), base=_now())
            save_data()
        await interaction.response.send_message(f"📦 {canonical} {accepted:,}개 지원 → 공동 대응 +{points:,}" + ("\n🎉 목표 달성 · `!재난보상`" if finished else ""), ephemeral=True)

    disaster_view = DisasterPanelView(apply_role_interaction, apply_delivery_interaction)
    bot.add_view(disaster_view)

    async def send_disaster_panel(channel: discord.abc.Messageable, event: Mapping[str, Any], *, auto: bool = False) -> Optional[discord.Message]:
        try:
            return await channel.send(embed=_disaster_embed(event, auto=auto), view=DisasterPanelView(apply_role_interaction, apply_delivery_interaction))
        except (discord.Forbidden, discord.HTTPException):
            return None

    status_command = bot.get_command("재난상황")
    if status_command is not None:
        async def disaster_status_v790(ctx: commands.Context) -> None:
            if ctx.guild is None:
                await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
                return
            guild_id = int(ctx.guild.id)
            async with disaster_core._guild_lock(bot, guild_id):
                state, event = current_event(guild_id)
                if event and event.get("status") == "active" and disaster_core._remaining(event) <= 0:
                    disaster_core._finish_event(state, event, force=True)
                    _schedule_next(_guild_state(world_data, guild_id))
                    save_data()
                    event = {}
                if not event:
                    ops = _guild_state(world_data, guild_id)
                    settings = ops.get("disaster", {})
                    enabled = bool(settings.get("auto_enabled", True))
                    due = _format_remaining(settings.get("next_auto_at")) if enabled else "자동 발생 꺼짐"
                    await ctx.send(f"🕊️ 현재 공동 재난 없음\n📡 자동 감시망: **{'켜짐' if enabled else '꺼짐'}**\n🛰️ 다음 감시 예상: **{due}**\n관리자 설정: `!재난자동`, `!재난채널`")
                    return
                await send_disaster_panel(ctx.channel, event)
        status_command.callback = disaster_status_v790
        status_command.help = "현재 자동 발생 공동 재난을 버튼형 패널로 확인합니다."
        status_command.description = status_command.help

    missions_command = bot.get_command("재난임무")
    if missions_command is not None:
        async def disaster_missions_v790(ctx: commands.Context) -> None:
            if ctx.guild is None:
                await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
                return
            _, event = current_event(int(ctx.guild.id))
            if not event:
                await ctx.send("📭 진행 중인 재난이 없습니다. `!재난예보`를 확인하세요.")
                return
            await send_disaster_panel(ctx.channel, event)
        missions_command.callback = disaster_missions_v790

    @bot.command(name="재난예보", aliases=["재난감시", "비상예보"], help="자동 공동 재난의 다음 감시 일정과 설정을 확인합니다.")
    async def disaster_forecast(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        settings = state["disaster"]
        active = disaster_core._active_event(disaster_core._guild_state(world_data, int(ctx.guild.id)))
        channel = _find_announcement_channel(ctx.guild, state)
        embed = discord.Embed(title="📡 서버 재난 자동 감시망", colour=0xD65A31)
        embed.add_field(name="자동 발생", value="✅ 켜짐" if settings.get("auto_enabled", True) else "⛔ 꺼짐", inline=True)
        embed.add_field(name="공지 채널", value=channel.mention if channel else "미설정", inline=True)
        embed.add_field(name="다음 감시", value="현재 재난 진행 중" if active else _format_remaining(settings.get("next_auto_at")), inline=False)
        embed.add_field(name="기상 관측 범위", value=" · ".join(f"{row['emoji']} {row['name']}" for row in WEATHER_STATES.values()), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="재난날씨", aliases=["재난기상", "비상날씨"], help="현재 공동 재난에 결합된 환경 상태를 확인합니다.")
    async def disaster_weather(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        _, event = current_event(int(ctx.guild.id))
        if not event:
            await ctx.send("📭 진행 중인 재난 기상이 없습니다.")
            return
        weather = WEATHER_STATES.get(str(event.get("weather") or "clear"), WEATHER_STATES["clear"])
        await ctx.send(f"{weather['emoji']} **{weather['name']}** · 위험도 **{weather['risk']}**\n{weather['text']}\n남은 시간 **{disaster_core._format_seconds(disaster_core._remaining(event))}**")

    @bot.command(name="재난기록", aliases=["공동재난기록", "비상기록"], help="최근 공동 재난과 기상 기록을 확인합니다.")
    async def disaster_history(ctx: commands.Context, 페이지: int = 1) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        state = disaster_core._guild_state(world_data, int(ctx.guild.id))
        history = [row for row in state.get("history", []) if isinstance(row, dict)]
        page = max(1, int(페이지 or 1))
        per_page = 8
        chunk = list(reversed(history))[(page - 1) * per_page: page * per_page]
        if not chunk:
            await ctx.send("📭 표시할 공동 재난 기록이 없습니다.")
            return
        lines = []
        for row in chunk:
            info = disaster_core.DISASTERS.get(str(row.get("key")), disaster_core.DISASTERS["blackout"])
            weather = WEATHER_STATES.get(str(row.get("weather") or "clear"), WEATHER_STATES["clear"])
            result = "✅ 성공" if row.get("success") else "❌ 실패"
            lines.append(f"`{row.get('id','-')}` {info['emoji']} **{info['name']}** · {weather['emoji']} {weather['name']} · {result} · {_safe_int(row.get('progress')):,}/{_safe_int(row.get('target'),1):,}")
        await ctx.send(f"📚 **공동 재난 기록 · {page}페이지**\n" + "\n".join(lines))

    @bot.command(name="재난자동", aliases=["재난자동설정"], help="관리자가 자동 재난 발생을 켜거나 끕니다.")
    async def disaster_auto(ctx: commands.Context, 상태: str = "") -> None:
        if not await require_admin_ctx(ctx):
            return
        token = str(상태).strip().casefold()
        state = _guild_state(world_data, int(ctx.guild.id))
        settings = state["disaster"]
        if token in {"켜기", "켜짐", "on", "true", "1"}:
            settings["auto_enabled"] = True
            if not _parse(settings.get("next_auto_at")):
                _schedule_next(state)
        elif token in {"끄기", "꺼짐", "off", "false", "0"}:
            settings["auto_enabled"] = False
        else:
            await ctx.send(f"📡 자동 재난: **{'켜짐' if settings.get('auto_enabled', True) else '꺼짐'}**\n사용법: `!재난자동 ON/OFF`")
            return
        save_data()
        await ctx.send(f"✅ 자동 재난 발생을 **{'켰습니다' if settings['auto_enabled'] else '껐습니다'}**.")

    @bot.command(name="재난채널", aliases=["재난공지채널"], help="자동 공동 재난을 게시할 채널을 지정합니다.")
    async def disaster_channel(ctx: commands.Context, 채널: Optional[discord.TextChannel] = None) -> None:
        if not await require_admin_ctx(ctx):
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("⚠️ 텍스트 채널을 지정해주세요.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))
        state["disaster"]["channel_id"] = int(target.id)
        if not _parse(state["disaster"].get("next_auto_at")):
            _schedule_next(state)
        save_data()
        await ctx.send(f"✅ 자동 공동 재난 게시 채널을 {target.mention}으로 지정했습니다.")

    spawn_command = bot.get_command("재난발생")
    if spawn_command is not None:
        async def spawn_v790(ctx: commands.Context, *, 종류: str = "") -> None:
            if not await require_admin_ctx(ctx):
                return
            if ctx.guild is None:
                await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
                return
            guild_id = int(ctx.guild.id)
            key = disaster_core._event_key(종류) if 종류 else None
            if 종류 and key is None:
                names = " / ".join(str(info.get("name", code)) for code, info in list(disaster_core.DISASTERS.items())[:20])
                await ctx.send(f"⚠️ 재난 종류를 찾지 못했습니다. 사용 가능: {names}")
                return
            async with disaster_core._guild_lock(bot, guild_id):
                state = disaster_core._guild_state(world_data, guild_id)
                active = disaster_core._active_event(state)
                if active and active.get("status") == "active":
                    await ctx.send("⚠️ 이미 진행 중인 재난이 있습니다. 강제 종료 없이 새 재난을 덮어쓰지 않습니다.")
                    return
                event, _, _ = disaster_core.ensure_active(ctx.guild, force_key=key, force=True)
                disaster_core._audit_event(event, "admin_spawn", user_id=str(ctx.author.id))
                settings = _guild_state(world_data, guild_id)["disaster"]
                settings["next_auto_at"] = ""
                save_data()
            message = await send_disaster_panel(ctx.channel, event)
            if message:
                state = _guild_state(world_data, guild_id)
                state["disaster"]["last_announcement_id"] = int(message.id)
                save_data()
        spawn_command.callback = spawn_v790

    @tasks.loop(minutes=AUTO_CHECK_MINUTES)
    async def disaster_auto_loop() -> None:
        if should_pause_nonessential():
            return
        await bot.wait_until_ready()
        changed = False
        for guild in list(bot.guilds):
            guild_id = int(guild.id)
            state = _guild_state(world_data, guild_id)
            settings = state["disaster"]
            if not settings.get("auto_enabled", True):
                continue
            async with disaster_core._guild_lock(bot, guild_id):
                disaster_state = disaster_core._guild_state(world_data, guild_id)
                active = disaster_core._active_event(disaster_state)
                if active and active.get("status") == "active":
                    if disaster_core._remaining(active) <= 0:
                        disaster_core._finish_event(disaster_state, active, force=True)
                        _schedule_next(state)
                        changed = True
                    continue
                due = _parse(settings.get("next_auto_at"))
                if due is None:
                    _schedule_next(state)
                    changed = True
                    continue
                if due > _now():
                    continue
                event = disaster_core._new_event(guild_id, int(guild.member_count or 0), None)
                disaster_state["active"] = event
                disaster_state["stats"]["started"] = _safe_int(disaster_state["stats"].get("started"), 0) + 1
                disaster_core._audit_event(event, "auto_spawn", actor="scheduler")
                settings["next_auto_at"] = ""
                changed = True
            channel = _find_announcement_channel(guild, state)
            if channel:
                message = await send_disaster_panel(channel, event, auto=True)
                if message:
                    settings["last_announcement_id"] = int(message.id)
            # 선택 알림 사용자는 과도한 DM을 막기 위해 서버별 최대 25명만 조용히 전송합니다.
            sent = 0
            for member in guild.members:
                if member.bot:
                    continue
                user = get_user(member.id)
                if not isinstance(user, dict):
                    continue
                topics = _user_notifications(user)["topics"]
                if not (topics.get("disaster") or topics.get("weather")):
                    continue
                try:
                    info = disaster_core.DISASTERS.get(str(event.get("key")), disaster_core.DISASTERS["blackout"])
                    weather = WEATHER_STATES.get(str(event.get("weather") or "clear"), WEATHER_STATES["clear"])
                    await member.send(f"🚨 **{guild.name}** 공동 재난 발생 · {info['emoji']} {info['name']}\n{weather['emoji']} 재난 기상 · {weather['name']}\n서버에서 `!재난상황`을 확인하세요.")
                    sent += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass
                if sent >= 25:
                    break
        if changed:
            save_data()

    async def reconcile_temp_voice_rooms() -> None:
        changed = False
        for guild in list(bot.guilds):
            state = _guild_state(world_data, int(guild.id))["temp_voice"]
            rooms = state.setdefault("rooms", {})
            for room_id, row in list(rooms.items()):
                room = guild.get_channel(_safe_int(room_id, 0))
                if not isinstance(room, discord.VoiceChannel):
                    rooms.pop(room_id, None)
                    changed = True
                    continue
                if not room.members:
                    try:
                        await room.delete(reason="ABADDON 재접속 후 빈 임시 분대방 정리")
                    except (discord.Forbidden, discord.HTTPException):
                        continue
                    rooms.pop(room_id, None)
                    changed = True
                    continue
                if not isinstance(row, dict):
                    row = {"owner_id": str(room.members[0].id), "created_at": _iso(), "locked": False, "invited": [], "limit": room.user_limit}
                    rooms[room_id] = row
                    changed = True
                owner_id = _safe_int(row.get("owner_id"), 0)
                owner = next((member for member in room.members if int(member.id) == owner_id), None)
                if owner is None:
                    new_owner = room.members[0]
                    row["owner_id"] = str(new_owner.id)
                    try:
                        await room.set_permissions(new_owner, manage_channels=True, move_members=True, connect=True, view_channel=True, reason="임시 분대방 재접속 방장 복구")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    changed = True
        if changed:
            save_data()

    async def send_patch_notifications() -> None:
        seen: set[int] = set()
        changed = False
        for guild in list(bot.guilds):
            for member in guild.members:
                if member.bot or int(member.id) in seen:
                    continue
                seen.add(int(member.id))
                user = get_user(member.id)
                if not isinstance(user, dict):
                    continue
                prefs = _user_notifications(user)
                if not prefs["topics"].get("patch") or str(prefs.get("last_patch_notice_version") or "") == VERSION:
                    continue
                try:
                    await member.send(f"📣 **ABADDON v{VERSION} 패치 적용**\n자동 공동 재난·기상, 버튼 참여, 운영·알림·임시 음성·우클릭 기능이 추가됐습니다. 서버에서 `!패치노트`를 확인하세요.")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                prefs["last_patch_notice_version"] = VERSION
                changed = True
                if len(seen) >= 100:
                    break
            if len(seen) >= 100:
                break
        if changed:
            save_data()

    async def start_background_tasks() -> None:
        await reconcile_temp_voice_rooms()
        await send_patch_notifications()
        if not disaster_auto_loop.is_running():
            disaster_auto_loop.start()

    bot.add_listener(start_background_tasks, "on_ready")

    @bot.command(name="알림센터", aliases=["통합알림", "알림메뉴"], help="패치·재난·시장·길드 알림을 한 선택창에서 관리합니다.")
    async def notification_center(ctx: commands.Context) -> None:
        user = await require_user_ctx(ctx)
        if user is None:
            return
        prefs = _user_notifications(user)
        enabled = [f"{NOTIFICATION_TOPICS[k][0]} {NOTIFICATION_TOPICS[k][1]}" for k, on in prefs["topics"].items() if on and k in NOTIFICATION_TOPICS]
        embed = discord.Embed(title="🔔 통합 알림센터", description="받을 알림을 선택하세요. 기존 개별 알림 명령은 그대로 유지됩니다.", colour=0x5865F2)
        embed.add_field(name="현재 선택", value=" · ".join(enabled) if enabled else "선택된 알림 없음", inline=False)
        await ctx.send(embed=embed, view=NotificationView(bot, int(ctx.author.id), user, save_data))

    @bot.command(name="내알림", aliases=["알림상태통합"], help="통합 알림센터 설정을 확인합니다.")
    async def my_notifications(ctx: commands.Context) -> None:
        user = await require_user_ctx(ctx)
        if user is None:
            return
        prefs = _user_notifications(user)
        lines = [f"{'✅' if prefs['topics'].get(k) else '⬜'} {emoji} {label}" for k, (emoji, label) in NOTIFICATION_TOPICS.items()]
        await ctx.send("🔔 **내 통합 알림 설정**\n" + "\n".join(lines))

    def suggestion_rows(guild_id: int) -> List[MutableMapping[str, Any]]:
        return _guild_state(world_data, guild_id).setdefault("suggestions", [])

    async def create_suggestion(interaction: discord.Interaction, subject: str, body: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("⚠️ 서버에서만 등록할 수 있습니다.", ephemeral=True)
            return
        rows = suggestion_rows(int(interaction.guild.id))
        sid = f"SG-{len(rows)+1:04d}"
        row: MutableMapping[str, Any] = {"id": sid, "author_id": str(interaction.user.id), "subject": subject[:80], "body": body[:1000], "status": "검토중", "created_at": _iso(), "votes": {"up": [], "hold": [], "down": []}}
        rows.append(row)
        root["stats"]["suggestions"] = _safe_int(root["stats"].get("suggestions"), 0) + 1
        save_data()
        embed = discord.Embed(title=f"💡 {sid} · {subject[:80]}", description=body[:4000], colour=0xF1C40F)
        embed.add_field(name="상태", value="검토중", inline=True)
        embed.set_footer(text=f"제안자 {interaction.user.display_name}")
        await interaction.response.send_message("✅ 공개 건의를 등록했습니다.", ephemeral=True)
        if interaction.channel:
            await interaction.channel.send(embed=embed, view=SuggestionVoteView(sid, vote_suggestion))

    async def vote_suggestion(interaction: discord.Interaction, sid: str, choice: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("⚠️ 서버에서만 투표할 수 있습니다.", ephemeral=True)
            return
        row = next((r for r in suggestion_rows(int(interaction.guild.id)) if str(r.get("id")) == sid), None)
        if row is None:
            await interaction.response.send_message("⚠️ 건의를 찾지 못했습니다.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        votes = row.setdefault("votes", {"up": [], "hold": [], "down": []})
        for key in ("up", "hold", "down"):
            bucket = votes.setdefault(key, [])
            if uid in bucket:
                bucket.remove(uid)
        votes.setdefault(choice, []).append(uid)
        save_data()
        await interaction.response.send_message(f"✅ 투표 반영 · 👍 {len(votes['up'])} · 🤔 {len(votes['hold'])} · 👎 {len(votes['down'])}", ephemeral=True)

    @bot.command(name="건의", aliases=["공개건의", "건의등록"], help="공개 건의 작성 버튼을 엽니다.")
    async def suggestion_panel(ctx: commands.Context) -> None:
        await ctx.send("💡 **공개 건의·로드맵 투표소**\n비슷한 건의가 있는지 `!건의목록`에서 먼저 확인해주세요.", view=SuggestionOpenView(create_suggestion))

    @bot.command(name="건의목록", aliases=["제안목록"], help="공개 건의와 투표 현황을 확인합니다.")
    async def suggestion_list(ctx: commands.Context, 페이지: int = 1) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        rows = suggestion_rows(int(ctx.guild.id))
        page = max(1, int(페이지 or 1))
        chunk = list(reversed(rows))[(page - 1) * 8: page * 8]
        if not chunk:
            await ctx.send("📭 등록된 공개 건의가 없습니다.")
            return
        lines = []
        for row in chunk:
            votes = row.get("votes", {})
            lines.append(f"`{row.get('id')}` **{row.get('subject')}** · {row.get('status','검토중')} · 👍 {len(votes.get('up',[]))} / 🤔 {len(votes.get('hold',[]))} / 👎 {len(votes.get('down',[]))}")
        await ctx.send(f"💡 **공개 건의 목록 · {page}페이지**\n" + "\n".join(lines))

    @bot.command(name="건의상태", aliases=["제안상태"], help="관리자가 공개 건의 상태를 변경합니다.")
    async def suggestion_status(ctx: commands.Context, 번호: str = "", *, 상태: str = "") -> None:
        if not await require_admin_ctx(ctx):
            return
        allowed = {"검토중", "개발예정", "진행중", "보류", "적용완료", "반려"}
        if 상태 not in allowed:
            await ctx.send("⚠️ 상태: 검토중 / 개발예정 / 진행중 / 보류 / 적용완료 / 반려")
            return
        row = next((r for r in suggestion_rows(int(ctx.guild.id)) if str(r.get("id")) == 번호), None)
        if row is None:
            await ctx.send("⚠️ 건의 번호를 찾지 못했습니다.")
            return
        row["status"] = 상태
        row["updated_at"] = _iso()
        save_data()
        await ctx.send(f"✅ `{번호}` 상태를 **{상태}**로 변경했습니다.")

    @bot.command(name="로드맵", aliases=["개발로드맵"], help="개발 예정·진행 중·완료된 공개 건의를 확인합니다.")
    async def roadmap(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        rows = suggestion_rows(int(ctx.guild.id))
        grouped: Dict[str, List[str]] = {k: [] for k in ("개발예정", "진행중", "적용완료", "검토중", "보류")}
        for row in reversed(rows):
            status = str(row.get("status", "검토중"))
            if status in grouped and len(grouped[status]) < 8:
                grouped[status].append(f"`{row.get('id')}` {row.get('subject')}")
        embed = discord.Embed(title="🗺️ ABADDON 공개 개발 로드맵", colour=0x3498DB)
        for status, lines in grouped.items():
            if lines:
                embed.add_field(name=status, value="\n".join(lines), inline=False)
        if not embed.fields:
            embed.description = "아직 표시할 공개 로드맵이 없습니다."
        await ctx.send(embed=embed)

    @bot.command(name="운영통합센터", aliases=["통합운영센터", "관리허브"], help="문의·점검·통계·알림·재난 진입점을 한 화면에 표시합니다.")
    async def operations_hub(ctx: commands.Context) -> None:
        embed = discord.Embed(title="🛡️ ABADDON 통합 운영센터", description="기존 기능을 삭제하지 않고 목적별 진입점만 한 화면으로 묶었습니다.", colour=0x2F3136)
        embed.add_field(name="🎫 접수", value="`!문의패널` · `!접수패널` · `!건의`", inline=False)
        embed.add_field(name="🧪 점검", value="`!시스템점검` · `!테스트 상세` · `!790안정화검수`", inline=False)
        embed.add_field(name="📊 분석", value="`!서버통계` · `!운영대시보드` · `!운영분석`", inline=False)
        await ctx.send(embed=embed, view=OperationsHubView())

    @bot.command(name="운영분석", aliases=["경제분석", "콘텐츠분석"], help="실제 재화 유입·콘텐츠 이용·오류 기록을 확률 노출 없이 집계합니다.")
    async def operations_analytics(ctx: commands.Context) -> None:
        if not await require_admin_ctx(ctx):
            return
        users = [row for row in user_data.values() if isinstance(row, dict)]
        total_food = sum(max(0, _safe_int(row.get("balance"), 0)) for row in users)
        resource_totals: Counter[str] = Counter()
        for row in users:
            for bag_name in ("resources", "materials"):
                bag = row.get(bag_name)
                if isinstance(bag, dict):
                    for key, value in bag.items():
                        resource_totals[str(key)] += max(0, _safe_int(value, 0))
        dstate = disaster_core._guild_state(world_data, int(ctx.guild.id))
        dstats = dstate.get("stats", {})
        suggestions = suggestion_rows(int(ctx.guild.id))
        temp_rooms = _guild_state(world_data, int(ctx.guild.id))["temp_voice"].get("rooms", {})
        embed = discord.Embed(title="📊 운영·경제·콘텐츠 분석", description="내부 확률표는 표시하지 않고 실제 누적 결과와 사용 상태만 집계합니다.", colour=0x1ABC9C)
        embed.add_field(name="생존자·식량", value=f"등록 {len(users):,}명 · 보유 식량 합계 {total_food:,}", inline=False)
        embed.add_field(name="주요 자원 보유", value=" · ".join(f"{k} {v:,}" for k, v in resource_totals.most_common(8)) or "기록 없음", inline=False)
        embed.add_field(name="공동 재난", value=f"발생 {_safe_int(dstats.get('started'))} · 성공 {_safe_int(dstats.get('success'))} · 실패 {_safe_int(dstats.get('failed'))}", inline=True)
        embed.add_field(name="커뮤니티", value=f"공개 건의 {len(suggestions)} · 활성 임시방 {len(temp_rooms)}", inline=True)
        embed.add_field(name="안전 기록", value=f"삭제 {_safe_int(root['stats'].get('deletions'))} · 명령 충돌 {getattr(bot, 'v731_duplicate_audit', {}).get('collisions', 0) if isinstance(getattr(bot, 'v731_duplicate_audit', {}), dict) else 0}", inline=False)
        await ctx.send(embed=embed)

    def temp_voice_state(guild_id: int) -> MutableMapping[str, Any]:
        return _guild_state(world_data, guild_id)["temp_voice"]

    @bot.command(name="분대음성설정", aliases=["임시음성설정", "분대방설정"], help="임시 분대 음성방 생성 로비를 설치합니다.")
    async def temp_voice_setup(ctx: commands.Context) -> None:
        if not await require_admin_ctx(ctx):
            return
        guild = ctx.guild
        state = temp_voice_state(int(guild.id))
        category = guild.get_channel(_safe_int(state.get("category_id"), 0))
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category("〔🎙️ 임시 분대 통신〕", reason="ABADDON 임시 분대 음성방")
        lobby = guild.get_channel(_safe_int(state.get("lobby_id"), 0))
        if not isinstance(lobby, discord.VoiceChannel):
            lobby = await guild.create_voice_channel("➕ 분대 음성방 만들기", category=category, reason="ABADDON 임시 분대 음성방")
        state.update(enabled=True, category_id=int(category.id), lobby_id=int(lobby.id))
        save_data()
        await ctx.send(f"✅ 임시 분대 음성방을 활성화했습니다.\n로비: {lobby.mention}\n입장하면 개인 분대방이 생성되고 모두 나가면 자동 정리됩니다.", view=TempVoiceControlView())

    def owned_temp_room(ctx: commands.Context) -> Tuple[Optional[discord.VoiceChannel], Optional[MutableMapping[str, Any]]]:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice or not isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            return None, None
        room = ctx.author.voice.channel
        state = temp_voice_state(int(ctx.guild.id))
        row = state.get("rooms", {}).get(str(room.id))
        if not isinstance(row, dict) or str(row.get("owner_id")) != str(ctx.author.id):
            return None, None
        return room, row

    @bot.command(name="분대방이름", aliases=["임시방이름"], help="자신이 만든 임시 분대 음성방의 이름을 변경합니다.")
    async def temp_voice_name(ctx: commands.Context, *, 이름: str = "") -> None:
        room, row = owned_temp_room(ctx)
        if room is None or row is None:
            await ctx.send("⚠️ 자신이 만든 임시 분대 음성방 안에서 사용하세요.")
            return
        name = re.sub(r"[\r\n]", " ", 이름).strip()[:90]
        if not name:
            await ctx.send("⚠️ 새 이름을 입력해주세요.")
            return
        await room.edit(name=f"🎙️ {name}", reason="임시 분대방 이름 변경")
        row["name"] = name
        save_data()
        await ctx.send(f"✅ 분대방 이름을 **{name}**으로 변경했습니다.")

    @bot.command(name="분대방잠금", aliases=["임시방잠금"], help="임시 분대방의 공개 입장을 켜거나 끕니다.")
    async def temp_voice_lock(ctx: commands.Context) -> None:
        room, row = owned_temp_room(ctx)
        if room is None or row is None:
            await ctx.send("⚠️ 자신이 만든 임시 분대방 안에서 사용하세요.")
            return
        locked = not bool(row.get("locked", False))
        overwrite = room.overwrites_for(ctx.guild.default_role)
        overwrite.connect = False if locked else None
        await room.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason="임시 분대방 잠금")
        row["locked"] = locked
        save_data()
        await ctx.send(f"{'🔒 잠금' if locked else '🔓 공개'} 상태로 변경했습니다.")

    @bot.command(name="분대방초대", aliases=["임시방초대"], help="잠긴 임시 분대방에 사용자를 초대합니다.")
    async def temp_voice_invite(ctx: commands.Context, 대상: discord.Member) -> None:
        room, row = owned_temp_room(ctx)
        if room is None or row is None:
            await ctx.send("⚠️ 자신이 만든 임시 분대방 안에서 사용하세요.")
            return
        overwrite = room.overwrites_for(대상)
        overwrite.connect = True
        overwrite.view_channel = True
        await room.set_permissions(대상, overwrite=overwrite, reason="임시 분대방 초대")
        invited = row.setdefault("invited", [])
        if str(대상.id) not in invited:
            invited.append(str(대상.id))
        save_data()
        await ctx.send(f"✅ {대상.mention}님을 분대방에 초대했습니다.")

    @bot.command(name="분대방인원", aliases=["임시방인원"], help="임시 분대방 최대 인원을 설정합니다.")
    async def temp_voice_limit(ctx: commands.Context, 인원: int = 0) -> None:
        room, row = owned_temp_room(ctx)
        if room is None or row is None:
            await ctx.send("⚠️ 자신이 만든 임시 분대방 안에서 사용하세요.")
            return
        limit = max(0, min(99, int(인원 or 0)))
        await room.edit(user_limit=limit, reason="임시 분대방 인원 제한")
        row["limit"] = limit
        save_data()
        await ctx.send(f"✅ 최대 인원을 **{'제한 없음' if limit == 0 else str(limit)+'명'}**으로 설정했습니다.")

    @bot.command(name="분대방방장", aliases=["분대방위임", "임시방방장"], help="임시 분대방 방장을 다른 사용자에게 넘깁니다.")
    async def temp_voice_transfer(ctx: commands.Context, 대상: discord.Member) -> None:
        room, row = owned_temp_room(ctx)
        if room is None or row is None or 대상 not in room.members:
            await ctx.send("⚠️ 같은 임시 분대방에 있는 사용자에게만 위임할 수 있습니다.")
            return
        row["owner_id"] = str(대상.id)
        await room.set_permissions(대상, manage_channels=True, move_members=True, connect=True, view_channel=True, reason="임시 분대방 방장 위임")
        await room.set_permissions(ctx.author, manage_channels=None, move_members=None, reason="임시 분대방 방장 위임")
        save_data()
        await ctx.send(f"✅ 분대방 방장을 {대상.mention}님에게 넘겼습니다.")

    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        state = temp_voice_state(int(member.guild.id))
        if not state.get("enabled"):
            return
        lobby_id = _safe_int(state.get("lobby_id"), 0)
        if after.channel and int(after.channel.id) == lobby_id:
            category = member.guild.get_channel(_safe_int(state.get("category_id"), 0))
            if not isinstance(category, discord.CategoryChannel):
                return
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                member: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True, view_channel=True),
                member.guild.me: discord.PermissionOverwrite(manage_channels=True, move_members=True, connect=True, view_channel=True),
            }
            try:
                room = await member.guild.create_voice_channel(f"🎙️ {member.display_name}의 분대", category=category, overwrites=overwrites, reason="임시 분대 음성방 생성")
                state.setdefault("rooms", {})[str(room.id)] = {"owner_id": str(member.id), "created_at": _iso(), "locked": False, "invited": [], "limit": 0}
                root["stats"]["temp_rooms"] = _safe_int(root["stats"].get("temp_rooms"), 0) + 1
                save_data()
                await member.move_to(room, reason="임시 분대 음성방 이동")
            except (discord.Forbidden, discord.HTTPException):
                return
        if before.channel and str(before.channel.id) in state.get("rooms", {}):
            room = before.channel
            row = state["rooms"].get(str(room.id), {})
            await asyncio.sleep(1)
            if not room.members:
                try:
                    await room.delete(reason="빈 임시 분대방 자동 정리")
                except (discord.Forbidden, discord.HTTPException):
                    return
                state["rooms"].pop(str(room.id), None)
                save_data()
            elif str(row.get("owner_id")) == str(member.id):
                new_owner = room.members[0]
                row["owner_id"] = str(new_owner.id)
                try:
                    await room.set_permissions(new_owner, manage_channels=True, move_members=True, connect=True, view_channel=True, reason="임시 분대방 자동 방장 이전")
                    await room.set_permissions(member, manage_channels=None, move_members=None, reason="임시 분대방 이전 방장 권한 정리")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                save_data()

    bot.add_listener(on_voice_state_update, "on_voice_state_update")

    @bot.command(name="하이라이트설정", aliases=["스타보드설정"], help="반응이 모인 메시지를 보관할 하이라이트 채널을 설정합니다.")
    async def highlight_setup(ctx: commands.Context, 채널: Optional[discord.TextChannel] = None, 이모지: str = "⭐", 기준: int = 3) -> None:
        if not await require_admin_ctx(ctx):
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("⚠️ 텍스트 채널을 지정해주세요.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))["highlight"]
        state.update(enabled=True, channel_id=int(target.id), emoji=str(이모지)[:32], threshold=max(2, min(50, int(기준 or 3))))
        save_data()
        await ctx.send(f"✅ 하이라이트 보드 설정 · {target.mention} · {state['emoji']} {state['threshold']}개 이상")

    @bot.command(name="하이라이트상태", aliases=["스타보드상태"], help="하이라이트 보드 설정을 확인합니다.")
    async def highlight_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        state = _guild_state(world_data, int(ctx.guild.id))["highlight"]
        channel = ctx.guild.get_channel(_safe_int(state.get("channel_id"), 0))
        await ctx.send(f"⭐ **하이라이트 보드**\n상태: {'켜짐' if state.get('enabled') else '꺼짐'}\n채널: {channel.mention if channel else '미설정'}\n기준: {state.get('emoji','⭐')} {_safe_int(state.get('threshold'),3)}개")

    async def publish_highlight(guild: discord.Guild, message: discord.Message, count: int) -> None:
        state = _guild_state(world_data, int(guild.id))["highlight"]
        target = guild.get_channel(_safe_int(state.get("channel_id"), 0))
        if not isinstance(target, discord.TextChannel) or target.id == message.channel.id:
            return
        posts = state.setdefault("posts", {})
        existing_id = _safe_int(posts.get(str(message.id)), 0)
        embed = discord.Embed(description=(message.content or "첨부 메시지")[:4000], colour=0xF1C40F, timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="원문", value=f"[메시지로 이동]({message.jump_url}) · {state.get('emoji','⭐')} {count}", inline=False)
        if message.attachments:
            image = next((a for a in message.attachments if str(a.content_type or "").startswith("image/")), None)
            if image:
                embed.set_image(url=image.url)
        try:
            if existing_id:
                post = await target.fetch_message(existing_id)
                await post.edit(embed=embed)
            else:
                post = await target.send(embed=embed)
                posts[str(message.id)] = int(post.id)
                root["stats"]["highlights"] = _safe_int(root["stats"].get("highlights"), 0) + 1
            save_data()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return

    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None:
            return
        state = _guild_state(world_data, int(guild.id))["highlight"]
        if not state.get("enabled") or str(payload.emoji) != str(state.get("emoji", "⭐")):
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return
        reaction = next((r for r in message.reactions if str(r.emoji) == str(state.get("emoji", "⭐"))), None)
        if reaction and reaction.count >= _safe_int(state.get("threshold"), 3):
            await publish_highlight(guild, message, reaction.count)

    bot.add_listener(on_raw_reaction_add, "on_raw_reaction_add")

    @bot.command(name="하이라이트추가", aliases=["스타보드추가"], help="관리자가 현재 채널의 메시지 ID를 하이라이트에 추가합니다.")
    async def highlight_add(ctx: commands.Context, 메시지ID: int) -> None:
        if not await require_admin_ctx(ctx) or not isinstance(ctx.channel, discord.TextChannel):
            return
        try:
            message = await ctx.channel.fetch_message(int(메시지ID))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await ctx.send("⚠️ 메시지를 찾지 못했습니다.")
            return
        await publish_highlight(ctx.guild, message, 0)
        await ctx.send("✅ 하이라이트 보드에 반영했습니다.")

    @bot.command(name="하이라이트제거", aliases=["스타보드제거"], help="관리자가 원본 메시지 ID의 하이라이트를 제거합니다.")
    async def highlight_remove(ctx: commands.Context, 메시지ID: int) -> None:
        if not await require_admin_ctx(ctx):
            return
        state = _guild_state(world_data, int(ctx.guild.id))["highlight"]
        post_id = _safe_int(state.setdefault("posts", {}).pop(str(메시지ID), 0), 0)
        channel = ctx.guild.get_channel(_safe_int(state.get("channel_id"), 0))
        if post_id and isinstance(channel, discord.TextChannel):
            try:
                post = await channel.fetch_message(post_id)
                await post.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        save_data()
        await ctx.send("✅ 하이라이트 연결 기록을 제거했습니다.")

    def record_context(kind: str, interaction: discord.Interaction, payload: Mapping[str, Any]) -> str:
        rows = root.setdefault("intake", [])
        case_id = f"CX-{secrets.token_hex(4).upper()}"
        rows.append({"id": case_id, "kind": kind, "guild_id": str(interaction.guild_id or 0), "actor_id": str(interaction.user.id), "created_at": _iso(), **dict(payload)})
        root["stats"]["context_actions"] = _safe_int(root["stats"].get("context_actions"), 0) + 1
        save_data()
        return case_id

    async def ctx_bug(interaction: discord.Interaction, message: discord.Message) -> None:
        case_id = record_context("bug", interaction, {"message_id": str(message.id), "channel_id": str(message.channel.id), "jump_url": message.jump_url, "content": message.content[:1000]})
        await interaction.response.send_message(f"🐛 버그 접수 완료 · 사건 `{case_id}`\n운영진에게 메시지 링크와 내용이 저장됐습니다.", ephemeral=True)

    async def ctx_report(interaction: discord.Interaction, message: discord.Message) -> None:
        case_id = record_context("report", interaction, {"message_id": str(message.id), "author_id": str(message.author.id), "jump_url": message.jump_url, "content": message.content[:1000]})
        await interaction.response.send_message(f"🚨 신고 증거 저장 완료 · 사건 `{case_id}`", ephemeral=True)

    async def ctx_forward(interaction: discord.Interaction, message: discord.Message) -> None:
        case_id = record_context("forward", interaction, {"message_id": str(message.id), "jump_url": message.jump_url, "content": message.content[:1000]})
        await interaction.response.send_message(f"📨 운영진 전달 대기열에 저장했습니다 · `{case_id}`", ephemeral=True)

    async def ctx_summary(interaction: discord.Interaction, message: discord.Message) -> None:
        text = re.sub(r"\s+", " ", message.content or "").strip()
        summary = text[:450] + ("…" if len(text) > 450 else "")
        await interaction.response.send_message("📝 **메시지 요약**\n" + (summary or "요약할 텍스트가 없습니다."), ephemeral=True)

    async def ctx_find_command(interaction: discord.Interaction, message: discord.Message) -> None:
        query = (message.content or "").casefold()
        matches = []
        for command in bot.walk_commands():
            names = [command.qualified_name, *command.aliases]
            if any(str(name).casefold() in query for name in names):
                matches.append("!" + command.qualified_name)
            if len(matches) >= 10:
                break
        await interaction.response.send_message("🔎 **관련 명령어**\n" + (" · ".join(matches) if matches else "문장에서 직접 일치하는 명령어를 찾지 못했습니다. `!명령어` 검색을 사용하세요."), ephemeral=True)

    async def ctx_survivor_info(interaction: discord.Interaction, member: discord.Member) -> None:
        user = get_user(member.id)
        if not isinstance(user, dict):
            await interaction.response.send_message("📭 등록된 생존자 정보가 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(f"🪪 **{member.display_name}**\n레벨 {_safe_int(user.get('level'),1)} · 직업 {user.get('job') or '미선택'} · 전투력 {_safe_int(calculate_user_power(user),0):,}\n길드 ID {user.get('guild_id') or '-'}", ephemeral=True)

    async def ctx_guild_invite(interaction: discord.Interaction, member: discord.Member) -> None:
        inviter = get_user(interaction.user.id)
        target = get_user(member.id)
        if not isinstance(inviter, dict) or not inviter.get("guild_id"):
            await interaction.response.send_message("⚠️ 먼저 길드에 가입해야 합니다.", ephemeral=True)
            return
        if not isinstance(target, dict):
            await interaction.response.send_message("⚠️ 대상이 생존자 등록을 하지 않았습니다.", ephemeral=True)
            return
        invites = target.setdefault("guild_invites", [])
        invite = {"guild_id": str(inviter.get("guild_id")), "from_id": str(interaction.user.id), "guild_server_id": str(interaction.guild_id or 0), "created_at": _iso()}
        if not any(str(row.get("guild_id")) == invite["guild_id"] for row in invites if isinstance(row, dict)):
            invites.append(invite)
        save_data()
        try:
            await member.send(f"🏰 {interaction.user.display_name}님이 길드 초대를 보냈습니다. 서버에서 `!길드초대수락`을 실행하세요.")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await interaction.response.send_message(f"✅ {member.mention}님에게 길드 초대를 보냈습니다.", ephemeral=True)

    async def ctx_duel(interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.send_message(f"⚔️ {member.mention}님에게 결투 신청 준비 완료\n채널에서 `!pvp {member.mention}`을 실행하면 기존 안전 결투 규칙으로 연결됩니다.", ephemeral=True)

    async def ctx_trade(interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.send_message(f"💰 {member.mention}님과 거래하려면 `!송금 {member.mention} 금액` 또는 거래소를 사용하세요.", ephemeral=True)

    async def ctx_ops_record(interaction: discord.Interaction, member: discord.Member) -> None:
        if not _has_manage_guild(interaction.user):
            await interaction.response.send_message("⚠️ 운영진만 확인할 수 있습니다.", ephemeral=True)
            return
        user = get_user(member.id) or {}
        warnings = user.get("warnings") if isinstance(user, dict) else None
        count = len(warnings) if isinstance(warnings, list) else _safe_int(user.get("warning_count"), 0) if isinstance(user, dict) else 0
        await interaction.response.send_message(f"🛡️ **{member.display_name} 운영 기록**\n경고 {count}건 · 등록 {'예' if isinstance(user, dict) and user else '아니오'}", ephemeral=True)

    context_specs = (
        app_commands.ContextMenu(name="버그로 접수", callback=ctx_bug),
        app_commands.ContextMenu(name="신고 증거로 저장", callback=ctx_report),
        app_commands.ContextMenu(name="운영진에게 전달", callback=ctx_forward),
        app_commands.ContextMenu(name="메시지 요약", callback=ctx_summary),
        app_commands.ContextMenu(name="관련 명령어 찾기", callback=ctx_find_command),
        app_commands.ContextMenu(name="생존자 정보", callback=ctx_survivor_info),
        app_commands.ContextMenu(name="길드 초대", callback=ctx_guild_invite),
        app_commands.ContextMenu(name="결투 신청", callback=ctx_duel),
        app_commands.ContextMenu(name="거래 안내", callback=ctx_trade),
        app_commands.ContextMenu(name="운영 기록 확인", callback=ctx_ops_record),
    )
    context_added = 0
    existing_context = {(cmd.name, getattr(cmd, "type", None)) for cmd in bot.tree.get_commands()}
    for command in context_specs:
        key = (command.name, command.type)
        if key in existing_context:
            continue
        try:
            bot.tree.add_command(command)
            existing_context.add(key)
            context_added += 1
        except app_commands.CommandAlreadyRegistered:
            pass

    @bot.command(name="길드초대수락", aliases=["길드초대받기"], help="우클릭으로 받은 최근 길드 초대를 수락합니다.")
    async def guild_invite_accept(ctx: commands.Context) -> None:
        user = await require_user_ctx(ctx)
        if user is None:
            return
        if user.get("guild_id"):
            await ctx.send("⚠️ 이미 길드에 가입되어 있습니다.")
            return
        invites = [row for row in user.get("guild_invites", []) if isinstance(row, dict)]
        if not invites:
            await ctx.send("📭 대기 중인 길드 초대가 없습니다.")
            return
        invite = invites[-1]
        guild_id = str(invite.get("guild_id"))
        from apocalypse_bot.commands import v750_guild_raid as guild_core
        async with guild_core._guild_lock(bot, guild_id):
            guilds = world_data.get("guilds")
            guild = guilds.get(guild_id) if isinstance(guilds, dict) else None
            if not isinstance(guild, dict):
                await ctx.send("⚠️ 초대한 길드를 찾지 못했습니다.")
                return
            if user.get("guild_id"):
                await ctx.send("⚠️ 이미 다른 길드에 가입되어 있습니다.")
                return
            members = guild.setdefault("members", [])
            if len({str(x) for x in members}) >= guild_core.guild_member_capacity(guild):
                await ctx.send("⚠️ 길드 정원이 가득 찼습니다.")
                return
            uid = str(ctx.author.id)
            if uid not in [str(x) for x in members]:
                members.append(uid)
            joined = guild.setdefault("member_joined_at", {})
            if isinstance(joined, dict):
                joined[uid] = _iso()
            user["guild_id"] = guild_id
            user["guild_invites"] = []
            save_data()
        await ctx.send(f"✅ **{guild.get('name','길드')}**에 가입했습니다.")

    def latest_patch_checks(guild_id: int = 0) -> List[Tuple[str, bool, str]]:
        expected = (
            "재난예보", "재난날씨", "재난기록", "재난자동", "재난채널", "알림센터", "내알림",
            "건의", "건의목록", "건의상태", "로드맵", "운영통합센터", "운영분석",
            "분대음성설정", "분대방이름", "분대방잠금", "분대방초대", "분대방인원", "분대방방장",
            "하이라이트설정", "하이라이트상태", "하이라이트추가", "하이라이트제거", "길드초대수락", "790안정화검수",
        )
        missing = [name for name in expected if bot.get_command(name) is None]
        checks: List[Tuple[str, bool, str]] = []
        checks.append(("v7.9 명령 등록", not missing, f"신규·통합 명령 {len(expected)}개" if not missing else "누락: " + ", ".join(missing)))
        checks.append(("재난 자동 발생", disaster_auto_loop is not None and len(disaster_core.DISASTERS) >= 14, f"재난 {len(disaster_core.DISASTERS)}종 · 기상 {len(WEATHER_STATES)}종 · 자동 감시 루프"))
        checks.append(("재난 버튼 패널", len(disaster_view.children) == 5, "정찰·구조·수리·방어·물자 지원 버튼 5개"))
        checks.append(("우클릭 명령", context_added == 10 or len([c for c in bot.tree.get_commands() if isinstance(c, app_commands.ContextMenu)]) >= 10, "메시지 5종 · 사용자 5종"))
        checks.append(("임시 음성방", any(getattr(fn, "__name__", "") == "on_voice_state_update" for fn in bot.extra_events.get("on_voice_state_update", [])), "입장 생성·빈 방 정리·방장 이전"))
        checks.append(("하이라이트 listener", bool(bot.extra_events.get("on_raw_reaction_add")), "반응 임계치·원문 동기화 저장"))
        try:
            from apocalypse_bot.commands.v600_game_center import GAME_SECTION_VALIDATION, GAME_SECTIONS
            ops_sections = GAME_SECTIONS.get("community_ops", ())
            menu_ids = {action_id for row in GAME_SECTIONS.values() for section in row for action_id in section[3]}
            menu_ok = bool(GAME_SECTION_VALIDATION.get("ok")) and len(ops_sections) >= 4 and all(len(row[3]) <= 25 for row in ops_sections)
            required_menu = {"channel_rules_existing", "guild_overall_ranking", "v790_stability", "disaster_forecast_v790"}
            missing_menu = sorted(required_menu - menu_ids)
            checks.append(("게임센터 최신화", menu_ok and not missing_menu, f"운영·알림·음성·건의 기능군 {len(ops_sections)}개" if not missing_menu else "누락: " + ", ".join(missing_menu)))
        except Exception as exc:
            checks.append(("게임센터 최신화", False, f"{type(exc).__name__}: {exc}"))
        state = _guild_state(world_data, guild_id) if guild_id else {}
        checks.append(("저장 구조", not state or all(key in state for key in ("disaster", "temp_voice", "suggestions", "highlight")), "기존 재난 데이터와 별도 확장 상태 보존"))
        checks.append(("폐기·삭제 안전", _safe_int(root["stats"].get("deletions"), 0) == 0, "기존 명령·기능·기록 자동 삭제 0건"))
        return checks

    @bot.command(name="790안정화검수", aliases=["790검수", "운영확장검수"], help="v7.9 신규·수정 기능만 읽기 전용으로 검사합니다.")
    async def v790_audit(ctx: commands.Context) -> None:
        if not await require_admin_ctx(ctx):
            return
        checks = latest_patch_checks(int(ctx.guild.id))
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🛡️ ABADDON v{VERSION} 안정화 검수", description="직전 패치에서 추가·수정된 운영·재난 기능만 검사합니다.", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        for name, ok, detail in checks[:25]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="읽기 전용 · 재화/재난/건의/음성방 상태 변경 없음")
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        checks = latest_patch_checks(int(ctx.guild.id) if ctx.guild else 0)
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {len(checks)-failed}/{len(checks)} 통과", description="`!테스트 상세`는 v7.9.0에서 추가·수정된 기능만 검사합니다.", colour=discord.Colour.green() if failed == 0 else discord.Colour.orange())
        # Discord 임베드 필드 제한을 항상 지킵니다.
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        if len(checks) > 24:
            embed.add_field(name="추가 검사", value=f"나머지 {len(checks)-24}개 항목은 `!790안정화검수`에서 확인", inline=False)
        embed.set_footer(text="최신 패치 전용 · 필드 최대 25개 보호")
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치에서 추가·수정된 기능만 읽기 전용으로 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v790_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(title="🛡️ ABADDON v7.9.0 — 운영·알림·임시 음성·재난 확장", description="자동 공동 재난과 기상, 버튼 참여, 통합 알림·운영센터, 공개 건의, 임시 음성방, 우클릭 명령과 하이라이트 보드를 추가했습니다.", colour=0x8E44AD)
            embed.add_field(name="🚨 자동 재난", value=f"재난 {len(disaster_core.DISASTERS)}종 · 기상 {len(WEATHER_STATES)}종 · 버튼 역할/물자 지원", inline=False)
            embed.add_field(name="🛡️ 운영 편의", value="통합 운영센터 · 경제/콘텐츠 분석 · 통합 알림 · 공개 건의/로드맵", inline=False)
            embed.add_field(name="🎙️ 커뮤니티", value="임시 분대 음성방 · 메시지/사용자 우클릭 10종 · 하이라이트 보드", inline=False)
            embed.add_field(name="🧪 안정화", value="최신 패치 전용 테스트 · 임베드 필드 25개 제한 보호 · 삭제 0건", inline=False)
            embed.set_footer(text="ABADDON v7.9.0 · 2026-08-03")
            await ctx.send(embed=embed)
        patch.callback = v790_patch_notes
        patch.help = "ABADDON v7.9.0 운영·재난 확장 패치노트입니다."
        patch.description = patch.help

    bot.abaddon_version = VERSION
    bot.v790_version = VERSION
    bot.v790_latest_patch_checks = latest_patch_checks
    bot.v790_weather_catalog = WEATHER_STATES
    bot.v790_context_commands_added = context_added
    print(f"[ABADDON v{VERSION}] operations/disaster expansion registered disasters={len(disaster_core.DISASTERS)} weather={len(WEATHER_STATES)} context={context_added} deletions=0", flush=True)
