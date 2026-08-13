from __future__ import annotations

"""Pure state/rule helpers for ABADDON v13.2.0 BLACK CITY.

This module deliberately has no discord.py dependency so migrations, economy,
territory, market, season and rollback behavior can be tested offline.
"""

import copy
import hashlib
import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

VERSION = "13.2.0"
SCHEMA_VERSION = 1

DISTRICTS: Dict[str, Dict[str, Any]] = {
    "중앙카지노": {"en": "Central Casino", "kind": "casino", "unlock": 0, "economy": 5, "chaos": 3},
    "화투거리": {"en": "Hwatu Street", "kind": "cards", "unlock": 0, "culture": 5, "chaos": 1},
    "심야경마장": {"en": "Midnight Racetrack", "kind": "racing", "unlock": 0, "economy": 4, "chaos": 2},
    "상업지구": {"en": "Commerce Ward", "kind": "market", "unlock": 0, "economy": 6, "security": 1},
    "폐허지구": {"en": "Ruin Ward", "kind": "expedition", "unlock": 0, "chaos": 5, "security": -2},
    "항구": {"en": "Black Harbor", "kind": "trade", "unlock": 18, "economy": 4, "chaos": 2},
    "지하감옥": {"en": "Underground Prison", "kind": "crime", "unlock": 28, "security": 5, "chaos": 1},
    "악마시장": {"en": "Demon Market", "kind": "secret", "unlock": 40, "economy": 5, "chaos": 5},
    "월드관문": {"en": "World Gate", "kind": "boss", "unlock": 55, "prosperity": 5, "chaos": 4},
}

CITY_TRAITS: Tuple[Tuple[str, str], ...] = (
    ("불야성", "Never-Sleeping"),
    ("안개의 항구", "Harbor of Mist"),
    ("붉은 패의 거리", "Red-Card Quarter"),
    ("검은 황금도시", "Black-Gold City"),
    ("재난 위의 낙원", "Paradise Above Ruin"),
    ("무법과 질서의 경계", "Border of Law and Chaos"),
)

FACTION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "카지노연맹": {"en": "Casino Union", "focus": "economy", "bonus": "trade"},
    "붉은화투회": {"en": "Red Hwatu Society", "focus": "culture", "bonus": "cards"},
    "심야경마단": {"en": "Midnight Riders", "focus": "speed", "bonus": "racing"},
    "폐허탐험대": {"en": "Ruin Expedition", "focus": "exploration", "bonus": "gather"},
    "도시경비대": {"en": "City Guard", "focus": "security", "bonus": "defense"},
    "악마상인회": {"en": "Demon Merchants", "focus": "chaos", "bonus": "secret"},
}

PROFESSIONS: Dict[str, Dict[str, Any]] = {
    "대장장이": {"en": "Blacksmith", "resource": "철광", "district": "상업지구"},
    "연금술사": {"en": "Alchemist", "resource": "검은약초", "district": "폐허지구"},
    "탐정": {"en": "Detective", "resource": "단서", "district": "중앙카지노"},
    "조련사": {"en": "Tamer", "resource": "먹이", "district": "심야경마장"},
    "딜러": {"en": "Dealer", "resource": "카드조각", "district": "화투거리"},
    "경마조교사": {"en": "Race Trainer", "resource": "말편자", "district": "심야경마장"},
    "유물감정사": {"en": "Relic Appraiser", "resource": "유물파편", "district": "폐허지구"},
    "방송인": {"en": "Broadcaster", "resource": "방송토큰", "district": "중앙카지노"},
    "밀수업자": {"en": "Smuggler", "resource": "밀수상자", "district": "항구"},
    "도시행정관": {"en": "City Administrator", "resource": "행정문서", "district": "상업지구"},
}

RECIPES: Dict[str, Dict[str, Any]] = {
    "강화철판": {"en": "Reinforced Plate", "requires": {"철광": 4}, "value": 2600},
    "밤안개물약": {"en": "Night Mist Potion", "requires": {"검은약초": 3, "유리병": 1}, "value": 3100},
    "추적도구": {"en": "Tracking Kit", "requires": {"단서": 3, "철광": 1}, "value": 2800},
    "고급먹이": {"en": "Premium Feed", "requires": {"먹이": 4}, "value": 2100},
    "검은카드덱": {"en": "Black Card Deck", "requires": {"카드조각": 5}, "value": 3600},
    "행운의말편자": {"en": "Lucky Horseshoe", "requires": {"말편자": 4, "철광": 1}, "value": 3900},
    "복원유물": {"en": "Restored Relic", "requires": {"유물파편": 6}, "value": 5200},
    "중계드론": {"en": "Broadcast Drone", "requires": {"방송토큰": 4, "철광": 2}, "value": 4700},
    "밀봉화물": {"en": "Sealed Cargo", "requires": {"밀수상자": 3, "행정문서": 1}, "value": 5800},
    "도시허가증": {"en": "City Permit", "requires": {"행정문서": 5}, "value": 4200},
}

FACILITIES: Dict[str, Dict[str, Any]] = {
    "대형경기장": {"en": "Grand Arena", "cost": 100_000, "effect": "championship"},
    "서버박물관": {"en": "Server Museum", "cost": 80_000, "effect": "collection"},
    "공동금고": {"en": "Community Vault", "cost": 120_000, "effect": "security"},
    "전설경마장": {"en": "Legendary Racetrack", "cost": 90_000, "effect": "racing"},
    "월드보스관문": {"en": "World Boss Gate", "cost": 150_000, "effect": "boss"},
    "세력의회": {"en": "Faction Council", "cost": 110_000, "effect": "diplomacy"},
}

CRIMES: Dict[str, Dict[str, Any]] = {
    "NPC금고털이": {"en": "NPC Vault Heist", "difficulty": 45, "reward": 4200, "heat": 16},
    "밀수품운반": {"en": "Smuggling Run", "difficulty": 35, "reward": 3300, "heat": 11},
    "현상범추적": {"en": "Bounty Hunt", "difficulty": 55, "reward": 5200, "heat": 8},
    "감옥탈출": {"en": "Prison Break", "difficulty": 65, "reward": 6000, "heat": 22},
    "경비대추격": {"en": "Guard Chase", "difficulty": 50, "reward": 4600, "heat": 18},
}

NPCS: Dict[str, Dict[str, Any]] = {
    "시장레오나": {"en": "Mayor Leona", "home": "상업지구", "job": "시장"},
    "경비대장카인": {"en": "Captain Kain", "home": "지하감옥", "job": "경비대장"},
    "상인벨": {"en": "Merchant Belle", "home": "악마시장", "job": "상인"},
    "기자모라": {"en": "Reporter Mora", "home": "중앙카지노", "job": "기자"},
    "조교사로웬": {"en": "Trainer Rowen", "home": "심야경마장", "job": "조교사"},
    "감정사이브": {"en": "Appraiser Eve", "home": "폐허지구", "job": "감정사"},
}

