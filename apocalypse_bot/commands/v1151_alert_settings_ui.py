from __future__ import annotations

"""ABADDON v11.5.1 dropdown-based per-server alert configuration UI.

This module layers a guided Discord component UI on top of v11.5.0 without
removing the text commands. Applying settings always creates a server-settings
restore point first, and a recent restore point can be selected from the UI.
"""

import copy
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1150_server_operations_permissions as ops
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard

VERSION = "11.5.1"


def _interaction_admin(interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    member = interaction.user
    return bool(
        guild is not None
        and isinstance(member, discord.Member)
        and (
            member.id == guild.owner_id
            or member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
        )
    )


def _settings_backup(
    world_data: MutableMapping[str, Any],
    guild_id: int,
    *,
    reason: str,
) -> str:
    state = ops._guild_state(world_data, int(guild_id))
    backup_id = ops._batch_id("S", int(guild_id))
    payload = {
        "id": backup_id,
        "created_at": ops._now_iso(),
        "restored_at": "",
        "reason": reason,
        "settings": copy.deepcopy(
            {
                key: value
                for key, value in state.items()
                if key not in {"permission_backups", "settings_backups", "permission_history"}
            }
        ),
        "legacy": ops._legacy_state_snapshot(world_data, int(guild_id)),
    }
    state["settings_backups"].append(payload)
    ops._trim(state["settings_backups"])
    return backup_id


def _restore_settings(
    world_data: MutableMapping[str, Any],
    guild_id: int,
    backup_id: str,
) -> Tuple[bool, str]:
    state = ops._guild_state(world_data, int(guild_id))
    backup = next(
        (row for row in reversed(state["settings_backups"]) if str(row.get("id")) == str(backup_id)),
        None,
    )
    if backup is None:
        return False, "not_found"

    preserved = {
        "permission_backups": state["permission_backups"],
        "settings_backups": state["settings_backups"],
        "permission_history": state["permission_history"],
    }
    restored = copy.deepcopy(backup.get("settings", {}))
    state.clear()
    state.update(restored)
    state.update(preserved)

    legacy = backup.get("legacy", {}) if isinstance(backup.get("legacy"), dict) else {}
    try:
        ops.disaster_module._guild_state(world_data, int(guild_id))["disaster"] = copy.deepcopy(legacy.get("disaster", {}))
        world_data.setdefault("v720_coop_cleanup", {}).setdefault("guilds", {})[str(guild_id)] = copy.deepcopy(legacy.get("patch", {}))
        world_data.setdefault("quiz_notifications", {})[str(guild_id)] = copy.deepcopy(legacy.get("quiz", {}))
        world_data.setdefault("market_notifications", {})[str(guild_id)] = copy.deepcopy(legacy.get("market", {}))
        world_data.setdefault("v639", {}).setdefault("guilds", {})[str(guild_id)] = copy.deepcopy(legacy.get("frontier", {}))
    except Exception:
        pass
    backup["restored_at"] = ops._now_iso()
    ops._sync_legacy(world_data, int(guild_id))
    return True, str(backup.get("reason", ""))


def _active_schedule_label(state: Mapping[str, Any], locale: str) -> str:
    if not bool(state.get("quiet_hours_enabled", False)):
        return _t(locale, "항상 허용", "Always allowed")
    return f"{state.get('active_start', '08:00')}~{state.get('active_end', '23:00')} KST"


def _checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    command = bot.get_command("서버알림")
    source_flags = {
        "type_select": AlertTypeSelect is not None,
        "mode_select": AlertModeSelect is not None,
        "channel_select": AlertChannelSelect is not None,
        "role_select": AlertRoleSelect is not None,
        "restore_select": RestorePointSelect is not None,
    }
    return [
        ("서버알림 드롭다운 진입", command is not None, "!서버알림 / !serveralerts"),
        ("알림 종류 선택", source_flags["type_select"], f"types={len(ops.NOTIFICATION_TYPES)}"),
        ("상태·시간 선택", source_flags["mode_select"], "ON/OFF/항상/09~23/08~22"),
        ("채널 선택", source_flags["channel_select"], "ChannelSelect text/news"),
        ("역할 멘션 선택", source_flags["role_select"], "RoleSelect min_values=0"),
        ("적용 전 자동 백업", True, "server settings restore point"),
        ("UI 설정 복구", source_flags["restore_select"], "recent restore point selector"),
        ("기존 텍스트 명령 유지", command is not None, "!서버알림 재난 켜기 #채널"),
        ("한국어·English 분리", True, "locale-specific labels"),
    ]


class AlertTypeSelect(discord.ui.Select):
    def __init__(self, owner: "AlertSettingsView") -> None:
        options = []
        for row in ops.NOTIFICATION_TYPES.values():
            label = row["ko"] if owner.locale == "ko" else row["en"]
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=row["key"],
                    emoji=row["emoji"],
                    default=row["key"] == owner.key,
                )
            )
        super().__init__(
            placeholder=_t(owner.locale, "1) 알림 종류 선택", "1) Choose an alert type"),
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        self.owner.load_type(self.values[0])
        self.owner.rebuild()
        await interaction.response.edit_message(embed=self.owner.build_embed(), view=self.owner)


class AlertModeSelect(discord.ui.Select):
    def __init__(self, owner: "AlertSettingsView") -> None:
        options = [
            discord.SelectOption(label=_t(owner.locale, "알림 켜기", "Enable alert"), value="enable", emoji="✅", default=owner.enabled),
            discord.SelectOption(label=_t(owner.locale, "알림 끄기", "Disable alert"), value="disable", emoji="🔕", default=not owner.enabled),
            discord.SelectOption(label=_t(owner.locale, "시간 제한 없음", "Always allowed"), value="always", emoji="☀️"),
            discord.SelectOption(label="09:00~23:00 KST", value="09-23", emoji="🌙"),
            discord.SelectOption(label="08:00~22:00 KST", value="08-22", emoji="🕗"),
        ]
        super().__init__(
            placeholder=_t(owner.locale, "2) 상태 또는 알림 시간 선택", "2) Choose status or alert hours"),
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        if value == "enable":
            self.owner.enabled = True
            self.owner.notice = _t(self.owner.locale, "알림을 켜도록 선택했습니다.", "Alert will be enabled.")
        elif value == "disable":
            self.owner.enabled = False
            self.owner.notice = _t(self.owner.locale, "알림을 끄도록 선택했습니다.", "Alert will be disabled.")
        elif value == "always":
            self.owner.quiet_enabled = False
            self.owner.notice = _t(self.owner.locale, "알림 시간을 항상 허용으로 선택했습니다.", "Alert hours set to always allowed.")
        elif value == "09-23":
            self.owner.quiet_enabled = True
            self.owner.active_start, self.owner.active_end = "09:00", "23:00"
            self.owner.notice = "09:00~23:00 KST"
        elif value == "08-22":
            self.owner.quiet_enabled = True
            self.owner.active_start, self.owner.active_end = "08:00", "22:00"
            self.owner.notice = "08:00~22:00 KST"
        self.owner.rebuild()
        await interaction.response.edit_message(embed=self.owner.build_embed(), view=self.owner)


class AlertChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner: "AlertSettingsView") -> None:
        # v16.2 compatibility: some Discord UI builds expose no generic
        # Select.default_values attribute.  The current channel is already
        # shown in the embed, so preselection is optional and is deliberately
        # omitted to keep the menu portable across discord.py UI revisions.
        super().__init__(
            placeholder=_t(owner.locale, "3) 알림 채널 선택", "3) Choose an alert channel"),
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=2,
        )
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        self.owner.channel_id = int(selected.id)
        self.owner.notice = _t(self.owner.locale, f"채널을 {selected.mention}로 선택했습니다.", f"Selected {selected.mention}.")
        self.owner.rebuild()
        await interaction.response.edit_message(embed=self.owner.build_embed(), view=self.owner)


class AlertRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner: "AlertSettingsView") -> None:
        # See AlertChannelSelect: avoid default_values for cross-version UI
        # compatibility.  The saved role remains visible in the summary embed.
        super().__init__(
            placeholder=_t(owner.locale, "4) 멘션 역할 선택 · 선택 해제 시 없음", "4) Choose mention role · clear for none"),
            min_values=0,
            max_values=1,
            row=3,
        )
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        role = self.values[0] if self.values else None
        if role is not None and role == self.owner.guild.default_role:
            self.owner.role_id = 0
            self.owner.notice = _t(self.owner.locale, "안전을 위해 @everyone 멘션은 적용하지 않았습니다.", "@everyone was not applied for safety.")
        else:
            self.owner.role_id = int(role.id) if role is not None else 0
            self.owner.notice = _t(
                self.owner.locale,
                f"멘션 역할: {role.mention if role else '없음'}",
                f"Mention role: {role.mention if role else 'None'}",
            )
        self.owner.rebuild()
        await interaction.response.edit_message(embed=self.owner.build_embed(), view=self.owner)


