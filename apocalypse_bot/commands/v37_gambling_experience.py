from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands.v635_visuals import apply_casino_visual

from apocalypse_bot.commands.v36_gambling_market import (
    KST,
    MARKET_ASSETS,
    _format_change,
    _parse_time,
    _price_change,
    _record_trade,
    ensure_market,
    ensure_user_market,
    update_market,
)


GAMBLE_MIN_BET = 100
GAMBLE_MAX_BET = 10_000_000
GAMBLE_HISTORY_LIMIT = 20

# 생존 룰렛: 탄환 확률이 올라갈수록 생존 배당과 피격 손실이 함께 상승합니다.
# key = 남은 약실 수(탄환 확률 1/key)
ROULETTE_RISK_TABLE: Dict[int, Dict[str, Any]] = {
    6: {"reward": 2, "losses": (1, 1, 1, 2)},
    5: {"reward": 3, "losses": (2, 2, 3)},
    4: {"reward": 4, "losses": (3, 4, 5)},
    3: {"reward": 6, "losses": (5, 6, 7)},
    2: {"reward": 10, "losses": (7, 8, 9, 10)},
    1: {"reward": 0, "losses": (10,)},
}

WORK_DAILY_LIMIT = 40
WORK_COOLDOWN_SECONDS = 8

COIN_DAILY_LIMIT = 30
COIN_COOLDOWN_SECONDS = 60
COIN_FAILURE_COST_MIN = 60
COIN_FAILURE_COST_MAX = 350
# 전체 확률 기준: 실패 35.0% / 일반 48.0% / 희귀 12.0% / 영웅 3.8% / 전설 1.1% / 신화 0.1%
COIN_DRAW_WEIGHTS: Sequence[Tuple[str, int]] = (
    ("실패", 350),
    ("보급권", 480),
    ("군수권", 120),
    ("혈청", 38),
    ("유물", 11),
    ("코어", 1),
)

# Render Environment에 URL을 넣으면 알바 결과 임베드 하단에 큰 이미지를 표시합니다.
# URL이 없어도 사용자 프로필 사진은 우측 썸네일로 자동 표시됩니다.
WORK_RESULT_IMAGE_URLS = {
    "failure": os.getenv("WORK_FAIL_IMAGE_URL", "").strip(),
    "success": os.getenv("WORK_SUCCESS_IMAGE_URL", "").strip(),
    "jackpot": os.getenv("WORK_JACKPOT_IMAGE_URL", "").strip(),
}

MARKET_ALERT_THRESHOLD = 0.08
MARKET_ALERT_COOLDOWN_SECONDS = 5 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _kst_date() -> str:
    return _utc_now().astimezone(KST).strftime("%Y-%m-%d")


def _signed(value: int) -> str:
    return f"+{value:,}" if value >= 0 else f"{value:,}"


def _balance_line(before: int, after: int) -> str:
    delta = after - before
    return f"💰 잔액 **{after:,} 식량** ({_signed(delta)})"


async def _safe_reactions(message: Optional[discord.Message], emojis: Iterable[str]) -> None:
    if message is None:
        return
    for emoji in emojis:
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return


async def _edit_message(message: discord.Message, content: str) -> None:
    try:
        await message.edit(content=content, embed=None)
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass


async def _edit_embed(message: discord.Message, embed: discord.Embed) -> None:
    try:
        await message.edit(content=None, embed=embed)
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass


def _ensure_gambling_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    profile = user.setdefault("gambling_profile", {})
    if not isinstance(profile, dict):
        profile = {}
        user["gambling_profile"] = profile

    defaults = {
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "total_profit": 0,
        "daily_date": _kst_date(),
        "daily_profit": 0,
        "largest_win": 0,
        "largest_loss": 0,
        "last_game": "없음",
        "last_delta": 0,
        "last_balance": int(user.get("balance", 0)),
        "last_at": "",
        "history": [],
    }
    for key, value in defaults.items():
        profile.setdefault(key, value.copy() if isinstance(value, list) else value)

    if profile.get("daily_date") != _kst_date():
        profile["daily_date"] = _kst_date()
        profile["daily_profit"] = 0

    if not isinstance(profile.get("history"), list):
        profile["history"] = []
    return profile


def _record_gamble(user: Dict[str, Any], game: str, bet: int, delta: int) -> Dict[str, Any]:
    profile = _ensure_gambling_profile(user)
    if delta > 0:
        profile["wins"] = int(profile.get("wins", 0)) + 1
        profile["largest_win"] = max(int(profile.get("largest_win", 0)), delta)
    elif delta < 0:
        profile["losses"] = int(profile.get("losses", 0)) + 1
        profile["largest_loss"] = min(int(profile.get("largest_loss", 0)), delta)
    else:
        profile["draws"] = int(profile.get("draws", 0)) + 1

    profile["total_profit"] = int(profile.get("total_profit", 0)) + delta
    profile["daily_profit"] = int(profile.get("daily_profit", 0)) + delta
    profile["last_game"] = game
    profile["last_delta"] = delta
    profile["last_balance"] = int(user.get("balance", 0))
    profile["last_at"] = _utc_now().isoformat()
    profile["history"].append(
        {
            "time": profile["last_at"],
            "game": game,
            "bet": int(bet),
            "delta": int(delta),
            "balance": int(user.get("balance", 0)),
        }
    )
    del profile["history"][:-GAMBLE_HISTORY_LIMIT]
    return profile


async def _validate_bet(ctx: commands.Context, user: Dict[str, Any], bet: int) -> bool:
    if bet < GAMBLE_MIN_BET or bet > GAMBLE_MAX_BET:
        ctx.command.reset_cooldown(ctx)
        await ctx.send(
            "⚠️ 배팅 금액이 범위를 벗어났습니다.\n"
            f"최소 **{GAMBLE_MIN_BET:,}**부터 최대 **{GAMBLE_MAX_BET:,} 식량**까지 가능합니다."
        )
        return False
    balance = int(user.get("balance", 0))
    if balance < bet:
        ctx.command.reset_cooldown(ctx)
        await ctx.send(f"⚠️ 식량이 부족합니다. 보유: **{balance:,}** · 필요: **{bet:,}**")
        return False
    return True