SEASON_ENDINGS: Dict[str, Dict[str, str]] = {
    "번영도시": {"ko": "번영 도시", "en": "Prosperous City"},
    "카지노제국": {"ko": "카지노 제국", "en": "Casino Empire"},
    "무법도시": {"ko": "무법 도시", "en": "Outlaw City"},
    "폐허왕국": {"ko": "폐허 왕국", "en": "Kingdom of Ruin"},
    "악마시장지배": {"ko": "악마 시장 지배", "en": "Demon Market Dominion"},
    "시민연합승리": {"ko": "시민 연합 승리", "en": "Citizen Alliance Victory"},
    "아바돈각성": {"ko": "아바돈 각성", "en": "ABADDON Awakens"},
    "진엔딩": {"ko": "검은 도시의 진엔딩", "en": "True Ending of Black City"},
}


def now_ts() -> int:
    return int(time.time())


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def stable_seed(*parts: Any) -> int:
    raw = "|".join(str(x) for x in parts).encode("utf-8", "replace")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def normalize_token(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch not in " _-·/\\")


def json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def ensure_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("black_city_v1320", {})
    root.setdefault("schema", SCHEMA_VERSION)
    root.setdefault("guilds", {})
    root.setdefault("global_history", [])
    return root


def _default_districts() -> Dict[str, Dict[str, Any]]:
    return {
        name: {
            "name": name,
            "unlocked": int(spec.get("unlock", 0)) == 0,
            "owner": None,
            "defense": 20,
            "development": 1,
            "activity": 0,
        }
        for name, spec in DISTRICTS.items()
    }


def ensure_guild(root: MutableMapping[str, Any], guild_id: int, *, guild_name: str = "") -> MutableMapping[str, Any]:
    guilds = root.setdefault("guilds", {})
    key = str(int(guild_id or 0))
    row = guilds.setdefault(key, {})
    if not row.get("id"):
        seed = stable_seed(key, guild_name or "ABADDON")
        trait = CITY_TRAITS[seed % len(CITY_TRAITS)]
        row.update({
            "id": key,
            "name": f"{(guild_name or 'ABADDON')[:18]} 검은 도시",
            "trait": trait[0],
            "created_at": now_ts(),
            "metrics": {"prosperity": 20, "economy": 20, "security": 25, "chaos": 15, "fame": 10},
            "districts": _default_districts(),
            "factions": {},
            "diplomacy": {},
            "market": {"listings": {}, "ledger": [], "price_history": {}},
            "facilities": {},
            "construction_fund": 0,
            "crime": {"active": {}, "bounties": {}, "jail": {}, "trials": {}, "event_fund": 50_000},
            "npcs": {},
            "news": [],
            "history": [],
            "season": {},
            "settings": {
                "enabled": False,
                "public_world": False,
                "auto_news": False,
                "auto_npc": False,
                "auto_season": False,
                "channel_id": 0,
                "role_id": 0,
            },
            "backups": [],
            "audit_log": [],
            "ledger": {},
            "active_world_event": None,
            "last_tick": 0,
        })
    row.setdefault("metrics", {"prosperity": 20, "economy": 20, "security": 25, "chaos": 15, "fame": 10})
    row.setdefault("districts", _default_districts())
    for name, spec in _default_districts().items():
        row["districts"].setdefault(name, spec)
    row.setdefault("factions", {})
    row.setdefault("diplomacy", {})
    row.setdefault("market", {"listings": {}, "ledger": [], "price_history": {}})
    row["market"].setdefault("listings", {})
    row["market"].setdefault("ledger", [])
    row["market"].setdefault("price_history", {})
    row.setdefault("facilities", {})
    row.setdefault("construction_fund", 0)
    row.setdefault("crime", {"active": {}, "bounties": {}, "jail": {}, "trials": {}, "event_fund": 50_000})
    for k, default in {"active": {}, "bounties": {}, "jail": {}, "trials": {}, "event_fund": 50_000}.items():
        row["crime"].setdefault(k, copy.deepcopy(default))
    row.setdefault("npcs", {})
    row.setdefault("news", [])
    row.setdefault("history", [])
    row.setdefault("season", {})
    row.setdefault("settings", {})
    for k, v in {
        "enabled": False, "public_world": False, "auto_news": False,
        "auto_npc": False, "auto_season": False, "channel_id": 0, "role_id": 0,
    }.items():
        row["settings"].setdefault(k, v)
    row.setdefault("backups", [])
    row.setdefault("audit_log", [])
    row.setdefault("ledger", {})
    row.setdefault("active_world_event", None)
    row.setdefault("last_tick", 0)
    return row


