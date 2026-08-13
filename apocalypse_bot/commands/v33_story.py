import discord


STORY_VERSION = 1
STORY_START_NODE = "s1_signal"


def _choice(text, result, next_node=None, *, effects=None, flags=None, requires_any=None, requires_all=None, ending=None):
    return {
        "text": text,
        "result": result,
        "next": next_node,
        "effects": effects or {},
        "flags": flags or [],
        "requires_any": requires_any or [],
        "requires_all": requires_all or [],
        "ending": ending,
    }


STORY_NODES = {
    "s1_signal": {
        "chapter": "제1장",
        "title": "검은 주파수",
        "location": "폐허도심 · 버려진 옥탑",
        "body": (
            "정전된 도시 위로 빗소리만 내려앉은 밤. 고장 난 줄 알았던 군용 무전기에서 "
            "짧은 구조 신호가 반복된다.\n\n"
            "‘…생존자는 북쪽 중계탑으로… 검은 신호를 믿지 마…’\n\n"
            "신호의 발신지는 세 곳으로 갈라진다. 시립병원, 경찰서, 그리고 당신의 은신처 바로 아래 지하실이다."
        ),
        "choices": [
            _choice(
                "시립병원으로 향해 부상자를 찾는다.",
                "응급 계단을 따라 병원 내부로 진입했다. 복도 끝에서 희미한 손전등 불빛이 흔들린다.",
                "s2_hospital",
                effects={"food": 300, "medical": {"붕대": 1}},
                flags=["route_hospital"],
            ),
            _choice(
                "경찰서 기록실에서 신호의 정체를 조사한다.",
                "봉쇄된 경찰서 후문을 열었다. 기록실 안에는 사태 직전의 무전 기록이 그대로 남아 있다.",
                "s2_police",
                effects={"food": 250, "materials": {"고철": 2}},
                flags=["route_police"],
            ),
            _choice(
                "밖으로 나가지 않고 지하실부터 확인한다.",
                "은신처 지하에서 임시 송신 장비와 누군가 급히 남긴 지도를 발견했다.",
                "s2_bunker",
                effects={"food": 200, "hp": 8},
                flags=["route_bunker", "signal_distrust"],
            ),
        ],
    },
    "s2_hospital": {
        "chapter": "제2장",
        "title": "마지막 당직자",
        "location": "시립병원 · 응급병동",
        "body": (
            "응급병동에는 감염자 대신 한 명의 의사가 남아 있다. 그는 백신 표본이 든 냉각 상자를 붙잡고 있다. "
            "하지만 방화문 너머에서 수십 개의 손톱이 철판을 긁는 소리가 들린다."
        ),
        "choices": [
            _choice(
                "의사와 표본을 함께 구조한다.",
                "의사와 함께 비상계단을 빠져나왔다. 그는 중계탑 신호가 감염자를 유도하는 미끼라고 경고한다.",
                "s3_survivor",
                effects={"food": 450, "medical": {"소독약": 1}, "infection": -3},
                flags=["helped_doctor", "knows_lure"],
            ),
            _choice(
                "약품만 챙기고 혼자 탈출한다.",
                "의사의 외침을 뒤로하고 약품 창고를 털었다. 생존에는 도움이 되겠지만 무전기의 진실은 알 수 없다.",
                "s3_survivor",
                effects={"medical": {"붕대": 2, "항생제": 1}, "infection": 2},
                flags=["took_medicine"],
            ),
            _choice(
                "옥상 안테나에서 발신 기록을 복사한다.",
                "옥상 단말기에서 ‘ABADDON’이라는 암호화 프로토콜과 중계탑 좌표를 찾아냈다.",
                "s3_survivor",
                effects={"food": 350, "materials": {"전자부품": 2}},
                flags=["decoded_signal", "knows_abaddon"],
            ),
        ],
    },
    "s2_police": {
        "chapter": "제2장",
        "title": "봉쇄 명령 17호",
        "location": "경찰서 · 지하 기록실",
        "body": (
            "기록실의 마지막 문서에는 정부 명령이 찍혀 있다. ‘중계탑 접근 생존자 전원 격리.’ "
            "옆 유치장에서는 아직 살아 있는 사람이 문을 두드리고, 무기고 경보등은 붉게 깜빡인다."
        ),
        "choices": [
            _choice(
                "유치장의 생존자를 풀어준다.",
                "구조한 생존자는 전직 통신기사였다. 그는 중계탑의 비상 우회 회선을 알고 있다고 말한다.",
                "s3_survivor",
                effects={"food": 400, "hp": -5},
                flags=["freed_prisoner", "knows_bypass"],
            ),
            _choice(
                "무기고를 열어 장비를 확보한다.",
                "경보가 울렸지만 필요한 장비를 챙겼다. 중계탑까지 밀고 들어갈 힘은 생겼다.",
                "s3_survivor",
                effects={"food": 500, "materials": {"화약": 2, "고철": 2}},
                flags=["took_armory"],
            ),
            _choice(
                "사건 기록과 서버 자료를 복사한다.",
                "검은 신호가 단순한 구조 방송이 아니라 감염자 이동을 통제하는 실험이었다는 증거를 확보했다.",
                "s3_survivor",
                effects={"food": 350, "materials": {"전자부품": 3}},
                flags=["copied_logs", "knows_lure"],
            ),
        ],
    },
    "s2_bunker": {
        "chapter": "제2장",
        "title": "벽 아래의 지도",
        "location": "폐허도심 · 지하 방공호",
        "body": (
            "지하 방공호에는 최근까지 누군가 생활한 흔적이 남아 있다. 벽면 지도에는 중계탑과 격리연구소가 "
            "하나의 검은 선으로 연결되어 있다. 구석의 발전기는 아직 한 번 정도 작동할 연료가 남았다."
        ),
        "choices": [
            _choice(
                "발전기를 돌려 암호 신호를 해독한다.",
                "해독된 문장에는 ‘ABADDON 프로토콜 재가동’이라는 문구와 중계탑 관리자 코드가 포함되어 있었다.",
                "s3_survivor",
                effects={"food": 300, "materials": {"전자부품": 2}},
                flags=["decoded_signal", "knows_abaddon"],
            ),
            _choice(
                "방공호의 식량과 장비를 챙긴다.",
                "필요한 보급품을 확보했다. 누가 이 장소를 사용했는지는 끝내 알아내지 못했다.",
                "s3_survivor",
                effects={"food": 800, "medical": {"붕대": 1}},
                flags=["stocked_supplies"],
            ),
            _choice(
                "지도에 표시된 비밀 통로로 이동한다.",
                "오래된 통신 관로를 따라가자 중계탑 봉쇄선 뒤편으로 이어지는 우회로가 나타났다.",
                "s3_survivor",
                effects={"food": 250, "hp": -4},
                flags=["knows_bypass"],
            ),
        ],
    },
    "s3_survivor": {
        "chapter": "제3장",
        "title": "붉은 우비의 생존자",
        "location": "북부 고가도로",
        "body": (
            "중계탑으로 향하는 고가도로에서 붉은 우비를 입은 생존자 ‘서윤’을 만난다. "
            "그녀는 중계탑 안에 갇힌 동생을 구해야 한다며 동행을 요청한다. 하지만 허리춤의 무전기에서는 "
            "당신이 들었던 것과 똑같은 검은 주파수가 흘러나온다."
        ),
        "choices": [
            _choice(
                "서윤을 믿고 함께 이동한다.",
                "서윤은 중계탑 경비 드론의 사각지대와 내부 출입 암호를 알려주었다.",
                "s4_tower",
                effects={"food": 350, "hp": 5},
                flags=["saved_survivor", "tower_code"],
            ),
            _choice(
                "무전기와 정보를 넘기라고 압박한다.",
                "서윤은 마지못해 단말기를 건넸다. 당신은 내부 지도를 얻었지만 그녀는 홀로 사라졌다.",
                "s4_tower",
                effects={"food": 500, "infection": 1},
                flags=["took_radio", "tower_map"],
            ),
            _choice(
                "위험을 피하기 위해 혼자 움직인다.",
                "서윤과 갈라져 폐차 사이를 우회했다. 안전했지만 중계탑 정문을 정면으로 돌파해야 한다.",
                "s4_tower",
                effects={"food": 250, "hp": 8},
                flags=["lone_survivor"],
            ),
        ],
    },
    "s4_tower": {
        "chapter": "제4장",
        "title": "죽은 자들의 안테나",
        "location": "북부 중계탑 · 제어실",
        "body": (
            "제어실 화면에는 도시 전역의 감염자 이동 경로가 실시간으로 표시된다. 검은 신호가 울릴 때마다 "
            "붉은 점들이 한 방향으로 몰린다. 중앙 단말기에는 세 개의 명령만 남아 있다: 복구, 파괴, 복사."
        ),
        "choices": [
            _choice(
                "중계 장비를 복구해 생존자 채널을 연다.",
                "짧은 시간 동안 도시 곳곳의 생존자 목소리가 되살아났다. 격리연구소에서 마지막 응답이 도착한다.",
                "s5_core",
                effects={"food": 700, "materials": {"전자부품": 2}},
                flags=["opened_channel"],
            ),
            _choice(
                "감염자 유도 송신기를 파괴한다.",
                "송신기가 폭발하며 도시의 감염자 무리가 혼란에 빠졌다. 대신 연구소로 향하는 길도 무너졌다.",
                "s5_core",
                effects={"food": 600, "hp": -8, "infection": 2},
                flags=["destroyed_jammer"],
            ),
            _choice(
                "ABADDON 프로토콜 전체를 복사한다.",
                "서버에서 도시 통제 권한과 실험 기록을 확보했다. 누군가 이 힘을 손에 넣는다면 새로운 질서를 만들 수 있다.",
                "s5_core",
                effects={"food": 550, "materials": {"전자부품": 4}},
                flags=["copied_protocol", "knows_abaddon"],
            ),
        ],
    },
    "s5_core": {
        "chapter": "최종장",
        "title": "아바돈 프로토콜",
        "location": "격리연구소 · 중앙 통제실",
        "body": (
            "연구소 중앙 통제실에서 검은 신호의 정체가 드러난다. ‘ABADDON’은 감염자를 제거하는 무기가 아니라, "
            "소리와 전파로 감염자 군체를 유도하는 도시 통제 시스템이었다.\n\n"
            "배터리는 단 한 번의 명령만 수행할 수 있다. 당신의 선택이 도시의 다음 아침을 결정한다."
        ),
        "choices": [
            _choice(
                "생존자들에게 안전 경로를 방송한다.",
                "검은 주파수는 처음으로 사람을 살리는 신호가 되었다. 도시 곳곳에서 대피 행렬이 움직이기 시작한다.",
                effects={"food": 6000, "title": "새벽의 송신자", "infection": -5},
                requires_any=["saved_survivor", "helped_doctor", "freed_prisoner", "opened_channel"],
                ending={
                    "id": "dawn_broadcaster",
                    "title": "엔딩 A · 새벽의 송신자",
                    "body": "당신의 목소리는 폐허를 가로질러 살아남은 사람들을 하나로 모았다. 검은 신호는 희망의 주파수로 다시 태어났다.",
                },
            ),
            _choice(
                "시스템과 연구 기록을 모두 파괴한다.",
                "중앙 서버가 불타며 감염자 군체를 조종하던 신호가 영원히 끊겼다. 누구도 다시 이 도시를 리모컨처럼 다룰 수 없다.",
                effects={"food": 5000, "title": "검은 신호 파괴자", "hp": -10},
                ending={
                    "id": "signal_breaker",
                    "title": "엔딩 B · 검은 신호 파괴자",
                    "body": "도시는 더 위험해졌지만 자유로워졌다. 당신은 아무도 가져서는 안 될 힘을 잿더미로 만들었다.",
                },
            ),
            _choice(
                "ABADDON의 통제 권한을 장악한다.",
                "도시 지도 위의 붉은 점들이 당신의 명령에 따라 움직인다. 이제 감염자도, 생존자도 당신의 선택을 피할 수 없다.",
                effects={"food": 7000, "title": "아바돈의 대리인", "materials": {"에너지코어": 1}},
                requires_any=["copied_protocol", "copied_logs", "decoded_signal", "took_radio"],
                ending={
                    "id": "abaddon_heir",
                    "title": "엔딩 C · 아바돈의 대리인",
                    "body": "당신은 종말을 끝내지 않았다. 대신 종말을 지배하는 첫 번째 생존자가 되었다.",
                },
            ),
        ],
    },
}