def _ensure_work_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    work = user.setdefault("part_time_job", {})
    if not isinstance(work, dict):
        work = {}
        user["part_time_job"] = work
    defaults = {
        "date": _kst_date(),
        "attempts": 0,
        "level": 1,
        "exp": 0,
        "total_earned": 0,
        "total_lost": 0,
        "last_work": "",
    }
    for key, value in defaults.items():
        work.setdefault(key, value)
    if work.get("date") != _kst_date():
        work["date"] = _kst_date()
        work["attempts"] = 0
    return work


def _work_required_exp(level: int) -> int:
    return 20 + max(1, level) * 10


def _level_up_work(work: Dict[str, Any]) -> int:
    gained = 0
    while int(work.get("exp", 0)) >= _work_required_exp(int(work.get("level", 1))):
        need = _work_required_exp(int(work.get("level", 1)))
        work["exp"] = int(work.get("exp", 0)) - need
        work["level"] = int(work.get("level", 1)) + 1
        gained += 1
    return gained


def _ensure_coin_profile(account: Dict[str, Any]) -> Dict[str, Any]:
    coin = account.setdefault("coin_draw", {})
    if not isinstance(coin, dict):
        coin = {}
        account["coin_draw"] = coin
    defaults = {
        "date": _kst_date(),
        "attempts": 0,
        "last_claim": "",
        "total_claims": 0,
        "total_attempts": 0,
        "failures": 0,
        "total_failure_cost": 0,
    }
    for key, value in defaults.items():
        coin.setdefault(key, value)
    if coin.get("date") != _kst_date():
        coin["date"] = _kst_date()
        coin["attempts"] = 0
    return coin


def _coin_cooldown_remaining(coin: Dict[str, Any]) -> int:
    last = _parse_time(coin.get("last_claim"))
    if not last:
        return 0
    remaining = int((last + timedelta(seconds=COIN_COOLDOWN_SECONDS) - _utc_now()).total_seconds())
    return max(0, remaining)


