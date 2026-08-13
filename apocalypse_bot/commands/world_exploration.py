import random
from datetime import datetime, timezone

from discord.ext import commands

from apocalypse_bot.commands.v637_dynamic_events import (
    active_fortune_modifiers, consume_weapon_durability, hazard_for_region,
)

REGIONS = {
    "폐허도심": {"emoji": "🏙️", "level": 1, "stamina": 10, "danger": 1, "desc": "무너진 상가와 골목. 초보 생존자의 첫 탐색지.", "rewards": (250, 650), "materials": ["나무", "고철", "천", "스크랩"]},
    "버려진학교": {"emoji": "🏫", "level": 3, "stamina": 12, "danger": 2, "desc": "교실과 체육관에 감염자가 숨어 있다.", "rewards": (400, 900), "materials": ["천", "가죽", "약초", "볼트"]},
    "시립병원": {"emoji": "🏥", "level": 5, "stamina": 15, "danger": 3, "desc": "의약품이 남아 있지만 변이체 출몰이 잦다.", "rewards": (650, 1300), "materials": ["약초", "천", "전자부품", "스크랩"]},
    "지하철역": {"emoji": "🚇", "level": 8, "stamina": 18, "danger": 4, "desc": "어둡고 좁은 터널. 기습에 매우 취약하다.", "rewards": (900, 1800), "materials": ["철", "고철", "볼트", "화약"]},
    "대형마트": {"emoji": "🛒", "level": 11, "stamina": 20, "danger": 5, "desc": "식량 창고를 차지한 감염자 무리가 배회한다.", "rewards": (1200, 2400), "materials": ["나무", "천", "가죽", "전자부품"]},
    "경찰서": {"emoji": "🚓", "level": 15, "stamina": 23, "danger": 6, "desc": "무기와 방호 장비를 노릴 수 있는 고위험 지역.", "rewards": (1700, 3300), "materials": ["철", "화약", "볼트", "전자부품"]},
    "군부대": {"emoji": "🪖", "level": 20, "stamina": 27, "danger": 7, "desc": "중무장 감염자와 실험체가 점령한 군사 시설.", "rewards": (2500, 4700), "materials": ["철", "화약", "전자부품", "스크랩"]},
    "격리연구소": {"emoji": "☣️", "level": 28, "stamina": 32, "danger": 9, "desc": "사태의 비밀이 묻힌 최상급 위험 지역.", "rewards": (3800, 7000), "materials": ["전자부품", "화약", "약초", "볼트"]},
}

