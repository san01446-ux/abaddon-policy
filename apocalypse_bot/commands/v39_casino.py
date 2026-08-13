from __future__ import annotations

ABADDON_TEXT_FIRST_DISABLED = True

import asyncio
import math
import os
import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v37_gambling_experience import (
    GAMBLE_MAX_BET,
    GAMBLE_MIN_BET,
    _kst_date,
    _safe_reactions,
    _signed,
)
from apocalypse_bot.commands.v635_visuals import apply_casino_visual
from apocalypse_bot.commands.v636_world_combat import pet_casino_adjustment, weather_slot_weights
from apocalypse_bot.commands.v639_frontier_operations import apply_supply_slot_weights
from apocalypse_bot.commands.v40_black_casino import (
    add_casino_chips,
    apply_loss_shield,
    casino_chips,
    claim_jackpot,
    consume_slot_buffs,
    daily_loss_bonus,
    dealer_line,
    ensure_black_casino_account,
    ensure_black_casino_world,
    pending_achievement_text,
    record_black_casino_game,
    set_casino_chips,
    slot_symbol_weights,
    vip_info,
)


CASINO_DAILY_LOSS_LIMIT = 50_000_000
CASINO_HISTORY_LIMIT = 30
CASINO_INTERACTIVE_TIMEOUT = 75
CASINO_GAME_COOLDOWN = 8

CASINO_GAME_NAMES: Set[str] = {
    "블랙잭",
    "하이로우",
    "슬롯머신",
    "다이스",
    "바카라",
}

CARD_SUITS: Tuple[str, ...] = ("♠️", "♥️", "♦️", "♣️")
CARD_RANKS: Tuple[str, ...] = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")

SLOT_SYMBOLS: Sequence[Tuple[str, float]] = (
    ("🍒", 39),
    ("🍋", 29),
    ("🔔", 17),
    ("👑", 8),
    ("7️⃣", 4.5),
    ("💠", 1.8),
    ("💀", 1),
)

SLOT_TRIPLE_PAYOUTS: Dict[str, float] = {
    "🍒": 4.5,
    "🍋": 5.5,
    "🔔": 8.0,
    "👑": 14.0,
    "7️⃣": 26.0,
    "💠": 50.0,
    "💀": 0.0,
}


# ---------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_deck(deck_count: int = 1) -> List[Tuple[str, str]]:
    deck = [(rank, suit) for _ in range(deck_count) for suit in CARD_SUITS for rank in CARD_RANKS]
    random.shuffle(deck)
    return deck


def _card_text(card: Tuple[str, str]) -> str:
    rank, suit = card
    return f"`{rank}{suit}`"


def _hand_text(cards: Sequence[Tuple[str, str]], hide_second: bool = False) -> str:
    if hide_second and len(cards) >= 2:
        return f"{_card_text(cards[0])} `??`"
    return " ".join(_card_text(card) for card in cards)


