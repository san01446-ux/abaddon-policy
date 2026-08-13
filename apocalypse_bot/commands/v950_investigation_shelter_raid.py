from __future__ import annotations

import asyncio
import copy
import hashlib
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v900_faction_world_state import (
    _bar,
    _give,
    _is_admin,
    _metric_delta,
    _guild as _world_state,
    _now,
    _owned,
    _safe_int,
    _take,
)
from apocalypse_bot.commands.v920_world_cycle_professions import _lock, _party_of

VERSION = "9.5.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
INVESTIGATION_STAMINA = 8
RAID_ACTION_COOLDOWN = 8 * 60

CASE_TEMPLATES: Mapping[str, Dict[str, Any]] = {
    "white_lantern": {
        "title": "백색등이 꺼진 밤",
        "emoji": "🚑",
        "summary": "구조대의 야간 이동 기록과 사라진 의료 상자를 추적합니다.",
        "suspects": ("위조 구조대원", "암시장 운반책", "오작동 관제기"),
        "answer": "암시장 운반책",
        "clues": {
            "찢어진 구조대 완장": "field",
            "오염된 보급 명세서": "record",
            "암시장 통행 표식": "witness",
            "차축에 남은 검은 분진": "field",
        },
        "links": (
            frozenset(("찢어진 구조대 완장", "암시장 통행 표식")),
            frozenset(("오염된 보급 명세서", "차축에 남은 검은 분진")),
        ),
        "effects": {"stability": 3, "morale": 2},
    },
    "silent_radio": {
        "title": "침묵한 17번 주파수",
        "emoji": "📡",
        "summary": "구조 요청을 가장한 반복 신호의 발신지를 조사합니다.",
        "suspects": ("실종 정찰대", "심연 감염 숭배자", "자동 송신기"),
        "answer": "심연 감염 숭배자",
        "clues": {
            "반복되는 구조 호출": "record",
            "혈흔 묻은 주파수표": "field",
            "뒤집힌 세력 표식": "witness",
            "변조된 송신 코어": "record",
        },
        "links": (
            frozenset(("반복되는 구조 호출", "변조된 송신 코어")),
            frozenset(("혈흔 묻은 주파수표", "뒤집힌 세력 표식")),
        ),
        "effects": {"stability": 2, "contamination": -2},
    },
    "poisoned_well": {
        "title": "정화소의 검은 물",
        "emoji": "💧",
        "summary": "정화 완료 판정을 받은 저장수에서 다시 오염이 발견됐습니다.",
        "suspects": ("부패한 검사관", "균열된 배관", "감염체 둥지"),
        "answer": "부패한 검사관",
        "clues": {
            "위조된 수질 검사표": "record",
            "잠긴 정화 밸브": "field",
            "검사관의 비밀 장부": "witness",
            "오염된 봉인 왁스": "field",
        },
        "links": (
            frozenset(("위조된 수질 검사표", "검사관의 비밀 장부")),
            frozenset(("잠긴 정화 밸브", "오염된 봉인 왁스")),
        ),
        "effects": {"contamination": -5, "morale": 1},
    },
    "ghost_convoy": {
        "title": "지도에 없는 보급차",
        "emoji": "🚚",
        "summary": "폐쇄된 노선을 달리는 정체불명의 보급차를 추적합니다.",
        "suspects": ("보급 호위대 이탈자", "고철왕의 기계 군단", "밀수 중개상"),
        "answer": "고철왕의 기계 군단",
        "clues": {
            "사람이 없는 운전석": "field",
            "기계식 운행 명령서": "record",
            "긁혀 지워진 차량 번호": "witness",
            "과열된 제어 회로": "field",
        },
        "links": (
            frozenset(("사람이 없는 운전석", "기계식 운행 명령서")),
            frozenset(("긁혀 지워진 차량 번호", "과열된 제어 회로")),
        ),
        "effects": {"supply": 4, "stability": 1},
    },
    "false_flag": {
        "title": "두 개의 민병대 표식",
        "emoji": "🛡️",
        "summary": "민병대 표식을 단 습격자들이 피난 행렬을 공격했습니다.",
        "suspects": ("푸른 방패 민병대", "붉은 송곳니 약탈단", "공포에 빠진 주민"),
        "answer": "붉은 송곳니 약탈단",
        "clues": {
            "좌우가 뒤집힌 방패 문양": "field",
            "약탈단식 탄약 묶음": "record",
            "생존자의 엇갈린 증언": "witness",
            "붉은 섬유 조각": "field",
        },
        "links": (
            frozenset(("좌우가 뒤집힌 방패 문양", "붉은 섬유 조각")),
            frozenset(("약탈단식 탄약 묶음", "생존자의 엇갈린 증언")),
        ),
        "effects": {"stability": 4, "morale": 3},
    },
    "buried_archive": {
        "title": "매몰된 기록 보관소",
        "emoji": "🗄️",
        "summary": "붕괴 직전 봉인된 기록실에서 조작된 대피 명단이 발견됐습니다.",
        "suspects": ("옛 지휘관", "기록 관리 드론", "검은 먼지 밀수조직"),
        "answer": "검은 먼지 밀수조직",
        "clues": {
            "삭제된 대피자 명단": "record",
            "밀수품 봉인 도장": "field",
            "기록관의 마지막 음성": "witness",
            "숨겨진 지하 통로 지도": "field",
        },
        "links": (
            frozenset(("삭제된 대피자 명단", "기록관의 마지막 음성")),
            frozenset(("밀수품 봉인 도장", "숨겨진 지하 통로 지도")),
        ),
        "effects": {"supply": 2, "stability": 2, "morale": 1},
    },
}

BOUNTIES: Mapping[str, Dict[str, Any]] = {
    "red_fang": {"name": "붉은 송곳니 추적대장", "emoji": "🐺", "target": 500, "reward": 40000, "trophy": "붉은 송곳니 휘장"},
    "scrap_drone": {"name": "고철왕 정찰 드론", "emoji": "🤖", "target": 430, "reward": 34000, "trophy": "파손된 기계 눈"},
    "smuggler": {"name": "검은 먼지 밀수책", "emoji": "🕶️", "target": 470, "reward": 37000, "trophy": "암호화된 거래패"},
    "mutant": {"name": "협곡의 유리갑각 변이체", "emoji": "🦂", "target": 560, "reward": 45000, "trophy": "유리갑각 표본"},
    "cultist": {"name": "심연 신호 전도자", "emoji": "🕯️", "target": 520, "reward": 42000, "trophy": "꺼지지 않는 검은 초"},
}

DECORATIONS: Mapping[str, Dict[str, Any]] = {
    "구조등": {"emoji": "🚨", "cost": {"고철": 20, "폐허회로": 2}, "appeal": 2},
    "정찰지도": {"emoji": "🗺️", "cost": {"나무": 25, "식량": 1500}, "appeal": 2},
    "야전침상": {"emoji": "🛏️", "cost": {"나무": 35, "약초": 8}, "appeal": 3},
    "무전벽": {"emoji": "📻", "cost": {"고철": 30, "폐허회로": 4}, "appeal": 4},
    "표본진열대": {"emoji": "🧪", "cost": {"나무": 30, "오염표본": 5}, "appeal": 4},
    "황혼등": {"emoji": "🏮", "cost": {"고철": 45, "보물파편": 4}, "appeal": 5},
}

