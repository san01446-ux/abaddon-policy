import asyncio
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

from apocalypse_bot.commands.daily_quiz import BASE_QUESTIONS, get_daily_quiz
from apocalypse_bot.core.rate_limit_guard import should_pause_nonessential

KST = ZoneInfo("Asia/Seoul")


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _today_question(world_data, guild_id: int, date_text: str):
    # 직접 !오늘의퀴즈 / !정답과 동일한 KST 고정 문제 스냅샷을 사용합니다.
    return get_daily_quiz(world_data, guild_id, date_text)


def register_v31_commands(bot, get_user, check_registered, save_data, world_data):
    def settings():
        return world_data.setdefault("quiz_notifications", {})

    def guild_setting(guild_id: int):
        return settings().setdefault(str(guild_id), {
            "enabled": False,
            "channel_id": None,
            "role_id": None,
            "last_date": "",
            "start_sent": False,
            "reminder_sent": False,
            "closing_sent": False,
            "end_sent": False,
            "thread_id": None,
            "message_id": None,
        })

    async def fetch_channel(guild, channel_id):
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                return None
        return channel

    async def get_thread(guild, state):
        thread_id = state.get("thread_id")
        if not thread_id:
            return None
        thread = guild.get_thread(int(thread_id))
        if thread:
            return thread
        try:
            fetched = await bot.fetch_channel(int(thread_id))
            return fetched if isinstance(fetched, discord.Thread) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            return None

    def reset_daily_state(state, date_text):
        if state.get("last_date") == date_text:
            return
        state.update({
            "last_date": date_text,
            "start_sent": False,
            "reminder_sent": False,
            "closing_sent": False,
            "end_sent": False,
            "thread_id": None,
            "message_id": None,
        })

    def mention_text(guild, state):
        role_id = state.get("role_id")
        if role_id and guild.get_role(int(role_id)):
            return f"<@&{role_id}>"
        return ""

    async def post_start(guild, channel, state, date_text):
        q, golden = _today_question(world_data, guild.id, date_text)
        choices = "\n".join(f"**{i}.** {text}" for i, text in enumerate(q["choices"], 1))
        reward_food = 3000 if golden else 700
        reward_exp = 1200 if golden else 350
        title = "🌟 황금 일일 퀴즈가 시작되었습니다!" if golden else "📣 오늘의 일일 퀴즈가 시작되었습니다!"
        embed = discord.Embed(
            title=title,
            description=(
                f"**분류:** `{q['category']}`\n\n"
                f"### Q. {q['q']}\n{choices}\n\n"
                f"⏰ **참여 시간:** 오후 1:00 ~ 오후 7:00 (KST)\n"
                f"🎁 **보상:** 식량 {reward_food:,}개 + 경험치 {reward_exp:,}\n"
                "🎯 **기회:** 하루 최대 3회"
            ),
            color=0x7C3AED,
            timestamp=datetime.now(KST),
        )
        embed.set_footer(text="아바돈 일일 퀴즈 · 아래 스레드에서 !정답 번호 또는 답안을 입력하세요")
        content = mention_text(guild, state)
        message = await channel.send(content=content or None, embed=embed)
        state["message_id"] = message.id

        try:
            thread = await message.create_thread(
                name=f"🧠 {date_text} 일일 퀴즈 답안",
                auto_archive_duration=1440,
            )
            state["thread_id"] = thread.id
            await thread.send(
                "이 스레드에서 `!정답 번호` 또는 `!정답 답안`을 입력하세요.\n"
                "예: `!정답 2` · 정답은 다른 생존자에게 스포하지 말기!"
            )
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            await channel.send(
                "⚠️ 스레드를 만들 권한이 없어 현재 채널에서 진행합니다. "
                "봇에 **공개 스레드 만들기 / 스레드에서 메시지 보내기** 권한을 주세요."
            )

        state["start_sent"] = True
        save_data()

    async def post_reminder(guild, channel, state):
        thread = await get_thread(guild, state)
        target = thread or channel
        await target.send("🔔 **일일 퀴즈 참여 알림!** 아직 풀지 않았다면 `!정답`으로 도전하세요. 오후 7시에 마감됩니다.")
        state["reminder_sent"] = True
        save_data()

    async def post_closing(guild, channel, state):
        thread = await get_thread(guild, state)
        target = thread or channel
        await target.send("⏰ **마감 30분 전!** 오늘의 일일 퀴즈가 오후 7시에 종료됩니다.")
        state["closing_sent"] = True
        save_data()

    async def post_end(guild, channel, state, date_text):
        q, _ = _today_question(world_data, guild.id, date_text)
        answer_index = int(q["answer"]) - 1
        answer_text = q["choices"][answer_index]
        thread = await get_thread(guild, state)
        target = thread or channel
        await target.send(
            "🏁 **오늘의 일일 퀴즈가 종료되었습니다!**\n"
            f"정답은 **{q['answer']}번 · {answer_text}**였습니다. 내일 오후 1시에 새로운 문제가 열립니다."
        )
        if thread:
            try:
                await asyncio.sleep(2)
                await thread.edit(locked=True, archived=True, reason="일일 퀴즈 마감")
            except (discord.Forbidden, discord.HTTPException):
                pass
        state["end_sent"] = True
        save_data()

    @tasks.loop(minutes=1)
    async def quiz_scheduler():
        if should_pause_nonessential():
            return
        now = datetime.now(KST)
        date_text = now.strftime("%Y-%m-%d")
        minute = now.hour * 60 + now.minute

        for guild in list(bot.guilds):
            state = guild_setting(guild.id)
            if not state.get("enabled"):
                continue
            reset_daily_state(state, date_text)
            channel = await fetch_channel(guild, state.get("channel_id"))
            if channel is None:
                continue
            try:
                # 재시작되어도 해당 시간대 안이라면 빠진 알림을 순서대로 복구합니다.
                if 13 * 60 <= minute < 19 * 60 and not state.get("start_sent"):
                    await post_start(guild, channel, state, date_text)
                if 16 * 60 <= minute < 18 * 60 + 30 and state.get("start_sent") and not state.get("reminder_sent"):
                    await post_reminder(guild, channel, state)
                if 18 * 60 + 30 <= minute < 19 * 60 and state.get("start_sent") and not state.get("closing_sent"):
                    await post_closing(guild, channel, state)
                if minute >= 19 * 60 and state.get("start_sent") and not state.get("end_sent"):
                    await post_end(guild, channel, state, date_text)
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"[퀴즈 자동 알림 오류] guild={guild.id}: {exc}")

    @quiz_scheduler.before_loop
    async def before_quiz_scheduler():
        await bot.wait_until_ready()

    async def start_quiz_scheduler():
        if not quiz_scheduler.is_running():
            quiz_scheduler.start()

    bot.add_listener(start_quiz_scheduler, "on_ready")

    async def require_admin(ctx):
        if ctx.guild and (ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator):
            return True
        await ctx.send("❌ 이 명령어는 서버 관리자만 사용할 수 있습니다.")
        return False

    @bot.command(name="퀴즈알림설정")
    async def quiz_notify_setup(ctx, 역할: discord.Role = None):
        if not await require_admin(ctx):
            return
        state = guild_setting(ctx.guild.id)
        state.update({
            "enabled": True,
            "channel_id": ctx.channel.id,
            "role_id": 역할.id if 역할 else None,
        })
        save_data()
        role_text = 역할.mention if 역할 else "역할 멘션 없음"
        await ctx.send(
            "✅ **일일 퀴즈 자동 알림 설정 완료**\n"
            f"채널: {ctx.channel.mention}\n"
            f"알림 역할: {role_text}\n"
            "일정: **13:00 시작 · 16:00 알림 · 18:30 마감 예고 · 19:00 종료** (한국 시간)\n"
            "봇 권한: 메시지 보내기, 임베드 링크, 공개 스레드 만들기, 스레드에서 메시지 보내기"
        )

    @bot.command(name="퀴즈알림해제")
    async def quiz_notify_disable(ctx):
        if not await require_admin(ctx):
            return
        state = guild_setting(ctx.guild.id)
        state["enabled"] = False
        save_data()
        await ctx.send("🔕 이 서버의 일일 퀴즈 자동 알림을 해제했습니다.")

    @bot.command(name="퀴즈알림상태")
    async def quiz_notify_status(ctx):
        if not ctx.guild:
            return
        state = guild_setting(ctx.guild.id)
        channel = ctx.guild.get_channel(int(state["channel_id"])) if state.get("channel_id") else None
        role = ctx.guild.get_role(int(state["role_id"])) if state.get("role_id") else None
        await ctx.send(
            "📋 **일일 퀴즈 자동 알림 상태**\n"
            f"상태: {'✅ 사용 중' if state.get('enabled') else '❌ 꺼짐'}\n"
            f"채널: {channel.mention if channel else '미설정'}\n"
            f"알림 역할: {role.mention if role else '없음'}\n"
            "일정: 13:00 / 16:00 / 18:30 / 19:00 (KST)"
        )

    @bot.hybrid_group(name="rpg", fallback="안내", invoke_without_command=True, description="RPG 시작과 가입 안내를 확인합니다.")
    async def rpg_group(ctx):
        await ctx.send("사용법: `!rpg start`\n가입 전이라면 먼저 `!가입 생존자`를 입력하세요.")

    @rpg_group.command(name="start", aliases=["시작"])
    async def rpg_start(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if user.get("rpg_started"):
            await ctx.send(
                "✅ 이미 아바돈 RPG를 시작한 생존자입니다.\n"
                "`!정보`로 상태를 확인하고 `!지역탐색` 또는 `!던전 약함`으로 출발하세요."
            )
            return

        user["rpg_started"] = True
        tutorial = user.setdefault("tutorial", {})
        tutorial.update({"started": True, "step": int(tutorial.get("step", 0)), "completed": bool(tutorial.get("completed", False)), "skipped": bool(tutorial.get("skipped", False)), "rewards_received": int(tutorial.get("rewards_received", 0))})
        user["balance"] = user.get("balance", 0) + 500
        medical = user.setdefault("medical_items", {})
        medical["붕대"] = medical.get("붕대", 0) + 2
        medical["소독약"] = medical.get("소독약", 0) + 1
        save_data()

        embed = discord.Embed(
            title="☣️ ABADDON RPG START",
            description=(
                f"{ctx.author.mention}, 종말의 생존자 등록이 완료되었습니다.\n\n"
                "🎒 **초기 생존 키트 지급**\n"
                "식량 **500개** · 붕대 **2개** · 소독약 **1개**\n\n"
                "### 첫 임무\n"
                "1. `!정보` — 생존자 상태 확인\n"
                "2. `!직업목록` → `!직업선택 직업명`\n"
                "3. `!상점` → `!구매 아이템명`\n"
                "4. `!지역탐색` 또는 `!던전 약함`\n"
                "5. `!출석`과 `!오늘의퀴즈`로 매일 보급 획득\n\n"
                "🧭 단계별 보상 튜토리얼: `!튜토리얼`"
            ),
            color=0x6D28D9,
        )
        embed.set_footer(text="전체 명령어는 !도움말 또는 !명령어")
        await ctx.send(embed=embed)

    @rpg_group.command(name="전투")
    async def rpg_combat(ctx, 난이도: str = "보통"):
        if not await check_registered(ctx):
            return
        starter = getattr(bot, "v636_start_combat", None)
        if starter is None:
            await ctx.send("⚠️ 전술 전투 모듈이 아직 준비되지 않았습니다.")
            return
        await starter(ctx, "RPG", 난이도)
