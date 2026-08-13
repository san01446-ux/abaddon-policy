from __future__ import annotations

"""ABADDON v18.5.0 community consolidation + web dashboard.

This release intentionally reuses the mature SERVER GUARD / intake / temp-voice
systems already present in the bot instead of creating parallel moderation stacks.
It adds a simple server-settings surface, persistent button-role launcher, web
admin API, and regression/audit hooks.
"""

import json
import os
import re
import threading
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence
from urllib import parse as urllib_parse

import discord
from discord.ext import commands

VERSION = "18.5.2"
SUPPORT_USERNAME = "jjonga0022"
_DASHBOARD_LOCK = threading.RLock()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _locale(bot: commands.Bot, ctx_or_interaction: Any) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        user = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
        guild = getattr(ctx_or_interaction, "guild", None)
        return global_mod._user_locale(root, int(user.id), int(guild.id if guild else 0))
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _manager(member: Any) -> bool:
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    return bool(member.id == member.guild.owner_id or perms.administrator or perms.manage_guild)


def _management_settings(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault("server_management", {})
    if not isinstance(root, dict):
        root = {}
        world_data["server_management"] = root
    settings = root.setdefault(str(guild_id), {})
    if not isinstance(settings, dict):
        settings = {}
        root[str(guild_id)] = settings
    settings.setdefault("log_channel_id", 0)
    settings.setdefault("ticket_category_id", 0)
    settings.setdefault("ticket_log_channel_id", 0)
    settings.setdefault("open_tickets", {})
    settings.setdefault("mod_role_ids", [])
    automod = settings.setdefault("automod", {})
    if not isinstance(automod, dict):
        automod = {}
        settings["automod"] = automod
    automod.setdefault("enabled", False)
    automod.setdefault("spam", True)
    automod.setdefault("mention_spam", True)
    automod.setdefault("invites", False)
    automod.setdefault("bad_words", False)
    automod.setdefault("auto_timeout", False)
    button_roles = settings.setdefault("button_roles_v1850", {})
    if not isinstance(button_roles, dict):
        button_roles = {}
        settings["button_roles_v1850"] = button_roles
    button_roles.setdefault("role_ids", [])
    button_roles.setdefault("title", "알림 역할 선택")
    button_roles.setdefault("updated_by", 0)
    return settings


def _game_settings(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault("guild_settings", {})
    if not isinstance(root, dict):
        root = {}
        world_data["guild_settings"] = root
    row = root.setdefault(str(guild_id), {})
    if not isinstance(row, dict):
        row = {}
        root[str(guild_id)] = row
    row.setdefault("announcement_channel_id", None)
    row.setdefault("rpg_channel_id", None)
    row.setdefault("codex_notifications", True)
    row.setdefault("tutorial_notifications", True)
    row.setdefault("story_enabled", True)
    return row


def _temp_voice_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v790_operations", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v790_operations"] = root
    guilds = root.setdefault("guilds", {})
    if not isinstance(guilds, dict):
        guilds = {}
        root["guilds"] = guilds
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(guild_id)] = state
    voice = state.setdefault("temp_voice", {"enabled": False, "lobby_id": 0, "category_id": 0, "rooms": {}})
    if not isinstance(voice, dict):
        voice = {"enabled": False, "lobby_id": 0, "category_id": 0, "rooms": {}}
        state["temp_voice"] = voice
    voice.setdefault("enabled", False)
    voice.setdefault("lobby_id", 0)
    voice.setdefault("category_id", 0)
    voice.setdefault("rooms", {})
    return voice

