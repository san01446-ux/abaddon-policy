from datetime import datetime, timezone
import random

from discord.ext import commands

MEDICINES = {
    "붕대": {"emoji": "🩹", "desc": "출혈 치료 및 HP 8 회복", "price": 800},
    "소독약": {"emoji": "🧴", "desc": "감염도 8 감소, 출혈 치료 보조", "price": 1400},
    "항생제": {"emoji": "💊", "desc": "감염도 20 감소", "price": 3200},
    "진통제": {"emoji": "💉", "desc": "골절·중독 완화 및 HP 12 회복", "price": 2200},
    "백신": {"emoji": "🧪", "desc": "감염도 45 감소, 감염 상태 제거 가능", "price": 12000},
}

STATUS_LABELS = {
    "출혈": "🩸 출혈",
    "감염": "🤢 감염",
    "중독": "☠️ 중독",
    "골절": "🦴 골절",
    "기절": "😵 기절",
}

DUNGEON_INFECTION_CHANCE = {
    "약함": 0.05,
    "보통": 0.12,
    "강함": 0.20,
    "지옥": 0.40,
}


def _now():
    return datetime.now(timezone.utc)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def ensure_conditions(user):
    if not isinstance(user.get("infection"), int):
        user["infection"] = 0
    user["infection"] = max(0, min(100, user["infection"]))

    if not isinstance(user.get("conditions"), dict):
        user["conditions"] = {}
    for name in STATUS_LABELS:
        user["conditions"].setdefault(name, 0)

    if not isinstance(user.get("medical_items"), dict):
        user["medical_items"] = {}
    for name in MEDICINES:
        user["medical_items"].setdefault(name, 0)

    user.setdefault("last_condition_update", _now().isoformat())
    return user


def active_conditions(user):
    ensure_conditions(user)
    return [name for name, value in user["conditions"].items() if int(value or 0) > 0]


def condition_text(user):
    active = active_conditions(user)
    return ", ".join(STATUS_LABELS.get(name, name) for name in active) if active else "✅ 정상"


