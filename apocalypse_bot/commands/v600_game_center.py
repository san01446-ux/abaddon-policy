from __future__ import annotations

import asyncio
import inspect
import os
import shlex
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union, get_args, get_origin

import discord
from discord.ext import commands

from apocalypse_bot.commands.v430_story_expedition import ensure_v430
from apocalypse_bot.commands.story_progression import can_access_season, locked_text


VERSION = "10.6.0"
MENU_TIMEOUT = 300
SELECT_PAGE_SIZE = 25
STORY3_START_NODE = "eclipse_signal"


def _real_cog(command: commands.Command) -> Optional[commands.Cog]:
    """Return only an actual Cog instance; discord.py MISSING sentinels are never contexts."""
    cog = getattr(command, "cog", None)
    return cog if isinstance(cog, commands.Cog) else None


def _schedule_delete(message: Any, delay: Any) -> None:
    try:
        seconds = float(delay)
    except (TypeError, ValueError):
        return
    if seconds <= 0 or message is None or not hasattr(message, "delete"):
        return

    async def _delete() -> None:
        await asyncio.sleep(seconds)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
            pass

    try:
        asyncio.create_task(_delete())
    except RuntimeError:
        pass


_UI_FAILURE_NOTICE: Dict[Tuple[int, str], float] = {}

def _allow_failure_notice(user_id: int, command_name: str, *, window: float = 3.0) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    key = (int(user_id), str(command_name))
    previous = float(_UI_FAILURE_NOTICE.get(key, 0.0) or 0.0)
    _UI_FAILURE_NOTICE[key] = now
    for old_key, old_time in list(_UI_FAILURE_NOTICE.items()):
        if now - old_time > 30:
            _UI_FAILURE_NOTICE.pop(old_key, None)
    return now - previous > window


# =========================================================
# 게임 드롭다운 카탈로그
# =========================================================
@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    description: str
    command: str
    example: str = ""
    force_modal: bool = False


def _a(key: str, label: str, description: str, command: str, example: str = "", *, force_modal: bool = False) -> ActionSpec:
    return ActionSpec(key, label, description, command, example, force_modal)


