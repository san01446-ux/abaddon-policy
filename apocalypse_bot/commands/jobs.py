import discord
from discord.ext import commands

from apocalypse_bot.game_data.jobs import JOBS, JOB_CHANGE_COST


def register_job_commands(bot, get_user, check_registered, save_data):
    @bot.command(name="직업목록")
    async def job_list(ctx):
        lines = ["👔 **[생존자 직업 목록]**"]
        for name, info in JOBS.items():
            lines.append(
                f"\n{info['emoji']} **{name}**\n"
                f"└ {info['description']}\n"
                f"└ 패시브: {info['passive']}"
            )
        lines.append("\n선택: `!직업선택 직업명`")
        await ctx.send("\n".join(lines))

    @bot.command(name="직업선택")
    async def choose_job(ctx, *, 직업명: str = ""):
        if not await check_registered(ctx):
            return
        u = get_user(ctx.author.id)
        직업명 = 직업명.strip()
        if 직업명 not in JOBS:
            await ctx.send("⚠️ 존재하지 않는 직업입니다. `!직업목록`을 확인하세요.")
            return
        if u.get("job"):
            await ctx.send(
                f"⚠️ 이미 **{u['job']}** 직업을 선택했습니다.\n"
                f"변경하려면 `!직업변경 {직업명}`을 사용하세요."
            )
            return
        u["job"] = 직업명
        u["job_changed_at"] = ""
        save_data()
        info = JOBS[직업명]
        await ctx.send(
            f"{info['emoji']} **[직업 선택 완료]**\n"
            f"{ctx.author.mention}님의 직업은 **{직업명}**입니다.\n"
            f"패시브: **{info['passive']}**"
        )

    @bot.command(name="직업정보")
    async def job_info(ctx, *, 직업명: str = ""):
        if not await check_registered(ctx):
            return
        u = get_user(ctx.author.id)
        name = 직업명.strip() or u.get("job")
        if not name:
            await ctx.send("⚠️ 아직 직업이 없습니다. `!직업목록`에서 선택하세요.")
            return
        if name not in JOBS:
            await ctx.send("⚠️ 존재하지 않는 직업입니다. `!직업목록`을 확인하세요.")
            return
        info = JOBS[name]
        await ctx.send(
            f"{info['emoji']} **[{name}]**\n"
            f"{info['description']}\n\n"
            f"⚔️ 전투력 보너스: **+{info['power_bonus']}**\n"
            f"❤️ 최대 체력 보너스: **+{info['hp_bonus']}**\n"
            f"⚡ 최대 스태미나 보너스: **+{info['stamina_bonus']}**\n"
            f"✨ 패시브: **{info['passive']}**"
        )

    @bot.command(name="직업변경")
    async def change_job(ctx, *, 직업명: str = ""):
        if not await check_registered(ctx):
            return
        u = get_user(ctx.author.id)
        직업명 = 직업명.strip()
        if 직업명 not in JOBS:
            await ctx.send("⚠️ 존재하지 않는 직업입니다. `!직업목록`을 확인하세요.")
            return
        current = u.get("job")
        if not current:
            await ctx.send(f"⚠️ 첫 직업은 무료입니다. `!직업선택 {직업명}`을 사용하세요.")
            return
        if current == 직업명:
            await ctx.send("⚠️ 현재 직업과 같습니다.")
            return
        if u.get("balance", 0) < JOB_CHANGE_COST:
            await ctx.send(
                f"⚠️ 직업 변경에는 식량 **{JOB_CHANGE_COST:,}개**가 필요합니다.\n"
                f"현재 보유: **{u.get('balance', 0):,}개**"
            )
            return
        u["balance"] -= JOB_CHANGE_COST
        u["job"] = 직업명
        save_data()
        info = JOBS[직업명]
        await ctx.send(
            f"🔄 **[직업 변경 완료]**\n"
            f"**{current} → {info['emoji']} {직업명}**\n"
            f"비용: 식량 **{JOB_CHANGE_COST:,}개**\n"
            f"패시브: **{info['passive']}**"
        )