def refresh_conditions(user, get_max_hp):
    ensure_conditions(user)
    now = _now()
    previous = _parse_time(user.get("last_condition_update")) or now
    elapsed_minutes = max(0, int((now - previous).total_seconds() // 60))
    messages = []

    if elapsed_minutes >= 5 and user["conditions"].get("출혈", 0) > 0:
        ticks = elapsed_minutes // 5
        damage = min(20, ticks * user["conditions"]["출혈"])
        user["hp"] = max(1, user.get("hp", 1) - damage)
        messages.append(f"🩸 출혈 피해 -{damage} HP")

    if elapsed_minutes >= 30 and user["conditions"].get("감염", 0) > 0:
        growth = min(15, elapsed_minutes // 30 * user["conditions"]["감염"])
        user["infection"] = min(100, user["infection"] + growth)
        messages.append(f"🦠 감염도 +{growth}%")

    # 가벼운 중독은 시간이 지나면 약해진다.
    if elapsed_minutes >= 20 and user["conditions"].get("중독", 0) > 0:
        user["conditions"]["중독"] = max(0, user["conditions"]["중독"] - elapsed_minutes // 20)

    if user["infection"] >= 25:
        user["conditions"]["감염"] = max(1, user["conditions"].get("감염", 0))
    elif user["infection"] == 0:
        user["conditions"]["감염"] = 0

    user["hp"] = min(get_max_hp(user), max(1, user.get("hp", 1)))
    user["last_condition_update"] = now.isoformat()
    return messages


def apply_dungeon_conditions(user, difficulty, victory):
    ensure_conditions(user)
    events = []
    chance = DUNGEON_INFECTION_CHANCE[difficulty]
    if victory:
        chance *= 0.55

    if random.random() < chance:
        amount = random.randint(
            {"약함": 3, "보통": 6, "강함": 10, "지옥": 16}[difficulty],
            {"약함": 7, "보통": 12, "강함": 18, "지옥": 28}[difficulty],
        )
        user["infection"] = min(100, user["infection"] + amount)
        user["conditions"]["감염"] = max(1, user["conditions"].get("감염", 0))
        events.append(f"🦠 감염도 +{amount}%")

    injury_chance = {"약함": 0.05, "보통": 0.10, "강함": 0.18, "지옥": 0.28}[difficulty]
    if victory:
        injury_chance *= 0.45

    if random.random() < injury_chance:
        possible = ["출혈", "중독"]
        if difficulty in ("강함", "지옥"):
            possible.append("골절")
        status = random.choice(possible)
        user["conditions"][status] = min(3, user["conditions"].get(status, 0) + 1)
        events.append(f"{STATUS_LABELS[status]} 발생")

    if user["infection"] >= 100:
        user["infection"] = 85
        user["conditions"]["기절"] = 1
        events.append("😵 감염 쇼크로 기절 — 구조 후 감염도 85%")

    return events


def exploration_modifier(user):
    ensure_conditions(user)
    penalty = 0.0
    if user["conditions"].get("골절", 0):
        penalty += 0.20
    if user["conditions"].get("중독", 0):
        penalty += 0.10
    if user["infection"] >= 70:
        penalty += 0.15
    return max(0.55, 1.0 - penalty)


def register_condition_commands(bot, get_user, check_registered, save_data, get_max_hp):
    @bot.command(name="의약품")
    async def medicines(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        ensure_conditions(user)
        lines = ["💊 **[보유 의약품]**"]
        for name, info in MEDICINES.items():
            lines.append(f"{info['emoji']} {name}: **{user['medical_items'][name]}개** — {info['desc']}")
        lines.append("\n구매: `!약품구매 이름 수량` / 사용: `!사용 이름`")
        await ctx.send("\n".join(lines))

    @bot.command(name="약품구매")
    async def buy_medicine(ctx, 이름: str = "", 수량: int = 1):
        if not await check_registered(ctx):
            return
        if 이름 not in MEDICINES or 수량 < 1 or 수량 > 99:
            await ctx.send("⚠️ 사용법: `!약품구매 붕대 2` (한 번에 1~99개)")
            return
        user = get_user(ctx.author.id)
        ensure_conditions(user)
        cost = MEDICINES[이름]["price"] * 수량
        if user.get("balance", 0) < cost:
            await ctx.send(f"⚠️ 식량이 부족합니다. 필요 **{cost:,}개** / 보유 **{user.get('balance', 0):,}개**")
            return
        user["balance"] -= cost
        user["medical_items"][이름] += 수량
        save_data()
        await ctx.send(f"💊 **{이름} {수량}개** 구매 완료! 비용: 식량 **{cost:,}개**")

    @bot.command(name="사용")
    async def use_medicine(ctx, *, 이름: str = ""):
        if not await check_registered(ctx):
            return
        이름 = 이름.strip()
        if 이름 not in MEDICINES:
            await ctx.send("⚠️ 사용법: `!사용 붕대` / `!의약품`에서 목록 확인")
            return
        user = get_user(ctx.author.id)
        ensure_conditions(user)
        if user["medical_items"].get(이름, 0) <= 0:
            await ctx.send(f"⚠️ **{이름}**을 보유하고 있지 않습니다.")
            return

        before = (user["hp"], user["infection"], dict(user["conditions"]))
        result = []
        if 이름 == "붕대":
            user["conditions"]["출혈"] = 0
            user["hp"] = min(get_max_hp(user), user["hp"] + 8)
            result.append("출혈 치료, HP 회복")
        elif 이름 == "소독약":
            user["infection"] = max(0, user["infection"] - 8)
            user["conditions"]["출혈"] = max(0, user["conditions"]["출혈"] - 1)
            result.append("감염도 -8%, 출혈 완화")
        elif 이름 == "항생제":
            user["infection"] = max(0, user["infection"] - 20)
            result.append("감염도 -20%")
        elif 이름 == "진통제":
            user["conditions"]["골절"] = max(0, user["conditions"]["골절"] - 1)
            user["conditions"]["중독"] = max(0, user["conditions"]["중독"] - 1)
            user["hp"] = min(get_max_hp(user), user["hp"] + 12)
            result.append("골절·중독 완화, HP 회복")
        elif 이름 == "백신":
            user["infection"] = max(0, user["infection"] - 45)
            if user["infection"] < 25:
                user["conditions"]["감염"] = 0
            result.append("감염도 -45%")

        if user["infection"] == 0:
            user["conditions"]["감염"] = 0
        after = (user["hp"], user["infection"], dict(user["conditions"]))
        if before == after:
            await ctx.send(f"⚠️ 지금은 **{이름}**을 사용할 필요가 없습니다.")
            return
        user["medical_items"][이름] -= 1
        save_data()
        await ctx.send(f"{MEDICINES[이름]['emoji']} **{이름} 사용 완료** — " + ", ".join(result))

    @bot.command(name="병원")
    async def hospital(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        ensure_conditions(user)
        severity = sum(int(v or 0) for v in user["conditions"].values())
        missing_hp = max(0, get_max_hp(user) - user["hp"])
        cost = 1400 + severity * 1800 + user["infection"] * 90 + missing_hp * 25

        if severity == 0 and user["infection"] == 0 and missing_hp == 0:
            await ctx.send("🏥 현재 치료가 필요하지 않습니다. 아주 멀쩡합니다.")
            return
        if user.get("balance", 0) < cost:
            await ctx.send(
                f"🏥 치료비는 식량 **{cost:,}개**입니다.\n"
                f"현재 보유: **{user.get('balance', 0):,}개**"
            )
            return

        user["balance"] -= cost
        user["hp"] = get_max_hp(user)
        user["infection"] = max(0, user["infection"] - 35)
        for name in ("출혈", "중독", "골절", "기절"):
            user["conditions"][name] = 0
        if user["infection"] < 25:
            user["conditions"]["감염"] = 0
        save_data()
        await ctx.send(
            f"🏥 **[치료 완료]** 비용 식량 **{cost:,}개**\n"
            f"❤️ HP 완전 회복 / 🦠 감염도 **{user['infection']}%**\n"
            f"📌 현재 상태: {condition_text(user)}"
        )