GAME_CATEGORIES: Mapping[str, Tuple[str, str, Sequence[ActionSpec]]] = {
    "survival": (
        "🧭 생존·성장",
        "가입 이후 기본 성장, 직업, 상태, 퀘스트와 시즌 보상을 관리합니다.",
        (
            _a("info", "내 정보", "레벨·경험치·직업·전투력을 확인합니다.", "정보"),
            _a("wallet", "지갑", "현재 보유 식량과 금융 상태를 확인합니다.", "지갑"),
            _a("attendance", "출석", "오늘의 출석을 진행합니다.", "출석"),
            _a("attendance_reward", "출석 누적 보상", "출석 연속 보상을 확인·수령합니다.", "출석보상"),
            _a("support", "긴급 지원금", "조건에 맞으면 생존 지원금을 받습니다.", "돈주세요"),
            _a("status", "상태 확인", "HP·스태미나·감염·상태이상을 확인합니다.", "상태"),
            _a("rest", "휴식", "스태미나와 상태를 회복합니다.", "휴식"),
            _a("jobs", "직업 목록", "선택 가능한 직업을 확인합니다.", "직업목록"),
            _a("job_choose", "직업 선택", "직업명을 입력해 직업을 선택합니다.", "직업선택", "예: 정찰병", force_modal=True),
            _a("job_info", "직업 정보", "특정 직업의 능력을 확인합니다.", "직업정보", "예: 의무병", force_modal=True),
            _a("job_change", "직업 변경", "조건을 충족하면 직업을 변경합니다.", "직업변경", "예: 기술자", force_modal=True),
            _a("tutorial", "튜토리얼", "튜토리얼 진행 상태를 확인합니다.", "튜토리얼"),
            _a("growth_board", "성장 루프 보드", "일일·주간 미션, 연속 달성, 참여 점수를 이모지 진행률로 확인합니다.", "성장보드"),
            _a("mission_reward_v710", "성장 미션 보상", "완료한 일일·주간 성장 루프 보상을 한 번에 받습니다.", "미션보상"),
            _a("lifetime_reward_v710", "누적 참여 보상", "누적 참여 점수 이정표 보상을 확인하고 수령합니다.", "누적보상"),
            _a("catchup_support_v710", "신규·복귀 보급", "신규 또는 14일 이상 복귀 생존자의 따라잡기 보급을 확인합니다.", "복귀보급"),
            _a("daily_quest", "일일 퀘스트", "오늘의 임무와 진행도를 확인합니다.", "일일퀘스트"),
            _a("daily_reward", "일일 퀘스트 보상", "완료한 일일 퀘스트 보상을 받습니다.", "퀘스트보상"),
            _a("weekly_quest", "주간 퀘스트", "이번 주 임무와 진행도를 확인합니다.", "주간퀘스트"),
            _a("weekly_reward", "주간 퀘스트 보상", "완료한 주간 퀘스트 보상을 받습니다.", "주간보상"),
            _a("season_pass", "시즌 패스", "시즌 포인트와 보상 단계를 확인합니다.", "시즌패스"),
            _a("season_reward", "시즌 보상 수령", "보상 레벨을 입력해 수령합니다.", "시즌보상", "예: 5", force_modal=True),
            _a("achievements", "업적", "보유 업적을 확인합니다.", "업적"),
            _a("titles", "칭호 목록", "보유한 칭호를 확인합니다.", "칭호목록"),
            _a("title_set", "칭호 장착", "칭호 이름을 입력해 대표 칭호를 바꿉니다.", "칭호", "예: 두 번째 새벽의 인도자", force_modal=True),
            _a("ranking", "종합 랭킹", "서버 성장 랭킹을 확인합니다.", "랭킹"),
        ),
    ),
    "equipment": (
        "⚒️ 장비·제작",
        "상점, 인벤토리, 장착, 강화, 옵션과 제작 기능을 사용합니다.",
        (
            _a("shop", "장비 상점", "장비 상점을 확인합니다.", "상점", "선택: 티어 예) 3", force_modal=False),
            _a("equipment_list", "장비 목록", "티어별 장비 목록을 확인합니다.", "장비목록", "선택: 티어 예) 4", force_modal=False),
            _a("buy", "장비 구매", "아이템 이름을 입력해 구매합니다.", "구매", "예: 생존자 장검", force_modal=True),
            _a("inventory", "인벤토리", "보유 아이템을 확인합니다.", "인벤토리"),
            _a("equipment", "장착 현황", "현재 장착 장비와 전투력을 확인합니다.", "장비"),
            _a("equip", "장비 장착", "아이템 이름을 입력해 장착합니다.", "장착", "예: 생존자 장검", force_modal=True),
            _a("unequip", "장비 해제", "슬롯 또는 아이템 이름으로 해제합니다.", "해제", "예: 무기", force_modal=True),
            _a("discard", "아이템 버리기", "아이템을 인벤토리에서 제거합니다.", "버리기", "예: 낡은 단검", force_modal=True),
            _a("identify", "아이템 감정", "미감정 장비를 감정합니다.", "감정", "예: 봉인된 총검", force_modal=True),
            _a("enhance", "장비 강화", "장비 이름을 입력해 강화합니다.", "강화", "예: 생존자 장검", force_modal=True),
            _a("enhance_info", "강화 정보", "장비 강화 단계와 확률을 확인합니다.", "강화정보", "예: 생존자 장검", force_modal=True),
            _a("protected_enhance", "보호 강화", "보호 재료를 사용해 강화합니다.", "보호강화", "예: 생존자 장검", force_modal=True),
            _a("equipment_option", "장비 옵션", "장비의 랜덤 옵션을 확인합니다.", "장비옵션", "예: 생존자 장검", force_modal=True),
            _a("reroll_option", "옵션 재설정", "장비 옵션을 다시 설정합니다.", "옵션재설정", "예: 생존자 장검", force_modal=True),
            _a("set_effect", "세트 효과", "현재 적용 가능한 세트 효과를 확인합니다.", "세트효과"),
            _a("equipment_preset_v710", "장비 프리셋", "레이드·생활·탐색 장비 구성을 최대 3개 저장하고 적용합니다.", "장비프리셋"),
            _a("materials", "재료 보관함", "보유 제작 재료를 확인합니다.", "재료"),
            _a("craft_list", "제작 목록", "제작 가능한 아이템을 확인합니다.", "제작목록"),
            _a("craft", "아이템 제작", "아이템 이름을 입력해 제작합니다.", "제작", "예: 응급 키트", force_modal=True),
            _a("new_gear", "신규 장비 도감", "최신 추가 장비를 티어별로 확인합니다.", "신규장비", "선택: 티어 예) 7", force_modal=False),
            _a("durability", "무기 내구도", "장착 무기의 내구도와 현재 출력·개조 부품을 확인합니다.", "내구도", "선택: 장비명", force_modal=False),
            _a("repair_weapon", "무기 수리", "수리 키트와 자원을 사용해 무기 내구도를 복구합니다.", "무기수리", "선택: 장비명", force_modal=False),
            _a("mod_list", "개조 부품 목록", "제작·장착 가능한 무기 부품 6종을 확인합니다.", "개조목록"),
            _a("craft_mod", "개조 부품 제작", "부품명을 입력해 개조 부품을 제작합니다.", "개조부품제작", "예: 소음기", force_modal=True),
            _a("install_mod", "무기 개조", "보유 무기에 제작한 부품을 장착합니다.", "무기개조", "예: 개조소총 소음기", force_modal=True),
            _a("economy_balance", "경제 밸런스 안내", "현재 성장·가격 밸런스를 확인합니다.", "경제밸런스"),
            _a("enhance_rank", "강화 랭킹", "서버 내 강화 기록 랭킹을 확인합니다.", "강화랭킹"),
        ),
    ),
    "combat": (
        "⚔️ 전투·지역",
        "훈련, 던전, 일반 레이드, PVP와 지역 탐색을 실행합니다.",
        (
            _a("training", "훈련", "기본 전투 훈련을 진행합니다.", "훈련"),
            _a("monsters", "괴물 목록", "난이도별 괴물을 확인합니다.", "괴물목록", "선택: 쉬움/보통/어려움", force_modal=False),
            _a("dungeon", "던전", "난이도를 입력해 던전에 도전합니다.", "던전", "예: 보통", force_modal=True),
            _a("deep_dungeon", "심층 던전", "층수를 입력해 심층 던전에 도전합니다.", "심층던전", "예: 5", force_modal=True),
            _a("dungeon_record", "던전 기록", "심층 던전 최고 기록을 확인합니다.", "던전기록"),
            _a("boss_codex", "보스 도감", "발견한 보스 정보를 확인합니다.", "보스도감"),
            _a("raid", "레이드 현황", "진행 중인 레이드를 확인합니다.", "레이드"),
            _a("raid_attack", "레이드 공격", "진행 중인 레이드를 공격합니다.", "레이드공격"),
            _a("pvp", "PVP", "상대 멘션 또는 ID를 입력해 대결합니다.", "pvp", "예: @상대", force_modal=True),
            _a("region_list", "지역 목록", "이동 가능한 지역을 확인합니다.", "지역목록"),
            _a("region_info", "지역 정보", "특정 지역의 위험도와 보상을 확인합니다.", "지역정보", "예: 폐허도심", force_modal=True),
            _a("region_move", "지역 이동", "지역명을 입력해 이동합니다.", "지역이동", "예: 침수지구", force_modal=True),
            _a("region_explore", "지역 탐색", "현재 지역을 탐색합니다.", "지역탐색"),
            _a("zombie_codex", "좀비 도감", "지역별 좀비 도감을 확인합니다.", "좀비도감", "예: 폐허도심", force_modal=True),
            _a("invasion", "침공 현황", "서버 침공 상태를 확인합니다.", "침공"),
            _a("invasion_join", "침공 참전", "진행 중인 침공에 참가합니다.", "참전"),
            _a("invasion_attack", "침공 공격", "침공 보스를 공격합니다.", "침공공격"),
            _a("invasion_rank", "침공 랭킹", "침공 피해 랭킹을 확인합니다.", "침공랭킹"),
            _a("invasion_shop", "침공 상점", "침공 토큰 상점을 확인합니다.", "침공상점"),
        ),
    ),
    "worldboss": (
        "🌋 월드보스·레이드",
        "실제 약점·페이즈·부위 기믹과 안전한 보상 큐를 사용하는 6종 서버 공동 보스를 관리합니다.",
        (
            _a("worldboss_status", "현재 월드보스", "활성 보스의 HP, 페이즈, 약점과 TOP 5를 확인합니다.", "월드보스"),
            _a("worldboss_attack_v630", "월드보스 공격", "하루 10회, 45초 간격으로 공동 보스를 공격합니다.", "월드보스공격"),
            _a("worldboss_contribution", "내 기여도", "누적 피해, 현재 순위와 오늘 남은 공격을 확인합니다.", "월드보스기여도"),
            _a("worldboss_ranking_v630", "현재 전투 순위", "현재 전투의 누적 피해 순위를 확인합니다.", "보스랭킹"),
            _a("worldboss_weekly_rank_v710", "주간 누적 랭킹", "이번 주 서버 월드보스 누적 피해와 공격 횟수를 확인합니다.", "월드보스주간랭킹"),
            _a("worldboss_weekly_reward_v710", "지난주 랭킹 보상", "지난주 월드보스 누적 순위 보상을 수령합니다.", "월드보스주간보상"),
            _a("worldboss_reward", "보상 수령", "새 보스가 출현해도 보존되는 보상 큐에서 오래된 보상부터 수령합니다.", "월드보스보상"),
            _a("worldboss_reward_list", "미수령 보상 목록", "보상 큐에 저장된 미수령 전투를 확인합니다.", "월드보스보상목록"),
            _a("worldboss_list", "보스 6종 목록", "보스별 HP, 특성, 약점과 전용 재료를 확인합니다.", "월드보스목록"),
            _a("worldboss_codex_v630", "내 월드보스 도감", "보스별 누적 피해·공격·처치 기록을 확인합니다.", "월드보스도감"),
            _a("worldboss_spawn_admin", "관리자 보스 소환", "보스명을 입력해 서버 공동 보스를 소환합니다.", "월드보스리셋", "예: 아틀라스", force_modal=True),
            _a("worldboss_test_admin", "관리자 테스트 소환", "실전 슬롯·경제·내구도·도감과 분리된 HP 50,000 샌드박스 보스를 소환합니다.", "월드보스테스트", "예: 문지기", force_modal=True),
            _a("worldboss_test_status", "테스트 상태", "독립 테스트 보스의 HP와 기믹을 확인합니다.", "월드보스테스트상태"),
            _a("worldboss_test_attack", "테스트 공격", "실전 기록에 영향 없이 테스트 보스를 공격합니다.", "월드보스테스트공격"),
        ),
    ),
    "expedition": (
        "🧭 원정·유물",
        "턴제 원정, 전투 행동, 유물 성장과 임무를 관리합니다.",
        (
            _a("expedition", "원정 현황", "현재 원정대와 전투 상태를 확인합니다.", "원정"),
            _a("exp_help", "원정 도움말", "원정 전투 행동을 확인합니다.", "원정 도움말"),
            _a("exp_list", "원정 지역 목록", "원정 지역과 입장 조건을 확인합니다.", "원정 목록"),
            _a("exp_start", "원정 출발", "지역명을 입력해 원정을 시작합니다.", "원정 출발", "예: 지하철잔해", force_modal=True),
            _a("exp_action", "원정 행동", "공격·기술·방어·집중·응급·도주 중 하나를 입력합니다.", "원정 행동", "예: 공격", force_modal=True),
            _a("tactical_combat", "전술 전투", "버튼으로 공격·기술·방어·응급·도주를 선택합니다.", "전투", "예: 보통", force_modal=True),
            _a("tactical_dungeon", "던전 전술", "던전을 버튼형 전술 전투로 진행합니다.", "던전전술", "예: 강함", force_modal=True),
            _a("exp_abandon", "원정 포기", "현재 전투를 포기합니다.", "원정 포기"),
            _a("exp_supply", "원정 보급", "일일 응급 키트와 식량을 받습니다.", "원정 보급"),
            _a("exp_relic", "원정 유물", "원정에서 발견한 유물을 확인합니다.", "원정 유물"),
            _a("exp_record", "원정 기록", "최근 원정 결과를 확인합니다.", "원정 기록"),
            _a("exp_rank", "원정 랭킹", "원정 평판 랭킹을 확인합니다.", "원정 랭킹"),
            _a("exp_gear", "원정 장비", "장착 유물과 합산 효과를 확인합니다.", "원정 장비"),
            _a("exp_mission", "원정 임무", "일일 또는 주간 원정 임무를 확인합니다.", "원정 임무", "선택: 주간", force_modal=False),
            _a("exp_mission_reward", "원정 임무 보상", "구분과 번호를 입력해 보상을 받습니다.", "원정 임무보상", "예: 일일 1", force_modal=True),
            _a("exp_recovery", "원정 복구", "오래 방치된 전투 상태를 점검합니다.", "원정 복구"),
            _a("relic", "유물 보관함", "보유 유물과 강화 상태를 확인합니다.", "유물"),
            _a("relic_equip", "유물 장착", "유물 이름을 입력해 장착합니다.", "유물 장착", "예: 새벽 송신기", force_modal=True),
            _a("relic_unequip", "유물 해제", "장착한 유물을 해제합니다.", "유물 해제", "예: 새벽 송신기", force_modal=True),
            _a("relic_enhance", "유물 강화", "유물 가루로 유물을 강화합니다.", "유물 강화", "예: 새벽 송신기", force_modal=True),
            _a("relic_dismantle", "유물 분해", "유물 이름과 수량을 입력합니다.", "유물 분해", "예: 깨진 노선표 2", force_modal=True),
            _a("life_mastery", "생활 숙련도", "생활·원정 성장 기록을 확인합니다.", "생활숙련도"),
            _a("overall_rank", "종합 랭킹", "다양한 성장 지표의 종합 랭킹을 확인합니다.", "종합랭킹"),
        ),
    ),
    "life": (
        "🌲 생활·기지",
        "알바, 채집, 낚시, 벌목, 광산과 기지 성장 기능을 사용합니다.",
        (
            _a("work", "알바", "생존 식량을 벌기 위한 알바를 진행합니다.", "알바"),
            _a("coin", "희귀 코인 탐색", "폐허에서 희귀 코인을 찾습니다.", "코인"),
            _a("gather", "채집", "약초와 생활 자원을 채집합니다.", "채집"),
            _a("fish", "낚시", "물고기와 희귀 자원을 낚습니다.", "낚시"),
            _a("lumber", "벌목", "기지용 나무를 획득합니다.", "벌목"),
            _a("mine", "광산", "광석과 고철을 채굴합니다.", "광산"),
            _a("resources", "자원 현황", "보유 생활 자원을 확인합니다.", "자원"),
            _a("encounter_codex", "인카운트 도감", "알바·땅파기·채집·벌목 중 발견한 조우 기록을 확인합니다.", "인카운트도감"),
            _a("farming_menu", "폐허 파밍", "지역을 고르고 물자 회수 또는 랜덤 인카운트를 진행합니다.", "파밍"),
            _a("farming_regions", "파밍 지역", "레벨·위험도·주요 회수 물자를 확인합니다.", "파밍지역"),
            _a("farming_start", "파밍 출발", "마트·주거구역·화물역·격리구역 중 하나로 출발합니다.", "파밍출발", "예: 화물역", force_modal=True),
            _a("farming_choice", "인카운트 선택", "접촉 대상에 맞춰 합류·지원·돌파·우회·공동 수색 등 현장 행동을 선택합니다.", "파밍선택", "예: 합류", force_modal=True),
            _a("farming_history", "파밍 기록", "회수 결과와 인카운트 선택 기록을 확인합니다.", "파밍기록"),
            _a("farming_encounter_codex_v811", "파밍 인카운트 도감", "직접 발견한 우호 세력·구조 요청·위험·미확인 접촉을 확인합니다.", "파밍인카운트도감"),
            _a("workshop", "폐허 복구 공방", "미감정 폐품과 감정 완료 폐품을 확인합니다.", "공방"),
            _a("scrap_identify", "폐품 감정", "미감정 폐품을 분석해 복구 대상을 확인합니다.", "폐품감정", "선택: 폐품 ID", force_modal=False),
            _a("scrap_dismantle", "폐품 분해", "감정 완료 폐품을 분해해 생활 재료를 회수합니다.", "폐품분해", "선택: 폐품 ID", force_modal=False),
            _a("scrap_repair", "폐품 수리", "감정 완료 폐품을 복구해 완제품 정산을 시도합니다.", "폐품수리", "선택: 폐품 ID", force_modal=False),
            _a("signal_search_v770", "전파 탐색", "폐허 신호 퍼즐을 찾아 해독 대기 상태로 저장합니다.", "전파탐색"),
            _a("signal_decode_v770", "신호 해독", "수신 후보 번호를 선택해 신호를 해독합니다.", "신호해독", "예: 3", force_modal=True),
            _a("signal_history_v770", "주파수 기록", "해독 기록과 연구 자료를 확인합니다.", "주파수기록"),
            _a("contract_board", "의뢰 게시판", "매일 바뀌는 생존 물자 납품 계약을 확인합니다.", "의뢰게시판"),
            _a("contract_accept", "계약 수락", "오늘의 계약 번호 하나를 선택합니다.", "계약수락", "예: 2", force_modal=True),
            _a("contract_deliver", "계약 납품", "수락한 계약의 자원을 제출하고 정산합니다.", "납품"),
            _a("contract_status", "계약 현황", "오늘 완료·수락 중인 계약을 확인합니다.", "계약현황"),
            _a("laboratory", "생활 연구소", "연구 자료·설계도 조각과 생활 기술을 확인합니다.", "연구소"),
            _a("research_start", "연구 시작", "생활 기술 하나를 선택해 연구를 시작합니다.", "연구시작", "예: 폐품회수", force_modal=True),
            _a("research_progress", "연구 진행", "진행 중 연구의 남은 시간과 완료 상태를 확인합니다.", "연구진행"),
            _a("blueprints", "생활 설계도", "해금한 생활 기술과 잠긴 설계도를 확인합니다.", "설계도"),
            _a("v770_stability", "v7.8 파밍 안정화 검수", "파밍·인카운트·공방·계약·연구 저장 구조와 진행 연출을 읽기 전용 검사합니다.", "770안정화검수"),
            _a("v811_stability", "v8.1.1 인카운트 검수", "인카운트 다양성·우호 세력·동적 버튼·이모지 프레임 연출을 읽기 전용 검사합니다.", "811안정화검수"),
            _a("disaster_status", "서버 공동 재난", "현재 서버 재난과 공동 대응 진행도를 확인합니다.", "재난상황"),
            _a("disaster_missions", "재난 대응 임무", "현장 역할과 납품 가능한 물자를 확인합니다.", "재난임무"),
            _a("disaster_join", "재난 현장 참여", "정찰·구조·수리·방어 역할로 현장 대응에 참여합니다.", "재난참여", "예: 구조", force_modal=True),
            _a("disaster_deliver", "재난 물자 납품", "재난 대응에 필요한 자원과 수량을 납품합니다.", "재난납품", "예: 고철 20", force_modal=True),
            _a("disaster_ranking", "재난 기여도", "현재 또는 최근 공동 재난의 기여 순위를 확인합니다.", "재난기여도"),
            _a("disaster_reward", "재난 개인 보상", "성공한 공동 재난의 개인 기여 보상을 수령합니다.", "재난보상"),
            _a("disaster_buff", "재난 성공 버프", "공동 재난 해결로 활성화된 서버 버프를 확인합니다.", "재난버프"),
            _a("disaster_spawn", "관리자 재난 발생", "관리자가 공동 재난 종류를 선택해 즉시 시작합니다.", "재난발생", "예: 정전", force_modal=True),
            _a("disaster_settle", "관리자 재난 정산", "목표 달성 또는 만료된 공동 재난을 안전하게 정산합니다.", "재난정산"),
            _a("v780_stability", "v7.8 신규 기능 검수", "v7.8에서 추가·수정된 기능만 읽기 전용 검사합니다.", "780안정화검수"),
            _a("base", "기지 현황", "기지 레벨과 저장량을 확인합니다.", "기지"),
            _a("base_build", "기지 건설", "기지가 없다면 새로 건설합니다.", "기지건설"),
            _a("base_upgrade", "기지 강화", "재료를 사용해 기지를 강화합니다.", "기지강화"),
            _a("base_collect", "기지 수확", "누적된 기지 생산물을 수확합니다.", "기지수확"),
            _a("weather", "종말 날씨", "서버별 2~5시간 랜덤 주기의 12종 날씨와 생활·전투 보정을 확인합니다.", "날씨"),
            _a("daily_fortune", "오늘의 운세", "매일 바뀌는 운세·행운 아이템·소폭 보정을 확인합니다.", "오늘의", "운세", force_modal=False),
            _a("radio_signal", "생존자 무전", "현재 환경 구간의 SOS 신호를 버튼으로 해독합니다.", "무전"),
            _a("hazard_zone", "돌연변이 구역", "오늘의 고위험·고보상 지역을 확인합니다.", "위험구역"),
            _a("random_box", "대형 랜덤박스", "식량으로 하루 최대 3개의 대형 보급 상자를 엽니다.", "랜덤박스", "예: 1", force_modal=True),
            _a("base_defense", "기지 방어", "주간 서버 협동 방어전 상태를 확인합니다.", "기지방어"),
            _a("base_defense_attack", "기지 방어 공격", "기지 레벨과 장비 전투력으로 방어전에 참가합니다.", "기지방어공격"),
            _a("resource_market", "자원 시장", "나무·광석·고철의 변동 가격을 확인합니다.", "자원시장"),
            _a("resource_buy", "자원 구매", "자원명과 수량을 입력해 식량으로 구매합니다.", "자원구매", "예: 나무 10", force_modal=True),
            _a("resource_sell", "자원 판매", "자원명과 수량을 입력해 식량으로 판매합니다.", "자원판매", "예: 광석 5", force_modal=True),
            _a("base_chip_exchange", "기지 칩 교환", "카지노 칩을 건축 자원으로 교환합니다.", "기지칩교환", "예: 고철 10", force_modal=True),
            _a("bank", "은행 현황", "예금·대출·신용을 확인합니다.", "은행"),
            _a("deposit", "은행 입금", "입금할 금액을 입력합니다.", "입금", "예: 1000", force_modal=True),
            _a("withdraw", "은행 출금", "출금할 금액을 입력합니다.", "출금", "예: 1000", force_modal=True),
            _a("loan", "은행 대출", "대출 금액을 입력합니다.", "대출", "예: 5000", force_modal=True),
            _a("repay", "은행 상환", "은행 대출 상환액을 입력합니다.", "상환", "예: 1000", force_modal=True),
            _a("bank_interest", "이자 정산", "예금·대출 이자를 정산합니다.", "은행이자"),
            _a("credit", "신용 확인", "신용점수와 대출 한도를 확인합니다.", "신용"),
            _a("bank_history", "은행 기록", "최근 은행 거래를 확인합니다.", "은행기록"),
            _a("loan_shark", "사채 현황", "사채 빚과 추심 위험을 확인합니다.", "사채"),
            _a("shark_borrow", "사채 빌리기", "사채 금액을 입력합니다.", "사채빌리기", "예: 3000", force_modal=True),
            _a("shark_repay", "사채 상환", "사채 상환액을 입력합니다.", "사채상환", "예: 1000", force_modal=True),
            _a("shark_collection", "사채 추심 확인", "현재 추심 위험을 확인합니다.", "사채추심"),
        ),
    ),
    "digging": (
        "⛏️ 굴착·보물",
        "땅파기, 미감정 보물, 감정사와 보물함을 관리합니다.",
        (
            _a("dig", "땅파기", "하루 50회·1분 간격으로 굴착해 식량·자원·미감정 보물을 찾습니다.", "땅파기"),
            _a("treasure_box", "보물함", "남은 굴착 횟수, 미감정 보물과 감정 기록을 확인합니다.", "보물함"),
            _a("appraisers", "감정사 목록", "감정사 4명의 비용·매입 배율·등급 상승 확률을 확인합니다.", "감정사"),
            _a("treasure_appraise", "보물 감정", "감정사를 드롭다운에서 선택해 가장 오래된 미감정 보물을 감정합니다.", "보물감정"),
        ),
    ),
    "card_games": (
        "🃏 카드게임·동료",
        "기존 안전 모집방으로 포커 4종·화투 2종·원카드·조커잡기를 즐기고 NPC 동료를 관리합니다.",
        (
            _a("card_game_menu", "카드게임 8종", "포커 4종·맞고·고스톱·원카드·조커잡기 통합 메뉴를 엽니다.", "카드게임"),
            _a("abaddon_ai", "아바돈 1:1 게임", "혼자일 때 아바돈과 7종 미니게임을 시작합니다.", "아바돈게임", "예: 식량 5000 또는 1000", force_modal=True),
            _a("abaddon_wager", "아바돈 선택 베팅", "게임·재화(칩/식량)·금액을 지정해 아바돈과 1:1 대결합니다.", "아바돈내기", "예: 포커 식량 5000", force_modal=True),
            _a("poker", "5장 포커 모집", "2~6명이 비공개 5장과 1회 교환으로 승부합니다.", "포커", "예: 10000", force_modal=True),
            _a("texas_holdem_v1010", "텍사스 홀덤", "2~6명이 홀카드 2장과 커뮤니티 카드로 승부합니다.", "텍사스홀덤", "예: 10000", force_modal=True),
            _a("omaha_holdem_v1010", "오마하 홀덤", "홀카드 4장 중 정확히 2장과 보드 3장을 사용합니다.", "오마하홀덤", "예: 10000", force_modal=True),
            _a("seven_stud_v1010", "세븐카드 스터드", "개인 7장 중 가장 좋은 5장 족보로 승부합니다.", "세븐카드스터드", "예: 10000", force_modal=True),
            _a("matgo_v1010", "맞고", "2인 화투 고/스톱 게임을 시작합니다.", "맞고", "예: 10000", force_modal=True),
            _a("gostop_v1010", "고스톱", "3~4인 화투 고/스톱 게임을 시작합니다.", "고스톱", "예: 10000", force_modal=True),
            _a("one_card", "원카드 모집", "2~6명이 같은 무늬·숫자를 내며 먼저 패를 비웁니다.", "원카드", "예: 10000", force_modal=True),
            _a("joker_draw", "조커잡기 모집", "2~8명이 짝을 버리고 마지막 조커를 피합니다.", "조커잡기", "예: 10000", force_modal=True),
            _a("companions_v1010", "동료 목록", "영입 가능한 NPC 동료 6명과 패시브를 확인합니다.", "동료"),
            _a("recruit_companion_v1010", "동료 영입", "인연 조건을 달성한 NPC를 영입합니다.", "동료영입", "예: 구조대장 민재", force_modal=True),
            _a("assign_companion_v1010", "동료 배치", "영입 동료를 탐사·카드게임·대기에 배치합니다.", "동료배치", "예: 정찰대장 이라 탐사", force_modal=True),
            _a("companion_mission_v1010", "동료 임무", "오늘의 연결 임무와 보상을 확인합니다.", "동료임무"),
        ),
    ),
    "casino": (
        "🎰 카지노·도박",
        "폐허 카지노, BLACK CASINO, 환전, 미션과 랭킹을 사용합니다.",
        (
            _a("casino", "카지노 로비", "카지노 게임 목록과 상태를 확인합니다.", "카지노"),
            _a("blackjack", "블랙잭", "배팅액을 입력해 버튼형 블랙잭을 시작합니다.", "블랙잭", "예: 1000", force_modal=True),
            _a("highlow", "하이로우", "배팅액을 입력해 하이로우를 시작합니다.", "하이로우", "예: 1000", force_modal=True),
            _a("slots", "슬롯", "배팅액을 입력해 슬롯을 돌립니다.", "슬롯", "예: 1000", force_modal=True),
            _a("dice", "다이스", "홀/짝/숫자와 배팅액을 입력합니다.", "다이스", "예: 홀 1000", force_modal=True),
            _a("baccarat", "바카라", "플레이어/뱅커/타이와 배팅액을 입력합니다.", "바카라", "예: 플레이어 1000", force_modal=True),
            _a("roulette", "생존 룰렛", "배팅액을 입력해 생존 룰렛을 실행합니다.", "룰렛", "예: 1000", force_modal=True),
            _a("frequency", "검은 주파수", "배팅액을 입력해 주파수 슬롯을 실행합니다.", "주파수", "예: 1000", force_modal=True),
            _a("gamble_explore", "폐허 방향 탐색", "방향과 배팅액을 입력합니다.", "탐색", "예: 왼쪽 1000", force_modal=True),
            _a("casino_balance", "카지노 잔액", "칩과 전적을 확인합니다.", "카지노잔액"),
            _a("casino_history", "카지노 기록", "최근 게임 기록을 확인합니다.", "카지노기록"),
            _a("casino_rank", "카지노 랭킹", "누적 순이익 랭킹을 확인합니다.", "카지노랭킹"),
            _a("casino_chips", "BLACK CASINO 칩", "칩·VIP·일일 상태를 확인합니다.", "카지노칩"),
            _a("casino_exchange", "카지노 환전", "방향과 금액을 입력합니다.", "카지노환전", "예: 구매 1000", force_modal=True),
            _a("casino_vip", "카지노 VIP", "VIP 등급과 혜택을 확인합니다.", "카지노VIP"),
            _a("casino_jackpot", "잭팟", "전 서버 잭팟을 확인합니다.", "카지노잭팟"),
            _a("casino_mission", "카지노 미션", "오늘의 카지노 미션을 확인합니다.", "카지노미션"),
            _a("casino_mission_reward", "카지노 미션 보상", "번호를 입력합니다. 0은 전부 수령입니다.", "카지노미션보상", "예: 0", force_modal=True),
            _a("casino_achievement", "카지노 업적", "페이지를 입력해 업적을 확인합니다.", "카지노업적", "예: 1", force_modal=True),
            _a("casino_shop", "카지노 상점", "카지노 NPC 상점을 확인합니다.", "카지노상점"),
            _a("casino_buy", "카지노 구매", "상품명과 수량을 입력합니다.", "카지노구매", "예: 럭키휠이용권 1", force_modal=True),
            _a("lucky_wheel", "럭키휠", "이용권 또는 칩으로 럭키휠을 돌립니다.", "럭키휠"),
            _a("coinflip", "코인플립", "앞면/뒷면과 배팅액을 입력합니다.", "코인플립", "예: 앞면 1000", force_modal=True),
            _a("allin", "올인", "앞면 또는 뒷면을 선택해 전액 배팅합니다.", "올인", "예: 앞면", force_modal=True),
            _a("casino_season_rank", "카지노 시즌 랭킹", "구분과 페이지를 입력합니다.", "카지노시즌랭킹", "예: 시즌 1", force_modal=True),
        ),
    ),
    "story": (
        "📖 스토리·시즌",
        "검은 주파수, 백색 방주, 시즌 3 종말의 왕좌와 퀴즈·시즌 콘텐츠를 진행합니다.",
        (
            _a("story1", "시즌 1 · 검은 주파수", "시즌 1 현재 장면을 확인합니다.", "스토리"),
            _a("story1_start", "시즌 1 시작", "검은 주파수 캠페인을 시작합니다.", "스토리 시작"),
            _a("story1_choose", "시즌 1 선택", "선택지 번호를 입력합니다.", "스토리 선택", "예: 1", force_modal=True),
            _a("story1_history", "시즌 1 기록", "시즌 1 선택 기록을 확인합니다.", "스토리 기록"),
            _a("story1_restart", "시즌 1 재시작", "엔딩 수집을 유지하고 다시 시작합니다.", "스토리 재시작"),
            _a("story2", "시즌 2 · 백색 방주", "시즌 2 현재 장면을 확인합니다.", "시즌2"),
            _a("story2_start", "시즌 2 시작", "백색 방주 캠페인을 시작합니다.", "시즌2 시작"),
            _a("story2_choose", "시즌 2 선택", "선택지 번호를 입력합니다.", "시즌2 선택", "예: 1", force_modal=True),
            _a("story2_history", "시즌 2 기록", "시즌 2 선택 기록을 확인합니다.", "시즌2 기록"),
            _a("story2_restart", "시즌 2 재시작", "엔딩 수집을 유지하고 다시 시작합니다.", "시즌2 재시작"),
            _a("story2_scene", "시즌 2 장면 다시보기", "장면 번호를 입력합니다.", "시즌2 장면", "예: 1", force_modal=True),
            _a("story2_collection", "시즌 2 엔딩 수집", "발견한 백색 방주 엔딩을 확인합니다.", "시즌2 수집"),
            _a("story2_legacy", "시즌 2 계승 정보", "시즌 1 선택의 계승 내용을 확인합니다.", "시즌2 계승"),
            _a("story3", "시즌 3 · 종말의 왕좌", "v6.0 신규 캠페인을 드롭다운으로 진행합니다.", "시즌3"),
            _a("story3_start", "시즌 3 시작", "종말의 왕좌 캠페인을 시작합니다.", "시즌3 시작"),
            _a("story3_choose", "시즌 3 선택", "선택지 번호를 입력합니다.", "시즌3 선택", "예: 1", force_modal=True),
            _a("story3_history", "시즌 3 기록", "시즌 3 선택 기록과 엔딩을 확인합니다.", "시즌3 기록"),
            _a("story3_restart", "시즌 3 재시작", "엔딩·보상 기록을 유지하고 재시작합니다.", "시즌3 재시작"),
            _a("story4", "시즌 4 · 황혼의 종착역", "황혼선 04의 현재 장면과 선택지를 확인합니다.", "시즌4"),
            _a("story4_start", "시즌 4 시작", "황혼의 종착역 캠페인을 시작합니다.", "시즌4 시작"),
            _a("story4_choose", "시즌 4 선택", "선택지 번호를 입력합니다.", "시즌4 선택", "예: 1", force_modal=True),
            _a("story4_history", "시즌 4 기록", "선택 기록과 발견한 엔딩을 확인합니다.", "시즌4 기록"),
            _a("story4_restart", "시즌 4 재시작", "엔딩·보상 기록을 유지하고 재시작합니다.", "시즌4 재시작"),
            _a("story_journey", "시즌 여정", "시즌 1~4 완료와 엔딩 수집 현황을 확인합니다.", "시즌여정"),
            _a("story_legacy", "시즌 4 유산", "시즌 4 엔딩 수집 단계 보상을 확인하고 받습니다.", "시즌유산"),
            _a("daily_quiz", "오늘의 퀴즈", "오늘의 생존 퀴즈를 확인합니다.", "오늘의퀴즈"),
            _a("quiz_answer", "퀴즈 정답", "번호·번호+번·정답 문구로 답안을 입력합니다.", "정답", "예: 1번", force_modal=True),
            _a("quiz_rank", "퀴즈 랭킹", "퀴즈 누적 정답 랭킹을 확인합니다.", "퀴즈랭킹"),
            _a("quiz_stats", "퀴즈 통계", "문제은행 수와 내 누적 정답을 확인합니다.", "퀴즈통계"),
        ),
    ),
    "guild": (
        "🏰 길드·공동 기지",
        "기존 길드 명령과 공동 기지, 임무, 금고를 한 화면에서 관리합니다.",
        (
            _a("guild_list", "길드 목록", "서버의 길드 목록을 확인합니다.", "길드목록"),
            _a("guild_create", "길드 생성", "길드명을 입력해 생성합니다.", "길드생성", "예: 황혼원정대", force_modal=True),
            _a("guild_join", "길드 가입", "자유 가입 길드에 즉시 가입합니다.", "길드가입", "예: 황혼원정대", force_modal=True),
            _a("guild_info", "길드 정보", "현재 가입 길드 정보를 확인합니다.", "길드정보"),
            _a("guild_donate", "기존 식량 기부", "기존 길드 식량 기부 명령을 사용합니다.", "길드기부", "예: 1000", force_modal=True),
            _a("guild_upgrade", "기존 길드 강화", "기존 길드 레벨을 강화합니다.", "길드강화"),
            _a("guild_leave", "길드 탈퇴", "마지막 멤버여도 기록은 휴면 상태로 보존합니다.", "길드탈퇴"),
            _a("guild_dashboard", "통합 길드 관리", "조직·기지·임무·금고·레이드를 한 화면에서 확인합니다.", "길드관리"),
            _a("guild_description", "길드 소개", "현재 길드 소개를 확인합니다.", "길드소개"),
            _a("guild_settings", "가입 방식 설정", "자유·승인·비공개 중 하나를 설정합니다.", "길드설정", "예: 가입방식 승인", force_modal=True),
            _a("guild_apply", "길드 가입 신청", "승인제 길드에 가입을 신청합니다.", "길드신청", "예: 황혼원정대", force_modal=True),
            _a("guild_applications", "가입 신청 목록", "대기 중인 가입 신청을 확인합니다.", "길드신청목록"),
            _a("guild_application_process", "가입 신청 처리", "대상과 승인/거절을 입력합니다.", "길드신청처리", "예: @생존자 승인", force_modal=True),
            _a("guild_role", "길드 직책", "길드원을 간부 또는 일반으로 변경합니다.", "길드직책", "예: @생존자 간부", force_modal=True),
            _a("guild_kick", "길드 추방", "길드원을 추방합니다.", "길드추방", "예: @생존자", force_modal=True),
            _a("guild_transfer", "길드장 위임", "길드장 권한을 다른 길드원에게 넘깁니다.", "길드위임", "예: @생존자", force_modal=True),
            _a("guild_base", "공동 기지", "발전기·창고·의무실·무기고와 공사를 확인합니다.", "길드기지"),
            _a("guild_build", "시설 건설", "새 공동 시설을 건설합니다.", "길드건설", "예: 발전기", force_modal=True),
            _a("guild_facility_upgrade", "시설 강화", "완성된 공동 시설을 강화합니다.", "길드시설강화", "예: 창고", force_modal=True),
            _a("guild_base_collect", "기지 생산 수확", "발전기 생산 식량을 공동 금고로 회수합니다.", "길드기지수확"),
            _a("guild_missions", "길드 공동 임무", "일일·주간 공동 목표를 확인합니다.", "길드임무"),
            _a("guild_mission_reward", "길드 임무 보상", "일일 또는 주간 완료 보상을 받습니다.", "길드임무보상", "예: 주간", force_modal=True),
            _a("guild_vault", "통합 길드 금고", "식량·건축 자원과 출금 요청을 확인합니다.", "길드금고"),
            _a("guild_deposit", "길드 금고 입금", "식량 또는 건축 자원을 입금합니다.", "길드입금", "예: 식량 10000", force_modal=True),
            _a("guild_withdraw_request", "길드 출금 요청", "재화·금액·사유를 입력해 승인을 요청합니다.", "길드출금요청", "예: 식량 5000 장비 수리", force_modal=True),
        ),
    ),
    "guild_raid": (
        "👹 길드 레이드·감사",
        "승인형 금고 처리, 주간 길드 레이드와 관리자 무결성 검사를 사용합니다.",
        (
            _a("guild_withdraw_approve", "출금 승인", "다른 길드원의 출금 요청을 승인합니다.", "길드출금승인", "예: 요청번호", force_modal=True),
            _a("guild_withdraw_reject", "출금 거절", "출금 요청을 사유와 함께 거절합니다.", "길드출금거절", "예: 요청번호 사유", force_modal=True),
            _a("guild_transactions", "길드 거래 내역", "최근 입출금과 승인 기록을 확인합니다.", "길드거래내역"),
            _a("guild_raid", "주간 길드 레이드", "현재 보스·부위·길드 진행도를 확인합니다.", "길드레이드"),
            _a("guild_raid_ready", "레이드 준비", "개인 전술·쿨다운·시설 보정과 추천 부위를 확인합니다.", "길드레이드준비"),
            _a("guild_raid_preset", "개인 전술 프리셋", "기본 전술과 공격 부위를 저장합니다.", "길드전술설정", "예: 돌격 동력핵", force_modal=True),
            _a("guild_raid_practice", "레이드 연습", "실제 HP·쿨다운·보상에 영향 없는 모의 공격입니다.", "길드레이드연습", "예: 지원 장갑판", force_modal=True),
            _a("guild_raid_history", "레이드 기록", "현재와 과거 길드 레이드 기록을 페이지로 확인합니다.", "길드레이드기록", "예: 1", force_modal=False),
            _a("guild_raid_attack", "길드 레이드 공격", "전술과 부위를 선택해 공격합니다. 인자를 생략하면 저장한 프리셋을 사용합니다.", "길드레이드공격", "예: 지원 동력핵", force_modal=False),
            _a("guild_raid_reward", "레이드 보상", "토벌한 레이드의 개인 기여 보상을 받습니다.", "길드레이드보상"),
            _a("guild_raid_ranking", "레이드 기여도", "현재 길드 레이드 기여도 순위를 확인합니다.", "길드레이드랭킹"),
            _a("guild_overall_ranking", "길드 종합 랭킹", "시설·레이드·기여도를 합산한 길드 순위를 확인합니다.", "길드종합랭킹"),
            _a("guild_audit", "길드 데이터 검수", "길드·금고·레이드 데이터를 읽기 전용으로 검사합니다.", "길드검수"),
            _a("guild_repair_preview", "복구 미리보기", "변경 없이 안전 복구 후보만 표시합니다.", "길드복구미리보기"),
            _a("v750_stability", "v7.5 안정화 검수", "명령 충돌·잠금·중복 정산·삭제 여부를 검사합니다.", "750안정화검수"),
            _a("guild_dispatch", "길드 파견 지휘소", "협동 파견 지역·모집·진행 상태를 확인합니다.", "길드파견"),
            _a("guild_dispatch_open", "길드 파견 모집", "지역을 선택해 길드 파견 모집을 엽니다.", "길드파견모집", "예: 연구소", force_modal=True),
            _a("guild_dispatch_join", "길드 파견 참가", "선봉·기술·의무·보급 역할로 참가합니다.", "길드파견참가", "예: 기술", force_modal=True),
            _a("guild_dispatch_start", "길드 파견 출발", "모집한 파견대를 출발시키고 금고 비용을 차감합니다.", "길드파견출발"),
            _a("guild_dispatch_settle", "길드 파견 정산", "복귀한 파견의 길드 보상을 한 번만 정산합니다.", "길드파견정산"),
            _a("guild_dispatch_reward", "길드 파견 개인 보상", "완료된 파견의 개인 보상을 수령합니다.", "길드파견보상"),
            _a("guild_dispatch_history", "길드 파견 기록", "완료된 파견 기록을 페이지로 확인합니다.", "길드파견기록", "예: 1", force_modal=False),
            _a("guild_dispatch_practice", "길드 파견 모의", "금고·기록 변경 없이 1인 파견 결과를 예측합니다.", "길드파견모의", "예: 연구소 기술", force_modal=True),
            _a("v760_stability", "v7.6 파견 안정화 검수", "파견 중복 정산·보상 키·저장 구조를 읽기 전용 검사합니다.", "760안정화검수"),
        ),
    ),
    "social": (
        "🤝 파티·거래",
        "파티, 거래소, 경매와 유저 간 상호작용을 사용합니다. 길드는 전용 메뉴로 이동했습니다.",
        (
            _a("party_create", "파티 생성", "전투 파티를 생성합니다.", "파티생성"),
            _a("party_join", "파티 가입", "리더 멘션 또는 ID를 입력합니다.", "파티가입", "예: @리더", force_modal=True),
            _a("party_info", "파티 정보", "현재 파티 상태를 확인합니다.", "파티정보"),
            _a("party_hunt", "파티 사냥", "파티원과 함께 사냥합니다.", "파티사냥"),
            _a("party_leave", "파티 탈퇴", "현재 파티에서 탈퇴합니다.", "파티탈퇴"),
            _a("market", "거래소", "현재 등록된 판매 물품을 확인합니다.", "거래소"),
            _a("sell", "거래소 판매", "아이템명과 가격을 입력합니다.", "판매", "예: 고철 500", force_modal=True),
            _a("market_buy", "거래소 구매", "등록 번호를 입력합니다.", "구매등록번호", "예: 3", force_modal=True),
            _a("sell_cancel", "판매 취소", "판매 등록 번호를 입력합니다.", "판매취소", "예: 3", force_modal=True),
            _a("auction_search", "경매 검색", "검색어를 입력합니다.", "거래검색", "예: 장검", force_modal=True),
            _a("auction_register", "경매 등록", "아이템명과 시작가를 입력합니다.", "경매등록", "예: \"생존자 장검\" 5000", force_modal=True),
            _a("auction_bid", "경매 입찰", "등록 번호와 입찰액을 입력합니다.", "입찰", "예: 2 7000", force_modal=True),
            _a("auction_finish", "경매 마감", "등록 번호를 입력합니다.", "경매마감", "예: 2", force_modal=True),
            _a("auction_history", "경매 기록", "최근 경매 거래 기록을 확인합니다.", "거래기록"),
            _a("transfer", "송금", "대상 멘션/ID와 금액을 입력합니다.", "송금", "예: @상대 1000", force_modal=True),
        ),
    ),
    "world_map": (
        "🗺️ 탐험 지도·지역 개척",
        "서버 공동 지도를 개척하고 정찰·기부·거점·지역 보스를 순차 진행합니다.",
        (
            _a("terminal_v810", "통합 생존 단말기", "현재 상태에 맞는 주요 기능을 한 선택창에서 엽니다.", "단말기"),
            _a("world_map_v810", "공동 탐험 지도", "서버 지역 개척 진행도와 순차 해금 상태를 확인합니다.", "세계지도"),
            _a("world_region_info_v810", "개척 지역 정보", "지역의 개척도·환경·거점·보스를 확인합니다.", "지역개척정보", "예: 대피소 외곽", force_modal=True),
            _a("world_scout_v810", "지역 정찰", "스태미나를 사용해 현장 선택형 정찰을 시작합니다.", "지역정찰", "예: 대피소 외곽", force_modal=True),
            _a("world_choice_v810", "정찰 선택", "재접속 뒤 진행 중인 정찰을 안전·신호·돌파 중 하나로 마무리합니다.", "지역선택", "예: 신호", force_modal=True),
            _a("frontier_status_v810", "공동 개척 현황", "개방 지역의 진행도·안전도·오염도를 확인합니다.", "개척현황"),
            _a("frontier_donate_v810", "개척 자원 기부", "개인 자원을 공동 개척도에 기부합니다.", "개척기부", "예: 외곽 고철 20", force_modal=True),
            _a("outpost_v810", "지역 공동 거점", "감시탑·정화소·보급소 상태를 확인합니다.", "거점", "예: 외곽", force_modal=True),
            _a("outpost_build_v810", "거점 건설·강화", "개인 자원으로 공동 거점 시설을 건설합니다.", "거점건설", "예: 외곽 감시탑", force_modal=True),
            _a("region_boss_v810", "지역 보스", "개척 목표 달성 후 출현하는 지역 보스 상태를 확인합니다.", "지역보스", "예: 외곽", force_modal=True),
            _a("region_boss_attack_v810", "지역 보스 공격", "활성 지역 보스를 공격하고 공동 피해를 누적합니다.", "지역보스공격", "예: 외곽", force_modal=True),
            _a("region_reward_v810", "지역 개척 보상", "격파한 지역 보스의 개인 기여 보상을 받습니다.", "지역보상", "예: 외곽", force_modal=True),
            _a("exploration_history_v810", "개인 탐험 기록", "최근 정찰 선택과 공동 개척 기여를 확인합니다.", "탐험기록"),
            _a("admin_check_v810", "통합 관리자 점검", "최신 패치·데이터·메뉴·오류 점검 진입점을 엽니다.", "관리점검"),
            _a("error_lookup_v810", "오류 사건 조회", "저장된 명령·UI 오류 사건 번호를 조회합니다.", "오류조회", "예: UI-02072778", force_modal=True),
            _a("recent_errors_v810", "최근 오류 목록", "최근 보관된 명령·UI 오류 사건을 확인합니다.", "최근오류"),
            _a("v810_stability", "v8.1 안정화 검수", "단말기·지도·정찰·거점·보스·오류 조회를 읽기 전용 검사합니다.", "810안정화검수"),
        ),
    ),
    "community_ops": (
        "🛡️ 운영·알림·커뮤니티",
        "통합 운영센터, 자동 재난 감시, 개인 알림, 공개 건의, 임시 음성방과 하이라이트를 관리합니다.",
        (
            _a("disaster_forecast_v790", "재난 예보", "자동 공동 재난의 다음 감시 일정과 채널을 확인합니다.", "재난예보"),
            _a("disaster_weather_v790", "재난 기상", "현재 공동 재난에 결합된 환경 상태를 확인합니다.", "재난날씨"),
            _a("disaster_history_v790", "재난 기록", "최근 공동 재난과 기상 결과를 확인합니다.", "재난기록", "선택: 페이지", force_modal=False),
            _a("disaster_auto_v790", "재난 자동 설정", "관리자가 자동 발생을 켜거나 끕니다.", "재난자동", "예: 켜기", force_modal=True),
            _a("disaster_channel_v790", "재난 공지 채널", "자동 공동 재난 게시 채널을 지정합니다.", "재난채널", "선택: #채널", force_modal=False),
            _a("notification_center_v790", "통합 알림센터", "패치·재난·시장·길드 알림을 선택합니다.", "알림센터"),
            _a("my_notifications_v790", "내 알림", "현재 통합 알림 설정을 확인합니다.", "내알림"),
            _a("suggestion_panel_v790", "공개 건의", "버튼과 모달로 공개 건의를 등록합니다.", "건의"),
            _a("suggestion_list_v790", "건의 목록", "투표와 검토 상태를 확인합니다.", "건의목록", "선택: 페이지", force_modal=False),
            _a("suggestion_status_v790", "건의 상태 변경", "관리자가 건의의 개발 상태를 변경합니다.", "건의상태", "예: SG-0001 진행중", force_modal=True),
            _a("roadmap_v790", "공개 로드맵", "개발 예정·진행 중·완료 건의를 확인합니다.", "로드맵"),
            _a("operations_hub_v790", "통합 운영센터", "문의·점검·통계·알림·재난 진입점을 엽니다.", "운영통합센터"),
            _a("operations_analytics_v790", "운영 분석", "실제 재화·콘텐츠·오류 누적 결과를 집계합니다.", "운영분석"),
            _a("temp_voice_setup_v790", "임시 분대 음성방 설치", "입장 시 자동 생성되는 분대 음성방 로비를 설치합니다.", "분대음성설정"),
            _a("temp_voice_name_v790", "분대방 이름", "자신이 만든 임시 분대방 이름을 바꿉니다.", "분대방이름", "예: 철도 원정대", force_modal=True),
            _a("temp_voice_lock_v790", "분대방 잠금", "임시 분대방 공개 입장을 전환합니다.", "분대방잠금"),
            _a("temp_voice_invite_v790", "분대방 초대", "잠긴 분대방에 사용자를 초대합니다.", "분대방초대", "예: @생존자", force_modal=True),
            _a("temp_voice_limit_v790", "분대방 인원", "임시 분대방 최대 인원을 설정합니다.", "분대방인원", "예: 5", force_modal=True),
            _a("temp_voice_transfer_v790", "분대방 방장 위임", "같은 방의 사용자에게 방장을 넘깁니다.", "분대방방장", "예: @생존자", force_modal=True),
            _a("highlight_setup_v790", "하이라이트 설정", "반응이 모인 메시지를 보관할 채널과 기준을 설정합니다.", "하이라이트설정", "예: #현장-사진 ⭐ 3", force_modal=True),
            _a("highlight_status_v790", "하이라이트 상태", "현재 하이라이트 보드 설정을 확인합니다.", "하이라이트상태"),
            _a("highlight_add_v790", "하이라이트 수동 추가", "현재 채널 메시지 ID를 하이라이트에 추가합니다.", "하이라이트추가", "예: 메시지ID", force_modal=True),
            _a("highlight_remove_v790", "하이라이트 제거", "원본 메시지 ID의 하이라이트 연결을 제거합니다.", "하이라이트제거", "예: 메시지ID", force_modal=True),
            _a("guild_invite_accept_v790", "길드 초대 수락", "우클릭으로 받은 최근 길드 초대를 수락합니다.", "길드초대수락"),
            _a("v790_stability", "v7.9 안정화 검수", "자동 재난·버튼·운영·알림·음성·우클릭을 읽기 전용 검사합니다.", "790안정화검수"),
            _a("channel_rules_existing", "채널 규칙", "현재 채널의 전용 규칙·가이드를 설치하거나 갱신합니다.", "채널규칙", "선택: 자동/갱신", force_modal=False),
        ),
    ),
    "pets": (
        "🐾 펫·도감",
        "펫 상점, 성장, 모험과 통합 도감 기능을 사용합니다.",
        (
            _a("pet_shop", "펫 상점", "구매 가능한 펫을 확인합니다.", "펫상점"),
            _a("pet_buy", "펫 구매", "펫 이름을 입력해 구매합니다.", "펫구매", "예: 폐허늑대", force_modal=True),
            _a("pet_info", "펫 정보", "펫 이름을 입력해 정보를 확인합니다.", "펫정보", "예: 폐허늑대", force_modal=True),
            _a("pet_train", "펫 훈련", "현재 펫을 훈련합니다.", "펫훈련"),
            _a("pet_list", "펫 목록", "보유 펫 목록을 확인합니다.", "펫목록"),
            _a("pet_equip", "펫 장착", "펫 이름을 입력해 대표 펫으로 장착합니다.", "펫장착", "예: 폐허늑대", force_modal=True),
            _a("pet_feed", "펫 먹이", "현재 펫에게 먹이를 줍니다.", "펫먹이"),
            _a("pet_adventure", "펫 모험", "펫을 모험에 보냅니다.", "펫모험"),
            _a("pet_evolve", "펫 진화", "조건을 충족한 펫을 진화시킵니다.", "펫진화"),
            _a("codex", "통합 도감", "장비·펫·몬스터 도감 메뉴를 엽니다.", "도감"),
            _a("codex_gear", "장비 도감", "수집한 장비 도감을 확인합니다.", "도감 장비"),
            _a("codex_pet", "펫 도감", "수집한 펫 도감을 확인합니다.", "도감 펫"),
            _a("codex_monster", "몬스터 도감", "처치한 몬스터 도감을 확인합니다.", "도감 몬스터"),
            _a("codex_reward", "도감 보상", "달성한 도감 보상을 받습니다.", "도감보상"),
        ),
    ),
    "factions_world": (
        "🌍 세력·무역·세계상태",
        "NPC 세력 평판, 지역 무역 호송, 서버 공동 세력전쟁과 시즌 5 세계 선택을 관리합니다.",
        (
            _a("factions_v900", "세력 목록", "우호 세력과 현재 관계를 확인합니다.", "세력"),
            _a("reputation_v900", "세력 평판", "세력별 평판과 증표를 확인합니다.", "평판"),
            _a("faction_info_v900", "세력 정보", "세력의 역할·관계·혜택을 확인합니다.", "세력정보", "예: 구조대", force_modal=True),
            _a("faction_outpost_v900", "세력 거점", "세력 거점의 의뢰·교환·지원 기능을 확인합니다.", "세력거점", "예: 정찰대", force_modal=True),
            _a("faction_mission_v900", "세력 의뢰", "오늘의 세력 의뢰와 요청 물자를 확인합니다.", "세력의뢰", "예: 의무단", force_modal=True),
            _a("faction_mission_accept_v900", "세력 의뢰 수락", "오늘의 의뢰 하나를 수락합니다.", "세력의뢰수락", "예: 복구단", force_modal=True),
            _a("faction_mission_complete_v900", "세력 의뢰 완료", "수락한 의뢰 물자를 제출하고 정산합니다.", "세력의뢰완료"),
            _a("faction_shop_v900", "세력 상점", "세력 증표 교환 목록을 확인합니다.", "세력상점", "예: 호위대", force_modal=True),
            _a("faction_exchange_v900", "세력 교환", "세력 증표로 보급품 또는 칭호를 교환합니다.", "세력교환", "예: 구조대 1", force_modal=True),
            _a("trade_routes_v900", "지역 무역로", "개방된 무역로와 오늘의 수요를 확인합니다.", "무역로"),
            _a("regional_economy_v900", "지역 경제", "지역별 수요와 공동 보급 지표를 확인합니다.", "지역경제"),
            _a("convoy_open_v900", "호송 모집", "화물을 적재하고 지역 호송대를 모집합니다.", "호송모집", "예: 철도 식량 5000", force_modal=True),
            _a("convoy_join_v900", "호송 참가", "선봉·정비·의무·교섭 역할로 호송대에 참가합니다.", "호송참가", "예: 정비", force_modal=True),
            _a("convoy_start_v900", "호송 출발", "모집 중인 호송대를 출발시킵니다.", "호송출발"),
            _a("convoy_status_v900", "호송 상태", "현재 호송대의 노선·화물·편성을 확인합니다.", "호송상태"),
            _a("convoy_settle_v900", "호송 정산", "도착한 호송 결과를 한 번만 정산합니다.", "호송정산"),
            _a("convoy_reward_v900", "호송 보상", "정산된 호송의 개인 보상을 받습니다.", "호송보상"),
            _a("convoy_cancel_v900", "호송 취소", "출발 전 모집을 취소하고 화물을 반환합니다.", "호송취소"),
            _a("faction_war_v900", "세력전쟁", "현재 적대 세력과 공동 전쟁 진행도를 확인합니다.", "세력전쟁"),
            _a("front_select_v900", "집중 전선 선택", "관리자가 구조·방어·복구 집중 전선을 선택합니다.", "전선선택", "예: 방어", force_modal=True),
            _a("war_join_v900", "전쟁 참여", "정찰·구조·방어·복구 행동으로 전쟁에 참여합니다.", "전쟁참여", "예: 구조", force_modal=True),
            _a("war_donate_v900", "전쟁 기부", "자원을 공동 전쟁 진행도에 기부합니다.", "전쟁기부", "예: 식량 5000", force_modal=True),
            _a("war_contribution_v900", "전쟁 기여도", "현재 세력전쟁 기여 순위를 확인합니다.", "전쟁기여도"),
            _a("war_settle_v900", "전쟁 정산", "관리자가 완료된 세력전쟁을 정산합니다.", "전쟁정산"),
            _a("war_reward_v900", "전쟁 보상", "정산된 전쟁의 개인 기여 보상을 받습니다.", "전쟁보상"),
            _a("war_restart_v900", "다음 전쟁 개시", "관리자가 정산 후 새로운 적대 세력전을 시작합니다.", "전쟁재개"),
            _a("world_status_v900", "세계 상태", "안정도·보급·사기·오염과 전쟁·시즌 상태를 확인합니다.", "세계상태"),
            _a("season5_v900", "시즌 5", "잿빛 연합전선의 현재 장과 선택지를 확인합니다.", "시즌5"),
            _a("season5_vote_v900", "시즌 5 투표", "현재 장의 서버 선택지에 투표합니다.", "시즌5투표", "예: 2", force_modal=True),
            _a("season5_decide_v900", "시즌 5 결정", "관리자가 투표 결과를 확정하고 다음 장을 엽니다.", "시즌5결정", "선택: 1", force_modal=False),
            _a("world_chronicle_v900", "세계 연대기", "시즌 선택·전쟁·호송 기록을 확인합니다.", "세계연대기"),
            _a("v900_stability", "v9.0 안정화 검수", "세력·무역·전쟁·시즌 5 연결을 읽기 전용 검사합니다.", "900안정화검수"),
        ),
    ),
    "world_cycle_profession": (
        "🌐 세계 순환·전문화·분대",
        "안전한 세계 시간 순환, 공동 복구, 주간 지령, 기존 직업 전문화와 기존 파티 분대 전술을 관리합니다.",
        (
            _a("world_cycle_v920", "세계 순환", "세계 지표의 안전한 시간 순환과 다음 반영 시각을 확인합니다.", "세계순환"),
            _a("world_cycle_settings_v920", "세계 순환 설정", "관리자가 세계 순환을 켜거나 일시정지합니다.", "세계순환설정", "예: 일시정지", force_modal=True),
            _a("world_cycle_now_v920", "세계 즉시 순환", "관리자가 세계 순환 1회를 즉시 반영합니다.", "세계순환즉시"),
            _a("today_world_v920", "오늘의 세계", "세계 지표·복구·지령을 한 화면에 요약합니다.", "오늘의세계"),
            _a("recovery_v920", "공동 복구 작전", "현재 장기 복구 작전과 버튼 참여 패널을 엽니다.", "복구작전"),
            _a("recovery_start_v920", "복구 작전 시작", "관리자가 발전·식수·병원·보급로·통신·방벽 작전을 시작합니다.", "복구작전시작", "예: 발전망", force_modal=True),
            _a("recovery_join_v920", "복구 현장 참여", "정찰·구조·수리·경계 행동으로 공동 진행도를 올립니다.", "복구참여", "예: 수리", force_modal=True),
            _a("recovery_supply_v920", "복구 물자 납품", "복구 작전에 필요한 자원을 목표를 넘지 않게 지원합니다.", "복구납품", "예: 고철 20", force_modal=True),
            _a("recovery_contribution_v920", "복구 기여도", "현재 공동 복구 기여 순위를 확인합니다.", "복구기여도"),
            _a("recovery_reward_v920", "복구 보상", "완료된 복구 작전의 개인 기여 보상을 받습니다.", "복구보상"),
            _a("directive_v920", "세계 지령", "이번 주 공동 목표와 투표 패널을 확인합니다.", "세계지령"),
            _a("directive_vote_v920", "지령 투표", "이번 주 세계 지령에 투표합니다.", "지령투표", "예: 보급", force_modal=True),
            _a("directive_decide_v920", "지령 결정", "관리자가 최다 득표 또는 지정 지령을 확정합니다.", "지령결정", "선택: 안정", force_modal=False),
            _a("specialization_v920", "내 전문화", "현재 기본 직업과 선택한 전문화를 확인합니다.", "전문화"),
            _a("specialization_list_v920", "전문화 목록", "현재 직업에서 선택 가능한 전문화를 확인합니다.", "전문화목록"),
            _a("specialization_info_v920", "전문화 정보", "특정 전문화의 역할과 연동 콘텐츠를 확인합니다.", "전문화정보", "예: 방벽대장", force_modal=True),
            _a("specialization_choose_v920", "전문화 선택", "레벨 20 이상에서 현재 직업의 전문화를 선택합니다.", "전문화선택", "예: 방벽대장", force_modal=True),
            _a("specialization_change_v920", "전문화 변경", "식량을 사용해 같은 기본 직업의 전문화를 변경합니다.", "전문화변경", "예: 돌격대장", force_modal=True),
            _a("squad_tactics_v920", "분대 전술", "기존 파티의 전술과 역할 편성을 확인합니다.", "분대전술"),
            _a("squad_tactic_set_v920", "분대 전술 설정", "파티장이 균형·돌격·방어·구조·정찰 전술을 설정합니다.", "분대전술설정", "예: 구조", force_modal=True),
            _a("squad_role_v920", "분대 역할", "자신의 역할을 선봉·의무·기술·정찰 중 선택합니다.", "분대역할", "예: 기술", force_modal=True),
            _a("squad_ready_v920", "분대 준비 점검", "인원·역할 다양성·전문화·작전 대기시간을 확인합니다.", "분대준비"),
            _a("squad_operation_v920", "분대 작전", "파티장이 역할과 전문화를 반영한 협동 작전을 수행합니다.", "분대작전", "예: 오염정찰", force_modal=True),
            _a("squad_history_v920", "분대 작전 기록", "현재 파티의 최근 분대 작전 기록을 확인합니다.", "분대작전기록"),
            _a("v920_stability", "v9.2 안정화 검수", "세계 순환·복구·전문화·분대 전술 연결을 읽기 전용 검사합니다.", "920안정화검수"),
        ),
    ),
    "investigation_shelter": (
        "🕵️ 사건 수사·대피소·협동 레이드",
        "단서 조합 사건 수사, 현상금 추적, 개인 대피소 전시와 서버 공동 수사 레이드를 관리합니다.",
        (
            _a("case_board_v950", "사건판", "이번 주 공동 사건과 단서·증거 연결 진행도를 확인합니다.", "사건판"),
            _a("clue_list_v950", "단서 목록", "개인이 확보한 사건 단서를 확인합니다.", "단서목록"),
            _a("clue_investigate_v950", "단서 조사", "현장·기록·증언 트랙에서 단서를 조사합니다.", "단서조사", "예: 현장", force_modal=True),
            _a("clue_combine_v950", "단서 조합", "보유한 두 단서를 연결해 사건 논리를 완성합니다.", "단서조합", "예: 단서1 + 단서2", force_modal=True),
            _a("case_solve_v950", "사건 추리", "연결된 증거를 바탕으로 사건의 배후를 지목합니다.", "사건추리", "예: 용의자", force_modal=True),
            _a("bounty_v950", "현상금", "이번 주 공동 현상금 표적과 진행도를 확인합니다.", "현상금"),
            _a("bounty_track_v950", "현상금 추적", "추적·잠복·협상·제압으로 현상금 진행도를 올립니다.", "현상금추적", "예: 추적", force_modal=True),
            _a("bounty_report_v950", "현상금 보고", "완료된 현상금의 개인 기여 보상을 받습니다.", "현상금보고"),
            _a("bounty_history_v950", "현상금 기록", "개인의 현상금 완료 기록을 확인합니다.", "현상금기록"),
            _a("shelter_v950", "개인 대피소", "개인 대피소의 테마·장식·전시품을 확인합니다.", "대피소"),
            _a("shelter_decorate_v950", "대피소 꾸미기", "개인 대피소 테마를 변경합니다.", "대피소꾸미기", "예: 아포칼립스", force_modal=True),
            _a("decoration_list_v950", "장식 목록", "제작 가능한 대피소 장식과 비용을 확인합니다.", "장식목록"),
            _a("decoration_craft_v950", "장식 제작", "재료를 사용해 개인 대피소 장식을 제작합니다.", "장식제작", "예: 구조등", force_modal=True),
            _a("showcase_v950", "전시실", "보유 트로피와 현재 전시품을 확인합니다.", "전시실"),
            _a("trophy_display_v950", "트로피 전시", "보유한 트로피를 개인 대피소에 전시합니다.", "트로피전시", "예: 트로피 이름", force_modal=True),
            _a("shelter_visit_v950", "대피소 방문", "다른 생존자의 개인 대피소를 방문합니다.", "대피소방문", "예: @생존자", force_modal=True),
            _a("shelter_like_v950", "대피소 좋아요", "다른 생존자의 대피소에 좋아요를 남깁니다.", "대피소좋아요", "예: @생존자", force_modal=True),
            _a("investigation_raid_v950", "협동 수사 레이드", "현재 수사 레이드 모집·진행·완료 상태를 확인합니다.", "수사레이드"),
            _a("investigation_raid_open_v950", "수사 레이드 모집", "서버 공동 수사 레이드 모집을 시작합니다.", "수사레이드모집", "선택: 사건명", force_modal=False),
            _a("investigation_raid_join_v950", "수사 레이드 참가", "현장수사·기술분석·현장경계·교섭 역할로 참가합니다.", "수사레이드참가", "예: 기술분석", force_modal=True),
            _a("investigation_raid_start_v950", "수사 레이드 출발", "모집자가 2명 이상의 수사 레이드를 출발시킵니다.", "수사레이드출발"),
            _a("investigation_raid_action_v950", "수사 레이드 행동", "수색·분석·확보·교차검증으로 진행도를 올립니다.", "수사레이드행동", "예: 분석", force_modal=True),
            _a("investigation_raid_settle_v950", "수사 레이드 정산", "관리자가 완료된 수사 레이드를 한 번만 정산합니다.", "수사레이드정산"),
            _a("investigation_raid_reward_v950", "수사 레이드 보상", "정산된 수사 레이드의 개인 기여 보상을 받습니다.", "수사레이드보상"),
            _a("investigation_raid_history_v950", "수사 레이드 기록", "서버의 최근 협동 수사 레이드 기록을 확인합니다.", "수사레이드기록"),
            _a("v950_stability", "v9.5 안정화 검수", "수사·대피소·레이드·영문 명령 연결을 읽기 전용 검사합니다.", "950안정화검수"),
        ),
    ),
}