def ensure_user(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault("black_city_v1320", {})
    row.setdefault("district", "중앙카지노")
    row.setdefault("faction", None)
    row.setdefault("profession", None)
    row.setdefault("profession_level", 1)
    row.setdefault("profession_exp", 0)
    row.setdefault("materials", {})
    row.setdefault("crafted", {})
    row.setdefault("hideout", {"owned": False, "level": 0, "theme": "빈방", "decorations": [], "public": False, "guestbook": []})
    row.setdefault("heat", 0)
    row.setdefault("reputation", 0)
    row.setdefault("jail_until", 0)
    row.setdefault("clues", 0)
    row.setdefault("bounties_completed", 0)
    row.setdefault("season_score", 0)
    row.setdefault("npc_requests", {})
    row.setdefault("discoveries", [])
    row.setdefault("last_gather_at", 0)
    row.setdefault("last_crime_at", 0)
    row.setdefault("last_move_at", 0)
    row.setdefault("stats", {"trades": 0, "crafts": 0, "territory_actions": 0, "crimes": 0, "arrests": 0})
    return row


def balance(user: Mapping[str, Any]) -> int:
    try:
        return int(user.get("balance", 0))
    except Exception:
        return 0


def add_balance(user: MutableMapping[str, Any], amount: int) -> int:
    user["balance"] = balance(user) + int(amount)
    return int(user["balance"])


def add_material(user: MutableMapping[str, Any], item: str, qty: int) -> int:
    row = ensure_user(user)
    mats = row.setdefault("materials", {})
    mats[item] = max(0, int(mats.get(item, 0)) + int(qty))
    return int(mats[item])


def add_history(guild: MutableMapping[str, Any], kind: str, text: str, *, actor_id: int = 0, data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    entry = {
        "id": make_id("HIS"), "at": now_ts(), "kind": str(kind), "text": str(text)[:500],
        "actor_id": int(actor_id or 0), "data": json_clone(dict(data or {})),
    }
    guild.setdefault("history", []).append(entry)
    guild["history"] = guild["history"][-500:]
    guild.setdefault("news", []).append(entry.copy())
    guild["news"] = guild["news"][-100:]
    return entry


def add_audit(guild: MutableMapping[str, Any], action: str, actor_id: int, data: Optional[Mapping[str, Any]] = None) -> None:
    guild.setdefault("audit_log", []).append({
        "id": make_id("AUD"), "at": now_ts(), "action": str(action),
        "actor_id": int(actor_id or 0), "data": json_clone(dict(data or {})),
    })
    guild["audit_log"] = guild["audit_log"][-300:]


def metric(guild: Mapping[str, Any], name: str) -> int:
    return int(guild.get("metrics", {}).get(name, 0))


def change_metrics(guild: MutableMapping[str, Any], **changes: int) -> Dict[str, int]:
    metrics = guild.setdefault("metrics", {})
    for key, value in changes.items():
        metrics[key] = clamp(int(metrics.get(key, 0)) + int(value))
    unlock_districts(guild)
    return {str(k): int(v) for k, v in metrics.items()}


def city_level(guild: Mapping[str, Any]) -> int:
    m = guild.get("metrics", {})
    return max(1, (int(m.get("prosperity", 0)) + int(m.get("economy", 0)) + int(m.get("fame", 0))) // 30)


def unlock_score(guild: Mapping[str, Any]) -> int:
    return metric(guild, "prosperity") + metric(guild, "fame") // 2


def unlock_districts(guild: MutableMapping[str, Any]) -> List[str]:
    score = unlock_score(guild)
    unlocked: List[str] = []
    for name, spec in DISTRICTS.items():
        row = guild.setdefault("districts", {}).setdefault(name, {"name": name})
        if not row.get("unlocked") and score >= int(spec.get("unlock", 0)):
            row["unlocked"] = True
            unlocked.append(name)
            add_history(guild, "district_unlock", f"새 지역 {name}이(가) 개방되었습니다.")
    return unlocked


def move_user(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], district: str) -> Tuple[bool, str]:
    city_user = ensure_user(user)
    resolved = next((name for name in DISTRICTS if normalize_token(name) == normalize_token(district)), None)
    if not resolved:
        return False, "존재하지 않는 지역입니다."
    state = guild.get("districts", {}).get(resolved, {})
    if not state.get("unlocked"):
        return False, "아직 잠겨 있는 지역입니다."
    city_user["district"] = resolved
    city_user["last_move_at"] = now_ts()
    state["activity"] = int(state.get("activity", 0)) + 1
    change_metrics(guild, fame=1 if int(state["activity"]) % 10 == 0 else 0)
    return True, resolved


def create_faction(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, name: str) -> Tuple[bool, str, Optional[MutableMapping[str, Any]]]:
    city_user = ensure_user(user)
    if city_user.get("faction"):
        return False, "이미 세력에 가입되어 있습니다.", None
    clean = " ".join(str(name or "").split())[:24]
    if len(clean) < 2:
        return False, "세력 이름은 2자 이상이어야 합니다.", None
    for existing in guild.setdefault("factions", {}):
        if normalize_token(existing) == normalize_token(clean):
            return False, "같은 이름의 세력이 이미 있습니다.", None
    if balance(user) < 20_000:
        return False, "세력 창설에는 20,000칩이 필요합니다.", None
    add_balance(user, -20_000)
    faction = {
        "id": make_id("FAC"), "name": clean, "leader_id": int(user_id),
        "members": [int(user_id)], "treasury": 10_000, "power": 10,
        "territories": [], "wins": 0, "losses": 0, "created_at": now_ts(),
        "open": True, "motto": "검은 도시에서 살아남는다.",
    }
    guild["factions"][clean] = faction
    city_user["faction"] = clean
    add_history(guild, "faction_create", f"{clean} 세력이 창설되었습니다.", actor_id=user_id)
    return True, clean, faction


def join_faction(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, name: str) -> Tuple[bool, str]:
    city_user = ensure_user(user)
    if city_user.get("faction"):
        return False, "이미 세력에 가입되어 있습니다."
    resolved = next((x for x in guild.get("factions", {}) if normalize_token(x) == normalize_token(name)), None)
    if not resolved:
        return False, "세력을 찾지 못했습니다."
    faction = guild["factions"][resolved]
    if not faction.get("open", True):
        return False, "가입이 닫힌 세력입니다."
    members = faction.setdefault("members", [])
    if int(user_id) not in members:
        members.append(int(user_id))
    city_user["faction"] = resolved
    faction["power"] = int(faction.get("power", 0)) + 2
    add_history(guild, "faction_join", f"새 시민이 {resolved}에 가입했습니다.", actor_id=user_id)
    return True, resolved


def leave_faction(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int) -> Tuple[bool, str]:
    city_user = ensure_user(user)
    name = city_user.get("faction")
    if not name or name not in guild.get("factions", {}):
        city_user["faction"] = None
        return False, "가입한 세력이 없습니다."
    faction = guild["factions"][name]
    if int(faction.get("leader_id", 0)) == int(user_id) and len(faction.get("members", [])) > 1:
        return False, "세력장은 다른 구성원에게 위임한 뒤 탈퇴해야 합니다."
    faction["members"] = [int(x) for x in faction.get("members", []) if int(x) != int(user_id)]
    city_user["faction"] = None
    if not faction["members"]:
        for district in guild.get("districts", {}).values():
            if district.get("owner") == name:
                district["owner"] = None
        guild["factions"].pop(name, None)
        add_history(guild, "faction_disband", f"{name} 세력이 해산되었습니다.", actor_id=user_id)
    return True, str(name)


def faction_power(guild: Mapping[str, Any], name: str) -> int:
    fac = guild.get("factions", {}).get(name, {})
    return int(fac.get("power", 0)) + len(fac.get("members", [])) * 3 + int(fac.get("treasury", 0)) // 10_000


def territory_attack(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, district: str, *, nonce: str = "") -> Dict[str, Any]:
    city_user = ensure_user(user)
    faction_name = city_user.get("faction")
    if not faction_name or faction_name not in guild.get("factions", {}):
        return {"ok": False, "message": "세력에 가입해야 합니다."}
    resolved = next((x for x in DISTRICTS if normalize_token(x) == normalize_token(district)), None)
    if not resolved:
        return {"ok": False, "message": "지역을 찾지 못했습니다."}
    district_state = guild.get("districts", {}).get(resolved, {})
    if not district_state.get("unlocked"):
        return {"ok": False, "message": "잠긴 지역입니다."}
    owner = district_state.get("owner")
    if owner == faction_name:
        district_state["defense"] = min(100, int(district_state.get("defense", 20)) + 5)
        return {"ok": True, "won": True, "defended": True, "district": resolved, "owner": faction_name}
    action_id = make_id("WAR")
    seed = stable_seed(guild.get("id"), user_id, resolved, nonce or action_id, now_ts() // 300)
    attack = faction_power(guild, faction_name) + 10 + seed % 31
    defense = int(district_state.get("defense", 20)) + (faction_power(guild, str(owner)) if owner else 15) + (seed // 31) % 21
    won = attack >= defense
    fac = guild["factions"][faction_name]
    ensure_user(user)["stats"]["territory_actions"] = int(ensure_user(user)["stats"].get("territory_actions", 0)) + 1
    if won:
        old_owner = owner
        district_state["owner"] = faction_name
        district_state["defense"] = 25
        if resolved not in fac.setdefault("territories", []):
            fac["territories"].append(resolved)
        fac["wins"] = int(fac.get("wins", 0)) + 1
        fac["power"] = int(fac.get("power", 0)) + 3
        if old_owner and old_owner in guild.get("factions", {}):
            other = guild["factions"][old_owner]
            other["territories"] = [x for x in other.get("territories", []) if x != resolved]
            other["losses"] = int(other.get("losses", 0)) + 1
        change_metrics(guild, fame=2, chaos=2, security=-1)
        add_history(guild, "territory_change", f"{faction_name}이(가) {resolved}을(를) 점령했습니다.", actor_id=user_id, data={"old_owner": old_owner})
    else:
        fac["losses"] = int(fac.get("losses", 0)) + 1
        district_state["defense"] = min(100, int(district_state.get("defense", 20)) + 2)
        change_metrics(guild, chaos=1)
    return {"ok": True, "won": won, "district": resolved, "attack": attack, "defense": defense, "owner": district_state.get("owner"), "id": action_id}


def set_diplomacy(guild: MutableMapping[str, Any], actor_faction: str, target: str, state: str) -> Tuple[bool, str]:
    if actor_faction not in guild.get("factions", {}) or target not in guild.get("factions", {}):
        return False, "세력을 찾지 못했습니다."
    if actor_faction == target:
        return False, "자기 세력과 외교할 수 없습니다."
    token = normalize_token(state)
    resolved = "중립"
    if token in {"동맹", "alliance", "ally"}: resolved = "동맹"
    elif token in {"적대", "war", "hostile"}: resolved = "적대"
    elif token in {"휴전", "truce"}: resolved = "휴전"
    key = "|".join(sorted((actor_faction, target)))
    guild.setdefault("diplomacy", {})[key] = {"state": resolved, "updated_at": now_ts()}
    add_history(guild, "diplomacy", f"{actor_faction}과(와) {target}의 관계가 {resolved}(으)로 변경되었습니다.")
    return True, resolved


def choose_profession(user: MutableMapping[str, Any], name: str) -> Tuple[bool, str]:
    resolved = next((x for x in PROFESSIONS if normalize_token(x) == normalize_token(name)), None)
    if not resolved:
        return False, "직업을 찾지 못했습니다."
    row = ensure_user(user)
    if row.get("profession") and row.get("profession") != resolved and balance(user) < 5_000:
        return False, "직업 변경에는 5,000칩이 필요합니다."
    if row.get("profession") and row.get("profession") != resolved:
        add_balance(user, -5_000)
    row["profession"] = resolved
    return True, resolved


def gather(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, *, timestamp: Optional[int] = None) -> Dict[str, Any]:
    timestamp = int(timestamp or now_ts())
    row = ensure_user(user)
    profession = row.get("profession")
    if profession not in PROFESSIONS:
        return {"ok": False, "message": "먼저 도시 직업을 선택하세요."}
    remaining = 300 - (timestamp - int(row.get("last_gather_at", 0)))
    if remaining > 0:
        return {"ok": False, "message": "채집 재사용 대기 중입니다.", "remaining": remaining}
    spec = PROFESSIONS[profession]
    seed = stable_seed(guild.get("id"), user_id, profession, timestamp // 300)
    qty = 2 + seed % 4 + max(0, int(row.get("profession_level", 1)) // 5)
    resource = str(spec["resource"])
    add_material(user, resource, qty)
    if seed % 5 == 0:
        add_material(user, "유리병", 1)
    row["profession_exp"] = int(row.get("profession_exp", 0)) + qty * 3
    need = int(row.get("profession_level", 1)) * 50
    leveled = False
    if int(row["profession_exp"]) >= need:
        row["profession_exp"] -= need
        row["profession_level"] = int(row.get("profession_level", 1)) + 1
        leveled = True
    row["last_gather_at"] = timestamp
    change_metrics(guild, prosperity=1 if seed % 4 == 0 else 0, economy=1 if seed % 3 == 0 else 0)
    return {"ok": True, "resource": resource, "qty": qty, "leveled": leveled, "level": row["profession_level"]}


def craft(user: MutableMapping[str, Any], item: str, qty: int = 1) -> Dict[str, Any]:
    resolved = next((x for x in RECIPES if normalize_token(x) == normalize_token(item)), None)
    if not resolved:
        return {"ok": False, "message": "제작법을 찾지 못했습니다."}
    qty = max(1, min(20, int(qty)))
    row = ensure_user(user)
    mats = row.setdefault("materials", {})
    recipe = RECIPES[resolved]
    missing = {k: int(v) * qty - int(mats.get(k, 0)) for k, v in recipe["requires"].items() if int(mats.get(k, 0)) < int(v) * qty}
    if missing:
        return {"ok": False, "message": "재료가 부족합니다.", "missing": missing}
    for material, required in recipe["requires"].items():
        mats[material] = int(mats.get(material, 0)) - int(required) * qty
    row.setdefault("crafted", {})[resolved] = int(row.setdefault("crafted", {}).get(resolved, 0)) + qty
    row["stats"]["crafts"] = int(row["stats"].get("crafts", 0)) + qty
    return {"ok": True, "item": resolved, "qty": qty}


def user_item_count(user: Mapping[str, Any], item: str) -> int:
    row = user.get("black_city_v1320", {}) if isinstance(user, Mapping) else {}
    return int(row.get("crafted", {}).get(item, 0))


def create_listing(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], seller_id: int, item: str, qty: int, price_each: int) -> Dict[str, Any]:
    resolved = next((x for x in RECIPES if normalize_token(x) == normalize_token(item)), None)
    if not resolved:
        return {"ok": False, "message": "판매 가능한 제작품을 찾지 못했습니다."}
    qty = max(1, min(100, int(qty)))
    price_each = max(1, min(100_000_000, int(price_each)))
    row = ensure_user(user)
    crafted = row.setdefault("crafted", {})
    if int(crafted.get(resolved, 0)) < qty:
        return {"ok": False, "message": "보유 수량이 부족합니다."}
    crafted[resolved] = int(crafted.get(resolved, 0)) - qty
    listing_id = make_id("MKT")
    listing = {
        "id": listing_id, "seller_id": int(seller_id), "item": resolved, "qty": qty,
        "price_each": price_each, "created_at": now_ts(), "status": "open", "buyer_id": 0,
    }
    guild.setdefault("market", {}).setdefault("listings", {})[listing_id] = listing
    add_history(guild, "market_list", f"{resolved} {qty}개가 거래소에 등록되었습니다.", actor_id=seller_id)
    return {"ok": True, "listing": listing}


def cancel_listing(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], seller_id: int, listing_id: str) -> Dict[str, Any]:
    listing = guild.get("market", {}).get("listings", {}).get(str(listing_id).upper())
    if not isinstance(listing, MutableMapping) or listing.get("status") != "open":
        return {"ok": False, "message": "열려 있는 판매 글을 찾지 못했습니다."}
    if int(listing.get("seller_id", 0)) != int(seller_id):
        return {"ok": False, "message": "판매자만 취소할 수 있습니다."}
    listing["status"] = "cancelled"
    row = ensure_user(user)
    item = str(listing["item"])
    row.setdefault("crafted", {})[item] = int(row.setdefault("crafted", {}).get(item, 0)) + int(listing.get("qty", 0))
    return {"ok": True, "listing": listing}


def buy_listing(
    guild: MutableMapping[str, Any], buyer: MutableMapping[str, Any], seller: MutableMapping[str, Any],
    buyer_id: int, listing_id: str,
) -> Dict[str, Any]:
    listing = guild.get("market", {}).get("listings", {}).get(str(listing_id).upper())
    if not isinstance(listing, MutableMapping) or listing.get("status") != "open":
        return {"ok": False, "message": "판매 중인 항목을 찾지 못했습니다."}
    if int(listing.get("seller_id", 0)) == int(buyer_id):
        return {"ok": False, "message": "자기 판매 글은 구매할 수 없습니다."}
    tx_key = f"market:{listing.get('id')}"
    if tx_key in guild.setdefault("ledger", {}):
        return {"ok": False, "message": "이미 처리된 거래입니다."}
    total = int(listing.get("qty", 0)) * int(listing.get("price_each", 0))
    if balance(buyer) < total:
        return {"ok": False, "message": "잔액이 부족합니다.", "total": total}
    fee = max(1, total * 3 // 100)
    add_balance(buyer, -total)
    add_balance(seller, total - fee)
    buyer_row = ensure_user(buyer)
    item = str(listing["item"])
    buyer_row.setdefault("crafted", {})[item] = int(buyer_row.setdefault("crafted", {}).get(item, 0)) + int(listing.get("qty", 0))
    listing["status"] = "sold"
    listing["buyer_id"] = int(buyer_id)
    listing["sold_at"] = now_ts()
    tx = {
        "id": make_id("TX"), "listing_id": listing["id"], "buyer_id": int(buyer_id),
        "seller_id": int(listing["seller_id"]), "item": item, "qty": int(listing["qty"]),
        "total": total, "fee": fee, "at": now_ts(),
    }
    guild["ledger"][tx_key] = tx
    market = guild.setdefault("market", {})
    market.setdefault("ledger", []).append(tx)
    market["ledger"] = market["ledger"][-500:]
    market.setdefault("price_history", {}).setdefault(item, []).append({"price": int(listing["price_each"]), "at": now_ts()})
    market["price_history"][item] = market["price_history"][item][-50:]
    buyer_row["stats"]["trades"] = int(buyer_row["stats"].get("trades", 0)) + 1
    ensure_user(seller)["stats"]["trades"] = int(ensure_user(seller)["stats"].get("trades", 0)) + 1
    change_metrics(guild, economy=1, prosperity=1)
    add_history(guild, "market_sale", f"{item} {listing['qty']}개 거래가 체결되었습니다.", actor_id=buyer_id, data={"tx": tx["id"]})
    return {"ok": True, "tx": tx}


def market_prices(guild: Mapping[str, Any]) -> Dict[str, Dict[str, int]]:
    result: Dict[str, Dict[str, int]] = {}
    for item, rows in guild.get("market", {}).get("price_history", {}).items():
        values = [int(x.get("price", 0)) for x in rows if isinstance(x, Mapping) and int(x.get("price", 0)) > 0]
        if values:
            result[str(item)] = {"last": values[-1], "avg": sum(values) // len(values), "count": len(values)}
    return result


def buy_hideout(user: MutableMapping[str, Any]) -> Tuple[bool, str]:
    row = ensure_user(user)
    home = row["hideout"]
    if home.get("owned"):
        return False, "이미 아지트를 보유하고 있습니다."
    if balance(user) < 15_000:
        return False, "아지트 구매에는 15,000칩이 필요합니다."
    add_balance(user, -15_000)
    home.update({"owned": True, "level": 1, "theme": "검은벽돌", "public": False})
    return True, "검은벽돌"


def decorate_hideout(user: MutableMapping[str, Any], decoration: str) -> Tuple[bool, str]:
    row = ensure_user(user)
    home = row["hideout"]
    if not home.get("owned"):
        return False, "먼저 아지트를 구매하세요."
    clean = " ".join(str(decoration or "").split())[:30]
    if not clean:
        return False, "장식 이름을 입력하세요."
    cost = 2_000 + len(home.get("decorations", [])) * 500
    if balance(user) < cost:
        return False, f"장식 설치에 {cost:,}칩이 필요합니다."
    add_balance(user, -cost)
    if clean not in home.setdefault("decorations", []):
        home["decorations"].append(clean)
    return True, clean


def donate_facility(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, facility: str, amount: int) -> Dict[str, Any]:
    resolved = next((x for x in FACILITIES if normalize_token(x) == normalize_token(facility)), None)
    if not resolved:
        return {"ok": False, "message": "공동 시설을 찾지 못했습니다."}
    amount = max(1, int(amount))
    if balance(user) < amount:
        return {"ok": False, "message": "잔액이 부족합니다."}
    state = guild.setdefault("facilities", {}).setdefault(resolved, {"progress": 0, "complete": False, "contributors": {}})
    if state.get("complete"):
        return {"ok": False, "message": "이미 완공된 시설입니다."}
    add_balance(user, -amount)
    state["progress"] = int(state.get("progress", 0)) + amount
    state.setdefault("contributors", {})[str(user_id)] = int(state.setdefault("contributors", {}).get(str(user_id), 0)) + amount
    cost = int(FACILITIES[resolved]["cost"])
    complete = int(state["progress"]) >= cost
    if complete:
        state["complete"] = True
        state["completed_at"] = now_ts()
        change_metrics(guild, prosperity=5, fame=4, security=2 if FACILITIES[resolved]["effect"] == "security" else 0)
        add_history(guild, "facility_complete", f"공동 시설 {resolved}이(가) 완공되었습니다.", actor_id=user_id)
    return {"ok": True, "facility": resolved, "amount": amount, "progress": state["progress"], "cost": cost, "complete": complete}


def create_bounty(guild: MutableMapping[str, Any], creator: MutableMapping[str, Any], creator_id: int, target_id: int, amount: int, reason: str) -> Dict[str, Any]:
    amount = max(100, min(1_000_000, int(amount)))
    if int(target_id) == int(creator_id):
        return {"ok": False, "message": "자기 자신에게 현상금을 걸 수 없습니다."}
    if balance(creator) < amount:
        return {"ok": False, "message": "잔액이 부족합니다."}
    add_balance(creator, -amount)
    bounty_id = make_id("BNT")
    bounty = {
        "id": bounty_id, "creator_id": int(creator_id), "target_id": int(target_id),
        "amount": amount, "reason": str(reason or "도시 의뢰")[:120], "status": "open", "created_at": now_ts(),
    }
    guild.setdefault("crime", {}).setdefault("bounties", {})[bounty_id] = bounty
    add_history(guild, "bounty", f"선택형 현상금 임무 {bounty_id}가 등록되었습니다.", actor_id=creator_id)
    return {"ok": True, "bounty": bounty}


def attempt_crime(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, crime: str, *, timestamp: Optional[int] = None) -> Dict[str, Any]:
    timestamp = int(timestamp or now_ts())
    row = ensure_user(user)
    if int(row.get("jail_until", 0)) > timestamp:
        return {"ok": False, "message": "수감 중에는 범죄 임무를 시작할 수 없습니다.", "remaining": int(row["jail_until"]) - timestamp}
    resolved = next((x for x in CRIMES if normalize_token(x) == normalize_token(crime)), None)
    if not resolved:
        return {"ok": False, "message": "범죄 임무를 찾지 못했습니다."}
    remain = 600 - (timestamp - int(row.get("last_crime_at", 0)))
    if remain > 0:
        return {"ok": False, "message": "범죄 임무 재사용 대기 중입니다.", "remaining": remain}
    spec = CRIMES[resolved]
    seed = stable_seed(guild.get("id"), user_id, resolved, timestamp // 600)
    skill = int(row.get("reputation", 0)) // 5 + int(row.get("profession_level", 1)) * 2
    roll = seed % 101 + skill
    success = roll >= int(spec["difficulty"])
    reward = 0
    row["last_crime_at"] = timestamp
    row["stats"]["crimes"] = int(row["stats"].get("crimes", 0)) + 1
    row["heat"] = clamp(int(row.get("heat", 0)) + int(spec["heat"]) - (5 if success else 0))
    if success:
        reward = min(int(spec["reward"]), int(guild.setdefault("crime", {}).get("event_fund", 0)))
        guild["crime"]["event_fund"] = int(guild["crime"].get("event_fund", 0)) - reward
        add_balance(user, reward)
        row["reputation"] = int(row.get("reputation", 0)) + 2
        change_metrics(guild, chaos=2, economy=1, security=-1)
        add_history(guild, "crime_success", f"선택형 범죄 임무 {resolved}이(가) 성공했습니다.", actor_id=user_id)
    else:
        row["heat"] = clamp(int(row.get("heat", 0)) + 10)
        change_metrics(guild, security=1, chaos=1)
    return {"ok": True, "crime": resolved, "success": success, "reward": reward, "heat": row["heat"], "roll": roll}


def investigate(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int, target_id: int) -> Dict[str, Any]:
    row = ensure_user(user)
    seed = stable_seed(guild.get("id"), user_id, target_id, now_ts() // 300)
    clues = 1 + seed % 3
    row["clues"] = int(row.get("clues", 0)) + clues
    change_metrics(guild, security=1)
    return {"ok": True, "clues": clues, "total": row["clues"], "target_id": int(target_id)}


def arrest(guild: MutableMapping[str, Any], officer: MutableMapping[str, Any], target: MutableMapping[str, Any], officer_id: int, target_id: int) -> Dict[str, Any]:
    officer_row = ensure_user(officer)
    target_row = ensure_user(target)
    if int(officer_row.get("clues", 0)) < 3:
        return {"ok": False, "message": "체포에는 단서 3개가 필요합니다."}
    if int(target_row.get("heat", 0)) < 25:
        return {"ok": False, "message": "대상의 수배도가 아직 낮습니다."}
    officer_row["clues"] = int(officer_row.get("clues", 0)) - 3
    seed = stable_seed(guild.get("id"), officer_id, target_id, now_ts() // 300)
    success = (seed % 100 + int(officer_row.get("reputation", 0))) >= max(30, int(target_row.get("heat", 0)) // 2)
    if success:
        until = now_ts() + 600 + int(target_row.get("heat", 0)) * 10
        target_row["jail_until"] = until
        target_row["heat"] = max(0, int(target_row.get("heat", 0)) - 20)
        officer_row["stats"]["arrests"] = int(officer_row["stats"].get("arrests", 0)) + 1
        add_balance(officer, 1500)
        guild.setdefault("crime", {}).setdefault("jail", {})[str(target_id)] = {"until": until, "officer_id": int(officer_id), "at": now_ts()}
        change_metrics(guild, security=3, chaos=-2)
        add_history(guild, "arrest", "도시 경비 임무에서 수배범이 체포되었습니다.", actor_id=officer_id, data={"target_id": target_id})
    return {"ok": True, "success": success, "target_id": int(target_id), "jail_until": int(target_row.get("jail_until", 0))}


def attempt_escape(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int) -> Dict[str, Any]:
    row = ensure_user(user)
    if int(row.get("jail_until", 0)) <= now_ts():
        row["jail_until"] = 0
        return {"ok": False, "message": "현재 수감 중이 아닙니다."}
    seed = stable_seed(guild.get("id"), user_id, row.get("jail_until"), now_ts() // 300)
    success = seed % 100 < 30
    if success:
        row["jail_until"] = 0
        row["heat"] = clamp(int(row.get("heat", 0)) + 20)
        guild.setdefault("crime", {}).setdefault("jail", {}).pop(str(user_id), None)
        change_metrics(guild, chaos=3, security=-2)
        add_history(guild, "escape", "한 수감자가 지하 감옥에서 탈출했습니다.", actor_id=user_id)
    return {"ok": True, "success": success, "remaining": max(0, int(row.get("jail_until", 0)) - now_ts())}


def ensure_npcs(guild: MutableMapping[str, Any], *, timestamp: Optional[int] = None) -> MutableMapping[str, Any]:
    timestamp = int(timestamp or now_ts())
    hour = time.gmtime(timestamp + 9 * 3600).tm_hour
    for name, spec in NPCS.items():
        row = guild.setdefault("npcs", {}).setdefault(name, {})
        row.setdefault("name", name)
        row.setdefault("mood", "평온")
        row.setdefault("relationship", {})
        row.setdefault("event", None)
        row.setdefault("last_event_at", 0)
        # A simple schedule with deterministic night movement.
        if 0 <= hour < 6:
            location = "악마시장" if name in {"상인벨", "기자모라"} else spec["home"]
            status = "심야 활동"
        elif 6 <= hour < 9:
            location = spec["home"]
            status = "출근 준비"
        elif 9 <= hour < 19:
            location = spec["home"]
            status = "근무 중"
        else:
            location = "중앙카지노" if name != "경비대장카인" else "지하감옥"
            status = "도시 순찰" if name == "경비대장카인" else "휴식"
        row["location"] = location
        row["status"] = status
    return guild["npcs"]


def npc_tick(guild: MutableMapping[str, Any], *, timestamp: Optional[int] = None) -> Optional[Dict[str, Any]]:
    timestamp = int(timestamp or now_ts())
    ensure_npcs(guild, timestamp=timestamp)
    if timestamp - int(guild.get("last_npc_event_at", 0)) < 1800:
        return None
    seed = stable_seed(guild.get("id"), timestamp // 1800, metric(guild, "chaos"))
    if seed % 3:
        return None
    names = list(NPCS)
    actor = names[seed % len(names)]
    other = names[(seed // 7) % len(names)]
    if actor == other:
        other = names[(names.index(actor) + 1) % len(names)]
    events = [
        ("다툼", f"{actor}와(과) {other}이(가) 상업지구에서 말다툼을 벌였습니다.", {"chaos": 2}),
        ("협력", f"{actor}와(과) {other}이(가) 시민 의뢰를 함께 해결했습니다.", {"prosperity": 2, "fame": 1}),
        ("실종", f"{actor}이(가) 폐허지구에서 잠시 실종되었습니다.", {"chaos": 3, "security": -1}),
        ("귀환", f"{actor}이(가) 유물과 함께 도시로 귀환했습니다.", {"prosperity": 2, "fame": 2}),
        ("대회", f"{actor}이(가) NPC 전용 카드 대회를 열었습니다.", {"fame": 3, "economy": 1}),
    ]
    kind, text, changes = events[(seed // 13) % len(events)]
    change_metrics(guild, **changes)
    guild["last_npc_event_at"] = timestamp
    entry = add_history(guild, f"npc_{kind}", text)
    guild["npcs"][actor]["event"] = entry["id"]
    guild["npcs"][actor]["last_event_at"] = timestamp
    return entry


def create_npc_request(guild: MutableMapping[str, Any], user: MutableMapping[str, Any], user_id: int) -> Dict[str, Any]:
    ensure_npcs(guild)
    row = ensure_user(user)
    seed = stable_seed(guild.get("id"), user_id, now_ts() // 86400)
    npc = list(NPCS)[seed % len(NPCS)]
    request_id = f"REQ-{now_ts() // 86400}-{npc}"
    existing = row.setdefault("npc_requests", {}).get(request_id)
    if existing:
        return {"ok": True, "request": existing, "existing": True}
    options = [
        ("도시채집", "도시에서 자원을 한 번 채집하세요.", 1800),
        ("도시제작", "제작품을 하나 만드세요.", 2500),
        ("도시이동", "다른 지역을 방문하세요.", 1200),
        ("건설기부", "공동 시설에 기부하세요.", 2200),
        ("도시거래소", "거래소를 확인하세요.", 1000),
    ]
    command, text, reward = options[(seed // 11) % len(options)]
    request = {"id": request_id, "npc": npc, "command": command, "text": text, "reward": reward, "status": "open", "created_at": now_ts()}
    row["npc_requests"][request_id] = request
    return {"ok": True, "request": request, "existing": False}


def ensure_season(guild: MutableMapping[str, Any], *, timestamp: Optional[int] = None) -> MutableMapping[str, Any]:
    timestamp = int(timestamp or now_ts())
    season = guild.setdefault("season", {})
    if not season.get("id") or int(season.get("ends_at", 0)) <= timestamp:
        previous = season.get("ending")
        season.clear()
        season.update({
            "id": make_id("SEA"), "number": int(guild.get("season_count", 0)) + 1,
            "started_at": timestamp, "ends_at": timestamp + 28 * 86400,
            "stage": 1, "score": {"development": 0, "faction": 0, "disaster": 0, "boss": 0},
            "ending": None, "completed": False, "previous_ending": previous,
        })
        guild["season_count"] = int(season["number"])
        add_history(guild, "season_start", f"BLACK CITY 시즌 {season['number']}이 시작되었습니다.")
    update_season_stage(guild, timestamp=timestamp)
    return season


def update_season_stage(guild: MutableMapping[str, Any], *, timestamp: Optional[int] = None) -> int:
    timestamp = int(timestamp or now_ts())
    season = guild.get("season", {})
    if not season:
        return 0
    elapsed = max(0, timestamp - int(season.get("started_at", timestamp)))
    stage = min(4, elapsed // (7 * 86400) + 1)
    if int(season.get("stage", 1)) != stage:
        season["stage"] = int(stage)
        add_history(guild, "season_stage", f"도시 시즌이 {stage}주차 단계로 진입했습니다.")
    return int(stage)


def determine_ending(guild: Mapping[str, Any]) -> str:
    m = guild.get("metrics", {})
    prosperity = int(m.get("prosperity", 0)); economy = int(m.get("economy", 0))
    security = int(m.get("security", 0)); chaos = int(m.get("chaos", 0)); fame = int(m.get("fame", 0))
    faction_count = len(guild.get("factions", {}))
    facilities = sum(1 for x in guild.get("facilities", {}).values() if x.get("complete"))
    demon_owner = guild.get("districts", {}).get("악마시장", {}).get("owner")
    boss_score = int(guild.get("season", {}).get("score", {}).get("boss", 0))
    if facilities >= 5 and prosperity >= 75 and security >= 65 and boss_score >= 50:
        return "진엔딩"
    if chaos >= 80 and fame >= 70:
        return "아바돈각성"
    if demon_owner and chaos >= 60:
        return "악마시장지배"
    if security >= 75 and faction_count >= 3:
        return "시민연합승리"
    if chaos >= 70 and security <= 35:
        return "무법도시"
    if economy >= 80 and guild.get("districts", {}).get("중앙카지노", {}).get("owner"):
        return "카지노제국"
    if prosperity <= 25 and chaos >= 55:
        return "폐허왕국"
    return "번영도시"


def finish_season(guild: MutableMapping[str, Any], *, force: bool = False, timestamp: Optional[int] = None) -> Dict[str, Any]:
    timestamp = int(timestamp or now_ts())
    season = ensure_season(guild, timestamp=timestamp)
    if not force and timestamp < int(season.get("ends_at", 0)):
        return {"ok": False, "message": "아직 시즌이 끝나지 않았습니다.", "remaining": int(season["ends_at"]) - timestamp}
    ending = determine_ending(guild)
    season["ending"] = ending
    season["completed"] = True
    season["completed_at"] = timestamp
    add_history(guild, "season_end", f"시즌 {season['number']} 결말: {SEASON_ENDINGS[ending]['ko']}")
    # Soft reset only volatile pressure; keep history, collection, factions and facilities.
    metrics = guild.setdefault("metrics", {})
    metrics["chaos"] = clamp((int(metrics.get("chaos", 0)) + 20) // 2)
    metrics["economy"] = clamp((int(metrics.get("economy", 0)) + 30) // 2)
    metrics["security"] = clamp((int(metrics.get("security", 0)) + 40) // 2)
    return {"ok": True, "ending": ending, "season": json_clone(season)}


def city_tick(guild: MutableMapping[str, Any], *, timestamp: Optional[int] = None) -> Dict[str, Any]:
    timestamp = int(timestamp or now_ts())
    last = int(guild.get("last_tick", 0))
    if last and timestamp - last < 300:
        return {"changed": False, "next_in": 300 - (timestamp - last)}
    guild["last_tick"] = timestamp
    ensure_npcs(guild, timestamp=timestamp)
    season = ensure_season(guild, timestamp=timestamp)
    event = npc_tick(guild, timestamp=timestamp) if guild.get("settings", {}).get("auto_npc") else None
    # Passive city pressure, deterministic per 5-minute window.
    seed = stable_seed(guild.get("id"), timestamp // 300)
    changes = {
        "economy": 1 if seed % 7 == 0 else 0,
        "chaos": 1 if seed % 11 == 0 else 0,
        "security": -1 if seed % 17 == 0 else 0,
    }
    change_metrics(guild, **changes)
    return {"changed": True, "npc_event": event, "stage": int(season.get("stage", 1)), "changes": changes}


def create_backup(guild: MutableMapping[str, Any], actor_id: int, *, limit: int = 10) -> Dict[str, Any]:
    backup_id = make_id("CITY")
    snapshot = {k: copy.deepcopy(v) for k, v in guild.items() if k != "backups"}
    record = {"id": backup_id, "created_at": now_ts(), "actor_id": int(actor_id), "snapshot": snapshot}
    guild.setdefault("backups", []).append(record)
    guild["backups"] = guild["backups"][-max(1, int(limit)):]
    add_audit(guild, "backup", actor_id, {"backup_id": backup_id})
    return {"id": backup_id, "created_at": record["created_at"], "actor_id": int(actor_id)}


def restore_backup(guild: MutableMapping[str, Any], backup_id: str, actor_id: int) -> Dict[str, Any]:
    record = next((x for x in guild.get("backups", []) if str(x.get("id", "")).upper() == str(backup_id).upper()), None)
    if not record:
        return {"ok": False, "message": "도시 백업을 찾지 못했습니다."}
    before_backups = copy.deepcopy(guild.get("backups", []))
    snapshot = copy.deepcopy(record.get("snapshot", {}))
    guild.clear()
    guild.update(snapshot)
    guild["backups"] = before_backups
    add_audit(guild, "restore", actor_id, {"backup_id": record["id"]})
    return {"ok": True, "backup_id": record["id"]}


def economy_audit(guild: Mapping[str, Any], users: Mapping[Any, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    open_listings = 0
    escrow_value = 0
    for listing in guild.get("market", {}).get("listings", {}).values():
        if not isinstance(listing, Mapping):
            issues.append("거래소에 잘못된 레코드가 있습니다.")
            continue
        if listing.get("status") == "open":
            open_listings += 1
            qty = int(listing.get("qty", 0)); price = int(listing.get("price_each", 0))
            if qty <= 0 or price <= 0:
                issues.append(f"판매글 {listing.get('id')} 수량/가격 오류")
            escrow_value += max(0, qty * price)
    duplicate_tx = len(guild.get("ledger", {})) != len(set(guild.get("ledger", {}).keys()))
    if duplicate_tx:
        issues.append("거래 원장 키 중복")
    negative_extreme = []
    for uid, user in users.items():
        if isinstance(user, Mapping) and balance(user) < -1_000_000_000:
            negative_extreme.append(str(uid))
    if negative_extreme:
        issues.append(f"비정상적으로 낮은 잔액 {len(negative_extreme)}건")
    return {
        "ok": not issues,
        "issues": issues,
        "open_listings": open_listings,
        "escrow_value": escrow_value,
        "transactions": len(guild.get("market", {}).get("ledger", [])),
        "event_fund": int(guild.get("crime", {}).get("event_fund", 0)),
        "negative_extreme": negative_extreme,
    }


def full_audit(guild: Mapping[str, Any], users: Mapping[Any, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    def check(name: str, ok: bool, detail: Any = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    check("도시 ID", bool(guild.get("id")), guild.get("id"))
    check("도시 지표 범위", all(0 <= int(x) <= 100 for x in guild.get("metrics", {}).values()), guild.get("metrics"))
    check("지역 9개", len(guild.get("districts", {})) == len(DISTRICTS), len(guild.get("districts", {})))
    owners = [x.get("owner") for x in guild.get("districts", {}).values() if x.get("owner")]
    check("영토 소유 세력 유효", all(x in guild.get("factions", {}) for x in owners), owners)
    members: List[int] = []
    for fac in guild.get("factions", {}).values():
        members.extend(int(x) for x in fac.get("members", []))
    check("세력 중복 가입 없음", len(members) == len(set(members)), len(members))
    econ = economy_audit(guild, users)
    check("경제 원장", econ["ok"], econ["issues"])
    check("공동시설 정의", all(x in FACILITIES for x in guild.get("facilities", {})), list(guild.get("facilities", {})))
    check("범죄 이벤트 자금", int(guild.get("crime", {}).get("event_fund", 0)) >= 0, guild.get("crime", {}).get("event_fund"))
    check("시즌 상태", not guild.get("season") or bool(guild.get("season", {}).get("id")), guild.get("season", {}).get("id"))
    check("백업 JSON 직렬화", _jsonable(guild.get("backups", [])), len(guild.get("backups", [])))
    return {"ok": all(x["ok"] for x in checks), "passed": sum(1 for x in checks if x["ok"]), "total": len(checks), "checks": checks, "economy": econ}


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False)
        return True
    except Exception:
        return False


def public_snapshot(guild: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a privacy-safe website payload. No user IDs or private inventories."""
    if not guild.get("settings", {}).get("public_world"):
        return {"status": "private", "city_id": str(guild.get("id", ""))}
    districts = []
    for name, row in guild.get("districts", {}).items():
        districts.append({
            "name": name, "unlocked": bool(row.get("unlocked")),
            "owner": str(row.get("owner") or ""), "development": int(row.get("development", 1)),
        })
    return {
        "status": "online",
        "version": VERSION,
        "city": {"name": str(guild.get("name", "")), "trait": str(guild.get("trait", "")), "level": city_level(guild)},
        "metrics": {k: int(v) for k, v in guild.get("metrics", {}).items()},
        "districts": districts,
        "factions": [
            {"name": name, "members": len(row.get("members", [])), "territories": len(row.get("territories", [])), "power": int(row.get("power", 0))}
            for name, row in guild.get("factions", {}).items()
        ],
        "season": {
            "number": int(guild.get("season", {}).get("number", 0)),
            "stage": int(guild.get("season", {}).get("stage", 0)),
            "ending": guild.get("season", {}).get("ending"),
            "ends_at": int(guild.get("season", {}).get("ends_at", 0)),
        },
        "news": [
            {"id": str(x.get("id", "")), "at": int(x.get("at", 0)), "kind": str(x.get("kind", "")), "text": str(x.get("text", ""))}
            for x in list(guild.get("news", []))[-12:]
        ],
        "updated_at": now_ts(),
    }
