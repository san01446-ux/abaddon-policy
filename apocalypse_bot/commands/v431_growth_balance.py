from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from discord.ext import commands


V431_VERSION = 1
BATTLE_STALE_SECONDS = 6 * 60 * 60
MAX_RELIC_SLOTS = 2

PRICE_MULTIPLIERS = {
    "일반": 1.18,
    "고급": 1.20,
    "희귀": 1.22,
    "영웅": 1.24,
    "전설": 1.27,
    "신화": 1.30,
    "유일": 1.33,
}

NEW_EQUIPMENT: Dict[str, Dict[str, Dict[str, Any]]] = {
    "일반": {
        "구조대군화": {"price": 950, "power": 4, "desc": "미끄러운 잔해에서 발목을 지켜주는 구조대 군화"},
        "철제반지": {"price": 1100, "power": 4, "desc": "고철을 다듬어 만든 단단한 생존 반지"},
        "폐허목걸이": {"price": 1250, "power": 5, "desc": "길을 잃지 않도록 표식을 새긴 목걸이"},
    },
    "고급": {
        "정찰고글": {"price": 4200, "power": 10, "desc": "먼지와 섬광을 막아주는 정찰용 고글"},
        "방탄장갑": {"price": 4600, "power": 11, "desc": "손등에 얇은 방탄판을 덧댄 장갑"},
        "전술군화": {"price": 5000, "power": 12, "desc": "긴 원정에서도 발을 안정적으로 지지하는 군화"},
    },
    "희귀": {
        "폐허추적자코트": {"price": 13200, "power": 20, "desc": "잔해와 오염비를 견디는 원정대 방호 코트"},
        "저격보조장갑": {"price": 14500, "power": 21, "desc": "반동을 억제하고 조준을 돕는 전투 장갑"},
        "혈청팬던트": {"price": 15800, "power": 22, "desc": "응급 혈청을 밀봉해 둔 생존 팬던트"},
    },
    "영웅": {
        "원정대장헬멧": {"price": 36500, "power": 36, "desc": "전장 통신 장치가 내장된 원정대장 헬멧"},
        "충격흡수부츠": {"price": 39500, "power": 38, "desc": "폭발 충격과 낙하 충격을 줄이는 특수 부츠"},
        "백색신호반지": {"price": 43000, "power": 40, "desc": "백색 신호에 반응해 미세하게 빛나는 반지"},
    },
    "전설": {
        "방주정찰갑옷": {"price": 110000, "power": 66, "desc": "방주 외곽 정찰대가 사용하던 밀폐형 슈트"},
        "공단분쇄글러브": {"price": 122000, "power": 69, "desc": "산업용 압력 장치를 전투용으로 개조한 글러브"},
        "심연항법목걸이": {"price": 136000, "power": 72, "desc": "신호가 끊긴 구역에서도 방향을 가리키는 목걸이"},
    },
    "신화": {
        "백색지휘관헬멧": {"price": 390000, "power": 120, "desc": "방주 지휘 권한을 모사하는 생체 인증 헬멧"},
        "시공왜곡군화": {"price": 430000, "power": 126, "desc": "한 걸음의 시간을 짧게 접어 이동하는 군화"},
        "방주동기화반지": {"price": 475000, "power": 132, "desc": "착용자의 신경 신호를 방주 장치와 동기화하는 반지"},
    },
    "유일": {
        "방주0번갑옷": {"price": 1900000, "power": 260, "desc": "방주 0번 중앙 집행관에게만 지급되던 절대 방호 갑옷"},
        "종말항해장갑": {"price": 2150000, "power": 275, "desc": "지도 밖의 공간을 더듬어 길을 여는 장갑"},
        "경계너머목걸이": {"price": 2450000, "power": 292, "desc": "도시 경계 밖의 미지 신호를 붙잡는 단 하나의 목걸이"},
    },
}

