from __future__ import annotations

import copy
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v637_dynamic_events import consume_weapon_durability

VERSION = "7.0.0"
ROOT_KEY = "world_boss_v630"
DAILY_ATTACK_LIMIT = 10
TEST_ATTACK_LIMIT = 50
ATTACK_COOLDOWN_SECONDS = 45
HISTORY_LIMIT = 12
REWARD_ARCHIVE_LIMIT = 30
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "world_boss"

BOSSES: Mapping[str, Dict[str, Any]] = {
    "gatekeeper": {
        "name": "검은 성역의 문지기",
        "aliases": ("문지기", "성역", "게이트"),
        "grade": "전설",
        "max_hp": 1_200_000,
        "trait": "흑철 방벽",
        "material": "성역의 흑철",
        "weakness": "강화 5단계 이상 무기",
        "image": "gatekeeper.png",
        "color": 0xBE263E,
        "dodge": 0.04,
        "defense": 0.18,
        "counter": (70, 240),
        "parts": {"방벽 핵": 240_000, "봉인 사슬": 180_000},
        "lore": "검은 성역의 문을 지키며 생존자의 공격 기록을 수집하는 고대 수문장.",
        "patterns": (
            "🛡️ 흑철 방벽이 닫히며 이번 공격 피해가 감소했습니다.",
            "⛓️ 봉인 사슬이 전장을 휘감아 다음 공격의 명중률을 흔듭니다.",
            "🔻 성역의 문양이 붉게 빛나며 반격이 강화됩니다.",
        ),
    },
    "atlas": {
        "name": "방사능 거신 아틀라스",
        "aliases": ("아틀라스", "거신", "방사능"),
        "grade": "신화",
        "max_hp": 1_500_000,
        "trait": "방사능 노심",
        "material": "오염된 노심",
        "weakness": "방호 장비와 기술자 직업",
        "image": "atlas.png",
        "color": 0x4FDC75,
        "dodge": 0.02,
        "defense": 0.13,
        "counter": (100, 320),
        "parts": {"노심 냉각관": 260_000, "오른팔 장갑": 230_000},
        "lore": "오래된 원자로와 융합한 거대 병기. 걸음을 옮길 때마다 지표가 오염된다.",
        "patterns": (
            "☢️ 노심이 폭주해 전장에 방사능 구름이 퍼졌습니다.",
            "🦾 장갑판이 맞물리며 물리 방어가 일시적으로 상승했습니다.",
            "⚡ 축전기가 방전되며 공격자 주변 장비에 충격을 줍니다.",
        ),
    },
    "nemesis": {
        "name": "심연 포식자 네메시스",
        "aliases": ("네메시스", "포식자", "심연"),
        "grade": "신화",
        "max_hp": 1_350_000,
        "trait": "생명 흡수",
        "material": "심연의 점액핵",
        "weakness": "화염 계열 장비와 치명타",
        "image": "nemesis.png",
        "color": 0x7647D2,
        "dodge": 0.08,
        "defense": 0.08,
        "counter": (80, 270),
        "parts": {"포식 기관": 220_000, "심연 촉수": 190_000},
        "lore": "바닥 없는 균열에서 올라온 포식체. 피해 일부를 먹어 치워 자신의 생명으로 바꾼다.",
        "patterns": (
            "🩸 네메시스가 흩어진 생명 신호를 흡수해 체력을 회복했습니다.",
            "🕳️ 심연의 입이 열리며 공격 궤적 일부가 사라졌습니다.",
            "🟣 촉수가 지면을 뚫고 올라와 공격자의 발을 묶었습니다.",
        ),
    },
    "babel": {
        "name": "폐허의 기계왕 바벨",
        "aliases": ("바벨", "기계왕", "기계"),
        "grade": "유일",
        "max_hp": 1_650_000,
        "trait": "자가 수복 장갑",
        "material": "바벨 구동축",
        "weakness": "고철·광석 계열 자원 보유량",
        "image": "babel.png",
        "color": 0xDB8029,
        "dodge": 0.03,
        "defense": 0.20,
        "counter": (120, 360),
        "parts": {"중앙 연산핵": 300_000, "왼팔 포대": 240_000},
        "lore": "폐허의 공장 전체를 몸으로 삼은 전쟁 기계. 파괴된 부품을 주변 잔해로 즉시 교체한다.",
        "patterns": (
            "🔧 주변 고철이 바벨의 장갑에 달라붙어 손상 부위를 메웠습니다.",
            "🚨 자동 포대가 공격자를 추적하며 제압 사격을 시작합니다.",
            "⚙️ 중앙 연산핵이 공격 패턴을 분석해 방어 수치를 재조정했습니다.",
        ),
    },
    "ark_ghost": {
        "name": "백색 방주의 망령",
        "aliases": ("망령", "백색 방주", "방주"),
        "grade": "유일",
        "max_hp": 1_450_000,
        "trait": "환영 분신",
        "material": "백색 기억결정",
        "weakness": "스토리 시즌 2 기록과 원정 유물",
        "image": "ark_ghost.png",
        "color": 0xA4DAEE,
        "dodge": 0.13,
        "defense": 0.07,
        "counter": (60, 220),
        "parts": {"기억 닻": 210_000, "환영 투영기": 200_000},
        "lore": "백색 방주에 남은 마지막 항해 기록이 사람의 형상을 얻은 존재.",
        "patterns": (
            "👻 환영 분신이 진짜 몸을 가리며 공격 일부가 허공을 갈랐습니다.",
            "🤍 기억 파동이 전장을 덮어 과거의 목소리가 들려옵니다.",
            "🪞 공격자의 움직임을 복제한 분신이 반대편에서 나타났습니다.",
        ),
    },
    "abaddon": {
        "name": "종말의 왕 아바돈",
        "aliases": ("아바돈", "종말의 왕", "왕좌"),
        "grade": "종말",
        "max_hp": 2_500_000,
        "trait": "왕좌의 심판",
        "material": "왕좌의 검은 파편",
        "weakness": "서버 전체의 다양한 역할 참여",
        "image": "abaddon.png",
        "color": 0xDE223F,
        "dodge": 0.08,
        "defense": 0.16,
        "counter": (160, 480),
        "parts": {"종말의 왕관": 420_000, "왕좌의 심장": 380_000, "검은 날개": 310_000},
        "lore": "모든 종말 신호가 수렴한 왕좌의 주인. 서버 공동 전투의 최종 시험.",
        "patterns": (
            "👑 왕좌의 심판이 내려와 전장의 모든 신호가 잠시 정지했습니다.",
            "🌑 검은 날개가 하늘을 덮으며 치명타 방어가 상승했습니다.",
            "🔥 종말의 불꽃이 번져 공격자들의 장비를 시험합니다.",
        ),
    },
}


PHASE_NAMES = {1: "탐색 단계", 2: "적응 단계", 3: "붕괴 단계", 4: "광폭화 단계"}
PHASE_RULES: Mapping[int, Dict[str, float]] = {
    1: {"defense": 0.00, "dodge": 0.00, "damage_taken": 1.00, "pattern": 0.16, "counter": 0.18, "counter_mult": 1.00},
    2: {"defense": 0.03, "dodge": 0.01, "damage_taken": 0.97, "pattern": 0.24, "counter": 0.25, "counter_mult": 1.05},
    3: {"defense": -0.03, "dodge": 0.00, "damage_taken": 1.08, "pattern": 0.32, "counter": 0.32, "counter_mult": 1.20},
    4: {"defense": 0.04, "dodge": 0.02, "damage_taken": 0.90, "pattern": 0.44, "counter": 0.45, "counter_mult": 1.55},
}

