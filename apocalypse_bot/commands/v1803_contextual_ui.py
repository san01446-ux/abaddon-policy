from __future__ import annotations

"""ABADDON v18.0.3 CONTEXTUAL UI HOTFIX.

Purpose
-------
- remove the old global recommendation row that appended the same Story/Gear/Shop/Today/Hub buttons to unrelated results;
- keep action-result summaries, tutorial progression and saved-state comparison from v16.6;
- build 2-4 direct buttons that actually match the command that just ran;
- add one related-function dropdown when the current feature group has more safe zero-argument commands;
- never place audit/admin/server-management commands in gameplay recommendation panels;
- preserve every legacy prefix command, save key and command-center group.
"""

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _invoke_command, _bridge_notice
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
from apocalypse_bot.commands import v1650_survivor_core_complete as core1650
from apocalypse_bot.commands import v1660_first_survival_live_qa as live1660

VERSION = "18.1.4"
ROOT_KEY = "v1803_contextual_ui"
MAX_BUTTONS = 4
MAX_SELECT_OPTIONS = 12


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, ctx_or_user: Any) -> str:
    try:
        return live1660._locale(bot, ctx_or_user)
    except Exception:
        return "ko"


def _command_key(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "").strip()


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> Optional[MutableMapping[str, Any]]:
    try:
        row = get_user(int(user_id))
    except Exception:
        return None
    return row if isinstance(row, MutableMapping) else None


def _root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault(ROOT_KEY, {})
    if not isinstance(row, MutableMapping):
        row = {}
        user[ROOT_KEY] = row
    row.setdefault("enabled", True)
    row.setdefault("dropdown", True)
    row.setdefault("max_buttons", MAX_BUTTONS)
    return row


def _zero_arg(command: Optional[commands.Command]) -> bool:
    """Only expose UI actions that can safely be invoked without another modal/input."""
    if command is None:
        return False
    try:
        params = getattr(command, "clean_params", {}) or {}
        for param in params.values():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if param.default is inspect.Parameter.empty:
                return False
        return True
    except Exception:
        return False


def _aliases(command: commands.Command) -> Tuple[str, ...]:
    rows = [str(getattr(command, "qualified_name", "") or ""), str(getattr(command, "name", "") or "")]
    rows.extend(str(x) for x in getattr(command, "aliases", []) or [])
    return tuple(x.casefold() for x in rows if x)


def _same_command(command: commands.Command, current: str) -> bool:
    token = str(current).casefold().strip()
    return token in _aliases(command)


@dataclass(frozen=True)
class Candidate:
    names: Tuple[str, ...]
    ko: str
    en: str
    emoji: str
    style: discord.ButtonStyle = discord.ButtonStyle.secondary
    allow_current: bool = False


@dataclass(frozen=True)
class ResolvedAction:
    command_name: str
    ko: str
    en: str
    emoji: str
    style: discord.ButtonStyle


def C(*names: str, ko: str, en: str, emoji: str, style: discord.ButtonStyle = discord.ButtonStyle.secondary, allow_current: bool = False) -> Candidate:
    return Candidate(tuple(names), ko, en, emoji, style, allow_current)