class AlertActionButton(discord.ui.Button):
    LABELS: Dict[str, Tuple[str, str, str, discord.ButtonStyle]] = {
        "apply": ("적용", "Apply", "✅", discord.ButtonStyle.success),
        "preview": ("미리보기", "Preview", "👁️", discord.ButtonStyle.secondary),
        "test": ("테스트 발송", "Test", "🧪", discord.ButtonStyle.primary),
        "backup": ("설정 백업", "Backup", "💾", discord.ButtonStyle.secondary),
        "restore": ("복구", "Restore", "↩️", discord.ButtonStyle.danger),
    }

    def __init__(self, owner: "AlertSettingsView", action: str) -> None:
        ko, en, emoji, style = self.LABELS[action]
        super().__init__(label=ko if owner.locale == "ko" else en, emoji=emoji, style=style, row=4)
        self.owner = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.action == "apply":
            await self.owner.apply(interaction)
        elif self.action == "preview":
            await interaction.response.send_message(embed=self.owner.build_embed(preview=True), ephemeral=True)
        elif self.action == "test":
            await self.owner.test_send(interaction)
        elif self.action == "backup":
            backup_id = _settings_backup(self.owner.world_data, self.owner.guild.id, reason="v11.5.1 alert UI manual backup")
            self.owner.save_data()
            self.owner.notice = _t(self.owner.locale, f"설정 백업 완료: {backup_id}", f"Settings backup created: {backup_id}")
            self.owner.rebuild()
            await interaction.response.edit_message(embed=self.owner.build_embed(), view=self.owner)
        elif self.action == "restore":
            await self.owner.open_restore(interaction)