ZOMBIE_ARCHETYPES = [
    ("비틀거리는 감염자", 1, "느리지만 끈질기다"), ("굶주린 감염자", 1, "먹잇감을 보면 돌진한다"),
    ("부패한 주민", 1, "악취를 풍기는 일반 감염자"), ("기어다니는 감염자", 1, "바닥에서 발목을 노린다"),
    ("교복 감염자", 2, "빠른 움직임으로 달려든다"), ("체육부 감염자", 2, "체력이 높고 몸통박치기를 한다"),
    ("경비원 감염자", 2, "두꺼운 제복으로 공격을 버틴다"), ("비명 감염자", 2, "괴성으로 주변 무리를 부른다"),
    ("간호사 감염자", 3, "날카로운 의료 도구를 휘두른다"), ("수술실 감염자", 3, "피 냄새에 민감하다"),
    ("독성 환자", 3, "체액에 독성이 남아 있다"), ("부풀어 오른 감염자", 3, "죽을 때 오염 물질을 터뜨린다"),
    ("터널 잠복자", 4, "어둠 속에서 기습한다"), ("선로 질주자", 4, "직선 돌진 속도가 매우 빠르다"),
    ("전기기사 감염자", 4, "합선 장비를 끌고 다닌다"), ("메아리 사냥꾼", 4, "소리를 따라 정확히 접근한다"),
    ("창고 포식자", 5, "거대한 몸으로 통로를 막는다"), ("카트 돌격자", 5, "쇼핑카트를 밀며 돌진한다"),
    ("냉동실 감염자", 5, "굳은 피부로 방어력이 높다"), ("무리의 어미", 5, "주변 감염자를 강화한다"),
    ("진압대 감염자", 6, "방패를 들고 접근한다"), ("저격수 감염자", 6, "멀리서 위협적인 투사체를 던진다"),
    ("구치소 광인", 6, "고통을 무시하고 공격한다"), ("무전병 감염자", 6, "소음으로 지원 무리를 부른다"),
    ("군용 방탄 감염자", 7, "방탄 장구를 착용했다"), ("폭발물 운반체", 7, "접근하면 폭발 위험이 있다"),
    ("특전 감염자", 7, "빠르고 전투 본능이 남아 있다"), ("중화기 감염자", 7, "거대한 체구와 장비로 압박한다"),
    ("실험체 A-01", 8, "재생 능력을 보이는 초기 실험체"), ("실험체 B-07", 8, "팔이 비정상적으로 길게 변이했다"),
    ("포자 살포자", 8, "감염성 포자를 뿌린다"), ("산성 분출자", 8, "부식성 체액을 발사한다"),
    ("벽타기 변이체", 8, "벽과 천장을 타고 이동한다"), ("맹목의 추적자", 8, "시력 대신 청각이 극도로 발달했다"),
    ("골격 파괴자", 9, "뼈가 갑옷처럼 돌출됐다"), ("혈액 포식자", 9, "부상자를 우선 공격한다"),
    ("전염성 숙주", 9, "감염 확률이 매우 높다"), ("분열 감염체", 9, "쓰러지면 작은 개체로 갈라진다"),
    ("검은 포효", 9, "포효로 생존자를 기절시킨다"), ("붉은 사냥개", 9, "네 발로 질주하는 고속 변이체"),
    ("교수형 거인", 10, "거대한 팔로 주변을 쓸어버린다"), ("철갑 파괴자", 10, "총탄도 버티는 경화 피부를 가졌다"),
    ("역병 의사", 10, "독과 감염을 동시에 퍼뜨린다"), ("심연의 잠복자", 10, "완전히 모습을 감췄다가 습격한다"),
    ("군체 지휘체", 10, "감염자 무리를 조직적으로 움직인다"), ("불완전한 타이탄", 10, "연구소에서 탈출한 거대 실험체"),
    ("제로 환자 잔재", 11, "최초 감염원과 유사한 조직체"), ("종말의 집행자", 11, "중무장 생존자 부대를 전멸시킨 개체"),
    ("검은 태아", 11, "정체불명의 고위험 생체 덩어리"), ("프로토콜 오메가", 12, "연구소 최종 봉쇄 대상"),
]