SHELTER_THEMES: Mapping[str, Tuple[str, str]] = {
    "생존": ("🏕️", "거친 천막과 보급 상자로 꾸민 실용적인 대피소"),
    "정찰": ("🧭", "지도와 무전 장비가 가득한 정찰 거점"),
    "의무": ("⚕️", "깨끗한 치료대와 표본 보관함이 있는 의무실"),
    "기술": ("🧰", "회로와 공구가 정돈된 복구 공방"),
    "아포칼립스": ("☣️", "경고등과 방호벽이 둘러싼 종말 생존 벙커"),
}

RAID_CASES: Mapping[str, Dict[str, Any]] = {
    "black_station": {"name": "검은 역무실 봉쇄", "emoji": "🚇", "target": 1800, "summary": "폐쇄 역무실의 가짜 구조 신호와 자동 방어망을 동시에 해제합니다."},
    "plague_archive": {"name": "감염 기록고 심층 수사", "emoji": "☣️", "target": 2100, "summary": "오염 기록을 조작한 세력과 감염 표본의 이동 경로를 밝혀냅니다."},
    "moving_fortress": {"name": "이동 요새 내부 잠입", "emoji": "🏰", "target": 2400, "summary": "기계 군단의 이동 요새에 잠입해 지휘 코어와 포로 기록을 확보합니다."},
    "ashen_court": {"name": "잿빛 재판정", "emoji": "⚖️", "target": 2250, "summary": "서로 충돌하는 증언을 검증하고 세력 간 전쟁을 조작한 배후를 추적합니다."},
}

RAID_ROLES: Mapping[str, Tuple[str, str]] = {
    "field": ("현장수사", "🔎"),
    "analysis": ("기술분석", "🧪"),
    "guard": ("현장경계", "🛡️"),
    "negotiation": ("교섭", "🤝"),
}

RAID_ACTIONS: Mapping[str, Tuple[str, str, int]] = {
    "search": ("현장 수색", "🔦", 65),
    "analyze": ("증거 분석", "🧬", 72),
    "secure": ("현장 확보", "🛡️", 62),
    "interview": ("증언 교차검증", "🗣️", 68),
}


def _norm(value: Any) -> str:
    return str(value or "").strip().replace(" ", "").casefold()


def _iso(now: Optional[datetime] = None) -> str:
    return (now or _now()).astimezone(timezone.utc).isoformat()


def _week_key(now: Optional[datetime] = None) -> str:
    local = (now or _now()).astimezone(KST)
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def _stable_choice(keys: Sequence[str], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return keys[int.from_bytes(digest[:4], "big") % len(keys)]


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v950_investigation", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v950_investigation"] = root
    root["schema_version"] = SCHEMA_VERSION
    root.setdefault("guilds", {})
    root.setdefault("stats", {"cases_solved": 0, "bounties": 0, "raids": 0, "deletions": 0})
    return root


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _root(world_data)
    state = root["guilds"].setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        root["guilds"][str(guild_id)] = state
    week = _week_key()
    case_key = _stable_choice(tuple(CASE_TEMPLATES), f"case:{guild_id}:{week}")
    bounty_key = _stable_choice(tuple(BOUNTIES), f"bounty:{guild_id}:{week}")
    state.setdefault("case_history", [])
    state.setdefault("bounty_history", [])
    case = state.setdefault("case", {})
    if not isinstance(case, dict) or case.get("week") != week:
        if isinstance(case, dict) and case.get("id"):
            archived_ids = {str(row.get("id")) for row in state["case_history"] if isinstance(row, dict)}
            if str(case.get("id")) not in archived_ids:
                snapshot = copy.deepcopy(case)
                snapshot.setdefault("archived_at", _iso())
                snapshot.setdefault("archive_reason", "weekly_rotation")
                state["case_history"].insert(0, snapshot)
        state["case"] = {
            "id": f"CASE-{week}-{str(guild_id)[-4:]}", "week": week, "key": case_key,
            "found": {}, "links": [], "solved": False, "solved_by": "", "solved_at": "",
            "contributors": {}, "attempts": [],
        }
    bounty = state.setdefault("bounty", {})
    if not isinstance(bounty, dict) or bounty.get("week") != week:
        if isinstance(bounty, dict) and bounty.get("id"):
            archived_ids = {str(row.get("id")) for row in state["bounty_history"] if isinstance(row, dict)}
            if str(bounty.get("id")) not in archived_ids:
                snapshot = copy.deepcopy(bounty)
                snapshot.setdefault("archived_at", _iso())
                snapshot.setdefault("archive_reason", "weekly_rotation")
                state["bounty_history"].insert(0, snapshot)
        info = BOUNTIES[bounty_key]
        state["bounty"] = {
            "id": f"BNT-{week}-{str(guild_id)[-4:]}", "week": week, "key": bounty_key,
            "progress": 0, "target": info["target"], "resolved": False, "contributors": {},
            "claims": [], "history_written": False,
        }
    state.setdefault("raid", {})
    state.setdefault("raid_history", [])
    return state


def _profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = user.setdefault("investigation_v950", {})
    if not isinstance(profile, dict):
        profile = {}
        user["investigation_v950"] = profile
    profile["schema_version"] = SCHEMA_VERSION
    profile.setdefault("clues", {})
    profile.setdefault("case_links", [])
    profile.setdefault("solved_cases", [])
    profile.setdefault("case_actions", {})
    profile.setdefault("bounty_claims", [])
    profile.setdefault("bounty_actions", {})
    profile.setdefault("bounty_history", [])
    profile.setdefault("trophies", [])
    profile.setdefault("raid_claims", [])
    shelter = profile.setdefault("shelter", {})
    if not isinstance(shelter, dict):
        shelter = {}
        profile["shelter"] = shelter
    shelter.setdefault("name", "나의 대피소")
    shelter.setdefault("theme", "생존")
    shelter.setdefault("decorations", [])
    shelter.setdefault("showcase", [])
    shelter.setdefault("likes", [])
    shelter.setdefault("visitors", [])
    profile.setdefault("stats", {"clues": 0, "cases": 0, "bounties": 0, "raids": 0})
    return profile


def _case_info(state: Mapping[str, Any]) -> Dict[str, Any]:
    return CASE_TEMPLATES[str(state["case"]["key"])]


def _bounty_info(state: Mapping[str, Any]) -> Dict[str, Any]:
    return BOUNTIES[str(state["bounty"]["key"])]


