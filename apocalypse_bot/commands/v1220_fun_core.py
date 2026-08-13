from __future__ import annotations

"""Pure rules and catalogues for ABADDON v12.2.0 Chaos Festival Complete.

This module intentionally has no Discord imports so its deterministic rules can be
unit-tested in deployment environments that do not install the gateway library.
"""

import hashlib
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

VERSION = "12.2.0"
SCHEMA_VERSION = 3

CHAOS_EVENTS: Dict[str, Dict[str, Any]] = {
    "goblin": {"emoji": "🟡", "ko": "황금 고블린", "en": "Golden Goblin", "mode": "first", "duration": 90, "reward": 3500},
    "chest": {"emoji": "🧰", "ko": "수상한 보물상자", "en": "Suspicious Treasure Chest", "mode": "choice", "duration": 120, "reward": 2800},
    "meteor": {"emoji": "☄️", "ko": "운석 낙하", "en": "Meteor Strike", "mode": "raid", "duration": 180, "hp": 120, "reward": 5000},
    "ghost": {"emoji": "👻", "ko": "유령 출몰", "en": "Ghost Sighting", "mode": "answer", "duration": 150, "reward": 3200},
    "robbery": {"emoji": "🏦", "ko": "은행 강도", "en": "Bank Robbery", "mode": "teams", "duration": 180, "reward": 4200},
    "rampage": {"emoji": "😈", "ko": "아바돈 폭주", "en": "ABADDON Rampage", "mode": "raid", "duration": 240, "hp": 220, "reward": 8000},
    "lucky": {"emoji": "🍀", "ko": "행운의 시간", "en": "Lucky Hour", "mode": "modifier", "duration": 900, "multiplier": 1.25},
    "cursed": {"emoji": "🕯️", "ko": "저주의 시간", "en": "Cursed Hour", "mode": "modifier", "duration": 600, "multiplier": 0.90},
}

EVENT_ALIASES = {
    "황금": "goblin", "고블린": "goblin", "goblin": "goblin",
    "상자": "chest", "보물상자": "chest", "chest": "chest",
    "운석": "meteor", "meteor": "meteor",
    "유령": "ghost", "ghost": "ghost",
    "강도": "robbery", "은행": "robbery", "robbery": "robbery",
    "폭주": "rampage", "아바돈": "rampage", "rampage": "rampage",
    "행운": "lucky", "lucky": "lucky",
    "저주": "cursed", "cursed": "cursed",
}

NPCS: Dict[str, Dict[str, Any]] = {
    "루시안": {"emoji": "🎩", "en": "Lucian", "trait_ko": "승부욕 강한 냉정한 딜러", "trait_en": "A cool, fiercely competitive dealer", "likes": ("커피", "낡은칩", "검은장미")},
    "미라": {"emoji": "🔮", "en": "Mira", "trait_ko": "수수께끼를 좋아하는 점술가", "trait_en": "A fortune-teller who loves riddles", "likes": ("수정", "별사탕", "달빛")},
    "도일": {"emoji": "🕵️", "en": "Doyle", "trait_ko": "모든 판을 기록하는 탐정", "trait_en": "A detective who records every table", "likes": ("수첩", "홍차", "단서")},
    "로제": {"emoji": "🌹", "en": "Rosé", "trait_ko": "화려한 쇼를 즐기는 진행자", "trait_en": "A host who lives for spectacle", "likes": ("리본", "향수", "금화")},
    "브릭": {"emoji": "🧱", "en": "Brick", "trait_ko": "말보다 행동이 빠른 경비대장", "trait_en": "A security chief who acts before speaking", "likes": ("공구", "스테이크", "방패")},
    "세라": {"emoji": "🪽", "en": "Sera", "trait_ko": "다정하지만 비밀이 많은 안내자", "trait_en": "A kind guide with too many secrets", "likes": ("깃털", "책", "은방울")},
}

