from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v637_dynamic_events import (
    active_fortune_modifiers,
    consume_weapon_durability,
    weapon_action_multiplier,
    weapon_durability_status,
)

VERSION = "6.3.7"
KST = timezone(timedelta(hours=9))
WEATHER_INTERVAL_HOURS = (2, 3, 4, 5)

WEATHER_TABLE = (
    {
        "id": "clear", "emoji": "☀️", "name": "맑음", "desc": "시야와 이동이 안정적입니다.", "weight": 16,
        "life_reward": 1.08, "life_fail": 0.00, "rare_bonus": 0.01, "combat": 1.04, "slot_luck": 1.00,
    },
    {
        "id": "tailwind", "emoji": "🍃", "name": "생존 순풍", "desc": "먼지가 가라앉고 이동 경로가 선명해집니다.", "weight": 10,
        "life_reward": 1.12, "life_fail": 0.00, "rare_bonus": 0.018, "combat": 1.06, "slot_luck": 1.00,
    },
    {
        "id": "fog", "emoji": "🌫️", "name": "독성 안개", "desc": "시야가 좁아지고 채집 사고 위험이 증가합니다.", "weight": 12,
        "life_reward": 0.95, "life_fail": 0.10, "rare_bonus": 0.00, "combat": 0.92, "slot_luck": 1.00,
    },
    {
        "id": "rain", "emoji": "🌧️", "name": "산성 폭우", "desc": "야외 활동이 어려워지지만 희귀 잔해가 드러납니다.", "weight": 10,
        "life_reward": 0.90, "life_fail": 0.14, "rare_bonus": 0.035, "combat": 0.90, "slot_luck": 1.00,
    },
    {
        "id": "cold", "emoji": "❄️", "name": "극저온 한파", "desc": "스태미나 소모와 전투 부담이 커집니다.", "weight": 8,
        "life_reward": 0.88, "life_fail": 0.08, "rare_bonus": 0.02, "combat": 0.88, "slot_luck": 1.00,
    },
    {
        "id": "storm", "emoji": "⚡", "name": "방사능 폭풍", "desc": "전자 장비와 생체 신호가 불안정해집니다.", "weight": 7,
        "life_reward": 1.12, "life_fail": 0.18, "rare_bonus": 0.05, "combat": 0.86, "slot_luck": 1.02,
    },
    {
        "id": "blood_moon", "emoji": "🌑", "name": "블러드 문", "desc": "적이 강해지고 카지노의 희귀 결과가 아주 조금 상승합니다.", "weight": 5,
        "life_reward": 1.02, "life_fail": 0.06, "rare_bonus": 0.025, "combat": 0.94, "slot_luck": 1.12,
    },
    {
        "id": "dust", "emoji": "🌪️", "name": "철분 모래폭풍", "desc": "금속성 모래가 장비를 마모시키지만 광물 잔해가 쌓입니다.", "weight": 8,
        "life_reward": 1.06, "life_fail": 0.12, "rare_bonus": 0.025, "combat": 0.90, "slot_luck": 1.00,
    },
    {
        "id": "ash", "emoji": "🌋", "name": "화산재 낙진", "desc": "검은 재가 하늘을 덮습니다. 호흡과 시야가 불안정합니다.", "weight": 6,
        "life_reward": 0.94, "life_fail": 0.11, "rare_bonus": 0.04, "combat": 0.89, "slot_luck": 1.00,
    },
    {
        "id": "spore_bloom", "emoji": "🍄", "name": "포자 개화", "desc": "변이 식생이 폭발적으로 번져 생체 재료가 풍부해집니다.", "weight": 6,
        "life_reward": 1.15, "life_fail": 0.16, "rare_bonus": 0.06, "combat": 0.87, "slot_luck": 1.00,
    },
    {
        "id": "static", "emoji": "📡", "name": "전자기 교란", "desc": "무전과 센서가 흔들리며 기계 잔해가 활성화됩니다.", "weight": 7,
        "life_reward": 1.03, "life_fail": 0.08, "rare_bonus": 0.03, "combat": 0.91, "slot_luck": 1.01,
    },
    {
        "id": "eclipse", "emoji": "🌘", "name": "검은 일식", "desc": "빛이 사라지고 미확인 신호와 희귀 현상이 늘어납니다.", "weight": 5,
        "life_reward": 1.05, "life_fail": 0.09, "rare_bonus": 0.045, "combat": 0.93, "slot_luck": 1.07,
    },
)