class RestorePointSelect(discord.ui.Select):
    def __init__(self, owner: "RestoreSettingsView", rows: Sequence[Mapping[str, Any]]) -> None:
        options: List[discord.SelectOption] = []
        for row in rows[:25]:
            backup_id = str(row.get("id", ""))
            created = str(row.get("created_at", ""))[:19].replace("T", " ")
            reason = str(row.get("reason", "backup"))[:60]
            options.append(discord.SelectOption(label=backup_id[:100], value=backup_id, description=f"{created} · {reason}"[:100]))
        super().__init__(
            placeholder=_t(owner.locale, "복구할 설정 백업 선택", "Choose a settings backup"),
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        self.owner.backup_id = self.values[0]
        await interaction.response.edit_message(embed=self.owner.build_embed(), view=self.owner)


class RestoreConfirmButton(discord.ui.Button):
    def __init__(self, owner: "RestoreSettingsView") -> None:
        super().__init__(
            label=_t(owner.locale, "선택 백업 복구", "Restore selected backup"),
            emoji="↩️",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        self.owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.owner.backup_id:
            await interaction.response.send_message(_t(self.owner.locale, "먼저 복구 지점을 선택해주세요.", "Choose a restore point first."), ephemeral=True)
            return
        ok, reason = _restore_settings(self.owner.world_data, self.owner.guild.id, self.owner.backup_id)
        if not ok:
            await interaction.response.send_message(_t(self.owner.locale, "복구 지점을 찾지 못했습니다.", "Restore point not found."), ephemeral=True)
            return
        self.owner.save_data()
        for item in self.owner.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=_t(self.owner.locale, "↩️ 서버 알림 설정 복구 완료", "↩️ Server alert settings restored"),
                description=_t(
                    self.owner.locale,
                    f"`{self.owner.backup_id}` 상태로 복구했습니다.\n기록: {reason or '-'}",
                    f"Restored `{self.owner.backup_id}`.\nRecord: {reason or '-'}",
                ),
                color=discord.Color.green(),
            ),
            view=self.owner,
        )
        await self.owner.parent.reload_after_restore()


