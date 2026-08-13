from __future__ import annotations

"""ABADDON v11.4.1 horse-marker visibility hotfix.

This module is deliberately small and loads after v11.4.0. It keeps every
existing race rule and settlement path intact while making each horse visible
again on the live track.
"""

from typing import Any, Callable, List, Mapping, MutableMapping, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1092_horse_racing_rules import FINISH, HORSES, render_track_lane

VERSION = "11.4.1"


def _checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    sample_positions = [0, 5, 12, 20, 29, FINISH]
    lanes = [render_track_lane(position) for position in sample_positions]
    flag_indexes = [lane.index("🏁") for lane in lanes]
    return [
        ("말 표식 표시", all(lane.count("♞") == 1 for lane in lanes), "각 레인 ♞ 1개"),
        ("공통 결승선", len(set(flag_indexes)) == 1, f"flag_index={flag_indexes[0] if flag_indexes else '-'}"),
        ("완주 위치 표시", lanes[-1].endswith("♞🏁]"), f"finish={FINISH}"),
        ("말 이름 이모지", all(bool(str(row.get("emoji") or "")) for row in HORSES), f"horses={len(HORSES)}"),
        ("실시간 경마 명령", bot.get_command("경마") is not None, "!경마 / !horserace"),
        ("경마 전적 명령", bot.get_command("경마전적") is not None, "!경마전적 / !horseracestats"),
    ]


def register_v1141_horse_marker_hotfix(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[dict[str, Any]],
) -> None:
    @bot.command(
        name="경마표시검수",
        aliases=["racetrackaudit", "horsemarkeraudit", "v1141audit"],
        help="v11.4.1에서 수정한 말 표식과 공통 결승선만 검사합니다.",
    )
    async def v1141_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        rows = _checks(bot)
        passed = sum(1 for _, ok, _ in rows if ok)
        embed = _dashboard(
            bot,
            locale,
            f"🏇 ABADDON v{VERSION} 경마 표시 검수 · {passed}/{len(rows)}",
            f"🏇 ABADDON v{VERSION} Race Display Audit · {passed}/{len(rows)}",
            "사라진 말 표식과 공통 결승선 표시만 검사합니다.",
            "Checks only the restored horse markers and shared finish line.",
            discord.Color.green() if passed == len(rows) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(
                name=_t(locale, "결과", "Result"),
                value=f"✅ {passed} · ❌ {len(rows) - passed}\n`!경마표시검수 상세`",
                inline=False,
            )
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1141_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await v1141_audit.callback(ctx, 모드)
        test_command.callback = v1141_test
        test_command.help = "v11.4.1에서 수정한 경마 말 표식·공통 결승선만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1141_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"🏇 ABADDON v{VERSION} — 경마 말 표식 복구",
                f"🏇 ABADDON v{VERSION} — Horse Marker Restored",
                "이번 핫픽스에서 실제로 수정한 항목만 표시합니다.",
                "Shows only changes made in this hotfix.",
                discord.Color.gold(),
            )
            embed.add_field(
                name=_t(locale, "🐎 말 표시 복구", "🐎 Horse Visibility"),
                value=_t(locale, "각 말 이름 옆에 말 이모지를 표시하고, 트랙 안에는 움직이는 ♞ 표식을 다시 넣었습니다.", "Shows a horse emoji beside every name and restores the moving ♞ marker inside each lane."),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "🏁 결승선 고정", "🏁 Fixed Finish"),
                value=_t(locale, f"모든 레인은 0~{FINISH}의 같은 길이를 사용하며 체커기는 정확히 같은 위치에 표시됩니다.", f"Every lane uses coordinates 0–{FINISH}, with the flag at exactly the same position."),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "✅ 규칙 보존", "✅ Rules Preserved"),
                value=_t(locale, "순위 계산·사진 판정·배당·음수 잔액·정산 방식은 변경하지 않았습니다.", "Standings, photo finish, odds, negative balances and settlement rules are unchanged."),
                inline=False,
            )
            await ctx.send(embed=embed)
        patch_notes.callback = v1141_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 경마 표시 핫픽스를 확인합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1141_horse_marker"]
    guide.append({
        "id": "v1141_horse_marker",
        "emoji": "🏇",
        "title": "v11.4.1 경마 말 표식 복구",
        "hint": "말 이름 이모지 · 움직이는 ♞ 표식 · 공통 결승선 · 최신 전용 검수",
        "commands": [
            "!경마 10000 · !경마장 · !경마전적",
            "!경마표시검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1141_version = VERSION  # type: ignore[attr-defined]
    bot.v1141_checks = lambda: _checks(bot)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] horse_markers=visible shared_finish={FINISH} rules=unchanged", flush=True)