RESOURCE_BASE_PRICES = {"나무": 520, "광석": 840, "고철": 680}
RESOURCE_CHIP_PRICES = {"나무": 140, "광석": 220, "고철": 180}
DIFFICULTY_MULT = {"약함": 0.65, "보통": 1.00, "강함": 1.45, "지옥": 2.15}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _weighted_weather(rng: random.Random, previous_id: Optional[str] = None) -> Dict[str, Any]:
    rows = [row for row in WEATHER_TABLE if row["id"] != previous_id] or list(WEATHER_TABLE)
    total = sum(float(row.get("weight", 1.0)) for row in rows)
    point = rng.random() * total
    acc = 0.0
    for row in rows:
        acc += float(row.get("weight", 1.0))
        if point <= acc:
            return dict(row)
    return dict(rows[-1])


def _daily_weather_schedule(guild_id: int | str | None, day_key: str) -> list[Dict[str, Any]]:
    digest = hashlib.sha256(f"abaddon-weather-v637:{guild_id or 0}:{day_key}".encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:16], "big"))
    remaining = 24
    start_hour = 0
    previous_id: Optional[str] = None
    schedule: list[Dict[str, Any]] = []
    index = 0
    while remaining > 0:
        valid = [hours for hours in WEATHER_INTERVAL_HOURS if hours <= remaining and (remaining - hours == 0 or remaining - hours >= 2)]
        duration = rng.choice(valid)
        weather = _weighted_weather(rng, previous_id)
        schedule.append({"index": index, "start_hour": start_hour, "end_hour": start_hour + duration, "duration": duration, "weather": weather})
        previous_id = str(weather["id"])
        start_hour += duration
        remaining -= duration
        index += 1
    return schedule


def get_weather_state(guild_id: int | str | None, now: Optional[datetime] = None) -> Dict[str, Any]:
    now_utc = now or _utc_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_kst = now_utc.astimezone(KST)
    day_key = now_kst.strftime("%Y-%m-%d")
    schedule = _daily_weather_schedule(guild_id, day_key)
    current_hour = now_kst.hour + now_kst.minute / 60 + now_kst.second / 3600
    segment = next((row for row in schedule if row["start_hour"] <= current_hour < row["end_hour"]), schedule[-1])
    state = dict(segment["weather"])
    start_at_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=int(segment["start_hour"]))
    next_at_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=int(segment["end_hour"]))
    start_at = start_at_kst.astimezone(timezone.utc)
    next_at = next_at_kst.astimezone(timezone.utc)
    state["remaining"] = max(0, int((next_at - now_utc).total_seconds()))
    state["period"] = f"{day_key}:{segment['index']}"
    state["duration_hours"] = int(segment["duration"])
    state["starts_at"] = start_at.isoformat()
    state["next_at"] = next_at.isoformat()
    state["schedule_count"] = len(schedule)
    return state

def weather_life_modifiers(guild_id: int | str | None) -> Tuple[float, float, float, Dict[str, Any]]:
    state = get_weather_state(guild_id)
    return float(state["life_reward"]), float(state["life_fail"]), float(state["rare_bonus"]), state


def weather_combat_multiplier(guild_id: int | str | None) -> Tuple[float, Dict[str, Any]]:
    state = get_weather_state(guild_id)
    return float(state["combat"]), state


def weather_slot_weights(guild_id: int | str | None, symbols, weights):
    state = get_weather_state(guild_id)
    if state["id"] not in {"blood_moon", "eclipse"}:
        return list(weights), state
    boosted = []
    for symbol, weight in zip(symbols, weights):
        if symbol in {"7️⃣", "💠"}:
            boosted.append(float(weight) * float(state["slot_luck"]))
        elif symbol == "💀":
            boosted.append(float(weight) * 1.05)
        else:
            boosted.append(float(weight))
    return boosted, state