# Direct buttons are intentionally conservative. The dropdown supplies the rest
# of the *same feature group* so a result never ends with unrelated navigation.
GROUP_BUTTONS: Dict[str, Tuple[Candidate, ...]] = {
    "terminal": (
        C("생존단말기", "단말기", "survivalterminal", ko="생존 단말기", en="Survivor Terminal", emoji="📡", style=discord.ButtonStyle.primary),
        C("의뢰소", "contractoffice", ko="의뢰소", en="Contracts", emoji="📜"),
        C("생산센터", "productioncenter", ko="생산센터", en="Production", emoji="⚙️"),
        C("인연", "bonds", ko="NPC 인연", en="NPC Bonds", emoji="🤝"),
    ),
    "contracts": (
        C("의뢰소", "contractoffice", ko="의뢰소", en="Contracts", emoji="📜", style=discord.ButtonStyle.primary),
        C("의뢰진행", "contractprogress", ko="진행 확인", en="Progress", emoji="🎯"),
        C("의뢰기록", "contracthistory", ko="의뢰 기록", en="History", emoji="📚"),
        C("세력평판", "평판", "factionreputation", ko="세력 평판", en="Faction Rep", emoji="🏴"),
    ),
    "onboarding": (
        C("정보", "profile", ko="내 정보", en="Profile", emoji="👤", style=discord.ButtonStyle.primary),
        C("초보생존", "firstsurvival", ko="생존자 여정", en="Survivor Journey", emoji="🌱"),
        C("오늘할일", "today", ko="오늘 할 일", en="Today", emoji="🎯"),
        C("7일보급", "sevendaysupply", ko="7일 보급", en="7-Day Supply", emoji="🎁"),
    ),
    "quests": (
        C("오늘할일", "today", ko="오늘 할 일", en="Today", emoji="🎯", style=discord.ButtonStyle.primary),
        C("성장보드", "growthboard", ko="성장 보드", en="Growth Board", emoji="📈"),
        C("미션보상", "missionreward", ko="미션 보상", en="Mission Reward", emoji="🎁"),
        C("통합업적", "achievements", ko="통합 업적", en="Achievements", emoji="🏆"),
    ),
    "exploration": (
        C("솔로원정", "lonesurvivor", ko="솔로 원정", en="Solo Expedition", emoji="🌑", style=discord.ButtonStyle.primary),
        C("세계지도", "worldmap", ko="세계 지도", en="World Map", emoji="🗺️"),
        C("탐험가방", "가방", "bag", ko="탐험 가방", en="Expedition Bag", emoji="🎒"),
        C("생존허브", "survivorhub", ko="생존 허브", en="Survivor Hub", emoji="👤"),
    ),
    "base": (
        C("기지", "base", ko="기지", en="Base", emoji="🏕️", style=discord.ButtonStyle.primary),
        C("대피소", "shelter", ko="대피소", en="Shelter", emoji="🏠"),
        C("세계지도", "worldmap", ko="세계 지도", en="World Map", emoji="🗺️"),
        C("생산센터", "productioncenter", ko="생산센터", en="Production", emoji="⚙️"),
    ),
    "codex": (
        C("스토리나침반", "storycompass", ko="스토리 나침반", en="Story Compass", emoji="🧭", style=discord.ButtonStyle.primary),
        C("전설도감", "legendcodex", ko="전설 도감", en="Legend Codex", emoji="📚"),
        C("결말기록", "endinghistory", ko="결말 기록", en="Endings", emoji="🎬"),
        C("연대기박물관", "chroniclemuseum", ko="박물관", en="Museum", emoji="🏛️"),
    ),
    "museum": (
        C("연대기박물관", "chroniclemuseum", ko="연대기 박물관", en="Museum", emoji="🏛️", style=discord.ButtonStyle.primary),
        C("내전시관", "mygallery", ko="내 전시관", en="My Gallery", emoji="🖼️"),
        C("통합업적", "achievements", ko="통합 업적", en="Achievements", emoji="🏆"),
        C("통합칭호", "titles", ko="통합 칭호", en="Titles", emoji="🎖️"),
    ),
    "connections": (
        C("연결허브", "connectedhub", ko="연결 허브", en="Connected Hub", emoji="🔗", style=discord.ButtonStyle.primary),
        C("연결목표", "connectedgoals", ko="연결 목표", en="Goals", emoji="🎯"),
        C("연결보상", "connectedreward", ko="연결 보상", en="Reward", emoji="🎁"),
        C("도시효과", "cityeffects", ko="도시 효과", en="City Effects", emoji="🏙️"),
    ),
    "production": (
        C("생산센터", "productioncenter", ko="생산센터", en="Production", emoji="⚙️", style=discord.ButtonStyle.primary),
        C("채집센터", "채집", "gather", ko="채집", en="Gather", emoji="⛏️"),
        C("가방", "탐험가방", "bag", ko="가방", en="Bag", emoji="🎒"),
        C("제작", "craft", ko="제작", en="Craft", emoji="🔨"),
    ),
    "life": (
        C("채집센터", "채집", "gather", ko="다시 채집", en="Gather Again", emoji="⛏️", style=discord.ButtonStyle.success, allow_current=True),
        C("가방", "탐험가방", "bag", ko="가방", en="Bag", emoji="🎒"),
        C("제작", "craft", ko="제작", en="Craft", emoji="🔨"),
        C("생산센터", "productioncenter", ko="생산센터", en="Production", emoji="⚙️"),
    ),
    "gear": (
        C("장비", "equipment", ko="장비", en="Equipment", emoji="🛡️", style=discord.ButtonStyle.primary),
        C("가방", "탐험가방", "bag", ko="가방", en="Bag", emoji="🎒"),
        C("제작", "craft", ko="제작", en="Craft", emoji="🔨"),
        C("상점", "shop", ko="상점", en="Shop", emoji="🛒"),
    ),
    "combat": (
        C("전투", "combat", ko="전투", en="Combat", emoji="⚔️", style=discord.ButtonStyle.danger, allow_current=True),
        C("월드보스목록", "worldbosses", ko="월드보스", en="World Boss", emoji="👹"),
        C("장비", "equipment", ko="장비", en="Equipment", emoji="🛡️"),
        C("탐험가방", "가방", "bag", ko="가방", en="Bag", emoji="🎒"),
    ),
    "economy": (
        C("상점", "shop", ko="상점", en="Shop", emoji="🛒", style=discord.ButtonStyle.primary),
        C("자원시장", "시장", "market", ko="시장", en="Market", emoji="📈"),
        C("도시거래소", "거래소", "exchange", ko="거래소", en="Exchange", emoji="🔁"),
        C("암시장", "blackmarket", ko="암시장", en="Black Market", emoji="🕶️"),
    ),
    "cards": (
        C("파티게임", "cardgames", ko="카드 게임", en="Card Games", emoji="🎴", style=discord.ButtonStyle.primary),
        C("게임전적", "gamerecords", ko="전적", en="Records", emoji="📊"),
    ),
    "casino": (
        C("카지노", "casino", ko="카지노 로비", en="Casino Lobby", emoji="🎰", style=discord.ButtonStyle.primary, allow_current=True),
        C("카지노잔액", "casinobalance", ko="카지노 잔액", en="Casino Balance", emoji="💳"),
        C("카지노미션", "casinomission", ko="카지노 미션", en="Casino Mission", emoji="🎯"),
        C("게임전적", "gamerecords", ko="전적", en="Records", emoji="📊"),
    ),
    "gambling": (
        C("도박정보", "gamblinginfo", ko="도박 안내", en="Gambling Guide", emoji="🎲", style=discord.ButtonStyle.primary),
        C("도박잔액", "gamblingbalance", ko="도박 잔액", en="Gambling Balance", emoji="💰"),
        C("경마장", "horseracing", ko="경마장", en="Horse Racing", emoji="🏇"),
        C("정부지원금", "governmentrelief", ko="정부지원금", en="Relief", emoji="🏛️"),
    ),
    "party_games": (
        C("파티게임", "partygames", ko="파티 게임", en="Party Games", emoji="🎉", style=discord.ButtonStyle.primary),
        C("게임전적", "gamerecords", ko="전적", en="Records", emoji="📊"),
    ),
    "collections": (
        C("최종컬렉션", "finalcollection", ko="최종 컬렉션", en="Collection", emoji="🌑", style=discord.ButtonStyle.primary),
        C("전설도감", "legendcodex", ko="전설 도감", en="Legend Codex", emoji="📚"),
        C("통합칭호", "titles", ko="칭호", en="Titles", emoji="🎖️"),
        C("연대기박물관", "chroniclemuseum", ko="박물관", en="Museum", emoji="🏛️"),
    ),
    "black_city": (
        C("도시지도", "citymap", ko="도시 지도", en="City Map", emoji="🏙️", style=discord.ButtonStyle.primary),
        C("도시상태", "citystatus", ko="도시 상태", en="City Status", emoji="📊"),
        C("도시시세", "citymarket", ko="도시 시세", en="City Market", emoji="💹"),
        C("도시의뢰", "citycontracts", ko="도시 의뢰", en="City Contracts", emoji="📜"),
    ),
    "city_decor": (
        C("도시꾸미기", "citydecorate", ko="도시 꾸미기", en="Decorate City", emoji="🎨", style=discord.ButtonStyle.primary, allow_current=True),
        C("도시지도", "citymap", ko="도시 지도", en="City Map", emoji="🏙️"),
        C("도시효과", "cityeffects", ko="도시 효과", en="City Effects", emoji="✨"),
        C("생산센터", "productioncenter", ko="생산센터", en="Production", emoji="⚙️"),
    ),
    "neon": (
        C("차원기지", "dimensionbase", ko="차원 기지", en="Dimension Base", emoji="🌀", style=discord.ButtonStyle.primary),
        C("차원채집", "dimensiongather", ko="차원 채집", en="Dimension Gather", emoji="⛏️"),
        C("솔로원정", "lonesurvivor", ko="솔로 원정", en="Solo Expedition", emoji="🌑"),
    ),
    "crew_raid": (
        C("크루채집", "crewgather", ko="크루 채집", en="Crew Gather", emoji="🚀", style=discord.ButtonStyle.primary),
        C("협동보스", "coopboss", ko="협동 보스", en="Co-op Boss", emoji="👹"),
    ),
    "factions": (
        C("세력", "faction", ko="세력", en="Factions", emoji="🏴", style=discord.ButtonStyle.primary),
        C("세력정보", "factioninfo", ko="세력 정보", en="Faction Info", emoji="📋"),
        C("세력상점", "factionshop", ko="세력 상점", en="Faction Shop", emoji="🛒"),
        C("세력의뢰", "factioncontracts", ko="세력 의뢰", en="Faction Contracts", emoji="📜"),
    ),
    "disaster": (
        C("재난상황", "disasterstatus", ko="재난 상황", en="Disaster Status", emoji="☄️", style=discord.ButtonStyle.primary),
        C("재난예보", "disasterforecast", ko="재난 예보", en="Forecast", emoji="🌦️"),
        C("재난임무", "disastermission", ko="재난 임무", en="Mission", emoji="🚨"),
        C("재난보상", "disasterreward", ko="재난 보상", en="Reward", emoji="🎁"),
    ),
    "creator": (
        C("콘텐츠공방", "creatorforge", ko="콘텐츠 공방", en="Creator Forge", emoji="🧩", style=discord.ButtonStyle.primary),
        C("콘텐츠목록", "creatorlist", ko="콘텐츠 목록", en="Content List", emoji="📚"),
        C("사용자사건", "userevent", ko="사용자 사건", en="Community Event", emoji="🎭"),
    ),
    "world_misc": (
        C("살아있는세계", "livingworld", ko="살아 있는 세계", en="Living World", emoji="🌍", style=discord.ButtonStyle.primary),
        C("세계속보", "worldbulletin", ko="세계 속보", en="World Bulletin", emoji="📻"),
        C("지역위험도", "regionrisk", ko="지역 위험도", en="Region Risk", emoji="⚠️"),
        C("세계시장", "worldmarket", ko="세계 시장", en="World Market", emoji="🛒"),
    ),
    "guild": (
        C("길드소개", "guild", ko="길드", en="Guild", emoji="🛡️", style=discord.ButtonStyle.primary),
        C("길드임무", "guildmission", ko="길드 임무", en="Guild Mission", emoji="🎯"),
        C("길드레이드", "guildraid", ko="길드 레이드", en="Guild Raid", emoji="⚔️"),
        C("길드종합랭킹", "guildranking", ko="길드 랭킹", en="Guild Ranking", emoji="🏆"),
    ),
    "companions": (
        C("동료", "companion", ko="동료", en="Companions", emoji="🐾", style=discord.ButtonStyle.primary),
        C("동료도감", "companioncodex", ko="동료 도감", en="Companion Codex", emoji="📚"),
        C("동료임무", "companionmission", ko="동료 임무", en="Companion Mission", emoji="🎯"),
        C("펫센터", "petcenter", ko="펫 센터", en="Pet Center", emoji="🐹"),
    ),
    "npc": (
        C("인연", "bonds", ko="NPC 인연", en="NPC Bonds", emoji="🤝", style=discord.ButtonStyle.primary),
        C("NPC목록", "npclist", ko="NPC 목록", en="NPC List", emoji="👥"),
        C("인연기록", "bondhistory", ko="인연 기록", en="Bond History", emoji="📚"),
        C("배신경보", "betrayalalert", ko="배신 경보", en="Betrayal Alert", emoji="⚠️"),
    ),
    "schedule": (
        C("일정", "schedule", ko="일정", en="Schedule", emoji="📅", style=discord.ButtonStyle.primary),
        C("오늘일정", "todayschedule", ko="오늘 일정", en="Today", emoji="☀️"),
        C("이번주일정", "weekschedule", ko="이번 주", en="This Week", emoji="🗓️"),
    ),
    "competition": (
        C("서버시즌", "serverseason", ko="서버 시즌", en="Server Season", emoji="🌐", style=discord.ButtonStyle.primary),
        C("시즌미션", "seasonmissions", ko="시즌 미션", en="Season Missions", emoji="🎯"),
        C("시즌랭킹", "seasonranking", ko="시즌 랭킹", en="Season Ranking", emoji="🥇"),
        C("서버목표", "servergoal", ko="서버 목표", en="Server Goal", emoji="🏁"),
    ),
    "definitive": (
        C("최종단말기", "definitiveterminal", ko="최종 단말기", en="Definitive Terminal", emoji="🌑", style=discord.ButtonStyle.primary),
        C("최종일식", "finaleclipse", ko="FINAL ECLIPSE", en="FINAL ECLIPSE", emoji="🌘"),
        C("일식결말", "eclipseending", ko="일식 결말", en="Eclipse Ending", emoji="🎬"),
        C("일식보상", "eclipsereward", ko="일식 보상", en="Eclipse Reward", emoji="🎁"),
    ),
    "retention": (
        C("오늘의루프", "dailyloop", ko="오늘의 루프", en="Daily Loop", emoji="🔄", style=discord.ButtonStyle.primary),
        C("최종루프보상", "finalloopreward", ko="루프 보상", en="Loop Reward", emoji="🎁"),
        C("최종컬렉션", "finalcollection", ko="최종 컬렉션", en="Collection", emoji="🏆"),
        C("초보생존", "firstsurvival", ko="생존자 여정", en="Survivor Journey", emoji="🌱"),
    ),
}