RELIC_EFFECTS: Dict[str, Dict[str, Any]] = {
    "깨진 노선표": {"tier": 1, "group": "탐색", "reward_pct": 0.03, "escape": 0.02},
    "붉은 승차권": {"tier": 1, "group": "탐색", "attack_pct": 0.03, "crit": 0.01},
    "멈춘 심전도계": {"tier": 1, "group": "의료", "heal_pct": 0.08, "defense_pct": 0.02},
    "밀봉된 의무 기록": {"tier": 2, "group": "의료", "heal_pct": 0.12, "reward_pct": 0.03},
    "공단 감독관 배지": {"tier": 2, "group": "공단", "attack_pct": 0.07, "defense_pct": 0.03},
    "식지 않는 슬래그": {"tier": 2, "group": "공단", "attack_pct": 0.05, "status_chance": 0.04},
    "백색 출입키": {"tier": 3, "group": "방주", "reward_pct": 0.08, "relic_pct": 0.04},
    "동면실 이름표": {"tier": 3, "group": "방주", "defense_pct": 0.09, "heal_pct": 0.08},
    "방주 0번 인장": {"tier": 4, "group": "방주", "attack_pct": 0.12, "crit": 0.04},
    "통합 지휘 코어": {"tier": 4, "group": "지휘", "attack_pct": 0.10, "defense_pct": 0.10, "reward_pct": 0.06},
    "새벽 송신기": {"tier": 4, "group": "지휘", "heal_pct": 0.18, "relic_pct": 0.06},
    "미지의 노선도": {"tier": 4, "group": "탐색", "reward_pct": 0.12, "escape": 0.08, "relic_pct": 0.03},
}

RELIC_TIER_NAMES = {1: "낡음", 2: "희귀", 3: "영웅", 4: "전설"}
RELIC_DUST_RETURN = {1: 1, 2: 2, 3: 4, 4: 7}
RELIC_UPGRADE_DUST = {0: 2, 1: 5, 2: 10, 3: 18, 4: 30}
RELIC_UPGRADE_FOOD = {0: 5000, 1: 12000, 2: 25000, 3: 50000, 4: 90000}

BOSS_NAMES = {
    "지하철잔해": "종착역 포식왕",
    "침수병원": "수술실의 백색 거인",
    "잿빛공단": "용광로 감독기 오메가",
    "백색연구구역": "기억수정 실험체 PRIME",
    "방주외곽": "방주 집행관 ZERO",
}

