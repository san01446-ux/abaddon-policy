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

from apocalypse_bot.commands.v610_digging_treasure import (
    GRADE_ORDER,
    GRADE_VALUES,
    GRADE_WEIGHTS,
    PENDING_LIMIT,
    TREASURE_NAMES,
    _ensure_profile as _ensure_treasure_profile,
)

VERSION = "8.1.1"
SCHEMA_VERSION = 2
KST = timezone(timedelta(hours=9))
FARM_DAILY_LIMIT = 16
SIGNAL_DAILY_LIMIT = 5
ENCOUNTER_TTL_SECONDS = 900

# Public surfaces intentionally expose no acquisition rates. All weighted tables remain internal.
FARM_REGIONS: Dict[str, Dict[str, Any]] = {
    "market": {
        "name": "버려진 대형마트",
        "emoji": "🛒",
        "aliases": ("마트", "대형마트", "시장", "market"),
        "level": 1,
        "stamina": 8,
        "cooldown": 480,
        "danger": "낮음",
        "focus": "식량과 생활 물자",
    },
    "residential": {
        "name": "붕괴 주거구역",
        "emoji": "🏚️",
        "aliases": ("주거", "주거구역", "폐가", "residential"),
        "level": 5,
        "stamina": 10,
        "cooldown": 720,
        "danger": "보통",
        "focus": "고철·나무·약초와 폐품",
    },
    "freight": {
        "name": "지하 화물역",
        "emoji": "🚇",
        "aliases": ("화물역", "지하역", "철도", "freight"),
        "level": 15,
        "stamina": 13,
        "cooldown": 1_080,
        "danger": "높음",
        "focus": "광석·보물 파편과 봉인 물자",
    },
    "quarantine": {
        "name": "흑색 격리구역",
        "emoji": "☣️",
        "aliases": ("격리", "격리구역", "흑색구역", "quarantine"),
        "level": 30,
        "stamina": 16,
        "cooldown": 1_500,
        "danger": "매우 높음",
        "focus": "오염 표본·설계도 조각과 미감정 보물",
    },
}

_REGION_LOOKUP: Dict[str, str] = {}
for _region_key, _region in FARM_REGIONS.items():
    _REGION_LOOKUP[_region_key.casefold()] = _region_key
    _REGION_LOOKUP[str(_region["name"]).replace(" ", "").casefold()] = _region_key
    for _alias in _region["aliases"]:
        _REGION_LOOKUP[str(_alias).replace(" ", "").casefold()] = _region_key

# Internal weighted acquisition tables. Do not render these values in public messages or site copy.
_COMMON_TABLES: Dict[str, Tuple[Tuple[int, Tuple[str, str, int, int]], ...]] = {
    "market": (
        (46, ("food", "식량", 180, 520)),
        (20, ("resource", "나무", 2, 6)),
        (18, ("resource", "약초", 2, 5)),
        (16, ("resource", "고철", 2, 5)),
    ),
    "residential": (
        (30, ("resource", "고철", 3, 8)),
        (26, ("resource", "나무", 3, 8)),
        (22, ("resource", "약초", 2, 6)),
        (22, ("food", "식량", 260, 720)),
    ),
    "freight": (
        (31, ("resource", "광석", 3, 8)),
        (26, ("resource", "고철", 4, 10)),
        (25, ("food", "식량", 420, 1_050)),
        (18, ("material", "보물파편", 1, 3)),
    ),
    "quarantine": (
        (29, ("resource", "약초", 4, 10)),
        (25, ("material", "오염표본", 1, 3)),
        (25, ("food", "식량", 650, 1_500)),
        (21, ("material", "보물파편", 2, 5)),
    ),
}

_BONUS_TABLES: Dict[str, Tuple[Tuple[int, Tuple[str, str, int, int]], ...]] = {
    "market": (
        (43, ("food", "식량", 120, 360)),
        (28, ("resource", "고철", 1, 4)),
        (19, ("scrap", "미감정 폐품", 1, 1)),
        (8, ("material", "보물파편", 1, 1)),
        (2, ("treasure", "미감정 보물", 1, 1)),
    ),
    "residential": (
        (34, ("resource", "고철", 2, 6)),
        (25, ("scrap", "미감정 폐품", 1, 1)),
        (22, ("material", "폐허회로", 1, 2)),
        (15, ("material", "보물파편", 1, 2)),
        (4, ("treasure", "미감정 보물", 1, 1)),
    ),
    "freight": (
        (30, ("resource", "광석", 2, 6)),
        (24, ("material", "보물파편", 1, 3)),
        (20, ("scrap", "미감정 폐품", 1, 1)),
        (19, ("material", "폐허회로", 1, 3)),
        (5, ("treasure", "미감정 보물", 1, 1)),
        (2, ("material", "설계도조각", 1, 1)),
    ),
    "quarantine": (
        (29, ("material", "오염표본", 1, 3)),
        (24, ("material", "보물파편", 2, 4)),
        (19, ("scrap", "미감정 폐품", 1, 1)),
        (16, ("material", "폐허회로", 2, 4)),
        (8, ("treasure", "미감정 보물", 1, 1)),
        (4, ("material", "설계도조각", 1, 1)),
    ),
}

_ENCOUNTERS: Tuple[Dict[str, Any], ...] = (
    {
        "key": "infected", "category": "threat", "emoji": "🧟", "actor": "감염체 무리",
        "title": "감염체 무리가 통로를 막았습니다",
        "description": "깨진 진열대 뒤로 보급 상자가 보입니다. 소음을 내면 더 많은 감염체가 몰려올 수 있습니다.",
        "regions": ("market", "residential", "freight", "quarantine"),
    },
    {
        "key": "raiders", "category": "threat", "emoji": "🏴", "actor": "약탈자 정찰조",
        "title": "약탈자 정찰조가 접근합니다",
        "description": "상대는 아직 당신을 완전히 발견하지 못했습니다. 주변에는 버려진 운반 상자가 흩어져 있습니다.",
        "regions": ("residential", "freight", "quarantine"),
    },
    {
        "key": "mutant_hounds", "category": "threat", "emoji": "🐺", "actor": "변이 들개 떼",
        "title": "변이 들개 떼가 냄새를 따라왔습니다",
        "description": "철망 너머에서 낮은 울음소리가 번집니다. 가까운 창고 안에는 아직 물자 반응이 남아 있습니다.",
        "regions": ("market", "residential", "freight"),
    },
    {
        "key": "rogue_drones", "category": "threat", "emoji": "🤖", "actor": "오작동 경비 드론",
        "title": "오작동 경비 드론이 표적을 탐색합니다",
        "description": "붉은 탐조등이 통로를 훑고 있습니다. 드론 뒤편 제어함을 확보하면 폐허 회로를 건질 수 있습니다.",
        "regions": ("freight", "quarantine"),
    },
    {
        "key": "toxic_leak", "category": "hazard", "emoji": "☣️", "actor": "독성 누출 구역",
        "title": "배관에서 독성 증기가 새어 나옵니다",
        "description": "시야가 흐려지고 경보음이 빨라집니다. 밸브를 안정화하면 봉쇄된 물자함까지 접근할 수 있습니다.",
        "regions": ("freight", "quarantine"),
    },
    {
        "key": "collapse", "category": "hazard", "emoji": "🏚️", "actor": "붕괴 직전 구조물",
        "title": "천장 균열이 빠르게 번지고 있습니다",
        "description": "잔해 사이에서 생체 신호와 금속 상자 반응이 함께 잡힙니다. 오래 머물수록 통로가 불안정해집니다.",
        "regions": ("market", "residential", "freight"),
    },
    {
        "key": "electrical_fire", "category": "hazard", "emoji": "⚡", "actor": "과부하 전력실",
        "title": "전력실에서 청색 불꽃이 튀고 있습니다",
        "description": "차단기를 내리면 주변 보급 장치가 살아날 수 있지만, 잘못 건드리면 통로 전체가 정전됩니다.",
        "regions": ("market", "freight", "quarantine"),
    },
    {
        "key": "distress", "category": "rescue", "emoji": "📡", "actor": "미확인 구조 신호",
        "title": "붕괴 건물에서 구조 신호가 잡혔습니다",
        "description": "약한 생체 신호와 함께 보급품 위치 정보가 반복 송신됩니다.",
        "regions": ("residential", "freight", "quarantine"),
    },
    {
        "key": "trapped_family", "category": "rescue", "emoji": "🧑‍🧑‍🧒", "actor": "고립된 생존자 가족",
        "title": "무너진 상가 안에서 사람 목소리가 들립니다",
        "description": "잔해 아래에 고립된 생존자들이 있습니다. 주변에는 그들이 모아 둔 식량 상자가 보입니다.",
        "regions": ("market", "residential"),
    },
    {
        "key": "wounded_scout", "category": "rescue", "emoji": "🩹", "actor": "부상당한 길잡이",
        "title": "부상당한 길잡이가 벽에 기대어 신호를 보냅니다",
        "description": "그는 안전한 지름길과 숨겨진 저장고 위치를 알고 있지만, 먼저 응급 처치가 필요해 보입니다.",
        "regions": ("residential", "freight", "quarantine"),
    },
    {
        "key": "white_lamp", "category": "ally", "emoji": "🚑", "actor": "백색등 구조대",
        "title": "백색등 구조대가 현장 수색을 진행 중입니다",
        "description": "구조대는 잔해 안쪽 생존 신호를 추적하고 있습니다. 인력을 보태면 공동 회수 구역을 열 수 있습니다.",
        "regions": ("market", "residential", "freight"),
    },
    {
        "key": "blue_shield", "category": "ally", "emoji": "🛡️", "actor": "푸른 방패 민병대",
        "title": "푸른 방패 민병대가 통로를 지키고 있습니다",
        "description": "민병대는 피난민 이동로를 확보하는 중입니다. 주변 위협을 정리하면 남은 물자를 공정하게 나누겠다고 합니다.",
        "regions": ("residential", "freight", "quarantine"),
    },
    {
        "key": "dawn_medics", "category": "ally", "emoji": "⚕️", "actor": "새벽 의무단",
        "title": "새벽 의무단의 임시 진료소를 발견했습니다",
        "description": "의무단은 부상자를 치료하며 약초와 의료 표본을 분류하고 있습니다. 손을 보태면 현장 자료를 나눠 줍니다.",
        "regions": ("market", "residential", "quarantine"),
    },
    {
        "key": "rail_engineers", "category": "ally", "emoji": "🧰", "actor": "철도 복구단",
        "title": "철도 복구단이 끊어진 화물선을 수리합니다",
        "description": "복구단은 잔해 제거와 전력 연결에 도움이 필요합니다. 작업이 끝나면 봉인 화물칸을 함께 확인할 수 있습니다.",
        "regions": ("freight",),
    },
    {
        "key": "supply_escort", "category": "ally", "emoji": "🚚", "actor": "보급 호위대",
        "title": "보급 호위대가 멈춰 선 수송차를 지키고 있습니다",
        "description": "바퀴가 잔해에 걸려 이동이 중단됐습니다. 호위를 돕거나 수리를 지원하면 일부 보급품을 받을 수 있습니다.",
        "regions": ("market", "residential", "freight"),
    },
    {
        "key": "ranger_patrol", "category": "ally", "emoji": "🧭", "actor": "황무지 정찰대",
        "title": "황무지 정찰대가 안전 표식을 갱신하고 있습니다",
        "description": "정찰대는 위험 구역과 숨겨진 회수 지점을 지도에 표시 중입니다. 정보를 교환하면 새로운 길이 열릴 수 있습니다.",
        "regions": ("residential", "freight", "quarantine"),
    },
    {
        "key": "vault", "category": "mystery", "emoji": "🔐", "actor": "봉인 보관실",
        "title": "봉인된 지하 보관실을 발견했습니다",
        "description": "문 주변에 급조된 경보 장치가 남아 있습니다. 내부 물자는 아직 회수되지 않은 듯합니다.",
        "regions": ("market", "residential", "freight", "quarantine"),
    },
    {
        "key": "archive_terminal", "category": "mystery", "emoji": "🖥️", "actor": "구형 기록 단말",
        "title": "꺼져 있던 기록 단말이 갑자기 켜졌습니다",
        "description": "화면에는 좌표와 구조 명단이 교대로 나타납니다. 전원을 유지하면 숨겨진 저장고를 찾을 수 있습니다.",
        "regions": ("residential", "freight", "quarantine"),
    },
    {
        "key": "lost_convoy", "category": "mystery", "emoji": "🚛", "actor": "실종된 보급대 흔적",
        "title": "실종된 보급대의 표식을 발견했습니다",
        "description": "끊어진 로프와 빈 탄피, 멀리 이어지는 바퀴 자국이 보입니다. 흔적을 추적하면 남은 화물을 찾을 수 있습니다.",
        "regions": ("market", "residential", "freight"),
    },
    {
        "key": "wandering_trader", "category": "trade", "emoji": "🧳", "actor": "떠돌이 공정 상인",
        "title": "중립 표식을 단 떠돌이 상인이 손을 흔듭니다",
        "description": "상인은 약탈품을 취급하지 않는다며, 주변 길을 안전하게 만드는 데 협력하면 물자를 나누겠다고 합니다.",
        "regions": ("market", "residential", "freight", "quarantine"),
    },
)