SPECIAL_BUTTONS: Dict[str, Tuple[Candidate, ...]] = {
    # Screenshot case: coin searching is an income/gambling loop, not a reason to
    # show Story/Gear/Shop/Today/Survivor-Hub all at once.
    "코인": (
        C("코인", "코인탐색", ko="다시 코인 탐색", en="Scan Coin Again", emoji="🪙", style=discord.ButtonStyle.success, allow_current=True),
        C("매도", "코인판매", ko="코인 판매", en="Sell Coins", emoji="📤", style=discord.ButtonStyle.danger),
        C("자산", "투자자산", ko="보유 자산", en="Portfolio", emoji="💼"),
        C("시세", "암시장시세", ko="시장 시세", en="Market Prices", emoji="📈"),
    ),
    "오늘의퀴즈": (
        C("오늘의퀴즈", "dailyquiz", ko="오늘의 퀴즈", en="Daily Quiz", emoji="🧠", style=discord.ButtonStyle.primary, allow_current=True),
        C("퀴즈랭킹", "quizranking", ko="퀴즈 랭킹", en="Quiz Ranking", emoji="🏆"),
        C("퀴즈통계", "quizstats", ko="퀴즈 통계", en="Quiz Stats", emoji="📊"),
        C("퀴즈알림상태", "quiznotifystatus", ko="알림 상태", en="Notify Status", emoji="🔔"),
    ),
    "퀴즈랭킹": (
        C("오늘의퀴즈", "dailyquiz", ko="오늘의 퀴즈", en="Daily Quiz", emoji="🧠", style=discord.ButtonStyle.primary),
        C("퀴즈통계", "quizstats", ko="퀴즈 통계", en="Quiz Stats", emoji="📊"),
        C("퀴즈알림상태", "quiznotifystatus", ko="알림 상태", en="Notify Status", emoji="🔔"),
    ),
    "퀴즈통계": (
        C("오늘의퀴즈", "dailyquiz", ko="오늘의 퀴즈", en="Daily Quiz", emoji="🧠", style=discord.ButtonStyle.primary),
        C("퀴즈랭킹", "quizranking", ko="퀴즈 랭킹", en="Quiz Ranking", emoji="🏆"),
        C("퀴즈알림상태", "quiznotifystatus", ko="알림 상태", en="Notify Status", emoji="🔔"),
    ),
    "탈것도감": (
        C("탈것도감", "mounts", ko="탈것 도감", en="Mount Catalog", emoji="🏍️", style=discord.ButtonStyle.primary, allow_current=True),
        C("최종컬렉션", "finalcollection", ko="컬렉션", en="Collection", emoji="🏆"),
        C("연대기박물관", "chroniclemuseum", ko="박물관", en="Museum", emoji="🏛️"),
    ),
    "최종단말기": (
        C("최종일식", "finaleclipse", ko="FINAL ECLIPSE", en="FINAL ECLIPSE", emoji="🌘", style=discord.ButtonStyle.primary),
        C("일식결말", "eclipseending", ko="일식 결말", en="Eclipse Ending", emoji="🎬"),
        C("일식보상", "eclipsereward", ko="일식 보상", en="Eclipse Reward", emoji="🎁"),
        C("오늘의루프", "dailyloop", ko="오늘의 루프", en="Daily Loop", emoji="🔄"),
    ),
    "정보": (
        C("오늘할일", "today", ko="오늘 할 일", en="Today", emoji="🎯", style=discord.ButtonStyle.primary),
        C("장비", "equipment", ko="장비", en="Equipment", emoji="🛡️"),
        C("생존허브", "survivorhub", ko="생존 허브", en="Survivor Hub", emoji="👤"),
        C("초보생존", "firstsurvival", ko="생존자 여정", en="Survivor Journey", emoji="🌱"),
    ),
}


