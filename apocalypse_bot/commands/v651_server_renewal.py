from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v433_voice_sanctuary as renewal
from apocalypse_bot.commands.v641_stabilization import THEMES, THEME_GROUPS

VERSION = "6.5.1c"
PATCH_DATE = "2026-08-02"

THEME_TO_STYLE: Dict[str, str] = {}
for key, info in THEMES.items():
    group = str(info.get("group", ""))
    if group == "아포칼립스":
        style = "아포칼립스"
    elif group == "깔끔고딕":
        style = "고딕"
        if key in {"순백성당", "은빛도서관"}:
            style = "깔끔"
        elif key == "왕실무도회":
            style = "판타지"
    elif group == "화사자연":
        style = "커뮤니티"
        if key in {"라벤더문", "천공정원"}:
            style = "판타지"
    else:
        style = "사이버"
        if key in {"별빛극장", "마법학원", "달빛서재"}:
            style = "판타지"
        elif key == "아르데코":
            style = "미니멀"
    THEME_TO_STYLE[key] = style

CLASSIC_STYLES = tuple(sorted(renewal.STYLE_NAMES))


def _normalise(raw: str) -> str:
    return "".join(ch for ch in str(raw or "").strip().lower() if ch not in " _-·/")


def resolve_theme(raw: str) -> Tuple[Optional[str], Optional[str]]:
    token = _normalise(raw)
    for style in CLASSIC_STYLES:
        if token == _normalise(style):
            return None, style
    for key, info in THEMES.items():
        if token in {_normalise(key), _normalise(info.get("title", ""))}:
            return key, THEME_TO_STYLE[key]
    return None, None


def _guild_theme_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = world_data.setdefault("v641", {})
    guilds = root.setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(guild_id)] = state
    return state


def _theme_summary_embed(world_data: Dict[str, Any], guild: discord.Guild) -> discord.Embed:
    state = _guild_theme_state(world_data, guild.id)
    current_key = str(state.get("theme", "검은성당"))
    current = THEMES.get(current_key, THEMES["검은성당"])
    layout = renewal._layout_settings(world_data, guild.id)["layout"]
    plan = layout.get("renewal_plan") if isinstance(layout, dict) else None
    autopilot = layout.get("autopilot", {}) if isinstance(layout, dict) else {}
    backups = layout.get("backups", []) if isinstance(layout, dict) else []
    embed = discord.Embed(
        title="🛠️ ABADDON 서버 리뉴얼 통합 상태",
        description="테마·채널 구조·게임 구역·알림·이벤트 채널·백업을 한 메뉴에서 관리합니다.",
        color=int(current.get("color", 0x5865F2)),
    )
    embed.add_field(name="현재 브리핑 테마", value=f"{current.get('emoji','🎨')} **{current.get('title', current_key)}** (`{current_key}`)", inline=False)
    embed.add_field(name="테마 카탈로그", value=f"**{len(THEMES)}종** · 구조 변환 스타일 **{len(CLASSIC_STYLES)}종**", inline=True)
    embed.add_field(name="백업", value=f"**{len(backups)}개**", inline=True)
    if isinstance(plan, dict):
        cursor = int(plan.get("cursor", 0) or 0)
        total = len(plan.get("actions", []))
        embed.add_field(name="리뉴얼 계획", value=f"{cursor}/{total} · {plan.get('status','대기')}", inline=False)
    else:
        embed.add_field(name="리뉴얼 계획", value="진행 중인 계획 없음", inline=False)
    embed.add_field(name="안전 자동 진행", value="켜짐" if autopilot.get("enabled") else "꺼짐", inline=True)
    embed.add_field(name="빠른 설정", value="`!서버리뉴얼` · `!서버브리핑` · `!알림설정` · `!이벤트채널설정`", inline=False)
    return embed


