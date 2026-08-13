from __future__ import annotations

"""ABADDON v16.8.0 LONE SURVIVOR.

A fully additive, button-driven solo roguelite expedition that connects the
existing apocalypse RPG systems without deleting or replacing legacy content.

Highlights
- 6–9 stage solo runs with deterministic seed codes;
- seven setting-linked regions from Season 1 through NEON ABYSS;
- four difficulties, five recruitable NPC roles and a weekly mutation region;
- combat, hazards, supplies, NPC encounters, relics, city blueprints and bosses;
- save/resume after restart, partial retreat rewards and non-punitive rescue;
- codex, records and clear result summaries showing gains and state changes;
- Korean-only or English-only UI selected by the existing global locale system.
"""

import hashlib
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _invoke_command

VERSION = "16.8.0"
ROOT_KEY = "v1680_lone_survivor"
SEED_RE = re.compile(r"^[A-Z0-9]{4,12}$")


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(ctx_or_interaction: Any) -> str:
    try:
        user = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None) or ctx_or_interaction
        guild = getattr(ctx_or_interaction, "guild", None)
        guild_id = int(getattr(ctx_or_interaction, "guild_id", 0) or getattr(guild, "id", 0) or 0)
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(user.id), guild_id)
    except Exception:
        return "ko"


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    if maximum is not None:
        result = min(int(maximum), result)
    return result


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> Optional[MutableMapping[str, Any]]:
    row = get_user(int(user_id))
    return row if isinstance(row, MutableMapping) else None


def _root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault(ROOT_KEY, {})
    if not isinstance(row, MutableMapping):
        row = {}
        user[ROOT_KEY] = row
    row.setdefault("schema", 1)
    row.setdefault("active", None)
    row.setdefault("default_difficulty", "survivor")
    row.setdefault("default_companions", ["scout", "medic"])
    row.setdefault("preferred_seed", "")
    row.setdefault("unlocked_blueprints", [])
    row.setdefault("records", {
        "runs": 0, "victories": 0, "retreats": 0, "rescues": 0,
        "best_stage": 0, "best_score": 0, "total_food": 0, "total_exp": 0,
        "zones": {}, "recent": [],
    })
    row.setdefault("codex", {
        "events": [], "enemies": [], "npcs": [], "endings": [],
        "relics": [], "blueprints": [],
    })
    row.setdefault("settings", {"result_detail": True})
    return row


def _list_add_unique(target: MutableMapping[str, Any], key: str, value: str, limit: int = 200) -> bool:
    rows = target.setdefault(key, [])
    if not isinstance(rows, list):
        rows = []
        target[key] = rows
    value = str(value)
    if value in rows:
        return False
    rows.append(value)
    del rows[:-limit]
    return True


@dataclass(frozen=True)
class Difficulty:
    key: str
    ko: str
    en: str
    stages: int
    damage: float
    reward: float
    rescue_keep: float
    emoji: str


DIFFICULTIES: Dict[str, Difficulty] = {
    "survivor": Difficulty("survivor", "생존자", "Survivor", 6, 0.78, 0.85, 0.45, "🌱"),
    "veteran": Difficulty("veteran", "베테랑", "Veteran", 7, 1.00, 1.00, 0.35, "🪖"),
    "nightmare": Difficulty("nightmare", "악몽", "Nightmare", 8, 1.28, 1.45, 0.28, "☠️"),
    "abyss": Difficulty("abyss", "심연", "Abyss", 9, 1.58, 1.95, 0.22, "🟣"),
}

DIFFICULTY_ALIASES = {
    "생존자": "survivor", "쉬움": "survivor", "easy": "survivor", "survivor": "survivor",
    "베테랑": "veteran", "보통": "veteran", "normal": "veteran", "veteran": "veteran",
    "악몽": "nightmare", "어려움": "nightmare", "hard": "nightmare", "nightmare": "nightmare",
    "심연": "abyss", "최고": "abyss", "abyss": "abyss", "extreme": "abyss",
}


@dataclass(frozen=True)
class Zone:
    key: str
    ko: str
    en: str
    subtitle_ko: str
    subtitle_en: str
    min_level: int
    emoji: str
    enemies_ko: Tuple[str, ...]
    enemies_en: Tuple[str, ...]
    relic_ko: str
    relic_en: str
    blueprint: str


ZONES: Dict[str, Zone] = {
    "black_frequency": Zone(
        "black_frequency", "폐허 도시 · 검은 주파수", "Ruined City · Black Frequency",
        "시즌 1 신호를 따라 지하 중계소로 향합니다.", "Follow the Season 1 signal toward the underground relay.",
        1, "📻", ("굶주린 감염자", "전파 추적자", "검은 중계소 수문장"),
        ("Starved Infected", "Signal Stalker", "Black Relay Gatekeeper"), "깨진 군용 송신기", "Broken Military Transmitter", "neon_gate",
    ),
    "white_ark": Zone(
        "white_ark", "백색 방주 · 설원 항로", "White Ark · Frozen Route",
        "눈보라 속 방주 신호와 실종 탐사대를 추적합니다.", "Track the ark signal and a missing patrol through the blizzard.",
        10, "🚢", ("빙결 감염체", "설원 약탈자", "백색 방주의 파수꾼"),
        ("Frozen Infected", "Snow Raider", "White Ark Sentinel"), "동결 항해일지", "Frozen Voyage Log", "harbor",
    ),
    "end_throne": Zone(
        "end_throne", "종말의 왕좌 · 오염 지대", "Throne of the End · Contamination Zone",
        "왕좌를 둘러싼 변이 군락의 중심부를 돌파합니다.", "Break through the mutation hive surrounding the throne.",
        20, "👑", ("포자 군체", "왕좌 수호병", "종말의 왕좌 대행자"),
        ("Spore Colony", "Throne Guard", "Harbinger of the End"), "왕좌의 검은 파편", "Black Throne Fragment", "gold_statue",
    ),
    "twilight_line": Zone(
        "twilight_line", "황혼선 · 붕괴 철도", "Twilight Line · Collapsed Railway",
        "멈추지 않는 황혼선의 마지막 객차를 탐색합니다.", "Search the final carriage of the never-ending Twilight Line.",
        28, "🚂", ("선로 망령", "황혼 승무원", "종착역 기관장"),
        ("Rail Wraith", "Twilight Crew", "Terminal Engineer"), "황혼선 황동표", "Twilight Brass Ticket", "neon_train",
    ),
    "ashen_front": Zone(
        "ashen_front", "잿빛 연합전선", "Ashen Coalition Front",
        "붕괴 직전의 전선을 지키며 세력 생존자를 구조합니다.", "Hold a collapsing front and rescue faction survivors.",
        34, "📡", ("전선 돌격체", "잿빛 저격수", "연합전선 파괴자"),
        ("Frontline Charger", "Ashen Sniper", "Coalition Breaker"), "잿빛 지휘 인장", "Ashen Command Seal", "faction_banner",
    ),
    "black_city": Zone(
        "black_city", "BLACK CITY · 지하 암시장", "BLACK CITY · Underground Market",
        "도시 아래 비밀 거래망과 감옥 통로를 잠입합니다.", "Infiltrate hidden trade routes and prison passages beneath the city.",
        12, "🏙️", ("암시장 추적자", "교도소 사냥개", "검은 도시 집행자"),
        ("Market Tracker", "Prison Hound", "Black City Enforcer"), "도시 거래 원장", "City Trade Ledger", "demon_market",
    ),
    "neon_abyss": Zone(
        "neon_abyss", "NEON ABYSS · 차원 균열", "NEON ABYSS · Dimensional Rift",
        "차원 파장을 고정하고 심연 도시의 균열핵을 회수합니다.", "Stabilize the rift and recover the abyss city's dimensional core.",
        30, "🌀", ("차원 잔상", "균열 포식자", "심연의 분신"),
        ("Dimensional Echo", "Rift Devourer", "Avatar of the Abyss"), "차원결정 심장", "Dimensional Crystal Heart", "rift_portal",
    ),
}

ZONE_ALIASES: Dict[str, str] = {}
for _key, _zone in ZONES.items():
    for _alias in {_key, _zone.ko, _zone.en, _zone.ko.split("·")[0].strip(), _zone.en.split("·")[0].strip()}:
        ZONE_ALIASES[_alias.casefold().replace(" ", "")] = _key
ZONE_ALIASES.update({
    "시즌1": "black_frequency", "폐허": "black_frequency", "검은주파수": "black_frequency",
    "시즌2": "white_ark", "방주": "white_ark", "설원": "white_ark",
    "시즌3": "end_throne", "왕좌": "end_throne", "오염지대": "end_throne",
    "시즌4": "twilight_line", "황혼선": "twilight_line", "철도": "twilight_line",
    "시즌5": "ashen_front", "전선": "ashen_front", "잿빛": "ashen_front",
    "블랙시티": "black_city", "blackcity": "black_city", "암시장": "black_city",
    "네온어비스": "neon_abyss", "neonabyss": "neon_abyss", "차원": "neon_abyss",
})


@dataclass(frozen=True)
class Companion:
    key: str
    ko: str
    en: str
    effect_ko: str
    effect_en: str
    emoji: str


COMPANIONS: Dict[str, Companion] = {
    "scout": Companion("scout", "정찰병 유나", "Scout Yuna", "위험 감지·도감 발견률 증가", "Hazard detection and codex discovery", "🧭"),
    "medic": Companion("medic", "의무병 하린", "Medic Harin", "행동 후 소량 치료·감염 억제", "Minor healing and infection control", "🩺"),
    "engineer": Companion("engineer", "기술자 도윤", "Engineer Doyun", "재료·도시 설계도 발견 보정", "Material and city blueprint bonus", "🔧"),
    "gunner": Companion("gunner", "중화기병 제로", "Gunner Zero", "전투 성공률·보스 피해 증가", "Combat success and boss damage", "💥"),
    "negotiator": Companion("negotiator", "교섭가 미라", "Negotiator Mira", "NPC·선택 사건 보상 증가", "NPC and choice-event bonus", "🤝"),
}

COMPANION_ALIASES: Dict[str, str] = {
    "정찰": "scout", "정찰병": "scout", "유나": "scout", "scout": "scout",
    "의무": "medic", "의무병": "medic", "하린": "medic", "medic": "medic",
    "기술": "engineer", "기술자": "engineer", "도윤": "engineer", "engineer": "engineer",
    "중화기": "gunner", "중화기병": "gunner", "제로": "gunner", "gunner": "gunner",
    "교섭": "negotiator", "교섭가": "negotiator", "미라": "negotiator", "negotiator": "negotiator",
}

CITY_PART_LABELS: Dict[str, Tuple[str, str]] = {
    "neon_gate": ("네온 관문", "Neon Gate"),
    "harbor": ("도시 항구", "City Harbor"),
    "gold_statue": ("황금 동상", "Golden Statue"),
    "neon_train": ("네온 열차", "Neon Train"),
    "faction_banner": ("세력 깃발", "Faction Banner"),
    "demon_market": ("악마 시장", "Demon Market"),
    "rift_portal": ("차원문", "Rift Portal"),
}

MATERIALS_KO = ("고철", "약초", "나무", "광석")
MATERIALS_EN = {"고철": "Scrap", "약초": "Herbs", "나무": "Wood", "광석": "Ore"}