# v18.1.4: "관련 기능 더보기"는 command hub 전체를 즉석에서 훑지 않습니다.
# 명령 분류가 조금만 어긋나도 help/검수/운영 명령이 섞일 수 있었기 때문에,
# 실제 플레이에서 입력값 없이 안전하게 열 수 있는 기능만 명시적으로 허용합니다.
# 존재하지 않거나 필수 인수가 생긴 명령은 런타임의 _zero_arg에서 자동 제외됩니다.
SAFE_RELATED_BY_GROUP: Dict[str, Tuple[str, ...]] = {
    "terminal": ("생존허브", "오늘할일", "정보", "아바돈", "최종단말기"),
    "contracts": ("의뢰소", "오늘의세계", "생존허브", "지역위험도"),
    "onboarding": ("초보생존", "첫걸음", "7일보급", "최종복귀보급", "생존허브"),
    "quests": ("오늘할일", "오늘의루프", "통합업적", "생존허브"),
    "exploration": ("솔로원정", "세계지도", "오늘의세계", "탐험가방", "생존허브"),
    "base": ("기지", "대피소", "도시꾸미기", "생산센터", "탐험가방"),
    "codex": ("도감", "전설도감", "탈것도감", "연대기박물관", "통합업적"),
    "museum": ("연대기박물관", "내전시관", "통합업적", "통합칭호", "전설도감", "결말기록"),
    "connections": ("인연", "NPC목록", "NPC대화", "인연기록", "배신경보"),
    "production": ("생산센터", "제작", "채집", "벌목", "광산", "탐험가방"),
    "life": ("채집", "벌목", "낚시", "광산", "탐험가방", "지갑", "생산센터"),
    "gear": ("장비", "탐험가방", "인벤토리", "제작", "강화", "수리", "생산센터"),
    "combat": ("전투", "장비", "탐험가방", "솔로원정", "생존허브"),
    "economy": ("코인", "시세", "매도", "자산", "암시장기록", "지갑", "상점", "암시장"),
    "cards": ("카드게임", "게임도시", "게임전적", "도박잔액", "카지노"),
    "casino": ("카지노", "카지노잔액", "카지노미션", "게임전적", "도박정보"),
    "gambling": ("도박정보", "도박잔액", "정부지원금", "게임도시", "카지노", "코인"),
    "party_games": ("게임", "게임전적", "오늘의퀴즈", "퀴즈랭킹", "퀴즈통계"),
    "collections": ("최종컬렉션", "통합업적", "통합칭호", "전설도감", "탈것도감", "연대기박물관"),
    "black_city": ("도시", "지역위험도", "세계시장", "세력평판", "도시꾸미기"),
    "city_decor": ("도시꾸미기", "생산센터", "도시", "탐험가방", "연대기박물관"),
    "neon": ("차원문", "차원지도", "솔로원정", "장비", "생존허브"),
    "crew_raid": ("크루", "레이드", "길드관리", "장비", "게임전적"),
    "factions": ("세력평판", "세계상태", "지역위험도", "세계시장", "오늘의세계"),
    "disaster": ("재난상황", "재난예보", "재난임무", "재난보상", "재난날씨", "세계속보"),
    "creator": ("콘텐츠공방", "콘텐츠목록", "사용자사건"),
    "world_misc": ("오늘의세계", "세계상태", "세계속보", "세계시장", "세계지도", "지역위험도"),
    "guild": ("길드관리", "길드전", "길드전랭킹", "레이드", "크루"),
    "companions": ("동료", "NPC목록", "인연", "NPC대화", "AI동료상태"),
    "npc": ("인연", "NPC목록", "NPC대화", "인연기록", "배신경보", "AI동료상태"),
    "schedule": ("오늘할일", "오늘의루프", "스케줄러상태", "알림센터"),
    "competition": ("PvP랭크", "PvP랭킹", "길드전", "길드전랭킹", "서버시즌", "시즌랭킹"),
    "definitive": ("최종단말기", "최종일식", "일식결말", "일식보상", "오늘의루프"),
    "retention": ("오늘의루프", "최종루프보상", "최종컬렉션", "초보생존", "7일보급"),
}