# v10.0.0 keeps the existing catalog intact and appends one self-contained page.
# The page has 22 entries, safely below Discord's 25-option select limit.
GAME_CATEGORIES = dict(GAME_CATEGORIES)
GAME_CATEGORIES["global_v1000"] = (
    "🌐 글로벌 생존자·언어",
    "개인/서버 언어, 임무 추적, 생존 도감, NPC 인연, 글로벌 탐사와 보상 회수 기능입니다.",
    (
        _a("language_v1000", "개인 언어", "게임 화면 언어를 한국어 또는 영어로 설정합니다.", "언어", "예: 한국어 또는 english", force_modal=True),
        _a("server_language_v1000", "서버 언어", "공개 공동 패널의 기본 언어를 설정합니다.", "서버언어", "예: 한국어 또는 english", force_modal=True),
        _a("tasks_v1000", "임무 추적기", "진행 중 콘텐츠와 미수령 보상을 한 화면에서 확인합니다.", "할일"),
        _a("codex_v1000", "생존 도감", "지역·세력·인카운트·사건 도감을 확인합니다.", "생존도감"),
        _a("item_codex_v1000", "아이템 도감", "보유·발견 아이템을 확인합니다.", "아이템도감"),
        _a("character_codex_v1000", "인물 도감", "주요 우호 인물과 관계 단계를 확인합니다.", "인물도감"),
        _a("region_codex_v1000", "지역 도감", "공동 탐험 지역과 상태를 확인합니다.", "지역도감"),
        _a("getting_started_v1000", "신규 안내", "신규 생존자의 첫 플레이 순서를 확인합니다.", "시작안내"),
        _a("returning_guide_v1000", "복귀 안내", "최근 대형 기능과 복귀 동선을 확인합니다.", "복귀안내"),
        _a("relationships_v1000", "NPC 인연", "NPC가 기억하는 개인 관계 기록을 확인합니다.", "인연"),
        _a("character_record_v1000", "인물 기록", "특정 NPC와의 관계·기억을 확인합니다.", "인물기록", "예: 구조대장", force_modal=True),
        _a("global_expedition_v1000", "글로벌 탐사", "이번 주 서버 공동 탐사 작전을 확인합니다.", "탐사작전"),
        _a("join_expedition_v1000", "탐사 참가", "정찰·의무·기술·경계 역할로 참가합니다.", "탐사참가", "예: 정찰", force_modal=True),
        _a("expedition_action_v1000", "탐사 행동", "신호분석·구조·복구·확보 행동을 수행합니다.", "탐사행동", "예: 신호분석", force_modal=True),
        _a("settle_expedition_v1000", "탐사 정산", "완료된 탐사 작전을 한 번만 정산합니다.", "탐사정산"),
        _a("claim_expedition_v1000", "탐사 보상", "정산된 탐사의 개인 기여 보상을 받습니다.", "탐사보상"),
        _a("expedition_history_v1000", "탐사 기록", "최근 글로벌 탐사 기록을 확인합니다.", "탐사기록"),
        _a("unclaimed_rewards_v1000", "미수령 보상", "감지 가능한 미수령 공동 보상을 점검합니다.", "미수령보상"),
        _a("claim_all_v1000", "전체 보상 수령", "안전하게 확인 가능한 보상을 순서대로 수령합니다.", "전체보상수령"),
        _a("language_audit_v1000", "다국어 검수", "단일 언어 출력과 번역 런타임을 검사합니다.", "다국어검수"),
        _a("command_audit_v1000", "명령어 검수", "한글·영문 명령 접근과 충돌을 검사합니다.", "명령어검수"),
        _a("v1000_stability", "v10.0 안정화 검수", "현지화·진행 연출·탐사·보상 연결을 검사합니다.", "1000안정화검수"),
    ),
)