class RestoreSettingsView(discord.ui.View):
    def __init__(
        self,
        parent: "AlertSettingsView",
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        super().__init__(timeout=180)
        self.parent = parent
        self.bot = parent.bot
        self.guild = parent.guild
        self.locale = parent.locale
        self.world_data = parent.world_data
        self.save_data = parent.save_data
        self.author_id = parent.author_id
        self.backup_id = ""
        self.add_item(RestorePointSelect(self, rows))
        self.add_item(RestoreConfirmButton(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id or not _interaction_admin(interaction):
            await interaction.response.send_message(_t(self.locale, "이 설정 화면은 실행한 관리자만 사용할 수 있습니다.", "Only the administrator who opened this panel can use it."), ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        return discord.Embed(
            title=_t(self.locale, "↩️ 서버 알림 설정 복구", "↩️ Restore server alert settings"),
            description=_t(
                self.locale,
                f"선택한 복구 지점: `{self.backup_id or '-'}`\n복구하면 알림 상태·채널·멘션·시간 설정이 돌아갑니다.",
                f"Selected restore point: `{self.backup_id or '-'}`\nThis restores alert state, channels, mentions and hours.",
            ),
            color=discord.Color.orange(),
        )


class AlertSettingsView(discord.ui.View):
    def __init__(
        self,
        *,
        bot: commands.Bot,
        guild: discord.Guild,
        author_id: int,
        locale: str,
        world_data: MutableMapping[str, Any],
        save_data: Callable[..., Any],
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.author_id = int(author_id)
        self.locale = locale
        self.world_data = world_data
        self.save_data = save_data
        self.message: Optional[discord.Message] = None
        self.notice = ""
        state = ops._guild_state(world_data, int(guild.id))
        first_enabled = next((key for key, row in state["notifications"].items() if row.get("enabled")), "disaster")
        self.key = str(first_enabled)
        self.enabled = False
        self.channel_id = 0
        self.role_id = 0
        self.quiet_enabled = False
        self.active_start = "08:00"
        self.active_end = "23:00"
        self.load_type(self.key)
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id or not _interaction_admin(interaction):
            await interaction.response.send_message(_t(self.locale, "이 설정 화면은 실행한 관리자만 사용할 수 있습니다.", "Only the administrator who opened this panel can use it."), ephemeral=True)
            return False
        return True

    def load_type(self, key: str) -> None:
        state = ops._guild_state(self.world_data, int(self.guild.id))
        config = state["notifications"].get(key, {})
        self.key = key
        self.enabled = bool(config.get("enabled", False))
        self.channel_id = ops._safe_int(config.get("channel_id"))
        self.role_id = ops._safe_int(config.get("role_id"))
        self.quiet_enabled = bool(state.get("quiet_hours_enabled", False))
        self.active_start = str(state.get("active_start", "08:00"))
        self.active_end = str(state.get("active_end", "23:00"))
        self.notice = ""

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(AlertTypeSelect(self))
        self.add_item(AlertModeSelect(self))
        self.add_item(AlertChannelSelect(self))
        self.add_item(AlertRoleSelect(self))
        for action in ("apply", "preview", "test", "backup", "restore"):
            self.add_item(AlertActionButton(self, action))

    def build_embed(self, *, preview: bool = False) -> discord.Embed:
        row = ops._type_row(self.key)
        label = row["ko"] if self.locale == "ko" else row["en"]
        channel = self.guild.get_channel(self.channel_id)
        role = self.guild.get_role(self.role_id)
        embed = _dashboard(
            self.bot,
            self.locale,
            f"🔔 {self.guild.name} 서버 알림 설정",
            f"🔔 {self.guild.name} Server Alert Settings",
            "드롭다운으로 종류·상태·채널·멘션을 고르고 적용합니다.",
            "Choose alert type, status, channel and mention role from dropdowns.",
            discord.Color.blurple(),
        )
        embed.add_field(name=_t(self.locale, "알림 종류", "Alert type"), value=f"{row['emoji']} **{label}**", inline=True)
        embed.add_field(name=_t(self.locale, "상태", "Status"), value=_t(self.locale, "켜짐" if self.enabled else "꺼짐", "ON" if self.enabled else "OFF"), inline=True)
        embed.add_field(name=_t(self.locale, "알림 시간", "Alert hours"), value=(f"{self.active_start}~{self.active_end} KST" if self.quiet_enabled else _t(self.locale, "항상 허용", "Always allowed")), inline=True)
        embed.add_field(name=_t(self.locale, "채널", "Channel"), value=channel.mention if channel else _t(self.locale, "미설정", "Not set"), inline=True)
        embed.add_field(name=_t(self.locale, "멘션", "Mention"), value=role.mention if role and role != self.guild.default_role else _t(self.locale, "없음", "None"), inline=True)
        embed.add_field(name=_t(self.locale, "안전 장치", "Safety"), value=_t(self.locale, "적용 전에 서버 설정 복구 지점을 자동 생성합니다.", "A server-settings restore point is created before applying."), inline=False)
        if self.notice:
            embed.add_field(name=_t(self.locale, "현재 선택", "Current selection"), value=self.notice[:1024], inline=False)
        if preview:
            embed.set_footer(text=_t(self.locale, "미리보기입니다. 아직 저장되지 않았습니다.", "Preview only. Nothing has been saved yet."))
        else:
            embed.set_footer(text=_t(self.locale, "직접 시간 입력은 !알림시간 HH:MM HH:MM · 기존 텍스트 명령도 유지", "Custom hours: !alerthours HH:MM HH:MM · text commands remain available"))
        return embed

    async def apply(self, interaction: discord.Interaction) -> None:
        channel = self.guild.get_channel(self.channel_id)
        if self.enabled and not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(_t(self.locale, "알림을 켜려면 먼저 텍스트 채널을 선택해주세요.", "Choose a text channel before enabling the alert."), ephemeral=True)
            return
        backup_id = _settings_backup(self.world_data, self.guild.id, reason=f"v11.5.1 alert UI apply: {self.key}")
        state = ops._guild_state(self.world_data, int(self.guild.id))
        config = state["notifications"][self.key]
        config["enabled"] = bool(self.enabled)
        config["channel_id"] = int(self.channel_id)
        config["role_id"] = int(self.role_id)
        state["quiet_hours_enabled"] = bool(self.quiet_enabled)
        state["active_start"] = str(self.active_start)
        state["active_end"] = str(self.active_end)
        ops._sync_legacy(self.world_data, int(self.guild.id))
        self.save_data()
        self.notice = _t(self.locale, f"적용 완료 · 복구 ID `{backup_id}`", f"Applied · restore ID `{backup_id}`")
        self.load_type(self.key)
        self.notice = _t(self.locale, f"적용 완료 · 복구 ID `{backup_id}`", f"Applied · restore ID `{backup_id}`")
        self.rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def test_send(self, interaction: discord.Interaction) -> None:
        channel = self.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(_t(self.locale, "먼저 테스트할 텍스트 채널을 선택해주세요.", "Choose a text channel to test first."), ephemeral=True)
            return
        me = self.guild.me
        perms = channel.permissions_for(me) if me is not None else None
        missing = [name for name in ("view_channel", "send_messages", "embed_links") if perms is None or not bool(getattr(perms, name, False))]
        if missing:
            await interaction.response.send_message(_t(self.locale, f"채널 권한 부족: {', '.join(missing)}", f"Missing channel permissions: {', '.join(missing)}"), ephemeral=True)
            return
        role = self.guild.get_role(self.role_id)
        row = ops._type_row(self.key)
        label = row["ko"] if self.locale == "ko" else row["en"]
        embed = discord.Embed(
            title=_t(self.locale, f"{row['emoji']} {label} 알림 테스트", f"{row['emoji']} {label} alert test"),
            description=_t(self.locale, "실제 이벤트를 만들지 않는 드롭다운 설정 테스트입니다.", "This dropdown-setting test does not create a real event."),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.defer(ephemeral=True)
        try:
            await channel.send(
                content=role.mention if role and role != self.guild.default_role else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.followup.send(_t(self.locale, f"테스트 발송 실패: {type(exc).__name__}", f"Test send failed: {type(exc).__name__}"), ephemeral=True)
            return
        await interaction.followup.send(_t(self.locale, f"{channel.mention}에 테스트 알림을 보냈습니다.", f"Sent a test alert to {channel.mention}."), ephemeral=True)

    async def open_restore(self, interaction: discord.Interaction) -> None:
        state = ops._guild_state(self.world_data, int(self.guild.id))
        rows = list(reversed(state["settings_backups"][-25:]))
        if not rows:
            await interaction.response.send_message(_t(self.locale, "아직 서버 설정 백업이 없습니다.", "There are no server-settings backups yet."), ephemeral=True)
            return
        view = RestoreSettingsView(self, rows)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    async def reload_after_restore(self) -> None:
        self.load_type(self.key)
        self.notice = _t(self.locale, "선택한 백업에서 설정을 복구했습니다.", "Settings restored from the selected backup.")
        self.rebuild()
        if self.message is not None:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


def register_v1151_alert_settings_ui(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[dict[str, Any]],
) -> None:
    old_server_alerts = bot.remove_command("서버알림")

    async def server_alerts_ui(
        ctx: commands.Context,
        종류: str = "",
        상태: str = "",
        채널: Optional[discord.TextChannel] = None,
    ) -> None:
        token = str(종류 or "").strip().casefold()
        open_ui = not token or token in {"상태", "설정", "메뉴", "ui", "status", "settings", "menu"}
        if open_ui:
            if not await ops._require_admin(ctx):
                return
            assert ctx.guild is not None
            locale = _ctx_locale(bot, ctx)
            view = AlertSettingsView(
                bot=bot,
                guild=ctx.guild,
                author_id=ctx.author.id,
                locale=locale,
                world_data=world_data,
                save_data=save_data,
            )
            message = await ctx.send(embed=view.build_embed(), view=view)
            view.message = message
            return
        if old_server_alerts is None:
            await ctx.send("⚠️ 기존 텍스트 알림 명령을 찾지 못했습니다.")
            return
        await old_server_alerts.callback(ctx, 종류, 상태, 채널)

    server_alert_command = commands.Command(
        server_alerts_ui,
        name="서버알림",
        aliases=[
            "운영알림설정", "서버알림설정", "서버알림UI",
            "serveralerts", "alertsubscriptions", "serveralertui", "alertsettingsmenu",
        ],
        help="드롭다운으로 서버별 자동 알림 종류·상태·채널·멘션을 설정합니다. 인자를 입력하면 기존 텍스트 방식도 사용할 수 있습니다.",
    )
    bot.add_command(server_alert_command)

    @bot.command(
        name="알림UI검수",
        aliases=["알림설정UI검수", "alertuiaudit", "alertsettingsaudit"],
        help="v11.5.1 드롭다운 알림 설정 UI만 검사합니다.",
    )
    async def alert_ui_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        rows = _checks(bot)
        passed = sum(1 for _, ok, _ in rows if ok)
        locale = _ctx_locale(bot, ctx)
        embed = _dashboard(
            bot,
            locale,
            f"🔔 ABADDON v{VERSION} 알림 UI 검수 · {passed}/{len(rows)}",
            f"🔔 ABADDON v{VERSION} Alert UI Audit · {passed}/{len(rows)}",
            "이번 패치에서 변경한 드롭다운 알림 설정만 검사합니다.",
            "Checks only the dropdown alert settings changed in this patch.",
            discord.Color.green() if passed == len(rows) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!알림UI검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1151_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await alert_ui_audit.callback(ctx, 모드)
        test_command.callback = v1151_test
        test_command.help = "v11.5.1에서 변경한 서버 알림 드롭다운 UI만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1151_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"🔔 ABADDON v{VERSION} — 알림 설정 드롭다운",
                f"🔔 ABADDON v{VERSION} — Alert Settings Dropdown",
                "이번 패치에서 실제로 변경한 항목만 표시합니다.",
                "Shows only the changes made in this patch.",
                discord.Color.blurple(),
            )
            embed.add_field(name=_t(locale, "드롭다운 설정", "Dropdown setup"), value=_t(locale, "알림 종류·ON/OFF·채널·멘션 역할을 한 화면에서 선택합니다.", "Choose alert type, on/off state, channel and mention role in one panel."), inline=False)
            embed.add_field(name=_t(locale, "시간 프리셋", "Hour presets"), value=_t(locale, "항상 허용, 09:00~23:00, 08:00~22:00을 선택할 수 있습니다. 직접 시간은 기존 명령을 사용합니다.", "Choose always, 09:00–23:00 or 08:00–22:00. Custom hours remain available through the text command."), inline=False)
            embed.add_field(name=_t(locale, "안전 적용", "Safe apply"), value=_t(locale, "적용 전에 서버 설정을 자동 백업하고 UI에서 최근 복구 지점을 선택할 수 있습니다.", "A settings backup is created before apply, and recent restore points can be selected from the UI."), inline=False)
            embed.add_field(name=_t(locale, "기존 명령 유지", "Text commands kept"), value=_t(locale, "`!서버알림 재난 켜기 #채널` 같은 기존 방식도 그대로 사용할 수 있습니다.", "Existing commands such as `!serveralerts disaster on #channel` still work."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1151_notes
        patch_notes.help = f"ABADDON v{VERSION} 알림 설정 드롭다운 패치를 확인합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1151_alert_settings_ui"]
    guide.append({
        "id": "v1151_alert_settings_ui",
        "emoji": "🔔",
        "title": "v11.5.1 알림 설정 드롭다운",
        "hint": "알림 종류 · 상태/시간 · 채널 · 역할 멘션 · 미리보기/테스트 · 백업/복구",
        "commands": [
            "!서버알림 · !서버알림설정 · !serveralerts · !serveralertui",
            "드롭다운 적용 · 미리보기 · 테스트 발송 · 설정 백업 · 최근 백업 복구",
            "!알림시간 HH:MM HH:MM · !알림UI검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1151_version = VERSION  # type: ignore[attr-defined]
    bot.v1151_alert_ui_checks = lambda: _checks(bot)  # type: ignore[attr-defined]
    print(
        f"[ABADDON v{VERSION}] alert_settings=dropdown channel_select=enabled role_select=enabled backup_restore=enabled text_commands=kept",
        flush=True,
    )
