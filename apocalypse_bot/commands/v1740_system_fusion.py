from __future__ import annotations

"""ABADDON v17.4.0 — SYSTEM FUSION.

Additive consolidation layer for the existing apocalypse RPG.  It keeps every
legacy command and save structure intact while adding three high-level hubs:

* Survivor Terminal: story, world, contracts, expedition, NPC bonds and city.
* Survival Contract Office: daily/weekly contracts generated from live state.
* Production Center: gathering, inventory, crafting, material uses and city.

The module deliberately reads the existing v17.1–v17.3 state instead of
creating duplicate story/world/expedition systems.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import random
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _invoke_command, _safe_embed, _safe_view
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as command_hub

VERSION = "17.4.0"
ROOT_KEY = "system_fusion_v1740"
KST = timezone(timedelta(hours=9))


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _week_key() -> str:
    now = datetime.now(KST)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _locale(bot: commands.Bot, actor: Any, guild_id: int = 0) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(actor.id), int(guild_id))
    except Exception:
        return "ko"


def _ctx_locale(bot: commands.Bot, ctx: commands.Context) -> str:
    return _locale(bot, ctx.author, int(ctx.guild.id if ctx.guild else 0))


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> MutableMapping[str, Any]:
    row = get_user(int(user_id))
    return row if isinstance(row, MutableMapping) else {}


def _root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault(ROOT_KEY, {})
    if not isinstance(row, MutableMapping):
        row = {}
        user[ROOT_KEY] = row
    row.setdefault("version", VERSION)
    row.setdefault("active", {})
    row.setdefault("completed", {})
    row.setdefault("history", [])
    row.setdefault("factions", {})
    row.setdefault("last_board_day", "")
    row.setdefault("last_board_week", "")
    if not isinstance(row.get("active"), MutableMapping):
        row["active"] = {}
    if not isinstance(row.get("completed"), MutableMapping):
        row["completed"] = {}
    if not isinstance(row.get("history"), list):
        row["history"] = []
    if not isinstance(row.get("factions"), MutableMapping):
        row["factions"] = {}
    row["version"] = VERSION
    return row


FACTIONS: Dict[str, Dict[str, Any]] = {
    "alliance": {
        "ko": "생존자 연합", "en": "Survivor Alliance", "emoji": "🛡️",
        "desc_ko": "구조·의료·방어와 시민 생존을 우선합니다.",
        "desc_en": "Prioritizes rescue, medicine, defense and civilian survival.",
        "npc": "yoonseo", "metric": "hope", "opposed": "cult",
    },
    "workshop": {
        "ko": "BLACK CITY 공방회", "en": "BLACK CITY Artificers", "emoji": "⚙️",
        "desc_ko": "제작·도시 부품·전력 시설을 담당합니다.",
        "desc_en": "Handles crafting, city parts and power infrastructure.",
        "npc": "sera", "metric": "power", "opposed": "market",
    },
    "market": {
        "ko": "암시장 상인회", "en": "Black Market Consortium", "emoji": "💰",
        "desc_ko": "희귀 물자와 위험한 거래로 도시 경제를 움직입니다.",
        "desc_en": "Moves the city economy through rare supplies and risky trade.",
        "npc": "eve", "metric": "tension", "opposed": "alliance",
    },
    "observatory": {
        "ko": "NEON ABYSS 관측단", "en": "NEON ABYSS Observatory", "emoji": "🌀",
        "desc_ko": "차원 균열·유물·변이 지역을 연구합니다.",
        "desc_en": "Studies rifts, relics and mutated regions.",
        "npc": "mira", "metric": "power", "opposed": "cult",
    },
    "cult": {
        "ko": "검은 태양 교단", "en": "Black Sun Order", "emoji": "🕯️",
        "desc_ko": "심연의 힘과 금지된 세계 변화를 추구합니다.",
        "desc_en": "Pursues abyssal power and forbidden world changes.",
        "npc": "nox", "metric": "tension", "opposed": "alliance",
    },
}

REP_TIERS: Tuple[Tuple[int, str, str], ...] = (
    (0, "낯선 생존자", "Unknown Survivor"),
    (20, "협력자", "Associate"),
    (50, "신뢰받는 요원", "Trusted Agent"),
    (90, "핵심 인물", "Key Figure"),
    (140, "전설적 동맹", "Legendary Ally"),
)


def _rep(user: MutableMapping[str, Any], faction_id: str) -> int:
    factions = _root(user)["factions"]
    return int(factions.get(faction_id, 0) or 0)


def _rep_tier(locale: str, value: int) -> str:
    chosen = REP_TIERS[0]
    for tier in REP_TIERS:
        if value >= tier[0]:
            chosen = tier
    return _t(locale, chosen[1], chosen[2])


def _world_state(world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> MutableMapping[str, Any]:
    try:
        from apocalypse_bot.commands import v1720_living_world_bonds as living
        return living._world_state(world_data, int(guild_id), save_data)
    except Exception:
        return {}


def _connected_status(user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> Dict[str, bool]:
    try:
        from apocalypse_bot.commands import v1730_connected_survival_loop as connected
        raw = connected._daily_status(user, world_data, int(guild_id), save_data)
        return {str(k): bool(v) for k, v in raw.items()}
    except Exception:
        return {"world": False, "expedition": False, "npc": False, "city": False}


def _story_line(locale: str, user: Mapping[str, Any]) -> Tuple[str, str]:
    try:
        from apocalypse_bot.commands import v1730_connected_survival_loop as connected
        return connected._story_line(locale, user)
    except Exception:
        return "스토리나침반", _t(locale, "스토리 진행 확인", "Review story progress")


def _city_effects(world_data: Mapping[str, Any], guild_id: int) -> Dict[str, int]:
    try:
        from apocalypse_bot.commands import v1730_connected_survival_loop as connected
        return connected._city_effects(world_data, int(guild_id))
    except Exception:
        return {}


def _material_total(user: Mapping[str, Any]) -> int:
    known = ("고철", "약초", "나무", "광석", "전자부품", "네온결정", "차원결정")
    resources = user.get("resources", {}) if isinstance(user.get("resources"), Mapping) else {}
    inventory = user.get("inventory", {}) if isinstance(user.get("inventory"), Mapping) else {}
    return sum(int(resources.get(k, 0) or 0) + int(inventory.get(k, 0) or 0) for k in known)


def _material_rows(user: Mapping[str, Any], locale: str, limit: int = 7) -> List[str]:
    labels = {
        "고철": "Scrap", "약초": "Herbs", "나무": "Wood", "광석": "Ore",
        "전자부품": "Electronic Parts", "네온결정": "Neon Crystal", "차원결정": "Rift Crystal",
    }
    resources = user.get("resources", {}) if isinstance(user.get("resources"), Mapping) else {}
    inventory = user.get("inventory", {}) if isinstance(user.get("inventory"), Mapping) else {}
    rows: List[Tuple[int, str]] = []
    for ko, en in labels.items():
        amount = int(resources.get(ko, 0) or 0) + int(inventory.get(ko, 0) or 0)
        rows.append((amount, f"• **{en if locale == 'en' else ko}** ×{amount:,}"))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [line for _amount, line in rows[:limit]]


CONTRACT_TEMPLATES: Tuple[Dict[str, Any], ...] = (
    {"key": "world", "faction": "alliance", "ko": "오늘의 구조 신호 대응", "en": "Answer Today's Rescue Signal", "desc_ko": "오늘의 세계 사건에 참여하세요.", "desc_en": "Participate in today's world event.", "target": 1, "food": 18000, "exp": 90},
    {"key": "expedition", "faction": "observatory", "ko": "변이 지역 현장 조사", "en": "Survey the Mutated Zone", "desc_ko": "솔로 원정을 귀환·철수·구조로 마무리하세요.", "desc_en": "Finish a solo expedition by returning, retreating or being rescued.", "target": 1, "food": 22000, "exp": 110},
    {"key": "npc", "faction": "alliance", "ko": "현장 요원 동행 작전", "en": "Field Agent Joint Operation", "desc_ko": "NPC 동행 작전을 1회 완료하세요.", "desc_en": "Complete one NPC bond mission.", "target": 1, "food": 16000, "exp": 100},
    {"key": "city", "faction": "workshop", "ko": "도시 시설 긴급 정비", "en": "Emergency City Maintenance", "desc_ko": "도시 부품을 배치·삭제·복구하세요.", "desc_en": "Place, remove or restore a city decoration.", "target": 1, "food": 20000, "exp": 95},
    {"key": "materials", "faction": "workshop", "ko": "공방 재료 조달", "en": "Workshop Material Procurement", "desc_ko": "수락 후 주요 재료를 15개 이상 획득하세요.", "desc_en": "Gain at least 15 tracked materials after accepting.", "target": 15, "food": 24000, "exp": 105},
    {"key": "balance", "faction": "market", "ko": "암시장 유동성 확보", "en": "Secure Black-Market Liquidity", "desc_ko": "수락 후 식량 잔액을 15,000 이상 늘리세요.", "desc_en": "Increase your supply balance by at least 15,000 after accepting.", "target": 15000, "food": 12000, "exp": 80},
    {"key": "connected", "faction": "cult", "ko": "검은 태양의 세 가지 징조", "en": "Three Omens of the Black Sun", "desc_ko": "연결 목표 4개 중 3개를 완료하세요.", "desc_en": "Complete 3 of the 4 connected objectives.", "target": 3, "food": 28000, "exp": 130},
)

WEEKLY_TEMPLATE: Dict[str, Any] = {
    "key": "weekly_contracts", "faction": "observatory", "ko": "주간 생존망 안정화", "en": "Weekly Survival-Network Stabilization",
    "desc_ko": "이번 주 일일 의뢰를 3개 완료하세요.", "desc_en": "Complete three daily contracts this week.",
    "target": 3, "food": 75000, "exp": 350,
}


def _board(world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> List[Dict[str, Any]]:
    day = _today()
    week = _week_key()
    state = _world_state(world_data, guild_id, save_data)
    seed_bits = [day, week, str(guild_id), str(state.get("market_index", 100)), str(state.get("conflict", {}).get("id", ""))]
    seed = int(hashlib.sha256(":".join(seed_bits).encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    pool = [dict(x) for x in CONTRACT_TEMPLATES]
    # Bias the board toward the current world's pressure without making it random-only.
    metrics = state.get("metrics", {}) if isinstance(state.get("metrics"), Mapping) else {}
    risks = state.get("risks", {}) if isinstance(state.get("risks"), Mapping) else {}
    if risks and max(int(v or 0) for v in risks.values()) >= 65:
        pool.append(dict(CONTRACT_TEMPLATES[1]))
    if int(metrics.get("power", 50) or 50) < 45:
        pool.append(dict(CONTRACT_TEMPLATES[3]))
    if int(state.get("market_index", 100) or 100) >= 110:
        pool.append(dict(CONTRACT_TEMPLATES[5]))
    rng.shuffle(pool)
    chosen: List[Dict[str, Any]] = []
    used = set()
    for item in pool:
        if item["key"] in used:
            continue
        used.add(item["key"])
        chosen.append(item)
        if len(chosen) == 3:
            break
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(chosen, start=1):
        item = dict(item)
        item.update({"id": f"{day}:D{index}", "slot": index, "period": "daily", "day": day, "week": week})
        rows.append(item)
    weekly = dict(WEEKLY_TEMPLATE)
    weekly.update({"id": f"{week}:W1", "slot": 4, "period": "weekly", "day": day, "week": week})
    rows.append(weekly)
    return rows


def _snapshot(user: Mapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> Dict[str, Any]:
    status = _connected_status(dict(user) if not isinstance(user, MutableMapping) else user, world_data, guild_id, save_data)
    return {
        "balance": int(user.get("balance", 0) or 0),
        "materials": _material_total(user),
        "connected": sum(1 for value in status.values() if value),
        "at": int(datetime.now().timestamp()),
    }


def _weekly_completed(root: Mapping[str, Any], week: str) -> int:
    history = root.get("history", []) if isinstance(root.get("history"), list) else []
    return sum(1 for row in history if isinstance(row, Mapping) and row.get("type") == "complete" and row.get("period") == "daily" and row.get("week") == week)


def _progress(contract: Mapping[str, Any], active: Mapping[str, Any], user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> Tuple[int, int]:
    key = str(contract.get("key"))
    target = max(1, int(contract.get("target", 1) or 1))
    status = _connected_status(user, world_data, guild_id, save_data)
    snap = active.get("snapshot", {}) if isinstance(active.get("snapshot"), Mapping) else {}
    if key in {"world", "expedition", "npc", "city"}:
        return (1 if status.get(key) else 0), target
    if key == "materials":
        return max(0, _material_total(user) - int(snap.get("materials", 0) or 0)), target
    if key == "balance":
        return max(0, int(user.get("balance", 0) or 0) - int(snap.get("balance", 0) or 0)), target
    if key == "connected":
        return sum(1 for value in status.values() if value), target
    if key == "weekly_contracts":
        return _weekly_completed(_root(user), str(contract.get("week", _week_key()))), target
    return 0, target


def _apply_relation(user: MutableMapping[str, Any], faction_id: str, amount: int) -> str:
    spec = FACTIONS.get(faction_id, {})
    npc_id = str(spec.get("npc", ""))
    if not npc_id:
        return ""
    try:
        from apocalypse_bot.commands import v1720_living_world_bonds as living
        npc = next((row for row in living.NPCS if row.get("id") == npc_id), None)
        bond = living._bond(user, npc_id)
        before = int(bond.get("trust", 0) or 0)
        bond["trust"] = min(100, before + max(1, amount // 4))
        bond["affinity"] = min(100, int(bond.get("affinity", 0) or 0) + max(1, amount // 6))
        living._clamp_bond(bond)
        return str(npc.get("ko", npc_id) if npc else npc_id)
    except Exception:
        return ""


def _complete_contract(
    user: MutableMapping[str, Any], contract: Mapping[str, Any], active: MutableMapping[str, Any],
    world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None], locale: str,
) -> discord.Embed:
    root = _root(user)
    faction_id = str(contract.get("faction", "alliance"))
    faction = FACTIONS[faction_id]
    period = str(contract.get("period", "daily"))
    base_rep = 18 if period == "weekly" else 8
    city = _city_effects(world_data, guild_id)
    reward_bonus = min(20, int(city.get("hope", 0) or 0))
    food = int(contract.get("food", 0) or 0) + reward_bonus * 400
    exp = int(contract.get("exp", 0) or 0)
    before_balance = int(user.get("balance", 0) or 0)
    before_exp = int(user.get("exp", 0) or 0)
    before_rep = _rep(user, faction_id)
    user["balance"] = before_balance + food
    user["exp"] = before_exp + exp
    root["factions"][faction_id] = before_rep + base_rep
    opposed = str(faction.get("opposed", ""))
    if opposed and _rep(user, opposed) > 0:
        root["factions"][opposed] = max(0, _rep(user, opposed) - (2 if period == "weekly" else 1))
    npc_name = _apply_relation(user, faction_id, base_rep)
    world = _world_state(world_data, guild_id, save_data)
    metrics = world.get("metrics") if isinstance(world, MutableMapping) else None
    metric = str(faction.get("metric", "hope"))
    world_change = 0
    if isinstance(metrics, MutableMapping):
        world_change = 2 if period == "weekly" else 1
        current = int(metrics.get(metric, 50) or 50)
        if metric == "tension" and faction_id == "market":
            metrics[metric] = min(100, current + world_change)
        elif metric == "tension" and faction_id == "cult":
            metrics[metric] = min(100, current + world_change * 2)
        else:
            metrics[metric] = min(100, current + world_change)
    contract_id = str(contract.get("id"))
    root["completed"][contract_id] = int(datetime.now().timestamp())
    root["active"].pop(contract_id, None)
    history = root["history"]
    history.append({
        "type": "complete", "at": int(datetime.now().timestamp()), "id": contract_id,
        "period": period, "week": contract.get("week"), "faction": faction_id,
        "food": food, "exp": exp, "rep": base_rep,
    })
    del history[:-120]
    save_data()
    title = _t(locale, str(contract.get("ko")), str(contract.get("en")))
    embed = discord.Embed(title=_t(locale, f"✅ 의뢰 완료 — {title}", f"✅ Contract Complete — {title}"), color=0x2ECC71)
    embed.add_field(name=_t(locale, "🎁 획득·소모", "🎁 Gains & Costs"), value=_t(locale, f"식량 +{food:,}\nEXP +{exp:,}\n{faction['emoji']} {faction['ko']} 평판 +{base_rep}", f"Supplies +{food:,}\nEXP +{exp:,}\n{faction['emoji']} {faction['en']} reputation +{base_rep}"), inline=False)
    embed.add_field(name=_t(locale, "📊 변화", "📊 Changes"), value=f"{before_balance:,} → **{int(user['balance']):,}**\nEXP {before_exp:,} → **{int(user['exp']):,}**\nREP {before_rep} → **{_rep(user, faction_id)}**", inline=False)
    changes = []
    if npc_name:
        changes.append(_t(locale, f"{npc_name} 신뢰·호감 상승", "Related NPC trust and affinity increased"))
    if world_change:
        changes.append(_t(locale, f"세계 지표 `{metric}` +{world_change}", f"World metric `{metric}` +{world_change}"))
    embed.add_field(name=_t(locale, "🌍 세계·인연 반영", "🌍 World & Bond Effects"), value="\n".join(changes) or "-", inline=False)
    embed.add_field(name=_t(locale, "🔓 다음 단계", "🔓 Next Unlock"), value=_t(locale, f"현재 등급: **{_rep_tier(locale, _rep(user, faction_id))}**", f"Current tier: **{_rep_tier(locale, _rep(user, faction_id))}**"), inline=False)
    embed.set_footer(text=_t(locale, "다음 행동: 의뢰소 · 생산센터 · NPC 인연 · 솔로 원정", "Next: Contract Office · Production Center · NPC Bonds · Solo Expedition"))
    return _safe_embed(embed)


class FusionActionButton(discord.ui.Button):
    def __init__(self, owner: "FusionView", command_names: Sequence[str], label_ko: str, label_en: str, emoji: str, *, args: Sequence[str] = (), style: discord.ButtonStyle = discord.ButtonStyle.secondary, row: int = 0) -> None:
        super().__init__(label=_t(owner.locale, label_ko, label_en)[:80], emoji=emoji, style=style, row=row)
        self.owner_view = owner
        self.command_names = tuple(command_names)
        self.args = tuple(args)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        command = next((view.bot.get_command(name) for name in self.command_names if view.bot.get_command(name) is not None), None)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결된 명령을 찾지 못했습니다.", "The linked command is unavailable."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name, *self.args)


class FusionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, actions: Sequence[Tuple[Sequence[str], str, str, str, Sequence[str], discord.ButtonStyle]]) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        for index, (commands_, ko, en, emoji, args, style) in enumerate(actions[:10]):
            self.add_item(FusionActionButton(self, commands_, ko, en, emoji, args=args, style=style, row=index // 5))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 패널은 실행자만 사용할 수 있습니다.", "Only the opener can use this panel."), ephemeral=True)
        return False


def _terminal_view(bot: commands.Bot, owner_id: int, locale: str) -> FusionView:
    return FusionView(bot, owner_id, locale, (
        (("스토리나침반", "storycompass"), "스토리 계속", "Continue Story", "📖", (), discord.ButtonStyle.success),
        (("의뢰소", "contractoffice"), "오늘의 의뢰", "Contracts", "📜", (), discord.ButtonStyle.primary),
        (("솔로원정", "lonesurvivor"), "원정 출발", "Expedition", "🌑", (), discord.ButtonStyle.primary),
        (("생산센터", "productioncenter"), "제작·도시", "Production", "⚙️", (), discord.ButtonStyle.primary),
        (("인연", "bonds"), "NPC 인연", "NPC Bonds", "💞", (), discord.ButtonStyle.secondary),
    ))


def _production_view(bot: commands.Bot, owner_id: int, locale: str) -> FusionView:
    return FusionView(bot, owner_id, locale, (
        (("채집", "gather"), "재료 획득", "Gather", "⛏️", (), discord.ButtonStyle.success),
        (("가방", "bag", "인벤토리"), "가방", "Inventory", "🎒", (), discord.ButtonStyle.primary),
        (("제작", "craft"), "제작", "Craft", "🔨", (), discord.ButtonStyle.primary),
        (("도시꾸미기", "citydecorate"), "도시 배치", "City Placement", "🏙️", (), discord.ButtonStyle.primary),
        (("재료용도", "materialuses"), "재료 사용처", "Material Uses", "🧰", (), discord.ButtonStyle.secondary),
    ))


def _contract_view(bot: commands.Bot, owner_id: int, locale: str) -> FusionView:
    return FusionView(bot, owner_id, locale, (
        (("의뢰수락", "contractaccept"), "1번 수락", "Accept #1", "1️⃣", ("1",), discord.ButtonStyle.success),
        (("의뢰수락", "contractaccept"), "2번 수락", "Accept #2", "2️⃣", ("2",), discord.ButtonStyle.success),
        (("의뢰수락", "contractaccept"), "3번 수락", "Accept #3", "3️⃣", ("3",), discord.ButtonStyle.success),
        (("의뢰진행", "contractprogress"), "진행 확인", "Check Progress", "✅", (), discord.ButtonStyle.primary),
        (("세력평판", "factionreputation"), "세력 평판", "Faction Rep", "🏴", (), discord.ButtonStyle.secondary),
    ))


def _terminal_embed(locale: str, user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> discord.Embed:
    target, story = _story_line(locale, user)
    world = _world_state(world_data, guild_id, save_data)
    event = world.get("event", {}) if isinstance(world.get("event"), Mapping) else {}
    event_title = str(event.get("title_en" if locale == "en" else "title_ko", "-"))
    risks = world.get("risks", {}) if isinstance(world.get("risks"), Mapping) else {}
    highest = max(((str(k), int(v or 0)) for k, v in risks.items()), key=lambda x: x[1], default=("-", 0))
    root = _root(user)
    active = root.get("active", {}) if isinstance(root.get("active"), Mapping) else {}
    effects = _city_effects(world_data, guild_id)
    try:
        from apocalypse_bot.commands import v1730_connected_survival_loop as connected
        bond = connected._best_bond(locale, user, world)
    except Exception:
        bond = _t(locale, "인연 정보 없음", "No bond data")
    embed = discord.Embed(title=_t(locale, "📡 ABADDON 생존 단말기", "📡 ABADDON Survivor Terminal"), description=_t(locale, "현재 상황과 다음 행동을 하나의 화면에서 연결합니다.", "Connects your current state to the next useful action."), color=0x3949AB)
    embed.add_field(name=_t(locale, "📖 현재 스토리", "📖 Current Story"), value=f"{story}\n`!{target}`", inline=False)
    embed.add_field(name=_t(locale, "🌍 오늘의 세계", "🌍 Today's World"), value=_t(locale, f"**{event_title}** · 최고 위험 `{highest[0]}` {highest[1]}% · 시장 {int(world.get('market_index', 100) or 100)}%", f"**{event_title}** · Highest risk `{highest[0]}` {highest[1]}% · Market {int(world.get('market_index', 100) or 100)}%"), inline=False)
    embed.add_field(name=_t(locale, "📜 진행 중 의뢰", "📜 Active Contracts"), value=_t(locale, f"**{len(active)}/3** · `!의뢰소`에서 오늘 의뢰 확인", f"**{len(active)}/3** · Open `!contractoffice`"), inline=True)
    embed.add_field(name=_t(locale, "💞 관계 변화", "💞 Bond Focus"), value=bond, inline=False)
    active_effects = [f"{k} +{v}%" for k, v in effects.items() if int(v or 0) > 0]
    embed.add_field(name=_t(locale, "🏙️ 적용 중 도시 효과", "🏙️ Active City Effects"), value=" · ".join(active_effects) or _t(locale, "활성 효과 없음", "No active effects"), inline=False)
    embed.add_field(name=_t(locale, "🧭 지금 추천", "🧭 Recommended Now"), value=_t(locale, "스토리를 이어가거나 오늘의 의뢰를 수락한 뒤 원정·생산·NPC 행동으로 연결하세요.", "Continue the story or accept a contract, then flow into expedition, production or NPC actions."), inline=False)
    return _safe_embed(embed)


def _contract_board_embed(locale: str, user: MutableMapping[str, Any], world_data: MutableMapping[str, Any], guild_id: int, save_data: Callable[[], None]) -> discord.Embed:
    rows = _board(world_data, guild_id, save_data)
    root = _root(user)
    active = root.get("active", {}) if isinstance(root.get("active"), Mapping) else {}
    completed = root.get("completed", {}) if isinstance(root.get("completed"), Mapping) else {}
    embed = discord.Embed(title=_t(locale, "📜 BLACK CITY 생존 의뢰소", "📜 BLACK CITY Survival Contract Office"), description=_t(locale, "살아 있는 세계 상태에 맞춰 일일 3개·주간 1개 의뢰가 생성됩니다.", "Generates 3 daily and 1 weekly contract from the living world state."), color=0x8E44AD)
    for item in rows:
        faction = FACTIONS[str(item["faction"])]
        contract_id = str(item["id"])
        current = active.get(contract_id) if isinstance(active, Mapping) else None
        done = contract_id in completed
        marker = "✅" if done else "🟡" if isinstance(current, Mapping) else "⬜"
        progress_text = ""
        if isinstance(current, Mapping):
            p, target = _progress(item, current, user, world_data, guild_id, save_data)
            progress_text = _t(locale, f"\n진행 **{min(p, target)}/{target}**", f"\nProgress **{min(p, target)}/{target}**")
        title = _t(locale, str(item["ko"]), str(item["en"]))
        desc = _t(locale, str(item["desc_ko"]), str(item["desc_en"]))
        reward = _t(locale, f"식량 {int(item['food']):,} · EXP {int(item['exp']):,} · 평판", f"Supplies {int(item['food']):,} · EXP {int(item['exp']):,} · Reputation")
        embed.add_field(name=f"{marker} {item['slot']}. {title}", value=f"{faction['emoji']} **{_t(locale, faction['ko'], faction['en'])}**\n{desc}\n🎁 {reward}{progress_text}", inline=False)
    embed.set_footer(text=_t(locale, "수락: !의뢰수락 번호 · 확인: !의뢰진행 · 최대 동시 3개", "Accept: !contractaccept number · Check: !contractprogress · Max 3 active"))
    return _safe_embed(embed)


def _production_embed(locale: str, user: MutableMapping[str, Any], world_data: Mapping[str, Any], guild_id: int) -> discord.Embed:
    effects = _city_effects(world_data, guild_id)
    embed = discord.Embed(title=_t(locale, "⚙️ ABADDON 생산센터", "⚙️ ABADDON Production Center"), description=_t(locale, "채집 → 가방 → 제작 → 도시 배치를 한 흐름으로 정리합니다.", "Organizes gathering → inventory → crafting → city placement into one flow."), color=0x00897B)
    embed.add_field(name=_t(locale, "⛏️ 보유 재료", "⛏️ Materials"), value="\n".join(_material_rows(user, locale)) or "-", inline=False)
    embed.add_field(name=_t(locale, "🧰 재료 활용", "🧰 Material Uses"), value=_t(locale, "재료명을 `!재료용도 고철`처럼 조회하면 제작·도시·NPC·원정 사용처가 표시됩니다.", "Use `!materialuses scrap` to see crafting, city, NPC and expedition uses."), inline=False)
    live = [f"{k} +{v}%" for k, v in effects.items() if int(v or 0) > 0]
    embed.add_field(name=_t(locale, "🏙️ 도시 적용 효과", "🏙️ City Effects"), value=" · ".join(live) or _t(locale, "효과 부품 없음", "No effect-bearing parts"), inline=False)
    embed.add_field(name=_t(locale, "🧭 생산 흐름", "🧭 Production Flow"), value=_t(locale, "재료 획득 → 가방 확인 → 제작 → 도시 배치 → 도시 효과 확인", "Gather → Inventory → Craft → Place in city → Review city effects"), inline=False)
    return _safe_embed(embed)


def _faction_embed(locale: str, user: MutableMapping[str, Any]) -> discord.Embed:
    embed = discord.Embed(title=_t(locale, "🏴 세력 평판", "🏴 Faction Reputation"), description=_t(locale, "의뢰 선택은 세력·NPC·시장·세계 지표에 함께 영향을 줍니다.", "Contract choices jointly affect factions, NPCs, market and world metrics."), color=0xC0392B)
    for faction_id, spec in FACTIONS.items():
        value = _rep(user, faction_id)
        next_tier = next((tier for tier in REP_TIERS if tier[0] > value), None)
        next_text = _t(locale, f"다음 등급까지 {next_tier[0] - value}" if next_tier else "최고 등급", f"{next_tier[0] - value} to next tier" if next_tier else "Maximum tier")
        embed.add_field(name=f"{spec['emoji']} {_t(locale, spec['ko'], spec['en'])}", value=f"**{value}** · {_rep_tier(locale, value)}\n{_t(locale, spec['desc_ko'], spec['desc_en'])}\n{next_text}", inline=False)
    return _safe_embed(embed)


def register_v1740_system_fusion(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del user_data
    if getattr(bot, "_abaddon_v1740_registered", False):
        return
    bot._abaddon_v1740_registered = True

    # `의뢰수락` was historically an alias of the delivery-contract command.
    # Preserve that command through `!계약수락` / `!납품계약`, but release the
    # generic alias for the new unified survival contract office.
    legacy_delivery = bot.get_command("계약수락")
    if legacy_delivery is not None and "의뢰수락" in list(getattr(legacy_delivery, "aliases", []) or []):
        legacy_delivery.aliases = [alias for alias in legacy_delivery.aliases if alias != "의뢰수락"]
        if getattr(bot, "all_commands", {}).get("의뢰수락") is legacy_delivery:
            bot.all_commands.pop("의뢰수락", None)

    async def survival_terminal(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        await ctx.send(embed=_terminal_embed(locale, user, world_data, gid, save_data), view=_safe_view(_terminal_view(bot, ctx.author.id, locale)))

    # Upgrade the preserved `!단말기` command in place.  Its existing Korean
    # aliases (`!생존단말기`, `!통합단말기`) continue to work, and English-only
    # aliases are added without creating a duplicate command object.
    terminal_command = bot.get_command("단말기") or bot.get_command("생존단말기")
    if terminal_command is not None:
        terminal_command.callback = survival_terminal
        terminal_command.help = "스토리·세계·의뢰·원정·NPC·생산·도시를 한 화면에서 연결합니다."
        terminal_command.description = terminal_command.help
        for alias in ("survivalterminal", "terminalhub", "fusionhub"):
            if bot.get_command(alias) is None:
                terminal_command.aliases.append(alias)
                bot.all_commands[alias] = terminal_command

    @bot.command(name="생산센터", aliases=["productioncenter", "productionhub", "craftinghub"], help="채집·가방·제작·재료 사용처·도시 배치를 한 화면에서 연결합니다.")
    async def production_center(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        await ctx.send(embed=_production_embed(locale, user, world_data, gid), view=_safe_view(_production_view(bot, ctx.author.id, locale)))

    @bot.command(name="의뢰소", aliases=["contractoffice", "missionoffice", "survivalcontracts"], help="살아 있는 세계 상태에 맞춘 일일 3개·주간 1개 생존 의뢰를 확인합니다.")
    async def contract_office(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        await ctx.send(embed=_contract_board_embed(locale, user, world_data, gid, save_data), view=_safe_view(_contract_view(bot, ctx.author.id, locale)))

    @bot.command(name="의뢰수락", aliases=["contractaccept", "acceptcontract"], help="의뢰소 번호 또는 의뢰 ID를 입력해 최대 3개까지 수락합니다.")
    async def contract_accept(ctx: commands.Context, selector: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        rows = _board(world_data, gid, save_data)
        token = str(selector or "").strip()
        selected = None
        if token.isdigit():
            selected = next((row for row in rows if int(row["slot"]) == int(token)), None)
        else:
            selected = next((row for row in rows if str(row["id"]).casefold() == token.casefold()), None)
        if selected is None:
            await ctx.send(_t(locale, "`!의뢰수락 1`처럼 1~4번을 입력하세요.", "Use `!contractaccept 1` with a number from 1 to 4."))
            return
        root = _root(user)
        contract_id = str(selected["id"])
        if contract_id in root["completed"]:
            await ctx.send(_t(locale, "이미 완료한 의뢰입니다.", "This contract is already complete.")); return
        if contract_id in root["active"]:
            await ctx.send(_t(locale, "이미 진행 중인 의뢰입니다.", "This contract is already active.")); return
        if len(root["active"]) >= 3:
            await ctx.send(_t(locale, "동시에 진행할 수 있는 의뢰는 최대 3개입니다.", "You can have at most three active contracts.")); return
        root["active"][contract_id] = {"contract": dict(selected), "snapshot": _snapshot(user, world_data, gid, save_data), "accepted_at": int(datetime.now().timestamp())}
        save_data()
        faction = FACTIONS[str(selected["faction"])]
        await ctx.send(_t(locale, f"📜 **{selected['ko']}** 의뢰를 수락했습니다.\n{faction['emoji']} {faction['ko']} · 진행 확인 `!의뢰진행`", f"📜 Accepted **{selected['en']}**.\n{faction['emoji']} {faction['en']} · Check with `!contractprogress`"))

    @bot.command(name="의뢰진행", aliases=["contractprogress", "checkcontracts"], help="진행 중 의뢰의 현재 진행도를 검사하고 완료 가능한 보상을 정산합니다.")
    async def contract_progress(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        gid = int(ctx.guild.id if ctx.guild else 0)
        root = _root(user)
        active_map = root.get("active", {}) if isinstance(root.get("active"), MutableMapping) else {}
        if not active_map:
            await ctx.send(_t(locale, "진행 중인 의뢰가 없습니다. `!의뢰소`를 열어보세요.", "No active contracts. Open `!contractoffice`.")); return
        completed_embeds: List[discord.Embed] = []
        lines: List[str] = []
        for contract_id, active in list(active_map.items()):
            if not isinstance(active, MutableMapping):
                continue
            contract = active.get("contract", {}) if isinstance(active.get("contract"), Mapping) else {}
            progress, target = _progress(contract, active, user, world_data, gid, save_data)
            title = _t(locale, str(contract.get("ko", contract_id)), str(contract.get("en", contract_id)))
            if progress >= target:
                completed_embeds.append(_complete_contract(user, contract, active, world_data, gid, save_data, locale))
            else:
                lines.append(f"⬜ **{title}** · {min(progress, target)}/{target}")
        if completed_embeds:
            for embed in completed_embeds:
                await ctx.send(embed=embed, view=_safe_view(_terminal_view(bot, ctx.author.id, locale)))
        if lines:
            await ctx.send(embed=_safe_embed(discord.Embed(title=_t(locale, "📊 의뢰 진행 상황", "📊 Contract Progress"), description="\n".join(lines), color=0xF39C12)))

    @bot.command(name="의뢰포기", aliases=["contractabandon", "abandoncontract"], help="진행 중 의뢰 번호 또는 ID를 입력해 포기합니다.")
    async def contract_abandon(ctx: commands.Context, selector: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        root = _root(user)
        token = str(selector or "").strip()
        matches = []
        for contract_id, active in root["active"].items():
            contract = active.get("contract", {}) if isinstance(active, Mapping) else {}
            if token == str(contract.get("slot")) or token.casefold() == str(contract_id).casefold():
                matches.append(contract_id)
        if not matches:
            await ctx.send(_t(locale, "포기할 진행 중 의뢰를 찾지 못했습니다.", "Active contract not found.")); return
        for contract_id in matches:
            active = root["active"].pop(contract_id)
            root["history"].append({"type": "abandon", "id": contract_id, "at": int(datetime.now().timestamp()), "period": active.get("contract", {}).get("period") if isinstance(active, Mapping) else ""})
        del root["history"][:-120]
        save_data()
        await ctx.send(_t(locale, "🗑️ 의뢰를 포기했습니다. 보상과 평판 변화는 없습니다.", "🗑️ Contract abandoned. No reward or reputation change."))

    @bot.command(name="의뢰기록", aliases=["contracthistory", "missionhistory"], help="최근 의뢰 완료·포기 기록과 주간 완료 횟수를 확인합니다.")
    async def contract_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = _safe_user(get_user, ctx.author.id)
        history = _root(user).get("history", [])
        lines = []
        for row in reversed(history[-15:]):
            if not isinstance(row, Mapping):
                continue
            icon = "✅" if row.get("type") == "complete" else "🗑️"
            lines.append(f"{icon} `{row.get('id','-')}` · <t:{int(row.get('at',0) or 0)}:R>")
        embed = discord.Embed(title=_t(locale, "📚 생존 의뢰 기록", "📚 Survival Contract History"), description="\n".join(lines) or _t(locale, "기록이 없습니다.", "No records yet."), color=0x5D6D7E)
        embed.add_field(name=_t(locale, "이번 주 완료", "Completed This Week"), value=str(_weekly_completed(_root(user), _week_key())), inline=True)
        await ctx.send(embed=_safe_embed(embed))

    async def faction_reputation(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        await ctx.send(embed=_faction_embed(_ctx_locale(bot, ctx), _safe_user(get_user, ctx.author.id)))

    # Reuse the preserved faction `!평판` command and its `!세력평판` alias.
    reputation_command = bot.get_command("평판") or bot.get_command("세력평판")
    if reputation_command is not None:
        reputation_command.callback = faction_reputation
        reputation_command.help = "생존 의뢰로 변하는 5개 세력 평판과 현재 등급을 확인합니다."
        reputation_command.description = reputation_command.help
        for alias in ("factionreputation", "reputationboard"):
            if bot.get_command(alias) is None:
                reputation_command.aliases.append(alias)
                bot.all_commands[alias] = reputation_command

    @bot.command(name="1740융합검수", aliases=["v1740fusionaudit", "systemfusionaudit"], help="생존단말기·의뢰소·생산센터·세력평판 연결을 검사합니다.")
    async def fusion_audit(ctx: commands.Context, detail: str = "") -> None:
        locale = _ctx_locale(bot, ctx)
        required = ["생존단말기", "의뢰소", "의뢰수락", "의뢰진행", "의뢰포기", "의뢰기록", "생산센터", "세력평판"]
        checks = [(name, bot.get_command(name) is not None) for name in required]
        checks.extend([
            ("Five faction definitions", len(FACTIONS) == 5),
            ("Three daily + one weekly board", len(_board(world_data, int(ctx.guild.id if ctx.guild else 0), save_data)) == 4),
            ("Legacy connected hub preserved", bot.get_command("연결허브") is not None),
            ("Legacy survivor hub preserved", bot.get_command("생존허브") is not None),
            ("Casino / Gambling separation", bot.get_command("카지노") is not None and bot.get_command("도박정보") is not None),
            ("Korean / English entry points", bot.get_command("생존단말기") is not None and bot.get_command("survivalterminal") is not None),
        ])
        ok = all(value for _name, value in checks)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.4 융합 검수", "🧪 ABADDON v17.4 Fusion Audit"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if ok else 0xE74C3C)
        if detail:
            embed.add_field(name=_t(locale, "통합 범위", "Fusion Scope"), value="Survivor Terminal → Contracts → Factions/NPC → Production → City/World → Next Actions", inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1740통합검수", aliases=["v1740audit", "1740audit"], help="v17.4 시스템 융합과 기존 핵심 기능 보존을 통합 검사합니다.")
    async def audit_1740(ctx: commands.Context, detail: str = "") -> None:
        locale = _ctx_locale(bot, ctx)
        entries = command_hub._build_registry(bot)
        checks = [
            ("Survivor Terminal category", any(e.group == "terminal" and e.name == "생존단말기" for e in entries)),
            ("Contract Office category", any(e.group == "contracts" and e.name == "의뢰소" for e in entries)),
            ("Production Center category", any(e.group == "production" and e.name == "생산센터" for e in entries)),
            ("Faction reputation category", any(e.group == "factions" and e.name == "세력평판" for e in entries)),
            ("Story Season 1–6 preserved", all(bot.get_command(name) is not None for name in ("스토리", "시즌6")) if bot.get_command("스토리") else bot.get_command("시즌6") is not None),
            ("Solo expedition preserved", bot.get_command("솔로원정") is not None),
            ("Living world preserved", bot.get_command("살아있는세계") is not None),
            ("NPC bonds preserved", bot.get_command("인연") is not None),
            ("City workshop preserved", bot.get_command("도시꾸미기") is not None),
            ("Casino / Gambling preserved", bot.get_command("카지노") is not None and bot.get_command("도박정보") is not None),
        ]
        ok = all(value for _name, value in checks)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.4.0 통합 검수", "🧪 ABADDON v17.4.0 Integration Audit"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if ok else 0xE74C3C)
        if detail:
            embed.add_field(name=_t(locale, "보존 원칙", "Preservation"), value=_t(locale, "기존 명령·저장 데이터 삭제 0건 · 신규 통합 허브와 의뢰 저장만 추가", "0 legacy commands or saves removed · only fusion hubs and contract state added"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1740(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = discord.Embed(title="🔗 ABADDON v17.4.0 · SYSTEM FUSION", description=_t(locale, "흩어진 기능을 생존단말기·의뢰소·생산센터 중심으로 재정리했습니다.", "Reorganized scattered features around Survivor Terminal, Contract Office and Production Center."), color=0x673AB7)
            embed.add_field(name=_t(locale, "📡 생존단말기", "📡 Survivor Terminal"), value=_t(locale, "스토리·세계·의뢰·원정·NPC·도시 효과와 다음 행동을 한 화면에 표시합니다.", "Shows story, world, contracts, expedition, NPC bonds, city effects and next actions in one screen."), inline=False)
            embed.add_field(name=_t(locale, "📜 생존 의뢰소", "📜 Survival Contract Office"), value=_t(locale, "세계 상태 기반 일일 3개·주간 1개 의뢰, 진행 확인, 완료 결과와 세력 평판을 추가했습니다.", "Adds 3 daily + 1 weekly world-driven contracts, progress checks, result summaries and faction reputation."), inline=False)
            embed.add_field(name=_t(locale, "⚙️ 생산센터", "⚙️ Production Center"), value=_t(locale, "채집·가방·제작·재료 사용처·도시 배치를 한 흐름으로 연결했습니다.", "Connects gathering, inventory, crafting, material uses and city placement."), inline=False)
            embed.add_field(name=_t(locale, "🏴 세력·인연·세계", "🏴 Factions, Bonds & World"), value=_t(locale, "의뢰 결과가 세력 평판, 관련 NPC 관계와 살아 있는 세계 지표에 반영됩니다.", "Contract results affect faction reputation, related NPC bonds and living-world metrics."), inline=False)
            embed.add_field(name=_t(locale, "🧪 점검", "🧪 Checks"), value="`!1740융합검수 상세` · `!1740통합검수 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건 · KO/EN 화면 분리 유지", "0 legacy features or saves removed · KO/EN UI remains separated"))
            await ctx.send(embed=_safe_embed(embed))
        patch.callback = patch_v1740
        patch.help = "ABADDON v17.4.0 최신 패치노트입니다."
        patch.description = patch.help

    test = bot.get_command("테스트")
    if test is not None:
        async def test_v1740(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            locale = _ctx_locale(bot, ctx)
            required = ["생존단말기", "의뢰소", "생산센터", "세력평판", "1740융합검수", "1740통합검수"]
            checks = [(name, bot.get_command(name) is not None) for name in required]
            checks.extend([("Legacy story/world/NPC/city", all(bot.get_command(name) is not None for name in ("시즌6", "살아있는세계", "인연", "도시꾸미기"))), ("KO/EN aliases", bot.get_command("survivalterminal") is not None and bot.get_command("contractoffice") is not None)])
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.4 최신 테스트", "🧪 ABADDON v17.4 Latest Test"), description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks), color=0x2ECC71 if all(value for _name, value in checks) else 0xE74C3C)
            if str(mode).casefold() in {"상세", "detail", "full"}:
                embed.add_field(name=_t(locale, "범위", "Scope"), value="Terminal · Contracts · Factions · NPC · Production · City · World · Command Hub · KO/EN", inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback = test_v1740
        test.help = "v17.4 시스템 융합 최신 범위를 검사합니다."
        test.description = test.help

    entries = command_hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {entry.qualified_name: entry for entry in entries})
    guide.append({
        "id": "v1740_system_fusion", "emoji": "🔗", "title": "v17.4 SYSTEM FUSION",
        "hint": "생존단말기·의뢰소·생산센터를 중심으로 기존 기능을 통합하고 세력·NPC·세계 변화를 연결",
        "commands": [
            "!생존단말기 · !의뢰소 · !의뢰수락 · !의뢰진행 · !의뢰기록",
            "!생산센터 · !세력평판",
            "!1740융합검수 상세 · !1740통합검수 상세",
        ],
    })
    print(f"[ABADDON v{VERSION}] system fusion registered: commands={len(entries)} factions={len(FACTIONS)} contracts={len(CONTRACT_TEMPLATES)}", flush=True)


__all__ = ["register_v1740_system_fusion", "FACTIONS", "CONTRACT_TEMPLATES", "_root", "_board"]
