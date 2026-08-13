from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import discord
from discord.ext import commands

from apocalypse_bot.commands.story_progression import (
    can_access_season, is_story_admin, locked_text, season_display_status, season_state,
)

VERSION = "7.5.1"
START_NODE = "t1_red_signal"


def _choice(
    text: str,
    result: str,
    next_node: Optional[str] = None,
    *,
    effects: Optional[Dict[str, Any]] = None,
    flags: Optional[Sequence[str]] = None,
    requires_any: Optional[Sequence[str]] = None,
    requires_all: Optional[Sequence[str]] = None,
    ending: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "text": text,
        "result": result,
        "next": next_node,
        "effects": dict(effects or {}),
        "flags": list(flags or []),
        "requires_any": list(requires_any or []),
        "requires_all": list(requires_all or []),
        "ending": ending,
    }


NODES: Dict[str, Dict[str, Any]] = {
    "t1_red_signal": {
        "chapter": "프롤로그",
        "title": "붉은 철로의 호출",
        "location": "도시 외곽 · 폐쇄된 중앙역",
        "body": (
            "백색 방주의 신호가 잠잠해진 뒤, 폐선된 철로에서 존재하지 않아야 할 열차가 들어온다. "
            "차체에는 ‘황혼선 04’가 새겨져 있고, 객실마다 다른 구조 신호가 반복된다.\n\n"
            "기관실은 운행 권한을 요구하고, 승강장에는 피난민이 남아 있으며, 봉인 객차에서는 시즌 1의 검은 주파수가 새어 나온다."
        ),
        "choices": [
            _choice(
                "승강장에 남은 피난민부터 열차에 태운다.",
                "문이 닫히기 직전 마지막 가족까지 객실로 끌어올렸다. 열차는 무거워졌지만 사람들의 신뢰를 얻었다.",
                "t2_passengers",
                effects={"food": 450},
                flags=["saved_platform", "passenger_trust"],
            ),
            _choice(
                "기관실에 들어가 운행 권한과 동력 상태를 확보한다.",
                "기관실 단말기가 당신을 임시 기관장으로 등록했다. 남은 연료로 갈 수 있는 노선은 단 하나다.",
                "t2_engine",
                effects={"materials": {"전자부품": 2}},
                flags=["engine_access", "temporary_conductor"],
            ),
            _choice(
                "봉인 객차를 열어 검은 주파수의 정체를 조사한다.",
                "봉인 객차에는 도시 밖의 철도망과 생존 거점이 표시된 오래된 노선도가 숨겨져 있었다.",
                "t2_archive",
                effects={"food": 250, "materials": {"고철": 2}},
                flags=["opened_archive", "unknown_route"],
            ),
        ],
    },
    "t2_passengers": {
        "chapter": "제1장",
        "title": "좌석이 부족한 밤",
        "location": "황혼선 04 · 피난 객실",
        "body": (
            "객실 정원보다 많은 사람이 탑승했다. 식량은 사흘치뿐이고, 앞쪽 객차에서는 무장 경비대가 어린 승객을 내리라고 요구한다. "
            "열차 방송은 ‘효율적인 생존자 선별’을 반복한다."
        ),
        "choices": [
            _choice(
                "식량을 균등 배급하고 모두를 끝까지 태운다.",
                "배급량은 줄었지만 객실의 불안은 가라앉았다. 승객들이 자발적으로 경비와 정비를 맡기 시작했다.",
                "t3_border",
                effects={"food": -300},
                flags=["shared_rations", "passenger_union"],
            ),
            _choice(
                "경비대와 협상해 위험 인원을 별도 객차로 옮긴다.",
                "충돌은 피했지만 열차 안에는 보이지 않는 경계선이 생겼다. 경비대장은 기관실 암호 일부를 넘겼다.",
                "t3_border",
                effects={"food": 350},
                flags=["security_deal", "engine_code"],
            ),
            _choice(
                "열차 방송 장치를 끄고 승객 투표로 규칙을 정한다.",
                "처음으로 열차 안의 명령이 기계가 아닌 사람들의 목소리로 결정됐다.",
                "t3_border",
                effects={"food": 200},
                flags=["passenger_vote", "human_rules"],
            ),
        ],
    },
    "t2_engine": {
        "chapter": "제1장",
        "title": "심장을 태우는 연료",
        "location": "황혼선 04 · 기관실",
        "body": (
            "기관차의 핵심로는 에너지코어를 태우며 움직인다. 정상 노선은 붕괴했고, 긴급 우회선은 방사능 지대를 통과한다. "
            "자동 기관장 아바돈은 승객 일부를 동력원에서 분리하면 속도를 높일 수 있다고 계산한다."
        ),
        "choices": [
            _choice(
                "속도를 포기하고 안전 출력을 유지한다.",
                "열차는 느려졌지만 핵심로가 안정됐다. 정비 기록에서 최종 분기기의 제어키를 찾았다.",
                "t3_border",
                effects={"materials": {"전자부품": 2}},
                flags=["safe_output", "switch_key"],
            ),
            _choice(
                "비상 축전지를 과부하시켜 붕괴 구간을 돌파한다.",
                "차체가 불꽃을 뿜으며 끊어진 교량을 넘어섰다. 대신 핵심로의 남은 수명이 크게 줄었다.",
                "t3_border",
                effects={"food": 700},
                flags=["overdrive", "damaged_core"],
            ),
            _choice(
                "아바돈의 기관장 권한을 복제해 직접 운행을 장악한다.",
                "모든 제어등이 당신의 명령을 기다린다. 열차는 이제 피난 수단이면서 하나의 움직이는 도시가 됐다.",
                "t3_border",
                effects={"materials": {"전자부품": 3}},
                flags=["copied_conductor", "full_control"],
            ),
        ],
    },
    "t2_archive": {
        "chapter": "제1장",
        "title": "지도에 없는 네 번째 노선",
        "location": "황혼선 04 · 봉인 기록 객차",
        "body": (
            "노선도에는 세 개의 알려진 종착역 외에 검은 잉크로 지워진 네 번째 역이 있다. 기록 장치는 그곳을 ‘도시 외부 생존권’이라고 부르지만, "
            "마지막 운행 기록은 모두 귀환하지 못한 것으로 끝난다."
        ),
        "choices": [
            _choice(
                "지워진 노선 전체를 복원한다.",
                "신호 조각을 이어 붙이자 산맥 너머의 생존 거점과 연결된 좌표가 나타났다.",
                "t3_border",
                effects={"materials": {"전자부품": 3}},
                flags=["restored_route", "beyond_map"],
            ),
            _choice(
                "과거 승객 명단을 공개해 실종자의 진실을 알린다.",
                "열차가 이전에도 사람을 선별해 버렸다는 사실이 드러났다. 승객들은 더 이상 자동 방송을 믿지 않는다.",
                "t3_border",
                effects={"food": 400},
                flags=["revealed_manifest", "passenger_trust"],
            ),
            _choice(
                "기록을 숨기고 네 번째 노선을 혼자 확보한다.",
                "비밀 노선은 당신만 아는 탈출구가 됐다. 하지만 객실의 불안은 더 짙어졌다.",
                "t3_border",
                effects={"food": 800},
                flags=["secret_route", "unknown_route"],
            ),
        ],
    },
    "t3_border": {
        "chapter": "제2장",
        "title": "국경 없는 검문소",
        "location": "외곽 철도 검문구역",
        "body": (
            "철로를 막은 생존 연합이 열차 정지를 요구한다. 그들은 황혼선이 감염자를 끌어들이는 이동형 송신기라고 주장한다. "
            "뒤에서는 오염 폭풍이 다가오고, 멈출 수 있는 시간은 짧다."
        ),
        "choices": [
            _choice(
                "승객 대표와 함께 내려 공동 검사를 허용한다.",
                "검사 결과 송신기는 사실이었지만, 승객들의 협조로 안전하게 분리할 수 있었다.",
                "t4_last_switch",
                effects={"food": 500},
                flags=["shared_inspection", "removed_beacon"],
                requires_any=["passenger_trust", "passenger_union", "passenger_vote"],
            ),
            _choice(
                "기관 권한으로 차단기를 무시하고 검문소를 돌파한다.",
                "차단벽은 무너졌지만 생존 연합은 황혼선을 적으로 선언했다.",
                "t4_last_switch",
                effects={"food": 900},
                flags=["broke_checkpoint", "iron_route"],
                requires_any=["engine_access", "engine_code", "full_control", "switch_key"],
            ),
            _choice(
                "네 번째 노선의 좌표를 제시해 공동 탈출을 제안한다.",
                "연합은 위험을 감수하고 열차에 합류했다. 지도 밖의 선로가 처음으로 여러 사람의 선택지가 됐다.",
                "t4_last_switch",
                effects={"food": 650},
                flags=["allied_union", "open_unknown_route"],
                requires_any=["restored_route", "beyond_map", "unknown_route"],
            ),
            _choice(
                "송신기를 과부하시켜 오염 폭풍을 다른 방향으로 유도한다.",
                "폭풍은 비껴갔지만 황혼선의 통신 장비가 거의 모두 타버렸다.",
                "t4_last_switch",
                effects={"materials": {"고철": 3}},
                flags=["redirected_storm", "silent_train"],
            ),
        ],
    },
    "t4_last_switch": {
        "chapter": "최종장",
        "title": "황혼의 종착역",
        "location": "최종 분기기 · 04번 선로",
        "body": (
            "분기기 앞에서 네 개의 노선이 갈라진다. 첫 번째는 생존 연합의 불빛으로, 두 번째는 통제 가능한 요새 도시로, "
            "세 번째는 안전하지만 끝없이 순환하는 지하선으로, 네 번째는 지도 밖의 미지로 이어진다.\n\n"
            "황혼선은 단 한 번만 방향을 바꿀 수 있다."
        ),
        "choices": [
            _choice(
                "모든 승객과 연합을 마지막 역의 불빛으로 인도한다.",
                "황혼선이 멈추자 플랫폼의 불빛이 하나씩 켜졌다. 열차는 더 이상 도망치는 수단이 아니라 새로운 정착지의 첫 벽이 됐다.",
                effects={"food": 8000, "title": "마지막 역의 인도자"},
                requires_any=["shared_inspection", "allied_union", "human_rules", "passenger_union"],
                ending={
                    "id": "last_station_dawn",
                    "title": "엔딩 A · 마지막 역의 불빛",
                    "body": "당신은 가장 빠른 길이 아니라 가장 많은 사람이 함께 도착할 수 있는 길을 선택했다.",
                },
            ),
            _choice(
                "기관장 권한으로 요새 도시와 황혼선을 모두 장악한다.",
                "철로와 성벽의 모든 신호가 당신에게 복종했다. 움직이는 도시와 멈춘 도시가 하나의 지휘망으로 연결됐다.",
                effects={"food": 10000, "title": "철로 위의 지휘관", "materials": {"에너지코어": 1}},
                requires_any=["full_control", "copied_conductor", "iron_route", "temporary_conductor"],
                ending={
                    "id": "iron_conductor",
                    "title": "엔딩 B · 철로 위의 왕",
                    "body": "당신은 황혼선을 구하지 않았다. 황혼선이 멈출 곳과 움직일 사람을 결정하는 존재가 됐다.",
                },
            ),
            _choice(
                "지하 순환선으로 들어가 외부 위험을 영원히 차단한다.",
                "열차는 안전한 어둠 속을 계속 달린다. 누구도 죽지 않았지만 누구도 종착역에 도착하지 못했다.",
                effects={"food": 6500, "title": "끝없는 순환의 승객"},
                ending={
                    "id": "eternal_loop",
                    "title": "엔딩 C · 끝없는 순환",
                    "body": "완전한 안전은 정지와 다르지 않았다. 황혼선은 살아남았지만 미래를 잃었다.",
                },
            ),
            _choice(
                "네 번째 노선을 열어 지도 밖의 세계로 출발한다.",
                "분기기가 비명을 지르며 처음 사용되는 선로를 열었다. 새벽빛이 산맥 너머에서 철로 위로 번졌다.",
                effects={"food": 9000, "title": "지도 밖의 개척자", "materials": {"전자부품": 3}},
                requires_any=["beyond_map", "open_unknown_route", "restored_route", "secret_route"],
                ending={
                    "id": "beyond_the_map",
                    "title": "엔딩 D · 지도 밖의 새벽",
                    "body": "도시의 모든 결말을 뒤로하고, 당신은 아직 누구도 이름 붙이지 않은 세계를 선택했다.",
                },
            ),
        ],
    },
}

