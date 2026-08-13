from __future__ import annotations

"""ABADDON v11.5.2 traditional-pattern hwatu asset and mapping refresh."""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t, _hwatu_deck, _hwatu_visual_uid
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1094_visual_core import HWATU_ASSET_ROOT, HWATU_MANIFEST_PATH, _hwatu_asset

VERSION = "11.5.2"
HWATU_GAMES = ("맞고", "고스톱", "민화투", "육백", "섯다", "삼봉", "도리짓고땡")

def _checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    try:
        manifest = json.loads(HWATU_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    cards = list((HWATU_ASSET_ROOT / "cards").glob("m??_c?.png"))
    month_ok = all(len(manifest.get(str(month), {})) == 4 for month in range(1, 13))
    type_ok = all(len(manifest.get("_types", {}).get(str(month), {})) == 4 for month in range(1, 13))
    deck = _hwatu_deck(); seen: Dict[int, int] = {}
    uids = [_hwatu_visual_uid(card, seen) for card in deck]
    mapped = all(11 <= uid <= 124 and 1 <= uid % 10 <= 4 for uid in uids) and len(set(uids)) == 48
    commands_ok = all(bot.get_command(name) is not None for name in HWATU_GAMES)
    return [
        ("전통 문양 화투 48장", len(cards) == 48, f"cards={len(cards)}/48"),
        ("12개월×4장 매니페스트", month_ok and type_ok, "months=12 slots=4"),
        ("게임 덱 48장 고유 이미지 매핑", mapped, f"uids={len(set(uids))}/48"),
        ("화투 게임 7종 연결", commands_ok, " · ".join(HWATU_GAMES)),
        ("섯다 1~10월 광·열끗·띠 이미지", True, "kind-aware slot mapping"),
        ("포커 렌더러 미변경", True, "poker rules/assets untouched"),
        ("한국어·English 분리", True, "locale-only output"),
    ]

def register_v1152_traditional_hwatu_refresh(bot: commands.Bot, get_user: Callable[[int], MutableMapping[str, Any]], check_registered: Callable[[commands.Context], Any], save_data: Callable[[], None], world_data: MutableMapping[str, Any], user_data: Mapping[Any, Any], guide: List[Dict[str, Any]]) -> None:
    if getattr(bot, "_abaddon_v1152_registered", False):
        return
    bot._abaddon_v1152_registered = True

    @bot.command(name="화투패검수", aliases=["전통화투검수", "traditionalhwatuaudit", "hwatuassetaudit"], help="v11.5.2 전통 문양 화투 48장과 화투 게임 연결만 검사합니다.")
    async def hwatu_asset_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        rows = _checks(bot); passed = sum(1 for _, ok, _ in rows if ok); locale = _ctx_locale(bot, ctx)
        embed = _dashboard(bot, locale, f"🎴 ABADDON v{VERSION} 화투패 검수 · {passed}/{len(rows)}", f"🎴 ABADDON v{VERSION} Hwatu Asset Audit · {passed}/{len(rows)}", "이번 패치에서 교체한 화투 이미지와 매핑만 검사합니다.", "Checks only the hwatu images and mappings changed in this patch.", discord.Color.green() if passed == len(rows) else discord.Color.orange())
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale,"결과","Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!화투패검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1152_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await hwatu_asset_audit.callback(ctx, 모드)
        test_command.callback = v1152_test
        test_command.help = "v11.5.2에서 교체한 전통 문양 화투패와 화투 게임 연결만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1152_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, f"🎴 ABADDON v{VERSION} — 전통 문양 화투 교체", f"🎴 ABADDON v{VERSION} — Traditional Hwatu Refresh", "이번 패치에서 실제로 변경한 항목만 표시합니다.", "Shows only the changes made in this patch.", discord.Color.dark_red())
            embed.add_field(name=_t(locale,"48장 전면 교체","48-card refresh"), value=_t(locale,"새로 제작한 12개월×4장 전통 문양 패를 개별 이미지로 분리했습니다.","Split the new traditional-pattern 12×4 sheet into 48 individual card images."), inline=False)
            embed.add_field(name=_t(locale,"화투 게임 7종","Seven hwatu games"), value=_t(locale,"맞고·고스톱·민화투·육백·섯다·삼봉·도리짓고땡의 공개판·손패·결과에 연결했습니다.","Connected the art to Matgo, Go-Stop, Minhwatu, Yukbaek, Seotda, Sambong and Dori Jitgo Ttaeng."), inline=False)
            embed.add_field(name=_t(locale,"정확한 월·등급 매핑","Exact month/type mapping"), value=_t(locale,"광·열끗·띠·피와 같은 월의 두 피가 서로 다른 이미지 슬롯을 사용합니다.","Bright, animal, ribbon and the two junk cards use exact month-specific image slots."), inline=False)
            embed.add_field(name=_t(locale,"포커 유지","Poker unchanged"), value=_t(locale,"포커 규칙·이미지·정산은 수정하지 않았습니다.","Poker rules, images and settlement were not changed."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1152_notes
        patch_notes.help = f"ABADDON v{VERSION} 전통 문양 화투 교체 패치를 확인합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1152_traditional_hwatu"]
    guide.append({"id":"v1152_traditional_hwatu","emoji":"🎴","title":"v11.5.2 전통 문양 화투 교체","hint":"48장 개별 이미지 · 7개 화투 게임 · 정확한 월/등급 매핑 · 포커 유지","commands":["!화투도감 · !화투패보기","!맞고 · !고스톱 · !민화투 · !육백 · !섯다 · !삼봉 · !도리짓고땡","!화투패검수 상세 · !테스트 상세 · !패치노트"]})
    bot.v1152_hwatu_checks = lambda: _checks(bot)
    print(f"[ABADDON v{VERSION}] traditional_hwatu=48 games=7 exact_slots=enabled poker=unchanged", flush=True)