_BALANCE_APPLIED = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    return result


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _period_key(kind: str) -> str:
    now = _utc_now()
    if kind == "daily":
        return now.date().isoformat()
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _seeded_sample(kind: str, period: str, pool: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    seed = int(hashlib.sha256(f"ABADDON:{kind}:{period}".encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    selected = rng.sample(pool, min(count, len(pool)))
    return [dict(item, progress=0, claimed=False) for item in selected]


def _daily_pool() -> List[Dict[str, Any]]:
    return [
        {"key": "clear", "title": "원정 2회 승리", "target": 2, "food": 2200, "dust": 1, "kits": 0},
        {"key": "damage", "title": "적에게 누적 700 피해", "target": 700, "food": 1800, "dust": 1, "kits": 0},
        {"key": "guard", "title": "방어 행동 3회", "target": 3, "food": 1600, "dust": 1, "kits": 1},
        {"key": "skill", "title": "전술 기술 2회 사용", "target": 2, "food": 1800, "dust": 1, "kits": 0},
        {"key": "material", "title": "원정 재료 5개 획득", "target": 5, "food": 2000, "dust": 1, "kits": 0},
        {"key": "relic", "title": "유물 1개 발견", "target": 1, "food": 2600, "dust": 2, "kits": 0},
    ]


def _weekly_pool() -> List[Dict[str, Any]]:
    return [
        {"key": "clear", "title": "원정 10회 승리", "target": 10, "food": 15000, "dust": 6, "kits": 2},
        {"key": "boss", "title": "지역 보스 2회 격파", "target": 2, "food": 18000, "dust": 8, "kits": 1},
        {"key": "damage", "title": "적에게 누적 6,000 피해", "target": 6000, "food": 12000, "dust": 5, "kits": 1},
        {"key": "guard", "title": "방어 행동 15회", "target": 15, "food": 11000, "dust": 5, "kits": 2},
        {"key": "relic", "title": "유물 4개 발견", "target": 4, "food": 16000, "dust": 7, "kits": 1},
        {"key": "streak", "title": "원정 5연승 달성", "target": 5, "food": 20000, "dust": 8, "kits": 2},
    ]


def ensure_expedition_growth(expedition: Dict[str, Any]) -> Dict[str, Any]:
    expedition.setdefault("v431_version", V431_VERSION)
    expedition.setdefault("equipped_relics", [])
    expedition.setdefault("relic_levels", {})
    expedition.setdefault("relic_dust", 0)
    expedition.setdefault("zone_clears", {})
    expedition.setdefault("battle_results", [])
    expedition.setdefault("daily_missions", {})
    expedition.setdefault("weekly_missions", {})

    if not isinstance(expedition.get("equipped_relics"), list):
        expedition["equipped_relics"] = []
    expedition["equipped_relics"] = [
        str(name) for name in expedition["equipped_relics"]
        if str(name) in RELIC_EFFECTS
    ][:MAX_RELIC_SLOTS]
    if not isinstance(expedition.get("relic_levels"), dict):
        expedition["relic_levels"] = {}
    expedition["relic_levels"] = {
        str(name): min(5, _safe_int(level, 0, 0))
        for name, level in expedition["relic_levels"].items()
        if str(name) in RELIC_EFFECTS
    }
    expedition["relic_dust"] = _safe_int(expedition.get("relic_dust"), 0, 0)
    if not isinstance(expedition.get("zone_clears"), dict):
        expedition["zone_clears"] = {}
    expedition["zone_clears"] = {str(k): _safe_int(v, 0, 0) for k, v in expedition["zone_clears"].items()}
    if not isinstance(expedition.get("battle_results"), list):
        expedition["battle_results"] = []
    expedition["battle_results"] = expedition["battle_results"][-30:]

    for kind, pool in (("daily", _daily_pool()), ("weekly", _weekly_pool())):
        field = f"{kind}_missions"
        period = _period_key(kind)
        current = expedition.get(field)
        if not isinstance(current, dict) or current.get("period") != period:
            expedition[field] = {
                "period": period,
                "missions": _seeded_sample(kind, period, pool, 3),
            }
        missions = expedition[field].get("missions")
        if not isinstance(missions, list):
            expedition[field]["missions"] = _seeded_sample(kind, period, pool, 3)
        for mission in expedition[field]["missions"]:
            mission["progress"] = _safe_int(mission.get("progress"), 0, 0)
            mission["target"] = max(1, _safe_int(mission.get("target"), 1, 1))
            mission["claimed"] = bool(mission.get("claimed"))
    expedition["v431_version"] = V431_VERSION
    return expedition


def expire_stale_battle(expedition: Dict[str, Any]) -> bool:
    battle = expedition.get("battle")
    if not isinstance(battle, dict):
        return False
    started = _parse_time(battle.get("started_at"))
    if started is None:
        battle["started_at"] = _utc_now().isoformat()
        return False
    if (_utc_now() - started).total_seconds() < BATTLE_STALE_SECONDS:
        return False
    expedition["fails"] = _safe_int(expedition.get("fails"), 0, 0) + 1
    expedition["streak"] = 0
    expedition.setdefault("history", []).append(
        f"{_utc_now().strftime('%m-%d %H:%M')} · {battle.get('zone', '미상')} 장시간 방치로 자동 구조"
    )
    expedition["history"] = expedition["history"][-20:]
    expedition["battle"] = None
    expedition["_v431_expired_battle"] = True
    return True


def relic_bonus(expedition: Dict[str, Any]) -> Dict[str, float]:
    ensure_expedition_growth(expedition)
    totals = {
        "attack_pct": 0.0,
        "defense_pct": 0.0,
        "reward_pct": 0.0,
        "relic_pct": 0.0,
        "heal_pct": 0.0,
        "crit": 0.0,
        "escape": 0.0,
        "status_chance": 0.0,
    }
    groups: List[str] = []
    for name in expedition["equipped_relics"]:
        info = RELIC_EFFECTS.get(name, {})
        level = _safe_int(expedition["relic_levels"].get(name), 0, 0)
        scale = 1.0 + level * 0.18
        groups.append(str(info.get("group", "")))
        for key in totals:
            totals[key] += float(info.get(key, 0.0)) * scale
    if len(groups) >= 2 and groups[0] and groups[0] == groups[1]:
        totals["attack_pct"] += 0.03
        totals["defense_pct"] += 0.03
        totals["reward_pct"] += 0.03
    return totals


def progress_expedition_missions(expedition: Dict[str, Any], key: str, amount: int = 1) -> None:
    ensure_expedition_growth(expedition)
    amount = max(0, _safe_int(amount, 0, 0))
    if amount <= 0:
        return
    for field in ("daily_missions", "weekly_missions"):
        for mission in expedition[field].get("missions", []):
            if mission.get("key") == key and not mission.get("claimed"):
                current = _safe_int(mission.get("progress"), 0, 0)
                updated = max(current, amount) if key == "streak" else current + amount
                mission["progress"] = min(
                    _safe_int(mission.get("target"), 1, 1),
                    updated,
                )


def prepare_enemy(expedition: Dict[str, Any], zone_name: str, enemy_name: str, enemy_hp: int) -> Dict[str, Any]:
    ensure_expedition_growth(expedition)
    clears = _safe_int(expedition["zone_clears"].get(zone_name), 0, 0)
    boss_due = (clears + 1) % 5 == 0
    if boss_due:
        rank = "보스"
        name = BOSS_NAMES.get(zone_name, f"{enemy_name} 지배체")
        hp_mult = 1.85
        attack_mult = 1.38
        reward_mult = 1.65
    elif random.random() < 0.18:
        rank = "정예"
        name = f"정예 {enemy_name}"
        hp_mult = 1.35
        attack_mult = 1.18
        reward_mult = 1.25
    else:
        rank = "일반"
        name = enemy_name
        hp_mult = 1.0
        attack_mult = 1.0
        reward_mult = 1.0
    maximum = max(1, round(enemy_hp * hp_mult))
    return {
        "enemy": name,
        "enemy_rank": rank,
        "enemy_hp": maximum,
        "enemy_max_hp": maximum,
        "enemy_attack_mult": attack_mult,
        "reward_mult": reward_mult,
        "player_status": {},
        "enemy_status": {},
        "skill_cooldown": 0,
    }


def apply_player_turn_status(user: Dict[str, Any], battle: Dict[str, Any], apply_damage) -> List[str]:
    statuses = battle.setdefault("player_status", {})
    lines: List[str] = []
    for key, label, damage in (("bleed", "🩸 출혈", 4), ("poison", "☠️ 중독", 5)):
        turns = _safe_int(statuses.get(key), 0, 0)
        if turns > 0:
            actual, knocked = apply_damage(user, damage + max(0, battle.get("turn", 1) // 5))
            statuses[key] = turns - 1
            lines.append(f"{label} 지속 피해 **{actual}**")
            if knocked:
                lines.append("😵 상태이상 피해로 쓰러졌습니다.")
    if _safe_int(statuses.get("stun"), 0, 0) > 0:
        statuses["stun"] = _safe_int(statuses.get("stun"), 0, 0) - 1
        lines.append("⚡ 기절 상태로 이번 행동을 할 수 없습니다.")
    battle["player_status"] = {k: v for k, v in statuses.items() if _safe_int(v, 0, 0) > 0}
    return lines


def maybe_inflict_player_status(battle: Dict[str, Any], special: bool) -> Optional[str]:
    rank = battle.get("enemy_rank", "일반")
    chance = 0.08 + (0.08 if rank == "정예" else 0.16 if rank == "보스" else 0.0)
    if special:
        chance += 0.08
    if random.random() >= chance:
        return None
    status = random.choices(
        ["bleed", "poison", "stun", "armor_break"],
        weights=[35, 30, 12, 23],
        k=1,
    )[0]
    turns = {"bleed": 3, "poison": 3, "stun": 1, "armor_break": 2}[status]
    battle.setdefault("player_status", {})[status] = max(
        turns,
        _safe_int(battle.setdefault("player_status", {}).get(status), 0, 0),
    )
    return {
        "bleed": "🩸 출혈 3턴",
        "poison": "☠️ 중독 3턴",
        "stun": "⚡ 기절 1턴",
        "armor_break": "🛡️ 방어 붕괴 2턴",
    }[status]


def apply_balance_tables(item_db: Dict[str, Any], pet_db: Dict[str, Any]) -> None:
    global _BALANCE_APPLIED
    if _BALANCE_APPLIED:
        return
    for tier, items in NEW_EQUIPMENT.items():
        item_db.setdefault(tier, {})
        for name, info in items.items():
            item_db[tier].setdefault(name, dict(info, v431_new=True))
    for tier, items in item_db.items():
        multiplier = PRICE_MULTIPLIERS.get(tier, 1.20)
        for info in items.values():
            original = _safe_int(info.get("price"), 1, 1)
            info["price"] = max(1, int(round(original * multiplier / 50.0) * 50))
    for info in pet_db.values():
        info["price"] = max(1, int(round(_safe_int(info.get("price"), 1, 1) * 1.25 / 100.0) * 100))

    from apocalypse_bot.commands.conditions import MEDICINES
    for info in MEDICINES.values():
        info["price"] = max(1, int(round(_safe_int(info.get("price"), 1, 1) * 1.25 / 100.0) * 100))

    from apocalypse_bot.commands.v40_black_casino import SHOP_ITEMS
    for info in SHOP_ITEMS.values():
        info["price"] = max(1, int(round(_safe_int(info.get("price"), 1, 1) * 1.15 / 1000.0) * 1000))
    _BALANCE_APPLIED = True


def _format_bonus(bonus: Dict[str, float]) -> str:
    labels = {
        "attack_pct": "공격",
        "defense_pct": "피해감소",
        "reward_pct": "식량보상",
        "relic_pct": "유물확률",
        "heal_pct": "회복",
        "crit": "치명타",
        "escape": "도주",
        "status_chance": "상태이상",
    }
    parts = [f"{labels[key]} +{value * 100:.1f}%" for key, value in bonus.items() if value > 0]
    return " · ".join(parts) if parts else "효과 없음"


def register_v431_growth_balance(
    bot,
    get_user,
    check_registered,
    save_data,
    item_db,
    pet_db,
) -> None:
    apply_balance_tables(item_db, pet_db)

    from apocalypse_bot.commands.v430_story_expedition import RELIC_DESCRIPTIONS, SEASON2_NODES, ensure_v430

    async def _require(ctx):
        if not await check_registered(ctx):
            return None, None
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        ensure_expedition_growth(expedition)
        return user, expedition

    @bot.command(name="신규장비", aliases=["장비패치"])
    async def new_equipment(ctx, 티어: str = ""):
        if not await check_registered(ctx):
            return
        tiers: Iterable[str] = [티어] if 티어 in NEW_EQUIPMENT else NEW_EQUIPMENT.keys()
        lines = ["🧰 **[v4.3.1 신규 장비]**"]
        for tier in tiers:
            lines.append(f"\n**{tier}**")
            for name in NEW_EQUIPMENT[tier]:
                info = item_db[tier][name]
                lines.append(f"• **{name}** · {info['price']:,}개 · 전투력 +{info['power']}\n　{info['desc']}")
        lines.append("\n구매는 기존처럼 `!구매 장비이름`을 사용합니다.")
        await ctx.send("\n".join(lines))

    @bot.command(name="경제밸런스", aliases=["경제변경"])
    async def economy_balance(ctx):
        if not await check_registered(ctx):
            return
        await ctx.send(
            "📈 **[v4.3.1 경제 밸런스]**\n"
            "• 기존 장비 가격: 티어별 약 **18~33% 인상**\n"
            "• 신규 장비: 21종 추가\n"
            "• 펫·의약품·카지노 보조상품 가격 인상\n"
            "• 훈련·기지·길드·펫 성장 비용 인상\n"
            "• 무료 식량·알바·기지 생산량 일부 조정\n"
            "• 일반 도박과 BLACK CASINO 기대수익 소폭 하향\n"
            "기존 보유 식량과 장비는 회수하거나 초기화하지 않습니다."
        )

    @bot.group(name="유물", invoke_without_command=True)
    async def relic_group(ctx):
        user, expedition = await _require(ctx)
        if user is None:
            return
        owned = expedition.get("relics", {})
        if not owned:
            await ctx.send("🏺 보유한 원정 유물이 없습니다. `!원정 출발 지역명`으로 발견할 수 있습니다.")
            return
        bonus = relic_bonus(expedition)
        lines = [
            f"🏺 **[{ctx.author.display_name}의 유물 장비]**",
            f"장착: **{', '.join(expedition['equipped_relics']) or '없음'}** ({len(expedition['equipped_relics'])}/{MAX_RELIC_SLOTS})",
            f"유물 가루: **{expedition['relic_dust']}개**",
            f"합산 효과: {_format_bonus(bonus)}",
            "",
        ]
        for name, amount in sorted(owned.items()):
            info = RELIC_EFFECTS.get(name, {"tier": 1})
            level = expedition["relic_levels"].get(name, 0)
            mark = "⭐" if name in expedition["equipped_relics"] else "•"
            lines.append(f"{mark} **{name} +{level}** ×{amount} · {RELIC_TIER_NAMES.get(info['tier'], '유물')}")
        lines.append("\n`!유물 장착 이름` · `!유물 강화 이름` · `!유물 분해 이름 수량`")
        await ctx.send("\n".join(lines))

    @relic_group.command(name="장착")
    async def relic_equip(ctx, *, 이름: str):
        user, expedition = await _require(ctx)
        if user is None:
            return
        name = 이름.strip()
        if expedition.get("relics", {}).get(name, 0) <= 0 or name not in RELIC_EFFECTS:
            await ctx.send("⚠️ 보유한 장착 가능 유물을 찾지 못했습니다.")
            return
        if name in expedition["equipped_relics"]:
            await ctx.send("⭐ 이미 장착 중인 유물입니다.")
            return
        if len(expedition["equipped_relics"]) >= MAX_RELIC_SLOTS:
            await ctx.send(f"⚠️ 유물은 최대 {MAX_RELIC_SLOTS}개 장착할 수 있습니다. 먼저 `!유물 해제 이름`을 사용하세요.")
            return
        expedition["equipped_relics"].append(name)
        save_data()
        await ctx.send(f"⭐ **{name}** 장착 완료\n현재 효과: {_format_bonus(relic_bonus(expedition))}")

    @relic_group.command(name="해제")
    async def relic_unequip(ctx, *, 이름: str = ""):
        user, expedition = await _require(ctx)
        if user is None:
            return
        if not 이름.strip() and len(expedition["equipped_relics"]) == 1:
            이름 = expedition["equipped_relics"][0]
        name = 이름.strip()
        if name not in expedition["equipped_relics"]:
            await ctx.send("⚠️ 해당 유물을 장착하고 있지 않습니다.")
            return
        expedition["equipped_relics"].remove(name)
        save_data()
        await ctx.send(f"📦 **{name}** 장착 해제 완료")

    @relic_group.command(name="강화")
    async def relic_upgrade(ctx, *, 이름: str):
        user, expedition = await _require(ctx)
        if user is None:
            return
        name = 이름.strip()
        if expedition.get("relics", {}).get(name, 0) <= 0 or name not in RELIC_EFFECTS:
            await ctx.send("⚠️ 강화할 유물을 보유하고 있지 않습니다.")
            return
        level = _safe_int(expedition["relic_levels"].get(name), 0, 0)
        if level >= 5:
            await ctx.send("🏆 이미 최대 강화 단계 +5입니다.")
            return
        dust = RELIC_UPGRADE_DUST[level]
        food = RELIC_UPGRADE_FOOD[level]
        if expedition["relic_dust"] < dust or _safe_int(user.get("balance"), 0) < food:
            await ctx.send(
                f"⚠️ 강화 재료가 부족합니다.\n필요: 유물 가루 **{dust}개** + 식량 **{food:,}개**\n"
                f"보유: 가루 **{expedition['relic_dust']}개** + 식량 **{_safe_int(user.get('balance'), 0):,}개**"
            )
            return
        expedition["relic_dust"] -= dust
        user["balance"] = _safe_int(user.get("balance"), 0) - food
        expedition["relic_levels"][name] = level + 1
        save_data()
        await ctx.send(f"✨ **{name} +{level + 1}** 강화 완료\n비용: 가루 {dust}개 · 식량 {food:,}개")

    @relic_group.command(name="분해")
    async def relic_dismantle(ctx, 이름: str, 수량: int = 1):
        user, expedition = await _require(ctx)
        if user is None:
            return
        amount = _safe_int(expedition.get("relics", {}).get(이름), 0, 0)
        수량 = _safe_int(수량, 0, 0)
        if 이름 not in RELIC_EFFECTS or 수량 < 1 or amount <= 수량:
            await ctx.send("⚠️ 유물은 최소 1개를 남겨야 하며, 보유한 중복 수량 안에서만 분해할 수 있습니다.")
            return
        if 이름 in expedition["equipped_relics"] and amount - 수량 <= 0:
            await ctx.send("⚠️ 장착 중인 마지막 유물은 분해할 수 없습니다.")
            return
        tier = _safe_int(RELIC_EFFECTS[이름].get("tier"), 1, 1)
        gained = RELIC_DUST_RETURN.get(tier, 1) * 수량
        expedition["relics"][이름] -= 수량
        expedition["relic_dust"] += gained
        save_data()
        await ctx.send(f"♻️ **{이름} ×{수량}** 분해 완료 · 유물 가루 **+{gained}개**")

    expedition_group = bot.get_command("원정")
    if isinstance(expedition_group, commands.Group):
        @expedition_group.command(name="장비")
        async def expedition_equipment(ctx):
            user, expedition = await _require(ctx)
            if user is None:
                return
            await ctx.send(
                "🎒 **[원정 장비 효과]**\n"
                f"장착 유물: **{', '.join(expedition['equipped_relics']) or '없음'}**\n"
                f"합산 효과: {_format_bonus(relic_bonus(expedition))}\n"
                f"유물 가루: **{expedition['relic_dust']}개**\n\n"
                "관리: `!유물` · `!유물 장착 이름` · `!유물 강화 이름`"
            )

        @expedition_group.command(name="임무")
        async def expedition_missions(ctx, 구분: str = "오늘"):
            user, expedition = await _require(ctx)
            if user is None:
                return
            field = "weekly_missions" if 구분 in {"주간", "주", "weekly"} else "daily_missions"
            title = "주간" if field == "weekly_missions" else "일일"
            lines = [f"📋 **[{title} 원정 임무]** · {expedition[field]['period']}"]
            for index, mission in enumerate(expedition[field]["missions"], 1):
                progress = min(mission["target"], mission["progress"])
                mark = "✅" if mission["claimed"] else "🎁" if progress >= mission["target"] else "⬜"
                lines.append(
                    f"{mark} **{index}. {mission['title']}** · {progress:,}/{mission['target']:,}\n"
                    f"　보상 식량 {mission['food']:,} · 가루 {mission['dust']} · 키트 {mission['kits']}"
                )
            lines.append(f"\n수령: `!원정 임무보상 {title} 번호` · 번호 0은 전부")
            await ctx.send("\n".join(lines))

        @expedition_group.command(name="임무보상")
        async def expedition_mission_claim(ctx, 구분: str = "일일", 번호: int = 0):
            user, expedition = await _require(ctx)
            if user is None:
                return
            field = "weekly_missions" if 구분 in {"주간", "주", "weekly"} else "daily_missions"
            missions = expedition[field]["missions"]
            indexes = range(len(missions)) if _safe_int(번호, 0) == 0 else [_safe_int(번호, 0) - 1]
            claimed = food = dust = kits = 0
            for index in indexes:
                if index < 0 or index >= len(missions):
                    continue
                mission = missions[index]
                if mission["claimed"] or mission["progress"] < mission["target"]:
                    continue
                mission["claimed"] = True
                claimed += 1
                food += _safe_int(mission.get("food"), 0, 0)
                dust += _safe_int(mission.get("dust"), 0, 0)
                kits += _safe_int(mission.get("kits"), 0, 0)
            if claimed <= 0:
                await ctx.send("⚠️ 수령 가능한 원정 임무 보상이 없습니다.")
                return
            user["balance"] = _safe_int(user.get("balance"), 0, 0) + food
            user.setdefault("stats", {})["earned"] = _safe_int(user.setdefault("stats", {}).get("earned"), 0, 0) + food
            expedition["relic_dust"] += dust
            expedition["kits"] = _safe_int(expedition.get("kits"), 0, 0) + kits
            save_data()
            await ctx.send(f"🎁 임무 **{claimed}개** 보상 수령 · 식량 +{food:,} · 가루 +{dust} · 키트 +{kits}")

        @expedition_group.command(name="복구")
        async def expedition_recover(ctx):
            user, expedition = await _require(ctx)
            if user is None:
                return
            if expedition.pop("_v431_expired_battle", False) or expire_stale_battle(expedition):
                expedition.pop("_v431_expired_battle", None)
                save_data()
                await ctx.send("🚑 6시간 이상 방치된 원정을 자동 종료하고 생존자를 구조했습니다.")
                return
            battle = expedition.get("battle")
            if isinstance(battle, dict):
                await ctx.send(
                    f"✅ 원정 전투 데이터가 정상입니다. **{battle.get('zone')} · {battle.get('enemy')}**\n"
                    "`!원정`으로 현재 전투를 다시 표시할 수 있습니다."
                )
            else:
                await ctx.send("✅ 복구할 원정 전투가 없습니다. 새 원정을 시작해도 안전합니다.")

    season2_group = bot.get_command("시즌2")
    if isinstance(season2_group, commands.Group):
        @season2_group.command(name="장면")
        async def season2_scenes(ctx, 번호: int = 0):
            if not await check_registered(ctx):
                return
            user = get_user(ctx.author.id)
            season2 = ensure_v430(user)["season2"]
            history = season2.get("history", [])
            if not history:
                await ctx.send("📖 다시 볼 시즌 2 장면이 없습니다.")
                return
            if 번호 <= 0:
                lines = ["📖 **[백색 방주 장면 목록]**"]
                for index, record in enumerate(history, 1):
                    lines.append(f"{index}. {record.get('chapter')} · **{record.get('title')}**")
                lines.append("\n상세: `!시즌2 장면 번호`")
                await ctx.send("\n".join(lines))
                return
            if 번호 > len(history):
                await ctx.send(f"⚠️ 장면 번호는 1~{len(history)} 사이입니다.")
                return
            record = history[번호 - 1]
            node = next((n for n in SEASON2_NODES.values() if n.get("title") == record.get("title")), None)
            body = node.get("body") if node else "장면 원문을 찾지 못했습니다."
            await ctx.send(f"📖 **{record.get('chapter')} · {record.get('title')}**\n{body}\n\n선택: {record.get('choice')}")

        @season2_group.command(name="수집")
        async def season2_collection(ctx):
            if not await check_registered(ctx):
                return
            user = get_user(ctx.author.id)
            season2 = ensure_v430(user)["season2"]
            endings = set(season2.get("endings", []))
            names = [
                ("second_dawn", "두 번째 새벽"),
                ("sealed_ark", "봉쇄된 낙원"),
                ("white_commander", "백색 지휘관"),
                ("beyond_border", "경계 너머"),
            ]
            await ctx.send(
                "🏁 **[시즌 2 엔딩 수집도]**\n"
                + "\n".join(f"{'✅' if key in endings else '🔒'} {name}" for key, name in names)
                + f"\n\n수집 **{len(endings)}/4**"
            )

        @season2_group.command(name="계승")
        async def season2_legacy(ctx):
            if not await check_registered(ctx):
                return
            user = get_user(ctx.author.id)
            story = user.get("story", {}) if isinstance(user.get("story"), dict) else {}
            ending = story.get("ending", {}) if isinstance(story.get("ending"), dict) else {}
            flags = story.get("flags", []) if isinstance(story.get("flags"), list) else []
            await ctx.send(
                "🔗 **[시즌 1 계승 정보]**\n"
                f"시즌 1 완료: **{'완료' if story.get('completed') else '미완료'}**\n"
                f"마지막 엔딩: **{ending.get('title', '기록 없음')}**\n"
                f"핵심 선택 기록: **{len(flags)}개**\n"
                "이 정보는 시즌 2의 관리자 권한·구조·신호 관련 분기 해금에 사용됩니다."
            )

        @season2_group.command(name="복구")
        async def season2_recover(ctx):
            if not await check_registered(ctx):
                return
            user = get_user(ctx.author.id)
            season2 = ensure_v430(user)["season2"]
            node = season2.get("node")
            if node not in SEASON2_NODES:
                season2["node"] = "a1_white_noise"
                season2["completed"] = False
                save_data()
                await ctx.send("🔧 손상된 시즌 2 장면을 프롤로그로 복구했습니다. 엔딩·보상 기록은 유지됩니다.")
                return
            await ctx.send(f"✅ 시즌 2 진행 데이터가 정상입니다. 현재 장면: **{SEASON2_NODES[node]['title']}**")

    print(
        "[V4.3.1 등록 확인] "
        f"신규장비={bot.get_command('신규장비') is not None} "
        f"유물={bot.get_command('유물') is not None} "
        f"원정임무={bot.get_command('원정').get_command('임무') is not None if bot.get_command('원정') else False}",
        flush=True,
    )
