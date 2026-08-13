from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v37_gambling_experience import _kst_date, _safe_reactions, _signed


CASINO_VERSION = "4.0"
CASINO_CHIP_MIN_EXCHANGE = 100
CASINO_CHIP_MAX_EXCHANGE = 100_000_000
CASINO_SELL_BASE_RATE = 0.90
CASINO_JACKPOT_BASE = 1_000_000
CASINO_JACKPOT_CONTRIBUTION_RATE = 0.02
CASINO_WHEEL_COST = 12_000
CASINO_HISTORY_LIMIT = 50

VIP_TIERS: Sequence[Tuple[str, int, str]] = (
    ("BRONZE", 0, "🥉"),
    ("SILVER", 5_000, "🥈"),
    ("GOLD", 25_000, "🥇"),
    ("PLATINUM", 100_000, "💠"),
    ("DIAMOND", 500_000, "💎"),
    ("BLACK", 2_000_000, "🖤"),
)

DEALERS: Dict[str, Dict[str, Any]] = {
    "리아": {
        "emoji": "🃏",
        "game": "블랙잭",
        "title": "차가운 카드 딜러",
        "lines": [
            "카드는 거짓말하지 않아. 사람만 거짓말하지.",
            "21에 가까워질수록 네 표정은 더 솔직해지네.",
            "히트할지 멈출지, 결국 네가 결정해.",
        ],
    },
    "카인": {
        "emoji": "🎲",
        "game": "다이스",
        "title": "웃지 않는 승부사",
        "lines": [
            "주사위는 공평해. 결과가 잔인할 뿐이지.",
            "운을 믿지 마. 네가 감당할 수 있는 금액만 걸어.",
            "숫자는 이미 정해졌을지도 몰라.",
        ],
    },
    "루나": {
        "emoji": "🎰",
        "game": "슬롯머신",
        "title": "네온 슬롯 관리자",
        "lines": [
            "릴이 멈추는 순간, 네 밤도 결정돼.",
            "잭팟은 누구에게나 열려 있어. 거의 누구에게도 오지 않을 뿐.",
            "빛나는 심벌만 보지 마. 해골도 섞여 있으니까.",
        ],
    },
    "모르간": {
        "emoji": "👑",
        "game": "바카라",
        "title": "BLACK CASINO의 주인",
        "lines": [
            "이곳의 규칙은 단순해. 선택하고, 결과를 받아들여.",
            "VIP가 된다고 운명이 널 봐주는 건 아니야. 다만 문은 더 많이 열리지.",
            "잃은 칩은 카지노에 남고, 이야기는 네게 남는다.",
        ],
    },
}

SHOP_ITEMS: Dict[str, Dict[str, Any]] = {
    "이용권": {
        "name": "카지노 이용권",
        "emoji": "🎟️",
        "price": 25_000,
        "desc": "럭키휠을 무료로 1회 돌립니다.",
    },
    "행운부적": {
        "name": "행운의 부적",
        "emoji": "🍀",
        "price": 80_000,
        "desc": "슬롯 10회 동안 희귀 심벌 등장 가중치를 조금 높입니다.",
    },
    "잭팟부스터": {
        "name": "잭팟 부스터",
        "emoji": "💎",
        "price": 250_000,
        "desc": "슬롯 1회에서 7️⃣ 3개도 누적 잭팟 당첨 대상으로 만듭니다.",
    },
    "VIP패스": {
        "name": "VIP 포인트 패스",
        "emoji": "🪪",
        "price": 500_000,
        "desc": "사용 즉시 VIP 포인트 5,000을 획득합니다.",
    },
    "손실보호권": {
        "name": "손실 보호권",
        "emoji": "🛡️",
        "price": 180_000,
        "desc": "다음 카지노 패배 1회의 손실을 50% 줄입니다.",
    },
}

ACHIEVEMENTS: Sequence[Tuple[str, str, Callable[[Dict[str, Any]], bool]]] = (
    ("첫 입장", "BLACK CASINO에서 첫 게임을 플레이", lambda a: int(a.get("plays", 0)) >= 1),
    ("첫 승리", "카지노에서 첫 승리", lambda a: int(a.get("wins", 0)) >= 1),
    ("단골 손님", "카지노 25판 플레이", lambda a: int(a.get("plays", 0)) >= 25),
    ("밤의 주민", "카지노 100판 플레이", lambda a: int(a.get("plays", 0)) >= 100),
    ("천 번의 선택", "카지노 1,000판 플레이", lambda a: int(a.get("plays", 0)) >= 1000),
    ("뜨거운 손", "5연승 달성", lambda a: int(a.get("best_streak", 0)) >= 5),
    ("멈출 수 없는 손", "10연승 달성", lambda a: int(a.get("best_streak", 0)) >= 10),
    ("기록 파괴자", "20연승 달성", lambda a: int(a.get("best_streak", 0)) >= 20),
    ("고액 배팅", "누적 배팅 1,000,000칩", lambda a: int(a.get("total_bet", 0)) >= 1_000_000),
    ("큰손", "누적 배팅 100,000,000칩", lambda a: int(a.get("total_bet", 0)) >= 100_000_000),
    ("칩 수집가", "보유 칩 1,000,000개", lambda a: int(a.get("chips", 0)) >= 1_000_000),
    ("카지노 재벌", "보유 칩 100,000,000개", lambda a: int(a.get("chips", 0)) >= 100_000_000),
    ("첫 환전", "처음으로 칩을 구매", lambda a: int(a.get("exchange_bought", 0)) > 0),
    ("현금화", "처음으로 칩을 식량으로 판매", lambda a: int(a.get("exchange_sold", 0)) > 0),
    ("VIP SILVER", "SILVER 등급 달성", lambda a: int(a.get("vip_points", 0)) >= 5_000),
    ("VIP GOLD", "GOLD 등급 달성", lambda a: int(a.get("vip_points", 0)) >= 25_000),
    ("VIP PLATINUM", "PLATINUM 등급 달성", lambda a: int(a.get("vip_points", 0)) >= 100_000),
    ("VIP DIAMOND", "DIAMOND 등급 달성", lambda a: int(a.get("vip_points", 0)) >= 500_000),
    ("VIP BLACK", "BLACK 등급 달성", lambda a: int(a.get("vip_points", 0)) >= 2_000_000),
    ("휠 입문", "럭키휠 1회 이용", lambda a: int(a.get("wheel_spins", 0)) >= 1),
    ("휠 중독", "럭키휠 50회 이용", lambda a: int(a.get("wheel_spins", 0)) >= 50),
    ("앞면의 신", "코인플립 10승", lambda a: int(a.get("coinflip_wins", 0)) >= 10),
    ("올인", "올인 승부 1회", lambda a: int(a.get("all_in_plays", 0)) >= 1),
    ("올인 생존자", "올인 승리 1회", lambda a: int(a.get("all_in_wins", 0)) >= 1),
    ("미션 수행자", "일일 카지노 미션 10회 수령", lambda a: int(a.get("mission_claims", 0)) >= 10),
    ("계약 완료", "일일 카지노 미션 100회 수령", lambda a: int(a.get("mission_claims", 0)) >= 100),
    ("행운의 소유자", "행운 수치 25 달성", lambda a: int(a.get("luck", 0)) >= 25),
    ("딜러의 친구", "NPC 친밀도 합계 100", lambda a: sum(int(v) for v in a.get("npc_affinity", {}).values()) >= 100),
    ("잭팟 목격자", "누적 잭팟 1회 당첨", lambda a: int(a.get("jackpot_wins", 0)) >= 1),
    ("잭팟 황제", "누적 잭팟 5회 당첨", lambda a: int(a.get("jackpot_wins", 0)) >= 5),
)