SAFE_RELATED_BY_COMMAND: Dict[str, Tuple[str, ...]] = {
    "코인": ("시세", "매도", "자산", "암시장기록", "지갑", "암시장"),
    "오늘의퀴즈": ("퀴즈랭킹", "퀴즈통계", "퀴즈알림상태", "퀴즈목록"),
    "탈것도감": ("최종컬렉션", "연대기박물관", "통합업적", "전설도감"),
    "최종단말기": ("최종일식", "일식결말", "일식보상", "오늘의루프", "최종컬렉션"),
}


NO_RECOMMEND_GROUPS = {
    "server_setup", "security", "alerts", "recovery", "audit", "admin",
    "final_ops", "help", "support", "voice", "chat",
}
NO_RECOMMEND_TOKENS = (
    "검수", "audit", "오류", "error", "설정", "setting", "삭제", "delete",
    "복구", "restore", "백업", "backup", "서버운영", "운영단말기", "권리증명",
    "테스트", "test", "진단", "diagnostic",
)


def _resolve(bot: commands.Bot, current: str, candidate: Candidate) -> Optional[ResolvedAction]:
    for name in candidate.names:
        command = bot.get_command(name)
        if not _zero_arg(command):
            continue
        assert command is not None
        if not candidate.allow_current and _same_command(command, current):
            continue
        return ResolvedAction(command.qualified_name, candidate.ko, candidate.en, candidate.emoji, candidate.style)
    return None


def _story_buttons(bot: commands.Bot, user: Mapping[str, Any], current: str) -> List[ResolvedAction]:
    rows: List[ResolvedAction] = []
    try:
        target, _label, season, _state = core1650._story_target(user)
    except Exception:
        target, season = "스토리나침반", 1
    history = "스토리 기록" if season == 1 else f"시즌{season} 기록" if season <= 6 else "세계연대기"
    candidates = (
        C(target, ko="스토리 계속", en="Continue Story", emoji="📖", style=discord.ButtonStyle.success),
        C(history, "세계연대기", ko="지난 이야기", en="Story History", emoji="📜"),
        C("스토리나침반", "storycompass", ko="스토리 나침반", en="Story Compass", emoji="🧭", style=discord.ButtonStyle.primary),
    )
    for c in candidates:
        item = _resolve(bot, current, c)
        if item and item.command_name not in {x.command_name for x in rows}:
            rows.append(item)
    return rows[:MAX_BUTTONS]


def _special_policy_key(command_name: str) -> Optional[str]:
    token = command_name.casefold()
    if command_name in SPECIAL_BUTTONS:
        return command_name
    if command_name in {"코인", "코인탐색", "매도", "코인판매", "자산", "투자자산", "시세", "암시장시세", "암시장기록"}:
        return "코인"
    if command_name in {"최종단말기", "최종일식", "일식결말", "일식보상"} or "finaleclipse" in token:
        return "최종단말기"
    if "퀴즈" in command_name or "quiz" in token:
        return "오늘의퀴즈"
    if "탈것" in command_name or "mount" in token:
        return "탈것도감"
    return None


def _classify(ctx: commands.Context) -> Tuple[str, str]:
    command = getattr(ctx, "command", None)
    if command is None:
        return "system", "other"
    try:
        return hub._classify(command)
    except Exception:
        return "system", "other"


def _blocked(command_name: str, group: str) -> bool:
    low = command_name.casefold()
    if group in NO_RECOMMEND_GROUPS:
        return True
    if any(token in low for token in NO_RECOMMEND_TOKENS):
        return True
    return command_name in {
        "명령어", "help", "버튼", "패치노트", "버튼정책", "1803버튼검수",
        "추천버튼설정", "결과요약설정", "실시간오류센터", "현재오류", "과거오류",
        # v18.2.1 owner/admin commands must never receive gameplay recommendations.
        "서버사용로그", "서버사용통계", "운영통계", "실사용통계",
        "내서버목록", "봇검수", "프로덕션검수", "정리현황",
        "생존자명단", "생존자수", "생존자검색", "1821검수", "1831메뉴검수",
    }


def _primary_actions(bot: commands.Bot, user: Mapping[str, Any], command_name: str, group: str) -> List[ResolvedAction]:
    if group.startswith("story"):
        rows = _story_buttons(bot, user, command_name)
    else:
        key = _special_policy_key(command_name)
        candidates = SPECIAL_BUTTONS.get(key or "") or GROUP_BUTTONS.get(group, ())
        rows = []
        for c in candidates:
            item = _resolve(bot, command_name, c)
            if item and item.command_name not in {x.command_name for x in rows}:
                rows.append(item)
            if len(rows) >= MAX_BUTTONS:
                break

    # State-sensitive actions are only injected into gameplay groups where they
    # make direct sense; there is no global Story/Today/Hub fallback anymore.
    hp = int(user.get("hp", 100) or 100)
    infection = int(user.get("infection", 0) or 0)
    balance = int(user.get("balance", 0) or 0)
    if group in {"combat", "exploration", "story1", "story2", "story3", "story4", "story5", "story6"} and (hp <= 40 or infection >= 60):
        recover = _resolve(bot, command_name, C("휴식", "recover", ko="회복하기", en="Recover", emoji="❤️", style=discord.ButtonStyle.danger))
        if recover and recover.command_name not in {x.command_name for x in rows}:
            rows.insert(0, recover)
    if group in {"gambling", "economy"} and balance <= -10_000:
        relief = _resolve(bot, command_name, C("정부지원금", "governmentrelief", ko="정부지원금", en="Relief", emoji="🏛️", style=discord.ButtonStyle.success))
        if relief and relief.command_name not in {x.command_name for x in rows}:
            rows.insert(0, relief)
    return rows[:MAX_BUTTONS]


