import random
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks


INVASION_TYPES = [
    {
        "name": "붉은 군단의 도심 침공",
        "boss": "군체 지휘관 카르나",
        "emoji": "🩸",
        "base_hp": 18000,
        "duration": 30,
        "desc": "붉은 포자에 잠식된 감염 군단이 생존 구역으로 진격합니다.",
    },
    {
        "name": "실험체 ZERO 탈주",
        "boss": "실험체 ZERO",
        "emoji": "🧬",
        "base_hp": 23000,
        "duration": 35,
        "desc": "지하 연구소의 봉인이 무너졌습니다. 초고속 재생 개체를 저지하세요.",
    },
    {
        "name": "타이탄 무리의 대이동",
        "boss": "강철 타이탄",
        "emoji": "☢️",
        "base_hp": 30000,
        "duration": 40,
        "desc": "중장갑 변이체 무리가 기지를 향해 이동 중입니다.",
    },
    {
        "name": "아바돈의 악몽",
        "boss": "심연의 포식자",
        "emoji": "😈",
        "base_hp": 38000,
        "duration": 45,
        "desc": "현실을 찢고 나온 심연 개체가 서버 전체를 사냥하기 시작했습니다.",
    },
]


def _now():
    return datetime.now()


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _ensure_world(world_data):
    world_data.setdefault("invasions", {})
    world_data.setdefault("invasion_history", [])
    world_data.setdefault("invasion_settings", {"auto_enabled": True, "last_auto_check": ""})
    return world_data


def _ensure_user(u):
    u.setdefault("invasion", {})
    defaults = {
        "damage": 0,
        "wins": 0,
        "participations": 0,
        "mvp": 0,
        "tokens": 0,
        "last_attack": "",
    }
    for key, value in defaults.items():
        u["invasion"].setdefault(key, value)
    return u


def _active(invasion):
    if not invasion or invasion.get("status") != "active":
        return False
    end_at = _parse_time(invasion.get("end_at"))
    return bool(end_at and end_at > _now() and invasion.get("hp", 0) > 0)


def _remaining_text(invasion):
    end_at = _parse_time(invasion.get("end_at"))
    if not end_at:
        return "알 수 없음"
    seconds = max(0, int((end_at - _now()).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}분 {seconds}초"


def _guild_key(ctx):
    return str(ctx.guild.id) if ctx.guild else "dm"


def _new_invasion(guild_id, member_count=1, forced_type=None):
    template = forced_type or random.choice(INVASION_TYPES)
    scale = max(1.0, min(4.0, 1.0 + max(0, member_count - 10) / 40))
    max_hp = int(template["base_hp"] * scale)
    start_at = _now()
    return {
        "guild_id": str(guild_id),
        "name": template["name"],
        "boss": template["boss"],
        "emoji": template["emoji"],
        "desc": template["desc"],
        "status": "active",
        "phase": 1,
        "max_hp": max_hp,
        "hp": max_hp,
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(minutes=template["duration"])).isoformat(),
        "participants": {},
        "total_attacks": 0,
        "reward_claimed": False,
        "result_announced": False,
    }