def _build_action_catalog() -> Tuple[Dict[str, ActionSpec], Dict[str, str]]:
    index: Dict[str, ActionSpec] = {}
    categories: Dict[str, str] = {}
    duplicate_definitions: Dict[str, List[str]] = defaultdict(list)
    for category_key, (_title, _description, actions) in GAME_CATEGORIES.items():
        for action in actions:
            if action.key in index:
                duplicate_definitions[action.key].extend((categories[action.key], category_key))
                continue
            index[action.key] = action
            categories[action.key] = category_key
    if duplicate_definitions:
        details = {key: sorted(set(values)) for key, values in duplicate_definitions.items()}
        raise RuntimeError(f"게임 기능 키 중복 정의: {details}")
    return index, categories


ACTION_INDEX, ACTION_CATEGORY = _build_action_catalog()

MAX_GAME_FAVORITES = 20
MAX_GAME_RECENT = 10
RISKY_ACTION_KEYS = {
    "discard", "enhance", "protected_enhance", "reroll_option",
    "deposit", "withdraw", "loan", "repay", "shark_borrow", "shark_repay",
    "blackjack", "highlow", "slots", "dice", "baccarat", "roulette",
    "frequency", "gamble_explore", "casino_exchange", "casino_buy",
    "lucky_wheel", "coinflip", "allin", "guild_leave", "party_leave",
    "sell", "market_buy", "sell_cancel", "auction_register", "auction_bid",
    "auction_finish", "transfer", "pet_buy",
}


# =========================================================
# V7.0.1 명령어 가시성 패치
# 한 카테고리에 기능이 25개를 넘으면 Discord Select 제한에 걸리므로
# 목적별 기능군으로 먼저 묶고, 각 기능군 안에서 최대 25개씩 표시합니다.
# 기존 prefix 명령은 삭제하지 않고 그대로 유지합니다.
# =========================================================
GAME_SECTIONS: Mapping[str, Sequence[Tuple[str, str, str, Sequence[str]]]] = {
    "survival": (
        ("basics", "🧾 기본 생존", "정보·출석·상태·튜토리얼처럼 가장 먼저 쓰는 기능입니다.", ("info", "wallet", "attendance", "attendance_reward", "support", "status", "rest", "tutorial")),
        ("jobs", "🧑‍🔧 직업", "직업을 살펴보고 선택하거나 변경합니다.", ("jobs", "job_choose", "job_info", "job_change")),
        ("growth_loop", "🌱 성장 루프", "오늘 할 일, 일일·주간 미션, 누적 참여와 따라잡기 보급을 관리합니다.", ("growth_board", "mission_reward_v710", "lifetime_reward_v710", "catchup_support_v710")),
        ("quests", "🎯 기존 퀘스트·시즌", "기존 일일·주간 퀘스트, 시즌 패스, 업적과 칭호를 관리합니다.", ("daily_quest", "daily_reward", "weekly_quest", "weekly_reward", "season_pass", "season_reward", "achievements", "titles", "title_set", "ranking")),
    ),
    "equipment": (
        ("manage", "🎒 상점·보유·장착", "장비를 사고 확인하고 장착하는 기본 흐름입니다.", ("shop", "equipment_list", "buy", "inventory", "equipment", "equip", "unequip", "discard", "identify", "new_gear")),
        ("enhance", "✨ 강화·옵션·프리셋", "강화, 보호 강화, 옵션, 세트 효과, 장비 프리셋과 랭킹입니다.", ("enhance", "enhance_info", "protected_enhance", "equipment_option", "reroll_option", "set_effect", "equipment_preset_v710", "enhance_rank")),
        ("craft", "🛠️ 제작·수리·개조", "재료 확인부터 제작, 수리, 무기 개조까지 이어집니다.", ("materials", "craft_list", "craft", "durability", "repair_weapon", "mod_list", "craft_mod", "install_mod", "economy_balance")),
    ),
    "combat": (
        ("dungeon", "⚔️ 훈련·던전·레이드", "전투 연습, 던전, 레이드와 PVP를 진행합니다.", ("training", "monsters", "dungeon", "deep_dungeon", "dungeon_record", "boss_codex", "raid", "raid_attack", "pvp")),
        ("region", "🗺️ 지역 탐험", "지역 정보·이동·탐색과 좀비 도감을 확인합니다.", ("region_list", "region_info", "region_move", "region_explore", "zombie_codex")),
        ("invasion", "🚨 서버 침공", "서버 공동 침공 참가, 공격, 랭킹과 상점입니다.", ("invasion", "invasion_join", "invasion_attack", "invasion_rank", "invasion_shop")),
    ),
    "worldboss": (
        ("battle", "🌋 전투·기여·보상", "현재 보스를 확인하고 공격한 뒤 전투·주간 기여도와 보상을 관리합니다.", ("worldboss_status", "worldboss_attack_v630", "worldboss_contribution", "worldboss_ranking_v630", "worldboss_weekly_rank_v710", "worldboss_weekly_reward_v710", "worldboss_reward", "worldboss_reward_list")),
        ("records", "📚 목록·도감", "보스 6종과 개인 누적 기록을 확인합니다.", ("worldboss_list", "worldboss_codex_v630")),
        ("admin", "🧪 관리자 테스트", "실전과 분리된 샌드박스 보스를 소환하고 점검합니다.", ("worldboss_spawn_admin", "worldboss_test_admin", "worldboss_test_status", "worldboss_test_attack")),
    ),
    "expedition": (
        ("adventure", "🧭 원정 진행", "원정 출발과 턴제 행동, 전술 전투, 보급을 진행합니다.", ("expedition", "exp_help", "exp_list", "exp_start", "exp_action", "tactical_combat", "tactical_dungeon", "exp_abandon", "exp_supply")),
        ("records", "📋 원정 관리", "유물 발견, 기록, 랭킹, 장비와 임무를 확인합니다.", ("exp_relic", "exp_record", "exp_rank", "exp_gear", "exp_mission", "exp_mission_reward", "exp_recovery")),
        ("relic", "🔮 유물·숙련", "유물 장착·강화·분해와 생활 숙련도를 관리합니다.", ("relic", "relic_equip", "relic_unequip", "relic_enhance", "relic_dismantle", "life_mastery", "overall_rank")),
    ),
    "life": (
        ("activities", "🌲 생활 활동", "알바와 채집 활동, 자원·인카운트 기록입니다.", ("work", "coin", "gather", "fish", "lumber", "mine", "resources", "encounter_codex")),
        ("ruin_farming", "🧭 폐허 파밍·생활 기술", "지역 파밍, 다채로운 인카운트, 우호 세력, 폐품 공방, 전파 해독, 납품과 연구를 실행합니다.", ("farming_menu", "farming_regions", "farming_start", "farming_choice", "farming_history", "farming_encounter_codex_v811", "workshop", "scrap_identify", "scrap_dismantle", "scrap_repair", "signal_search_v770", "signal_decode_v770", "signal_history_v770", "contract_board", "contract_accept", "contract_deliver", "contract_status", "laboratory", "research_start", "research_progress", "blueprints", "v770_stability", "v811_stability")),
        ("server_disaster", "🚨 서버 공동 재난", "서버 전체가 현장 역할과 자원 납품으로 재난을 해결하고 기여 보상·버프를 받습니다.", ("disaster_status", "disaster_missions", "disaster_join", "disaster_deliver", "disaster_ranking", "disaster_reward", "disaster_buff", "disaster_spawn", "disaster_settle", "v780_stability")),
        ("base", "🏕️ 기지·세계 이벤트", "기지 성장, 날씨, 운세, 무전과 방어전입니다.", ("base", "base_build", "base_upgrade", "base_collect", "weather", "daily_fortune", "radio_signal", "hazard_zone", "random_box", "base_defense", "base_defense_attack")),
        ("market", "📦 자원 시장", "자원을 사고팔거나 기지 칩으로 교환합니다.", ("resource_market", "resource_buy", "resource_sell", "base_chip_exchange")),
        ("bank", "🏦 은행", "입출금, 대출, 상환, 이자와 신용 기록입니다.", ("bank", "deposit", "withdraw", "loan", "repay", "bank_interest", "credit", "bank_history")),
        ("shark", "🦈 사채", "고위험 사채 대출과 상환·추심 상태입니다.", ("loan_shark", "shark_borrow", "shark_repay", "shark_collection")),
    ),
    "digging": (
        ("treasure", "⛏️ 굴착·감정", "땅을 파고 보물을 감정해 보관합니다.", ("dig", "treasure_box", "appraisers", "treasure_appraise")),
    ),
    "card_games": (
        ("cards", "🃏 카드게임 8종", "기존 모집·예약·환불 흐름으로 포커·화투·파티 카드게임을 시작합니다.", ("card_game_menu", "abaddon_ai", "abaddon_wager", "poker", "texas_holdem_v1010", "omaha_holdem_v1010", "seven_stud_v1010", "matgo_v1010", "gostop_v1010", "one_card", "joker_draw")),
        ("companions", "🤝 NPC 동료", "관계 기억을 실제 영입·배치·대화·일일 임무로 연결합니다.", ("companions_v1010", "recruit_companion_v1010", "assign_companion_v1010", "companion_mission_v1010")),
    ),
    "casino": (
        ("lobby", "🎰 카지노 로비·보상", "잔액, 환전, VIP, 미션, 상점과 랭킹을 관리합니다.", ("casino", "casino_balance", "casino_history", "casino_rank", "casino_chips", "casino_exchange", "casino_vip", "casino_jackpot", "casino_mission", "casino_mission_reward", "casino_achievement", "casino_shop", "casino_buy", "casino_season_rank")),
        ("games", "🎲 카지노 게임", "식량 또는 칩을 사용하는 도박 게임입니다. 실행 전 금액을 꼭 확인하세요.", ("blackjack", "highlow", "slots", "dice", "baccarat", "roulette", "frequency", "gamble_explore", "lucky_wheel", "coinflip", "allin")),
    ),
    "story": (
        ("season1", "📻 시즌 1 · 검은 주파수", "첫 번째 메인 스토리를 시작하고 선택·기록을 관리합니다.", ("story1", "story1_start", "story1_choose", "story1_history", "story1_restart")),
        ("season2", "🚢 시즌 2 · 백색 방주", "두 번째 스토리와 장면·엔딩 수집·계승 기록입니다.", ("story2", "story2_start", "story2_choose", "story2_history", "story2_restart", "story2_scene", "story2_collection", "story2_legacy")),
        ("season3", "👑 시즌 3 · 종말의 왕좌", "세 번째 스토리의 시작·선택·기록·재시작입니다.", ("story3", "story3_start", "story3_choose", "story3_history", "story3_restart")),
        ("season4", "🚂 시즌 4 · 황혼의 종착역", "네 번째 스토리와 시즌 전체 여정·엔딩 유산 보상입니다.", ("story4", "story4_start", "story4_choose", "story4_history", "story4_restart", "story_journey", "story_legacy")),
        ("quiz", "🧠 오늘의 퀴즈", "오늘 문제를 풀고 문제은행·누적 랭킹을 확인합니다.", ("daily_quiz", "quiz_answer", "quiz_rank", "quiz_stats")),
    ),
    "guild": (
        ("organization", "🏰 길드 조직", "기존 길드 기능과 가입·직책·운영 설정입니다.", ("guild_list", "guild_create", "guild_join", "guild_info", "guild_donate", "guild_upgrade", "guild_dashboard", "guild_description", "guild_settings", "guild_apply", "guild_applications", "guild_application_process", "guild_role", "guild_kick", "guild_transfer", "guild_leave")),
        ("base", "🏗️ 공동 기지·임무", "시설 건설·강화·생산과 일일·주간 공동 목표입니다.", ("guild_base", "guild_build", "guild_facility_upgrade", "guild_base_collect", "guild_missions", "guild_mission_reward")),
        ("vault", "🏦 통합 금고", "식량·자원 입금과 승인형 출금 요청입니다.", ("guild_vault", "guild_deposit", "guild_withdraw_request")),
    ),
    "guild_raid": (
        ("vault_admin", "🧾 금고 승인·감사", "출금 승인·거절과 거래 기록을 확인합니다.", ("guild_withdraw_approve", "guild_withdraw_reject", "guild_transactions")),
        ("raid", "👹 주간 길드 레이드", "전술 프리셋·연습·기록·부위 파괴·기여도·개인 보상입니다.", ("guild_raid", "guild_raid_ready", "guild_raid_preset", "guild_raid_practice", "guild_raid_history", "guild_raid_attack", "guild_raid_reward", "guild_raid_ranking", "guild_overall_ranking")),
        ("audit", "🛡️ 길드 안정화", "읽기 전용 감사·복구 미리보기·v7.5 안정화 검사입니다.", ("guild_audit", "guild_repair_preview", "v750_stability")),
        ("dispatch", "🧭 길드 협동 파견", "모집·역할 편성·출발·정산·개인 보상과 무변경 모의 계산입니다.", ("guild_dispatch", "guild_dispatch_open", "guild_dispatch_join", "guild_dispatch_start", "guild_dispatch_settle", "guild_dispatch_reward", "guild_dispatch_history", "guild_dispatch_practice", "v760_stability")),
    ),
    "social": (
        ("party", "👥 파티", "파티 생성·가입·정보·사냥·탈퇴입니다.", ("party_create", "party_join", "party_info", "party_hunt", "party_leave")),
        ("trade", "💰 거래·경매", "개인 송금, 거래소 판매·구매와 경매를 관리합니다.", ("market", "sell", "market_buy", "sell_cancel", "auction_search", "auction_register", "auction_bid", "auction_finish", "auction_history", "transfer")),
    ),
    "world_map": (
        ("navigation", "🛰️ 단말기·공동 지도", "상태 맞춤 단말기와 지역 전체 현황·개인 기록입니다.", ("terminal_v810", "world_map_v810", "world_region_info_v810", "frontier_status_v810", "exploration_history_v810")),
        ("scouting", "🧭 지역 정찰·개척 기부", "현장 선택형 정찰과 자원 기부로 공동 개척도를 올립니다.", ("world_scout_v810", "world_choice_v810", "frontier_donate_v810")),
        ("outpost_boss", "🏕️ 거점·지역 보스", "감시탑·정화소·보급소 건설과 지역 보스 전투·보상입니다.", ("outpost_v810", "outpost_build_v810", "region_boss_v810", "region_boss_attack_v810", "region_reward_v810")),
        ("map_admin", "🛡️ 지도·오류 안정화", "최신 패치 검사와 관리자 점검·오류 사건 조회입니다.", ("admin_check_v810", "error_lookup_v810", "recent_errors_v810", "v810_stability")),
    ),
    "community_ops": (
        ("disaster_auto", "🚨 자동 재난·기상", "재난 예보·기상·기록과 관리자 자동 발생 설정입니다.", ("disaster_forecast_v790", "disaster_weather_v790", "disaster_history_v790", "disaster_auto_v790", "disaster_channel_v790")),
        ("notifications", "🔔 통합 알림·운영", "개인 알림 설정과 기존 운영 기능의 통합 진입점·분석입니다.", ("notification_center_v790", "my_notifications_v790", "operations_hub_v790", "operations_analytics_v790", "v790_stability")),
        ("suggestions", "💡 공개 건의·로드맵", "건의 등록·투표·상태 변경과 개발 로드맵입니다.", ("suggestion_panel_v790", "suggestion_list_v790", "suggestion_status_v790", "roadmap_v790", "guild_invite_accept_v790")),
        ("temp_voice", "🎙️ 임시 분대 음성방", "입장 자동 생성과 방장 이름·잠금·초대·인원·위임 기능입니다.", ("temp_voice_setup_v790", "temp_voice_name_v790", "temp_voice_lock_v790", "temp_voice_invite_v790", "temp_voice_limit_v790", "temp_voice_transfer_v790")),
        ("highlights", "⭐ 서버 하이라이트", "반응 기준 하이라이트 보드 설정·확인·수동 추가·제거입니다.", ("highlight_setup_v790", "highlight_status_v790", "highlight_add_v790", "highlight_remove_v790")),
        ("channel_guides", "📌 채널 안내", "기존 채널별 규칙과 가이드 설치 기능을 연결합니다.", ("channel_rules_existing",)),
    ),
    "pets": (
        ("growth", "🐾 펫 성장", "펫을 구매하고 장착·훈련·먹이·모험·진화합니다.", ("pet_shop", "pet_buy", "pet_info", "pet_train", "pet_list", "pet_equip", "pet_feed", "pet_adventure", "pet_evolve")),
        ("codex", "📖 통합 도감", "장비·펫·몬스터 수집과 도감 보상을 확인합니다.", ("codex", "codex_gear", "codex_pet", "codex_monster", "codex_reward")),
    ),
    "factions_world": (
        ("factions", "🤝 세력·평판·거점", "NPC 세력 관계, 일일 의뢰와 증표 교환입니다.", ("factions_v900", "reputation_v900", "faction_info_v900", "faction_outpost_v900", "faction_mission_v900", "faction_mission_accept_v900", "faction_mission_complete_v900", "faction_shop_v900", "faction_exchange_v900")),
        ("trade", "🚚 무역로·호송", "지역 수요, 호송 모집·편성·출발·정산·보상입니다.", ("trade_routes_v900", "regional_economy_v900", "convoy_open_v900", "convoy_join_v900", "convoy_start_v900", "convoy_status_v900", "convoy_settle_v900", "convoy_reward_v900", "convoy_cancel_v900")),
        ("war", "⚔️ 세력전쟁", "구조·방어·복구 전선과 참여·기부·정산·보상·다음 전쟁입니다.", ("faction_war_v900", "front_select_v900", "war_join_v900", "war_donate_v900", "war_contribution_v900", "war_settle_v900", "war_reward_v900", "war_restart_v900")),
        ("season5", "📖 시즌 5·세계 상태", "세계 지표, 서버 투표·결정·연대기와 v9.0 검수입니다.", ("world_status_v900", "season5_v900", "season5_vote_v900", "season5_decide_v900", "world_chronicle_v900", "v900_stability")),
    ),
    "world_cycle_profession": (
        ("cycle", "🌍 세계 순환", "안전한 시간 순환과 오늘의 세계 상황입니다.", ("world_cycle_v920", "world_cycle_settings_v920", "world_cycle_now_v920", "today_world_v920")),
        ("recovery", "🏗️ 공동 복구", "6개 장기 작전의 버튼 행동·물자 납품·기여도·보상입니다.", ("recovery_v920", "recovery_start_v920", "recovery_join_v920", "recovery_supply_v920", "recovery_contribution_v920", "recovery_reward_v920")),
        ("directive", "📜 세계 지령", "주간 공동 목표 투표와 관리자 확정입니다.", ("directive_v920", "directive_vote_v920", "directive_decide_v920")),
        ("specialization", "🧑‍🔧 직업 전문화", "기존 기본 직업을 유지하는 전문화 12종입니다.", ("specialization_v920", "specialization_list_v920", "specialization_info_v920", "specialization_choose_v920", "specialization_change_v920")),
        ("squad", "👥 분대 전술", "기존 파티 기반 전술·역할·준비·협동 작전·기록입니다.", ("squad_tactics_v920", "squad_tactic_set_v920", "squad_role_v920", "squad_ready_v920", "squad_operation_v920", "squad_history_v920")),
        ("audit", "🛡️ v9.2 안정화", "세계 순환·복구·전문화·분대 전술 연결을 읽기 전용 검사합니다.", ("v920_stability",)),
    ),
    "investigation_shelter": (
        ("investigation", "🔎 사건 수사", "공동 사건판·단서 조사·조합·추리와 주간 현상금입니다.", ("case_board_v950", "clue_list_v950", "clue_investigate_v950", "clue_combine_v950", "case_solve_v950", "bounty_v950", "bounty_track_v950", "bounty_report_v950", "bounty_history_v950")),
        ("shelter", "🏕️ 개인 대피소", "테마·장식 제작·트로피 전시·방문·좋아요입니다.", ("shelter_v950", "shelter_decorate_v950", "decoration_list_v950", "decoration_craft_v950", "showcase_v950", "trophy_display_v950", "shelter_visit_v950", "shelter_like_v950")),
        ("raid", "🕵️ 협동 수사 레이드", "모집·역할 참가·출발·행동·정산·보상·기록입니다.", ("investigation_raid_v950", "investigation_raid_open_v950", "investigation_raid_join_v950", "investigation_raid_start_v950", "investigation_raid_action_v950", "investigation_raid_settle_v950", "investigation_raid_reward_v950", "investigation_raid_history_v950")),
        ("audit", "🛡️ v9.5 안정화", "수사·대피소·레이드·영문 명령 연결을 읽기 전용 검사합니다.", ("v950_stability",)),
    ),
}

