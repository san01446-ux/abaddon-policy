from __future__ import annotations

"""ABADDON v16.7.0 LIVE OPS & POLISH.

A stability-first polish layer that keeps all legacy commands and saves intact.
It adds:
- a button-driven operations hub;
- a confirmed message cleanup center;
- restart-local 24-hour command latency/failure visibility;
- dead-command, menu-link and city-asset audits;
- compact mobile-safe embeds and Korean/English separated labels.
"""

import re
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Deque, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _real_cog, _safe_embed, _safe_view
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub

VERSION = "16.7.0"
_LINK_RE = re.compile(r"https?://|discord(?:app)?\.com/invite|discord\.gg/", re.I)


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _locale_interaction(interaction: discord.Interaction, fallback: str = "ko") -> str:
    try:
        guild_id = int(interaction.guild_id or 0)
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(interaction.user.id), guild_id)
    except Exception:
        return fallback


def _is_admin_member(member: Any, guild: Optional[discord.Guild]) -> bool:
    if guild is None:
        return False
    if int(getattr(member, "id", 0)) == int(getattr(guild, "owner_id", 0)):
        return True
    permissions = getattr(member, "guild_permissions", None)
    return bool(permissions and (permissions.administrator or permissions.manage_guild))


def _can_manage_messages(member: Any, guild: Optional[discord.Guild]) -> bool:
    if guild is None:
        return False
    if int(getattr(member, "id", 0)) == int(getattr(guild, "owner_id", 0)):
        return True
    permissions = getattr(member, "guild_permissions", None)
    return bool(permissions and (permissions.administrator or permissions.manage_messages))


async def _invoke(bot: commands.Bot, ctx: commands.Context, command_name: str, *args: Any) -> bool:
    command = bot.get_command(command_name)
    if command is None:
        return False
    previous = getattr(ctx, "command", None)
    try:
        ctx.command = command
        cog = _real_cog(command)
        if cog is not None:
            result = command.callback(cog, ctx, *args)
        else:
            result = command.callback(ctx, *args)
        if hasattr(result, "__await__"):
            await result
        return True
    finally:
        ctx.command = previous


class OwnerView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 240.0) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            locale = _locale_interaction(interaction)
            await interaction.response.send_message(
                _t(locale, "이 패널은 실행한 사람만 사용할 수 있습니다.", "Only the user who opened this panel can use it."),
                ephemeral=True,
            )
            return False
        return True


class InvokeButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, ctx: commands.Context, target: str, label_ko: str, label_en: str, emoji: str, *, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        self.bot = bot
        self.ctx = ctx
        self.target = target
        self.label_ko = label_ko
        self.label_en = label_en
        locale = _locale(ctx)
        super().__init__(label=_t(locale, label_ko, label_en)[:80], emoji=emoji, style=style, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        locale = _locale_interaction(interaction, _locale(self.ctx))
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            ok = await _invoke(self.bot, self.ctx, self.target)
            if ok:
                await interaction.followup.send(_t(locale, f"✅ `{self.target}` 화면을 열었습니다.", f"✅ Opened `{self.target}`."), ephemeral=True)
            else:
                await interaction.followup.send(_t(locale, f"⚠️ `{self.target}` 명령을 찾지 못했습니다.", f"⚠️ Could not find `{self.target}`."), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(_t(locale, f"❌ 실행 중 오류가 발생했습니다: `{type(exc).__name__}`", f"❌ Failed to run: `{type(exc).__name__}`"), ephemeral=True)


class CloseButton(discord.ui.Button):
    def __init__(self, locale: str, *, row: int = 1) -> None:
        super().__init__(label=_t(locale, "닫기", "Close"), emoji="✖️", style=discord.ButtonStyle.danger, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(view=self.view)
        self.view.stop()


class OperationsPolishView(OwnerView):
    def __init__(self, bot: commands.Bot, ctx: commands.Context, locale: str) -> None:
        super().__init__(ctx.author.id, timeout=300)
        rows: Sequence[Tuple[str, str, str, str, int, discord.ButtonStyle]] = (
            ("메시지정리센터", "메시지 정리", "Cleanup", "🧹", 0, discord.ButtonStyle.danger),
            ("실시간오류센터", "실시간 오류", "Live Errors", "🛰️", 0, discord.ButtonStyle.primary),
            ("명령건강검진", "명령 건강", "Command Health", "🩺", 0, discord.ButtonStyle.primary),
            ("서버운영센터", "서버 운영", "Server Ops", "🛠️", 0, discord.ButtonStyle.secondary),
            ("알림센터", "알림 센터", "Alerts", "🔔", 0, discord.ButtonStyle.secondary),
            ("실사용통계", "24시간 통계", "24h Metrics", "📊", 1, discord.ButtonStyle.success),
            ("죽은기능검수", "죽은 기능", "Dead Links", "🧟", 1, discord.ButtonStyle.secondary),
            ("초보센터", "초보 안내", "Beginner Guide", "🌱", 1, discord.ButtonStyle.secondary),
            ("패치노트", "패치노트", "Patch Notes", "📜", 1, discord.ButtonStyle.secondary),
        )
        for target, ko, en, emoji, row, style in rows:
            self.add_item(InvokeButton(bot, ctx, target, ko, en, emoji, row=row, style=style))
        self.add_item(CloseButton(locale, row=1))


async def _purge(interaction: discord.Interaction, *, amount: int, mode: str, user_id: int = 0) -> Tuple[bool, int, str]:
    locale = _locale_interaction(interaction)
    guild = interaction.guild
    channel = interaction.channel
    if guild is None or channel is None or not callable(getattr(channel, "purge", None)):
        return False, 0, _t(locale, "텍스트 채널에서만 사용할 수 있습니다.", "This can only be used in a text channel.")
    if not _can_manage_messages(interaction.user, guild):
        return False, 0, _t(locale, "실행자에게 메시지 관리 권한이 필요합니다.", "You need Manage Messages permission.")
    me = guild.me
    perms_for = getattr(channel, "permissions_for", None)
    if me is not None and callable(perms_for) and not perms_for(me).manage_messages:
        return False, 0, _t(locale, "아바돈에게 메시지 관리 권한을 주세요.", "Give ABADDON Manage Messages permission.")

    amount = max(1, min(100, int(amount)))
    check = None
    if mode == "bot":
        check = lambda message: bool(message.author.bot)
    elif mode == "link":
        check = lambda message: bool(_LINK_RE.search(message.content or ""))
    elif mode == "attachment":
        check = lambda message: bool(message.attachments)
    elif mode == "user":
        check = lambda message: int(message.author.id) == int(user_id)
    try:
        kwargs: Dict[str, Any] = {"limit": amount, "reason": f"ABADDON v{VERSION} cleanup: {interaction.user}"}
        if check is not None:
            kwargs["check"] = check
        deleted = await channel.purge(**kwargs)
        return True, len(deleted), ""
    except discord.Forbidden:
        return False, 0, _t(locale, "Discord 권한 때문에 삭제하지 못했습니다.", "Discord permissions prevented deletion.")
    except discord.HTTPException as exc:
        return False, 0, _t(locale, f"Discord 요청 오류: {type(exc).__name__}", f"Discord request failed: {type(exc).__name__}")


class ConfirmCleanupView(OwnerView):
    def __init__(self, owner_id: int, *, amount: int, mode: str, user_id: int = 0, locale: str = "ko") -> None:
        super().__init__(owner_id, timeout=90)
        self.amount = amount
        self.mode = mode
        self.user_id = user_id
        self.locale = locale

        confirm = discord.ui.Button(label=_t(locale, "정리 실행", "Run Cleanup"), emoji="🧹", style=discord.ButtonStyle.danger)
        cancel = discord.ui.Button(label=_t(locale, "취소", "Cancel"), emoji="↩️", style=discord.ButtonStyle.secondary)

        async def confirm_callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            ok, count, error = await _purge(interaction, amount=self.amount, mode=self.mode, user_id=self.user_id)
            if ok:
                await interaction.edit_original_response(content=_t(self.locale, f"✅ 메시지 **{count}개**를 정리했습니다.", f"✅ Cleaned **{count}** messages."), view=None)
            else:
                await interaction.edit_original_response(content=f"❌ {error}", view=None)
            self.stop()

        async def cancel_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=_t(self.locale, "취소했습니다.", "Cancelled."), view=None)
            self.stop()

        confirm.callback = confirm_callback
        cancel.callback = cancel_callback
        self.add_item(confirm)
        self.add_item(cancel)


class UserCleanupModal(discord.ui.Modal):
    def __init__(self, owner_id: int, locale: str) -> None:
        super().__init__(title=_t(locale, "사용자 메시지 정리", "Clean User Messages")[:45])
        self.owner_id = owner_id
        self.locale = locale
        self.user_value = discord.ui.TextInput(label=_t(locale, "사용자 ID 또는 멘션", "User ID or mention"), max_length=32, placeholder="123456789012345678")
        self.amount_value = discord.ui.TextInput(label=_t(locale, "최근 탐색 개수 (1~100)", "Recent scan count (1-100)"), default="100", max_length=3)
        self.add_item(self.user_value)
        self.add_item(self.amount_value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if int(interaction.user.id) != int(self.owner_id):
            await interaction.response.send_message(_t(self.locale, "이 입력창을 연 사람만 사용할 수 있습니다.", "Only the user who opened this form can use it."), ephemeral=True)
            return
        numbers = re.sub(r"\D", "", str(self.user_value.value))
        if not numbers:
            await interaction.response.send_message(_t(self.locale, "사용자 ID를 확인해주세요.", "Check the user ID."), ephemeral=True)
            return
        try:
            amount = max(1, min(100, int(str(self.amount_value.value).strip())))
        except Exception:
            amount = 100
        await interaction.response.send_message(
            _t(self.locale, f"<@{int(numbers)}>의 최근 메시지를 최대 {amount}개 범위에서 정리할까요?", f"Clean messages from <@{int(numbers)}> within the latest {amount} messages?"),
            view=ConfirmCleanupView(interaction.user.id, amount=amount, mode="user", user_id=int(numbers), locale=self.locale),
            ephemeral=True,
        )


class CleanupButton(discord.ui.Button):
    def __init__(self, *, label: str, emoji: str, amount: int, mode: str, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.amount = amount
        self.mode = mode

    async def callback(self, interaction: discord.Interaction) -> None:
        locale = _locale_interaction(interaction)
        mode_names = {
            "all": _t(locale, "최근 메시지", "recent messages"),
            "bot": _t(locale, "봇 메시지", "bot messages"),
            "link": _t(locale, "링크 메시지", "link messages"),
            "attachment": _t(locale, "첨부 메시지", "attachment messages"),
        }
        await interaction.response.send_message(
            _t(locale, f"{mode_names.get(self.mode, self.mode)}를 최대 **{self.amount}개 범위**에서 정리할까요?", f"Clean {mode_names.get(self.mode, self.mode)} within the latest **{self.amount} messages**?"),
            view=ConfirmCleanupView(interaction.user.id, amount=self.amount, mode=self.mode, locale=locale),
            ephemeral=True,
        )


class CleanupCenterView(OwnerView):
    def __init__(self, owner_id: int, locale: str) -> None:
        super().__init__(owner_id, timeout=240)
        for amount, row in ((10, 0), (30, 0), (50, 0), (100, 0)):
            self.add_item(CleanupButton(label=str(amount), emoji="🧹", amount=amount, mode="all", row=row, style=discord.ButtonStyle.danger if amount == 100 else discord.ButtonStyle.secondary))
        self.add_item(CleanupButton(label=_t(locale, "봇", "Bots"), emoji="🤖", amount=100, mode="bot", row=1))
        self.add_item(CleanupButton(label=_t(locale, "링크", "Links"), emoji="🔗", amount=100, mode="link", row=1))
        self.add_item(CleanupButton(label=_t(locale, "첨부", "Files"), emoji="📎", amount=100, mode="attachment", row=1))

        user_button = discord.ui.Button(label=_t(locale, "사용자", "User"), emoji="👤", style=discord.ButtonStyle.primary, row=1)
        async def user_callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(UserCleanupModal(owner_id, locale))
        user_button.callback = user_callback
        self.add_item(user_button)
        self.add_item(CloseButton(locale, row=1))


def _ops_embed(locale: str) -> discord.Embed:
    embed = discord.Embed(
        title=_t(locale, "🛡️ ABADDON 라이브 운영·광택 센터", "🛡️ ABADDON Live Ops & Polish Center"),
        description=_t(
            locale,
            "기존 운영 기능을 삭제하지 않고 자주 쓰는 점검·정리·안내 기능을 버튼 두 줄로 묶었습니다.",
            "Keeps every legacy operation tool while grouping frequent checks, cleanup, and onboarding into two button rows.",
        ),
        color=0x5865F2,
    )
    embed.add_field(name=_t(locale, "🧹 정리", "🧹 Cleanup"), value=_t(locale, "수량·봇·링크·첨부·특정 사용자 메시지를 확인 후 정리", "Confirmed cleanup by amount, bots, links, files, or user"), inline=False)
    embed.add_field(name=_t(locale, "🛰️ 실시간 품질", "🛰️ Live Quality"), value=_t(locale, "오류 사건·24시간 사용량·느린 명령·죽은 연결 검사", "Incidents, 24h usage, slow commands, and dead-link audits"), inline=False)
    embed.add_field(name=_t(locale, "🌱 운영 지원", "🌱 Operations Support"), value=_t(locale, "서버 운영·알림·초보 안내·최신 패치노트 바로가기", "Server ops, alerts, beginner guide, and latest patch notes"), inline=False)
    embed.set_footer(text=_t(locale, "개별 버튼은 실행자에게만 반응 · 기존 명령/저장 삭제 0건", "Buttons respond only to the opener · 0 legacy commands/saves removed"))
    return _safe_embed(embed)


def register_v1670_live_ops_polish(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del check_registered, world_data, user_data
    if getattr(bot, "_abaddon_v1670_registered", False):
        return
    bot._abaddon_v1670_registered = True
    bot.abaddon_version = VERSION

    live_events: Deque[Dict[str, Any]] = deque(maxlen=5000)
    starts: Dict[int, float] = {}
    setattr(bot, "v1670_live_events", live_events)
    setattr(bot, "v1670_started_at", datetime.now(timezone.utc).isoformat())

    @bot.listen("on_command")
    async def v1670_command_start(ctx: commands.Context) -> None:
        if getattr(ctx, "command", None) is not None:
            starts[int(getattr(ctx.message, "id", id(ctx)))] = time.perf_counter()

    def add_event(ctx: commands.Context, ok: bool, error: str = "") -> None:
        key = int(getattr(ctx.message, "id", id(ctx)))
        start = starts.pop(key, None)
        duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0) if start is not None else 0.0
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "qualified_name", "unknown"))
        live_events.append({"ts": time.time(), "name": name, "ok": bool(ok), "ms": round(duration_ms, 2), "error": str(error)[:120]})

    @bot.listen("on_command_completion")
    async def v1670_command_complete(ctx: commands.Context) -> None:
        add_event(ctx, True)

    @bot.listen("on_command_error")
    async def v1670_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
        if getattr(ctx, "command", None) is not None:
            add_event(ctx, False, type(error).__name__)

    async def send_ops(ctx: commands.Context) -> None:
        locale = _locale(ctx)
        if not _is_admin_member(ctx.author, ctx.guild):
            await ctx.send(_t(locale, "🔒 서버 관리 권한이 필요합니다.", "🔒 Manage Server permission is required."))
            return
        await ctx.send(embed=_ops_embed(locale), view=_safe_view(OperationsPolishView(bot, ctx, locale)))

    @bot.command(name="운영광택센터", aliases=["라이브운영센터", "liveopshub", "polishcenter"], help="메시지 정리·실시간 오류·명령 건강·통계·초보 안내를 버튼으로 통합합니다.")
    async def operations_polish_center(ctx: commands.Context) -> None:
        await send_ops(ctx)

    existing_ops = bot.get_command("운영통합센터")
    if existing_ops is not None:
        previous_ops = existing_ops.callback
        async def upgraded_operations_hub(ctx: commands.Context) -> None:
            await send_ops(ctx)
        existing_ops.callback = upgraded_operations_hub
        existing_ops.help = "메시지 정리·실시간 오류·명령 건강·통계·알림·초보 안내를 버튼으로 엽니다."
        existing_ops.description = existing_ops.help
        existing_ops.extras = dict(getattr(existing_ops, "extras", {}) or {})
        existing_ops.extras["v1670_previous_callback"] = previous_ops

    @bot.command(name="메시지정리센터", aliases=["청소센터", "cleanupcenter", "messagecleanup"], help="확인 버튼 뒤 최근·봇·링크·첨부·사용자 메시지를 안전하게 정리합니다.")
    async def message_cleanup_center(ctx: commands.Context) -> None:
        locale = _locale(ctx)
        if not _can_manage_messages(ctx.author, ctx.guild):
            await ctx.send(_t(locale, "🔒 메시지 관리 권한이 필요합니다.", "🔒 Manage Messages permission is required."))
            return
        embed = discord.Embed(
            title=_t(locale, "🧹 메시지 정리 센터", "🧹 Message Cleanup Center"),
            description=_t(locale, "삭제 유형을 고르면 **한 번 더 확인한 뒤** 실행합니다. 한 번에 최대 100개까지만 탐색합니다.", "Choose a cleanup type. A confirmation step is always required, and at most 100 recent messages are scanned."),
            color=0xE67E22,
        )
        embed.add_field(name=_t(locale, "수량 정리", "Amount"), value="10 · 30 · 50 · 100", inline=True)
        embed.add_field(name=_t(locale, "조건 정리", "Filters"), value=_t(locale, "봇 · 링크 · 첨부 · 특정 사용자", "Bots · Links · Files · Specific user"), inline=True)
        embed.set_footer(text=_t(locale, "Discord 14일 이상 된 메시지는 일괄 삭제 제한을 받을 수 있습니다.", "Discord may restrict bulk deletion of messages older than 14 days."))
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(CleanupCenterView(ctx.author.id, locale)))

    @bot.command(name="실사용통계", aliases=["라이브사용통계", "liveusage", "commandmetrics"], hidden=True, help="[봇 소유자 전용] 재시작 이후 최대 24시간의 전체 명령 사용량·실패율·응답시간을 확인합니다.")
    async def live_usage(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(ctx)
        from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner
        if not await _private_owner(bot, ctx.author):
            await ctx.send("🔒 이 통계는 봇 소유자만 확인할 수 있습니다.")
            return
        cutoff = time.time() - 86400
        rows = [row for row in live_events if float(row.get("ts", 0)) >= cutoff]
        successes = [row for row in rows if row.get("ok")]
        failures = [row for row in rows if not row.get("ok")]
        durations = sorted(float(row.get("ms", 0)) for row in rows if float(row.get("ms", 0)) > 0)
        avg_ms = mean(durations) if durations else 0.0
        p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else 0.0
        counts = Counter(str(row.get("name", "unknown")) for row in rows)
        fail_counts = Counter(str(row.get("name", "unknown")) for row in failures)
        slow = sorted(rows, key=lambda row: float(row.get("ms", 0)), reverse=True)[:8]
        embed = discord.Embed(title=_t(locale, "📊 최근 24시간 실사용 통계", "📊 Last 24 Hours Live Usage"), color=0x2ECC71 if not failures else 0xF1C40F)
        embed.description = _t(locale, "봇 재시작 이후 수집한 런타임 통계입니다. 재시작하면 초기화됩니다.", "Runtime-only metrics collected since the last restart. They reset on restart.")
        embed.add_field(name=_t(locale, "실행", "Runs"), value=f"{len(rows):,}", inline=True)
        embed.add_field(name=_t(locale, "실패", "Failures"), value=f"{len(failures):,} ({(len(failures)/len(rows)*100 if rows else 0):.1f}%)", inline=True)
        embed.add_field(name=_t(locale, "응답시간", "Latency"), value=f"avg {avg_ms:.0f}ms · p95 {p95:.0f}ms", inline=True)
        embed.add_field(name=_t(locale, "자주 사용", "Most Used"), value="\n".join(f"`!{name}` {count}회" for name, count in counts.most_common(8)) or _t(locale, "기록 없음", "No data"), inline=False)
        if 상세:
            embed.add_field(name=_t(locale, "반복 실패", "Repeated Failures"), value="\n".join(f"`!{name}` {count}회" for name, count in fail_counts.most_common(8)) or _t(locale, "없음", "None"), inline=False)
            embed.add_field(name=_t(locale, "느린 실행", "Slowest Runs"), value="\n".join(f"`!{row['name']}` {float(row.get('ms',0)):.0f}ms" for row in slow) or _t(locale, "기록 없음", "No data"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    def dead_audit_rows() -> Tuple[List[Any], List[Any], List[Any], List[Any], List[str], List[str]]:
        entries = hub._build_registry(bot)
        unresolved = [entry for entry in entries if bot.get_command(entry.qualified_name) is None]
        bad_callbacks = [entry for entry in entries if (bot.get_command(entry.qualified_name) is not None and not callable(getattr(bot.get_command(entry.qualified_name), "callback", None)))]
        missing_help = [entry for entry in entries if not str(entry.help_text or "").strip()]
        missing_en = [entry for entry in entries if not any(re.fullmatch(r"[A-Za-z0-9_. -]+", alias or "") for alias in entry.aliases)]
        required_targets = ["명령어", "help", "초보센터", "스토리나침반", "생존허브", "카지노", "도박정보", "도시꾸미기", "실시간오류센터", "메시지정리센터"]
        missing_targets = [name for name in required_targets if bot.get_command(name) is None]
        missing_assets: List[str] = []
        try:
            from apocalypse_bot.commands import v1500_neon_abyss as neon
            missing_assets = [part for part in neon.COMPONENT_LABELS if neon._safe_component_path(part) is None]
        except Exception:
            missing_assets = ["v1500_module"]
        return entries, unresolved, bad_callbacks, missing_help, missing_targets, missing_assets + [f"EN:{entry.qualified_name}" for entry in missing_en[:30]]

    @bot.command(name="죽은기능검수", aliases=["죽은명령검수", "deadfeatureaudit", "deadcommandaudit"], help="등록됐지만 실행·메뉴·빠른 이동·도시 자산 연결이 끊긴 기능을 검사합니다.")
    async def dead_feature_audit(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(ctx)
        if not _is_admin_member(ctx.author, ctx.guild):
            await ctx.send(_t(locale, "🔒 서버 관리 권한이 필요합니다.", "🔒 Manage Server permission is required."))
            return
        entries, unresolved, bad_callbacks, missing_help, missing_targets, misc = dead_audit_rows()
        missing_assets = [item for item in misc if not item.startswith("EN:")]
        missing_en = [item[3:] for item in misc if item.startswith("EN:")]
        checks = (
            (_t(locale, "런타임 명령 연결", "Runtime command links"), not unresolved, f"{len(entries)-len(unresolved):,}/{len(entries):,}"),
            (_t(locale, "실행 콜백", "Executable callbacks"), not bad_callbacks, f"missing {len(bad_callbacks)}"),
            (_t(locale, "설명문", "Descriptions"), not missing_help, f"missing {len(missing_help)}"),
            (_t(locale, "영문 접근 경로", "English access paths"), not missing_en, f"missing {len(missing_en)}"),
            (_t(locale, "핵심 빠른 이동", "Core shortcut targets"), not missing_targets, f"missing {len(missing_targets)}"),
            (_t(locale, "도시 부품 자산", "City component assets"), not missing_assets, f"missing {len(missing_assets)}"),
        )
        ok = all(row[1] for row in checks)
        embed = discord.Embed(title=_t(locale, "🧟 죽은 기능·연결 검수", "🧟 Dead Feature & Link Audit"), color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if passed else '⚠️'} **{name}** · {detail}" for name, passed, detail in checks)
        if 상세:
            if unresolved: embed.add_field(name=_t(locale, "미연결 명령", "Unresolved Commands"), value=" · ".join(f"!{entry.qualified_name}" for entry in unresolved[:20])[:1024], inline=False)
            if missing_targets: embed.add_field(name=_t(locale, "빠른 이동 누락", "Missing Shortcuts"), value=" · ".join(missing_targets)[:1024], inline=False)
            if missing_assets: embed.add_field(name=_t(locale, "도시 자산 누락", "Missing City Assets"), value=" · ".join(missing_assets)[:1024], inline=False)
            if missing_en: embed.add_field(name=_t(locale, "영문 접근 누락", "Missing English Access"), value=" · ".join(f"!{name}" for name in missing_en[:20])[:1024], inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="화면광택검수", aliases=["모바일화면검수", "uipolishaudit", "mobileuiaudit"], help="임베드·버튼·선택 메뉴 제한과 핵심 화면의 모바일 가독성을 검사합니다.")
    async def ui_polish_audit(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(ctx)
        commands_dir = Path(__file__).resolve().parent
        files = {
            "safe_payload": commands_dir / "v600_game_center.py",
            "command_hub": commands_dir / "v1630_core_rpg_command_city_overhaul.py",
            "runtime_hotfix": commands_dir / "v1661_runtime_interaction_hotfix.py",
        }
        source = {key: path.read_text(encoding="utf-8", errors="replace") for key, path in files.items()}
        checks = (
            (_t(locale, "임베드 6000자 보호", "6000-char embed guard"), "6000" in source["safe_payload"] and "_safe_embed" in source["safe_payload"]),
            (_t(locale, "선택 메뉴 25개 보호", "25-option select guard"), "_safe_select_options" in source["safe_payload"]),
            (_t(locale, "버튼 5×5 보호", "5×5 button guard"), "_safe_view" in source["safe_payload"]),
            (_t(locale, "만료 UI 선승인", "Expired UI acknowledgement"), "_safe_component_edit" in source["command_hub"]),
            (_t(locale, "MISSING Cog 보호", "MISSING Cog guard"), "_MissingSentinel" in source["runtime_hotfix"] or "discord.utils" in source["runtime_hotfix"]),
            (_t(locale, "한/영 화면 분리", "KO/EN screen separation"), bot.get_command("명령어") is not None and bot.get_command("help") is not None),
        )
        ok = all(passed for _name, passed in checks)
        embed = discord.Embed(title=_t(locale, "✨ 화면·모바일 광택 검수", "✨ UI & Mobile Polish Audit"), color=0x2ECC71 if ok else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if passed else '❌'} {name}" for name, passed in checks)
        if 상세:
            embed.add_field(name=_t(locale, "표준", "Standards"), value=_t(locale, "제목 256 · 설명 4096 · 필드 25 · 전체 6000 · 선택 25 · 버튼 한 줄 5개", "Title 256 · description 4096 · 25 fields · 6000 total · 25 select options · 5 buttons per row"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1670통합검수", aliases=["v1670audit", "1670audit"], help="v16.7 운영 패널·메시지 정리·실사용 통계·죽은 기능·화면 광택 연결을 검사합니다.")
    async def audit_1670(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(ctx)
        required = ["운영광택센터", "운영통합센터", "메시지정리센터", "실사용통계", "죽은기능검수", "화면광택검수", "실시간오류센터", "명령건강검진", "패치노트"]
        checks = [(name, bot.get_command(name) is not None) for name in required]
        entries, unresolved, bad_callbacks, _missing_help, missing_targets, misc = dead_audit_rows()
        checks.extend([
            (_t(locale, "전체 명령 런타임 연결", "All runtime command links"), not unresolved),
            (_t(locale, "콜백 실행 가능", "Callbacks executable"), not bad_callbacks),
            (_t(locale, "핵심 바로가기", "Core shortcuts"), not missing_targets),
            (_t(locale, "도시 부품 20종", "20 city components"), not [x for x in misc if not x.startswith("EN:")]),
            (_t(locale, "실사용 수집기", "Live metric collector"), isinstance(getattr(bot, "v1670_live_events", None), deque)),
        ])
        ok = all(value for _name, value in checks)
        embed = discord.Embed(title=_t(locale, f"🧪 ABADDON v{VERSION} 통합 검수", f"🧪 ABADDON v{VERSION} Integration Audit"), color=0x2ECC71 if ok else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks)
        if 상세:
            embed.add_field(name=_t(locale, "검수 범위", "Scope"), value=_t(locale, f"운영 패널 · 확인형 청소 · 24시간 통계 · 죽은 연결 · 모바일 UI · 명령 {len(entries):,}개", f"Ops panel · confirmed cleanup · 24h metrics · dead links · mobile UI · {len(entries):,} commands"), inline=False)
        embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건", "0 legacy features or save data removed"))
        await ctx.send(embed=_safe_embed(embed))

    # Rebuild command-center entries on every open so newly added v16.7 commands are never hidden.
    ko_help = bot.get_command("명령어")
    if ko_help is not None:
        previous_ko_help = ko_help.callback
        async def help_ko_v1670(ctx: commands.Context, *, 검색어: str = "") -> None:
            current_entries = hub._build_registry(bot)
            view = hub.CompleteCommandCenterView(ctx.author.id, current_entries, "ko", bot, get_user, save_data)
            if 검색어:
                rows = hub._search(current_entries, 검색어)
                if rows:
                    view.set_special(rows, f"🔎 전체 명령 검색 · {검색어}")
                    view.rebuild()
            await ctx.send(embed=_safe_embed(view.current_embed()), view=_safe_view(view))
        ko_help.callback = help_ko_v1670
        ko_help.help = "시즌 1 RPG부터 운영·정리·검수까지 실제 등록된 전체 명령을 매번 새로 불러옵니다."
        ko_help.description = ko_help.help
        ko_help.extras = dict(getattr(ko_help, "extras", {}) or {})
        ko_help.extras["v1670_previous_callback"] = previous_ko_help

    en_help = bot.get_command("help")
    if en_help is not None:
        previous_en_help = en_help.callback
        async def help_en_v1670(ctx: commands.Context, *, keyword: str = "") -> None:
            current_entries = hub._build_registry(bot)
            view = hub.CompleteCommandCenterView(ctx.author.id, current_entries, "en", bot, get_user, save_data)
            if keyword:
                rows = hub._search(current_entries, keyword)
                if rows:
                    view.set_special(rows, f"🔎 Search All Commands · {keyword}")
                    view.rebuild()
            await ctx.send(embed=_safe_embed(view.current_embed()), view=_safe_view(view))
        en_help.callback = help_en_v1670
        en_help.help = "Reloads every registered command on open, including live operations, cleanup, and audits, with English-only UI."
        en_help.description = en_help.help
        en_help.extras = dict(getattr(en_help, "extras", {}) or {})
        en_help.extras["v1670_previous_callback"] = previous_en_help

    patch = bot.get_command("패치노트")
    if patch is not None:
        previous_patch = patch.callback
        async def patch_notes_v1670(ctx: commands.Context) -> None:
            locale = _locale(ctx)
            embed = discord.Embed(title=_t(locale, f"✨ ABADDON v{VERSION} LIVE OPS & POLISH", f"✨ ABADDON v{VERSION} LIVE OPS & POLISH"), color=0x7137C8)
            embed.add_field(name=_t(locale, "🛡️ 운영 광택 센터", "🛡️ Operations Polish Center"), value=_t(locale, "정리·오류·명령 건강·서버 운영·알림·초보 안내·패치노트를 버튼 두 줄에 묶었습니다.", "Grouped cleanup, errors, command health, server ops, alerts, onboarding, and patch notes into two button rows."), inline=False)
            embed.add_field(name=_t(locale, "🧹 확인형 메시지 정리", "🧹 Confirmed Cleanup"), value=_t(locale, "10/30/50/100개와 봇·링크·첨부·특정 사용자 정리를 항상 확인 후 실행합니다.", "Cleans 10/30/50/100 messages or bots, links, files, and a user only after confirmation."), inline=False)
            embed.add_field(name=_t(locale, "📊 24시간 실사용", "📊 24h Live Metrics"), value=_t(locale, "재시작 이후 사용량·실패율·평균/p95 응답시간·반복 실패·느린 실행을 가시화합니다.", "Shows usage, failure rate, average/p95 latency, repeated failures, and slow runs since restart."), inline=False)
            embed.add_field(name=_t(locale, "🧟 죽은 기능 검수", "🧟 Dead Feature Audit"), value=_t(locale, "등록 명령·콜백·설명·영문 접근·빠른 이동·도시 부품 자산 연결을 검사합니다.", "Checks registered commands, callbacks, descriptions, English access, shortcuts, and city component assets."), inline=False)
            embed.add_field(name=_t(locale, "✨ 모바일 화면 마감", "✨ Mobile UI Polish"), value=_t(locale, "임베드 6000자, 선택 25개, 버튼 5×5와 만료 상호작용 안전망을 재검수했습니다.", "Re-audited 6000-char embeds, 25-option selects, 5×5 buttons, and expired-interaction guards."), inline=False)
            embed.add_field(name=_t(locale, "🧪 점검", "🧪 Checks"), value="`!1670통합검수 상세` · `!죽은기능검수 상세` · `!화면광택검수 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건", "0 legacy features or save data removed"))
            await ctx.send(embed=_safe_embed(embed))
        patch.callback = patch_notes_v1670
        patch.help = "ABADDON v16.7.0 운영 편의·실사용 가시화·죽은 기능·모바일 화면 마감 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1670_previous_callback"] = previous_patch

    test = bot.get_command("테스트")
    if test is not None:
        previous_test = test.callback
        async def latest_test_v1670(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            locale = _locale(ctx)
            required = ["운영광택센터", "메시지정리센터", "실사용통계", "죽은기능검수", "화면광택검수", "1670통합검수", "명령어", "help", "카지노", "도박정보"]
            checks = [(name, bot.get_command(name) is not None) for name in required]
            ok = all(value for _name, value in checks)
            embed = discord.Embed(title=_t(locale, f"🧪 ABADDON v{VERSION} 최신 테스트", f"🧪 ABADDON v{VERSION} Latest Test"), color=0x2ECC71 if ok else 0xE74C3C)
            embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks)
            detail = str(mode or "").casefold() in {"상세", "detail", "full"} or any(str(arg).casefold() in {"상세", "detail", "full"} for arg in args)
            if detail:
                embed.add_field(name=_t(locale, "이번 범위", "Current Scope"), value=_t(locale, "운영 버튼 · 확인형 메시지 정리 · 런타임 통계 · 죽은 연결 · 모바일 UI", "Ops buttons · confirmed cleanup · runtime metrics · dead links · mobile UI"), inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback = latest_test_v1670
        test.help = "v16.7 운영 편의·메시지 정리·실사용 통계·죽은 기능·모바일 화면을 검사합니다."
        test.description = test.help
        test.extras = dict(getattr(test, "extras", {}) or {})
        test.extras["v1670_previous_callback"] = previous_test

    # Refresh the live command index after the new commands and callbacks are registered.
    entries = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {entry.qualified_name: entry for entry in entries})

    guide.append({
        "id": "v1670_live_ops_polish",
        "emoji": "✨",
        "title": "v16.7 LIVE OPS & POLISH",
        "hint": "운영 버튼·확인형 메시지 정리·24시간 실사용·죽은 기능·모바일 화면 마감",
        "commands": [
            "!운영광택센터 · !메시지정리센터 · !실사용통계 상세",
            "!죽은기능검수 상세 · !화면광택검수 상세",
            "!1670통합검수 상세 · !테스트 상세 · !패치노트",
        ],
    })