def _english_display(entry: hub.CommandEntry) -> str:
    try:
        return hub._english_alias(entry)
    except Exception:
        for alias in entry.aliases:
            if alias.isascii():
                return alias
        return entry.qualified_name


def _related_entries(bot: commands.Bot, locale: str, command_name: str, group: str, used: Iterable[str]) -> List[Tuple[str, str, str]]:
    """Return only explicitly curated, zero-argument, non-admin related actions.

    v18.1.4 deliberately removes the old "scan every command in this classifier
    group" fallback. That fallback could surface help/audit/final action commands
    when old metadata classified them too broadly, and every extra entry also
    enlarged the component->prefix bridge surface.
    """
    used_set = set(used)
    key = _special_policy_key(command_name)
    wanted = SAFE_RELATED_BY_COMMAND.get(key or command_name) or SAFE_RELATED_BY_GROUP.get(group, ())
    if not wanted:
        return []

    # Help text comes from the command hub when available, but only after the
    # command name has passed the curated whitelist and safety filters.
    entry_by_name: Dict[str, hub.CommandEntry] = {}
    entries = getattr(bot, "v1630_command_entries", [])
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, hub.CommandEntry):
            entry_by_name.setdefault(entry.qualified_name, entry)

    out: List[Tuple[str, str, str]] = []
    seen = set()
    for requested in wanted:
        command = bot.get_command(requested)
        if command is None or not _zero_arg(command):
            continue
        qname = command.qualified_name
        if qname in used_set or qname in seen or _same_command(command, command_name):
            continue
        if _blocked(qname, group):
            continue
        seen.add(qname)

        entry = entry_by_name.get(qname)
        if locale == "ko":
            label = qname
        elif entry is not None:
            label = _english_display(entry)
        else:
            label = next((str(a) for a in getattr(command, "aliases", []) if str(a).isascii()), qname)

        if entry is not None:
            try:
                desc = hub._display_help(locale, entry)
            except Exception:
                desc = entry.help_text
        else:
            desc = str(getattr(command, "help", "") or getattr(command, "brief", "") or "")
        desc = " ".join(str(desc).split()) or _t(locale, "관련 기능", "Related feature")
        out.append((qname, str(label)[:100], desc[:100]))
        if len(out) >= MAX_SELECT_OPTIONS:
            break
    return out


async def _clear_completed_indicator(interaction: discord.Interaction, delay: float = 0.35) -> None:
    """Remove the deferred thinking response with one webhook request.

    v18.1.3 removes the previous edit-then-delete pair. The real command result is
    already delivered through the normal channel route, so a single delete is
    enough to resolve Discord's thinking indicator and lowers interaction-webhook
    pressure on shared hosting IPs.
    """
    await asyncio.sleep(max(0.1, float(delay)))
    try:
        await interaction.delete_original_response()
    except (discord.NotFound, discord.HTTPException):
        pass


async def _run_context_interaction(view: "ContextActionView", interaction: discord.Interaction, command: commands.Command) -> None:
    """v18.1.3 single-response watchdog for contextual buttons/selects.

    Quick commands answer directly through the interaction callback (one request).
    Only slow commands receive a delayed silent ACK inside ``_invoke_command``.
    This function deliberately does not pre-defer or edit/delete the source menu.
    """
    locks = getattr(view.bot, "_v1805_context_locks", None)
    if not isinstance(locks, set):
        locks = set()
        setattr(view.bot, "_v1805_context_locks", locks)
    lock_key = int(interaction.user.id)
    if lock_key in locks:
        text = _t(view.locale, "⏳ 이전 버튼을 처리 중입니다. 잠시 후 다시 눌러주세요.", "⏳ Your previous action is still running. Please try again shortly.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True, wait=False)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass
        return

    locks.add(lock_key)
    try:
        try:
            ok = await asyncio.wait_for(
                _invoke_command(
                    view.bot,
                    interaction,
                    command.qualified_name,
                    prefer_channel_delivery=True,
                ),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            await _bridge_notice(
                interaction,
                _t(
                    view.locale,
                    f"⏱️ 버튼 실행이 15초를 넘겼습니다. 기존 `!{command.qualified_name}` 명령으로 다시 시도해주세요.",
                    f"⏱️ This button took longer than 15 seconds. Please use `!{command.qualified_name}` instead.",
                ),
            )
            print(f"[ABADDON v18.1.3] contextual interaction timeout command={command.qualified_name} user={interaction.user.id}", flush=True)
            return
        except Exception as exc:
            await _bridge_notice(
                interaction,
                _t(
                    view.locale,
                    f"🫧 버튼 연결을 마무리하지 못했습니다. `!{command.qualified_name}` 명령은 그대로 사용할 수 있어요.",
                    f"🫧 The button bridge could not finish. `!{command.qualified_name}` is still available.",
                ),
            )
            print(f"[ABADDON v18.1.3] contextual interaction error command={command.qualified_name} {type(exc).__name__}: {exc}", flush=True)
            return

        # _invoke_command already provides the success/failure response. Do not
        # create an additional webhook edit/delete/followup here.
        if not ok:
            return
    finally:
        locks.discard(lock_key)


class ContextButton(discord.ui.Button):
    def __init__(self, owner: "ContextActionView", action: ResolvedAction, row: int = 0) -> None:
        super().__init__(
            label=_t(owner.locale, action.ko, action.en)[:80],
            emoji=action.emoji,
            style=action.style,
            row=row,
        )
        self.owner_view = owner
        self.command_name = action.command_name

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        command = view.bot.get_command(self.command_name)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결된 기능을 찾지 못했습니다.", "The linked feature was not found."), ephemeral=True)
            return
        await _run_context_interaction(view, interaction, command)


class ContextSelect(discord.ui.Select):
    def __init__(self, owner: "ContextActionView", options: Sequence[Tuple[str, str, str]]) -> None:
        self.owner_view = owner
        rows = [discord.SelectOption(label=label[:100], value=command[:100], description=desc[:100]) for command, label, desc in options[:MAX_SELECT_OPTIONS]]
        super().__init__(
            placeholder=_t(owner.locale, "관련 기능 더보기", "More related features"),
            min_values=1,
            max_values=1,
            options=rows,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        command_name = str(self.values[0])
        command = view.bot.get_command(command_name)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "선택한 기능을 찾지 못했습니다.", "The selected feature was not found."), ephemeral=True)
            return
        await _run_context_interaction(view, interaction, command)


class ContextActionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, buttons: Sequence[ResolvedAction], related: Sequence[Tuple[str, str, str]]) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        for action in buttons[:MAX_BUTTONS]:
            self.add_item(ContextButton(self, action, row=0))
        if related:
            self.add_item(ContextSelect(self, related))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 UI는 실행자만 사용할 수 있습니다.", "Only the opener can use this UI."), ephemeral=True)
        return False