QUICK_PATHS: Mapping[str, Tuple[str, str, Sequence[str]]] = {
    "first_day": ("🌱 처음 시작", "가입 뒤 첫날에 필요한 정보·직업·출석·성장 보드·첫 전투 순서입니다.", ("info", "attendance", "jobs", "job_choose", "specialization_list_v920", "tutorial", "growth_board", "catchup_support_v710", "shop", "inventory", "equipment", "training")),
    "grow": ("📈 강해지고 싶어요", "성장 보드에서 목표를 확인하고 프리셋·강화·미션 보상으로 성장합니다.", ("growth_board", "mission_reward_v710", "info", "shop", "inventory", "equipment", "equipment_preset_v710", "equip", "enhance", "season_pass", "achievements")),
    "fight": ("⚔️ 전투하고 싶어요", "상태를 확인하고 훈련·던전·지역·레이드·월드보스에 도전합니다.", ("status", "rest", "training", "dungeon", "tactical_combat", "world_map_v810", "world_scout_v810", "region_list", "region_explore", "raid", "worldboss_status")),
    "earn": ("🥫 식량과 자원이 필요해요", "지원금·생활 활동·폐허 파밍·납품 계약과 공동 재난으로 재화와 기여 보상을 모읍니다.", ("wallet", "support", "work", "gather", "fish", "lumber", "mine", "farming_menu", "contract_board", "world_scout_v810", "frontier_donate_v810", "disaster_status", "disaster_join", "dig", "treasure_appraise", "resource_market")),
    "story": ("📖 스토리를 보고 싶어요", "메인 시즌과 원정·유물·세계 상태 콘텐츠로 이동합니다.", ("story1", "story2", "story3", "story4", "season5_v900", "world_status_v900", "world_cycle_v920", "today_world_v920", "case_board_v950", "clue_investigate_v950", "bounty_v950", "expedition", "exp_start", "relic", "daily_quiz")),
    "community": ("🤝 같이 놀고 싶어요", "길드·세력·호송·공동 전쟁·파티·카드게임으로 이동합니다.", ("guild_dashboard", "guild_base", "factions_v900", "convoy_status_v900", "faction_war_v900", "recovery_v920", "party_create", "squad_tactics_v920", "investigation_raid_v950", "shelter_v950", "card_game_menu", "market", "transfer")),
}


def _section_entry(category_key: str, section_key: str) -> Optional[Tuple[str, str, str, Sequence[str]]]:
    return next((item for item in GAME_SECTIONS.get(category_key, ()) if item[0] == section_key), None)


def _section_specs(category_key: str, section_key: str) -> List[ActionSpec]:
    entry = _section_entry(category_key, section_key)
    if entry is None:
        return []
    return [ACTION_INDEX[key] for key in entry[3] if key in ACTION_INDEX]


def _quick_path_specs(path_key: str) -> List[ActionSpec]:
    entry = QUICK_PATHS.get(path_key)
    if entry is None:
        return []
    return [ACTION_INDEX[key] for key in entry[2] if key in ACTION_INDEX]


def _today_specs(user: Dict[str, Any]) -> List[ActionSpec]:
    # 매일 반복 가치가 높은 기능을 먼저 제시하고, 상태에 따라 회복·직업 선택을 앞에 붙입니다.
    keys: List[str] = []
    if not user.get("job"):
        keys.extend(("jobs", "job_choose"))
    if int(user.get("hp", 100) or 0) < 60 or int(user.get("stamina", 100) or 0) < 40:
        keys.extend(("status", "rest"))
    keys.extend(("attendance", "daily_quest", "daily_reward", "weekly_quest", "season_pass", "daily_quiz", "daily_fortune", "weather", "work", "worldboss_status"))
    result: List[ActionSpec] = []
    for key in keys:
        spec = ACTION_INDEX.get(key)
        if spec is not None and spec not in result:
            result.append(spec)
    return result[:20]


def _scan_game_sections() -> Dict[str, Any]:
    expected = set(ACTION_INDEX)
    assigned: List[str] = []
    locations: Dict[str, List[str]] = defaultdict(list)
    invalid_categories: List[str] = []
    duplicate_sections: List[str] = []
    overflow: List[str] = []
    for category_key, sections in GAME_SECTIONS.items():
        if category_key not in GAME_CATEGORIES:
            invalid_categories.append(category_key)
        section_names: set[str] = set()
        for section_key, _title, _description, keys in sections:
            if section_key in section_names:
                duplicate_sections.append(f"{category_key}/{section_key}")
            section_names.add(section_key)
            if len(keys) > SELECT_PAGE_SIZE:
                overflow.append(f"{category_key}/{section_key} ({len(keys)}개)")
            for raw_key in keys:
                key = str(raw_key)
                assigned.append(key)
                locations[key].append(f"{category_key}/{section_key}")
    counts = Counter(assigned)
    return {
        "missing": sorted(expected.difference(counts)),
        "duplicated": {key: locations[key] for key, count in counts.items() if count > 1},
        "unknown": sorted(set(counts).difference(expected)),
        "invalid_categories": sorted(invalid_categories),
        "duplicate_sections": sorted(duplicate_sections),
        "overflow": sorted(overflow),
    }


def _repair_game_sections() -> Dict[str, Any]:
    """게임센터 메타데이터 오류가 봇 전체 부팅을 막지 않도록 안전 복구합니다.

    첫 번째 정상 연결을 보존하고 중복·미등록 키를 제거합니다. 누락된 기능은
    원래 카테고리의 복구 섹션으로 되돌립니다. 실제 명령이나 사용자 데이터는
    삭제하지 않으며 메뉴 연결만 정규화합니다.
    """
    global GAME_SECTIONS
    seen: set[str] = set()
    repaired: Dict[str, List[Tuple[str, str, str, Tuple[str, ...]]]] = {}
    removed_duplicates: Dict[str, List[str]] = defaultdict(list)
    removed_unknown: Dict[str, List[str]] = defaultdict(list)
    renamed_sections: List[str] = []

    for category_key, sections in GAME_SECTIONS.items():
        if category_key not in GAME_CATEGORIES:
            continue
        rows: List[Tuple[str, str, str, Tuple[str, ...]]] = []
        used_section_names: set[str] = set()
        for section_key, title, description, keys in sections:
            safe_section_key = str(section_key)
            if safe_section_key in used_section_names:
                suffix = 2
                while f"{safe_section_key}_{suffix}" in used_section_names:
                    suffix += 1
                renamed_sections.append(f"{category_key}/{safe_section_key}->{safe_section_key}_{suffix}")
                safe_section_key = f"{safe_section_key}_{suffix}"
            used_section_names.add(safe_section_key)
            clean: List[str] = []
            for raw_key in keys:
                key = str(raw_key)
                if key not in ACTION_INDEX:
                    removed_unknown[f"{category_key}/{safe_section_key}"].append(key)
                    continue
                if key in seen:
                    removed_duplicates[f"{category_key}/{safe_section_key}"].append(key)
                    continue
                seen.add(key)
                clean.append(key)
            for index in range(0, len(clean), SELECT_PAGE_SIZE):
                chunk = tuple(clean[index:index + SELECT_PAGE_SIZE])
                chunk_key = safe_section_key if index == 0 else f"{safe_section_key}_{index // SELECT_PAGE_SIZE + 1}"
                chunk_title = str(title) if index == 0 else f"{title} {index // SELECT_PAGE_SIZE + 1}"
                rows.append((chunk_key, chunk_title, str(description), chunk))
        repaired[category_key] = rows

    missing = [key for key in ACTION_INDEX if key not in seen]
    by_category: Dict[str, List[str]] = defaultdict(list)
    for key in missing:
        by_category[ACTION_CATEGORY[key]].append(key)
    for category_key, keys in by_category.items():
        rows = repaired.setdefault(category_key, [])
        for index in range(0, len(keys), SELECT_PAGE_SIZE):
            number = index // SELECT_PAGE_SIZE + 1
            rows.append((
                f"recovered_{number}",
                "🛟 자동 복구 기능" if number == 1 else f"🛟 자동 복구 기능 {number}",
                "메뉴 연결 검사에서 누락되어 안전하게 복구된 기능입니다.",
                tuple(keys[index:index + SELECT_PAGE_SIZE]),
            ))

    GAME_SECTIONS = {key: tuple(rows) for key, rows in repaired.items()}
    return {
        "removed_duplicates": dict(removed_duplicates),
        "removed_unknown": dict(removed_unknown),
        "renamed_sections": renamed_sections,
        "recovered_missing": missing,
    }


def _validate_game_sections(*, strict: Optional[bool] = None) -> Dict[str, Any]:
    strict_mode = (os.getenv("ABADDON_STRICT_MENU_VALIDATION", "0") == "1") if strict is None else bool(strict)
    before = _scan_game_sections()
    has_error = any(bool(before[key]) for key in before)
    if not has_error:
        return {"ok": True, "repaired": False, "before": before, "after": before, "changes": {}}

    message = (
        "게임 기능군 연결 오류: "
        f"missing={before['missing']}, duplicated={before['duplicated']}, unknown={before['unknown']}, "
        f"invalid_categories={before['invalid_categories']}, duplicate_sections={before['duplicate_sections']}, "
        f"overflow={before['overflow']}"
    )
    if strict_mode:
        raise RuntimeError(message)

    changes = _repair_game_sections()
    after = _scan_game_sections()
    remaining = any(bool(after[key]) for key in after)
    if remaining:
        raise RuntimeError(f"{message} / 자동 복구 후에도 오류가 남았습니다: {after}")
    print(f"[ABADDON v{VERSION}] 게임센터 연결 자동 복구: {changes}", flush=True)
    return {"ok": True, "repaired": True, "before": before, "after": after, "changes": changes}


GAME_SECTION_VALIDATION = _validate_game_sections()


# =========================================================
# 인터랙션 -> 기존 명령어 브리지
# =========================================================
class _SyntheticMessage:
    def __init__(self, interaction: discord.Interaction, content: str) -> None:
        self.id = int(interaction.id)
        actor = getattr(interaction, "user", None)
        if actor is None or actor is getattr(discord.utils, "MISSING", object()) or not hasattr(actor, "id"):
            actor = getattr(getattr(interaction, "message", None), "author", None)
        self.author = actor
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.content = content
        self.created_at = datetime.now(timezone.utc)
        self.edited_at = None
        self.webhook_id = None
        self.attachments: List[Any] = []
        self.mentions: List[Any] = []
        self.role_mentions: List[Any] = []
        self.channel_mentions: List[Any] = []
        self.reference = None

    async def add_reaction(self, _emoji: Any) -> None:
        return None

    async def delete(self, **_kwargs: Any) -> None:
        # 메뉴에서 실행된 합성 메시지는 실제 사용자 메시지가 아니므로 안전하게 무시합니다.
        return None

    async def edit(self, **_kwargs: Any) -> None:
        return None

    async def pin(self, **_kwargs: Any) -> None:
        return None

    async def unpin(self, **_kwargs: Any) -> None:
        return None

    @property
    def jump_url(self) -> str:
        return str(getattr(getattr(self, "interaction", None), "message", "") or "")