PETS: Dict[str, Dict[str, Any]] = {
    "ember": {"emoji": "🐉", "ko": "잿불용", "en": "Emberling", "rarity": "희귀", "food": "매운고기", "evolves": "inferno"},
    "mimic": {"emoji": "📦", "ko": "꼬마 미믹", "en": "Mini Mimic", "rarity": "희귀", "food": "금화", "evolves": "vault"},
    "raven": {"emoji": "🐦‍⬛", "ko": "밤까마귀", "en": "Night Raven", "rarity": "일반", "food": "검은열매", "evolves": "oracle"},
    "slime": {"emoji": "🟢", "ko": "칩 슬라임", "en": "Chip Slime", "rarity": "일반", "food": "젤리", "evolves": "jackpot"},
    "fox": {"emoji": "🦊", "ko": "달여우", "en": "Moon Fox", "rarity": "고급", "food": "별사탕", "evolves": "eclipse"},
    "horse": {"emoji": "🐴", "ko": "꼬마 경주마", "en": "Pocket Racer", "rarity": "고급", "food": "당근", "evolves": "comet"},
    "ghost": {"emoji": "👻", "ko": "말랑 유령", "en": "Soft Ghost", "rarity": "희귀", "food": "달빛", "evolves": "phantom"},
    "beetle": {"emoji": "🪲", "ko": "금빛 장수풍뎅이", "en": "Golden Beetle", "rarity": "전설", "food": "황금수액", "evolves": "sunlord"},
}

EVOLUTIONS: Dict[str, Tuple[str, str, str]] = {
    "inferno": ("🔥", "화염룡", "Inferno Dragon"), "vault": ("🏦", "금고 미믹", "Vault Mimic"),
    "oracle": ("🔮", "예언 까마귀", "Oracle Raven"), "jackpot": ("🎰", "잭팟 슬라임", "Jackpot Slime"),
    "eclipse": ("🌘", "월식여우", "Eclipse Fox"), "comet": ("☄️", "혜성마", "Comet Racer"),
    "phantom": ("🫥", "환영 유령", "Phantom Ghost"), "sunlord": ("☀️", "태양왕충", "Sunlord Beetle"),
}

EXPEDITIONS: Dict[str, Dict[str, Any]] = {
    "ruins": {"emoji": "🏚️", "ko": "붕괴한 폐허", "en": "Collapsed Ruins", "difficulty": 1, "steps": 4},
    "deepsea": {"emoji": "🌊", "ko": "검은 심해", "en": "Black Deep Sea", "difficulty": 2, "steps": 5},
    "casino": {"emoji": "🎰", "ko": "저주받은 카지노", "en": "Cursed Casino", "difficulty": 2, "steps": 5},
    "train": {"emoji": "🚂", "ko": "유령 열차", "en": "Ghost Train", "difficulty": 2, "steps": 5},
    "moon": {"emoji": "🌕", "ko": "버려진 달 기지", "en": "Abandoned Moon Base", "difficulty": 3, "steps": 6},
    "market": {"emoji": "😈", "ko": "악마 시장", "en": "Demon Market", "difficulty": 3, "steps": 6},
    "hwatu": {"emoji": "🎴", "ko": "고대 화투 신전", "en": "Ancient Hwatu Shrine", "difficulty": 3, "steps": 6},
    "labyrinth": {"emoji": "🌀", "ko": "시간의 미궁", "en": "Labyrinth of Time", "difficulty": 4, "steps": 7},
}

EXPEDITION_ALIASES = {
    "폐허": "ruins", "ruins": "ruins", "심해": "deepsea", "deepsea": "deepsea",
    "카지노": "casino", "casino": "casino", "열차": "train", "train": "train",
    "달": "moon", "moon": "moon", "시장": "market", "market": "market",
    "화투": "hwatu", "hwatu": "hwatu", "미궁": "labyrinth", "labyrinth": "labyrinth",
}

BUSINESSES: Dict[str, Dict[str, Any]] = {
    "cafe": {"emoji": "☕", "ko": "종말 카페", "en": "Endtime Café", "cost": 25_000, "base": 900},
    "casino": {"emoji": "🎰", "ko": "개인 카지노", "en": "Private Casino", "cost": 80_000, "base": 2400},
    "racetrack": {"emoji": "🏇", "ko": "소형 경마장", "en": "Mini Racetrack", "cost": 65_000, "base": 2000},
    "agency": {"emoji": "🕵️", "ko": "탐정사무소", "en": "Detective Agency", "cost": 40_000, "base": 1300},
    "studio": {"emoji": "📺", "ko": "방송국", "en": "Broadcast Studio", "cost": 55_000, "base": 1700},
    "toyshop": {"emoji": "🧸", "ko": "장난감 가게", "en": "Toy Shop", "cost": 30_000, "base": 1000},
    "mercenary": {"emoji": "⚔️", "ko": "용병 길드", "en": "Mercenary Guild", "cost": 70_000, "base": 2200},
    "hwatuworkshop": {"emoji": "🎴", "ko": "화투 공방", "en": "Hwatu Workshop", "cost": 45_000, "base": 1450},
}