NPC_ENCOUNTERS: Dict[str, Tuple[str, str]] = {
    "radio_sera": ("통신병 세라", "Radio Operator Sera"),
    "mechanic_ryu": ("떠돌이 정비사 류", "Wandering Mechanic Ryu"),
    "black_city_guide": ("검은 도시 안내인", "Black City Guide"),
    "search_captain": ("부상당한 수색대장", "Wounded Search Captain"),
}

EVENT_LABELS: Dict[str, Tuple[str, str]] = {
    "hazard:collapse": ("붕괴 지형", "Collapsing Terrain"),
    "supply:sealed_cache": ("폐쇄된 보급함", "Sealed Supply Cache"),
    "camp": ("야영", "Camp"),
    "choice:signal": ("송신기 복구", "Transmitter Repair"),
    "choice:survivors": ("생존자 표식", "Survivor Markings"),
    "choice:memory": ("폐허의 기억", "Ruin Memory"),
    "choice:shortcut": ("위험한 지름길", "Dangerous Shortcut"),
}

ENDING_LABELS: Dict[str, Tuple[str, str]] = {
    "victory": ("귀환 성공", "Returned Successfully"),
    "retreat": ("전략적 철수", "Tactical Retreat"),
    "rescue": ("긴급 구조", "Emergency Rescue"),
}


def _normalize_zone(raw: str) -> Optional[str]:
    token = str(raw or "").strip().casefold().replace(" ", "")
    return ZONE_ALIASES.get(token)


def _normalize_difficulty(raw: str) -> Optional[str]:
    return DIFFICULTY_ALIASES.get(str(raw or "").strip().casefold())


def _normalize_companions(raw: str, fallback: Sequence[str] = ()) -> List[str]:
    tokens = [x.strip().casefold() for x in re.split(r"[,/·+\s]+", str(raw or "")) if x.strip()]
    result: List[str] = []
    for token in tokens:
        key = COMPANION_ALIASES.get(token)
        if key and key not in result:
            result.append(key)
        if len(result) >= 2:
            break
    if not result:
        for key in fallback:
            if key in COMPANIONS and key not in result:
                result.append(key)
            if len(result) >= 2:
                break
    return result[:2]


def _seed_code(raw: str = "") -> str:
    token = re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())[:12]
    if SEED_RE.fullmatch(token):
        return token
    basis = f"{time.time_ns()}:{random.random()}".encode("utf-8")
    return hashlib.sha256(basis).hexdigest()[:8].upper()


def _seed_int(*parts: Any) -> int:
    blob = "|".join(str(x) for x in parts).encode("utf-8")
    return int(hashlib.sha256(blob).hexdigest()[:16], 16)


def _rng(session: Mapping[str, Any], tag: str) -> random.Random:
    return random.Random(_seed_int(session.get("seed", "ABADDON"), session.get("stage", 0), session.get("turn", 0), tag))


def _week_id() -> str:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _weekly_anomaly() -> Dict[str, Any]:
    week = _week_id()
    rng = random.Random(_seed_int("ABADDON-WEEKLY", week))
    zone = rng.choice(list(ZONES.values()))
    mutation = rng.choice((
        ("blood_moon", "핏빛 월식", "Blood Moon", "전투 피해와 보상이 함께 증가합니다.", "Combat damage and rewards both increase.", 1.18, 1.28, "🌕"),
        ("static_storm", "정전기 폭풍", "Static Storm", "탐색 사건과 차원 자원 발견률이 증가합니다.", "Exploration events and dimensional resources are more common.", 1.05, 1.22, "⚡"),
        ("silent_city", "침묵의 도시", "Silent City", "NPC는 드물지만 유물과 설계도가 더 자주 등장합니다.", "NPCs are rare, but relics and blueprints appear more often.", 1.08, 1.30, "🌑"),
        ("survivor_signal", "생존자 구조 신호", "Survivor Rescue Signal", "NPC 조우와 관계 보상이 증가합니다.", "NPC encounters and bond rewards are increased.", 0.96, 1.18, "📡"),
    ))
    return {
        "week": week, "zone": zone.key, "key": mutation[0], "ko": mutation[1], "en": mutation[2],
        "desc_ko": mutation[3], "desc_en": mutation[4], "damage": mutation[5], "reward": mutation[6], "emoji": mutation[7],
    }


def _highest_zone(user: Mapping[str, Any]) -> str:
    level = _safe_int(user.get("level"), 1, 1)
    unlocked = [zone for zone in ZONES.values() if level >= zone.min_level]
    return unlocked[-1].key if unlocked else "black_frequency"


def _equipment_power(user: Mapping[str, Any]) -> int:
    equipment = user.get("equipment") if isinstance(user.get("equipment"), Mapping) else {}
    enhancements = user.get("enhancements") if isinstance(user.get("enhancements"), Mapping) else {}
    equipped = [str(x) for x in equipment.values() if x]
    return len(equipped) * 3 + sum(_safe_int(enhancements.get(name), 0, 0, 20) for name in equipped)