PART_EFFECTS: Mapping[str, Mapping[str, Dict[str, Any]]] = {
    "gatekeeper": {
        "방벽 핵": {"description": "흑철 방벽 약화 · 방어력 -8%", "defense": -0.08},
        "봉인 사슬": {"description": "속박 해제 · 회피 -4%, 반격률 -8%", "dodge": -0.04, "counter": -0.08},
    },
    "atlas": {
        "노심 냉각관": {"description": "노심 불안정 · 패턴률 -8%, 회복 봉쇄", "pattern": -0.08, "heal_mult": 0.0},
        "오른팔 장갑": {"description": "타격 장치 파손 · 반격률 -10%, 반격 피해 -45%", "counter": -0.10, "counter_mult": 0.55},
    },
    "nemesis": {
        "포식 기관": {"description": "생명 흡수 봉쇄 · 체력 회복 불가", "heal_mult": 0.0},
        "심연 촉수": {"description": "촉수 제압 · 회피 -5%, 반격률 -6%", "dodge": -0.05, "counter": -0.06},
    },
    "babel": {
        "중앙 연산핵": {"description": "연산 오류 · 방어력 -8%, 자가 수복 봉쇄", "defense": -0.08, "heal_mult": 0.0},
        "왼팔 포대": {"description": "제압 포대 정지 · 반격률 -12%, 반격 피해 -50%", "counter": -0.12, "counter_mult": 0.50},
    },
    "ark_ghost": {
        "기억 닻": {"description": "현실 고정 해제 · 방어력 -6%", "defense": -0.06},
        "환영 투영기": {"description": "분신 소멸 · 회피 -9%, 환영 피해 감소 제거", "dodge": -0.09, "disable_illusion": True},
    },
    "abaddon": {
        "종말의 왕관": {"description": "심판 약화 · 방어력 -6%", "defense": -0.06},
        "왕좌의 심장": {"description": "왕좌 노출 · 받는 피해 +10%", "damage_taken": 0.10},
        "검은 날개": {"description": "천공 봉쇄 · 회피 -5%, 반격률 -8%", "dodge": -0.05, "counter": -0.08},
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _date_key() -> str:
    return _utc_now().astimezone().strftime("%Y-%m-%d")


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _bar(current: int, maximum: int, size: int = 20) -> str:
    ratio = max(0.0, min(1.0, current / max(1, maximum)))
    filled = int(round(ratio * size))
    return "█" * filled + "░" * (size - filled)


def _boss_key(query: Optional[str]) -> Optional[str]:
    text = str(query or "").strip().casefold()
    if not text:
        return None
    for key, info in BOSSES.items():
        candidates = (key, info["name"], *info.get("aliases", ()))
        if any(text == str(item).casefold() or text in str(item).casefold() for item in candidates):
            return key
    return None


def _root(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("guilds", {})
    if not isinstance(root.get("guilds"), dict):
        root["guilds"] = {}
    root["version"] = VERSION
    return root


def _guild_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = _root(world_data)
    state = root["guilds"].setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        root["guilds"][str(guild_id)] = state
    state.setdefault("active", None)
    state.setdefault("test_active", None)
    state.setdefault("completed", [])
    state.setdefault("history", [])
    state.setdefault("sequence", 0)
    state.setdefault(
        "legacy_migrated",
        bool(isinstance(state.get("active"), dict) or state.get("completed") or state.get("history") or _safe_int(state.get("sequence"), 0, 0)),
    )
    if not isinstance(state.get("completed"), list):
        state["completed"] = []
    if not isinstance(state.get("history"), list):
        state["history"] = []
    return state


def _new_battle(
    state: Dict[str, Any],
    key: str,
    *,
    hp_override: Optional[int] = None,
    test: bool = False,
) -> Dict[str, Any]:
    info = BOSSES[key]
    state["sequence"] = _safe_int(state.get("sequence"), 0, 0) + 1
    maximum = max(1, _safe_int(hp_override if hp_override is not None else info["max_hp"], 1, 1))
    mode_tag = "T" if test else "R"
    battle_id = f"{mode_tag}-{_utc_now().strftime('%Y%m%d%H%M%S')}-{int(state['sequence']):03d}"
    battle = {
        "battle_id": battle_id,
        "boss_key": key,
        "name": info["name"],
        "max_hp": maximum,
        "hp": maximum,
        "phase": 1,
        "status": "active",
        "spawned_at": _iso_now(),
        "defeated_at": "",
        "participants": {},
        "rewards_claimed": [],
        "killer_id": None,
        "parts": {
            name: {
                "target": max(1, int(target * maximum / info["max_hp"])),
                "damage": 0,
                "broken": False,
            }
            for name, target in info.get("parts", {}).items()
        },
        "event_log": [],
        "test": bool(test),
    }
    state["test_active" if test else "active"] = battle
    if not test:
        state["legacy_migrated"] = True
    return battle


def _archive_completed(state: Dict[str, Any], battle: Dict[str, Any]) -> bool:
    if not isinstance(battle, dict) or battle.get("test") or battle.get("status") != "defeated":
        return False
    battle_id = str(battle.get("battle_id", ""))
    completed = state.setdefault("completed", [])
    if any(isinstance(item, dict) and str(item.get("battle_id", "")) == battle_id for item in completed):
        return False
    snapshot = copy.deepcopy(battle)
    if not isinstance(snapshot.get("rewards_claimed"), list):
        snapshot["rewards_claimed"] = []
    completed.insert(0, snapshot)
    # 보상을 받지 않은 전투는 절대로 잘라내지 않습니다. 전원 수령 완료 전투만 오래된 순서로 정리합니다.
    while len(completed) > REWARD_ARCHIVE_LIMIT:
        removable_index = None
        for index in range(len(completed) - 1, -1, -1):
            item = completed[index]
            if not isinstance(item, dict):
                removable_index = index
                break
            raw_participants = item.get("participants", {})
            participant_ids = {
                str(uid)
                for uid, row in raw_participants.items()
                if isinstance(raw_participants, dict)
                and isinstance(row, dict)
                and _safe_int(row.get("damage"), 0, 0) > 0
            } if isinstance(raw_participants, dict) else set()
            raw_claimed = item.get("rewards_claimed", [])
            claimed_ids = set(str(uid) for uid in raw_claimed if uid is not None) if isinstance(raw_claimed, list) else set()
            if not participant_ids or participant_ids.issubset(claimed_ids):
                removable_index = index
                break
        if removable_index is None:
            break
        completed.pop(removable_index)
    return True


def _migrate_legacy(world_data: Dict[str, Any], guild_id: int) -> Optional[Dict[str, Any]]:
    state = _guild_state(world_data, guild_id)
    if isinstance(state.get("active"), dict):
        return state["active"]
    if state.get("legacy_migrated"):
        return None
    state["legacy_migrated"] = True
    legacy = world_data.get("world_boss")
    if not isinstance(legacy, dict) or not legacy.get("name"):
        return None
    legacy_participants = legacy.get("participants", {})
    # core/bot.py가 호환성을 위해 빈 구형 보스를 자동 생성하므로,
    # 실제 참가 기록이 있는 구형 전투만 7.0 데이터로 이관합니다.
    if not isinstance(legacy_participants, dict) or not legacy_participants:
        return None
    key = _boss_key(str(legacy.get("name"))) or random.choice(tuple(BOSSES))
    battle = _new_battle(state, key, hp_override=max(1, _safe_int(legacy.get("max_hp", BOSSES[key]["max_hp"]), 1, 1)))
    battle["hp"] = max(0, min(int(battle["max_hp"]), _safe_int(legacy.get("hp", battle["max_hp"]), battle["max_hp"], 0)))
    battle["status"] = "defeated" if battle["hp"] <= 0 or legacy.get("status") == "defeated" else "active"
    participants = legacy_participants
    if isinstance(participants, dict):
        for uid, row in participants.items():
            if isinstance(row, dict):
                damage = _safe_int(row.get("damage"), 0, 0)
                attacks = _safe_int(row.get("attacks"), 0, 0)
            else:
                damage = _safe_int(row, 0, 0)
                attacks = 0
            battle["participants"][str(uid)] = {
                "damage": damage,
                "attacks": attacks,
                "last_at": "",
                "daily": {"date": _date_key(), "count": 0},
                "job": "",
            }
    if battle["status"] == "defeated":
        battle.setdefault("defeated_at", _iso_now())
        _archive_completed(state, battle)
        state["active"] = None
        return None
    return battle


def _battle(world_data: Dict[str, Any], guild_id: int, *, test: bool = False) -> Optional[Dict[str, Any]]:
    state = _guild_state(world_data, guild_id)
    slot = "test_active" if test else "active"
    battle = state.get(slot)
    if not isinstance(battle, dict) and not test:
        battle = _migrate_legacy(world_data, guild_id)
    if not isinstance(battle, dict):
        return None
    if battle.get("status") == "defeated":
        if not test:
            _archive_completed(state, battle)
        state[slot] = None
        return None
    return battle


def _rows(battle: Dict[str, Any]) -> List[Tuple[str, int, int]]:
    rows: List[Tuple[str, int, int]] = []
    participants = battle.get("participants", {})
    if isinstance(participants, dict):
        for uid, row in participants.items():
            if not isinstance(row, dict):
                continue
            rows.append((str(uid), _safe_int(row.get("damage"), 0, 0), _safe_int(row.get("attacks"), 0, 0)))
    return sorted(rows, key=lambda item: (-item[1], item[0]))


def _phase_for(hp: int, maximum: int) -> int:
    ratio = hp / max(1, maximum)
    if ratio <= 0.25:
        return 4
    if ratio <= 0.50:
        return 3
    if ratio <= 0.75:
        return 2
    return 1


def _part_broken(battle: Dict[str, Any], name: str) -> bool:
    part = battle.get("parts", {}).get(name, {}) if isinstance(battle.get("parts"), dict) else {}
    return isinstance(part, dict) and bool(part.get("broken"))


def _mechanics(battle: Dict[str, Any], info: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(battle.get("boss_key", "gatekeeper"))
    phase = _safe_int(battle.get("phase"), 1, 1)
    rule = PHASE_RULES.get(phase, PHASE_RULES[4])
    result: Dict[str, Any] = {
        "defense": float(info.get("defense", 0.0)) + rule["defense"],
        "dodge": float(info.get("dodge", 0.0)) + rule["dodge"],
        "damage_taken": rule["damage_taken"],
        "pattern": rule["pattern"],
        "counter": rule["counter"],
        "counter_mult": rule["counter_mult"],
        "heal_mult": 1.0,
        "disable_illusion": False,
    }
    for part_name, part in battle.get("parts", {}).items():
        if not isinstance(part, dict) or not part.get("broken"):
            continue
        effect = PART_EFFECTS.get(key, {}).get(str(part_name), {})
        for field in ("defense", "dodge", "pattern", "counter"):
            result[field] += float(effect.get(field, 0.0))
        if "damage_taken" in effect:
            result["damage_taken"] += float(effect["damage_taken"])
        if "counter_mult" in effect:
            result["counter_mult"] *= float(effect["counter_mult"])
        if "heal_mult" in effect:
            result["heal_mult"] *= float(effect["heal_mult"])
        if effect.get("disable_illusion"):
            result["disable_illusion"] = True
    result["defense"] = max(0.0, min(0.55, float(result["defense"])))
    result["dodge"] = max(0.0, min(0.35, float(result["dodge"])))
    result["pattern"] = max(0.05, min(0.70, float(result["pattern"])))
    result["counter"] = max(0.0, min(0.70, float(result["counter"])))
    result["counter_mult"] = max(0.20, float(result["counter_mult"]))
    result["damage_taken"] = max(0.55, min(1.45, float(result["damage_taken"])))
    return result


def _equipment_names(user: Mapping[str, Any]) -> List[str]:
    equipment = user.get("equipment", {})
    if not isinstance(equipment, dict):
        return []
    return [str(name) for name in equipment.values() if name]


def _max_weapon_enhancement(user: Mapping[str, Any]) -> int:
    equipment = user.get("equipment", {}) if isinstance(user.get("equipment"), dict) else {}
    weapon = equipment.get("무기")
    enhancements = user.get("enhancements", {}) if isinstance(user.get("enhancements"), dict) else {}
    return _safe_int(enhancements.get(str(weapon), 0), 0, 0) if weapon else 0


def _weakness_multiplier(
    user: Mapping[str, Any],
    key: str,
    battle: Dict[str, Any],
    *,
    critical: bool,
) -> Tuple[float, List[str]]:
    multiplier = 1.0
    labels: List[str] = []
    names = _equipment_names(user)
    joined = " ".join(names)

    if key == "gatekeeper":
        enhance = _max_weapon_enhancement(user)
        if enhance >= 5:
            bonus = min(0.28, 0.15 + max(0, enhance - 5) * 0.025)
            multiplier += bonus
            labels.append(f"강화 +{enhance} 무기 {bonus * 100:.0f}%")

    elif key == "atlas":
        bonus = 0.0
        if str(user.get("job") or "") == "기술자":
            bonus += 0.18
            labels.append("기술자 18%")
        defensive_keywords = ("방호", "방독", "방탄", "갑옷", "강화복", "전술복", "아크리액터", "밀폐")
        if any(keyword in joined for keyword in defensive_keywords):
            bonus += 0.10
            labels.append("방호 장비 10%")
        multiplier += min(0.28, bonus)

    elif key == "nemesis":
        bonus = 0.0
        fire_keywords = ("화염", "불꽃", "용암", "인페르노", "소각", "열선", "화염방사")
        if any(keyword in joined for keyword in fire_keywords):
            bonus += 0.18
            labels.append("화염 장비 18%")
        if critical:
            bonus += 0.12
            labels.append("치명타 약점 12%")
        multiplier += min(0.30, bonus)

    elif key == "babel":
        resources = user.get("resources", {}) if isinstance(user.get("resources"), dict) else {}
        stock = _safe_int(resources.get("광석"), 0, 0) + _safe_int(resources.get("고철"), 0, 0)
        thresholds = ((5000, 0.25), (2500, 0.20), (1000, 0.15), (500, 0.10), (100, 0.05))
        for required, bonus in thresholds:
            if stock >= required:
                multiplier += bonus
                labels.append(f"광석·고철 {stock:,}개 {bonus * 100:.0f}%")
                break

    elif key == "ark_ghost":
        root = user.get("v430", {}) if isinstance(user.get("v430"), dict) else {}
        season2 = root.get("season2", {}) if isinstance(root.get("season2"), dict) else {}
        expedition = root.get("expedition", {}) if isinstance(root.get("expedition"), dict) else {}
        bonus = 0.0
        if season2.get("completed") or _safe_int(season2.get("runs"), 0, 0) > 0 or bool(season2.get("endings")):
            bonus += 0.14
            labels.append("시즌 2 기록 14%")
        equipped_relics = expedition.get("equipped_relics", []) if isinstance(expedition.get("equipped_relics"), list) else []
        if equipped_relics:
            relic_bonus = min(0.12, 0.06 * len(equipped_relics))
            bonus += relic_bonus
            labels.append(f"원정 유물 {relic_bonus * 100:.0f}%")
        multiplier += min(0.26, bonus)

    elif key == "abaddon":
        jobs: Set[str] = set()
        participants = battle.get("participants", {})
        if isinstance(participants, dict):
            for row in participants.values():
                if isinstance(row, dict) and row.get("job"):
                    jobs.add(str(row["job"]))
        job = str(user.get("job") or "")
        if job:
            jobs.add(job)
        if len(jobs) >= 2:
            bonus = min(0.24, (len(jobs) - 1) * 0.06)
            multiplier += bonus
            labels.append(f"역할 {len(jobs)}종 협동 {bonus * 100:.0f}%")

    return multiplier, labels


def _asset_file(name: str) -> Optional[discord.File]:
    path = ASSET_ROOT / name
    if not path.is_file():
        return None
    return discord.File(path, filename=name)


async def _send_asset(
    ctx: commands.Context,
    embed: discord.Embed,
    filename: str,
    *,
    content: Optional[str] = None,
) -> discord.Message:
    file = _asset_file(filename)
    if file is None:
        return await ctx.send(content=content, embed=embed)
    embed.set_image(url=f"attachment://{filename}")
    return await ctx.send(content=content, embed=embed, file=file)


async def _safe_reactions(message: Optional[discord.Message], emojis: Iterable[str]) -> None:
    if message is None:
        return
    for emoji in emojis:
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return


def _status_embed(battle: Dict[str, Any], *, test: bool = False) -> discord.Embed:
    key = str(battle.get("boss_key"))
    info = BOSSES.get(key, BOSSES["gatekeeper"])
    hp = _safe_int(battle.get("hp"), 0, 0)
    maximum = max(1, _safe_int(battle.get("max_hp"), 1, 1))
    percent = hp / maximum * 100
    phase = _safe_int(battle.get("phase"), _phase_for(hp, maximum), 1)
    rows = _rows(battle)
    top = "\n".join(
        f"**{idx}.** <@{uid}> · `{damage:,}` 피해 · {attacks}회"
        for idx, (uid, damage, attacks) in enumerate(rows[:5], 1)
    ) or "아직 참가자가 없습니다."
    parts: List[str] = []
    for name, part in battle.get("parts", {}).items():
        if not isinstance(part, dict):
            continue
        marker = "💥" if part.get("broken") else "🔧"
        line = f"{marker} {name} · {_safe_int(part.get('damage'), 0, 0):,}/{max(1, _safe_int(part.get('target'), 1, 1)):,}"
        if part.get("broken"):
            description = PART_EFFECTS.get(key, {}).get(str(name), {}).get("description")
            if description:
                line += f"\n└ {description}"
        parts.append(line)
    mode = "🧪 테스트" if test else "🌋"
    embed = discord.Embed(
        title=f"{mode} [{info['grade']}] {info['name']}",
        description=(
            f"`{_bar(hp, maximum)}`\n"
            f"**HP {hp:,} / {maximum:,} ({percent:.1f}%)**\n"
            f"현재 **{PHASE_NAMES.get(phase, '전투 단계')}** · 특성 **{info['trait']}**"
        ),
        color=int(info["color"]),
        timestamp=_utc_now(),
    )
    embed.add_field(name="🎯 실제 적용 약점", value=info["weakness"], inline=False)
    embed.add_field(name="🧩 부위 파괴 효과", value="\n".join(parts) if parts else "파괴 가능한 부위 없음", inline=False)
    embed.add_field(name="🏅 기여도 TOP 5", value=top, inline=False)
    attack_command = "`!월드보스테스트공격`" if test else "`!월드보스공격`"
    limit = TEST_ATTACK_LIMIT if test else DAILY_ATTACK_LIMIT
    embed.add_field(name="⚔️ 공격", value=f"{attack_command} · 하루 {limit}회", inline=False)
    if test:
        embed.add_field(name="🧪 샌드박스", value="식량·내구도·도감·실전 보상에 영향을 주지 않습니다.", inline=False)
    embed.set_footer(text=f"전투 ID {battle.get('battle_id','-')} · 페이즈별 방어/패턴/반격 수치 실시간 적용")
    return embed


def _boss_list_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌋 ABADDON 7.0 다중 월드보스 도감",
        description="약점은 실제 피해 보너스로, 페이즈와 부위 파괴는 실제 방어·회피·회복·반격 수치로 적용됩니다.",
        color=discord.Color.dark_red(),
    )
    for key, info in BOSSES.items():
        effects = PART_EFFECTS.get(key, {})
        effect_text = " / ".join(str(row.get("description", "")) for row in effects.values())
        embed.add_field(
            name=f"{info['grade']} · {info['name']}",
            value=(
                f"HP **{info['max_hp']:,}** · {info['trait']}\n"
                f"약점: {info['weakness']}\n"
                f"부위 효과: {effect_text}\n"
                f"재료: {info['material']}"
            ),
            inline=False,
        )
    embed.set_footer(text="관리자 실전 소환: !월드보스소환 보스명 · 독립 테스트: !월드보스테스트 보스명")
    return embed


def _require_guild(ctx: commands.Context) -> bool:
    return ctx.guild is not None


def register_v630_world_boss(
    bot: commands.Bot,
    get_user: Callable[[Any], Optional[Dict[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    calculate_user_power: Callable[[Dict[str, Any]], int],
    add_title: Callable[[Dict[str, Any], str], Any],
) -> None:
    """7.0 월드보스: 실전/테스트 분리, 보상 큐, 실제 약점·페이즈·부위 기믹."""

    async def require_registered_guild(ctx: commands.Context) -> Optional[int]:
        if not await check_registered(ctx):
            return None
        if not _require_guild(ctx):
            await ctx.send("⚠️ 월드보스는 서버 채널에서만 이용할 수 있습니다.")
            return None
        return int(ctx.guild.id)

    def _archive_legacy_defeat(state: Dict[str, Any]) -> None:
        active = state.get("active")
        if isinstance(active, dict) and active.get("status") == "defeated":
            _archive_completed(state, active)
            state["active"] = None

    async def status_callback(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        state = _guild_state(world_data, guild_id)
        _archive_legacy_defeat(state)
        battle = _battle(world_data, guild_id)
        if battle is None:
            pending = 0
            uid = str(ctx.author.id)
            for item in state.get("completed", []):
                if not isinstance(item, dict):
                    continue
                participants = item.get("participants", {})
                claimed = item.get("rewards_claimed", [])
                if isinstance(participants, dict) and uid in participants and uid not in claimed:
                    pending += 1
            embed = discord.Embed(
                title="🌋 현재 출현한 실전 월드보스가 없습니다",
                description="관리자가 `!월드보스소환 보스명`을 사용하면 서버 공동 전투가 시작됩니다.",
                color=discord.Color.dark_grey(),
            )
            embed.add_field(name="보스 목록", value="`!월드보스목록`", inline=True)
            embed.add_field(name="미수령 보상", value=f"**{pending}건** · `!월드보스보상목록`", inline=True)
            embed.add_field(name="독립 테스트", value="`!월드보스테스트상태`", inline=True)
            await ctx.send(embed=embed)
            save_data()
            return
        key = str(battle.get("boss_key", "gatekeeper"))
        info = BOSSES.get(key, BOSSES["gatekeeper"])
        await _send_asset(ctx, _status_embed(battle), str(info["image"]))

    async def ranking_callback(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        battle = _battle(world_data, guild_id)
        if battle is None or not _rows(battle):
            await ctx.send("📭 현재 실전 월드보스 기여 기록이 없습니다.")
            return
        rows = _rows(battle)
        total = sum(row[1] for row in rows)
        lines = []
        for idx, (uid, damage, attacks) in enumerate(rows[:20], 1):
            share = damage / max(1, total) * 100
            lines.append(f"**{idx}.** <@{uid}> · **{damage:,}** 피해 · {share:.1f}% · {attacks}회")
        embed = discord.Embed(
            title=f"🏆 {battle.get('name','월드보스')} 기여도 순위",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"총 누적 피해 {total:,} · 전투 ID {battle.get('battle_id','-')}")
        await ctx.send(embed=embed)

    def user_attack_state(battle: Dict[str, Any], uid: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        participants = battle.setdefault("participants", {})
        row = participants.setdefault(
            uid,
            {"damage": 0, "attacks": 0, "last_at": "", "daily": {"date": _date_key(), "count": 0}, "job": ""},
        )
        if not isinstance(row, dict):
            row = {"damage": 0, "attacks": 0, "last_at": "", "daily": {"date": _date_key(), "count": 0}, "job": ""}
            participants[uid] = row
        daily = row.setdefault("daily", {"date": _date_key(), "count": 0})
        if not isinstance(daily, dict):
            daily = {"date": _date_key(), "count": 0}
            row["daily"] = daily
        if daily.get("date") != _date_key():
            daily["date"] = _date_key()
            daily["count"] = 0
        row["job"] = str(user.get("job") or row.get("job") or "")
        return row

    async def perform_attack(ctx: commands.Context, *, test_mode: bool = False) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        battle = _battle(world_data, guild_id, test=test_mode)
        if battle is None or battle.get("status") != "active" or _safe_int(battle.get("hp"), 0, 0) <= 0:
            if not test_mode and getattr(ctx, "command", None):
                try:
                    ctx.command.reset_cooldown(ctx)
                except Exception:
                    pass
            label = "테스트 월드보스" if test_mode else "실전 월드보스"
            await ctx.send(f"⚠️ 현재 공격 가능한 {label}가 없습니다.")
            return

        uid = str(ctx.author.id)
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 찾지 못했습니다.")
            return
        row = user_attack_state(battle, uid, user)
        daily = row["daily"]
        limit = TEST_ATTACK_LIMIT if test_mode else DAILY_ATTACK_LIMIT
        if _safe_int(daily.get("count"), 0, 0) >= limit:
            if not test_mode and getattr(ctx, "command", None):
                try:
                    ctx.command.reset_cooldown(ctx)
                except Exception:
                    pass
            await ctx.send(f"🛑 오늘의 {'테스트 ' if test_mode else ''}월드보스 공격 **{limit}회**를 모두 사용했습니다.")
            return

        key = str(battle.get("boss_key", "gatekeeper"))
        info = BOSSES.get(key, BOSSES["gatekeeper"])
        before_hp = _safe_int(battle.get("hp"), 0, 0)
        maximum = max(1, _safe_int(battle.get("max_hp"), 1, 1))
        old_phase = _safe_int(battle.get("phase"), _phase_for(before_hp, maximum), 1)
        mechanics = _mechanics(battle, info)
        power = max(1, _safe_int(calculate_user_power(user), 1, 1))
        level = max(1, _safe_int(user.get("level"), 1, 1))
        base = random.randint(max(80, int(power * 1.15)), max(120, int(power * 2.25))) + level * 35
        base = min(base, max(50_000, int(maximum * 0.055)))
        critical = random.random() < min(0.28, 0.09 + level / 900)
        dodge = random.random() < float(mechanics["dodge"])
        weakness_mult, weakness_labels = _weakness_multiplier(user, key, battle, critical=critical)
        damage = 0
        if not dodge:
            damage = max(
                1,
                int(
                    base
                    * (1.0 - float(mechanics["defense"]))
                    * float(mechanics["damage_taken"])
                    * weakness_mult
                    * (1.75 if critical else 1.0)
                ),
            )
        detail: List[str] = []
        if test_mode:
            detail.append("🧪 샌드박스 전투: 식량·내구도·도감·실전 보상 미반영")
        if dodge:
            detail.append("👻 보스가 공격 궤적을 벗어났습니다.")
        elif critical:
            detail.append("💥 치명타가 적중했습니다!")
        if weakness_labels and damage > 0:
            detail.append("🎯 약점 발동 · " + " / ".join(weakness_labels))

        pattern_triggered = random.random() < float(mechanics["pattern"])
        forced_counter_bonus = 0.0
        if pattern_triggered:
            patterns = tuple(info.get("patterns", ()))
            if patterns:
                detail.append(random.choice(patterns))
            heal = 0
            if key in {"nemesis", "babel"} and before_hp < maximum and float(mechanics["heal_mult"]) > 0:
                ratio = 0.006 if key == "nemesis" else 0.004
                heal = min(maximum - before_hp, max(1, int(maximum * ratio * float(mechanics["heal_mult"]))))
                battle["hp"] = min(maximum, before_hp + heal)
                before_hp = _safe_int(battle.get("hp"), before_hp, 0)
                detail.append(f"💚 보스 체력 **{heal:,}** 회복")
            elif key == "ark_ghost" and damage > 0 and not mechanics.get("disable_illusion"):
                damage = max(1, int(damage * 0.55))
                detail.append("🪞 환영 투영기가 공격을 분산해 피해가 45% 감소했습니다.")
            elif key == "gatekeeper" and damage > 0 and not _part_broken(battle, "방벽 핵"):
                damage = max(1, int(damage * 0.65))
                detail.append("🛡️ 흑철 방벽 핵이 피해를 35% 흡수했습니다.")
            elif key == "atlas" and not _part_broken(battle, "노심 냉각관"):
                forced_counter_bonus = 0.12
                detail.append("☢️ 방사능 노출로 이번 공격의 반격 위험이 상승했습니다.")
            elif key == "abaddon" and damage > 0 and old_phase >= 2 and not _part_broken(battle, "종말의 왕관"):
                damage = max(1, int(damage * 0.72))
                detail.append("👑 왕좌의 심판이 피해를 28% 무효화했습니다.")

        part_text = ""
        available = [
            (name, part)
            for name, part in battle.get("parts", {}).items()
            if isinstance(part, dict) and not part.get("broken")
        ]
        if damage > 0 and available and random.random() < 0.32:
            part_name, part = random.choice(available)
            part_damage = max(1, int(damage * random.uniform(0.42, 0.76)))
            part["damage"] = _safe_int(part.get("damage"), 0, 0) + part_damage
            if _safe_int(part["damage"], 0, 0) >= max(1, _safe_int(part.get("target"), 1, 1)):
                part["broken"] = True
                effect_text = PART_EFFECTS.get(key, {}).get(str(part_name), {}).get("description", "전투 기믹 약화")
                part_text = f"💥 **{part_name} 파괴!**\n{effect_text}"
            else:
                part_text = f"🔧 {part_name}에 **{part_damage:,}** 부위 피해"

        damage = min(max(0, damage), _safe_int(battle.get("hp"), 0, 0))
        battle["hp"] = max(0, _safe_int(battle.get("hp"), 0, 0) - damage)
        row["damage"] = _safe_int(row.get("damage"), 0, 0) + damage
        row["attacks"] = _safe_int(row.get("attacks"), 0, 0) + 1
        row["last_at"] = _iso_now()
        daily["count"] = _safe_int(daily.get("count"), 0, 0) + 1

        weapon_state: Dict[str, Any] = {}
        if not test_mode:
            stats = user.setdefault("stats", {})
            stats["worldboss_damage"] = _safe_int(stats.get("worldboss_damage"), 0, 0) + damage
            codex = user.setdefault("worldboss_codex", {}).setdefault(
                info["name"], {"damage": 0, "attacks": 0, "kills": 0}
            )
            codex["damage"] = _safe_int(codex.get("damage"), 0, 0) + damage
            codex["attacks"] = _safe_int(codex.get("attacks"), 0, 0) + 1
            weekly_tracker = getattr(bot, "v710_record_worldboss_damage", None)
            if callable(weekly_tracker):
                try:
                    weekly_tracker(guild_id, ctx.author.id, damage)
                except Exception as exc:
                    print(f"[V7.1 월드보스 주간 집계 경고] {type(exc).__name__}: {exc}", flush=True)
            weapon_state = consume_weapon_durability(user, 2 if critical else 1)
        else:
            codex = None

        new_phase = _phase_for(_safe_int(battle.get("hp"), 0, 0), maximum)
        battle["phase"] = new_phase

        counter = 0
        counter_loss = 0
        counter_chance = min(0.85, float(mechanics["counter"]) + forced_counter_bonus)
        if damage > 0 and random.random() < counter_chance:
            low, high = info.get("counter", (0, 0))
            counter = max(0, int(random.randint(int(low), int(high)) * float(mechanics["counter_mult"])))
            if counter > 0:
                if test_mode:
                    detail.append(f"🧪 반격 시뮬레이션 **{counter:,} 식량** · 실제 차감 없음")
                else:
                    balance = _safe_int(user.get("balance"), 0, 0)
                    counter_loss = min(balance, counter)
                    user["balance"] = max(0, balance - counter_loss)
                    stats = user.setdefault("stats", {})
                    stats["worldboss_counter_loss"] = _safe_int(stats.get("worldboss_counter_loss"), 0, 0) + counter_loss
                    detail.append(f"💢 보스 반격 적중 · **{counter_loss:,} 식량** 손실")

        remaining = limit - _safe_int(daily.get("count"), 0, 0)
        embed = discord.Embed(
            title=f"{'🧪' if test_mode else '⚔️'} {info['name']} 공격 결과",
            description="\n".join(detail) if detail else "공격이 보스의 외피를 가르며 전장에 충격파가 번졌습니다.",
            color=discord.Color.gold() if critical else int(info["color"]),
            timestamp=_utc_now(),
        )
        embed.add_field(name="⚔️ 가한 피해", value=f"**{damage:,}**", inline=True)
        embed.add_field(name="❤️ 남은 HP", value=f"**{_safe_int(battle.get('hp'), 0, 0):,}/{maximum:,}**", inline=True)
        embed.add_field(name="🎫 오늘 남은 공격", value=f"**{remaining}회**", inline=True)
        embed.add_field(
            name="📊 내 누적 기여",
            value=f"**{_safe_int(row.get('damage'), 0, 0):,} 피해** · {_safe_int(row.get('attacks'), 0, 0)}회",
            inline=False,
        )
        if counter_loss:
            embed.add_field(name="💰 반격 후 잔액", value=f"**{_safe_int(user.get('balance'), 0, 0):,} 식량**", inline=True)
        if weapon_state.get("name"):
            embed.add_field(
                name="🔧 무기 내구도",
                value=f"**{weapon_state['current']} / {weapon_state['maximum']} · {weapon_state['label']}**",
                inline=False,
            )
        if part_text:
            embed.add_field(name="🧩 부위 파괴", value=part_text, inline=False)
        embed.set_thumbnail(url=str(ctx.author.display_avatar.url))
        embed.set_footer(text=f"{PHASE_NAMES.get(new_phase)} · {'테스트 샌드박스' if test_mode else f'{ATTACK_COOLDOWN_SECONDS}초 후 재공격'}")

        defeated = _safe_int(battle.get("hp"), 0, 0) <= 0
        state = _guild_state(world_data, guild_id)
        if defeated:
            battle["status"] = "defeated"
            battle["defeated_at"] = _iso_now()
            battle["killer_id"] = uid
            if test_mode:
                state["test_active"] = None
            else:
                if isinstance(codex, dict):
                    codex["kills"] = _safe_int(codex.get("kills"), 0, 0) + 1
                add_title(user, "마지막 일격의 생존자")
                history = state.setdefault("history", [])
                history.insert(
                    0,
                    {
                        "battle_id": battle["battle_id"],
                        "boss_key": key,
                        "name": info["name"],
                        "defeated_at": battle["defeated_at"],
                        "participants": len(_rows(battle)),
                        "killer_id": uid,
                    },
                )
                del history[HISTORY_LIMIT:]
                _archive_completed(state, battle)
                state["active"] = None
        save_data()
        msg = await ctx.send(embed=embed)
        await _safe_reactions(msg, ("💥", "⚔️", "🔥") if critical else ("⚔️", "🛡️"))

        if new_phase > old_phase and not defeated:
            phase_file = "enrage.png" if new_phase == 4 else "phase.png"
            rule = PHASE_RULES[new_phase]
            phase_embed = discord.Embed(
                title=f"⚠️ {PHASE_NAMES.get(new_phase)} 진입",
                description=(
                    f"받는 피해 배율 **×{rule['damage_taken']:.2f}** · 패턴률 **{rule['pattern'] * 100:.0f}%** · "
                    f"반격률 **{rule['counter'] * 100:.0f}%**로 변경되었습니다."
                ),
                color=discord.Color.red() if new_phase == 4 else discord.Color.blue(),
            )
            await _send_asset(ctx, phase_embed, phase_file)
        if defeated:
            if test_mode:
                victory = discord.Embed(
                    title=f"🧪 테스트 토벌 완료 · {info['name']}",
                    description="테스트 전투가 자동 정리되었습니다. 실전 보상과 기록에는 반영되지 않습니다.",
                    color=discord.Color.blue(),
                )
            else:
                victory = discord.Embed(
                    title=f"🏆 {info['name']} 토벌 완료",
                    description=(
                        f"마지막 일격: {ctx.author.mention}\n참가자 **{len(_rows(battle))}명** · "
                        "보상은 독립 큐에 안전하게 저장되었습니다. `!월드보스보상`으로 수령하세요."
                    ),
                    color=discord.Color.gold(),
                )
            await _send_asset(ctx, victory, "victory.png")

    async def attack_callback(ctx: commands.Context) -> None:
        await perform_attack(ctx, test_mode=False)

    async def spawn_callback(ctx: commands.Context, *, 보스이름: str = None) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        if not (
            ctx.author == ctx.guild.owner
            or ctx.author.guild_permissions.manage_guild
            or ctx.author.guild_permissions.administrator
        ):
            await ctx.send("❌ 서버 관리 권한이 필요합니다.")
            return
        key = _boss_key(보스이름) if 보스이름 else random.choice(tuple(BOSSES))
        if key is None:
            await ctx.send("⚠️ 보스를 찾지 못했습니다. `!월드보스목록`에서 이름을 확인하세요.")
            return
        state = _guild_state(world_data, guild_id)
        _archive_legacy_defeat(state)
        active = state.get("active")
        if isinstance(active, dict) and active.get("status") == "active" and _safe_int(active.get("hp"), 0, 0) > 0:
            await ctx.send("⚠️ 이미 활성 실전 월드보스가 있습니다. 먼저 `!월드보스종료`를 사용하세요.")
            return
        battle = _new_battle(state, key)
        save_data()
        info = BOSSES[key]
        pending_total = len(state.get("completed", []))
        embed = discord.Embed(
            title=f"🌋 [{info['grade']}] {info['name']} 출현",
            description=(
                f"서버 공동 HP **{battle['max_hp']:,}**\n특성 **{info['trait']}** · 약점 **{info['weakness']}**\n"
                f"이전 처치 보상 큐 **{pending_total}전투 보존 중**\n`!월드보스공격`으로 전투에 참가하세요."
            ),
            color=int(info["color"]),
        )
        await _send_asset(ctx, embed, str(info["image"]), content="@here 월드보스 출현 신호가 감지되었습니다.")

    async def health_callback(ctx: commands.Context, 체력: int) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ 관리자 전용 명령어입니다.")
            return
        battle = _battle(world_data, guild_id)
        if battle is None:
            await ctx.send("⚠️ 활성 실전 월드보스가 없습니다.")
            return
        value = max(1, int(체력))
        battle["max_hp"] = value
        battle["hp"] = value
        battle["status"] = "active"
        battle["phase"] = 1
        save_data()
        await ctx.send(f"❤️ 실전 월드보스 체력을 **{value:,}**으로 재설정했습니다.")

    async def end_callback(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ 관리자 전용 명령어입니다.")
            return
        state = _guild_state(world_data, guild_id)
        battle = _battle(world_data, guild_id)
        if battle is None:
            await ctx.send("⚠️ 활성 실전 월드보스가 없습니다.")
            return
        battle["status"] = "ended"
        battle["defeated_at"] = _iso_now()
        state["active"] = None
        save_data()
        await ctx.send(f"🛑 **{battle.get('name','월드보스')}** 실전 전투를 종료했습니다. 보상 큐에는 추가되지 않습니다.")

    replacements = {
        "월드보스": status_callback,
        "보스랭킹": ranking_callback,
        "월드보스공격": attack_callback,
        "월드보스리셋": spawn_callback,
        "월드보스체력": health_callback,
        "월드보스종료": end_callback,
    }
    for name, callback in replacements.items():
        cmd = bot.get_command(name)
        if cmd is not None:
            cmd.callback = callback
            if name == "월드보스공격":
                cmd._buckets = commands.CooldownMapping.from_cooldown(
                    1, ATTACK_COOLDOWN_SECONDS, commands.BucketType.user
                )

    @bot.command(name="월드보스목록", aliases=["보스목록", "월보목록", "worldbosslist"])
    async def boss_list(ctx: commands.Context) -> None:
        if await require_registered_guild(ctx) is None:
            return
        await ctx.send(embed=_boss_list_embed())

    @bot.command(name="월드보스기여도", aliases=["내기여도", "월보기여도"])
    async def contribution(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        battle = _battle(world_data, guild_id)
        if battle is None:
            await ctx.send("📭 현재 실전 전투가 없습니다.")
            return
        rows = _rows(battle)
        uid = str(ctx.author.id)
        row = battle.get("participants", {}).get(uid, {})
        rank = next((idx for idx, item in enumerate(rows, 1) if item[0] == uid), None)
        daily = row.get("daily", {}) if isinstance(row, dict) else {}
        count = 0 if daily.get("date") != _date_key() else _safe_int(daily.get("count"), 0, 0)
        embed = discord.Embed(title=f"📊 {ctx.author.display_name} 월드보스 기여도", color=discord.Color.blue())
        embed.add_field(name="누적 피해", value=f"**{_safe_int(row.get('damage'), 0, 0):,}**", inline=True)
        embed.add_field(name="현재 순위", value=f"**{rank or '-'}위**", inline=True)
        embed.add_field(
            name="공격 횟수",
            value=f"누적 {_safe_int(row.get('attacks'), 0, 0)}회 · 오늘 {count}/{DAILY_ATTACK_LIMIT}",
            inline=False,
        )
        await ctx.send(embed=embed)

    def pending_rewards(state: Dict[str, Any], uid: str) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for battle in reversed(state.get("completed", [])):
            if not isinstance(battle, dict):
                continue
            participants = battle.get("participants", {})
            claimed = battle.get("rewards_claimed", [])
            if not isinstance(participants, dict) or uid not in participants:
                continue
            row = participants.get(uid)
            if not isinstance(row, dict) or _safe_int(row.get("damage"), 0, 0) <= 0:
                continue
            if uid not in claimed:
                result.append(battle)
        return result

    @bot.command(name="월드보스보상목록", aliases=["월보보상목록", "worldbossrewards"])
    async def reward_list(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        state = _guild_state(world_data, guild_id)
        _archive_legacy_defeat(state)
        uid = str(ctx.author.id)
        pending = pending_rewards(state, uid)
        if not pending:
            await ctx.send("📭 현재 미수령 월드보스 보상이 없습니다.")
            save_data()
            return
        lines = []
        for battle in pending[:10]:
            entry = battle.get("participants", {}).get(uid, {})
            lines.append(
                f"• **{battle.get('name','월드보스')}** · 피해 {_safe_int(entry.get('damage'), 0, 0):,} · `{battle.get('battle_id','-')}`"
            )
        embed = discord.Embed(
            title=f"🎁 미수령 월드보스 보상 {len(pending)}건",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="!월드보스보상 사용 시 오래된 보상부터 한 건씩 안전하게 수령합니다.")
        await ctx.send(embed=embed)
        save_data()

    @bot.command(name="월드보스보상", aliases=["보스보상", "월보보상"])
    async def reward(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        state = _guild_state(world_data, guild_id)
        _archive_legacy_defeat(state)
        uid = str(ctx.author.id)
        pending = pending_rewards(state, uid)
        if not pending:
            await ctx.send("⚠️ 수령 가능한 처치 완료 월드보스 보상이 없습니다.")
            save_data()
            return
        battle = pending[0]
        claimed = battle.setdefault("rewards_claimed", [])
        if not isinstance(claimed, list):
            claimed = []
            battle["rewards_claimed"] = claimed
        rows = _rows(battle)
        entry = next((row for row in rows if row[0] == uid), None)
        if entry is None or entry[1] <= 0:
            await ctx.send("⚠️ 전투 기여 기록이 없어 보상을 받을 수 없습니다.")
            return
        rank = next(idx for idx, row in enumerate(rows, 1) if row[0] == uid)
        total = sum(row[1] for row in rows)
        damage = entry[1]
        info = BOSSES.get(str(battle.get("boss_key")), BOSSES["gatekeeper"])
        base = 8000
        share = min(45_000, int((damage / max(1, total)) * 90_000))
        rank_bonus = 25_000 if rank == 1 else 14_000 if rank <= 3 else 6_000 if rank <= 10 else 2_000
        food = base + share + rank_bonus
        material_amount = max(1, 10 - min(rank, 8))
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 찾지 못했습니다.")
            return
        user["balance"] = _safe_int(user.get("balance"), 0, 0) + food
        stats = user.setdefault("stats", {})
        stats["earned"] = _safe_int(stats.get("earned"), 0, 0) + food
        materials = user.setdefault("materials", {})
        materials[info["material"]] = _safe_int(materials.get(info["material"]), 0, 0) + material_amount
        titles: List[str] = []
        if rank == 1:
            title = f"{info['name']} 최우수 토벌자"
            add_title(user, title)
            titles.append(title)
        elif rank <= 3:
            title = f"{info['name']} 선봉대"
            add_title(user, title)
            titles.append(title)
        if str(battle.get("killer_id")) == uid:
            title = "마지막 일격의 생존자"
            add_title(user, title)
            titles.append(title)
        claimed.append(uid)
        remaining = len(pending_rewards(state, uid))
        save_data()
        embed = discord.Embed(
            title="🎁 월드보스 기여도 보상 수령",
            description=(
                f"**{battle.get('name','월드보스')}** · 전투 순위 **{rank}위** · 기여 피해 **{damage:,}**\n"
                f"전투 ID `{battle.get('battle_id','-')}`"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="💰 식량", value=f"**+{food:,}**", inline=True)
        embed.add_field(name=f"🧩 {info['material']}", value=f"**+{material_amount}개**", inline=True)
        embed.add_field(name="💳 현재 잔액", value=f"**{_safe_int(user.get('balance'), 0, 0):,} 식량**", inline=True)
        embed.add_field(name="📦 남은 보상", value=f"**{remaining}건**", inline=True)
        if titles:
            embed.add_field(name="🏷️ 칭호", value="\n".join(f"`{title}`" for title in dict.fromkeys(titles)), inline=False)
        await _send_asset(ctx, embed, "reward.png")

    @bot.command(name="월드보스이력", aliases=["월보이력", "worldbosshistory"])
    async def history(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        state = _guild_state(world_data, guild_id)
        rows = state.get("history", [])
        if not rows:
            await ctx.send("📭 아직 기록된 실전 월드보스 토벌 이력이 없습니다.")
            return
        lines = []
        for item in rows[:HISTORY_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"• **{item.get('name','월드보스')}** · 참가 {item.get('participants',0)}명 · `{item.get('battle_id','-')}`"
            )
        await ctx.send(embed=discord.Embed(title="📜 월드보스 최근 토벌 이력", description="\n".join(lines), color=discord.Color.dark_gold()))

    @bot.command(name="월드보스도감", aliases=["월보도감"])
    async def codex(ctx: commands.Context) -> None:
        if await require_registered_guild(ctx) is None:
            return
        user = get_user(ctx.author.id)
        records = user.setdefault("worldboss_codex", {}) if isinstance(user, dict) else {}
        lines = []
        for info in BOSSES.values():
            row = records.get(info["name"], {}) if isinstance(records, dict) else {}
            lines.append(
                f"**{info['name']}** · 피해 {_safe_int(row.get('damage'), 0, 0):,} · "
                f"공격 {_safe_int(row.get('attacks'), 0, 0)}회 · 처치 {_safe_int(row.get('kills'), 0, 0)}회"
            )
        embed = discord.Embed(
            title=f"📚 {ctx.author.display_name} 월드보스 도감",
            description="\n".join(lines),
            color=discord.Color.purple(),
        )
        await ctx.send(embed=embed)

    @bot.command(name="월드보스테스트", aliases=["월보테스트", "worldbosstest"])
    async def test_spawn(ctx: commands.Context, *, 보스이름: str = None) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ 관리자 전용 명령어입니다.")
            return
        key = _boss_key(보스이름) if 보스이름 else "gatekeeper"
        if key is None:
            await ctx.send("⚠️ 보스 이름을 찾지 못했습니다.")
            return
        state = _guild_state(world_data, guild_id)
        test_active = state.get("test_active")
        if isinstance(test_active, dict) and test_active.get("status") == "active" and _safe_int(test_active.get("hp"), 0, 0) > 0:
            await ctx.send("⚠️ 이미 테스트 월드보스가 있습니다. `!월드보스테스트종료` 후 다시 소환하세요.")
            return
        battle = _new_battle(state, key, hp_override=50_000, test=True)
        save_data()
        info = BOSSES[key]
        embed = discord.Embed(
            title=f"🧪 독립 테스트 월드보스 · {info['name']}",
            description=(
                "HP **50,000** · 실전 슬롯과 완전 분리\n"
                "식량·내구도·도감·보상에 영향을 주지 않습니다.\n"
                "공격: `!월드보스테스트공격`"
            ),
            color=int(info["color"]),
        )
        await _send_asset(ctx, embed, str(info["image"]))

    @bot.command(name="월드보스테스트상태", aliases=["월보테스트상태", "worldbossteststatus"])
    async def test_status(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        battle = _battle(world_data, guild_id, test=True)
        if battle is None:
            await ctx.send("📭 현재 독립 테스트 월드보스가 없습니다.")
            return
        info = BOSSES.get(str(battle.get("boss_key")), BOSSES["gatekeeper"])
        await _send_asset(ctx, _status_embed(battle, test=True), str(info["image"]))

    @bot.command(name="월드보스테스트공격", aliases=["월보테스트공격", "worldbosstestattack"])
    async def test_attack(ctx: commands.Context) -> None:
        await perform_attack(ctx, test_mode=True)

    @bot.command(name="월드보스테스트종료", aliases=["월보테스트종료", "worldbosstestend"])
    async def test_end(ctx: commands.Context) -> None:
        guild_id = await require_registered_guild(ctx)
        if guild_id is None:
            return
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ 관리자 전용 명령어입니다.")
            return
        state = _guild_state(world_data, guild_id)
        battle = state.get("test_active")
        if not isinstance(battle, dict):
            await ctx.send("📭 종료할 테스트 월드보스가 없습니다.")
            return
        state["test_active"] = None
        save_data()
        await ctx.send(f"🧪 **{battle.get('name','테스트 월드보스')}** 테스트 전투를 정리했습니다.")

    bot.v700_world_boss_version = VERSION
    setattr(bot, "_abaddon_v630_world_boss", True)