ENDING_NAMES = {
    "last_station_dawn": "마지막 역의 불빛",
    "iron_conductor": "철로 위의 왕",
    "eternal_loop": "끝없는 순환",
    "beyond_the_map": "지도 밖의 새벽",
}


def _default_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "started": False,
        "completed": False,
        "node": START_NODE,
        "flags": [],
        "history": [],
        "ending": None,
        "endings": [],
        "claimed_rewards": [],
        "legacy_claims": [],
        "runs": 0,
    }


def ensure_v730(user: Dict[str, Any]) -> Dict[str, Any]:
    root = user.setdefault("v730", {})
    if not isinstance(root, dict):
        root = {}
        user["v730"] = root
    state = root.setdefault("season4", _default_state())
    if not isinstance(state, dict):
        state = _default_state()
        root["season4"] = state
    for key, value in _default_state().items():
        if key not in state:
            state[key] = list(value) if isinstance(value, list) else value
    for key in ("flags", "history", "endings", "claimed_rewards", "legacy_claims"):
        if not isinstance(state.get(key), list):
            state[key] = []
    if state.get("node") not in NODES:
        state["node"] = START_NODE
        state["completed"] = False
    state["runs"] = max(0, int(state.get("runs", 0) or 0))
    return root


def _legacy_flags(user: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    story1 = user.get("story") if isinstance(user.get("story"), dict) else {}
    if story1.get("completed"):
        flags.append("season1_completed")
    season2 = ((user.get("v430") or {}).get("season2") if isinstance(user.get("v430"), dict) else {}) or {}
    if isinstance(season2, dict) and season2.get("completed"):
        flags.append("season2_completed")
    season3 = ((user.get("v600") or {}).get("season3") if isinstance(user.get("v600"), dict) else {}) or {}
    if isinstance(season3, dict) and season3.get("completed"):
        flags.append("season3_completed")
    for source in (story1, season2, season3):
        ending = source.get("ending") if isinstance(source, dict) else None
        if isinstance(ending, dict) and ending.get("id"):
            flags.append(str(ending["id"]))
    return list(dict.fromkeys(flags))


def _available(state: Mapping[str, Any], node: Mapping[str, Any]) -> List[Dict[str, Any]]:
    flags = set(str(item) for item in state.get("flags", []))
    rows: List[Dict[str, Any]] = []
    for choice in node.get("choices", []):
        any_req = set(str(item) for item in choice.get("requires_any", []))
        all_req = set(str(item) for item in choice.get("requires_all", []))
        if any_req and not flags.intersection(any_req):
            continue
        if all_req and not all_req.issubset(flags):
            continue
        rows.append(choice)
    return rows


def _apply_effects(
    user: Dict[str, Any],
    effects: Mapping[str, Any],
    add_title: Callable[[Dict[str, Any], str], Any],
) -> List[str]:
    lines: List[str] = []
    food = int(effects.get("food", 0) or 0)
    if food:
        before = max(0, int(user.get("balance", 0) or 0))
        user["balance"] = max(0, before + food)
        actual = user["balance"] - before
        if actual > 0:
            stats = user.setdefault("stats", {})
            stats["earned"] = int(stats.get("earned", 0) or 0) + actual
        lines.append(f"🥫 식량 {actual:+,}")
    materials = user.setdefault("materials", {})
    for name, amount_raw in (effects.get("materials") or {}).items():
        amount = int(amount_raw or 0)
        before = max(0, int(materials.get(name, 0) or 0))
        materials[name] = max(0, before + amount)
        actual = materials[name] - before
        if actual:
            lines.append(f"🧰 {name} {actual:+,}")
    title = effects.get("title")
    if title:
        add_title(user, str(title))
        lines.append(f"🏷️ 칭호 획득: {title}")
    return lines


class Season4ChoiceSelect(discord.ui.Select):
    def __init__(self, owner_id: int, callback: Callable[[discord.Interaction, int], Any], choices: Sequence[Mapping[str, Any]]) -> None:
        self.owner_id = int(owner_id)
        self.choice_callback = callback
        options = [
            discord.SelectOption(
                label=f"{index}. {str(choice['text'])[:80]}",
                value=str(index),
                emoji=("🚂", "🧭", "📡", "🌅")[min(index - 1, 3)],
            )
            for index, choice in enumerate(choices, start=1)
        ]
        super().__init__(placeholder="황혼선의 다음 선택을 고르세요", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("이 선택지는 해당 생존자의 이야기입니다.", ephemeral=True)
            return
        await self.choice_callback(interaction, int(self.values[0]))


class Season4ChoiceView(discord.ui.View):
    def __init__(self, owner_id: int, callback: Callable[[discord.Interaction, int], Any], choices: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(timeout=300)
        self.add_item(Season4ChoiceSelect(owner_id, callback, choices))


def register_v730_season_story(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    guide: List[Dict[str, Any]],
    add_title: Callable[[Dict[str, Any], str], Any],
    add_season_points: Callable[[Dict[str, Any], int], Any],
) -> None:
    if getattr(bot, "_abaddon_v730_registered", False):
        return

    story_category = next((category for category in guide if category.get("id") in {"story", "story_season"}), None)
    if story_category is not None:
        existing = "\n".join(str(row) for row in story_category.get("commands", []))
        for row in (
            "!시즌4 — 황혼의 종착역 현재 장면과 선택지",
            "!시즌4 시작 / 선택 번호 / 기록 / 재시작 — 시즌 4 진행",
            "!시즌여정 — 시즌 1~4 완료와 엔딩 수집 현황",
            "!시즌유산 — 시즌 4 엔딩 수집 단계 보상",
        ):
            if row.split()[0] not in existing:
                story_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    async def require_season4_access(ctx: commands.Context, user: Dict[str, Any]) -> bool:
        allowed, _reason = await can_access_season(ctx, bot, user, 4)
        if allowed:
            return True
        await ctx.send(locked_text(4))
        return False

    async def render_to(send: Callable[..., Any], owner_id: int, user: Dict[str, Any]) -> None:
        state = ensure_v730(user)["season4"]
        if not state["started"]:
            embed = discord.Embed(
                title="🚂 스토리 시즌 4 · 황혼의 종착역",
                description=(
                    "도시 밖으로 이어지는 마지막 열차 ‘황혼선 04’에 탑승하는 선택형 캠페인입니다.\n"
                    "시즌 3 엔딩을 1회 완료하면 해금됩니다. 서버 관리자와 봇 소유자는 점검을 위해 잠금을 우회할 수 있습니다."
                ),
                colour=discord.Colour.from_rgb(212, 85, 67),
            )
            embed.add_field(name="시작", value="`!시즌4 시작`", inline=True)
            embed.add_field(name="엔딩", value="4종", inline=True)
            embed.add_field(name="유산", value="`!시즌유산`", inline=True)
            await send(embed=embed)
            return
        if state["completed"]:
            ending = state.get("ending") if isinstance(state.get("ending"), dict) else {}
            embed = discord.Embed(
                title="🏁 시즌 4 완료",
                description=ending.get("body", "황혼선의 운행 기록이 끝났습니다."),
                colour=discord.Colour.gold(),
            )
            embed.add_field(name="마지막 엔딩", value=ending.get("title", "기록 없음"), inline=False)
            embed.add_field(name="수집", value=f"{len(state['endings'])}/4 · 완료 {state['runs']}회", inline=False)
            embed.set_footer(text="다른 분기: !시즌4 재시작 · 수집 보상: !시즌유산")
            await send(embed=embed)
            return
        node = NODES[state["node"]]
        choices = _available(state, node)
        embed = discord.Embed(
            title=f"🚂 {node['chapter']} · {node['title']}",
            description=node["body"],
            colour=discord.Colour.from_rgb(212, 85, 67),
        )
        embed.add_field(name="📍 위치", value=node["location"], inline=False)
        embed.add_field(
            name="🧭 선택",
            value="\n".join(f"**{idx}.** {choice['text']}" for idx, choice in enumerate(choices, start=1)) or "현재 열 수 있는 선택지가 없습니다.",
            inline=False,
        )
        embed.set_footer(text="드롭다운 또는 !시즌4 선택 번호")

        expected_node = str(state["node"])

        async def interaction_choose(interaction: discord.Interaction, number: int) -> None:
            # 이전 장면의 선택 메뉴를 즉시 닫아 중복 클릭과 장면 엇갈림을 막습니다.
            if not interaction.response.is_done():
                await interaction.response.defer()
            if interaction.message is not None:
                try:
                    await interaction.message.edit(view=None)
                except discord.HTTPException:
                    pass
            await apply_choice(interaction.user.id, number, interaction=interaction, expected_node=expected_node)

        view = Season4ChoiceView(owner_id, interaction_choose, choices) if choices else None
        await send(embed=embed, view=view)

    async def apply_choice(
        user_id: int,
        number: int,
        *,
        ctx: Optional[commands.Context] = None,
        interaction: Optional[discord.Interaction] = None,
        expected_node: Optional[str] = None,
    ) -> None:
        user = get_user(user_id)
        state = ensure_v730(user)["season4"]
        async def reply(*args: Any, **kwargs: Any) -> Any:
            if interaction is not None:
                if interaction.response.is_done():
                    return await interaction.followup.send(*args, **kwargs)
                return await interaction.response.send_message(*args, **kwargs)
            assert ctx is not None
            return await ctx.send(*args, **kwargs)

        if not state["started"]:
            await reply("⚠️ 먼저 `!시즌4 시작`을 사용해주세요.", ephemeral=interaction is not None)
            return
        if state["completed"]:
            await reply("🏁 이미 완료했습니다. `!시즌4 재시작`으로 다른 분기를 진행하세요.", ephemeral=interaction is not None)
            return
        if expected_node is not None and str(state.get("node")) != str(expected_node):
            await reply("⏭️ 이미 다음 장면으로 이동했습니다. 최신 시즌 4 화면에서 선택해주세요.", ephemeral=True)
            return
        node_id = state["node"]
        node = NODES[node_id]
        choices = _available(state, node)
        if number < 1 or number > len(choices):
            await reply(f"선택 번호는 1~{len(choices)}입니다.", ephemeral=interaction is not None)
            return
        choice = choices[number - 1]
        original_index = node["choices"].index(choice)
        reward_key = f"v730:{node_id}:{original_index}"
        effect_lines: List[str] = []
        if reward_key not in state["claimed_rewards"]:
            effect_lines = _apply_effects(user, choice.get("effects", {}), add_title)
            state["claimed_rewards"].append(reward_key)
        for flag in choice.get("flags", []):
            if flag not in state["flags"]:
                state["flags"].append(flag)
        state["history"].append({"chapter": node["chapter"], "title": node["title"], "choice": choice["text"]})
        state["history"] = state["history"][-40:]
        ending = choice.get("ending")
        if ending:
            state["completed"] = True
            state["ending"] = ending
            if ending["id"] not in state["endings"]:
                state["endings"].append(ending["id"])
            state["runs"] = int(state.get("runs", 0) or 0) + 1
            add_season_points(user, 25)
            save_data()
            embed = discord.Embed(
                title=f"🏁 {ending['title']}",
                description=f"{choice['result']}\n\n{ending['body']}",
                colour=discord.Colour.gold(),
            )
            embed.add_field(name="🎁 결과", value="\n".join(effect_lines) or "재플레이 선택이라 보상은 중복 지급되지 않았습니다.", inline=False)
            embed.add_field(name="🎖️ 시즌 포인트", value="+25P", inline=False)
            embed.set_footer(text=f"엔딩 수집 {len(state['endings'])}/4 · !시즌유산")
            await reply(embed=embed)
            return
        state["node"] = choice["next"]
        save_data()
        await reply(f"🎬 **선택 결과**\n{choice['result']}\n\n" + ("\n".join(effect_lines) or "🔁 이미 받은 선택 보상입니다."))
        if ctx is not None:
            await render_to(ctx.send, user_id, user)
        elif interaction is not None:
            await render_to(interaction.followup.send, user_id, user)

    @bot.group(name="시즌4", aliases=["황혼의종착역", "황혼선"], invoke_without_command=True)
    async def season4(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season4_access(ctx, user):
            return
        await render_to(ctx.send, ctx.author.id, user)

    @season4.command(name="시작")
    async def season4_start(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season4_access(ctx, user):
            return
        state = ensure_v730(user)["season4"]
        if state["completed"]:
            await ctx.send("🏁 이미 완료했습니다. `!시즌4 재시작`으로 다른 엔딩을 찾아보세요.")
            return
        if not state["started"]:
            state["started"] = True
            state["node"] = START_NODE
            state["flags"] = _legacy_flags(user)
            state["history"] = []
            state["ending"] = None
            save_data()
            await ctx.send("🚂 **스토리 시즌 4: 황혼의 종착역**이 시작됩니다.")
        await render_to(ctx.send, ctx.author.id, user)

    @season4.command(name="선택")
    async def season4_choose(ctx: commands.Context, 번호: int) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season4_access(ctx, user):
            return
        await apply_choice(ctx.author.id, 번호, ctx=ctx)

    @season4.command(name="기록")
    async def season4_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season4_access(ctx, user):
            return
        state = ensure_v730(user)["season4"]
        if not state["history"]:
            await ctx.send("📜 아직 선택 기록이 없습니다. `!시즌4 시작`으로 시작하세요.")
            return
        rows = ["🚂 **[황혼의 종착역 선택 기록]**"]
        rows.extend(f"{idx}. **{row['chapter']} {row['title']}** — {row['choice']}" for idx, row in enumerate(state["history"], start=1))
        found = [ENDING_NAMES[item] for item in state["endings"] if item in ENDING_NAMES]
        rows.append("\n🏁 발견 엔딩: " + (", ".join(found) if found else "없음"))
        await ctx.send("\n".join(rows))

    @season4.command(name="재시작")
    async def season4_restart(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season4_access(ctx, user):
            return
        state = ensure_v730(user)["season4"]
        if not state["started"]:
            await ctx.send("먼저 `!시즌4 시작`을 사용해주세요.")
            return
        keep_endings = list(state["endings"])
        keep_rewards = list(state["claimed_rewards"])
        keep_legacy = list(state["legacy_claims"])
        runs = int(state.get("runs", 0) or 0)
        state.clear()
        state.update(_default_state())
        state["started"] = True
        state["flags"] = _legacy_flags(user)
        state["endings"] = keep_endings
        state["claimed_rewards"] = keep_rewards
        state["legacy_claims"] = keep_legacy
        state["runs"] = runs
        save_data()
        await ctx.send("🔄 시즌 4를 다시 시작합니다. 엔딩 수집과 이미 받은 선택 보상은 유지됩니다.")
        await render_to(ctx.send, ctx.author.id, user)

    @bot.command(name="시즌여정", aliases=["스토리여정", "시즌현황", "스토리해금"], help="스토리 시즌 1~4 완료·잠금·엔딩 수집 현황을 확인합니다.")
    async def season_journey(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        admin = await is_story_admin(ctx, bot)

        def row(season: int, name: str, state: Mapping[str, Any], total: int) -> str:
            mark = season_display_status(user, season, admin=admin)
            endings = len(state.get("endings", [])) if isinstance(state.get("endings"), list) else (1 if state.get("ending") else 0)
            suffix = " · 관리자 우회 가능" if mark == "🛡️" else ""
            return f"{mark} **시즌 {season} · {name}** · 엔딩 {endings}/{total}{suffix}"

        s1 = season_state(user, 1)
        s2 = season_state(user, 2)
        s3 = season_state(user, 3)
        s4 = ensure_v730(user)["season4"]
        embed = discord.Embed(
            title="📚 아바돈 스토리 순차 해금",
            description="시즌을 1회 완료하면 다음 시즌이 열립니다. 기존에 시작한 후속 시즌은 진행이 보존됩니다.",
            colour=discord.Colour.from_rgb(212, 85, 67),
        )
        embed.add_field(
            name="진행",
            value="\n".join([
                row(1, "검은 주파수", s1, 3),
                row(2, "백색 방주", s2, 4),
                row(3, "종말의 왕좌", s3, 4),
                row(4, "황혼의 종착역", s4, 4),
            ]),
            inline=False,
        )
        embed.add_field(
            name="해금 순서",
            value="📡 시즌 1 완료 → ⚪ 시즌 2 → 👑 시즌 3 → 🚂 시즌 4",
            inline=False,
        )
        if admin:
            embed.add_field(name="🛡️ 관리자 점검 권한", value="이 계정은 모든 시즌 잠금을 우회하여 실행할 수 있습니다.", inline=False)
        embed.set_footer(text="시즌 4 엔딩 수집 보상: !시즌유산")
        await ctx.send(embed=embed)

    @bot.command(name="시즌유산", aliases=["황혼유산", "시즌4보상"], help="시즌 4 엔딩 수집 단계 보상을 확인하고 받습니다.")
    async def season_legacy(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season4_access(ctx, user):
            return
        state = ensure_v730(user)["season4"]
        count = len(state["endings"])
        claims = state["legacy_claims"]
        rewards = {
            1: ("🥫 식량 2,000", lambda: _apply_effects(user, {"food": 2000}, add_title)),
            2: ("🧰 에너지코어 1 · 🎖️ 시즌 5P", lambda: (_apply_effects(user, {"materials": {"에너지코어": 1}}, add_title), add_season_points(user, 5))),
            3: ("🥫 식량 6,000 · 🏷️ 황혼의 승객", lambda: _apply_effects(user, {"food": 6000, "title": "황혼의 승객"}, add_title)),
            4: ("🥫 식량 12,000 · 🎖️ 시즌 10P · 🏷️ 종말선의 기록자", lambda: (_apply_effects(user, {"food": 12000, "title": "종말선의 기록자"}, add_title), add_season_points(user, 10))),
        }
        received: List[str] = []
        for threshold, (label, grant) in rewards.items():
            if count >= threshold and threshold not in claims:
                grant()
                claims.append(threshold)
                received.append(f"🎁 {threshold}종: {label}")
        if received:
            save_data()
        rows = []
        for threshold, (label, _grant) in rewards.items():
            status = "✅ 수령" if threshold in claims else ("🎁 수령 가능" if count >= threshold else "🔒 잠김")
            rows.append(f"{status} · 엔딩 {threshold}종 · {label}")
        embed = discord.Embed(title="🏺 시즌 4 유산 보상", description=f"현재 엔딩 수집 **{count}/4**", colour=discord.Colour.gold())
        embed.add_field(name="진행", value="\n".join(rows), inline=False)
        if received:
            embed.add_field(name="이번 수령", value="\n".join(received), inline=False)
        await ctx.send(embed=embed)

    bot._abaddon_v730_registered = True  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] 시즌 4 황혼의 종착역·시즌 유산 등록 완료", flush=True)