def _parse_pair(raw: str) -> Tuple[str, str]:
    text = str(raw or "").strip()
    for sep in ("+", ",", "/", "|"):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    parts = text.split()
    if len(parts) >= 2:
        midpoint = max(1, len(parts) // 2)
        return " ".join(parts[:midpoint]), " ".join(parts[midpoint:])
    return text, ""


def _find_clue(raw: str, clue_names: Sequence[str]) -> Optional[str]:
    token = _norm(raw)
    exact = next((name for name in clue_names if _norm(name) == token), None)
    if exact:
        return exact
    matches = [name for name in clue_names if token and token in _norm(name)]
    return matches[0] if len(matches) == 1 else None


def _raid_embed(raid: Mapping[str, Any]) -> discord.Embed:
    if not raid:
        return discord.Embed(title="🕵️ 협동 수사 레이드", description="현재 모집 중인 수사 레이드가 없습니다.", colour=0x95A5A6)
    info = RAID_CASES[str(raid["key"])]
    progress = _safe_int(raid.get("progress"), 0)
    target = _safe_int(raid.get("target"), 1)
    embed = discord.Embed(title=f"{info['emoji']} 협동 수사 레이드 · {info['name']}", description=info["summary"], colour=0x9B59B6)
    embed.add_field(name="상태", value=str(raid.get("status", "planning")), inline=True)
    embed.add_field(name="진행도", value=f"{_bar(progress, target, 14)} {progress:,}/{target:,}", inline=False)
    members = raid.get("members", {}) if isinstance(raid.get("members"), dict) else {}
    role_lines = []
    for uid, role in members.items():
        name, emoji = RAID_ROLES.get(str(role), ("미지정", "▫️"))
        role_lines.append(f"{emoji} <@{uid}> · {name}")
    embed.add_field(name="수사대", value="\n".join(role_lines) or "모집 대기", inline=False)
    if raid.get("status") == "completed":
        embed.set_footer(text="참여자는 !수사레이드보상으로 개인 보상을 받을 수 있습니다")
    return embed


class InvestigationChoiceView(discord.ui.View):
    def __init__(self, owner_id: int, runner: Callable[[discord.Interaction, str], Any]) -> None:
        super().__init__(timeout=180)
        self.owner_id = int(owner_id)
        self.runner = runner
        for key, label, emoji in (("field", "현장", "🔎"), ("record", "기록", "🗂️"), ("witness", "증언", "🗣️")):
            button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.primary)
            async def callback(interaction: discord.Interaction, selected: str = key) -> None:
                if interaction.user.id != self.owner_id:
                    await interaction.response.send_message("이 조사 패널은 명령을 실행한 생존자 전용입니다.", ephemeral=True)
                    return
                await self.runner(interaction, selected)
            button.callback = callback
            self.add_item(button)


class RaidActionView(discord.ui.View):
    def __init__(self, runner: Callable[[discord.Interaction, str], Any]) -> None:
        super().__init__(timeout=300)
        for key, (name, emoji, _base) in RAID_ACTIONS.items():
            button = discord.ui.Button(label=name, emoji=emoji, style=discord.ButtonStyle.primary, custom_id=f"abaddon:v950:raid:{key}")
            async def callback(interaction: discord.Interaction, selected: str = key) -> None:
                await self.runner(interaction, selected)
            button.callback = callback
            self.add_item(button)


