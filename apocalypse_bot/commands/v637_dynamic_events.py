from __future__ import annotations

import copy
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "6.3.7a"
KST = timezone(timedelta(hours=9))

REGION_NAMES: Tuple[str, ...] = (
    "폐허도심", "버려진학교", "시립병원", "지하철역",
    "대형마트", "경찰서", "군부대", "격리연구소",
)

HAZARD_TYPES: Tuple[Dict[str, Any], ...] = (
    {
        "id": "infection", "emoji": "☣️", "name": "고농도 감염 구역",
        "desc": "공기 중 포자 농도가 급증했습니다. 실패 시 감염 위험이 크게 오릅니다.",
        "success_penalty": 0.12, "reward_mult": 3.00, "damage_mult": 1.45, "infection_bonus": 4,
    },
    {
        "id": "collapse", "emoji": "🏚️", "name": "연쇄 붕괴 구역",
        "desc": "지반과 건물이 불안정합니다. 잔해 속 희귀 물자가 드러납니다.",
        "success_penalty": 0.09, "reward_mult": 2.70, "damage_mult": 1.60, "infection_bonus": 1,
    },
    {
        "id": "spore", "emoji": "🍄", "name": "포자 폭주 구역",
        "desc": "변이 균사가 번졌습니다. 생체 재료가 풍부하지만 전투가 거칠어집니다.",
        "success_penalty": 0.11, "reward_mult": 2.85, "damage_mult": 1.40, "infection_bonus": 5,
    },
    {
        "id": "static", "emoji": "📡", "name": "전자기 교란 구역",
        "desc": "센서와 무전이 흔들립니다. 전자부품과 데이터 잔해 발견률이 상승합니다.",
        "success_penalty": 0.08, "reward_mult": 2.55, "damage_mult": 1.35, "infection_bonus": 1,
    },
    {
        "id": "predator", "emoji": "🩸", "name": "포식 군체 활동 구역",
        "desc": "상위 변이체가 먹잇감을 추적합니다. 성공 보상이 매우 높습니다.",
        "success_penalty": 0.15, "reward_mult": 3.25, "damage_mult": 1.70, "infection_bonus": 3,
    },
)

FORTUNE_GRADES: Tuple[Dict[str, Any], ...] = (
    {
        "name": "대길", "emoji": "🌟", "weight": 5, "color": 0xF6C453,
        "combat": 1.06, "life": 1.07, "reward": 1.08, "market": 0.96,
        "radio": 1.18, "box_luck": 0.045, "claim": (5000, 9000),
        "summary": "작은 선택이 큰 보상으로 이어지는 날입니다.",
    },
    {
        "name": "길", "emoji": "✨", "weight": 18, "color": 0xE9B84A,
        "combat": 1.04, "life": 1.05, "reward": 1.05, "market": 0.975,
        "radio": 1.12, "box_luck": 0.025, "claim": (3000, 6000),
        "summary": "준비한 만큼 안정적인 성과가 따라옵니다.",
    },
    {
        "name": "소길", "emoji": "🍀", "weight": 31, "color": 0x69B578,
        "combat": 1.02, "life": 1.03, "reward": 1.03, "market": 0.985,
        "radio": 1.07, "box_luck": 0.012, "claim": (1800, 4200),
        "summary": "무리하지 않는 선택이 좋은 결과를 만듭니다.",
    },
    {
        "name": "평", "emoji": "🌙", "weight": 34, "color": 0x607D9E,
        "combat": 1.01, "life": 1.01, "reward": 1.01, "market": 0.995,
        "radio": 1.03, "box_luck": 0.005, "claim": (1000, 3000),
        "summary": "평범한 하루지만 꼼꼼함이 손실을 막아줍니다.",
    },
    {
        "name": "주의", "emoji": "🕯️", "weight": 12, "color": 0x7E526F,
        "combat": 1.00, "life": 1.00, "reward": 1.00, "market": 1.00,
        "radio": 1.00, "box_luck": 0.000, "claim": (700, 1800),
        "summary": "큰 승부보다 정비와 회복에 집중하는 편이 좋습니다.",
    },
)

FORTUNE_ITEMS: Tuple[str, ...] = (
    "파스텔 파우치", "낡은 나침반", "붉은 실 매듭", "작은 손전등",
    "검은 깃털", "은빛 볼트", "빈 탄피", "유리 구슬", "접힌 지도",
)
FORTUNE_FOODS: Tuple[str, ...] = (
    "옥수수", "통조림 복숭아", "따뜻한 수프", "말린 사과", "초콜릿",
    "감자", "허브차", "구운 버섯", "견과류",
)
FORTUNE_DIRECTIONS: Tuple[str, ...] = ("북쪽", "동쪽", "남쪽", "서쪽", "지하", "높은 곳")
FORTUNE_ACTIONS: Tuple[str, ...] = (
    "오늘은 `!무전`으로 끊긴 신호를 먼저 확인해보세요.",
    "장비 상태를 `!내구도`로 확인하면 예상치 못한 손실을 막을 수 있습니다.",
    "`!위험구역`을 확인한 뒤 탐색 지역을 고르는 편이 좋습니다.",
    "`!자원시장`의 가격을 비교하면 작은 이득이 쌓입니다.",
    "`!랜덤박스`는 오늘의 운세 보정을 받은 뒤 여는 편이 유리합니다.",
    "전투보다 기지와 장비를 정비하는 편이 안전합니다.",
)

WEAPON_PARTS: Dict[str, Dict[str, Any]] = {
    "소음기": {
        "desc": "은밀한 사격용 부품. 공격력과 치명타를 소폭 높입니다.",
        "compat": "firearm", "power": 3, "stats": {"치명타": 1},
        "craft": {"고철": 25, "광석": 8}, "food": 120_000,
    },
    "대용량탄창": {
        "desc": "연속 교전 대응 부품. 무기 전투력을 높입니다.",
        "compat": "firearm", "power": 6, "stats": {"공격력": 2},
        "craft": {"고철": 30, "광석": 10}, "food": 160_000,
    },
    "정밀조준경": {
        "desc": "원거리 장비용 조준 장치. 공격력과 치명타가 상승합니다.",
        "compat": "ranged", "power": 8, "stats": {"공격력": 2, "치명타": 2},
        "craft": {"고철": 18, "광석": 20}, "food": 220_000,
    },
    "강화손잡이": {
        "desc": "충격을 흡수해 내구도 소모를 줄입니다.",
        "compat": "any", "power": 2, "stats": {}, "durability_guard": 0.35,
        "craft": {"나무": 20, "고철": 15}, "food": 100_000,
    },
    "냉각코일": {
        "desc": "에너지 장비의 과열을 억제하고 기술 피해를 높입니다.",
        "compat": "energy", "power": 10, "stats": {"공격력": 3}, "skill_mult": 1.12,
        "craft": {"광석": 35, "고철": 25}, "food": 350_000,
    },
    "충격증폭기": {
        "desc": "근접 충격을 증폭해 일반 공격 피해를 높입니다.",
        "compat": "melee", "power": 9, "stats": {"공격력": 3}, "attack_mult": 1.10,
        "craft": {"광석": 28, "고철": 30}, "food": 320_000,
    },
}