def _coin_failure_cost(balance: int) -> int:
    """잔액을 음수로 만들지 않는 코인 스캐너 수리비를 계산합니다."""
    balance = max(0, int(balance))
    if balance <= 0:
        return 0
    high = min(COIN_FAILURE_COST_MAX, max(120, balance // 25 + 100))
    low = min(COIN_FAILURE_COST_MIN, high)
    return min(balance, random.randint(low, high))


def _format_seconds(seconds: int) -> str:
    minutes, second = divmod(max(0, seconds), 60)
    if minutes:
        return f"{minutes}분 {second}초"
    return f"{second}초"


def register_v37_commands(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    progress_quest: Optional[Callable[[Dict[str, Any], str], None]] = None,
) -> None:
    """V3.8 도박 연출, 알바 임베드, 실패 포함 희귀 코인, 잔액 통계, 시세 자동 알림을 등록합니다."""

    # V3.6 이전의 단순 도박 명령어를 더 풍부한 연출 버전으로 교체합니다.
    for command_name in ("탐색", "주파수", "룰렛", "파산신청"):
        bot.remove_command(command_name)

    roulette_locks: Dict[str, asyncio.Lock] = {}
    roulette_states = world_data.setdefault("roulette_state", {})
    if not isinstance(roulette_states, dict):
        roulette_states = {}
        world_data["roulette_state"] = roulette_states

    def roulette_lock(guild_id: str) -> asyncio.Lock:
        return roulette_locks.setdefault(guild_id, asyncio.Lock())

    @bot.hybrid_command(name="탐색", description="왼쪽 또는 오른쪽 폐허 통로에 식량을 배팅합니다.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def gamble_explore(ctx: commands.Context, 방향: str, 배팅액: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        direction = str(방향).strip()
        if direction not in {"왼쪽", "오른쪽"}:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 사용법: `!탐색 왼쪽 {GAMBLE_MIN_BET}` 또는 `/탐색`")
            return
        if not await _validate_bet(ctx, user, 배팅액):
            return

        before = int(user.get("balance", 0))
        visual_send = getattr(bot, "v632_send_visual", None)
        visual_edit = getattr(bot, "v632_edit_visual", None)
        visual_tip = getattr(bot, "v632_tip", lambda _k: "통로의 출구와 함정을 먼저 확인하세요.")
        start_embed = discord.Embed(title="🚪 갈림길 탐색", description=f"{direction} 통로에 **{배팅액:,} 식량**을 걸었습니다. 낡은 철문이 천천히 열립니다...", color=discord.Color.dark_teal())
        start_embed.add_field(name="🧭 선택 통로", value=f"**{direction}**", inline=True)
        start_embed.add_field(name="💰 배팅", value=f"**{배팅액:,} 식량**", inline=True)
        start_embed.add_field(name="💡 TIP", value=visual_tip("exploration"), inline=False)
        suspense = await visual_send(ctx, start_embed, "activities/exploration/encounter") if visual_send else await ctx.send(embed=start_embed)
        await asyncio.sleep(0.8)
        scan_embed = discord.Embed(title="👣 통로 내부 탐색 중", description=f"{direction} 통로 안쪽에서 발소리와 금속 마찰음이 들립니다...", color=discord.Color.orange())
        scan_embed.add_field(name="🔦 진행", value="보급함·매복·와이어 덫 확인", inline=True)
        scan_embed.add_field(name="💡 TIP", value=visual_tip("exploration"), inline=False)
        if visual_edit: await visual_edit(suspense, scan_embed, "activities/exploration/encounter")
        else: await _edit_embed(suspense, scan_embed)
        await asyncio.sleep(0.8)

        user.setdefault("stats", {}).setdefault("gambles", 0)
        user["stats"]["gambles"] += 1
        if progress_quest:
            progress_quest(user, "도박 참여")

        success = random.random() < 0.44
        if success:
            multiplier = random.choice([1, 1, 1, 2, 2])
            reward = 배팅액 * multiplier
            user["balance"] = before + reward
            user["stats"].setdefault("earned", 0)
            user["stats"]["earned"] += reward
            flavor = random.choice(["녹슨 보급함에서 밀봉된 생존 물자를 발견했습니다.","감염체가 이동한 틈에 숨겨진 보급 가방을 회수했습니다.","무너진 벽 뒤의 은닉 장소에서 자원을 찾아냈습니다."])
            title = "✅ 탐색 성공"
        else:
            user["balance"] = before - 배팅액
            reward = -배팅액
            flavor = random.choice(["매복한 감염체에게 보급 가방을 빼앗겼습니다.","와이어 함정이 작동해 배팅 물자를 모두 잃었습니다.","암시장 경비대의 순찰에 걸려 식량을 압수당했습니다."])
            title = "❌ 탐색 실패"

        _record_gamble(user, "갈림길 탐색", 배팅액, reward)
        save_data()
        result_embed = discord.Embed(title=title, description=flavor, color=discord.Color.green() if success else discord.Color.red(), timestamp=_utc_now())
        result_embed.add_field(name="🎒 결과", value=f"**{'획득' if reward >= 0 else '손실'} {abs(reward):,} 식량**", inline=True)
        result_embed.add_field(name="💳 잔액 변화", value=_balance_line(before, int(user['balance'])), inline=True)
        result_embed.add_field(name="💡 TIP", value=visual_tip("exploration"), inline=False)
        if visual_edit: await visual_edit(suspense, result_embed, f"activities/exploration/{'success' if success else 'failure'}")
        else: await _edit_embed(suspense, result_embed)
        await _safe_reactions(suspense, ("🎉", "✅") if success else ("💀", "❌"))
        maybe_encounter = getattr(bot, "v632_maybe_encounter", None)
        if maybe_encounter:
            await maybe_encounter(ctx, "exploration", user)

    @bot.hybrid_command(name="주파수", description="세 개의 검은 신호 결과에 식량을 배팅합니다.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def black_frequency(ctx: commands.Context, 배팅액: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await _validate_bet(ctx, user, 배팅액):
            return

        before = int(user.get("balance", 0))
        signals = ["🔴", "🟢", "🔵", "⚡", "💀"]
        result = [random.choice(signals) for _ in range(3)]
        suspense = await ctx.send(
            f"📻 **[검은 주파수 슬롯]**\n배팅 **{배팅액:,} 식량**\n"
            "신호를 수신하고 있습니다... `[ ? | ? | ? ]`"
        )
        for index in range(3):
            await asyncio.sleep(0.65)
            revealed = [result[i] if i <= index else "?" for i in range(3)]
            await _edit_message(
                suspense,
                f"📻 **[검은 주파수 슬롯]**\n배팅 **{배팅액:,} 식량**\n"
                f"주파수 고정 중... **[ {' | '.join(revealed)} ]**",
            )
        await asyncio.sleep(0.65)

        user.setdefault("stats", {}).setdefault("gambles", 0)
        user["stats"]["gambles"] += 1
        if progress_quest:
            progress_quest(user, "도박 참여")

        if len(set(result)) == 1:
            if result[0] == "💀":
                loss = 배팅액 * 3
                user["balance"] = before - loss
                delta = -loss
                message = f"☠️ **저주받은 신호!** 배팅액의 3배인 **{loss:,} 식량**을 잃었습니다."
                success = False
            else:
                multiplier = random.randint(4, 16)
                gain = 배팅액 * multiplier
                user["balance"] = before + gain
                user["stats"].setdefault("earned", 0)
                user["stats"]["earned"] += gain
                delta = gain
                message = f"📡 **완전 일치 잭팟 {multiplier}배!** **{gain:,} 식량**을 획득했습니다."
                success = True
        elif len(set(result)) == 2:
            gain = int(배팅액 * 0.4)
            user["balance"] = before + gain
            user["stats"].setdefault("earned", 0)
            user["stats"]["earned"] += gain
            delta = gain
            message = f"📻 **부분 일치!** **{gain:,} 식량**을 획득했습니다."
            success = True
            work_outcome = "jackpot"
        else:
            user["balance"] = before - 배팅액
            delta = -배팅액
            message = f"📵 **통신 두절!** **{배팅액:,} 식량**을 잃었습니다."
            success = False

        _record_gamble(user, "검은 주파수", 배팅액, delta)
        save_data()
        result_text = f"📻 **[ {' | '.join(result)} ]**\n{message}\n{_balance_line(before, int(user['balance']))}"
        embed = discord.Embed(
            title="📻 검은 주파수 결과",
            description=result_text,
            color=discord.Color.green() if success else discord.Color.red(),
        )
        visual = apply_casino_visual(embed, "슬롯 검은 주파수", message, delta, 배팅액)
        try:
            await suspense.edit(content=None, embed=embed, attachments=[visual] if visual else [])
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            await ctx.send(embed=embed, file=visual) if visual else await ctx.send(embed=embed)
        await _safe_reactions(suspense, ("📡", "🎉") if success else ("💀", "📵"))

    @bot.hybrid_command(name="룰렛", description="남은 약실에 따라 위험도가 올라가는 생존 룰렛입니다.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def survival_roulette(ctx: commands.Context, 배팅액: int) -> None:
        if not await check_registered(ctx):
            return
        if ctx.guild is None:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 생존 룰렛은 서버 채널에서만 사용할 수 있습니다.")
            return
        user = get_user(ctx.author.id)
        if not await _validate_bet(ctx, user, 배팅액):
            return

        guild_id = str(ctx.guild.id)
        async with roulette_lock(guild_id):
            state = roulette_states.setdefault(guild_id, {"bullet": random.randint(1, 6), "chamber": 1})
            chamber = max(1, min(6, int(state.get("chamber", 1))))
            bullet = max(chamber, min(6, int(state.get("bullet", random.randint(chamber, 6)))))
            state["chamber"] = chamber
            state["bullet"] = bullet
            denominator = 7 - chamber
            risk = ROULETTE_RISK_TABLE.get(denominator, ROULETTE_RISK_TABLE[1])
            reward_multiplier = int(risk["reward"])
            possible_losses = tuple(int(v) for v in risk["losses"])
            min_loss_multiplier = min(possible_losses)
            max_loss_multiplier = max(possible_losses)
            before = int(user.get("balance", 0))

            suspense = await ctx.send(
                f"🔫 **[생존 룰렛]**\n배팅 **{배팅액:,} 식량**\n"
                f"현재 탄환 확률 **1/{denominator}**\n"
                f"생존 배당 **{reward_multiplier}배** · 피격 손실 **{min_loss_multiplier}~{max_loss_multiplier}배**\n"
                "실린더가 천천히 회전합니다..."
            )
            await asyncio.sleep(0.9)
            await _edit_message(
                suspense,
                f"🔫 **현재 탄환 확률 1/{denominator}**\n"
                f"생존 {reward_multiplier}배 · 피격 {min_loss_multiplier}~{max_loss_multiplier}배 손실\n"
                "실린더가 멈췄습니다. 방아쇠에 손가락을 올립니다...",
            )
            await asyncio.sleep(0.9)
            await _edit_message(suspense, f"😰 **1/{denominator}의 확률...**\n방아쇠를 당깁니다.\n\n`철컥—` 또는 `탕!`")
            await asyncio.sleep(0.75)

            user.setdefault("stats", {}).setdefault("gambles", 0)
            user["stats"]["gambles"] += 1
            if progress_quest:
                progress_quest(user, "도박 참여")

            if chamber == bullet:
                loss_multiplier = random.choice(possible_losses)
                loss = 배팅액 * loss_multiplier
                # 보유액보다 손실이 크면 일반 식량 잔액이 그대로 마이너스가 됩니다.
                user["balance"] = before - loss
                delta = -loss
                del roulette_states[guild_id]
                debt_text = (
                    f"\n⚠️ 보유액을 초과해 **{abs(int(user['balance'])):,} 식량 빚**이 생겼습니다. `!파산신청` 가능"
                    if int(user["balance"]) < 0 else ""
                )
                text = (
                    f"💥 **탕! 탄환이 발사됐습니다.**\n"
                    f"위험 단계에 따라 **{loss_multiplier}배**, 총 **{loss:,} 식량**을 잃었습니다.{debt_text}\n"
                    "실린더가 교체되어 다음 도전은 다시 **1/6**부터 시작합니다."
                )
                success = False
            else:
                multiplier = reward_multiplier
                gain = 배팅액 * multiplier
                user["balance"] = before + gain
                user["stats"].setdefault("earned", 0)
                user["stats"]["earned"] += gain
                delta = gain
                state["chamber"] = chamber + 1
                next_denominator = 7 - int(state["chamber"])
                next_risk = ROULETTE_RISK_TABLE.get(next_denominator, ROULETTE_RISK_TABLE[1])
                text = (
                    f"💨 **철컥! 빈 약실입니다. 생존했습니다.**\n"
                    f"현재 위험도 고정 배당 **{multiplier}배**, **{gain:,} 식량** 획득\n"
                    f"다음 탄환 확률 **1/{next_denominator}** · 생존 {int(next_risk['reward'])}배 · "
                    f"피격 최대 {max(int(v) for v in next_risk['losses'])}배 손실"
                )
                success = True

            _record_gamble(user, "생존 룰렛", 배팅액, delta)
            save_data()
            result_text = f"{text}\n{_balance_line(before, int(user['balance']))}"
            embed = discord.Embed(
                title="🔫 생존 룰렛 결과",
                description=result_text,
                color=discord.Color.green() if success else discord.Color.red(),
            )
            visual = apply_casino_visual(embed, "룰렛 생존 결과", text, delta, 배팅액)
            try:
                await suspense.edit(content=None, embed=embed, attachments=[visual] if visual else [])
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                await ctx.send(embed=embed, file=visual) if visual else await ctx.send(embed=embed)
            await _safe_reactions(suspense, ("😮", "✅") if success else ("💥", "💀"))

    @bot.hybrid_command(name="파산신청", description="식량이 마이너스일 때 1시간마다 빚 탕감을 신청합니다.")
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def bankruptcy(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if int(user.get("balance", 0)) >= 0:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 빚이 없어 파산 신청이 불가능합니다.")
            return

        before = int(user["balance"])
        debt = abs(before)
        rate = random.randint(10, 70)
        forgiven = int(debt * rate / 100)
        user["balance"] = min(0, before + forgiven)
        save_data()
        message = await ctx.send(
            f"⚖️ **파산 심사 결과**\n빚의 **{rate}%**인 **{forgiven:,} 식량**이 탕감됐습니다.\n"
            f"남은 빚 **{abs(min(0, int(user['balance']))):,} 식량**"
        )
        await _safe_reactions(message, ("⚖️", "🙏"))

    @bot.hybrid_command(name="도박잔액", aliases=["도박자금", "도박통계"], description="현재 식량과 최근·오늘·누적 도박 손익을 확인합니다.")
    async def gambling_balance(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        profile = _ensure_gambling_profile(user)
        last_delta = int(profile.get("last_delta", 0))
        total_games = int(profile.get("wins", 0)) + int(profile.get("losses", 0)) + int(profile.get("draws", 0))
        last_time = _parse_time(profile.get("last_at"))
        last_text = last_time.astimezone(KST).strftime("%m-%d %H:%M:%S") if last_time else "기록 없음"
        await ctx.send(
            f"💳 **[{ctx.author.display_name}의 도박 자금]**\n"
            f"현재 식량 **{int(user.get('balance', 0)):,}개**\n"
            f"최근 결과 **{profile.get('last_game', '없음')} {_signed(last_delta)}** · {last_text}\n"
            f"오늘 손익 **{_signed(int(profile.get('daily_profit', 0)))}**\n"
            f"누적 손익 **{_signed(int(profile.get('total_profit', 0)))}**\n"
            f"전적 **{profile.get('wins', 0)}승 {profile.get('losses', 0)}패 {profile.get('draws', 0)}무** · 총 {total_games}회\n"
            f"최대 승리 **+{int(profile.get('largest_win', 0)):,}** · 최대 손실 **{int(profile.get('largest_loss', 0)):,}**\n"
            f"배팅 범위 **{GAMBLE_MIN_BET:,} ~ {GAMBLE_MAX_BET:,} 식량**"
        )

    @bot.hybrid_command(name="알바", aliases=["일하기"], description="하루 40회 폐허 알바를 하며 식량과 알바 경험치를 얻습니다.")
    @commands.cooldown(1, WORK_COOLDOWN_SECONDS, commands.BucketType.user)
    async def part_time_work(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        work = _ensure_work_profile(user)
        attempts = int(work.get("attempts", 0))
        if attempts >= WORK_DAILY_LIMIT:
            ctx.command.reset_cooldown(ctx)
            message = await ctx.send(
                "🛑 오늘 가능한 알바 **40회**를 모두 사용했습니다. 자정(KST)에 초기화됩니다.\n"
                "⛏️ 다음 수입 루트: **`!땅파기`** · 하루 50회 · 1분 간격 · 보물 발견 가능"
            )
            await _safe_reactions(message, ("🛑", "🧰", "⛏️", "💎"))
            return

        level = max(1, int(work.get("level", 1)))
        bad_chance = max(0.10, 0.28 - (level - 1) * 0.006)
        jackpot_chance = min(0.10, 0.03 + (level - 1) * 0.002)
        roll = random.random()
        before = int(user.get("balance", 0))
        stage_embed = discord.Embed(
            title="🧰 폐허 알바 배정 중",
            description="오늘 맡을 작업장과 위험도를 확인합니다...",
            color=discord.Color.dark_teal(),
        )
        stage_embed.add_field(name="📋 작업 배정", value="직종·위험도 조회", inline=True)
        stage_embed.add_field(name="🦺 안전 점검", value="장비·보상 확인", inline=True)
        visual_send = getattr(bot, "v631_send_visual", None)
        if visual_send:
            suspense = await visual_send(ctx, stage_embed, "activities/work/success")
        else:
            suspense = await ctx.send(embed=stage_embed)
        await asyncio.sleep(0.65)
        work_stage = discord.Embed(
            title="🔧 작업 진행 중",
            description=random.choice([
                "발전기 배선을 연결하고 있습니다...",
                "무너진 보급 창고의 물자를 분류합니다...",
                "거점 방벽의 균열을 보수하고 있습니다...",
                "감염체를 피해 배달 경로를 통과합니다...",
            ]),
            color=discord.Color.orange(),
        )
        work_stage.add_field(name="진행도", value="`███████░░░` **70%**", inline=False)
        visual_edit = getattr(bot, "v631_edit_visual", None)
        if visual_edit:
            await visual_edit(suspense, work_stage, "activities/work/success")
        else:
            await _edit_embed(suspense, work_stage)
        await asyncio.sleep(0.65)

        bonus_resource = None
        bonus_amount = 0
        if roll < bad_chance:
            loss = min(max(0, before), random.randint(200, 1100) + level * random.randint(5, 25))
            user["balance"] = before - loss
            delta = -loss
            exp_delta = -random.randint(1, 3)
            work["exp"] = max(0, int(work.get("exp", 0)) + exp_delta)
            event = random.choice(
                [
                    "폐허 발전기의 냉각 장치가 과열되어 긴급 보수비가 발생했습니다. 🔧",
                    "오염 구역의 지지대가 무너져 회수 장비를 교체했습니다. ⚠️",
                    "보급 운반 중 약탈자 신호를 피하다 일부 운송 장비를 잃었습니다. 📦",
                    "낡은 무전 중계기가 역전류를 일으켜 수리 비용을 정산했습니다. 📻",
                    "방벽 보수용 용접기가 고장 나 작업대 부품을 새로 구입했습니다. ⚙️",
                ]
            )
            work["total_lost"] = int(work.get("total_lost", 0)) + loss
            success = False
            work_outcome = "failure"
        elif roll < bad_chance + jackpot_chance:
            gain = random.randint(3200, 9500) + level * random.randint(80, 280)
            user["balance"] = before + gain
            delta = gain
            exp_delta = random.randint(5, 9)
            work["exp"] = int(work.get("exp", 0)) + exp_delta
            event = random.choice(
                [
                    "붕괴 직전의 창고에서 숨겨진 비상 식량을 발견했습니다! 💎",
                    "암시장 상인을 감염체에게서 구해 특별 수당을 받았습니다! 🛡️",
                    "고장 난 발전기를 완벽히 복구해 거액의 보너스를 받았습니다! ⚡",
                ]
            )
            work["total_earned"] = int(work.get("total_earned", 0)) + gain
            user.setdefault("stats", {}).setdefault("earned", 0)
            user["stats"]["earned"] += gain
            success = True
            work_outcome = "jackpot"
        else:
            gain = random.randint(380, 1450) + level * random.randint(25, 70)
            user["balance"] = before + gain
            delta = gain
            exp_delta = random.randint(2, 5)
            work["exp"] = int(work.get("exp", 0)) + exp_delta
            event = random.choice(
                [
                    "폐허 보급소의 야간 재고 정리를 무사히 마쳤습니다. 🏚️",
                    "거점 보급 창고에서 물자 분류 작업을 끝냈습니다. 📦",
                    "생존자 거점 사이의 배달 임무를 완료했습니다. 🚲",
                    "낡은 무전기를 수리해 작업 수당을 받았습니다. 📻",
                    "방벽 보수 작업을 마치고 일당을 받았습니다. 🧱",
                ]
            )
            work["total_earned"] = int(work.get("total_earned", 0)) + gain
            user.setdefault("stats", {}).setdefault("earned", 0)
            user["stats"]["earned"] += gain
            success = True
            work_outcome = "success"

        if success and random.random() < (0.42 if work_outcome == "jackpot" else 0.24):
            bonus_resource = random.choice(["고철", "광석", "나무"])
            bonus_amount = random.randint(2, 4) if work_outcome == "jackpot" else random.randint(1, 2)
            resources = user.setdefault("resources", {})
            resources[bonus_resource] = int(resources.get(bonus_resource, 0)) + bonus_amount

        work["attempts"] = attempts + 1
        work["last_work"] = _utc_now().isoformat()
        level_ups = _level_up_work(work)
        save_data()
        remaining = WORK_DAILY_LIMIT - int(work["attempts"])
        level_up_text = f" · 🎊 **{level_ups}단계 상승!**" if level_ups else ""
        color_map = {
            "failure": discord.Color.red(),
            "success": discord.Color.green(),
            "jackpot": discord.Color.gold(),
        }
        title_map = {
            "failure": "🔨 폐허 알바 사고 발생",
            "success": "🧰 폐허 알바 완료",
            "jackpot": "💎 폐허 알바 대박 보너스",
        }
        result_embed = discord.Embed(
            title=title_map[work_outcome],
            description=event,
            color=color_map[work_outcome],
            timestamp=_utc_now(),
        )
        result_embed.set_author(
            name=ctx.author.display_name,
            icon_url=str(ctx.author.display_avatar.url),
        )
        result_embed.set_thumbnail(url=str(ctx.author.display_avatar.url))
        result_embed.add_field(
            name="💰 이번 결과",
            value=f"**{_signed(delta)} 식량**",
            inline=True,
        )
        result_embed.add_field(
            name="💳 현재 잔액",
            value=f"**{int(user['balance']):,} 식량**",
            inline=True,
        )
        result_embed.add_field(
            name="📅 오늘 남은 횟수",
            value=f"**{remaining}회**",
            inline=True,
        )
        result_embed.add_field(
            name="🧪 알바 경험치",
            value=f"**{int(work['exp'])}/{_work_required_exp(int(work['level']))}** ({_signed(exp_delta)})",
            inline=True,
        )
        result_embed.add_field(
            name="🟩 알바 레벨",
            value=f"**Lv.{int(work['level'])}**{level_up_text}",
            inline=True,
        )
        if bonus_resource and bonus_amount:
            result_embed.add_field(
                name="📦 추가 발견물",
                value=f"**{bonus_resource} +{bonus_amount}**",
                inline=True,
            )
        result_embed.add_field(
            name="📈 성장 효과",
            value="레벨이 높을수록 사고 확률은 내려가고 보상·대박 확률은 올라갑니다.",
            inline=False,
        )
        if remaining == 0:
            result_embed.add_field(
                name="⛏️ 다음 수입 루트",
                value="오늘 알바를 모두 사용했습니다. 이제 `!땅파기`로 물자와 보물을 찾을 수 있습니다.",
                inline=False,
            )
        result_embed.add_field(
            name="💡 TIP",
            value=getattr(bot, "v631_tip", lambda _k: "알바 레벨이 오르면 사고 확률이 감소합니다.")("work"),
            inline=False,
        )
        outcome_asset = {
            "failure": "activities/work/failure",
            "success": "activities/work/success",
            "jackpot": "activities/work/rare",
        }[work_outcome]
        visual_edit = getattr(bot, "v631_edit_visual", None)
        if visual_edit:
            await visual_edit(suspense, result_embed, outcome_asset)
        else:
            await _edit_embed(suspense, result_embed)
        if work_outcome == "failure":
            await _safe_reactions(suspense, ("🔨", "😭", "💸", "❌"))
        elif work_outcome == "jackpot":
            await _safe_reactions(suspense, ("💎", "🎊", "🔥", "💰", "🏆"))
        else:
            await _safe_reactions(suspense, ("💰", "✅", "🧰", "👏"))
        maybe_encounter = getattr(bot, "v631_maybe_encounter", None)
        if maybe_encounter:
            await maybe_encounter(ctx, "work", user)

    @bot.hybrid_command(name="코인", aliases=["코인탐색"], description="1분마다 희귀도가 다른 암시장 자산 코인을 탐색합니다. 하루 30회")
    async def coin_draw(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        account = ensure_user_market(user)
        coin = _ensure_coin_profile(account)
        if int(coin.get("attempts", 0)) >= COIN_DAILY_LIMIT:
            message = await ctx.send(
                f"🛑 오늘의 코인 탐색 **{COIN_DAILY_LIMIT}회**를 모두 사용했습니다. 자정(KST)에 초기화됩니다.\n"
                "🧰 다음 수입 루트: **`!알바`** · 알바까지 소진하면 **`!땅파기`**"
            )
            await _safe_reactions(message, ("🛑", "🪙", "🧰", "⛏️"))
            return
        remaining_seconds = _coin_cooldown_remaining(coin)
        if remaining_seconds > 0:
            await ctx.send(f"⏳ 다음 코인 탐색까지 **{_format_seconds(remaining_seconds)}** 남았습니다.")
            return

        visual_send = getattr(bot, "v632_send_visual", None)
        visual_edit = getattr(bot, "v632_edit_visual", None)
        visual_tip = getattr(bot, "v632_tip", lambda _k: "실물 자산 서명과 위조 신호를 구분하세요.")
        scan_start = discord.Embed(title="🪙 폐허 코인 스캐너 가동", description="무너진 금고와 폐쇄 서버의 자산 신호를 추적합니다.", color=discord.Color.dark_teal())
        scan_start.add_field(name="📡 진행", value="◐ → ◓ → ◑ · 자산 신호 탐색", inline=True)
        scan_start.add_field(name="💡 TIP", value=visual_tip("coin"), inline=False)
        suspense = await visual_send(ctx, scan_start, "activities/coin/encounter") if visual_send else await ctx.send(embed=scan_start)
        await asyncio.sleep(0.8)
        decrypt = discord.Embed(title="🔐 암호 해독 중", description="자산 서명과 위조 신호를 분리합니다.", color=discord.Color.orange())
        decrypt.add_field(name="📡 진행", value="◓ → ◑ → ◒ · 서명 대조", inline=True)
        decrypt.add_field(name="💡 TIP", value=visual_tip("coin"), inline=False)
        if visual_edit: await visual_edit(suspense, decrypt, "activities/coin/encounter")
        else: await _edit_embed(suspense, decrypt)
        await asyncio.sleep(0.8)

        keys = [item[0] for item in COIN_DRAW_WEIGHTS]
        weights = [item[1] for item in COIN_DRAW_WEIGHTS]
        draw_result = random.choices(keys, weights=weights, k=1)[0]

        coin["attempts"] = int(coin.get("attempts", 0)) + 1
        coin["last_claim"] = _utc_now().isoformat()
        coin["total_attempts"] = int(coin.get("total_attempts", 0)) + 1
        remaining = COIN_DAILY_LIMIT - int(coin["attempts"])

        if draw_result == "실패":
            coin["failures"] = int(coin.get("failures", 0)) + 1
            before_balance = int(user.get("balance", 0))
            failure_cost = _coin_failure_cost(before_balance)
            user["balance"] = max(0, before_balance - failure_cost)
            coin["total_failure_cost"] = int(coin.get("total_failure_cost", 0)) + failure_cost
            save_data()
            failure_text = random.choice([
                "금고 신호가 끊겼습니다. 먼지와 빈 탄피만 발견했습니다.",
                "감염체가 먼저 금고를 헤집고 갔습니다. 남은 코인이 없습니다.",
                "위조 신호였습니다. 스캐너가 허공만 추적했습니다.",
                "잠금장치가 붕괴하면서 내부 자산이 잔해 아래로 사라졌습니다.",
                "폐허 상인이 한발 먼저 챙겨 갔습니다. 이번 탐색은 실패입니다.",
            ])
            embed = discord.Embed(
                title="🕳️ 코인 탐색 실패",
                description=failure_text,
                color=discord.Color.dark_red(),
                timestamp=_utc_now(),
            )
            repair_value = f"**-{failure_cost:,} 식량**" if failure_cost else "**0 식량 · 잔액 보호**"
            embed.add_field(name="💸 스캐너 수리비", value=repair_value, inline=True)
            embed.add_field(name="💳 현재 잔액", value=f"**{int(user['balance']):,} 식량**", inline=True)
            embed.add_field(name="📅 오늘 남은 탐색", value=f"**{remaining}회**", inline=True)
            embed.add_field(name="🎲 실패 확률", value="**35.0%**", inline=True)
            embed.add_field(name="⏳ 다음 탐색", value="**1분 후**", inline=True)
            embed.add_field(
                name="📉 누적 실패 비용",
                value=f"**{int(coin.get('total_failure_cost', 0)):,} 식량**",
                inline=True,
            )
            if remaining == 0:
                embed.add_field(
                    name="🧰 다음 수입 루트",
                    value="오늘 코인을 모두 사용했습니다. `!알바` 다음에는 `!땅파기`를 이용하세요.",
                    inline=False,
                )
            embed.set_footer(text="실패 비용은 잔액을 넘지 않으며 60~350 식량 범위에서 계산됩니다")
            embed.add_field(name="💡 TIP", value=visual_tip("coin"), inline=False)
            if visual_edit: await visual_edit(suspense, embed, "activities/coin/failure")
            else: await _edit_embed(suspense, embed)
            await _safe_reactions(suspense, ("❌", "🕳️", "😭", "💸", "🪨"))
            maybe_encounter = getattr(bot, "v632_maybe_encounter", None)
            if maybe_encounter:
                await maybe_encounter(ctx, "coin", user)
            return

        asset_key = draw_result
        info = MARKET_ASSETS[asset_key]
        market = ensure_market(world_data)
        current_price = int(market["assets"][asset_key]["price"])
        position = account["holdings"][asset_key]
        old_quantity = int(position.get("quantity", 0))
        old_avg = int(position.get("avg_price", 0))
        new_quantity = old_quantity + 1
        position["quantity"] = new_quantity
        position["avg_price"] = int(round((old_quantity * old_avg) / max(new_quantity, 1)))
        coin["total_claims"] = int(coin.get("total_claims", 0)) + 1
        _record_trade(account, "획득", asset_key, 1, current_price, 0, 0)
        save_data()

        probability_map = {"보급권": "48.0%", "군수권": "12.0%", "혈청": "3.8%", "유물": "1.1%", "코어": "0.1%"}
        grade_map = {"보급권": "일반", "군수권": "희귀", "혈청": "영웅", "유물": "전설", "코어": "신화"}
        color_map = {"보급권": 0x95A5A6, "군수권": 0x3498DB, "혈청": 0xE67E22, "유물": 0x9B59B6, "코어": 0xF1C40F}
        embed = discord.Embed(
            title=f"{info['emoji']} {grade_map[asset_key]} 코인 발견",
            description="금고 신호가 실물 자산 서명과 일치했습니다.",
            color=color_map[asset_key],
            timestamp=_utc_now(),
        )
        embed.add_field(name="🪙 이번 발견", value=f"**{info['name']} +1개**", inline=True)
        embed.add_field(name="🎲 등장 확률", value=f"**{probability_map[asset_key]}**", inline=True)
        embed.add_field(name="📈 현재 시세", value=f"**{current_price:,} 식량**", inline=True)
        embed.add_field(name="📦 보유 수량", value=f"**{new_quantity:,}개**", inline=True)
        embed.add_field(name="📅 오늘 남은 탐색", value=f"**{remaining}회**", inline=True)
        embed.add_field(name="⏳ 다음 탐색", value="**1분 후**", inline=True)
        if remaining == 0:
            embed.add_field(
                name="🧰 다음 수입 루트",
                value="오늘 코인을 모두 사용했습니다. `!알바` 다음에는 `!땅파기`를 이용하세요.",
                inline=False,
            )
        embed.add_field(name="💡 TIP", value=visual_tip("coin"), inline=False)
        embed.set_footer(text="ABADDON 암시장 코인 스캐너 · 결과를 항목별 임베드로 표시")
        asset_kind = "rare" if asset_key in {"혈청", "유물", "코어"} else "success"
        if visual_edit: await visual_edit(suspense, embed, f"activities/coin/{asset_kind}")
        else: await _edit_embed(suspense, embed)
        reaction_map = {
            "보급권": ("🪙", "✅", "📦"),
            "군수권": ("🔵", "✨", "🎯", "🪙"),
            "혈청": ("🧪", "🔥", "⚔️", "🎉"),
            "유물": ("💎", "🌟", "🎊", "🔥", "🏆"),
            "코어": ("👑", "💠", "🌌", "🏆", "🎉", "🔥"),
        }
        await _safe_reactions(suspense, reaction_map[asset_key])
        maybe_encounter = getattr(bot, "v632_maybe_encounter", None)
        if maybe_encounter:
            await maybe_encounter(ctx, "coin", user)

    # ---------- 암시장 자동 알림 ----------
    def notification_settings() -> Dict[str, Any]:
        settings = world_data.setdefault("market_notifications", {})
        if not isinstance(settings, dict):
            settings = {}
            world_data["market_notifications"] = settings
        return settings

    def guild_notification(guild_id: int) -> Dict[str, Any]:
        current_tick = int(ensure_market(world_data).get("tick", 0))
        state = notification_settings().setdefault(
            str(guild_id),
            {
                "enabled": False,
                "channel_id": None,
                "role_id": None,
                "last_seen_tick": current_tick,
                "last_event": "",
                "last_alert_at": "",
            },
        )
        if not isinstance(state, dict):
            state = {}
            notification_settings()[str(guild_id)] = state
        state.setdefault("enabled", False)
        state.setdefault("channel_id", None)
        state.setdefault("role_id", None)
        state.setdefault("last_seen_tick", current_tick)
        state.setdefault("last_event", "")
        state.setdefault("last_alert_at", "")
        return state

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild and (ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator):
            return True
        await ctx.send("❌ 이 명령어는 서버 관리자만 사용할 수 있습니다.")
        return False

    async def setup_market_alert(ctx: commands.Context, role: Optional[discord.Role] = None) -> None:
        if not await require_admin(ctx):
            return
        market = ensure_market(world_data)
        state = guild_notification(ctx.guild.id)
        state.update(
            {
                "enabled": True,
                "channel_id": ctx.channel.id,
                "role_id": role.id if role else None,
                "last_seen_tick": int(market.get("tick", 0)),
                "last_event": str(market.get("event", "")),
            }
        )
        save_data()
        await ctx.send(
            "✅ **암시장 자동 알림 설정 완료**\n"
            f"채널: {ctx.channel.mention}\n"
            f"알림 역할: {role.mention if role else '없음'}\n"
            f"조건: 시장 사건 발생 또는 1분 변동률 **±{MARKET_ALERT_THRESHOLD * 100:.0f}% 이상**\n"
            "과도한 도배를 막기 위해 일반 급등락 알림은 5분 간격으로 제한됩니다."
        )

    async def disable_market_alert(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        state = guild_notification(ctx.guild.id)
        state["enabled"] = False
        save_data()
        await ctx.send("🔕 이 서버의 암시장 자동 알림을 해제했습니다.")

    async def show_market_alert_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = guild_notification(ctx.guild.id)
        channel = ctx.guild.get_channel(int(state["channel_id"])) if state.get("channel_id") else None
        role = ctx.guild.get_role(int(state["role_id"])) if state.get("role_id") else None
        await ctx.send(
            "📋 **암시장 자동 알림 상태**\n"
            f"상태: {'✅ 사용 중' if state.get('enabled') else '❌ 꺼짐'}\n"
            f"채널: {channel.mention if channel else '미설정'}\n"
            f"알림 역할: {role.mention if role else '없음'}\n"
            f"급등락 기준: **±{MARKET_ALERT_THRESHOLD * 100:.0f}%** · 재알림 간격 5분"
        )

    @bot.command(name="암시장알림설정")
    async def market_alert_setup_legacy(ctx: commands.Context, 역할: Optional[discord.Role] = None) -> None:
        await setup_market_alert(ctx, 역할)

    @bot.command(name="암시장알림해제")
    async def market_alert_disable_legacy(ctx: commands.Context) -> None:
        await disable_market_alert(ctx)

    @bot.command(name="암시장알림상태")
    async def market_alert_status_legacy(ctx: commands.Context) -> None:
        await show_market_alert_status(ctx)

    black_market_group = bot.get_command("암시장")
    if isinstance(black_market_group, commands.HybridGroup):
        @black_market_group.command(name="알림설정", description="현재 채널에 암시장 급등락·시장 사건 자동 알림을 설정합니다.")
        async def market_alert_setup_slash(ctx: commands.Context, 역할: Optional[discord.Role] = None) -> None:
            await setup_market_alert(ctx, 역할)

        @black_market_group.command(name="알림해제", description="이 서버의 암시장 자동 알림을 해제합니다.")
        async def market_alert_disable_slash(ctx: commands.Context) -> None:
            await disable_market_alert(ctx)

        @black_market_group.command(name="알림상태", description="암시장 자동 알림 채널과 상태를 확인합니다.")
        async def market_alert_status_slash(ctx: commands.Context) -> None:
            await show_market_alert_status(ctx)

    async def fetch_channel(guild: discord.Guild, channel_id: Any) -> Optional[discord.abc.Messageable]:
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            return channel
        try:
            return await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError, ValueError):
            return None

    def market_alert_embed(market: Dict[str, Any], movers: Sequence[Tuple[str, float]], event_changed: bool) -> discord.Embed:
        embed = discord.Embed(
            title="🚨 폐허 암시장 급등락 알림",
            description=(
                f"**{_utc_now().astimezone(KST):%Y-%m-%d %H시 %M분 %S초} 기준**\n"
                "전 서버 공통 시세에 큰 움직임이 감지됐습니다."
            ),
            color=discord.Color.red() if any(percent < 0 for _, percent in movers[:1]) else discord.Color.gold(),
        )
        if event_changed and market.get("event"):
            embed.add_field(name="⚠️ 새 시장 사건", value=str(market["event"]), inline=False)

        selected = list(movers[:3])
        if not selected:
            selected = sorted(
                ((key, _price_change(market["assets"][key])[1]) for key in MARKET_ASSETS),
                key=lambda item: abs(item[1]),
                reverse=True,
            )[:3]
        for key, percent in selected:
            info = MARKET_ASSETS[key]
            entry = market["assets"][key]
            embed.add_field(
                name=f"{info['emoji']} {info['name']} {_format_change(entry)}",
                value=f"현재가 **{int(entry['price']):,} 식량** · 직전가 **{int(entry['previous_price']):,}**",
                inline=False,
            )
        embed.set_footer(text="!시세 또는 /암시장 시세 · 인게임 식량 전용")
        return embed

    @tasks.loop(seconds=65)
    async def market_alert_loop() -> None:
        changed = update_market(world_data, force=False)
        if changed:
            save_data()
        market = ensure_market(world_data)
        tick = int(market.get("tick", 0))
        event = str(market.get("event", ""))
        movers = sorted(
            [
                (key, _price_change(market["assets"][key])[1])
                for key in MARKET_ASSETS
                if abs(_price_change(market["assets"][key])[1]) >= MARKET_ALERT_THRESHOLD * 100
            ],
            key=lambda item: abs(item[1]),
            reverse=True,
        )

        dirty = False
        for guild in list(bot.guilds):
            state = guild_notification(guild.id)
            if not state.get("enabled"):
                continue
            if int(state.get("last_seen_tick", -1)) >= tick:
                continue

            event_changed = bool(event and event != state.get("last_event"))
            last_alert = _parse_time(state.get("last_alert_at"))
            cooldown_ok = not last_alert or (_utc_now() - last_alert).total_seconds() >= MARKET_ALERT_COOLDOWN_SECONDS
            should_alert = event_changed or (bool(movers) and cooldown_ok)

            state["last_seen_tick"] = tick
            state["last_event"] = event
            dirty = True
            if not should_alert:
                continue

            channel = await fetch_channel(guild, state.get("channel_id"))
            if channel is None:
                continue
            role = guild.get_role(int(state["role_id"])) if state.get("role_id") else None
            try:
                await channel.send(
                    content=role.mention if role else None,
                    embed=market_alert_embed(market, movers, event_changed),
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
                state["last_alert_at"] = _utc_now().isoformat()
                dirty = True
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"[암시장 자동 알림 오류] guild={guild.id}: {exc}")

        if dirty:
            save_data()

    @market_alert_loop.before_loop
    async def before_market_alert_loop() -> None:
        await bot.wait_until_ready()
        await asyncio.sleep(5)

    async def start_market_alert_loop() -> None:
        if not market_alert_loop.is_running():
            market_alert_loop.start()

    bot.add_listener(start_market_alert_loop, "on_ready")