def pet_casino_adjustment(user: Dict[str, Any], game: str, delta: int) -> Tuple[int, str]:
    pet = str(user.get("pet") or "")
    if not pet or delta == 0:
        return 0, ""

    win_bonus = {
        "루나냥": 0.04, "유니콘": 0.05, "네온문": 0.05,
        "메카로보": 0.03, "미니드론": 0.03,
    }
    game_bonus = {
        "파이어몽": {"블랙잭", "하이로우"},
        "썬더드래곤": {"블랙잭", "다이스"},
        "다크프": {"슬롯머신", "바카라"},
    }
    loss_guard = {"스노우씨": 0.025, "아바돈": 0.02, "군견제로": 0.02, "미니골렘": 0.02}

    if delta > 0:
        rate = win_bonus.get(pet, 0.0)
        if pet in game_bonus and game in game_bonus[pet]:
            rate = max(rate, 0.035)
        bonus = max(0, int(delta * rate))
        if bonus:
            return bonus, f"\n🐾 **{pet} 동행 보너스**: 승리 칩 +{bonus:,}"
    else:
        rate = loss_guard.get(pet, 0.0)
        refund = max(0, int(abs(delta) * rate))
        if refund:
            return refund, f"\n🐾 **{pet} 보호 효과**: 손실 칩 {refund:,} 환급"
    return 0, ""


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def _resource_market(world_data: Dict[str, Any], guild_id: int | str) -> Dict[str, Any]:
    markets = world_data.setdefault("resource_markets", {})
    key = str(guild_id)
    market = markets.setdefault(key, {"pressure": {name: 0 for name in RESOURCE_BASE_PRICES}, "tick": 0})
    tick = int(_utc_now().timestamp() // 900)
    old_tick = int(market.get("tick", 0))
    if tick != old_tick:
        elapsed = min(96, max(1, tick - old_tick)) if old_tick else 1
        for name in RESOURCE_BASE_PRICES:
            pressure = float(market.setdefault("pressure", {}).get(name, 0.0))
            pressure *= 0.88 ** elapsed
            seed = hashlib.sha256(f"resource:{key}:{name}:{tick}".encode()).digest()
            drift = ((int.from_bytes(seed[:2], "big") / 65535.0) - 0.5) * 0.08
            market["pressure"][name] = max(-0.55, min(1.25, pressure + drift))
        market["tick"] = tick
    return market


def _resource_price(world_data: Dict[str, Any], guild_id: int | str, resource: str) -> int:
    market = _resource_market(world_data, guild_id)
    pressure = float(market["pressure"].get(resource, 0.0))
    return max(50, int(RESOURCE_BASE_PRICES[resource] * (1.0 + pressure)))


def _adjust_pressure(world_data: Dict[str, Any], guild_id: int | str, resource: str, quantity: int, direction: int) -> None:
    market = _resource_market(world_data, guild_id)
    current = float(market["pressure"].get(resource, 0.0))
    change = min(0.22, max(0.004, quantity / 6000.0)) * direction
    market["pressure"][resource] = max(-0.55, min(1.25, current + change))


def _flatten_items(item_db: Dict[str, Any], allowed_tiers=("전설", "신화", "유일")):
    pool = []
    for tier in allowed_tiers:
        for name, info in item_db.get(tier, {}).items():
            pool.append((tier, name, info))
    return pool


def register_v636_world_combat(
    bot: commands.Bot,
    get_user,
    check_registered,
    save_data,
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    calculate_user_power,
    get_max_hp,
    add_title,
    add_season_points,
    item_db: Dict[str, Any],
    apply_base_reaction_visual,
) -> None:
    async def send_defense_embed(ctx, embed):
        file = apply_base_reaction_visual(embed, "defense_upgrade")
        if file:
            await ctx.send(embed=embed, file=file)
        else:
            await ctx.send(embed=embed)

    @bot.command(name="날씨")
    async def weather_command(ctx: commands.Context):
        state = get_weather_state(ctx.guild.id if ctx.guild else 0)
        embed = discord.Embed(
            title=f"{state['emoji']} 현재 종말 날씨 · {state['name']}",
            description=state["desc"],
            color=0x52677A if state["id"] != "blood_moon" else 0x7A1735,
        )
        embed.add_field(name="생활 획득량", value=f"**×{state['life_reward']:.2f}**", inline=True)
        embed.add_field(name="생활 실패율", value=f"**+{state['life_fail'] * 100:.0f}%p**", inline=True)
        embed.add_field(name="전투 효율", value=f"**×{state['combat']:.2f}**", inline=True)
        embed.add_field(name="이번 지속 시간", value=f"**{state['duration_hours']}시간**", inline=True)
        embed.add_field(name="다음 변동", value=f"**{_format_duration(state['remaining'])} 후**", inline=True)
        embed.add_field(name="환경 종류", value=f"**총 {len(WEATHER_TABLE)}종**", inline=True)
        embed.set_footer(text="서버별 2~5시간 랜덤 주기 · 게임 내 환경이며 실제 지역 기상 정보가 아닙니다.")
        await ctx.send(embed=embed)

    @bot.command(name="자원시장")
    async def resource_market(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        lines = []
        market = _resource_market(world_data, guild_id)
        for name in RESOURCE_BASE_PRICES:
            price = _resource_price(world_data, guild_id, name)
            pressure = float(market["pressure"].get(name, 0.0))
            marker = "📈" if pressure > 0.08 else ("📉" if pressure < -0.08 else "➖")
            lines.append(f"{marker} **{name}** · 구매 {price:,} / 판매 {int(price * 0.72):,} 식량 · 칩 {RESOURCE_CHIP_PRICES[name]:,}")
        embed = discord.Embed(
            title="📊 기지 자원 변동 시장",
            description="\n".join(lines),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="식량 거래", value="`!자원구매 나무 10` · `!자원판매 광석 5`", inline=False)
        embed.add_field(name="카지노 칩 교환", value="`!기지칩교환 고철 10` · 상위 기지일수록 대량 자원이 필요합니다.", inline=False)
        embed.set_footer(text="코인/증서 암시장과 분리된 기지 건축 자원 전용 시장")
        await ctx.send(embed=embed)

    @bot.command(name="자원구매")
    async def resource_buy(ctx: commands.Context, 자원: str, 수량: int):
        if not await check_registered(ctx):
            return
        if 자원 not in RESOURCE_BASE_PRICES or 수량 <= 0 or 수량 > 1000:
            await ctx.send("⚠️ 사용법: `!자원구매 나무/광석/고철 수량` · 1~1,000")
            return
        user = get_user(ctx.author.id)
        guild_id = ctx.guild.id if ctx.guild else 0
        price = _resource_price(world_data, guild_id, 자원)
        fortune = active_fortune_modifiers(user)
        total = max(1, int(price * 수량 * float(fortune.get("market", 1.0))))
        if int(user.get("balance", 0)) < total:
            await ctx.send(f"⚠️ 식량이 부족합니다. 필요 **{total:,}** · 보유 **{int(user.get('balance', 0)):,}**")
            return
        user["balance"] -= total
        user.setdefault("resources", {})[자원] = int(user.setdefault("resources", {}).get(자원, 0)) + 수량
        _adjust_pressure(world_data, guild_id, 자원, 수량, +1)
        save_data()
        await ctx.send(f"✅ **{자원} {수량:,}개** 구매 · 식량 **-{total:,}**")

    @bot.command(name="자원판매")
    async def resource_sell(ctx: commands.Context, 자원: str, 수량: int):
        if not await check_registered(ctx):
            return
        if 자원 not in RESOURCE_BASE_PRICES or 수량 <= 0 or 수량 > 1000:
            await ctx.send("⚠️ 사용법: `!자원판매 나무/광석/고철 수량` · 1~1,000")
            return
        user = get_user(ctx.author.id)
        owned = int(user.setdefault("resources", {}).get(자원, 0))
        if owned < 수량:
            await ctx.send(f"⚠️ {자원}이 부족합니다. 보유 **{owned:,}개**")
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        unit = int(_resource_price(world_data, guild_id, 자원) * 0.72)
        total = unit * 수량
        user["resources"][자원] -= 수량
        user["balance"] = int(user.get("balance", 0)) + total
        user.setdefault("stats", {})["earned"] = int(user.setdefault("stats", {}).get("earned", 0)) + total
        _adjust_pressure(world_data, guild_id, 자원, 수량, -1)
        save_data()
        await ctx.send(f"✅ **{자원} {수량:,}개** 판매 · 식량 **+{total:,}**")

    @bot.command(name="기지칩교환")
    async def base_chip_exchange(ctx: commands.Context, 자원: str, 수량: int):
        if not await check_registered(ctx):
            return
        if 자원 not in RESOURCE_CHIP_PRICES or 수량 <= 0 or 수량 > 500:
            await ctx.send("⚠️ 사용법: `!기지칩교환 나무/광석/고철 수량` · 1~500")
            return
        from apocalypse_bot.commands.v40_black_casino import casino_chips, add_casino_chips
        user = get_user(ctx.author.id)
        total = RESOURCE_CHIP_PRICES[자원] * 수량
        if casino_chips(user) < total:
            await ctx.send(f"⚠️ 카지노 칩이 부족합니다. 필요 **{total:,}칩** · 보유 **{casino_chips(user):,}칩**")
            return
        add_casino_chips(user, -total)
        user.setdefault("resources", {})[자원] = int(user.setdefault("resources", {}).get(자원, 0)) + 수량
        save_data()
        await ctx.send(f"🏗️ 카지노 칩 **-{total:,}** → **{자원} {수량:,}개** 교환 완료")

    def defense_state(guild_id: int, member_count: int) -> Dict[str, Any]:
        events = world_data.setdefault("base_defense_raids", {})
        key = str(guild_id)
        now = _utc_now()
        iso = now.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        state = events.get(key)
        if not isinstance(state, dict) or state.get("week") != week or state.get("expires_at", "") < now.isoformat():
            max_hp = max(120_000, 80_000 + max(1, member_count) * 6_000)
            state = {
                "week": week, "name": "철벽 파쇄 군체", "hp": max_hp, "max_hp": max_hp,
                "participants": {}, "cleared": False,
                "expires_at": (now + timedelta(days=7)).isoformat(),
            }
            events[key] = state
        return state

    @bot.command(name="기지방어")
    async def base_defense(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        if not ctx.guild:
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return
        state = defense_state(ctx.guild.id, ctx.guild.member_count or 1)
        embed = discord.Embed(
            title=f"🛡️ 대규모 기지 방어 · {state['name']}",
            description="기존 서버 레이드와 달리 **개인 기지 레벨 + 장비 전투력**을 함께 반영하는 주간 협동전입니다.",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="군체 내구도", value=f"**{int(state['hp']):,} / {int(state['max_hp']):,}**", inline=False)
        embed.add_field(name="참가 방법", value="`!기지방어공격` · 개인 기지가 건설되어 있어야 합니다.", inline=False)
        embed.add_field(name="완료 보상", value="요새 인장·식량·시즌 점수, 최고 기여자는 전설~유일 장비 1개", inline=False)
        await send_defense_embed(ctx, embed)

    @bot.command(name="기지방어공격")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def base_defense_attack(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        if not ctx.guild:
            return
        user = get_user(ctx.author.id)
        base = user.get("base", {})
        if not base.get("built"):
            ctx.command.reset_cooldown(ctx)
            await ctx.send("⚠️ `!기지건설` 후 참가할 수 있습니다.")
            return
        state = defense_state(ctx.guild.id, ctx.guild.member_count or 1)
        if state.get("cleared") or int(state.get("hp", 0)) <= 0:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("🏆 이번 주 기지 방어는 이미 완료됐습니다.")
            return
        power = max(1, int(calculate_user_power(user)))
        base_level = max(1, int(base.get("level", 1)))
        damage = int(power * random.uniform(0.75, 1.25) * (1.0 + base_level * 0.16))
        critical = random.random() < min(0.32, 0.08 + base_level * 0.025)
        if critical:
            damage = int(damage * 1.8)
        damage = min(damage, int(state["hp"]))
        state["hp"] = int(state["hp"]) - damage
        weapon_state = consume_weapon_durability(user, 1)
        uid = str(ctx.author.id)
        state.setdefault("participants", {})[uid] = int(state.setdefault("participants", {}).get(uid, 0)) + damage
        message = f"🛡️ {ctx.author.mention} · 기지 Lv.{base_level} 방어포격 **{damage:,}**{' 💥' if critical else ''}\n잔여 내구도 **{state['hp']:,} / {state['max_hp']:,}**"
        if state["hp"] <= 0:
            state["cleared"] = True
            participants = state.get("participants", {})
            top_id = max(participants, key=participants.get) if participants else uid
            for pid, dealt in participants.items():
                pu = get_user(pid)
                if not pu:
                    continue
                reward = 60_000 + int(180_000 * dealt / max(1, state["max_hp"]))
                pu["balance"] = int(pu.get("balance", 0)) + reward
                pu.setdefault("materials", {})["요새 인장"] = int(pu.setdefault("materials", {}).get("요새 인장", 0)) + 1
                pu.setdefault("stats", {})["earned"] = int(pu.setdefault("stats", {}).get("earned", 0)) + reward
            top_user = get_user(top_id)
            limited_text = ""
            pool = _flatten_items(item_db)
            if top_user and pool:
                tier, item_name, info = random.choice(pool)
                if item_name not in top_user.setdefault("inventory", []):
                    top_user["inventory"].append(item_name)
                    top_user.setdefault("enhancements", {})[item_name] = 0
                    limited_text = f"\n🎁 최고 기여자 한정 장비: **[{tier}] {item_name}**"
                else:
                    duplicate = max(50_000, int(info.get("price", 0)) // 4)
                    top_user["balance"] = int(top_user.get("balance", 0)) + duplicate
                    limited_text = f"\n♻️ 최고 기여자 중복 장비 환전: **{duplicate:,} 식량**"
            add_title(user, "요새 수호자")
            add_season_points(user, 80)
            message += "\n\n🏆 **기지 방어 성공!** 참가자 보상이 자동 지급됐습니다." + limited_text
        save_data()
        await ctx.send(message)

    ENEMIES = {
        "약함": ("폐허 배회자", 0.55),
        "보통": ("중무장 약탈자", 0.95),
        "강함": ("변이 집행자", 1.35),
        "지옥": ("심연 군체 사도", 1.95),
    }

    def ensure_battle(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        battle = user.get("tactical_battle")
        return battle if isinstance(battle, dict) and battle.get("active") else None

    def battle_embed(user: Dict[str, Any], battle: Dict[str, Any]) -> discord.Embed:
        hp_max = int(get_max_hp(user))
        enemy_max = int(battle["enemy_max_hp"])
        def bar(now, maximum, width=14):
            filled = max(0, min(width, round(width * now / max(1, maximum))))
            return "█" * filled + "░" * (width - filled)
        embed = discord.Embed(
            title=f"⚔️ 전술 전투 · {battle['enemy']}",
            description=f"모드 **{battle['mode']}** · 난이도 **{battle['difficulty']}** · 턴 **{battle['turn']}**",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="생존자", value=f"❤️ {user['hp']} / {hp_max}\n`{bar(user['hp'], hp_max)}`", inline=True)
        embed.add_field(name="적", value=f"💀 {battle['enemy_hp']} / {enemy_max}\n`{bar(battle['enemy_hp'], enemy_max)}`", inline=True)
        durability = weapon_durability_status(user)
        durability_line = (
            f"{durability['emoji']} {durability['name']} **{durability['current']}/{durability['maximum']}**"
            if durability.get("name") else "➖ 장착 무기 없음"
        )
        embed.add_field(
            name="상태",
            value=(
                f"기술 대기 **{battle.get('skill_cd', 0)}턴**\n"
                f"방어 **{'활성' if battle.get('guard') else '해제'}**\n"
                f"{durability_line}"
            ),
            inline=True,
        )
        logs = battle.get("log", [])[-5:]
        if logs:
            embed.add_field(name="최근 전투 기록", value="\n".join(logs), inline=False)
        embed.set_footer(text="공격 · 기술 · 방어 · 응급 · 도주 버튼으로 진행")
        return embed

    async def finish_victory(user: Dict[str, Any], battle: Dict[str, Any]) -> str:
        diff = battle["difficulty"]
        fortune = active_fortune_modifiers(user)
        reward = int(10_000 * DIFFICULTY_MULT[diff] * random.uniform(0.85, 1.20) * float(fortune.get("reward", 1.0)))
        user["balance"] = int(user.get("balance", 0)) + reward
        user.setdefault("stats", {})["tactical_wins"] = int(user.setdefault("stats", {}).get("tactical_wins", 0)) + 1
        user.setdefault("materials", {})["전술 데이터"] = int(user.setdefault("materials", {}).get("전술 데이터", 0)) + (1 if diff in {"약함", "보통"} else 2)
        if battle.get("mode") == "스토리":
            story = user.setdefault("story", {})
            flags = story.setdefault("flags", [])
            if "tactical_trial_clear" not in flags:
                flags.append("tactical_trial_clear")
        add_season_points(user, {"약함": 4, "보통": 8, "강함": 14, "지옥": 24}[diff])
        user["tactical_battle"] = None
        save_data()
        return f"🏆 전투 승리 · 식량 **+{reward:,}** · 전술 데이터 획득"

    async def resolve_action(user: Dict[str, Any], action: str) -> Tuple[str, bool]:
        battle = ensure_battle(user)
        if not battle:
            return "⚠️ 진행 중인 전술 전투가 없습니다.", True
        power = max(1, int(battle["player_power"]))
        enemy_power = max(1, int(battle["enemy_power"]))
        lines = []
        finished = False
        if action == "공격":
            crit = random.random() < 0.14
            damage = int(power * random.uniform(0.30, 0.48) * (1.65 if crit else 1.0) * weapon_action_multiplier(user, "공격"))
            battle["enemy_hp"] = max(0, int(battle["enemy_hp"]) - damage)
            durability = consume_weapon_durability(user, 1)
            lines.append(f"{'💥' if crit else '⚔️'} 공격 · 적 HP **-{damage}**")
            if durability.get("name"):
                lines.append(f"🔧 {durability['name']} 내구도 **{durability['current']} / {durability['maximum']}**")
        elif action == "기술":
            if int(battle.get("skill_cd", 0)) > 0:
                return f"⏳ 기술 재사용까지 **{battle['skill_cd']}턴** 남았습니다.", False
            damage = int(power * random.uniform(0.65, 0.92) * weapon_action_multiplier(user, "기술"))
            battle["enemy_hp"] = max(0, int(battle["enemy_hp"]) - damage)
            battle["skill_cd"] = 3
            durability = consume_weapon_durability(user, 2)
            lines.append(f"⚡ 전술 기술 · 적 HP **-{damage}**")
            if durability.get("name"):
                lines.append(f"🔧 {durability['name']} 내구도 **{durability['current']} / {durability['maximum']}**")
        elif action == "방어":
            battle["guard"] = True
            lines.append("🛡️ 방어 태세 · 이번 적 피해가 크게 감소합니다.")
        elif action == "응급":
            medical = user.setdefault("medical_items", {})
            if int(medical.get("붕대", 0)) <= 0:
                return "⚠️ 붕대가 없습니다. `!약품구매 붕대 1`로 준비하세요.", False
            medical["붕대"] -= 1
            heal = min(35, int(get_max_hp(user)) - int(user.get("hp", 1)))
            user["hp"] += heal
            lines.append(f"🩹 붕대 사용 · HP **+{heal}**")
        elif action == "도주":
            chance = 0.42 + (0.12 if int(user.get("hp", 1)) < int(get_max_hp(user)) * 0.35 else 0.0)
            if random.random() < chance:
                user["tactical_battle"] = None
                save_data()
                return "🏃 전투에서 이탈했습니다.", True
            lines.append("🚫 도주 실패")
        else:
            return "⚠️ 알 수 없는 행동입니다.", False

        if int(battle["enemy_hp"]) <= 0:
            return await finish_victory(user, battle), True

        guard = bool(battle.pop("guard", False))
        weather_mult = float(battle.get("weather_combat", 1.0))
        incoming = int(enemy_power * random.uniform(0.12, 0.22) / max(0.65, weather_mult))
        if guard:
            incoming = max(1, int(incoming * 0.35))
        user["hp"] = max(0, int(user.get("hp", 1)) - incoming)
        lines.append(f"💢 적 반격 · HP **-{incoming}**")
        if user["hp"] <= 0:
            user["hp"] = max(1, int(get_max_hp(user)) // 5)
            user["tactical_battle"] = None
            user.setdefault("stats", {})["tactical_losses"] = int(user.setdefault("stats", {}).get("tactical_losses", 0)) + 1
            save_data()
            return "\n".join(lines) + f"\n🚑 전투 불능 · 구조 후 HP **{user['hp']}**", True
        if int(battle.get("skill_cd", 0)) > 0 and action != "기술":
            battle["skill_cd"] = max(0, int(battle["skill_cd"]) - 1)
        battle["turn"] = int(battle.get("turn", 1)) + 1
        battle.setdefault("log", []).append(" / ".join(lines))
        battle["log"] = battle["log"][-8:]
        save_data()
        return "\n".join(lines), finished

    class TacticalView(discord.ui.View):
        def __init__(self, owner_id: int):
            super().__init__(timeout=300)
            self.owner_id = owner_id

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("이 전투의 생존자만 조작할 수 있습니다.", ephemeral=True)
                return False
            return True

        async def act(self, interaction: discord.Interaction, action: str):
            user = get_user(interaction.user.id)
            text, finished = await resolve_action(user, action)
            battle = ensure_battle(user)
            if finished or not battle:
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(content=text, embed=None if not battle else battle_embed(user, battle), view=self)
            else:
                await interaction.response.edit_message(content=text, embed=battle_embed(user, battle), view=self)

        @discord.ui.button(label="공격", emoji="⚔️", style=discord.ButtonStyle.danger)
        async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.act(interaction, "공격")

        @discord.ui.button(label="기술", emoji="⚡", style=discord.ButtonStyle.primary)
        async def skill(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.act(interaction, "기술")

        @discord.ui.button(label="방어", emoji="🛡️", style=discord.ButtonStyle.secondary)
        async def guard(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.act(interaction, "방어")

        @discord.ui.button(label="응급", emoji="🩹", style=discord.ButtonStyle.success)
        async def heal(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.act(interaction, "응급")

        @discord.ui.button(label="도주", emoji="🏃", style=discord.ButtonStyle.secondary)
        async def run(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.act(interaction, "도주")

    async def start_combat(ctx: commands.Context, mode: str = "RPG", difficulty: str = "보통"):
        difficulty = {"weak":"약함", "easy":"약함", "normal":"보통", "medium":"보통", "hard":"강함", "hell":"지옥"}.get(str(difficulty or "").lower(), difficulty)
        if not await check_registered(ctx):
            return
        if difficulty not in ENEMIES:
            await ctx.send("⚠️ 난이도: `약함 / 보통 / 강함 / 지옥` · English: `weak / normal / hard / hell`")
            return
        user = get_user(ctx.author.id)
        active = ensure_battle(user)
        if active:
            await ctx.send("⚠️ 이미 진행 중인 전술 전투가 있습니다.", embed=battle_embed(user, active), view=TacticalView(ctx.author.id))
            return
        enemy_name, mult = ENEMIES[difficulty]
        weather_mult, weather = weather_combat_multiplier(ctx.guild.id if ctx.guild else 0)
        fortune = active_fortune_modifiers(user)
        power = max(1, int(calculate_user_power(user) * float(fortune.get("combat", 1.0))))
        enemy_power = max(2, int(power * mult * random.uniform(0.88, 1.12)))
        enemy_hp = max(40, int(enemy_power * 2.4))
        battle = {
            "active": True, "mode": mode, "difficulty": difficulty, "enemy": enemy_name,
            "player_power": power, "enemy_power": enemy_power, "enemy_hp": enemy_hp,
            "enemy_max_hp": enemy_hp, "turn": 1, "skill_cd": 0, "guard": False,
            "weather_combat": weather_mult, "weather": weather["name"], "fortune_combat": float(fortune.get("combat", 1.0)),
            "log": [f"{weather['emoji']} {weather['name']} 속에서 교전 시작"],
        }
        user["tactical_battle"] = battle
        save_data()
        await ctx.send(embed=battle_embed(user, battle), view=TacticalView(ctx.author.id))

    bot.v636_start_combat = start_combat

    @bot.command(name="전투")
    async def combat_command(ctx: commands.Context, 난이도: str = "보통"):
        await start_combat(ctx, "RPG", 난이도)

    @bot.command(name="던전전술")
    async def tactical_dungeon(ctx: commands.Context, 난이도: str = "보통"):
        await start_combat(ctx, "던전 전술", 난이도)

    @bot.command(name="전투상태")
    async def combat_status(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        battle = ensure_battle(user)
        if not battle:
            await ctx.send("진행 중인 전술 전투가 없습니다. `!전투 보통` 또는 `!던전전술 보통`")
            return
        await ctx.send(embed=battle_embed(user, battle), view=TacticalView(ctx.author.id))

    @bot.command(name="전투포기")
    async def combat_abandon(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not ensure_battle(user):
            await ctx.send("진행 중인 전투가 없습니다.")
            return
        user["tactical_battle"] = None
        save_data()
        await ctx.send("🏳️ 전술 전투를 포기했습니다.")

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_notes(ctx: commands.Context):
            embed = discord.Embed(
                title="🌦️⚔️ ABADDON v6.3.7 — 변동 환경·기지방어·전술전투",
                description="중복 시스템을 피하고 기존 기능을 확장하는 방식으로 추가했습니다.",
                color=discord.Color.dark_purple(),
            )
            embed.add_field(name="🌦️ 날씨·재난", value="`!날씨` · 서버별 2~5시간 랜덤 주기·12종 환경 · 생활/던전/희귀 결과에 소폭 반영", inline=False)
            embed.add_field(name="🛡️ 기지 방어 레이드", value="기존 레이드와 분리된 기지 성장 연계 주간 협동전 · `!기지방어`, `!기지방어공격`", inline=False)
            embed.add_field(name="📊 자원 경제", value="기존 코인 암시장과 분리된 나무/광석/고철 변동 시장 · 식량 거래 및 카지노 칩 교환", inline=False)
            embed.add_field(name="🐾 펫 카지노 시너지", value="일부 펫이 승리 보너스 또는 손실 보호를 제공하며 효과는 작게 제한", inline=False)
            embed.add_field(name="⚔️ 전술 전투", value="RPG·스토리·던전에서 함께 쓰는 버튼형 전투 엔진 · 기존 `!던전`은 빠른 자동전투로 유지", inline=False)
            embed.add_field(name="🖼️ 장비 강화·홈페이지", value="무기 종류별 강화 이펙트와 실제 장비 기반 홈페이지 강화/제작 이미지로 교체", inline=False)
            embed.set_footer(text="최신 버전 v6.3.7 · 이후 v6.3.7 통합 패치노트로 대체")
            await ctx.send(embed=embed)
        patch.callback = patch_notes
        patch.help = "ABADDON v6.3.7 환경·기지방어·전술전투 기반 패치 내용을 확인합니다."
        patch.description = patch.help

    bot.v636_version = VERSION
