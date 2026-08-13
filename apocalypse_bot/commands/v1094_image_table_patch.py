from __future__ import annotations

"""ABADDON v10.9.4 full card-table image and Korean layout patch."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import ALL_GAMES, _dashboard
from apocalypse_bot.commands.v1094_visual_core import font_status
from apocalypse_bot.commands.v1094_card_table_images import render_private_hand, render_session_table

VERSION = "10.9.4"
PATCH_DATE = "2026-08-04"


def _source_contains(path: str, token: str) -> bool:
    try:
        return token in Path(path).read_text(encoding="utf-8")
    except Exception:
        return False


def _checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    fonts = font_status()
    regular = str(fonts.get("regular", ""))
    bold = str(fonts.get("bold", ""))
    safe_path = Path(__file__).with_name("v651_card_games.py")
    v1060 = Path(__file__).with_name("v1060_authentic_card_games.py")
    return [
        ("한글 글꼴", "missing" not in regular and "missing" not in bold, f"regular={regular} / bold={bold}"),
        ("카드 테이블 PNG 렌더러", callable(render_session_table), "public table renderer"),
        ("비공개 손패 PNG", callable(render_private_hand), "ephemeral private hand renderer"),
        ("게임 메시지 이미지 교체", _source_contains(str(safe_path), "attachments=[file]"), "message.edit + fresh attachment"),
        ("맞고·고스톱 이미지", _source_contains(str(v1060), "abaddon_hwatu_private_hand.png"), "floor/capture + private hand"),
        ("포커 이미지", _source_contains(str(v1060), "abaddon_poker_private_hand.png"), "board/street/pot + private hand"),
        ("블랙잭 이미지", _source_contains(str(v1060), "abaddon_blackjack_private_hand.png"), "dealer/player table"),
        ("섯다 이미지", _source_contains(str(v1060), "abaddon_seotda_private_hand.png"), "hidden public table + private hand"),
        ("원카드·조커잡기 이미지", _source_contains(str(safe_path), "abaddon_onecard_hand.png") and _source_contains(str(safe_path), "abaddon_oldmaid_hand.png"), "table + private hand"),
        ("전체 카드게임 연결", len(ALL_GAMES) == 25, f"games={len(ALL_GAMES)}/25"),
        ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
        ("최신 이미지 검수", bot.get_command("이미지검수") is not None, "!이미지검수 상세"),
    ]


def register_v1094_image_table_patch(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1094_registered", False):
        return
    bot._abaddon_v1094_registered = True

    @bot.command(name="1094이미지검수", aliases=["legacyimageaudit1094"], hidden=True, help="[레거시] v10.9.4 PNG 글꼴·레이아웃·카드 테이블 연결을 검사합니다.")
    async def image_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        checks = _checks(bot)
        passed = sum(1 for _name, ok, _detail in checks if ok)
        embed = _dashboard(
            bot, locale,
            f"🖼️ ABADDON v{VERSION} 이미지 검수 · {passed}/{len(checks)}",
            f"🖼️ ABADDON v{VERSION} Image Audit · {passed}/{len(checks)}",
            "한글 글꼴, 텍스트 배치, 공개 테이블과 비공개 손패 PNG 연결을 검사합니다.",
            "Checks Korean fonts, text layout, public table images and private-hand images.",
            discord.Color.green() if passed == len(checks) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(checks)
        if detail:
            for name, ok, value in checks:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ **{passed}** · ❌ **{len(checks)-passed}**\n`!1094이미지검수 상세`", inline=False)
        embed.set_footer(text=_t(locale, "실제 패 모양과 글자 잘림은 테스트 서버에서 각 게임 1판씩 확인", "Play one live round per game family to verify card art and clipping"))
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1094_test(ctx: commands.Context, 모드: str = "기본") -> None:
            locale = _ctx_locale(bot, ctx)
            checks = _checks(bot)
            passed = sum(1 for _name, ok, _detail in checks if ok)
            embed = _dashboard(
                bot, locale,
                f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {passed}/{len(checks)}",
                f"🧪 ABADDON v{VERSION} Latest Patch Test · {passed}/{len(checks)}",
                "이번 패치에서 바꾼 PNG 글꼴·레이아웃·카드 테이블 연결만 검사합니다.",
                "Checks only PNG fonts, layout and card-table connections changed in this patch.",
                discord.Color.green() if passed == len(checks) else discord.Color.orange(),
            )
            detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(checks)
            if detail:
                for name, ok, value in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
            else:
                embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ **{passed}** · ❌ **{len(checks)-passed}**\n`!테스트 상세`", inline=False)
            embed.add_field(name=_t(locale, "실제 점검", "Live Check"), value=_t(locale, "`!정보` → `!세계지도` → `!카드대시보드` → 카드게임 계열별 1판", "`!info` → `!worldmap` → `!carddashboard` → one round per card family"), inline=False)
            await ctx.send(embed=embed)
        test_command.callback = v1094_test
        test_command.help = "v10.9.4에서 수정한 PNG 글꼴·레이아웃·카드 테이블 경로를 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1094_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot, locale,
                f"🎴 ABADDON v{VERSION} — 카드 테이블 이미지·글꼴 패치",
                f"🎴 ABADDON v{VERSION} — Card Table Image & Font Patch",
                "이번 패치에서 실제 적용한 항목만 표시합니다.",
                "Only changes actually applied in this patch are shown.",
                discord.Color.dark_purple(),
            )
            embed.add_field(name=_t(locale, "🖋️ 한글 출력", "🖋️ Korean Rendering"), value=_t(locale, "호스트 한글 폰트를 우선 사용하고 없으면 Noto Sans CJK KR을 `/tmp`에 자동 저장합니다. 자동 줄바꿈·축소·말줄임을 공용 처리합니다.", "Uses a host Korean font first, otherwise caches Noto Sans CJK KR in `/tmp`; shared wrapping, shrinking and ellipsis are applied."), inline=False)
            embed.add_field(name=_t(locale, "🎴 실제 테이블 PNG", "🎴 Live Table PNG"), value=_t(locale, "맞고·고스톱, 포커 계열, 블랙잭·바카라, 섯다, 원카드·조커잡기와 나머지 신규 카드게임까지 진행 메시지의 PNG를 상태 변경마다 교체합니다.", "Refreshes a table PNG on every state change for hwatu, poker, casino, Seotda, One Card, Old Maid and the remaining new card modes."), inline=False)
            embed.add_field(name=_t(locale, "👁️ 비공개 손패", "👁️ Private Hands"), value=_t(locale, "포커·화투·블랙잭·섯다·원카드·조커잡기의 내 패 버튼을 본인 전용 PNG로 바꿨습니다.", "My Hand buttons for poker, hwatu, Blackjack, Seotda, One Card and Old Maid now return private PNGs."), inline=False)
            embed.add_field(name=_t(locale, "🌐 홈페이지 문장 정리", "🌐 Simpler Website Copy"), value=_t(locale, "첫 화면과 최신 패치 설명을 짧고 쉬운 문장으로 줄이고, 한국어·English 페이지를 따로 유지했습니다.", "Shortened the home and latest-patch copy while keeping Korean and English pages separate."), inline=False)
            embed.add_field(name=_t(locale, "🧪 최신 검수", "🧪 Latest Audit"), value=_t(locale, "`!테스트 상세`와 `!1094이미지검수 상세`가 v10.9.4에서 수정한 경로만 검사합니다.", "`!test detail` and `!imageaudit detail` check only v10.9.4 paths."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1094_patch_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1094_image_tables"]
    guide.append({
        "id": "v1094_image_tables", "emoji": "🖼️", "title": "v10.9.4 카드 테이블 이미지",
        "hint": "한글 폰트 · 자동 줄바꿈 · 25종 테이블 PNG · 비공개 손패 PNG · 최신 패치 검수",
        "commands": [
            "!이미지검수 상세 · !imageaudit detail", "!테스트 상세 · !test detail",
            "!정보 · !세계지도 · !카드대시보드", "!패치노트 · !patchnotes",
        ],
    })

    bot.v1094_version = VERSION  # type: ignore[attr-defined]
    bot.v1094_image_checks = lambda: _checks(bot)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] image_tables=25 private_hands=enabled korean_font=auto layout=wrapped website_copy=simplified", flush=True)