def register_v950_investigation_shelter_raid(
    bot: commands.Bot,
    get_user: Callable[[Any], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
    add_season_points: Callable[[MutableMapping[str, Any], int], Any],
) -> None:
    del user_data
    if getattr(bot, "_abaddon_v950_registered", False):
        return
    root = _root(world_data)

    additions = {
        "story": (
            "!사건판 / !단서조사 / !사건추리 — 단서 조합형 폐허 사건 수사",
            "!현상금 / !현상금추적 — 주간 표적 추적·생포·보고",
        ),
        "social": (
            "!대피소 / !전시실 — 개인 대피소 꾸미기·트로피 전시",
            "!수사레이드 — 서버 공동 증거 수집·분석·현장 확보",
        ),
        "server": ("!950안정화검수 — v9.5 수사·대피소·협동 레이드·영문 명령 읽기 전용 검사",),
    }
    for category_id, rows in additions.items():
        category = next((item for item in guide if item.get("id") == category_id), None)
        if not category:
            continue
        current = "\n".join(map(str, category.get("commands", [])))
        for row in rows:
            if row.split(" — ", 1)[0] not in current:
                category.setdefault("commands", []).append(row)
                current += "\n" + row

    async def require_user(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 불러오지 못했습니다.")
            return None
        _profile(user)
        return user

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not _is_admin(ctx.author):
            await ctx.send("⛔ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    async def investigate(guild_id: int, user_id: int, track: str) -> Tuple[bool, str]:
        user = get_user(user_id)
        if not isinstance(user, dict):
            return False, "먼저 생존자로 등록해주세요."
        async with _lock(bot, f"v950:case:{guild_id}"), _lock(bot, f"user:{user_id}"):
            state = _guild_state(world_data, guild_id)
            case = state["case"]
            if case.get("solved"):
                return False, "이번 주 사건은 이미 해결됐습니다."
            profile = _profile(user)
            day = _now().astimezone(KST).strftime("%Y-%m-%d")
            action_key = f"{case['id']}:{day}"
            used = _safe_int(profile["case_actions"].get(action_key), 0)
            if used >= 4:
                return False, "오늘 이 사건에서 사용할 수 있는 조사 행동을 모두 수행했습니다."
            stamina = _safe_int(user.get("stamina"), 100)
            if stamina < INVESTIGATION_STAMINA:
                return False, f"스태미나가 부족합니다. 필요 {INVESTIGATION_STAMINA}"
            info = _case_info(state)
            candidates = [name for name, clue_track in info["clues"].items() if clue_track == track]
            if not candidates:
                candidates = list(info["clues"])
            unseen = [name for name in candidates if _safe_int(profile["clues"].get(name), 0) <= 0]
            clue = random.choice(unseen or candidates)
            user["stamina"] = stamina - INVESTIGATION_STAMINA
            profile["clues"][clue] = _safe_int(profile["clues"].get(clue), 0) + 1
            profile["case_actions"][action_key] = used + 1
            profile["stats"]["clues"] = _safe_int(profile["stats"].get("clues"), 0) + 1
            uid = str(user_id)
            case.setdefault("found", {})[clue] = _safe_int(case.setdefault("found", {}).get(clue), 0) + 1
            case.setdefault("contributors", {})[uid] = _safe_int(case.setdefault("contributors", {}).get(uid), 0) + 1
            save_data()
            route = {"field": "🔦 현장 수색", "record": "🗂️ 기록 분석", "witness": "🗣️ 증언 청취"}.get(track, "🔎 조사")
            return True, f"{route} → 📌 **단서 확보** · {clue}\n스태미나 -{INVESTIGATION_STAMINA} · 오늘 조사 {used+1}/4"

    @bot.command(name="사건판", aliases=["수사사건현황", "caseboard", "investigationboard"], help="이번 주 폐허 사건과 공동 수사 진행도를 확인합니다.")
    async def case_board(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild_state(world_data, ctx.guild.id)
        case = state["case"]
        info = _case_info(state)
        found = len(case.get("found", {}))
        links = len(case.get("links", []))
        embed = discord.Embed(title=f"{info['emoji']} 사건판 · {info['title']}", description=info["summary"], colour=0xE67E22)
        embed.add_field(name="사건 번호", value=f"`{case['id']}`", inline=True)
        embed.add_field(name="상태", value="✅ 해결" if case.get("solved") else "🔎 수사 중", inline=True)
        embed.add_field(name="공동 단서", value=f"{found}/{len(info['clues'])}", inline=True)
        embed.add_field(name="연결된 증거", value=f"{links}/{len(info['links'])}", inline=True)
        embed.add_field(name="용의선", value=" · ".join(info["suspects"]), inline=False)
        embed.set_footer(text="조사 트랙과 단서 조합은 정답 확률을 공개하지 않으며 실제 확보 기록만 표시합니다")
        async def runner(interaction: discord.Interaction, track: str) -> None:
            await interaction.response.defer(ephemeral=True)
            ok, message = await investigate(interaction.guild.id, interaction.user.id, track)
            await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)
        await ctx.send(embed=embed, view=InvestigationChoiceView(ctx.author.id, runner))

    @bot.command(name="단서목록", aliases=["내단서", "clues", "cluelist"], help="보유한 사건 단서와 수량을 확인합니다.")
    async def clue_list(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        clues = _profile(user)["clues"]
        rows = [f"📌 {name} ×{amount}" for name, amount in sorted(clues.items()) if _safe_int(amount) > 0]
        await ctx.send("🗂️ **보유 단서**\n" + ("\n".join(rows[:30]) if rows else "아직 확보한 단서가 없습니다."))

    @bot.command(name="단서조사", aliases=["사건조사", "investigate", "searchclue"], help="현장·기록·증언 중 하나를 조사해 단서를 확보합니다.")
    async def clue_investigate(ctx: commands.Context, 조사유형: str = "현장") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        token = _norm(조사유형)
        track = "field" if token in {"현장", "field", "scene"} else "record" if token in {"기록", "record", "archive"} else "witness" if token in {"증언", "witness", "interview"} else ""
        if not track:
            await ctx.send("조사 유형: `현장` · `기록` · `증언`")
            return
        ok, message = await investigate(ctx.guild.id, ctx.author.id, track)
        await ctx.send(("✅ " if ok else "⚠️ ") + message)

    @bot.command(name="단서조합", aliases=["증거연결", "combineclues", "linkevidence"], help="보유한 두 단서를 연결해 사건의 논리 고리를 완성합니다.")
    async def clue_combine(ctx: commands.Context, *, 단서: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        state = _guild_state(world_data, ctx.guild.id)
        info = _case_info(state)
        left_raw, right_raw = _parse_pair(단서)
        left = _find_clue(left_raw, tuple(info["clues"]))
        right = _find_clue(right_raw, tuple(info["clues"]))
        if not left or not right or left == right:
            await ctx.send("형식: `!단서조합 단서이름 + 단서이름` · `!단서목록`을 확인하세요.")
            return
        profile = _profile(user)
        if _safe_int(profile["clues"].get(left), 0) <= 0 or _safe_int(profile["clues"].get(right), 0) <= 0:
            await ctx.send("⚠️ 두 단서를 모두 보유해야 합니다.")
            return
        pair = frozenset((left, right))
        valid = pair in info["links"]
        link_key = "|".join(sorted(pair))
        async with _lock(bot, f"v950:case:{ctx.guild.id}"):
            case = state["case"]
            if valid and link_key not in case["links"]:
                case["links"].append(link_key)
                profile["case_links"].append(f"{case['id']}:{link_key}")
                save_data()
                await ctx.send(f"🧩 **증거 연결 성공**\n`{left}` ↔ `{right}`\n사건의 모순 하나가 해소됐습니다.")
            elif valid:
                await ctx.send("ℹ️ 이미 공동 사건판에 연결된 증거입니다.")
            else:
                case["attempts"].append({"user": str(ctx.author.id), "pair": link_key, "at": _iso(), "valid": False})
                save_data()
                await ctx.send("🕸️ 두 단서는 현재 사건에서 직접 이어지지 않습니다. 다른 조합을 검토하세요.")

    @bot.command(name="사건추리", aliases=["사건해결", "solvecase", "deducecase"], help="연결된 증거를 바탕으로 사건의 배후를 지목합니다.")
    async def case_solve(ctx: commands.Context, *, 용의자: str = "") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _lock(bot, f"v950:case:{ctx.guild.id}"), _lock(bot, f"user:{ctx.author.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            case = state["case"]
            info = _case_info(state)
            if case.get("solved"):
                await ctx.send("✅ 이번 주 사건은 이미 해결됐습니다.")
                return
            if len(case.get("links", [])) < len(info["links"]):
                await ctx.send("⚠️ 아직 필요한 증거 연결이 부족합니다. `!단서조합`을 진행하세요.")
                return
            answer = next((item for item in info["suspects"] if _norm(item) == _norm(용의자) or _norm(용의자) in _norm(item)), None)
            if not answer:
                await ctx.send("용의선: " + " · ".join(info["suspects"]))
                return
            if answer != info["answer"]:
                case["attempts"].append({"user": str(ctx.author.id), "suspect": answer, "at": _iso(), "valid": False})
                save_data()
                await ctx.send("❌ 지목한 배후는 현재 증거와 맞지 않습니다. 공동 사건판은 유지됩니다.")
                return
            case["solved"] = True
            case["solved_by"] = str(ctx.author.id)
            case["solved_at"] = _iso()
            profile = _profile(user)
            profile["solved_cases"].append(case["id"])
            profile["stats"]["cases"] = _safe_int(profile["stats"].get("cases"), 0) + 1
            trophy = f"사건 기록 · {info['title']}"
            if trophy not in profile["trophies"]:
                profile["trophies"].append(trophy)
            _give(user, "식량", 25000)
            _give(user, "보물파편", 3)
            add_season_points(user, 35)
            add_title(user, "폐허의 탐정")
            try:
                _metric_delta(_world_state(world_data, ctx.guild.id), info["effects"])
            except Exception:
                pass
            root["stats"]["cases_solved"] = _safe_int(root["stats"].get("cases_solved"), 0) + 1
            state["case_history"].insert(0, copy.deepcopy(case))
            save_data()
        await ctx.send(f"🎯 **사건 해결** · {info['title']}\n배후: **{answer}**\n🥫 식량 +25,000 · 💠 보물파편 +3 · 🏆 트로피 획득")

    @bot.command(name="현상금", aliases=["현상금목록", "bounty", "bounties"], help="이번 주 공동 현상금 표적과 추적 진행도를 확인합니다.")
    async def bounty(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild_state(world_data, ctx.guild.id)
        row = state["bounty"]
        info = _bounty_info(state)
        await ctx.send(f"{info['emoji']} **주간 현상금 · {info['name']}**\n{_bar(_safe_int(row['progress']), _safe_int(row['target']), 14)} {_safe_int(row['progress']):,}/{_safe_int(row['target']):,}\n상태: {'✅ 제압 완료' if row.get('resolved') else '🎯 추적 중'}")

    @bot.command(name="현상금추적", aliases=["표적추적", "trackbounty", "huntbounty"], help="추적·잠복·협상·제압 방식으로 주간 현상금 진행도를 올립니다.")
    async def bounty_track(ctx: commands.Context, 방식: str = "추적") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        token = _norm(방식)
        modes = {"추적": ("🧭", 55), "잠복": ("🌫️", 48), "협상": ("🤝", 50), "제압": ("⚔️", 65)}
        key = next((name for name in modes if token in {_norm(name), {"추적":"track","잠복":"stakeout","협상":"negotiate","제압":"capture"}[name]}), None)
        if not key:
            await ctx.send("방식: `추적` · `잠복` · `협상` · `제압`")
            return
        async with _lock(bot, f"v950:bounty:{ctx.guild.id}"), _lock(bot, f"user:{ctx.author.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            row = state["bounty"]
            if row.get("resolved"):
                await ctx.send("✅ 이번 주 현상금 표적은 이미 제압됐습니다. `!현상금보고`로 보상을 받으세요.")
                return
            profile = _profile(user)
            day = _now().astimezone(KST).strftime("%Y-%m-%d")
            action_key = f"{row['id']}:{day}"
            used = _safe_int(profile["bounty_actions"].get(action_key), 0)
            if used >= 3:
                await ctx.send("⚠️ 오늘 현상금 추적 행동을 모두 사용했습니다.")
                return
            stamina = _safe_int(user.get("stamina"), 100)
            if stamina < 10:
                await ctx.send("⚠️ 스태미나 10이 필요합니다.")
                return
            emoji, base = modes[key]
            power_bonus = min(35, max(0, calculate_user_power(user) // 80))
            gain = base + power_bonus + random.randint(0, 18)
            remaining = max(0, _safe_int(row["target"]) - _safe_int(row["progress"]))
            gain = min(gain, remaining)
            user["stamina"] = stamina - 10
            row["progress"] = _safe_int(row["progress"]) + gain
            uid = str(ctx.author.id)
            row["contributors"][uid] = _safe_int(row["contributors"].get(uid), 0) + gain
            profile["bounty_actions"][action_key] = used + 1
            if row["progress"] >= row["target"]:
                row["resolved"] = True
                root["stats"]["bounties"] = _safe_int(root["stats"].get("bounties"), 0) + 1
                if not row.get("history_written"):
                    state["bounty_history"].insert(0, copy.deepcopy(row))
                    row["history_written"] = True
            save_data()
        await ctx.send(f"{emoji} **{key} 작전 완료** · 현상금 진행도 +{gain}\n스태미나 -10" + ("\n🎯 표적 제압 완료! `!현상금보고`로 보상을 받으세요." if row.get("resolved") else ""))

    @bot.command(name="현상금보고", aliases=["현상금보상", "claimbounty", "bountyreport"], help="완료된 주간 현상금의 개인 기여 보상을 받습니다.")
    async def bounty_report(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _lock(bot, f"v950:bounty:{ctx.guild.id}"), _lock(bot, f"user:{ctx.author.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            uid = str(ctx.author.id)
            profile = _profile(user)
            candidates = []
            current = state.get("bounty") if isinstance(state.get("bounty"), dict) else {}
            if current:
                candidates.append(current)
            candidates.extend(row for row in state.get("bounty_history", []) if isinstance(row, dict))
            row = next((item for item in candidates
                        if item.get("resolved")
                        and _safe_int(item.get("contributors", {}).get(uid), 0) > 0
                        and f"{item.get('id')}:{uid}" not in profile["bounty_claims"]), None)
            if row is None:
                await ctx.send("📭 수령 가능한 현상금 보상이 없습니다.")
                return
            claim_key = f"{row['id']}:{uid}"
            info = BOUNTIES.get(str(row.get("key")))
            if not isinstance(info, dict):
                await ctx.send("⚠️ 현상금 기록의 표적 정보를 확인할 수 없습니다. 관리자에게 사건 번호를 알려주세요.")
                return
            contribution = _safe_int(row.get("contributors", {}).get(uid), 0)
            food = int(info["reward"]) + min(25000, contribution * 25)
            _give(user, "식량", food)
            _give(user, "보물파편", max(1, contribution // 180))
            profile["bounty_claims"].append(claim_key)
            profile["bounty_history"].insert(0, {"id": row["id"], "target": info["name"], "contribution": contribution, "at": _iso()})
            profile["stats"]["bounties"] = _safe_int(profile["stats"].get("bounties"), 0) + 1
            if info["trophy"] not in profile["trophies"]:
                profile["trophies"].append(info["trophy"])
            save_data()
        await ctx.send(f"🎁 **현상금 보고 완료** · {info['name']}\n🥫 식량 +{food:,} · 🏆 {info['trophy']}")

    @bot.command(name="현상금기록", aliases=["표적기록", "bountyhistory", "hunthistory"], help="개인 현상금 완료 기록을 확인합니다.")
    async def bounty_history(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        rows = _profile(user)["bounty_history"]
        lines = [f"• {row.get('target')} · 기여 {row.get('contribution',0):,}" for row in rows[:15]]
        await ctx.send("🎯 **현상금 기록**\n" + ("\n".join(lines) if lines else "완료 기록이 없습니다."))

    def shelter_embed(member: discord.abc.User, user: MutableMapping[str, Any]) -> discord.Embed:
        profile = _profile(user)
        shelter = profile["shelter"]
        theme = str(shelter.get("theme") or "생존")
        emoji, description = SHELTER_THEMES.get(theme, SHELTER_THEMES["생존"])
        decorations = shelter.get("decorations", [])
        showcase = shelter.get("showcase", [])
        embed = discord.Embed(title=f"{emoji} {member.display_name}의 {shelter.get('name','대피소')}", description=description, colour=0x1ABC9C)
        embed.add_field(name="테마", value=theme, inline=True)
        embed.add_field(name="방문 좋아요", value=str(len(shelter.get("likes", []))), inline=True)
        embed.add_field(name="장식", value=" · ".join(f"{DECORATIONS.get(item,{}).get('emoji','▫️')}{item}" for item in decorations[:12]) or "아직 없음", inline=False)
        embed.add_field(name="전시 트로피", value="\n".join(f"🏆 {item}" for item in showcase[:8]) or "아직 없음", inline=False)
        return embed

    @bot.command(name="대피소", aliases=["개인대피소", "shelter", "myshelter"], help="개인 대피소의 테마·장식·전시품을 확인합니다.")
    async def shelter(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is not None:
            await ctx.send(embed=shelter_embed(ctx.author, user))

    @bot.command(name="대피소꾸미기", aliases=["대피소테마", "decorateshelter", "sheltertheme"], help="개인 대피소 테마를 변경합니다.")
    async def shelter_decorate(ctx: commands.Context, *, 테마: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        selected = next((name for name in SHELTER_THEMES if _norm(name) == _norm(테마)), None)
        if not selected:
            await ctx.send("테마: " + " · ".join(SHELTER_THEMES))
            return
        _profile(user)["shelter"]["theme"] = selected
        save_data()
        await ctx.send(f"🎨 대피소 테마를 **{selected}**(으)로 변경했습니다.")

    @bot.command(name="장식목록", aliases=["대피소장식", "decorations", "decorationlist"], help="제작 가능한 개인 대피소 장식과 비용을 확인합니다.")
    async def decoration_list(ctx: commands.Context) -> None:
        lines = [f"{info['emoji']} **{name}** · " + " / ".join(f"{item} {amount}" for item, amount in info["cost"].items()) for name, info in DECORATIONS.items()]
        await ctx.send("🧰 **대피소 장식 제작 목록**\n" + "\n".join(lines))

    @bot.command(name="장식제작", aliases=["대피소장식제작", "craftdecoration", "builddecoration"], help="재료를 사용해 개인 대피소 장식을 제작합니다.")
    async def decoration_craft(ctx: commands.Context, *, 장식명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        name = next((item for item in DECORATIONS if _norm(item) == _norm(장식명)), None)
        if not name:
            await ctx.send("⚠️ `!장식목록`에서 제작 가능한 장식을 확인하세요.")
            return
        info = DECORATIONS[name]
        async with _lock(bot, f"user:{ctx.author.id}"):
            shelter = _profile(user)["shelter"]
            if name in shelter["decorations"]:
                await ctx.send("ℹ️ 이미 보유한 장식입니다.")
                return
            missing = [f"{item} {_owned(user,item):,}/{amount:,}" for item, amount in info["cost"].items() if _owned(user, item) < amount]
            if missing:
                await ctx.send("⚠️ 재료 부족 · " + " · ".join(missing))
                return
            for item, amount in info["cost"].items():
                if not _take(user, item, amount):
                    await ctx.send("⚠️ 제작 중 재료 상태가 바뀌었습니다. 다시 시도하세요.")
                    return
            shelter["decorations"].append(name)
            save_data()
        await ctx.send(f"{info['emoji']} **장식 제작 완료** · {name}")

    @bot.command(name="전시실", aliases=["트로피실", "showcase", "trophyroom"], help="보유 트로피와 현재 전시 중인 수집품을 확인합니다.")
    async def showcase(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        profile = _profile(user)
        await ctx.send("🏛️ **보유 트로피**\n" + ("\n".join(f"🏆 {item}" for item in profile["trophies"][:30]) if profile["trophies"] else "아직 획득한 트로피가 없습니다.") + "\n\n전시: " + (" · ".join(profile["shelter"]["showcase"]) or "없음"))

    @bot.command(name="트로피전시", aliases=["전시등록", "displaytrophy", "showtrophy"], help="보유한 트로피를 개인 대피소 전시실에 올립니다.")
    async def trophy_display(ctx: commands.Context, *, 트로피명: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        profile = _profile(user)
        trophy = next((item for item in profile["trophies"] if _norm(트로피명) in _norm(item)), None)
        if not trophy:
            await ctx.send("⚠️ 보유한 트로피를 찾지 못했습니다. `!전시실`을 확인하세요.")
            return
        showcase = profile["shelter"]["showcase"]
        if trophy in showcase:
            await ctx.send("ℹ️ 이미 전시 중인 트로피입니다.")
            return
        if len(showcase) >= 8:
            await ctx.send("⚠️ 전시 공간은 최대 8개입니다.")
            return
        showcase.append(trophy)
        save_data()
        await ctx.send(f"🏆 **전시 등록** · {trophy}")

    @bot.command(name="대피소방문", aliases=["대피소구경", "visitshelter", "viewshelter"], help="다른 생존자의 개인 대피소를 방문합니다.")
    async def shelter_visit(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        target = 대상 or ctx.author
        user = get_user(target.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 해당 사용자는 등록된 생존자가 아닙니다.")
            return
        visitors = _profile(user)["shelter"]["visitors"]
        record = f"{ctx.author.id}:{_now().astimezone(KST).strftime('%Y-%m-%d')}"
        if record not in visitors:
            visitors.append(record)
            save_data()
        await ctx.send(embed=shelter_embed(target, user))

    @bot.command(name="대피소좋아요", aliases=["대피소추천", "likeshelter", "shelterlike"], help="다른 생존자의 개인 대피소에 좋아요를 남깁니다.")
    async def shelter_like(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        target = 대상
        if target is None or target.id == ctx.author.id:
            await ctx.send("⚠️ 좋아요를 남길 다른 생존자를 지정해주세요.")
            return
        user = get_user(target.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 해당 사용자는 등록된 생존자가 아닙니다.")
            return
        likes = _profile(user)["shelter"]["likes"]
        uid = str(ctx.author.id)
        day = _now().astimezone(KST).strftime("%Y-%m-%d")
        like_key = f"{uid}:{day}"
        if like_key in likes:
            await ctx.send("ℹ️ 오늘은 이미 이 대피소에 좋아요를 남겼습니다.")
            return
        likes.append(like_key)
        save_data()
        await ctx.send(f"💚 **{target.display_name}**의 대피소에 좋아요를 남겼습니다.")

    def create_raid(guild_id: int, owner_id: int, key: str) -> MutableMapping[str, Any]:
        state = _guild_state(world_data, guild_id)
        current = state.get("raid") if isinstance(state.get("raid"), dict) else {}
        # A new raid may only replace a fully settled one. Active or completed-but-
        # unsettled operations stay in place so no participant loses a settlement.
        if current and current.get("status") in {"planning", "active", "completed"} and not current.get("settled"):
            raise RuntimeError("unsettled_raid_exists")
        if current and current.get("id"):
            archived_ids = {str(row.get("id")) for row in state["raid_history"] if isinstance(row, dict)}
            if str(current.get("id")) not in archived_ids:
                state["raid_history"].insert(0, copy.deepcopy(current))
        info = RAID_CASES[key]
        raid = {
            "id": f"IR-{secrets.token_hex(3).upper()}", "key": key, "owner": str(owner_id),
            "status": "planning", "progress": 0, "target": int(info["target"]),
            "members": {str(owner_id): "field"}, "contributions": {}, "cooldowns": {},
            "claims": [], "started_at": "", "completed_at": "", "settled": False,
        }
        state["raid"] = raid
        save_data()
        return raid

    def raid_key(raw: str) -> Optional[str]:
        token = _norm(raw)
        return next((key for key, info in RAID_CASES.items() if token in {_norm(key), _norm(info["name"])} or (token and token in _norm(info["name"]))), None)

    def raid_role(raw: str) -> Optional[str]:
        token = _norm(raw)
        return next((key for key, (name, _emoji) in RAID_ROLES.items() if token in {_norm(key), _norm(name)}), None)

    async def raid_action(guild_id: int, user_id: int, action: str) -> Tuple[bool, str]:
        user = get_user(user_id)
        if not isinstance(user, dict):
            return False, "먼저 생존자로 등록해주세요."
        async with _lock(bot, f"v950:raid:{guild_id}"), _lock(bot, f"user:{user_id}"):
            state = _guild_state(world_data, guild_id)
            raid = state.get("raid") if isinstance(state.get("raid"), dict) else {}
            if not raid or raid.get("status") != "active":
                return False, "진행 중인 수사 레이드가 없습니다."
            uid = str(user_id)
            if uid not in raid.get("members", {}):
                return False, "먼저 수사 레이드에 참가해주세요."
            now_ts = int(_now().timestamp())
            ready_at = _safe_int(raid.setdefault("cooldowns", {}).get(uid), 0)
            if now_ts < ready_at:
                return False, f"다음 행동까지 {ready_at-now_ts}초 남았습니다."
            if action not in RAID_ACTIONS:
                return False, "수사 행동을 확인할 수 없습니다."
            role = str(raid["members"].get(uid))
            name, emoji, base = RAID_ACTIONS[action]
            role_bonus = 22 if (role, action) in {("field", "search"), ("analysis", "analyze"), ("guard", "secure"), ("negotiation", "interview")} else 6
            power_bonus = min(45, calculate_user_power(user) // 70)
            gain = base + role_bonus + power_bonus + random.randint(0, 18)
            remaining = max(0, _safe_int(raid["target"]) - _safe_int(raid["progress"]))
            gain = min(gain, remaining)
            raid["progress"] = _safe_int(raid["progress"]) + gain
            raid.setdefault("contributions", {})[uid] = _safe_int(raid.setdefault("contributions", {}).get(uid), 0) + gain
            raid["cooldowns"][uid] = now_ts + RAID_ACTION_COOLDOWN
            if raid["progress"] >= raid["target"]:
                raid["status"] = "completed"
                raid["completed_at"] = _iso()
            save_data()
            return True, f"{emoji} **{name}** · 공동 진행도 +{gain}" + ("\n🎉 수사 레이드 목표 달성!" if raid.get("status") == "completed" else "")

    @bot.command(name="수사레이드", aliases=["협동수사", "investigationraid", "caseraid"], help="현재 협동 수사 레이드 모집·진행·완료 상태를 확인합니다.")
    async def investigation_raid(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = _guild_state(world_data, ctx.guild.id)
        raid = state.get("raid") if isinstance(state.get("raid"), dict) else {}
        async def runner(interaction: discord.Interaction, action: str) -> None:
            await interaction.response.defer(ephemeral=True)
            ok, message = await raid_action(interaction.guild.id, interaction.user.id, action)
            await interaction.followup.send(("✅ " if ok else "⚠️ ") + message, ephemeral=True)
        await ctx.send(embed=_raid_embed(raid), view=RaidActionView(runner) if raid and raid.get("status") == "active" else None)

    @bot.command(name="수사레이드모집", aliases=["수사대모집", "openinvestigationraid", "openraidcase"], help="협동 수사 레이드 모집을 시작합니다.")
    async def investigation_raid_open(ctx: commands.Context, *, 사건명: str = "") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        key = raid_key(사건명) or _stable_choice(tuple(RAID_CASES), f"raid:{ctx.guild.id}:{_week_key()}:{ctx.author.id}")
        async with _lock(bot, f"v950:raid:{ctx.guild.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            current = state.get("raid") if isinstance(state.get("raid"), dict) else {}
            if current and current.get("status") in {"planning", "active"}:
                await ctx.send("⚠️ 이미 모집 또는 진행 중인 수사 레이드가 있습니다.")
                return
            if current and current.get("status") == "completed" and not current.get("settled"):
                await ctx.send("⚠️ 완료된 수사 레이드를 먼저 `!수사레이드정산`해야 새 모집을 열 수 있습니다.")
                return
            raid = create_raid(ctx.guild.id, ctx.author.id, key)
        await ctx.send(embed=_raid_embed(raid))

    @bot.command(name="수사레이드참가", aliases=["수사대참가", "joininvestigationraid", "joincaseraid"], help="현장수사·기술분석·현장경계·교섭 역할로 참가합니다.")
    async def investigation_raid_join(ctx: commands.Context, 역할: str = "현장수사") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        role = raid_role(역할)
        if not role:
            await ctx.send("역할: `현장수사` · `기술분석` · `현장경계` · `교섭`")
            return
        async with _lock(bot, f"v950:raid:{ctx.guild.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            raid = state.get("raid") if isinstance(state.get("raid"), dict) else {}
            if not raid or raid.get("status") != "planning":
                await ctx.send("⚠️ 참가 가능한 모집이 없습니다.")
                return
            if len(raid.get("members", {})) >= 8 and str(ctx.author.id) not in raid.get("members", {}):
                await ctx.send("⚠️ 수사대는 최대 8명입니다.")
                return
            raid.setdefault("members", {})[str(ctx.author.id)] = role
            save_data()
        name, emoji = RAID_ROLES[role]
        await ctx.send(f"{emoji} 수사 레이드 참가 · 역할 **{name}**")

    @bot.command(name="수사레이드출발", aliases=["수사대출발", "startinvestigationraid", "startcaseraid"], help="모집자가 2명 이상의 수사 레이드를 출발시킵니다.")
    async def investigation_raid_start(ctx: commands.Context) -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        async with _lock(bot, f"v950:raid:{ctx.guild.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            raid = state.get("raid") if isinstance(state.get("raid"), dict) else {}
            if not raid or raid.get("status") != "planning":
                await ctx.send("⚠️ 출발 가능한 모집이 없습니다.")
                return
            if str(raid.get("owner")) != str(ctx.author.id) and not _is_admin(ctx.author):
                await ctx.send("⛔ 모집자 또는 관리자만 출발할 수 있습니다.")
                return
            if len(raid.get("members", {})) < 2:
                await ctx.send("⚠️ 최소 2명의 수사대가 필요합니다.")
                return
            raid["status"] = "active"
            raid["started_at"] = _iso()
            save_data()
        await ctx.send("🚨 **협동 수사 레이드 출발**\n🔦 현장 진입 → 📡 신호 확보 → 🧬 증거 분석 → 🛡️ 현장 봉쇄")

    @bot.command(name="수사레이드행동", aliases=["수사대행동", "investigationaction", "raidinvestigate"], help="수색·분석·확보·교차검증 행동으로 공동 진행도를 올립니다.")
    async def investigation_raid_action(ctx: commands.Context, 행동: str = "수색") -> None:
        if await require_user(ctx) is None or ctx.guild is None:
            return
        token = _norm(행동)
        action_aliases = {
            "search": {"search", "수색", "현장수색"},
            "analyze": {"analyze", "analysis", "분석", "증거분석"},
            "secure": {"secure", "guard", "확보", "현장확보"},
            "interview": {"interview", "verify", "교차검증", "증언검증"},
        }
        action = next((key for key, aliases in action_aliases.items() if token in {_norm(item) for item in aliases}), None)
        if not action:
            await ctx.send("행동: `수색` · `분석` · `확보` · `교차검증`")
            return
        ok, message = await raid_action(ctx.guild.id, ctx.author.id, action)
        await ctx.send(("✅ " if ok else "⚠️ ") + message)

    @bot.command(name="수사레이드정산", aliases=["수사대정산", "settleinvestigationraid", "settlecaseraid"], help="완료된 협동 수사 레이드를 한 번만 정산합니다.")
    async def investigation_raid_settle(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        async with _lock(bot, f"v950:raid:{ctx.guild.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            raid = state.get("raid") if isinstance(state.get("raid"), dict) else {}
            if not raid or raid.get("status") != "completed":
                await ctx.send("⚠️ 정산 가능한 완료 레이드가 없습니다.")
                return
            if raid.get("settled"):
                await ctx.send("ℹ️ 이미 정산된 레이드입니다.")
                return
            raid["settled"] = True
            state["raid_history"].insert(0, copy.deepcopy(raid))
            root["stats"]["raids"] = _safe_int(root["stats"].get("raids"), 0) + 1
            try:
                _metric_delta(_world_state(world_data, ctx.guild.id), {"stability": 3, "morale": 2})
            except Exception:
                pass
            save_data()
        await ctx.send("✅ 협동 수사 레이드 정산 완료 · 참여자 개인 보상 개방")

    @bot.command(name="수사레이드보상", aliases=["수사대보상", "claiminvestigationraid", "claimcaseraid"], help="정산된 협동 수사 레이드의 개인 기여 보상을 받습니다.")
    async def investigation_raid_reward(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        async with _lock(bot, f"v950:raid:{ctx.guild.id}"), _lock(bot, f"user:{ctx.author.id}"):
            state = _guild_state(world_data, ctx.guild.id)
            uid = str(ctx.author.id)
            profile = _profile(user)
            candidates = []
            current = state.get("raid") if isinstance(state.get("raid"), dict) else {}
            if current:
                candidates.append(current)
            candidates.extend(row for row in state.get("raid_history", []) if isinstance(row, dict))
            raid = next((row for row in candidates if row.get("settled") and _safe_int(row.get("contributions", {}).get(uid), 0) > 0 and f"{row.get('id')}:{uid}" not in profile["raid_claims"]), None)
            if raid is None:
                await ctx.send("📭 수령 가능한 수사 레이드 보상이 없습니다.")
                return
            contribution = _safe_int(raid["contributions"].get(uid), 0)
            food = min(70000, 15000 + contribution * 30)
            fragments = max(2, contribution // 250)
            _give(user, "식량", food)
            _give(user, "보물파편", fragments)
            profile["raid_claims"].append(f"{raid['id']}:{uid}")
            profile["stats"]["raids"] = _safe_int(profile["stats"].get("raids"), 0) + 1
            trophy = f"협동 수사 기록 · {RAID_CASES[str(raid['key'])]['name']}"
            if trophy not in profile["trophies"]:
                profile["trophies"].append(trophy)
            add_season_points(user, min(80, 20 + contribution // 40))
            save_data()
        await ctx.send(f"🎁 **수사 레이드 보상** · 식량 +{food:,} · 보물파편 +{fragments} · 🏆 기록 트로피")

    @bot.command(name="수사레이드기록", aliases=["수사대기록", "investigationraidhistory", "caseraidhistory"], help="현재 서버의 최근 협동 수사 레이드 기록을 확인합니다.")
    async def investigation_raid_history(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        rows = _guild_state(world_data, ctx.guild.id).get("raid_history", [])
        lines = [f"• `{row.get('id')}` · {RAID_CASES.get(str(row.get('key')),{}).get('name','미확인')} · 참여 {len(row.get('members',{}))}명" for row in rows[:15]]
        await ctx.send("🗃️ **협동 수사 레이드 기록**\n" + ("\n".join(lines) if lines else "완료 기록이 없습니다."))

    @bot.command(name="950안정화검수", aliases=["95검수", "v950audit", "investigationaudit"], help="v9.5 수사·대피소·레이드·영문 명령 연결을 읽기 전용 검사합니다.")
    async def v950_stability(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        state = _guild_state(world_data, ctx.guild.id)
        english = getattr(bot, "v950_english_sync", {})
        checks = [
            ("사건 템플릿", len(CASE_TEMPLATES) >= 6),
            ("현상금 표적", len(BOUNTIES) >= 5),
            ("대피소 장식", len(DECORATIONS) >= 6),
            ("협동 수사 레이드", len(RAID_CASES) >= 4),
            ("영문 명령 전체 동기화", _safe_int(english.get("commands_without_ascii"), 1) == 0),
            ("삭제 기록", _safe_int(root["stats"].get("deletions"), 0) == 0),
        ]
        embed = discord.Embed(title="🛡️ ABADDON v9.5.0 안정화 검수", colour=0x2ECC71 if all(ok for _name, ok in checks) else 0xE67E22)
        for name, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value="정상" if ok else "확인 필요", inline=True)
        embed.add_field(name="현재 사건", value=str(state["case"].get("id")), inline=False)
        embed.add_field(name="영문 동기화", value=f"등록 {english.get('registered',0)} · 충돌 회피 {english.get('skipped',0)} · 미등록 {english.get('commands_without_ascii','?')}", inline=False)
        embed.set_footer(text="읽기 전용 검사 · 기능·데이터·기록 삭제 없음")
        await ctx.send(embed=embed)

    # Latest-patch-only test hook used by !테스트 상세.
    async def _v950_test_detail_impl(ctx: commands.Context) -> discord.Embed:
        english = getattr(bot, "v950_english_sync", {})
        checks = [
            ("사건 수사", bot.get_command("사건판") is not None and bot.get_command("단서조합") is not None),
            ("현상금", bot.get_command("현상금추적") is not None),
            ("개인 대피소", bot.get_command("대피소") is not None and bot.get_command("전시실") is not None),
            ("협동 수사 레이드", bot.get_command("수사레이드") is not None),
            ("영문 전체 등록", _safe_int(english.get("commands_without_ascii"), 1) == 0),
            ("v9.5 드롭다운", all(key in getattr(bot, "v600_action_index", {}) for key in ("case_board_v950", "shelter_v950", "investigation_raid_v950"))),
        ]
        embed = discord.Embed(title="🧪 최신 패치 상세 검사 · v9.5.0", colour=0x2ECC71 if all(ok for _name, ok in checks) else 0xE67E22)
        for name, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value="정상" if ok else "확인 필요", inline=True)
        embed.set_footer(text="이번 패치에서 추가·수정된 기능만 검사합니다")
        return embed

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        embed = await _v950_test_detail_impl(ctx)
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치 v9.5.0에서 추가·수정된 기능만 읽기 전용 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v950_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="🕵️ ABADDON v9.5.0 — 사건 수사·개인 대피소·협동 수사 레이드",
                description="v9.3~v9.5 로드맵을 통합하고 모든 prefix 명령의 영문 접근 경로를 최종 등록했습니다.",
                colour=0x8E44AD,
            )
            embed.add_field(name="🔎 사건 수사", value="주간 사건판 · 단서 조사·조합 · 용의자 추리 · 세계 상태 연동", inline=False)
            embed.add_field(name="🎯 현상금", value="주간 표적 추적·잠복·협상·제압 · 기여 보상과 트로피", inline=False)
            embed.add_field(name="🏕️ 개인 대피소", value="테마·장식 제작 · 전시실 · 방문·좋아요 · 트로피 보존", inline=False)
            embed.add_field(name="🕵️ 협동 수사 레이드", value="최대 8명 역할 편성 · 수색·분석·확보·교차검증 · 중복 정산 방지", inline=False)
            embed.add_field(name="🌐 English command refresh", value="전체 prefix 명령에 충돌 없는 ASCII/English 접근 경로를 등록하고 영어 검색 색인을 최신화", inline=False)
            embed.set_footer(text="ABADDON v9.5.0 · 기존 기능·데이터·기록 삭제 0건")
            await ctx.send(embed=embed)
        patch.callback = v950_patch_notes
        patch.help = "ABADDON v9.5.0 사건 수사·대피소·협동 수사 레이드·영문 명령 통합 패치노트입니다."
        patch.description = patch.help

    bot._abaddon_v950_registered = True
    bot.v950_version = VERSION
    bot.v950_root = root
    print(f"[ABADDON v{VERSION}] investigation/shelter/raid registered cases={len(CASE_TEMPLATES)} bounties={len(BOUNTIES)} decorations={len(DECORATIONS)} raids={len(RAID_CASES)} deletions=0")