_ENCOUNTER_BY_KEY: Dict[str, Dict[str, Any]] = {str(row["key"]): row for row in _ENCOUNTERS}
_ENCOUNTER_CATEGORY_LABELS = {
    "threat": "🚨 적대 신호", "hazard": "⚠️ 환경 위험", "rescue": "🆘 구조 요청",
    "ally": "🤝 우호 세력", "mystery": "✨ 미확인 발견", "trade": "🕊️ 중립 접촉",
}
_ENCOUNTER_ACTIONS: Dict[str, Dict[str, Tuple[str, str, discord.ButtonStyle]]] = {
    "threat": {
        "fight": ("맞서기", "⚔️", discord.ButtonStyle.danger),
        "evade": ("우회", "🫥", discord.ButtonStyle.secondary),
        "rescue": ("보호", "🛡️", discord.ButtonStyle.success),
        "search": ("빈틈 탐색", "🔎", discord.ButtonStyle.primary),
    },
    "hazard": {
        "fight": ("돌파", "💥", discord.ButtonStyle.danger),
        "evade": ("안전 우회", "🫥", discord.ButtonStyle.secondary),
        "rescue": ("현장 안정화", "🧰", discord.ButtonStyle.success),
        "search": ("원인 조사", "📡", discord.ButtonStyle.primary),
    },
    "rescue": {
        "fight": ("잔해 제거", "💪", discord.ButtonStyle.danger),
        "evade": ("안전 확인", "👁️", discord.ButtonStyle.secondary),
        "rescue": ("구조", "🩹", discord.ButtonStyle.success),
        "search": ("주변 수색", "📡", discord.ButtonStyle.primary),
    },
    "ally": {
        "fight": ("합류", "🤝", discord.ButtonStyle.success),
        "evade": ("경계 유지", "🧭", discord.ButtonStyle.secondary),
        "rescue": ("지원", "📦", discord.ButtonStyle.success),
        "search": ("공동 수색", "🔎", discord.ButtonStyle.primary),
    },
    "mystery": {
        "fight": ("강제 개방", "🔧", discord.ButtonStyle.danger),
        "evade": ("원격 확인", "🛰️", discord.ButtonStyle.secondary),
        "rescue": ("안전 해제", "🔐", discord.ButtonStyle.success),
        "search": ("정밀 조사", "🔎", discord.ButtonStyle.primary),
    },
    "trade": {
        "fight": ("호위 협력", "🛡️", discord.ButtonStyle.success),
        "evade": ("관망", "👁️", discord.ButtonStyle.secondary),
        "rescue": ("거래 지원", "🤝", discord.ButtonStyle.success),
        "search": ("주변 탐색", "📦", discord.ButtonStyle.primary),
    },
}


ACTION_ALIASES = {
    "전투": "fight", "싸움": "fight", "공격": "fight", "맞서기": "fight", "돌파": "fight",
    "잔해제거": "fight", "합류": "fight", "호위": "fight", "강제개방": "fight", "fight": "fight",
    "회피": "evade", "도주": "evade", "피하기": "evade", "우회": "evade", "안전우회": "evade",
    "경계": "evade", "경계유지": "evade", "관망": "evade", "원격확인": "evade", "evade": "evade",
    "구조": "rescue", "구출": "rescue", "도움": "rescue", "보호": "rescue", "지원": "rescue",
    "현장안정화": "rescue", "안전해제": "rescue", "거래지원": "rescue", "rescue": "rescue",
    "추가탐색": "search", "탐색": "search", "수색": "search", "공동수색": "search",
    "정밀조사": "search", "원인조사": "search", "주변수색": "search", "search": "search",
}
ACTION_LABELS = {
    "fight": "⚔️ 전투",
    "evade": "🫥 회피",
    "rescue": "🩹 구조",
    "search": "🔎 추가 탐색",
}

_SCRAP_NAMES: Dict[str, Tuple[str, ...]] = {
    "device": ("손상된 휴대 단말", "금이 간 감시 카메라", "폐기된 무전 증폭기"),
    "machine": ("고장 난 정수 펌프", "불완전한 자동문 모터", "녹슨 소형 발전기"),
    "medical": ("봉인 불량 의료 장치", "낡은 생체 스캐너", "파손된 약품 냉각기"),
    "archive": ("암호화 기록 저장기", "훼손된 설계 데이터함", "구형 연구 로그 단말"),
}
_SCRAP_KIND_BY_REGION = {
    "market": ("device", "machine"),
    "residential": ("device", "machine", "medical"),
    "freight": ("machine", "device", "archive"),
    "quarantine": ("medical", "archive", "device"),
}

_SIGNAL_PUZZLES: Tuple[Dict[str, Any], ...] = (
    {"question": "신호 묶음 `2 · 4 · 8 · 16 · ?`", "options": ("18", "24", "32", "34"), "answer": 3},
    {"question": "신호 묶음 `A · C · F · J · ?`", "options": ("M", "N", "O", "P"), "answer": 3},
    {"question": "주파수 파형 `낮음 · 높음 · 높음 · 낮음 · 낮음 · ?`", "options": ("낮음", "높음", "무음", "불규칙"), "answer": 2},
    {"question": "좌표 코드 `북 · 동 · 남 · 서 · 북 · ?`", "options": ("북", "동", "남", "서"), "answer": 2},
    {"question": "점멸 코드 `● ○ ●● ○○ ●●● ?`", "options": ("○", "○○", "○○○", "●"), "answer": 3},
)

_CONTRACT_TEMPLATES: Tuple[Dict[str, Any], ...] = (
    {"title": "대피소 식량 재포장", "kind": "resource", "key": "나무", "amount": (8, 16), "food": (3_500, 6_000), "research": 2},
    {"title": "정비반 금속 긴급 요청", "kind": "resource", "key": "고철", "amount": (10, 22), "food": (4_000, 7_500), "research": 2},
    {"title": "격리병동 약초 보급", "kind": "resource", "key": "약초", "amount": (8, 18), "food": (4_500, 8_000), "research": 3},
    {"title": "철도 복구용 광석 납품", "kind": "resource", "key": "광석", "amount": (7, 15), "food": (5_000, 9_500), "research": 3},
    {"title": "감정소 보물 파편 매입", "kind": "material", "key": "보물파편", "amount": (3, 7), "food": (7_000, 13_000), "research": 4},
    {"title": "통신실 폐허 회로 조달", "kind": "material", "key": "폐허회로", "amount": (3, 8), "food": (7_500, 14_000), "research": 4},
    {"title": "연구소 오염 표본 수거", "kind": "material", "key": "오염표본", "amount": (2, 6), "food": (9_000, 17_000), "research": 5},
)

_RESEARCH: Dict[str, Dict[str, Any]] = {
    "field_rations": {
        "name": "현장 배급 최적화", "aliases": ("현장배급", "배급", "식량최적화"),
        "points": 12, "fragments": 1, "duration": 900,
        "description": "파밍 출발 시 필요한 스태미나 부담을 줄입니다.",
    },
    "salvage": {
        "name": "폐품 회수 공정", "aliases": ("폐품회수", "회수공정", "분해기술"),
        "points": 16, "fragments": 2, "duration": 1_200,
        "description": "폐품 분해와 수리 실패 시 회수되는 재료를 개선합니다.",
    },
    "signal_filter": {
        "name": "주파수 잡음 필터", "aliases": ("잡음필터", "주파수필터", "신호연구"),
        "points": 18, "fragments": 2, "duration": 1_500,
        "description": "전파 해독 성공 시 연구 자료를 더 안정적으로 확보합니다.",
    },
    "contract_network": {
        "name": "생존 계약망", "aliases": ("계약망", "납품망", "생존계약"),
        "points": 24, "fragments": 3, "duration": 1_800,
        "description": "일일 납품 계약의 정산 조건을 개선합니다.",
    },
}
_RESEARCH_LOOKUP: Dict[str, str] = {}
for _tech_key, _tech in _RESEARCH.items():
    _RESEARCH_LOOKUP[_tech_key.casefold()] = _tech_key
    _RESEARCH_LOOKUP[str(_tech["name"]).replace(" ", "").casefold()] = _tech_key
    for _alias in _tech["aliases"]:
        _RESEARCH_LOOKUP[str(_alias).replace(" ", "").casefold()] = _tech_key


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _kst_date() -> str:
    return _now().astimezone(KST).strftime("%Y-%m-%d")


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _format_seconds(seconds: Any) -> str:
    value = max(0, _safe_int(seconds, 0))
    minutes, remain = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {remain}초"
    return f"{remain}초"


def _region_key(value: Any) -> Optional[str]:
    return _REGION_LOOKUP.get(str(value or "").strip().replace(" ", "").casefold())


def _research_key(value: Any) -> Optional[str]:
    return _RESEARCH_LOOKUP.get(str(value or "").strip().replace(" ", "").casefold())


def _action_key(value: Any) -> Optional[str]:
    return ACTION_ALIASES.get(str(value or "").strip().replace(" ", "").casefold())