REGION_ZOMBIES = {}
for index, zombie in enumerate(ZOMBIE_ARCHETYPES):
    region_name = list(REGIONS.keys())[min(len(REGIONS) - 1, index // 7)]
    REGION_ZOMBIES.setdefault(region_name, []).append(zombie)

EVENTS = [
    ("보급 상자", "📦 잠긴 보급 상자를 발견했다.", "reward"),
    ("생존자 구조", "🧍 무너진 건물에서 생존자를 구조했다.", "reward"),
    ("감염자 매복", "🧟 잔해 뒤에서 감염자 무리가 튀어나왔다.", "damage"),
    ("오염 구역", "☣️ 공기 중에 정체불명의 포자가 떠다닌다.", "infection"),
    ("버려진 작업대", "🔧 쓸 만한 재료가 남은 작업대를 발견했다.", "material"),
    ("안전한 은신처", "🏕️ 잠시 몸을 숨길 안전한 공간을 찾았다.", "heal"),
]


def ensure_world_user(user):
    user.setdefault("region", "폐허도심")
    if user["region"] not in REGIONS:
        user["region"] = "폐허도심"
    user.setdefault("region_discoveries", ["폐허도심"])
    if not isinstance(user["region_discoveries"], list):
        user["region_discoveries"] = ["폐허도심"]
    user.setdefault("zombie_kills", {})
    if not isinstance(user["zombie_kills"], dict):
        user["zombie_kills"] = {}
    user.setdefault("exploration_count", 0)
    return user


def region_power_bonus(user):
    ensure_world_user(user)
    return max(0, REGIONS[user["region"]]["danger"] - 1)


def register_world_commands(bot, get_user, check_registered, save_data, spend_stamina, apply_damage, get_max_hp, get_max_stamina):
    @bot.command(name="지역목록")
    async def region_list(ctx):
        if not await check_registered(ctx):
            return
        user = ensure_world_user(get_user(ctx.author.id))
        lines = ["🗺️ **[탐색 가능 지역]**"]
        for name, info in REGIONS.items():
            lock = "✅" if user.get("level", 1) >= info["level"] else f"🔒 Lv.{info['level']}"
            current = " ← 현재 위치" if user["region"] == name else ""
            lines.append(f"{info['emoji']} **{name}** | 위험도 {info['danger']} | {lock}{current}")
        lines.append("\n이동: `!지역이동 지역명` / 탐색: `!지역탐색`")
        await ctx.send("\n".join(lines))

    @bot.command(name="지역정보")
    async def region_info(ctx, *, 지역명: str = ""):
        if not await check_registered(ctx):
            return
        user = ensure_world_user(get_user(ctx.author.id))
        name = 지역명.strip() or user["region"]
        if name not in REGIONS:
            await ctx.send("⚠️ 존재하지 않는 지역입니다. `!지역목록`을 확인하세요.")
            return
        info = REGIONS[name]
        zombies = REGION_ZOMBIES.get(name, [])
        preview = ", ".join(z[0] for z in zombies[:5]) or "정보 없음"
        await ctx.send(
            f"{info['emoji']} **[{name}]**\n"
            f"권장 레벨: **Lv.{info['level']}** | 위험도: **{info['danger']}**\n"
            f"탐색 스태미나: **{info['stamina']}**\n"
            f"설명: {info['desc']}\n"
            f"주요 감염자: {preview}"
        )

    @bot.command(name="지역이동")
    async def move_region(ctx, *, 지역명: str = ""):
        if not await check_registered(ctx):
            return
        user = ensure_world_user(get_user(ctx.author.id))
        name = 지역명.strip()
        if name not in REGIONS:
            await ctx.send("⚠️ 사용법: `!지역이동 폐허도심` / `!지역목록` 확인")
            return
        required = REGIONS[name]["level"]
        if user.get("level", 1) < required:
            await ctx.send(f"🔒 **{name}**은 Lv.{required}부터 이동할 수 있습니다.")
            return
        user["region"] = name
        if name not in user["region_discoveries"]:
            user["region_discoveries"].append(name)
        save_data()
        await ctx.send(f"🚶 {REGIONS[name]['emoji']} **{name}**으로 이동했습니다. `!지역탐색`으로 주변을 조사하세요.")

    @bot.command(name="좀비도감")
    async def zombie_book(ctx, *, 지역명: str = ""):
        if not await check_registered(ctx):
            return
        user = ensure_world_user(get_user(ctx.author.id))
        name = 지역명.strip() or user["region"]
        if name not in REGIONS:
            await ctx.send("⚠️ 사용법: `!좀비도감 지역명`")
            return
        lines = [f"🧟 **[{name} 감염자 도감]**"]
        for zombie_name, danger, desc in REGION_ZOMBIES.get(name, []):
            kills = user["zombie_kills"].get(zombie_name, 0)
            lines.append(f"• **{zombie_name}** ★{danger} — {desc} | 처치 {kills}회")
        await ctx.send("\n".join(lines))

    @bot.command(name="지역탐색")
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def explore_region(ctx):
        if not await check_registered(ctx):
            return
        user = ensure_world_user(get_user(ctx.author.id))
        info = REGIONS[user["region"]]
        guild_id = ctx.guild.id if ctx.guild else 0
        hazard = hazard_for_region(guild_id, user["region"])
        fortune = active_fortune_modifiers(user)
        if not spend_stamina(user, info["stamina"]):
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚡ 스태미나가 부족합니다. 필요 **{info['stamina']}** / 현재 **{user['stamina']}**")
            return

        zombie = random.choice(REGION_ZOMBIES.get(user["region"], ZOMBIE_ARCHETYPES[:5]))
        zname, zdanger, zdesc = zombie
        level = user.get("level", 1)
        success_rate = max(0.25, min(0.92, 0.72 + (level - info["level"]) * 0.025 - info["danger"] * 0.025))
        if hazard:
            success_rate = max(0.10, success_rate - float(hazard.get("success_penalty", 0.0)))
        success = random.random() < success_rate
        user["exploration_count"] += 1

        if success:
            reward_mult = float(fortune.get("life", 1.0)) * (float(hazard.get("reward_mult", 1.0)) if hazard else 1.0)
            reward = int(random.randint(*info["rewards"]) * reward_mult)
            user["balance"] += reward
            user.setdefault("stats", {}).setdefault("earned", 0)
            user["stats"]["earned"] += reward
            user["zombie_kills"][zname] = user["zombie_kills"].get(zname, 0) + 1
            material = random.choice(info["materials"])
            amount = max(1, int(random.randint(1, max(2, info["danger"] // 2 + 1)) * (float(hazard.get("reward_mult", 1.0)) if hazard else 1.0)))
            user.setdefault("materials", {})
            user["materials"][material] = user["materials"].get(material, 0) + amount
            text = (
                f"🔎 **[{user['region']} 탐색 성공]**\n"
                f"🧟 {zname} 처치 — {zdesc}\n"
                f"🥫 식량 +**{reward:,}개**\n🧰 {material} +**{amount}개**"
            )
        else:
            damage = random.randint(5 + info["danger"] * 2, 12 + info["danger"] * 4)
            if hazard:
                damage = int(damage * float(hazard.get("damage_mult", 1.0)))
            actual, knocked = apply_damage(user, damage)
            infection_gain = random.randint(0, max(1, info["danger"] // 2)) + (int(hazard.get("infection_bonus", 0)) if hazard else 0)
            user["infection"] = min(100, user.get("infection", 0) + infection_gain)
            text = (
                f"💥 **[{user['region']} 탐색 실패]**\n"
                f"🧟 {zname}의 기습을 받았습니다.\n"
                f"❤️ 피해 -**{actual}** | HP **{user['hp']} / {get_max_hp(user)}**\n"
                f"🦠 감염도 +**{infection_gain}%** → {user['infection']}%"
            )
            if knocked:
                text += "\n🚑 쓰러진 뒤 구조되어 간신히 살아남았습니다."

        if hazard:
            text += (
                f"\n\n{hazard['emoji']} **돌연변이 구역 활성: {hazard['name']}**"
                f"\n성공률 **-{float(hazard['success_penalty']) * 100:.0f}%p** · 성공 보상 **×{float(hazard['reward_mult']):.2f}**"
            )

        if random.random() < 0.32:
            ename, edesc, etype = random.choice(EVENTS)
            text += f"\n\n🎲 **랜덤 이벤트: {ename}**\n{edesc}"
            if etype == "reward":
                bonus = random.randint(150, 600) * max(1, info["danger"])
                user["balance"] += bonus
                text += f"\n🥫 추가 식량 +**{bonus:,}개**"
            elif etype == "damage":
                actual, _ = apply_damage(user, random.randint(4, 8 + info["danger"] * 2))
                text += f"\n❤️ 추가 피해 -**{actual}**"
            elif etype == "infection":
                gain = random.randint(2, 4 + info["danger"])
                user["infection"] = min(100, user.get("infection", 0) + gain)
                text += f"\n🦠 감염도 +**{gain}%**"
            elif etype == "material":
                material = random.choice(info["materials"])
                amount = random.randint(2, 5)
                user["materials"][material] = user["materials"].get(material, 0) + amount
                text += f"\n🧰 {material} +**{amount}개**"
            elif etype == "heal":
                before = user["hp"]
                user["hp"] = min(get_max_hp(user), user["hp"] + random.randint(8, 18))
                text += f"\n❤️ HP +**{user['hp'] - before}**"

        weapon_state = consume_weapon_durability(user, 1 if success else 2)
        text += f"\n⚡ 스태미나 -**{info['stamina']}** | 현재 **{user['stamina']} / {get_max_stamina(user)}**"
        if weapon_state.get("name"):
            text += f"\n🔧 {weapon_state['name']} 내구도 **{weapon_state['current']} / {weapon_state['maximum']} · {weapon_state['label']}**"
        save_data()
        await ctx.send(text)
