from __future__ import annotations

"""ABADDON v10.9.1 card catalogue dashboard and discord.py 2.7 UI hotfix.

This patch is intentionally narrow: it adds a visual per-game catalogue for all
25 card modes and verifies that the shared localization runtime no longer reads
or writes the deprecated ``discord.ui.TextInput.label`` attribute.
"""

import time
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1000_global_survivor as localization_runtime
from apocalypse_bot.commands.v651_card_games import MIN_BET
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _interaction_locale, _t
from apocalypse_bot.commands.v1060_authentic_card_games import GAME_EMOJI, GAME_EN, GAME_RULE_SUMMARY
from apocalypse_bot.commands.v1090_integrated_renewal import ALL_GAMES, _dashboard, _game_display
from apocalypse_bot.commands.v1092_visual_assets import build_card_catalog, build_card_detail

VERSION = "10.9.1"
PATCH_DATE = "2026-08-03"

DIRECT_COMMANDS: Dict[str, str] = {
    "블랙잭": "카드블랙잭",
    "바카라": "카드바카라",
}

PLAYER_RANGES: Dict[str, Tuple[int, int]] = {
    "포커": (2, 8), "텍사스홀덤": (2, 8), "오마하홀덤": (2, 8),
    "세븐카드스터드": (2, 7), "파인애플홀덤": (2, 8), "숏덱홀덤": (2, 8),
    "바둑이": (2, 8), "하이로우포커": (2, 7), "인디언포커": (2, 2),
    "블랙잭": (2, 8), "바카라": (2, 8), "섯다": (2, 6),
    "맞고": (2, 2), "고스톱": (3, 3), "원카드": (2, 6), "조커잡기": (2, 8),
    "훌라": (2, 6), "라미": (2, 6), "대통령": (2, 8), "주사위카드": (2, 8),
    "삼봉": (2, 6), "도리짓고땡": (2, 6), "민화투": (2, 3), "육백": (3, 3),
    "블랙잭토너먼트": (2, 8),
}

CATEGORIES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("♠️ 포커 계열", "♠️ Poker Family", (
        "포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "파인애플홀덤",
        "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커",
    )),
    ("🎴 한국 카드·화투", "🎴 Korean Cards & Hwatu", (
        "섯다", "삼봉", "도리짓고땡", "맞고", "고스톱", "민화투", "육백",
    )),
    ("🃏 카지노·토너먼트", "🃏 Casino & Tournament", (
        "블랙잭", "바카라", "주사위카드", "블랙잭토너먼트",
    )),
    ("🎉 파티·조합", "🎉 Party & Meld", (
        "원카드", "조커잡기", "훌라", "라미", "대통령",
    )),
)


def _direct_name(kind: str) -> str:
    return DIRECT_COMMANDS.get(kind, kind)


def _ascii_alias(bot: commands.Bot, kind: str) -> str:
    command = bot.get_command(_direct_name(kind))
    if command is None:
        return GAME_EN.get(kind, kind).replace(" ", "").casefold()
    for alias in command.aliases:
        if alias.isascii():
            return alias
    if command.name.isascii():
        return command.name
    return GAME_EN.get(kind, kind).replace(" ", "").casefold()


def _start_commands(bot: commands.Bot, locale: str, kind: str) -> Tuple[str, str]:
    if locale == "ko":
        return f"!{_direct_name(kind)} {MIN_BET}", f"!아바돈초대 {kind} {MIN_BET}"
    alias = _ascii_alias(bot, kind)
    english_name = GAME_EN.get(kind, kind)
    return f"!{alias} {MIN_BET}", f"!inviteabaddon {english_name} {MIN_BET}"