def _encounter_from_pending(pending: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(pending.get("encounter_key") or "")
    if key in _ENCOUNTER_BY_KEY:
        return _ENCOUNTER_BY_KEY[key]
    index = _safe_int(pending.get("encounter_index"), 0) % len(_ENCOUNTERS)
    return _ENCOUNTERS[index]


def _encounter_action(category: str, action: str) -> Tuple[str, str, discord.ButtonStyle]:
    mapping = _ENCOUNTER_ACTIONS.get(category, _ENCOUNTER_ACTIONS["threat"])
    return mapping.get(action, mapping["search"])


def _choose_encounter(profile: Mapping[str, Any], region_key: str, rng: random.Random) -> Dict[str, Any]:
    pool = [row for row in _ENCOUNTERS if region_key in row.get("regions", ())]
    recent = [str(x) for x in profile.get("recent_encounters", [])] if isinstance(profile.get("recent_encounters"), list) else []
    fresh = [row for row in pool if str(row.get("key")) not in recent[-4:]]
    return rng.choice(fresh or pool or list(_ENCOUNTERS))


def _category_colour(category: str) -> discord.Colour:
    return {
        "threat": discord.Colour.red(),
        "hazard": discord.Colour.orange(),
        "rescue": discord.Colour.gold(),
        "ally": discord.Colour.green(),
        "mystery": discord.Colour.purple(),
        "trade": discord.Colour.teal(),
    }.get(category, discord.Colour.dark_teal())


def _route_line(position: int, *, encounter: bool = False, result: bool = False) -> str:
    nodes = ["🚪", "🗺️", "📡", "⚠️" if encounter else "✨", "📦", "🏠"]
    position = max(0, min(position, len(nodes) - 1))
    pieces: List[str] = []
    for index, node in enumerate(nodes):
        if index == position:
            marker = "💨" if index < len(nodes) - 1 else "✅"
            pieces.append(f"{marker}{node}")
        elif index < position:
            pieces.append(f"✅{node}")
        else:
            pieces.append(f"▫️{node}")
    suffix = " · 정산 완료" if result else ""
    return " `" + " ━ ".join(pieces) + "`" + suffix


def _dict(parent: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _list(parent: MutableMapping[str, Any], key: str) -> List[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        value = []
        parent[key] = value
    return value


def ensure_v770_profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = user.get("farming_v770")
    if not isinstance(profile, dict):
        profile = {}
        user["farming_v770"] = profile
    profile["schema_version"] = SCHEMA_VERSION
    today = _kst_date()
    if profile.get("date") != today:
        profile["date"] = today
        profile["attempts"] = 0
    profile["attempts"] = max(0, _safe_int(profile.get("attempts"), 0))
    profile["last_at"] = str(profile.get("last_at") or "")
    pending = profile.get("pending_encounter")
    profile["pending_encounter"] = pending if isinstance(pending, dict) else {}
    profile["history"] = [row for row in profile.get("history", []) if isinstance(row, dict)] if isinstance(profile.get("history"), list) else []
    profile["recent_encounters"] = [str(x) for x in profile.get("recent_encounters", [])][-4:] if isinstance(profile.get("recent_encounters"), list) else []
    profile["encounter_discovery"] = [str(x) for x in profile.get("encounter_discovery", []) if str(x) in _ENCOUNTER_BY_KEY] if isinstance(profile.get("encounter_discovery"), list) else []
    stats = _dict(profile, "stats")
    for key in ("runs", "encounters", "fight", "evade", "rescue", "search", "treasures", "scrap", "contracts", "signals", "ally", "rescue_event", "threat", "hazard", "mystery", "trade"):
        stats[key] = max(0, _safe_int(stats.get(key), 0))

    workshop = _dict(profile, "workshop")
    workshop["unidentified"] = [row for row in workshop.get("unidentified", []) if isinstance(row, dict)] if isinstance(workshop.get("unidentified"), list) else []
    workshop["identified"] = [row for row in workshop.get("identified", []) if isinstance(row, dict)] if isinstance(workshop.get("identified"), list) else []
    workshop["history"] = [row for row in workshop.get("history", []) if isinstance(row, dict)] if isinstance(workshop.get("history"), list) else []

    signal = _dict(profile, "signal")
    if signal.get("date") != today:
        signal["date"] = today
        signal["attempts"] = 0
        signal["pending"] = {}
    signal["attempts"] = max(0, _safe_int(signal.get("attempts"), 0))
    signal["last_at"] = str(signal.get("last_at") or "")
    signal["pending"] = signal.get("pending") if isinstance(signal.get("pending"), dict) else {}
    signal["history"] = [row for row in signal.get("history", []) if isinstance(row, dict)] if isinstance(signal.get("history"), list) else []

    contracts = _dict(profile, "contracts")
    if contracts.get("date") != today:
        contracts["date"] = today
        contracts["accepted"] = ""
        contracts["completed"] = []
    contracts["accepted"] = str(contracts.get("accepted") or "")
    contracts["completed"] = [str(x) for x in contracts.get("completed", [])] if isinstance(contracts.get("completed"), list) else []
    contracts["history"] = [row for row in contracts.get("history", []) if isinstance(row, dict)] if isinstance(contracts.get("history"), list) else []

    research = _dict(profile, "research")
    research["points"] = max(0, _safe_int(research.get("points"), 0))
    research["unlocked"] = [str(x) for x in research.get("unlocked", []) if str(x) in _RESEARCH] if isinstance(research.get("unlocked"), list) else []
    research["active"] = research.get("active") if isinstance(research.get("active"), dict) else {}
    research["history"] = [row for row in research.get("history", []) if isinstance(row, dict)] if isinstance(research.get("history"), list) else []
    return profile


def _user_lock(bot: commands.Bot, user_id: Any) -> asyncio.Lock:
    locks = getattr(bot, "_abaddon_v770_user_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        setattr(bot, "_abaddon_v770_user_locks", locks)
    key = str(user_id)
    lock = locks.get(key)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


def _weighted_pick(rng: random.Random, table: Sequence[Tuple[int, Any]]) -> Any:
    total = sum(max(0, int(weight)) for weight, _row in table)
    cursor = rng.randrange(max(1, total))
    running = 0
    for weight, row in table:
        running += max(0, int(weight))
        if cursor < running:
            return row
    return table[-1][1]


def _new_treasure(rng: random.Random) -> Dict[str, Any]:
    grade = rng.choices(GRADE_ORDER, weights=GRADE_WEIGHTS, k=1)[0]
    return {
        "id": f"FR-{secrets.token_hex(3).upper()}",
        "grade": grade,
        "name": rng.choice(tuple(TREASURE_NAMES[grade])),
        "base_value": rng.randint(*GRADE_VALUES[grade]),
        "found_at": _iso(),
        "source": "farming_v770",
    }


def _new_scrap(rng: random.Random, region_key: str) -> Dict[str, Any]:
    kind = rng.choice(_SCRAP_KIND_BY_REGION.get(region_key, ("device",)))
    tier = rng.choices((0, 1, 2, 3, 4), weights=(48, 30, 15, 6, 1), k=1)[0]
    return {
        "id": f"SP-{secrets.token_hex(3).upper()}",
        "kind": kind,
        "tier": tier,
        "seed": rng.randrange(1, 2**31 - 1),
        "found_at": _iso(),
        "source": region_key,
    }


def _public_reward_label(kind: str, key: str, amount: int) -> str:
    if kind == "food":
        return f"🥫 식량 +{amount:,}"
    if kind == "resource":
        emoji = {"나무": "🪵", "고철": "🔩", "광석": "🪨", "약초": "🌿", "물고기": "🐟"}.get(key, "📦")
        return f"{emoji} {key} +{amount:,}"
    if kind == "material":
        emoji = {"보물파편": "🧩", "폐허회로": "🔌", "오염표본": "🧪", "설계도조각": "📐"}.get(key, "🧱")
        return f"{emoji} {key} +{amount:,}"
    if kind == "treasure":
        return "💎 미감정 보물 +1"
    if kind == "scrap":
        return "🧰 미감정 폐품 +1"
    if kind == "research":
        return f"📡 연구 자료 +{amount:,}"
    return f"📦 {key} +{amount:,}"


def _grant_rewards(user: MutableMapping[str, Any], profile: MutableMapping[str, Any], rewards: Sequence[Mapping[str, Any]], rng: random.Random) -> List[str]:
    lines: List[str] = []
    resources = _dict(user, "resources")
    materials = _dict(user, "materials")
    stats = _dict(user, "stats")
    workshop = _dict(profile, "workshop")
    research = _dict(profile, "research")
    treasure_profile = _ensure_treasure_profile(user)
    for reward in rewards:
        kind = str(reward.get("kind") or "")
        key = str(reward.get("key") or "")
        amount = max(0, _safe_int(reward.get("amount"), 0))
        if amount <= 0:
            continue
        if kind == "food":
            user["balance"] = max(0, _safe_int(user.get("balance"), 0)) + amount
            stats["earned"] = max(0, _safe_int(stats.get("earned"), 0)) + amount
        elif kind == "resource":
            resources[key] = max(0, _safe_int(resources.get(key), 0)) + amount
        elif kind == "material":
            materials[key] = max(0, _safe_int(materials.get(key), 0)) + amount
        elif kind == "research":
            research["points"] = max(0, _safe_int(research.get("points"), 0)) + amount
        elif kind == "treasure":
            if len(treasure_profile.get("pending", [])) < PENDING_LIMIT:
                treasure_profile["pending"].append(_new_treasure(rng))
                treasure_profile["treasure_count"] = max(0, _safe_int(treasure_profile.get("treasure_count"), 0)) + 1
                profile["stats"]["treasures"] += 1
            else:
                replacement = 2
                materials["보물파편"] = max(0, _safe_int(materials.get("보물파편"), 0)) + replacement
                lines.append(_public_reward_label("material", "보물파편", replacement))
                continue
        elif kind == "scrap":
            workshop.setdefault("unidentified", []).append(_new_scrap(rng, str(reward.get("region") or "market")))
            profile["stats"]["scrap"] += 1
        lines.append(_public_reward_label(kind, key, amount))
    return lines


def _roll_base_rewards(region_key: str, rng: random.Random, *, enhanced: bool = False, allow_special: bool = True) -> List[Dict[str, Any]]:
    common = _weighted_pick(rng, _COMMON_TABLES[region_key])
    kind, key, low, high = common
    rewards: List[Dict[str, Any]] = [{"kind": kind, "key": key, "amount": rng.randint(low, high), "region": region_key}]
    bonus_gate = 68 if enhanced else 44
    if rng.randrange(100) < bonus_gate:
        bonus = _weighted_pick(rng, _BONUS_TABLES[region_key])
        b_kind, b_key, b_low, b_high = bonus
        if allow_special or b_kind not in {"treasure", "scrap"}:
            rewards.append({"kind": b_kind, "key": b_key, "amount": rng.randint(b_low, b_high), "region": region_key})
    if enhanced and rng.randrange(100) < 24:
        bonus = _weighted_pick(rng, _BONUS_TABLES[region_key])
        b_kind, b_key, b_low, b_high = bonus
        if allow_special or b_kind not in {"treasure", "scrap"}:
            rewards.append({"kind": b_kind, "key": b_key, "amount": rng.randint(b_low, b_high), "region": region_key})
    return rewards


def _farm_cost(profile: Mapping[str, Any], region_key: str) -> int:
    base = int(FARM_REGIONS[region_key]["stamina"])
    unlocked = set(_dict(dict(profile), "research").get("unlocked", [])) if isinstance(profile, Mapping) else set()
    return max(4, base - (2 if "field_rations" in unlocked else 0))


def _cooldown_remaining(profile: Mapping[str, Any], region_key: str) -> int:
    last = _parse(profile.get("last_at"))
    if last is None:
        return 0
    elapsed = (_now() - last).total_seconds()
    return max(0, int(FARM_REGIONS[region_key]["cooldown"] - elapsed + 0.999))


def _signal_cooldown(signal: Mapping[str, Any]) -> int:
    last = _parse(signal.get("last_at"))
    if last is None:
        return 0
    elapsed = (_now() - last).total_seconds()
    return max(0, int(300 - elapsed + 0.999))


def _encounter_result(
    user: MutableMapping[str, Any], profile: MutableMapping[str, Any], pending: Mapping[str, Any], action: str,
    calculate_user_power: Callable[[Mapping[str, Any]], int],
) -> Tuple[List[Dict[str, Any]], str, int]:
    region_key = _region_key(pending.get("region")) or "market"
    encounter = _encounter_from_pending(pending)
    category = str(encounter.get("category") or "threat")
    actor = str(encounter.get("actor") or encounter.get("title") or "미확인 신호")
    seed = _safe_int(pending.get("seed"), 1, 1)
    rng = random.Random(int(hashlib.sha256(f"{seed}:{encounter.get('key')}:{action}".encode("utf-8")).hexdigest()[:16], 16))
    power = max(1, _safe_int(calculate_user_power(user), 1, 1))
    threshold = {"market": 120, "residential": 380, "freight": 900, "quarantine": 1_900}[region_key]
    hp_loss = 0
    rewards: List[Dict[str, Any]]

    if category == "ally":
        if action == "fight":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=False)
            rewards.append({"kind": "research", "key": "연구 자료", "amount": rng.randint(2, 5), "region": region_key})
            story = f"{actor}와 합류해 경계선을 밀어냈습니다. 임무가 끝난 뒤 회수 물자와 현장 지도를 공정하게 나눴습니다."
        elif action == "rescue":
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            rewards.append({"kind": "material", "key": "보물파편", "amount": rng.randint(1, 2), "region": region_key})
            story = f"{actor}의 부족한 장비와 인력을 지원했습니다. 감사의 뜻으로 보관 중이던 회수품 일부를 받았습니다."
        elif action == "search":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=True)
            story = f"{actor}와 공동 수색망을 펼쳤습니다. 서로 놓쳤던 신호를 보완하며 숨겨진 회수 지점을 발견했습니다."
        else:
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            story = f"{actor}와 거리를 유지한 채 안전 정보만 교환했습니다. 충돌 없이 필요한 물자만 확보했습니다."
    elif category == "rescue":
        if action == "rescue":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=False)
            rewards.append({"kind": "research", "key": "연구 자료", "amount": rng.randint(3, 6), "region": region_key})
            story = f"{actor}을 안전 구역까지 이끌었습니다. 구조 대상은 숨겨 둔 물자와 경로 정보를 넘겨주었습니다."
        elif action == "fight":
            score = power * rng.uniform(0.80, 1.18)
            rewards = _roll_base_rewards(region_key, rng, enhanced=score >= threshold * 0.85, allow_special=score >= threshold)
            if score < threshold * 0.75:
                hp_loss = rng.randint(2, 8)
            story = "무너진 잔해와 위협 요소를 힘으로 밀어내 구조 통로를 만들었습니다." if not hp_loss else "통로를 열었지만 붕괴 충격을 피하지 못했습니다. 구조 신호는 확보했습니다."
        elif action == "search":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=False)
            rewards.append({"kind": "material", "key": "보물파편", "amount": rng.randint(1, 2), "region": region_key})
            story = "주변을 먼저 수색해 2차 붕괴 위험과 안전한 진입로를 찾아냈습니다. 구조와 회수를 함께 마쳤습니다."
        else:
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            story = "안전한 접근로와 구조대가 올 수 있는 좌표를 남기고, 위험 구역 바깥의 물자만 회수했습니다."
    elif category == "hazard":
        if action == "rescue":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=False)
            rewards.append({"kind": "material", "key": "폐허회로", "amount": rng.randint(1, 3), "region": region_key})
            story = "위험 설비를 차단하고 현장을 안정화했습니다. 봉쇄 장치가 풀리며 정비 물자함이 열렸습니다."
        elif action == "search":
            score = power * rng.uniform(0.76, 1.20)
            rewards = _roll_base_rewards(region_key, rng, enhanced=score >= threshold * 0.80, allow_special=score >= threshold)
            if score < threshold * 0.72:
                hp_loss = rng.randint(2, 9)
            story = "원인을 추적해 안전 구간과 회수 지점을 찾아냈습니다." if not hp_loss else "원인을 확인했지만 위험이 번져 급히 철수했습니다."
        elif action == "fight":
            score = power * rng.uniform(0.72, 1.15)
            rewards = _roll_base_rewards(region_key, rng, enhanced=score >= threshold, allow_special=score >= threshold * 1.10)
            if score < threshold:
                hp_loss = rng.randint(4, 12)
            story = "위험 구간을 정면으로 돌파해 봉쇄된 물자를 확보했습니다." if not hp_loss else "강행 돌파 중 충격을 받았지만 손에 잡힌 물자는 지켜냈습니다."
        else:
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            story = "위험 반경을 크게 돌아 안전한 외곽 물자만 확보했습니다."
    elif category == "mystery":
        if action == "search":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=True)
            if rng.randrange(100) < 32:
                rewards.append({"kind": "material", "key": "보물파편", "amount": rng.randint(1, 3), "region": region_key})
            story = "신호와 흔적을 차근히 대조해 숨겨진 회수 구획을 열었습니다."
        elif action == "rescue":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=False)
            rewards.append({"kind": "research", "key": "연구 자료", "amount": rng.randint(2, 5), "region": region_key})
            story = "경보 장치와 잠금 구조를 안전하게 해제했습니다. 기록과 물자를 손상 없이 확보했습니다."
        elif action == "fight":
            score = power * rng.uniform(0.74, 1.20)
            rewards = _roll_base_rewards(region_key, rng, enhanced=score >= threshold * 0.90, allow_special=score >= threshold * 1.08)
            if score < threshold * 0.75:
                hp_loss = rng.randint(3, 10)
            story = "봉인을 강제로 열어 안쪽 물자를 회수했습니다." if not hp_loss else "강제 개방 과정에서 경보가 작동해 일부만 챙기고 빠져나왔습니다."
        else:
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            story = "원격으로 위험 여부를 확인하고 노출된 물자만 안전하게 가져왔습니다."
    elif category == "trade":
        if action in {"fight", "rescue"}:
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=False)
            rewards.append({"kind": "food", "key": "식량", "amount": rng.randint(280, 760), "region": region_key})
            story = f"{actor}의 이동과 거래를 도왔습니다. 상인은 약속대로 정당한 몫을 나누고 안전한 길을 알려주었습니다."
        elif action == "search":
            rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=True)
            story = f"{actor}와 주변 폐허를 함께 확인해 거래품과 숨겨진 회수품을 동시에 확보했습니다."
        else:
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            story = f"{actor}의 신분 표식을 확인한 뒤 필요한 정보만 교환하고 자리를 떠났습니다."
    else:
        if action == "evade":
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            story = "위험 구역을 크게 우회해 확보 가능한 물자만 챙겼습니다."
        elif action == "rescue":
            rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
            rewards.append({"kind": "research", "key": "연구 자료", "amount": rng.randint(2, 5), "region": region_key})
            story = "보호가 필요한 대상을 우선 확보하고 숨겨진 위치 정보를 전달받았습니다."
        elif action == "fight":
            score = power * rng.uniform(0.82, 1.18)
            if score >= threshold:
                rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=True)
                story = "위협을 제압하고 봉쇄된 회수 구역까지 진입했습니다."
            else:
                rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
                hp_loss = rng.randint(4, 13)
                story = "교전 끝에 간신히 빠져나왔습니다. 일부 물자만 회수했습니다."
        else:
            score = power * rng.uniform(0.72, 1.22)
            if score >= threshold * 0.82:
                rewards = _roll_base_rewards(region_key, rng, enhanced=True, allow_special=True)
                if rng.randrange(100) < 35:
                    rewards.append({"kind": "material", "key": "보물파편", "amount": rng.randint(1, 3), "region": region_key})
                story = "위험을 감수해 주변 구획을 더 조사했고 숨겨진 회수 지점을 찾아냈습니다."
            else:
                rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=False)
                hp_loss = rng.randint(2, 9)
                story = "구조물이 무너지기 시작해 탐색을 중단했습니다. 손에 잡힌 물자만 들고 철수했습니다."

    if category in {"ally", "rescue"} and rng.randrange(100) < 18:
        rewards.append({"kind": "material", "key": "보물파편", "amount": 1, "region": region_key})
    if hp_loss:
        user["hp"] = max(1, _safe_int(user.get("hp"), 100, 1) - hp_loss)
    return rewards, story, hp_loss