RADIO_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("주파수 동기화", "📻"),
    ("좌표 역산", "🧭"),
    ("긴급 응답", "🆘"),
)
RADIO_SIGNALS: Tuple[Dict[str, Any], ...] = (
    {"name": "끊긴 구조 신호", "emoji": "🆘", "text": "붕괴된 건물 아래에서 짧은 구조 신호가 반복됩니다.", "reward": "rescue"},
    {"name": "암호화 군용 무전", "emoji": "🔐", "text": "낡은 군용 대역에서 좌표와 숫자열이 교차합니다.", "reward": "military"},
    {"name": "보급대 자동 비콘", "emoji": "📦", "text": "폐기된 보급 차량의 자동 비콘이 아직 살아 있습니다.", "reward": "supply"},
    {"name": "미확인 생존자 호출", "emoji": "👤", "text": "당신의 호출부호를 정확히 아는 누군가가 응답을 기다립니다.", "reward": "mystery"},
    {"name": "교란된 중계탑 신호", "emoji": "📡", "text": "잡음 사이로 중계탑 유지보수 코드가 섞여 들어옵니다.", "reward": "tech"},
)

RANDOM_BOX_COST = 250_000
RANDOM_BOX_DAILY_LIMIT = 3


def _now_kst(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(KST)


def _today_key(now: Optional[datetime] = None) -> str:
    return _now_kst(now).strftime("%Y-%m-%d")


def _weighted_choice(rng: random.Random, rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    total = sum(max(0.0, float(row.get("weight", 1))) for row in rows)
    point = rng.random() * max(total, 1.0)
    acc = 0.0
    for row in rows:
        acc += max(0.0, float(row.get("weight", 1)))
        if point <= acc:
            return row
    return rows[-1]


def _stable_rng(*parts: object) -> random.Random:
    raw = ":".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def _fortune_payload(user_id: int | str, date_key: str) -> Dict[str, Any]:
    rng = _stable_rng("abaddon-fortune", user_id, date_key)
    grade = dict(_weighted_choice(rng, FORTUNE_GRADES))
    grade.update({
        "date": date_key,
        "item": rng.choice(FORTUNE_ITEMS),
        "food_item": rng.choice(FORTUNE_FOODS),
        "direction": rng.choice(FORTUNE_DIRECTIONS),
        "action": rng.choice(FORTUNE_ACTIONS),
        "claimed": False,
    })
    return grade


def ensure_daily_fortune(user: Dict[str, Any], user_id: int | str, now: Optional[datetime] = None) -> Dict[str, Any]:
    date_key = _today_key(now)
    record = user.get("daily_fortune")
    if not isinstance(record, dict) or record.get("date") != date_key:
        record = _fortune_payload(user_id, date_key)
        user["daily_fortune"] = record
    return record


def active_fortune_modifiers(user: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    record = user.get("daily_fortune")
    if not isinstance(record, dict) or record.get("date") != _today_key(now):
        return {"active": False, "combat": 1.0, "life": 1.0, "reward": 1.0, "market": 1.0, "radio": 1.0, "box_luck": 0.0}
    return {
        "active": True,
        "combat": float(record.get("combat", 1.0)),
        "life": float(record.get("life", 1.0)),
        "reward": float(record.get("reward", 1.0)),
        "market": float(record.get("market", 1.0)),
        "radio": float(record.get("radio", 1.0)),
        "box_luck": float(record.get("box_luck", 0.0)),
    }


def current_weapon_name(user: Dict[str, Any]) -> Optional[str]:
    equipment = user.get("equipment")
    if not isinstance(equipment, dict):
        return None
    weapon = equipment.get("무기")
    return str(weapon) if weapon else None


def _max_durability(user: Dict[str, Any], item_name: str) -> int:
    enhance = int(user.get("enhancements", {}).get(item_name, 0)) if isinstance(user.get("enhancements"), dict) else 0
    return min(140, 100 + max(0, enhance) * 2)


def ensure_weapon_state(user: Dict[str, Any], item_name: Optional[str] = None) -> Tuple[Optional[str], int, int]:
    item_name = item_name or current_weapon_name(user)
    if not item_name:
        return None, 0, 0
    durability = user.setdefault("equipment_durability", {})
    if not isinstance(durability, dict):
        durability = {}
        user["equipment_durability"] = durability
    maximum = _max_durability(user, item_name)
    try:
        current = int(durability.get(item_name, maximum))
    except (TypeError, ValueError):
        current = maximum
    current = max(0, min(maximum, current))
    durability[item_name] = current
    mods = user.setdefault("weapon_mods", {})
    if not isinstance(mods, dict):
        user["weapon_mods"] = {}
    user["weapon_mods"].setdefault(item_name, [])
    if not isinstance(user["weapon_mods"][item_name], list):
        user["weapon_mods"][item_name] = []
    return item_name, current, maximum


def weapon_durability_status(user: Dict[str, Any], item_name: Optional[str] = None) -> Dict[str, Any]:
    name, current, maximum = ensure_weapon_state(user, item_name)
    if not name:
        return {"name": None, "current": 0, "maximum": 0, "ratio": 0.0, "label": "무기 없음", "emoji": "➖"}
    ratio = current / max(1, maximum)
    if current <= 0:
        label, emoji = "파손", "💥"
    elif ratio < 0.30:
        label, emoji = "위험", "🔴"
    elif ratio < 0.60:
        label, emoji = "마모", "🟠"
    else:
        label, emoji = "정상", "🟢"
    return {"name": name, "current": current, "maximum": maximum, "ratio": ratio, "label": label, "emoji": emoji}


def equipment_condition_multiplier(user: Dict[str, Any], item_name: str) -> float:
    if str(item_name) != str(current_weapon_name(user) or ""):
        return 1.0
    status = weapon_durability_status(user, item_name)
    ratio = float(status["ratio"])
    if ratio <= 0:
        return 0.45
    if ratio < 0.30:
        return 0.72
    if ratio < 0.60:
        return 0.90
    return 1.0


def _mods_for(user: Dict[str, Any], item_name: Optional[str] = None) -> List[str]:
    item_name = item_name or current_weapon_name(user)
    if not item_name:
        return []
    mods = user.get("weapon_mods", {})
    if not isinstance(mods, dict):
        return []
    values = mods.get(item_name, [])
    return [str(value) for value in values] if isinstance(values, list) else []


def equipment_mod_power_bonus(user: Dict[str, Any], item_name: str) -> int:
    return sum(int(WEAPON_PARTS.get(part, {}).get("power", 0)) for part in _mods_for(user, item_name))


def equipment_mod_stat_bonus(user: Dict[str, Any], item_name: str) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for part in _mods_for(user, item_name):
        for key, value in WEAPON_PARTS.get(part, {}).get("stats", {}).items():
            totals[key] = totals.get(key, 0) + int(value)
    return totals


def weapon_action_multiplier(user: Dict[str, Any], action: str) -> float:
    result = 1.0
    for part in _mods_for(user):
        info = WEAPON_PARTS.get(part, {})
        if action == "공격":
            result *= float(info.get("attack_mult", 1.0))
        if action == "기술":
            result *= float(info.get("skill_mult", 1.0))
    return result


def consume_weapon_durability(user: Dict[str, Any], amount: int = 1) -> Dict[str, Any]:
    name, current, maximum = ensure_weapon_state(user)
    if not name or amount <= 0:
        return weapon_durability_status(user, name)
    guard = 0.0
    for part in _mods_for(user, name):
        guard = max(guard, float(WEAPON_PARTS.get(part, {}).get("durability_guard", 0.0)))
    rng = random.random()
    effective = max(0, int(amount))
    if guard > 0 and rng < guard:
        effective = max(0, effective - 1)
    user.setdefault("equipment_durability", {})[name] = max(0, current - effective)
    return weapon_durability_status(user, name)


def _weapon_family(name: str) -> str:
    lowered = str(name)
    firearm = ("권총", "소총", "샷건", "레일건", "캐논", "포", "화염방사", "드래곤브레스")
    ranged = firearm + ("석궁", "스코프", "조준경")
    energy = ("플라즈마", "레일건", "고주파", "오메가", "절대영도", "차원", "공허", "아크")
    melee = ("검", "도끼", "나이프", "낫", "창", "해머", "봉", "파이프", "철근", "장갑")
    if any(key in lowered for key in energy):
        return "energy"
    if any(key in lowered for key in firearm):
        return "firearm"
    if any(key in lowered for key in ranged):
        return "ranged"
    if any(key in lowered for key in melee):
        return "melee"
    return "any"


def part_compatible(item_name: str, part_name: str) -> bool:
    required = str(WEAPON_PARTS.get(part_name, {}).get("compat", "any"))
    if required == "any":
        return True
    family = _weapon_family(item_name)
    if required == "ranged":
        return family in {"firearm", "ranged", "energy"}
    if required == "firearm":
        return family in {"firearm", "energy"}
    return family == required


def get_hazard_zone(guild_id: int | str | None, now: Optional[datetime] = None) -> Dict[str, Any]:
    date_key = _today_key(now)
    rng = _stable_rng("abaddon-hazard", guild_id or 0, date_key)
    region = rng.choice(REGION_NAMES)
    hazard = dict(rng.choice(HAZARD_TYPES))
    hazard.update({"date": date_key, "region": region})
    return hazard


def hazard_for_region(guild_id: int | str | None, region: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    state = get_hazard_zone(guild_id, now)
    return state if state.get("region") == region else None


def _flatten_items(item_db: Mapping[str, Mapping[str, Any]], tiers: Iterable[str]) -> List[Tuple[str, str, Mapping[str, Any]]]:
    pool: List[Tuple[str, str, Mapping[str, Any]]] = []
    for tier in tiers:
        rows = item_db.get(tier, {})
        if isinstance(rows, Mapping):
            for name, info in rows.items():
                pool.append((str(tier), str(name), info if isinstance(info, Mapping) else {}))
    return pool


def register_v637_dynamic_events(
    bot: commands.Bot,
    get_user,
    check_registered,
    save_data,
    world_data: Dict[str, Any],
    item_db: Mapping[str, Mapping[str, Any]],
    find_item,
    get_item_slot,
    calculate_user_power,
) -> None:
    def resolve_item_name(user: Dict[str, Any], raw_name: str = "") -> Optional[str]:
        raw_name = str(raw_name or "").strip()
        if raw_name:
            return raw_name if raw_name in user.get("inventory", []) else None
        return current_weapon_name(user)

    @bot.command(name="오늘의", aliases=["오늘의운세", "운세"])
    async def daily_fortune(ctx: commands.Context, *, 주제: str = "운세"):
        if not await check_registered(ctx):
            return
        if ctx.invoked_with == "오늘의" and str(주제).strip() not in {"", "운세"}:
            await ctx.send("⚠️ 사용법: `!오늘의 운세` 또는 `!오늘의운세`")
            return
        user = get_user(ctx.author.id)
        record = ensure_daily_fortune(user, ctx.author.id)
        reward_line = ""
        if not bool(record.get("claimed")):
            rng = _stable_rng("fortune-claim", ctx.author.id, record["date"])
            low, high = record.get("claim", (1000, 2000))
            reward = rng.randint(int(low), int(high))
            user["balance"] = int(user.get("balance", 0)) + reward
            user.setdefault("stats", {})["earned"] = int(user.setdefault("stats", {}).get("earned", 0)) + reward
            record["claimed"] = True
            if record.get("name") == "대길":
                user.setdefault("materials", {})["행운의 부적"] = int(user.setdefault("materials", {}).get("행운의 부적", 0)) + 1
                reward_line = f"\n🎁 첫 확인 보상 **식량 +{reward:,}**, 행운의 부적 1개"
            else:
                reward_line = f"\n🎁 첫 확인 보상 **식량 +{reward:,}**"
            save_data()
        else:
            reward_line = "\n✅ 오늘의 첫 확인 보상은 이미 받았습니다."
        embed = discord.Embed(
            title=f"{record['emoji']} {ctx.author.display_name}님의 오늘의 운세 · {record['name']}",
            description=f"**{record['summary']}**{reward_line}",
            color=int(record.get("color", 0x607D9E)),
        )
        embed.add_field(name="행운의 아이템", value=f"**{record['item']}**", inline=True)
        embed.add_field(name="행운의 음식", value=f"**{record['food_item']}**", inline=True)
        embed.add_field(name="행운의 방향", value=f"**{record['direction']}**", inline=True)
        embed.add_field(
            name="오늘의 미세 효과",
            value=(
                f"전투 ×{float(record['combat']):.2f} · 생활 ×{float(record['life']):.2f} · "
                f"보상 ×{float(record['reward']):.2f}\n시장 구매 ×{float(record['market']):.3f} · 무전 보상 ×{float(record['radio']):.2f}"
            ),
            inline=False,
        )
        embed.add_field(name="추천", value=record["action"], inline=False)
        embed.set_footer(text="운세 효과는 매일 자정(KST)에 바뀌며, 확인한 날에만 적용됩니다.")
        await ctx.send(embed=embed)

    def _radio_event(user: Dict[str, Any], user_id: int | str, guild_id: int | str) -> Dict[str, Any]:
        from apocalypse_bot.commands.v636_world_combat import get_weather_state
        weather = get_weather_state(guild_id)
        period = str(weather.get("period"))
        event = user.get("radio_event")
        if not isinstance(event, dict) or event.get("period") != period:
            rng = _stable_rng("radio", user_id, guild_id, period)
            signal = dict(rng.choice(RADIO_SIGNALS))
            event = {
                "period": period,
                "signal": signal,
                "correct": rng.randrange(len(RADIO_CHOICES)),
                "resolved": False,
                "success": None,
                "result": "",
                "expires_at": weather.get("next_at", ""),
            }
            user["radio_event"] = event
        return event

    async def _resolve_radio(interaction: discord.Interaction, choice_index: int, period: str):
        user = get_user(interaction.user.id)
        guild_id = interaction.guild.id if interaction.guild else 0
        event = _radio_event(user, interaction.user.id, guild_id)
        if str(event.get("period")) != str(period):
            await interaction.response.send_message("📻 신호가 이미 끊겼습니다. `!무전`으로 새 신호를 확인하세요.", ephemeral=True)
            return
        if event.get("resolved"):
            await interaction.response.send_message(str(event.get("result") or "이미 해독한 신호입니다."), ephemeral=True)
            return
        success = int(event.get("correct", -1)) == int(choice_index)
        modifiers = active_fortune_modifiers(user)
        signal = event.get("signal", {})
        rng = _stable_rng("radio-result", interaction.user.id, event.get("period"), choice_index)
        if success:
            base = rng.randint(12_000, 28_000)
            food = int(base * float(modifiers.get("radio", 1.0)))
            resource = rng.choice(("나무", "광석", "고철"))
            amount = rng.randint(4, 12)
            user["balance"] = int(user.get("balance", 0)) + food
            user.setdefault("resources", {})[resource] = int(user.setdefault("resources", {}).get(resource, 0)) + amount
            user.setdefault("materials", {})["암호 해독 조각"] = int(user.setdefault("materials", {}).get("암호 해독 조각", 0)) + 1
            rare_line = ""
            if rng.random() < 0.04 + float(modifiers.get("box_luck", 0.0)):
                pool = _flatten_items(item_db, ("희귀", "영웅"))
                if pool:
                    tier, item_name, info = rng.choice(pool)
                    if item_name not in user.setdefault("inventory", []):
                        user["inventory"].append(item_name)
                        user.setdefault("enhancements", {})[item_name] = 0
                        rare_line = f"\n🎁 숨겨진 보급품 **[{tier}] {item_name}**"
                    else:
                        duplicate = max(10_000, int(info.get("price", 0)) // 5)
                        user["balance"] += duplicate
                        rare_line = f"\n♻️ 중복 장비 환전 **+{duplicate:,} 식량**"
            result = f"✅ **{signal.get('name', '신호')} 해독 성공**\n🥫 식량 +{food:,} · {resource} +{amount} · 암호 해독 조각 +1{rare_line}"
        else:
            stamina_loss = rng.randint(3, 7)
            user["stamina"] = max(0, int(user.get("stamina", 100)) - stamina_loss)
            infection = 1 if rng.random() < 0.35 else 0
            if infection:
                user["infection"] = min(100, int(user.get("infection", 0)) + infection)
            result = f"❌ **신호 추적 실패**\n⚡ 스태미나 -{stamina_loss}" + (f" · 🦠 감염도 +{infection}%" if infection else "")
        event["resolved"] = True
        event["success"] = success
        event["result"] = result
        save_data()
        await interaction.response.edit_message(content=result, embed=None, view=None)

    class RadioView(discord.ui.View):
        def __init__(self, owner_id: int, period: str):
            super().__init__(timeout=240)
            self.owner_id = owner_id
            self.period = period
            for index, (label, emoji) in enumerate(RADIO_CHOICES):
                button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, row=0)
                async def callback(interaction: discord.Interaction, idx=index):
                    if interaction.user.id != self.owner_id:
                        await interaction.response.send_message("이 신호를 수신한 생존자만 해독할 수 있습니다.", ephemeral=True)
                        return
                    await _resolve_radio(interaction, idx, self.period)
                button.callback = callback
                self.add_item(button)

    @bot.command(name="무전", aliases=["무전해독", "구조신호", "sos", "SOS"])
    async def radio_command(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        guild_id = ctx.guild.id if ctx.guild else 0
        event = _radio_event(user, ctx.author.id, guild_id)
        if event.get("resolved"):
            await ctx.send(f"📻 이번 환경 구간의 신호는 이미 처리했습니다.\n{event.get('result', '')}")
            return
        signal = event.get("signal", {})
        embed = discord.Embed(
            title=f"{signal.get('emoji', '📻')} 생존자 무전 수신 · {signal.get('name', '미확인 신호')}",
            description=str(signal.get("text", "잡음만 들립니다.")),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="해독 방식", value="세 방식 중 하나만 선택할 수 있습니다. 오답은 스태미나·감염 위험이 있습니다.", inline=False)
        embed.add_field(name="가능 보상", value="식량·기지 자원·암호 조각, 낮은 확률로 희귀 장비", inline=False)
        embed.set_footer(text="날씨가 바뀌면 새로운 신호가 생성됩니다.")
        await ctx.send(embed=embed, view=RadioView(ctx.author.id, str(event.get("period"))))

    @bot.command(name="내구도")
    async def durability_command(ctx: commands.Context, *, 장비명: str = ""):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        item_name = resolve_item_name(user, 장비명)
        if not item_name:
            await ctx.send("⚠️ 장착한 무기가 없거나 보유하지 않은 장비입니다. `!내구도 장비이름`")
            return
        if get_item_slot(item_name) != "무기":
            await ctx.send("⚠️ 내구도 시스템은 현재 무기 슬롯에 적용됩니다.")
            return
        status = weapon_durability_status(user, item_name)
        mods = _mods_for(user, item_name)
        factor = equipment_condition_multiplier(user, item_name)
        embed = discord.Embed(title=f"🔧 무기 상태 · {item_name}", color=discord.Color.dark_gold())
        embed.add_field(name="내구도", value=f"{status['emoji']} **{status['current']} / {status['maximum']} · {status['label']}**", inline=False)
        embed.add_field(name="현재 출력", value=f"기본 전투 기여도의 **{factor * 100:.0f}%**", inline=True)
        embed.add_field(name="개조 부품", value=", ".join(mods) if mods else "없음", inline=True)
        embed.add_field(name="관리", value="`!무기수리 [장비명]` · `!개조목록` · `!무기개조 장비명 부품명`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="무기수리", aliases=["수리"])
    async def weapon_repair(ctx: commands.Context, *, 장비명: str = ""):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        item_name = resolve_item_name(user, 장비명)
        if not item_name or get_item_slot(item_name) != "무기":
            await ctx.send("⚠️ 사용법: `!무기수리 장비이름` · 장착 무기는 이름을 생략할 수 있습니다.")
            return
        status = weapon_durability_status(user, item_name)
        missing = int(status["maximum"]) - int(status["current"])
        if missing <= 0:
            await ctx.send(f"🟢 **{item_name}**은 이미 최대 내구도입니다.")
            return
        materials = user.setdefault("materials", {})
        if int(materials.get("수리 키트", 0)) > 0:
            materials["수리 키트"] -= 1
            user.setdefault("equipment_durability", {})[item_name] = status["maximum"]
            save_data()
            await ctx.send(f"🧰 수리 키트 사용 · **{item_name}** 내구도 **{status['maximum']} / {status['maximum']}**")
            return
        scrap = max(1, math.ceil(missing / 8))
        food = missing * 800
        resources = user.setdefault("resources", {})
        if int(resources.get("고철", 0)) < scrap or int(user.get("balance", 0)) < food:
            await ctx.send(
                f"⚠️ 수리 재료 부족 · 필요 **고철 {scrap}개 + 식량 {food:,}**\n"
                f"보유 고철 **{int(resources.get('고철', 0))}개** · 식량 **{int(user.get('balance', 0)):,}**\n"
                "수리 키트는 `!랜덤박스` 또는 떠돌이 상인 `!까마귀`에서 얻을 수 있습니다."
            )
            return
        resources["고철"] -= scrap
        user["balance"] -= food
        user.setdefault("equipment_durability", {})[item_name] = status["maximum"]
        save_data()
        await ctx.send(f"🔧 **{item_name}** 수리 완료 · 고철 -{scrap} · 식량 -{food:,} · 내구도 최대")

    @bot.command(name="개조목록")
    async def mod_list(ctx: commands.Context):
        embed = discord.Embed(title="🛠️ 무기 개조 부품", color=discord.Color.dark_gold())
        for name, info in WEAPON_PARTS.items():
            costs = " · ".join(f"{key} {value}" for key, value in info["craft"].items())
            embed.add_field(
                name=name,
                value=f"{info['desc']}\n제작: {costs} · 식량 {int(info['food']):,}",
                inline=False,
            )
        embed.set_footer(text="부품 제작 → 무기 개조 순서 · 무기당 최대 2개 장착")
        await ctx.send(embed=embed)

    @bot.command(name="개조부품제작", aliases=["부품제작"])
    async def craft_mod_part(ctx: commands.Context, *, 부품명: str):
        if not await check_registered(ctx):
            return
        part = str(부품명).strip()
        info = WEAPON_PARTS.get(part)
        if not info:
            await ctx.send("⚠️ 존재하지 않는 부품입니다. `!개조목록`을 확인하세요.")
            return
        user = get_user(ctx.author.id)
        resources = user.setdefault("resources", {})
        missing = [f"{name} {amount}" for name, amount in info["craft"].items() if int(resources.get(name, 0)) < int(amount)]
        if int(user.get("balance", 0)) < int(info["food"]):
            missing.append(f"식량 {int(info['food']):,}")
        if missing:
            await ctx.send("⚠️ 제작 재료 부족: " + ", ".join(missing))
            return
        for name, amount in info["craft"].items():
            resources[name] = int(resources.get(name, 0)) - int(amount)
        user["balance"] = int(user.get("balance", 0)) - int(info["food"])
        user.setdefault("materials", {})[part] = int(user.setdefault("materials", {}).get(part, 0)) + 1
        save_data()
        await ctx.send(f"🛠️ **{part}** 제작 완료 · `!무기개조 장비이름 {part}`")

    def _parse_item_part(raw: str) -> Tuple[Optional[str], Optional[str]]:
        text = str(raw or "").strip()
        for part in sorted(WEAPON_PARTS, key=len, reverse=True):
            suffix = f" {part}"
            if text.endswith(suffix):
                return text[:-len(suffix)].strip(), part
        return None, None

    @bot.command(name="무기개조", aliases=["개조"])
    async def weapon_mod(ctx: commands.Context, *, 입력: str):
        if not await check_registered(ctx):
            return
        item_name, part = _parse_item_part(입력)
        if not item_name or not part:
            await ctx.send("⚠️ 사용법: `!무기개조 장비이름 부품이름` · `!개조목록`")
            return
        user = get_user(ctx.author.id)
        if item_name not in user.get("inventory", []) or get_item_slot(item_name) != "무기":
            await ctx.send("⚠️ 보유한 무기만 개조할 수 있습니다.")
            return
        if not part_compatible(item_name, part):
            await ctx.send(f"⚠️ **{part}**은 **{item_name}** 계열과 호환되지 않습니다.")
            return
        owned_parts = int(user.setdefault("materials", {}).get(part, 0))
        if owned_parts <= 0:
            await ctx.send(f"⚠️ **{part}**이 없습니다. `!개조부품제작 {part}`")
            return
        _, _, _ = ensure_weapon_state(user, item_name)
        mods = user.setdefault("weapon_mods", {}).setdefault(item_name, [])
        if part in mods:
            await ctx.send("⚠️ 이미 장착한 부품입니다.")
            return
        if len(mods) >= 2:
            await ctx.send("⚠️ 무기당 개조 부품은 최대 2개입니다. `!개조해제 장비이름 부품이름`")
            return
        mods.append(part)
        user["materials"][part] -= 1
        save_data()
        await ctx.send(f"✅ **{item_name}**에 **{part}** 장착 · 현재 부품: {', '.join(mods)}")

    @bot.command(name="개조해제")
    async def remove_mod(ctx: commands.Context, *, 입력: str):
        if not await check_registered(ctx):
            return
        item_name, part = _parse_item_part(입력)
        if not item_name or not part:
            await ctx.send("⚠️ 사용법: `!개조해제 장비이름 부품이름`")
            return
        user = get_user(ctx.author.id)
        mods = user.setdefault("weapon_mods", {}).setdefault(item_name, [])
        if part not in mods:
            await ctx.send("⚠️ 해당 부품이 장착되어 있지 않습니다.")
            return
        mods.remove(part)
        # 분해 손실을 적용하되 빈손으로 끝나지 않도록 고철을 환급합니다.
        user.setdefault("resources", {})["고철"] = int(user.setdefault("resources", {}).get("고철", 0)) + 5
        save_data()
        await ctx.send(f"🔩 **{part}** 해제 · 회수 불가, 고철 5개 반환")

    def _crow_market(guild_id: int | str) -> Dict[str, Any]:
        from apocalypse_bot.commands.v636_world_combat import get_weather_state
        weather = get_weather_state(guild_id)
        period = str(weather.get("period"))
        rng = _stable_rng("crow-market", guild_id, period)
        present = rng.random() < 0.30
        stock: List[Dict[str, Any]] = []
        if present:
            mod = rng.choice(tuple(WEAPON_PARTS))
            stock.append({"type": "material", "name": "수리 키트", "qty": 1, "chips": 7_500})
            stock.append({"type": "material", "name": mod, "qty": 1, "chips": 12_000 + rng.randrange(0, 5_001, 500)})
            resource = rng.choice(("나무", "광석", "고철"))
            stock.append({"type": "resource", "name": resource, "qty": 20, "chips": 6_000})
            pool = _flatten_items(item_db, ("영웅", "전설", "신화"))
            if pool:
                tier, item_name, info = rng.choice(pool)
                stock.append({"type": "equipment", "name": item_name, "tier": tier, "qty": 1, "chips": max(28_000, min(150_000, int(info.get("price", 100_000)) // 8))})
        return {"period": period, "present": present, "stock": stock, "remaining": int(weather.get("remaining", 0))}

    @bot.command(name="까마귀", aliases=["떠돌이상인", "게릴라상점"])
    async def crow_shop(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        market = _crow_market(guild_id)
        if not market["present"]:
            await ctx.send("🐦‍⬛ 까마귀의 천막이 보이지 않습니다. 날씨가 바뀔 때 다시 출현 여부가 결정됩니다.")
            return
        from apocalypse_bot.commands.v40_black_casino import casino_chips
        user = get_user(ctx.author.id)
        purchased = user.setdefault("crow_purchases", {}).get(market["period"], [])
        lines = []
        for idx, row in enumerate(market["stock"], 1):
            sold = " · **구매 완료**" if idx in purchased else ""
            tier = f"[{row.get('tier')}] " if row.get("tier") else ""
            lines.append(f"`{idx}` {tier}**{row['name']} ×{row['qty']}** · {row['chips']:,}칩{sold}")
        embed = discord.Embed(
            title="🐦‍⬛ 떠돌이 암상인 · 까마귀",
            description="\n".join(lines),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="구매", value="`!까마귀구매 번호` · 각 상품은 생존자당 1회", inline=False)
        embed.add_field(name="보유 칩", value=f"**{casino_chips(user):,}칩**", inline=True)
        embed.add_field(name="철수까지", value=f"**{max(1, market['remaining'] // 60)}분**", inline=True)
        embed.set_footer(text="카지노 게임 결과 이미지와 무관한 기간 한정 물물교환 상점")
        await ctx.send(embed=embed)

    @bot.command(name="까마귀구매")
    async def crow_buy(ctx: commands.Context, 번호: int):
        if not await check_registered(ctx):
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        market = _crow_market(guild_id)
        if not market["present"]:
            await ctx.send("🐦‍⬛ 상인은 이미 철수했습니다.")
            return
        if 번호 < 1 or 번호 > len(market["stock"]):
            await ctx.send("⚠️ 상품 번호를 확인하세요. `!까마귀`")
            return
        user = get_user(ctx.author.id)
        purchases = user.setdefault("crow_purchases", {}).setdefault(market["period"], [])
        if 번호 in purchases:
            await ctx.send("⚠️ 이번 방문에서 이미 구매한 상품입니다.")
            return
        row = market["stock"][번호 - 1]
        from apocalypse_bot.commands.v40_black_casino import casino_chips, add_casino_chips
        if casino_chips(user) < int(row["chips"]):
            await ctx.send(f"⚠️ 카지노 칩 부족 · 필요 {int(row['chips']):,}칩")
            return
        add_casino_chips(user, -int(row["chips"]))
        if row["type"] == "material":
            user.setdefault("materials", {})[row["name"]] = int(user.setdefault("materials", {}).get(row["name"], 0)) + int(row["qty"])
            result = f"{row['name']} ×{row['qty']}"
        elif row["type"] == "resource":
            user.setdefault("resources", {})[row["name"]] = int(user.setdefault("resources", {}).get(row["name"], 0)) + int(row["qty"])
            result = f"{row['name']} ×{row['qty']}"
        else:
            item_name = str(row["name"])
            if item_name not in user.setdefault("inventory", []):
                user["inventory"].append(item_name)
                user.setdefault("enhancements", {})[item_name] = 0
                result = f"[{row.get('tier')}] {item_name}"
            else:
                compensation = 80_000
                user["balance"] = int(user.get("balance", 0)) + compensation
                result = f"중복 장비 환전 +{compensation:,} 식량"
        purchases.append(번호)
        save_data()
        await ctx.send(f"🐦‍⬛ 거래 완료 · **{result}** · 칩 -{int(row['chips']):,}")

    @bot.command(name="위험구역", aliases=["돌연변이구역", "오염구역"])
    async def hazard_command(ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else 0
        state = get_hazard_zone(guild_id)
        embed = discord.Embed(
            title=f"{state['emoji']} 오늘의 돌연변이 구역 · {state['region']}",
            description=state["desc"],
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="탐색 성공률", value=f"**-{state['success_penalty'] * 100:.0f}%p**", inline=True)
        embed.add_field(name="성공 보상", value=f"**×{state['reward_mult']:.2f}**", inline=True)
        embed.add_field(name="피해 위험", value=f"**×{state['damage_mult']:.2f}**", inline=True)
        embed.add_field(name="도전", value=f"`!지역이동 {state['region']}` → `!지역탐색`", inline=False)
        embed.set_footer(text="매일 자정(KST)에 지정 구역과 위험 유형이 변경됩니다.")
        await ctx.send(embed=embed)

    @bot.command(name="랜덤박스", aliases=["대형랜덤박스", "보급박스"])
    async def random_box(ctx: commands.Context, 수량: int = 1):
        if not await check_registered(ctx):
            return
        if 수량 < 1 or 수량 > 3:
            await ctx.send("⚠️ 한 번에 1~3개만 열 수 있습니다. `!랜덤박스 3`")
            return
        user = get_user(ctx.author.id)
        date_key = _today_key()
        daily = user.setdefault("random_box_daily", {})
        if daily.get("date") != date_key:
            daily.clear()
            daily.update({"date": date_key, "opened": 0})
        opened = int(daily.get("opened", 0))
        if opened + 수량 > RANDOM_BOX_DAILY_LIMIT:
            await ctx.send(f"⚠️ 오늘 남은 대형 랜덤박스는 **{max(0, RANDOM_BOX_DAILY_LIMIT - opened)}개**입니다.")
            return
        total_cost = RANDOM_BOX_COST * 수량
        if int(user.get("balance", 0)) < total_cost:
            await ctx.send(f"⚠️ 식량 부족 · 필요 **{total_cost:,}** / 보유 **{int(user.get('balance', 0)):,}**")
            return
        user["balance"] -= total_cost
        modifiers = active_fortune_modifiers(user)
        # 운세는 최상위 결과에 최대 약 0.9%p만 보태도록 제한합니다.
        luck = float(modifiers.get("box_luck", 0.0)) * 0.20
        lines: List[str] = []
        for number in range(1, 수량 + 1):
            roll = random.random() - luck
            if roll < 0.015:
                pool = _flatten_items(item_db, ("전설", "신화", "유일"))
                if pool:
                    tier, item_name, info = random.choice(pool)
                    if item_name not in user.setdefault("inventory", []):
                        user["inventory"].append(item_name)
                        user.setdefault("enhancements", {})[item_name] = 0
                        result = f"🌟 [{tier}] {item_name}"
                    else:
                        refund = max(100_000, int(info.get("price", 0)) // 4)
                        user["balance"] += refund
                        result = f"♻️ 중복 장비 환전 +{refund:,} 식량"
                else:
                    result = "🧰 수리 키트 2개"
                    user.setdefault("materials", {})["수리 키트"] = int(user.setdefault("materials", {}).get("수리 키트", 0)) + 2
            elif roll < 0.075:
                jackpot = random.randint(650_000, 1_600_000)
                user["balance"] += jackpot
                result = f"💰 대형 식량 꾸러미 +{jackpot:,}"
            elif roll < 0.19:
                part = random.choice(tuple(WEAPON_PARTS))
                user.setdefault("materials", {})[part] = int(user.setdefault("materials", {}).get(part, 0)) + 1
                result = f"🛠️ 개조 부품 · {part}"
            elif roll < 0.33:
                kits = random.randint(1, 2)
                user.setdefault("materials", {})["수리 키트"] = int(user.setdefault("materials", {}).get("수리 키트", 0)) + kits
                result = f"🔧 수리 키트 ×{kits}"
            elif roll < 0.58:
                resource = random.choice(("나무", "광석", "고철"))
                amount = random.randint(25, 70)
                user.setdefault("resources", {})[resource] = int(user.setdefault("resources", {}).get(resource, 0)) + amount
                result = f"🏗️ {resource} ×{amount}"
            elif roll < 0.82:
                material = random.choice(("철", "볼트", "전자부품", "화약", "스크랩"))
                amount = random.randint(4, 12)
                user.setdefault("materials", {})[material] = int(user.setdefault("materials", {}).get(material, 0)) + amount
                result = f"🧰 {material} ×{amount}"
            elif roll < 0.94:
                refund = random.randint(60_000, 190_000)
                user["balance"] += refund
                result = f"🥫 일부 식량 회수 +{refund:,}"
            else:
                scrap = random.randint(2, 8)
                user.setdefault("resources", {})["고철"] = int(user.setdefault("resources", {}).get("고철", 0)) + scrap
                result = f"📦 거의 빈 상자 · 고철 ×{scrap}"
            lines.append(f"🎁 **{number}번째** — {result}")
        daily["opened"] = opened + 수량
        user.setdefault("stats", {})["random_boxes"] = int(user.setdefault("stats", {}).get("random_boxes", 0)) + 수량
        save_data()
        embed = discord.Embed(
            title="🎁 대형 랜덤박스 개봉",
            description="\n".join(lines),
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="지불", value=f"식량 **-{total_cost:,}**", inline=True)
        embed.add_field(name="오늘 남은 횟수", value=f"**{RANDOM_BOX_DAILY_LIMIT - daily['opened']}개**", inline=True)
        embed.set_footer(text="오늘의 운세를 먼저 확인하면 상위 결과 확률이 소폭 상승합니다.")
        await ctx.send(embed=embed)

    @bot.command(name="테스트", aliases=["패치테스트"])
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def patch_test(ctx: commands.Context, 모드: str = "기본"):
        # 실제 재화·전투 상태를 변경하지 않는 읽기 전용 진단입니다.
        checks: List[Tuple[str, bool, str]] = []
        expected = (
            "날씨", "오늘의", "오늘의운세", "무전", "내구도", "무기수리", "개조목록",
            "개조부품제작", "무기개조", "까마귀", "까마귀구매", "위험구역", "랜덤박스",
            "전투", "던전전술", "테스트", "패치노트", "명령어",
        )
        missing = [name for name in expected if bot.get_command(name) is None]
        checks.append(("명령어 등록", not missing, "누락 없음" if not missing else ", ".join(missing)))
        try:
            from apocalypse_bot.commands.v636_world_combat import WEATHER_TABLE, get_weather_state
            state = get_weather_state(ctx.guild.id if ctx.guild else 0)
            hours = float(state.get("duration_hours", 0))
            checks.append(("랜덤 날씨 주기", 2.0 <= hours <= 5.0, f"{hours:g}시간 · {state.get('name')}"))
            checks.append(("날씨 종류", len(WEATHER_TABLE) >= 12, f"{len(WEATHER_TABLE)}종"))
        except Exception as exc:
            checks.append(("날씨 엔진", False, f"{type(exc).__name__}: {exc}"))
        try:
            hazard = get_hazard_zone(ctx.guild.id if ctx.guild else 0)
            checks.append(("돌연변이 구역", hazard.get("region") in REGION_NAMES, f"{hazard.get('region')} · {hazard.get('name')}"))
        except Exception as exc:
            checks.append(("돌연변이 구역", False, type(exc).__name__))
        try:
            fortune_a = _fortune_payload(ctx.author.id, _today_key())
            fortune_b = _fortune_payload(ctx.author.id, _today_key())
            checks.append(("오늘의 운세 결정성", fortune_a == fortune_b, str(fortune_a.get("name"))))
        except Exception as exc:
            checks.append(("오늘의 운세", False, type(exc).__name__))
        try:
            equipment_count = sum(len(rows) for rows in item_db.values() if isinstance(rows, Mapping))
            checks.append(("장비 데이터", equipment_count >= 70, f"{equipment_count}종"))
        except Exception as exc:
            checks.append(("장비 데이터", False, type(exc).__name__))
        try:
            user = get_user(ctx.author.id)
            probe = copy.deepcopy(user)
            status = weapon_durability_status(probe)
            checks.append(("내구도 데이터", isinstance(probe.get("equipment_durability"), dict), status.get("label", "준비")))
            checks.append(("개조 데이터", isinstance(probe.get("weapon_mods"), dict), f"부품 {len(WEAPON_PARTS)}종"))
        except Exception as exc:
            checks.append(("장비 상태", False, type(exc).__name__))
        try:
            dummy = discord.Embed(title="test")
            from apocalypse_bot.commands.v635_visuals import apply_casino_visual
            checks.append(("카지노 이미지 제거", apply_casino_visual(dummy, "슬롯", "테스트", 0, 100) is None, "첨부 없음"))
        except Exception as exc:
            checks.append(("카지노 이미지 제거", False, type(exc).__name__))
        checks.append(("전술 전투 후크", callable(getattr(bot, "v636_start_combat", None)), "호출 가능"))
        # Discord 명령 사전은 동일 이름을 덮어쓰지 못하므로 등록 수와 유일성을 함께 확인합니다.
        command_names = [command.qualified_name for command in bot.walk_commands()]
        checks.append(("명령 이름 유일성", len(command_names) == len(set(command_names)), f"총 {len(command_names)}개"))

        passed = sum(1 for _, ok, _ in checks if ok)
        failed = len(checks) - passed
        embed = discord.Embed(
            title=f"🧪 ABADDON v6.3.7a 패치 테스트 · {passed}/{len(checks)} 통과",
            description="재화와 전투 상태를 바꾸지 않는 읽기 전용 진단입니다.",
            color=discord.Color.green() if failed == 0 else discord.Color.orange(),
        )
        if str(모드).lower() in {"상세", "전체", "detail", "full"} or failed:
            for name, ok, detail in checks:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(detail)[:1024], inline=False)
        else:
            embed.add_field(name="결과", value=f"✅ 통과 **{passed}** · ❌ 실패 **{failed}**\n상세 보기: `!테스트 상세`", inline=False)
        embed.set_footer(text="Discord 배포 후 버튼 클릭과 권한은 실제 서버에서 별도 확인이 필요합니다.")
        await ctx.send(embed=embed)

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v637_patch_notes(ctx: commands.Context):
            embed = discord.Embed(
                title="🧯 ABADDON v6.3.7a — 장비 모듈 시작 오류 핫픽스",
                description="장비 비주얼 모듈에 남아 있던 잘못된 최상위 호출을 제거해 봇 시작 오류를 수정했습니다. v6.3.7 기능은 그대로 유지됩니다.",
                color=discord.Color.dark_purple(),
            )
            embed.add_field(name="🧯 시작 오류 수정", value="`v633_equipment_crafting.py`의 잘못된 `ebp(image)` 호출 제거 · `NameError` 재발 방지", inline=False)
            embed.add_field(name="🌦️ 변동 날씨 12종", value="고정 6시간 대신 매일 서버별 **2~5시간 랜덤 주기** · 신규 재난/호재 날씨 추가", inline=False)
            embed.add_field(name="📻 무전·SOS", value="`!무전` · 주파수/좌표/긴급응답 선택형 해독 · 환경 구간마다 새 신호", inline=False)
            embed.add_field(name="🔧 내구도·무기 개조", value="전투와 탐색으로 내구도 소모 · 파손 시 전투 기여 감소 · 수리 키트와 개조 부품 6종", inline=False)
            embed.add_field(name="🐦‍⬛ 까마귀·랜덤박스", value="기간 한정 칩 상점 `!까마귀` · 하루 3회 대형 보급 상자 `!랜덤박스`", inline=False)
            embed.add_field(name="☣️ 돌연변이 구역", value="매일 한 지역이 고위험·고보상 구역으로 지정 · `!위험구역`", inline=False)
            embed.add_field(name="🌟 오늘의 운세", value="`!오늘의 운세` / `!오늘의운세` · 일일 미세 버프와 첫 확인 보상", inline=False)
            embed.add_field(name="🧪 자체 테스트", value="`!테스트` / `!테스트 상세` · 명령 등록·날씨·장비·전투 후크를 읽기 전용으로 점검", inline=False)
            embed.set_footer(text="최신 버전 v6.3.7a · 장비 모듈 시작 오류 핫픽스")
            await ctx.send(embed=embed)
        patch.callback = v637_patch_notes
        patch.help = "ABADDON v6.3.7a 장비 모듈 시작 오류 핫픽스를 확인합니다."
        patch.description = patch.help

    bot.v637_version = VERSION