def _v1890_settings(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault("server_ops_v1890", {})
    if not isinstance(root, dict):
        root = {}
        world_data["server_ops_v1890"] = root
    guilds = root.setdefault("guilds", {})
    if not isinstance(guilds, dict):
        guilds = {}
        root["guilds"] = guilds
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    security = row.setdefault("security", {})
    if not isinstance(security, dict):
        security = {}
        row["security"] = security
    security.setdefault("destructive_watch_enabled", True)
    security.setdefault("threshold", 3)
    security.setdefault("window_seconds", 20)
    external = row.setdefault("external", {})
    if not isinstance(external, dict):
        external = {}
        row["external"] = external
    external.setdefault("youtube", {})
    external.setdefault("twitch", {})
    return row


def _valid_button_roles(guild: discord.Guild, settings: Mapping[str, Any]) -> List[discord.Role]:
    raw = settings.get("button_roles_v1850", {}) if isinstance(settings, Mapping) else {}
    values = raw.get("role_ids", []) if isinstance(raw, Mapping) else []
    me = guild.me
    result: List[discord.Role] = []
    for value in values:
        role = guild.get_role(_safe_int(value))
        if role is None or role.is_default() or role.managed:
            continue
        if me is not None and role >= me.top_role:
            continue
        if role not in result:
            result.append(role)
    return result[:25]


def _channel_text(guild: discord.Guild, channel_id: Any) -> str:
    channel = guild.get_channel(_safe_int(channel_id))
    return channel.mention if channel is not None and hasattr(channel, "mention") else "미설정"


def _category_text(guild: discord.Guild, category_id: Any) -> str:
    category = guild.get_channel(_safe_int(category_id))
    return category.name if isinstance(category, discord.CategoryChannel) else "미설정"


def _settings_embed(bot: commands.Bot, world_data: MutableMapping[str, Any], guild: discord.Guild, locale: str = "ko") -> discord.Embed:
    mgmt = _management_settings(world_data, guild.id)
    game = _game_settings(world_data, guild.id)
    voice = _temp_voice_state(world_data, guild.id)
    auto = mgmt.get("automod", {})
    role_count = len(_valid_button_roles(guild, mgmt))
    open_tickets = len(mgmt.get("open_tickets", {})) if isinstance(mgmt.get("open_tickets"), dict) else 0
    dashboard = str(os.getenv("ABADDON_SITE_URL", "") or "").rstrip("/")
    dashboard_text = f"{dashboard}/dashboard.html" if dashboard else _t(locale, "홈페이지 환경변수 미설정", "Website URL not configured")

    embed = discord.Embed(
        title=_t(locale, "⚙️ ABADDON 서버 설정 센터", "⚙️ ABADDON Server Settings"),
        description=_t(
            locale,
            "기능을 새로 외우지 않아도 됩니다. **아래 상태를 보고 필요한 것만 켜거나 설치**하세요.",
            "No need to memorize setup commands. **Check the status below and enable only what you need.**",
        ),
        color=0x5865F2,
    )
    embed.add_field(
        name=_t(locale, "🛡️ 보호·로그", "🛡️ Protection & logs"),
        value=_t(
            locale,
            f"자동관리 **{'켜짐' if auto.get('enabled') else '꺼짐'}**\n로그 {_channel_text(guild, mgmt.get('log_channel_id'))}\n초대차단 **{'켜짐' if auto.get('invites') else '꺼짐'}** · 자동처벌 **{'켜짐' if auto.get('auto_timeout') else '꺼짐'}**",
            f"AutoMod **{'ON' if auto.get('enabled') else 'OFF'}**\nLog {_channel_text(guild, mgmt.get('log_channel_id'))}\nInvite block **{'ON' if auto.get('invites') else 'OFF'}** · auto-timeout **{'ON' if auto.get('auto_timeout') else 'OFF'}**",
        ),
        inline=True,
    )
    embed.add_field(
        name=_t(locale, "🎫 문의·커뮤니티", "🎫 Tickets & community"),
        value=_t(
            locale,
            f"문의 카테고리 **{_category_text(guild, mgmt.get('ticket_category_id'))}**\n열린 문의 **{open_tickets}개**\n버튼 역할 **{role_count}개**",
            f"Ticket category **{_category_text(guild, mgmt.get('ticket_category_id'))}**\nOpen tickets **{open_tickets}**\nButton roles **{role_count}**",
        ),
        inline=True,
    )
    lobby = guild.get_channel(_safe_int(voice.get("lobby_id")))
    embed.add_field(
        name=_t(locale, "🔊 음성·RPG", "🔊 Voice & RPG"),
        value=_t(
            locale,
            f"임시 음성 **{'켜짐' if voice.get('enabled') else '꺼짐'}** · {getattr(lobby, 'mention', '로비 미설치')}\n스토리 **{'켜짐' if game.get('story_enabled', True) else '꺼짐'}**\nRPG 권장 {_channel_text(guild, game.get('rpg_channel_id'))}",
            f"Temp voice **{'ON' if voice.get('enabled') else 'OFF'}** · {getattr(lobby, 'mention', 'lobby not installed')}\nStory **{'ON' if game.get('story_enabled', True) else 'OFF'}**\nRPG channel {_channel_text(guild, game.get('rpg_channel_id'))}",
        ),
        inline=False,
    )
    embed.add_field(
        name=_t(locale, "🌐 웹 대시보드", "🌐 Web dashboard"),
        value=f"{dashboard_text}\n" + _t(locale, "Discord 로그인 후 관리 가능한 서버만 표시됩니다.", "After Discord login, only servers you can manage are shown."),
        inline=False,
    )
    embed.set_footer(text=_t(locale, "버튼은 이 설정 메시지를 실행한 관리자만 사용할 수 있습니다.", "Only the manager who opened this panel can use its buttons."))
    return embed


class ButtonRolePicker(discord.ui.View):
    def __init__(self, guild: discord.Guild, user_id: int, roles: Sequence[discord.Role]):
        super().__init__(timeout=180)
        self.guild_id = int(guild.id)
        self.user_id = int(user_id)
        options = [
            discord.SelectOption(
                label=role.name[:100],
                value=str(role.id),
                description=f"{len(role.members):,}명 사용 중"[:100],
                emoji="🔔",
                default=any(member.id == user_id for member in role.members),
            )
            for role in roles[:25]
        ]
        select = discord.ui.Select(
            placeholder="받을 역할을 선택하세요 · 다시 선택하면 즉시 반영",
            min_values=0,
            max_values=max(1, len(options)),
            options=options,
            custom_id="abaddon:v1850:roles:picker",
        )
        select.callback = self._selected  # type: ignore[assignment]
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("이 역할 선택창은 다른 사용자의 메뉴입니다.", ephemeral=True)
            return False
        return True

    async def _selected(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        select = next((item for item in self.children if isinstance(item, discord.ui.Select)), None)
        if select is None:
            await interaction.response.send_message("역할 선택 메뉴를 찾지 못했습니다.", ephemeral=True)
            return
        configured = [interaction.guild.get_role(_safe_int(opt.value)) for opt in select.options]
        configured = [role for role in configured if isinstance(role, discord.Role)]
        selected_ids = {_safe_int(value) for value in select.values}
        add = [role for role in configured if role.id in selected_ids and role not in interaction.user.roles]
        remove = [role for role in configured if role.id not in selected_ids and role in interaction.user.roles]
        me = interaction.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            await interaction.response.send_message("아바돈에게 `역할 관리` 권한이 필요합니다.", ephemeral=True)
            return
        add = [role for role in add if not role.managed and role < me.top_role]
        remove = [role for role in remove if not role.managed and role < me.top_role]
        try:
            if add:
                await interaction.user.add_roles(*add, reason="ABADDON 버튼 역할 선택")
            if remove:
                await interaction.user.remove_roles(*remove, reason="ABADDON 버튼 역할 선택 해제")
        except discord.Forbidden:
            await interaction.response.send_message("역할 서열 때문에 변경하지 못했습니다. 아바돈 역할을 더 위로 올려주세요.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Discord 역할 변경 요청에 실패했습니다: `{type(exc).__name__}`", ephemeral=True)
            return
        text = []
        if add:
            text.append("추가: " + ", ".join(role.mention for role in add))
        if remove:
            text.append("해제: " + ", ".join(role.mention for role in remove))
        await interaction.response.send_message("✅ 역할 설정을 반영했습니다.\n" + ("\n".join(text) if text else "변경된 역할은 없습니다."), ephemeral=True)


class ButtonRoleLauncher(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any]):
        super().__init__(timeout=None)
        self.world_data = world_data

    @discord.ui.button(label="역할 선택", emoji="🎭", style=discord.ButtonStyle.primary, custom_id="abaddon:v1850:roles:open")
    async def open_roles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return
        settings = _management_settings(self.world_data, interaction.guild.id)
        roles = _valid_button_roles(interaction.guild, settings)
        if not roles:
            await interaction.response.send_message("이 서버에는 아직 선택 가능한 버튼 역할이 설정되지 않았습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🎭 **받고 싶은 역할을 선택하세요.**\n선택을 해제하면 해당 역할도 회수됩니다.",
            view=ButtonRolePicker(interaction.guild, interaction.user.id, roles),
            ephemeral=True,
        )


class ServerSettingsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data, owner_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("이 설정 패널은 다른 관리자가 연 메뉴입니다. `!서버설정`을 직접 실행해주세요.", ephemeral=True)
            return False
        if interaction.guild is None or not _manager(interaction.user):
            await interaction.response.send_message("서버 관리 권한이 필요합니다.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction, note: str = "") -> None:
        loc = _locale(self.bot, interaction)
        embed = _settings_embed(self.bot, self.world_data, interaction.guild, loc)
        if note:
            embed.description = f"{embed.description}\n\n✅ {note}"
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="자동관리 ON/OFF", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def automod(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        row = _management_settings(self.world_data, interaction.guild.id)["automod"]
        row["enabled"] = not bool(row.get("enabled"))
        self.save_data()
        await self._refresh(interaction, f"자동관리를 {'켰습니다' if row['enabled'] else '껐습니다'}. ")

    @discord.ui.button(label="현재 채널=로그", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def log_here(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("텍스트 채널에서 사용해주세요.", ephemeral=True)
            return
        _management_settings(self.world_data, interaction.guild.id)["log_channel_id"] = interaction.channel.id
        self.save_data()
        await self._refresh(interaction, f"{interaction.channel.mention}을 기본 로그 채널로 설정했습니다.")

    @discord.ui.button(label="문의 패널 안내", emoji="🎫", style=discord.ButtonStyle.success, row=0)
    async def ticket_help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("이 채널에 간단 문의 버튼을 설치하려면 `!문의패널`을 실행하세요. 신고/버그/건의까지 나누려면 `!접수패널`을 사용하세요.", ephemeral=True)

    @discord.ui.button(label="임시 음성 설치", emoji="🔊", style=discord.ButtonStyle.success, row=1)
    async def voice_help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        voice = _temp_voice_state(self.world_data, interaction.guild.id)
        lobby = interaction.guild.get_channel(_safe_int(voice.get("lobby_id")))
        if isinstance(lobby, discord.VoiceChannel):
            voice["enabled"] = not bool(voice.get("enabled"))
            self.save_data()
            await self._refresh(interaction, f"임시 음성방을 {'켰습니다' if voice['enabled'] else '껐습니다'}. 로비: {lobby.mention}")
            return
        await interaction.response.send_message("처음 한 번만 `!임시음성설정`을 실행하면 ➕ 음성방 생성 로비가 자동으로 만들어집니다.", ephemeral=True)

    @discord.ui.button(label="버튼 역할", emoji="🎭", style=discord.ButtonStyle.primary, row=1)
    async def role_help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        roles = _valid_button_roles(interaction.guild, _management_settings(self.world_data, interaction.guild.id))
        if roles:
            await interaction.response.send_message("현재 버튼 역할: " + ", ".join(role.mention for role in roles) + "\n패널 설치: `!버튼역할패널`", ephemeral=True)
        else:
            await interaction.response.send_message("먼저 `!버튼역할설정 @역할1 @역할2`로 사용자가 직접 받을 역할을 정해주세요.", ephemeral=True)

    @discord.ui.button(label="웹 대시보드", emoji="🌐", style=discord.ButtonStyle.secondary, row=1)
    async def dashboard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        site = str(os.getenv("ABADDON_SITE_URL", "") or "").rstrip("/")
        if not site:
            await interaction.response.send_message("웹 대시보드 주소가 아직 Render 환경변수 `ABADDON_SITE_URL`에 연결되지 않았습니다.", ephemeral=True)
            return
        await interaction.response.send_message(f"🌐 서버 설정 대시보드\n{site}/dashboard.html", ephemeral=True)

    @discord.ui.button(label="새로고침", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._refresh(interaction)


class CommunitySupportModal(discord.ui.Modal, title="ABADDON 문의 전송"):
    inquiry = discord.ui.TextInput(
        label="문의 / 버그 / 신고 내용",
        style=discord.TextStyle.paragraph,
        placeholder="문제 상황, 사용한 명령어, 채널, 필요한 도움을 자세히 적어주세요.",
        required=True,
        max_length=1200,
    )

    def __init__(self) -> None:
        super().__init__(timeout=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            from apocalypse_bot.commands import v1813_interaction_transport_guard as support_bridge
            owner = await support_bridge._resolve_owner(interaction.client)
            support_url = support_bridge._support_url()
        except Exception:
            owner = None
            support_url = ""

        if owner is None:
            await interaction.response.send_message(
                "❌ 제작자 DM 대상을 찾지 못했습니다. 잠시 후 다시 시도하거나 `jjonga0022`로 직접 문의해주세요.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🛰️ ABADDON 커뮤니티 문의 전달",
            description="커뮤니티 센터의 **문의** 버튼을 통해 접수된 내용입니다.",
            color=0x8E44AD,
        )
        user = interaction.user
        guild = interaction.guild
        channel = interaction.channel
        embed.add_field(name="보낸 사람", value=f"{user} · `{user.id}`", inline=False)
        embed.add_field(name="서버", value=f"{getattr(guild, 'name', 'DM')} · `{getattr(guild, 'id', 0) or '-'}`", inline=False)
        embed.add_field(name="채널", value=f"{getattr(channel, 'mention', '#DM')} · `{getattr(channel, 'id', 0) or '-'}`", inline=False)
        embed.add_field(name="내용", value=str(self.inquiry.value).strip()[:1024] or "(내용 없음)", inline=False)
        if support_url:
            embed.add_field(name="지원 서버", value=support_url[:1024], inline=False)
        try:
            await owner.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "❌ 제작자에게 DM을 전달하지 못했습니다. `jjonga0022`로 직접 문의해주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ 문의 내용을 제작자 DM으로 전달했습니다. 추가 스크린샷이 필요하면 `jjonga0022`로 DM을 이어서 보내주세요.",
            ephemeral=True,
        )


class CommunityQuickView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any]):
        super().__init__(timeout=None)
        self.world_data = world_data

    @discord.ui.button(label="문의", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="abaddon:v1850:community:tickets")
    async def ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(CommunitySupportModal())

    @discord.ui.button(label="임시 음성", emoji="🔊", style=discord.ButtonStyle.success, custom_id="abaddon:v1850:community:voice")
    async def voice(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("서버 관리자: `!임시음성설정`\n사용자: 생성 로비에 입장하면 개인 음성방이 자동 생성됩니다.", ephemeral=True)

    @discord.ui.button(label="역할", emoji="🎭", style=discord.ButtonStyle.secondary, custom_id="abaddon:v1850:community:roles")
    async def roles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버에서 사용해주세요.", ephemeral=True)
            return
        settings = _management_settings(self.world_data, interaction.guild.id)
        roles = _valid_button_roles(interaction.guild, settings)
        if not roles:
            await interaction.response.send_message("이 서버에는 버튼 역할이 아직 설정되지 않았습니다.", ephemeral=True)
            return
        await interaction.response.send_message("🎭 받을 역할을 고르세요.", view=ButtonRolePicker(interaction.guild, interaction.user.id, roles), ephemeral=True)

    @discord.ui.button(label="도움말", emoji="🧭", style=discord.ButtonStyle.secondary, custom_id="abaddon:v1850:community:help")
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("`!첫10분` · `!명령어` · `!서버설정` · 장애문의 DM `jjonga0022`", ephemeral=True)


def _session(handler: Any) -> Dict[str, Any]:
    try:
        from apocalypse_bot.commands import v1810_public_launch_pack as public
        token = public._authorization_token(handler)
        if not token:
            return {}
        with public._HTTP_LOCK:
            row = public._HTTP_SESSIONS.get(token, {})
            return dict(row) if isinstance(row, dict) else {}
    except Exception:
        return {}


def _oauth_guild_permission(session: Mapping[str, Any], guild_id: int) -> bool:
    for row in session.get("guilds", []) if isinstance(session.get("guilds"), list) else []:
        if not isinstance(row, Mapping) or str(row.get("id")) != str(guild_id):
            continue
        permissions = _safe_int(row.get("permissions"), 0)
        return bool(row.get("owner") or (permissions & 0x8) or (permissions & 0x20))
    return False


def _can_manage_session(bot: commands.Bot, session: Mapping[str, Any], guild_id: int) -> bool:
    guild = bot.get_guild(int(guild_id))
    uid = _safe_int(session.get("user_id"), 0)
    if guild is None or uid <= 0:
        return False
    if uid == guild.owner_id:
        return True
    member = guild.get_member(uid)
    if member is not None and (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
        return True
    return _oauth_guild_permission(session, guild_id)


def _settings_payload(world_data: MutableMapping[str, Any], guild: discord.Guild) -> Dict[str, Any]:
    mgmt = _management_settings(world_data, guild.id)
    game = _game_settings(world_data, guild.id)
    voice = _temp_voice_state(world_data, guild.id)
    auto = mgmt.get("automod", {})
    anti = mgmt.get("anti_raid", {}) if isinstance(mgmt.get("anti_raid"), Mapping) else {}
    v1890 = _v1890_settings(world_data, guild.id)
    security = v1890.get("security", {}) if isinstance(v1890.get("security"), Mapping) else {}
    external = v1890.get("external", {}) if isinstance(v1890.get("external"), Mapping) else {}
    roles = _valid_button_roles(guild, mgmt)
    return {
        "guild_id": str(guild.id),
        "guild_name": guild.name,
        "automod_enabled": bool(auto.get("enabled")),
        "invite_block": bool(auto.get("invites")),
        "bad_words_enabled": bool(auto.get("bad_words")),
        "auto_timeout": bool(auto.get("auto_timeout")),
        "anti_raid_enabled": bool(anti.get("enabled")),
        "anti_raid_auto_lockdown": bool(anti.get("auto_lockdown")),
        "destructive_watch_enabled": bool(security.get("destructive_watch_enabled", True)),
        "destructive_watch_threshold": int(security.get("threshold", 3) or 3),
        "destructive_watch_window_seconds": int(security.get("window_seconds", 20) or 20),
        "welcome_channel_id": str(_safe_int(mgmt.get("welcome_channel_id"), 0) or ""),
        "leave_channel_id": str(_safe_int(mgmt.get("leave_channel_id"), 0) or ""),
        "autorole_id": str(_safe_int(mgmt.get("autorole_id"), 0) or ""),
        "external_youtube_count": len(external.get("youtube", {}) if isinstance(external.get("youtube"), Mapping) else {}),
        "external_twitch_count": len(external.get("twitch", {}) if isinstance(external.get("twitch"), Mapping) else {}),
        "youtube_api_ready": bool(os.getenv("YOUTUBE_API_KEY", "").strip()),
        "twitch_api_ready": bool(os.getenv("TWITCH_CLIENT_ID", "").strip() and os.getenv("TWITCH_CLIENT_SECRET", "").strip()),
        "log_channel_id": str(_safe_int(mgmt.get("log_channel_id"), 0) or ""),
        "ticket_category_id": str(_safe_int(mgmt.get("ticket_category_id"), 0) or ""),
        "ticket_log_channel_id": str(_safe_int(mgmt.get("ticket_log_channel_id"), 0) or ""),
        "temp_voice_enabled": bool(voice.get("enabled")),
        "temp_voice_lobby_id": str(_safe_int(voice.get("lobby_id"), 0) or ""),
        "button_role_ids": [str(role.id) for role in roles],
        "story_enabled": bool(game.get("story_enabled", True)),
        "codex_notifications": bool(game.get("codex_notifications", True)),
        "tutorial_notifications": bool(game.get("tutorial_notifications", True)),
        "announcement_channel_id": str(_safe_int(game.get("announcement_channel_id"), 0) or ""),
        "rpg_channel_id": str(_safe_int(game.get("rpg_channel_id"), 0) or ""),
    }


def _dashboard_structure(guild: discord.Guild) -> Dict[str, Any]:
    me = guild.me
    roles = [
        {"id": str(role.id), "name": role.name}
        for role in guild.roles
        if not role.is_default() and not role.managed and (me is None or role < me.top_role)
    ][-100:]
    return {
        "text_channels": [{"id": str(ch.id), "name": ch.name} for ch in guild.text_channels[:100]],
        "categories": [{"id": str(ch.id), "name": ch.name} for ch in guild.categories[:100]],
        "voice_channels": [{"id": str(ch.id), "name": ch.name} for ch in guild.voice_channels[:100]],
        "roles": roles,
    }


def _body_json(handler: Any) -> Dict[str, Any]:
    try:
        length = max(0, min(65536, _safe_int(handler.headers.get("Content-Length"), 0)))
        raw = handler.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8", "replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _install_dashboard_hooks(bot: commands.Bot, world_data: MutableMapping[str, Any], save_data) -> None:
    previous_get = getattr(bot, "_abaddon_public_http_get_hook", None)
    previous_post = getattr(bot, "_abaddon_public_http_post_hook", None)

    def get_hook(handler: Any, parsed: Any) -> bool:
        path = str(parsed.path or "")
        if path not in {"/api/dashboard/guilds", "/api/dashboard/settings", "/api/dashboard/structure"}:
            return bool(previous_get(handler, parsed)) if callable(previous_get) else False
        session = _session(handler)
        if not session:
            handler._send_json(401, {"ok": False, "error": "login_required"})
            return True
        if path == "/api/dashboard/guilds":
            rows = []
            for guild in bot.guilds:
                if not _can_manage_session(bot, session, guild.id):
                    continue
                rows.append({
                    "id": str(guild.id),
                    "name": guild.name,
                    "members": int(guild.member_count or len(guild.members)),
                    "icon": str(guild.icon.url) if guild.icon else "",
                })
            rows.sort(key=lambda row: row["name"].casefold())
            handler._send_json(200, {"ok": True, "guilds": rows, "version": VERSION})
            return True
        query = urllib_parse.parse_qs(parsed.query or "")
        guild_id = _safe_int((query.get("guild_id") or [0])[0], 0)
        if not guild_id or not _can_manage_session(bot, session, guild_id):
            handler._send_json(403, {"ok": False, "error": "guild_forbidden"})
            return True
        guild = bot.get_guild(guild_id)
        if guild is None:
            handler._send_json(404, {"ok": False, "error": "guild_not_found"})
            return True
        if path == "/api/dashboard/settings":
            handler._send_json(200, {"ok": True, "settings": _settings_payload(world_data, guild)})
            return True
        handler._send_json(200, {"ok": True, "structure": _dashboard_structure(guild)})
        return True

    def post_hook(handler: Any, parsed: Any) -> bool:
        path = str(parsed.path or "")
        if path != "/api/dashboard/settings":
            return bool(previous_post(handler, parsed)) if callable(previous_post) else False
        session = _session(handler)
        if not session:
            handler._send_json(401, {"ok": False, "error": "login_required"})
            return True
        body = _body_json(handler)
        guild_id = _safe_int(body.get("guild_id"), 0)
        if not guild_id or not _can_manage_session(bot, session, guild_id):
            handler._send_json(403, {"ok": False, "error": "guild_forbidden"})
            return True
        guild = bot.get_guild(guild_id)
        if guild is None:
            handler._send_json(404, {"ok": False, "error": "guild_not_found"})
            return True
        with _DASHBOARD_LOCK:
            mgmt = _management_settings(world_data, guild_id)
            game = _game_settings(world_data, guild_id)
            voice = _temp_voice_state(world_data, guild_id)
            v1890 = _v1890_settings(world_data, guild_id)
            security = v1890["security"]
            anti = mgmt.setdefault("anti_raid", {})
            auto = mgmt["automod"]
            for key, target in (
                ("automod_enabled", "enabled"),
                ("invite_block", "invites"),
                ("bad_words_enabled", "bad_words"),
                ("auto_timeout", "auto_timeout"),
            ):
                if key in body:
                    auto[target] = bool(body.get(key))
            if "anti_raid_enabled" in body:
                anti["enabled"] = bool(body.get("anti_raid_enabled"))
                if not anti["enabled"]:
                    anti["raid_active"] = False
            if "anti_raid_auto_lockdown" in body:
                anti["auto_lockdown"] = bool(body.get("anti_raid_auto_lockdown"))
            if "destructive_watch_enabled" in body:
                security["destructive_watch_enabled"] = bool(body.get("destructive_watch_enabled"))
            if "destructive_watch_threshold" in body:
                security["threshold"] = max(2, min(20, _safe_int(body.get("destructive_watch_threshold"), 3)))
            if "destructive_watch_window_seconds" in body:
                security["window_seconds"] = max(5, min(300, _safe_int(body.get("destructive_watch_window_seconds"), 20)))

            for key, target in (
                ("story_enabled", "story_enabled"),
                ("codex_notifications", "codex_notifications"),
                ("tutorial_notifications", "tutorial_notifications"),
            ):
                if key in body:
                    game[target] = bool(body.get(key))

            def text_id(key: str) -> int:
                cid = _safe_int(body.get(key), 0)
                return cid if isinstance(guild.get_channel(cid), discord.TextChannel) else 0

            def category_id(key: str) -> int:
                cid = _safe_int(body.get(key), 0)
                return cid if isinstance(guild.get_channel(cid), discord.CategoryChannel) else 0

            if "welcome_channel_id" in body:
                mgmt["welcome_channel_id"] = text_id("welcome_channel_id")
            if "leave_channel_id" in body:
                mgmt["leave_channel_id"] = text_id("leave_channel_id")
            if "autorole_id" in body:
                rid = _safe_int(body.get("autorole_id"), 0)
                role = guild.get_role(rid)
                me = guild.me
                mgmt["autorole_id"] = role.id if role is not None and not role.is_default() and not role.managed and (me is None or role < me.top_role) else 0
            if "log_channel_id" in body:
                mgmt["log_channel_id"] = text_id("log_channel_id")
            if "ticket_log_channel_id" in body:
                mgmt["ticket_log_channel_id"] = text_id("ticket_log_channel_id")
            if "ticket_category_id" in body:
                mgmt["ticket_category_id"] = category_id("ticket_category_id")
            if "announcement_channel_id" in body:
                game["announcement_channel_id"] = text_id("announcement_channel_id") or None
            if "rpg_channel_id" in body:
                game["rpg_channel_id"] = text_id("rpg_channel_id") or None
            if "temp_voice_enabled" in body:
                # Enabling requires the Discord-side lobby to exist. The dashboard never creates channels from its HTTP thread.
                lobby = guild.get_channel(_safe_int(voice.get("lobby_id"), 0))
                voice["enabled"] = bool(body.get("temp_voice_enabled")) and isinstance(lobby, discord.VoiceChannel)
            if "button_role_ids" in body and isinstance(body.get("button_role_ids"), list):
                valid: List[int] = []
                me = guild.me
                for raw in body.get("button_role_ids", [])[:25]:
                    role = guild.get_role(_safe_int(raw, 0))
                    if role is None or role.is_default() or role.managed:
                        continue
                    if me is not None and role >= me.top_role:
                        continue
                    if role.id not in valid:
                        valid.append(role.id)
                mgmt["button_roles_v1850"]["role_ids"] = valid
                mgmt["button_roles_v1850"]["updated_by"] = _safe_int(session.get("user_id"), 0)
            save_data()
        handler._send_json(200, {"ok": True, "settings": _settings_payload(world_data, guild), "version": VERSION})
        return True

    setattr(bot, "_abaddon_public_http_get_hook", get_hook)
    setattr(bot, "_abaddon_public_http_post_hook", post_hook)


def register_v1850_community_dashboard(
    bot: commands.Bot,
    world_data: MutableMapping[str, Any],
    save_data,
) -> None:
    if getattr(bot, "_abaddon_v1850_registered", False):
        return
    bot._abaddon_v1850_registered = True
    bot.abaddon_version = VERSION

    try:
        bot.add_view(ButtonRoleLauncher(world_data))
        bot.add_view(CommunityQuickView(world_data))
    except ValueError:
        pass

    _install_dashboard_hooks(bot, world_data, save_data)

    # Replace the old text-wall server settings callback with one compact surface.
    server_settings = bot.get_command("서버설정")
    if server_settings is not None:
        previous = server_settings.callback

        async def settings_center(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            if ctx.guild is None or not isinstance(ctx.author, discord.Member):
                await ctx.send(_t(loc, "서버에서 사용해주세요.", "Use this inside a server."))
                return
            if not _manager(ctx.author):
                await ctx.send(_t(loc, "❌ 서버 관리 권한이 필요합니다.", "❌ Manage Server permission is required."))
                return
            await ctx.send(
                embed=_settings_embed(bot, world_data, ctx.guild, loc),
                view=ServerSettingsView(bot, world_data, save_data, ctx.author.id),
            )

        server_settings.callback = settings_center
        server_settings.help = "서버 운영·문의·음성·역할·RPG 설정을 한 화면에서 확인하고 관리합니다."
        server_settings.description = server_settings.help
        server_settings.extras = dict(getattr(server_settings, "extras", {}) or {})
        server_settings.extras["v1850_previous_callback"] = previous

    @bot.command(
        name="커뮤니티센터",
        aliases=["communitycenter", "communityhub"],
        help="문의·임시 음성·버튼 역할·도움말을 한눈에 여는 간단한 커뮤니티 허브입니다.",
    )
    async def community_center(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        embed = discord.Embed(
            title=_t(loc, "🏚️ ABADDON 커뮤니티 센터", "🏚️ ABADDON Community Center"),
            description=_t(loc, "생존에 필요한 지원만 바로 열면 됩니다.", "Open only the support you need."),
            color=0x57F287,
        )
        embed.add_field(name=_t(loc, "🎫 문의", "🎫 Support"), value=_t(loc, "버튼을 누르면 제작자 DM으로 문의·버그·신고를 바로 전달", "Send questions, bug reports and reports straight to the creator DM"), inline=True)
        embed.add_field(name=_t(loc, "🔊 임시 음성", "🔊 Temp voice"), value=_t(loc, "로비 입장 → 개인 음성방 자동 생성", "Join lobby → your room is created automatically"), inline=True)
        embed.add_field(name=_t(loc, "🎭 역할", "🎭 Roles"), value=_t(loc, "알림/관심 역할을 직접 선택", "Choose notification/interest roles yourself"), inline=True)
        embed.set_footer(text=f"ABADDON v{VERSION} · support @{SUPPORT_USERNAME} · one-touch support")
        await ctx.send(embed=embed, view=CommunityQuickView(world_data))

    @bot.command(
        name="패치점검",
        aliases=["patchcheck", "점검목록"],
        help="현재 최신 패치에서 직접 눌러봐야 할 핵심 기능 체크리스트를 보여줍니다.",
    )
    async def patch_check(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        embed = discord.Embed(
            title=_t(loc, "🧪 ABADDON v18.5.2 점검 목록", "🧪 ABADDON v18.5.2 test checklist"),
            description=_t(loc, "이번 패치 후 아래 명령/버튼만 순서대로 눌러보면 핵심 동작을 빠르게 확인할 수 있습니다.", "After this patch, run the items below in order to verify the core flows."),
            color=0xFEE75C,
        )
        embed.add_field(name="1) !커뮤니티센터", value=_t(loc, "`문의` 버튼 → 문의 모달이 열리고, 전송 후 제작자 DM으로 전달되는지 확인", "Press `Support` → the modal should open and the report should be delivered to the creator DM."), inline=False)
        embed.add_field(name="2) !문의패널", value=_t(loc, "기존 비공개 문의 채널 생성 버튼이 여전히 정상 생성되는지 확인", "Confirm the existing private ticket panel still creates a channel correctly."), inline=False)
        embed.add_field(name="3) !명령어", value=_t(loc, "메인 메뉴가 ABADDON 컨셉 문구로 바뀌었는지, `처음 시작/메인 RPG/검색` 버튼이 정상 동작하는지 확인", "Confirm the main menu uses the ABADDON-themed copy and buttons like Start/Main RPG/Search still work."), inline=False)
        embed.add_field(name="4) !서버설정 / !버튼역할패널", value=_t(loc, "서버 설정 화면이 열리고 역할 패널/역할 선택이 유지되는지 확인", "Open server settings and confirm the role panel / role selection still works."), inline=False)
        embed.add_field(name="5) !로그 / !채집 / !장비", value=_t(loc, "실제 명령이 아닌 키워드를 입력했을 때 관련 기능 핵심 버튼 + 드롭다운이 뜨는지 확인", "Type non-command keywords and confirm the related quick buttons + dropdown appear."), inline=False)
        embed.add_field(name="6) !웹대시보드 / !임시음성설정", value=_t(loc, "웹 대시보드 주소 안내와 임시 음성 생성 로비가 정상 동작하는지 확인", "Verify the web dashboard link and temp-voice lobby generation still work."), inline=False)
        embed.set_footer(text=_t(loc, "앞으로는 패치 배포 후 `!패치점검`만 실행해서 우선 점검하면 됩니다.", "From now on, run `!패치점검` first after each deployment."))
        await ctx.send(embed=embed)

    @bot.command(
        name="버튼역할설정",
        aliases=["buttonroleset", "buttonroles"],
        help="사용자가 버튼으로 직접 선택할 역할을 최대 25개 설정합니다.",
    )
    async def button_role_setup(ctx: commands.Context, 역할들: commands.Greedy[discord.Role]) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or not _manager(ctx.author):
            await ctx.send("❌ 서버 관리 권한이 필요합니다.")
            return
        me = ctx.guild.me
        usable: List[int] = []
        skipped: List[str] = []
        for role in list(역할들)[:25]:
            if role.is_default() or role.managed or (me is not None and role >= me.top_role):
                skipped.append(role.name)
                continue
            if role.id not in usable:
                usable.append(role.id)
        if not usable:
            await ctx.send("⚠️ 사용법: `!버튼역할설정 @게임알림 @월드보스알림`\n아바돈 역할보다 높은 역할/연동 역할은 사용할 수 없습니다.")
            return
        row = _management_settings(world_data, ctx.guild.id)["button_roles_v1850"]
        row["role_ids"] = usable
        row["updated_by"] = ctx.author.id
        save_data()
        text = "✅ 버튼 역할을 설정했습니다: " + ", ".join(ctx.guild.get_role(rid).mention for rid in usable if ctx.guild.get_role(rid))
        if skipped:
            text += "\n⚠️ 제외: " + ", ".join(skipped[:10])
        text += "\n이제 `!버튼역할패널`을 원하는 채널에서 실행하세요."
        await ctx.send(text)

    @bot.command(
        name="버튼역할패널",
        aliases=["buttonrolepanel", "rolebuttonpanel"],
        help="현재 채널에 재시작 후에도 살아있는 버튼 역할 패널을 설치합니다.",
    )
    async def button_role_panel(ctx: commands.Context, *, 제목: str = "서버 알림 역할") -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or not _manager(ctx.author):
            await ctx.send("❌ 서버 관리 권한이 필요합니다.")
            return
        settings = _management_settings(world_data, ctx.guild.id)
        roles = _valid_button_roles(ctx.guild, settings)
        if not roles:
            await ctx.send("⚠️ 먼저 `!버튼역할설정 @역할1 @역할2`를 실행해주세요.")
            return
        title = re.sub(r"[\r\n]", " ", 제목).strip()[:100] or "서버 알림 역할"
        settings["button_roles_v1850"]["title"] = title
        save_data()
        embed = discord.Embed(
            title=f"🎭 {title}",
            description="아래 **역할 선택** 버튼을 누른 뒤 받고 싶은 역할만 고르세요.\n선택을 해제하면 역할도 자동으로 회수됩니다.\n\n" + "\n".join(f"• {role.mention}" for role in roles),
            color=0x5865F2,
        )
        embed.set_footer(text="ABADDON BUTTON ROLES · 재시작 후에도 버튼 연결 유지")
        await ctx.send(embed=embed, view=ButtonRoleLauncher(world_data))

    @bot.command(
        name="버튼역할상태",
        aliases=["buttonrolestatus"],
        help="현재 서버의 버튼 역할 설정을 확인합니다.",
    )
    async def button_role_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        roles = _valid_button_roles(ctx.guild, _management_settings(world_data, ctx.guild.id))
        await ctx.send("🎭 **버튼 역할 상태**\n" + ("\n".join(f"• {role.mention}" for role in roles) if roles else "설정된 역할 없음"))

    @bot.command(
        name="웹대시보드",
        aliases=["webdashboard", "serverdashboard"],
        help="ABADDON 공식 웹 서버 설정 대시보드 주소를 확인합니다.",
    )
    async def web_dashboard(ctx: commands.Context) -> None:
        site = str(os.getenv("ABADDON_SITE_URL", "") or "").rstrip("/")
        if not site:
            await ctx.send("🌐 웹 대시보드 파일은 포함되어 있지만 Render의 `ABADDON_SITE_URL` 설정이 필요합니다. `!서버진단`으로 확인해주세요.")
            return
        await ctx.send(f"🌐 **ABADDON 서버 대시보드**\n{site}/dashboard.html\nDiscord 로그인 후 **본인이 관리할 수 있는 서버만** 표시됩니다.")

    @bot.command(
        name="1850검수",
        aliases=["1850audit", "communityaudit"],
        hidden=True,
        help="[봇 소유자 전용] v18.5 커뮤니티/웹 대시보드 통합 상태를 검사합니다.",
    )
    async def audit_1850(ctx: commands.Context) -> None:
        try:
            if not await bot.is_owner(ctx.author):
                return
        except Exception:
            return
        required = ["서버설정", "커뮤니티센터", "문의패널", "접수패널", "임시음성설정", "버튼역할설정", "버튼역할패널", "버튼역할상태", "웹대시보드", "자동관리", "로그채널"]
        rows = [(name, bot.get_command(name) is not None) for name in required]
        custom_ids = []
        for view in (ButtonRoleLauncher(world_data), CommunityQuickView(world_data)):
            custom_ids.extend(str(getattr(item, "custom_id", "")) for item in view.children if getattr(item, "custom_id", None))
        checks = [
            ("명령 연결", all(ok for _, ok in rows)),
            ("Persistent custom_id", len(custom_ids) == len(set(custom_ids)) and bool(custom_ids)),
            ("Dashboard GET hook", callable(getattr(bot, "_abaddon_public_http_get_hook", None))),
            ("Dashboard POST hook", callable(getattr(bot, "_abaddon_public_http_post_hook", None))),
            ("지원 연락처", getattr(bot, "abaddon_support_username", SUPPORT_USERNAME) == SUPPORT_USERNAME),
        ]
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 통합 검수", color=0x57F287 if all(ok for _, ok in checks) else 0xFEE75C)
        embed.description = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks)
        embed.add_field(name="명령", value=" · ".join(f"{'✅' if ok else '❌'}{name}" for name, ok in rows)[:1024], inline=False)
        embed.add_field(name="Persistent IDs", value="\n".join(custom_ids) or "없음", inline=False)
        embed.add_field(name="웹 환경", value=f"SITE `{bool(os.getenv('ABADDON_SITE_URL'))}` · OAuth ID `{bool(os.getenv('DISCORD_OAUTH_CLIENT_ID'))}` · OAuth Secret `{bool(os.getenv('DISCORD_OAUTH_CLIENT_SECRET'))}` · Redirect `{bool(os.getenv('DISCORD_OAUTH_REDIRECT_URI'))}`", inline=False)
        await ctx.send(embed=embed)

    # Live command hubs rebuild from registered commands. Refresh their cached metadata too.
    try:
        from apocalypse_bot.commands.v1831_persistent_command_hub import _refresh_registry
        _refresh_registry(bot)
    except Exception:
        pass
    try:
        from apocalypse_bot.commands.v1832_bilingual_persistent_hub import _sync_registry
        _sync_registry(bot)
    except Exception:
        pass

    print(
        f"[ABADDON v{VERSION}] community/dashboard registered · existing_guard=reused "
        f"button_roles=persistent dashboard_api=get+post",
        flush=True,
    )


def finalize_v1850_surfaces(bot: commands.Bot) -> None:
    """Run after later presentation patches so the visible version stays current."""
    if getattr(bot, "_abaddon_v1850_finalized", False):
        return
    bot._abaddon_v1850_finalized = True
    bot.abaddon_version = VERSION

    intro = bot.get_command("봇소개")
    if intro is not None:
        async def bot_info(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            embed = discord.Embed(
                title=_t(loc, "🛰️ ABADDON · 종말 생존 RPG", "🛰️ ABADDON · Apocalypse Survival RPG"),
                description=_t(
                    loc,
                    "스토리·전투·채집·경제뿐 아니라 문의·보안·임시 음성·역할·웹 관리까지 하나로 이어지는 Discord 생존 플랫폼입니다.",
                    "A Discord survival platform connecting story, combat, gathering and economy with tickets, protection, temporary voice, roles and web administration.",
                ),
                color=0xC8AA62,
            )
            fields = [
                (_t(loc, "🌱 쉬운 시작", "🌱 Easy start"), _t(loc, "`!첫10분` → `!명령어`", "`!first10` → `!commands`")),
                (_t(loc, "🏠 커뮤니티", "🏠 Community"), _t(loc, "`!커뮤니티센터` · 문의/임시음성/버튼역할", "`!communitycenter` · tickets/temp voice/button roles")),
                (_t(loc, "⚙️ 서버 관리", "⚙️ Server management"), _t(loc, "`!서버설정` · `!웹대시보드`", "`!serverconfig` · `!webdashboard`")),
                (_t(loc, "🛡️ 안정화", "🛡️ Reliability"), _t(loc, "영구 핵심 UI · 자동 오류 DM · SQLite/백업 · 서버진단", "Persistent core UI · owner error DM · SQLite/backups · server diagnostics")),
                (_t(loc, "🛟 장애 문의", "🛟 Bug support"), f"Discord DM **`{SUPPORT_USERNAME}`**"),
            ]
            for name, value in fields:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=f"ABADDON v{VERSION} · support @{SUPPORT_USERNAME}")
            await ctx.send(embed=embed)
        intro.callback = bot_info
        intro.help = "ABADDON v18.5 최신 기능과 서버/커뮤니티 관리 진입점을 확인합니다."
        intro.description = intro.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_note(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            loc = _locale(bot, ctx)
            embed = discord.Embed(title="🏠 ABADDON v18.5.0 — COMMUNITY & WEB DASHBOARD", color=0x5865F2)
            embed.description = _t(loc, "흩어져 있던 서버 운영 기능을 하나의 쉬운 진입점으로 통합하고 웹 설정을 추가했습니다.", "Consolidates scattered server tools into one simple entry point and adds web configuration.")
            embed.add_field(name=_t(loc, "⚙️ 서버 설정 센터", "⚙️ Server settings"), value="`!서버설정`", inline=True)
            embed.add_field(name=_t(loc, "🏠 커뮤니티 센터", "🏠 Community center"), value="`!커뮤니티센터`", inline=True)
            embed.add_field(name=_t(loc, "🎭 버튼 역할", "🎭 Button roles"), value="`!버튼역할설정` → `!버튼역할패널`", inline=False)
            embed.add_field(name=_t(loc, "🔊·🎫 기존 기능 재사용", "🔊·🎫 Existing systems reused"), value=_t(loc, "문의/접수·임시 음성·모더레이션·로그를 중복 구현하지 않고 기존 데이터와 그대로 연결", "Tickets/intake, temp voice, moderation and logs reuse the existing data and proven systems."), inline=False)
            embed.add_field(name=_t(loc, "🌐 웹 대시보드", "🌐 Web dashboard"), value="`!웹대시보드` · Discord OAuth · 관리 가능한 서버만 표시", inline=False)
            embed.add_field(name=_t(loc, "🛟 문의", "🛟 Support"), value=f"Discord DM `{SUPPORT_USERNAME}`", inline=False)
            embed.set_footer(text="게임 유저 데이터 구조 변경 없음 · /var/data 유지")
            await ctx.send(embed=embed)
        patch.callback = patch_note
        patch.help = "ABADDON v18.5.0 커뮤니티/서버관리/웹 대시보드 패치노트입니다."
        patch.description = patch.help

    print(f"[ABADDON v{VERSION}] final public surfaces active", flush=True)