BUSINESS_ALIASES = {
    "카페": "cafe", "cafe": "cafe", "카지노": "casino", "casino": "casino",
    "경마장": "racetrack", "racetrack": "racetrack", "탐정": "agency", "agency": "agency",
    "방송국": "studio", "studio": "studio", "장난감": "toyshop", "toyshop": "toyshop",
    "용병": "mercenary", "mercenary": "mercenary", "화투": "hwatuworkshop", "공방": "hwatuworkshop", "hwatuworkshop": "hwatuworkshop",
}

TITLES = {
    "festival_rookie": ("🎪", "축제 신입", "Festival Rookie", 0),
    "chaos_runner": ("🌪️", "혼돈의 질주자", "Chaos Runner", 15),
    "party_legend": ("🎉", "파티 전설", "Party Legend", 40),
    "treasure_hunter": ("🧭", "보물 사냥꾼", "Treasure Hunter", 25),
    "business_mogul": ("🏙️", "상권의 지배자", "Business Mogul", 60),
    "secret_keeper": ("🗝️", "비밀을 본 자", "Secret Keeper", 50),
}

BACKGROUNDS = {
    "night_casino": ("🌃", "밤의 카지노", "Night Casino", 0),
    "meteor_sky": ("☄️", "운석 하늘", "Meteor Sky", 10),
    "hwatu_shrine": ("🎴", "화투 신전", "Hwatu Shrine", 25),
    "moon_base": ("🌕", "달 기지", "Moon Base", 35),
    "chaos_carnival": ("🎪", "혼돈의 축제", "Chaos Carnival", 50),
}

TABLE_SKINS = {
    "classic": ("🟩", "클래식 녹색", "Classic Green", 0),
    "obsidian": ("⬛", "흑요석", "Obsidian", 15),
    "neon": ("🟪", "네온 도시", "Neon City", 25),
    "hwatu": ("🎴", "화투 비단", "Hwatu Silk", 30),
    "royal": ("👑", "왕실 결승", "Royal Final", 45),
}

CARD_BACKS = {
    "abaddon": ("😈", "아바돈 문장", "ABADDON Crest", 0),
    "raven": ("🐦‍⬛", "검은 까마귀", "Black Raven", 15),
    "meteor": ("☄️", "붉은 운석", "Red Meteor", 25),
    "gold": ("🟨", "황금 금고", "Golden Vault", 40),
}

BALANCE_QUESTIONS = (
    ("평생 포커에서 원페어만 나오기", "평생 화투에서 피만 나오기"),
    ("경마 1등 말인데 배당 1.01", "꼴찌 후보인데 배당 99.0"),
    ("아바돈과 하루 종일 맞고", "루시안과 밤새 홀덤"),
    ("매일 보물상자 하나", "한 달에 전설 상자 하나"),
    ("게임머니 10배 대신 모든 결과 공개", "현재 재산 유지 대신 완전 익명"),
)

FORTUNES = (
    ("대길", "오늘은 작은 선택이 큰 잭팟으로 돌아옵니다.", "Great luck", "A small choice may become a jackpot today."),
    ("길", "서두르지 않으면 좋은 패가 옵니다.", "Good luck", "Good cards arrive when you do not rush."),
    ("중길", "친구와 함께하면 운이 두 배입니다.", "Fair luck", "Your luck doubles with company."),
    ("소길", "무리한 레이즈보다 한 번의 체크가 빛납니다.", "Small luck", "One calm check beats a reckless raise."),
    ("주의", "미믹이 평범한 상자처럼 웃고 있습니다.", "Caution", "A mimic is smiling like an ordinary chest."),
)