def _style_text(locale: str, kind: str) -> str:
    if kind in {"맞고", "고스톱", "민화투", "육백"}:
        return _t(locale, "손패 선택 → 바닥패 맞추기 → 더미 뒤집기 → 획득·정산", "Play a hand card → match the floor → flip stock → capture and settle")
    if kind in {"포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "파인애플홀덤", "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커", "삼봉", "도리짓고땡"}:
        return _t(locale, "거리별 공개·체크·콜·노리밋 레이즈·폴드·쇼다운", "Street reveals, check, call, no-limit raise, fold and showdown")
    if kind in {"블랙잭", "블랙잭토너먼트"}:
        return _t(locale, "히트·스탠드 선택과 딜러 규칙으로 진행", "Choose hit or stand against dealer rules")
    if kind == "바카라":
        return _t(locale, "플레이어·뱅커·타이 선택 후 표준 서드카드 규칙 적용", "Choose Player, Banker or Tie, then apply standard third-card rules")
    return _t(locale, "뽑기·내기·버리기·패스 등 종목별 턴 선택", "Game-specific draw, play, discard and pass turns")


def _catalog_embed(bot: commands.Bot, locale: str) -> discord.Embed:
    embed = _dashboard(
        bot,
        locale,
        "🎴 카드게임 도감 대시보드 · 25종",
        "🎴 Card-Game Catalogue Dashboard · 25 Modes",
        "종목을 선택하면 인원, 실제 진행 방식, 아바돈 지원, 시작 명령을 한 장의 카드로 확인합니다.",
        "Choose a mode to see players, live flow, ABADDON support and start commands in one card.",
        discord.Color.dark_purple(),
    )
    for ko_name, en_name, games in CATEGORIES:
        value = " · ".join(f"{GAME_EMOJI.get(kind, '🃏')} {_game_display(kind, locale)}" for kind in games)
        embed.add_field(name=_t(locale, ko_name, en_name), value=value, inline=False)
    embed.add_field(
        name=_t(locale, "공통 경제 규칙", "Shared Economy Rules"),
        value=_t(locale, "잔액 음수 허용 · 자유 레이즈 안전 한도 · 배수/최종 정산 상한 없음 · 파산신청 연동", "Negative balances · free-raise safety limit · uncapped multipliers/settlement · bankruptcy integration"),
        inline=False,
    )
    embed.set_footer(text=_t(locale, "아래 선택 메뉴에서 게임을 골라 상세 카드를 여세요.", "Choose a game below to open its detail card."))
    return embed


def _detail_embed(bot: commands.Bot, locale: str, kind: str) -> discord.Embed:
    minimum, maximum = PLAYER_RANGES.get(kind, (2, 8))
    start_command, ai_command = _start_commands(bot, locale, kind)
    name = _game_display(kind, locale)
    embed = _dashboard(
        bot,
        locale,
        f"{GAME_EMOJI.get(kind, '🃏')} {kind} · 게임 정보 카드",
        f"{GAME_EMOJI.get(kind, '🃏')} {name} · Game Information Card",
        GAME_RULE_SUMMARY[kind][0],
        GAME_RULE_SUMMARY[kind][1],
        discord.Color.gold() if kind in {"맞고", "고스톱", "섯다", "삼봉", "도리짓고땡", "민화투", "육백"} else discord.Color.dark_purple(),
    )
    player_text = f"{minimum}" if minimum == maximum else f"{minimum}–{maximum}"
    ai_text = _t(locale, "ABADDON 지원", "ABADDON supported")
    if minimum >= 3:
        ai_text += _t(locale, " · 혼자 시작 시 ABADDON-β 자동 보충", " · ABADDON-β auto-fills solo three-player tables")
    embed.add_field(name=_t(locale, "참가 인원", "Players"), value=f"**{player_text}** · {ai_text}", inline=True)
    embed.add_field(name=_t(locale, "기준 판돈", "Base Stake"), value=f"**{MIN_BET:,}** {_t(locale, '칩부터 · 상한 없음', 'chips minimum · no maximum')}", inline=True)
    embed.add_field(name=_t(locale, "실제 진행", "Live Flow"), value=_style_text(locale, kind), inline=False)
    embed.add_field(name=_t(locale, "일반 방 시작", "Start a Table"), value=f"`{start_command}`", inline=True)
    embed.add_field(name=_t(locale, "아바돈 즉시 대전", "Play ABADDON"), value=f"`{ai_command}`", inline=True)
    embed.add_field(
        name=_t(locale, "종료 결과", "Final Result"),
        value=_t(locale, "승패·공개 족보/점수·팟·이번 게임 증감액·게임 전→후 잔액 표시", "Shows outcome, public hand/score, pot, game net and balance before→after"),
        inline=False,
    )
    embed.set_footer(text=_t(locale, "버튼으로 일반 방 또는 아바돈 대전을 바로 만들 수 있습니다.", "Use the buttons to create a public table or start an ABADDON match."))
    return embed


def register_v1091_card_dashboard_hotfix(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1091_registered", False):
        return
    bot._abaddon_v1091_registered = True

    class StakeModal(discord.ui.Modal):
        def __init__(self, kind: str, locale: str, ai: bool) -> None:
            super().__init__(title=_t(locale, f"{kind} 판돈 입력", f"{_game_display(kind, locale)} Stake"))
            self.kind = kind
            self.locale = locale
            self.ai = ai
            self.amount = discord.ui.TextInput(placeholder=str(MIN_BET), min_length=1, max_length=100)
            label_cls = getattr(discord.ui, "Label", None)
            if label_cls is not None:
                self.add_item(label_cls(text=_t(locale, "판돈", "Stake"), description=_t(locale, "음수 잔액 허용 · 서버 안전 한도 안에서 자유 입력", "Negative balances · free input within the server safety limit"), component=self.amount))
            else:  # Compatibility only for older discord.py installations.
                self.amount = discord.ui.TextInput(label=_t(locale, "판돈", "Stake"), placeholder=str(MIN_BET), min_length=1, max_length=100)
                self.add_item(self.amount)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            try:
                amount = int(str(self.amount.value).replace(",", ""))
            except ValueError:
                await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True)
                return
            if amount < MIN_BET:
                await interaction.response.send_message(_t(self.locale, f"최소 판돈은 {MIN_BET:,}칩입니다.", f"Minimum stake is {MIN_BET:,} chips."), ephemeral=True)
                return
            if self.ai:
                starter = getattr(bot, "v1090_start_ai_card", None)
                if not callable(starter):
                    await interaction.response.send_message(_t(self.locale, "아바돈 시작 경로를 찾지 못했습니다.", "ABADDON start route is unavailable."), ephemeral=True)
                    return
                await starter(interaction, self.kind, amount)
                return
            creator = getattr(bot, "v1090_create_card_lobby", None)
            if not callable(creator):
                await interaction.response.send_message(_t(self.locale, "게임방 생성 경로를 찾지 못했습니다.", "Table creation route is unavailable."), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            _ok, text = await creator(interaction, self.kind, amount)
            await interaction.followup.send(text, ephemeral=True)

    class CardDetailView(discord.ui.View):
        def __init__(self, locale: str, kind: str) -> None:
            super().__init__(timeout=300)
            self.locale = locale
            self.kind = kind
            self.create_table.label = _t(locale, "게임방 만들기", "Create Table")
            self.play_ai.label = _t(locale, "아바돈 대전", "Play ABADDON")
            self.back.label = _t(locale, "전체 목록", "All Games")

        @discord.ui.button(label="게임방 만들기", style=discord.ButtonStyle.success, emoji="🎴")
        async def create_table(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await interaction.response.send_modal(StakeModal(self.kind, self.locale, False))

        @discord.ui.button(label="아바돈 대전", style=discord.ButtonStyle.primary, emoji="🤖")
        async def play_ai(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await interaction.response.send_modal(StakeModal(self.kind, self.locale, True))

        @discord.ui.button(label="전체 목록", style=discord.ButtonStyle.secondary, emoji="↩️")
        async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            embed = _catalog_embed(bot, self.locale)
            image = build_card_catalog(locale=self.locale, categories=CATEGORIES, game_en=GAME_EN)
            file = discord.File(image, filename="abaddon_card_catalog.png")
            embed.set_image(url="attachment://abaddon_card_catalog.png")
            try:
                await interaction.response.edit_message(embed=embed, view=CardCatalogView(self.locale), attachments=[file])
            except TypeError:
                await interaction.response.edit_message(embed=embed, view=CardCatalogView(self.locale))

    class CardCatalogSelect(discord.ui.Select):
        def __init__(self, locale: str) -> None:
            self.locale = locale
            options = [
                discord.SelectOption(
                    label=_game_display(kind, locale),
                    value=kind,
                    emoji=GAME_EMOJI.get(kind, "🃏"),
                    description=GAME_RULE_SUMMARY[kind][0 if locale == "ko" else 1][:100],
                )
                for kind in ALL_GAMES
            ]
            super().__init__(placeholder=_t(locale, "카드게임 25종 상세 보기", "View details for 25 card modes"), min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            kind = self.values[0]
            embed = _detail_embed(bot, self.locale, kind)
            minimum, maximum = PLAYER_RANGES.get(kind, (2, 8))
            player_text = f"{minimum}" if minimum == maximum else f"{minimum}–{maximum}"
            start_command, ai_command = _start_commands(bot, self.locale, kind)
            image = build_card_detail(
                locale=self.locale,
                name=_game_display(kind, self.locale),
                rule=GAME_RULE_SUMMARY[kind][0 if self.locale == "ko" else 1],
                players=player_text,
                flow=_style_text(self.locale, kind),
                start=start_command,
                ai_start=ai_command,
            )
            file = discord.File(image, filename="abaddon_card_detail.png")
            embed.set_image(url="attachment://abaddon_card_detail.png")
            try:
                await interaction.response.edit_message(embed=embed, view=CardDetailView(self.locale, kind), attachments=[file])
            except TypeError:
                await interaction.response.edit_message(embed=embed, view=CardDetailView(self.locale, kind))

    class CardCatalogView(discord.ui.View):
        def __init__(self, locale: str) -> None:
            super().__init__(timeout=300)
            self.add_item(CardCatalogSelect(locale))

    @bot.command(name="카드대시보드", aliases=["carddashboard", "cardcatalog", "cardgamesdashboard", "카드도감"])
    async def card_dashboard(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        embed = _catalog_embed(bot, locale)
        image = build_card_catalog(locale=locale, categories=CATEGORIES, game_en=GAME_EN)
        file = discord.File(image, filename="abaddon_card_catalog.png")
        embed.set_image(url="attachment://abaddon_card_catalog.png")
        await ctx.send(embed=embed, file=file, view=CardCatalogView(locale))

    card_dashboard.help = "카드게임 25종을 카테고리와 개별 정보 카드로 확인하고 바로 시작합니다."
    card_dashboard.description = card_dashboard.help

    # Add the catalogue route to the existing card centre without removing its fast-start selector.
    card_menu = bot.get_command("카드게임")
    if card_menu is not None:
        previous = card_menu.callback

        async def card_menu_with_catalogue(ctx: commands.Context) -> None:
            await previous(ctx)
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                "📚 카드게임 종류별 이미지 대시보드",
                "📚 Per-Game Visual Card Dashboard",
                "25종을 이미지 한 장으로 확인하고 아래 메뉴에서 상세 규칙과 시작 버튼을 여세요.",
                "Review all 25 modes in one image, then use the menu for details and launch buttons.",
                discord.Color.dark_teal(),
            )
            image = build_card_catalog(locale=locale, categories=CATEGORIES, game_en=GAME_EN)
            file = discord.File(image, filename="abaddon_card_catalog.png")
            embed.set_image(url="attachment://abaddon_card_catalog.png")
            await ctx.send(embed=embed, file=file, view=CardCatalogView(locale))

        card_menu.callback = card_menu_with_catalogue
        card_menu.help = "빠른 시작 메뉴와 카드게임 25종 상세 대시보드를 함께 표시합니다."
        card_menu.description = card_menu.help

    def latest_checks() -> List[Tuple[str, bool, str]]:
        checks: List[Tuple[str, bool, str]] = []
        checks.append(("카드 대시보드 명령", bot.get_command("카드대시보드") is not None, "!카드대시보드 / !carddashboard"))
        checks.append(("카드게임 25종", len(ALL_GAMES) == 25 and len(set(ALL_GAMES)) == 25, f"{len(ALL_GAMES)}/25"))
        checks.append(("상세 카드 데이터", all(kind in GAME_RULE_SUMMARY and kind in PLAYER_RANGES for kind in ALL_GAMES), "rules + players 25/25"))
        checks.append(("Discord 선택 제한", len(ALL_GAMES) <= 25, f"options={len(ALL_GAMES)}"))
        checks.append(("일반 방 버튼 경로", callable(getattr(bot, "v1090_create_card_lobby", None)), "dashboard → stake modal → lobby"))
        checks.append(("아바돈 버튼 경로", callable(getattr(bot, "v1090_start_ai_card", None)), "dashboard → stake modal → ABADDON"))
        checks.append(("3인 정보 표시", PLAYER_RANGES.get("고스톱") == (3, 3) and PLAYER_RANGES.get("육백") == (3, 3), "ABADDON + β"))
        checks.append(("한국어/English 분리", _game_display("텍사스홀덤", "ko") == "텍사스홀덤" and _game_display("텍사스홀덤", "en") != "텍사스홀덤", "selected locale only"))
        checks.append(("TextInput 경고 차단", bool(getattr(localization_runtime, "V1091_DEPRECATION_SAFE_LOCALIZER", False)), "deprecated .label access skipped"))
        checks.append(("discord.ui.Label 모달", hasattr(discord.ui, "Label"), "2.7-compatible modal caption"))
        checks.append(("명령 설명 최신화", "25종" in str(card_dashboard.help), "card dashboard help"))
        checks.append(("최신 패치노트", bot.get_command("패치노트") is not None, VERSION))
        return checks

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1091_test(ctx: commands.Context, 모드: str = "기본") -> None:
            locale = _ctx_locale(bot, ctx)
            checks = latest_checks()
            passed = sum(1 for _name, ok, _info in checks if ok)
            failed = len(checks) - passed
            embed = _dashboard(
                bot,
                locale,
                f"🧪 ABADDON v{VERSION} 최신 핫픽스 테스트 · {passed}/{len(checks)} 통과",
                f"🧪 ABADDON v{VERSION} Latest Hotfix Audit · {passed}/{len(checks)} PASS",
                "이번 v10.9.1에서 수정한 카드 대시보드와 UI 경고 경로만 읽기 전용으로 검사합니다.",
                "Read-only checks cover only the v10.9.1 card dashboard and UI warning paths.",
                discord.Color.green() if failed == 0 else discord.Color.orange(),
            )
            detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or failed > 0
            if detail:
                for name, ok, info in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(info)[:1024], inline=True)
            else:
                embed.add_field(name=_t(locale, "결과", "Result"), value=_t(locale, f"✅ 통과 **{passed}** · ❌ 실패 **{failed}**\n상세: `!테스트 상세`", f"✅ PASS **{passed}** · ❌ FAIL **{failed}**\nDetails: `!test detail`"), inline=False)
            embed.add_field(name=_t(locale, "이번 검수 범위", "This Audit Scope"), value=_t(locale, "카드게임 25종 정보 카드 · 일반/AI 시작 버튼 · 한국어/English 분리 · TextInput 폐기 경고 제거", "25 game cards · public/AI launch buttons · locale separation · TextInput deprecation-warning removal"), inline=False)
            embed.set_footer(text=_t(locale, "Render 로그에서 v1000_global_survivor.py:430~433 경고가 다시 생기지 않는지 확인하세요.", "Confirm the old v1000_global_survivor.py:430–433 warnings do not return in Render logs."))
            await ctx.send(embed=embed)

        test_command.callback = v1091_test
        test_command.help = "v10.9.1 카드 대시보드·discord.py UI 경고 핫픽스만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    flow_audit = bot.get_command("게임진행검수")
    if flow_audit is not None and test_command is not None:
        async def v1091_game_audit(ctx: commands.Context) -> None:
            await test_command.callback(ctx, "상세")
        flow_audit.callback = v1091_game_audit

    patch_command = bot.get_command("패치노트")
    if patch_command is not None:
        async def v1091_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"🩹 ABADDON v{VERSION} — 카드 대시보드·UI 로그 핫픽스",
                f"🩹 ABADDON v{VERSION} — Card Dashboard & UI Log Hotfix",
                "이번 패치에서 실제로 수정한 항목만 표시합니다.",
                "This panel lists only items changed in this hotfix.",
                discord.Color.dark_teal(),
            )
            embed.add_field(name=_t(locale, "🎴 카드게임 25종 상세 카드", "🎴 Detail Cards for 25 Modes"), value=_t(locale, "`!카드대시보드`에서 카테고리 → 종목 선택 → 규칙·인원·실제 진행·일반 방·아바돈 대전을 한 화면으로 확인", "Use `!carddashboard` to choose a category and mode, then see rules, players, live flow, public table and ABADDON launch in one panel"), inline=False)
            embed.add_field(name=_t(locale, "▶️ 대시보드에서 바로 시작", "▶️ Start from the Dashboard"), value=_t(locale, "일반 게임방 만들기와 아바돈 대전 버튼에 최신 `discord.ui.Label` 판돈 입력창 적용", "Public-table and ABADDON buttons use the current `discord.ui.Label` stake modal"), inline=False)
            embed.add_field(name=_t(locale, "🧹 Render 경고 제거", "🧹 Render Warning Removed"), value=_t(locale, "공용 번역기가 폐기된 `TextInput.label`을 읽거나 수정하지 않도록 분리하고, 버튼·선택 메뉴·현행 Label만 번역", "The shared localizer no longer reads or writes deprecated `TextInput.label`; buttons, selects and modern Label containers remain localized"), inline=False)
            embed.add_field(name=_t(locale, "🧪 최신 범위 검수", "🧪 Latest-Scope Audit"), value=_t(locale, "`!테스트 상세`가 v10.9.1의 카드 대시보드·일반/AI 시작 경로·언어 분리·경고 제거만 검사", "`!test detail` checks only the v10.9.1 dashboard, launch routes, locale separation and warning fix"), inline=False)
            embed.set_footer(text=_t(locale, f"v{VERSION} · 명령어/설명/홈페이지/패치노트 동기화", f"v{VERSION} · commands/descriptions/website/patch notes synchronized"))
            await ctx.send(embed=embed)

        patch_command.callback = v1091_patch_notes
        patch_command.help = f"ABADDON v{VERSION} 카드 대시보드·UI 로그 핫픽스 패치노트를 표시합니다."
        patch_command.description = patch_command.help

    guide[:] = [row for row in guide if row.get("id") != "v1091_card_dashboard_hotfix"]
    guide.append({
        "id": "v1091_card_dashboard_hotfix",
        "emoji": "🩹",
        "title": "v10.9.1 카드 대시보드·UI 로그 핫픽스",
        "hint": "카드 25종 상세 카드 · 일반/AI 즉시 시작 · TextInput 폐기 경고 제거 · 최신 범위 테스트",
        "commands": [
            "!카드대시보드 · !카드도감",
            "!carddashboard · !cardcatalog",
            "!카드게임 · !아바돈초대",
            "!테스트 상세 · !패치노트",
        ],
    })

    bot.v1091_card_catalog_view_factory = CardCatalogView  # type: ignore[attr-defined]
    bot.v1091_version = VERSION  # type: ignore[attr-defined]
    bot.v1091_card_dashboard_games = ALL_GAMES  # type: ignore[attr-defined]
    bot.v1091_latest_checks = latest_checks  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] card_dashboard=25 label_deprecation=safe latest_audit=12", flush=True)