def _metric_at_least(key: str, threshold: int) -> Callable[[Dict[str, Any]], bool]:
    return lambda account, key=key, threshold=threshold: int(account.get(key, 0)) >= threshold


def _game_plays_at_least(game: str, threshold: int) -> Callable[[Dict[str, Any]], bool]:
    return lambda account, game=game, threshold=threshold: int(account.get("game_plays", {}).get(game, 0)) >= threshold


# 장기 운영용 누적·게임별 마일스톤을 더해 총 100종 이상의 업적을 제공합니다.
_extra_achievements: List[Tuple[str, str, Callable[[Dict[str, Any]], bool]]] = []
for threshold in (5, 10, 50, 250, 500, 2_000, 5_000, 10_000):
    _extra_achievements.append((f"카지노 방문 {threshold:,}", f"카지노 게임 {threshold:,}판 플레이", _metric_at_least("plays", threshold)))
for threshold in (5, 10, 25, 50, 100, 250, 500, 1_000):
    _extra_achievements.append((f"승리 기록 {threshold:,}", f"카지노 누적 {threshold:,}승", _metric_at_least("wins", threshold)))
for threshold in (100_000, 500_000, 5_000_000, 10_000_000, 50_000_000, 500_000_000, 1_000_000_000, 10_000_000_000):
    _extra_achievements.append((f"누적 배팅 {threshold:,}", f"누적 배팅 {threshold:,}칩 달성", _metric_at_least("total_bet", threshold)))
for threshold in (10_000, 100_000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000, 10_000_000_000, 100_000_000_000):
    _extra_achievements.append((f"누적 수익 {threshold:,}", f"카지노 누적 순이익 {threshold:,}칩", _metric_at_least("total_profit", threshold)))
for threshold in (10_000, 100_000, 500_000, 5_000_000, 10_000_000, 50_000_000, 500_000_000, 1_000_000_000):
    _extra_achievements.append((f"칩 보유 {threshold:,}", f"카지노 칩 {threshold:,}개 보유", _metric_at_least("chips", threshold)))
for threshold in (5, 10, 25, 100, 250, 500):
    _extra_achievements.append((f"휠 회전 {threshold:,}", f"럭키휠 {threshold:,}회 이용", _metric_at_least("wheel_spins", threshold)))
for threshold in (1, 5, 25, 50, 100, 250):
    _extra_achievements.append((f"코인 승리 {threshold:,}", f"코인플립 {threshold:,}승", _metric_at_least("coinflip_wins", threshold)))
for threshold in (5, 10, 25, 50, 100):
    _extra_achievements.append((f"올인 도전 {threshold:,}", f"올인 승부 {threshold:,}회", _metric_at_least("all_in_plays", threshold)))
for threshold in (3, 5, 10, 25, 50):
    _extra_achievements.append((f"올인 승리 {threshold:,}", f"올인 승부 {threshold:,}승", _metric_at_least("all_in_wins", threshold)))
for threshold in (1, 3, 25, 50, 250, 500):
    _extra_achievements.append((f"미션 보상 {threshold:,}", f"일일 미션 보상 {threshold:,}회 수령", _metric_at_least("mission_claims", threshold)))
for threshold in (1_000_000, 10_000_000, 100_000_000, 1_000_000_000, 10_000_000_000):
    _extra_achievements.append((f"잭팟 누적 {threshold:,}", f"잭팟 누적 당첨액 {threshold:,}칩", _metric_at_least("jackpot_total", threshold)))
for threshold in (100_000, 1_000_000, 10_000_000, 100_000_000):
    _extra_achievements.append((f"칩 구매 {threshold:,}", f"누적 칩 구매 {threshold:,}개", _metric_at_least("exchange_bought", threshold)))
for game in ("블랙잭", "하이로우", "슬롯머신", "다이스", "바카라", "코인플립"):
    for threshold in (10, 50, 100):
        _extra_achievements.append((f"{game} {threshold}판", f"{game} {threshold}회 플레이", _game_plays_at_least(game, threshold)))

ACHIEVEMENTS = tuple(list(ACHIEVEMENTS) + _extra_achievements)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _season_id() -> str:
    return _kst_date()[:7]


def ensure_black_casino_world(world_data: Dict[str, Any]) -> Dict[str, Any]:
    casino = world_data.setdefault("black_casino", {})
    if not isinstance(casino, dict):
        casino = {}
        world_data["black_casino"] = casino
    casino.setdefault("jackpot", CASINO_JACKPOT_BASE)
    casino.setdefault("jackpot_total_contributed", 0)
    casino.setdefault("jackpot_wins", 0)
    casino.setdefault("last_jackpot_winner", "")
    casino.setdefault("last_jackpot_amount", 0)
    casino.setdefault("last_jackpot_at", "")
    casino.setdefault("season", _season_id())
    casino.setdefault("season_started_at", _utc_now().isoformat())
    if casino.get("season") != _season_id():
        casino["season"] = _season_id()
        casino["season_started_at"] = _utc_now().isoformat()
    casino["jackpot"] = max(CASINO_JACKPOT_BASE, int(casino.get("jackpot", CASINO_JACKPOT_BASE) or CASINO_JACKPOT_BASE))
    return casino


