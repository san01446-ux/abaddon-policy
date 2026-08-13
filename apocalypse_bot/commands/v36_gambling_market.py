from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

import discord
from discord.ext import commands, tasks


KST = timezone(timedelta(hours=9))
MARKET_TICK_SECONDS = 60
TRADE_FEE_RATE = 0.02
TRADE_COOLDOWN_SECONDS = 10
MAX_TRADE_HISTORY = 20
MAX_PRICE_HISTORY = 30


MARKET_ASSETS: Dict[str, Dict[str, Any]] = {
    "보급권": {
        "name": "일반 보급권",
        "emoji": "🟢",
        "base_price": 750,
        "min_price": 100,
        "max_price": 20_000,
        "volatility": 0.018,
        "aliases": ["일반", "일반코인", "일반보급권", "보급", "보급권"],
        "desc": "폐허 암시장에서 가장 자주 거래되는 기본 보급 증서",
    },
    "군수권": {
        "name": "군용 보급권",
        "emoji": "🔵",
        "base_price": 55_000,
        "min_price": 5_000,
        "max_price": 1_500_000,
        "volatility": 0.026,
        "aliases": ["군용", "슈퍼", "슈퍼코인", "군수", "군용보급권", "군수권"],
        "desc": "군수 창고 물자 우선 배급권",
    },
    "혈청": {
        "name": "붉은 변이 혈청",
        "emoji": "🟠",
        "base_price": 1_800_000,
        "min_price": 100_000,
        "max_price": 80_000_000,
        "volatility": 0.038,
        "aliases": ["혈청", "전설", "전설코인", "붉은혈청", "변이혈청", "붉은변이혈청"],
        "desc": "효능과 부작용이 모두 불명확한 고위험 실험 물질",
    },
    "유물": {
        "name": "천상 유물",
        "emoji": "🌸",
        "base_price": 58_000_000,
        "min_price": 1_000_000,
        "max_price": 2_000_000_000,
        "volatility": 0.052,
        "aliases": ["유물", "천상", "천상코인", "천상유물"],
        "desc": "종말 이전 문명의 흔적이 담긴 희귀 유물",
    },
    "코어": {
        "name": "아바돈 코어",
        "emoji": "💠",
        "base_price": 2_000_000_000,
        "min_price": 50_000_000,
        "max_price": 100_000_000_000,
        "volatility": 0.072,
        "aliases": ["코어", "다이아", "다이아코인", "아바돈", "아바돈코어"],
        "desc": "공허 에너지가 응축된 최상위 투기 자산",
    },
}


COIN_DISPLAY_NAMES: Dict[str, str] = {
    "보급권": "일반 코인",
    "군수권": "슈퍼 코인",
    "혈청": "전설 코인",
    "유물": "천상 코인",
    "코어": "다이아 코인",
}


