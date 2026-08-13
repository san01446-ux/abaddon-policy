from __future__ import annotations

"""ABADDON v19.0.0 native Discord integration + simpler controls.

Goals
-----
- keep the existing 1,400+ prefix features, but surface Discord-native entry points;
- standardise user-facing toggles to ON/OFF while preserving legacy Korean values;
- replace the old reaction poll callback with a simple Discord native Poll;
- bridge ABADDON schedules to Discord Guild Scheduled Events;
- reuse the existing 5+5 context-menu budget by replacing two lower-value entries;
- add user-install capable personal slash commands (requires Developer Portal User Install enabled);
- create optional suggestion threads and a message-context thread action;
- expose Discord Soundboard list/upload/play/delete helpers;
- sync ABADDON bad-word settings to one Discord native AutoMod rule.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

import discord
from discord import app_commands
from discord.ext import commands

from apocalypse_bot.commands import v1831_persistent_command_hub as command_hub
from apocalypse_bot.commands import v1852_smart_command_discovery as discovery

VERSION = "19.0.0"
DATA_KEY = "native_discord_v1900"
KST = timezone(timedelta(hours=9))
AUTOMOD_RULE_NAME = "ABADDON · 금칙어 동기화"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(DATA_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[DATA_KEY] = root
    root.setdefault("schema", 1)
    root.setdefault("guilds", {})
    root.setdefault("stats", {"polls": 0, "events": 0, "threads": 0, "sounds": 0, "automod_syncs": 0})
    return root


def _guild(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data).setdefault("guilds", {})
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("auto_threads", False)
    row.setdefault("suggestion_forum_id", 0)
    row.setdefault("native_automod_enabled", False)
    row.setdefault("native_automod_rule_id", 0)
    row.setdefault("last_event_id", 0)
    return row


def _management(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = world_data.setdefault("server_management", {})
    row = root.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        root[str(int(guild_id))] = row
    automod = row.setdefault("automod", {})
    if not isinstance(automod, dict):
        automod = {}
        row["automod"] = automod
    automod.setdefault("enabled", False)
    automod.setdefault("bad_word_list", [])
    return row


def _is_manager(member: Any) -> bool:
    if not isinstance(member, discord.Member):
        return False
    p = member.guild_permissions
    return bool(member.id == member.guild.owner_id or p.administrator or p.manage_guild)


async def _require_manager(ctx: commands.Context) -> bool:
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        await ctx.send("❌ 서버에서 사용해주세요.")
        return False
    if not _is_manager(ctx.author):
        await ctx.send("❌ 서버 관리 권한이 필요합니다.")
        return False
    return True


def _on_off(value: Any) -> Optional[bool]:
    token = str(value or "").strip().casefold()
    if token in {"on", "켜기", "켜", "1", "true", "활성", "활성화"}:
        return True
    if token in {"off", "끄기", "꺼", "0", "false", "비활성", "비활성화"}:
        return False
    return None


def _kst_datetime(date_text: str, time_text: str) -> datetime:
    return datetime.strptime(f"{date_text.strip()} {time_text.strip()}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)


def _user(user_data: MutableMapping[str, Any], user_id: int) -> Optional[MutableMapping[str, Any]]:
    row = user_data.get(str(int(user_id)))
    return row if isinstance(row, dict) else None


def _power(row: Mapping[str, Any]) -> int:
    # Avoid reaching into another command module's closures. This is a compact profile hint,
    # not the authoritative combat calculator.
    stats = row.get("stats") if isinstance(row.get("stats"), Mapping) else {}
    explicit = _safe_int(row.get("power"), 0) or _safe_int(row.get("combat_power"), 0)
    if explicit:
        return explicit
    level = max(1, _safe_int(row.get("level"), 1))
    return level * 10 + _safe_int(stats.get("enhance_success"), 0) * 2


def _find_party(world_data: MutableMapping[str, Any], user_id: int):
    parties = world_data.get("parties") if isinstance(world_data.get("parties"), Mapping) else {}
    uid = str(int(user_id))
    for leader_id, party in parties.items():
        if isinstance(party, Mapping) and uid in [str(x) for x in party.get("members", [])]:
            return str(leader_id), party
    return None, None


def _apply_toggle_help(bot: commands.Bot) -> None:
    names = {
        "자동관리": "`!자동관리 ON` / `!자동관리 OFF` · 도배/멘션 자동관리",
        "초대차단": "`!초대차단 ON` / `!초대차단 OFF` · Discord 초대 링크 차단",
        "욕설차단": "`!욕설차단 ON` / `!욕설차단 OFF` · 금칙어 자동 차단",
        "자동처벌": "`!자동처벌 ON` / `!자동처벌 OFF` · 자동 타임아웃",
        "안티레이드": "`!안티레이드 ON` / `!안티레이드 OFF` · 가입 폭주 감시",
        "파괴감시": "`!파괴감시 ON` / `!파괴감시 OFF` · 채널/역할/웹훅 파괴 감시",
        "알림요약": "`!알림요약 ON` / `!알림요약 OFF` · 운영 알림 요약",
        "스레드자동": "`!스레드자동 ON` / `!스레드자동 OFF` · 건의 스레드 자동 생성",
        "디스코드자동관리": "`!디스코드자동관리 ON` / `!디스코드자동관리 OFF` · Discord 기본 AutoMod 동기화",
    }
    for name, help_text in names.items():
        cmd = bot.get_command(name)
        if cmd is not None:
            cmd.help = help_text
            cmd.description = help_text


class NativeEventModal(discord.ui.Modal, title="ABADDON Discord 이벤트 만들기"):
    event_name = discord.ui.TextInput(label="이벤트 제목", placeholder="예: 월드보스 토벌", max_length=100)
    date = discord.ui.TextInput(label="날짜", placeholder="YYYY-MM-DD", max_length=10)
    clock = discord.ui.TextInput(label="시간", placeholder="HH:MM", max_length=5)
    description = discord.ui.TextInput(label="설명", style=discord.TextStyle.paragraph, required=False, max_length=900)

    def __init__(self, world_data: MutableMapping[str, Any], save_data) -> None:
        super().__init__(timeout=300)
        self.world_data = world_data
        self.save_data = save_data

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ 서버에서 사용해주세요.", ephemeral=True)
            return
        if not _is_manager(interaction.user):
            await interaction.response.send_message("❌ 서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        try:
            start = _kst_datetime(str(self.date.value), str(self.clock.value)).astimezone(timezone.utc)
        except ValueError:
            await interaction.response.send_message("❌ 날짜/시간은 `YYYY-MM-DD` / `HH:MM` 형식으로 입력해주세요.", ephemeral=True)
            return
        if start <= discord.utils.utcnow() + timedelta(minutes=1):
            await interaction.response.send_message("❌ 시작 시간은 현재보다 최소 1분 뒤여야 합니다.", ephemeral=True)
            return
        try:
            event = await interaction.guild.create_scheduled_event(
                name=str(self.event_name.value).strip()[:100],
                description=str(self.description.value).strip()[:1000] or "ABADDON에서 생성한 Discord 서버 이벤트",
                start_time=start,
                end_time=start + timedelta(hours=1),
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location="ABADDON / Discord",
                reason=f"ABADDON 이벤트 생성: {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError) as exc:
            await interaction.response.send_message(f"❌ Discord 이벤트를 만들지 못했습니다: `{type(exc).__name__}`\n아바돈에 이벤트 관리 권한이 있는지 확인해주세요.", ephemeral=True)
            return
        row = _guild(self.world_data, interaction.guild.id)
        row["last_event_id"] = int(event.id)
        _root(self.world_data)["stats"]["events"] = _safe_int(_root(self.world_data)["stats"].get("events"), 0) + 1
        self.save_data()
        await interaction.response.send_message(f"✅ Discord 서버 이벤트를 만들었습니다.\n**{event.name}** · <t:{int(start.timestamp())}:F>\n{event.url}", ephemeral=True)


class NativePollModal(discord.ui.Modal, title="ABADDON 간단 투표"):
    question = discord.ui.TextInput(label="질문", placeholder="예: 오늘 월드보스 갈까요?", max_length=300)
    choices = discord.ui.TextInput(label="선택지 (선택)", placeholder="비워두면 찬성/반대 · 여러 개면 | 로 구분", required=False, max_length=500)

    def __init__(self, world_data: MutableMapping[str, Any]) -> None:
        super().__init__(timeout=300)
        self.world_data = world_data

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.choices.value or "").strip()
        options = [x.strip() for x in raw.split("|") if x.strip()] if raw else ["찬성", "반대"]
        if len(options) < 2:
            options = ["찬성", "반대"]
        options = options[:10]
        try:
            poll = discord.Poll(question=str(self.question.value).strip()[:300], duration=timedelta(hours=24), multiple=False)
            for option in options:
                poll.add_answer(text=option[:55])
            await interaction.response.send_message(poll=poll)
            _root(self.world_data)["stats"]["polls"] = _safe_int(_root(self.world_data)["stats"].get("polls"), 0) + 1
        except Exception as exc:
            await interaction.response.send_message(f"❌ Discord 기본 투표를 만들지 못했습니다: `{type(exc).__name__}`", ephemeral=True)


class SimplePollLauncherView(discord.ui.View):
    def __init__(self, world_data: MutableMapping[str, Any]) -> None:
        super().__init__(timeout=180)
        self.world_data = world_data

    @discord.ui.button(label="투표 만들기", emoji="📊", style=discord.ButtonStyle.primary)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is not None and isinstance(interaction.user, discord.Member) and not _is_manager(interaction.user):
            await interaction.response.send_message("❌ 서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        await interaction.response.send_modal(NativePollModal(self.world_data))


class NativeDiscordHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data

    @discord.ui.button(label="투표", emoji="📊", style=discord.ButtonStyle.primary)
    async def poll(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(NativePollModal(self.world_data))

    @discord.ui.button(label="서버 이벤트", emoji="📅", style=discord.ButtonStyle.success)
    async def event(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(NativeEventModal(self.world_data, self.save_data))

    @discord.ui.button(label="스레드", emoji="🧵", style=discord.ButtonStyle.secondary)
    async def threads(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("🧵 `!스레드자동 ON/OFF` · `!건의포럼 ON #포럼` · 메시지 우클릭 → **앱 → ABADDON 스레드 열기**", ephemeral=True)

    @discord.ui.button(label="Soundboard", emoji="🔊", style=discord.ButtonStyle.secondary)
    async def sounds(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("🔊 `!사운드보드` · `!사운드추가 이름`(MP3/OGG 첨부) · `!사운드재생 이름`", ephemeral=True)

    @discord.ui.button(label="AutoMod", emoji="🛡️", style=discord.ButtonStyle.danger)
    async def automod(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message("🛡️ `!디스코드자동관리 ON/OFF` · ABADDON 금칙어를 Discord 기본 AutoMod 규칙에 동기화합니다.", ephemeral=True)


async def _native_poll_send(ctx: commands.Context, world_data: MutableMapping[str, Any], content: str) -> None:
    if ctx.guild is not None and isinstance(ctx.author, discord.Member) and not _is_manager(ctx.author):
        await ctx.send("❌ 서버 관리 권한이 필요합니다.")
        return
    parts = [x.strip() for x in str(content or "").split("|") if x.strip()]
    if not parts:
        await ctx.send("📊 **간단 투표**\n`!투표 질문` → 찬성/반대\n`!투표 질문 | 선택1 | 선택2` → 선택형 투표")
        return
    question = parts[0][:300]
    options = parts[1:11] if len(parts) >= 3 else ["찬성", "반대"]
    try:
        poll = discord.Poll(question=question, duration=timedelta(hours=24), multiple=False)
        for option in options:
            poll.add_answer(text=option[:55])
        await ctx.send(poll=poll)
        _root(world_data)["stats"]["polls"] = _safe_int(_root(world_data)["stats"].get("polls"), 0) + 1
    except Exception:
        # Runtime fallback for a Discord permission/library mismatch.
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        msg = await ctx.send("📊 **" + question + "**\n" + "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options)))
        for emoji in emojis[:len(options)]:
            try:
                await msg.add_reaction(emoji)
            except discord.HTTPException:
                break


async def _sync_native_automod(guild: discord.Guild, world_data: MutableMapping[str, Any], enabled: bool) -> str:
    row = _guild(world_data, guild.id)
    settings = _management(world_data, guild.id)
    words = [str(x).strip()[:30] for x in settings.get("automod", {}).get("bad_word_list", []) if str(x).strip()][:1000]
    try:
        rules = await guild.fetch_automod_rules()
    except (discord.Forbidden, discord.HTTPException):
        return "Discord AutoMod 규칙을 조회할 권한이 없습니다."
    rule = next((x for x in rules if x.name == AUTOMOD_RULE_NAME), None)
    if not enabled:
        if rule is not None:
            try:
                await rule.edit(enabled=False, reason="ABADDON native AutoMod OFF")
            except (discord.Forbidden, discord.HTTPException):
                return "Discord AutoMod 규칙을 끄지 못했습니다."
        row["native_automod_enabled"] = False
        return "Discord 기본 AutoMod 동기화를 OFF로 설정했습니다."
    if not words:
        return "먼저 `!욕설추가 단어`로 ABADDON 금칙어를 1개 이상 등록해주세요."
    trigger = discord.AutoModTrigger(keyword_filter=words)
    actions = [discord.AutoModRuleAction()]
    try:
        if rule is None:
            rule = await guild.create_automod_rule(
                name=AUTOMOD_RULE_NAME,
                event_type=discord.AutoModRuleEventType.message_send,
                trigger=trigger,
                actions=actions,
                enabled=True,
                reason="ABADDON native AutoMod sync",
            )
        else:
            rule = await rule.edit(trigger=trigger, actions=actions, enabled=True, reason="ABADDON native AutoMod resync")
    except (discord.Forbidden, discord.HTTPException, ValueError) as exc:
        return f"Discord AutoMod 동기화 실패: {type(exc).__name__}"
    row["native_automod_enabled"] = True
    row["native_automod_rule_id"] = int(rule.id)
    settings["automod"]["enabled"] = True
    _root(world_data)["stats"]["automod_syncs"] = _safe_int(_root(world_data)["stats"].get("automod_syncs"), 0) + 1
    return f"Discord 기본 AutoMod ON · 금칙어 {len(words)}개 동기화 완료"


def register_v1900_native_discord_integration(
    bot: commands.Bot,
    user_data: MutableMapping[str, Any],
    world_data: MutableMapping[str, Any],
    save_data,
) -> None:
    _root(world_data)

    # ------------------------------------------------------------------
    # Simple native poll: keep the familiar !투표 name but replace the old
    # required-pipe syntax with an optional question and a one-button launcher.
    # ------------------------------------------------------------------
    previous_poll = bot.remove_command("투표")

    @bot.command(name="투표", help="간단 Discord 투표: `!투표 질문` · 입력 없이 `!투표`만 치면 버튼형 작성창을 엽니다.")
    async def native_poll_command(ctx: commands.Context, *, 내용: str = "") -> None:
        if ctx.guild is not None and isinstance(ctx.author, discord.Member) and not _is_manager(ctx.author):
            await ctx.send("❌ 서버 관리 권한이 필요합니다.")
            return
        if not str(내용).strip():
            embed = discord.Embed(
                title="📊 ABADDON 간단 투표",
                description="복잡한 형식은 필요 없습니다. 아래 버튼을 눌러 질문과 선택지만 적으세요.\n\n빠른 사용: `!투표 오늘 월드보스 갈까요?`",
                color=0x3498DB,
            )
            embed.add_field(name="기본", value="질문만 입력하면 **찬성 / 반대**", inline=True)
            embed.add_field(name="선택형", value="`질문 | 던전 | 채집 | 카지노`", inline=True)
            await ctx.send(embed=embed, view=SimplePollLauncherView(world_data))
            return
        await _native_poll_send(ctx, world_data, 내용)
        save_data()

    native_poll_command.extras = dict(getattr(native_poll_command, "extras", {}) or {})
    if previous_poll is not None:
        native_poll_command.extras["v1900_previous_command"] = previous_poll

    # ------------------------------------------------------------------
    # ON / OFF personal + server surfaces.
    # ------------------------------------------------------------------
    @bot.command(name="알림", aliases=["alerts", "notifications"], help="내 통합 알림을 한 번에 ON/OFF 합니다. `!알림 ON` / `!알림 OFF`")
    async def master_notifications(ctx: commands.Context, 상태: str = "상태") -> None:
        row = _user(user_data, ctx.author.id)
        if row is None:
            await ctx.send("⚠️ 먼저 생존자 가입을 완료해주세요.")
            return
        prefs = row.setdefault("notification_center", {})
        topics = prefs.setdefault("topics", {}) if isinstance(prefs, dict) else {}
        if str(상태).casefold() in {"상태", "status"}:
            values = list(topics.values()) if isinstance(topics, dict) else []
            await ctx.send(f"🔔 내 알림: **{'ON' if values and any(values) else 'OFF'}** · 세부 설정은 `!알림센터`")
            return
        value = _on_off(상태)
        if value is None:
            await ctx.send("사용법: `!알림 ON` / `!알림 OFF`")
            return
        if not isinstance(topics, dict):
            topics = {}
            prefs["topics"] = topics
        # Preserve all known topic keys; if none exist use the mature v7.9 keys.
        keys = list(topics) or ["patch", "disaster", "market", "guild"]
        for key in keys:
            topics[key] = value
        save_data()
        await ctx.send(f"🔔 통합 알림 **{'ON' if value else 'OFF'}**")

    @bot.command(name="토글목록", aliases=["togglelist", "onoff"], help="ON/OFF로 사용할 수 있는 대표 설정 명령을 봅니다.")
    async def toggle_list(ctx: commands.Context) -> None:
        await ctx.send(
            "⚙️ **ON / OFF 설정**\n"
            "`!자동관리 ON/OFF` · `!초대차단 ON/OFF` · `!욕설차단 ON/OFF`\n"
            "`!안티레이드 ON/OFF` · `!파괴감시 ON/OFF` · `!스레드자동 ON/OFF`\n"
            "`!디스코드자동관리 ON/OFF` · `!알림 ON/OFF`\n"
            "기존 `ON/OFF` 입력도 호환용으로 계속 사용할 수 있습니다."
        )

    # ------------------------------------------------------------------
    # Discord native scheduled events.
    # ------------------------------------------------------------------
    @bot.command(name="디스코드센터", aliases=["discordcenter", "nativecenter"], help="Discord 기본 투표·이벤트·스레드·Soundboard·AutoMod 기능을 한곳에서 엽니다.")
    async def discord_center(ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="🛰️ ABADDON · Discord 네이티브 센터",
            description="명령어를 외우지 말고 필요한 Discord 기본 기능만 누르세요.",
            color=0x5865F2,
        )
        embed.add_field(name="📊 간단 투표", value="`!투표 질문` → 기본 찬성/반대", inline=True)
        embed.add_field(name="📅 서버 이벤트", value="`!이벤트만들기` → 입력 버튼", inline=True)
        embed.add_field(name="🧵 스레드/포럼", value="`!스레드자동 ON/OFF` · `!건의포럼 ON #포럼`", inline=True)
        embed.add_field(name="🔊 Soundboard", value="`!사운드보드`", inline=True)
        embed.add_field(name="🛡️ Discord AutoMod", value="`!디스코드자동관리 ON/OFF`", inline=True)
        embed.add_field(name="👤 개인 설치", value="`!개인설치`", inline=True)
        embed.set_footer(text=f"ABADDON v{VERSION} · Discord native integration")
        await ctx.send(embed=embed, view=NativeDiscordHubView(bot, world_data, save_data))

    @bot.command(name="이벤트만들기", aliases=["eventcreate", "discordevent"], help="버튼을 눌러 Discord 서버 이벤트 입력창을 엽니다.")
    async def event_create(ctx: commands.Context) -> None:
        if not await _require_manager(ctx):
            return

        class OpenEvent(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=120)

            @discord.ui.button(label="이벤트 입력", emoji="📅", style=discord.ButtonStyle.success)
            async def open(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
                del button
                if int(interaction.user.id) != int(ctx.author.id):
                    await interaction.response.send_message("이 버튼은 명령을 실행한 관리자만 사용할 수 있습니다.", ephemeral=True)
                    return
                await interaction.response.send_modal(NativeEventModal(world_data, save_data))

        await ctx.send("📅 아래 버튼을 눌러 제목/날짜/시간만 입력하세요.", view=OpenEvent())

    @bot.command(name="이벤트목록", aliases=["eventlist", "discordevents"], help="현재 Discord 서버 이벤트를 확인합니다.")
    async def event_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버에서 사용해주세요.")
            return
        try:
            events = await ctx.guild.fetch_scheduled_events(with_counts=True)
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ Discord 이벤트 목록을 읽을 수 없습니다.")
            return
        if not events:
            await ctx.send("📭 현재 Discord 서버 이벤트가 없습니다.")
            return
        lines = [f"• **{e.name}** · <t:{int(e.start_time.timestamp())}:R> · 관심 {getattr(e, 'user_count', 0) or 0}명\n  {e.url}" for e in events[:15]]
        await ctx.send("📅 **Discord 서버 이벤트**\n" + "\n".join(lines))

    @bot.command(name="일정이벤트", aliases=["scheduleevent", "syncschedule"], help="기존 ABADDON 일정 ID를 Discord 서버 이벤트로 변환합니다. `!일정이벤트 일정ID`")
    async def schedule_to_discord(ctx: commands.Context, 일정ID: str) -> None:
        if not await _require_manager(ctx):
            return
        hub = world_data.get("v1190_event_hub", {})
        guilds = hub.get("guilds", {}) if isinstance(hub, Mapping) else {}
        grow = guilds.get(str(ctx.guild.id), {}) if isinstance(guilds, Mapping) else {}
        events = grow.get("events", {}) if isinstance(grow, Mapping) else {}
        event = events.get(str(일정ID).upper()) if isinstance(events, Mapping) else None
        if not isinstance(event, Mapping) or str(event.get("status", "scheduled")) != "scheduled":
            await ctx.send("❌ 해당 ABADDON 일정을 찾지 못했습니다. `!일정`에서 ID를 확인해주세요.")
            return
        starts_at = _safe_int(event.get("starts_at"), 0)
        if starts_at <= int(discord.utils.utcnow().timestamp()) + 60:
            await ctx.send("❌ 이미 지난 일정이거나 시작까지 1분 미만입니다.")
            return
        start = datetime.fromtimestamp(starts_at, tz=timezone.utc)
        try:
            native = await ctx.guild.create_scheduled_event(
                name=str(event.get("title") or "ABADDON 일정")[:100],
                description=f"ABADDON 일정 `{str(일정ID).upper()}` · 종류 {event.get('type','기타')}",
                start_time=start,
                end_time=start + timedelta(hours=1),
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location="ABADDON / Discord",
                reason=f"ABADDON 일정 연동: {ctx.author}",
            )
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError) as exc:
            await ctx.send(f"❌ Discord 이벤트 연동 실패: `{type(exc).__name__}` · 이벤트 관리 권한을 확인해주세요.")
            return
        try:
            event["discord_scheduled_event_id"] = int(native.id)  # type: ignore[index]
        except Exception:
            pass
        _root(world_data)["stats"]["events"] = _safe_int(_root(world_data)["stats"].get("events"), 0) + 1
        save_data()
        await ctx.send(f"✅ ABADDON 일정 `{str(일정ID).upper()}` → Discord 서버 이벤트 연동 완료\n{native.url}")

    # ------------------------------------------------------------------
    # Threads: auto-thread suggestions + context menu.
    # ------------------------------------------------------------------
    @bot.command(name="스레드자동", aliases=["autothread", "threadauto"], help="공개 건의 게시물의 자동 스레드를 ON/OFF 합니다.")
    async def auto_thread_toggle(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await _require_manager(ctx):
            return
        row = _guild(world_data, ctx.guild.id)
        if str(상태).casefold() in {"상태", "status"}:
            await ctx.send(f"🧵 건의 자동 스레드 **{'ON' if row.get('auto_threads') else 'OFF'}**")
            return
        value = _on_off(상태)
        if value is None:
            await ctx.send("사용법: `!스레드자동 ON` / `!스레드자동 OFF`")
            return
        row["auto_threads"] = value
        save_data()
        await ctx.send(f"🧵 건의 자동 스레드 **{'ON' if value else 'OFF'}**")

    @bot.command(name="건의포럼", aliases=["suggestionforum", "forumbridge"], help="건의를 Discord 포럼 게시물로 자동 복사합니다. `!건의포럼 ON #포럼` / `OFF`")
    async def suggestion_forum(ctx: commands.Context, 상태: str = "상태", 채널: Optional[discord.ForumChannel] = None) -> None:
        if not await _require_manager(ctx):
            return
        row = _guild(world_data, ctx.guild.id)
        if str(상태).casefold() in {"상태", "status"}:
            cid = _safe_int(row.get("suggestion_forum_id"), 0)
            forum = ctx.guild.get_channel(cid) if cid else None
            await ctx.send(f"🧵 건의 포럼: **{'ON' if isinstance(forum, discord.ForumChannel) else 'OFF'}**" + (f" · {forum.mention}" if isinstance(forum, discord.ForumChannel) else ""))
            return
        value = _on_off(상태)
        if value is None:
            await ctx.send("사용법: `!건의포럼 ON #포럼채널` / `!건의포럼 OFF`")
            return
        if value:
            if not isinstance(채널, discord.ForumChannel):
                await ctx.send("❌ ON으로 켤 때 포럼 채널을 같이 지정해주세요. 예: `!건의포럼 ON #건의포럼`")
                return
            row["suggestion_forum_id"] = int(채널.id)
        else:
            row["suggestion_forum_id"] = 0
        save_data()
        await ctx.send(f"🧵 건의 포럼 자동 연결 **{'ON' if value else 'OFF'}**" + (f" · {채널.mention}" if value and 채널 else ""))

    @bot.listen("on_message")
    async def v1900_auto_thread_listener(message: discord.Message) -> None:
        if bot.user is None or message.author.id != bot.user.id or message.guild is None:
            return
        grow = _guild(world_data, message.guild.id)
        if not isinstance(message.channel, discord.TextChannel) or not message.embeds:
            return
        title = str(message.embeds[0].title or "")
        if not title.startswith("💡 SG-"):
            return
        forum_id = _safe_int(grow.get("suggestion_forum_id"), 0)
        forum = message.guild.get_channel(forum_id) if forum_id else None
        if isinstance(forum, discord.ForumChannel):
            try:
                await forum.create_thread(
                    name=(title.replace("💡 ", "")[:100] or "ABADDON 건의"),
                    content=f"ABADDON 건의 원문: {message.jump_url}\n이 포럼 글에서 검토/토론을 이어가세요.",
                    reason="ABADDON 건의 포럼 자동 연결",
                )
                _root(world_data)["stats"]["threads"] = _safe_int(_root(world_data)["stats"].get("threads"), 0) + 1
                save_data()
                return
            except (discord.Forbidden, discord.HTTPException):
                pass
        if not grow.get("auto_threads"):
            return
        try:
            await message.create_thread(name=(title.replace("💡 ", "")[:95] or "ABADDON 건의 토론"), auto_archive_duration=1440, reason="ABADDON 건의 자동 스레드")
            _root(world_data)["stats"]["threads"] = _safe_int(_root(world_data)["stats"].get("threads"), 0) + 1
            save_data()
        except (discord.Forbidden, discord.HTTPException):
            return

    # Replace one of the existing five message context menus to remain within the library/client budget.
    try:
        bot.tree.remove_command("메시지 요약", type=discord.AppCommandType.message)
    except Exception:
        pass

    async def context_open_thread(interaction: discord.Interaction, message: discord.Message) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버 메시지에서 사용해주세요.", ephemeral=True)
            return
        if not _is_manager(interaction.user) and int(interaction.user.id) != int(message.author.id):
            await interaction.response.send_message("메시지 작성자 또는 서버 관리자만 스레드를 열 수 있습니다.", ephemeral=True)
            return
        if not isinstance(message.channel, discord.TextChannel):
            await interaction.response.send_message("텍스트 채널 메시지에서 사용해주세요.", ephemeral=True)
            return
        try:
            thread = await message.create_thread(name=f"ABADDON · {interaction.user.display_name}"[:95], auto_archive_duration=1440, reason="ABADDON context thread")
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(f"스레드를 만들지 못했습니다: `{type(exc).__name__}`", ephemeral=True)
            return
        _root(world_data)["stats"]["threads"] = _safe_int(_root(world_data)["stats"].get("threads"), 0) + 1
        save_data()
        await interaction.response.send_message(f"🧵 스레드 생성 완료: {thread.mention}", ephemeral=True)

    try:
        bot.tree.add_command(app_commands.ContextMenu(name="ABADDON 스레드 열기", callback=context_open_thread))
    except (app_commands.CommandAlreadyRegistered, app_commands.CommandLimitReached):
        pass

    # Replace the old user '거래 안내' context menu with direct party joining.
    try:
        bot.tree.remove_command("거래 안내", type=discord.AppCommandType.user)
    except Exception:
        pass

    async def context_party_join(interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("서버에서 사용해주세요.", ephemeral=True)
            return
        if _find_party(world_data, interaction.user.id)[1] is not None:
            await interaction.response.send_message("이미 파티에 소속되어 있습니다.", ephemeral=True)
            return
        leader_id, party = _find_party(world_data, member.id)
        if not isinstance(party, MutableMapping) or str(leader_id) != str(member.id):
            await interaction.response.send_message(f"{member.mention}님이 이끄는 파티가 없습니다. 대상이 `!파티생성`을 먼저 실행해야 합니다.", ephemeral=True)
            return
        members = party.setdefault("members", [])
        if len(members) >= 4:
            await interaction.response.send_message("파티 정원이 가득 찼습니다.", ephemeral=True)
            return
        members.append(str(interaction.user.id))
        save_data()
        await interaction.response.send_message(f"👥 {member.mention}님의 파티에 바로 참가했습니다.", ephemeral=True)

    try:
        bot.tree.add_command(app_commands.ContextMenu(name="파티 참가", callback=context_party_join))
    except (app_commands.CommandAlreadyRegistered, app_commands.CommandLimitReached):
        pass

    # ------------------------------------------------------------------
    # Soundboard.
    # ------------------------------------------------------------------
    async def _sounds(guild: discord.Guild):
        try:
            rows = await guild.fetch_soundboard_sounds()
            return list(rows)
        except (discord.Forbidden, discord.HTTPException):
            return list(getattr(guild, "soundboard_sounds", []) or [])

    @bot.command(name="사운드보드", aliases=["soundboard", "sounds"], help="현재 서버 Soundboard 소리를 확인합니다.")
    async def soundboard_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ 서버에서 사용해주세요.")
            return
        rows = await _sounds(ctx.guild)
        if not rows:
            await ctx.send("🔊 등록된 서버 Soundboard 소리가 없습니다. 관리자: MP3/OGG를 첨부하고 `!사운드추가 이름`")
            return
        lines = [f"• {getattr(s, 'emoji', '') or '🔊'} **{s.name}** · ID `{s.id}`" for s in rows[:25]]
        await ctx.send("🔊 **Discord Soundboard**\n" + "\n".join(lines) + "\n\n재생: `!사운드재생 이름`")

    @bot.command(name="사운드추가", aliases=["soundadd"], help="첨부한 MP3/OGG를 Discord Soundboard에 추가합니다. 최대 512KB/5.2초 제한은 Discord 정책을 따릅니다.")
    async def sound_add(ctx: commands.Context, *, 이름: str) -> None:
        if not await _require_manager(ctx):
            return
        if not ctx.message.attachments:
            await ctx.send("❌ MP3 또는 OGG 파일을 메시지에 첨부하고 `!사운드추가 이름`을 입력해주세요.")
            return
        attachment = ctx.message.attachments[0]
        if attachment.size > 512 * 1024 or not attachment.filename.lower().endswith((".mp3", ".ogg")):
            await ctx.send("❌ Soundboard 파일은 MP3/OGG, 최대 512KB여야 합니다.")
            return
        try:
            data = await attachment.read()
            sound = await ctx.guild.create_soundboard_sound(name=str(이름).strip()[:32], sound=data, reason=f"ABADDON sound upload: {ctx.author}")
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError) as exc:
            await ctx.send(f"❌ Soundboard 등록 실패: `{type(exc).__name__}`\n파일 길이(최대 5.2초)와 표현식 생성 권한을 확인해주세요.")
            return
        _root(world_data)["stats"]["sounds"] = _safe_int(_root(world_data)["stats"].get("sounds"), 0) + 1
        await ctx.send(f"✅ Soundboard 등록 완료: **{sound.name}**")

    @bot.command(name="사운드재생", aliases=["soundplay"], help="현재 들어가 있는 음성 채널에서 Discord Soundboard 소리를 재생합니다.")
    async def sound_play(ctx: commands.Context, *, 이름: str) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member) or ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("❌ 먼저 음성 채널에 들어가주세요.")
            return
        rows = await _sounds(ctx.guild)
        query = str(이름).strip().casefold()
        sound = next((s for s in rows if s.name.casefold() == query), None) or next((s for s in rows if query in s.name.casefold()), None)
        if sound is None:
            await ctx.send("❌ 해당 Soundboard 소리를 찾지 못했습니다. `!사운드보드`로 목록을 확인해주세요.")
            return
        channel = ctx.author.voice.channel
        if not isinstance(channel, discord.VoiceChannel):
            await ctx.send("❌ 일반 음성 채널에서 사용해주세요.")
            return
        try:
            await channel.send_sound(sound)
        except (discord.Forbidden, discord.HTTPException, AttributeError) as exc:
            await ctx.send(f"❌ Soundboard 재생 실패: `{type(exc).__name__}` · 아바돈의 Soundboard 사용 권한을 확인해주세요.")
            return
        await ctx.send(f"🔊 **{sound.name}** 재생", delete_after=5)

    @bot.command(name="사운드삭제", aliases=["sounddelete", "soundremove"], help="서버 Soundboard 소리를 삭제합니다.")
    async def sound_delete(ctx: commands.Context, *, 이름: str) -> None:
        if not await _require_manager(ctx):
            return
        rows = await _sounds(ctx.guild)
        query = str(이름).strip().casefold()
        sound = next((s for s in rows if s.name.casefold() == query), None)
        if sound is None:
            await ctx.send("❌ 정확한 이름의 Soundboard 소리를 찾지 못했습니다.")
            return
        try:
            await sound.delete(reason=f"ABADDON sound delete: {ctx.author}")
        except (discord.Forbidden, discord.HTTPException, AttributeError) as exc:
            await ctx.send(f"❌ 삭제 실패: `{type(exc).__name__}`")
            return
        await ctx.send(f"🗑️ Soundboard **{sound.name}** 삭제 완료")

    # ------------------------------------------------------------------
    # Discord native AutoMod bridge.
    # ------------------------------------------------------------------
    @bot.command(name="디스코드자동관리", aliases=["discordautomod", "nativeautomod"], help="ABADDON 금칙어를 Discord 기본 AutoMod 규칙에 ON/OFF 동기화합니다.")
    async def native_automod(ctx: commands.Context, 상태: str = "상태") -> None:
        if not await _require_manager(ctx):
            return
        row = _guild(world_data, ctx.guild.id)
        if str(상태).casefold() in {"상태", "status"}:
            await ctx.send(f"🛡️ Discord 기본 AutoMod 동기화 **{'ON' if row.get('native_automod_enabled') else 'OFF'}**\n규칙명: `{AUTOMOD_RULE_NAME}`")
            return
        value = _on_off(상태)
        if value is None:
            await ctx.send("사용법: `!디스코드자동관리 ON` / `!디스코드자동관리 OFF`")
            return
        result = await _sync_native_automod(ctx.guild, world_data, value)
        save_data()
        await ctx.send("🛡️ " + result)

    @bot.command(name="디스코드자동관리동기화", aliases=["automodsync", "nativeautomodsync"], help="현재 ABADDON 금칙어를 Discord 기본 AutoMod 규칙에 다시 동기화합니다.")
    async def native_automod_resync(ctx: commands.Context) -> None:
        if not await _require_manager(ctx):
            return
        result = await _sync_native_automod(ctx.guild, world_data, True)
        save_data()
        await ctx.send("🔄 " + result)

    @bot.command(name="외부API설정안내", aliases=["externalapisetup", "youtubeapisetup"], help="YouTube/Twitch 외부 알림용 Render 환경변수 설정 방법을 확인합니다.")
    async def external_api_setup(ctx: commands.Context) -> None:
        await ctx.send(
            "🔐 **외부 알림 API 설정**\n"
            "• `YOUTUBE_API_KEY` = **유튜브 주소가 아니라 Google Cloud에서 발급한 YouTube Data API v3 API Key**\n"
            "• `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` = Twitch Developer 앱 자격증명\n"
            "이 값들은 **Render → apocalypse-bot → Environment**에만 넣고 홈페이지/config.js에는 넣지 마세요.\n\n"
            "API 설정 후 실제 채널 등록: `!유튜브알림등록 @핸들 #알림채널`"
        )

    # ------------------------------------------------------------------
    # User-install ready personal slash commands.
    # ------------------------------------------------------------------
    @app_commands.command(name="abaddon", description="ABADDON 개인 메뉴를 엽니다")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def personal_abaddon(interaction: discord.Interaction) -> None:
        row = _user(user_data, interaction.user.id)
        if row is None:
            text = "☣️ **ABADDON 개인 메뉴**\n생존자 데이터가 아직 없습니다. ABADDON이 설치된 서버에서 `!가입 생존자`로 시작해주세요."
        else:
            text = f"☣️ **{interaction.user.display_name} 생존자 카드**\nLv.{_safe_int(row.get('level'),1)} · 직업 {row.get('job') or '미선택'} · 전투력 약 {_power(row):,}\n즐겨찾기/추천은 서버에서 `!즐겨찾기` / `!추천`으로 이어서 사용할 수 있습니다."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="기능찾기", description="ABADDON 기능을 키워드로 찾습니다")
    @app_commands.describe(검색어="예: 로그, 채집, 장비, 길드")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def personal_find(interaction: discord.Interaction, 검색어: str) -> None:
        entries = command_hub._refresh_registry(bot)
        query = str(검색어).strip().casefold()
        found = []
        for entry in entries:
            hay = f"{entry.qualified_name} {entry.help_text} {entry.section} {entry.group}".casefold()
            if query and query in hay:
                found.append(entry)
            if len(found) >= 15:
                break
        if not found:
            await interaction.response.send_message("검색 결과가 없습니다. 더 짧은 단어로 검색해주세요.", ephemeral=True)
            return
        await interaction.response.send_message("🔎 **ABADDON 기능찾기**\n" + "\n".join(f"• `!{x.qualified_name}` — {str(x.help_text)[:80]}" for x in found), ephemeral=True)

    for app_cmd in (personal_abaddon, personal_find):
        if len(bot.tree.get_commands()) >= 100:
            print(f"[ABADDON v{VERSION}] user-install slash skipped (root limit): /{app_cmd.name}", flush=True)
            continue
        try:
            bot.tree.add_command(app_cmd)
        except (app_commands.CommandAlreadyRegistered, app_commands.CommandLimitReached):
            pass
    bot._abaddon_slash_root_count = len(bot.tree.get_commands())
    bot._abaddon_slash_total_count = sum(1 for _ in bot.tree.walk_commands())

    @bot.command(name="개인설치", aliases=["userinstall", "personalinstall"], help="ABADDON 개인 설치형 기능 준비 상태와 설정 방법을 확인합니다.")
    async def personal_install_info(ctx: commands.Context) -> None:
        await ctx.send(
            "👤 **ABADDON 개인 설치형**\n"
            "코드는 `/abaddon`, `/기능찾기`를 **User Install + 서버 설치 모두 허용**하도록 준비했습니다.\n"
            "Discord Developer Portal → **Installation**에서 **User Install**을 활성화해야 실제 개인 설치 버튼이 나타납니다.\n"
            "개인 설치 상태에서도 서버가 없어도 개인 메뉴/기능찾기를 사용할 수 있습니다."
        )

    # ------------------------------------------------------------------
    # Patch checklist / audit / public copy.
    # ------------------------------------------------------------------
    patch_check = bot.get_command("패치점검")
    if patch_check is not None:
        previous = patch_check.callback

        async def patch_check_v1900(ctx: commands.Context) -> None:
            embed = discord.Embed(title="🧪 ABADDON v19.0.0 점검 목록", description="Discord 네이티브 통합 + ON/OFF 단순화 점검입니다.", color=0xFEE75C)
            for name, value in [
                ("1) !디스코드센터", "투표/이벤트/스레드/Soundboard/AutoMod 버튼 확인"),
                ("2) !투표 오늘 월드보스 갈까요?", "Discord 기본 찬성/반대 Poll 생성 확인"),
                ("3) !투표 오늘 뭐할까? | 던전 | 채집 | 카지노", "선택형 Poll 확인"),
                ("4) !이벤트만들기 / !일정이벤트 ID", "새 이벤트 생성 + 기존 ABADDON 일정의 Discord 이벤트 연동 확인"),
                ("5) !스레드자동 ON / !건의포럼 ON #포럼", "건의가 스레드 또는 지정 포럼 게시물로 이어지는지 확인"),
                ("6) 메시지 우클릭 → 앱", "ABADDON 스레드 열기 / 기존 신고·관련 명령 동작 확인"),
                ("7) 유저 우클릭 → 앱", "파티 참가 / 생존자 정보 / 길드 초대 확인"),
                ("8) !사운드보드", "목록 표시 · 필요 시 짧은 MP3/OGG로 !사운드추가 테스트"),
                ("9) !디스코드자동관리 ON", "기존 금칙어 → Discord 기본 AutoMod 규칙 동기화 확인"),
                ("10) !자동관리 ON / !안티레이드 ON / !알림 ON", "대표 토글이 ON/OFF 입력으로 정상 동작하는지 확인"),
                ("11) /abaddon /기능찾기", "슬래시 동기화 후 개인 설치 호환 명령 확인"),
                ("12) !외부API설정안내", "YouTube API Key가 URL이 아니라 Google Cloud API Key라고 안내되는지 확인"),
                ("13) !명령어 / !로그", "기존 버튼·드롭다운·스마트 탐색 회귀 확인"),
            ]:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text="소유자 최종검수: !1900검수")
            await ctx.send(embed=embed)

        patch_check.callback = patch_check_v1900
        patch_check.help = "v19.0 배포 후 직접 확인할 Discord 네이티브 통합 점검 목록입니다."
        patch_check.description = patch_check.help
        patch_check.extras = dict(getattr(patch_check, "extras", {}) or {})
        patch_check.extras["v1900_previous_callback"] = previous

    @bot.command(name="1900검수", aliases=["1900audit", "nativeaudit"], hidden=True, help="[소유자 전용] v19 Discord 네이티브 통합 상태를 검사합니다.")
    @commands.is_owner()
    async def audit_1900(ctx: commands.Context) -> None:
        prefix = ["디스코드센터", "투표", "이벤트만들기", "이벤트목록", "스레드자동", "건의포럼", "일정이벤트", "사운드보드", "사운드추가", "사운드재생", "디스코드자동관리", "토글목록", "알림", "개인설치"]
        app_names = {(c.name, getattr(c, "type", None)) for c in bot.tree.get_commands()}
        user_menu = sum(1 for c in bot.tree.get_commands() if isinstance(c, app_commands.ContextMenu) and getattr(c, "type", None) == discord.AppCommandType.user)
        msg_menu = sum(1 for c in bot.tree.get_commands() if isinstance(c, app_commands.ContextMenu) and getattr(c, "type", None) == discord.AppCommandType.message)
        embed = discord.Embed(title="🧪 ABADDON v19.0.0 Native Discord 검수", color=0x57F287 if all(bot.get_command(x) for x in prefix) else 0xFEE75C)
        embed.add_field(name="Prefix 기능", value=" · ".join(f"{'✅' if bot.get_command(x) else '❌'}{x}" for x in prefix), inline=False)
        embed.add_field(name="Context Menu", value=f"USER {user_menu} · MESSAGE {msg_menu}\n스레드 열기 {'✅' if ('ABADDON 스레드 열기', discord.AppCommandType.message) in app_names else '❌'} · 파티 참가 {'✅' if ('파티 참가', discord.AppCommandType.user) in app_names else '❌'}", inline=False)
        embed.add_field(name="User Install 명령", value=f"/abaddon {'✅' if any(c.name=='abaddon' for c in bot.tree.get_commands()) else '❌'} · /기능찾기 {'✅' if any(c.name=='기능찾기' for c in bot.tree.get_commands()) else '❌'}", inline=False)
        embed.add_field(name="Discord.py", value=str(getattr(discord, "__version__", "?")), inline=True)
        embed.add_field(name="v19 통계", value=" · ".join(f"{k}={v}" for k, v in _root(world_data).get("stats", {}).items()), inline=False)
        await ctx.send(embed=embed)

    _apply_toggle_help(bot)
    try:
        command_hub._refresh_registry(bot)
    except Exception:
        pass
    try:
        from apocalypse_bot.commands.v1832_bilingual_persistent_hub import _sync_registry
        _sync_registry(bot)
    except Exception:
        pass

    print(
        f"[ABADDON v{VERSION}] native discord registered · poll,event,user-install,threads,soundboard,automod,on-off",
        flush=True,
    )


def finalize_v1900_surfaces(bot: commands.Bot) -> None:
    bot.abaddon_version = VERSION
    intro = bot.get_command("봇소개")
    if intro is not None:
        async def intro_v1900(ctx: commands.Context) -> None:
            embed = discord.Embed(title="☣️ ABADDON · Discord 네이티브 생존 플랫폼", description="1,400+ 기능을 유지하면서 Discord 자체 UI와 직접 연결한 v19입니다.", color=0x5865F2)
            embed.add_field(name="🛰️ Discord 네이티브", value="우클릭 앱 · 기본 Poll · 서버 이벤트 · 스레드 · Soundboard · Discord AutoMod", inline=False)
            embed.add_field(name="⚙️ 쉬운 ON/OFF", value="`!자동관리 ON` · `!안티레이드 OFF` · `!알림 ON`처럼 통일", inline=False)
            embed.add_field(name="👤 개인 설치 준비", value="`/abaddon` · `/기능찾기`는 User Install 호환 · Developer Portal에서 User Install 활성화 필요", inline=False)
            embed.add_field(name="📡 외부 알림", value="YouTube/Twitch는 v18.9 기능 유지 · YouTube는 URL이 아니라 Google Cloud API Key 사용", inline=False)
            embed.add_field(name="🛟 장애 문의", value="Discord DM `jjonga0022`", inline=False)
            embed.set_footer(text=f"ABADDON v{VERSION} · !패치점검")
            await ctx.send(embed=embed)
        intro.callback = intro_v1900
        intro.help = "ABADDON v19 Discord 네이티브 통합 기능을 확인합니다."
        intro.description = intro.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1900(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            embed = discord.Embed(title="🛰️ ABADDON v19.0.0 — NATIVE DISCORD INTEGRATION", color=0x5865F2)
            embed.add_field(name="📊 간단 투표", value="`!투표 질문`이면 찬성/반대 Discord Poll · `|`로 선택지만 추가", inline=False)
            embed.add_field(name="⚙️ ON/OFF", value="토글 기능 표기를 ON/OFF로 통일 · 기존 ON/OFF는 호환 유지", inline=False)
            embed.add_field(name="🖱️ 우클릭 앱", value="기존 5+5 제한 안에서 메시지 스레드 열기/파티 참가로 재구성", inline=False)
            embed.add_field(name="📅 Discord 서버 이벤트", value="입력 모달로 새 이벤트 생성 + 기존 `!일정` ID를 `!일정이벤트`로 Discord 이벤트에 연동", inline=False)
            embed.add_field(name="👤 User Install", value="/abaddon · /기능찾기 User Install 호환 코드 추가", inline=False)
            embed.add_field(name="🧵 포럼/스레드 · 🔊 Soundboard", value="건의 자동 스레드/포럼 연결 + 우클릭 스레드 · 서버 Soundboard 목록/추가/재생/삭제", inline=False)
            embed.add_field(name="🛡️ AutoMod", value="ABADDON 금칙어 → Discord 기본 AutoMod 규칙 ON/OFF 동기화", inline=False)
            embed.set_footer(text="점검: !패치점검 → 소유자 !1900검수")
            await ctx.send(embed=embed)
        patch.callback = patch_v1900
        patch.help = "ABADDON v19.0.0 Discord 네이티브 통합 패치노트입니다."
        patch.description = patch.help

    print(f"[ABADDON v{VERSION}] final native discord surfaces active", flush=True)