def register_v651_server_renewal(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data: Callable[[], None],
) -> None:
    group = bot.get_command("서버리뉴얼")
    if not isinstance(group, commands.Group):
        return

    original_preview = bot.get_command("서버리뉴얼 미리보기")
    original_apply = bot.get_command("서버리뉴얼 적용")
    original_game_preview = bot.get_command("서버리뉴얼 게임미리보기")
    original_game_apply = bot.get_command("서버리뉴얼 게임정리")

    async def require_admin(ctx: commands.Context) -> Optional[discord.Guild]:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return None
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("⚠️ 서버 관리자만 사용할 수 있습니다.")
            return None
        return ctx.guild

    async def sync_theme(ctx: commands.Context, theme_key: Optional[str]) -> None:
        if theme_key is None or ctx.guild is None:
            return
        state = _guild_theme_state(world_data, ctx.guild.id)
        state["theme"] = theme_key
        state["renewal_synced_at"] = int(time.time())
        state["renewal_synced_by"] = int(ctx.author.id)
        save_data()

    if original_preview is not None:
        old = original_preview.callback

        async def preview_callback(ctx: commands.Context, style: str = "깔끔") -> None:
            theme_key, base_style = resolve_theme(style)
            if base_style is None:
                await ctx.send("❌ 지원하지 않는 테마입니다. `!서버리뉴얼 테마목록`에서 28종 목록을 확인하세요.")
                return
            if theme_key:
                info = THEMES[theme_key]
                await ctx.send(f"🎨 **{info['title']}** 테마는 채널 구조 **{base_style}** 스타일로 미리 봅니다. 브리핑 색상·이모지는 `{theme_key}`를 사용합니다.")
            await old(ctx, base_style)

        original_preview.callback = preview_callback

    if original_apply is not None:
        old = original_apply.callback

        async def apply_callback(ctx: commands.Context, style: str = "깔끔") -> None:
            theme_key, base_style = resolve_theme(style)
            if base_style is None:
                await ctx.send("❌ 지원하지 않는 테마입니다. `!서버리뉴얼 테마목록`에서 28종 목록을 확인하세요.")
                return
            await sync_theme(ctx, theme_key)
            await old(ctx, base_style)
            if theme_key:
                info = THEMES[theme_key]
                await ctx.send(f"✅ 서버 브리핑 테마도 {info['emoji']} **{info['title']}**로 동기화했습니다.")

        original_apply.callback = apply_callback

    if original_game_preview is not None:
        old = original_game_preview.callback

        async def game_preview_callback(ctx: commands.Context, style: str = "깔끔") -> None:
            theme_key, base_style = resolve_theme(style)
            if base_style is None:
                await ctx.send("❌ 지원하지 않는 테마입니다. `!서버리뉴얼 테마목록`에서 확인하세요.")
                return
            if theme_key:
                info = THEMES[theme_key]
                await ctx.send(f"🎮 **{info['title']}** 게임·음성 구역은 **{base_style}** 구조 스타일로 미리 봅니다.")
            await old(ctx, base_style)

        original_game_preview.callback = game_preview_callback

    if original_game_apply is not None:
        old = original_game_apply.callback

        async def game_apply_callback(ctx: commands.Context, style: str = "깔끔") -> None:
            theme_key, base_style = resolve_theme(style)
            if base_style is None:
                await ctx.send("❌ 지원하지 않는 테마입니다. `!서버리뉴얼 테마목록`에서 확인하세요.")
                return
            await sync_theme(ctx, theme_key)
            await old(ctx, base_style)
            if theme_key:
                info = THEMES[theme_key]
                await ctx.send(f"✅ 게임 구역 계획과 서버 브리핑을 {info['emoji']} **{info['title']}** 기준으로 동기화했습니다.")

        original_game_apply.callback = game_apply_callback

    theme_list_cmd = bot.get_command("서버리뉴얼 테마목록")
    if theme_list_cmd is not None:
        async def theme_list_callback(ctx: commands.Context) -> None:
            guild = await require_admin(ctx)
            if guild is None:
                return
            state = _guild_theme_state(world_data, guild.id)
            current_key = str(state.get("theme", "검은성당"))
            embed = discord.Embed(
                title=f"🎨 서버 리뉴얼 테마 {len(THEMES)}종",
                description="28종 테마는 브리핑 색상·문구와 채널 구조 스타일을 함께 연결합니다. 기존 7개 구조 스타일은 호환용으로 계속 사용할 수 있습니다.",
                color=0x6D2335,
            )
            icons = {"아포칼립스":"☣️", "깔끔고딕":"🏰", "화사자연":"🌸", "모던판타지":"🔮"}
            for group_name, keys in THEME_GROUPS.items():
                rows = []
                for key in keys:
                    info = THEMES[key]
                    marker = "✅" if key == current_key else "▫️"
                    rows.append(f"{marker} {info['emoji']} **{info['title']}** → `{THEME_TO_STYLE[key]}`")
                embed.add_field(name=f"{icons.get(group_name,'🎨')} {group_name} · {len(keys)}종", value="\n".join(rows)[:1024], inline=False)
            embed.add_field(name="직접 사용", value="`!서버리뉴얼 미리보기 벚꽃정원`\n`!서버리뉴얼 적용 깔끔고딕`\n`!서버리뉴얼 게임미리보기 네온아카데미`", inline=False)
            await ctx.send(embed=embed)

        theme_list_cmd.callback = theme_list_callback

    status_cmd = bot.get_command("서버리뉴얼 상태")
    async def renewal_status_callback(ctx: commands.Context) -> None:
        guild = await require_admin(ctx)
        if guild is None:
            return
        await ctx.send(embed=_theme_summary_embed(world_data, guild))

    if status_cmd is None:
        status_cmd = commands.Command(renewal_status_callback, name="상태", aliases=["설정", "설정상태"])
        group.add_command(status_cmd)
    else:
        status_cmd.callback = renewal_status_callback
        for alias in ("설정", "설정상태"):
            if alias not in status_cmd.aliases:
                status_cmd.aliases.append(alias)
            group.all_commands[alias] = status_cmd

    async def main_callback(ctx: commands.Context) -> None:
        guild = await require_admin(ctx)
        if guild is None:
            return
        owner_id = int(ctx.author.id)

        async def run_group(interaction: discord.Interaction, name: str, *args: Any) -> None:
            if int(interaction.user.id) != owner_id:
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            command_obj = bot.get_command(f"서버리뉴얼 {name}")
            if command_obj is None:
                await interaction.response.send_message(f"❌ `{name}` 기능을 찾지 못했습니다.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            try:
                await command_obj.callback(ctx, *args)
                await interaction.followup.send("✅ 선택한 서버 리뉴얼 기능을 실행했습니다.", ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(f"❌ 실행 실패: `{type(exc).__name__}: {str(exc)[:160]}`", ephemeral=True)

        async def run_top(interaction: discord.Interaction, name: str) -> None:
            if int(interaction.user.id) != owner_id:
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            command_obj = bot.get_command(name)
            if command_obj is None:
                await interaction.response.send_message(f"❌ `{name}` 기능을 찾지 못했습니다.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            try:
                await command_obj.callback(ctx)
                await interaction.followup.send("✅ 선택한 서버 설정을 열었습니다.", ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(f"❌ 실행 실패: `{type(exc).__name__}: {str(exc)[:160]}`", ephemeral=True)

        class ThemeSelect(discord.ui.Select):
            def __init__(self, mode: str, group_name: str) -> None:
                self.mode = mode
                options = []
                for key in THEME_GROUPS[group_name]:
                    info = THEMES[key]
                    options.append(discord.SelectOption(
                        label=f"{info['title']} · {THEME_TO_STYLE[key]} 구조"[:100],
                        value=key,
                        emoji=info.get("emoji", "🎨"),
                        description=str(info.get("tagline", ""))[:100],
                    ))
                super().__init__(placeholder=f"{group_name} 테마 선택", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction) -> None:
                command_map = {
                    "layout_preview": "미리보기",
                    "layout_apply": "적용",
                    "game_preview": "게임미리보기",
                    "game_apply": "게임정리",
                }
                await run_group(interaction, command_map[self.mode], self.values[0])

        class ThemeSelectView(discord.ui.View):
            def __init__(self, mode: str, group_name: str) -> None:
                super().__init__(timeout=300)
                self.add_item(ThemeSelect(mode, group_name))

        class ThemeGroupSelect(discord.ui.Select):
            def __init__(self, mode: str) -> None:
                self.mode = mode
                options = [
                    discord.SelectOption(label="아포칼립스 12종", value="아포칼립스", emoji="☣️", description="생존·폐허·방어 중심"),
                    discord.SelectOption(label="깔끔·고딕 4종", value="깔끔고딕", emoji="🏰", description="깔끔·성당·도서관·왕실"),
                    discord.SelectOption(label="화사·자연 6종", value="화사자연", emoji="🌸", description="정원·온실·해변·들판"),
                    discord.SelectOption(label="모던·판타지 6종", value="모던판타지", emoji="🔮", description="네온·도시·학원·서재"),
                ]
                super().__init__(placeholder="테마 분류를 고르세요", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction) -> None:
                if int(interaction.user.id) != owner_id:
                    await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                    return
                group_name = self.values[0]
                await interaction.response.send_message(
                    f"🎨 **{group_name}** 테마를 선택하세요.",
                    view=ThemeSelectView(self.mode, group_name),
                    ephemeral=True,
                )

        class ThemeGroupView(discord.ui.View):
            def __init__(self, mode: str) -> None:
                super().__init__(timeout=300)
                self.add_item(ThemeGroupSelect(mode))

        class RenewalMenu(discord.ui.Select):
            def __init__(self) -> None:
                options = [
                    discord.SelectOption(label="28종 테마 미리보기", value="layout_preview", emoji="🔎", description="분류→테마 선택 후 구조 계획 확인"),
                    discord.SelectOption(label="28종 테마 적용 계획", value="layout_apply", emoji="🎨", description="브리핑 테마 동기화+채널 구조 계획"),
                    discord.SelectOption(label="게임·음성 구역 미리보기", value="game_preview", emoji="🎮", description="선택 테마의 게임 구역 확인"),
                    discord.SelectOption(label="게임·음성 구역 계획", value="game_apply", emoji="🧭", description="게임 구역과 브리핑 테마 동기화"),
                    discord.SelectOption(label="전체 테마 28종 목록", value="themes", emoji="🌈", description="최신 테마와 구조 매핑 확인"),
                    discord.SelectOption(label="현재 서버 설정 상태", value="status", emoji="📊", description="테마·계획·백업·자동 진행 요약"),
                    discord.SelectOption(label="서버 브리핑 보기", value="briefing", emoji="📻", description="날씨·위험구역·기지·보급선"),
                    discord.SelectOption(label="현재 채널을 이벤트 채널로", value="event_channel", emoji="📢", description="날씨·보급선·밀수품 공개 알림"),
                    discord.SelectOption(label="개인 이벤트 알림 설정", value="alerts", emoji="🔔", description="날씨·보급선·밀수품 DM/멘션"),
                    discord.SelectOption(label="현재 상태 수동 백업", value="backup", emoji="💾", description="현재 정상 서버 구조 저장"),
                    discord.SelectOption(label="백업 목록·복구 선택", value="backups", emoji="🗃️", description="복구 기준 드롭다운"),
                    discord.SelectOption(label="계획 상태 확인", value="plan_status", emoji="📋", description="진행률과 다음 작업"),
                    discord.SelectOption(label="안전 자동 진행 시작", value="auto_start", emoji="⏯️", description="대기시간을 지키며 자동 실행"),
                    discord.SelectOption(label="자동 진행 일시정지", value="auto_stop", emoji="⏸️", description="계획을 보존하고 자동만 중지"),
                    discord.SelectOption(label="자동 진행 상태", value="auto_status", emoji="🛰️", description="진행률·다음 실행시간"),
                    discord.SelectOption(label="다음 단계 1개 실행", value="next", emoji="▶️", description="Discord 변경 한 개 처리"),
                    discord.SelectOption(label="복구 다음 단계 1개", value="recover_next", emoji="🛟", description="백업 복구 한 단계"),
                    discord.SelectOption(label="계획 취소", value="cancel", emoji="⏹️", description="남은 계획 제거"),
                    discord.SelectOption(label="429 안전상태", value="ratelimit", emoji="🛡️", description="격리·대기시간 확인"),
                    discord.SelectOption(label="빈 카테고리 선택 삭제", value="empty", emoji="🗑️", description="비어 있는 카테고리만 정리"),
                ]
                super().__init__(placeholder="서버 리뉴얼·설정 기능을 선택하세요", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction) -> None:
                choice = self.values[0]
                if choice in {"layout_preview", "layout_apply", "game_preview", "game_apply"}:
                    if int(interaction.user.id) != owner_id:
                        await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                        return
                    await interaction.response.send_message("먼저 테마 분류를 고르세요.", view=ThemeGroupView(choice), ephemeral=True)
                    return
                group_map = {
                    "themes":"테마목록", "status":"상태", "backup":"백업", "backups":"백업목록",
                    "plan_status":"계획상태", "auto_start":"자동시작", "auto_stop":"자동중지",
                    "auto_status":"자동상태", "next":"다음", "recover_next":"복구다음",
                    "cancel":"계획취소", "ratelimit":"429상태", "empty":"빈카테고리선택",
                }
                if choice in group_map:
                    await run_group(interaction, group_map[choice])
                    return
                top_map = {"briefing":"서버브리핑", "event_channel":"이벤트채널설정", "alerts":"알림설정"}
                await run_top(interaction, top_map[choice])

        class RenewalView(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=300)
                self.add_item(RenewalMenu())

        embed = _theme_summary_embed(world_data, guild)
        embed.title = "🕯️ ABADDON 서버 리뉴얼 제어실 v6.5.1c"
        embed.description = (
            "아래 드롭다운에서 **28종 테마·채널 구조·게임 구역·알림·이벤트 채널·백업·복구**를 관리하세요.\n"
            "테마 적용은 브리핑 테마를 동기화하고, 실제 채널 변경은 기존처럼 안전 계획을 거쳐 한 단계씩 진행합니다."
        )
        embed.add_field(name="권장 순서", value="수동 백업 → 28종 테마 미리보기 → 적용 계획 → 안전 자동 진행", inline=False)
        await ctx.send(embed=embed, view=RenewalView())

    group.callback = main_callback
    group.help = "28종 서버 테마와 채널 구조·게임 구역·알림·백업·복구를 드롭다운으로 관리합니다."
    group.description = group.help

    bot.v651_server_renewal_version = VERSION
    bot.v651_server_theme_count = len(THEMES)
