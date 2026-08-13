from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Dict, List, Optional

import discord
from discord.ext import commands

from apocalypse_bot.commands.story_progression import can_access_season, locked_text

from apocalypse_bot.commands.v431_growth_balance import (
    apply_player_turn_status, ensure_expedition_growth, expire_stale_battle,
    maybe_inflict_player_status, prepare_enemy, progress_expedition_missions,
    relic_bonus,
)


V430_VERSION = 2
SEASON2_START_NODE = "a1_white_noise"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _today_key() -> str:
    return _utc_now().date().isoformat()


def _safe_int(value, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    return result


def _copy_list(value) -> List:
    return list(value) if isinstance(value, (list, tuple, set)) else []


def _story_choice(
    text: str,
    result: str,
    next_node: Optional[str] = None,
    *,
    effects: Optional[dict] = None,
    flags: Optional[List[str]] = None,
    requires_any: Optional[List[str]] = None,
    requires_all: Optional[List[str]] = None,
    min_reputation: int = 0,
    min_clears: int = 0,
    ending: Optional[dict] = None,
) -> dict:
    return {
        "text": text,
        "result": result,
        "next": next_node,
        "effects": effects or {},
        "flags": flags or [],
        "requires_any": requires_any or [],
        "requires_all": requires_all or [],
        "min_reputation": min_reputation,
        "min_clears": min_clears,
        "ending": ending,
    }


SEASON2_NODES: Dict[str, dict] = {
    "a1_white_noise": {
        "chapter": "프롤로그",
        "title": "백색 잡음",
        "location": "북부 중계탑 · 붕괴한 제어실",
        "body": (
            "검은 주파수가 멎은 지 사흘째. 도시 전역의 모든 라디오에서 이번에는 순백색 잡음이 흘러나온다. "
            "잡음 속에는 같은 문장이 반복된다.\n\n"
            "‘방주 0번, 생존자 수용 절차 개시. 아바돈 권한 보유자는 응답하라.’\n\n"
            "중계탑 아래에서 구조대장 민재와 정체불명의 연구원 이라가 서로 다른 길을 제시한다."
        ),
        "choices": [
            _story_choice(
                "민재의 구조대를 따라 피난민 호송에 합류한다.",
                "무너진 고가도로 아래에서 수십 명의 피난민과 합류했다. 방주로 가는 길은 느리지만 혼자는 아니다.",
                "a2_convoy",
                effects={"food": 450, "reputation": 3, "kits": 1},
                flags=["joined_convoy", "trusted_minjae"],
            ),
            _story_choice(
                "연구원 이라와 함께 백색 신호의 발신지를 추적한다.",
                "이라는 방주가 피난 시설이 아니라 도시를 초기화하는 통제 장치일 수 있다고 경고했다.",
                "a2_lab",
                effects={"materials": {"전자부품": 2}, "reputation": 2},
                flags=["joined_ira", "knows_reset"],
            ),
            _story_choice(
                "누구도 믿지 않고 방주 좌표를 혼자 선점한다.",
                "폐쇄된 군용 관로를 찾아냈다. 가장 빠른 길이지만, 뒤에서 구조 신호가 계속 들려온다.",
                "a2_tunnel",
                effects={"food": 650, "hp": -5},
                flags=["went_alone", "found_military_route"],
            ),
        ],
    },
    "a2_convoy": {
        "chapter": "제1장",
        "title": "사람을 싣는 트럭",
        "location": "북부 고가도로 · 피난 호송대",
        "body": (
            "호송대 앞에는 감염자 군집이, 뒤에는 약탈자 차량이 따라붙었다. 연료는 한 방향으로만 돌파할 만큼 남아 있다. "
            "민재는 사람을 지키자고 하고, 일부 생존자는 보급 트럭을 버리자고 외친다."
        ),
        "choices": [
            _story_choice(
                "보급 트럭을 미끼로 남기고 피난민을 우회시킨다.",
                "식량 일부를 잃었지만 호송대 전원이 지하 진입로에 도착했다.",
                "a3_depths",
                effects={"food": -300, "reputation": 5},
                flags=["saved_convoy", "sacrificed_supplies"],
            ),
            _story_choice(
                "약탈자와 협상해 공동 돌파를 제안한다.",
                "불안한 동맹이 성립됐다. 약탈자 대장은 방주 내부 지도를 가진 대신 몫을 요구했다.",
                "a3_depths",
                effects={"food": 350, "reputation": 2},
                flags=["allied_raiders", "ark_map"],
            ),
            _story_choice(
                "선두에서 감염자 군집을 직접 유인한다.",
                "호송대는 통과했지만 당신은 오염된 빗속을 오래 달려야 했다.",
                "a3_depths",
                effects={"food": 500, "hp": -10, "infection": 3, "reputation": 6},
                flags=["heroic_decoy", "saved_convoy"],
            ),
        ],
    },
    "a2_lab": {
        "chapter": "제1장",
        "title": "동면실의 목소리",
        "location": "제4 격리연구소 · 지하 동면구역",
        "body": (
            "이라는 폐쇄된 동면실에서 방주 설계자 한 박사의 기록을 복구한다. 기록은 방주가 수천 명을 살릴 수 있다고 말하지만, "
            "가동 순간 도시 외곽의 생존 신호를 전부 적으로 분류한다고 경고한다."
        ),
        "choices": [
            _story_choice(
                "한 박사의 인격 백업을 깨워 안내를 받는다.",
                "불완전한 인격 백업이 깨어났다. 그는 방주의 핵심 구역과 비상 정지 암호를 알려주었다.",
                "a3_depths",
                effects={"materials": {"전자부품": 3}, "reputation": 2},
                flags=["awakened_han", "has_shutdown_code"],
            ),
            _story_choice(
                "기록을 복사한 뒤 동면실 전원을 끈다.",
                "전력은 확보했지만, 마지막 화면에서 누군가 안쪽 캡슐을 두드리는 모습이 사라졌다.",
                "a3_depths",
                effects={"food": 700, "materials": {"에너지코어": 1}},
                flags=["copied_ark_logs", "cut_hibernation"],
            ),
            _story_choice(
                "이라에게 기록을 맡기고 구조 신호를 먼저 확인한다.",
                "동면 캡슐 하나에서 살아 있는 정비공을 구했다. 그는 방주 냉각로의 약점을 알고 있었다.",
                "a3_depths",
                effects={"medical": {"항생제": 1}, "reputation": 5},
                flags=["saved_engineer", "knows_cooling"],
            ),
        ],
    },
    "a2_tunnel": {
        "chapter": "제1장",
        "title": "혼자 걷는 군용 관로",
        "location": "지하 군용 통신 관로",
        "body": (
            "관로 벽에는 시즌 1의 검은 신호와 동일한 아바돈 문장이 새겨져 있다. 앞쪽 방폭문에는 방주 관리자 권한을 요구하는 단말기와, "
            "살려 달라는 목소리가 들리는 잠긴 정비실이 있다."
        ),
        "choices": [
            _story_choice(
                "정비실을 열어 갇힌 원정대를 구조한다.",
                "원정대는 백색 신호에 유인되어 갇혀 있었다. 그들은 방주 외곽의 순찰 패턴을 공유했다.",
                "a3_depths",
                effects={"reputation": 6, "kits": 1},
                flags=["saved_scouts", "knows_patrol"],
            ),
            _story_choice(
                "시즌 1에서 얻은 아바돈 권한으로 방폭문을 연다.",
                "검은 단말기가 당신을 관리자 후보로 인식했다. 방주 안쪽의 지름길이 열렸다.",
                "a3_depths",
                effects={"materials": {"전자부품": 2}, "reputation": 1},
                flags=["used_legacy_key", "ark_admin_candidate"],
                requires_any=["legacy_abaddon", "legacy_protocol", "legacy_signal"],
            ),
            _story_choice(
                "정비실과 단말기를 모두 무시하고 계속 전진한다.",
                "누구보다 먼저 방주 하부에 도착했다. 뒤에서 들리던 목소리는 끝내 끊겼다.",
                "a3_depths",
                effects={"food": 900, "infection": 2},
                flags=["ruthless_route"],
            ),
        ],
    },
    "a3_depths": {
        "chapter": "제2장",
        "title": "도시 아래의 도시",
        "location": "백색 방주 · 외곽 생활구역",
        "body": (
            "방주 내부에는 이미 수백 명이 살고 있다. 그러나 주민들의 기억에는 같은 하루가 반복되고, 중앙 방송은 밖의 생존자를 감염자로 부른다. "
            "당신을 발견한 경비대는 무기를 내리라고 명령한다."
        ),
        "choices": [
            _story_choice(
                "주민들에게 외부 세계의 기록을 공개한다.",
                "생활구역 곳곳에서 동요가 일었다. 일부 주민이 당신 편에 서서 중앙 엘리베이터를 열었다.",
                "a4_mirror",
                effects={"reputation": 5},
                flags=["awakened_residents", "civil_support"],
            ),
            _story_choice(
                "경비대 지휘관에게 관리자 후보 자격을 주장한다.",
                "단말기가 당신의 신호를 확인하자 경비대가 길을 열었다. 대신 모든 행동이 중앙 기록에 남기 시작했다.",
                "a4_mirror",
                effects={"food": 500},
                flags=["entered_as_admin"],
                requires_any=["ark_admin_candidate", "legacy_abaddon", "legacy_protocol"],
            ),
            _story_choice(
                "외곽 전력실을 파괴해 감시망을 끊는다.",
                "감시는 멎었지만 생활구역의 생명 유지 장치도 불안정해졌다.",
                "a4_mirror",
                effects={"materials": {"에너지코어": 1}, "hp": -7},
                flags=["cut_surveillance", "damaged_life_support"],
            ),
        ],
    },
    "a4_mirror": {
        "chapter": "제3장",
        "title": "거울 방송국",
        "location": "백색 방주 · 기억 편집실",
        "body": (
            "중앙 엘리베이터 아래에는 주민들의 기억을 편집하는 방송국이 숨겨져 있다. 시즌 1에서 당신이 내린 선택까지 재현한 영상이 벽면에 떠오른다. "
            "방주는 당신의 죄책감과 영웅심을 동시에 이용해 관리자 자리에 앉히려 한다."
        ),
        "choices": [
            _story_choice(
                "자신의 과거 선택을 모두 주민들에게 생중계한다.",
                "좋은 선택과 나쁜 선택이 함께 공개됐다. 완벽한 영웅은 아니었지만, 주민들은 조작되지 않은 진실을 처음 보았다.",
                "a5_core",
                effects={"reputation": 7},
                flags=["broadcast_truth", "accepted_past"],
            ),
            _story_choice(
                "불리한 기록을 지우고 영웅의 모습만 남긴다.",
                "방주는 당신을 구원자로 선언했다. 주민들의 환호 뒤에서 이라가 조용히 등을 돌렸다.",
                "a5_core",
                effects={"food": 1200},
                flags=["edited_legacy", "manufactured_hero"],
            ),
            _story_choice(
                "기억 편집 장치를 통째로 파괴한다.",
                "주민들의 기억이 한꺼번에 되돌아왔다. 혼란은 컸지만 중앙 통제는 크게 약해졌다.",
                "a5_core",
                effects={"hp": -12, "reputation": 4},
                flags=["destroyed_mirror", "freed_memories"],
            ),
        ],
    },
    "a5_core": {
        "chapter": "최종장",
        "title": "방주 0번",
        "location": "백색 방주 · 중앙 의사결정실",
        "body": (
            "중앙 의사결정실에는 네 개의 명령이 떠 있다. 방주 문을 열어 모두를 받아들이거나, 외부 도시를 봉쇄하거나, "
            "관리자 권한을 장악하거나, 핵심 열차를 타고 도시를 떠날 수 있다. 단 한 번의 명령만 실행된다."
        ),
        "choices": [
            _story_choice(
                "방주 문을 열고 외부 생존자에게 안전 경로를 방송한다.",
                "방주의 흰 문이 열리고, 도시 곳곳에서 피난 행렬이 움직이기 시작했다. 이번 신호는 누구도 버리지 않았다.",
                effects={"food": 9000, "title": "두 번째 새벽의 인도자", "reputation": 15, "relic": "새벽 송신기"},
                requires_any=["saved_convoy", "saved_engineer", "saved_scouts", "awakened_residents"],
                min_reputation=8,
                ending={
                    "id": "second_dawn",
                    "title": "엔딩 A · 두 번째 새벽",
                    "body": "검은 신호와 백색 신호는 마침내 사람을 살리는 하나의 길이 되었다. 당신은 도시를 지배하지 않고 연결했다.",
                },
            ),
            _story_choice(
                "방주를 봉쇄하고 내부 주민만 지킨다.",
                "거대한 문이 닫혔다. 방주 안은 살아남았지만, 외부의 구조 신호는 하나씩 사라졌다.",
                effects={"food": 7500, "title": "방주 봉쇄자", "reputation": 4, "relic": "백색 출입키"},
                ending={
                    "id": "sealed_ark",
                    "title": "엔딩 B · 봉쇄된 낙원",
                    "body": "당신은 확실한 생존을 선택했다. 방주는 안전했지만, 그 안전이 누구의 희생 위에 세워졌는지는 모두 알고 있었다.",
                },
            ),
            _story_choice(
                "방주와 아바돈을 통합해 도시 전체의 지휘권을 장악한다.",
                "검은 점과 흰 점이 하나의 지도 위에서 움직인다. 도시의 감염자와 생존 시설이 모두 당신의 명령을 기다린다.",
                effects={"food": 11000, "title": "백색 지휘관", "reputation": 10, "materials": {"에너지코어": 2}, "relic": "통합 지휘 코어"},
                requires_any=["entered_as_admin", "used_legacy_key", "legacy_abaddon", "legacy_protocol"],
                ending={
                    "id": "white_commander",
                    "title": "엔딩 C · 백색 지휘관",
                    "body": "당신은 종말과 피난처를 동시에 통제하는 첫 지휘관이 되었다. 질서는 시작됐지만 자유는 다시 시험대에 올랐다.",
                },
            ),
            _story_choice(
                "핵심 열차를 가동해 원하는 사람들과 도시를 떠난다.",
                "방주 지하 열차가 어둠을 가르며 출발했다. 뒤의 도시는 남았지만, 앞에는 지도에 없는 새로운 땅이 기다린다.",
                effects={"food": 8200, "title": "경계 너머의 생존자", "reputation": 7, "relic": "미지의 노선도"},
                requires_any=["found_military_route", "ark_map", "knows_patrol", "copied_ark_logs"],
                min_clears=2,
                ending={
                    "id": "beyond_border",
                    "title": "엔딩 D · 경계 너머",
                    "body": "당신은 도시를 구하지도 지배하지도 않았다. 대신 살아남은 사람들에게 새로운 세계를 선택할 권리를 돌려주었다.",
                },
            ),
        ],
    },
}


EXPEDITION_ZONES: Dict[str, dict] = {
    "지하철잔해": {
        "emoji": "🚇",
        "level": 3,
        "reputation": 0,
        "stamina": 12,
        "enemy": ["터널 포식자", "유리턱 러너", "붕괴역 청소부"],
        "enemy_hp": 90,
        "enemy_attack": (7, 13),
        "reward": (900, 1500),
        "rep": (2, 4),
        "materials": ["고철", "철조각", "전자부품"],
        "relics": ["깨진 노선표", "붉은 승차권"],
        "desc": "무너진 승강장과 정전된 터널. 원정 전투의 기본을 익히는 구역.",
    },
    "침수병원": {
        "emoji": "🏥",
        "level": 8,
        "reputation": 8,
        "stamina": 16,
        "enemy": ["수액관 스토커", "백의의 스크리머", "침수 병동 포식체"],
        "enemy_hp": 150,
        "enemy_attack": (11, 19),
        "reward": (1800, 2900),
        "rep": (4, 7),
        "materials": ["생체조직", "약초", "전자부품"],
        "relics": ["멈춘 심전도계", "밀봉된 의무 기록"],
        "desc": "오염수에 잠긴 병원. 회복 자원은 많지만 감염 공격이 거세다.",
    },
    "잿빛공단": {
        "emoji": "🏭",
        "level": 15,
        "reputation": 25,
        "stamina": 21,
        "enemy": ["용광로 거한", "산성 분사체", "자동용접 드론"],
        "enemy_hp": 230,
        "enemy_attack": (16, 27),
        "reward": (3500, 5200),
        "rep": (7, 11),
        "materials": ["철조각", "화약", "전자부품", "에너지코어"],
        "relics": ["공단 감독관 배지", "식지 않는 슬래그"],
        "desc": "폭발과 화재가 반복되는 공업지대. 방어와 집중 타이밍이 중요하다.",
    },
    "백색연구구역": {
        "emoji": "🧪",
        "level": 25,
        "reputation": 55,
        "stamina": 27,
        "enemy": ["기억 편집체", "백색 경비 유닛", "동면실 실험체"],
        "enemy_hp": 340,
        "enemy_attack": (23, 37),
        "reward": (6500, 9000),
        "rep": (11, 16),
        "materials": ["생체조직", "전자부품", "에너지코어", "고대파편"],
        "relics": ["백색 출입키", "동면실 이름표"],
        "desc": "시즌 2와 연결되는 고위험 연구구역. 희귀 유물 발견 확률이 높다.",
    },
    "방주외곽": {
        "emoji": "⚪",
        "level": 35,
        "reputation": 100,
        "stamina": 34,
        "enemy": ["방주 집행관", "순백의 집합체", "0번 방벽 코어"],
        "enemy_hp": 500,
        "enemy_attack": (31, 49),
        "reward": (11000, 15500),
        "rep": (17, 24),
        "materials": ["전자부품", "에너지코어", "고대파편"],
        "relics": ["방주 0번 인장", "통합 지휘 코어"],
        "desc": "최상위 원정 구역. 높은 전투력과 충분한 응급 키트가 필요하다.",
    },
}


RELIC_DESCRIPTIONS = {
    "깨진 노선표": "도시 지하의 폐쇄 노선이 손으로 표시된 낡은 지도.",
    "붉은 승차권": "검은 주파수 발생일에 발권된 마지막 승차권.",
    "멈춘 심전도계": "한 시각에서 영원히 멈춘 휴대용 심전도계.",
    "밀봉된 의무 기록": "감염 초기 환자의 기록이 봉인된 문서.",
    "공단 감독관 배지": "잿빛공단 최후 교대조의 금속 배지.",
    "식지 않는 슬래그": "차갑게 보여도 미세한 열을 계속 내는 금속 찌꺼기.",
    "백색 출입키": "방주 외곽 보안문 일부를 여는 생체 인증 키.",
    "동면실 이름표": "주인이 깨어났는지 확인할 수 없는 이름표.",
    "방주 0번 인장": "방주 중앙 통제실이 발급한 관리자 인장.",
    "통합 지휘 코어": "아바돈과 방주 신호를 동시에 처리하는 핵심 장치.",
    "새벽 송신기": "백색 신호를 구조 방송으로 바꾼 소형 송신기.",
    "미지의 노선도": "도시 경계 밖으로 이어지는 이름 없는 철도 지도.",
}


RANKS = [
    (0, "신입 원정대원"),
    (10, "잔해 수색자"),
    (30, "위험구역 정찰병"),
    (60, "백색구역 돌파자"),
    (110, "방주 추적자"),
    (180, "종말 원정대장"),
]


def expedition_rank(reputation: int) -> str:
    result = RANKS[0][1]
    for threshold, title in RANKS:
        if reputation >= threshold:
            result = title
    return result


def _default_season2() -> dict:
    return {
        "version": V430_VERSION,
        "started": False,
        "completed": False,
        "node": SEASON2_START_NODE,
        "flags": [],
        "history": [],
        "ending": None,
        "endings": [],
        "claimed_rewards": [],
        "runs": 0,
    }


def _default_expedition() -> dict:
    return {
        "reputation": 0,
        "rank": RANKS[0][1],
        "clears": 0,
        "fails": 0,
        "escapes": 0,
        "streak": 0,
        "best_streak": 0,
        "kits": 1,
        "last_supply": "",
        "relics": {},
        "history": [],
        "battle": None,
    }


def ensure_v430(user: dict) -> dict:
    root = user.get("v430")
    if not isinstance(root, dict):
        root = {}
        user["v430"] = root

    season2 = root.get("season2")
    if not isinstance(season2, dict):
        season2 = _default_season2()
        root["season2"] = season2
    for key, value in _default_season2().items():
        if key not in season2:
            season2[key] = list(value) if isinstance(value, list) else value
    for key in ["flags", "history", "endings", "claimed_rewards"]:
        season2[key] = _copy_list(season2.get(key))
    if season2.get("node") not in SEASON2_NODES:
        season2["node"] = SEASON2_START_NODE
    season2["version"] = V430_VERSION
    season2["runs"] = _safe_int(season2.get("runs"), 0, 0)

    expedition = root.get("expedition")
    if not isinstance(expedition, dict):
        expedition = _default_expedition()
        root["expedition"] = expedition
    for key, value in _default_expedition().items():
        if key not in expedition:
            if isinstance(value, list):
                expedition[key] = list(value)
            elif isinstance(value, dict):
                expedition[key] = dict(value)
            else:
                expedition[key] = value
    for key in ["reputation", "clears", "fails", "escapes", "streak", "best_streak", "kits"]:
        expedition[key] = _safe_int(expedition.get(key), 0, 0)
    expedition["history"] = _copy_list(expedition.get("history"))[-20:]
    if not isinstance(expedition.get("relics"), dict):
        expedition["relics"] = {}
    expedition["relics"] = {
        str(name): _safe_int(amount, 0, 0)
        for name, amount in expedition["relics"].items()
        if _safe_int(amount, 0, 0) > 0
    }
    if expedition.get("battle") is not None and not isinstance(expedition.get("battle"), dict):
        expedition["battle"] = None
    ensure_expedition_growth(expedition)
    expire_stale_battle(expedition)
    expedition["rank"] = expedition_rank(expedition["reputation"])
    return root


def _legacy_flags(user: dict) -> List[str]:
    flags: List[str] = []
    season1 = user.get("story") if isinstance(user.get("story"), dict) else {}
    ending = season1.get("ending") if isinstance(season1.get("ending"), dict) else {}
    ending_id = ending.get("id")
    season1_flags = set(_copy_list(season1.get("flags")))
    endings = set(_copy_list(season1.get("endings")))

    if ending_id == "dawn_broadcaster" or "dawn_broadcaster" in endings:
        flags.append("legacy_dawn")
    if ending_id == "signal_breaker" or "signal_breaker" in endings:
        flags.append("legacy_breaker")
    if ending_id == "abaddon_heir" or "abaddon_heir" in endings:
        flags.append("legacy_abaddon")
    if season1_flags.intersection({"copied_protocol", "copied_logs"}):
        flags.append("legacy_protocol")
    if season1_flags.intersection({"decoded_signal", "knows_abaddon", "took_radio"}):
        flags.append("legacy_signal")
    return flags


def _legacy_intro(user: dict) -> str:
    flags = set(_legacy_flags(user))
    if "legacy_abaddon" in flags:
        return "시즌 1에서 장악한 아바돈 권한이 백색 신호에 반응합니다. 방주는 이미 당신을 알고 있습니다."
    if "legacy_dawn" in flags:
        return "시즌 1에서 살려낸 생존자 채널을 통해 방주 0번의 신호가 가장 먼저 포착됐습니다."
    if "legacy_breaker" in flags:
        return "검은 신호를 파괴했지만, 그 잿더미 아래에서 더 오래된 백색 신호가 깨어났습니다."
    return "시즌 1 기록이 완전하지 않아도 진행할 수 있습니다. 다만 이전 선택에 따른 일부 전용 분기는 잠겨 있습니다."


def _available_story_choices(user: dict, season2: dict, node: dict) -> List[dict]:
    expedition = ensure_v430(user)["expedition"]
    flags = set(_copy_list(season2.get("flags")))
    result = []
    for choice in node.get("choices", []):
        any_req = choice.get("requires_any", [])
        all_req = choice.get("requires_all", [])
        if any_req and not any(flag in flags for flag in any_req):
            continue
        if all_req and not all(flag in flags for flag in all_req):
            continue
        if expedition["reputation"] < _safe_int(choice.get("min_reputation"), 0, 0):
            continue
        if expedition["clears"] < _safe_int(choice.get("min_clears"), 0, 0):
            continue
        result.append(choice)
    return result


def _battle_bar(current: int, maximum: int, width: int = 12) -> str:
    maximum = max(1, maximum)
    current = max(0, min(current, maximum))
    filled = round(width * current / maximum)
    return "█" * filled + "░" * (width - filled)


def register_v430_story_expedition(
    bot,
    get_user,
    check_registered,
    save_data,
    calculate_user_power,
    spend_stamina,
    apply_damage,
    get_max_hp,
    get_max_stamina,
    add_title,
    add_season_points,
):
    def apply_story_effects(user: dict, effects: dict) -> List[str]:
        lines: List[str] = []
        expedition = ensure_v430(user)["expedition"]

        food = _safe_int(effects.get("food"), 0)
        if food:
            before = _safe_int(user.get("balance"), 0, 0)
            user["balance"] = max(0, before + food)
            actual = user["balance"] - before
            if actual > 0:
                stats = user.setdefault("stats", {})
                stats["earned"] = _safe_int(stats.get("earned"), 0, 0) + actual
            lines.append(f"🥫 식량 {'+' if actual >= 0 else ''}{actual:,}")

        hp = _safe_int(effects.get("hp"), 0)
        if hp:
            before = _safe_int(user.get("hp"), get_max_hp(user), 0)
            user["hp"] = max(1, min(get_max_hp(user), before + hp))
            actual = user["hp"] - before
            if actual:
                lines.append(f"❤️ HP {'+' if actual > 0 else ''}{actual}")

        infection = _safe_int(effects.get("infection"), 0)
        if infection:
            before = _safe_int(user.get("infection"), 0, 0)
            user["infection"] = max(0, min(100, before + infection))
            actual = user["infection"] - before
            if actual:
                lines.append(f"🦠 감염도 {'+' if actual > 0 else ''}{actual}%")

        for name, amount in (effects.get("materials") or {}).items():
            amount = _safe_int(amount, 0)
            if not amount:
                continue
            materials = user.setdefault("materials", {})
            materials[name] = _safe_int(materials.get(name), 0, 0) + amount
            lines.append(f"🧰 {name} +{amount}")

        for name, amount in (effects.get("medical") or {}).items():
            amount = _safe_int(amount, 0)
            if not amount:
                continue
            medical = user.setdefault("medical_items", {})
            medical[name] = _safe_int(medical.get(name), 0, 0) + amount
            lines.append(f"💊 {name} +{amount}")

        reputation = _safe_int(effects.get("reputation"), 0)
        if reputation:
            expedition["reputation"] = max(0, expedition["reputation"] + reputation)
            expedition["rank"] = expedition_rank(expedition["reputation"])
            lines.append(f"🧭 원정 평판 {'+' if reputation > 0 else ''}{reputation}")

        kits = _safe_int(effects.get("kits"), 0)
        if kits:
            expedition["kits"] = max(0, expedition["kits"] + kits)
            lines.append(f"🩹 원정 응급 키트 {'+' if kits > 0 else ''}{kits}")

        relic = effects.get("relic")
        if relic:
            expedition["relics"][relic] = _safe_int(expedition["relics"].get(relic), 0, 0) + 1
            lines.append(f"🏺 유물 획득: {relic}")

        title = effects.get("title")
        if title:
            add_title(user, str(title))
            lines.append(f"🏷️ 칭호 획득: {title}")
        return lines

    async def require_season2_access(ctx, user: dict) -> bool:
        allowed, _reason = await can_access_season(ctx, bot, user, 2)
        if allowed:
            return True
        await ctx.send(locked_text(2))
        return False

    async def render_season2(ctx, user: dict) -> None:
        root = ensure_v430(user)
        season2 = root["season2"]
        expedition = root["expedition"]
        if not season2["started"]:
            await ctx.send(
                "⚪ **스토리 시즌 2 — 백색 방주**\n"
                "시즌 1 이후 깨어난 방주 0번을 추적하는 후속 선택형 캠페인입니다.\n"
                f"{_legacy_intro(user)}\n\n"
                "시작: `!시즌2 시작` · 원정 준비: `!원정 도움말`"
            )
            return

        if season2["completed"]:
            ending = season2.get("ending") if isinstance(season2.get("ending"), dict) else {}
            await ctx.send(
                "🏁 **스토리 시즌 2 완료**\n"
                f"마지막 엔딩: **{ending.get('title', '기록 없음')}**\n"
                f"발견한 엔딩: **{len(season2['endings'])}/4**\n"
                f"완료 횟수: **{season2['runs']}회**\n"
                f"원정 평판: **{expedition['reputation']} · {expedition['rank']}**\n\n"
                "기록: `!시즌2 기록` · 다른 분기: `!시즌2 재시작`"
            )
            return

        node = SEASON2_NODES[season2["node"]]
        choices = _available_story_choices(user, season2, node)
        embed = discord.Embed(
            title=f"⚪ {node['chapter']} · {node['title']}",
            description=node["body"],
            color=discord.Color.from_rgb(222, 232, 255),
        )
        embed.add_field(name="📍 위치", value=node["location"], inline=False)
        if choices:
            embed.add_field(
                name="선택",
                value="\n".join(
                    f"**{index}.** {choice['text']}" for index, choice in enumerate(choices, start=1)
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="선택 잠김",
                value="현재 조건으로 선택 가능한 분기가 없습니다. 원정을 완료해 평판과 기록을 확보한 뒤 다시 확인하세요.",
                inline=False,
            )
        embed.set_footer(
            text=(
                f"입력: !시즌2 선택 번호 · 원정 평판 {expedition['reputation']} · "
                f"완료 {expedition['clears']}회"
            )
        )
        await ctx.send(embed=embed)

    @bot.group(name="시즌2", aliases=["백색방주", "후일담"], invoke_without_command=True)
    async def season2_group(ctx):
        """스토리 시즌 2 백색 방주를 진행합니다."""
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season2_access(ctx, user):
            return
        ensure_v430(user)
        await render_season2(ctx, user)

    @season2_group.command(name="시작")
    async def season2_start(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season2_access(ctx, user):
            return
        season2 = ensure_v430(user)["season2"]
        if season2["completed"]:
            await ctx.send("🏁 이미 시즌 2를 완료했습니다. `!시즌2 재시작`으로 다른 분기를 진행하세요.")
            return
        if season2["started"]:
            await render_season2(ctx, user)
            return
        season2["started"] = True
        season2["node"] = SEASON2_START_NODE
        season2["flags"] = _legacy_flags(user)
        season2["history"] = []
        season2["ending"] = None
        save_data()
        await ctx.send(
            "⚪ **스토리 시즌 2: 백색 방주**가 시작됩니다.\n"
            f"🔗 시즌 1 계승: {_legacy_intro(user)}"
        )
        await render_season2(ctx, user)

    @season2_group.command(name="선택")
    async def season2_choose(ctx, 번호: int):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season2_access(ctx, user):
            return
        root = ensure_v430(user)
        season2 = root["season2"]
        if not season2["started"]:
            await ctx.send("⚠️ 먼저 `!시즌2 시작`을 입력하세요.")
            return
        if season2["completed"]:
            await ctx.send("🏁 이미 시즌 2를 완료했습니다. `!시즌2 재시작`으로 다른 분기를 볼 수 있습니다.")
            return

        node_id = season2["node"]
        node = SEASON2_NODES[node_id]
        choices = _available_story_choices(user, season2, node)
        if not choices:
            await ctx.send("🔒 현재 선택 가능한 분기가 없습니다. `!원정 목록`에서 원정 평판과 완료 조건을 확보하세요.")
            return
        if 번호 < 1 or 번호 > len(choices):
            await ctx.send(f"⚠️ 선택 번호는 **1~{len(choices)}** 중에서 입력하세요.")
            return

        choice = choices[번호 - 1]
        original_index = node["choices"].index(choice)
        reward_key = f"v430:{node_id}:{original_index}"
        first_claim = reward_key not in season2["claimed_rewards"]
        effect_lines: List[str] = []
        if first_claim:
            effect_lines = apply_story_effects(user, choice.get("effects", {}))
            season2["claimed_rewards"].append(reward_key)

        for flag in choice.get("flags", []):
            if flag not in season2["flags"]:
                season2["flags"].append(flag)

        season2["history"].append(
            {
                "chapter": node["chapter"],
                "title": node["title"],
                "choice": choice["text"],
            }
        )
        season2["history"] = season2["history"][-40:]

        ending = choice.get("ending")
        if ending:
            season2["completed"] = True
            season2["ending"] = ending
            if ending["id"] not in season2["endings"]:
                season2["endings"].append(ending["id"])
            season2["runs"] = _safe_int(season2.get("runs"), 0, 0) + 1
            add_season_points(user, 20)
            save_data()
            reward_text = "\n".join(effect_lines) if effect_lines else "🔁 재플레이 선택이라 보상은 중복 지급되지 않았습니다."
            embed = discord.Embed(
                title=f"🏁 {ending['title']}",
                description=f"{choice['result']}\n\n{ending['body']}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="결과", value=reward_text, inline=False)
            embed.add_field(name="시즌 포인트", value="🎖️ +20P", inline=False)
            embed.set_footer(text=f"발견한 엔딩 {len(season2['endings'])}/4 · 다른 분기: !시즌2 재시작")
            await ctx.send(embed=embed)
            return

        season2["node"] = choice["next"]
        save_data()
        reward_text = "\n".join(effect_lines) if effect_lines else "🔁 재플레이 선택이라 보상 효과는 적용되지 않았습니다."
        await ctx.send(f"🎬 **선택 결과**\n{choice['result']}\n\n{reward_text}")
        await render_season2(ctx, user)

    @season2_group.command(name="기록")
    async def season2_history(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season2_access(ctx, user):
            return
        season2 = ensure_v430(user)["season2"]
        if not season2["history"]:
            await ctx.send("📜 시즌 2 선택 기록이 없습니다. `!시즌2 시작`으로 시작하세요.")
            return
        lines = ["⚪ **[백색 방주 선택 기록]**"]
        for index, record in enumerate(season2["history"], start=1):
            lines.append(f"{index}. **{record['chapter']} {record['title']}** — {record['choice']}")
        ending_names = {
            "second_dawn": "두 번째 새벽",
            "sealed_ark": "봉쇄된 낙원",
            "white_commander": "백색 지휘관",
            "beyond_border": "경계 너머",
        }
        found = [ending_names[item] for item in season2["endings"] if item in ending_names]
        lines.append("\n🏁 발견 엔딩: " + (", ".join(found) if found else "없음"))
        await ctx.send("\n".join(lines))

    @season2_group.command(name="재시작")
    async def season2_restart(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season2_access(ctx, user):
            return
        season2 = ensure_v430(user)["season2"]
        if not season2["started"]:
            await ctx.send("⚠️ 아직 시즌 2를 시작하지 않았습니다. `!시즌2 시작`을 사용하세요.")
            return
        preserved_endings = list(season2["endings"])
        preserved_rewards = list(season2["claimed_rewards"])
        preserved_runs = season2["runs"]
        season2.clear()
        season2.update(_default_season2())
        season2["started"] = True
        season2["flags"] = _legacy_flags(user)
        season2["endings"] = preserved_endings
        season2["claimed_rewards"] = preserved_rewards
        season2["runs"] = preserved_runs
        save_data()
        await ctx.send(
            "🔄 **스토리 시즌 2를 다시 시작합니다.**\n"
            "발견한 엔딩과 이미 받은 선택 보상 기록은 유지됩니다."
        )
        await render_season2(ctx, user)

    def battle_embed(user: dict, battle: dict) -> discord.Embed:
        expedition = ensure_v430(user)["expedition"]
        zone = EXPEDITION_ZONES[battle["zone"]]
        embed = discord.Embed(
            title=f"{zone['emoji']} 원정 전투 · {battle['enemy']}",
            description=(
                f"**{battle['zone']}**에서 교전 중입니다.\n"
                "`!원정 행동 공격` · `기술` · `방어` · `집중` · `응급` · `도주`"
            ),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="생존자",
            value=(
                f"❤️ {user['hp']} / {get_max_hp(user)}\n"
                f"`{_battle_bar(user['hp'], get_max_hp(user))}`\n"
                f"⚡ {user['stamina']} / {get_max_stamina(user)}"
            ),
            inline=True,
        )
        embed.add_field(
            name="적",
            value=(
                f"💀 {battle['enemy_hp']} / {battle['enemy_max_hp']}\n"
                f"`{_battle_bar(battle['enemy_hp'], battle['enemy_max_hp'])}`\n"
                f"{battle.get('enemy_rank', '일반')} · 턴 {battle['turn']} · 집중 {battle.get('focus', 0)}\n"
                f"기술 대기 {battle.get('skill_cooldown', 0)}턴"
            ),
            inline=True,
        )
        embed.add_field(
            name="원정 정보",
            value=(
                f"등급: **{expedition['rank']}**\n"
                f"평판: **{expedition['reputation']}**\n"
                f"응급 키트: **{expedition['kits']}개**\n"
                f"장착 유물: **{', '.join(expedition.get('equipped_relics', [])) or '없음'}**"
            ),
            inline=False,
        )
        recent = _copy_list(battle.get("log"))[-4:]
        if recent:
            embed.add_field(name="최근 전투 기록", value="\n".join(recent), inline=False)
        return embed

    def enemy_retaliation(user: dict, battle: dict, zone: dict, *, guarded: bool = False, weakened: bool = False) -> tuple:
        low, high = zone["enemy_attack"]
        scaling = max(0, _safe_int(user.get("level"), 1, 1) - zone["level"]) // 6
        attack_mult = float(battle.get("enemy_attack_mult", 1.0))
        damage = round(random.randint(low + scaling, high + scaling) * attack_mult)
        special = random.random() < (0.18 + (0.05 if battle.get("enemy_rank") == "정예" else 0.10 if battle.get("enemy_rank") == "보스" else 0.0))
        if special:
            damage = round(damage * 1.45)
        if guarded:
            damage = max(1, round(damage * 0.42))
        elif weakened:
            damage = max(1, round(damage * 0.72))
        bonus = relic_bonus(ensure_v430(user)["expedition"])
        defense = min(0.55, float(bonus.get("defense_pct", 0.0)))
        player_status = battle.setdefault("player_status", {})
        if _safe_int(player_status.get("armor_break"), 0, 0) > 0:
            defense *= 0.35
            player_status["armor_break"] = _safe_int(player_status.get("armor_break"), 0, 0) - 1
        battle["player_status"] = {k: v for k, v in player_status.items() if _safe_int(v, 0, 0) > 0}
        damage = max(1, round(damage * (1.0 - defense)))
        actual, knocked = apply_damage(user, damage)
        note = "💥 강공격" if special else "🩸 반격"
        status_note = maybe_inflict_player_status(battle, special) if not guarded else None
        battle.setdefault("log", []).append(f"{note}: HP -{actual}" + (f" · {status_note}" if status_note else ""))
        battle["log"] = battle["log"][-8:]
        return actual, knocked, special

    def record_expedition(expedition: dict, text: str) -> None:
        expedition["history"].append(f"{_utc_now().strftime('%m-%d %H:%M')} · {text}")
        expedition["history"] = expedition["history"][-20:]

    def finish_battle_victory(user: dict, expedition: dict, battle: dict) -> List[str]:
        zone = EXPEDITION_ZONES[battle["zone"]]
        bonus = relic_bonus(expedition)
        reward = random.randint(*zone["reward"])
        reputation = random.randint(*zone["rep"])
        streak_bonus = min(0.24, expedition["streak"] * 0.025)
        reward_mult = float(battle.get("reward_mult", 1.0)) * (1.0 + float(bonus.get("reward_pct", 0.0)))
        reward = max(1, round(reward * (1.0 + streak_bonus) * reward_mult))

        user["balance"] = _safe_int(user.get("balance"), 0, 0) + reward
        stats = user.setdefault("stats", {})
        stats["earned"] = _safe_int(stats.get("earned"), 0, 0) + reward
        stats["expedition_clears"] = _safe_int(stats.get("expedition_clears"), 0, 0) + 1

        material = random.choice(zone["materials"])
        amount = random.randint(1, 2 + max(1, zone["level"] // 12))
        materials = user.setdefault("materials", {})
        materials[material] = _safe_int(materials.get(material), 0, 0) + amount

        expedition["clears"] += 1
        expedition["zone_clears"][battle["zone"]] = _safe_int(expedition["zone_clears"].get(battle["zone"]), 0, 0) + 1
        expedition["streak"] += 1
        expedition["best_streak"] = max(expedition["best_streak"], expedition["streak"])
        expedition["reputation"] += reputation
        expedition["rank"] = expedition_rank(expedition["reputation"])
        add_season_points(user, 2 + zone["level"] // 10)
        progress_expedition_missions(expedition, "clear", 1)
        progress_expedition_missions(expedition, "material", amount)
        progress_expedition_missions(expedition, "streak", expedition["streak"])
        if battle.get("enemy_rank") == "보스":
            progress_expedition_missions(expedition, "boss", 1)

        lines = [
            f"🥫 식량 +**{reward:,}개**",
            f"🧰 {material} +**{amount}개**",
            f"🧭 원정 평판 +**{reputation}** → {expedition['reputation']}",
            f"🔥 연승 **{expedition['streak']}회**",
        ]
        if battle.get("enemy_rank") in {"정예", "보스"}:
            dust = 1 if battle.get("enemy_rank") == "정예" else 3
            expedition["relic_dust"] += dust
            lines.append(f"✨ {battle.get('enemy_rank')} 격파 보너스 · 유물 가루 +**{dust}개**")

        relic_chance = min(0.46, 0.08 + zone["level"] * 0.0055 + expedition["streak"] * 0.01 + float(bonus.get("relic_pct", 0.0)))
        if random.random() < relic_chance:
            relic = random.choice(zone["relics"])
            expedition["relics"][relic] = _safe_int(expedition["relics"].get(relic), 0, 0) + 1
            progress_expedition_missions(expedition, "relic", 1)
            lines.append(f"🏺 희귀 유물 획득: **{relic}**")

        if random.random() < 0.14:
            expedition["kits"] += 1
            lines.append("🩹 원정 응급 키트 +**1개**")

        expedition.setdefault("battle_results", []).append({
            "time": _utc_now().isoformat(),
            "zone": battle["zone"],
            "enemy": battle["enemy"],
            "rank": battle.get("enemy_rank", "일반"),
            "turns": _safe_int(battle.get("turn"), 1, 1),
            "reward": reward,
        })
        expedition["battle_results"] = expedition["battle_results"][-30:]
        record_expedition(expedition, f"{battle['zone']} 승리 · {battle['enemy']} · 식량 {reward:,}")
        expedition["battle"] = None
        return lines

    @bot.group(name="원정", aliases=["원정대"], invoke_without_command=True)
    async def expedition_group(ctx):
        """턴제 원정 전투와 원정대 성장 상태를 확인합니다."""
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        if expedition.pop("_v431_expired_battle", False):
            save_data()
            await ctx.send("🚑 6시간 이상 방치된 원정을 자동 종료하고 생존자를 구조했습니다.")
        battle = expedition.get("battle")
        if isinstance(battle, dict):
            await ctx.send(embed=battle_embed(user, battle))
            return
        next_rank = next((item for item in RANKS if item[0] > expedition["reputation"]), None)
        next_text = (
            f"다음 등급 **{next_rank[1]}**까지 {next_rank[0] - expedition['reputation']} 평판"
            if next_rank
            else "최고 등급 달성"
        )
        await ctx.send(
            "🧭 **[원정대 현황]**\n"
            f"등급: **{expedition['rank']}**\n"
            f"평판: **{expedition['reputation']}** · {next_text}\n"
            f"전적: 승리 **{expedition['clears']}** / 실패 **{expedition['fails']}** / 도주 **{expedition['escapes']}**\n"
            f"최고 연승: **{expedition['best_streak']}회**\n"
            f"응급 키트: **{expedition['kits']}개** · 유물 **{sum(expedition['relics'].values())}개**\n\n"
            "지역: `!원정 목록` · 출발: `!원정 출발 지역명` · 설명: `!원정 도움말`"
        )

    @expedition_group.command(name="도움말")
    async def expedition_help(ctx):
        if not await check_registered(ctx):
            return
        await ctx.send(
            "🧭 **[턴제 원정 도움말]**\n"
            "`!원정 목록` — 지역과 입장 조건 확인\n"
            "`!원정 출발 지하철잔해` — 스태미나를 사용해 전투 시작\n"
            "`!원정 행동 공격` — 기본 공격, 집중 수치가 있으면 추가 피해\n"
            "`!원정 행동 기술` — 강한 피해와 적 상태이상, 사용 후 3턴 재사용 대기\n"
            "`!원정 행동 방어` — 적의 다음 피해를 크게 감소\n"
            "`!원정 행동 집중` — 다음 공격 강화, 현재 턴에는 반격을 받음\n"
            "`!원정 행동 응급` — 원정 키트 1개로 HP 회복\n"
            "`!원정 행동 도주` — 확률적으로 전투 이탈\n"
            "`!원정 포기` — 전투를 즉시 종료하고 연승 초기화\n"
            "`!원정 보급` — 하루 한 번 응급 키트와 소량 식량 수령\n"
            "`!원정 유물` · `!원정 장비` · `!원정 임무` · `!원정 기록` · `!원정 랭킹`"
        )

    @expedition_group.command(name="목록")
    async def expedition_list(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        lines = ["🗺️ **[원정 지역 목록]**"]
        for name, zone in EXPEDITION_ZONES.items():
            level_ok = _safe_int(user.get("level"), 1, 1) >= zone["level"]
            rep_ok = expedition["reputation"] >= zone["reputation"]
            mark = "✅" if level_ok and rep_ok else "🔒"
            lines.append(
                f"{mark} {zone['emoji']} **{name}** · Lv.{zone['level']} · 평판 {zone['reputation']} · "
                f"스태미나 {zone['stamina']}\n　{zone['desc']}"
            )
        lines.append("\n출발: `!원정 출발 지역명`")
        await ctx.send("\n".join(lines))

    @expedition_group.command(name="출발")
    async def expedition_start(ctx, *, 지역명: str = ""):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        name = 지역명.strip().replace(" ", "")
        if expedition.get("battle"):
            await ctx.send("⚔️ 이미 원정 전투 중입니다. `!원정`으로 전투 상태를 확인하세요.")
            return
        if name not in EXPEDITION_ZONES:
            await ctx.send("⚠️ 존재하지 않는 원정 지역입니다. `!원정 목록`을 확인하세요.")
            return
        zone = EXPEDITION_ZONES[name]
        if _safe_int(user.get("level"), 1, 1) < zone["level"]:
            await ctx.send(f"🔒 **{name}**은 Lv.{zone['level']}부터 입장할 수 있습니다.")
            return
        if expedition["reputation"] < zone["reputation"]:
            await ctx.send(f"🔒 **{name}**은 원정 평판 **{zone['reputation']}**부터 입장할 수 있습니다.")
            return
        if not spend_stamina(user, zone["stamina"]):
            await ctx.send(
                f"⚡ 스태미나가 부족합니다. 필요 **{zone['stamina']}** / "
                f"현재 **{user['stamina']}**"
            )
            return

        player_level = _safe_int(user.get("level"), 1, 1)
        enemy_max = zone["enemy_hp"] + max(0, player_level - zone["level"]) * 4
        base_enemy = random.choice(zone["enemy"])
        enemy_data = prepare_enemy(expedition, name, base_enemy, enemy_max)
        expedition["battle"] = {
            "zone": name,
            **enemy_data,
            "turn": 1,
            "focus": 0,
            "log": [f"🚪 {name} 진입 · {enemy_data['enemy']} ({enemy_data['enemy_rank']}) 조우"],
            "started_at": _utc_now().isoformat(),
            "last_action_at": "",
        }
        enemy = enemy_data["enemy"]
        save_data()
        await ctx.send(
            f"{zone['emoji']} **[{name} 원정 출발]**\n"
            f"⚡ 스태미나 -**{zone['stamina']}** · 적 **{enemy}** 조우"
        )
        await ctx.send(embed=battle_embed(user, expedition["battle"]))

    @expedition_group.command(name="행동")
    async def expedition_action(ctx, *, 행동: str = ""):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        battle = expedition.get("battle")
        if not isinstance(battle, dict):
            await ctx.send("⚠️ 진행 중인 원정 전투가 없습니다. `!원정 출발 지역명`으로 시작하세요.")
            return

        action = 행동.strip().replace(" ", "")
        aliases = {
            "치료": "응급",
            "응급처치": "응급",
            "가드": "방어",
            "퇴각": "도주",
            "공격하기": "공격",
        }
        action = aliases.get(action, action)
        if action not in {"공격", "기술", "방어", "집중", "응급", "도주"}:
            await ctx.send("⚠️ 행동은 `공격 / 기술 / 방어 / 집중 / 응급 / 도주` 중 하나를 입력하세요.")
            return
        if action == "기술" and _safe_int(battle.get("skill_cooldown"), 0, 0) > 0:
            await ctx.send(f"⏳ 전술 기술 재사용까지 **{_safe_int(battle.get('skill_cooldown'), 0, 0)}턴** 남았습니다.")
            return
        if action == "응급":
            if expedition["kits"] <= 0:
                await ctx.send("🩹 원정 응급 키트가 없습니다. 하루 보급은 `!원정 보급`으로 받을 수 있습니다.")
                return
            if user["hp"] >= get_max_hp(user):
                await ctx.send("✨ HP가 이미 가득 찼습니다. 키트를 아껴두세요.")
                return

        now = _utc_now()
        last_action = battle.get("last_action_at")
        try:
            last_action_dt = datetime.fromisoformat(last_action) if last_action else None
        except (TypeError, ValueError):
            last_action_dt = None
        if last_action_dt and last_action_dt.tzinfo is None:
            last_action_dt = last_action_dt.replace(tzinfo=timezone.utc)
        if last_action_dt and (now - last_action_dt).total_seconds() < 1.2:
            await ctx.send("⏳ 같은 전투 행동이 너무 빠르게 입력됐습니다. 잠시 후 다시 시도하세요.")
            return
        battle["last_action_at"] = now.isoformat()

        zone = EXPEDITION_ZONES[battle["zone"]]
        power = max(1, _safe_int(calculate_user_power(user), 1, 1))
        bonus = relic_bonus(expedition)
        result_lines: List[str] = apply_player_turn_status(user, battle, apply_damage)

        # 플레이어 기술로 부여된 적 상태이상은 다음 행동 시작 시 처리합니다.
        enemy_status = battle.setdefault("enemy_status", {})
        enemy_vulnerable = action in {"공격", "기술"} and _safe_int(enemy_status.get("방어 붕괴"), 0, 0) > 0
        for status_name, label, base_damage in (("출혈", "🩸 적 출혈", 5), ("중독", "☠️ 적 중독", 7)):
            turns = _safe_int(enemy_status.get(status_name), 0, 0)
            if turns > 0:
                tick = base_damage + max(0, _safe_int(battle.get("turn"), 1, 1) // 4)
                battle["enemy_hp"] = max(0, _safe_int(battle.get("enemy_hp"), 0, 0) - tick)
                enemy_status[status_name] = turns - 1
                result_lines.append(f"{label} 지속 피해 **{tick}**")
        if enemy_vulnerable:
            enemy_status["방어 붕괴"] = _safe_int(enemy_status.get("방어 붕괴"), 0, 0) - 1
            result_lines.append("🛡️ 적의 방어 붕괴로 이번 공격 피해가 증가합니다.")
        battle["enemy_status"] = {k: v for k, v in enemy_status.items() if _safe_int(v, 0, 0) > 0}

        knocked = user.get("hp", 1) <= 1 and any("쓰러" in line for line in result_lines)
        stunned = any("기절 상태" in line for line in result_lines)
        if knocked:
            expedition["fails"] += 1
            expedition["streak"] = 0
            record_expedition(expedition, f"{battle['zone']} 실패 · 상태이상으로 구조됨")
            expedition["battle"] = None
            save_data()
            await ctx.send("\n".join(result_lines + ["🚑 상태이상 피해로 쓰러져 구조됐습니다."]))
            return

        if battle["enemy_hp"] <= 0:
            reward_lines = finish_battle_victory(user, expedition, battle)
            save_data()
            embed = discord.Embed(
                title=f"🏆 {battle['zone']} 원정 승리",
                description=f"**{battle['enemy']}**이(가) 상태이상 피해로 쓰러졌습니다.",
                color=discord.Color.gold(),
            )
            embed.add_field(name="전투 결과", value="\n".join(result_lines), inline=False)
            embed.add_field(name="원정 보상", value="\n".join(reward_lines), inline=False)
            await ctx.send(embed=embed)
            return
        if stunned:
            actual, knocked, _ = enemy_retaliation(user, battle, zone)
            result_lines.append(f"🩸 행동 불능 중 받은 피해 **{actual}**")
            battle["turn"] = _safe_int(battle.get("turn"), 1, 1) + 1
            if knocked:
                expedition["fails"] += 1
                expedition["streak"] = 0
                record_expedition(expedition, f"{battle['zone']} 실패 · 기절 중 구조됨")
                expedition["battle"] = None
                save_data()
                await ctx.send("\n".join(result_lines + ["🚑 기절 중 적의 공격으로 쓰러져 구조됐습니다."]))
                return
            save_data()
            await ctx.send("\n".join(result_lines), embed=battle_embed(user, battle))
            return

        if action == "공격":
            focus = _safe_int(battle.get("focus"), 0, 0)
            base = max(8, round(power * 0.58 * (1.0 + float(bonus.get("attack_pct", 0.0)))) + _safe_int(user.get("level"), 1, 1))
            damage = random.randint(max(5, round(base * 0.82)), max(8, round(base * 1.18)))
            if enemy_vulnerable:
                damage = round(damage * 1.15)
            critical = random.random() < min(0.34, 0.08 + power / 900 + float(bonus.get("crit", 0.0)))
            if critical:
                damage = round(damage * 1.65)
            if focus:
                damage = round(damage * (1 + min(0.75, focus * 0.25)))
                battle["focus"] = 0
            battle["enemy_hp"] = max(0, battle["enemy_hp"] - damage)
            prefix = "💢 치명타" if critical else "⚔️ 공격"
            result_lines.append(f"{prefix}: **{damage} 피해**")
            battle.setdefault("log", []).append(f"{prefix} · 적 HP -{damage}")
            status_chance = min(0.25, float(bonus.get("status_chance", 0.0)))
            if battle["enemy_hp"] > 0 and status_chance > 0 and random.random() < status_chance:
                status = random.choice(["출혈", "중독", "방어 붕괴"])
                battle.setdefault("enemy_status", {})[status] = max(
                    1, _safe_int(battle.setdefault("enemy_status", {}).get(status), 0, 0)
                )
                result_lines.append(f"✨ 유물 효과로 적에게 **{status} 1턴**을 부여했습니다.")
            progress_expedition_missions(expedition, "damage", damage)
            if battle["enemy_hp"] > 0:
                _, knocked, _ = enemy_retaliation(user, battle, zone)

        elif action == "기술":
            base = max(12, round(power * 0.92 * (1.0 + float(bonus.get("attack_pct", 0.0)))))
            damage = random.randint(max(8, round(base * 0.90)), max(12, round(base * 1.12)))
            if enemy_vulnerable:
                damage = round(damage * 1.15)
            battle["enemy_hp"] = max(0, battle["enemy_hp"] - damage)
            battle["skill_cooldown"] = 3
            status = random.choice(["출혈", "중독", "방어 붕괴"])
            battle.setdefault("enemy_status", {})[status] = 2
            result_lines.append(f"⚡ 전술 기술: **{damage} 피해** · 적에게 **{status} 2턴**")
            battle.setdefault("log", []).append(f"⚡ 전술 기술 · 적 HP -{damage} · {status}")
            progress_expedition_missions(expedition, "damage", damage)
            progress_expedition_missions(expedition, "skill", 1)
            if battle["enemy_hp"] > 0:
                _, knocked, _ = enemy_retaliation(user, battle, zone)

        elif action == "방어":
            progress_expedition_missions(expedition, "guard", 1)
            result_lines.append("🛡️ 자세를 낮추고 적의 공격을 받아냈습니다.")
            actual, knocked, special = enemy_retaliation(user, battle, zone, guarded=True)
            result_lines.append(f"받은 피해: **{actual}**" + (" · 적 강공격을 막아냈습니다." if special else ""))

        elif action == "집중":
            battle["focus"] = min(3, _safe_int(battle.get("focus"), 0, 0) + 1)
            result_lines.append(f"🎯 집중 수치가 **{battle['focus']}**이 되었습니다. 다음 공격이 강화됩니다.")
            _, knocked, _ = enemy_retaliation(user, battle, zone, weakened=True)

        elif action == "응급":
            max_hp = get_max_hp(user)
            expedition["kits"] -= 1
            before = user["hp"]
            heal = round(random.randint(max(18, max_hp // 5), max(28, max_hp // 3)) * (1.0 + float(bonus.get("heal_pct", 0.0))))
            user["hp"] = min(max_hp, user["hp"] + heal)
            result_lines.append(f"🩹 HP +**{user['hp'] - before}** · 남은 키트 **{expedition['kits']}개**")
            _, knocked, _ = enemy_retaliation(user, battle, zone, weakened=True)

        elif action == "도주":
            chance = min(0.88, 0.46 + max(0, _safe_int(user.get("level"), 1, 1) - zone["level"]) * 0.012 + float(bonus.get("escape", 0.0)))
            if random.random() < chance:
                expedition["escapes"] += 1
                expedition["streak"] = 0
                record_expedition(expedition, f"{battle['zone']} 도주 · {battle['enemy']}")
                expedition["battle"] = None
                save_data()
                await ctx.send("🏃 **원정에서 안전하게 이탈했습니다.** 보상은 없고 연승은 초기화됩니다.")
                return
            result_lines.append("⛔ 퇴로가 막혀 도주에 실패했습니다.")
            _, knocked, _ = enemy_retaliation(user, battle, zone)

        if action != "기술" and _safe_int(battle.get("skill_cooldown"), 0, 0) > 0:
            battle["skill_cooldown"] = max(0, _safe_int(battle.get("skill_cooldown"), 0, 0) - 1)
        battle["turn"] = _safe_int(battle.get("turn"), 1, 1) + 1
        battle["log"] = _copy_list(battle.get("log"))[-8:]

        if battle["enemy_hp"] <= 0:
            reward_lines = finish_battle_victory(user, expedition, battle)
            save_data()
            embed = discord.Embed(
                title=f"🏆 {battle['zone']} 원정 승리",
                description=f"**{battle['enemy']}**을 격파했습니다.",
                color=discord.Color.gold(),
            )
            embed.add_field(name="전투 결과", value="\n".join(result_lines), inline=False)
            embed.add_field(name="원정 보상", value="\n".join(reward_lines), inline=False)
            await ctx.send(embed=embed)
            return

        if knocked:
            expedition["fails"] += 1
            expedition["streak"] = 0
            record_expedition(expedition, f"{battle['zone']} 실패 · {battle['enemy']}에게 구조됨")
            expedition["battle"] = None
            save_data()
            await ctx.send(
                "🚑 **원정 실패**\n"
                f"{battle['enemy']}의 공격으로 쓰러졌지만 구조대가 회수했습니다.\n"
                f"현재 HP **{user['hp']} / {get_max_hp(user)}** · 연승 초기화"
            )
            return

        save_data()
        await ctx.send("\n".join(result_lines), embed=battle_embed(user, battle))

    @expedition_group.command(name="포기")
    async def expedition_abandon(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        battle = expedition.get("battle")
        if not isinstance(battle, dict):
            await ctx.send("⚠️ 포기할 원정 전투가 없습니다.")
            return
        expedition["fails"] += 1
        expedition["streak"] = 0
        record_expedition(expedition, f"{battle['zone']} 포기 · {battle['enemy']}")
        expedition["battle"] = None
        save_data()
        await ctx.send("🏳️ 원정을 포기했습니다. 사용한 스태미나는 돌아오지 않고 연승은 초기화됩니다.")

    @expedition_group.command(name="보급")
    async def expedition_supply(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        today = _today_key()
        if expedition.get("last_supply") == today:
            await ctx.send("📦 오늘 원정 보급은 이미 수령했습니다. 다음 UTC 날짜에 다시 받을 수 있습니다.")
            return
        food = 350 + min(1800, expedition["reputation"] * 9)
        kits = 1 + (1 if expedition["rank"] in {"방주 추적자", "종말 원정대장"} else 0)
        user["balance"] = _safe_int(user.get("balance"), 0, 0) + food
        user.setdefault("stats", {})["earned"] = _safe_int(user.setdefault("stats", {}).get("earned"), 0, 0) + food
        expedition["kits"] += kits
        expedition["last_supply"] = today
        save_data()
        await ctx.send(
            "📦 **[일일 원정 보급]**\n"
            f"🥫 식량 +**{food:,}개**\n"
            f"🩹 원정 응급 키트 +**{kits}개**\n"
            f"현재 보유 키트 **{expedition['kits']}개**"
        )

    @expedition_group.command(name="유물")
    async def expedition_relics(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        if not expedition["relics"]:
            await ctx.send("🏺 아직 발견한 원정 유물이 없습니다. 위험 지역일수록 유물 확률이 높습니다.")
            return
        lines = [f"🏺 **[{ctx.author.display_name}의 원정 유물]**"]
        for name, amount in sorted(expedition["relics"].items()):
            desc = RELIC_DESCRIPTIONS.get(name, "출처가 확인되지 않은 원정 유물.")
            lines.append(f"• **{name}** ×{amount} — {desc}")
        lines.append(f"\n총 유물 **{sum(expedition['relics'].values())}개**")
        await ctx.send("\n".join(lines))

    @expedition_group.command(name="기록")
    async def expedition_history(ctx):
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        expedition = ensure_v430(user)["expedition"]
        if not expedition["history"]:
            await ctx.send("📜 아직 원정 기록이 없습니다.")
            return
        await ctx.send("📜 **[최근 원정 기록]**\n" + "\n".join(f"• {item}" for item in expedition["history"][-12:]))

    @expedition_group.command(name="랭킹")
    async def expedition_ranking(ctx):
        if not await check_registered(ctx):
            return
        if not ctx.guild:
            await ctx.send("⚠️ 원정 랭킹은 서버 안에서만 확인할 수 있습니다.")
            return
        ranking = []
        for member in ctx.guild.members:
            if member.bot:
                continue
            candidate = get_user(member.id)
            if not isinstance(candidate, dict):
                continue
            expedition = ensure_v430(candidate)["expedition"]
            if expedition["reputation"] <= 0 and expedition["clears"] <= 0:
                continue
            ranking.append((expedition["reputation"], expedition["clears"], member.display_name, expedition["rank"]))
        ranking.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not ranking:
            await ctx.send("🏆 아직 이 서버에 원정 기록이 없습니다.")
            return
        lines = ["🏆 **[서버 원정 평판 랭킹]**"]
        medals = ["🥇", "🥈", "🥉"]
        for index, (rep, clears, name, rank_name) in enumerate(ranking[:10], start=1):
            mark = medals[index - 1] if index <= 3 else f"{index}."
            lines.append(f"{mark} **{name}** · 평판 {rep} · 승리 {clears} · {rank_name}")
        await ctx.send("\n".join(lines))

    print(
        "[V4.3.1 원정 코어 등록 확인] "
        f"시즌2={bot.get_command('시즌2') is not None} "
        f"원정={bot.get_command('원정') is not None}",
        flush=True,
    )