def _default_story():
    return {
        "version": STORY_VERSION,
        "started": False,
        "completed": False,
        "node": STORY_START_NODE,
        "flags": [],
        "history": [],
        "ending": None,
        "endings": [],
        "claimed_rewards": [],
        "runs": 0,
    }


def ensure_story(user):
    story = user.get("story")
    if not isinstance(story, dict):
        story = _default_story()
        user["story"] = story

    defaults = _default_story()
    for key, value in defaults.items():
        if key not in story:
            story[key] = value.copy() if isinstance(value, list) else value

    if not isinstance(story.get("flags"), list):
        story["flags"] = []
    if not isinstance(story.get("history"), list):
        story["history"] = []
    if not isinstance(story.get("endings"), list):
        story["endings"] = []
    if not isinstance(story.get("claimed_rewards"), list):
        story["claimed_rewards"] = []
    if story.get("node") not in STORY_NODES:
        story["node"] = STORY_START_NODE
    story["version"] = STORY_VERSION
    return story


def register_v33_commands(bot, get_user, check_registered, save_data, world_data, get_max_hp, add_title):
    def guild_story_enabled(ctx):
        if not ctx.guild:
            return True
        settings = world_data.setdefault("guild_settings", {}).setdefault(str(ctx.guild.id), {})
        return settings.get("story_enabled", True)

    def available_choices(story, node):
        flags = set(story.get("flags", []))
        result = []
        for choice in node.get("choices", []):
            any_req = choice.get("requires_any", [])
            all_req = choice.get("requires_all", [])
            if any_req and not any(flag in flags for flag in any_req):
                continue
            if all_req and not all(flag in flags for flag in all_req):
                continue
            result.append(choice)
        return result

    async def render_story(ctx, user):
        story = ensure_story(user)
        if not story["started"]:
            await ctx.send(
                "📻 **아바돈 스토리 시즌 1 — 검은 주파수**\n"
                "폐허 도시의 검은 구조 신호를 추적하는 선택형 캠페인입니다.\n"
                "시작: `!스토리 시작`"
            )
            return

        if story["completed"]:
            ending = story.get("ending") or {}
            endings = story.get("endings", [])
            await ctx.send(
                f"🏁 **스토리 시즌 1 완료**\n"
                f"마지막 엔딩: **{ending.get('title', '기록 없음')}**\n"
                f"발견한 엔딩: **{len(endings)}/3**\n"
                f"완료 횟수: **{story.get('runs', 0)}회**\n\n"
                "기록: `!스토리 기록` · 다른 분기: `!스토리 재시작`\n"
                "※ 이미 받은 선택 보상은 재플레이에서 중복 지급되지 않습니다."
            )
            return

        node = STORY_NODES[story["node"]]
        choices = available_choices(story, node)
        embed = discord.Embed(
            title=f"📖 {node['chapter']} · {node['title']}",
            description=node["body"],
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="📍 위치", value=node["location"], inline=False)
        embed.add_field(
            name="선택",
            value="\n".join(f"**{index}.** {choice['text']}" for index, choice in enumerate(choices, start=1)),
            inline=False,
        )
        embed.set_footer(text="입력: !스토리 선택 번호 · 진행 기록: !스토리 기록")
        await ctx.send(embed=embed)

    def apply_effects(user, effects):
        lines = []
        food = int(effects.get("food", 0) or 0)
        if food:
            user["balance"] = max(0, int(user.get("balance", 0)) + food)
            if food > 0:
                user.setdefault("stats", {}).setdefault("earned", 0)
                user["stats"]["earned"] += food
            lines.append(f"🥫 식량 {'+' if food > 0 else ''}{food:,}")

        hp = int(effects.get("hp", 0) or 0)
        if hp:
            before = int(user.get("hp", 100))
            user["hp"] = max(1, min(get_max_hp(user), before + hp))
            actual = user["hp"] - before
            if actual:
                lines.append(f"❤️ HP {'+' if actual > 0 else ''}{actual}")

        infection = int(effects.get("infection", 0) or 0)
        if infection:
            before = int(user.get("infection", 0))
            user["infection"] = max(0, min(100, before + infection))
            actual = user["infection"] - before
            if actual:
                lines.append(f"🦠 감염도 {'+' if actual > 0 else ''}{actual}%")

        for name, amount in effects.get("materials", {}).items():
            amount = int(amount)
            user.setdefault("materials", {})
            user["materials"][name] = user["materials"].get(name, 0) + amount
            lines.append(f"🧰 {name} +{amount}")

        for name, amount in effects.get("medical", {}).items():
            amount = int(amount)
            user.setdefault("medical_items", {})
            user["medical_items"][name] = user["medical_items"].get(name, 0) + amount
            lines.append(f"💊 {name} +{amount}")

        title = effects.get("title")
        if title:
            add_title(user, title)
            lines.append(f"🏷️ 칭호 획득: {title}")
        return lines

    @bot.hybrid_group(name="스토리", aliases=["이야기"], fallback="상태", invoke_without_command=True, description="검은 주파수 스토리를 진행하고 기록을 확인합니다.")
    async def story_group(ctx):
        if not await check_registered(ctx):
            return
        if not guild_story_enabled(ctx):
            await ctx.send("⛔ 이 서버에서는 스토리 기능이 꺼져 있습니다.")
            return
        user = get_user(ctx.author.id)
        ensure_story(user)
        await render_story(ctx, user)

    @story_group.command(name="시작")
    async def story_start(ctx):
        if not await check_registered(ctx):
            return
        if not guild_story_enabled(ctx):
            await ctx.send("⛔ 이 서버에서는 스토리 기능이 꺼져 있습니다.")
            return
        user = get_user(ctx.author.id)
        story = ensure_story(user)
        if story["completed"]:
            await ctx.send("🏁 이미 시즌 1을 완료했습니다. 다른 분기는 `!스토리 재시작`으로 진행하세요.")
            return
        if story["started"]:
            await render_story(ctx, user)
            return
        story["started"] = True
        story["node"] = STORY_START_NODE
        story["flags"] = []
        story["history"] = []
        story["ending"] = None
        save_data()
        await ctx.send("📻 **스토리 시즌 1: 검은 주파수**가 시작됩니다.")
        await render_story(ctx, user)

    @story_group.command(name="선택")
    async def story_choose(ctx, 번호: int):
        if not await check_registered(ctx):
            return
        if not guild_story_enabled(ctx):
            await ctx.send("⛔ 이 서버에서는 스토리 기능이 꺼져 있습니다.")
            return
        user = get_user(ctx.author.id)
        story = ensure_story(user)
        if not story["started"]:
            await ctx.send("⚠️ 먼저 `!스토리 시작`을 입력하세요.")
            return
        if story["completed"]:
            await ctx.send("🏁 이미 스토리를 완료했습니다. `!스토리 재시작`으로 다른 분기를 볼 수 있습니다.")
            return

        node_id = story["node"]
        node = STORY_NODES[node_id]
        choices = available_choices(story, node)
        if 번호 < 1 or 번호 > len(choices):
            await ctx.send(f"⚠️ 선택 번호는 **1~{len(choices)}** 중에서 입력하세요.")
            return

        choice = choices[번호 - 1]
        reward_key = f"v{STORY_VERSION}:{node_id}:{STORY_NODES[node_id]['choices'].index(choice)}"
        first_claim = reward_key not in story["claimed_rewards"]
        effect_lines = []
        if first_claim:
            effect_lines = apply_effects(user, choice.get("effects", {}))
            story["claimed_rewards"].append(reward_key)

        for flag in choice.get("flags", []):
            if flag not in story["flags"]:
                story["flags"].append(flag)

        story["history"].append({
            "chapter": node["chapter"],
            "title": node["title"],
            "choice": choice["text"],
        })
        story["history"] = story["history"][-30:]

        ending = choice.get("ending")
        if ending:
            story["completed"] = True
            story["ending"] = ending
            if ending["id"] not in story["endings"]:
                story["endings"].append(ending["id"])
            story["runs"] = int(story.get("runs", 0)) + 1
            save_data()
            reward_text = "\n".join(effect_lines) if effect_lines else "🔁 재플레이 선택이라 보상은 중복 지급되지 않았습니다."
            embed = discord.Embed(
                title=f"🏁 {ending['title']}",
                description=f"{choice['result']}\n\n{ending['body']}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="결과", value=reward_text, inline=False)
            embed.set_footer(text=f"발견한 엔딩 {len(story['endings'])}/3 · 다른 분기: !스토리 재시작")
            await ctx.send(embed=embed)
            return

        story["node"] = choice["next"]
        save_data()
        reward_text = "\n".join(effect_lines) if effect_lines else "🔁 재플레이 선택이라 보상 효과는 적용되지 않았습니다."
        await ctx.send(f"🎬 **선택 결과**\n{choice['result']}\n\n{reward_text}")
        await render_story(ctx, user)

    @story_group.command(name="전투")
    async def story_combat(ctx, 난이도: str = "보통"):
        if not await check_registered(ctx):
            return
        if not guild_story_enabled(ctx):
            await ctx.send("⛔ 이 서버에서는 스토리 기능이 꺼져 있습니다.")
            return
        user = get_user(ctx.author.id)
        story = ensure_story(user)
        if not story.get("started"):
            await ctx.send("⚠️ 먼저 `!스토리 시작`을 입력하세요.")
            return
        starter = getattr(bot, "v636_start_combat", None)
        if starter is None:
            await ctx.send("⚠️ 전술 전투 모듈이 아직 준비되지 않았습니다.")
            return
        await starter(ctx, "스토리", 난이도)

    @story_group.command(name="기록")
    async def story_history(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        story = ensure_story(user)
        if not story["history"]:
            await ctx.send("📜 아직 스토리 선택 기록이 없습니다. `!스토리 시작`으로 시작하세요.")
            return
        lines = ["📜 **[현재 회차 선택 기록]**"]
        for index, record in enumerate(story["history"], start=1):
            lines.append(f"{index}. **{record['chapter']} {record['title']}** — {record['choice']}")
        ending_names = {
            "dawn_broadcaster": "새벽의 송신자",
            "signal_breaker": "검은 신호 파괴자",
            "abaddon_heir": "아바돈의 대리인",
        }
        found = [ending_names[eid] for eid in story["endings"] if eid in ending_names]
        lines.append("\n🏁 발견 엔딩: " + (", ".join(found) if found else "없음"))
        await ctx.send("\n".join(lines))

    @story_group.command(name="재시작")
    async def story_restart(ctx):
        if not await check_registered(ctx):
            return
        if not guild_story_enabled(ctx):
            await ctx.send("⛔ 이 서버에서는 스토리 기능이 꺼져 있습니다.")
            return
        user = get_user(ctx.author.id)
        story = ensure_story(user)
        if not story["completed"]:
            await ctx.send("⚠️ 현재 회차가 진행 중입니다. 엔딩을 본 뒤 재시작할 수 있습니다.")
            return
        story["started"] = True
        story["completed"] = False
        story["node"] = STORY_START_NODE
        story["flags"] = []
        story["history"] = []
        story["ending"] = None
        save_data()
        await ctx.send(
            "🔄 스토리 시즌 1을 다시 시작합니다.\n"
            "선택 보상은 최초 한 번만 지급되지만 다른 선택과 엔딩은 정상적으로 기록됩니다."
        )
        await render_story(ctx, user)