def _daily_contracts(user_id: Any, profile: MutableMapping[str, Any]) -> List[Dict[str, Any]]:
    today = str(_dict(profile, "contracts").get("date") or _kst_date())
    seed = int(hashlib.sha256(f"contract:{user_id}:{today}".encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    templates = list(_CONTRACT_TEMPLATES)
    rng.shuffle(templates)
    rows: List[Dict[str, Any]] = []
    for index, template in enumerate(templates[:3], start=1):
        amount = rng.randint(*template["amount"])
        food = rng.randint(*template["food"])
        rows.append({
            "id": f"{today.replace('-', '')}-{index}",
            "number": index,
            "title": template["title"],
            "kind": template["kind"],
            "key": template["key"],
            "amount": amount,
            "food": food,
            "research": int(template["research"]),
        })
    return rows


def _complete_ready_research(profile: MutableMapping[str, Any]) -> Optional[str]:
    research = _dict(profile, "research")
    active = research.get("active") if isinstance(research.get("active"), dict) else {}
    if not active:
        return None
    completes_at = _parse(active.get("completes_at"))
    if completes_at is None or _now() < completes_at:
        return None
    key = _research_key(active.get("key"))
    if not key:
        research["active"] = {}
        return None
    if key not in research["unlocked"]:
        research["unlocked"].append(key)
    research["history"].append({"key": key, "completed_at": _iso()})
    research["active"] = {}
    return key


def _find_item(rows: List[Dict[str, Any]], item_id: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    if not rows:
        return None, None
    token = str(item_id or "").strip().upper()
    if not token:
        return 0, rows[0]
    for index, row in enumerate(rows):
        if str(row.get("id") or "").upper() == token:
            return index, row
    return None, None


def _identified_scrap(item: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(item)
    tier = max(0, min(4, _safe_int(item.get("tier"), 0)))
    kind = str(item.get("kind") or "device")
    rng = random.Random(_safe_int(item.get("seed"), 1, 1))
    result["name"] = rng.choice(_SCRAP_NAMES.get(kind, _SCRAP_NAMES["device"]))
    result["identified_at"] = _iso()
    result["repair_cost_food"] = (tier + 1) * rng.randint(380, 620)
    result["repair_cost_scrap"] = max(1, tier + rng.randint(1, 3))
    result["sale_value"] = (tier + 1) * rng.randint(1_400, 2_600)
    result["salvage"] = {
        "고철": max(1, tier + rng.randint(2, 5)),
        "폐허회로": 1 if tier >= 1 else 0,
        "설계도조각": 1 if tier >= 3 and rng.randrange(100) < 40 else 0,
    }
    return result


def register_v770_ruin_farming(
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
    if getattr(bot, "_abaddon_v770_registered", False):
        return

    life_category = next((row for row in guide if row.get("id") == "life"), None)
    if life_category is not None:
        additions = (
            "!파밍 / !파밍지역 / !파밍출발 지역 — 지역 선택형 폐허 회수",
            "!파밍선택 선택지 · !파밍기록 · !파밍인카운트도감",
            "!공방 · !폐품감정 · !폐품분해 · !폐품수리",
            "!전파탐색 · !신호해독 번호 · !주파수기록",
            "!의뢰게시판 · !계약수락 번호 · !납품 · !계약현황",
            "!연구소 · !연구시작 기술 · !연구진행 · !설계도",
        )
        existing = "\n".join(map(str, life_category.get("commands", [])))
        for row in additions:
            token = row.split(" — ", 1)[0].split(" · ", 1)[0]
            if token not in existing:
                life_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    server_category = next((row for row in guide if row.get("id") == "server"), None)
    if server_category is not None:
        line = "!770안정화검수 — 파밍·인카운트·공방·신호·계약·연구 저장 구조 읽기 전용 검사"
        if line.split(" — ", 1)[0] not in "\n".join(map(str, server_category.get("commands", []))):
            server_category.setdefault("commands", []).append(line)

    async def require_user(ctx: commands.Context) -> Tuple[Optional[MutableMapping[str, Any]], Optional[MutableMapping[str, Any]]]:
        if not await check_registered(ctx):
            return None, None
        user = get_user(ctx.author.id)
        if not isinstance(user, dict):
            await ctx.send("⚠️ 생존자 데이터를 불러오지 못했습니다. 잠시 뒤 다시 시도하세요.")
            return None, None
        return user, ensure_v770_profile(user)

    async def show_farming_route(ctx: commands.Context, region_key: str, *, encounter: bool) -> None:
        region = FARM_REGIONS[region_key]
        danger = {
            "market": "🟢 경계 안정", "residential": "🟡 잔해 위험",
            "freight": "🟠 신호 불안정", "quarantine": "🔴 오염 경보",
        }[region_key]
        atmosphere = {
            "market": ("🛒", "깨진 진열대 사이로 이동 경로를 확보합니다."),
            "residential": ("🏚️", "무너진 벽과 흔들리는 계단을 피해 진입합니다."),
            "freight": ("🚇", "멈춘 화물칸 사이에서 신호를 추적합니다."),
            "quarantine": ("☣️", "오염 수치를 확인하며 차폐 통로를 통과합니다."),
        }[region_key]
        stage_rows = [
            ("🚪 출발 신호", f"{region['emoji']} **{region['name']}** 작전을 개시합니다.", 0, discord.Colour.dark_teal()),
            ("👣 폐허 진입", atmosphere[1], 1, discord.Colour.dark_teal()),
            ("📡 전방 스캔", f"{danger} · 생체·물자·위험 신호를 동시에 분석합니다.", 2, discord.Colour.blurple()),
            (("🚨 접촉 경보" if encounter else "✨ 회수 신호"), (
                "복수의 움직임이 포착됐습니다. 현장 판단이 필요합니다."
                if encounter else "회수 가능한 물자 반응이 선명해졌습니다."
            ), 3, discord.Colour.orange() if encounter else discord.Colour.green()),
            (("⚠️ 판단 지점" if encounter else "📦 회수 작업"), (
                "접촉 대상과 주변 환경을 확인하고 선택지를 준비합니다."
                if encounter else "물자를 포장하고 안전한 복귀 경로를 고정합니다."
            ), 3 if encounter else 4, discord.Colour.red() if encounter else discord.Colour.dark_green()),
        ]
        message = None
        for index, (title, description, position, colour) in enumerate(stage_rows):
            pulse = ("▰" * (index + 1)) + ("▱" * (len(stage_rows) - index - 1))
            embed = discord.Embed(
                title=f"{region['emoji']} 파밍 작전 진행 · {title}",
                description=f"{description}\n\n{_route_line(position, encounter=encounter)}\n`{pulse}`",
                colour=colour,
            )
            embed.add_field(name="현장 경계", value=danger, inline=True)
            embed.add_field(name="신호 상태", value="🚨 인카운트 확인" if encounter and index >= 3 else "📡 탐색 중", inline=True)
            embed.set_footer(text="이모지 프레임을 갱신해 이동 중인 것처럼 연출합니다")
            try:
                if message is None:
                    message = await ctx.send(embed=embed)
                else:
                    await message.edit(embed=embed)
            except (discord.HTTPException, discord.Forbidden, AttributeError, TypeError):
                return
            if index < len(stage_rows) - 1:
                await asyncio.sleep(0.55)

    async def send_encounter(ctx: commands.Context, pending: Mapping[str, Any]) -> None:
        region_key = _region_key(pending.get("region")) or "market"
        region = FARM_REGIONS[region_key]
        encounter = _encounter_from_pending(pending)
        category = str(encounter.get("category") or "threat")
        expires_at = _parse(pending.get("expires_at")) or (_now() + timedelta(seconds=ENCOUNTER_TTL_SECONDS))
        choices = []
        for action in ("fight", "evade", "rescue", "search"):
            label, emoji, _style = _encounter_action(category, action)
            choices.append(f"{emoji} **{label}**")
        embed = discord.Embed(
            title=f"{encounter.get('emoji','⚠️')} 랜덤 인카운트 · {encounter['title']}",
            description=f"{encounter['description']}\n\n`📡 신호 분석 → 👁️ 대상 식별 → ⚡ 선택 대기`",
            colour=_category_colour(category),
        )
        embed.add_field(name="신호 분류", value=_ENCOUNTER_CATEGORY_LABELS.get(category, "⚠️ 미확인"), inline=True)
        embed.add_field(name="접촉 대상", value=f"{encounter.get('emoji','')} **{encounter.get('actor','미확인')}**", inline=True)
        embed.add_field(name="진행 루트", value=_route_line(3, encounter=True), inline=False)
        embed.add_field(name="현재 지역", value=f"**{region['name']}** · 위험도 {region['danger']}", inline=False)
        embed.add_field(
            name="현장 선택",
            value=" · ".join(choices) + "\n버튼이 사라져도 `!파밍선택 선택지`로 이어갈 수 있습니다.",
            inline=False,
        )
        embed.add_field(name="현장 신호 유지", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
        embed.set_footer(text=f"ABADDON v{VERSION} · 같은 인카운트는 한 번만 정산됩니다")
        await ctx.send(embed=embed, view=EncounterView(ctx.author.id, encounter))

    async def settle_expired(user: MutableMapping[str, Any], profile: MutableMapping[str, Any], actor_id: Any) -> Optional[str]:
        pending = profile.get("pending_encounter") if isinstance(profile.get("pending_encounter"), dict) else {}
        if not pending:
            return None
        expires_at = _parse(pending.get("expires_at"))
        if not expires_at or _now() < expires_at:
            return None
        rewards, story, hp_loss = _encounter_result(user, profile, pending, "evade", calculate_user_power)
        rng = random.Random(_safe_int(pending.get("seed"), 1, 1) ^ 0x5A17)
        lines = _grant_rewards(user, profile, rewards, rng)
        region_key = _region_key(pending.get("region")) or "market"
        encounter = _encounter_from_pending(pending)
        encounter_key = str(encounter.get("key") or "unknown")
        category = str(encounter.get("category") or "threat")
        profile["history"].append({
            "id": str(pending.get("id") or ""), "region": region_key, "action": "evade",
            "encounter_key": encounter_key, "category": category,
            "auto": True, "rewards": list(lines), "resolved_at": _iso(), "hp_loss": hp_loss,
        })
        profile["stats"]["evade"] += 1
        profile["stats"]["rescue_event" if category == "rescue" else category] += 1
        if encounter_key not in profile["encounter_discovery"]:
            profile["encounter_discovery"].append(encounter_key)
        profile["recent_encounters"] = (profile["recent_encounters"] + [encounter_key])[-4:]
        profile["pending_encounter"] = {}
        save_data()
        return f"⌛ 이전 인카운트 신호가 종료되어 안전 회피로 자동 정산했습니다. {' · '.join(lines)}"

    async def resolve_encounter(ctx: commands.Context, raw_action: str) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        action = _action_key(raw_action)
        if not action:
            await ctx.send("⚠️ 버튼에 표시된 행동을 고르거나 `전투 / 회피 / 구조 / 추가탐색 / 합류 / 지원 / 공동수색` 중 하나를 입력하세요.")
            return
        async with _user_lock(bot, ctx.author.id):
            profile = ensure_v770_profile(user)
            auto_text = await settle_expired(user, profile, ctx.author.id)
            if auto_text:
                await ctx.send(auto_text)
                return
            pending = profile.get("pending_encounter") if isinstance(profile.get("pending_encounter"), dict) else {}
            if not pending:
                await ctx.send("📭 진행 중인 파밍 인카운트가 없습니다. `!파밍`에서 지역을 선택하세요.")
                return
            rewards, story, hp_loss = _encounter_result(user, profile, pending, action, calculate_user_power)
            seed = _safe_int(pending.get("seed"), 1, 1)
            rng = random.Random(int(hashlib.sha256(f"grant:{seed}:{action}".encode("utf-8")).hexdigest()[:16], 16))
            lines = _grant_rewards(user, profile, rewards, rng)
            region_key = _region_key(pending.get("region")) or "market"
            hook_note = ""
            disaster_hook = getattr(bot, "v780_on_farming_result", None)
            if callable(disaster_hook):
                hook_result = disaster_hook(
                    int(ctx.guild.id) if ctx.guild else 0, ctx.author.id, user, profile,
                    region_key, action, tuple(lines),
                )
                if asyncio.iscoroutine(hook_result):
                    hook_result = await hook_result
                hook_note = str(hook_result or "")
            encounter = _encounter_from_pending(pending)
            encounter_key = str(encounter.get("key") or "unknown")
            category = str(encounter.get("category") or "threat")
            faction_hook = getattr(bot, "v900_on_encounter", None)
            if callable(faction_hook):
                faction_note = faction_hook(ctx.author.id, user, encounter_key, category, action)
                if asyncio.iscoroutine(faction_note):
                    faction_note = await faction_note
                if faction_note:
                    hook_note = (hook_note + "\n" if hook_note else "") + str(faction_note)
            profile["history"].append({
                "id": str(pending.get("id") or ""), "region": region_key, "action": action,
                "encounter_key": encounter_key, "category": category,
                "auto": False, "rewards": list(lines), "resolved_at": _iso(), "hp_loss": hp_loss,
            })
            profile["stats"][action] += 1
            profile["stats"]["rescue_event" if category == "rescue" else category] += 1
            if encounter_key not in profile["encounter_discovery"]:
                profile["encounter_discovery"].append(encounter_key)
            profile["recent_encounters"] = (profile["recent_encounters"] + [encounter_key])[-4:]
            profile["pending_encounter"] = {}
            add_season_points(user, 2 if action in {"fight", "search"} else 1)
            if profile["stats"]["encounters"] >= 12:
                add_title(user, "폐허의 현장 판단관")
            ally_discoveries = [key for key in profile["encounter_discovery"] if _ENCOUNTER_BY_KEY.get(key, {}).get("category") == "ally"]
            if len(ally_discoveries) >= 5:
                add_title(user, "폐허의 신뢰받는 동료")
            save_data()

        encounter = _encounter_from_pending(pending)
        category = str(encounter.get("category") or "threat")
        action_label, action_emoji, _style = _encounter_action(category, action)
        route_message = None
        frames = (
            ("⚡ 선택 실행", 3, "현장 판단을 실행합니다."),
            ("💨 행동 진행", 4, f"{encounter.get('actor','접촉 대상')}과의 상황을 정리합니다."),
            ("📦 물자 확보", 4, "회수 가능한 물자를 확인하고 중복 정산을 잠급니다."),
        )
        for index, (phase, position, detail) in enumerate(frames):
            frame = discord.Embed(
                title=f"{action_emoji} {phase}",
                description=f"{detail}\n\n{_route_line(position, encounter=True)}",
                colour=_category_colour(category),
            )
            frame.set_footer(text="현장 결과 계산 중" + "." * (index + 1))
            try:
                if route_message is None:
                    route_message = await ctx.send(embed=frame)
                else:
                    await route_message.edit(embed=frame)
            except (discord.HTTPException, discord.Forbidden, AttributeError, TypeError):
                route_message = None
                break
            await asyncio.sleep(0.45)

        embed = discord.Embed(title=f"{action_emoji} {action_label} · 인카운트 정산", description=story, colour=_category_colour(category))
        embed.add_field(name="접촉 대상", value=f"{encounter.get('emoji','')} {encounter.get('actor','미확인')}", inline=True)
        embed.add_field(name="신호 분류", value=_ENCOUNTER_CATEGORY_LABELS.get(category, "⚠️ 미확인"), inline=True)
        embed.add_field(name="진행 루트", value=_route_line(5, encounter=True, result=True), inline=False)
        embed.add_field(name="회수 결과", value="\n".join(f"• {line}" for line in lines) or "• 확보한 물자 없음", inline=False)
        if hook_note:
            embed.add_field(name="서버 공동 대응", value=hook_note, inline=False)
        if hp_loss:
            embed.add_field(name="부상", value=f"HP -{hp_loss} · 현재 HP {max(1, _safe_int(user.get('hp'), 1))}", inline=False)
        embed.set_footer(text="같은 인카운트는 한 번만 정산됩니다")
        if route_message is not None:
            try:
                await route_message.edit(embed=embed)
            except (discord.HTTPException, discord.Forbidden, AttributeError):
                await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    async def start_farming(ctx: commands.Context, region_text: str) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        region_key = _region_key(region_text)
        if not region_key:
            await ctx.send("⚠️ 지역은 `마트 / 주거구역 / 화물역 / 격리구역` 중 하나를 선택하세요.")
            return
        region = FARM_REGIONS[region_key]
        async with _user_lock(bot, ctx.author.id):
            profile = ensure_v770_profile(user)
            auto_text = await settle_expired(user, profile, ctx.author.id)
            if auto_text:
                await ctx.send(auto_text)
            if profile.get("pending_encounter"):
                await ctx.send("⚠️ 진행 중인 파밍 인카운트가 있습니다. 먼저 `!파밍선택`으로 결정을 내려주세요.")
                return
            level = max(1, _safe_int(user.get("level"), 1, 1))
            if level < int(region["level"]):
                await ctx.send(f"🔒 **{region['name']}** 진입에는 레벨 **{region['level']}**이 필요합니다. 현재 레벨 {level}")
                return
            if profile["attempts"] >= FARM_DAILY_LIMIT:
                await ctx.send(f"🛑 오늘의 파밍 기록이 가득 찼습니다. 자정(KST)에 다시 현장 신호를 받을 수 있습니다.")
                return
            remaining = _cooldown_remaining(profile, region_key)
            if remaining > 0:
                await ctx.send(f"⏳ 장비 정리와 이동 경로 재설정이 필요합니다. 다음 출발까지 **{_format_seconds(remaining)}**")
                return
            cost = _farm_cost(profile, region_key)
            stamina = max(0, _safe_int(user.get("stamina"), 100, 0))
            if stamina < cost:
                await ctx.send(f"⚠️ 스태미나가 부족합니다. 필요 **{cost}** · 현재 **{stamina}** · `!휴식`으로 회복하세요.")
                return
            user["stamina"] = stamina - cost
            profile["attempts"] += 1
            profile["last_at"] = _iso()
            profile["stats"]["runs"] += 1
            seed = secrets.randbits(63)
            rng = random.Random(seed)
            encounter = rng.randrange(100) < {"market": 24, "residential": 31, "freight": 38, "quarantine": 46}[region_key]
            if encounter:
                now = _now()
                encounter_row = _choose_encounter(profile, region_key, rng)
                encounter_key = str(encounter_row.get("key") or "infected")
                pending = {
                    "id": f"FE-{secrets.token_hex(4).upper()}",
                    "region": region_key,
                    "seed": seed,
                    "encounter_key": encounter_key,
                    "encounter_index": next((idx for idx, row in enumerate(_ENCOUNTERS) if row.get("key") == encounter_key), 0),
                    "created_at": _iso(now),
                    "expires_at": _iso(now + timedelta(seconds=ENCOUNTER_TTL_SECONDS)),
                    "stamina_cost": cost,
                }
                profile["pending_encounter"] = pending
                profile["stats"]["encounters"] += 1
                save_data()
            else:
                rewards = _roll_base_rewards(region_key, rng, enhanced=False, allow_special=True)
                if rng.randrange(100) < 18:
                    rewards.append({"kind": "research", "key": "연구 자료", "amount": rng.randint(1, 3), "region": region_key})
                lines = _grant_rewards(user, profile, rewards, rng)
                hook_note = ""
                disaster_hook = getattr(bot, "v780_on_farming_result", None)
                if callable(disaster_hook):
                    hook_result = disaster_hook(
                        int(ctx.guild.id) if ctx.guild else 0, ctx.author.id, user, profile,
                        region_key, "normal", tuple(lines),
                    )
                    if asyncio.iscoroutine(hook_result):
                        hook_result = await hook_result
                    hook_note = str(hook_result or "")
                profile["history"].append({
                    "id": f"FR-{secrets.token_hex(4).upper()}", "region": region_key, "action": "normal",
                    "auto": False, "rewards": list(lines), "resolved_at": _iso(), "hp_loss": 0,
                })
                add_season_points(user, 1)
                save_data()
        await show_farming_route(ctx, region_key, encounter=encounter)
        if encounter:
            await send_encounter(ctx, pending)
            return
        embed = discord.Embed(
            title=f"{region['emoji']} {region['name']} 파밍 완료",
            description=(
                "✨ 회수 신호를 따라 물자를 확보하고 복귀 지점까지 안전하게 돌아왔습니다.\n\n"
                "`🚪 출발 → 🗺️ 이동 → 📡 발견 → 📦 회수 → 🏠 복귀`"
            ),
            colour=discord.Colour.dark_green(),
        )
        embed.add_field(name="✨ 발견·회수 결과", value="\n".join(f"• {line}" for line in lines) or "• 확보한 물자 없음", inline=False)
        if hook_note:
            embed.add_field(name="🚨 서버 공동 대응", value=hook_note, inline=False)
        embed.add_field(name="오늘 기록", value=f"{profile['attempts']}/{FARM_DAILY_LIMIT}", inline=True)
        embed.add_field(name="남은 스태미나", value=str(max(0, _safe_int(user.get("stamina"), 0))), inline=True)
        embed.set_footer(text="보물과 폐품은 각각 !보물감정 · !공방에서 이어서 처리합니다")
        await ctx.send(embed=embed)

    class ProxyContext:
        def __init__(self, interaction: discord.Interaction) -> None:
            self.author = interaction.user
            self.guild = interaction.guild
            self.channel = interaction.channel
            self._interaction = interaction

        async def send(self, *args: Any, **kwargs: Any) -> discord.Message:
            kwargs.setdefault("wait", True)
            return await self._interaction.followup.send(*args, **kwargs)

    class FarmRegionSelect(discord.ui.Select):
        def __init__(self, owner_id: int) -> None:
            self.owner_id = owner_id
            options = [
                discord.SelectOption(
                    label=str(region["name"]), value=key,
                    description=f"레벨 {region['level']} · 위험도 {region['danger']} · {region['focus']}"[:100],
                    emoji=str(region["emoji"]),
                )
                for key, region in FARM_REGIONS.items()
            ]
            super().__init__(placeholder="파밍 지역을 선택하세요", min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("이 파밍 메뉴는 명령을 실행한 사용자만 사용할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.defer()
            await start_farming(ProxyContext(interaction), self.values[0])
            try:
                await interaction.message.edit(view=None)
            except (discord.HTTPException, discord.Forbidden, AttributeError):
                pass

    class FarmRegionView(discord.ui.View):
        def __init__(self, owner_id: int) -> None:
            super().__init__(timeout=300)
            self.add_item(FarmRegionSelect(owner_id))

    class EncounterView(discord.ui.View):
        def __init__(self, owner_id: int, encounter: Mapping[str, Any]) -> None:
            super().__init__(timeout=ENCOUNTER_TTL_SECONDS)
            self.owner_id = owner_id
            category = str(encounter.get("category") or "threat")
            for child, action in zip(self.children, ("fight", "evade", "rescue", "search")):
                label, emoji, style = _encounter_action(category, action)
                child.label = label
                child.emoji = emoji
                child.style = style

        async def _choose(self, interaction: discord.Interaction, action: str) -> None:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("이 인카운트는 파밍을 시작한 사용자만 선택할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.defer()
            await resolve_encounter(ProxyContext(interaction), action)
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except (discord.HTTPException, discord.Forbidden, AttributeError):
                pass

        @discord.ui.button(label="행동 1", emoji="⚔️", style=discord.ButtonStyle.danger)
        async def fight(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._choose(interaction, "fight")

        @discord.ui.button(label="행동 2", emoji="🫥", style=discord.ButtonStyle.secondary)
        async def evade(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._choose(interaction, "evade")

        @discord.ui.button(label="행동 3", emoji="🩹", style=discord.ButtonStyle.success)
        async def rescue(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._choose(interaction, "rescue")

        @discord.ui.button(label="행동 4", emoji="🔎", style=discord.ButtonStyle.primary)
        async def search(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._choose(interaction, "search")

    class SignalView(discord.ui.View):
        def __init__(self, owner_id: int) -> None:
            super().__init__(timeout=300)
            self.owner_id = owner_id

        async def _answer(self, interaction: discord.Interaction, answer: int) -> None:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("이 신호는 탐색을 시작한 사용자만 해독할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.defer()
            await signal_decode.callback(ProxyContext(interaction), answer)
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except (discord.HTTPException, discord.Forbidden, AttributeError):
                pass

        @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
        async def one(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._answer(interaction, 1)

        @discord.ui.button(label="2", style=discord.ButtonStyle.secondary)
        async def two(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._answer(interaction, 2)

        @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
        async def three(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._answer(interaction, 3)

        @discord.ui.button(label="4", style=discord.ButtonStyle.secondary)
        async def four(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
            await self._answer(interaction, 4)

    @bot.command(name="파밍", aliases=["폐허파밍", "파밍메뉴"], help="지역 선택형 폐허 파밍 메뉴를 엽니다.")
    async def farming_menu(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            auto_text = await settle_expired(user, profile, ctx.author.id)
        if auto_text:
            await ctx.send(auto_text)
        embed = discord.Embed(
            title="🧭 폐허 파밍 작전판",
            description="지역마다 회수 물자와 위험도가 다릅니다. 현장에서는 예기치 않은 인카운트가 발생할 수 있습니다.",
            colour=discord.Colour.dark_teal(),
        )
        for key, region in FARM_REGIONS.items():
            cost = _farm_cost(profile, key)
            embed.add_field(
                name=f"{region['emoji']} {region['name']}",
                value=f"레벨 {region['level']} · 위험도 {region['danger']} · 스태미나 {cost}\n{region['focus']}",
                inline=False,
            )
        pending = profile.get("pending_encounter") if isinstance(profile.get("pending_encounter"), dict) else {}
        embed.add_field(name="오늘 파밍", value=f"{profile['attempts']}/{FARM_DAILY_LIMIT}", inline=True)
        embed.add_field(name="진행 중 인카운트", value="있음 · `!파밍선택` 필요" if pending else "없음", inline=True)
        embed.set_footer(text="드롭다운 또는 !파밍출발 지역 · 현장 결과는 선택 완료 시 한 번만 정산됩니다")
        await ctx.send(embed=embed, view=FarmRegionView(ctx.author.id))

    @bot.command(name="파밍지역", aliases=["파밍목록", "파밍지역목록"], help="파밍 가능한 지역을 확인합니다.")
    async def farming_regions(ctx: commands.Context) -> None:
        await farming_menu.callback(ctx)

    @bot.command(name="파밍출발", aliases=["파밍시작", "폐허수색"], help="선택한 지역으로 파밍을 출발합니다.")
    async def farming_start(ctx: commands.Context, *, 지역: str = "") -> None:
        await start_farming(ctx, 지역)

    @bot.command(name="파밍선택", aliases=["인카운트선택", "현장선택"], help="파밍 인카운트의 행동을 선택합니다.")
    async def farming_choice(ctx: commands.Context, *, 선택: str = "") -> None:
        await resolve_encounter(ctx, 선택)

    @bot.command(name="파밍기록", aliases=["파밍상태", "파밍로그"], help="파밍 기록과 진행 중 인카운트를 확인합니다.")
    async def farming_history(ctx: commands.Context, 페이지: int = 1) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            auto_text = await settle_expired(user, profile, ctx.author.id)
        if auto_text:
            await ctx.send(auto_text)
        rows = list(reversed(profile.get("history", [])))
        page_size = 6
        pages = max(1, (len(rows) + page_size - 1) // page_size)
        page = max(1, min(pages, _safe_int(페이지, 1, 1)))
        embed = discord.Embed(title=f"📜 {ctx.author.display_name}의 파밍 기록", colour=discord.Colour.blurple())
        if rows:
            for row in rows[(page - 1) * page_size: page * page_size]:
                region_key = _region_key(row.get("region")) or "market"
                region = FARM_REGIONS[region_key]
                action = str(row.get("action") or "normal")
                action_label = "일반 회수" if action == "normal" else ACTION_LABELS.get(action, action)
                rewards = " · ".join(map(str, row.get("rewards", []))) or "기록 없음"
                embed.add_field(name=f"{region['emoji']} {region['name']} · {action_label}", value=rewards[:1024], inline=False)
        else:
            embed.description = "아직 완료된 파밍 기록이 없습니다."
        embed.add_field(name="오늘 횟수", value=f"{profile['attempts']}/{FARM_DAILY_LIMIT}", inline=True)
        embed.add_field(name="랜덤 인카운트", value=str(profile["stats"]["encounters"]), inline=True)
        embed.set_footer(text=f"{page}/{pages} 페이지 · 기록은 자동 삭제하지 않습니다")
        await ctx.send(embed=embed)

    @bot.command(name="공방", aliases=["폐품공방", "복구공방"], help="미감정·감정 완료 폐품과 연구 상태를 확인합니다.")
    async def workshop(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        _complete_ready_research(profile)
        work = _dict(profile, "workshop")
        embed = discord.Embed(title="🔧 폐허 복구 공방", description="파밍에서 회수한 폐품을 감정한 뒤 분해하거나 수리할 수 있습니다.", colour=discord.Colour.gold())
        unidentified = work.get("unidentified", [])
        identified = work.get("identified", [])
        embed.add_field(name="미감정 폐품", value=f"{len(unidentified)}개\n" + ("\n".join(f"• `{row.get('id')}`" for row in unidentified[:5]) or "없음"), inline=False)
        embed.add_field(name="감정 완료 폐품", value=f"{len(identified)}개\n" + ("\n".join(f"• `{row.get('id')}` · {row.get('name')}" for row in identified[:5]) or "없음"), inline=False)
        embed.add_field(name="처리 명령", value="`!폐품감정 [ID]` · `!폐품분해 [ID]` · `!폐품수리 [ID]`", inline=False)
        embed.set_footer(text="장비 수리와 별개의 생활 공방입니다. 플레이어 장비는 변경하지 않습니다")
        await ctx.send(embed=embed)

    @bot.command(name="폐품감정", aliases=["폐품확인", "폐품분석"], help="미감정 폐품 하나를 분석합니다.")
    async def scrap_identify(ctx: commands.Context, 폐품ID: str = "") -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            work = _dict(profile, "workshop")
            rows = work.setdefault("unidentified", [])
            index, item = _find_item(rows, 폐품ID)
            if item is None or index is None:
                await ctx.send("📭 감정할 미감정 폐품이 없습니다. `!파밍`에서 폐품을 찾아보세요.")
                return
            rows.pop(index)
            identified = _identified_scrap(item)
            work.setdefault("identified", []).append(identified)
            work.setdefault("history", []).append({"action": "identify", "id": identified["id"], "at": _iso()})
            save_data()
        await ctx.send(
            f"🔎 폐품 분석 완료 · `{identified['id']}` **{identified['name']}**\n"
            f"분해하면 재료를 회수하고, 수리하면 완제품으로 복구를 시도합니다."
        )

    @bot.command(name="폐품분해", aliases=["폐품해체", "폐품재활용"], help="감정 완료 폐품을 분해해 재료를 회수합니다.")
    async def scrap_dismantle(ctx: commands.Context, 폐품ID: str = "") -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            work = _dict(profile, "workshop")
            rows = work.setdefault("identified", [])
            index, item = _find_item(rows, 폐품ID)
            if item is None or index is None:
                await ctx.send("📭 분해할 감정 완료 폐품이 없습니다. 먼저 `!폐품감정`을 사용하세요.")
                return
            rows.pop(index)
            salvage = dict(item.get("salvage") or {})
            unlocked = set(_dict(profile, "research").get("unlocked", []))
            if "salvage" in unlocked:
                salvage["고철"] = max(0, _safe_int(salvage.get("고철"), 0)) + 1
            resources = _dict(user, "resources")
            materials = _dict(user, "materials")
            lines: List[str] = []
            for key, amount_raw in salvage.items():
                amount = max(0, _safe_int(amount_raw, 0))
                if not amount:
                    continue
                if key in {"고철", "광석", "나무", "약초", "물고기"}:
                    resources[key] = max(0, _safe_int(resources.get(key), 0)) + amount
                    lines.append(_public_reward_label("resource", key, amount))
                else:
                    materials[key] = max(0, _safe_int(materials.get(key), 0)) + amount
                    lines.append(_public_reward_label("material", key, amount))
            work.setdefault("history", []).append({"action": "dismantle", "id": item.get("id"), "at": _iso(), "rewards": lines})
            save_data()
        await ctx.send(f"♻️ **{item.get('name')}** 분해 완료\n" + "\n".join(f"• {line}" for line in lines))

    @bot.command(name="폐품수리", aliases=["폐품복구", "공방수리"], help="감정 완료 폐품을 자원으로 수리합니다.")
    async def scrap_repair(ctx: commands.Context, 폐품ID: str = "") -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            work = _dict(profile, "workshop")
            rows = work.setdefault("identified", [])
            index, item = _find_item(rows, 폐품ID)
            if item is None or index is None:
                await ctx.send("📭 수리할 감정 완료 폐품이 없습니다. 먼저 `!폐품감정`을 사용하세요.")
                return
            food_cost = max(1, _safe_int(item.get("repair_cost_food"), 1, 1))
            scrap_cost = max(1, _safe_int(item.get("repair_cost_scrap"), 1, 1))
            resources = _dict(user, "resources")
            if _safe_int(user.get("balance"), 0) < food_cost or _safe_int(resources.get("고철"), 0) < scrap_cost:
                await ctx.send(f"⚠️ 수리 재료 부족 · 식량 {food_cost:,} · 고철 {scrap_cost} 필요")
                return
            rows.pop(index)
            user["balance"] = _safe_int(user.get("balance"), 0) - food_cost
            resources["고철"] = _safe_int(resources.get("고철"), 0) - scrap_cost
            tier = max(0, min(4, _safe_int(item.get("tier"), 0)))
            rng = random.Random(_safe_int(item.get("seed"), 1, 1) ^ 0x77A0)
            unlocked = set(_dict(profile, "research").get("unlocked", []))
            threshold = 56 + tier * 5 + (8 if "salvage" in unlocked else 0)
            success = rng.randrange(100) < threshold
            lines: List[str] = []
            if success:
                payout = max(1, _safe_int(item.get("sale_value"), 1, 1))
                user["balance"] = _safe_int(user.get("balance"), 0) + payout
                _dict(user, "stats")["earned"] = _safe_int(_dict(user, "stats").get("earned"), 0) + payout
                lines.append(f"💰 복구품 매입 +{payout:,} 식량")
                if tier >= 3:
                    research = _dict(profile, "research")
                    research["points"] = _safe_int(research.get("points"), 0) + 2
                    lines.append("📡 연구 자료 +2")
            else:
                salvage = dict(item.get("salvage") or {})
                amount = max(1, _safe_int(salvage.get("고철"), 1) // 2 + (1 if "salvage" in unlocked else 0))
                resources["고철"] = _safe_int(resources.get("고철"), 0) + amount
                lines.append(f"🔩 회수 고철 +{amount}")
            work.setdefault("history", []).append({"action": "repair", "id": item.get("id"), "at": _iso(), "success": success, "rewards": lines})
            save_data()
        await ctx.send(
            f"{'✅' if success else '⚠️'} **{item.get('name')}** 수리 {'완료' if success else '중단'}\n"
            f"사용: 식량 {food_cost:,} · 고철 {scrap_cost}\n" + "\n".join(f"• {line}" for line in lines)
        )

    @bot.command(name="전파탐색", aliases=["신호탐색", "주파수탐색"], help="해독 가능한 폐허 신호를 탐색합니다.")
    async def signal_search(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            signal = _dict(profile, "signal")
            if signal.get("pending"):
                await ctx.send("⚠️ 아직 해독하지 않은 신호가 있습니다. `!신호해독 번호`를 사용하세요.")
                return
            if signal["attempts"] >= SIGNAL_DAILY_LIMIT:
                await ctx.send("🛑 오늘 확보 가능한 주파수 기록을 모두 분석했습니다.")
                return
            remaining = _signal_cooldown(signal)
            if remaining > 0:
                await ctx.send(f"📻 수신기를 재조정하고 있습니다. 다음 탐색까지 **{_format_seconds(remaining)}**")
                return
            seed = secrets.randbits(63)
            rng = random.Random(seed)
            puzzle_index = rng.randrange(len(_SIGNAL_PUZZLES))
            signal["attempts"] += 1
            signal["last_at"] = _iso()
            signal["pending"] = {
                "id": f"SG-{secrets.token_hex(4).upper()}", "puzzle": puzzle_index,
                "answer": int(_SIGNAL_PUZZLES[puzzle_index]["answer"]), "seed": seed, "created_at": _iso(),
            }
            save_data()
        puzzle = _SIGNAL_PUZZLES[puzzle_index]
        options = "\n".join(f"`{i}` {value}" for i, value in enumerate(puzzle["options"], start=1))
        embed = discord.Embed(title="📡 폐허 전파 해독", description=str(puzzle["question"]), colour=discord.Colour.purple())
        embed.add_field(name="수신 후보", value=options, inline=False)
        embed.add_field(name="입력", value="버튼 또는 `!신호해독 번호`", inline=False)
        await ctx.send(embed=embed, view=SignalView(ctx.author.id))

    @bot.command(name="신호해독", aliases=["전파해독", "주파수해독"], help="탐색한 신호의 정답 번호를 제출합니다.")
    async def signal_decode(ctx: commands.Context, 번호: int = 0) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        if 번호 not in {1, 2, 3, 4}:
            await ctx.send("⚠️ 답은 1~4 중 하나를 입력하세요.")
            return
        async with _user_lock(bot, ctx.author.id):
            signal = _dict(profile, "signal")
            pending = signal.get("pending") if isinstance(signal.get("pending"), dict) else {}
            if not pending:
                await ctx.send("📭 해독 대기 중인 신호가 없습니다. `!전파탐색`을 사용하세요.")
                return
            correct = 번호 == _safe_int(pending.get("answer"), 0)
            lines: List[str] = []
            if correct:
                rng = random.Random(_safe_int(pending.get("seed"), 1, 1) ^ 0x51A1)
                research = _dict(profile, "research")
                unlocked = set(research.get("unlocked", []))
                points = rng.randint(3, 6) + (2 if "signal_filter" in unlocked else 0)
                research["points"] = _safe_int(research.get("points"), 0) + points
                lines.append(f"📡 연구 자료 +{points}")
                materials = _dict(user, "materials")
                if rng.randrange(100) < 34:
                    key = rng.choice(("보물파편", "폐허회로", "설계도조각"))
                    amount = 1 if key != "보물파편" else rng.randint(1, 2)
                    materials[key] = _safe_int(materials.get(key), 0) + amount
                    lines.append(_public_reward_label("material", key, amount))
                add_season_points(user, 2)
                profile["stats"]["signals"] += 1
            signal.setdefault("history", []).append({"id": pending.get("id"), "correct": correct, "at": _iso()})
            signal["pending"] = {}
            save_data()
        await ctx.send(("✅ 신호 해독 성공\n" + "\n".join(f"• {line}" for line in lines)) if correct else "📵 신호 해독에 실패했습니다. 기록을 정리하고 수신기를 재조정합니다.")

    @bot.command(name="주파수기록", aliases=["전파기록", "신호기록"], help="전파 해독 기록과 연구 자료를 확인합니다.")
    async def signal_history(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        signal = _dict(profile, "signal")
        history = signal.get("history", [])
        success = sum(1 for row in history if isinstance(row, dict) and row.get("correct"))
        embed = discord.Embed(title="📻 주파수 기록", colour=discord.Colour.purple())
        embed.add_field(name="오늘 탐색", value=f"{signal['attempts']}/{SIGNAL_DAILY_LIMIT}", inline=True)
        embed.add_field(name="누적 해독", value=f"{success}/{len(history)}", inline=True)
        embed.add_field(name="연구 자료", value=str(_safe_int(_dict(profile, "research").get("points"), 0)), inline=True)
        embed.add_field(name="대기 신호", value="있음" if signal.get("pending") else "없음", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="의뢰게시판", aliases=["납품게시판", "계약게시판"], help="오늘의 자원 납품 계약을 확인합니다.")
    async def contract_board(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        contracts = _dict(profile, "contracts")
        rows = _daily_contracts(ctx.author.id, profile)
        completed = set(contracts.get("completed", []))
        embed = discord.Embed(title="📦 오늘의 생존 납품 계약", description="자원 시장과 별개인 하루 한정 주문입니다.", colour=discord.Colour.blue())
        for row in rows:
            status = "✅ 완료" if row["id"] in completed else ("📌 수락 중" if contracts.get("accepted") == row["id"] else "대기")
            embed.add_field(
                name=f"{row['number']}. {row['title']} · {status}",
                value=f"요청: {row['key']} {row['amount']}개\n정산: 식량 {row['food']:,} · 연구 자료 {row['research']}",
                inline=False,
            )
        embed.set_footer(text="!계약수락 번호 → !납품 · 완료 계약은 당일 다시 제출할 수 없습니다")
        await ctx.send(embed=embed)

    @bot.command(name="계약수락", aliases=["납품계약"], help="오늘의 납품 계약 하나를 수락합니다.")
    async def contract_accept(ctx: commands.Context, 번호: int = 0) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        rows = _daily_contracts(ctx.author.id, profile)
        row = next((item for item in rows if item["number"] == 번호), None)
        if row is None:
            await ctx.send("⚠️ 계약 번호는 `!의뢰게시판`에서 1~3 중 하나를 선택하세요.")
            return
        async with _user_lock(bot, ctx.author.id):
            contracts = _dict(profile, "contracts")
            if row["id"] in set(contracts.get("completed", [])):
                await ctx.send("✅ 이미 완료한 계약입니다.")
                return
            contracts["accepted"] = row["id"]
            save_data()
        await ctx.send(f"📌 **{row['title']}** 계약을 수락했습니다. 준비가 끝나면 `!납품`을 사용하세요.")

    @bot.command(name="납품", aliases=["계약납품", "의뢰제출"], help="수락한 계약의 자원을 제출하고 보상을 받습니다.")
    async def contract_deliver(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            contracts = _dict(profile, "contracts")
            accepted = str(contracts.get("accepted") or "")
            row = next((item for item in _daily_contracts(ctx.author.id, profile) if item["id"] == accepted), None)
            if row is None:
                await ctx.send("📭 수락한 계약이 없습니다. `!의뢰게시판`에서 계약을 고르세요.")
                return
            if row["id"] in set(contracts.get("completed", [])):
                contracts["accepted"] = ""
                save_data()
                await ctx.send("✅ 이미 정산된 계약입니다.")
                return
            bag = _dict(user, "resources" if row["kind"] == "resource" else "materials")
            current = max(0, _safe_int(bag.get(row["key"]), 0))
            if current < row["amount"]:
                await ctx.send(f"⚠️ {row['key']} 부족 · 필요 {row['amount']} · 보유 {current}")
                return
            bag[row["key"]] = current - row["amount"]
            unlocked = set(_dict(profile, "research").get("unlocked", []))
            payout = int(row["food"] * (1.10 if "contract_network" in unlocked else 1.0))
            user["balance"] = _safe_int(user.get("balance"), 0) + payout
            _dict(user, "stats")["earned"] = _safe_int(_dict(user, "stats").get("earned"), 0) + payout
            research = _dict(profile, "research")
            research["points"] = _safe_int(research.get("points"), 0) + row["research"]
            contracts.setdefault("completed", []).append(row["id"])
            contracts["accepted"] = ""
            contracts.setdefault("history", []).append({"id": row["id"], "title": row["title"], "at": _iso(), "food": payout})
            profile["stats"]["contracts"] += 1
            add_season_points(user, 3)
            save_data()
        await ctx.send(f"✅ **{row['title']}** 납품 완료\n🥫 식량 +{payout:,}\n📡 연구 자료 +{row['research']}")

    @bot.command(name="계약현황", aliases=["의뢰현황", "납품현황"], help="수락·완료한 오늘의 계약을 확인합니다.")
    async def contract_status(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        contracts = _dict(profile, "contracts")
        rows = _daily_contracts(ctx.author.id, profile)
        accepted = next((row for row in rows if row["id"] == contracts.get("accepted")), None)
        await ctx.send(
            f"📦 오늘 완료 **{len(set(contracts.get('completed', [])))}/{len(rows)}건**\n"
            + (f"📌 수락 중: **{accepted['title']}** · {accepted['key']} {accepted['amount']}개" if accepted else "📭 수락 중인 계약 없음")
        )

    @bot.command(name="연구소", aliases=["생활연구소", "기술연구"], help="생활 연구 자료와 해금 기술을 확인합니다.")
    async def laboratory(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        completed = _complete_ready_research(profile)
        if completed:
            save_data()
        research = _dict(profile, "research")
        materials = _dict(user, "materials")
        embed = discord.Embed(title="🧪 폐허 생활 연구소", colour=discord.Colour.teal())
        embed.add_field(name="연구 자료", value=str(_safe_int(research.get("points"), 0)), inline=True)
        embed.add_field(name="설계도 조각", value=str(_safe_int(materials.get("설계도조각"), 0)), inline=True)
        active = research.get("active") if isinstance(research.get("active"), dict) else {}
        if active:
            key = _research_key(active.get("key"))
            tech = _RESEARCH.get(key or "", {})
            ends = _parse(active.get("completes_at"))
            remaining = max(0, int((ends - _now()).total_seconds())) if ends else 0
            embed.add_field(name="진행 중", value=f"{tech.get('name', key)} · {_format_seconds(remaining)}", inline=False)
        else:
            embed.add_field(name="진행 중", value="없음", inline=False)
        for key, tech in _RESEARCH.items():
            status = "✅ 해금" if key in set(research.get("unlocked", [])) else "연구 가능"
            embed.add_field(name=f"{tech['name']} · {status}", value=f"{tech['description']}\n연구 자료 {tech['points']} · 설계도 조각 {tech['fragments']}", inline=False)
        embed.set_footer(text="!연구시작 기술명 · !연구진행 · !설계도")
        await ctx.send(embed=embed)

    @bot.command(name="연구시작", aliases=["기술연구시작", "연구개시"], help="생활 기술 연구를 시작합니다.")
    async def research_start(ctx: commands.Context, *, 기술: str = "") -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        key = _research_key(기술)
        if not key:
            await ctx.send("⚠️ 연구 기술은 `현장배급 / 폐품회수 / 잡음필터 / 계약망` 중 하나를 입력하세요.")
            return
        async with _user_lock(bot, ctx.author.id):
            research = _dict(profile, "research")
            _complete_ready_research(profile)
            if research.get("active"):
                await ctx.send("⚠️ 이미 진행 중인 연구가 있습니다. `!연구진행`을 확인하세요.")
                return
            if key in set(research.get("unlocked", [])):
                await ctx.send("✅ 이미 해금한 기술입니다.")
                return
            tech = _RESEARCH[key]
            materials = _dict(user, "materials")
            if _safe_int(research.get("points"), 0) < tech["points"] or _safe_int(materials.get("설계도조각"), 0) < tech["fragments"]:
                await ctx.send(f"⚠️ 연구 재료 부족 · 연구 자료 {tech['points']} · 설계도 조각 {tech['fragments']} 필요")
                return
            research["points"] = _safe_int(research.get("points"), 0) - tech["points"]
            materials["설계도조각"] = _safe_int(materials.get("설계도조각"), 0) - tech["fragments"]
            research["active"] = {"key": key, "started_at": _iso(), "completes_at": _iso(_now() + timedelta(seconds=int(tech["duration"])))}
            save_data()
        await ctx.send(f"🧪 **{tech['name']}** 연구를 시작했습니다. 완료 상태는 `!연구진행`에서 확인하세요.")

    @bot.command(name="연구진행", aliases=["연구상태", "연구완료"], help="진행 중 연구를 확인하고 완료 처리합니다.")
    async def research_progress(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        async with _user_lock(bot, ctx.author.id):
            completed = _complete_ready_research(profile)
            research = _dict(profile, "research")
            active = research.get("active") if isinstance(research.get("active"), dict) else {}
            if completed:
                save_data()
                await ctx.send(f"✅ 연구 완료 · **{_RESEARCH[completed]['name']}** 기술이 해금되었습니다.")
                return
            if not active:
                await ctx.send("📭 진행 중인 연구가 없습니다. `!연구소`에서 기술을 확인하세요.")
                return
            key = _research_key(active.get("key"))
            ends = _parse(active.get("completes_at"))
            remaining = max(0, int((ends - _now()).total_seconds())) if ends else 0
        await ctx.send(f"🧪 **{_RESEARCH.get(key or '', {}).get('name', key)}** 연구 중 · 남은 시간 **{_format_seconds(remaining)}**")

    @bot.command(name="설계도", aliases=["생활설계도", "연구설계도"], help="해금한 생활 기술 설계도를 확인합니다.")
    async def blueprints(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        completed = _complete_ready_research(profile)
        if completed:
            save_data()
        research = _dict(profile, "research")
        unlocked = set(research.get("unlocked", []))
        lines = [f"{'✅' if key in unlocked else '🔒'} **{tech['name']}** — {tech['description']}" for key, tech in _RESEARCH.items()]
        await ctx.send("📐 **생활 기술 설계도**\n" + "\n".join(lines))

    @bot.command(name="파밍인카운트도감", aliases=["폐허인카운트도감", "현장인물도감", "현장접촉기록"], help="발견한 파밍 인카운트와 우호 세력을 확인합니다.")
    async def encounter_codex(ctx: commands.Context) -> None:
        user, profile = await require_user(ctx)
        if user is None or profile is None:
            return
        discovered = [key for key in profile.get("encounter_discovery", []) if key in _ENCOUNTER_BY_KEY]
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for key in discovered:
            row = _ENCOUNTER_BY_KEY[key]
            by_category.setdefault(str(row.get("category") or "mystery"), []).append(row)
        embed = discord.Embed(
            title=f"📚 {ctx.author.display_name}의 현장 인카운트 도감",
            description="직접 마주친 접촉 대상만 기록됩니다. 발견하지 않은 대상은 이름도 공개되지 않습니다.",
            colour=discord.Colour.blurple(),
        )
        order = ("ally", "rescue", "trade", "mystery", "hazard", "threat")
        for category in order:
            rows = by_category.get(category, [])
            if not rows:
                continue
            value = "\n".join(f"{row.get('emoji','')} **{row.get('actor','미확인')}** · {row.get('title','')}" for row in rows[:8])
            if len(rows) > 8:
                value += f"\n외 {len(rows)-8}건"
            embed.add_field(name=_ENCOUNTER_CATEGORY_LABELS.get(category, category), value=value[:1024], inline=False)
        if not discovered:
            embed.add_field(name="아직 기록 없음", value="`!파밍출발 지역`으로 현장 인카운트를 발견해보세요.", inline=False)
        ally_count = sum(1 for key in discovered if _ENCOUNTER_BY_KEY[key].get("category") == "ally")
        embed.add_field(name="발견 현황", value=f"전체 **{len(discovered)}/{len(_ENCOUNTERS)}** · 우호 세력 **{ally_count}**", inline=False)
        embed.set_footer(text="중복 기록 없이 최초 발견만 도감에 추가")
        await ctx.send(embed=embed)

    @bot.command(name="770안정화검수", aliases=["파밍검수", "생활기술검수", "v770검수"], help="v7.8 파밍·생활 저장 구조를 읽기 전용 검사합니다.")
    @commands.has_permissions(administrator=True)
    async def v770_audit(ctx: commands.Context) -> None:
        issues: List[str] = []
        checked = 0
        pending_count = 0
        item_ids: List[str] = []
        encounter_ids: List[str] = []
        for uid, raw in user_data.items():
            if not isinstance(raw, dict):
                continue
            checked += 1
            snapshot = copy.deepcopy(raw)
            profile = ensure_v770_profile(snapshot)
            pending = profile.get("pending_encounter") if isinstance(profile.get("pending_encounter"), dict) else {}
            if pending:
                pending_count += 1
                encounter_ids.append(str(pending.get("id") or ""))
                if not _region_key(pending.get("region")):
                    issues.append(f"{uid}: 인카운트 지역 키 이상")
            work = _dict(profile, "workshop")
            for row in list(work.get("unidentified", [])) + list(work.get("identified", [])):
                token = str(row.get("id") or "")
                if not token:
                    issues.append(f"{uid}: 폐품 ID 누락")
                item_ids.append(token)
            signal = _dict(profile, "signal")
            if signal.get("pending") and _safe_int(signal["pending"].get("answer"), 0) not in {1, 2, 3, 4}:
                issues.append(f"{uid}: 신호 정답 키 이상")
            contracts = _dict(profile, "contracts")
            if len(contracts.get("completed", [])) != len(set(contracts.get("completed", []))):
                issues.append(f"{uid}: 계약 완료 ID 중복")
            research = _dict(profile, "research")
            if len(research.get("unlocked", [])) != len(set(research.get("unlocked", []))):
                issues.append(f"{uid}: 연구 해금 키 중복")
        duplicates = {token for token in item_ids if token and item_ids.count(token) > 1}
        duplicate_encounters = {token for token in encounter_ids if token and encounter_ids.count(token) > 1}
        if duplicates:
            issues.append(f"폐품 ID 중복 {len(duplicates)}건")
        if duplicate_encounters:
            issues.append(f"인카운트 ID 중복 {len(duplicate_encounters)}건")
        embed = discord.Embed(title="🛡️ ABADDON v8.1.1 인카운트 다양성·파밍 연출 안정화 검수", colour=discord.Colour.green() if not issues else discord.Colour.orange())
        embed.add_field(name="검사 생존자", value=str(checked), inline=True)
        embed.add_field(name="대기 인카운트", value=str(pending_count), inline=True)
        embed.add_field(name="발견 항목", value=str(len(issues)), inline=True)
        embed.add_field(name="수정·삭제", value="0건 · 읽기 전용", inline=True)
        embed.add_field(name="결과", value="✅ 이상 없음" if not issues else "\n".join(f"• {issue}" for issue in issues[:15]), inline=False)
        embed.set_footer(text="기존 기능 폐기·삭제는 관리자 승인 전 수행하지 않습니다")
        await ctx.send(embed=embed)

    @bot.listen("on_ready")
    async def v770_startup_audit() -> None:
        if getattr(bot, "_abaddon_v770_startup_done", False):
            return
        bot._abaddon_v770_startup_done = True
        profiles = 0
        pending = 0
        active_research = 0
        for raw in user_data.values():
            if not isinstance(raw, dict) or "farming_v770" not in raw:
                continue
            profiles += 1
            profile = ensure_v770_profile(raw)
            pending += 1 if profile.get("pending_encounter") else 0
            active_research += 1 if _dict(profile, "research").get("active") else 0
        print(
            f"[ABADDON v{VERSION}] livelihood startup status=ok profiles={profiles} "
            f"pending_encounters={pending} active_research={active_research} deletions=0",
            flush=True,
        )

    bot.v770_farming_fx_version = VERSION
    bot._abaddon_v770_registered = True
    print(
        f"[ABADDON v{VERSION}] 파밍 인카운트 다양성·연출 등록 완료: "
        f"지역={len(FARM_REGIONS)} 인카운트={len(_ENCOUNTERS)} 우호={sum(1 for row in _ENCOUNTERS if row.get('category') == 'ally')} 연구={len(_RESEARCH)} 삭제=0",
        flush=True,
    )