def _new_daily_missions() -> List[Dict[str, Any]]:
    pool = [
        {"key": "play", "title": "카지노 게임 3회", "target": 3, "reward_chips": 6_500, "reward_vip": 100},
        {"key": "win", "title": "카지노 승리 2회", "target": 2, "reward_chips": 9_500, "reward_vip": 150},
        {"key": "bet", "title": "누적 25,000칩 배팅", "target": 25_000, "reward_chips": 12_000, "reward_vip": 180},
        {"key": "슬롯머신", "title": "슬롯 5회", "target": 5, "reward_chips": 8_000, "reward_vip": 120},
        {"key": "블랙잭", "title": "블랙잭 3회", "target": 3, "reward_chips": 8_000, "reward_vip": 120},
        {"key": "하이로우", "title": "하이로우 3회", "target": 3, "reward_chips": 8_000, "reward_vip": 120},
        {"key": "다이스", "title": "다이스 4회", "target": 4, "reward_chips": 7_000, "reward_vip": 110},
        {"key": "바카라", "title": "바카라 3회", "target": 3, "reward_chips": 8_500, "reward_vip": 130},
    ]
    selected = random.sample(pool, 3)
    return [dict(item, progress=0, claimed=False) for item in selected]


def ensure_black_casino_account(user: Dict[str, Any]) -> Dict[str, Any]:
    account = user.setdefault("black_casino", {})
    if not isinstance(account, dict):
        account = {}
        user["black_casino"] = account
    defaults: Dict[str, Any] = {
        "chips": 0,
        "vip_points": 0,
        "luck": 0,
        "tickets": 1,
        "plays": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "best_streak": 0,
        "current_streak": 0,
        "total_bet": 0,
        "total_profit": 0,
        "highest_payout": 0,
        "exchange_bought": 0,
        "exchange_sold": 0,
        "wheel_spins": 0,
        "coinflip_wins": 0,
        "all_in_plays": 0,
        "all_in_wins": 0,
        "mission_claims": 0,
        "jackpot_wins": 0,
        "jackpot_total": 0,
        "achievements": [],
        "pending_achievements": [],
        "inventory": {},
        "npc_affinity": {},
        "game_plays": {},
        "history": [],
        "daily": {},
        "season": {},
    }
    for key, value in defaults.items():
        if isinstance(value, dict):
            if not isinstance(account.get(key), dict):
                account[key] = {}
            else:
                account.setdefault(key, {})
        elif isinstance(value, list):
            if not isinstance(account.get(key), list):
                account[key] = []
            else:
                account.setdefault(key, [])
        else:
            account.setdefault(key, value)

    inventory = account["inventory"]
    for key in SHOP_ITEMS:
        inventory.setdefault(key, 0)
        inventory[key] = max(0, int(inventory.get(key, 0) or 0))
    inventory.setdefault("행운부적_충전", 0)

    for name in DEALERS:
        account["npc_affinity"].setdefault(name, 0)

    daily = account["daily"]
    if daily.get("date") != _kst_date():
        daily.clear()
        daily.update({
            "date": _kst_date(),
            "missions": _new_daily_missions(),
            "free_ticket_claimed": False,
            "profit": 0,
            "plays": 0,
            "wins": 0,
            "bet": 0,
        })
    if not isinstance(daily.get("missions"), list):
        daily["missions"] = _new_daily_missions()
    for key in ("profit", "plays", "wins", "bet"):
        daily[key] = int(daily.get(key, 0) or 0)

    season = account["season"]
    if season.get("id") != _season_id():
        season.clear()
        season.update({"id": _season_id(), "profit": 0, "plays": 0, "wins": 0, "bet": 0})

    account["chips"] = int(account.get("chips", 0) or 0)
    account["vip_points"] = max(0, int(account.get("vip_points", 0) or 0))
    account["luck"] = max(0, min(100, int(account.get("luck", 0) or 0)))
    account["tickets"] = max(0, int(account.get("tickets", 0) or 0))
    return account


def casino_chips(user: Dict[str, Any]) -> int:
    return int(ensure_black_casino_account(user).get("chips", 0))


def set_casino_chips(user: Dict[str, Any], amount: int) -> int:
    account = ensure_black_casino_account(user)
    account["chips"] = int(amount)
    return int(account["chips"])


def add_casino_chips(user: Dict[str, Any], amount: int) -> int:
    return set_casino_chips(user, casino_chips(user) + int(amount))


def vip_info(user: Dict[str, Any]) -> Tuple[str, int, str, int, Optional[int]]:
    account = ensure_black_casino_account(user)
    points = int(account.get("vip_points", 0))
    current = VIP_TIERS[0]
    next_threshold: Optional[int] = None
    for index, tier in enumerate(VIP_TIERS):
        if points >= tier[1]:
            current = tier
            if index + 1 < len(VIP_TIERS):
                next_threshold = VIP_TIERS[index + 1][1]
        else:
            break
    return current[0], current[1], current[2], points, next_threshold


def vip_rank_index(user: Dict[str, Any]) -> int:
    name = vip_info(user)[0]
    return next((i for i, tier in enumerate(VIP_TIERS) if tier[0] == name), 0)


def chip_sell_rate(user: Dict[str, Any]) -> float:
    return min(0.95, CASINO_SELL_BASE_RATE + vip_rank_index(user) * 0.008)


def shop_discount(user: Dict[str, Any]) -> float:
    return min(0.20, vip_rank_index(user) * 0.04)


def daily_loss_bonus(user: Dict[str, Any]) -> int:
    return vip_rank_index(user) * 5_000_000