SHADOW_QUIZZES = (
    ("🐘", "코가 길고 귀가 큽니다.", "It has a long trunk and large ears.", "코끼리", "elephant"),
    ("🚀", "지구를 떠나 별 사이를 갑니다.", "It leaves Earth and travels among stars.", "로켓", "rocket"),
    ("🎴", "열두 달의 그림으로 승부합니다.", "Twelve months of pictures decide the game.", "화투", "hwatu"),
    ("🏇", "결승선을 향해 달립니다.", "It races toward the finish line.", "경마", "horse racing"),
    ("👻", "벽을 통과하지만 문은 예의상 엽니다.", "It walks through walls but opens doors to be polite.", "유령", "ghost"),
)

LIAR_WORDS = (
    ("사과", "배"), ("고스톱", "섯다"), ("커피", "홍차"), ("달", "태양"),
    ("경마", "자동차 경주"), ("고양이", "여우"), ("카지노", "놀이공원"),
)

BINGO_WORDS = (
    "첫 승리", "파산", "경마 적중", "화투 광", "포커 플러시", "아바돈 승리", "보물 발견", "NPC 선물",
    "동료 진화", "사업 수익", "돌발 이벤트", "비밀 상인", "칭찬 받기", "출석", "탐험 성공", "월드보스",
    "연합 승리", "예약 경기", "중계 응원", "업적 해금", "전설 아이템", "게임 복구", "고블린", "운석 파괴", "자유칸",
)

SECRET_HINTS = (
    "자정 무렵, 시장 명령을 조용히 불러 보세요.",
    "화투의 열두 달을 모두 모은 사람에게 신전이 반응합니다.",
    "파산 상태에서도 탐험을 포기하지 않은 사람을 누군가 지켜봅니다.",
    "꼴찌 후보 경주마로 우승하면 오래된 편자가 빛납니다.",
    "서버 구성원 다섯 명이 같은 분 안에 칭찬을 이어가면 문이 열립니다.",
)


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    code: str
    payload: Dict[str, Any]