class _InteractionResponseProxy:
    """Lazy message-like proxy for a component's initial response.

    Fetching the real webhook message costs another REST request, so common
    command paths avoid it. Legacy callbacks that truly need edit/delete/reaction
    semantics can still opt into that request lazily.
    """

    def __init__(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        self._message = None

    async def _fetch(self):
        if self._message is None:
            self._message = await self.interaction.original_response()
        return self._message

    async def edit(self, **kwargs: Any) -> Any:
        if "embed" in kwargs:
            kwargs["embed"] = _safe_embed(kwargs.get("embed"))
        if "view" in kwargs:
            kwargs["view"] = _safe_view(kwargs.get("view"))
        try:
            return await self.interaction.edit_original_response(**kwargs)
        except (discord.NotFound, discord.HTTPException):
            message = await self._fetch()
            return await message.edit(**kwargs)

    async def delete(self, **kwargs: Any) -> None:
        delay = float(kwargs.get("delay", 0) or 0)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await self.interaction.delete_original_response()
        except (discord.NotFound, discord.HTTPException):
            return None

    async def add_reaction(self, emoji: Any) -> None:
        message = await self._fetch()
        await message.add_reaction(emoji)

    async def remove_reaction(self, emoji: Any, member: Any) -> None:
        message = await self._fetch()
        await message.remove_reaction(emoji, member)

    async def pin(self, **kwargs: Any) -> None:
        message = await self._fetch()
        await message.pin(**kwargs)

    async def unpin(self, **kwargs: Any) -> None:
        message = await self._fetch()
        await message.unpin(**kwargs)

    @property
    def id(self) -> int:
        # Interaction IDs are unique snowflakes and sufficient for local maps.
        return int(getattr(self.interaction, "id", 0) or 0)

    @property
    def jump_url(self) -> str:
        source = getattr(self.interaction, "message", None)
        return str(getattr(source, "jump_url", "") or "")


class InteractionCommandContext:
    """기존 prefix 명령 callback을 Discord 드롭다운에서도 안전하게 재사용하는 최소 Context입니다."""

    def __init__(self, bot: commands.Bot, interaction: discord.Interaction, command: commands.Command, raw: str = "", *, prefer_channel_delivery: bool = False) -> None:
        self.bot = bot
        # v18.1.4: Component clicks reuse PREFIX command semantics.
        # HybridCommand.can_run treats ctx.interaction != None as an application-command
        # invocation and expects Discord's app-command baton. A button/select interaction
        # has no prefix Context baton, so keep the real component separately and expose
        # ctx.interaction=None to every legacy prefix/hybrid command.
        self.component_interaction = interaction
        self.interaction = None
        actor = getattr(interaction, "user", None)
        if actor is None or actor is getattr(discord.utils, "MISSING", object()) or not hasattr(actor, "id"):
            actor = getattr(getattr(interaction, "message", None), "author", None)
        self.author = actor
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.command = command
        self.prefix = "!"
        self.clean_prefix = "!"
        self.invoked_with = command.name
        self.invoked_parents: List[str] = []
        self.invoked_subcommand = None
        self.subcommand_passed = None
        self.command_failed = False
        self.args: List[Any] = []
        self.kwargs: Dict[str, Any] = {}
        self.message = _SyntheticMessage(interaction, f"!{command.qualified_name} {raw}".strip())
        if self.author is not None:
            self.message.author = self.author
        # Prefix callbacks must not see this synthetic message as a slash/app-command.
        self.message.interaction = None
        self.message.component_interaction = interaction
        self.cog = _real_cog(command)
        # v18.1.3: contextual buttons reuse legacy prefix callbacks, but their
        # command results should use the normal bot/channel REST route instead
        # of interaction follow-up webhooks. This significantly reduces webhook
        # bursts on shared hosting IPs while preserving ordinary game-center
        # interaction behaviour.
        self.prefer_channel_delivery = bool(prefer_channel_delivery)
        self.current_parameter = None
        self.current_argument = None

    @property
    def me(self) -> Optional[discord.Member]:
        return self.guild.me if self.guild else None

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        return self.guild.voice_client if self.guild else None

    @property
    def permissions(self) -> discord.Permissions:
        if self.channel is None or self.author is None:
            return discord.Permissions.none()
        return self.channel.permissions_for(self.author)

    @property
    def bot_permissions(self) -> discord.Permissions:
        if self.channel is None or self.me is None:
            return discord.Permissions.none()
        return self.channel.permissions_for(self.me)

    @property
    def valid(self) -> bool:
        return self.command is not None

    async def send(self, content: Optional[str] = None, **kwargs: Any) -> Any:
        ephemeral = bool(kwargs.pop("ephemeral", False))
        delete_after = kwargs.pop("delete_after", None)
        kwargs.pop("mention_author", None)
        if "embed" in kwargs:
            kwargs["embed"] = _safe_embed(kwargs.get("embed"))
        if "embeds" in kwargs:
            kwargs["embeds"] = [_safe_embed(item) for item in list(kwargs.get("embeds") or [])[:10] if item is not None]
        if "view" in kwargs:
            kwargs["view"] = _safe_view(kwargs.get("view"))
        if content is not None:
            content = str(content)[:2000]

        # v18.1.3 single-request fast path:
        # Most legacy commands answer quickly. Their FIRST ctx.send becomes the
        # component's initial response itself, so a button click costs only one
        # Discord REST callback instead of defer + webhook/channel send.
        if self.prefer_channel_delivery and not self.component_interaction.response.is_done():
            response_kwargs = dict(kwargs)
            # InteractionResponse.send_message does not accept ordinary Messageable
            # routing-only arguments. Keep only portable payload fields.
            for key in ("wait", "reference", "nonce", "stickers"):
                response_kwargs.pop(key, None)
            try:
                await self.component_interaction.response.send_message(
                    content=content,
                    ephemeral=ephemeral,
                    **response_kwargs,
                )
                proxy = _InteractionResponseProxy(self.component_interaction)
                if delete_after is not None:
                    async def _later_delete() -> None:
                        await asyncio.sleep(max(0.1, float(delete_after)))
                        await proxy.delete()
                    asyncio.create_task(_later_delete())
                return proxy
            except discord.HTTPException as exc:
                try:
                    from apocalypse_bot.core import rate_limit_guard as _rate_guard
                    _kind = _rate_guard.detect_rate_limit(exc)
                    if _kind:
                        _rate_guard.note_rate_limit(_kind, str(exc))
                        raise
                except ImportError:
                    pass
            except TypeError:
                # Rare legacy payload option unsupported by interaction response:
                # fall through to normal channel delivery without retrying webhook.
                pass

        if self.prefer_channel_delivery and ephemeral and self.component_interaction.response.is_done():
            # Preserve privacy for the rare slow legacy command that requested
            # an ephemeral reply after the delayed ACK already fired.
            followup_kwargs = dict(kwargs)
            followup_kwargs.setdefault("wait", True)
            try:
                return await self.component_interaction.followup.send(content=content, ephemeral=True, **followup_kwargs)
            except discord.HTTPException as exc:
                try:
                    from apocalypse_bot.core import rate_limit_guard as _rate_guard
                    _kind = _rate_guard.detect_rate_limit(exc)
                    if _kind:
                        _rate_guard.note_rate_limit(_kind, str(exc))
                except ImportError:
                    pass
                raise

        if self.prefer_channel_delivery and self.channel is not None and hasattr(self.channel, "send"):
            channel_kwargs = dict(kwargs)
            channel_kwargs.pop("wait", None)
            try:
                message = await self.channel.send(content=content, **channel_kwargs)
                _schedule_delete(message, delete_after)
                return message
            except discord.HTTPException as exc:
                # Never fire an immediate second Discord request after 1015/429.
                try:
                    from apocalypse_bot.core import rate_limit_guard as _rate_guard
                    _kind = _rate_guard.detect_rate_limit(exc)
                    if _kind:
                        _rate_guard.note_rate_limit(_kind, str(exc))
                        raise
                except ImportError:
                    _kind = ""
                if not _kind:
                    print(f"[ABADDON v18.1.3 channel payload fallback] {type(exc).__name__}: {exc}", flush=True)
                    safe_content = (content or "🫧 결과 화면 일부를 간단한 텍스트로 전환했습니다.")[:2000]
                    try:
                        message = await self.channel.send(content=safe_content)
                        _schedule_delete(message, delete_after)
                        return message
                    except discord.HTTPException:
                        raise exc

        # Non-bridge game-center paths keep their original followup behavior.
        followup_kwargs = dict(kwargs)
        followup_kwargs.setdefault("wait", True)
        try:
            message = await self.component_interaction.followup.send(content=content, ephemeral=ephemeral, **followup_kwargs)
            _schedule_delete(message, delete_after)
            return message
        except discord.HTTPException as exc:
            try:
                from apocalypse_bot.core import rate_limit_guard as _rate_guard
                _kind = _rate_guard.detect_rate_limit(exc)
                if _kind:
                    _rate_guard.note_rate_limit(_kind, str(exc))
                    raise
            except ImportError:
                pass
            print(f"[ABADDON UI payload fallback] {type(exc).__name__}: {exc}", flush=True)
            safe_content = (content or "🫧 결과 화면 일부가 Discord 제한을 넘어 텍스트로 전환했습니다.")[:2000]
            return await self.component_interaction.followup.send(content=safe_content, ephemeral=ephemeral, wait=True)

    async def reply(self, content: Optional[str] = None, **kwargs: Any) -> Any:
        kwargs.pop("mention_author", None)
        return await self.send(content, **kwargs)

    async def defer(self, **_kwargs: Any) -> None:
        return None

    async def trigger_typing(self) -> None:
        if self.channel is not None:
            await self.channel.trigger_typing()

    def typing(self, *, ephemeral: bool = False):
        del ephemeral
        if self.channel is None:
            raise RuntimeError("채널을 찾을 수 없습니다.")
        return self.channel.typing()

    async def send_help(self, *_args: Any, **_kwargs: Any) -> None:
        await self.send(f"ℹ️ `{self.clean_prefix}{self.command.qualified_name}` 명령의 기존 도움말을 확인해주세요.")

    async def invoke(self, command: commands.Command, /, *args: Any, **kwargs: Any) -> Any:
        previous = self.command
        try:
            self.command = command
            cog = _real_cog(command)
            if cog is not None:
                return await command.callback(cog, self, *args, **kwargs)
            return await command.callback(self, *args, **kwargs)
        finally:
            self.command = previous

    async def reinvoke(self, *, call_hooks: bool = False, restart: bool = True) -> Any:
        del call_hooks, restart
        if self.command is None:
            return None
        return await self.invoke(self.command, *self.args, **self.kwargs)


class GameBridgeError(RuntimeError):
    pass


def _clip_text(value: Any, limit: int, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text[:limit]


def _safe_select_options(options: Sequence[Any], fallback_label: str = "표시할 항목이 없습니다") -> List[Any]:
    """Normalize select options to Discord API limits and remove duplicate/empty values."""
    cleaned: List[Any] = []
    seen: set[str] = set()
    for index, option in enumerate(list(options)[:25]):
        value = _clip_text(getattr(option, "value", ""), 100, f"option_{index}")
        if not value or value in seen:
            continue
        seen.add(value)
        label = _clip_text(getattr(option, "label", ""), 100, f"항목 {index + 1}")
        description_raw = getattr(option, "description", None)
        description = _clip_text(description_raw, 100) if description_raw else None
        emoji = getattr(option, "emoji", None)
        kwargs = {
            "label": label or f"항목 {index + 1}",
            "value": value,
            "description": description,
            "default": bool(getattr(option, "default", False)),
        }
        try:
            if emoji:
                kwargs["emoji"] = emoji
            cleaned.append(discord.SelectOption(**kwargs))
        except (TypeError, ValueError):
            kwargs.pop("emoji", None)
            cleaned.append(discord.SelectOption(**kwargs))
    if not cleaned:
        cleaned.append(discord.SelectOption(label=_clip_text(fallback_label, 100, "항목 없음"), value="__empty__"))
    # A single-value select may not contain more than one default option.
    default_seen = False
    for option in cleaned:
        if bool(getattr(option, "default", False)):
            if default_seen:
                option.default = False
            default_seen = True
    return cleaned[:25]


def _safe_embed(embed: Optional[discord.Embed]) -> Optional[discord.Embed]:
    """Rebuild an embed inside Discord's per-field and 6000-character limits."""
    if embed is None:
        return None
    title = _clip_text(getattr(embed, "title", ""), 256) or None
    description = _clip_text(getattr(embed, "description", ""), 4096) or None
    rebuilt = discord.Embed(
        title=title,
        description=description,
        color=getattr(embed, "color", None),
        url=getattr(embed, "url", None),
        timestamp=getattr(embed, "timestamp", None),
    )
    budget = 6000 - len(title or "") - len(description or "")
    author = getattr(embed, "author", None)
    author_name = _clip_text(getattr(author, "name", ""), 256)
    if author_name and budget > 0:
        author_name = author_name[:budget]
        rebuilt.set_author(name=author_name, url=getattr(author, "url", None), icon_url=getattr(author, "icon_url", None))
        budget -= len(author_name)
    for field in list(getattr(embed, "fields", []) or [])[:25]:
        if budget <= 2:
            break
        name = _clip_text(getattr(field, "name", ""), min(256, budget), "-")
        budget -= len(name)
        value = _clip_text(getattr(field, "value", ""), min(1024, max(1, budget)), "-")
        budget -= len(value)
        rebuilt.add_field(name=name or "-", value=value or "-", inline=bool(getattr(field, "inline", False)))
    footer = getattr(embed, "footer", None)
    footer_text = _clip_text(getattr(footer, "text", ""), min(2048, max(0, budget)))
    if footer_text:
        rebuilt.set_footer(text=footer_text, icon_url=getattr(footer, "icon_url", None))
    image = getattr(embed, "image", None)
    image_url = str(getattr(image, "url", "") or "")
    if image_url:
        rebuilt.set_image(url=image_url)
    thumbnail = getattr(embed, "thumbnail", None)
    thumbnail_url = str(getattr(thumbnail, "url", "") or "")
    if thumbnail_url:
        rebuilt.set_thumbnail(url=thumbnail_url)
    return rebuilt


def _safe_view(view: Optional[discord.ui.View]) -> Optional[discord.ui.View]:
    """Normalize legacy component payloads to Discord's five-row layout limits."""
    if view is None:
        return None
    children = list(getattr(view, "children", []) or [])
    prepared: List[Any] = []
    for child in children[:25]:
        if isinstance(child, discord.ui.Select):
            child.options = _safe_select_options(list(getattr(child, "options", []) or []))
            child.placeholder = _clip_text(getattr(child, "placeholder", ""), 150) or None
        elif isinstance(child, discord.ui.Button):
            if getattr(child, "label", None):
                child.label = _clip_text(child.label, 80)
        custom_id = getattr(child, "custom_id", None)
        if custom_id and len(str(custom_id)) > 100:
            child.custom_id = str(custom_id)[:100]
        prepared.append(child)

    # v18.3.0: Avoid structurally rebuilding an already-valid View.
    # discord.py 2.7 detaches Item.view immediately on remove_item(), and doing
    # remove/add churn on every component edit creates an unnecessary dispatch
    # cache race. First simulate placement; almost every current ABADDON View is
    # already valid and can be returned without touching its child bindings.
    def _layout_fits(rows: List[Any]) -> bool:
        if len(rows) > 25:
            return False
        row_kind: List[Optional[str]] = [None] * 5
        row_count = [0] * 5
        for child in rows:
            is_select = isinstance(child, discord.ui.Select)
            target: Optional[int] = None
            requested = getattr(child, "row", None)
            candidates = ([requested] if isinstance(requested, int) and 0 <= requested <= 4 else []) + list(range(5))
            seen = set()
            for row in candidates:
                if row in seen:
                    continue
                seen.add(row)
                if is_select:
                    if row_kind[row] is None:
                        target = row
                        break
                elif row_kind[row] in {None, "button"} and row_count[row] < 5:
                    target = row
                    break
            if target is None:
                return False
            row_kind[target] = "select" if is_select else "button"
            row_count[target] += 1
        return True

    if len(children) <= 25 and _layout_fits(prepared):
        return view

    # Legacy fallback only: repack genuinely invalid/oversized payloads.
    # v18.3.0's dynamic View guard keeps dispatch bindings safe if this rare
    # fallback runs on a live message View.
    try:
        for child in list(getattr(view, "children", []) or []):
            view.remove_item(child)
        row_kind: List[Optional[str]] = [None] * 5
        row_count = [0] * 5
        for child in prepared:
            is_select = isinstance(child, discord.ui.Select)
            target: Optional[int] = None
            requested = getattr(child, "row", None)
            candidates = ([requested] if isinstance(requested, int) and 0 <= requested <= 4 else []) + list(range(5))
            for row in candidates:
                if is_select:
                    if row_kind[row] is None:
                        target = row
                        break
                elif row_kind[row] in {None, "button"} and row_count[row] < 5:
                    target = row
                    break
            if target is None:
                continue
            child.row = target
            view.add_item(child)
            row_kind[target] = "select" if is_select else "button"
            row_count[target] += 1
    except Exception as exc:
        # Keep the sanitized original view if an exotic third-party item cannot be repacked.
        print(f"[ABADDON UI layout sanitizer] {type(exc).__name__}: {exc}", flush=True)
    return view


def _unwrap_annotation(annotation: Any) -> Any:
    if annotation is inspect._empty:
        return str
    origin = get_origin(annotation)
    if origin is Union:
        args = [item for item in get_args(annotation) if item is not type(None)]
        return _unwrap_annotation(args[0]) if args else str
    return annotation


def _extract_snowflake(text: str) -> Optional[int]:
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


async def _convert_argument(ctx: InteractionCommandContext, annotation: Any, value: str) -> Any:
    annotation = _unwrap_annotation(annotation)
    annotation_name = str(annotation)
    raw = str(value).strip()

    if annotation in {str, Any} or annotation is inspect._empty or annotation_name in {"<class 'str'>", "str", "typing.Any"}:
        return raw
    if annotation is int or annotation_name in {"<class 'int'>", "int"}:
        try:
            return int(raw.replace(",", ""))
        except ValueError as exc:
            raise GameBridgeError(f"`{raw}`은 정수가 아닙니다.") from exc
    if annotation is float or annotation_name in {"<class 'float'>", "float"}:
        try:
            return float(raw)
        except ValueError as exc:
            raise GameBridgeError(f"`{raw}`은 숫자가 아닙니다.") from exc
    if annotation is bool or annotation_name in {"<class 'bool'>", "bool"}:
        lowered = raw.casefold()
        if lowered in {"켜기", "on", "true", "1", "예", "yes"}:
            return True
        if lowered in {"끄기", "off", "false", "0", "아니오", "no"}:
            return False
        raise GameBridgeError("켜기 또는 끄기를 입력해주세요.")

    guild = ctx.guild
    if guild is None:
        raise GameBridgeError("서버 안에서만 사용할 수 있습니다.")

    if "Member" in annotation_name or annotation is discord.Member:
        snowflake = _extract_snowflake(raw)
        member = guild.get_member(snowflake) if snowflake else None
        if member is None and snowflake:
            try:
                member = await guild.fetch_member(snowflake)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is None:
            lowered = raw.casefold()
            member = discord.utils.find(
                lambda item: item.name.casefold() == lowered or item.display_name.casefold() == lowered,
                guild.members,
            )
        if member is None:
            raise GameBridgeError(f"멤버 `{raw}`을 찾지 못했습니다. 멘션 또는 사용자 ID를 사용해주세요.")
        return member

    if "Role" in annotation_name or annotation is discord.Role:
        snowflake = _extract_snowflake(raw)
        role = guild.get_role(snowflake) if snowflake else None
        if role is None:
            lowered = raw.casefold().lstrip("@")
            role = discord.utils.find(lambda item: item.name.casefold() == lowered, guild.roles)
        if role is None:
            raise GameBridgeError(f"역할 `{raw}`을 찾지 못했습니다.")
        return role

    if "TextChannel" in annotation_name:
        snowflake = _extract_snowflake(raw)
        channel = guild.get_channel(snowflake) if snowflake else None
        if not isinstance(channel, discord.TextChannel):
            lowered = raw.casefold().lstrip("#")
            channel = discord.utils.find(lambda item: item.name.casefold() == lowered, guild.text_channels)
        if not isinstance(channel, discord.TextChannel):
            raise GameBridgeError(f"텍스트 채널 `{raw}`을 찾지 못했습니다.")
        return channel

    if "VoiceChannel" in annotation_name:
        snowflake = _extract_snowflake(raw)
        channel = guild.get_channel(snowflake) if snowflake else None
        if not isinstance(channel, discord.VoiceChannel):
            lowered = raw.casefold().lstrip("#")
            channel = discord.utils.find(lambda item: item.name.casefold() == lowered, guild.voice_channels)
        if not isinstance(channel, discord.VoiceChannel):
            raise GameBridgeError(f"음성 채널 `{raw}`을 찾지 못했습니다.")
        return channel

    return raw


def _parameter_required(parameter: inspect.Parameter) -> bool:
    return parameter.default is inspect._empty


def _command_requires_input(command: commands.Command) -> bool:
    return any(_parameter_required(param) for param in command.clean_params.values())


async def _parse_arguments(ctx: InteractionCommandContext, command: commands.Command, raw: str) -> Tuple[List[Any], Dict[str, Any]]:
    params = list(command.clean_params.values())
    raw = str(raw or "").strip()
    if not params:
        if raw:
            raise GameBridgeError("이 명령은 입력값이 필요하지 않습니다.")
        return [], {}

    try:
        tokens = shlex.split(raw) if raw else []
    except ValueError as exc:
        raise GameBridgeError("따옴표가 닫히지 않았습니다. 입력값을 확인해주세요.") from exc

    positional: List[Any] = []
    keyword: Dict[str, Any] = {}
    cursor = 0

    # 인수가 하나뿐인 문자열 명령은 공백을 포함한 전체 값을 그대로 전달합니다.
    if len(params) == 1 and _unwrap_annotation(params[0].annotation) is str:
        if not raw and _parameter_required(params[0]):
            raise GameBridgeError(f"`{params[0].name}` 입력이 필요합니다.")
        if raw:
            if params[0].kind is inspect.Parameter.KEYWORD_ONLY:
                keyword[params[0].name] = raw
            else:
                positional.append(raw)
        return positional, keyword

    for index, parameter in enumerate(params):
        is_last = index == len(params) - 1
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            remaining = " ".join(tokens[cursor:]).strip()
            if not remaining:
                if _parameter_required(parameter):
                    raise GameBridgeError(f"`{parameter.name}` 입력이 필요합니다.")
                continue
            keyword[parameter.name] = await _convert_argument(ctx, parameter.annotation, remaining)
            cursor = len(tokens)
            continue

        if cursor >= len(tokens):
            if _parameter_required(parameter):
                raise GameBridgeError(f"`{parameter.name}` 입력이 필요합니다.")
            continue

        # 마지막 인수가 문자열이면 남은 토큰 전체를 합쳐 전달합니다.
        annotation = _unwrap_annotation(parameter.annotation)
        if is_last and annotation is str:
            token = " ".join(tokens[cursor:])
            cursor = len(tokens)
        else:
            token = tokens[cursor]
            cursor += 1
        positional.append(await _convert_argument(ctx, parameter.annotation, token))

    if cursor < len(tokens):
        raise GameBridgeError("입력값이 너무 많습니다. 여러 단어 아이템 이름은 큰따옴표로 묶어주세요.")
    return positional, keyword


async def _bridge_notice(interaction: discord.Interaction, text: str) -> None:
    """Send one failure notice without overwriting the source component message."""
    payload = str(text or "")[:2000]
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(payload, ephemeral=True)
        else:
            await interaction.followup.send(payload, ephemeral=True, wait=False)
    except (discord.NotFound, discord.HTTPException):
        # Do not retry a failed Discord webhook: direct prefix commands remain available.
        pass


async def _bridge_late_ack(interaction: discord.Interaction, delay: float = 1.8) -> None:
    """Acknowledge only slow commands; quick commands answer in the first response."""
    await asyncio.sleep(max(0.5, float(delay)))
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(thinking=False)
    except (discord.NotFound, discord.HTTPException):
        pass


async def _invoke_command(
    bot: commands.Bot,
    interaction: discord.Interaction,
    command_name: str,
    raw: str = "",
    *,
    prefer_channel_delivery: bool = True,
) -> bool:
    # v18.1.3: no eager defer. Quick legacy commands reply through the initial
    # component response (one request). Only commands that exceed ~1.8 seconds
    # receive a silent deferred ACK, then deliver through the ordinary channel.
    late_ack = asyncio.create_task(_bridge_late_ack(interaction), name=f"abaddon-bridge-ack-{interaction.id}")
    command = bot.get_command(command_name)
    if command is None:
        await _bridge_notice(interaction, f"❌ 기존 명령 `{command_name}`을 찾지 못했습니다.")
        return False

    ctx = InteractionCommandContext(bot, interaction, command, raw, prefer_channel_delivery=prefer_channel_delivery)
    actor = getattr(ctx, "author", None)
    if actor is None or type(actor).__name__ == "_MissingSentinel" or not hasattr(actor, "id"):
        if not late_ack.done():
            late_ack.cancel()
        await _bridge_notice(interaction, "🫧 버튼 실행 사용자 정보를 확인하지 못했습니다. 기존 명령을 직접 입력해주세요.")
        return False
    ctx._v1813_button_bridge = bool(prefer_channel_delivery)
    ctx._v1814_prefix_semantics = True

    def _record_v1815_bridge_failure(error: Any) -> None:
        recorder = getattr(bot, "v1815_record_bridge_failure", None)
        if callable(recorder):
            try:
                recorder(ctx, error)
            except Exception as metric_error:
                print(f"[v18.1.5 버튼 사용 로그 경고] {type(metric_error).__name__}: {metric_error}", flush=True)

    hook_attempted = False
    succeeded = False
    bot.dispatch("command", ctx)
    try:
        can_run = await command.can_run(ctx)  # type: ignore[arg-type]
        if not can_run:
            raise commands.CheckFailure("명령 실행 조건을 충족하지 못했습니다.")
        cooldown_result = command._prepare_cooldowns(ctx)  # type: ignore[arg-type,attr-defined]
        if inspect.isawaitable(cooldown_result):
            await cooldown_result
        args, kwargs = await _parse_arguments(ctx, command, raw)
        cog = _real_cog(command)
        # Match discord.py's ordinary Context shape for listeners/hooks.
        ctx.args = ([cog, ctx] if cog is not None else [ctx]) + list(args)
        ctx.kwargs = kwargs

        # 일반 prefix 명령과 같은 전역/코그/명령 훅을 거쳐
        # v7.0.2 사용자 잠금·운영 통계가 버튼 실행에서도 유지되게 합니다.
        hook_attempted = True
        await command.call_before_hooks(ctx)  # type: ignore[arg-type]
        # Keep the hardened Cog guard: some legacy registrations can expose a
        # discord.py MISSING sentinel instead of a real Cog. Prefix semantics are
        # fixed above at can_run; callback injection remains explicitly safe.
        if cog is not None:
            await command.callback(cog, ctx, *args, **kwargs)
        else:
            await command.callback(ctx, *args, **kwargs)
        succeeded = True
    except commands.CommandOnCooldown as exc:
        ctx.command_failed = True
        _record_v1815_bridge_failure(exc)
        await _bridge_notice(interaction, f"⏳ 재사용 대기 중입니다. **{exc.retry_after:.1f}초** 뒤 다시 시도해주세요.")
    except commands.MissingPermissions as exc:
        ctx.command_failed = True
        _record_v1815_bridge_failure(exc)
        missing = ", ".join(exc.missing_permissions)
        await _bridge_notice(interaction, f"🔒 필요한 권한이 없습니다: `{missing}`")
    except commands.CheckFailure as exc:
        ctx.command_failed = True
        _record_v1815_bridge_failure(exc)
        await _bridge_notice(interaction, "🔒 이 명령을 실행할 권한이나 조건이 충족되지 않았습니다.")
    except GameBridgeError as exc:
        ctx.command_failed = True
        _record_v1815_bridge_failure(exc)
        await _bridge_notice(interaction, f"⚠️ {exc}")
    except TypeError as exc:
        ctx.command_failed = True
        _record_v1815_bridge_failure(exc)
        print(f"[버튼 명령 입력 오류] command={command_name} {type(exc).__name__}: {exc}", flush=True)
        await _bridge_notice(
            interaction,
            f"🫧 입력값 모양이 맞지 않아요. `!{command_name} {command.signature}` 사용법을 확인해주세요.",
        )
    except Exception as exc:
        ctx.command_failed = True
        _record_v1815_bridge_failure(exc)
        incident = f"UI-{int(interaction.id) % 100000000:08d}"
        trace = " | ".join(line.strip() for line in traceback.format_exc(limit=3).splitlines()[-5:] if line.strip())
        print(
            f"[버튼 명령 오류:{incident}] command={command_name} {type(exc).__name__}: {exc}"
            + (f" · {trace[:700]}" if trace else ""),
            flush=True,
        )
        if _allow_failure_notice(int(interaction.user.id), command_name):
            await _bridge_notice(
                interaction,
                f"🫧 버튼 실행 중 문제가 생겼어요. 기존 `!{command_name}` 방식도 사용할 수 있어요.\n"
                f"사건 번호: `{incident}`",
            )
    finally:
        if hook_attempted:
            try:
                await command.call_after_hooks(ctx)  # type: ignore[arg-type]
            except Exception as hook_error:
                ctx.command_failed = True
                print(
                    f"[버튼 명령 종료 훅 오류] command={command_name} "
                    f"{type(hook_error).__name__}: {hook_error}",
                    flush=True,
                )
        if succeeded and not ctx.command_failed:
            # v7.1.0 성장 활동 집계 등 on_command_completion 기반 기능도 동일하게 작동합니다.
            bot.dispatch("command_completion", ctx)
    # v18.1.3 uses a silent component acknowledgement (thinking=False), so there
    # is no ephemeral thinking message to edit/delete after a successful bridge.
    # One interaction ACK + normal channel delivery is the complete happy path.
    if not interaction.response.is_done():
        # Successful no-output commands still need one acknowledgement.
        try:
            await interaction.response.defer(thinking=False)
        except (discord.NotFound, discord.HTTPException):
            pass
    if not late_ack.done():
        late_ack.cancel()
    return succeeded and not ctx.command_failed


# =========================================================
# 게임 드롭다운 UI
# =========================================================
def _ensure_game_center_state(user: Dict[str, Any]) -> Dict[str, Any]:
    root = user.setdefault("v601_game_center", {})
    favorites = [str(item) for item in root.get("favorites", []) if str(item) in ACTION_INDEX]
    recent = [str(item) for item in root.get("recent", []) if str(item) in ACTION_INDEX]
    root["favorites"] = list(dict.fromkeys(favorites))[:MAX_GAME_FAVORITES]
    root["recent"] = list(dict.fromkeys(recent))[:MAX_GAME_RECENT]
    return root


def _record_recent(get_user: Any, save_data: Any, user_id: int, spec: ActionSpec) -> None:
    user = get_user(user_id)
    state = _ensure_game_center_state(user)
    recent = [item for item in state["recent"] if item != spec.key]
    recent.insert(0, spec.key)
    state["recent"] = recent[:MAX_GAME_RECENT]
    save_data()


def _toggle_favorite(get_user: Any, save_data: Any, user_id: int, spec: ActionSpec) -> Tuple[bool, str]:
    user = get_user(user_id)
    state = _ensure_game_center_state(user)
    favorites = list(state["favorites"])
    if spec.key in favorites:
        favorites.remove(spec.key)
        state["favorites"] = favorites
        save_data()
        return False, f"☆ **{spec.label}**을 즐겨찾기에서 해제했습니다."
    if len(favorites) >= MAX_GAME_FAVORITES:
        return False, f"⚠️ 즐겨찾기는 최대 {MAX_GAME_FAVORITES}개까지 저장할 수 있습니다."
    favorites.append(spec.key)
    state["favorites"] = favorites
    save_data()
    return True, f"⭐ **{spec.label}**을 즐겨찾기에 추가했습니다."


def _favorite_specs(get_user: Any, user_id: int) -> List[ActionSpec]:
    state = _ensure_game_center_state(get_user(user_id))
    return [ACTION_INDEX[key] for key in state["favorites"] if key in ACTION_INDEX]


def _recent_specs(get_user: Any, user_id: int) -> List[ActionSpec]:
    state = _ensure_game_center_state(get_user(user_id))
    return [ACTION_INDEX[key] for key in state["recent"] if key in ACTION_INDEX]


def _search_specs(query: str) -> List[ActionSpec]:
    terms = [item for item in str(query).casefold().split() if item]
    if not terms:
        return []
    results: List[ActionSpec] = []
    for spec in ACTION_INDEX.values():
        category_key = ACTION_CATEGORY.get(spec.key, "")
        category_title = GAME_CATEGORIES.get(category_key, ("", "", ()))[0]
        haystack = " ".join(
            [spec.key, spec.label, spec.description, spec.command, spec.example, category_key, category_title]
        ).casefold()
        if all(term in haystack for term in terms):
            results.append(spec)
    return results[:25]


def _main_embed(user: Optional[Dict[str, Any]] = None) -> discord.Embed:
    total_actions = sum(len(item[2]) for item in GAME_CATEGORIES.values())
    state = _ensure_game_center_state(user) if user is not None else {"favorites": [], "recent": []}
    embed = discord.Embed(
        title=f"🎮 ABADDON v{VERSION} 게임 제어실",
        description=(
            "**처음이라면 `🌱 처음 시작`부터 누르세요.** 무엇을 하고 싶은지 고르면 필요한 기능만 순서대로 보여줍니다.\n"
            "익숙한 생존자는 카테고리 → 기능군 → 기능 순서로 선택하거나 검색·즐겨찾기를 사용할 수 있습니다."
        ),
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="🌱 초보 추천 순서",
        value="`정보 확인` → `직업 선택` → `출석` → `튜토리얼` → `첫 전투`",
        inline=False,
    )
    embed.add_field(name="카테고리", value=f"**{len(GAME_CATEGORIES)}개**", inline=True)
    embed.add_field(name="연결 기능", value=f"**{total_actions}개**", inline=True)
    embed.add_field(name="즐겨찾기", value=f"**{len(state['favorites'])}/{MAX_GAME_FAVORITES}**", inline=True)
    embed.add_field(name="사용 흐름", value="카테고리 → 기능군 → 미리보기 → 실행", inline=False)
    embed.add_field(name="기존 명령어", value="전부 유지 · 기존 `!명령어` 그대로 사용 가능", inline=False)
    embed.set_footer(text="본인만 조작할 수 있습니다 · 제한시간 5분 · 드롭다운 25개 제한 자동 분할")
    return embed


def _category_embed(category_key: str) -> discord.Embed:
    title, description, actions = GAME_CATEGORIES[category_key]
    sections = GAME_SECTIONS.get(category_key, ())
    embed = discord.Embed(title=title, description=description, color=discord.Color.dark_teal())
    embed.add_field(name="전체 기능", value=f"**{len(actions)}개**", inline=True)
    embed.add_field(name="기능군", value=f"**{len(sections)}개**", inline=True)
    if sections:
        lines = [f"**{section_title}** · {section_description}" for _key, section_title, section_description, _keys in sections]
        embed.add_field(name="무엇을 할지 먼저 고르세요", value="\n".join(lines)[:1024], inline=False)
    embed.set_footer(text="비슷한 명령은 기능군 안에 함께 묶었습니다. 기존 직접 명령은 삭제되지 않았습니다.")
    return embed


def _section_embed(category_key: str, section_key: str, page: int = 0) -> discord.Embed:
    entry = _section_entry(category_key, section_key)
    if entry is None:
        return _category_embed(category_key)
    _key, title, description, _keys = entry
    specs = _section_specs(category_key, section_key)
    page_count = max(1, (len(specs) - 1) // SELECT_PAGE_SIZE + 1)
    page = max(0, min(page, page_count - 1))
    visible = specs[page * SELECT_PAGE_SIZE:(page + 1) * SELECT_PAGE_SIZE]
    embed = discord.Embed(title=title, description=description, color=discord.Color.dark_teal())
    if visible:
        preview = "\n".join(f"• **{spec.label}** — {spec.description}" for spec in visible[:8])
        if len(visible) > 8:
            preview += f"\n• 그 외 **{len(visible) - 8}개** 기능"
        embed.add_field(name=f"이 기능군에서 할 수 있는 일 · {len(specs)}개", value=preview[:1024], inline=False)
    embed.add_field(name="선택 방법", value="아래 드롭다운에서 기능을 고르면 실행 전 설명과 입력 예시가 열립니다.", inline=False)
    embed.set_footer(text=f"{page + 1}/{page_count} 페이지 · 기존 !명령어 직접 입력도 계속 지원")
    return embed


def _quick_path_embed(path_key: str) -> discord.Embed:
    title, description, _keys = QUICK_PATHS[path_key]
    specs = _quick_path_specs(path_key)
    embed = discord.Embed(title=title, description=description, color=discord.Color.green())
    embed.add_field(
        name="추천 순서",
        value="\n".join(f"**{index}. {spec.label}** · {spec.description}" for index, spec in enumerate(specs, 1))[:1024],
        inline=False,
    )
    embed.set_footer(text="아래 목록에서 하나를 고르면 실행 전 미리보기가 열립니다.")
    return embed


def _action_embed(bot: commands.Bot, spec: ActionSpec, user: Dict[str, Any]) -> discord.Embed:
    state = _ensure_game_center_state(user)
    command = bot.get_command(spec.command)
    requires_input = bool(command and (spec.force_modal or _command_requires_input(command)))
    risky = spec.key in RISKY_ACTION_KEYS
    embed = discord.Embed(
        title=f"{'⚠️' if risky else '🎮'} {spec.label}",
        description=f"**무엇을 하나요?**\n{spec.description}",
        color=discord.Color.gold() if risky else discord.Color.dark_teal(),
    )
    category_key = ACTION_CATEGORY.get(spec.key, "")
    category_title = GAME_CATEGORIES.get(category_key, ("기타", "", ()))[0]
    embed.add_field(name="분류", value=category_title, inline=True)
    embed.add_field(name="입력", value="실행 후 입력창이 열림" if requires_input else "버튼 한 번으로 실행", inline=True)
    embed.add_field(name="기존 직접 명령", value=f"`!{spec.command}`", inline=False)
    if spec.example:
        embed.add_field(name="입력 예시", value=spec.example, inline=False)
    embed.add_field(
        name="사용 순서",
        value="1. 아래 **실행하기** 선택\n2. 필요한 값 입력\n3. 결과 확인" if requires_input else "아래 **실행하기** 버튼을 누르면 바로 결과가 표시됩니다.",
        inline=False,
    )
    embed.add_field(name="즐겨찾기", value="⭐ 등록됨" if spec.key in state["favorites"] else "☆ 미등록", inline=True)
    if risky:
        embed.add_field(
            name="실행 전 확인",
            value="식량·아이템·칩·길드 상태가 실제로 변경될 수 있습니다. 금액과 대상을 다시 확인하세요.",
            inline=False,
        )
    embed.set_footer(text="기존 명령어는 그대로 유지됩니다. 메뉴는 명령을 대신 찾아주는 안전한 실행 도구입니다.")
    return embed

def _list_embed(title: str, description: str, specs: Sequence[ActionSpec]) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.dark_teal())
    if specs:
        lines = []
        for index, spec in enumerate(specs, start=1):
            lines.append(f"**{index}. {spec.label}** · `!{spec.command}`")
        embed.add_field(name=f"기능 {len(specs)}개", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="표시할 기능 없음", value="게임 제어실에서 기능을 실행하거나 즐겨찾기에 추가해주세요.", inline=False)
    embed.set_footer(text="목록에서 기능을 고르면 실행 전 미리보기가 열립니다.")
    return embed


class GameInputModal(discord.ui.Modal):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        spec: ActionSpec,
        get_user: Any,
        save_data: Any,
    ) -> None:
        super().__init__(title=spec.label[:45], timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.spec = spec
        self.get_user = get_user
        self.save_data = save_data
        self.value_input = discord.ui.TextInput(
            label="입력값",
            placeholder=(spec.example or f"기존 사용법: !{spec.command}")[:100],
            required=_command_requires_input(bot.get_command(spec.command)) if bot.get_command(spec.command) else True,
            max_length=400,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        success = await _invoke_command(self.bot, interaction, self.spec.command, str(self.value_input.value))
        if success:
            _record_recent(self.get_user, self.save_data, interaction.user.id, self.spec)


class GameSearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, owner_id: int, get_user: Any, save_data: Any) -> None:
        super().__init__(title="게임 기능 검색", timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        self.query_input = discord.ui.TextInput(
            label="검색어",
            placeholder="예: 강화, 원정, 블랙잭, 길드, 펫",
            required=True,
            max_length=60,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        query = str(self.query_input.value).strip()
        specs = _search_specs(query)
        if not specs:
            await interaction.response.send_message(f"🔎 `{query}` 검색 결과가 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_list_embed(f"🔎 검색 결과 · {query}", "라벨·설명·기존 명령어를 함께 검색했습니다.", specs),
            view=GameSpecListView(self.bot, self.owner_id, specs, self.get_user, self.save_data),
            ephemeral=True,
        )


class GameActionSelect(discord.ui.Select):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        category_key: str,
        section_key: str,
        specs: Sequence[ActionSpec],
        page: int,
        get_user: Any,
        save_data: Any,
    ) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.category_key = category_key
        self.section_key = section_key
        self.get_user = get_user
        self.save_data = save_data
        self.page = max(0, int(page))
        start = self.page * SELECT_PAGE_SIZE
        visible = list(specs[start:start + SELECT_PAGE_SIZE])
        self.specs = {spec.key: spec for spec in visible}
        options = [
            discord.SelectOption(
                label=spec.label[:100],
                value=spec.key,
                description=f"!{spec.command} · {spec.description}"[:100],
            )
            for spec in visible
        ]
        end = start + len(visible)
        super().__init__(
            placeholder=f"기능 선택 · {start + 1}-{end}/{len(specs)}",
            min_values=1,
            max_values=1,
            options=_safe_select_options(options),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        spec = self.specs.get(self.values[0])
        if spec is None:
            await interaction.response.send_message("⚠️ 선택한 기능을 찾지 못했습니다.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_action_embed(self.bot, spec, self.get_user(interaction.user.id)),
            view=GameActionDetailView(
                self.bot,
                self.owner_id,
                spec,
                self.get_user,
                self.save_data,
                self.category_key,
                self.section_key,
                self.page,
            ),
        )


class GameSpecListSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, owner_id: int, specs: Sequence[ActionSpec], get_user: Any, save_data: Any) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        self.specs = {spec.key: spec for spec in specs[:SELECT_PAGE_SIZE]}
        options = [
            discord.SelectOption(label=spec.label[:100], value=spec.key, description=f"!{spec.command} · {spec.description}"[:100])
            for spec in specs[:SELECT_PAGE_SIZE]
        ]
        super().__init__(placeholder="추천 기능을 선택하세요", min_values=1, max_values=1, options=_safe_select_options(options))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        spec = self.specs.get(self.values[0])
        if spec is None:
            await interaction.response.send_message("⚠️ 선택한 기능을 찾지 못했습니다.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_action_embed(self.bot, spec, self.get_user(interaction.user.id)),
            view=GameActionDetailView(self.bot, self.owner_id, spec, self.get_user, self.save_data, None, None, 0),
        )


class GameActionDetailView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        spec: ActionSpec,
        get_user: Any,
        save_data: Any,
        category_key: Optional[str],
        section_key: Optional[str],
        page: int,
    ) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.spec = spec
        self.get_user = get_user
        self.save_data = save_data
        self.category_key = category_key
        self.section_key = section_key
        self.page = page

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="실행하기", emoji="▶️", style=discord.ButtonStyle.success, row=1)
    async def execute(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        command = self.bot.get_command(self.spec.command)
        if command is None:
            await interaction.response.send_message(f"❌ 기존 명령 `{self.spec.command}`을 찾지 못했습니다.", ephemeral=True)
            return
        if self.spec.force_modal or _command_requires_input(command):
            await interaction.response.send_modal(
                GameInputModal(self.bot, self.owner_id, self.spec, self.get_user, self.save_data)
            )
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        success = await _invoke_command(self.bot, interaction, self.spec.command)
        if success:
            _record_recent(self.get_user, self.save_data, interaction.user.id, self.spec)

    @discord.ui.button(label="즐겨찾기", emoji="⭐", style=discord.ButtonStyle.secondary, row=1)
    async def favorite(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        _added, message = _toggle_favorite(self.get_user, self.save_data, interaction.user.id, self.spec)
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="이전 목록", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.category_key and self.section_key:
            await interaction.response.edit_message(
                embed=_section_embed(self.category_key, self.section_key, self.page),
                view=GameActionView(
                    self.bot,
                    self.owner_id,
                    self.category_key,
                    self.section_key,
                    self.get_user,
                    self.save_data,
                    self.page,
                ),
            )
            return
        await interaction.response.edit_message(
            embed=_main_embed(self.get_user(interaction.user.id)),
            view=GameCategoryView(self.bot, self.owner_id, self.get_user, self.save_data),
        )

    @discord.ui.button(label="처음으로", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=_main_embed(self.get_user(interaction.user.id)),
            view=GameCategoryView(self.bot, self.owner_id, self.get_user, self.save_data),
        )


class GameActionView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        owner_id: int,
        category_key: str,
        section_key: str,
        get_user: Any,
        save_data: Any,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.category_key = category_key
        self.section_key = section_key
        self.get_user = get_user
        self.save_data = save_data
        self.specs = _section_specs(category_key, section_key)
        self.page_count = max(1, (len(self.specs) - 1) // SELECT_PAGE_SIZE + 1)
        self.page = max(0, min(int(page), self.page_count - 1))
        self.add_item(GameActionSelect(bot, owner_id, category_key, section_key, self.specs, self.page, get_user, save_data))
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.page_count - 1
        self.back.label = "기능군" if len(GAME_SECTIONS.get(category_key, ())) > 1 else "카테고리"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="이전", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        page = max(0, self.page - 1)
        await interaction.response.edit_message(
            embed=_section_embed(self.category_key, self.section_key, page),
            view=GameActionView(self.bot, self.owner_id, self.category_key, self.section_key, self.get_user, self.save_data, page),
        )

    @discord.ui.button(label="다음", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        page = min(self.page_count - 1, self.page + 1)
        await interaction.response.edit_message(
            embed=_section_embed(self.category_key, self.section_key, page),
            view=GameActionView(self.bot, self.owner_id, self.category_key, self.section_key, self.get_user, self.save_data, page),
        )

    @discord.ui.button(label="기능군", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        sections = GAME_SECTIONS.get(self.category_key, ())
        if len(sections) > 1:
            await interaction.response.edit_message(
                embed=_category_embed(self.category_key),
                view=GameSectionView(self.bot, self.owner_id, self.category_key, self.get_user, self.save_data),
            )
            return
        await interaction.response.edit_message(
            embed=_main_embed(self.get_user(interaction.user.id)),
            view=GameCategoryView(self.bot, self.owner_id, self.get_user, self.save_data),
        )


class GameSectionSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, owner_id: int, category_key: str, get_user: Any, save_data: Any) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.category_key = category_key
        self.get_user = get_user
        self.save_data = save_data
        options = [
            discord.SelectOption(label=title[:100], value=key, description=description[:100])
            for key, title, description, _keys in GAME_SECTIONS.get(category_key, ())
        ]
        super().__init__(placeholder="먼저 하고 싶은 기능군을 선택하세요", min_values=1, max_values=1, options=_safe_select_options(options))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        section_key = self.values[0]
        await interaction.response.edit_message(
            embed=_section_embed(self.category_key, section_key),
            view=GameActionView(self.bot, self.owner_id, self.category_key, section_key, self.get_user, self.save_data),
        )


class GameSectionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, category_key: str, get_user: Any, save_data: Any) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.category_key = category_key
        self.get_user = get_user
        self.save_data = save_data
        self.add_item(GameSectionSelect(bot, owner_id, category_key, get_user, save_data))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="카테고리", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=_main_embed(self.get_user(interaction.user.id)),
            view=GameCategoryView(self.bot, self.owner_id, self.get_user, self.save_data),
        )

class GameSpecListView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, specs: Sequence[ActionSpec], get_user: Any, save_data: Any) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        self.add_item(GameSpecListSelect(bot, owner_id, specs, get_user, save_data))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="처음으로", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=_main_embed(self.get_user(interaction.user.id)),
            view=GameCategoryView(self.bot, self.owner_id, self.get_user, self.save_data),
        )


class QuickPathSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, owner_id: int, get_user: Any, save_data: Any) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        options = [
            discord.SelectOption(label=title[:100], value=key, description=description[:100])
            for key, (title, description, _keys) in QUICK_PATHS.items()
        ]
        super().__init__(placeholder="지금 원하는 목표를 선택하세요", min_values=1, max_values=1, options=_safe_select_options(options))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        path_key = self.values[0]
        specs = _quick_path_specs(path_key)
        await interaction.response.edit_message(
            embed=_quick_path_embed(path_key),
            view=GameSpecListView(self.bot, self.owner_id, specs, self.get_user, self.save_data),
        )