def slot_symbol_weights(user: Dict[str, Any], symbols: Sequence[Tuple[str, float]]) -> List[float]:
    account = ensure_black_casino_account(user)
    luck = int(account.get("luck", 0))
    charge = int(account["inventory"].get("행운부적_충전", 0))
    vip = vip_rank_index(user)
    bonus = luck // 14 + vip + (3 if charge > 0 else 0)
    rare_symbols = {"👑", "7️⃣", "💠"}
    weights: List[float] = []
    for symbol, base in symbols:
        if symbol in rare_symbols:
            weights.append(max(1.0, float(base) + bonus))
        elif symbol == "💀":
            weights.append(max(1.0, float(base)))
        else:
            weights.append(max(1.0, float(base) - bonus // 2))
    return weights


def consume_slot_buffs(user: Dict[str, Any]) -> Dict[str, bool]:
    account = ensure_black_casino_account(user)
    inventory = account["inventory"]
    result = {"charm": False, "booster": False}
    charge = int(inventory.get("행운부적_충전", 0))
    if charge > 0:
        inventory["행운부적_충전"] = charge - 1
        result["charm"] = True
    booster = int(inventory.get("잭팟부스터", 0))
    if booster > 0:
        inventory["잭팟부스터"] = booster - 1
        result["booster"] = True
    return result


def apply_loss_shield(user: Dict[str, Any], delta: int) -> Tuple[int, int]:
    if delta >= 0:
        return int(delta), 0
    account = ensure_black_casino_account(user)
    inventory = account["inventory"]
    if int(inventory.get("손실보호권", 0)) <= 0:
        return int(delta), 0
    inventory["손실보호권"] = int(inventory.get("손실보호권", 0)) - 1
    protected = max(1, abs(int(delta)) // 2)
    return int(delta) + protected, protected


def contribute_jackpot(world_data: Dict[str, Any], bet: int, multiplier: float = 1.0) -> int:
    world = ensure_black_casino_world(world_data)
    contribution = max(1, int(int(bet) * CASINO_JACKPOT_CONTRIBUTION_RATE * max(0.1, multiplier)))
    world["jackpot"] = int(world.get("jackpot", CASINO_JACKPOT_BASE)) + contribution
    world["jackpot_total_contributed"] = int(world.get("jackpot_total_contributed", 0)) + contribution
    return contribution


def claim_jackpot(user: Dict[str, Any], world_data: Dict[str, Any], winner_id: int) -> int:
    world = ensure_black_casino_world(world_data)
    account = ensure_black_casino_account(user)
    amount = int(world.get("jackpot", CASINO_JACKPOT_BASE))
    world["jackpot"] = CASINO_JACKPOT_BASE
    world["jackpot_wins"] = int(world.get("jackpot_wins", 0)) + 1
    world["last_jackpot_winner"] = str(winner_id)
    world["last_jackpot_amount"] = amount
    world["last_jackpot_at"] = _utc_now().isoformat()
    account["jackpot_wins"] = int(account.get("jackpot_wins", 0)) + 1
    account["jackpot_total"] = int(account.get("jackpot_total", 0)) + amount
    return amount


def _progress_daily(account: Dict[str, Any], game: str, bet: int, delta: int) -> None:
    daily = account["daily"]
    for mission in daily.get("missions", []):
        if mission.get("claimed"):
            continue
        key = mission.get("key")
        progress = int(mission.get("progress", 0))
        if key == "play":
            progress += 1
        elif key == "win" and delta > 0:
            progress += 1
        elif key == "bet":
            progress += int(bet)
        elif key == game:
            progress += 1
        mission["progress"] = min(int(mission.get("target", 0)), progress)


def _dealer_for_game(game: str) -> str:
    for name, info in DEALERS.items():
        if info["game"] == game:
            return name
    return "모르간"


def dealer_line(game: str) -> str:
    name = _dealer_for_game(game)
    info = DEALERS[name]
    return f"{info['emoji']} **딜러 {name}:** “{random.choice(info['lines'])}”"


def check_achievements(user: Dict[str, Any]) -> List[str]:
    account = ensure_black_casino_account(user)
    unlocked = set(str(v) for v in account.get("achievements", []))
    new_items: List[str] = []
    for name, _desc, condition in ACHIEVEMENTS:
        if name in unlocked:
            continue
        try:
            passed = bool(condition(account))
        except (TypeError, ValueError, KeyError):
            passed = False
        if passed:
            account["achievements"].append(name)
            account["pending_achievements"].append(name)
            new_items.append(name)
    del account["pending_achievements"][:-20]
    return new_items


def record_black_casino_game(
    user: Dict[str, Any],
    world_data: Dict[str, Any],
    game: str,
    bet: int,
    delta: int,
    payout: int,
    detail: str,
) -> Dict[str, Any]:
    account = ensure_black_casino_account(user)
    ensure_black_casino_world(world_data)
    account["plays"] = int(account.get("plays", 0)) + 1
    account["total_bet"] = int(account.get("total_bet", 0)) + int(bet)
    account["total_profit"] = int(account.get("total_profit", 0)) + int(delta)
    account["highest_payout"] = max(int(account.get("highest_payout", 0)), int(payout))
    account["game_plays"][game] = int(account["game_plays"].get(game, 0)) + 1
    account["vip_points"] = int(account.get("vip_points", 0)) + max(1, int(bet) // 1000) + (25 if delta > 0 else 5)

    if delta > 0:
        account["wins"] = int(account.get("wins", 0)) + 1
        account["current_streak"] = int(account.get("current_streak", 0)) + 1
        account["best_streak"] = max(int(account.get("best_streak", 0)), int(account["current_streak"]))
    elif delta < 0:
        account["losses"] = int(account.get("losses", 0)) + 1
        account["current_streak"] = 0
    else:
        account["draws"] = int(account.get("draws", 0)) + 1

    dealer = _dealer_for_game(game)
    account["npc_affinity"][dealer] = int(account["npc_affinity"].get(dealer, 0)) + (2 if delta > 0 else 1)

    daily = account["daily"]
    daily["profit"] = int(daily.get("profit", 0)) + int(delta)
    daily["plays"] = int(daily.get("plays", 0)) + 1
    daily["bet"] = int(daily.get("bet", 0)) + int(bet)
    if delta > 0:
        daily["wins"] = int(daily.get("wins", 0)) + 1

    season = account["season"]
    season["profit"] = int(season.get("profit", 0)) + int(delta)
    season["plays"] = int(season.get("plays", 0)) + 1
    season["bet"] = int(season.get("bet", 0)) + int(bet)
    if delta > 0:
        season["wins"] = int(season.get("wins", 0)) + 1

    _progress_daily(account, game, int(bet), int(delta))
    contribution = contribute_jackpot(world_data, int(bet), 1.0 + vip_rank_index(user) * 0.05)
    account["history"].append({
        "time": _utc_now().isoformat(),
        "game": game,
        "bet": int(bet),
        "delta": int(delta),
        "payout": int(payout),
        "chips": casino_chips(user),
        "detail": detail,
        "jackpot_contribution": contribution,
    })
    del account["history"][:-CASINO_HISTORY_LIMIT]
    check_achievements(user)
    return account


def pending_achievement_text(user: Dict[str, Any]) -> str:
    account = ensure_black_casino_account(user)
    pending = list(account.get("pending_achievements", []))
    if not pending:
        return ""
    account["pending_achievements"] = []
    shown = pending[-3:]
    suffix = f" 외 {len(pending) - 3}개" if len(pending) > 3 else ""
    return "\n🏅 **새 업적:** " + ", ".join(shown) + suffix


def register_v40_casino_commands(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Dict[str, Any]],
) -> None:
    """V4.0 BLACK CASINO의 칩, VIP, 잭팟, 미션, 상점, NPC, 시즌 콘텐츠를 등록합니다."""
    ensure_black_casino_world(world_data)
    casino_group = bot.get_command("카지노")
    if not isinstance(casino_group, commands.HybridGroup):
        raise RuntimeError("V4.0 카지노 확장 등록 실패: 기존 카지노 그룹을 찾을 수 없습니다.")

    async def require_user(ctx: commands.Context) -> Optional[Dict[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        ensure_black_casino_account(user)
        return user

    async def show_chip_status(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        account = ensure_black_casino_account(user)
        tier, _, emoji, points, next_threshold = vip_info(user)
        next_text = "최고 등급" if next_threshold is None else f"다음 등급까지 {max(0, next_threshold - points):,}P"
        embed = discord.Embed(title="🪙 BLACK CASINO 칩 지갑", color=discord.Color.gold())
        embed.add_field(name="카지노 칩", value=f"**{casino_chips(user):,}칩**", inline=True)
        embed.add_field(name="보유 식량", value=f"**{int(user.get('balance', 0)):,}개**", inline=True)
        embed.add_field(name="VIP", value=f"{emoji} **{tier}** · {points:,}P\n{next_text}", inline=True)
        embed.add_field(name="럭키휠 이용권", value=f"**{int(account.get('tickets', 0))}장**", inline=True)
        embed.add_field(name="행운", value=f"**{int(account.get('luck', 0))}/100**", inline=True)
        embed.add_field(name="판매 환율", value=f"1칩 → **{chip_sell_rate(user):.3f} 식량**", inline=True)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.set_footer(text="인게임 전용 재화 · 현금 환전 불가")
        await ctx.send(embed=embed)

    async def exchange(ctx: commands.Context, direction: str, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        text = str(direction).strip().lower()
        aliases = {"구매": "구매", "충전": "구매", "식량to칩": "구매", "buy": "구매", "판매": "판매", "환급": "판매", "칩to식량": "판매", "sell": "판매"}
        action = aliases.get(text)
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            amount = 0
        if action is None or not (CASINO_CHIP_MIN_EXCHANGE <= amount <= CASINO_CHIP_MAX_EXCHANGE):
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                "⚠️ 사용법: `!카지노환전 구매 10000` 또는 `!카지노환전 판매 10000`\n"
                f"환전 범위 **{CASINO_CHIP_MIN_EXCHANGE:,} ~ {CASINO_CHIP_MAX_EXCHANGE:,}**"
            )
            return
        account = ensure_black_casino_account(user)
        if action == "구매":
            if int(user.get("balance", 0)) < amount:
                ctx.command.reset_cooldown(ctx)
                await ctx.send(f"⚠️ 식량이 부족합니다. 보유 **{int(user.get('balance', 0)):,}개**")
                return
            user["balance"] = int(user.get("balance", 0)) - amount
            add_casino_chips(user, amount)
            account["exchange_bought"] = int(account.get("exchange_bought", 0)) + amount
            result = f"식량 **{amount:,}개**를 카지노 칩 **{amount:,}개**로 교환했습니다."
        else:
            if casino_chips(user) < amount:
                ctx.command.reset_cooldown(ctx)
                await ctx.send(f"⚠️ 카지노 칩이 부족합니다. 보유 **{casino_chips(user):,}칩**")
                return
            rate = chip_sell_rate(user)
            food = max(1, int(math.floor(amount * rate)))
            add_casino_chips(user, -amount)
            user["balance"] = int(user.get("balance", 0)) + food
            account["exchange_sold"] = int(account.get("exchange_sold", 0)) + amount
            result = f"카지노 칩 **{amount:,}개**를 식량 **{food:,}개**로 환급했습니다.\nVIP 적용 환율 **{rate:.3f}**"
        check_achievements(user)
        save_data()
        await ctx.send(
            f"🔄 **카지노 환전 완료**\n{result}\n"
            f"현재 **{casino_chips(user):,}칩** · 식량 **{int(user.get('balance', 0)):,}개**"
            f"{pending_achievement_text(user)}"
        )

    async def show_vip(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        tier, threshold, emoji, points, next_threshold = vip_info(user)
        lines = []
        for name, need, mark in VIP_TIERS:
            state = "✅" if points >= need else "🔒"
            lines.append(f"{state} {mark} **{name}** · {need:,}P")
        next_text = "BLACK 최고 등급을 달성했습니다." if next_threshold is None else f"다음 등급까지 **{next_threshold - points:,}P**"
        embed = discord.Embed(
            title=f"{emoji} 카지노 VIP · {tier}",
            description=f"현재 **{points:,}P** · {next_text}",
            color=discord.Color.gold(),
        )
        embed.add_field(name="등급표", value="\n".join(lines), inline=False)
        embed.add_field(
            name="현재 혜택",
            value=(
                f"칩 판매 환율 **{chip_sell_rate(user):.3f}**\n"
                f"NPC 상점 할인 **{shop_discount(user) * 100:.0f}%**\n"
                f"카지노 손실 보호 한도 추가 **{daily_loss_bonus(user):,}칩**\n"
                "희귀 슬롯 심벌 가중치 소폭 증가"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    async def show_jackpot(ctx: commands.Context) -> None:
        world = ensure_black_casino_world(world_data)
        last = "기록 없음"
        if world.get("last_jackpot_winner"):
            last = f"<@{world['last_jackpot_winner']}> · {int(world.get('last_jackpot_amount', 0)):,}칩"
        embed = discord.Embed(
            title="💎 전 서버 누적 잭팟",
            description=f"# {int(world.get('jackpot', CASINO_JACKPOT_BASE)):,} 칩",
            color=discord.Color.purple(),
        )
        embed.add_field(name="누적 방식", value="모든 BLACK CASINO 게임 배팅의 2% 이상이 서버 공용 잭팟에 쌓입니다.", inline=False)
        embed.add_field(name="당첨 조건", value="슬롯 💠💠💠 · 부스터 사용 시 7️⃣7️⃣7️⃣도 당첨", inline=False)
        embed.add_field(name="최근 당첨", value=last, inline=False)
        embed.set_footer(text="당첨 뒤 기본 잭팟 1,000,000칩으로 재시작")
        await ctx.send(embed=embed)

    async def show_missions(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        account = ensure_black_casino_account(user)
        lines = []
        for index, mission in enumerate(account["daily"].get("missions", []), start=1):
            progress = int(mission.get("progress", 0))
            target = int(mission.get("target", 0))
            if mission.get("claimed"):
                mark = "✅"
            elif progress >= target:
                mark = "🎁"
            else:
                mark = "▫️"
            lines.append(
                f"{mark} **{index}. {mission.get('title')}** · {progress:,}/{target:,}\n"
                f"└ 보상 {int(mission.get('reward_chips', 0)):,}칩 + VIP {int(mission.get('reward_vip', 0))}P"
            )
        embed = discord.Embed(
            title=f"📅 일일 카지노 미션 · {_kst_date()}",
            description="\n".join(lines) if lines else "미션이 없습니다.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="수령: /카지노 미션보상 번호 · !카지노미션보상 번호 · 0 입력 시 전부 수령")
        await ctx.send(embed=embed)

    async def claim_mission(ctx: commands.Context, number: int = 0) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        account = ensure_black_casino_account(user)
        missions = account["daily"].get("missions", [])
        targets = range(len(missions)) if int(number) == 0 else [int(number) - 1]
        claimed = 0
        chips = 0
        vip = 0
        for index in targets:
            if index < 0 or index >= len(missions):
                continue
            mission = missions[index]
            if mission.get("claimed") or int(mission.get("progress", 0)) < int(mission.get("target", 0)):
                continue
            mission["claimed"] = True
            claimed += 1
            chips += int(mission.get("reward_chips", 0))
            vip += int(mission.get("reward_vip", 0))
        if claimed <= 0:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 수령 가능한 미션이 없습니다.")
            return
        add_casino_chips(user, chips)
        account["vip_points"] = int(account.get("vip_points", 0)) + vip
        account["mission_claims"] = int(account.get("mission_claims", 0)) + claimed
        if all(bool(m.get("claimed")) for m in missions):
            account["tickets"] = int(account.get("tickets", 0)) + 1
            completion = "\n🎟️ **오늘 미션 전체 완료 보너스: 이용권 1장**"
        else:
            completion = ""
        check_achievements(user)
        save_data()
        await ctx.send(
            f"🎁 미션 **{claimed}개** 보상 수령\n+{chips:,}칩 · VIP +{vip:,}P{completion}"
            f"{pending_achievement_text(user)}"
        )

    async def show_achievements(ctx: commands.Context, page: int = 1) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        account = ensure_black_casino_account(user)
        check_achievements(user)
        unlocked = set(account.get("achievements", []))
        page_size = 20
        max_page = max(1, math.ceil(len(ACHIEVEMENTS) / page_size))
        page = max(1, min(max_page, int(page)))
        start = (page - 1) * page_size
        lines = []
        for name, desc, _condition in ACHIEVEMENTS[start:start + page_size]:
            mark = "✅" if name in unlocked else "🔒"
            lines.append(f"{mark} **{name}** · {desc}")
        achievement_note = pending_achievement_text(user)
        embed = discord.Embed(
            title=f"🏅 카지노 업적 {len(unlocked)}/{len(ACHIEVEMENTS)} · {page}/{max_page}",
            description="\n".join(lines) + achievement_note,
            color=discord.Color.gold(),
        )
        embed.set_footer(text="페이지: /카지노 업적 페이지 · !카지노업적 페이지")
        save_data()
        await ctx.send(embed=embed)

    async def show_shop(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        discount = shop_discount(user)
        lines = []
        for key, item in SHOP_ITEMS.items():
            price = max(1, int(item["price"] * (1.0 - discount)))
            lines.append(f"{item['emoji']} **{key}** · {price:,}칩\n└ {item['desc']}")
        embed = discord.Embed(
            title="🛍️ 딜러 리아의 카지노 상점",
            description="\n\n".join(lines),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="VIP 할인", value=f"현재 **{discount * 100:.0f}%**", inline=True)
        embed.add_field(name="보유 칩", value=f"**{casino_chips(user):,}칩**", inline=True)
        embed.set_footer(text="구매: /카지노 구매 상품 수량 · !카지노구매 상품 수량")
        await ctx.send(embed=embed)

    async def buy_shop(ctx: commands.Context, item_name: str, quantity: int = 1) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        key = str(item_name).replace(" ", "")
        aliases = {"티켓": "이용권", "부적": "행운부적", "부스터": "잭팟부스터", "패스": "VIP패스", "보호권": "손실보호권"}
        key = aliases.get(key, key)
        item = SHOP_ITEMS.get(key)
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 0
        if item is None or quantity < 1 or quantity > 20:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ 상품명과 수량을 확인하세요. 한 번에 1~20개 구매할 수 있습니다.")
            return
        account = ensure_black_casino_account(user)
        unit = max(1, int(item["price"] * (1.0 - shop_discount(user))))
        total = unit * quantity
        if casino_chips(user) < total:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 칩이 부족합니다. 필요 **{total:,}칩** · 보유 **{casino_chips(user):,}칩**")
            return
        add_casino_chips(user, -total)
        if key == "이용권":
            account["tickets"] = int(account.get("tickets", 0)) + quantity
        elif key == "행운부적":
            account["inventory"]["행운부적"] = int(account["inventory"].get("행운부적", 0)) + quantity
            account["inventory"]["행운부적_충전"] = int(account["inventory"].get("행운부적_충전", 0)) + 10 * quantity
            account["luck"] = min(100, int(account.get("luck", 0)) + quantity)
        elif key == "VIP패스":
            account["vip_points"] = int(account.get("vip_points", 0)) + 5_000 * quantity
        else:
            account["inventory"][key] = int(account["inventory"].get(key, 0)) + quantity
        check_achievements(user)
        save_data()
        await ctx.send(
            f"🛍️ **{item['name']} {quantity}개 구매 완료**\n-{total:,}칩 · 남은 칩 **{casino_chips(user):,}**"
            f"{pending_achievement_text(user)}"
        )

    async def wheel(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        account = ensure_black_casino_account(user)
        used_ticket = int(account.get("tickets", 0)) > 0
        if used_ticket:
            account["tickets"] = int(account.get("tickets", 0)) - 1
            cost_text = "이용권 1장"
        else:
            if casino_chips(user) < CASINO_WHEEL_COST:
                ctx.command.reset_cooldown(ctx)
                await ctx.send(f"⚠️ 이용권이 없고 휠 비용 **{CASINO_WHEEL_COST:,}칩**도 부족합니다.")
                return
            add_casino_chips(user, -CASINO_WHEEL_COST)
            cost_text = f"{CASINO_WHEEL_COST:,}칩"
        suspense = await ctx.send(f"🎡 **럭키휠 회전!**\n사용: {cost_text}\n`💰 🎁 💀 💎 ⭐ 🎟️`")
        for text in ("휠이 빠르게 회전합니다...", "속도가 조금씩 줄어듭니다...", "바늘이 마지막 칸을 지나갑니다..."):
            await asyncio.sleep(0.55)
            try:
                await suspense.edit(content=f"🎡 **{text}**\n`💰 🎁 💀 💎 ⭐ 🎟️`")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                pass
        outcomes = [
            ("💀 꽝", 30, 0, 0, 0),
            ("💰 5,000칩", 29, 5_000, 0, 0),
            ("🎁 15,000칩", 20, 15_000, 0, 0),
            ("⭐ VIP 500P", 11, 0, 500, 0),
            ("🍀 행운 +3", 6, 0, 0, 3),
            ("💎 100,000칩", 2.5, 100_000, 0, 0),
            ("🎟️ 이용권 3장", 0.5, 0, 0, 0),
        ]
        result = random.choices(outcomes, weights=[o[1] for o in outcomes], k=1)[0]
        label, _weight, chips, vip, luck = result
        if chips:
            add_casino_chips(user, chips)
        if vip:
            account["vip_points"] = int(account.get("vip_points", 0)) + vip
        if luck:
            account["luck"] = min(100, int(account.get("luck", 0)) + luck)
        if label.startswith("🎟️"):
            account["tickets"] = int(account.get("tickets", 0)) + 3
        account["wheel_spins"] = int(account.get("wheel_spins", 0)) + 1
        check_achievements(user)
        save_data()
        try:
            await suspense.edit(content=f"🎡 **럭키휠 결과**\n# {label}\n현재 **{casino_chips(user):,}칩**{pending_achievement_text(user)}")
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass
        await _safe_reactions(suspense, ("🎡", "🎉") if not label.startswith("💀") else ("🎡", "💀", "😭"))

    async def coinflip(ctx: commands.Context, choice: str, bet: int, all_in: bool = False) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        normalized = {"앞": "앞", "앞면": "앞", "head": "앞", "heads": "앞", "뒤": "뒤", "뒷면": "뒤", "tail": "뒤", "tails": "뒤"}.get(str(choice).lower())
        if normalized is None:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ `앞` 또는 `뒤`를 선택하세요.")
            return
        if all_in:
            bet = casino_chips(user)
        invalid_amount = int(bet) < 100 or casino_chips(user) < int(bet)
        if not all_in:
            invalid_amount = invalid_amount or int(bet) > 100_000_000
        if invalid_amount:
            ctx.command.reset_cooldown(ctx)
            limit_text = "보유 칩 전액" if all_in else "100~100,000,000칩"
            await ctx.send(f"⚠️ 배팅 범위 {limit_text} · 보유 **{casino_chips(user):,}칩**")
            return
        before = casino_chips(user)
        add_casino_chips(user, -int(bet))
        message = await ctx.send(f"🪙 **코인이 공중으로 올라갑니다...**\n선택 **{normalized}** · 배팅 **{int(bet):,}칩**")
        await asyncio.sleep(0.75)
        actual = random.choice(["앞", "뒤"])
        payout = int(bet) * 2 if actual == normalized else 0
        add_casino_chips(user, payout)
        delta = casino_chips(user) - before
        protected = 0
        if delta < 0:
            adjusted, protected = apply_loss_shield(user, delta)
            if adjusted != delta:
                add_casino_chips(user, adjusted - delta)
                delta = adjusted
        account = ensure_black_casino_account(user)
        if delta > 0:
            account["coinflip_wins"] = int(account.get("coinflip_wins", 0)) + 1
        if all_in:
            account["all_in_plays"] = int(account.get("all_in_plays", 0)) + 1
            if delta > 0:
                account["all_in_wins"] = int(account.get("all_in_wins", 0)) + 1
        from apocalypse_bot.commands.v39_casino import _record_casino
        detail = f"결과 {actual} · 선택 {normalized}" + (f" · 손실 보호 {protected:,}칩" if protected else "")
        _record_casino(user, "코인플립", int(bet), delta, payout, detail, world_data)
        save_data()
        result_text = "✅ 적중" if delta > 0 else "❌ 실패"
        try:
            await message.edit(content=f"🪙 **코인플립 {result_text}**\n결과 **{actual}** · 손익 **{_signed(delta)}칩**\n현재 **{casino_chips(user):,}칩**{pending_achievement_text(user)}")
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass
        await _safe_reactions(message, ("🪙", "🎉", "💰") if delta > 0 else ("🪙", "😭", "❌"))

    async def show_dealers(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        account = ensure_black_casino_account(user)
        lines = []
        for name, info in DEALERS.items():
            affinity = int(account["npc_affinity"].get(name, 0))
            lines.append(
                f"{info['emoji']} **{name}** · {info['title']} · 담당 {info['game']}\n"
                f"└ 친밀도 {affinity} · “{random.choice(info['lines'])}”"
            )
        embed = discord.Embed(title="🤖 BLACK CASINO 딜러", description="\n\n".join(lines), color=discord.Color.dark_teal())
        await ctx.send(embed=embed)

    async def season_ranking(ctx: commands.Context, scope: str = "시즌", page: int = 1) -> None:
        aliases = {
            "시즌": "시즌", "season": "시즌", "월간": "시즌",
            "전체": "전체", "누적": "전체", "all": "전체",
            "오늘": "오늘", "일간": "오늘", "daily": "오늘",
        }
        normalized = aliases.get(str(scope).strip().lower())
        if normalized is None:
            await ctx.send("⚠️ 구분은 `시즌`, `전체`, `오늘` 중 하나입니다. 예: `!카지노시즌랭킹 오늘 1`")
            return
        rankings: List[Tuple[str, int, int, int]] = []
        season = _season_id()
        for uid, candidate in user_data.items():
            if not isinstance(candidate, dict):
                continue
            account = ensure_black_casino_account(candidate)
            if normalized == "시즌":
                stats = account.get("season", {})
                if stats.get("id") != season:
                    continue
            elif normalized == "오늘":
                stats = account.get("daily", {})
                if stats.get("date") != _kst_date():
                    continue
            else:
                stats = account
            plays = int(stats.get("plays", 0))
            if plays <= 0:
                continue
            rankings.append((str(uid), int(stats.get("profit" if normalized != "전체" else "total_profit", 0)), int(stats.get("wins", 0)), plays))
        rankings.sort(key=lambda row: (row[1], row[2], -row[3]), reverse=True)
        rankings = rankings[:100]
        if not rankings:
            await ctx.send(f"📭 {normalized} 카지노 기록이 없습니다.")
            return
        page_size = 20
        max_page = max(1, math.ceil(len(rankings) / page_size))
        page = max(1, min(max_page, int(page)))
        start_index = (page - 1) * page_size
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for rank, (uid, profit, wins, plays) in enumerate(rankings[start_index:start_index + page_size], start=start_index + 1):
            mark = medals[rank - 1] if rank <= 3 else f"`{rank}.`"
            lines.append(f"{mark} <@{uid}> · **{_signed(profit)}칩** · {wins}승/{plays}판")
        title_suffix = season if normalized == "시즌" else (_kst_date() if normalized == "오늘" else "누적")
        embed = discord.Embed(
            title=f"🏆 BLACK CASINO {normalized} TOP100 · {title_suffix}",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"페이지 {page}/{max_page} · !카지노시즌랭킹 시즌/전체/오늘 페이지")
        await ctx.send(embed=embed)

    # /카지노 하위 명령어
    @casino_group.command(name="환전", description="식량과 카지노 칩을 교환합니다.")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def casino_exchange_cmd(ctx: commands.Context, 방향: str, 금액: int) -> None:
        await exchange(ctx, 방향, 금액)

    @casino_group.command(name="vip", description="카지노 VIP 등급과 혜택을 확인합니다.")
    async def casino_vip_cmd(ctx: commands.Context) -> None:
        await show_vip(ctx)

    @casino_group.command(name="잭팟", description="전 서버 누적 잭팟을 확인합니다.")
    async def casino_jackpot_cmd(ctx: commands.Context) -> None:
        await show_jackpot(ctx)

    @casino_group.command(name="미션", description="오늘의 카지노 미션을 확인합니다.")
    async def casino_mission_cmd(ctx: commands.Context) -> None:
        await show_missions(ctx)

    @casino_group.command(name="미션보상", description="완료한 카지노 미션 보상을 수령합니다. 0은 전부 수령")
    async def casino_mission_claim_cmd(ctx: commands.Context, 번호: int = 0) -> None:
        await claim_mission(ctx, 번호)

    @casino_group.command(name="업적", description="BLACK CASINO 100종 이상 업적을 페이지별로 확인합니다.")
    async def casino_achievement_cmd(ctx: commands.Context, 페이지: int = 1) -> None:
        await show_achievements(ctx, 페이지)

    @casino_group.command(name="상점", description="카지노 전용 NPC 상점을 확인합니다.")
    async def casino_shop_cmd(ctx: commands.Context) -> None:
        await show_shop(ctx)

    @casino_group.command(name="구매", description="카지노 NPC 상점에서 아이템을 구매합니다.")
    async def casino_buy_cmd(ctx: commands.Context, 상품: str, 수량: int = 1) -> None:
        await buy_shop(ctx, 상품, 수량)

    @casino_group.command(name="럭키휠", description="이용권 또는 칩으로 럭키휠을 돌립니다.")
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def casino_wheel_cmd(ctx: commands.Context) -> None:
        await wheel(ctx)

    @casino_group.command(name="코인플립", description="앞면 또는 뒷면에 카지노 칩을 배팅합니다.")
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def casino_coinflip_cmd(ctx: commands.Context, 선택: str, 배팅액: int) -> None:
        await coinflip(ctx, 선택, 배팅액)

    @casino_group.command(name="올인", description="보유 카지노 칩 전부를 코인플립에 배팅합니다.")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def casino_allin_cmd(ctx: commands.Context, 선택: str) -> None:
        await coinflip(ctx, 선택, 0, all_in=True)

    @casino_group.command(name="시즌랭킹", description="시즌·전체·오늘 TOP100 순이익 랭킹을 확인합니다.")
    async def casino_season_rank_cmd(ctx: commands.Context, 구분: str = "시즌", 페이지: int = 1) -> None:
        await season_ranking(ctx, 구분, 페이지)

    # prefix 바로가기
    @bot.command(name="카지노칩")
    async def casino_chip_prefix(ctx: commands.Context) -> None:
        await show_chip_status(ctx)

    @bot.command(name="카지노환전")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def casino_exchange_prefix(ctx: commands.Context, 방향: str, 금액: int) -> None:
        await exchange(ctx, 방향, 금액)

    @bot.command(name="카지노VIP")
    async def casino_vip_prefix(ctx: commands.Context) -> None:
        await show_vip(ctx)

    @bot.command(name="카지노잭팟")
    async def casino_jackpot_prefix(ctx: commands.Context) -> None:
        await show_jackpot(ctx)

    @bot.command(name="카지노미션")
    async def casino_mission_prefix(ctx: commands.Context) -> None:
        await show_missions(ctx)

    @bot.command(name="카지노미션보상")
    async def casino_mission_claim_prefix(ctx: commands.Context, 번호: int = 0) -> None:
        await claim_mission(ctx, 번호)

    @bot.command(name="카지노업적")
    async def casino_achievement_prefix(ctx: commands.Context, 페이지: int = 1) -> None:
        await show_achievements(ctx, 페이지)

    @bot.command(name="카지노상점")
    async def casino_shop_prefix(ctx: commands.Context) -> None:
        await show_shop(ctx)

    @bot.command(name="카지노구매")
    async def casino_buy_prefix(ctx: commands.Context, 상품: str, 수량: int = 1) -> None:
        await buy_shop(ctx, 상품, 수량)

    @bot.command(name="럭키휠")
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def casino_wheel_prefix(ctx: commands.Context) -> None:
        await wheel(ctx)

    @bot.command(name="코인플립")
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def casino_coinflip_prefix(ctx: commands.Context, 선택: str, 배팅액: int) -> None:
        await coinflip(ctx, 선택, 배팅액)

    @bot.command(name="올인")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def casino_allin_prefix(ctx: commands.Context, 선택: str) -> None:
        await coinflip(ctx, 선택, 0, all_in=True)

    @bot.command(name="카지노딜러")
    async def casino_dealer_prefix(ctx: commands.Context) -> None:
        await show_dealers(ctx)

    @bot.command(name="카지노시즌랭킹")
    async def casino_season_rank_prefix(ctx: commands.Context, 구분: str = "시즌", 페이지: int = 1) -> None:
        await season_ranking(ctx, 구분, 페이지)
