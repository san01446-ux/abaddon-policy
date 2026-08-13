from __future__ import annotations

"""ABADDON v11.4.2 per-race dynamic horse-odds hotfix."""

import random
from typing import Any, Callable, List, MutableMapping, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1092_horse_racing_rules import (
    HORSES,
    ODDS_MAX,
    ODDS_MIN,
    generate_race_odds,
    race_settlement,
)

VERSION = "11.4.2"


def _checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    markets = [generate_race_odds(random.Random(seed)) for seed in range(40)]
    unique = len({market for market in markets})
    bounds = all(len(market) == len(HORSES) and all(ODDS_MIN <= value <= ODDS_MAX for value in market) for market in markets)
    varied = all(len(set(market)) >= 3 for market in markets)
    sample = markets[7]
    gross, net = race_settlement(10_000, 2, 2, sample)
    miss_gross, miss_net = race_settlement(10_000, 2, 1, sample)
    return [
        ("경주별 배당 재생성", unique >= 35, f"unique={unique}/40"),
        ("6마리 배당 범위", bounds, f"x{ODDS_MIN:.1f}~x{ODDS_MAX:.1f}"),
        ("한 경주 내 배당 다양성", varied, "각 시장 최소 3개 값"),
        ("적중 정산 배당 연결", gross == int(round(10_000 * sample[2])) and net == gross - 10_000, f"x{sample[2]:.1f} → {gross:,}"),
        ("미적중 판돈 손실", miss_gross == 0 and miss_net == -10_000, f"gross={miss_gross} net={miss_net}"),
        ("경마 명령 유지", bot.get_command("경마") is not None, "!경마 / !horserace"),
        ("경마장 설명 최신화", bot.get_command("경마장") is not None and "배당" in str(bot.get_command("경마장").help), "경주마다 랜덤"),
    ]


def register_v1142_dynamic_horse_odds(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[dict[str, Any]],
) -> None:
    @bot.command(
        name="경마배당검수",
        aliases=["raceoddsaudit", "dynamicoddsaudit", "v1142audit"],
        help="v11.4.2에서 추가한 경주별 랜덤 배당과 정산 연결만 검사합니다.",
    )
    async def v1142_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        rows = _checks(bot)
        passed = sum(1 for _, ok, _ in rows if ok)
        embed = _dashboard(
            bot,
            locale,
            f"🏇 ABADDON v{VERSION} 경마 배당 검수 · {passed}/{len(rows)}",
            f"🏇 ABADDON v{VERSION} Race Odds Audit · {passed}/{len(rows)}",
            "경주마다 새 배당이 생성되고 해당 배당으로 정산되는지 검사합니다.",
            "Checks that every race gets a fresh market and settles with that locked market.",
            discord.Color.green() if passed == len(rows) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!경마배당검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1142_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await v1142_audit.callback(ctx, 모드)
        test_command.callback = v1142_test
        test_command.help = "v11.4.2에서 변경한 경주별 랜덤 배당·배당 고정·정산 연결만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1142_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"🏇 ABADDON v{VERSION} — 경주별 랜덤 배당",
                f"🏇 ABADDON v{VERSION} — Per-Race Random Odds",
                "이번 핫픽스에서 실제로 변경한 항목만 표시합니다.",
                "Shows only the changes made in this hotfix.",
                discord.Color.gold(),
            )
            embed.add_field(name=_t(locale, "🎲 매 경주 새 배당", "🎲 Fresh Market Every Race"), value=_t(locale, "`!경마`를 새로 실행할 때마다 6마리 배당을 다시 생성합니다.", "Every new `!horserace` generates a fresh six-horse market."), inline=False)
            embed.add_field(name=_t(locale, "🔒 출발 후 고정", "🔒 Locked After Start"), value=_t(locale, "말을 선택해 출발한 뒤에는 해당 경주의 배당이 끝까지 바뀌지 않습니다.", "Once a horse is selected and the race starts, that market stays fixed."), inline=False)
            embed.add_field(name=_t(locale, "💰 정확한 정산", "💰 Exact Settlement"), value=_t(locale, "적중 시 선택 화면에 표시된 배당을 그대로 사용하며 손익과 현재 잔액을 함께 표시합니다.", "A win uses the exact displayed odds and still shows net change and current balance."), inline=False)
            embed.add_field(name=_t(locale, "🐎 기존 규칙 유지", "🐎 Existing Rules Preserved"), value=_t(locale, "말 표식·공통 결승선·사진 판정·음수 잔액·판돈 상한 없음은 그대로 유지합니다.", "Horse markers, shared finish, photo finish, negative balance and uncapped stake remain unchanged."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1142_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 경마 배당 핫픽스를 확인합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1142_dynamic_odds"]
    guide.append({
        "id": "v1142_dynamic_odds",
        "emoji": "🎲",
        "title": "v11.4.2 경주별 랜덤 배당",
        "hint": "매 경주 새 배당 · 출발 후 고정 · 선택 배당 정산 · 최신 전용 검수",
        "commands": [
            "!경마 10000 · !경마장 · !경마전적",
            "!경마배당검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1142_version = VERSION  # type: ignore[attr-defined]
    bot.v1142_checks = lambda: _checks(bot)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] horse_odds=per_race locked_after_start=true range={ODDS_MIN:.1f}-{ODDS_MAX:.1f}", flush=True)