def register_v30_commands(
    bot,
    get_user,
    check_registered,
    save_data,
    send_pages,
    world_data,
    calculate_user_power,
    add_season_points,
):
    _ensure_world(world_data)

    async def finish_invasion(channel, guild_id, invasion, success):
        if invasion.get("status") != "active":
            return

        invasion["status"] = "victory" if success else "failed"
        invasion["finished_at"] = _now().isoformat()
        participants = invasion.get("participants", {})
        ranking = sorted(participants.items(), key=lambda x: x[1].get("damage", 0), reverse=True)

        if success and ranking:
            total_damage = max(1, sum(v.get("damage", 0) for _, v in ranking))
            for rank, (uid, record) in enumerate(ranking, start=1):
                u = get_user(uid)
                if not u:
                    continue
                _ensure_user(u)
                share = record.get("damage", 0) / total_damage
                food = max(500, int(2500 + share * 15000))
                tokens = max(1, 6 - min(rank, 5))
                if rank == 1:
                    food += 5000
                    tokens += 5
                    u["invasion"]["mvp"] += 1
                u["balance"] += food
                u["invasion"]["tokens"] += tokens
                u["invasion"]["wins"] += 1
                u.setdefault("stats", {}).setdefault("earned", 0)
                u["stats"]["earned"] += food
                add_season_points(u, 20 if rank == 1 else 10)
                record["reward"] = {"food": food, "tokens": tokens}

        history = world_data.setdefault("invasion_history", [])
        history.append({
            "guild_id": str(guild_id),
            "name": invasion.get("name"),
            "boss": invasion.get("boss"),
            "result": invasion["status"],
            "finished_at": invasion.get("finished_at"),
            "participants": len(participants),
            "total_attacks": invasion.get("total_attacks", 0),
        })
        del history[:-30]
        save_data()

        if not channel:
            return

        if success:
            top = ranking[:5]
            lines = [
                f"{invasion.get('emoji', '🚨')} **서버 침공 저지 성공!**",
                f"**{invasion['boss']}**이(가) 쓰러졌습니다.",
                f"참여 생존자: **{len(ranking)}명** · 총 공격: **{invasion.get('total_attacks', 0)}회**",
                "",
                "🏆 **기여도 순위**",
            ]
            for rank, (uid, record) in enumerate(top, start=1):
                reward = record.get("reward", {})
                lines.append(
                    f"`{rank}위` <@{uid}> — {record.get('damage', 0):,} 피해 "
                    f"/ 식량 {reward.get('food', 0):,} · 침공토큰 {reward.get('tokens', 0)}"
                )
            await channel.send("\n".join(lines))
        else:
            await channel.send(
                f"☠️ **서버 침공 방어 실패**\n"
                f"**{invasion['boss']}**을(를) 막지 못했습니다.\n"
                f"남은 체력: **{max(0, invasion.get('hp', 0)):,}/{invasion.get('max_hp', 1):,}**\n"
                "다음 침공에서는 더 많은 생존자가 필요합니다."
            )

    async def resolve_if_expired(ctx, invasion):
        if invasion and invasion.get("status") == "active":
            end_at = _parse_time(invasion.get("end_at"))
            if end_at and end_at <= _now():
                await finish_invasion(ctx.channel, _guild_key(ctx), invasion, False)
                return True
        return False

    @bot.hybrid_command(name="도움말", aliases=["help"], description="초보 가이드와 카테고리별 명령어 브라우저를 엽니다.")
    async def help_command(ctx, *, category: str = ""):
        # V7.0.1부터 도움말과 명령어 브라우저를 하나로 통합합니다.
        # 기존 !도움말 분류 사용자는 검색어로 그대로 연결되며, !도움말만 입력하면 초보 버튼이 있는 통합 화면이 열립니다.
        browser = bot.get_command("명령어")
        if browser is not None:
            try:
                if browser.cog is not None:
                    await browser.callback(browser.cog, ctx, 검색어=category.strip() or None)
                else:
                    await browser.callback(ctx, 검색어=category.strip() or None)
                return
            except TypeError:
                pass
        await ctx.send(
            "📚 명령어 브라우저를 열지 못했습니다. `!명령어` 또는 `!게임`을 사용해주세요.\n"
            "처음이라면 `!처음`을 입력하세요."
        )

    @bot.command(name="침공", aliases=["서버침공", "침공현황"])
    async def invasion_status(ctx):
        if not ctx.guild:
            await ctx.send("⚠️ 서버 침공은 서버 채널에서만 진행할 수 있습니다.")
            return
        invasions = _ensure_world(world_data)["invasions"]
        invasion = invasions.get(_guild_key(ctx))
        await resolve_if_expired(ctx, invasion)
        invasion = invasions.get(_guild_key(ctx))
        if not _active(invasion):
            await ctx.send(
                "🛰️ 현재 진행 중인 서버 침공이 없습니다.\n"
                "관리자는 `!침공시작`으로 침공을 시작할 수 있습니다."
            )
            return
        hp_pct = invasion["hp"] / max(1, invasion["max_hp"]) * 100
        embed = discord.Embed(
            title=f"{invasion['emoji']} {invasion['name']}",
            description=invasion["desc"],
            color=discord.Color.red(),
        )
        embed.add_field(name="침공 우두머리", value=invasion["boss"], inline=True)
        embed.add_field(name="현재 단계", value=f"{invasion.get('phase', 1)}단계", inline=True)
        embed.add_field(name="남은 시간", value=_remaining_text(invasion), inline=True)
        embed.add_field(name="체력", value=f"{invasion['hp']:,}/{invasion['max_hp']:,} ({hp_pct:.1f}%)", inline=False)
        embed.add_field(name="참여자", value=f"{len(invasion.get('participants', {}))}명", inline=True)
        embed.add_field(name="총 공격", value=f"{invasion.get('total_attacks', 0)}회", inline=True)
        embed.set_footer(text="!참전 → !침공공격 · 공격 쿨타임 45초")
        await ctx.send(embed=embed)

    @bot.command(name="참전", aliases=["침공참가"])
    async def invasion_join(ctx):
        if not await check_registered(ctx):
            return
        invasion = _ensure_world(world_data)["invasions"].get(_guild_key(ctx))
        await resolve_if_expired(ctx, invasion)
        if not _active(invasion):
            await ctx.send("⚠️ 현재 진행 중인 서버 침공이 없습니다.")
            return
        uid = str(ctx.author.id)
        if uid in invasion["participants"]:
            await ctx.send("⚠️ 이미 침공 방어전에 참전 중입니다. `!침공공격`을 사용하세요.")
            return
        u = _ensure_user(get_user(uid))
        invasion["participants"][uid] = {"damage": 0, "attacks": 0, "joined_at": _now().isoformat()}
        u["invasion"]["participations"] += 1
        save_data()
        await ctx.send(f"🛡️ {ctx.author.mention} 생존자가 **{invasion['name']}** 방어전에 참전했습니다!")

    @bot.command(name="침공공격", aliases=["침공전투"])
    @commands.cooldown(1, 45, commands.BucketType.user)
    async def invasion_attack(ctx):
        if not await check_registered(ctx):
            return
        invasion = _ensure_world(world_data)["invasions"].get(_guild_key(ctx))
        await resolve_if_expired(ctx, invasion)
        if not _active(invasion):
            await ctx.send("⚠️ 현재 진행 중인 서버 침공이 없습니다.")
            return
        uid = str(ctx.author.id)
        if uid not in invasion["participants"]:
            await ctx.send("⚠️ 먼저 `!참전`으로 방어전에 참가하세요.")
            return

        u = _ensure_user(get_user(uid))
        power = max(1, int(calculate_user_power(u)))
        phase = invasion.get("phase", 1)
        base_damage = random.randint(max(20, power * 2), max(40, power * 4))
        critical = random.random() < min(0.30, 0.08 + u.get("level", 1) / 500)
        damage = int(base_damage * (1.8 if critical else 1.0))

        event_text = ""
        roll = random.random()
        if roll < 0.08:
            damage = int(damage * 1.6)
            event_text = "\n💥 약점을 정확히 관통했습니다!"
        elif roll < 0.14:
            damage = max(1, int(damage * 0.45))
            event_text = "\n🧱 장갑에 공격이 일부 막혔습니다."
        elif roll > 0.96:
            bonus = random.randint(1, 2)
            u["invasion"]["tokens"] += bonus
            event_text = f"\n📦 전장에서 **침공토큰 {bonus}개**를 회수했습니다."

        invasion["hp"] = max(0, invasion["hp"] - damage)
        invasion["total_attacks"] += 1
        record = invasion["participants"][uid]
        record["damage"] += damage
        record["attacks"] += 1
        u["invasion"]["damage"] += damage
        u["invasion"]["last_attack"] = _now().isoformat()

        hp_ratio = invasion["hp"] / max(1, invasion["max_hp"])
        new_phase = 3 if hp_ratio <= 0.30 else 2 if hp_ratio <= 0.65 else 1
        phase_text = ""
        if new_phase > phase:
            invasion["phase"] = new_phase
            phase_text = f"\n⚠️ **{new_phase}단계 돌입!** 우두머리의 패턴이 더욱 흉포해집니다."

        save_data()
        await ctx.send(
            f"⚔️ {ctx.author.mention}이(가) **{damage:,}** 피해를 입혔습니다"
            f"{' (치명타!)' if critical else ''}.\n"
            f"❤️ 침공 우두머리 HP: **{invasion['hp']:,}/{invasion['max_hp']:,}**"
            f"{event_text}{phase_text}"
        )
        if invasion["hp"] <= 0:
            await finish_invasion(ctx.channel, _guild_key(ctx), invasion, True)

    @bot.command(name="침공랭킹", aliases=["침공기여도"])
    async def invasion_ranking(ctx):
        invasion = _ensure_world(world_data)["invasions"].get(_guild_key(ctx))
        await resolve_if_expired(ctx, invasion)
        if not invasion or not invasion.get("participants"):
            await ctx.send("⚠️ 표시할 침공 기여도 기록이 없습니다.")
            return
        ranking = sorted(invasion["participants"].items(), key=lambda x: x[1].get("damage", 0), reverse=True)
        lines = [f"🏆 **{invasion.get('name', '서버 침공')} 기여도**"]
        for rank, (uid, record) in enumerate(ranking[:20], start=1):
            lines.append(f"`{rank:>2}위` <@{uid}> — **{record.get('damage', 0):,}** 피해 / {record.get('attacks', 0)}회")
        await send_pages(ctx.channel, "\n".join(lines))

    @bot.command(name="침공기록")
    async def invasion_history(ctx):
        records = [x for x in _ensure_world(world_data).get("invasion_history", []) if x.get("guild_id") == _guild_key(ctx)]
        if not records:
            await ctx.send("📭 이 서버에는 아직 완료된 침공 기록이 없습니다.")
            return
        lines = ["📜 **최근 서버 침공 기록**"]
        for item in reversed(records[-10:]):
            result = "✅ 방어 성공" if item.get("result") == "victory" else "❌ 방어 실패"
            date = str(item.get("finished_at", ""))[:16].replace("T", " ")
            lines.append(f"• `{date}` **{item.get('name')}** — {result} / {item.get('participants', 0)}명")
        await ctx.send("\n".join(lines))

    @bot.command(name="침공상점")
    async def invasion_shop(ctx, item: str = ""):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        shop = {
            "강화석": (5, "materials", 3),
            "강화보호권": (18, "materials", 1),
            "옵션재설정권": (14, "materials", 1),
            "식량상자": (10, "balance", 8000),
        }
        if not item:
            lines = [f"🪙 **침공 교환소** · 보유 토큰: **{u['invasion']['tokens']}개**"]
            for name, (cost, _, amount) in shop.items():
                reward = f"{amount:,}개" if name != "식량상자" else f"식량 {amount:,}"
                lines.append(f"• `{name}` — 토큰 {cost}개 / {reward}")
            lines.append("구매: `!침공상점 아이템명`")
            await ctx.send("\n".join(lines))
            return
        if item not in shop:
            await ctx.send("⚠️ 판매하지 않는 물품입니다. `!침공상점`을 확인하세요.")
            return
        cost, target, amount = shop[item]
        if u["invasion"]["tokens"] < cost:
            await ctx.send(f"⚠️ 침공토큰이 부족합니다. 필요: **{cost}개**")
            return
        u["invasion"]["tokens"] -= cost
        if target == "materials":
            u.setdefault("materials", {})
            u["materials"][item] = u["materials"].get(item, 0) + amount
        else:
            u["balance"] += amount
        save_data()
        await ctx.send(f"✅ **{item}** 교환 완료! 남은 침공토큰: **{u['invasion']['tokens']}개**")

    @bot.command(name="침공시작")
    @commands.has_permissions(administrator=True)
    async def invasion_start(ctx):
        if not ctx.guild:
            return
        invasions = _ensure_world(world_data)["invasions"]
        current = invasions.get(_guild_key(ctx))
        await resolve_if_expired(ctx, current)
        if _active(current):
            await ctx.send("⚠️ 이미 진행 중인 서버 침공이 있습니다.")
            return
        invasion = _new_invasion(ctx.guild.id, ctx.guild.member_count or 1)
        invasion["channel_id"] = ctx.channel.id
        invasions[_guild_key(ctx)] = invasion
        save_data()
        await ctx.send(
            f"{invasion['emoji']} **[긴급 경보] {invasion['name']}**\n"
            f"{invasion['desc']}\n\n"
            f"👹 우두머리: **{invasion['boss']}**\n"
            f"❤️ 체력: **{invasion['max_hp']:,}**\n"
            f"⏰ 제한시간: **{_remaining_text(invasion)}**\n\n"
            "`!참전`으로 합류한 뒤 `!침공공격`으로 방어하세요!"
        )

    @bot.command(name="침공종료")
    @commands.has_permissions(administrator=True)
    async def invasion_end(ctx):
        invasion = _ensure_world(world_data)["invasions"].get(_guild_key(ctx))
        if not _active(invasion):
            await ctx.send("⚠️ 진행 중인 침공이 없습니다.")
            return
        await finish_invasion(ctx.channel, _guild_key(ctx), invasion, False)

    @bot.command(name="침공토큰지급")
    @commands.has_permissions(administrator=True)
    async def invasion_token_grant(ctx, member: discord.Member, amount: int):
        if amount <= 0:
            await ctx.send("⚠️ 지급 수량은 1개 이상이어야 합니다.")
            return
        u = get_user(member.id)
        if not u:
            await ctx.send("⚠️ 가입하지 않은 유저입니다.")
            return
        _ensure_user(u)["invasion"]["tokens"] += amount
        save_data()
        await ctx.send(f"✅ {member.mention}에게 침공토큰 **{amount}개**를 지급했습니다.")