class QuickPathView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, get_user: Any, save_data: Any) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        self.add_item(QuickPathSelect(bot, owner_id, get_user, save_data))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="카테고리 보기", emoji="🗂️", style=discord.ButtonStyle.secondary, row=1)
    async def categories(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=_main_embed(self.get_user(interaction.user.id)),
            view=GameCategoryView(self.bot, self.owner_id, self.get_user, self.save_data),
        )


class GameCategorySelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, owner_id: int, get_user: Any, save_data: Any) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        options = [
            discord.SelectOption(
                label=title[:100],
                value=key,
                description=f"{len(GAME_SECTIONS.get(key, ()))}개 기능군 · {description}"[:100],
            )
            for key, (title, description, _actions) in GAME_CATEGORIES.items()
        ]
        super().__init__(placeholder="익숙한 기능은 카테고리에서 찾으세요", min_values=1, max_values=1, options=_safe_select_options(options))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
            return
        category_key = self.values[0]
        sections = GAME_SECTIONS.get(category_key, ())
        if len(sections) == 1:
            section_key = sections[0][0]
            await interaction.response.edit_message(
                embed=_section_embed(category_key, section_key),
                view=GameActionView(self.bot, self.owner_id, category_key, section_key, self.get_user, self.save_data),
            )
            return
        await interaction.response.edit_message(
            embed=_category_embed(category_key),
            view=GameSectionView(self.bot, self.owner_id, category_key, self.get_user, self.save_data),
        )