def _blackjack_value(cards: Sequence[Tuple[str, str]]) -> int:
    total = 0
    aces = 0
    for rank, _ in cards:
        if rank == "A":
            total += 11
            aces += 1
        elif rank in {"J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _highlow_value(card: Tuple[str, str]) -> int:
    rank, _ = card
    if rank == "A":
        return 14
    if rank == "K":
        return 13
    if rank == "Q":
        return 12
    if rank == "J":
        return 11
    return int(rank)


def _baccarat_value(card: Tuple[str, str]) -> int:
    rank, _ = card
    if rank in {"10", "J", "Q", "K"}:
        return 0
    if rank == "A":
        return 1
    return int(rank)


def _baccarat_total(cards: Sequence[Tuple[str, str]]) -> int:
    return sum(_baccarat_value(card) for card in cards) % 10


def _format_time(value: Any) -> str:
    if not value:
        return "기록 없음"
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.astimezone().strftime("%m/%d %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _ensure_casino_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    profile = user.setdefault("casino_profile", {})
    if not isinstance(profile, dict):
        profile = {}
        user["casino_profile"] = profile

    defaults: Dict[str, Any] = {
        "daily_date": _kst_date(),
        "daily_profit": 0,
        "total_profit": 0,
        "plays": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "current_streak": 0,
        "best_streak": 0,
        "highest_payout": 0,
        "highest_profit": 0,
        "last_game": "없음",
        "last_at": "",
        "games": {},
        "history": [],
    }
    for key, value in defaults.items():
        if isinstance(value, dict):
            profile.setdefault(key, {})
        elif isinstance(value, list):
            profile.setdefault(key, [])
        else:
            profile.setdefault(key, value)

    if profile.get("daily_date") != _kst_date():
        profile["daily_date"] = _kst_date()
        profile["daily_profit"] = 0

    if not isinstance(profile.get("games"), dict):
        profile["games"] = {}
    if not isinstance(profile.get("history"), list):
        profile["history"] = []
    return profile


def _ensure_game_stats(profile: Dict[str, Any], game: str) -> Dict[str, Any]:
    games = profile.setdefault("games", {})
    stats = games.setdefault(game, {})
    if not isinstance(stats, dict):
        stats = {}
        games[game] = stats
    for key, value in {
        "plays": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "profit": 0,
        "best_profit": 0,
        "largest_bet": 0,
    }.items():
        stats.setdefault(key, value)
    return stats


def _record_casino(
    user: Dict[str, Any],
    game: str,
    bet: int,
    delta: int,
    payout: int,
    detail: str,
    world_data: Dict[str, Any],
) -> Dict[str, Any]:
    profile = _ensure_casino_profile(user)
    game_stats = _ensure_game_stats(profile, game)

    profile["plays"] = int(profile.get("plays", 0)) + 1
    profile["total_profit"] = int(profile.get("total_profit", 0)) + int(delta)
    profile["daily_profit"] = int(profile.get("daily_profit", 0)) + int(delta)
    profile["highest_payout"] = max(int(profile.get("highest_payout", 0)), int(payout))
    profile["highest_profit"] = max(int(profile.get("highest_profit", 0)), int(delta))
    profile["last_game"] = game
    profile["last_at"] = _utc_now().isoformat()

    game_stats["plays"] = int(game_stats.get("plays", 0)) + 1
    game_stats["profit"] = int(game_stats.get("profit", 0)) + int(delta)
    game_stats["best_profit"] = max(int(game_stats.get("best_profit", 0)), int(delta))
    game_stats["largest_bet"] = max(int(game_stats.get("largest_bet", 0)), int(bet))

    if delta > 0:
        profile["wins"] = int(profile.get("wins", 0)) + 1
        profile["current_streak"] = int(profile.get("current_streak", 0)) + 1
        profile["best_streak"] = max(int(profile.get("best_streak", 0)), int(profile["current_streak"]))
        game_stats["wins"] = int(game_stats.get("wins", 0)) + 1
        outcome = "승리"
    elif delta < 0:
        profile["losses"] = int(profile.get("losses", 0)) + 1
        profile["current_streak"] = 0
        game_stats["losses"] = int(game_stats.get("losses", 0)) + 1
        outcome = "패배"
    else:
        profile["draws"] = int(profile.get("draws", 0)) + 1
        game_stats["draws"] = int(game_stats.get("draws", 0)) + 1
        outcome = "무승부"

    history = profile.setdefault("history", [])
    history.append(
        {
            "time": profile["last_at"],
            "game": game,
            "bet": int(bet),
            "delta": int(delta),
            "payout": int(payout),
            "balance": casino_chips(user),
            "outcome": outcome,
            "detail": detail,
        }
    )
    del history[:-CASINO_HISTORY_LIMIT]
    record_black_casino_game(user, world_data, game, bet, delta, payout, detail)
    return profile


def _mark_play(user: Dict[str, Any], progress_quest: Optional[Callable[[Dict[str, Any], str], None]]) -> None:
    stats = user.setdefault("stats", {})
    stats["gambles"] = int(stats.get("gambles", 0)) + 1
    if progress_quest:
        progress_quest(user, "도박 참여")


def _add_positive_earnings(user: Dict[str, Any], delta: int) -> None:
    if delta <= 0:
        return
    stats = user.setdefault("stats", {})
    stats["casino_chips_earned"] = int(stats.get("casino_chips_earned", 0)) + int(delta)


def _remaining_loss_room(profile: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> int:
    daily_profit = int(profile.get("daily_profit", 0))
    limit = CASINO_DAILY_LOSS_LIMIT + (daily_loss_bonus(user) if user is not None else 0)
    return max(0, limit + min(0, daily_profit))


def _apply_loss_protection(user: Dict[str, Any], delta: int, detail: str) -> Tuple[int, str]:
    adjusted, protected = apply_loss_shield(user, delta)
    if protected > 0:
        add_casino_chips(user, protected)
        detail = f"{detail}\n🛡️ 손실 보호권이 발동해 **{protected:,}칩**을 보호했습니다."
    return adjusted, detail


async def _validate_casino_bet(ctx: commands.Context, user: Dict[str, Any], bet: int) -> bool:
    try:
        bet = int(bet)
    except (TypeError, ValueError):
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 배팅 금액은 숫자로 입력해야 합니다.")
        return False

    if bet < GAMBLE_MIN_BET or bet > GAMBLE_MAX_BET:
        ctx.command.reset_cooldown(ctx)
        await ctx.send(
            f"⚠️ 카지노 배팅은 최소 **{GAMBLE_MIN_BET:,}**부터 "
            f"최대 **{GAMBLE_MAX_BET:,} 칩**까지 가능합니다."
        )
        return False

    balance = casino_chips(user)
    if balance < bet:
        ctx.command.reset_cooldown(ctx)
        await ctx.send(f"⚠️ 칩이 부족합니다. 보유 **{balance:,}** · 필요 **{bet:,} 칩**")
        return False

    profile = _ensure_casino_profile(user)
    loss_limit = CASINO_DAILY_LOSS_LIMIT + daily_loss_bonus(user)
    if int(profile.get("daily_profit", 0)) <= -loss_limit:
        ctx.command.reset_cooldown(ctx)
        await ctx.send(
            "🛡️ **오늘의 카지노 손실 보호가 발동했습니다.**\n"
            f"하루 누적 손실이 **-{loss_limit:,} 칩**에 도달해 "
            "자정까지 추가 카지노 배팅이 제한됩니다.\n"
            "카지노 칩은 마이너스가 되지 않으며, 일반 식량 빚은 `!파산신청`으로 정리할 수 있습니다."
        )
        return False
    return True


def _result_embed(
    ctx: commands.Context,
    title: str,
    description: str,
    color: discord.Color,
    user: Dict[str, Any],
    before: int,
    delta: int,
    bet: int,
) -> Tuple[discord.Embed, Optional[discord.File]]:
    profile = _ensure_casino_profile(user)
    achievement_note = pending_achievement_text(user)
    embed = discord.Embed(title=title, description=description + achievement_note, color=color)
    embed.add_field(name="🎟️ 배팅", value=f"**{bet:,} 칩**", inline=True)
    embed.add_field(
        name="📈 결과",
        value=f"**{_signed(delta)} 칩**",
        inline=True,
    )
    embed.add_field(name="💰 현재 잔액", value=f"**{casino_chips(user):,} 칩**", inline=True)
    embed.add_field(
        name="📅 오늘 카지노 손익",
        value=f"**{_signed(int(profile.get('daily_profit', 0)))} 칩**",
        inline=True,
    )
    embed.add_field(
        name="🔥 연승",
        value=f"현재 **{int(profile.get('current_streak', 0))}연승** · 최고 **{int(profile.get('best_streak', 0))}연승**",
        inline=True,
    )
    embed.add_field(
        name="🛡️ 손실 보호",
        value=f"남은 한도 **{_remaining_loss_room(profile, user):,} 칩**",
        inline=True,
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.set_footer(text=f"게임 시작 전 잔액 {before:,} · 인게임 칩 전용 · 현금 환전 불가")
    visual = apply_casino_visual(embed, title, description, delta, bet)
    return embed, visual


def _casino_lobby_embed(ctx: commands.Context, user: Dict[str, Any], world_data: Dict[str, Any]) -> discord.Embed:
    profile = _ensure_casino_profile(user)
    plays = int(profile.get("plays", 0))
    wins = int(profile.get("wins", 0))
    win_rate = (wins / plays * 100.0) if plays else 0.0
    embed = discord.Embed(
        title="🎰 ABADDON 폐허 카지노",
        description=(
            "무너진 도시 아래에서 돌아가는 비밀 카지노입니다.\n"
            "모든 게임은 **아바돈 내부 칩**만 사용하며 실제 현금과 교환되지 않습니다."
        ),
        color=discord.Color.purple(),
    )
    account = ensure_black_casino_account(user)
    world = ensure_black_casino_world(world_data)
    tier, _threshold, tier_emoji, points, _next = vip_info(user)
    embed.add_field(name="🪙 카지노 칩", value=f"**{casino_chips(user):,}칩**", inline=True)
    embed.add_field(name="🥫 보유 식량", value=f"**{int(user.get('balance', 0)):,}개**", inline=True)
    embed.add_field(name="🏆 VIP", value=f"{tier_emoji} **{tier}** · {points:,}P", inline=True)
    embed.add_field(name="📅 오늘 손익", value=f"**{_signed(int(profile.get('daily_profit', 0)))}칩**", inline=True)
    embed.add_field(name="📊 누적 손익", value=f"**{_signed(int(profile.get('total_profit', 0)))}칩**", inline=True)
    embed.add_field(name="💎 전 서버 잭팟", value=f"**{int(world.get('jackpot', 0)):,}칩**", inline=True)
    embed.add_field(name="🎮 카지노 전적", value=f"{plays}판 · {wins}승 · 승률 {win_rate:.1f}%", inline=True)
    embed.add_field(name="🔥 최고 연승", value=f"**{int(profile.get('best_streak', 0))}연승**", inline=True)
    embed.add_field(name="🏆 최고 단일 수익", value=f"**{int(profile.get('highest_profit', 0)):,}**", inline=True)
    embed.add_field(
        name="🃏 테이블 게임",
        value=(
            "`/카지노 블랙잭` · `!블랙잭 금액`\n"
            "`/카지노 하이로우` · `!하이로우 금액`\n"
            "`/카지노 바카라` · `!바카라 선택 금액`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎰 즉시 결과 게임",
        value=(
            "`/카지노 슬롯` · `!슬롯 금액`\n"
            "`/카지노 다이스` · `!다이스 홀|짝|1~6 금액`\n"
            "기존 게임: `!룰렛`, `!주파수`, `!탐색 왼쪽 금액`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🌌 BLACK CASINO V4.0",
        value=(
            "`/카지노 환전` · `/카지노 vip` · `/카지노 잭팟` · `/카지노 미션`\n"
            "`/카지노 상점` · `/카지노 럭키휠` · `/카지노 코인플립` · `/카지노 올인`\n"
            f"🎟️ 이용권 {int(account.get('tickets', 0))}장 · 🍀 행운 {int(account.get('luck', 0))}/100"
        ),
        inline=False,
    )
    embed.add_field(
        name="📒 기록과 안내",
        value=(
            "`/카지노 잔액` · `/카지노 기록` · `/카지노 랭킹` · `/카지노 도움말`\n"
            f"배팅 범위 **{GAMBLE_MIN_BET:,} ~ {GAMBLE_MAX_BET:,} 칩** · "
            f"하루 손실 보호 **{CASINO_DAILY_LOSS_LIMIT:,} 칩**"
        ),
        inline=False,
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.set_footer(text="칩 환전: /카지노 환전 · NPC 딜러 4명 · 게임별 기본 쿨타임 8초")
    return embed


def _disable_view(view: discord.ui.View) -> None:
    for child in view.children:
        if hasattr(child, "disabled"):
            child.disabled = True


# ---------------------------------------------------------
# 등록
# ---------------------------------------------------------
def register_v39_commands(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    user_data: Dict[str, Dict[str, Any]],
    world_data: Dict[str, Any],
    progress_quest: Optional[Callable[[Dict[str, Any], str], None]] = None,
) -> None:
    """V3.9 통합 카지노 로비, 블랙잭, 하이로우, 슬롯, 다이스, 바카라를 등록합니다."""

    ensure_black_casino_world(world_data)
    active_sessions: Set[int] = set()

    async def begin_interactive(ctx: commands.Context, user: Dict[str, Any], bet: int) -> bool:
        ensure_black_casino_account(user)
        if ctx.author.id in active_sessions:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 이미 진행 중인 카지노 게임이 있습니다. 현재 게임을 먼저 끝내세요.")
            return False
        if not await _validate_casino_bet(ctx, user, bet):
            return False
        active_sessions.add(ctx.author.id)
        return True

    def end_interactive(user_id: int) -> None:
        active_sessions.discard(user_id)

    async def show_lobby(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        embed = _casino_lobby_embed(ctx, user, world_data)
        # v6.4.1 텍스트 우선 정책: 카지노 로비 이미지는 사용하지 않습니다.
        await ctx.send(embed=embed)

    async def show_balance(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        profile = _ensure_casino_profile(user)
        plays = int(profile.get("plays", 0))
        wins = int(profile.get("wins", 0))
        losses = int(profile.get("losses", 0))
        draws = int(profile.get("draws", 0))
        win_rate = wins / plays * 100 if plays else 0.0
        embed = discord.Embed(title="💳 카지노 자금 현황", color=discord.Color.gold())
        embed.add_field(name="카지노 칩", value=f"**{casino_chips(user):,}칩**", inline=True)
        embed.add_field(name="보유 식량", value=f"**{int(user.get('balance', 0)):,}개**", inline=True)
        embed.add_field(name="오늘 카지노 손익", value=f"**{_signed(int(profile.get('daily_profit', 0)))}**", inline=True)
        embed.add_field(name="누적 카지노 손익", value=f"**{_signed(int(profile.get('total_profit', 0)))}**", inline=True)
        embed.add_field(name="카지노 전적", value=f"{plays}전 {wins}승 {losses}패 {draws}무", inline=True)
        embed.add_field(name="승률", value=f"**{win_rate:.1f}%**", inline=True)
        embed.add_field(name="현재/최고 연승", value=f"{profile.get('current_streak', 0)} / {profile.get('best_streak', 0)}", inline=True)
        embed.add_field(name="최고 지급액", value=f"**{int(profile.get('highest_payout', 0)):,}**", inline=True)
        embed.add_field(name="최고 단일 순이익", value=f"**{int(profile.get('highest_profit', 0)):,}**", inline=True)
        tier, _, emoji, _, _ = vip_info(user)
        jackpot = int(ensure_black_casino_world(world_data).get("jackpot", 0))
        embed.add_field(name="VIP / 전 서버 잭팟", value=f"{emoji} **{tier}** · 💎 **{jackpot:,}칩**", inline=True)
        embed.add_field(name="오늘 손실 보호 여유", value=f"**{_remaining_loss_room(profile, user):,} 칩**", inline=False)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed, file=visual) if visual else await ctx.send(embed=embed)

    async def show_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        profile = _ensure_casino_profile(user)
        history = list(profile.get("history", []))[-10:]
        if not history:
            await ctx.send("📭 아직 카지노 이용 기록이 없습니다.")
            return
        lines = []
        for item in reversed(history):
            delta = int(item.get("delta", 0))
            marker = "🟢" if delta > 0 else ("🔴" if delta < 0 else "⚪")
            lines.append(
                f"{marker} `{_format_time(item.get('time'))}` **{item.get('game', '카지노')}** · "
                f"배팅 {int(item.get('bet', 0)):,} · 결과 **{_signed(delta)}**\n"
                f"└ {item.get('detail', '기록 없음')} · 잔액 {int(item.get('balance', 0)):,}"
            )
        embed = discord.Embed(
            title="📜 최근 카지노 기록",
            description="\n\n".join(lines),
            color=discord.Color.dark_purple(),
        )
        await ctx.send(embed=embed, file=visual) if visual else await ctx.send(embed=embed)

    async def show_ranking(ctx: commands.Context) -> None:
        rankings: List[Tuple[str, int, int, int]] = []
        for uid, candidate in user_data.items():
            if not isinstance(candidate, dict):
                continue
            profile = _ensure_casino_profile(candidate)
            plays = int(profile.get("plays", 0))
            if plays <= 0:
                continue
            rankings.append(
                (
                    str(uid),
                    int(profile.get("total_profit", 0)),
                    plays,
                    int(profile.get("best_streak", 0)),
                )
            )
        rankings.sort(key=lambda row: (row[1], row[3], -row[2]), reverse=True)
        if not rankings:
            await ctx.send("📭 아직 카지노 랭킹에 등록된 생존자가 없습니다.")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, (uid, profit, plays, streak) in enumerate(rankings[:10], start=1):
            mark = medals[index - 1] if index <= 3 else f"`{index}.`"
            lines.append(f"{mark} <@{uid}> · 손익 **{_signed(profit)}** · {plays}판 · 최고 {streak}연승")
        embed = discord.Embed(
            title="🏆 카지노 누적 수익 랭킹",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="카지노 신규 5종 게임의 누적 순이익 기준")
        await ctx.send(embed=embed)

    async def show_help(ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="📖 ABADDON 카지노 이용 안내",
            description=(
                "먼저 `/카지노 환전 구매 금액`으로 식량을 카지노 칩으로 교환합니다.\n"
                f"배팅 범위는 **{GAMBLE_MIN_BET:,} ~ {GAMBLE_MAX_BET:,} 칩**입니다.\n"
                f"카지노 신규 게임은 기본 **{CASINO_GAME_COOLDOWN}초 쿨타임**, "
                f"하루 누적 손실 **-{CASINO_DAILY_LOSS_LIMIT:,}** 도달 시 자정까지 배팅이 제한됩니다."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🃏 블랙잭",
            value=(
                "`!블랙잭 1000` 또는 `/카지노 블랙잭`\n"
                "21에 가까운 쪽이 승리합니다. 버튼으로 히트·스탠드·더블다운을 선택합니다.\n"
                "일반 승리 순이익 1배 · 블랙잭 순이익 1.5배 · 무승부 원금 반환"
            ),
            inline=False,
        )
        embed.add_field(
            name="⬆️ 하이로우",
            value=(
                "`!하이로우 1000` 또는 `/카지노 하이로우`\n"
                "다음 카드가 더 높을지 낮을지 선택합니다. 연속 성공할수록 현금화 배당이 상승합니다.\n"
                "[현금화] 버튼으로 언제든 멈출 수 있으며 최대 8연승에서 자동 정산됩니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="🎰 슬롯",
            value=(
                "`!슬롯 1000` 또는 `/카지노 슬롯`\n"
                "같은 그림 3개는 5~60배 총지급, 같은 그림 2개는 1.5배 총지급입니다.\n"
                "💀 3개는 저주받은 꽝입니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="🎲 다이스",
            value=(
                "`!다이스 홀 1000`, `!다이스 짝 1000`, `!다이스 6 1000`\n"
                "홀짝 적중은 1.9배 총지급, 숫자 정확히 적중은 5.5배 총지급입니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="🎴 바카라",
            value=(
                "`!바카라 플레이어 1000`, `!바카라 뱅커 1000`, `!바카라 타이 1000`\n"
                "플레이어 승 2배, 뱅커 승 1.95배, 타이 적중 9배 총지급입니다.\n"
                "플레이어·뱅커 배팅 중 타이가 나오면 원금을 반환합니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="🌌 카지노 확장 콘텐츠",
            value=(
                "칩 환전 · VIP 6등급 · 전 서버 누적 잭팟 · 일일 미션 · 시즌 랭킹\n"
                "NPC 딜러 · 럭키휠 · 코인플립 · 올인 · 전용 상점 · 업적 125종\n"
                "개인 카지노 · 카지노 꾸미기 · 공개 설정 · 카드 캠페인"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎲 일반 도박 · 카지노와 별도",
            value=(
                "`!룰렛 금액` · `!주파수 금액` · `!탐색 왼쪽|오른쪽 금액`\n"
                "잔액과 전체 도박 통계는 `!도박잔액`, 빚이 생겼다면 `!파산신청`을 사용하세요."
            ),
            inline=False,
        )
        embed.set_footer(text="v18.2.2 안내 동기화 · 실제 화폐 사용 및 현금 환전 기능 없음")
        await ctx.send(embed=embed)

    # -----------------------------------------------------
    # 블랙잭
    # -----------------------------------------------------
    class BlackjackView(discord.ui.View):
        def __init__(
            self,
            ctx: commands.Context,
            user: Dict[str, Any],
            bet: int,
            deck: List[Tuple[str, str]],
            player: List[Tuple[str, str]],
            dealer: List[Tuple[str, str]],
            before: int,
        ) -> None:
            super().__init__(timeout=CASINO_INTERACTIVE_TIMEOUT)
            self.ctx = ctx
            self.user = user
            self.base_bet = bet
            self.total_bet = bet
            self.deck = deck
            self.player = player
            self.dealer = dealer
            self.before = before
            self.message: Optional[discord.Message] = None
            self.finished = False
            self.doubled = False

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("❌ 이 테이블의 선택권은 게임을 시작한 생존자에게만 있습니다.", ephemeral=True)
                return False
            return True

        def table_embed(self, reveal_dealer: bool = False, note: str = "카드를 선택하세요.") -> discord.Embed:
            player_value = _blackjack_value(self.player)
            dealer_value = _blackjack_value(self.dealer) if reveal_dealer else "?"
            embed = discord.Embed(title="🃏 폐허 블랙잭", description=note, color=discord.Color.dark_teal())
            embed.add_field(
                name=f"👤 {self.ctx.author.display_name} · {player_value}",
                value=_hand_text(self.player),
                inline=False,
            )
            embed.add_field(
                name=f"🎩 딜러 · {dealer_value}",
                value=_hand_text(self.dealer, hide_second=not reveal_dealer),
                inline=False,
            )
            embed.add_field(name="현재 총배팅", value=f"**{self.total_bet:,} 칩**", inline=True)
            embed.add_field(name="남은 잔액", value=f"**{casino_chips(self.user):,} 칩**", inline=True)
            embed.set_footer(text="[히트] 카드 추가 · [스탠드] 승부 · [더블다운] 배팅 2배 후 한 장")
            return embed

        async def finalize(self, result: str, detail: str, payout: int, interaction: Optional[discord.Interaction] = None) -> None:
            if self.finished:
                return
            self.finished = True
            ensure_black_casino_account(self.user)["chips"] = casino_chips(self.user) + int(payout)
            after = casino_chips(self.user)
            delta = after - self.before
            delta, detail = _apply_loss_protection(self.user, delta, detail)
            bonus, note = pet_casino_adjustment(self.user, "블랙잭", delta)
            if bonus:
                add_casino_chips(self.user, bonus)
                delta += bonus
                detail += note
            after = casino_chips(self.user)
            _add_positive_earnings(self.user, delta)
            _record_casino(self.user, "블랙잭", self.total_bet, delta, payout, detail, world_data)
            save_data()
            _disable_view(self)
            color = discord.Color.green() if delta > 0 else (discord.Color.red() if delta < 0 else discord.Color.light_grey())
            embed, visual = _result_embed(
                self.ctx,
                f"🃏 블랙잭 {result}",
                (
                    f"👤 {_hand_text(self.player)} = **{_blackjack_value(self.player)}**\n"
                    f"🎩 {_hand_text(self.dealer)} = **{_blackjack_value(self.dealer)}**\n\n{detail}\n\n{dealer_line('블랙잭')}"
                ),
                color,
                self.user,
                self.before,
                delta,
                self.total_bet,
            )
            try:
                if interaction and not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=self, attachments=[visual] if visual else [])
                elif self.message:
                    await self.message.edit(embed=embed, view=self, attachments=[visual] if visual else [])
            finally:
                end_interactive(self.ctx.author.id)
                self.stop()
            reactions: Iterable[str]
            if delta > 0:
                reactions = ("🃏", "🎉", "💰", "🔥")
            elif delta < 0:
                reactions = ("💀", "😭", "📉", "🃏")
            else:
                reactions = ("🤝", "😮", "🃏")
            await _safe_reactions(self.message, reactions)

        async def dealer_play_and_finish(self, interaction: Optional[discord.Interaction] = None, timeout_note: str = "") -> None:
            while _blackjack_value(self.dealer) < 17:
                self.dealer.append(self.deck.pop())
            player_value = _blackjack_value(self.player)
            dealer_value = _blackjack_value(self.dealer)
            prefix = f"{timeout_note}\n" if timeout_note else ""
            if player_value > 21:
                await self.finalize("패배", prefix + "플레이어가 21을 초과했습니다.", 0, interaction)
            elif dealer_value > 21:
                await self.finalize("승리", prefix + "딜러가 21을 초과했습니다!", self.total_bet * 2, interaction)
            elif player_value > dealer_value:
                await self.finalize("승리", prefix + "딜러보다 21에 더 가까웠습니다!", self.total_bet * 2, interaction)
            elif player_value < dealer_value:
                await self.finalize("패배", prefix + "딜러의 패가 더 높았습니다.", 0, interaction)
            else:
                await self.finalize("무승부", prefix + "동점으로 원금을 돌려받았습니다.", self.total_bet, interaction)

        @discord.ui.button(label="히트", style=discord.ButtonStyle.primary, emoji="➕")
        async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            self.player.append(self.deck.pop())
            if _blackjack_value(self.player) >= 21:
                await self.dealer_play_and_finish(interaction)
                return
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.label == "더블다운":
                    child.disabled = True
            await interaction.response.edit_message(embed=self.table_embed(note="🫀 새 카드를 받았습니다. 더 받을지 결정하세요."), view=self)

        @discord.ui.button(label="스탠드", style=discord.ButtonStyle.success, emoji="✋")
        async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await self.dealer_play_and_finish(interaction)

        @discord.ui.button(label="더블다운", style=discord.ButtonStyle.danger, emoji="💰")
        async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if self.doubled or len(self.player) != 2:
                await interaction.response.send_message("⚠️ 더블다운은 첫 두 장에서 한 번만 가능합니다.", ephemeral=True)
                return
            if casino_chips(self.user) < self.base_bet:
                await interaction.response.send_message("⚠️ 더블다운에 필요한 추가 칩이 부족합니다.", ephemeral=True)
                return
            self.doubled = True
            ensure_black_casino_account(self.user)["chips"] = casino_chips(self.user) - self.base_bet
            self.total_bet += self.base_bet
            self.player.append(self.deck.pop())
            await self.dealer_play_and_finish(interaction)

        async def on_timeout(self) -> None:
            if self.finished:
                return
            await self.dealer_play_and_finish(timeout_note="⏱️ 선택 시간이 끝나 자동으로 스탠드 처리됐습니다.")

    async def run_blackjack(ctx: commands.Context, bet: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await begin_interactive(ctx, user, bet):
            return
        before = casino_chips(user)
        try:
            ensure_black_casino_account(user)["chips"] = before - int(bet)
            _mark_play(user, progress_quest)
            deck = _new_deck(2)
            player = [deck.pop(), deck.pop()]
            dealer = [deck.pop(), deck.pop()]
            view = BlackjackView(ctx, user, int(bet), deck, player, dealer, before)

            player_blackjack = _blackjack_value(player) == 21
            dealer_blackjack = _blackjack_value(dealer) == 21
            if player_blackjack or dealer_blackjack:
                view.message = await ctx.send(embed=view.table_embed(reveal_dealer=True, note="⚡ 첫 두 장에서 승부가 결정됐습니다!"))
                if player_blackjack and dealer_blackjack:
                    await view.finalize("무승부", "양쪽 모두 블랙잭입니다. 원금을 반환합니다.", int(bet))
                elif player_blackjack:
                    await view.finalize("내추럴 블랙잭!", "블랙잭 3:2 보너스를 획득했습니다.", int(bet * 2.5))
                else:
                    await view.finalize("패배", "딜러가 내추럴 블랙잭을 완성했습니다.", 0)
                return

            view.message = await ctx.send(embed=view.table_embed(note="딜러가 한 장을 뒤집어 둔 채 당신의 선택을 기다립니다..."), view=view)
        except Exception:
            ensure_black_casino_account(user)["chips"] = before
            end_interactive(ctx.author.id)
            raise

    # -----------------------------------------------------
    # 하이로우
    # -----------------------------------------------------
    class HighLowView(discord.ui.View):
        def __init__(
            self,
            ctx: commands.Context,
            user: Dict[str, Any],
            bet: int,
            deck: List[Tuple[str, str]],
            current_card: Tuple[str, str],
            before: int,
        ) -> None:
            super().__init__(timeout=CASINO_INTERACTIVE_TIMEOUT)
            self.ctx = ctx
            self.user = user
            self.bet = bet
            self.deck = deck
            self.current_card = current_card
            self.before = before
            self.streak = 0
            self.message: Optional[discord.Message] = None
            self.finished = False

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("❌ 이 카드의 선택권은 게임을 시작한 생존자에게만 있습니다.", ephemeral=True)
                return False
            return True

        def cashout_amount(self) -> int:
            if self.streak <= 0:
                return self.bet
            multiplier = min(16.0, 1.48 ** self.streak)
            return max(self.bet, int(self.bet * multiplier))

        def table_embed(self, note: str = "다음 카드의 높낮이를 예측하세요.") -> discord.Embed:
            embed = discord.Embed(title="⬆️⬇️ 하이로우", description=note, color=discord.Color.orange())
            embed.add_field(name="현재 카드", value=f"# {_card_text(self.current_card)}", inline=False)
            embed.add_field(name="연속 성공", value=f"**{self.streak}회**", inline=True)
            embed.add_field(name="지금 현금화", value=f"**{self.cashout_amount():,} 칩**", inline=True)
            embed.add_field(name="순이익 예상", value=f"**{_signed(self.cashout_amount() - self.bet)}**", inline=True)
            embed.set_footer(text="A가 가장 높습니다 · 동률 카드는 다시 뽑습니다 · 8연승 자동 현금화")
            return embed

        async def finish(self, result: str, detail: str, payout: int, interaction: Optional[discord.Interaction] = None) -> None:
            if self.finished:
                return
            self.finished = True
            ensure_black_casino_account(self.user)["chips"] = casino_chips(self.user) + payout
            after = casino_chips(self.user)
            delta = after - self.before
            delta, detail = _apply_loss_protection(self.user, delta, detail)
            bonus, note = pet_casino_adjustment(self.user, "하이로우", delta)
            if bonus:
                add_casino_chips(self.user, bonus)
                delta += bonus
                detail += note
            after = casino_chips(self.user)
            _add_positive_earnings(self.user, delta)
            _record_casino(self.user, "하이로우", self.bet, delta, payout, detail, world_data)
            save_data()
            _disable_view(self)
            color = discord.Color.green() if delta > 0 else (discord.Color.red() if delta < 0 else discord.Color.light_grey())
            embed, visual = _result_embed(
                self.ctx,
                f"⬆️⬇️ 하이로우 {result}",
                f"마지막 카드 {_card_text(self.current_card)}\n연속 성공 **{self.streak}회**\n\n{detail}\n\n{dealer_line('하이로우')}",
                color,
                self.user,
                self.before,
                delta,
                self.bet,
            )
            try:
                if interaction and not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=self, attachments=[visual] if visual else [])
                elif self.message:
                    await self.message.edit(embed=embed, view=self, attachments=[visual] if visual else [])
            finally:
                end_interactive(self.ctx.author.id)
                self.stop()
            await _safe_reactions(
                self.message,
                ("📈", "🔥", "💰", "🎉") if delta > 0 else (("💀", "📉", "😭") if delta < 0 else ("🤝", "😮")),
            )

        async def choose(self, interaction: discord.Interaction, higher: bool) -> None:
            previous = self.current_card
            next_card = self.deck.pop()
            while _highlow_value(next_card) == _highlow_value(previous) and self.deck:
                next_card = self.deck.pop()
            correct = _highlow_value(next_card) > _highlow_value(previous) if higher else _highlow_value(next_card) < _highlow_value(previous)
            self.current_card = next_card
            choice_text = "높음" if higher else "낮음"
            if not correct:
                await self.finish(
                    "실패",
                    f"{_card_text(previous)} 다음에 {_card_text(next_card)}가 나왔습니다. **{choice_text}** 예측 실패!",
                    0,
                    interaction,
                )
                return
            self.streak += 1
            if self.streak >= 8:
                await self.finish(
                    "최대 연승 성공",
                    f"{_card_text(previous)} → {_card_text(next_card)} 예측 성공! 8연승으로 자동 현금화합니다.",
                    self.cashout_amount(),
                    interaction,
                )
                return
            await interaction.response.edit_message(
                embed=self.table_embed(note=f"✅ {_card_text(previous)} → {_card_text(next_card)} · **{choice_text} 예측 성공!** 다시 선택하세요."),
                view=self,
            )

        @discord.ui.button(label="더 높다", style=discord.ButtonStyle.success, emoji="⬆️")
        async def higher(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await self.choose(interaction, True)

        @discord.ui.button(label="더 낮다", style=discord.ButtonStyle.primary, emoji="⬇️")
        async def lower(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await self.choose(interaction, False)

        @discord.ui.button(label="현금화", style=discord.ButtonStyle.secondary, emoji="💰")
        async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if self.streak <= 0:
                detail = "첫 예측 전에 멈춰 원금을 돌려받았습니다."
            else:
                detail = f"위험을 멈추고 {self.streak}연승 보상을 현금화했습니다."
            await self.finish("현금화", detail, self.cashout_amount(), interaction)

        async def on_timeout(self) -> None:
            if self.finished:
                return
            await self.finish("시간 종료", "선택 시간이 끝나 현재 배당으로 자동 현금화됐습니다.", self.cashout_amount())

    async def run_highlow(ctx: commands.Context, bet: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await begin_interactive(ctx, user, bet):
            return
        before = casino_chips(user)
        try:
            ensure_black_casino_account(user)["chips"] = before - int(bet)
            _mark_play(user, progress_quest)
            deck = _new_deck(2)
            current = deck.pop()
            view = HighLowView(ctx, user, int(bet), deck, current, before)
            view.message = await ctx.send(
                content="🃏 딜러가 첫 카드를 천천히 뒤집습니다...",
                embed=view.table_embed(),
                view=view,
            )
        except Exception:
            ensure_black_casino_account(user)["chips"] = before
            end_interactive(ctx.author.id)
            raise

    # -----------------------------------------------------
    # 슬롯
    # -----------------------------------------------------
    def draw_slot_symbol(user: Dict[str, Any], guild_id: int = 0) -> str:
        symbols = [item[0] for item in SLOT_SYMBOLS]
        weights = slot_symbol_weights(user, SLOT_SYMBOLS)
        weights, _weather = weather_slot_weights(guild_id, symbols, weights)
        weights = apply_supply_slot_weights(world_data, guild_id, symbols, weights)
        return random.choices(symbols, weights=weights, k=1)[0]

    async def run_slots(ctx: commands.Context, bet: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await _validate_casino_bet(ctx, user, bet):
            return
        before = casino_chips(user)
        ensure_black_casino_account(user)["chips"] = before - int(bet)
        _mark_play(user, progress_quest)
        slot_buffs = consume_slot_buffs(user)
        reels = [draw_slot_symbol(user, ctx.guild.id if ctx.guild else 0) for _ in range(3)]
        suspense = await ctx.send(f"🎰 **[폐허 슬롯머신]** 배팅 **{bet:,} 칩**\n`[ ? | ? | ? ]` 레버를 당깁니다...")
        for index in range(3):
            await asyncio.sleep(0.7)
            shown = [reels[i] if i <= index else "❔" for i in range(3)]
            try:
                await suspense.edit(content=f"🎰 **[폐허 슬롯머신]** 배팅 **{bet:,} 칩**\n`[ {' | '.join(shown)} ]` 릴이 멈추는 중...")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                pass
        await asyncio.sleep(0.5)

        payout = 0
        detail = "모든 릴이 달라 배팅금을 잃었습니다."
        jackpot_amount = 0
        if len(set(reels)) == 1:
            symbol = reels[0]
            multiplier = SLOT_TRIPLE_PAYOUTS[symbol]
            payout = int(bet * multiplier)
            if symbol == "💀":
                detail = "☠️ 저주받은 해골 3개가 일치했습니다. 지급액은 0입니다."
            else:
                detail = f"{symbol} 3개 완전 일치! **{multiplier:g}배 총지급**입니다."
                if symbol == "💠" or (symbol == "7️⃣" and slot_buffs.get("booster")):
                    jackpot_amount = claim_jackpot(user, world_data, ctx.author.id)
                    payout += jackpot_amount
                    detail += f"\n💎 **전 서버 누적 잭팟 {jackpot_amount:,}칩 당첨!**"
        elif len(set(reels)) == 2:
            payout = int(bet * 1.35)
            detail = "같은 그림 2개가 일치해 **1.35배 총지급**을 받았습니다."
        if slot_buffs.get("charm"):
            detail += "\n🍀 행운의 부적 효과가 적용됐습니다."
        if slot_buffs.get("booster") and jackpot_amount <= 0:
            detail += "\n💎 잭팟 부스터를 사용했지만 7️⃣ 3개가 나오지 않았습니다."

        ensure_black_casino_account(user)["chips"] = casino_chips(user) + payout
        delta = casino_chips(user) - before
        delta, detail = _apply_loss_protection(user, delta, detail)
        bonus, note = pet_casino_adjustment(user, "슬롯머신", delta)
        if bonus:
            add_casino_chips(user, bonus)
            delta += bonus
            detail += note
        _add_positive_earnings(user, delta)
        _record_casino(user, "슬롯머신", int(bet), delta, payout, detail, world_data)
        save_data()
        color = discord.Color.green() if delta > 0 else discord.Color.red()
        embed, visual = _result_embed(
            ctx,
            "🎰 슬롯 결과",
            f"# [ {' | '.join(reels)} ]\n\n{detail}\n\n{dealer_line('슬롯머신')}",
            color,
            user,
            before,
            delta,
            int(bet),
        )
        try:
            await suspense.edit(content=None, embed=embed, attachments=[visual] if visual else [])
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            await ctx.send(embed=embed)
        await _safe_reactions(
            suspense,
            ("🎰", "🎉", "💰", "🔥") if delta > 0 else ("💀", "😭", "📉", "🍒"),
        )

    # -----------------------------------------------------
    # 다이스
    # -----------------------------------------------------
    def normalize_dice_choice(choice: str) -> Optional[str]:
        text = str(choice).strip().lower()
        aliases = {"홀수": "홀", "odd": "홀", "짝수": "짝", "even": "짝"}
        text = aliases.get(text, text)
        if text in {"홀", "짝"}:
            return text
        if text in {"1", "2", "3", "4", "5", "6"}:
            return text
        return None

    async def run_dice(ctx: commands.Context, choice: str, bet: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        normalized = normalize_dice_choice(choice)
        if normalized is None:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 선택은 `홀`, `짝`, 또는 `1~6` 중 하나여야 합니다. 예: `!다이스 홀 1000`")
            return
        if not await _validate_casino_bet(ctx, user, bet):
            return
        before = casino_chips(user)
        ensure_black_casino_account(user)["chips"] = before - int(bet)
        _mark_play(user, progress_quest)
        suspense = await ctx.send(f"🎲 **다이스 컵을 흔듭니다...**\n선택 **{normalized}** · 배팅 **{bet:,} 칩**")
        for text in ("달그락...", "테이블 위로 컵이 떨어집니다...", "딜러가 컵을 들어 올립니다!"):
            await asyncio.sleep(0.65)
            try:
                await suspense.edit(content=f"🎲 **{text}**\n선택 **{normalized}** · 배팅 **{bet:,} 칩**")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                pass
        roll = random.randint(1, 6)
        die = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][roll - 1]
        payout = 0
        if normalized.isdigit():
            success = int(normalized) == roll
            if success:
                payout = int(bet * 5.2)
                detail = f"정확히 **{roll}**을 맞혀 5.5배 총지급을 받았습니다!"
            else:
                detail = f"주사위는 **{roll}**. 숫자 예측에 실패했습니다."
        else:
            actual = "홀" if roll % 2 else "짝"
            success = normalized == actual
            if success:
                payout = int(bet * 1.85)
                detail = f"주사위는 **{roll} ({actual})**. 1.9배 총지급을 받았습니다!"
            else:
                detail = f"주사위는 **{roll} ({actual})**. 홀짝 예측에 실패했습니다."
        ensure_black_casino_account(user)["chips"] = casino_chips(user) + payout
        delta = casino_chips(user) - before
        delta, detail = _apply_loss_protection(user, delta, detail)
        bonus, note = pet_casino_adjustment(user, "다이스", delta)
        if bonus:
            add_casino_chips(user, bonus)
            delta += bonus
            detail += note
        _add_positive_earnings(user, delta)
        _record_casino(user, "다이스", int(bet), delta, payout, detail, world_data)
        save_data()
        embed, visual = _result_embed(
            ctx,
            f"🎲 다이스 결과 {die}",
            detail + f"\n\n{dealer_line('다이스')}",
            discord.Color.green() if delta > 0 else discord.Color.red(),
            user,
            before,
            delta,
            int(bet),
        )
        try:
            await suspense.edit(content=None, embed=embed, attachments=[visual] if visual else [])
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            await ctx.send(embed=embed)
        await _safe_reactions(suspense, ("🎲", "🎯", "🎉", "💰") if success else ("🎲", "😭", "❌", "📉"))

    # -----------------------------------------------------
    # 바카라
    # -----------------------------------------------------
    def normalize_baccarat_choice(choice: str) -> Optional[str]:
        text = str(choice).strip().lower()
        aliases = {
            "p": "플레이어",
            "player": "플레이어",
            "플": "플레이어",
            "b": "뱅커",
            "banker": "뱅커",
            "뱅": "뱅커",
            "t": "타이",
            "tie": "타이",
            "무승부": "타이",
        }
        text = aliases.get(text, text)
        return text if text in {"플레이어", "뱅커", "타이"} else None

    def deal_baccarat(deck: List[Tuple[str, str]]) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        player = [deck.pop(), deck.pop()]
        banker = [deck.pop(), deck.pop()]
        p_total = _baccarat_total(player)
        b_total = _baccarat_total(banker)
        if p_total in {8, 9} or b_total in {8, 9}:
            return player, banker

        player_third: Optional[int] = None
        if p_total <= 5:
            card = deck.pop()
            player.append(card)
            player_third = _baccarat_value(card)

        b_total = _baccarat_total(banker)
        banker_draw = False
        if player_third is None:
            banker_draw = b_total <= 5
        elif b_total <= 2:
            banker_draw = True
        elif b_total == 3:
            banker_draw = player_third != 8
        elif b_total == 4:
            banker_draw = 2 <= player_third <= 7
        elif b_total == 5:
            banker_draw = 4 <= player_third <= 7
        elif b_total == 6:
            banker_draw = 6 <= player_third <= 7
        if banker_draw:
            banker.append(deck.pop())
        return player, banker

    async def run_baccarat(ctx: commands.Context, choice: str, bet: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        normalized = normalize_baccarat_choice(choice)
        if normalized is None:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 선택은 `플레이어`, `뱅커`, `타이` 중 하나입니다. 예: `!바카라 뱅커 1000`")
            return
        if not await _validate_casino_bet(ctx, user, bet):
            return
        before = casino_chips(user)
        ensure_black_casino_account(user)["chips"] = before - int(bet)
        _mark_play(user, progress_quest)
        suspense = await ctx.send(
            f"🎴 **[폐허 바카라]**\n선택 **{normalized}** · 배팅 **{bet:,} 칩**\n딜러가 카드를 배분합니다..."
        )
        await asyncio.sleep(0.8)
        try:
            await suspense.edit(content="🎴 플레이어의 패가 공개됩니다... 딜러가 뱅커 쪽 카드를 확인합니다...")
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass
        await asyncio.sleep(0.8)
        deck = _new_deck(8)
        player, banker = deal_baccarat(deck)
        p_total = _baccarat_total(player)
        b_total = _baccarat_total(banker)
        if p_total > b_total:
            actual = "플레이어"
        elif b_total > p_total:
            actual = "뱅커"
        else:
            actual = "타이"

        payout = 0
        if actual == "타이" and normalized in {"플레이어", "뱅커"}:
            payout = int(bet)
            detail = "타이가 발생해 플레이어·뱅커 배팅 원금을 반환합니다."
        elif normalized == actual:
            if actual == "플레이어":
                payout = int(bet * 2.0)
                detail = "플레이어 승 적중! 2배 총지급입니다."
            elif actual == "뱅커":
                payout = int(bet + math.floor(bet * 0.95))
                detail = "뱅커 승 적중! 수수료 반영 1.95배 총지급입니다."
            else:
                payout = int(bet * 9.0)
                detail = "타이 적중! 9배 총지급입니다."
        else:
            detail = f"결과는 **{actual}**. 선택이 빗나갔습니다."

        ensure_black_casino_account(user)["chips"] = casino_chips(user) + payout
        delta = casino_chips(user) - before
        delta, detail = _apply_loss_protection(user, delta, detail)
        bonus, note = pet_casino_adjustment(user, "바카라", delta)
        if bonus:
            add_casino_chips(user, bonus)
            delta += bonus
            detail += note
        _add_positive_earnings(user, delta)
        result_detail = (
            f"👤 플레이어 {_hand_text(player)} = **{p_total}**\n"
            f"🎩 뱅커 {_hand_text(banker)} = **{b_total}**\n\n{detail}\n\n{dealer_line('바카라')}"
        )
        _record_casino(user, "바카라", int(bet), delta, payout, f"{actual} · {detail}", world_data)
        save_data()
        color = discord.Color.green() if delta > 0 else (discord.Color.light_grey() if delta == 0 else discord.Color.red())
        embed, visual = _result_embed(ctx, f"🎴 바카라 결과: {actual}", result_detail, color, user, before, delta, int(bet))
        try:
            await suspense.edit(content=None, embed=embed, attachments=[visual] if visual else [])
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            await ctx.send(embed=embed)
        await _safe_reactions(
            suspense,
            ("🎴", "🎉", "💰", "🔥") if delta > 0 else (("🤝", "😮", "🎴") if delta == 0 else ("😭", "📉", "❌", "🎴")),
        )

    # -----------------------------------------------------
    # 카지노 하이브리드 그룹: slash는 /카지노 하위로 묶어 100개 제한 회피
    # -----------------------------------------------------
    @bot.hybrid_group(
        name="카지노",
        aliases=["casino"],
        fallback="로비",
        invoke_without_command=True,
        description="폐허 카지노 로비와 게임 목록을 확인합니다.",
    )
    async def casino_group(ctx: commands.Context) -> None:
        await show_lobby(ctx)

    @casino_group.command(name="블랙잭", description="히트·스탠드·더블다운 버튼으로 진행하는 블랙잭입니다.")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def casino_blackjack(ctx: commands.Context, 배팅액: int) -> None:
        await run_blackjack(ctx, 배팅액)

    @casino_group.command(name="하이로우", description="다음 카드의 높낮이를 맞히고 연승 배당을 현금화합니다.")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def casino_highlow(ctx: commands.Context, 배팅액: int) -> None:
        await run_highlow(ctx, 배팅액)

    @casino_group.command(name="슬롯", description="세 개의 릴을 돌리는 폐허 슬롯머신입니다.")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def casino_slots(ctx: commands.Context, 배팅액: int) -> None:
        await run_slots(ctx, 배팅액)

    @casino_group.command(name="다이스", description="홀짝 또는 정확한 숫자를 예측하는 주사위 게임입니다.")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def casino_dice(ctx: commands.Context, 선택: str, 배팅액: int) -> None:
        await run_dice(ctx, 선택, 배팅액)

    @casino_group.command(name="바카라", description="플레이어·뱅커·타이 중 하나에 배팅합니다.")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def casino_baccarat(ctx: commands.Context, 선택: str, 배팅액: int) -> None:
        await run_baccarat(ctx, 선택, 배팅액)

    async def invoke_existing_gamble(ctx: commands.Context, command_name: str, *args: Any) -> None:
        existing = bot.get_command(command_name)
        if existing is None:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 기존 `{command_name}` 명령어를 찾지 못했습니다.")
            return
        await existing.callback(ctx, *args)

    @casino_group.command(name="룰렛", description="1/6부터 위험도가 증가하는 기존 생존 룰렛을 실행합니다.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def casino_roulette(ctx: commands.Context, 배팅액: int) -> None:
        await invoke_existing_gamble(ctx, "룰렛", 배팅액)

    @casino_group.command(name="주파수", description="세 개의 검은 신호를 맞추는 기존 주파수 슬롯을 실행합니다.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def casino_frequency(ctx: commands.Context, 배팅액: int) -> None:
        await invoke_existing_gamble(ctx, "주파수", 배팅액)

    @casino_group.command(name="탐색", description="왼쪽·오른쪽 폐허 통로를 선택하는 기존 방향 도박입니다.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def casino_explore(ctx: commands.Context, 방향: str, 배팅액: int) -> None:
        await invoke_existing_gamble(ctx, "탐색", 방향, 배팅액)

    @casino_group.command(name="잔액", description="카지노 전적, 실시간 칩, 오늘·누적 손익을 확인합니다.")
    async def casino_balance(ctx: commands.Context) -> None:
        await show_balance(ctx)

    @casino_group.command(name="기록", description="최근 카지노 이용 내역과 결과를 확인합니다.")
    async def casino_history(ctx: commands.Context) -> None:
        await show_history(ctx)

    @casino_group.command(name="랭킹", description="카지노 누적 순이익 상위 생존자를 확인합니다.")
    async def casino_ranking(ctx: commands.Context) -> None:
        await show_ranking(ctx)

    @casino_group.command(name="도움말", description="카지노 게임별 규칙, 배당, 배팅 범위를 확인합니다.")
    async def casino_help(ctx: commands.Context) -> None:
        await show_help(ctx)

    # -----------------------------------------------------
    # 기존 !명령어 사용자용 바로가기(prefix 전용)
    # -----------------------------------------------------
    @bot.command(name="블랙잭")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def blackjack_prefix(ctx: commands.Context, 배팅액: int) -> None:
        await run_blackjack(ctx, 배팅액)

    @bot.command(name="하이로우")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def highlow_prefix(ctx: commands.Context, 배팅액: int) -> None:
        await run_highlow(ctx, 배팅액)

    @bot.command(name="슬롯")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def slots_prefix(ctx: commands.Context, 배팅액: int) -> None:
        await run_slots(ctx, 배팅액)

    @bot.command(name="다이스")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def dice_prefix(ctx: commands.Context, 선택: str, 배팅액: int) -> None:
        await run_dice(ctx, 선택, 배팅액)

    @bot.command(name="바카라")
    @commands.cooldown(1, CASINO_GAME_COOLDOWN, commands.BucketType.user)
    async def baccarat_prefix(ctx: commands.Context, 선택: str, 배팅액: int) -> None:
        await run_baccarat(ctx, 선택, 배팅액)

    @bot.command(name="카지노잔액", aliases=["카지노자금"])
    async def casino_balance_prefix(ctx: commands.Context) -> None:
        await show_balance(ctx)

    @bot.command(name="카지노기록")
    async def casino_history_prefix(ctx: commands.Context) -> None:
        await show_history(ctx)

    @bot.command(name="카지노랭킹")
    async def casino_ranking_prefix(ctx: commands.Context) -> None:
        await show_ranking(ctx)

    @bot.command(name="카지노도움말")
    async def casino_help_prefix(ctx: commands.Context) -> None:
        await show_help(ctx)