def _new_session(user: MutableMapping[str, Any], zone_key: str, difficulty_key: str, companions: Sequence[str], seed: str) -> Dict[str, Any]:
    zone = ZONES[zone_key]
    difficulty = DIFFICULTIES[difficulty_key]
    base_hp = min(160, max(70, _safe_int(user.get("hp"), 100, 1) + _safe_int(user.get("level"), 1, 1) // 2))
    anomaly = _weekly_anomaly()
    weekly = anomaly["zone"] == zone_key
    session = {
        "id": f"LX-{int(time.time())}-{str(user.get('level', 1))}",
        "version": VERSION,
        "zone": zone_key,
        "difficulty": difficulty_key,
        "companions": list(companions[:2]),
        "seed": _seed_code(seed),
        "stage": 0,
        "turn": 0,
        "total_stages": difficulty.stages,
        "hp": base_hp,
        "max_hp": base_hp,
        "infection": _safe_int(user.get("infection"), 0, 0, 100),
        "supplies": 3,
        "morale": 60,
        "camp_uses": 0,
        "status": "active",
        "started_at": int(time.time()),
        "updated_at": int(time.time()),
        "weekly_mutation": anomaly["key"] if weekly else "",
        "route": [],
        "log": [],
        "loot": {"food": 0, "exp": 0, "materials": {}, "items": [], "relics": [], "blueprints": [], "bonds": 0},
        "discoveries": {"events": [], "enemies": [], "npcs": [], "endings": [], "relics": [], "blueprints": []},
        "score": 0,
        "gear_power": _equipment_power(user),
    }
    # v17.3: existing NPC bond strength directly improves matching expedition
    # roles, so relationship progress is no longer only cosmetic.
    companion_to_npc = {"scout":"doyun", "medic":"yoonseo", "engineer":"sera", "gunner":"kane", "negotiator":"ren"}
    bond_root = user.get("npc_bonds_v1720", {}) if isinstance(user.get("npc_bonds_v1720"), Mapping) else {}
    bond_rows = bond_root.get("npcs", {}) if isinstance(bond_root, Mapping) else {}
    bond_bonus = 0
    for companion in session["companions"]:
        npc_id = companion_to_npc.get(str(companion))
        row = bond_rows.get(npc_id, {}) if npc_id and isinstance(bond_rows, Mapping) else {}
        if isinstance(row, Mapping):
            bond_bonus += min(10, (int(row.get("trust", 10) or 10) + int(row.get("loyalty", 20) or 20)) // 15)
    session["bond_bonus"] = min(20, bond_bonus)
    session["gear_power"] = int(session.get("gear_power", 0) or 0) + session["bond_bonus"]
    return session


def _session_label(locale: str, session: Mapping[str, Any]) -> str:
    zone = ZONES.get(str(session.get("zone")), ZONES["black_frequency"])
    difficulty = DIFFICULTIES.get(str(session.get("difficulty")), DIFFICULTIES["survivor"])
    return f"{zone.emoji} {_t(locale, zone.ko, zone.en)} · {difficulty.emoji} {_t(locale, difficulty.ko, difficulty.en)}"


def _bar(value: int, maximum: int, length: int = 10) -> str:
    maximum = max(1, int(maximum))
    filled = max(0, min(length, round(length * max(0, value) / maximum)))
    return "█" * filled + "░" * (length - filled)


def _pending_loot_lines(locale: str, loot: Mapping[str, Any], *, limit: int = 7) -> List[str]:
    lines: List[str] = []
    food = _safe_int(loot.get("food"), 0)
    exp = _safe_int(loot.get("exp"), 0)
    if food:
        lines.append(_t(locale, f"🥫 식량 **+{food:,}**", f"🥫 Supplies **+{food:,}**"))
    if exp:
        lines.append(f"✨ EXP **+{exp:,}**")
    materials = loot.get("materials") if isinstance(loot.get("materials"), Mapping) else {}
    for key, amount in materials.items():
        if _safe_int(amount):
            label = MATERIALS_EN.get(str(key), str(key)) if locale == "en" else str(key)
            lines.append(f"🧱 {label} **+{_safe_int(amount):,}**")
    for item in list(loot.get("items") or [])[-2:]:
        lines.append(_t(locale, f"🎒 {item}", f"🎒 {item}"))
    for relic in list(loot.get("relics") or [])[-2:]:
        lines.append(_t(locale, f"🔮 유물 · {relic}", f"🔮 Relic · {relic}"))
    for part in list(loot.get("blueprints") or [])[-2:]:
        ko, en = CITY_PART_LABELS.get(str(part), (str(part), str(part)))
        lines.append(_t(locale, f"🎨 도시 설계도 · {ko}", f"🎨 City Blueprint · {en}"))
    return lines[:limit] or [_t(locale, "아직 확보한 전리품 없음", "No secured loot yet")]


def _active_embed(locale: str, session: Mapping[str, Any], *, note: str = "") -> discord.Embed:
    zone = ZONES.get(str(session.get("zone")), ZONES["black_frequency"])
    difficulty = DIFFICULTIES.get(str(session.get("difficulty")), DIFFICULTIES["survivor"])
    stage = _safe_int(session.get("stage"), 0)
    total = _safe_int(session.get("total_stages"), difficulty.stages, 1)
    hp = _safe_int(session.get("hp"), 1, 0)
    max_hp = _safe_int(session.get("max_hp"), 100, 1)
    infection = _safe_int(session.get("infection"), 0, 0, 100)
    morale = _safe_int(session.get("morale"), 50, 0, 100)
    supplies = _safe_int(session.get("supplies"), 0, 0)
    embed = discord.Embed(
        title=_t(locale, "🧭 솔로 생존 원정", "🧭 Lone Survivor Expedition"),
        description=f"**{_session_label(locale, session)}**\n{_t(locale, zone.subtitle_ko, zone.subtitle_en)}",
        color=0x6C2BD9,
    )
    embed.add_field(name=_t(locale, "🗺️ 진행", "🗺️ Progress"), value=f"`{_bar(stage, total, 12)}` **{stage}/{total}**", inline=False)
    embed.add_field(name="❤️ HP", value=f"`{_bar(hp, max_hp)}` **{hp}/{max_hp}**", inline=True)
    embed.add_field(name=_t(locale, "☣️ 감염", "☣️ Infection"), value=f"**{infection}%**", inline=True)
    embed.add_field(name=_t(locale, "🔥 사기", "🔥 Morale"), value=f"**{morale}** · {_t(locale, '보급', 'Supplies')} **{supplies}**", inline=True)
    names: List[str] = []
    for key in session.get("companions") or []:
        companion = COMPANIONS.get(str(key))
        if companion:
            names.append(f"{companion.emoji} {_t(locale, companion.ko, companion.en)}")
    embed.add_field(name=_t(locale, "👥 원정대", "👥 Party"), value=" · ".join(names) or _t(locale, "단독 행동", "Solo"), inline=False)
    embed.add_field(name=_t(locale, "🎒 확보 중인 전리품", "🎒 Pending Loot"), value="\n".join(_pending_loot_lines(locale, session.get("loot") or {})), inline=False)
    if session.get("weekly_mutation"):
        anomaly = _weekly_anomaly()
        embed.add_field(name=f"{anomaly['emoji']} {_t(locale, anomaly['ko'], anomaly['en'])}", value=_t(locale, anomaly["desc_ko"], anomaly["desc_en"]), inline=False)
    logs = list(session.get("log") or [])[-4:]
    if logs:
        rendered = []
        for row in logs:
            if isinstance(row, Mapping):
                rendered.append(str(row.get("en") if locale == "en" else row.get("ko") or row.get("text") or "")[:220])
            else:
                rendered.append(str(row)[:220])
        embed.add_field(name=_t(locale, "📜 최근 행동", "📜 Recent Actions"), value="\n".join(f"• {x}" for x in rendered if x)[:1024], inline=False)
    if note:
        embed.add_field(name=_t(locale, "✨ 이번 결과", "✨ Latest Result"), value=note[:1024], inline=False)
    embed.set_footer(text=_t(locale, f"씨앗 {session.get('seed')} · 중도 저장됨 · 버튼으로 다음 행동 선택", f"Seed {session.get('seed')} · Auto-saved · Choose the next action"))
    return embed


def _hub_embed(locale: str, user: Mapping[str, Any]) -> discord.Embed:
    state = user.get(ROOT_KEY) if isinstance(user.get(ROOT_KEY), Mapping) else {}
    active = state.get("active") if isinstance(state.get("active"), Mapping) else None
    difficulty = DIFFICULTIES.get(str(state.get("default_difficulty")), DIFFICULTIES["survivor"])
    records = state.get("records") if isinstance(state.get("records"), Mapping) else {}
    anomaly = _weekly_anomaly()
    zone = ZONES[anomaly["zone"]]
    embed = discord.Embed(
        title=_t(locale, "🌑 ABADDON LONE SURVIVOR", "🌑 ABADDON LONE SURVIVOR"),
        description=_t(
            locale,
            "혼자서도 **출발 → 선택 → 전투·탐색 → 보스 → 귀환**까지 이어지는 10~15분 개인 로그라이크입니다. 기존 스토리·장비·재료·도시 공방 기록과 연결됩니다.",
            "A 10–15 minute solo roguelite: **depart → choose → fight/explore → boss → return**. It connects to story, gear, materials and city workshop records.",
        ),
        color=0x4B1F78,
    )
    if active:
        embed.add_field(name=_t(locale, "▶ 진행 중인 원정", "▶ Active Expedition"), value=f"{_session_label(locale, active)}\n{_t(locale, '단계', 'Stage')} **{active.get('stage', 0)}/{active.get('total_stages', 0)}** · `{active.get('seed')}`", inline=False)
    else:
        embed.add_field(name=_t(locale, "🚪 현재 상태", "🚪 Current Status"), value=_t(locale, "대기 중 · 빠른 출발 또는 맞춤 설정 가능", "Ready · Quick Start or Custom Setup"), inline=False)
    embed.add_field(
        name=_t(locale, "⚙️ 기본 설정", "⚙️ Defaults"),
        value=_t(locale, f"난이도 **{difficulty.ko}** · 동료 **{len(state.get('default_companions') or [])}명**", f"Difficulty **{difficulty.en}** · **{len(state.get('default_companions') or [])}** companions"),
        inline=True,
    )
    embed.add_field(name=_t(locale, "🏆 기록", "🏆 Records"), value=_t(locale, f"완주 **{records.get('victories', 0)}회** · 구조 **{records.get('rescues', 0)}회**", f"Wins **{records.get('victories', 0)}** · Rescues **{records.get('rescues', 0)}**"), inline=True)
    embed.add_field(
        name=f"{anomaly['emoji']} {_t(locale, '이번 주 변이 지역', 'Weekly Mutation')}",
        value=f"**{zone.emoji} {_t(locale, zone.ko, zone.en)}**\n{_t(locale, anomaly['ko'], anomaly['en'])} · {_t(locale, anomaly['desc_ko'], anomaly['desc_en'])}",
        inline=False,
    )
    embed.add_field(
        name=_t(locale, "🧩 포함된 기능", "🧩 Included Features"),
        value=_t(locale, "난이도 4단계 · NPC 5종 중 2명 편성 · 씨앗 코드 · 주간 변이 · 도감 · 중도 저장 · 긴급 구조", "4 difficulties · choose 2 of 5 NPC roles · seed codes · weekly mutation · codex · resume · rescue"),
        inline=False,
    )
    return embed


def _weekly_embed(locale: str) -> discord.Embed:
    anomaly = _weekly_anomaly()
    zone = ZONES[anomaly["zone"]]
    embed = discord.Embed(
        title=f"{anomaly['emoji']} {_t(locale, '주간 변이 지역', 'Weekly Mutation Region')}",
        description=f"**{anomaly['week']} · {zone.emoji} {_t(locale, zone.ko, zone.en)}**",
        color=0xD35400,
    )
    embed.add_field(name=_t(locale, anomaly["ko"], anomaly["en"]), value=_t(locale, anomaly["desc_ko"], anomaly["desc_en"]), inline=False)
    embed.add_field(name=_t(locale, "보정", "Modifiers"), value=_t(locale, f"받는 피해 ×{anomaly['damage']:.2f} · 전리품 ×{anomaly['reward']:.2f}", f"Damage ×{anomaly['damage']:.2f} · Loot ×{anomaly['reward']:.2f}"), inline=False)
    embed.set_footer(text=_t(locale, "해당 지역으로 출발하면 자동 적용됩니다.", "Automatically applied when starting this region."))
    return embed


def _codex_display(locale: str, category: str, value: str) -> str:
    value = str(value)
    if category == "events":
        if value in EVENT_LABELS:
            return _t(locale, *EVENT_LABELS[value])
        if value.startswith("combat:") or value.startswith("boss:"):
            return value.split(":", 1)[-1]
        return value
    if category == "enemies":
        parts = value.split(":")
        if len(parts) == 2 and parts[0] in ZONES:
            zone = ZONES[parts[0]]
            if parts[1] == "boss":
                return zone.enemies_en[-1] if locale == "en" else zone.enemies_ko[-1]
            try:
                index = int(parts[1])
                return zone.enemies_en[index] if locale == "en" else zone.enemies_ko[index]
            except (ValueError, IndexError):
                pass
        return value
    if category == "npcs":
        row = NPC_ENCOUNTERS.get(value)
        return _t(locale, *row) if row else value
    if category == "relics":
        zone = ZONES.get(value)
        return _t(locale, zone.relic_ko, zone.relic_en) if zone else value
    if category == "blueprints":
        row = CITY_PART_LABELS.get(value)
        return _t(locale, *row) if row else value
    if category == "endings":
        row = ENDING_LABELS.get(value)
        return _t(locale, *row) if row else value
    return value


def _codex_embed(locale: str, state: Mapping[str, Any]) -> discord.Embed:
    codex = state.get("codex") if isinstance(state.get("codex"), Mapping) else {}
    embed = discord.Embed(title=_t(locale, "📚 솔로 원정 도감", "📚 Lone Expedition Codex"), color=0x8E44AD)
    categories = (
        ("events", "사건", "Events", "🎬"), ("enemies", "적", "Enemies", "👹"),
        ("npcs", "NPC", "NPCs", "🤝"), ("relics", "유물", "Relics", "🔮"),
        ("blueprints", "도시 설계도", "City Blueprints", "🎨"), ("endings", "결말", "Endings", "🏁"),
    )
    for key, ko, en, emoji in categories:
        rows = list(codex.get(key) or [])
        preview = " · ".join(_codex_display(locale, key, str(x)) for x in rows[-6:]) or _t(locale, "미발견", "Undiscovered")
        embed.add_field(name=f"{emoji} {_t(locale, ko, en)} · {len(rows)}", value=preview[:1024], inline=False)
    embed.set_footer(text=_t(locale, "같은 씨앗을 다시 플레이해도 다른 행동을 선택하면 새로운 기록이 열립니다.", "Replaying a seed with different choices can unlock new entries."))
    return embed


def _records_embed(locale: str, state: Mapping[str, Any]) -> discord.Embed:
    records = state.get("records") if isinstance(state.get("records"), Mapping) else {}
    embed = discord.Embed(title=_t(locale, "🏆 솔로 원정 기록", "🏆 Lone Expedition Records"), color=0xF1C40F)
    embed.add_field(name=_t(locale, "전체", "Overall"), value=_t(locale, f"출발 **{records.get('runs', 0)}회** · 완주 **{records.get('victories', 0)}회** · 철수 **{records.get('retreats', 0)}회** · 구조 **{records.get('rescues', 0)}회**", f"Runs **{records.get('runs', 0)}** · Wins **{records.get('victories', 0)}** · Retreats **{records.get('retreats', 0)}** · Rescues **{records.get('rescues', 0)}**"), inline=False)
    embed.add_field(name=_t(locale, "최고", "Best"), value=_t(locale, f"최고 단계 **{records.get('best_stage', 0)}** · 최고 점수 **{records.get('best_score', 0):,}**", f"Best stage **{records.get('best_stage', 0)}** · Best score **{records.get('best_score', 0):,}**"), inline=True)
    embed.add_field(name=_t(locale, "누적 획득", "Lifetime Loot"), value=_t(locale, f"식량 **{records.get('total_food', 0):,}** · EXP **{records.get('total_exp', 0):,}**", f"Supplies **{records.get('total_food', 0):,}** · EXP **{records.get('total_exp', 0):,}**"), inline=True)
    recent = list(records.get("recent") or [])[-6:]
    if recent:
        lines = []
        for row in reversed(recent):
            if not isinstance(row, Mapping):
                continue
            zone = ZONES.get(str(row.get("zone")), ZONES["black_frequency"])
            result = str(row.get("result_en") if locale == "en" else row.get("result_ko") or row.get("result", "-"))
            lines.append(f"• {zone.emoji} **{_t(locale, zone.ko, zone.en)}** · {result} · {row.get('score', 0):,}pt · `{row.get('seed', '-')}`")
        embed.add_field(name=_t(locale, "최근 원정", "Recent Expeditions"), value="\n".join(lines)[:1024], inline=False)
    return embed


def _append_log(session: MutableMapping[str, Any], ko: str, en: str, event_key: str = "") -> None:
    logs = session.setdefault("log", [])
    if not isinstance(logs, list):
        logs = []
        session["log"] = logs
    logs.append({"at": int(time.time()), "ko": ko, "en": en, "event": event_key})
    del logs[:-30]
    if event_key:
        discoveries = session.setdefault("discoveries", {})
        _list_add_unique(discoveries, "events", event_key)


def _add_material(session: MutableMapping[str, Any], key: str, amount: int) -> None:
    loot = session.setdefault("loot", {})
    materials = loot.setdefault("materials", {})
    materials[key] = _safe_int(materials.get(key), 0) + max(0, int(amount))


def _add_loot(session: MutableMapping[str, Any], *, food: int = 0, exp: int = 0, score: int = 0) -> None:
    loot = session.setdefault("loot", {})
    loot["food"] = _safe_int(loot.get("food"), 0) + max(0, int(food))
    loot["exp"] = _safe_int(loot.get("exp"), 0) + max(0, int(exp))
    session["score"] = _safe_int(session.get("score"), 0) + max(0, int(score))


def _party_bonus(session: Mapping[str, Any], key: str) -> bool:
    return key in set(str(x) for x in (session.get("companions") or []))


def _mut_mod(session: Mapping[str, Any]) -> Tuple[float, float]:
    if not session.get("weekly_mutation"):
        return 1.0, 1.0
    anomaly = _weekly_anomaly()
    return float(anomaly["damage"]), float(anomaly["reward"])


def _event_weights(action: str, session: Mapping[str, Any]) -> List[Tuple[str, int]]:
    if action == "search":
        base = [("combat", 25), ("hazard", 20), ("supply", 18), ("treasure", 22), ("npc", 8), ("choice", 7)]
    elif action == "special":
        base = [("combat", 28), ("hazard", 15), ("supply", 7), ("treasure", 25), ("npc", 10), ("choice", 15)]
    else:
        base = [("combat", 28), ("hazard", 14), ("supply", 18), ("treasure", 12), ("npc", 13), ("choice", 15)]
    mutation = str(session.get("weekly_mutation") or "")
    adjusted = dict(base)
    if mutation == "silent_city":
        adjusted["npc"] = 2; adjusted["treasure"] += 14
    elif mutation == "survivor_signal":
        adjusted["npc"] += 18; adjusted["combat"] = max(12, adjusted["combat"] - 8)
    elif mutation == "static_storm":
        adjusted["choice"] += 8; adjusted["supply"] += 5
    return list(adjusted.items())


def _weighted_choice(rng: random.Random, rows: Sequence[Tuple[str, int]]) -> str:
    total = sum(max(0, weight) for _key, weight in rows)
    pick = rng.uniform(0, max(1, total))
    acc = 0.0
    for key, weight in rows:
        acc += max(0, weight)
        if pick <= acc:
            return key
    return rows[-1][0]


def _resolve_combat(locale: str, session: MutableMapping[str, Any], *, boss: bool = False) -> str:
    zone = ZONES[str(session.get("zone"))]
    diff = DIFFICULTIES[str(session.get("difficulty"))]
    rng = _rng(session, "boss" if boss else "combat")
    enemies = zone.enemies_en if locale == "en" else zone.enemies_ko
    enemy_index = len(enemies) - 1 if boss else rng.randrange(0, len(enemies) - 1)
    enemy = enemies[enemy_index]
    discovery_key = f"{zone.key}:{'boss' if boss else enemy_index}"
    _list_add_unique(session.setdefault("discoveries", {}), "enemies", discovery_key)
    gear = _safe_int(session.get("gear_power"), 0)
    chance = 0.58 + min(0.18, gear / 180) + (0.14 if _party_bonus(session, "gunner") else 0) + _safe_int(session.get("morale"), 50) / 1000
    chance -= {"survivor": 0.0, "veteran": 0.05, "nightmare": 0.13, "abyss": 0.21}.get(diff.key, 0)
    if boss:
        chance -= 0.10
    success = rng.random() < max(0.20, min(0.92, chance))
    damage_mod, reward_mod = _mut_mod(session)
    reward_mod *= diff.reward
    if success:
        damage = round(rng.randint(2, 9 if not boss else 15) * diff.damage * damage_mod)
        if _party_bonus(session, "scout"):
            damage = round(damage * 0.85)
        food = round(rng.randint(2200, 6200) * reward_mod * (2.2 if boss else 1.0))
        exp = round(rng.randint(35, 85) * reward_mod * (2.0 if boss else 1.0))
        material = rng.choice(MATERIALS_KO)
        amount = max(1, round(rng.randint(2, 6) * reward_mod))
        _add_loot(session, food=food, exp=exp, score=220 if boss else 80)
        _add_material(session, material, amount)
        session["hp"] = max(1, _safe_int(session.get("hp"), 1) - damage)
        if boss:
            session["boss_defeated"] = True
        ko = f"⚔️ **{zone.enemies_ko[-1] if boss else enemy}** 격파 · HP -{damage} · 식량 +{food:,} · EXP +{exp} · {material} +{amount}"
        en_enemy = zone.enemies_en[-1] if boss else zone.enemies_en[zone.enemies_ko.index(enemy)] if enemy in zone.enemies_ko else enemy
        en = f"⚔️ Defeated **{en_enemy}** · HP -{damage} · Supplies +{food:,} · EXP +{exp} · {MATERIALS_EN.get(material, material)} +{amount}"
    else:
        damage = round(rng.randint(14, 29 if not boss else 42) * diff.damage * damage_mod)
        if _party_bonus(session, "scout"):
            damage = round(damage * 0.88)
        infection = rng.randint(1, 5 if not boss else 8)
        session["hp"] = max(0, _safe_int(session.get("hp"), 1) - damage)
        session["infection"] = min(100, _safe_int(session.get("infection"), 0) + infection)
        session["morale"] = max(0, _safe_int(session.get("morale"), 50) - 8)
        if boss:
            session["boss_defeated"] = False
            session["stage"] = max(0, _safe_int(session.get("total_stages"), 1) - 1)
        ko = f"💥 **{zone.enemies_ko[-1] if boss else enemy}**의 반격 · HP -{damage} · 감염 +{infection}%"
        en_enemy = zone.enemies_en[-1] if boss else zone.enemies_en[zone.enemies_ko.index(enemy)] if enemy in zone.enemies_ko else enemy
        en = f"💥 Countered by **{en_enemy}** · HP -{damage} · Infection +{infection}%"
    _append_log(session, ko, en, discovery_key)
    return en if locale == "en" else ko


def _resolve_hazard(locale: str, session: MutableMapping[str, Any]) -> str:
    rng = _rng(session, "hazard")
    diff = DIFFICULTIES[str(session.get("difficulty"))]
    damage_mod, _reward_mod = _mut_mod(session)
    damage = round(rng.randint(7, 21) * diff.damage * damage_mod)
    avoided = _party_bonus(session, "scout") and rng.random() < 0.46
    if avoided:
        damage = max(0, damage // 4)
    infection = 0 if avoided else rng.randint(0, 4)
    session["hp"] = max(0, _safe_int(session.get("hp"), 1) - damage)
    session["infection"] = min(100, _safe_int(session.get("infection"), 0) + infection)
    ko = f"⚠️ 붕괴 지형{'을 정찰병이 조기 발견' if avoided else '에 휘말림'} · HP -{damage}" + (f" · 감염 +{infection}%" if infection else "")
    en = f"⚠️ Collapsing terrain {'spotted early by the scout' if avoided else 'struck the party'} · HP -{damage}" + (f" · Infection +{infection}%" if infection else "")
    _append_log(session, ko, en, "hazard:collapse")
    return en if locale == "en" else ko


def _resolve_supply(locale: str, session: MutableMapping[str, Any]) -> str:
    rng = _rng(session, "supply")
    diff = DIFFICULTIES[str(session.get("difficulty"))]
    _damage_mod, reward_mod = _mut_mod(session)
    reward_mod *= diff.reward
    food = round(rng.randint(2600, 8500) * reward_mod)
    material = rng.choice(MATERIALS_KO)
    amount = max(1, round(rng.randint(2, 7) * reward_mod))
    session["supplies"] = _safe_int(session.get("supplies"), 0) + 1
    _add_loot(session, food=food, exp=rng.randint(15, 35), score=55)
    _add_material(session, material, amount)
    ko = f"📦 폐쇄된 보급함 확보 · 식량 +{food:,} · {material} +{amount} · 야영 보급 +1"
    en = f"📦 Secured a sealed cache · Supplies +{food:,} · {MATERIALS_EN.get(material, material)} +{amount} · Camp supply +1"
    _append_log(session, ko, en, "supply:sealed_cache")
    return en if locale == "en" else ko


def _resolve_npc(locale: str, session: MutableMapping[str, Any]) -> str:
    rng = _rng(session, "npc")
    npc_key = rng.choice(tuple(NPC_ENCOUNTERS))
    ko_name, en_name = NPC_ENCOUNTERS[npc_key]
    bonus = 1.35 if _party_bonus(session, "negotiator") else 1.0
    bonds = round(rng.randint(4, 10) * bonus)
    food = round(rng.randint(1800, 4300) * bonus)
    loot = session.setdefault("loot", {})
    loot["bonds"] = _safe_int(loot.get("bonds"), 0) + bonds
    _add_loot(session, food=food, exp=25, score=65)
    _list_add_unique(session.setdefault("discoveries", {}), "npcs", npc_key)
    ko = f"🤝 **{ko_name}** 구조 · 관계 +{bonds} · 식량 +{food:,}"
    en = f"🤝 Rescued **{en_name}** · Bond +{bonds} · Supplies +{food:,}"
    _append_log(session, ko, en, f"npc:{npc_key}")
    return en if locale == "en" else ko


def _resolve_treasure(locale: str, session: MutableMapping[str, Any]) -> str:
    rng = _rng(session, "treasure")
    zone = ZONES[str(session.get("zone"))]
    engineer = _party_bonus(session, "engineer")
    roll = rng.random()
    if roll < (0.34 if engineer else 0.22):
        part = zone.blueprint
        loot = session.setdefault("loot", {})
        rows = loot.setdefault("blueprints", [])
        if part not in rows:
            rows.append(part)
        ko_part, en_part = CITY_PART_LABELS.get(part, (part, part))
        _list_add_unique(session.setdefault("discoveries", {}), "blueprints", part)
        _add_loot(session, exp=45, score=115)
        ko = f"🎨 도시 설계도 발견 · **{ko_part}** · 귀환 후 도시 공방에서 확인 가능"
        en = f"🎨 City blueprint found · **{en_part}** · available from City Workshop after return"
        _append_log(session, ko, en, f"blueprint:{part}")
        return en if locale == "en" else ko
    relic = _t(locale, zone.relic_ko, zone.relic_en)
    rows = session.setdefault("loot", {}).setdefault("relics", [])
    if relic not in rows:
        rows.append(relic)
    _list_add_unique(session.setdefault("discoveries", {}), "relics", zone.key)
    _add_loot(session, food=rng.randint(1200, 3500), exp=60, score=100)
    ko = f"🔮 희귀 유물 발견 · **{zone.relic_ko}**"
    en = f"🔮 Rare relic found · **{zone.relic_en}**"
    _append_log(session, ko, en, f"relic:{zone.key}")
    return en if locale == "en" else ko


def _resolve_choice(locale: str, session: MutableMapping[str, Any]) -> str:
    rng = _rng(session, "choice")
    outcomes = (
        ("signal", "낡은 송신기를 복구해 안전 경로를 확보했습니다.", "Repaired an old transmitter and secured a safe route."),
        ("survivors", "남겨진 생존자 표식을 따라 비밀 보급로를 찾았습니다.", "Followed survivor marks to a hidden supply route."),
        ("memory", "폐허의 기록을 개인 연대기에 남겼습니다.", "Added a ruin memory to the personal chronicle."),
        ("shortcut", "위험한 지름길을 선택해 원정 시간을 단축했습니다.", "Took a dangerous shortcut and shortened the expedition."),
    )
    key, ko_text, en_text = rng.choice(outcomes)
    damage = 0
    if key == "shortcut":
        damage = rng.randint(3, 10)
        session["hp"] = max(0, _safe_int(session.get("hp"), 1) - damage)
        session["morale"] = min(100, _safe_int(session.get("morale"), 50) + 8)
    reward = round(rng.randint(1800, 4500) * (1.25 if _party_bonus(session, "negotiator") else 1.0))
    _add_loot(session, food=reward, exp=35, score=75)
    ko = f"🎬 {ko_text} · 식량 +{reward:,}" + (f" · HP -{damage}" if damage else "")
    en = f"🎬 {en_text} · Supplies +{reward:,}" + (f" · HP -{damage}" if damage else "")
    _append_log(session, ko, en, f"choice:{key}")
    return en if locale == "en" else ko


def _medic_aftercare(locale: str, session: MutableMapping[str, Any]) -> str:
    if not _party_bonus(session, "medic"):
        return ""
    hp = _safe_int(session.get("hp"), 0)
    maximum = _safe_int(session.get("max_hp"), 100, 1)
    if hp <= 0 or hp >= maximum:
        return ""
    rng = _rng(session, "medic")
    heal = min(maximum - hp, rng.randint(3, 8))
    infection_before = _safe_int(session.get("infection"), 0)
    infection_reduced = min(infection_before, rng.randint(0, 2))
    session["hp"] = hp + heal
    session["infection"] = infection_before - infection_reduced
    return _t(locale, f" · 🩺 하린 치료 HP +{heal}" + (f" / 감염 -{infection_reduced}%" if infection_reduced else ""), f" · 🩺 Harin healed HP +{heal}" + (f" / Infection -{infection_reduced}%" if infection_reduced else ""))


def _resolve_action(locale: str, session: MutableMapping[str, Any], action: str) -> str:
    session["turn"] = _safe_int(session.get("turn"), 0) + 1
    session["updated_at"] = int(time.time())
    if action == "camp":
        if _safe_int(session.get("camp_uses"), 0) >= 2:
            return _t(locale, "⛺ 이번 원정에서는 더 이상 안전하게 야영할 수 없습니다.", "⛺ No more safe camps are available in this expedition.")
        if _safe_int(session.get("supplies"), 0) <= 0:
            return _t(locale, "⛺ 야영 보급이 부족합니다. 수색으로 보급함을 찾아야 합니다.", "⛺ No camp supplies remain. Search for a cache first.")
        rng = _rng(session, "camp")
        heal = min(_safe_int(session.get("max_hp"), 100) - _safe_int(session.get("hp"), 1), rng.randint(18, 32))
        infection = min(_safe_int(session.get("infection"), 0), rng.randint(2, 6))
        session["hp"] = _safe_int(session.get("hp"), 1) + heal
        session["infection"] = _safe_int(session.get("infection"), 0) - infection
        session["morale"] = min(100, _safe_int(session.get("morale"), 50) + 12)
        session["supplies"] = _safe_int(session.get("supplies"), 0) - 1
        session["camp_uses"] = _safe_int(session.get("camp_uses"), 0) + 1
        ko = f"⛺ 야영 완료 · HP +{heal} · 감염 -{infection}% · 사기 +12 · 보급 -1"
        en = f"⛺ Camp complete · HP +{heal} · Infection -{infection}% · Morale +12 · Supply -1"
        _append_log(session, ko, en, "camp")
        return en if locale == "en" else ko

    session["stage"] = _safe_int(session.get("stage"), 0) + 1
    stage = _safe_int(session.get("stage"), 0)
    total = _safe_int(session.get("total_stages"), 6)
    route = session.setdefault("route", [])
    if isinstance(route, list):
        route.append({"stage": stage, "action": action, "at": int(time.time())})
        del route[:-30]
    if stage >= total:
        message = _resolve_combat(locale, session, boss=True)
    else:
        event = _weighted_choice(_rng(session, f"event:{action}"), _event_weights(action, session))
        handlers = {
            "combat": _resolve_combat, "hazard": _resolve_hazard, "supply": _resolve_supply,
            "npc": _resolve_npc, "treasure": _resolve_treasure, "choice": _resolve_choice,
        }
        message = handlers[event](locale, session)
    message += _medic_aftercare(locale, session)
    return message


def _merge_discoveries(state: MutableMapping[str, Any], session: Mapping[str, Any]) -> None:
    codex = state.setdefault("codex", {})
    discoveries = session.get("discoveries") if isinstance(session.get("discoveries"), Mapping) else {}
    for key in ("events", "enemies", "npcs", "endings", "relics", "blueprints"):
        for value in discoveries.get(key) or []:
            _list_add_unique(codex, key, str(value))


def _apply_rewards(user: MutableMapping[str, Any], session: Mapping[str, Any], factor: float, state: MutableMapping[str, Any]) -> Dict[str, Any]:
    loot = session.get("loot") if isinstance(session.get("loot"), Mapping) else {}
    applied = {"food": round(_safe_int(loot.get("food"), 0) * factor), "exp": round(_safe_int(loot.get("exp"), 0) * factor), "materials": {}, "items": [], "relics": [], "blueprints": [], "bonds": round(_safe_int(loot.get("bonds"), 0) * factor)}
    user["balance"] = _safe_int(user.get("balance"), 0) + applied["food"]
    user["exp"] = _safe_int(user.get("exp"), 0) + applied["exp"]
    resources = user.setdefault("resources", {})
    if not isinstance(resources, MutableMapping):
        resources = {}; user["resources"] = resources
    materials = loot.get("materials") if isinstance(loot.get("materials"), Mapping) else {}
    for key, value in materials.items():
        amount = round(_safe_int(value, 0) * factor)
        if amount <= 0:
            continue
        resources[str(key)] = _safe_int(resources.get(str(key)), 0) + amount
        applied["materials"][str(key)] = amount
    inventory = user.setdefault("inventory", [])
    if not isinstance(inventory, list):
        inventory = []; user["inventory"] = inventory
    if factor >= 0.60:
        for item in loot.get("items") or []:
            inventory.append(str(item)); applied["items"].append(str(item))
        for relic in loot.get("relics") or []:
            label = str(relic)
            inventory.append(label); applied["relics"].append(label)
        unlocked = state.setdefault("unlocked_blueprints", [])
        if not isinstance(unlocked, list):
            unlocked = []; state["unlocked_blueprints"] = unlocked
        for part in loot.get("blueprints") or []:
            part = str(part)
            if part not in unlocked:
                unlocked.append(part)
            applied["blueprints"].append(part)
    user["hp"] = max(1, min(_safe_int(session.get("hp"), 1), max(100, _safe_int(session.get("max_hp"), 100))))
    user["infection"] = min(100, max(0, _safe_int(session.get("infection"), 0)))
    return applied


def _finalize(user: MutableMapping[str, Any], state: MutableMapping[str, Any], session: MutableMapping[str, Any], result: str, locale: str) -> Tuple[discord.Embed, "ResultActionsViewData"]:
    difficulty = DIFFICULTIES[str(session.get("difficulty"))]
    factors = {"victory": 1.0, "retreat": 0.60, "rescue": difficulty.rescue_keep}
    factor = factors[result]
    applied = _apply_rewards(user, session, factor, state)
    result_labels = {
        "victory": ("귀환 성공", "Returned Successfully", "🏁", 0x2ECC71),
        "retreat": ("전략적 철수", "Tactical Retreat", "🚪", 0xF39C12),
        "rescue": ("긴급 구조", "Emergency Rescue", "🚑", 0xE74C3C),
    }
    ko_result, en_result, emoji, color = result_labels[result]
    _list_add_unique(session.setdefault("discoveries", {}), "endings", result)
    _merge_discoveries(state, session)
    records = state.setdefault("records", {})
    records["runs"] = _safe_int(records.get("runs"), 0) + 1
    key = {"victory": "victories", "retreat": "retreats", "rescue": "rescues"}[result]
    records[key] = _safe_int(records.get(key), 0) + 1
    records["best_stage"] = max(_safe_int(records.get("best_stage"), 0), _safe_int(session.get("stage"), 0))
    records["best_score"] = max(_safe_int(records.get("best_score"), 0), _safe_int(session.get("score"), 0))
    records["total_food"] = _safe_int(records.get("total_food"), 0) + applied["food"]
    records["total_exp"] = _safe_int(records.get("total_exp"), 0) + applied["exp"]
    linked = user.setdefault("connected_survival_v1730", {})
    linked.setdefault("daily", {})["expedition_day"] = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    linked.setdefault("history", []).append({"at": int(time.time()), "type": "expedition", "result": result, "detail": str(session.get("zone", "unknown"))})
    linked["history"] = linked["history"][-100:]
    # Successful shared-role expeditions strengthen the corresponding v17.2 NPC bond.
    companion_to_npc = {"scout":"doyun", "medic":"yoonseo", "engineer":"sera", "gunner":"kane", "negotiator":"ren"}
    bond_root = user.setdefault("npc_bonds_v1720", {}).setdefault("npcs", {})
    for companion in session.get("companions", []):
        npc_id = companion_to_npc.get(str(companion))
        if not npc_id:
            continue
        bond = bond_root.setdefault(npc_id, {})
        bond["affinity"] = min(100, int(bond.get("affinity", 0) or 0) + (3 if result == "victory" else 1))
        bond["trust"] = min(100, int(bond.get("trust", 10) or 10) + (2 if result == "victory" else 1))
    zones = records.setdefault("zones", {})
    zone_key = str(session.get("zone"))
    zone_row = zones.setdefault(zone_key, {"runs": 0, "victories": 0, "best_score": 0})
    zone_row["runs"] = _safe_int(zone_row.get("runs"), 0) + 1
    if result == "victory":
        zone_row["victories"] = _safe_int(zone_row.get("victories"), 0) + 1
    zone_row["best_score"] = max(_safe_int(zone_row.get("best_score"), 0), _safe_int(session.get("score"), 0))
    recent = records.setdefault("recent", [])
    recent.append({
        "at": int(time.time()), "zone": zone_key, "difficulty": session.get("difficulty"),
        "result_ko": ko_result, "result_en": en_result, "score": _safe_int(session.get("score"), 0),
        "seed": session.get("seed"), "stage": session.get("stage"),
    })
    del recent[:-20]
    session["status"] = result
    session["ended_at"] = int(time.time())
    state["last_result"] = dict(session)
    state["active"] = None

    zone = ZONES[zone_key]
    embed = discord.Embed(title=f"{emoji} {_t(locale, ko_result, en_result)}", description=f"**{zone.emoji} {_t(locale, zone.ko, zone.en)}** · `{session.get('seed')}`", color=color)
    route_labels = {"advance": ("전진", "Advance"), "search": ("수색", "Search"), "camp": ("야영", "Camp"), "special": ("특수 행동", "Special")}
    route = []
    for row in session.get("route") or []:
        if isinstance(row, Mapping):
            ko, en = route_labels.get(str(row.get("action")), (str(row.get("action")), str(row.get("action"))))
            route.append(_t(locale, ko, en))
    embed.add_field(name=_t(locale, "🗺️ 이동 경로", "🗺️ Route"), value=" → ".join(route[-8:]) or "-", inline=False)
    embed.add_field(name=_t(locale, "⚔️ 주요 행동", "⚔️ Actions"), value=_t(locale, f"단계 **{session.get('stage', 0)}/{session.get('total_stages', 0)}** · 점수 **{session.get('score', 0):,}** · 사건 **{len(session.get('log') or [])}회**", f"Stage **{session.get('stage', 0)}/{session.get('total_stages', 0)}** · Score **{session.get('score', 0):,}** · **{len(session.get('log') or [])}** events"), inline=False)
    gain_lines = []
    if applied["food"]:
        gain_lines.append(_t(locale, f"🥫 식량 +{applied['food']:,}", f"🥫 Supplies +{applied['food']:,}"))
    if applied["exp"]:
        gain_lines.append(f"✨ EXP +{applied['exp']:,}")
    for key_name, value in applied["materials"].items():
        label = MATERIALS_EN.get(key_name, key_name) if locale == "en" else key_name
        gain_lines.append(f"🧱 {label} +{value}")
    for relic in applied["relics"]:
        gain_lines.append(_t(locale, f"🔮 {relic}", f"🔮 {relic}"))
    for part in applied["blueprints"]:
        ko_part, en_part = CITY_PART_LABELS.get(part, (part, part))
        gain_lines.append(_t(locale, f"🎨 {ko_part} 설계도", f"🎨 {en_part} Blueprint"))
    embed.add_field(name=_t(locale, f"🎁 실제 지급 · {round(factor*100)}%", f"🎁 Granted · {round(factor*100)}%"), value="\n".join(gain_lines)[:1024] or _t(locale, "지급 없음", "No rewards"), inline=False)
    embed.add_field(name=_t(locale, "📊 최종 변화", "📊 Final State"), value=f"❤️ HP **{user.get('hp', 1)}** · ☣️ {_t(locale, '감염', 'Infection')} **{user.get('infection', 0)}%** · 🥫 {_t(locale, '현재 식량', 'Current supplies')} **{_safe_int(user.get('balance'), 0):,}**", inline=False)
    if result == "rescue":
        embed.add_field(name=_t(locale, "🛟 구조 보호", "🛟 Rescue Protection"), value=_t(locale, "사망 대신 구조 처리되어 일부 전리품을 보존했습니다. 같은 씨앗으로 다시 도전할 수 있습니다.", "You were rescued instead of losing the run completely. Some loot was preserved and the seed can be replayed."), inline=False)
    embed.set_footer(text=_t(locale, "다음 행동 버튼으로 회복·제작·도시 배치·재도전을 이어가세요.", "Use the next-action buttons to heal, craft, decorate or retry."))
    return embed, ResultActionsViewData(seed=str(session.get("seed") or ""), zone=zone_key, difficulty=str(session.get("difficulty") or "survivor"))


@dataclass(frozen=True)
class ResultActionsViewData:
    seed: str
    zone: str
    difficulty: str


class OwnerView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 600) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        locale = _locale(interaction)
        await interaction.response.send_message(_t(locale, "이 원정 패널은 실행자만 사용할 수 있습니다.", "Only the opener can control this expedition."), ephemeral=True)
        return False


class LinkedCommandButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, command_name: str, locale: str, ko: str, en: str, emoji: str, *, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        super().__init__(label=_t(locale, ko, en)[:80], emoji=emoji, style=style, row=row)
        self.bot = bot
        self.command_name = command_name
        self.locale = locale

    async def callback(self, interaction: discord.Interaction) -> None:
        command = self.bot.get_command(self.command_name)
        if command is None:
            await interaction.response.send_message(_t(self.locale, "연결된 명령을 찾지 못했습니다.", "Linked command was not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(self.bot, interaction, command.qualified_name)


class ExpeditionSetupModal(discord.ui.Modal):
    def __init__(self, owner: "ExpeditionHubView") -> None:
        super().__init__(title=_t(owner.locale, "솔로 원정 맞춤 설정", "Custom Lone Expedition"))
        self.owner_view = owner
        user = owner.user
        state = _root(user)
        default_zone = _highest_zone(user)
        default_difficulty = str(state.get("default_difficulty") or "survivor")
        default_companions = ", ".join(str(x) for x in state.get("default_companions") or ["scout", "medic"])
        self.zone = discord.ui.TextInput(label=_t(owner.locale, "지역", "Region"), placeholder=_t(owner.locale, "폐허 / 방주 / 왕좌 / 황혼선 / 전선 / 블랙시티 / 차원", "ruins / ark / throne / twilight / front / black city / abyss"), default=default_zone, max_length=40)
        self.difficulty = discord.ui.TextInput(label=_t(owner.locale, "난이도", "Difficulty"), placeholder=_t(owner.locale, "생존자 / 베테랑 / 악몽 / 심연", "survivor / veteran / nightmare / abyss"), default=default_difficulty, max_length=20)
        self.companions = discord.ui.TextInput(label=_t(owner.locale, "NPC 동료 최대 2명", "Up to 2 NPC companions"), placeholder=_t(owner.locale, "정찰병, 의무병", "scout, medic"), default=default_companions, max_length=60, required=False)
        self.seed = discord.ui.TextInput(label=_t(owner.locale, "씨앗 코드 (선택)", "Seed Code (optional)"), placeholder="AB12CD34", default=str(state.get("preferred_seed") or ""), max_length=12, required=False)
        for item in (self.zone, self.difficulty, self.companions, self.seed):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        zone_key = _normalize_zone(str(self.zone.value))
        difficulty_key = _normalize_difficulty(str(self.difficulty.value))
        if zone_key is None or difficulty_key is None:
            await interaction.response.send_message(_t(view.locale, "지역 또는 난이도를 찾지 못했습니다. `!솔로원정` 안내에서 이름을 확인하세요.", "Unknown region or difficulty. Check `!soloexpedition` for names."), ephemeral=True)
            return
        if _safe_int(view.user.get("level"), 1) < ZONES[zone_key].min_level:
            await interaction.response.send_message(_t(view.locale, f"이 지역은 레벨 {ZONES[zone_key].min_level}부터 입장할 수 있습니다.", f"This region requires level {ZONES[zone_key].min_level}."), ephemeral=True)
            return
        companions = _normalize_companions(str(self.companions.value), _root(view.user).get("default_companions") or [])
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await view.start(interaction, zone_key, difficulty_key, companions, str(self.seed.value))


class ExpeditionHubView(OwnerView):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, user: MutableMapping[str, Any], save_data: Callable[[], None]) -> None:
        super().__init__(owner_id, timeout=600)
        self.bot = bot
        self.locale = locale
        self.user = user
        self.save_data = save_data
        quick = discord.ui.Button(label=_t(locale, "빠른 출발", "Quick Start"), emoji="🚀", style=discord.ButtonStyle.success, row=0)
        custom = discord.ui.Button(label=_t(locale, "맞춤 설정", "Custom Setup"), emoji="⚙️", style=discord.ButtonStyle.primary, row=0)
        resume = discord.ui.Button(label=_t(locale, "이어하기", "Resume"), emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
        weekly = discord.ui.Button(label=_t(locale, "주간 변이", "Weekly"), emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
        codex = discord.ui.Button(label=_t(locale, "원정 도감", "Codex"), emoji="📚", style=discord.ButtonStyle.secondary, row=0)
        records = discord.ui.Button(label=_t(locale, "기록", "Records"), emoji="🏆", style=discord.ButtonStyle.secondary, row=1)
        difficulty = discord.ui.Button(label=_t(locale, "기본 난이도", "Default Difficulty"), emoji="☠️", style=discord.ButtonStyle.secondary, row=1)
        seed = discord.ui.Button(label=_t(locale, "씨앗 도움말", "Seed Help"), emoji="🧬", style=discord.ButtonStyle.secondary, row=1)

        async def quick_cb(interaction: discord.Interaction) -> None:
            state = _root(self.user)
            if isinstance(state.get("active"), Mapping):
                await interaction.response.send_message(_t(self.locale, "이미 진행 중인 원정이 있습니다. `이어하기`를 눌러주세요.", "An expedition is already active. Press `Resume`."), ephemeral=True)
                return
            zone_key = _highest_zone(self.user)
            diff_key = str(state.get("default_difficulty") or "survivor")
            companions = _normalize_companions("", state.get("default_companions") or [])
            pass  # v18.1.3: _invoke_command owns the single interaction ACK
            await self.start(interaction, zone_key, diff_key if diff_key in DIFFICULTIES else "survivor", companions, str(state.get("preferred_seed") or ""))

        async def custom_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(ExpeditionSetupModal(self))

        async def resume_cb(interaction: discord.Interaction) -> None:
            state = _root(self.user)
            active = state.get("active") if isinstance(state.get("active"), MutableMapping) else None
            if not active:
                await interaction.response.send_message(_t(self.locale, "이어갈 원정이 없습니다.", "No expedition to resume."), ephemeral=True)
                return
            await interaction.response.edit_message(embed=_active_embed(self.locale, active), view=ActiveExpeditionView(self.bot, self.owner_id, self.locale, self.user, self.save_data))

        async def weekly_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(embed=_weekly_embed(self.locale), ephemeral=True)

        async def codex_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(embed=_codex_embed(self.locale, _root(self.user)), ephemeral=True)

        async def records_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(embed=_records_embed(self.locale, _root(self.user)), ephemeral=True)

        async def difficulty_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                embed=_difficulty_embed(self.locale, _root(self.user)),
                view=DifficultyView(self.owner_id, self.locale, self.user, self.save_data),
                ephemeral=True,
            )

        async def seed_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(_t(self.locale, "🧬 씨앗 코드는 같은 사건 순서를 재현합니다. 행동 선택이 달라지면 결과도 달라집니다. `!원정씨앗 AB12CD34`로 기본 코드를 저장할 수 있습니다.", "🧬 Seed codes reproduce the same event order. Different choices can still change outcomes. Save one with `!expeditionseed AB12CD34`."), ephemeral=True)

        quick.callback = quick_cb; custom.callback = custom_cb; resume.callback = resume_cb; weekly.callback = weekly_cb
        codex.callback = codex_cb; records.callback = records_cb; difficulty.callback = difficulty_cb; seed.callback = seed_cb
        for item in (quick, custom, resume, weekly, codex, records, difficulty, seed):
            self.add_item(item)

    async def start(self, interaction: discord.Interaction, zone_key: str, difficulty_key: str, companions: Sequence[str], seed: str) -> None:
        state = _root(self.user)
        if isinstance(state.get("active"), Mapping):
            await interaction.edit_original_response(content=_t(self.locale, "이미 진행 중인 원정이 있습니다.", "An expedition is already active."), embed=None, view=None)
            return
        session = _new_session(self.user, zone_key, difficulty_key, companions, seed)
        state["active"] = session
        state["default_difficulty"] = difficulty_key
        state["default_companions"] = list(companions)
        if seed:
            state["preferred_seed"] = _seed_code(seed)
        self.save_data()
        await interaction.edit_original_response(embed=_active_embed(self.locale, session, note=_t(self.locale, "🚪 원정 출발 · 모든 진행은 즉시 저장됩니다.", "🚪 Expedition started · every action is auto-saved.")), view=ActiveExpeditionView(self.bot, self.owner_id, self.locale, self.user, self.save_data))


class ActiveExpeditionView(OwnerView):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, user: MutableMapping[str, Any], save_data: Callable[[], None]) -> None:
        super().__init__(owner_id, timeout=1800)
        self.bot = bot
        self.locale = locale
        self.user = user
        self.save_data = save_data
        actions = (
            ("advance", "전진", "Advance", "🧭", discord.ButtonStyle.success),
            ("search", "수색", "Search", "🔍", discord.ButtonStyle.primary),
            ("camp", "야영", "Camp", "⛺", discord.ButtonStyle.secondary),
            ("special", "특수 행동", "Special", "✨", discord.ButtonStyle.primary),
            ("retreat", "철수", "Retreat", "🚪", discord.ButtonStyle.danger),
        )
        for action, ko, en, emoji, style in actions:
            button = discord.ui.Button(label=_t(locale, ko, en), emoji=emoji, style=style, row=0)
            async def callback(interaction: discord.Interaction, action=action) -> None:
                await self.act(interaction, action)
            button.callback = callback
            self.add_item(button)
        codex = discord.ui.Button(label=_t(locale, "현재 도감", "Codex"), emoji="📚", style=discord.ButtonStyle.secondary, row=1)
        record = discord.ui.Button(label=_t(locale, "진행 기록", "Run Log"), emoji="📜", style=discord.ButtonStyle.secondary, row=1)
        async def codex_cb(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(embed=_codex_embed(self.locale, _root(self.user)), ephemeral=True)
        async def record_cb(interaction: discord.Interaction) -> None:
            state = _root(self.user); active = state.get("active") if isinstance(state.get("active"), Mapping) else {}
            lines = []
            for row in list(active.get("log") or [])[-15:]:
                if isinstance(row, Mapping):
                    lines.append(str(row.get("en") if self.locale == "en" else row.get("ko") or ""))
            await interaction.response.send_message("\n".join(f"• {x}" for x in lines)[:1900] or _t(self.locale, "아직 기록이 없습니다.", "No log yet."), ephemeral=True)
        codex.callback = codex_cb; record.callback = record_cb
        self.add_item(codex); self.add_item(record)

    async def act(self, interaction: discord.Interaction, action: str) -> None:
        state = _root(self.user)
        session = state.get("active") if isinstance(state.get("active"), MutableMapping) else None
        if not session:
            await interaction.response.send_message(_t(self.locale, "진행 중인 원정이 없습니다.", "No active expedition."), ephemeral=True)
            return
        if action == "retreat":
            pass  # v18.1.3: _invoke_command owns the single interaction ACK
            embed, data = _finalize(self.user, state, session, "retreat", self.locale)
            self.save_data()
            await interaction.edit_original_response(embed=embed, view=ResultActionsView(self.bot, self.owner_id, self.locale, self.user, self.save_data, data))
            self.stop()
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        note = _resolve_action(self.locale, session, action)
        if _safe_int(session.get("hp"), 0) <= 0 or _safe_int(session.get("infection"), 0) >= 100:
            embed, data = _finalize(self.user, state, session, "rescue", self.locale)
            self.save_data()
            await interaction.edit_original_response(embed=embed, view=ResultActionsView(self.bot, self.owner_id, self.locale, self.user, self.save_data, data))
            self.stop()
            return
        if _safe_int(session.get("stage"), 0) >= _safe_int(session.get("total_stages"), 1) and bool(session.get("boss_defeated")):
            embed, data = _finalize(self.user, state, session, "victory", self.locale)
            self.save_data()
            await interaction.edit_original_response(embed=embed, view=ResultActionsView(self.bot, self.owner_id, self.locale, self.user, self.save_data, data))
            self.stop()
            return
        self.save_data()
        await interaction.edit_original_response(embed=_active_embed(self.locale, session, note=note), view=self)


class ResultActionsView(OwnerView):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, user: MutableMapping[str, Any], save_data: Callable[[], None], data: ResultActionsViewData) -> None:
        super().__init__(owner_id, timeout=600)
        self.bot = bot; self.locale = locale; self.user = user; self.save_data = save_data; self.data = data
        retry = discord.ui.Button(label=_t(locale, "같은 씨앗 재도전", "Retry Seed"), emoji="🔁", style=discord.ButtonStyle.success, row=0)
        new = discord.ui.Button(label=_t(locale, "새 원정", "New Run"), emoji="🧭", style=discord.ButtonStyle.primary, row=0)
        retry.callback = self.retry
        new.callback = self.new_run
        self.add_item(retry); self.add_item(new)
        for command, ko, en, emoji in (
            ("휴식", "회복", "Heal", "❤️"), ("제작목록", "제작", "Craft", "🔨"),
            ("도시꾸미기", "도시 배치", "City Decor", "🎨"), ("스토리나침반", "다음 스토리", "Next Story", "📖"),
        ):
            target = bot.get_command(command)
            if target is not None:
                self.add_item(LinkedCommandButton(bot, target.qualified_name, locale, ko, en, emoji, row=1))

    async def retry(self, interaction: discord.Interaction) -> None:
        state = _root(self.user)
        if isinstance(state.get("active"), Mapping):
            await interaction.response.send_message(_t(self.locale, "이미 진행 중인 원정이 있습니다.", "An expedition is already active."), ephemeral=True)
            return
        companions = _normalize_companions("", state.get("default_companions") or [])
        state["active"] = _new_session(self.user, self.data.zone, self.data.difficulty, companions, self.data.seed)
        self.save_data()
        await interaction.response.edit_message(embed=_active_embed(self.locale, state["active"], note=_t(self.locale, "🔁 같은 씨앗으로 재도전합니다.", "🔁 Retrying the same seed.")), view=ActiveExpeditionView(self.bot, self.owner_id, self.locale, self.user, self.save_data))

    async def new_run(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=_hub_embed(self.locale, self.user), view=ExpeditionHubView(self.bot, self.owner_id, self.locale, self.user, self.save_data))


def _difficulty_embed(locale: str, state: Mapping[str, Any]) -> discord.Embed:
    current = str(state.get("default_difficulty") or "survivor")
    embed = discord.Embed(title=_t(locale, "☠️ 원정 난이도", "☠️ Expedition Difficulty"), color=0xC0392B)
    for difficulty in DIFFICULTIES.values():
        marker = "✅" if difficulty.key == current else "▫️"
        embed.add_field(name=f"{marker} {difficulty.emoji} {_t(locale, difficulty.ko, difficulty.en)}", value=_t(locale, f"{difficulty.stages}단계 · 피해 ×{difficulty.damage:.2f} · 보상 ×{difficulty.reward:.2f} · 구조 보존 {round(difficulty.rescue_keep*100)}%", f"{difficulty.stages} stages · Damage ×{difficulty.damage:.2f} · Reward ×{difficulty.reward:.2f} · Rescue keeps {round(difficulty.rescue_keep*100)}%"), inline=False)
    return embed


class DifficultyView(OwnerView):
    def __init__(self, owner_id: int, locale: str, user: MutableMapping[str, Any], save_data: Callable[[], None]) -> None:
        super().__init__(owner_id, timeout=180)
        self.locale = locale; self.user = user; self.save_data = save_data
        for index, difficulty in enumerate(DIFFICULTIES.values()):
            button = discord.ui.Button(label=_t(locale, difficulty.ko, difficulty.en), emoji=difficulty.emoji, style=discord.ButtonStyle.secondary, row=index // 4)
            async def callback(interaction: discord.Interaction, key=difficulty.key) -> None:
                state = _root(self.user); state["default_difficulty"] = key; self.save_data()
                await interaction.response.edit_message(embed=_difficulty_embed(self.locale, state), view=DifficultyView(self.owner_id, self.locale, self.user, self.save_data))
            button.callback = callback
            self.add_item(button)


def _start_from_command(user: MutableMapping[str, Any], zone_raw: str, difficulty_raw: str, companions_raw: str, seed_raw: str) -> Tuple[bool, str, Optional[MutableMapping[str, Any]]]:
    state = _root(user)
    if isinstance(state.get("active"), Mapping):
        return False, "active", None
    zone_key = _normalize_zone(zone_raw) if zone_raw else _highest_zone(user)
    difficulty_key = _normalize_difficulty(difficulty_raw) if difficulty_raw else str(state.get("default_difficulty") or "survivor")
    if zone_key not in ZONES:
        return False, "zone", None
    if difficulty_key not in DIFFICULTIES:
        return False, "difficulty", None
    if _safe_int(user.get("level"), 1) < ZONES[zone_key].min_level:
        return False, f"level:{ZONES[zone_key].min_level}", None
    companions = _normalize_companions(companions_raw, state.get("default_companions") or [])
    session = _new_session(user, zone_key, difficulty_key, companions, seed_raw or str(state.get("preferred_seed") or ""))
    state["active"] = session
    state["default_difficulty"] = difficulty_key
    state["default_companions"] = companions
    return True, "", session


def register_v1680_lone_survivor(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    command_guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1680_registered", False):
        return
    bot._abaddon_v1680_registered = True

    @bot.command(name="솔로원정", aliases=["생존원정", "고독원정", "lonesurvivor", "soloexpedition"], help="혼자서 진행하는 버튼형 로그라이크 생존 원정 허브를 엽니다.")
    async def lone_survivor(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            return
        locale = _locale(ctx)
        await ctx.send(embed=_hub_embed(locale, user), view=ExpeditionHubView(bot, ctx.author.id, locale, user, save_data))

    @bot.command(name="솔로원정시작", aliases=["생존원정시작", "loneexpeditionstart", "soloexpeditionstart"], help="지역·난이도·NPC 동료·씨앗을 지정해 솔로 원정을 시작합니다.")
    async def lone_start(ctx: commands.Context, zone: str = "", difficulty: str = "", companions: str = "", seed: str = "") -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            return
        locale = _locale(ctx)
        ok, reason, session = _start_from_command(user, zone, difficulty, companions, seed)
        if not ok:
            messages = {
                "active": _t(locale, "이미 진행 중인 원정이 있습니다. `!원정이어하기`를 사용하세요.", "An expedition is already active. Use `!resumeexpedition`."),
                "zone": _t(locale, "지역을 찾지 못했습니다. `!솔로원정`에서 지역을 확인하세요.", "Unknown region. Check `!soloexpedition`."),
                "difficulty": _t(locale, "난이도를 찾지 못했습니다. 생존자/베테랑/악몽/심연 중 선택하세요.", "Unknown difficulty. Choose survivor/veteran/nightmare/abyss."),
            }
            if reason.startswith("level:"):
                message = _t(locale, f"해당 지역은 레벨 {reason.split(':')[1]}부터 입장할 수 있습니다.", f"That region requires level {reason.split(':')[1]}.")
            else:
                message = messages.get(reason, reason)
            await ctx.send(message)
            return
        save_data()
        await ctx.send(embed=_active_embed(locale, session or {}, note=_t(locale, "🚪 원정 출발 · 모든 행동은 자동 저장됩니다.", "🚪 Expedition started · every action is auto-saved.")), view=ActiveExpeditionView(bot, ctx.author.id, locale, user, save_data))

    @bot.command(name="원정이어하기", aliases=["솔로원정이어하기", "resumeexpedition", "resumeloneexpedition"], help="저장된 솔로 생존 원정을 마지막 단계부터 이어갑니다.")
    async def resume_expedition(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            return
        state = _root(user); active = state.get("active") if isinstance(state.get("active"), Mapping) else None
        locale = _locale(ctx)
        if not active:
            await ctx.send(_t(locale, "이어갈 솔로 원정이 없습니다. `!솔로원정`으로 시작하세요.", "No solo expedition to resume. Start with `!soloexpedition`."))
            return
        await ctx.send(embed=_active_embed(locale, active), view=ActiveExpeditionView(bot, ctx.author.id, locale, user, save_data))

    @bot.command(name="원정도감", aliases=["솔로원정도감", "expeditioncodex", "lonecodex"], help="솔로 원정에서 발견한 사건·적·NPC·유물·도시 설계도·결말을 확인합니다.")
    async def expedition_codex(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is not None:
            await ctx.send(embed=_codex_embed(_locale(ctx), _root(user)))

    @bot.command(name="주간변이지역", aliases=["주간원정", "weeklyanomaly", "weeklyexpedition"], help="이번 주 솔로 원정 변이 지역과 피해·보상 보정을 확인합니다.")
    async def weekly_anomaly(ctx: commands.Context) -> None:
        await ctx.send(embed=_weekly_embed(_locale(ctx)))

    @bot.command(name="원정씨앗", aliases=["솔로원정씨앗", "expeditionseed", "loneseed"], help="같은 사건 순서를 재현할 기본 원정 씨앗 코드를 저장하거나 확인합니다.")
    async def expedition_seed(ctx: commands.Context, code: str = "") -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            return
        locale = _locale(ctx); state = _root(user)
        if not code:
            saved = str(state.get("preferred_seed") or "")
            await ctx.send(_t(locale, f"🧬 저장된 씨앗: **`{saved or '없음'}`**\n같은 씨앗과 같은 행동은 같은 사건 흐름을 재현합니다.", f"🧬 Saved seed: **`{saved or 'none'}`**\nThe same seed and choices reproduce the same event flow."))
            return
        normalized = re.sub(r"[^A-Z0-9]", "", code.upper())[:12]
        if not SEED_RE.fullmatch(normalized):
            await ctx.send(_t(locale, "영문 대문자와 숫자 4~12자로 입력하세요.", "Use 4–12 uppercase letters and digits."))
            return
        state["preferred_seed"] = normalized; save_data()
        await ctx.send(_t(locale, f"✅ 기본 원정 씨앗을 **`{normalized}`**로 저장했습니다.", f"✅ Default expedition seed saved as **`{normalized}`**."))

    @bot.command(name="원정난이도", aliases=["솔로원정난이도", "expeditiondifficulty", "lonedifficulty"], help="솔로 원정 기본 난이도를 생존자·베테랑·악몽·심연 중 선택합니다.")
    async def expedition_difficulty(ctx: commands.Context, difficulty: str = "") -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            return
        locale = _locale(ctx); state = _root(user)
        if difficulty:
            key = _normalize_difficulty(difficulty)
            if key is None:
                await ctx.send(_t(locale, "생존자 / 베테랑 / 악몽 / 심연 중 선택하세요.", "Choose survivor / veteran / nightmare / abyss."))
                return
            state["default_difficulty"] = key; save_data()
        await ctx.send(embed=_difficulty_embed(locale, state), view=DifficultyView(ctx.author.id, locale, user, save_data))

    @bot.command(name="솔로원정기록", aliases=["생존원정기록", "loneexpeditionrecord", "solorecord"], help="솔로 원정 완주·철수·구조·최고 점수와 최근 씨앗 기록을 확인합니다.")
    async def lone_records(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is not None:
            await ctx.send(embed=_records_embed(_locale(ctx), _root(user)))

    @bot.command(name="솔로원정포기", aliases=["생존원정포기", "abandonloneexpedition"], help="진행 중인 솔로 원정을 확인 후 철수 처리하고 일부 전리품을 정산합니다.")
    async def abandon_lone(ctx: commands.Context, confirm: str = "") -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            return
        locale = _locale(ctx); state = _root(user); active = state.get("active") if isinstance(state.get("active"), MutableMapping) else None
        if not active:
            await ctx.send(_t(locale, "진행 중인 원정이 없습니다.", "No active expedition.")); return
        if confirm.casefold() not in {"확인", "confirm", "yes", "예"}:
            await ctx.send(_t(locale, "철수하려면 `!솔로원정포기 확인`을 입력하세요. 확보한 전리품의 60%가 지급됩니다.", "Use `!abandonloneexpedition confirm` to retreat. You will keep 60% of secured loot.")); return
        embed, data = _finalize(user, state, active, "retreat", locale); save_data()
        await ctx.send(embed=embed, view=ResultActionsView(bot, ctx.author.id, locale, user, save_data, data))

    @bot.command(name="1680통합검수", aliases=["v1680audit", "1680audit", "솔로원정검수"], help="v16.8 솔로 원정·씨앗·주간 변이·도감·저장 복구·구조·결과 정산 연결을 검사합니다.")
    async def v1680_audit(ctx: commands.Context, mode: str = "") -> None:
        locale = _locale(ctx)
        required = ("솔로원정", "솔로원정시작", "원정이어하기", "원정도감", "주간변이지역", "원정씨앗", "원정난이도", "솔로원정기록", "솔로원정포기")
        checks = [
            (_t(locale, "명령 등록", "Commands registered"), all(bot.get_command(name) is not None for name in required), f"{sum(bot.get_command(name) is not None for name in required)}/{len(required)}"),
            (_t(locale, "지역 데이터", "Region data"), len(ZONES) == 7, str(len(ZONES))),
            (_t(locale, "난이도", "Difficulties"), len(DIFFICULTIES) == 4, str(len(DIFFICULTIES))),
            (_t(locale, "NPC 동료", "NPC companions"), len(COMPANIONS) == 5, str(len(COMPANIONS))),
            (_t(locale, "주간 변이", "Weekly mutation"), _weekly_anomaly().get("zone") in ZONES, _weekly_anomaly().get("week", "-")),
            (_t(locale, "씨앗 결정성", "Seed determinism"), _seed_int("A", 1) == _seed_int("A", 1), "sha256"),
            (_t(locale, "구조 보호", "Rescue protection"), all(0 < x.rescue_keep < 1 for x in DIFFICULTIES.values()), "partial keep"),
            (_t(locale, "도시 설계도 호환", "City blueprint compatibility"), all(zone.blueprint in CITY_PART_LABELS for zone in ZONES.values()), f"{sum(zone.blueprint in CITY_PART_LABELS for zone in ZONES.values())}/7"),
            (_t(locale, "한영 UI 분리", "KO/EN UI separation"), all(zone.ko and zone.en for zone in ZONES.values()) and all(c.ko and c.en for c in COMPANIONS.values()), "separate labels"),
        ]
        passed = sum(ok for _label, ok, _detail in checks)
        embed = discord.Embed(title=_t(locale, "🧪 v16.8.0 솔로 원정 통합 검수", "🧪 v16.8.0 Lone Survivor Audit"), color=0x2ECC71 if passed == len(checks) else 0xE67E22)
        embed.description = f"**{passed}/{len(checks)}** {_t(locale, '통과', 'passed')}"
        for label, ok, detail in checks:
            embed.add_field(name=f"{'✅' if ok else '❌'} {label}", value=str(detail)[:1024], inline=False)
        embed.set_footer(text=_t(locale, "실제 Discord 동시 클릭과 장시간 중도 저장 복구는 배포 서버에서 최종 확인하세요.", "Verify concurrent interactions and long-duration resume on the deployed server."))
        await ctx.send(embed=embed)

    patch = bot.get_command("패치노트")
    if patch is not None and not patch.extras.get("v1680_previous_callback"):
        previous_patch = patch.callback
        async def patch_notes_v1680(ctx: commands.Context) -> None:
            locale = _locale(ctx)
            embed = discord.Embed(title=_t(locale, "🌑 ABADDON v16.8.0 — LONE SURVIVOR", "🌑 ABADDON v16.8.0 — LONE SURVIVOR"), color=0x6C2BD9)
            embed.description = _t(locale, "유저가 없어도 혼자 완주할 수 있는 개인 로그라이크 원정을 추가했습니다.", "Added a solo roguelite expedition designed to be fully playable alone.")
            embed.add_field(name=_t(locale, "🧭 개인 원정", "🧭 Solo Expedition"), value=_t(locale, "7개 지역 · 4개 난이도 · 6~9단계 · 선택형 전투·탐색·보스", "7 regions · 4 difficulties · 6–9 stages · choices, combat, exploration and bosses"), inline=False)
            embed.add_field(name=_t(locale, "👥 NPC 원정대", "👥 NPC Party"), value=_t(locale, "정찰·의무·기술·중화기·교섭 중 최대 2명 편성", "Choose up to 2: scout, medic, engineer, gunner or negotiator"), inline=False)
            embed.add_field(name=_t(locale, "🧬 반복 플레이", "🧬 Replayability"), value=_t(locale, "씨앗 코드 · 주간 변이 · 원정 도감 · 난이도별 보상", "Seed codes · weekly mutation · expedition codex · difficulty rewards"), inline=False)
            embed.add_field(name=_t(locale, "💾 안전성", "💾 Safety"), value=_t(locale, "행동마다 자동 저장 · 재시작 후 이어하기 · 사망 대신 긴급 구조", "Auto-save after every action · resume after restart · rescue instead of permanent death"), inline=False)
            embed.add_field(name=_t(locale, "🎁 기존 기능 연결", "🎁 Existing System Links"), value=_t(locale, "식량·EXP·재료·유물·도시 설계도 지급과 회복·제작·도시 공방·스토리 버튼", "Supplies, EXP, materials, relics, city blueprints and buttons to heal, craft, decorate and continue story"), inline=False)
            embed.set_footer(text="Korean / English separated · legacy commands preserved · 2026-08-06")
            await ctx.send(embed=embed)
        patch.callback = patch_notes_v1680
        patch.extras["v1680_previous_callback"] = previous_patch

    if not any(str(row.get("id")) == "v1680_lone_survivor" for row in command_guide):
        command_guide.append({
            "id": "v1680_lone_survivor",
            "title": "v16.8.0 LONE SURVIVOR",
            "commands": "!솔로원정 · !솔로원정시작 · !원정이어하기 · !원정도감 · !주간변이지역 · !원정씨앗 · !원정난이도 · !솔로원정기록",
            "description": "혼자서 진행하는 선택형 로그라이크 원정, NPC 편성, 씨앗, 주간 변이, 도감과 구조 보호입니다.",
        })


__all__ = ["register_v1680_lone_survivor", "ZONES", "DIFFICULTIES", "COMPANIONS", "_weekly_anomaly"]