def _build_context(bot: commands.Bot, user: Mapping[str, Any], ctx: commands.Context, locale: str) -> Tuple[List[ResolvedAction], List[Tuple[str, str, str]], str]:
    command_name = _command_key(ctx)
    _section, group = _classify(ctx)
    if _blocked(command_name, group):
        return [], [], group
    buttons = _primary_actions(bot, user, command_name, group)
    related = _related_entries(bot, locale, command_name, group, [x.command_name for x in buttons])
    return buttons, related, group


def _group_label(locale: str, group: str) -> str:
    try:
        _section, ko, en, _dko, _den, emoji = hub._group_spec(group)
        return f"{emoji} {_t(locale, ko, en)}"
    except Exception:
        return _t(locale, "🧭 관련 기능", "🧭 Related Features")


def _remove_old_listener(bot: commands.Bot) -> int:
    removed = 0
    for listener in list(getattr(bot, "extra_events", {}).get("on_command_completion", []) or []):
        if getattr(listener, "__name__", "") in {"v1660_result_and_guidance", "v1650_next_actions"}:
            try:
                bot.remove_listener(listener, "on_command_completion")
                removed += 1
            except Exception:
                pass
    return removed


def register_v1803_contextual_ui(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1803_registered", False):
        return
    bot._abaddon_v1803_registered = True
    bot.abaddon_version = VERSION
    removed_old = _remove_old_listener(bot)
    setattr(bot, "v1803_removed_old_recommendation_listeners", removed_old)

    @bot.command(name="버튼정책", aliases=["상황버튼정책", "contextbuttons", "buttonpolicy"], help="v18.1.4 기능 맞춤형 버튼·안전 드롭다운 정책을 확인합니다.")
    async def button_policy(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        embed = discord.Embed(title=_t(locale, "🧭 기능 맞춤형 버튼 정책", "🧭 Contextual Button Policy"), color=0x6C4DDB)
        embed.add_field(name=_t(locale, "직접 버튼", "Direct Buttons"), value=_t(locale, "현재 기능과 직접 연결되는 행동만 **최대 4개** 표시합니다.", "Shows only actions directly related to the current feature, up to **4**."), inline=False)
        embed.add_field(name=_t(locale, "관련 기능 드롭다운", "Related Dropdown"), value=_t(locale, "같은 기능군의 안전한 무인자 명령만 최대 **12개** 제공합니다.", "Offers up to **12** safe zero-argument commands from the same feature group."), inline=False)
        embed.add_field(name=_t(locale, "제거된 전역 버튼", "Removed Global Fallback"), value=_t(locale, "모든 결과에 일괄로 붙던 `스토리 계속 · 장비 확인 · 상점 · 오늘 할 일 · 생존 허브` 조합을 제거했습니다.", "Removed the old global `Story · Gear · Shop · Today · Hub` row from unrelated results."), inline=False)
        embed.add_field(name=_t(locale, "운영·검수", "Admin & Audit"), value=_t(locale, "검수·설정·복구·운영 명령에는 게임 추천 UI를 붙이지 않습니다.", "Audit, settings, restore and operations commands receive no gameplay recommendation UI."), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="1803버튼검수", aliases=["v1803audit", "1803audit", "버튼드롭다운검수"], help="기능 맞춤 버튼·드롭다운·구형 전역 버튼 제거 상태를 검사합니다.")
    async def audit_1803(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(bot, ctx)
        sample_user: Mapping[str, Any] = _safe_user(get_user, ctx.author.id) or {"hp": 100, "infection": 0, "balance": 0}

        def resolve_special(name: str) -> List[str]:
            key = _special_policy_key(name)
            rows = []
            for cand in SPECIAL_BUTTONS.get(key or name, ()):
                item = _resolve(bot, name, cand)
                if item:
                    rows.append(item.command_name)
            return rows

        coin = resolve_special("코인")
        quiz = resolve_special("오늘의퀴즈")
        bad_global = {"스토리나침반", "장비", "상점", "오늘할일", "생존허브"}
        checks = [
            (_t(locale, "구형 전역 추천 리스너 제거", "Old global listener removed"), removed_old >= 1),
            (_t(locale, "직접 버튼 최대 4개", "Maximum four direct buttons"), MAX_BUTTONS == 4),
            (_t(locale, "드롭다운 최대 12개", "Maximum twelve dropdown options"), MAX_SELECT_OPTIONS == 12),
            (_t(locale, "코인 결과 전용 동선", "Coin-specific flow"), bool(coin) and not bool(set(coin) & bad_global)),
            (_t(locale, "퀴즈 결과 전용 동선", "Quiz-specific flow"), bool(quiz) and all("퀴즈" in x or "quiz" in x.casefold() for x in quiz)),
            (_t(locale, "운영·검수 추천 차단", "No gameplay UI on audits/admin"), _blocked("1803버튼검수", "final_ops")),
            (_t(locale, "필수 입력 명령 버튼 제외", "Required-argument commands excluded"), callable(_zero_arg)),
            (_t(locale, "기존 결과 요약 로직 보존", "Result summary preserved"), callable(live1660._snapshot) and callable(live1660._diff) and callable(live1660._result_embed)),
            (_t(locale, "한/영 버튼 라벨 분리", "KO/EN labels separated"), all(c.ko and c.en for rows in GROUP_BUTTONS.values() for c in rows)),
        ]
        ok = all(v for _n, v in checks)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v18.0.3 버튼·드롭다운 검수", "🧪 ABADDON v18.0.3 Button & Dropdown Audit"), color=0x2ECC71 if ok else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks)
        if 상세:
            embed.add_field(name=_t(locale, "코인 버튼", "Coin Buttons"), value=" · ".join(f"`!{x}`" for x in coin) or "-", inline=False)
            embed.add_field(name=_t(locale, "퀴즈 버튼", "Quiz Buttons"), value=" · ".join(f"`!{x}`" for x in quiz) or "-", inline=False)
            embed.add_field(name=_t(locale, "정책", "Policy"), value=_t(locale, "직접 행동 0~4개 + 검수된 기능별 화이트리스트 드롭다운 0~12개 · 관련 기능이 없으면 드롭다운을 표시하지 않음", "0-4 direct actions + 0-12 curated safe related options; no dropdown when nothing relevant exists."), inline=False)
        await ctx.send(embed=embed)

    @bot.listen("on_command_completion")
    async def v1803_context_result_and_guidance(ctx: commands.Context) -> None:
        try:
            if getattr(ctx.author, "bot", False):
                return
            command_name = _command_key(ctx)
            if not command_name:
                return
            user = _safe_user(get_user, ctx.author.id)
            if user is None:
                return
            locale = _locale(bot, ctx)
            legacy_state = live1660._state(user)
            ui_state = _root(user)
            tutorial_note = live1660._advance_tutorial(user, command_name, locale)
            before = getattr(ctx, "_v1660_before", live1660._snapshot(user))
            after = live1660._snapshot(user)
            gains, changes, unlocks = live1660._diff(locale, before, after)
            if tutorial_note:
                save_data()

            # A contextual button already has its source action panel. Re-appending
            # result-summary/next-action UI after the bridged command creates extra
            # Discord requests and can trigger Cloudflare 1015 on shared hosting.
            # Direct prefix commands keep the full summary + recommendation flow.
            if bool(getattr(ctx, "_v1813_button_bridge", False)):
                return

            skip_names = {
                "초보생존", "firstsurvival", "초보센터", "beginnercenter",
                "결과요약설정", "추천버튼설정", "실시간오류센터", "경제정산검수",
                "1660통합검수", "버튼정책", "1803버튼검수", "패치노트",
            }
            if command_name in skip_names:
                return

            summary_enabled = bool(legacy_state.get("result_summary", True))
            recommendations_enabled = bool(legacy_state.get("smart_recommendations", True)) and bool(ui_state.get("enabled", True))
            buttons: List[ResolvedAction] = []
            related: List[Tuple[str, str, str]] = []
            group = "other"
            if recommendations_enabled:
                buttons, related, group = _build_context(bot, user, ctx, locale)
                if not bool(ui_state.get("dropdown", True)):
                    related = []
            view = ContextActionView(bot, ctx.author.id, locale, buttons, related) if (buttons or related) else None

            if summary_enabled and (gains or changes or unlocks or tutorial_note):
                embed = live1660._result_embed(locale, command_name, gains, changes, unlocks, tutorial_note)
                if view is not None:
                    embed.add_field(name=_t(locale, "🧭 이어서 할 수 있는 기능", "🧭 Relevant Next Actions"), value=_group_label(locale, group), inline=False)
                await ctx.send(embed=embed, view=view)
            elif view is not None:
                await ctx.send(_t(locale, f"🧭 **{_group_label(locale, group)} 관련 행동**", f"🧭 **{_group_label(locale, group)} actions**"), view=view)
        except Exception as exc:
            print(f"[ABADDON v{VERSION} 상황형 UI 경고] {type(exc).__name__}: {exc}", flush=True)

    # Let the already-mounted v18 command center see the two new hotfix commands
    # without rebuilding or deleting any legacy entry.
    try:
        existing = getattr(bot, "v1630_command_entries", None)
        fresh = hub._build_registry(bot)
        if isinstance(existing, list):
            existing[:] = fresh
            entries = existing
        else:
            entries = fresh
            setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} 명령 허브 새로고침 경고] {type(exc).__name__}: {exc}", flush=True)

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, "📜 ABADDON v18.0.3 상황형 UI 핫픽스", "📜 ABADDON v18.0.3 Contextual UI Hotfix"), color=0x6C4DDB)
            embed.add_field(name=_t(locale, "🧭 기능 맞춤 버튼", "🧭 Context Buttons"), value=_t(locale, "모든 결과에 같은 버튼을 붙이지 않고 현재 기능에 맞는 직접 행동만 최대 4개 표시합니다.", "Replaces the global button row with up to four actions relevant to the current feature."), inline=False)
            embed.add_field(name=_t(locale, "🔽 관련 기능 드롭다운", "🔽 Related Dropdown"), value=_t(locale, "같은 기능군의 안전한 무인자 명령만 드롭다운으로 제공합니다.", "The dropdown contains only safe zero-argument commands from the same feature group."), inline=False)
            embed.add_field(name=_t(locale, "🪙 코인 예시", "🪙 Coin Example"), value=_t(locale, "코인 탐색 결과에는 `다시 코인 탐색 · 알바 · 땅파기 · 수입/손익`만 표시합니다.", "Coin results now show `scan again · work · dig · balance`, not unrelated story/gear navigation."), inline=False)
            embed.add_field(name=_t(locale, "🧠 v18.0.2 퀴즈 유지", "🧠 v18.0.2 Quiz Preserved"), value=_t(locale, "200문제 문제은행·정답 검수·자동 알림 동기화를 그대로 보존합니다.", "Preserves the 200-question bank, answer audit and synchronized daily notifications."), inline=False)
            embed.add_field(name=_t(locale, "🧪 검수", "🧪 Audit"), value="`!1803버튼검수 상세` · `!1802퀴즈검수 상세` · `!1800통합검수 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 명령·저장 데이터 삭제 0건 · v18.0.x 핫픽스", "0 legacy command/save-data deletions · v18.0.x hotfix"))
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v18.0.3 기능 맞춤형 버튼·드롭다운 최신 핫픽스입니다."
        patch.description = patch.help

    print(
        f"[ABADDON v{VERSION}] contextual UI registered: "
        f"old_listener_removed={removed_old} groups={len(GROUP_BUTTONS)} specials={len(SPECIAL_BUTTONS)} "
        f"buttons<={MAX_BUTTONS} select<={MAX_SELECT_OPTIONS}",
        flush=True,
    )