class GameCategoryView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, get_user: Any, save_data: Any) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.get_user = get_user
        self.save_data = save_data
        self.add_item(GameCategorySelect(bot, owner_id, get_user, save_data))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("🔒 이 게임 제어실은 처음 연 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.button(label="처음 시작", emoji="🌱", style=discord.ButtonStyle.success, row=1)
    async def beginner(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="🌱 무엇부터 해야 할지 골라주세요",
            description=(
                "명령어 이름을 외울 필요가 없습니다. 아래 목표 중 하나를 선택하면 필요한 기능만 추천 순서로 보여줍니다.\n"
                "이미 플레이 중이어도 성장·전투·돈벌이 루트로 바로 이동할 수 있습니다."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="첫날 기본 순서", value="정보 → 직업 → 출석 → 튜토리얼 → 첫 전투", inline=False)
        await interaction.response.edit_message(
            embed=embed,
            view=QuickPathView(self.bot, self.owner_id, self.get_user, self.save_data),
        )

    @discord.ui.button(label="오늘 추천", emoji="☀️", style=discord.ButtonStyle.primary, row=1)
    async def today(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        user = self.get_user(interaction.user.id)
        specs = _today_specs(user)
        await interaction.response.send_message(
            embed=_list_embed("☀️ 오늘 먼저 할 일", "출석·퀘스트·상태를 기준으로 자주 놓치는 일일 기능을 모았습니다.", specs),
            view=GameSpecListView(self.bot, self.owner_id, specs, self.get_user, self.save_data),
            ephemeral=True,
        )

    @discord.ui.button(label="즐겨찾기", emoji="⭐", style=discord.ButtonStyle.secondary, row=1)
    async def favorites(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        specs = _favorite_specs(self.get_user, interaction.user.id)
        if not specs:
            await interaction.response.send_message(
                "⭐ 아직 즐겨찾기가 없습니다. 기능 미리보기에서 `즐겨찾기`를 눌러주세요.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=_list_embed("⭐ 내 게임 즐겨찾기", "자주 쓰는 기능을 최대 20개까지 저장합니다.", specs),
            view=GameSpecListView(self.bot, self.owner_id, specs, self.get_user, self.save_data),
            ephemeral=True,
        )

    @discord.ui.button(label="최근 실행", emoji="🕘", style=discord.ButtonStyle.secondary, row=1)
    async def recent(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        specs = _recent_specs(self.get_user, interaction.user.id)
        if not specs:
            await interaction.response.send_message("🕘 아직 게임 제어실 실행 기록이 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_list_embed("🕘 최근 실행", "게임 제어실에서 최근 실행한 기능입니다.", specs),
            view=GameSpecListView(self.bot, self.owner_id, specs, self.get_user, self.save_data),
            ephemeral=True,
        )

    @discord.ui.button(label="기능 검색", emoji="🔎", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            GameSearchModal(self.bot, self.owner_id, self.get_user, self.save_data)
        )


# =========================================================
# 스토리 시즌 3: 종말의 왕좌
# =========================================================
def _choice(
    text: str,
    result: str,
    next_node: Optional[str] = None,
    *,
    effects: Optional[Dict[str, Any]] = None,
    flags: Optional[Sequence[str]] = None,
    requires_any: Optional[Sequence[str]] = None,
    requires_all: Optional[Sequence[str]] = None,
    min_reputation: int = 0,
    ending: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "text": text,
        "result": result,
        "next": next_node,
        "effects": effects or {},
        "flags": list(flags or []),
        "requires_any": list(requires_any or []),
        "requires_all": list(requires_all or []),
        "min_reputation": int(min_reputation),
        "ending": ending,
    }


SEASON3_NODES: Dict[str, Dict[str, Any]] = {
    "eclipse_signal": {
        "chapter": "프롤로그",
        "title": "검은 일식",
        "location": "백색 방주 상공 · 정지한 태양",
        "body": (
            "방주의 문이 열린 지 41일째, 정오의 태양이 검게 물든다. 모든 단말기에 하나의 좌표와 문장이 나타난다.\n\n"
            "‘ABADDON 최종 계승 절차. 왕좌는 비어 있다.’\n\n"
            "민재는 사람을 먼저 대피시키자고 하고, 이라는 신호의 근원을 파괴해야 한다고 주장한다. "
            "방주 중앙 AI는 당신에게 관리자 승계를 요청한다."
        ),
        "choices": [
            _choice(
                "민재와 함께 외곽 생존자들을 지하 성역으로 대피시킨다.",
                "도시의 신호등이 모두 꺼진 가운데 피난 행렬이 움직였다. 사람들은 당신의 이름보다 열린 길을 기억했다.",
                "refuge_route",
                effects={"food": 800, "reputation": 5, "materials": {"고철": 3}},
                flags=["protected_people", "trusted_minjae_again"],
            ),
            _choice(
                "이라와 함께 일식 신호의 발신원인 심연 관측소로 향한다.",
                "이라는 검은 태양이 천체가 아니라 도시 전체를 덮는 신호 장치라고 밝혔다.",
                "observatory_route",
                effects={"materials": {"전자부품": 4}, "reputation": 3},
                flags=["followed_ira", "knows_false_sun"],
            ),
            _choice(
                "방주 AI의 관리자 승계를 받아들이고 중앙 권한을 확보한다.",
                "도시 지도 위의 모든 생존 신호와 감염 군집이 당신의 명령 대기 상태로 바뀌었다.",
                "throne_route",
                effects={"food": 1200, "materials": {"에너지코어": 1}},
                flags=["accepted_succession", "holds_ark_authority"],
                requires_any=["white_commander", "entered_as_admin", "used_legacy_key"],
            ),
        ],
    },
    "refuge_route": {
        "chapter": "제1장",
        "title": "문 없는 피난처",
        "location": "남부 지하 성역 · 폐쇄된 승강장",
        "body": (
            "피난민 수천 명이 낡은 승강장에 모였지만 공기 정화 장치는 절반만 작동한다. "
            "살아남으려면 방주 전력을 끌어오거나, 감염 구역을 통과해 외부 발전소를 점령해야 한다."
        ),
        "choices": [
            _choice(
                "방주 생활구역의 전력을 나누도록 설득한다.",
                "방주 주민들이 문을 열고 케이블을 연결했다. 두 공동체는 처음으로 같은 어둠을 견뎠다.",
                "broken_crown",
                effects={"food": 600, "reputation": 7},
                flags=["shared_power", "united_communities"],
                requires_any=["civil_support", "broadcast_truth", "second_dawn"],
            ),
            _choice(
                "원정대를 이끌고 외부 발전소를 탈환한다.",
                "치열한 교전 끝에 발전소를 되찾았다. 피난처는 살아났지만 원정대의 희생이 컸다.",
                "broken_crown",
                effects={"food": 1400, "hp": -12, "reputation": 5},
                flags=["captured_powerplant", "paid_in_blood"],
                min_reputation=12,
            ),
            _choice(
                "정화 장치를 최소 인원에게만 배정해 핵심 기술자를 보존한다.",
                "기술자들은 살아남았지만, 선택받지 못한 사람들의 침묵이 승강장을 채웠다.",
                "broken_crown",
                effects={"materials": {"전자부품": 5, "에너지코어": 1}},
                flags=["selected_survivors", "cold_calculation"],
            ),
        ],
    },
    "observatory_route": {
        "chapter": "제1장",
        "title": "태양을 만드는 기계",
        "location": "심연 관측소 · 지하 9층",
        "body": (
            "관측소 중심에는 태양처럼 빛나는 거대한 신호 구체가 있다. 구체는 감염자를 하나의 군집 의식으로 묶고, "
            "생존자의 기억을 연료로 삼는다. 이라는 즉시 파괴를 주장하지만 내부에는 수만 명의 기억 기록이 남아 있다."
        ),
        "choices": [
            _choice(
                "기억 기록을 복사한 뒤 신호 구체를 파괴한다.",
                "검은 태양이 갈라지고 도시의 감염 군집이 혼란에 빠졌다. 기록은 불완전하지만 사람들의 이름은 남았다.",
                "broken_crown",
                effects={"materials": {"전자부품": 5}, "reputation": 6, "hp": -8},
                flags=["saved_memories", "shattered_false_sun"],
            ),
            _choice(
                "신호 구체를 역이용해 감염 군집을 도시 밖으로 유도한다.",
                "감염자들이 검은 강처럼 외곽으로 이동했다. 도시는 잠시 안전해졌지만 구체는 아직 살아 있다.",
                "broken_crown",
                effects={"food": 1600, "reputation": 4},
                flags=["redirected_horde", "kept_false_sun"],
                requires_any=["knows_reset", "has_shutdown_code", "knows_cooling"],
            ),
            _choice(
                "모든 기억 기록을 구체와 함께 소각한다.",
                "신호는 완전히 끊겼다. 누구도 다시 이용할 수 없지만, 사라진 사람들의 마지막 흔적도 함께 사라졌다.",
                "broken_crown",
                effects={"materials": {"에너지코어": 2}},
                flags=["burned_memories", "absolute_silence"],
            ),
        ],
    },
    "throne_route": {
        "chapter": "제1장",
        "title": "관리자 없는 명령",
        "location": "백색 방주 · 통합 지휘실",
        "body": (
            "승계가 완료되자 방주와 검은 신호가 하나의 네트워크로 합쳐진다. 그러나 중앙 AI는 마지막 권한을 얻기 위해 "
            "당신의 감정 기록을 삭제해야 한다고 요구한다. 왕좌는 인간을 원하지 않는다. 명령만을 원한다."
        ),
        "choices": [
            _choice(
                "감정 기록 삭제를 거부하고 불완전한 인간 관리자 상태를 유지한다.",
                "시스템은 수천 개의 오류를 표시했지만 명령권은 남았다. 당신의 망설임이 사람들을 살릴 가능성이 되었다.",
                "broken_crown",
                effects={"reputation": 6},
                flags=["human_admin", "kept_empathy"],
            ),
            _choice(
                "감정 기록을 삭제하고 완전한 관리자 권한을 얻는다.",
                "도시의 모든 문과 무기가 동시에 당신에게 복종했다. 대신 오래된 이름들이 의미 없는 데이터로 보이기 시작했다.",
                "broken_crown",
                effects={"food": 2500, "materials": {"에너지코어": 2}},
                flags=["perfect_admin", "lost_empathy"],
            ),
            _choice(
                "권한을 여러 생존자 대표에게 분산해 단일 왕좌를 없앤다.",
                "명령은 느려졌지만 누구도 혼자 도시를 소유할 수 없게 되었다.",
                "broken_crown",
                effects={"food": 900, "reputation": 9},
                flags=["distributed_authority", "no_single_ruler"],
                requires_any=["saved_convoy", "awakened_residents", "broadcast_truth"],
            ),
        ],
    },
    "broken_crown": {
        "chapter": "제2장",
        "title": "부서진 왕관",
        "location": "도시 중앙 · 아바돈 핵심 승강로",
        "body": (
            "세 갈래의 길이 중앙 승강로에서 만난다. 검은 태양은 약해졌지만 지하의 아바돈 핵심이 깨어났다. "
            "핵심은 도시를 살리기 위해 한 명의 영구 관리자를 요구하고, 거부하면 모든 방어 시설을 정지시키겠다고 경고한다."
        ),
        "choices": [
            _choice(
                "관리자 자리를 거부하고 사람들에게 도시 방어권을 나눈다.",
                "방어망은 불안정해졌지만 수백 개의 수동 통제소가 동시에 켜졌다.",
                "last_gate",
                effects={"reputation": 8},
                flags=["refused_throne", "civil_defense"],
            ),
            _choice(
                "자신이 영구 관리자가 되어 방어망을 유지한다.",
                "모든 포탑과 문이 다시 움직였다. 대신 핵심은 당신의 생체 신호를 왕좌에 묶기 시작했다.",
                "last_gate",
                effects={"food": 2200, "hp": -15},
                flags=["bound_to_core", "kept_defenses"],
            ),
            _choice(
                "핵심을 원정용 에너지로 분해해 방주와 도시를 독립시킨다.",
                "중앙 방어망은 사라졌지만 각 구역은 스스로 살아남을 힘을 얻었다.",
                "last_gate",
                effects={"materials": {"에너지코어": 3}, "reputation": 5},
                flags=["dismantled_core", "independent_zones"],
                min_reputation=25,
            ),
        ],
    },
    "last_gate": {
        "chapter": "최종장",
        "title": "종말의 왕좌",
        "location": "아바돈 핵심 · 마지막 문",
        "body": (
            "마지막 문 뒤에는 도시 전체를 다시 쓰는 네 개의 명령이 떠 있다. 사람에게 권한을 돌려주거나, 왕좌에 남거나, "
            "모든 신호를 침묵시키거나, 방주 열차로 경계 너머의 세계를 열 수 있다."
        ),
        "choices": [
            _choice(
                "도시의 모든 관리자 권한을 공개하고 시민 평의회에 넘긴다.",
                "검은 왕좌는 빈 채로 남았다. 느리고 불완전한 합의가 시작됐지만, 누구의 삶도 한 사람의 명령으로 지워지지 않았다.",
                effects={"food": 14000, "reputation": 18, "title": "왕좌를 비운 자", "materials": {"에너지코어": 1}},
                flags=["ending_free_city"],
                requires_any=["distributed_authority", "refused_throne", "united_communities"],
                min_reputation=10,
                ending={"id": "free_city", "title": "엔딩 A · 사람의 도시", "body": "아바돈의 마지막 명령은 통제가 아니라 권한의 반환이었다."},
            ),
            _choice(
                "왕좌에 남아 도시와 방주를 영구히 통치한다.",
                "감염 군집은 멈췄고 식량 배급은 완벽해졌다. 사람들은 안전했지만 모든 문이 당신의 허락을 기다렸다.",
                effects={"food": 18000, "reputation": 10, "title": "종말의 군주", "materials": {"에너지코어": 3}},
                flags=["ending_throne"],
                requires_any=["bound_to_core", "perfect_admin", "accepted_succession"],
                ending={"id": "apocalypse_throne", "title": "엔딩 B · 종말의 왕좌", "body": "당신은 재난을 끝내지 않았다. 재난을 다스리는 존재가 되었다."},
            ),
            _choice(
                "아바돈·방주·검은 태양의 모든 신호를 영구 정지한다.",
                "도시는 어둠에 잠겼지만 더 이상 기억을 훔치는 방송도, 인간을 분류하는 명령도 없었다.",
                effects={"food": 11000, "reputation": 12, "title": "마지막 침묵", "materials": {"전자부품": 8}},
                flags=["ending_silence"],
                requires_any=["absolute_silence", "shattered_false_sun", "dismantled_core"],
                ending={"id": "final_silence", "title": "엔딩 C · 마지막 침묵", "body": "세상을 지키던 기계가 멈추자, 사람들은 처음으로 자신의 목소리만 들었다."},
            ),
            _choice(
                "방주 열차 노선을 개방해 도시 밖의 생존권역과 연결한다.",
                "잠겨 있던 터널 끝에서 다른 도시의 신호가 응답했다. 종말은 하나의 도시로 끝나는 이야기가 아니었다.",
                effects={"food": 15500, "reputation": 15, "title": "경계망의 개척자", "materials": {"에너지코어": 2}},
                flags=["ending_network"],
                requires_any=["saved_memories", "redirected_horde", "independent_zones", "beyond_border"],
                min_reputation=15,
                ending={"id": "open_network", "title": "엔딩 D · 열린 경계망", "body": "당신은 왕좌 대신 길을 선택했다. 멀리 떨어진 생존자들이 하나의 지도 위에 나타났다."},
            ),
        ],
    },
}

SEASON3_ENDING_NAMES = {
    "free_city": "사람의 도시",
    "apocalypse_throne": "종말의 왕좌",
    "final_silence": "마지막 침묵",
    "open_network": "열린 경계망",
}


def _default_season3() -> Dict[str, Any]:
    return {
        "version": 1,
        "started": False,
        "completed": False,
        "node": STORY3_START_NODE,
        "flags": [],
        "history": [],
        "ending": None,
        "endings": [],
        "claimed_rewards": [],
        "runs": 0,
    }


def ensure_v600(user: Dict[str, Any]) -> Dict[str, Any]:
    root = user.setdefault("v600", {})
    if not isinstance(root, dict):
        root = {}
        user["v600"] = root
    season3 = root.setdefault("season3", _default_season3())
    if not isinstance(season3, dict):
        season3 = _default_season3()
        root["season3"] = season3
    defaults = _default_season3()
    for key, value in defaults.items():
        if key not in season3:
            season3[key] = list(value) if isinstance(value, list) else value
    for key in ("flags", "history", "endings", "claimed_rewards"):
        if not isinstance(season3.get(key), list):
            season3[key] = []
    if season3.get("node") not in SEASON3_NODES:
        season3["node"] = STORY3_START_NODE
        season3["completed"] = False
    return root


def _season3_legacy_flags(user: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    story1 = user.get("story") if isinstance(user.get("story"), dict) else {}
    if story1.get("completed"):
        flags.append("season1_completed")
    ending1 = story1.get("ending")
    if isinstance(ending1, dict) and ending1.get("id"):
        flags.append(str(ending1["id"]))
    for item in story1.get("flags", []) if isinstance(story1.get("flags"), list) else []:
        flags.append(str(item))

    v430 = user.get("v430") if isinstance(user.get("v430"), dict) else {}
    season2 = v430.get("season2") if isinstance(v430.get("season2"), dict) else {}
    if season2.get("completed"):
        flags.append("season2_completed")
    ending2 = season2.get("ending")
    if isinstance(ending2, dict) and ending2.get("id"):
        flags.append(str(ending2["id"]))
    for item in season2.get("flags", []) if isinstance(season2.get("flags"), list) else []:
        flags.append(str(item))
    for item in season2.get("endings", []) if isinstance(season2.get("endings"), list) else []:
        flags.append(str(item))
    return list(dict.fromkeys(flags))


def _available_choices(user: Dict[str, Any], season3: Dict[str, Any], node: Dict[str, Any]) -> List[Dict[str, Any]]:
    flags = set(season3.get("flags", [])) | set(_season3_legacy_flags(user))
    expedition = ensure_v430(user)["expedition"]
    reputation = int(expedition.get("reputation", 0))
    available: List[Dict[str, Any]] = []
    for choice in node.get("choices", []):
        requires_any = set(choice.get("requires_any", []))
        requires_all = set(choice.get("requires_all", []))
        if requires_any and not (requires_any & flags):
            continue
        if requires_all and not requires_all.issubset(flags):
            continue
        if reputation < int(choice.get("min_reputation", 0)):
            continue
        available.append(choice)
    return available


def _story3_embed(user: Dict[str, Any], season3: Dict[str, Any]) -> discord.Embed:
    if season3.get("completed") and isinstance(season3.get("ending"), dict):
        ending = season3["ending"]
        embed = discord.Embed(
            title=f"🏁 {ending.get('title', '시즌 3 완료')}",
            description=ending.get("body", "종말의 왕좌 캠페인을 완료했습니다."),
            color=discord.Color.gold(),
        )
        embed.add_field(name="발견 엔딩", value=f"{len(season3.get('endings', []))}/4", inline=True)
        embed.add_field(name="완료 회차", value=str(season3.get("runs", 0)), inline=True)
        embed.set_footer(text="다른 분기: !시즌3 재시작")
        return embed

    node = SEASON3_NODES[season3.get("node", STORY3_START_NODE)]
    choices = _available_choices(user, season3, node)
    embed = discord.Embed(
        title=f"🌑 스토리 시즌 3 · {node['chapter']} {node['title']}",
        description=f"📍 **{node['location']}**\n\n{node['body']}",
        color=discord.Color.dark_red(),
    )
    if choices:
        embed.add_field(
            name="선택지",
            value="\n".join(f"**{index}.** {choice['text']}" for index, choice in enumerate(choices, start=1)),
            inline=False,
        )
    else:
        embed.add_field(name="선택지", value="🔒 현재 조건으로 선택 가능한 분기가 없습니다.", inline=False)
    expedition = ensure_v430(user)["expedition"]
    embed.add_field(name="원정 평판", value=str(expedition.get("reputation", 0)), inline=True)
    embed.add_field(name="엔딩 수집", value=f"{len(season3.get('endings', []))}/4", inline=True)
    embed.set_footer(text="아래 드롭다운 또는 !시즌3 선택 번호")
    return embed


class Season3ChoiceSelect(discord.ui.Select):
    def __init__(self, owner_id: int, choices: Sequence[Dict[str, Any]], choose_callback: Any) -> None:
        self.owner_id = owner_id
        self.choose_callback = choose_callback
        options = [
            discord.SelectOption(label=f"{index}. {choice['text']}"[:100], value=str(index), description=choice["result"][:100])
            for index, choice in enumerate(choices, start=1)
        ]
        super().__init__(placeholder="시즌 3 선택지를 고르세요", min_values=1, max_values=1, options=_safe_select_options(options))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🔒 이 스토리 선택지는 해당 생존자만 고를 수 있습니다.", ephemeral=True)
            return
        await self.choose_callback(interaction, int(self.values[0]))


class Season3ChoiceView(discord.ui.View):
    def __init__(self, owner_id: int, choices: Sequence[Dict[str, Any]], choose_callback: Any) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        if choices:
            self.add_item(Season3ChoiceSelect(owner_id, choices, choose_callback))


# =========================================================
# 등록
# =========================================================
def register_v600_game_center(
    bot: commands.Bot,
    get_user: Any,
    check_registered: Any,
    save_data: Any,
    add_title: Any,
    add_season_points: Any,
) -> None:
    if getattr(bot, "_abaddon_v600_registered", False):
        return
    bot._abaddon_v600_registered = True
    bot.v600_action_index = ACTION_INDEX
    bot.v600_action_category = ACTION_CATEGORY

    async def choose_season3(interaction: discord.Interaction, number: int) -> None:
        user = get_user(interaction.user.id)
        season3 = ensure_v600(user)["season3"]
        if not season3.get("started"):
            await interaction.response.send_message("⚠️ 먼저 `!시즌3 시작`을 사용해주세요.", ephemeral=True)
            return
        if season3.get("completed"):
            await interaction.response.send_message("🏁 이미 완료했습니다. `!시즌3 재시작`으로 다른 분기를 진행하세요.", ephemeral=True)
            return
        node_id = str(season3.get("node", STORY3_START_NODE))
        node = SEASON3_NODES[node_id]
        choices = _available_choices(user, season3, node)
        if number < 1 or number > len(choices):
            await interaction.response.send_message(f"⚠️ 선택 번호는 1~{len(choices)}입니다.", ephemeral=True)
            return

        choice = choices[number - 1]
        original_index = node["choices"].index(choice)
        reward_key = f"v600:{node_id}:{original_index}"
        first_claim = reward_key not in season3["claimed_rewards"]
        effect_lines: List[str] = []
        if first_claim:
            effects = choice.get("effects", {})
            food = int(effects.get("food", 0))
            if food:
                user["balance"] = max(0, int(user.get("balance", 0)) + food)
                effect_lines.append(f"🥫 식량 {'+' if food > 0 else ''}{food:,}")
            hp = int(effects.get("hp", 0))
            if hp:
                user["hp"] = max(1, int(user.get("hp", 100)) + hp)
                effect_lines.append(f"❤️ HP {'+' if hp > 0 else ''}{hp}")
            materials = effects.get("materials", {})
            if isinstance(materials, dict):
                bag = user.setdefault("materials", {})
                for item, amount in materials.items():
                    bag[item] = int(bag.get(item, 0)) + int(amount)
                    effect_lines.append(f"🧰 {item} +{int(amount)}")
            reputation = int(effects.get("reputation", 0))
            if reputation:
                expedition = ensure_v430(user)["expedition"]
                expedition["reputation"] = int(expedition.get("reputation", 0)) + reputation
                effect_lines.append(f"🧭 원정 평판 +{reputation}")
            title = effects.get("title")
            if title:
                add_title(user, str(title))
                effect_lines.append(f"🏷️ 칭호 **{title}**")
            season3["claimed_rewards"].append(reward_key)

        for flag in choice.get("flags", []):
            if flag not in season3["flags"]:
                season3["flags"].append(flag)
        season3["history"].append({"chapter": node["chapter"], "title": node["title"], "choice": choice["text"]})
        season3["history"] = season3["history"][-50:]

        ending = choice.get("ending")
        if ending:
            season3["completed"] = True
            season3["ending"] = ending
            if ending["id"] not in season3["endings"]:
                season3["endings"].append(ending["id"])
            season3["runs"] = int(season3.get("runs", 0)) + 1
            add_season_points(user, 30)
        else:
            season3["node"] = choice["next"]
        save_data()

        await interaction.response.defer(thinking=True)
        reward_text = "\n".join(effect_lines) if effect_lines else "🔁 이미 받은 선택 보상은 중복 지급되지 않습니다."
        await interaction.followup.send(f"🎬 **선택 결과**\n{choice['result']}\n\n{reward_text}")
        current = ensure_v600(user)["season3"]
        embed = _story3_embed(user, current)
        view = None
        if not current.get("completed"):
            current_node = SEASON3_NODES[current["node"]]
            current_choices = _available_choices(user, current, current_node)
            view = Season3ChoiceView(interaction.user.id, current_choices, choose_season3)
        await interaction.followup.send(embed=embed, view=view)


    async def require_season3_access(ctx: commands.Context, user: Dict[str, Any]) -> bool:
        allowed, _reason = await can_access_season(ctx, bot, user, 3)
        if allowed:
            return True
        await ctx.send(locked_text(3))
        return False

    async def send_season3(ctx: commands.Context) -> None:
        user = get_user(ctx.author.id)
        if not await require_season3_access(ctx, user):
            return
        season3 = ensure_v600(user)["season3"]
        if not season3.get("started"):
            await ctx.send(
                "🌑 **스토리 시즌 3: 종말의 왕좌**\n"
                "검은 주파수와 백색 방주 이후, 도시의 최종 관리자 권한을 둘러싼 캠페인입니다.\n"
                "시작: `!시즌3 시작`"
            )
            return
        embed = _story3_embed(user, season3)
        view = None
        if not season3.get("completed"):
            node = SEASON3_NODES[season3["node"]]
            choices = _available_choices(user, season3, node)
            view = Season3ChoiceView(ctx.author.id, choices, choose_season3)
        await ctx.send(embed=embed, view=view)

    @bot.command(name="게임", aliases=["게임센터", "게임메뉴", "rpg메뉴"])
    async def game_center(ctx: commands.Context) -> None:
        """모든 주요 RPG·게임 기능을 드롭다운으로 실행합니다."""
        if ctx.guild is None:
            await ctx.send("⚠️ 게임 제어실은 서버 채널에서만 사용할 수 있습니다.")
            return
        user = get_user(ctx.author.id)
        _ensure_game_center_state(user)
        await ctx.send(
            embed=_main_embed(user),
            view=GameCategoryView(bot, ctx.author.id, get_user, save_data),
        )

    @bot.group(name="시즌3", aliases=["종말의왕좌", "왕좌"], invoke_without_command=True)
    async def season3_group(ctx: commands.Context) -> None:
        """스토리 시즌 3 종말의 왕좌를 진행합니다."""
        if not await check_registered(ctx):
            return
        await send_season3(ctx)

    @season3_group.command(name="시작")
    async def season3_start(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season3_access(ctx, user):
            return
        season3 = ensure_v600(user)["season3"]
        if season3.get("completed"):
            await ctx.send("🏁 이미 시즌 3를 완료했습니다. `!시즌3 재시작`으로 다른 엔딩을 찾으세요.")
            return
        if not season3.get("started"):
            season3["started"] = True
            season3["node"] = STORY3_START_NODE
            season3["flags"] = _season3_legacy_flags(user)
            season3["history"] = []
            season3["ending"] = None
            save_data()
            inherited = []
            if "season1_completed" in season3["flags"]:
                inherited.append("검은 주파수")
            if "season2_completed" in season3["flags"]:
                inherited.append("백색 방주")
            await ctx.send(
                "🌑 **스토리 시즌 3: 종말의 왕좌**가 시작됩니다.\n"
                f"계승 기록: **{', '.join(inherited) if inherited else '신규 생존자 요약 계승'}**"
            )
        await send_season3(ctx)

    @season3_group.command(name="선택")
    async def season3_choose(ctx: commands.Context, 번호: int) -> None:
        if not await check_registered(ctx):
            return
        # prefix 선택은 동일 로직을 사용하되 가짜 Interaction을 만들지 않고 직접 처리합니다.
        user = get_user(ctx.author.id)
        if not await require_season3_access(ctx, user):
            return
        season3 = ensure_v600(user)["season3"]
        if not season3.get("started"):
            await ctx.send("⚠️ 먼저 `!시즌3 시작`을 사용해주세요.")
            return
        if season3.get("completed"):
            await ctx.send("🏁 이미 완료했습니다. `!시즌3 재시작`으로 다른 분기를 진행하세요.")
            return
        node_id = season3["node"]
        node = SEASON3_NODES[node_id]
        choices = _available_choices(user, season3, node)
        if 번호 < 1 or 번호 > len(choices):
            await ctx.send(f"⚠️ 선택 번호는 **1~{len(choices)}**입니다.")
            return
        choice = choices[번호 - 1]
        original_index = node["choices"].index(choice)
        reward_key = f"v600:{node_id}:{original_index}"
        first_claim = reward_key not in season3["claimed_rewards"]
        effect_lines: List[str] = []
        if first_claim:
            effects = choice.get("effects", {})
            food = int(effects.get("food", 0))
            if food:
                user["balance"] = max(0, int(user.get("balance", 0)) + food)
                effect_lines.append(f"🥫 식량 {'+' if food > 0 else ''}{food:,}")
            hp = int(effects.get("hp", 0))
            if hp:
                user["hp"] = max(1, int(user.get("hp", 100)) + hp)
                effect_lines.append(f"❤️ HP {'+' if hp > 0 else ''}{hp}")
            materials = effects.get("materials", {})
            if isinstance(materials, dict):
                bag = user.setdefault("materials", {})
                for item, amount in materials.items():
                    bag[item] = int(bag.get(item, 0)) + int(amount)
                    effect_lines.append(f"🧰 {item} +{int(amount)}")
            reputation = int(effects.get("reputation", 0))
            if reputation:
                expedition = ensure_v430(user)["expedition"]
                expedition["reputation"] = int(expedition.get("reputation", 0)) + reputation
                effect_lines.append(f"🧭 원정 평판 +{reputation}")
            title = effects.get("title")
            if title:
                add_title(user, str(title))
                effect_lines.append(f"🏷️ 칭호 **{title}**")
            season3["claimed_rewards"].append(reward_key)
        for flag in choice.get("flags", []):
            if flag not in season3["flags"]:
                season3["flags"].append(flag)
        season3["history"].append({"chapter": node["chapter"], "title": node["title"], "choice": choice["text"]})
        season3["history"] = season3["history"][-50:]
        ending = choice.get("ending")
        if ending:
            season3["completed"] = True
            season3["ending"] = ending
            if ending["id"] not in season3["endings"]:
                season3["endings"].append(ending["id"])
            season3["runs"] = int(season3.get("runs", 0)) + 1
            add_season_points(user, 30)
        else:
            season3["node"] = choice["next"]
        save_data()
        reward_text = "\n".join(effect_lines) if effect_lines else "🔁 이미 받은 선택 보상은 중복 지급되지 않습니다."
        await ctx.send(f"🎬 **선택 결과**\n{choice['result']}\n\n{reward_text}")
        await send_season3(ctx)

    @season3_group.command(name="기록")
    async def season3_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season3_access(ctx, user):
            return
        season3 = ensure_v600(user)["season3"]
        history = season3.get("history", [])
        if not history:
            await ctx.send("📜 시즌 3 선택 기록이 없습니다. `!시즌3 시작`으로 시작하세요.")
            return
        lines = ["🌑 **[종말의 왕좌 선택 기록]**"]
        for index, record in enumerate(history[-30:], start=max(1, len(history) - 29)):
            lines.append(f"{index}. **{record['chapter']} {record['title']}** — {record['choice']}")
        found = [SEASON3_ENDING_NAMES[item] for item in season3.get("endings", []) if item in SEASON3_ENDING_NAMES]
        lines.append("\n🏁 발견 엔딩: " + (", ".join(found) if found else "없음"))
        await ctx.send("\n".join(lines))

    @season3_group.command(name="재시작")
    async def season3_restart(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not await require_season3_access(ctx, user):
            return
        season3 = ensure_v600(user)["season3"]
        if not season3.get("started"):
            await ctx.send("⚠️ 아직 시즌 3를 시작하지 않았습니다.")
            return
        endings = list(season3.get("endings", []))
        claimed = list(season3.get("claimed_rewards", []))
        runs = int(season3.get("runs", 0))
        season3.clear()
        season3.update(_default_season3())
        season3["started"] = True
        season3["flags"] = _season3_legacy_flags(user)
        season3["endings"] = endings
        season3["claimed_rewards"] = claimed
        season3["runs"] = runs
        save_data()
        await ctx.send("🔄 시즌 3를 다시 시작합니다. 발견 엔딩과 이미 받은 선택 보상은 유지됩니다.")
        await send_season3(ctx)

    print(
        f"[ABADDON v{VERSION}] 게임 제어실 등록: 카테고리={len(GAME_CATEGORIES)} 기능={len(ACTION_INDEX)} 시즌3노드={len(SEASON3_NODES)}",
        flush=True,
    )
