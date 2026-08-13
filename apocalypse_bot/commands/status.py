from datetime import datetime, timezone

from discord.ext import commands

from apocalypse_bot.game_data.jobs import JOBS
from apocalypse_bot.commands.conditions import condition_text, refresh_conditions

BASE_MAX_HP = 100
BASE_MAX_STAMINA = 100
STAMINA_RECOVERY_SECONDS = 180   # 3분당 1
HP_RECOVERY_SECONDS = 600         # 10분당 1

DUNGEON_STAMINA_COSTS = {
    "약함": 10,
    "보통": 15,
    "강함": 22,
    "지옥": 30,
}

LIFE_STAMINA_COSTS = {
    "채집": 8,
    "낚시": 10,
    "벌목": 12,
    "광산": 15,
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


def get_max_hp(user):
    job = JOBS.get(user.get("job"), {})
    return BASE_MAX_HP + int(job.get("hp_bonus", 0)) + max(0, user.get("level", 1) - 1) * 3


def get_max_stamina(user):
    job = JOBS.get(user.get("job"), {})
    return BASE_MAX_STAMINA + int(job.get("stamina_bonus", 0)) + max(0, user.get("level", 1) - 1)


def ensure_vitals(user):
    max_hp = get_max_hp(user)
    max_stamina = get_max_stamina(user)

    if not isinstance(user.get("hp"), int):
        user["hp"] = max_hp
    if not isinstance(user.get("stamina"), int):
        user["stamina"] = max_stamina

    user["hp"] = max(0, min(user["hp"], max_hp))
    user["stamina"] = max(0, min(user["stamina"], max_stamina))
    user.setdefault("last_vitals_update", _now().isoformat())
    return user


def refresh_vitals(user):
    ensure_vitals(user)
    now = _now()
    previous = _parse_time(user.get("last_vitals_update")) or now
    elapsed = max(0, int((now - previous).total_seconds()))

    stamina_gain = elapsed // STAMINA_RECOVERY_SECONDS
    hp_gain = elapsed // HP_RECOVERY_SECONDS

    if stamina_gain:
        user["stamina"] = min(get_max_stamina(user), user["stamina"] + stamina_gain)
    if hp_gain:
        user["hp"] = min(get_max_hp(user), user["hp"] + hp_gain)

    user["last_vitals_update"] = now.isoformat()
    return stamina_gain, hp_gain


def spend_stamina(user, amount):
    refresh_vitals(user)
    if user["stamina"] < amount:
        return False
    user["stamina"] -= amount
    return True


def apply_damage(user, amount):
    refresh_vitals(user)
    actual = max(0, int(amount))
    user["hp"] = max(0, user["hp"] - actual)
    knocked_out = user["hp"] <= 0
    if knocked_out:
        user["hp"] = max(1, get_max_hp(user) // 5)
    return actual, knocked_out


def hp_bar(current, maximum, width=10):
    filled = round(width * current / max(1, maximum))
    return "█" * filled + "░" * (width - filled)


def register_status_commands(bot, get_user, check_registered, save_data):
    @bot.command(name="상태")
    async def status(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        stamina_gain, hp_gain = refresh_vitals(user)
        condition_events = refresh_conditions(user, get_max_hp)
        max_hp = get_max_hp(user)
        max_stamina = get_max_stamina(user)
        save_data()

        recovery = []
        if hp_gain:
            recovery.append(f"❤️ HP +{hp_gain}")
        if stamina_gain:
            recovery.append(f"⚡ 스태미나 +{stamina_gain}")
        recovery_text = "\n♻️ 자동 회복: " + ", ".join(recovery) if recovery else ""
        condition_event_text = "\n⚠️ 경과: " + ", ".join(condition_events) if condition_events else ""

        await ctx.send(
            f"🩺 **[{ctx.author.name}의 생존 상태]**\n"
            f"❤️ HP: **{user['hp']} / {max_hp}**\n"
            f"`{hp_bar(user['hp'], max_hp)}`\n"
            f"⚡ 스태미나: **{user['stamina']} / {max_stamina}**\n"
            f"`{hp_bar(user['stamina'], max_stamina)}`\n"
            f"🦠 감염도: **{user['infection']}%**\n"
            f"📌 상태: **{condition_text(user)}**"
            f"{recovery_text}{condition_event_text}\n\n"
            f"HP는 10분당 1, 스태미나는 3분당 1 자동 회복됩니다."
        )

    @bot.command(name="휴식")
    @commands.cooldown(1, 1800, commands.BucketType.user)
    async def rest(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        refresh_vitals(user)
        max_hp = get_max_hp(user)
        max_stamina = get_max_stamina(user)

        before_hp = user["hp"]
        before_stamina = user["stamina"]
        user["hp"] = min(max_hp, user["hp"] + max(15, max_hp // 4))
        user["stamina"] = min(max_stamina, user["stamina"] + max(35, max_stamina // 2))
        hp_gain = user["hp"] - before_hp
        stamina_gain = user["stamina"] - before_stamina

        if hp_gain == 0 and stamina_gain == 0:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("✨ 이미 HP와 스태미나가 가득 찼습니다.")
            return

        save_data()
        await ctx.send(
            f"🏕️ **[휴식 완료]**\n"
            f"❤️ HP +**{hp_gain}** → {user['hp']} / {max_hp}\n"
            f"⚡ 스태미나 +**{stamina_gain}** → {user['stamina']} / {max_stamina}\n"
            f"다음 휴식은 30분 후 가능합니다."
        )
