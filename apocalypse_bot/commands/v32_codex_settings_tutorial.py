import discord


TUTORIAL_STEPS = [
    {"command": "정보", "label": "생존자 정보 확인", "reward": 200},
    {"command": "직업목록", "label": "직업 목록 확인", "reward": 250},
    {"command": "상점", "label": "암시장 상점 확인", "reward": 300},
    {"command": "지역목록", "label": "이동 가능한 지역 확인", "reward": 350},
    {"command": "인벤토리", "label": "인벤토리 확인", "reward": 400},
]

CODEX_MILESTONES = {
    10: 1000,
    25: 3000,
    50: 7000,
    75: 12000,
    100: 25000,
}


def register_v32_commands(
    bot, get_user, check_registered, save_data, world_data,
    send_pages, item_db, pet_db,
):
    def guild_settings(guild_id: int):
        root = world_data.setdefault("guild_settings", {})
        return root.setdefault(str(guild_id), {
            "announcement_channel_id": None,
            "rpg_channel_id": None,
            "codex_notifications": True,
            "tutorial_notifications": True,
            "story_enabled": True,
        })

    def ensure_codex(user):
        codex = user.setdefault("collection_codex", {})
        codex.setdefault("items", [])
        codex.setdefault("pets", [])
        codex.setdefault("monsters", {})
        codex.setdefault("claimed_milestones", [])

        # 기존 보유 데이터를 자동 반영하여 업데이트 전 기록도 최대한 보존합니다.
        for item in user.get("inventory", []):
            if item not in codex["items"]:
                codex["items"].append(item)
        for pet in user.get("pet_collection", {}).keys():
            if pet and pet not in codex["pets"]:
                codex["pets"].append(pet)
        pet = user.get("pet")
        if pet and pet not in codex["pets"]:
            codex["pets"].append(pet)
        for monster, kills in user.get("zombie_kills", {}).items():
            codex["monsters"][monster] = max(int(kills or 0), int(codex["monsters"].get(monster, 0)))
        for monster, kills in user.get("dungeon_monster_kills", {}).items():
            codex["monsters"][monster] = max(int(kills or 0), int(codex["monsters"].get(monster, 0)))
        return codex

    def ensure_tutorial(user):
        tutorial = user.setdefault("tutorial", {})
        tutorial.setdefault("started", bool(user.get("rpg_started")))
        tutorial.setdefault("step", 0)
        tutorial.setdefault("completed", False)
        tutorial.setdefault("skipped", False)
        tutorial.setdefault("rewards_received", 0)
        return tutorial

    def all_items():
        result = []
        for tier in item_db.values():
            result.extend(tier.keys())
        return sorted(set(result))

    def all_monsters():
        names = set()
        try:
            from apocalypse_bot.core import bot as core_bot
            for dungeon in core_bot.DUNGEONS.values():
                for monster in dungeon.get("monsters", []):
                    if monster.get("name"):
                        names.add(monster["name"])
        except Exception:
            pass
        try:
            from apocalypse_bot.commands.world_exploration import REGIONS
            for region in REGIONS.values():
                for zombie in region.get("zombies", []):
                    if isinstance(zombie, dict):
                        name = zombie.get("name")
                    else:
                        name = str(zombie)
                    if name:
                        names.add(name)
        except Exception:
            pass
        return sorted(names)

    def codex_counts(user):
        codex = ensure_codex(user)
        item_total = max(1, len(all_items()))
        pet_total = max(1, len(pet_db))
        monster_total = max(1, len(all_monsters()))
        found = len(set(codex["items"])) + len(set(codex["pets"])) + len(codex["monsters"])
        total = item_total + pet_total + monster_total
        percent = min(100, int(found * 100 / total))
        return found, total, percent

    def admin_only(ctx):
        return bool(ctx.guild and (
            ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator
        ))

    @bot.hybrid_group(name="도감", fallback="전체", invoke_without_command=True, description="수집한 장비, 펫, 몬스터 도감을 확인합니다.")
    async def codex_group(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        codex = ensure_codex(user)
        found, total, percent = codex_counts(user)
        next_reward = next((p for p in CODEX_MILESTONES if p not in codex["claimed_milestones"]), None)
        await ctx.send(
            f"📖 **[{ctx.author.name}님의 생존 도감]**\n"
            f"전체 수집률: **{found}/{total} ({percent}%)**\n"
            f"🛠️ 장비: **{len(set(codex['items']))}/{len(all_items())}**\n"
            f"🐾 펫: **{len(set(codex['pets']))}/{len(pet_db)}**\n"
            f"🧟 몬스터: **{len(codex['monsters'])}/{len(all_monsters())}**\n"
            f"다음 보상: **{next_reward}%**" if next_reward else
            f"📖 **[{ctx.author.name}님의 생존 도감]**\n전체 수집률: **{found}/{total} ({percent}%)**\n모든 도감 보상을 수령했습니다."
        )

    @codex_group.command(name="장비")
    async def codex_items(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        owned = set(ensure_codex(user)["items"])
        lines = [f"{'✅' if name in owned else '❔'} {name if name in owned else '???'}" for name in all_items()]
        await send_pages(ctx.channel, "🛠️ **[장비 도감]**\n" + "\n".join(lines))

    @codex_group.command(name="펫")
    async def codex_pets(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        owned = set(ensure_codex(user)["pets"])
        lines = [f"{'✅' if name in owned else '❔'} {name if name in owned else '???'}" for name in sorted(pet_db)]
        await send_pages(ctx.channel, "🐾 **[펫 도감]**\n" + "\n".join(lines))

    @codex_group.command(name="몬스터")
    async def codex_monsters(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        kills = ensure_codex(user)["monsters"]
        lines = []
        for name in all_monsters():
            lines.append(f"{'✅' if name in kills else '❔'} {name if name in kills else '???'}" + (f" · 처치 {kills[name]}회" if name in kills else ""))
        await send_pages(ctx.channel, "🧟 **[몬스터 도감]**\n" + "\n".join(lines))

    @bot.command(name="도감보상")
    async def codex_reward(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        codex = ensure_codex(user)
        _, _, percent = codex_counts(user)
        available = [p for p in CODEX_MILESTONES if p <= percent and p not in codex["claimed_milestones"]]
        if not available:
            await ctx.send("⚠️ 현재 받을 수 있는 도감 보상이 없습니다.")
            return
        reward = sum(CODEX_MILESTONES[p] for p in available)
        codex["claimed_milestones"].extend(available)
        user["balance"] = user.get("balance", 0) + reward
        user.setdefault("stats", {}).setdefault("earned", 0)
        user["stats"]["earned"] += reward
        save_data()
        await ctx.send(f"🎁 도감 달성 보상 **식량 {reward:,}개** 지급!\n달성 구간: {', '.join(f'{p}%' for p in available)}")

    @bot.command(name="서버설정")
    async def server_settings(ctx):
        if not ctx.guild:
            return
        state = guild_settings(ctx.guild.id)
        quiz = world_data.setdefault("quiz_notifications", {}).get(str(ctx.guild.id), {})
        announce = ctx.guild.get_channel(state.get("announcement_channel_id") or 0)
        rpg_channel = ctx.guild.get_channel(state.get("rpg_channel_id") or 0)
        quiz_channel = ctx.guild.get_channel(quiz.get("channel_id") or 0)
        await ctx.send(
            "⚙️ **[아바돈 서버 설정 패널]**\n"
            f"📢 공지 채널: {announce.mention if announce else '미설정'}\n"
            f"🎮 RPG 권장 채널: {rpg_channel.mention if rpg_channel else '미설정'}\n"
            f"🧠 퀴즈 자동 알림: {'켜짐' if quiz.get('enabled') else '꺼짐'} · {quiz_channel.mention if quiz_channel else '미설정'}\n"
            f"📖 도감 알림: {'켜짐' if state.get('codex_notifications') else '꺼짐'}\n"
            f"🧭 튜토리얼 알림: {'켜짐' if state.get('tutorial_notifications') else '꺼짐'}\n"
            f"🎬 스토리 기능: {'켜짐' if state.get('story_enabled', True) else '꺼짐'}\n\n"
            "관리자 설정 명령어\n"
            "`!서버채널 공지` · `!서버채널 RPG`\n"
            "`!서버기능 도감 ON/OFF` · `!서버기능 튜토리얼 ON/OFF`\n"
            "`!서버기능 스토리 ON/OFF`\n"
            "퀴즈 채널은 기존 `!퀴즈알림설정`으로 설정합니다."
        )

    @bot.command(name="서버채널")
    async def server_channel(ctx, 종류: str):
        if not admin_only(ctx):
            await ctx.send("❌ 서버 관리자만 설정할 수 있습니다.")
            return
        state = guild_settings(ctx.guild.id)
        key = 종류.strip().lower()
        if key in ("공지", "announcement"):
            state["announcement_channel_id"] = ctx.channel.id
            text = "공지"
        elif key in ("rpg", "게임"):
            state["rpg_channel_id"] = ctx.channel.id
            text = "RPG 권장"
        else:
            await ctx.send(
                "⚠️ 사용법: `!서버채널 공지/RPG`\n"
                "퀴즈 채널은 `!퀴즈알림설정`을 사용하세요."
            )
            return
        save_data()
        await ctx.send(f"✅ 이 채널을 **{text} 채널**로 설정했습니다: {ctx.channel.mention}")

    @bot.command(name="서버기능")
    async def server_feature(ctx, 기능: str, 상태: str):
        if not admin_only(ctx):
            await ctx.send("❌ 서버 관리자만 설정할 수 있습니다.")
            return
        mapping = {"도감": "codex_notifications", "튜토리얼": "tutorial_notifications", "스토리": "story_enabled"}
        feature_key = mapping.get(기능)
        if not feature_key or 상태 not in ("켜기", "끄기", "on", "off"):
            await ctx.send("⚠️ 사용법: `!서버기능 도감/튜토리얼/스토리 ON/OFF`")
            return
        enabled = 상태 in ("켜기", "on")
        guild_settings(ctx.guild.id)[feature_key] = enabled
        save_data()
        await ctx.send(f"✅ **{기능} 기능**을 {'켰습니다' if enabled else '껐습니다'}.")

    @bot.command(name="튜토리얼")
    async def tutorial_status(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        tutorial = ensure_tutorial(user)
        if not tutorial["started"]:
            tutorial["started"] = True
            save_data()
        if tutorial["completed"]:
            await ctx.send("🏁 초보자 튜토리얼을 모두 완료했습니다!")
            return
        step = min(tutorial["step"], len(TUTORIAL_STEPS) - 1)
        current = TUTORIAL_STEPS[step]
        await ctx.send(
            f"🧭 **[초보자 튜토리얼 {step + 1}/{len(TUTORIAL_STEPS)}]**\n"
            f"임무: **{current['label']}**\n"
            f"입력: `!{current['command']}`\n"
            f"단계 보상: 식량 **{current['reward']:,}개**"
        )

    @bot.command(name="튜토리얼건너뛰기")
    async def tutorial_skip(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        tutorial = ensure_tutorial(user)
        if tutorial["completed"]:
            await ctx.send("⚠️ 이미 튜토리얼이 종료되었습니다.")
            return
        tutorial["started"] = True
        tutorial["completed"] = True
        tutorial["skipped"] = True
        save_data()
        await ctx.send("⏭️ 튜토리얼을 건너뛰었습니다. 건너뛰면 단계 보상은 지급되지 않습니다.")

    async def on_command_completion(ctx):
        if not ctx.guild or ctx.author.bot:
            return
        user = get_user(ctx.author.id)
        if not user:
            return

        changed = False
        codex = ensure_codex(user)
        before = (len(codex["items"]), len(codex["pets"]), len(codex["monsters"]))
        ensure_codex(user)
        after = (len(codex["items"]), len(codex["pets"]), len(codex["monsters"]))
        if before != after:
            changed = True

        tutorial = ensure_tutorial(user)
        command_name = ctx.command.qualified_name if ctx.command else ""
        if tutorial["started"] and not tutorial["completed"] and not tutorial["skipped"]:
            step = tutorial["step"]
            if step < len(TUTORIAL_STEPS) and command_name == TUTORIAL_STEPS[step]["command"]:
                reward = TUTORIAL_STEPS[step]["reward"]
                user["balance"] = user.get("balance", 0) + reward
                user.setdefault("stats", {}).setdefault("earned", 0)
                user["stats"]["earned"] += reward
                tutorial["rewards_received"] += reward
                tutorial["step"] += 1
                changed = True
                state = guild_settings(ctx.guild.id)
                if tutorial["step"] >= len(TUTORIAL_STEPS):
                    tutorial["completed"] = True
                    if state.get("tutorial_notifications", True):
                        await ctx.send(f"🏁 **초보자 튜토리얼 완료!** 총 보상 식량 **{tutorial['rewards_received']:,}개**를 받았습니다.")
                elif state.get("tutorial_notifications", True):
                    nxt = TUTORIAL_STEPS[tutorial["step"]]
                    await ctx.send(
                        f"✅ 튜토리얼 단계 완료! 식량 **{reward:,}개** 지급.\n"
                        f"다음 임무: **{nxt['label']}** → `!{nxt['command']}`"
                    )

        if changed:
            save_data()

    bot.add_listener(on_command_completion, "on_command_completion")