MARKET_EVENTS = [
    ("📦 대형 보급 수송대 발견", 0.04),
    ("🧟 감염체 습격으로 공급망 붕괴", -0.05),
    ("📡 구조 신호 포착으로 매수세 유입", 0.035),
    ("☣️ 혈청 부작용 소문 확산", -0.065),
    ("🏚️ 암시장 단속 소식", -0.04),
    ("🛰️ 군수 위성 데이터 복구", 0.055),
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_asset_name(value: str) -> str:
    return str(value or "").replace(" ", "").lower()


def resolve_asset(value: str) -> Optional[str]:
    target = _clean_asset_name(value)
    if not target:
        return None
    for key, info in MARKET_ASSETS.items():
        candidates = [key, info["name"], *info.get("aliases", [])]
        if target in {_clean_asset_name(candidate) for candidate in candidates}:
            return key
    return None


def ensure_market(world_data: Dict[str, Any]) -> Dict[str, Any]:
    market = world_data.setdefault("gambling_market", {})
    if not isinstance(market, dict):
        market = {}
        world_data["gambling_market"] = market

    assets = market.setdefault("assets", {})
    if not isinstance(assets, dict):
        assets = {}
        market["assets"] = assets

    for key, info in MARKET_ASSETS.items():
        entry = assets.setdefault(key, {})
        if not isinstance(entry, dict):
            entry = {}
            assets[key] = entry
        initial = int(info["base_price"])
        entry.setdefault("price", initial)
        entry.setdefault("previous_price", initial)
        entry.setdefault("open_price", initial)
        entry.setdefault("high_price", initial)
        entry.setdefault("low_price", initial)
        entry.setdefault("history", [initial])
        entry["price"] = max(int(info["min_price"]), min(int(info["max_price"]), int(entry.get("price", initial) or initial)))
        if not isinstance(entry.get("history"), list):
            entry["history"] = [entry["price"]]

    market.setdefault("last_update", _utc_now().isoformat())
    market.setdefault("tick", 0)
    market.setdefault("event", "")
    market.setdefault("event_expires_tick", 0)
    return market


def ensure_user_market(user: Dict[str, Any]) -> Dict[str, Any]:
    account = user.setdefault("gambling_market", {})
    if not isinstance(account, dict):
        account = {}
        user["gambling_market"] = account

    holdings = account.setdefault("holdings", {})
    if not isinstance(holdings, dict):
        holdings = {}
        account["holdings"] = holdings

    for key in MARKET_ASSETS:
        position = holdings.setdefault(key, {})
        if not isinstance(position, dict):
            position = {}
            holdings[key] = position
        position.setdefault("quantity", 0)
        position.setdefault("avg_price", 0)
        position["quantity"] = max(0, int(position.get("quantity", 0) or 0))
        position["avg_price"] = max(0, int(position.get("avg_price", 0) or 0))

    trades = account.setdefault("trades", [])
    if not isinstance(trades, list):
        account["trades"] = []
    account.setdefault("realized_profit", 0)
    account.setdefault("fees_paid", 0)
    account.setdefault("last_trade", "")
    return account


def _single_market_tick(market: Dict[str, Any]) -> None:
    market["tick"] = int(market.get("tick", 0) or 0) + 1
    global_event_shift = 0.0

    if random.random() < 0.035:
        event_name, global_event_shift = random.choice(MARKET_EVENTS)
        market["event"] = event_name
        market["event_expires_tick"] = market["tick"] + random.randint(2, 5)
    elif market.get("event") and market["tick"] >= int(market.get("event_expires_tick", 0) or 0):
        market["event"] = ""

    for key, info in MARKET_ASSETS.items():
        entry = market["assets"][key]
        old_price = max(1, int(entry.get("price", info["base_price"])))
        entry["previous_price"] = old_price

        base_price = float(info["base_price"])
        volatility = float(info["volatility"])
        mean_reversion = ((base_price - old_price) / max(base_price, 1.0)) * 0.0025
        random_move = random.gauss(0.0, volatility)
        asset_event = 0.0

        if random.random() < 0.012:
            asset_event = random.choice([-1, 1]) * random.uniform(volatility * 2.5, volatility * 5.5)

        total_change = max(-0.35, min(0.35, random_move + mean_reversion + global_event_shift + asset_event))
        new_price = int(round(old_price * (1.0 + total_change)))
        new_price = max(int(info["min_price"]), min(int(info["max_price"]), new_price))

        entry["price"] = new_price
        entry["high_price"] = max(int(entry.get("high_price", new_price) or new_price), new_price)
        entry["low_price"] = min(int(entry.get("low_price", new_price) or new_price), new_price)
        history = entry.setdefault("history", [])
        history.append(new_price)
        del history[:-MAX_PRICE_HISTORY]


def update_market(world_data: Dict[str, Any], force: bool = False) -> bool:
    market = ensure_market(world_data)
    now = _utc_now()
    last_update = _parse_time(market.get("last_update")) or now
    elapsed = max(0.0, (now - last_update).total_seconds())

    ticks = int(elapsed // MARKET_TICK_SECONDS)
    if force and ticks <= 0:
        ticks = 1
    if ticks <= 0:
        return False

    # 장시간 오프라인 후 한 번에 과도하게 움직이지 않도록 최대 120분만 보정합니다.
    ticks = min(ticks, 120)
    for _ in range(ticks):
        _single_market_tick(market)
    market["last_update"] = now.isoformat()
    return True


def _price_change(entry: Dict[str, Any]) -> Tuple[int, float]:
    current = int(entry.get("price", 0) or 0)
    previous = int(entry.get("previous_price", current) or current)
    difference = current - previous
    percent = difference / max(previous, 1) * 100
    return difference, percent


def _format_change(entry: Dict[str, Any]) -> str:
    difference, percent = _price_change(entry)
    if difference > 0:
        return f"📈 +{percent:.2f}%"
    if difference < 0:
        return f"📉 {percent:.2f}%"
    return "➖ 0.00%"


def _market_embed(world_data: Dict[str, Any]) -> discord.Embed:
    market = ensure_market(world_data)
    now_kst = _utc_now().astimezone(KST)
    embed = discord.Embed(
        title="📊 폐허 암시장 실시간 시세",
        description=(
            f"**{now_kst:%Y-%m-%d %H시 %M분 %S초} 기준**\n"
            "시세는 모든 서버에서 공유되며 **1분마다 자동 변동**합니다."
        ),
        color=discord.Color.purple(),
    )

    for key, info in MARKET_ASSETS.items():
        entry = market["assets"][key]
        embed.add_field(
            name=f"{info['emoji']} {info['name']}",
            value=(
                f"**{int(entry['price']):,} 식량**  {_format_change(entry)}\n"
                f"고가 {int(entry['high_price']):,} · 저가 {int(entry['low_price']):,}"
            ),
            inline=False,
        )

    if market.get("event"):
        embed.add_field(name="⚠️ 현재 시장 소식", value=str(market["event"]), inline=False)

    embed.set_footer(text="거래 수수료 2% · 인게임 식량 전용 · 현금 환전 불가")
    return embed


def _record_trade(account: Dict[str, Any], action: str, asset_key: str, quantity: int, price: int, fee: int, total: int) -> None:
    account.setdefault("trades", []).append(
        {
            "time": _utc_now().isoformat(),
            "action": action,
            "asset": asset_key,
            "quantity": int(quantity),
            "price": int(price),
            "fee": int(fee),
            "total": int(total),
        }
    )
    del account["trades"][:-MAX_TRADE_HISTORY]
    account["last_trade"] = _utc_now().isoformat()


def _trade_cooldown_remaining(account: Dict[str, Any]) -> int:
    last = _parse_time(account.get("last_trade"))
    if not last:
        return 0
    remaining = int((last + timedelta(seconds=TRADE_COOLDOWN_SECONDS) - _utc_now()).total_seconds())
    return max(0, remaining)


def _parse_quantity(value: Any, owned: int = 0) -> Optional[int]:
    text = str(value or "").strip().lower().replace(",", "")
    if text in {"전부", "all", "전체"}:
        return owned if owned > 0 else None
    try:
        quantity = int(text)
    except (TypeError, ValueError):
        return None
    return quantity if quantity > 0 else None


def register_v36_commands(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    progress_quest: Optional[Callable[[Dict[str, Any], str], None]] = None,
) -> None:
    """V3.6 실시간 암시장과 도박 안내 명령어를 등록합니다."""
    ensure_market(world_data)
    save_data()

    user_locks: Dict[int, asyncio.Lock] = {}

    def get_lock(user_id: int) -> asyncio.Lock:
        return user_locks.setdefault(int(user_id), asyncio.Lock())

    async def sync_market(force: bool = False) -> None:
        if update_market(world_data, force=force):
            save_data()

    async def show_prices(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        await sync_market()
        await ctx.send(embed=_market_embed(world_data))

    async def show_help(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        # v37 owns the current general-gambling limits. Import lazily to avoid
        # a module-load cycle (v37 itself imports the market helpers above).
        from apocalypse_bot.commands import v37_gambling_experience as gambling
        embed = discord.Embed(
            title="🎲 ABADDON 일반 도박 · 암시장 최신 안내",
            description=(
                "카지노 칩 게임과 **일반 도박은 서로 분리**되어 있습니다.\n"
                f"기본 일반 도박 배팅 범위: **{gambling.GAMBLE_MIN_BET:,} ~ {gambling.GAMBLE_MAX_BET:,} 식량**\n"
                "카지노는 `!카지노` · 카드게임은 `!카드게임`에서 별도로 확인하세요."
            ),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="🎯 기본 일반 도박 · 식량 사용",
            value=(
                "`!탐색 왼쪽 1000` · `!주파수 1000` · `!룰렛 1000`\n"
                "`!도박잔액` — 최근/오늘/누적 일반 도박 손익\n"
                "`!파산신청` — 식량 빚 일부 정리 · `!정부지원금` — 재기 조건 충족 시 지원"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏇 확장 배팅 콘텐츠",
            value=(
                "`!경마 10000` · `!경마장` · `!경마전적` — 실시간 6마리 경주\n"
                "`!지뢰찾기 [지뢰수] [배팅액]` · `!괴질탈출 배팅액` · `!비상주파수 배팅액`\n"
                "`!돌연변이경주` → `!돌연변이배팅 번호 금액`\n"
                "`!선물거래 방향 배팅액 [레버리지]` · `!괴수투기장 @상대 [배팅액]`\n"
                "`!생존룰렛` → `!생존선택 1|2|3`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧰 식량 · 코인 획득",
            value=(
                f"`!알바` — 하루 **{gambling.WORK_DAILY_LIMIT}회**, 기본 **{gambling.WORK_COOLDOWN_SECONDS}초** 간격\n"
                f"`!코인` — 하루 **{gambling.COIN_DAILY_LIMIT}회**, 기본 **{gambling.COIN_COOLDOWN_SECONDS}초** 간격\n"
                "코인 탐색 결과는 암시장 자산으로 보관되며 `!매도`에서 판매할 수 있습니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="📈 암시장 자산 거래 · 도박과 별도",
            value=(
                "`!시세` · `!매수 일반 10` · `!매도`/`!코인판매`\n"
                "`!자산` · `!암시장기록`\n"
                "관리자 알림: `!암시장알림설정 [@역할]` · `!암시장알림상태` · `!암시장알림해제`\n"
                "종목: `일반` · `군용` · `혈청` · `유물` · `코어`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎰 카지노 · 칩 전용",
            value=(
                "`!카지노` · `!카지노도움말` · `!카지노칩` · `!카지노환전 구매/판매 금액`\n"
                "블랙잭 · 하이로우 · 슬롯 · 다이스 · 바카라 · 럭키휠 · 코인플립 · 올인\n"
                "VIP · 잭팟 · 미션 · 업적 · 상점 · 시즌랭킹 · 딜러 · 개인 카지노/꾸미기"
            ),
            inline=False,
        )
        embed.add_field(
            name="🃏 카드게임",
            value="포커·원카드·화투 등 별도 카드게임은 `!카드게임`에서 확인합니다.",
            inline=False,
        )
        embed.set_footer(text="v18.2.2 안내 동기화 · 모든 재화는 게임 내부 가상 재화이며 현금 환전 기능 없음")
        await ctx.send(embed=embed)

    async def buy_asset(ctx: commands.Context, asset_name: str, quantity_value: Any) -> None:
        if not await check_registered(ctx):
            return
        await sync_market()
        asset_key = resolve_asset(asset_name)
        quantity = _parse_quantity(quantity_value)
        if not asset_key or not quantity:
            await ctx.send("⚠️ 사용법: `!매수 일반 10`\n종목: 일반 / 군용 / 혈청 / 유물 / 코어")
            return

        async with get_lock(ctx.author.id):
            user = get_user(ctx.author.id)
            account = ensure_user_market(user)
            remaining = _trade_cooldown_remaining(account)
            if remaining > 0:
                await ctx.send(f"⏳ 연속 거래 방지를 위해 **{remaining}초** 뒤 다시 거래하세요.")
                return

            market = ensure_market(world_data)
            price = int(market["assets"][asset_key]["price"])
            subtotal = price * quantity
            fee = max(1, math.ceil(subtotal * TRADE_FEE_RATE))
            total_cost = subtotal + fee
            if user.get("balance", 0) < total_cost:
                await ctx.send(
                    f"⚠️ 식량이 부족합니다.\n필요: **{total_cost:,}개** · 보유: **{int(user.get('balance', 0)):,}개**"
                )
                return

            position = account["holdings"][asset_key]
            old_quantity = int(position["quantity"])
            old_avg = int(position["avg_price"])
            new_quantity = old_quantity + quantity
            new_avg = int(round(((old_quantity * old_avg) + (quantity * price)) / max(new_quantity, 1)))

            user["balance"] -= total_cost
            position["quantity"] = new_quantity
            position["avg_price"] = new_avg
            account["fees_paid"] = int(account.get("fees_paid", 0)) + fee
            _record_trade(account, "매수", asset_key, quantity, price, fee, total_cost)
            user.setdefault("stats", {}).setdefault("gambles", 0)
            user["stats"]["gambles"] += 1
            if progress_quest:
                progress_quest(user, "도박 참여")
            save_data()

            info = MARKET_ASSETS[asset_key]
            await ctx.send(
                f"✅ **[암시장 매수 완료]**\n"
                f"{info['emoji']} {info['name']} **{quantity:,}개**\n"
                f"체결가 **{price:,}** · 수수료 **{fee:,}** · 총 지출 **{total_cost:,} 식량**\n"
                f"보유 수량 **{new_quantity:,}개** · 평균 단가 **{new_avg:,}**"
            )

    async def execute_coin_sale(user_id: int, asset_key: str, quantity_value: Any) -> Dict[str, Any]:
        """코인 판매를 실제 처리하고 UI와 텍스트 명령어가 공통으로 쓰는 결과를 반환합니다."""
        await sync_market()
        if asset_key not in MARKET_ASSETS:
            return {"ok": False, "message": "⚠️ 존재하지 않는 코인입니다."}

        async with get_lock(user_id):
            user = get_user(user_id)
            account = ensure_user_market(user)
            position = account["holdings"][asset_key]
            owned = int(position.get("quantity", 0) or 0)
            quantity = _parse_quantity(quantity_value, owned=owned)
            if not quantity or quantity > owned:
                return {
                    "ok": False,
                    "message": f"⚠️ 판매 수량이 올바르지 않습니다. 현재 보유: **{owned:,}개**",
                }

            remaining = _trade_cooldown_remaining(account)
            if remaining > 0:
                return {
                    "ok": False,
                    "message": f"⏳ 연속 거래 방지를 위해 **{remaining}초** 뒤 다시 거래하세요.",
                }

            market = ensure_market(world_data)
            price = int(market["assets"][asset_key]["price"])
            gross = price * quantity
            fee = max(1, math.ceil(gross * TRADE_FEE_RATE))
            net = max(0, gross - fee)
            avg_price = int(position.get("avg_price", 0) or 0)
            realized = net - (avg_price * quantity)

            user["balance"] = int(user.get("balance", 0) or 0) + net
            position["quantity"] = owned - quantity
            if position["quantity"] <= 0:
                position["quantity"] = 0
                position["avg_price"] = 0
            account["realized_profit"] = int(account.get("realized_profit", 0) or 0) + realized
            account["fees_paid"] = int(account.get("fees_paid", 0) or 0) + fee
            _record_trade(account, "매도", asset_key, quantity, price, fee, net)
            user.setdefault("stats", {}).setdefault("gambles", 0)
            user["stats"]["gambles"] += 1
            if realized > 0:
                user["stats"].setdefault("earned", 0)
                user["stats"]["earned"] += realized
            if progress_quest:
                progress_quest(user, "도박 참여")
            save_data()

            return {
                "ok": True,
                "asset_key": asset_key,
                "quantity": quantity,
                "price": price,
                "gross": gross,
                "fee": fee,
                "net": net,
                "realized": realized,
                "remaining": int(position["quantity"]),
                "balance": int(user.get("balance", 0) or 0),
            }

    def coin_sale_result_embed(result: Dict[str, Any]) -> discord.Embed:
        asset_key = str(result["asset_key"])
        info = MARKET_ASSETS[asset_key]
        coin_name = COIN_DISPLAY_NAMES.get(asset_key, info["name"])
        realized = int(result["realized"])
        sign = "+" if realized >= 0 else ""
        embed = discord.Embed(
            title="💸 코인 판매 완료",
            description=(
                f"{info['emoji']} **{coin_name} {int(result['quantity']):,}개**를 판매했습니다.\n"
                "현재 시세로 즉시 체결되었습니다."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="체결가", value=f"{int(result['price']):,} 식량", inline=True)
        embed.add_field(name="수수료", value=f"{int(result['fee']):,} 식량", inline=True)
        embed.add_field(name="순수령", value=f"**{int(result['net']):,} 식량**", inline=True)
        embed.add_field(name="실현 손익", value=f"{sign}{realized:,} 식량", inline=True)
        embed.add_field(name="남은 코인", value=f"{int(result['remaining']):,}개", inline=True)
        embed.add_field(name="현재 잔액", value=f"{int(result['balance']):,} 식량", inline=True)
        embed.set_footer(text="암시장 거래 수수료 2% · 게임 내 재화 전용")
        return embed

    def coin_sale_menu_embed(user_id: int) -> discord.Embed:
        user = get_user(user_id)
        account = ensure_user_market(user)
        lines = []
        for asset_key, info in MARKET_ASSETS.items():
            quantity = int(account["holdings"][asset_key].get("quantity", 0) or 0)
            lines.append(f"{info['emoji']} **{COIN_DISPLAY_NAMES[asset_key]}** : {quantity:,}개")

        embed = discord.Embed(
            title="🪙 코인 판매 💸",
            description="아래 드롭다운에서 판매할 코인을 선택하세요.",
            color=discord.Color.green(),
        )
        embed.add_field(name="보유한 코인", value="\n".join(lines), inline=False)
        embed.add_field(name="잔액", value=f"**{int(user.get('balance', 0) or 0):,} 식량**", inline=False)
        embed.set_footer(text="선택 후 1개 · 10개 · 전부 · 직접 입력 중에서 판매 수량을 정할 수 있습니다.")
        return embed

    def coin_quantity_embed(user_id: int, asset_key: str) -> discord.Embed:
        user = get_user(user_id)
        account = ensure_user_market(user)
        market = ensure_market(world_data)
        info = MARKET_ASSETS[asset_key]
        owned = int(account["holdings"][asset_key].get("quantity", 0) or 0)
        price = int(market["assets"][asset_key]["price"])
        gross_all = price * owned
        fee_all = max(1, math.ceil(gross_all * TRADE_FEE_RATE)) if owned > 0 else 0
        net_all = max(0, gross_all - fee_all)
        embed = discord.Embed(
            title=f"{info['emoji']} {COIN_DISPLAY_NAMES[asset_key]} 판매",
            description="판매할 수량을 아래 버튼에서 선택하세요.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="보유 수량", value=f"**{owned:,}개**", inline=True)
        embed.add_field(name="현재 시세", value=f"**{price:,} 식량**", inline=True)
        embed.add_field(name="전부 판매 예상 수령", value=f"**{net_all:,} 식량**", inline=False)
        embed.set_footer(text="실제 수령액은 거래 수수료 2%를 제외한 금액입니다.")
        return embed

    class CoinSellAmountModal(discord.ui.Modal):
        def __init__(self, quantity_view: "CoinSellQuantityView") -> None:
            super().__init__(title="코인 판매 수량 입력", timeout=180)
            self.quantity_view = quantity_view
            self.amount_input = discord.ui.TextInput(
                label="판매 수량",
                placeholder="예: 5 또는 전부",
                required=True,
                max_length=20,
            )
            self.add_item(self.amount_input)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            if interaction.user.id != self.quantity_view.author_id:
                await interaction.response.send_message(
                    "❌ 이 판매 메뉴는 명령어를 실행한 사람만 사용할 수 있습니다.",
                    ephemeral=True,
                )
                return

            result = await execute_coin_sale(
                self.quantity_view.author_id,
                self.quantity_view.asset_key,
                str(self.amount_input.value),
            )
            if not result.get("ok"):
                await interaction.response.send_message(
                    str(result.get("message", "⚠️ 판매에 실패했습니다.")),
                    ephemeral=True,
                )
                return

            await interaction.response.send_message("✅ 코인 판매가 완료되었습니다.", ephemeral=True)
            if self.quantity_view.message is not None:
                try:
                    await self.quantity_view.message.edit(embed=coin_sale_result_embed(result), view=None)
                except (discord.HTTPException, discord.NotFound):
                    pass

        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            if interaction.response.is_done():
                await interaction.followup.send("❌ 판매 수량 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 판매 수량 처리 중 오류가 발생했습니다.", ephemeral=True)
            print(f"[코인 판매 모달 오류] {type(error).__name__}: {error}")

    class CoinSellQuantityView(discord.ui.View):
        def __init__(self, author_id: int, asset_key: str) -> None:
            super().__init__(timeout=180)
            self.author_id = int(author_id)
            self.asset_key = asset_key
            self.message = None
            user = get_user(author_id)
            account = ensure_user_market(user)
            owned = int(account["holdings"][asset_key].get("quantity", 0) or 0)
            self.sell_one.disabled = owned < 1
            self.sell_ten.disabled = owned < 10
            self.sell_all.disabled = owned < 1
            self.sell_custom.disabled = owned < 1

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "❌ 이 판매 메뉴는 명령어를 실행한 사람만 사용할 수 있습니다.",
                    ephemeral=True,
                )
                return False
            return True

        async def finish_sale(self, interaction: discord.Interaction, quantity_value: Any) -> None:
            result = await execute_coin_sale(self.author_id, self.asset_key, quantity_value)
            if not result.get("ok"):
                await interaction.response.send_message(
                    str(result.get("message", "⚠️ 판매에 실패했습니다.")),
                    ephemeral=True,
                )
                return
            await interaction.response.edit_message(embed=coin_sale_result_embed(result), view=None)
            self.stop()

        @discord.ui.button(label="1개", style=discord.ButtonStyle.primary, emoji="1️⃣")
        async def sell_one(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await self.finish_sale(interaction, 1)

        @discord.ui.button(label="10개", style=discord.ButtonStyle.primary, emoji="🔟")
        async def sell_ten(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await self.finish_sale(interaction, 10)

        @discord.ui.button(label="전부", style=discord.ButtonStyle.danger, emoji="💸")
        async def sell_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await self.finish_sale(interaction, "전부")

        @discord.ui.button(label="직접 입력", style=discord.ButtonStyle.success, emoji="⌨️")
        async def sell_custom(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            await interaction.response.send_modal(CoinSellAmountModal(self))

        @discord.ui.button(label="뒤로", style=discord.ButtonStyle.secondary, emoji="↩️")
        async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            menu = CoinSellMenuView(self.author_id)
            menu.message = interaction.message
            await interaction.response.edit_message(embed=coin_sale_menu_embed(self.author_id), view=menu)
            self.stop()

        async def on_timeout(self) -> None:
            for child in self.children:
                child.disabled = True
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.NotFound):
                    pass

    class CoinSellSelect(discord.ui.Select):
        def __init__(self, menu_view: "CoinSellMenuView") -> None:
            self.menu_view = menu_view
            user = get_user(menu_view.author_id)
            account = ensure_user_market(user)
            market = ensure_market(world_data)
            options = []
            for asset_key, info in MARKET_ASSETS.items():
                owned = int(account["holdings"][asset_key].get("quantity", 0) or 0)
                price = int(market["assets"][asset_key]["price"])
                options.append(
                    discord.SelectOption(
                        label=COIN_DISPLAY_NAMES[asset_key],
                        value=asset_key,
                        description=f"보유 {owned:,}개 · 현재 시세 {price:,} 식량",
                        emoji=info["emoji"],
                    )
                )
            super().__init__(
                placeholder="드롭다운으로 코인 선택",
                min_values=1,
                max_values=1,
                options=options,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            if interaction.user.id != self.menu_view.author_id:
                await interaction.response.send_message(
                    "❌ 이 판매 메뉴는 명령어를 실행한 사람만 사용할 수 있습니다.",
                    ephemeral=True,
                )
                return

            asset_key = self.values[0]
            user = get_user(self.menu_view.author_id)
            account = ensure_user_market(user)
            owned = int(account["holdings"][asset_key].get("quantity", 0) or 0)
            if owned <= 0:
                await interaction.response.send_message(
                    f"⚠️ {MARKET_ASSETS[asset_key]['emoji']} **{COIN_DISPLAY_NAMES[asset_key]}**을 보유하고 있지 않습니다.",
                    ephemeral=True,
                )
                return

            quantity_view = CoinSellQuantityView(self.menu_view.author_id, asset_key)
            quantity_view.message = interaction.message
            await interaction.response.edit_message(
                embed=coin_quantity_embed(self.menu_view.author_id, asset_key),
                view=quantity_view,
            )
            self.menu_view.stop()

    class CoinSellMenuView(discord.ui.View):
        def __init__(self, author_id: int) -> None:
            super().__init__(timeout=180)
            self.author_id = int(author_id)
            self.message = None
            self.add_item(CoinSellSelect(self))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "❌ 이 판매 메뉴는 명령어를 실행한 사람만 사용할 수 있습니다.",
                    ephemeral=True,
                )
                return False
            return True

        async def on_timeout(self) -> None:
            for child in self.children:
                child.disabled = True
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except (discord.HTTPException, discord.NotFound):
                    pass

    async def show_coin_sell_menu(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        await sync_market()
        user = get_user(ctx.author.id)
        account = ensure_user_market(user)
        total_owned = sum(
            int(account["holdings"][key].get("quantity", 0) or 0)
            for key in MARKET_ASSETS
        )
        if total_owned <= 0:
            await ctx.send("📭 판매할 코인이 없습니다. `!코인`으로 코인을 먼저 탐색해보세요.")
            return

        view = CoinSellMenuView(ctx.author.id)
        message = await ctx.send(embed=coin_sale_menu_embed(ctx.author.id), view=view)
        view.message = message

    async def sell_asset(ctx: commands.Context, asset_name: str, quantity_value: Any) -> None:
        if not await check_registered(ctx):
            return
        asset_key = resolve_asset(asset_name)
        if not asset_key:
            await ctx.send("⚠️ 사용법: `!매도`로 드롭다운을 열거나 `!매도 일반 10`을 입력하세요.")
            return

        result = await execute_coin_sale(ctx.author.id, asset_key, quantity_value)
        if not result.get("ok"):
            await ctx.send(str(result.get("message", "⚠️ 판매에 실패했습니다.")))
            return
        await ctx.send(embed=coin_sale_result_embed(result))

    async def show_assets(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        await sync_market()
        user = get_user(ctx.author.id)
        account = ensure_user_market(user)
        market = ensure_market(world_data)

        lines = []
        total_cost = 0
        total_value = 0
        for key, info in MARKET_ASSETS.items():
            position = account["holdings"][key]
            quantity = int(position["quantity"])
            if quantity <= 0:
                continue
            avg_price = int(position["avg_price"])
            current_price = int(market["assets"][key]["price"])
            cost = avg_price * quantity
            value = current_price * quantity
            profit = value - cost
            total_cost += cost
            total_value += value
            sign = "+" if profit >= 0 else ""
            lines.append(
                f"{info['emoji']} **{info['name']}** {quantity:,}개\n"
                f"평단 {avg_price:,} · 현재 {current_price:,} · 평가손익 **{sign}{profit:,}**"
            )

        unrealized = total_value - total_cost
        realized = int(account.get("realized_profit", 0))
        sign_u = "+" if unrealized >= 0 else ""
        sign_r = "+" if realized >= 0 else ""
        body = "\n\n".join(lines) if lines else "보유 중인 암시장 자산이 없습니다."
        await ctx.send(
            f"💼 **[{ctx.author.display_name}의 암시장 자산]**\n"
            f"{body}\n\n"
            f"평가금 **{total_value:,} 식량** · 평가손익 **{sign_u}{unrealized:,}**\n"
            f"누적 실현손익 **{sign_r}{realized:,}** · 누적 수수료 **{int(account.get('fees_paid', 0)):,}**\n"
            f"현금성 식량 **{int(user.get('balance', 0)):,}개**"
        )

    async def show_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        account = ensure_user_market(user)
        trades = list(account.get("trades", []))[-10:]
        if not trades:
            await ctx.send("📜 아직 암시장 거래 기록이 없습니다.")
            return

        lines = []
        for trade in reversed(trades):
            asset_key = trade.get("asset")
            info = MARKET_ASSETS.get(asset_key, {"emoji": "📦", "name": str(asset_key)})
            when = _parse_time(trade.get("time"))
            when_text = when.astimezone(KST).strftime("%m-%d %H:%M") if when else "시간 미상"
            lines.append(
                f"`{when_text}` {info['emoji']} **{trade.get('action', '?')}** "
                f"{info['name']} {int(trade.get('quantity', 0)):,}개 @ {int(trade.get('price', 0)):,}"
            )
        await ctx.send("📜 **[최근 암시장 거래 기록]**\n" + "\n".join(lines))

    # !명령어 호환
    @bot.command(name="시세", aliases=["암시장시세"])
    async def market_price_legacy(ctx: commands.Context) -> None:
        await show_prices(ctx)

    @bot.command(name="매수", aliases=["투자"])
    async def market_buy_legacy(ctx: commands.Context, 종목: str, 수량: str) -> None:
        await buy_asset(ctx, 종목, 수량)

    @bot.command(name="매도", aliases=["코인판매"])
    async def market_sell_legacy(
        ctx: commands.Context,
        종목: Optional[str] = None,
        수량: Optional[str] = None,
    ) -> None:
        if 종목 is None and 수량 is None:
            await show_coin_sell_menu(ctx)
            return
        if 종목 is None or 수량 is None:
            await ctx.send("⚠️ `!매도`로 드롭다운을 열거나 `!매도 일반 10`처럼 입력하세요.")
            return
        await sell_asset(ctx, 종목, 수량)

    @bot.command(name="자산", aliases=["투자자산"])
    async def market_assets_legacy(ctx: commands.Context) -> None:
        await show_assets(ctx)

    @bot.command(name="암시장기록", aliases=["투자기록"])
    async def market_history_legacy(ctx: commands.Context) -> None:
        await show_history(ctx)

    @bot.command(name="도박정보", aliases=["도박도움말", "도박안내"])
    async def gambling_help_legacy(ctx: commands.Context) -> None:
        await show_help(ctx)

    # /암시장 하위 명령어
    @bot.hybrid_group(
        name="암시장",
        aliases=["도박시장"],
        fallback="시세",
        invoke_without_command=True,
        description="실시간 시세를 확인하고 암시장 자산을 거래합니다.",
    )
    async def black_market_group(ctx: commands.Context) -> None:
        await show_prices(ctx)

    @black_market_group.command(name="매수", description="식량으로 암시장 종목을 구매합니다.")
    async def black_market_buy(ctx: commands.Context, 종목: str, 수량: int) -> None:
        await buy_asset(ctx, 종목, 수량)

    @black_market_group.command(name="매도", description="인수를 생략하면 드롭다운에서 보유 코인을 판매합니다.")
    async def black_market_sell(
        ctx: commands.Context,
        종목: Optional[str] = None,
        수량: Optional[str] = None,
    ) -> None:
        if 종목 is None and 수량 is None:
            await show_coin_sell_menu(ctx)
            return
        if 종목 is None or 수량 is None:
            await ctx.send("⚠️ 종목과 수량을 모두 입력하거나, 둘 다 비워 드롭다운을 여세요.")
            return
        await sell_asset(ctx, 종목, 수량)

    @black_market_group.command(name="자산", description="보유 종목의 평가금과 손익을 확인합니다.")
    async def black_market_assets(ctx: commands.Context) -> None:
        await show_assets(ctx)

    @black_market_group.command(name="기록", description="최근 암시장 매수·매도 기록을 확인합니다.")
    async def black_market_history(ctx: commands.Context) -> None:
        await show_history(ctx)

    @black_market_group.command(name="도움말", description="기존 도박과 실시간 암시장 명령어를 확인합니다.")
    async def black_market_help(ctx: commands.Context) -> None:
        await show_help(ctx)

    @tasks.loop(seconds=MARKET_TICK_SECONDS)
    async def market_price_loop() -> None:
        if update_market(world_data, force=True):
            save_data()

    @bot.listen("on_ready")
    async def start_v36_market_loop() -> None:
        if not market_price_loop.is_running():
            market_price_loop.start()