def normalize_token(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").strip().casefold())


def stable_seed(*parts: Any) -> int:
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def stable_pick(items: Sequence[Any], *parts: Any) -> Any:
    if not items:
        raise ValueError("items must not be empty")
    return items[stable_seed(*parts) % len(items)]


def event_key(value: Any) -> str:
    token = normalize_token(value)
    return EVENT_ALIASES.get(token, token if token in CHAOS_EVENTS else "")


def expedition_key(value: Any) -> str:
    token = normalize_token(value)
    return EXPEDITION_ALIASES.get(token, token if token in EXPEDITIONS else "")


def business_key(value: Any) -> str:
    token = normalize_token(value)
    return BUSINESS_ALIASES.get(token, token if token in BUSINESSES else "")


def reward_once(user_row: MutableMapping[str, Any], ledger_key: str, amount: int) -> RuleResult:
    ledger = user_row.setdefault("reward_ledger", {})
    if not isinstance(ledger, dict):
        ledger = {}
        user_row["reward_ledger"] = ledger
    key = str(ledger_key)[:120]
    if key in ledger:
        return RuleResult(False, "duplicate", {"amount": 0, "original": int(ledger[key].get("amount", 0)) if isinstance(ledger[key], Mapping) else 0})
    ledger[key] = {"amount": int(amount), "at": int(time.time())}
    if len(ledger) > 500:
        for old_key in sorted(ledger, key=lambda k: int(ledger[k].get("at", 0)) if isinstance(ledger[k], Mapping) else 0)[:-400]:
            ledger.pop(old_key, None)
    return RuleResult(True, "granted", {"amount": int(amount)})


def make_bingo(guild_id: int, season: str) -> List[str]:
    words = list(BINGO_WORDS[:-1])
    rng = random.Random(stable_seed("bingo", guild_id, season))
    rng.shuffle(words)
    board = words[:24]
    board.insert(12, "자유칸")
    return board


def bingo_lines(marked: Iterable[int]) -> int:
    points = {int(x) for x in marked if 0 <= int(x) < 25}
    lines = []
    lines.extend([{r * 5 + c for c in range(5)} for r in range(5)])
    lines.extend([{r * 5 + c for r in range(5)} for c in range(5)])
    lines.append({0, 6, 12, 18, 24})
    lines.append({4, 8, 12, 16, 20})
    return sum(1 for line in lines if line.issubset(points))


def assign_secret_friends(user_ids: Sequence[int], seed: Any) -> Dict[int, int]:
    unique = sorted({int(x) for x in user_ids})
    if len(unique) < 3:
        return {}
    targets = unique[:]
    rng = random.Random(stable_seed("secret-friend", seed, *unique))
    for _ in range(100):
        rng.shuffle(targets)
        if all(a != b for a, b in zip(unique, targets)):
            return dict(zip(unique, targets))
    return {uid: unique[(i + 1) % len(unique)] for i, uid in enumerate(unique)}


def mafia_roles(user_ids: Sequence[int], seed: Any) -> Dict[int, str]:
    players = sorted({int(x) for x in user_ids})
    if len(players) < 4:
        return {}
    roles = ["마피아"] * max(1, len(players) // 4) + ["의사", "경찰"]
    if len(players) >= 7:
        roles.append("광대")
    roles.extend(["시민"] * (len(players) - len(roles)))
    rng = random.Random(stable_seed("mafia", seed, *players))
    rng.shuffle(roles)
    return dict(zip(players, roles))


def liar_roles(user_ids: Sequence[int], seed: Any) -> RuleResult:
    players = sorted({int(x) for x in user_ids})
    if len(players) < 3:
        return RuleResult(False, "not_enough", {})
    normal, liar = stable_pick(LIAR_WORDS, "liar-words", seed, *players)
    liar_id = stable_pick(players, "liar-id", seed, *players)
    words = {uid: liar if uid == liar_id else normal for uid in players}
    return RuleResult(True, "ready", {"liar_id": liar_id, "normal": normal, "liar_word": liar, "words": words})


def start_expedition(zone: str, user_id: int, now: int | None = None) -> RuleResult:
    key = expedition_key(zone)
    if not key:
        return RuleResult(False, "unknown_zone", {})
    spec = EXPEDITIONS[key]
    now = int(now or time.time())
    seed = stable_seed("expedition", key, user_id, now // 60)
    return RuleResult(True, "started", {
        "id": f"X-{seed & 0xFFFFFFFF:08X}", "zone": key, "step": 0, "hp": 100,
        "luck": 0, "treasures": [], "started_at": now, "seed": seed,
        "status": "active", "choices": ["정찰", "돌진", "휴식"],
    })


def advance_expedition(session: Mapping[str, Any], choice: str) -> RuleResult:
    if str(session.get("status")) != "active":
        return RuleResult(False, "not_active", dict(session))
    zone = str(session.get("zone", ""))
    spec = EXPEDITIONS.get(zone)
    if not spec:
        return RuleResult(False, "unknown_zone", dict(session))
    row = dict(session)
    token = normalize_token(choice)
    aliases = {"1": "정찰", "정찰": "정찰", "scout": "정찰", "2": "돌진", "돌진": "돌진", "charge": "돌진", "3": "휴식", "휴식": "휴식", "rest": "휴식"}
    action = aliases.get(token, "")
    if not action:
        return RuleResult(False, "bad_choice", row)
    step = int(row.get("step", 0)) + 1
    rng = random.Random(int(row.get("seed", 0)) + step * 1009 + stable_seed(action))
    difficulty = int(spec["difficulty"])
    roll = rng.random()
    event = "safe"
    reward = 0
    damage = 0
    if action == "휴식":
        heal = 10 + rng.randrange(0, 11)
        row["hp"] = min(100, int(row.get("hp", 100)) + heal)
        event = "rest"
    elif roll < 0.18 + difficulty * 0.05:
        damage = 8 + difficulty * 4 + rng.randrange(0, 10)
        row["hp"] = max(0, int(row.get("hp", 100)) - damage)
        event = "trap"
    elif roll > 0.73 - (0.04 if action == "정찰" else 0):
        reward = (600 + difficulty * 350) * (2 if action == "돌진" and roll > 0.90 else 1)
        treasure = stable_pick(("낡은 금화", "별의 조각", "악마의 영수증", "고대 화투 조각", "유령 승차권", "달 기지 열쇠"), row["seed"], step)
        treasures = list(row.get("treasures", []))
        treasures.append(treasure)
        row["treasures"] = treasures
        event = "treasure"
    else:
        row["luck"] = int(row.get("luck", 0)) + (2 if action == "정찰" else 1)
    row["step"] = step
    row["last_action"] = action
    row["last_event"] = event
    if int(row.get("hp", 0)) <= 0:
        row["status"] = "failed"
    elif step >= int(spec["steps"]):
        row["status"] = "complete"
        reward += 1200 * difficulty + int(row.get("luck", 0)) * 100
    return RuleResult(True, event, {"session": row, "reward": reward, "damage": damage})


def business_income(business: Mapping[str, Any], visitor_count: int, seed: Any) -> int:
    key = str(business.get("type", ""))
    spec = BUSINESSES.get(key)
    if not spec:
        return 0
    level = max(1, int(business.get("level", 1)))
    employees = max(0, len(business.get("employees", [])) if isinstance(business.get("employees"), list) else 0)
    rating = max(0.5, min(2.0, float(business.get("rating", 1.0) or 1.0)))
    rng = random.Random(stable_seed("business", key, seed, visitor_count, level))
    variance = 0.85 + rng.random() * 0.30
    gross = (int(spec["base"]) * level + visitor_count * 140 + employees * 220) * rating * variance
    tax = gross * min(0.35, 0.08 + level * 0.01)
    return max(0, int(gross - tax))


def compatibility_score(user_a: int, user_b: int, date_key: str) -> int:
    a, b = sorted((int(user_a), int(user_b)))
    return 25 + stable_seed("compat", a, b, date_key) % 76


def fortune_for(user_id: int, date_key: str) -> Tuple[str, str, str, str, int]:
    row = stable_pick(FORTUNES, "fortune", user_id, date_key)
    lucky = 1 + stable_seed("lucky-number", user_id, date_key) % 99
    return (*row, lucky)


def sanitize_anonymous_message(text: str) -> RuleResult:
    value = str(text or "").strip()
    if not value:
        return RuleResult(False, "empty", {})
    if len(value) > 160:
        return RuleResult(False, "too_long", {})
    if "http://" in value.casefold() or "https://" in value.casefold() or "discord.gg/" in value.casefold():
        return RuleResult(False, "link", {})
    value = re.sub(r"<@!?\d+>|<@&\d+>|@everyone|@here", "[멘션 차단]", value, flags=re.IGNORECASE)
    return RuleResult(True, "ok", {"text": value})


def unlock_cosmetics(fun: MutableMapping[str, Any]) -> List[str]:
    score = int(fun.get("fun_score", 0))
    owned = fun.setdefault("cosmetics", {})
    if not isinstance(owned, dict):
        owned = {}
        fun["cosmetics"] = owned
    new: List[str] = []
    for category, catalog in (("titles", TITLES), ("backgrounds", BACKGROUNDS), ("tables", TABLE_SKINS), ("card_backs", CARD_BACKS)):
        bucket = owned.setdefault(category, [])
        if not isinstance(bucket, list):
            bucket = []
            owned[category] = bucket
        for key, row in catalog.items():
            requirement = int(row[3])
            if score >= requirement and key not in bucket:
                bucket.append(key)
                new.append(f"{category}:{key}")
    return new


def secret_flags(fun: Mapping[str, Any], context: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    if int(context.get("hwatu_months", 0)) >= 12:
        flags.append("twelve_moons")
    if int(context.get("balance", 0)) < 0 and int(context.get("expeditions_complete", 0)) > 0:
        flags.append("bankrupt_explorer")
    if int(context.get("underdog_race_wins", 0)) > 0:
        flags.append("underdog_crown")
    if int(context.get("praise_chain", 0)) >= 5:
        flags.append("praise_door")
    if int(fun.get("secret_points", 0)) >= 7:
        flags.append("abaddon_final")
    return flags


def audit_catalogues() -> Dict[str, Any]:
    return {
        "events": len(CHAOS_EVENTS), "npcs": len(NPCS), "pets": len(PETS),
        "expeditions": len(EXPEDITIONS), "businesses": len(BUSINESSES),
        "titles": len(TITLES), "backgrounds": len(BACKGROUNDS),
        "tables": len(TABLE_SKINS), "card_backs": len(CARD_BACKS),
        "bingo_cells": len(BINGO_WORDS), "version": VERSION,
    }
