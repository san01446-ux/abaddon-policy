from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import inspect
import random
import re
import secrets
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "10.0.0"
SCHEMA_VERSION = 1
KST = timezone(timedelta(hours=9))
HANGUL_RE = re.compile(r"[가-힣]")
HANGUL_RUN_RE = re.compile(r"[가-힣]+")
ASCII_RE = re.compile(r"^[\x00-\x7f]+$")
LANGUAGE_CHECK_SENTINEL = "__ABADDON_LANGUAGE_SELECTION_REQUIRED__"

# This module intentionally keeps gameplay state shared. Locale only affects rendering.
_RUNTIME: Dict[str, Any] = {}
_PATCHED = False


# ---------------------------------------------------------------------------
# Localized copy for v10.0.0 features
# ---------------------------------------------------------------------------
TEXT: Mapping[str, Mapping[str, str]] = {
    "ko": {
        "language_title": "🌐 표시 언어 선택",
        "language_prompt": "게임 화면에 사용할 언어를 선택해 주세요. 선택한 언어 하나만 표시됩니다.",
        "language_saved": "✅ 표시 언어를 **한국어**로 설정했습니다.",
        "server_language_saved": "✅ 서버 공개 패널의 기본 언어를 **한국어**로 설정했습니다.",
        "language_current": "🌐 현재 개인 언어: **한국어**\n공개 공동 패널은 서버 기본 언어를 사용합니다.",
        "admin_only": "⛔ 서버 관리자만 사용할 수 있습니다.",
        "guild_only": "⚠️ 서버 채널에서만 사용할 수 있습니다.",
        "registered_only": "⛔ 먼저 `!가입 생존자`로 생존자를 등록해 주세요.",
        "tasks_title": "📋 생존자 임무 추적기",
        "tasks_desc": "현재 진행 중인 공동 콘텐츠와 받을 수 있는 보상을 한 화면에 정리했습니다.",
        "codex_title": "📚 아바돈 생존 도감",
        "relationships_title": "🤝 생존자 인연 기록",
        "expedition_title": "🛰️ 주간 글로벌 탐사 작전",
        "expedition_joined": "✅ **{role}** 역할로 탐사 작전에 합류했습니다.",
        "expedition_already_joined": "ℹ️ 이미 이번 탐사 작전에 참가하고 있습니다.",
        "expedition_not_joined": "⚠️ 먼저 `!탐사참가 역할`로 작전에 합류해 주세요.",
        "expedition_complete": "🎯 공동 목표가 완료되었습니다. 관리자가 정산하면 개인 보상을 받을 수 있습니다.",
        "expedition_not_ready": "⚠️ 아직 공동 목표가 완료되지 않았습니다.",
        "expedition_settled": "✅ 탐사 작전 정산 완료 · 참여자 개인 보상이 개방되었습니다.",
        "expedition_claimed": "🎁 탐사 보상 수령 · 식량 **+{food:,}** · 보물파편 **+{fragments}** · 관계 경험 **+{bond}**",
        "expedition_no_reward": "📭 수령 가능한 탐사 작전 보상이 없습니다.",
        "notifications_title": "🔔 알림·보상 회수 센터",
        "no_notifications": "새로운 알림이 없습니다.",
        "unclaimed_title": "🎁 미수령 보상 점검",
        "claim_all_done": "✅ 안전하게 확인 가능한 보상 수령 절차를 완료했습니다.",
        "getting_started_title": "🧭 신규 생존자 시작 안내",
        "returning_title": "🧳 복귀 생존자 안내",
        "audit_title": "🛡️ ABADDON v10.0.0 통합 안정화 검수",
        "audit_ok": "정상",
        "audit_fail": "확인 필요",
        "missing_title": "🌐 번역 누락·대체 기록",
        "command_audit_title": "⌨️ 한·영 명령어 전수 검사",
        "progress_depart": "출발 준비",
        "progress_move": "지역 이동",
        "progress_scan": "신호 탐지",
        "progress_action": "현장 행동",
        "progress_return": "귀환 처리",
        "progress_done": "작전 완료",
        "progress_label": "진행률",
        "route_label": "이동 경로",
        "help_footer": "선택 언어 하나만 표시 · 한·영 병렬 출력 없음",
    },
    "en": {
        "language_title": "🌐 Display Language",
        "language_prompt": "Choose the language used by the game interface. Only the selected language will be displayed.",
        "language_saved": "✅ Display language set to **English**.",
        "server_language_saved": "✅ The server language for public panels is now **English**.",
        "language_current": "🌐 Personal language: **English**\nPublic co-op panels use the server language.",
        "admin_only": "⛔ This command is restricted to server administrators.",
        "guild_only": "⚠️ This command can only be used in a server channel.",
        "registered_only": "⛔ Register a survivor first with `!register survivor`.",
        "tasks_title": "📋 Survivor Mission Tracker",
        "tasks_desc": "Active co-op content and available rewards are collected in one place.",
        "codex_title": "📚 ABADDON Survival Codex",
        "relationships_title": "🤝 Survivor Relationship Records",
        "expedition_title": "🛰️ Weekly Global Expedition",
        "expedition_joined": "✅ Joined the expedition as **{role}**.",
        "expedition_already_joined": "ℹ️ You are already part of this expedition.",
        "expedition_not_joined": "⚠️ Join first with `!joinexpedition role`.",
        "expedition_complete": "🎯 The shared objective is complete. Personal rewards open after an administrator settles the operation.",
        "expedition_not_ready": "⚠️ The shared objective has not been completed yet.",
        "expedition_settled": "✅ Expedition settled. Personal contribution rewards are now available.",
        "expedition_claimed": "🎁 Expedition reward claimed · Food **+{food:,}** · Treasure Fragments **+{fragments}** · Bond XP **+{bond}**",
        "expedition_no_reward": "📭 There are no expedition rewards available.",
        "notifications_title": "🔔 Notification & Reward Center",
        "no_notifications": "There are no new notifications.",
        "unclaimed_title": "🎁 Unclaimed Reward Check",
        "claim_all_done": "✅ All safely detectable reward claims have been processed.",
        "getting_started_title": "🧭 New Survivor Guide",
        "returning_title": "🧳 Returning Survivor Guide",
        "audit_title": "🛡️ ABADDON v10.0.0 Integrated Stability Audit",
        "audit_ok": "PASS",
        "audit_fail": "REVIEW",
        "missing_title": "🌐 Translation Fallback Report",
        "command_audit_title": "⌨️ Korean-English Command Audit",
        "progress_depart": "Preparing departure",
        "progress_move": "Moving through the region",
        "progress_scan": "Scanning signals",
        "progress_action": "Executing field action",
        "progress_return": "Processing return",
        "progress_done": "Operation complete",
        "progress_label": "Progress",
        "route_label": "Travel Route",
        "help_footer": "One selected language only · no stacked Korean-English output",
    },
}


# Carefully curated high-frequency phrases. Exact v10 content uses TEXT above;
# this glossary localizes legacy content without duplicating gameplay logic.
EXACT_EN: Dict[str, str] = {
    "정상": "PASS",
    "확인 필요": "REVIEW REQUIRED",
    "완료 기록이 없습니다.": "There are no completed records.",
    "수령 가능한 보상이 없습니다.": "There are no rewards available to claim.",
    "이미 수령한 보상입니다.": "This reward has already been claimed.",
    "이미 정산된 레이드입니다.": "This raid has already been settled.",
    "관리자만 사용할 수 있습니다.": "This command is restricted to administrators.",
    "서버에서만 사용할 수 있습니다.": "This command can only be used in a server.",
    "처리 중입니다.": "Processing is already in progress.",
    "데이터를 저장했습니다.": "Data saved successfully.",
    "현재 진행 중인 사건이 없습니다.": "There is no active case.",
    "아직 발견하지 못했습니다.": "Not discovered yet.",
    "사용법": "Usage",
    "보유": "Owned",
    "필요": "Required",
    "현재": "Current",
    "완료": "Complete",
    "실패": "Failed",
    "성공": "Success",
}

PHRASES_EN: Dict[str, str] = {
    # World and lore
    "아바돈": "ABADDON", "생존자": "Survivor", "종말": "Apocalypse", "폐허": "Ruins",
    "황무지": "Wasteland", "대피소": "Shelter", "세계 상태": "World Status", "세계상태": "World Status",
    "세계 순환": "World Cycle", "세계순환": "World Cycle", "세계지도": "World Map",
    "세계 지령": "World Directive", "세계지령": "World Directive", "연대기": "Chronicle",
    "지역": "Region", "지역정보": "Region Info", "지역 정찰": "Region Scout", "지역정찰": "Region Scout",
    "개척": "Development", "거점": "Outpost", "보급로": "Supply Route", "무역로": "Trade Route",
    "호송": "Convoy", "재난": "Disaster", "기상": "Weather", "오염": "Contamination",
    "안정도": "Stability", "보급": "Supply", "사기": "Morale", "안전도": "Safety",
    "백색등 구조대": "White Light Rescue Corps", "푸른 방패 민병대": "Blue Shield Militia",
    "새벽 의무단": "Dawn Medical Corps", "철도 복구단": "Railway Restoration Crew",
    "보급 호위대": "Supply Escort Unit", "황무지 정찰대": "Wasteland Recon Unit",
    "붉은 송곳니 약탈단": "Red Fang Raiders", "검은 먼지 밀수조직": "Black Dust Smugglers",
    "고철왕의 기계 군단": "Scrap King's Machine Legion", "심연 감염 숭배자": "Abyss Infection Cult",
    # Character systems
    "캐릭터": "Character", "직업": "Job", "전문화": "Specialization", "레벨": "Level",
    "경험치": "Experience", "전투력": "Combat Power", "체력": "HP", "스태미나": "Stamina",
    "감염": "Infection", "칭호": "Title", "업적": "Achievement", "랭킹": "Ranking",
    "군인": "Soldier", "의사": "Doctor", "기술자": "Engineer", "저격수": "Sniper",
    "연구원": "Researcher", "사냥꾼": "Hunter", "정찰병": "Scout", "의무병": "Medic",
    "방벽대장": "Bulwark Captain", "돌격대장": "Assault Captain", "전장의무관": "Field Medical Officer",
    "감염치료사": "Infection Specialist", "요새설계사": "Fortress Architect", "노선복구사": "Route Restorer",
    "관측저격수": "Observer Sniper", "파쇄사수": "Breaker Marksman", "오염분석관": "Contamination Analyst",
    "신호해독관": "Signal Decoder", "황무지추적자": "Wasteland Tracker", "보급개척자": "Supply Pathfinder",
    # Items/economy
    "식량": "Food", "고철": "Scrap Metal", "나무": "Wood", "광석": "Ore", "약초": "Herbs",
    "강화석": "Enhancement Stone", "강화보호권": "Enhancement Protection", "옵션재설정권": "Option Reset Ticket",
    "보물파편": "Treasure Fragment", "폐허회로": "Ruin Circuit", "오염표본": "Contamination Sample",
    "장비": "Equipment", "무기": "Weapon", "방어구": "Armor", "아이템": "Item", "재료": "Materials",
    "인벤토리": "Inventory", "상점": "Shop", "구매": "Purchase", "판매": "Sell", "거래소": "Market",
    "은행": "Bank", "입금": "Deposit", "출금": "Withdraw", "대출": "Loan", "상환": "Repayment",
    "강화": "Enhancement", "제작": "Crafting", "수리": "Repair", "내구도": "Durability",
    "보상": "Reward", "미수령": "Unclaimed", "수령": "Claim", "기여도": "Contribution",
    # Gameplay
    "파밍": "Scavenging", "파밍출발": "Start Scavenging", "랜덤 인카운트": "Random Encounter",
    "인카운트": "Encounter", "탐색": "Explore", "정찰": "Scout", "수색": "Search",
    "분석": "Analyze", "확보": "Secure", "구조": "Rescue", "교섭": "Negotiate", "협상": "Negotiate",
    "전투": "Combat", "공격": "Attack", "방어": "Defend", "기술": "Skill", "도주": "Escape",
    "괴물": "Monster", "감염체": "Infected", "변이체": "Mutant", "약탈자": "Raider",
    "던전": "Dungeon", "레이드": "Raid", "월드보스": "World Boss", "보스": "Boss",
    "길드": "Guild", "파티": "Party", "분대": "Squad", "분대 전술": "Squad Tactics",
    "세력": "Faction", "평판": "Reputation", "동맹": "Ally", "신뢰": "Trusted", "중립": "Neutral",
    "세력전쟁": "Faction War", "복구작전": "Restoration Operation", "복구 작전": "Restoration Operation",
    "의뢰": "Mission", "계약": "Contract", "일일": "Daily", "주간": "Weekly", "시즌": "Season",
    "사건판": "Case Board", "사건": "Case", "단서": "Clue", "증거": "Evidence", "용의자": "Suspect",
    "현상금": "Bounty", "수사": "Investigation", "수사 레이드": "Investigation Raid",
    "수사레이드": "Investigation Raid", "전시실": "Showcase", "트로피": "Trophy", "장식": "Decoration",
    "인연": "Relationship", "관계": "Relationship", "도감": "Codex", "알림": "Notification",
    "임무": "Mission", "추적": "Tracking", "작전": "Operation", "탐사": "Expedition",
    # Interface and results
    "명령어": "Command", "도움말": "Help", "설정": "Settings", "관리자": "Administrator",
    "시스템점검": "System Check", "안정화검수": "Stability Audit", "검수": "Audit", "테스트": "Test",
    "진행률": "Progress", "진행도": "Progress", "상태": "Status", "기록": "Records", "목록": "List",
    "정보": "Information", "설명": "Description", "이름": "Name", "수량": "Amount", "가격": "Price",
    "남은 시간": "Time Remaining", "재사용 대기": "Cooldown", "대기시간": "Cooldown",
    "참가": "Join", "참여": "Participate", "모집": "Recruitment", "출발": "Depart", "귀환": "Return",
    "정산": "Settlement", "해금": "Unlocked", "잠김": "Locked", "활성": "Active", "비활성": "Inactive",
    "완료되었습니다": "has been completed", "완료했습니다": "completed", "완료": "Complete",
    "실패했습니다": "failed", "성공했습니다": "succeeded", "성공": "Success", "실패": "Failure",
    "없습니다": "is unavailable", "있습니다": "is available", "아직": "Not yet", "이미": "Already",
    "확인하세요": "Please check", "확인해 주세요": "Please check", "입력하세요": "Enter a value",
    "선택하세요": "Choose an option", "사용할 수 없습니다": "cannot be used", "부족합니다": "is insufficient",
    "잘못됐습니다": "is invalid", "찾을 수 없습니다": "could not be found", "저장": "Save",
    "삭제": "Deletion", "변경": "Change", "추가": "Add", "갱신": "Refresh", "검색": "Search",
    "버튼": "Button", "드롭다운": "Dropdown", "입력창": "Input Form", "페이지": "Page",
    # v10.1.0 companions and expanded card games
    "동료·확장 카드게임": "Companions & Expanded Card Games",
    "NPC 동료 6명과 포커·화투 확장 카드게임": "Six NPC companions and expanded poker and hwatu games",
    "카드게임 8종": "Eight Card Modes", "텍사스 홀덤": "Texas Hold'em",
    "오마하 홀덤": "Omaha Hold'em", "세븐카드 스터드": "Seven-Card Stud",
    "동료 목록": "Companion List", "동료 영입": "Recruit Companion",
    "동료 배치": "Assign Companion", "동료 대화": "Talk to Companion",
    "동료 임무": "Companion Mission", "동료 기록": "Companion Log",
    "동료": "Companion", "맞고": "Matgo", "고스톱": "Go-Stop", "화투": "Hwatu",
    "개": "", "명": " players", "회": " times", "점": " points", "단계": " stage",
}

# English prose occasionally present in older Korean surfaces.
PHRASES_KO: Dict[str, str] = {
    "English command refresh": "영문 명령어 최신화",
    "Help Interfaces": "도움말 화면",
    "Account & Profile": "계정·프로필",
    "Life & Exploration": "생활·탐험",
    "Equipment & Crafting": "장비·제작",
    "Combat & Dungeons": "전투·던전",
    "Economy & Trading": "경제·거래",
    "Story & Expeditions": "스토리·원정",
    "Server Management": "서버 관리",
    "Overview": "전체 안내",
}


# Approximate Revised Romanization fallback. This is only used for rare legacy
# proper nouns or uncurated fragments and is tracked by the audit command.
_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_JONG = ["", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lb", "ls", "lt", "lp", "lh", "m", "p", "ps", "t", "t", "ng", "t", "t", "k", "t", "p", "h"]


def _romanize_run(value: str) -> str:
    out: List[str] = []
    for ch in value:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            cho = code // 588
            jung = (code % 588) // 28
            jong = code % 28
            out.append(_CHO[cho] + _JUNG[jung] + _JONG[jong])
        else:
            out.append(ch)
    result = "".join(out)
    return result[:1].upper() + result[1:] if result else "LegacyText"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_key() -> str:
    local = datetime.now(timezone.utc).astimezone(KST)
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1000_global_survivor", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1000_global_survivor"] = root
    root["schema_version"] = SCHEMA_VERSION
    root.setdefault("users", {})
    root.setdefault("guilds", {})
    root.setdefault("translation", {"fallback_total": 0, "fallbacks": {}, "parallel_blocks": 0})
    root.setdefault("stats", {"expeditions": 0, "claims": 0, "deletions": 0})
    return root


def _user_locale(root: Mapping[str, Any], user_id: Any, guild_id: Any = None) -> str:
    users = root.get("users", {}) if isinstance(root, dict) else {}
    row = users.get(str(user_id), {}) if isinstance(users, dict) else {}
    locale = str(row.get("locale", "")) if isinstance(row, dict) else ""
    if locale in {"ko", "en"}:
        return locale
    return _guild_locale(root, guild_id)


def _guild_locale(root: Mapping[str, Any], guild_id: Any) -> str:
    guilds = root.get("guilds", {}) if isinstance(root, dict) else {}
    row = guilds.get(str(guild_id), {}) if isinstance(guilds, dict) else {}
    locale = str(row.get("locale", "ko")) if isinstance(row, dict) else "ko"
    return locale if locale in {"ko", "en"} else "ko"


def _set_user_locale(root: MutableMapping[str, Any], user_id: Any, locale: str) -> None:
    users = root.setdefault("users", {})
    row = users.setdefault(str(user_id), {})
    row["locale"] = locale
    row["selected_at"] = _now_iso()
    row["version"] = VERSION


def _set_guild_locale(root: MutableMapping[str, Any], guild_id: Any, locale: str) -> None:
    guilds = root.setdefault("guilds", {})
    row = guilds.setdefault(str(guild_id), {})
    row["locale"] = locale
    row["changed_at"] = _now_iso()
    row["version"] = VERSION


def L(locale: str, key: str, **values: Any) -> str:
    table = TEXT.get(locale, TEXT["ko"])
    text = table.get(key, TEXT["ko"].get(key, key))
    try:
        return text.format(**values)
    except Exception:
        return text


def _preferred_ascii_alias(bot: commands.Bot, korean_name: str) -> str:
    command = bot.get_command(korean_name)
    if command is None:
        return korean_name
    candidates = [str(command.name), *(str(x) for x in getattr(command, "aliases", []))]
    candidates = [x for x in candidates if ASCII_RE.fullmatch(x) and any(ch.isalpha() for ch in x)]
    return min(candidates, key=lambda x: (len(x), x)) if candidates else korean_name


def _replace_command_tokens(text: str, bot: Optional[commands.Bot]) -> str:
    if bot is None:
        return text

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        suffix = match.group(2) or ""
        preferred = _preferred_ascii_alias(bot, name)
        return "!" + preferred + suffix

    return re.sub(r"!([가-힣A-Za-z0-9_]+)([^\s`]*)", repl, text)


def _record_fallback(source: str, translated: str) -> None:
    root = _RUNTIME.get("root")
    if not isinstance(root, dict):
        return
    info = root.setdefault("translation", {"fallback_total": 0, "fallbacks": {}, "parallel_blocks": 0})
    info["fallback_total"] = int(info.get("fallback_total", 0) or 0) + 1
    key = hashlib.sha1(source.encode("utf-8", "ignore")).hexdigest()[:10].upper()
    rows = info.setdefault("fallbacks", {})
    row = rows.setdefault(key, {"source_preview": source[:120], "output_preview": translated[:120], "count": 0})
    row["count"] = int(row.get("count", 0) or 0) + 1


def translate_text(text: Any, locale: str, *, bot: Optional[commands.Bot] = None) -> Any:
    if not isinstance(text, str) or not text:
        return text
    if locale == "ko":
        result = text
        for source, target in sorted(PHRASES_KO.items(), key=lambda item: len(item[0]), reverse=True):
            result = result.replace(source, target)
        return result
    if not HANGUL_RE.search(text):
        return text

    # Preserve fenced code language identifiers and mentions/URLs; translate the visible text.
    result = _replace_command_tokens(text, bot)
    if result in EXACT_EN:
        return EXACT_EN[result]
    for source, target in sorted(EXACT_EN.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(source, target)
    for source, target in sorted(PHRASES_EN.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(source, target)

    # Remove common particles/endings that remain after vocabulary replacement.
    suffixes = {
        "으로": " as ", "에서": " in ", "에게": " to ", "부터": " from ", "까지": " to ",
        "하고": " and ", "이며": " and ", " 또는 ": " or ", " 및 ": " and ",
        "을": "", "를": "", "은": "", "는": "", "이": "", "가": "", "의": "'s ",
        "에": " in ", "와": " and ", "과": " and ", "도": " also ", "만": " only ",
        "입니다": "", "합니다": "", "됩니다": "", "하세요": "", "해주세요": "", "했습니다": "",
    }
    for source, target in sorted(suffixes.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(source, target)

    if HANGUL_RE.search(result):
        before = result
        result = HANGUL_RUN_RE.sub(lambda m: _romanize_run(m.group(0)), result)
        _record_fallback(before, result)
    # Clean repeated whitespace while preserving newlines.
    result = "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in result.splitlines())
    return result


def _translate_embed(embed: Optional[discord.Embed], locale: str, bot: Optional[commands.Bot]) -> Optional[discord.Embed]:
    if embed is None:
        return None
    try:
        data = copy.deepcopy(embed.to_dict())
        for key in ("title", "description"):
            if isinstance(data.get(key), str):
                data[key] = translate_text(data[key], locale, bot=bot)
        if isinstance(data.get("footer"), dict) and isinstance(data["footer"].get("text"), str):
            data["footer"]["text"] = translate_text(data["footer"]["text"], locale, bot=bot)
        if isinstance(data.get("author"), dict) and isinstance(data["author"].get("name"), str):
            data["author"]["name"] = translate_text(data["author"]["name"], locale, bot=bot)
        for field in data.get("fields", []) or []:
            if isinstance(field.get("name"), str):
                field["name"] = translate_text(field["name"], locale, bot=bot)
            if isinstance(field.get("value"), str):
                field["value"] = translate_text(field["value"], locale, bot=bot)
        return discord.Embed.from_dict(data)
    except Exception:
        return embed



V1093_COMPONENT_EMOJI_SANITIZER = True

_UI_EMOJI_REPLACEMENTS: Mapping[str, str] = {
    "🀙": "🎴",  # Mahjong tile glyph: Discord does not accept it as a component emoji.
    "🂠": "🎴",  # Playing-card-back symbol is not an RGI emoji in Discord components.
    "¼": "🔹",
    "½": "🔸",
    "✖️2": "✖️",
}


def _sanitize_ui_emoji(value: Any) -> Any:
    """Return a Discord-safe component emoji.

    Discord accepts custom emoji IDs and recognised Unicode emoji sequences, but
    rejects several symbol glyphs that still render as text in Python.  A single
    invalid option makes the whole message fail with HTTP 50035, so known unsafe
    glyphs are normalised before every send/edit.  Unknown custom emojis are left
    intact because their numeric ID is authoritative.
    """
    if value is None:
        return None
    emoji_id = getattr(value, "id", None)
    if emoji_id is not None:
        return value
    name = str(getattr(value, "name", value) or "")
    replacement = _UI_EMOJI_REPLACEMENTS.get(name)
    if replacement:
        return replacement
    # Component emoji names must not contain ordinary ASCII text.  Keycap emoji
    # are the sole useful exception (e.g. 6️⃣).
    has_ascii_word = any(ch.isascii() and ch.isalnum() for ch in name)
    is_keycap = bool(name) and name[-1:] == "⃣" and name[0] in "0123456789#*"
    if has_ascii_word and not is_keycap:
        return None
    return value


def _sanitize_component_emojis(item: Any) -> None:
    try:
        emoji = getattr(item, "emoji", None)
        safe = _sanitize_ui_emoji(emoji)
        if safe is not emoji:
            item.emoji = safe
    except Exception:
        pass
    try:
        for option in getattr(item, "options", None) or []:
            emoji = getattr(option, "emoji", None)
            safe = _sanitize_ui_emoji(emoji)
            if safe is not emoji:
                option.emoji = safe
    except Exception:
        pass

def _translate_view(view: Any, locale: str, bot: Optional[commands.Bot]) -> Any:
    """Translate interactive UI without touching deprecated TextInput.label.

    discord.py 2.6+ moved modal input captions to ``discord.ui.Label``.
    Reading or assigning ``TextInput.label`` emits a DeprecationWarning in 2.7.
    ABADDON modal inputs are already created in the selected locale, so the
    runtime translator only needs to localize buttons, selects, placeholders,
    options, and modern Label containers.
    """
    if view is None:
        return view
    # Emoji validation applies even to views that intentionally opt out of text
    # localization; one bad glyph invalidates the entire Discord form body.
    for child in getattr(view, "children", []):
        _sanitize_component_emojis(child)
    if getattr(view, "_abaddon_no_localize", False):
        return view

    text_input_type = getattr(getattr(discord, "ui", None), "TextInput", ())
    label_type = getattr(getattr(discord, "ui", None), "Label", ())

    def translate_component(item: Any) -> None:
        _sanitize_component_emojis(item)
        is_text_input = bool(text_input_type) and isinstance(item, text_input_type)
        is_label_container = bool(label_type) and isinstance(item, label_type)

        # discord.ui.Label uses ``text`` instead of the deprecated input label.
        if is_label_container:
            text = getattr(item, "text", None)
            if text:
                if not hasattr(item, "_abaddon_original_text"):
                    item._abaddon_original_text = str(text)
                item.text = translate_text(item._abaddon_original_text, locale, bot=bot)[:45]
            description = getattr(item, "description", None)
            if description:
                if not hasattr(item, "_abaddon_original_description"):
                    item._abaddon_original_description = str(description)
                item.description = translate_text(item._abaddon_original_description, locale, bot=bot)[:100]
            component = getattr(item, "component", None)
            if component is not None:
                translate_component(component)
            return

        # Buttons and selects still use label. TextInput.label is deliberately
        # skipped because it is deprecated and already localized at creation.
        if not is_text_input:
            label = getattr(item, "label", None)
            if label:
                if not hasattr(item, "_abaddon_original_label"):
                    item._abaddon_original_label = str(label)
                item.label = translate_text(item._abaddon_original_label, locale, bot=bot)[:80]

        placeholder = getattr(item, "placeholder", None)
        if placeholder:
            if not hasattr(item, "_abaddon_original_placeholder"):
                item._abaddon_original_placeholder = str(placeholder)
            item.placeholder = translate_text(item._abaddon_original_placeholder, locale, bot=bot)[:150]

        options = getattr(item, "options", None)
        if options:
            for option in options:
                option_label = getattr(option, "label", None)
                if option_label:
                    if not hasattr(option, "_abaddon_original_label"):
                        option._abaddon_original_label = str(option_label)
                    option.label = translate_text(option._abaddon_original_label, locale, bot=bot)[:100]
                option_description = getattr(option, "description", None)
                if option_description:
                    if not hasattr(option, "_abaddon_original_description"):
                        option._abaddon_original_description = str(option_description)
                    option.description = translate_text(option._abaddon_original_description, locale, bot=bot)[:100]

    try:
        for child in getattr(view, "children", []):
            translate_component(child)
    except Exception:
        return view
    return view


V1091_DEPRECATION_SAFE_LOCALIZER = True


def _translate_modal(modal: Any, locale: str, bot: Optional[commands.Bot]) -> Any:
    if modal is None:
        return modal
    try:
        if getattr(modal, "title", None):
            if not hasattr(modal, "_abaddon_original_title"):
                modal._abaddon_original_title = str(modal.title)
            modal.title = translate_text(modal._abaddon_original_title, locale, bot=bot)[:45]
        _translate_view(modal, locale, bot)
    except Exception:
        pass
    return modal


def _locale_from_context(ctx: Any) -> str:
    root = _RUNTIME.get("root", {})
    author = getattr(ctx, "author", None)
    guild = getattr(ctx, "guild", None)
    return _user_locale(root, getattr(author, "id", 0), getattr(guild, "id", 0))


def _locale_from_interaction(interaction: Any) -> str:
    root = _RUNTIME.get("root", {})
    user = getattr(interaction, "user", None)
    guild = getattr(interaction, "guild", None)
    return _user_locale(root, getattr(user, "id", 0), getattr(guild, "id", 0))


def _locale_from_messageable(obj: Any) -> str:
    root = _RUNTIME.get("root", {})
    guild = getattr(obj, "guild", None)
    return _guild_locale(root, getattr(guild, "id", 0))


def _localize_send_args(args: Tuple[Any, ...], kwargs: Dict[str, Any], locale: str, bot: Optional[commands.Bot]) -> Tuple[Tuple[Any, ...], Dict[str, Any]]:
    args = list(args)
    if args and isinstance(args[0], str):
        args[0] = translate_text(args[0], locale, bot=bot)
    if isinstance(kwargs.get("content"), str):
        kwargs["content"] = translate_text(kwargs["content"], locale, bot=bot)
    if kwargs.get("embed") is not None:
        kwargs["embed"] = _translate_embed(kwargs["embed"], locale, bot)
    if kwargs.get("embeds"):
        kwargs["embeds"] = [_translate_embed(x, locale, bot) for x in kwargs["embeds"]]
    if kwargs.get("view") is not None:
        kwargs["view"] = _translate_view(kwargs["view"], locale, bot)
    return tuple(args), kwargs


def install_localization_runtime(bot: commands.Bot, root: MutableMapping[str, Any]) -> None:
    global _PATCHED
    _RUNTIME["bot"] = bot
    _RUNTIME["root"] = root
    if _PATCHED:
        return
    _PATCHED = True

    # Prefix/hybrid command output: personal locale.
    original_context_send = commands.Context.send

    @functools.wraps(original_context_send)
    async def context_send(self: commands.Context, *args: Any, **kwargs: Any) -> Any:
        locale = _locale_from_context(self)
        localized_args, localized_kwargs = _localize_send_args(tuple(args), dict(kwargs), locale, _RUNTIME.get("bot"))
        message = await original_context_send(self, *localized_args, **localized_kwargs)
        try:
            setattr(message, "_abaddon_locale", locale)
        except Exception:
            pass
        return message

    commands.Context.send = context_send  # type: ignore[assignment]

    # Interaction replies: personal locale.
    response_cls = getattr(discord, "InteractionResponse", None)
    if response_cls is not None:
        original_response_send = response_cls.send_message

        @functools.wraps(original_response_send)
        async def response_send(self: Any, *args: Any, **kwargs: Any) -> Any:
            locale = _locale_from_interaction(getattr(self, "_parent", None))
            localized_args, localized_kwargs = _localize_send_args(tuple(args), dict(kwargs), locale, _RUNTIME.get("bot"))
            return await original_response_send(self, *localized_args, **localized_kwargs)

        response_cls.send_message = response_send

        if hasattr(response_cls, "edit_message"):
            original_response_edit = response_cls.edit_message

            @functools.wraps(original_response_edit)
            async def response_edit(self: Any, *args: Any, **kwargs: Any) -> Any:
                locale = _locale_from_interaction(getattr(self, "_parent", None))
                localized_args, localized_kwargs = _localize_send_args(tuple(args), dict(kwargs), locale, _RUNTIME.get("bot"))
                return await original_response_edit(self, *localized_args, **localized_kwargs)

            response_cls.edit_message = response_edit

        if hasattr(response_cls, "send_modal"):
            original_send_modal = response_cls.send_modal

            @functools.wraps(original_send_modal)
            async def send_modal(self: Any, modal: Any, *args: Any, **kwargs: Any) -> Any:
                locale = _locale_from_interaction(getattr(self, "_parent", None))
                return await original_send_modal(self, _translate_modal(modal, locale, _RUNTIME.get("bot")), *args, **kwargs)

            response_cls.send_modal = send_modal

    # Follow-up webhook output: personal locale where the interaction is available.
    webhook_cls = getattr(discord, "Webhook", None)
    if webhook_cls is not None and hasattr(webhook_cls, "send"):
        original_webhook_send = webhook_cls.send

        @functools.wraps(original_webhook_send)
        async def webhook_send(self: Any, *args: Any, **kwargs: Any) -> Any:
            interaction = getattr(self, "_state", None)
            parent = getattr(interaction, "_interaction", None)
            locale = _locale_from_interaction(parent) if parent is not None else "ko"
            localized_args, localized_kwargs = _localize_send_args(tuple(args), dict(kwargs), locale, _RUNTIME.get("bot"))
            message = await original_webhook_send(self, *localized_args, **localized_kwargs)
            try:
                setattr(message, "_abaddon_locale", locale)
            except Exception:
                pass
            return message

        webhook_cls.send = webhook_send

    # Public automatic channel messages use the server language.
    messageable_cls = getattr(getattr(discord, "abc", None), "Messageable", None)
    if messageable_cls is not None and hasattr(messageable_cls, "send"):
        original_messageable_send = messageable_cls.send

        @functools.wraps(original_messageable_send)
        async def messageable_send(self: Any, *args: Any, **kwargs: Any) -> Any:
            locale = _locale_from_messageable(self)
            localized_args, localized_kwargs = _localize_send_args(tuple(args), dict(kwargs), locale, _RUNTIME.get("bot"))
            message = await original_messageable_send(self, *localized_args, **localized_kwargs)
            try:
                setattr(message, "_abaddon_locale", locale)
            except Exception:
                pass
            return message

        messageable_cls.send = messageable_send

    # Message edits are used by progress animations and persistent panels.
    message_cls = getattr(discord, "Message", None)
    if message_cls is not None and hasattr(message_cls, "edit"):
        original_message_edit = message_cls.edit

        @functools.wraps(original_message_edit)
        async def message_edit(self: Any, *args: Any, **kwargs: Any) -> Any:
            channel = getattr(self, "channel", None)
            locale = getattr(self, "_abaddon_locale", None) or _locale_from_messageable(channel)
            localized_args, localized_kwargs = _localize_send_args(tuple(args), dict(kwargs), locale, _RUNTIME.get("bot"))
            return await original_message_edit(self, *localized_args, **localized_kwargs)

        message_cls.edit = message_edit


# ---------------------------------------------------------------------------
# Progress animation helpers
# ---------------------------------------------------------------------------
def _bar(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, float(percent)))
    filled = int(round(width * percent / 100.0))
    return "▰" * filled + "▱" * (width - filled)


def _route_frame(index: int, total: int = 5) -> str:
    cells = ["▫️"] * total
    cells[0] = "🏠"
    cells[-1] = "🎯"
    pos = max(1, min(total - 2, index))
    cells[pos] = "🚶" if index % 2 else "🏃"
    return "━".join(cells) + " 💨"


async def animate_progress(
    target: Any,
    *,
    locale: str,
    start_percent: float = 0.0,
    end_percent: float = 100.0,
    title: Optional[str] = None,
    final_note: str = "",
    steps: int = 5,
    delay: float = 0.32,
) -> Optional[Any]:
    title = title or L(locale, "expedition_title")
    labels = [
        L(locale, "progress_depart"), L(locale, "progress_move"), L(locale, "progress_scan"),
        L(locale, "progress_action"), L(locale, "progress_return"), L(locale, "progress_done"),
    ]
    message = None
    for idx in range(max(2, steps)):
        ratio = idx / max(1, steps - 1)
        percent = start_percent + (end_percent - start_percent) * ratio
        label = labels[min(len(labels) - 1, int(ratio * (len(labels) - 1)))]
        route = _route_frame(min(3, 1 + int(ratio * 3)))
        content = (
            f"**{title}**\n"
            f"{route}\n"
            f"{label}  `{_bar(percent)}` **{percent:5.1f}%**"
        )
        if idx == steps - 1 and final_note:
            content += "\n" + final_note
        try:
            if message is None:
                message = await target.send(content)
                try:
                    setattr(message, "_abaddon_locale", locale)
                except Exception:
                    pass
            else:
                await message.edit(content=content)
        except (discord.HTTPException, discord.Forbidden, discord.NotFound, AttributeError):
            if idx == steps - 1:
                try:
                    await target.send(content)
                except Exception:
                    pass
            break
        if idx < steps - 1:
            await asyncio.sleep(delay)
    return message


# ---------------------------------------------------------------------------
# v10 data and content
# ---------------------------------------------------------------------------
NPC_RELATIONSHIPS: Mapping[str, Mapping[str, Tuple[str, str]]] = {
    "rescue_captain": {"ko": ("구조대장 민재", "🚑"), "en": ("Captain Min-jae", "🚑")},
    "field_medic": {"ko": ("야전 의무관 세린", "⚕️"), "en": ("Field Medic Serin", "⚕️")},
    "rail_engineer": {"ko": ("철도 기술자 도윤", "🧰"), "en": ("Rail Engineer Do-yun", "🧰")},
    "recon_leader": {"ko": ("정찰대장 이라", "🧭"), "en": ("Recon Leader Ira", "🧭")},
    "militia_guard": {"ko": ("민병대 수문장 하진", "🛡️"), "en": ("Militia Warden Ha-jin", "🛡️")},
    "convoy_master": {"ko": ("호송대장 로안", "🚚"), "en": ("Convoy Master Roan", "🚚")},
}

ROLE_NAMES: Mapping[str, Mapping[str, str]] = {
    "scout": {"ko": "정찰", "en": "Scout"},
    "medic": {"ko": "의무", "en": "Medic"},
    "engineer": {"ko": "기술", "en": "Engineer"},
    "guard": {"ko": "경계", "en": "Guard"},
}

ACTION_NAMES: Mapping[str, Mapping[str, str]] = {
    "scan": {"ko": "신호분석", "en": "Signal Analysis"},
    "rescue": {"ko": "구조", "en": "Rescue"},
    "repair": {"ko": "복구", "en": "Repair"},
    "secure": {"ko": "확보", "en": "Secure"},
}

EXPEDITION_TEMPLATES: Mapping[str, Mapping[str, Any]] = {
    "ghost_line": {
        "emoji": "🚇", "target": 2400, "npc": "rail_engineer",
        "ko": ("유령 노선 04", "지도에서 사라진 열차의 구조 신호와 봉인 객차를 조사합니다."),
        "en": ("Ghost Line 04", "Investigate a missing train, its distress signal, and a sealed carriage."),
    },
    "red_fog": {
        "emoji": "🌫️", "target": 2600, "npc": "recon_leader",
        "ko": ("적색 안개 관측망", "협곡을 뒤덮은 안개 속 송신기를 연결하고 실종 정찰대를 찾습니다."),
        "en": ("Red Fog Observation Net", "Reconnect transmitters in the canyon and locate the missing recon team."),
    },
    "white_hospital": {
        "emoji": "🏥", "target": 2250, "npc": "field_medic",
        "ko": ("백색 야전병원", "고립된 야전병원에 의료품을 전달하고 감염 구역을 안정화합니다."),
        "en": ("White Field Hospital", "Deliver medical supplies and stabilize the infection zone around an isolated hospital."),
    },
    "broken_convoy": {
        "emoji": "🚚", "target": 2500, "npc": "convoy_master",
        "ko": ("부서진 호송대", "약탈단의 추적을 피하며 생존자와 보급 차량을 종착지까지 호위합니다."),
        "en": ("Broken Convoy", "Escort survivors and supply vehicles to the terminal while evading raiders."),
    },
    "sunken_archive": {
        "emoji": "🗄️", "target": 2700, "npc": "rescue_captain",
        "ko": ("침수 기록 보관소", "수몰된 보관소에서 대피 명단과 세계 상태 기록을 회수합니다."),
        "en": ("Sunken Archive", "Recover evacuation lists and world-state records from a flooded archive."),
    },
    "last_wall": {
        "emoji": "🧱", "target": 2850, "npc": "militia_guard",
        "ko": ("마지막 방벽", "서버 공동 방벽을 보강하고 야간 감염체 공세를 막아냅니다."),
        "en": ("The Last Wall", "Reinforce the shared wall and repel the infected assault before nightfall."),
    },
}


def _stable_template(guild_id: Any, week: str) -> str:
    keys = tuple(EXPEDITION_TEMPLATES)
    digest = hashlib.sha256(f"v1000:{guild_id}:{week}".encode()).digest()
    return keys[int.from_bytes(digest[:4], "big") % len(keys)]


def _profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = user.setdefault("global_v1000", {})
    if not isinstance(profile, dict):
        profile = {}
        user["global_v1000"] = profile
    profile.setdefault("relationships", {})
    profile.setdefault("codex", [])
    profile.setdefault("expedition_claims", [])
    profile.setdefault("notifications", [])
    profile.setdefault("last_seen_version", "9.5.0")
    profile.setdefault("stats", {"expedition_actions": 0, "relationships": 0})
    return profile


def _guild_state(root: MutableMapping[str, Any], guild_id: Any) -> MutableMapping[str, Any]:
    guilds = root.setdefault("guilds", {})
    row = guilds.setdefault(str(guild_id), {})
    row.setdefault("locale", "ko")
    row.setdefault("expedition_history", [])
    week = _week_key()
    expedition = row.get("expedition")
    if not isinstance(expedition, dict) or expedition.get("week") != week:
        if isinstance(expedition, dict) and expedition.get("id"):
            ids = {str(x.get("id")) for x in row["expedition_history"] if isinstance(x, dict)}
            if str(expedition.get("id")) not in ids:
                snapshot = copy.deepcopy(expedition)
                snapshot.setdefault("archived_at", _now_iso())
                row["expedition_history"].insert(0, snapshot)
        key = _stable_template(guild_id, week)
        info = EXPEDITION_TEMPLATES[key]
        row["expedition"] = {
            "id": f"GEX-{week}-{str(guild_id)[-4:]}", "week": week, "key": key,
            "progress": 0, "target": int(info["target"]), "status": "active",
            "members": {}, "contributions": {}, "actions": [], "settled": False,
            "created_at": _now_iso(),
        }
    return row


def _is_admin(member: Any) -> bool:
    return bool(
        getattr(getattr(member, "guild_permissions", None), "administrator", False)
        or getattr(member, "id", None) in set(getattr(_RUNTIME.get("bot"), "owner_ids", set()) or set())
        or getattr(member, "id", None) == getattr(_RUNTIME.get("bot"), "owner_id", None)
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _give(user: MutableMapping[str, Any], key: str, amount: int) -> None:
    amount = max(0, int(amount))
    if key == "식량":
        user["balance"] = _safe_int(user.get("balance"), 0) + amount
        stats = user.setdefault("stats", {})
        stats["earned"] = _safe_int(stats.get("earned"), 0) + amount
        return
    materials = user.setdefault("materials", {})
    materials[key] = _safe_int(materials.get(key), 0) + amount


def _relationship_level(score: int, locale: str) -> str:
    thresholds = [
        (-10**9, "⚠️ 경계", "⚠️ Wary"), (0, "▫️ 낯섦", "▫️ Unfamiliar"),
        (20, "🕊️ 중립", "🕊️ Neutral"), (50, "🤝 신뢰", "🤝 Trusted"),
        (90, "💠 동료", "💠 Companion"), (140, "🌟 생존의 인연", "🌟 Bond of Survival"),
    ]
    value = thresholds[0][1 if locale == "ko" else 2]
    for threshold, ko, en in thresholds:
        if score >= threshold:
            value = ko if locale == "ko" else en
    return value


def _add_notification(user: MutableMapping[str, Any], ko: str, en: str) -> None:
    profile = _profile(user)
    rows = profile.setdefault("notifications", [])
    rows.insert(0, {"id": secrets.token_hex(4), "ko": ko, "en": en, "at": _now_iso(), "read": False})
    del rows[50:]


def _unclaimed_summary(world_data: Mapping[str, Any], root: MutableMapping[str, Any], user: Mapping[str, Any], guild_id: Any, user_id: Any) -> List[Tuple[str, str, str]]:
    uid = str(user_id)
    rows: List[Tuple[str, str, str]] = []
    profile = user.get("global_v1000", {}) if isinstance(user, dict) else {}
    claims = set(profile.get("expedition_claims", [])) if isinstance(profile, dict) else set()
    state = _guild_state(root, guild_id)
    candidates = []
    current = state.get("expedition")
    if isinstance(current, dict):
        candidates.append(current)
    candidates.extend(x for x in state.get("expedition_history", []) if isinstance(x, dict))
    for expedition in candidates:
        claim_id = f"{expedition.get('id')}:{uid}"
        if expedition.get("settled") and _safe_int(expedition.get("contributions", {}).get(uid), 0) > 0 and claim_id not in claims:
            rows.append(("expedition", "주간 글로벌 탐사", "Weekly Global Expedition"))
            break

    v950 = world_data.get("v950_investigation", {}) if isinstance(world_data, dict) else {}
    guilds = v950.get("guilds", {}) if isinstance(v950, dict) else {}
    vstate = guilds.get(str(guild_id), {}) if isinstance(guilds, dict) else {}
    vprofile = user.get("investigation_v950", {}) if isinstance(user, dict) else {}
    bounty_claims = set(vprofile.get("bounty_claims", [])) if isinstance(vprofile, dict) else set()
    raid_claims = set(vprofile.get("raid_claims", [])) if isinstance(vprofile, dict) else set()
    for bounty in [vstate.get("bounty"), *vstate.get("bounty_history", [])] if isinstance(vstate, dict) else []:
        if isinstance(bounty, dict):
            cid = f"{bounty.get('id')}:{uid}"
            if bounty.get("resolved") and _safe_int(bounty.get("contributors", {}).get(uid), 0) > 0 and cid not in bounty_claims:
                rows.append(("bounty", "현상금 보고", "Bounty Report"))
                break
    for raid in [vstate.get("raid"), *vstate.get("raid_history", [])] if isinstance(vstate, dict) else []:
        if isinstance(raid, dict):
            cid = f"{raid.get('id')}:{uid}"
            if raid.get("settled") and _safe_int(raid.get("contributions", {}).get(uid), 0) > 0 and cid not in raid_claims:
                rows.append(("investigation_raid", "수사 레이드 보상", "Investigation Raid Reward"))
                break
    return rows


# ---------------------------------------------------------------------------
# Language choice view
# ---------------------------------------------------------------------------
class LanguageChoiceView(discord.ui.View):
    def __init__(self, owner_id: int, root: MutableMapping[str, Any], save_data: Callable[[], Any]):
        super().__init__(timeout=300)
        self.owner_id = int(owner_id)
        self.root = root
        self.save_data = save_data
        self._abaddon_no_localize = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(getattr(interaction.user, "id", 0)) != self.owner_id:
            await interaction.response.send_message("This language selector belongs to another user.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="한국어", emoji="🇰🇷", style=discord.ButtonStyle.primary, custom_id="abaddon:v1000:lang:ko")
    async def korean(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        _set_user_locale(self.root, interaction.user.id, "ko")
        self.save_data()
        await interaction.response.edit_message(content=L("ko", "language_saved"), view=None)

    @discord.ui.button(label="English", emoji="🇺🇸", style=discord.ButtonStyle.success, custom_id="abaddon:v1000:lang:en")
    async def english(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        _set_user_locale(self.root, interaction.user.id, "en")
        self.save_data()
        await interaction.response.edit_message(content=L("en", "language_saved"), view=None)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_v1000_global_survivor(
    bot: commands.Bot,
    get_user: Callable[[Any], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    command_guide_categories: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], Any],
    add_title: Callable[..., Any],
    add_season_points: Callable[..., Any],
) -> None:
    del calculate_user_power, add_title
    if getattr(bot, "_abaddon_v1000_registered", False):
        return
    root = _root(world_data)
    install_localization_runtime(bot, root)

    async def require_user(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        user = get_user(ctx.author.id)
        if user is None:
            await ctx.send(L(_locale_from_context(ctx), "registered_only"))
            return None
        return user

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            await ctx.send(L(_locale_from_context(ctx), "guild_only"))
            return False
        if not _is_admin(ctx.author):
            await ctx.send(L(_locale_from_context(ctx), "admin_only"))
            return False
        return True

    async def language_gate(ctx: commands.Context) -> bool:
        command_name = str(getattr(getattr(ctx, "command", None), "name", ""))
        allowed = {
            "언어", "language", "lang", "서버언어", "serverlanguage", "serverlang",
            "1000안정화검수", "v1000audit", "다국어검수", "languageaudit",
        }
        if command_name in allowed:
            return True
        row = root.get("users", {}).get(str(ctx.author.id), {})
        if isinstance(row, dict) and row.get("locale") in {"ko", "en"}:
            return True
        # The only intentionally bilingual game message.
        view = LanguageChoiceView(ctx.author.id, root, save_data)
        await ctx.send(
            "🌐 **언어 선택 / Language Selection**\n"
            "게임 화면에 사용할 언어를 선택해 주세요.\n"
            "Choose the language used by the game interface.",
            view=view,
        )
        raise commands.CheckFailure(LANGUAGE_CHECK_SENTINEL)

    bot.add_check(language_gate)
    bot.v1000_language_gate = language_gate

    @bot.command(name="언어", aliases=["language", "lang"], help="개인 게임 화면의 표시 언어를 한국어 또는 영어로 설정합니다.")
    async def language_command(ctx: commands.Context, 선택: str = "") -> None:
        token = str(선택 or "").strip().casefold()
        if token in {"한국어", "한글", "ko", "kor", "korean"}:
            _set_user_locale(root, ctx.author.id, "ko")
            save_data()
            await ctx.send(L("ko", "language_saved"))
            return
        if token in {"영어", "en", "eng", "english"}:
            _set_user_locale(root, ctx.author.id, "en")
            save_data()
            await ctx.send(L("en", "language_saved"))
            return
        locale = _user_locale(root, ctx.author.id, getattr(ctx.guild, "id", 0))
        view = LanguageChoiceView(ctx.author.id, root, save_data)
        await ctx.send(L(locale, "language_current") + "\n\n" + L(locale, "language_prompt"), view=view)

    @bot.command(name="서버언어", aliases=["serverlanguage", "serverlang"], help="공개 공동 패널과 자동 방송의 서버 기본 언어를 설정합니다.")
    async def server_language(ctx: commands.Context, 선택: str = "") -> None:
        if not await require_admin(ctx):
            return
        token = str(선택 or "").strip().casefold()
        locale = "en" if token in {"영어", "en", "eng", "english"} else "ko" if token in {"한국어", "한글", "ko", "kor", "korean"} else ""
        if not locale:
            current = _guild_locale(root, ctx.guild.id)
            usage = "사용법: `!서버언어 한국어` 또는 `!서버언어 영어`" if current == "ko" else "Usage: `!serverlanguage korean` or `!serverlanguage english`"
            await ctx.send(f"🌐 **{'한국어' if current == 'ko' else 'English'}**\n{usage}")
            return
        _set_guild_locale(root, ctx.guild.id, locale)
        save_data()
        await ctx.send(L(locale, "server_language_saved"))

    @bot.command(name="할일", aliases=["tasks", "missiontracker", "임무추적", "trackmission"], help="현재 진행 중인 콘텐츠와 미수령 보상을 추적합니다.")
    async def task_tracker(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        locale = _locale_from_context(ctx)
        state = _guild_state(root, ctx.guild.id)
        expedition = state["expedition"]
        progress = 100 * _safe_int(expedition.get("progress")) / max(1, _safe_int(expedition.get("target"), 1))
        unclaimed = _unclaimed_summary(world_data, root, user, ctx.guild.id, ctx.author.id)
        v950 = world_data.get("v950_investigation", {}).get("guilds", {}).get(str(ctx.guild.id), {})
        case = v950.get("case", {}) if isinstance(v950, dict) else {}
        bounty = v950.get("bounty", {}) if isinstance(v950, dict) else {}
        lines = []
        if locale == "ko":
            lines.extend([
                f"🛰️ 탐사 작전 `{_bar(progress)}` **{progress:.1f}%**",
                f"🔎 주간 사건: {'해결 완료' if case.get('solved') else '수사 진행 중'}",
                f"🎯 현상금: {_safe_int(bounty.get('progress')):,}/{_safe_int(bounty.get('target')):,}",
                f"🎁 미수령 보상: **{len(unclaimed)}건**",
                "🧭 추천 순서: 탐사 행동 → 사건 조사 → 현상금 추적 → 보상 회수",
            ])
        else:
            lines.extend([
                f"🛰️ Expedition `{_bar(progress)}` **{progress:.1f}%**",
                f"🔎 Weekly case: {'Solved' if case.get('solved') else 'Investigation active'}",
                f"🎯 Bounty: {_safe_int(bounty.get('progress')):,}/{_safe_int(bounty.get('target')):,}",
                f"🎁 Unclaimed rewards: **{len(unclaimed)}**",
                "🧭 Suggested route: expedition action → case investigation → bounty tracking → reward center",
            ])
        embed = discord.Embed(title=L(locale, "tasks_title"), description=L(locale, "tasks_desc") + "\n\n" + "\n".join(lines), colour=0x3498DB)
        embed.set_footer(text=L(locale, "help_footer"))
        await ctx.send(embed=embed)

    @bot.command(name="생존도감", aliases=["survivalcodex", "codex"], help="지역·세력·인카운트·사건·트로피를 통합한 생존 도감을 엽니다.")
    async def survival_codex(ctx: commands.Context, 분류: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        locale = _locale_from_context(ctx)
        token = str(분류 or "").strip().casefold()
        groups = {
            "regions": ("🗺️ 지역", "🗺️ Regions", ["대피소 외곽", "침수 철도", "잿빛 수림", "적색 안개 협곡", "원자로 묘지", "황혼 종착지"]),
            "factions": ("🤝 세력", "🤝 Factions", [x[locale][0] for x in NPC_RELATIONSHIPS.values()]),
            "encounters": ("🎭 인카운트", "🎭 Encounters", ["구조 신호", "우호 정찰대", "오작동 드론", "환경 붕괴", "봉인 보관실", "공정 상인"]),
            "cases": ("🔎 사건·현상금", "🔎 Cases & Bounties", ["주간 사건 수사", "현상금 추적", "협동 수사 레이드", "주간 글로벌 탐사"]),
        }
        aliases = {"지역": "regions", "region": "regions", "regions": "regions", "세력": "factions", "faction": "factions", "인카운트": "encounters", "encounter": "encounters", "사건": "cases", "case": "cases"}
        selected = aliases.get(token, token) if token else ""
        embed = discord.Embed(title=L(locale, "codex_title"), colour=0x9B59B6)
        for key, (ko_title, en_title, values) in groups.items():
            if selected and selected != key:
                continue
            title = ko_title if locale == "ko" else en_title
            rendered = []
            for value in values:
                rendered.append("• " + (translate_text(value, locale, bot=bot) if locale == "en" else str(value)))
            embed.add_field(name=title, value="\n".join(rendered), inline=False)
        embed.set_footer(text=("분류: 지역 · 세력 · 인카운트 · 사건" if locale == "ko" else "Categories: regions · factions · encounters · cases"))
        await ctx.send(embed=embed)

    @bot.command(name="아이템도감", aliases=["itemcodex"], help="주요 재료·장비·수집품 도감을 확인합니다.")
    async def item_codex(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        locale = _locale_from_context(ctx)
        inventory = user.get("inventory", {}) if isinstance(user.get("inventory"), dict) else {}
        materials = user.get("materials", {}) if isinstance(user.get("materials"), dict) else {}
        owned = list(inventory)[:15] + list(materials)[:15]
        if not owned:
            owned = ["식량", "고철", "나무", "약초", "보물파편"]
        title = "🎒 아이템 도감" if locale == "ko" else "🎒 Item Codex"
        lines = [f"• {translate_text(str(name), locale, bot=bot)}" for name in owned[:25]]
        await ctx.send(embed=discord.Embed(title=title, description="\n".join(lines), colour=0xF1C40F))

    @bot.command(name="인물도감", aliases=["charactercodex", "npccodex"], help="만날 수 있는 주요 우호 인물과 관계 단계를 확인합니다.")
    async def character_codex(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        locale = _locale_from_context(ctx)
        rel = _profile(user)["relationships"]
        lines = []
        for key, info in NPC_RELATIONSHIPS.items():
            name, emoji = info[locale]
            score = _safe_int(rel.get(key), 0)
            lines.append(f"{emoji} **{name}** · {_relationship_level(score, locale)} · {score:+d}")
        await ctx.send(embed=discord.Embed(title=("👥 인물 도감" if locale == "ko" else "👥 Character Codex"), description="\n".join(lines), colour=0x1ABC9C))

    @bot.command(name="지역도감", aliases=["regioncodex"], help="서버 공동 탐험 지역과 현재 상태를 확인합니다.")
    async def region_codex(ctx: commands.Context) -> None:
        locale = _locale_from_context(ctx)
        regions = [
            ("🏚️", "대피소 외곽", "Shelter Outskirts"), ("🌊", "침수 철도", "Flooded Railway"),
            ("🌲", "잿빛 수림", "Ashen Forest"), ("🌫️", "적색 안개 협곡", "Red Fog Canyon"),
            ("☢️", "원자로 묘지", "Reactor Graveyard"), ("🚂", "황혼 종착지", "Twilight Terminus"),
        ]
        lines = [f"{emoji} **{ko if locale == 'ko' else en}**" for emoji, ko, en in regions]
        await ctx.send(embed=discord.Embed(title=("🗺️ 지역 도감" if locale == "ko" else "🗺️ Region Codex"), description="\n".join(lines), colour=0x2ECC71))

    @bot.command(name="시작안내", aliases=["gettingstarted", "startguide"], help="신규 생존자의 첫 플레이 순서를 안내합니다.")
    async def getting_started(ctx: commands.Context) -> None:
        locale = _locale_from_context(ctx)
        if locale == "ko":
            lines = [
                "1. `!가입 생존자` — 생존자 등록",
                "2. `!처음` 또는 `!초보센터` — 버튼형 첫걸음 안내",
                "3. `!정보` · `!오늘할일` — 현재 상태와 오늘 할 일 확인",
                "4. `!직업목록` → `!직업선택 직업명` — 직업 결정",
                "5. `!채집` / `!벌목` / `!광산` / `!낚시` — 첫 자원 확보",
                "6. `!장비` · `!제작목록` · `!강화` — 장비 성장",
                "7. `!스토리` / `!솔로원정` / `!던전 보통` — 본격 생존 진행",
                "8. 전체 기능은 `!명령어`에서 검색",
            ]
        else:
            lines = [
                "1. `!register survivor` — register a survivor",
                "2. `!help` / `!commands` — open the current command center",
                "3. `!profile` · `!tasks` — check status and current objectives",
                "4. Choose a job from the job/category interface",
                "5. Gather resources, craft gear, then enter story/expedition/combat content",
            ]
        embed = discord.Embed(title=L(locale, "getting_started_title"), description="\n".join(lines), colour=0x2ECC71)
        embed.set_footer(text="ABADDON v18.2.2 · 현재 명령 센터 기준")
        await ctx.send(embed=embed)

    @bot.command(name="복귀안내", aliases=["returningguide", "returnguide"], help="마지막 확인 버전 이후 추가된 주요 기능을 안내합니다.")
    async def returning_guide(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        locale = _locale_from_context(ctx)
        profile = _profile(user)
        previous = str(profile.get("last_seen_version", "9.5.0"))
        profile["last_seen_version"] = "18.2.2"
        save_data()
        if locale == "ko":
            lines = [
                f"마지막 확인 버전: **v{previous}**",
                "🌘 FINAL ECLIPSE · 시즌/결말/일일 루프",
                "🏛️ 연대기 박물관 · 통합 업적/칭호 · 커뮤니티 시즌",
                "🤝 살아있는 세계 · 최신 NPC 인연/배신/관계 시스템",
                "🧭 솔로 원정 · 연결형 생존 루프 · 도시/생산/탐험 허브",
                "🎰 카지노와 일반 도박 분리 · 최신 도박 안내 `!도박정보`",
                "🧩 3단계 `!명령어` 센터 · 버튼/드롭다운 기반 탐색",
                "📋 오늘은 `!오늘할일` 또는 `!생존허브`부터 확인하세요.",
            ]
        else:
            lines = [
                f"Last reviewed version: **v{previous}**",
                "🌘 Final Eclipse and the current daily/endgame loop",
                "🏛️ Chronicle Museum, achievements, titles and community season",
                "🤝 Living-world NPC bonds and relationship systems",
                "🧭 Solo expedition, production, city and connected survival hubs",
                "🎰 Casino and non-casino gambling are separated",
                "🧩 Current 3-stage command center and contextual controls",
            ]
        embed = discord.Embed(title=L(locale, "returning_title"), description="\n".join(lines), colour=0xE67E22)
        embed.set_footer(text="ABADDON v18.2.2 · 현재 주요 기능 기준")
        await ctx.send(embed=embed)

    @bot.command(name="인연기록구버전", aliases=["legacyrelationships", "legacybonds"], hidden=True, help="[레거시] v10.0 NPC 개인 관계 기록을 확인합니다. 최신 인연 시스템은 !인연을 사용하세요.")
    async def relationships(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        locale = _locale_from_context(ctx)
        rel = _profile(user)["relationships"]
        lines = []
        for key, info in NPC_RELATIONSHIPS.items():
            name, emoji = info[locale]
            score = _safe_int(rel.get(key), 0)
            lines.append(f"{emoji} **{name}** · {_relationship_level(score, locale)} · `{score:+d}`")
        await ctx.send(embed=discord.Embed(title=L(locale, "relationships_title"), description="\n".join(lines), colour=0xE91E63))

    @bot.command(name="인물기록", aliases=["characterrecord", "npcrecord"], help="특정 NPC와 쌓은 관계와 기억을 확인합니다.")
    async def character_record(ctx: commands.Context, *, 인물: str = "") -> None:
        user = await require_user(ctx)
        if user is None:
            return
        locale = _locale_from_context(ctx)
        token = re.sub(r"\s+", "", str(인물).casefold())
        aliases: Dict[str, str] = {}
        for key, info in NPC_RELATIONSHIPS.items():
            aliases[key.casefold()] = key
            for loc in ("ko", "en"):
                aliases[re.sub(r"\s+", "", info[loc][0].casefold())] = key
        selected = aliases.get(token)
        if selected is None:
            usage = "`!인물기록 구조대장 민재`" if locale == "ko" else "`!characterrecord Captain Min-jae`"
            await ctx.send(("인물을 찾지 못했습니다. " if locale == "ko" else "Character not found. ") + usage)
            return
        name, emoji = NPC_RELATIONSHIPS[selected][locale]
        score = _safe_int(_profile(user)["relationships"].get(selected), 0)
        if locale == "ko":
            desc = f"{emoji} **{name}**\n관계 단계: {_relationship_level(score, locale)}\n관계 점수: **{score:+d}**\n탐사·구조·협상 선택을 통해 이 인물의 기억이 달라집니다."
        else:
            desc = f"{emoji} **{name}**\nRelationship: {_relationship_level(score, locale)}\nBond score: **{score:+d}**\nExpedition, rescue, and negotiation choices change this character's memory."
        await ctx.send(embed=discord.Embed(title=("📖 인물 기록" if locale == "ko" else "📖 Character Record"), description=desc, colour=0xE91E63))

    def expedition_info(guild_id: int, locale: str) -> Tuple[MutableMapping[str, Any], Mapping[str, Any], str, str]:
        state = _guild_state(root, guild_id)
        expedition = state["expedition"]
        info = EXPEDITION_TEMPLATES[str(expedition["key"])]
        name, summary = info[locale]
        return expedition, info, name, summary

    @bot.command(name="탐사작전", aliases=["expeditionoperation", "globalexpedition"], help="이번 주 서버 공동 글로벌 탐사 작전을 확인합니다.")
    async def expedition_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send(L(_locale_from_context(ctx), "guild_only"))
            return
        locale = _locale_from_context(ctx)
        expedition, info, name, summary = expedition_info(ctx.guild.id, locale)
        progress = 100 * _safe_int(expedition["progress"]) / max(1, _safe_int(expedition["target"], 1))
        role_counts = Counter(str(x) for x in expedition.get("members", {}).values())
        role_text = " · ".join(f"{ROLE_NAMES[key][locale]} {role_counts.get(key, 0)}" for key in ROLE_NAMES)
        status = "정산 완료" if expedition.get("settled") and locale == "ko" else "Settled" if expedition.get("settled") else "목표 완료" if expedition.get("status") == "completed" and locale == "ko" else "Objective Complete" if expedition.get("status") == "completed" else "진행 중" if locale == "ko" else "Active"
        embed = discord.Embed(title=f"{info['emoji']} {name}", description=summary, colour=0x5865F2)
        embed.add_field(name=L(locale, "progress_label"), value=f"`{_bar(progress)}` **{progress:.1f}%**\n{_safe_int(expedition['progress']):,}/{_safe_int(expedition['target']):,}", inline=False)
        embed.add_field(name=("상태" if locale == "ko" else "Status"), value=status, inline=True)
        embed.add_field(name=("참가자" if locale == "ko" else "Members"), value=f"{len(expedition.get('members', {}))}", inline=True)
        embed.add_field(name=("역할 편성" if locale == "ko" else "Role Formation"), value=role_text or ("참가자 없음" if locale == "ko" else "No members yet"), inline=False)
        embed.set_footer(text=("참가: !탐사참가 정찰 · 행동: !탐사행동 신호분석" if locale == "ko" else "Join: !joinexpedition scout · Action: !expeditionaction scan"))
        await ctx.send(embed=embed)

    @bot.command(name="탐사참가", aliases=["joinexpedition", "expeditionjoin"], help="정찰·의무·기술·경계 역할로 주간 탐사에 참가합니다.")
    async def expedition_join(ctx: commands.Context, 역할: str = "정찰") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        locale = _locale_from_context(ctx)
        token = re.sub(r"\s+", "", str(역할).casefold())
        aliases = {
            "정찰": "scout", "scout": "scout", "recon": "scout",
            "의무": "medic", "medic": "medic", "medical": "medic",
            "기술": "engineer", "engineer": "engineer", "tech": "engineer",
            "경계": "guard", "guard": "guard", "security": "guard",
        }
        role = aliases.get(token)
        if role is None:
            await ctx.send("역할: `정찰` · `의무` · `기술` · `경계`" if locale == "ko" else "Roles: `scout` · `medic` · `engineer` · `guard`")
            return
        state = _guild_state(root, ctx.guild.id)
        expedition = state["expedition"]
        uid = str(ctx.author.id)
        if uid in expedition["members"]:
            await ctx.send(L(locale, "expedition_already_joined"))
            return
        expedition["members"][uid] = role
        expedition["contributions"].setdefault(uid, 0)
        _profile(user)["relationships"].setdefault(str(EXPEDITION_TEMPLATES[expedition["key"]]["npc"]), 0)
        save_data()
        await ctx.send(L(locale, "expedition_joined", role=ROLE_NAMES[role][locale]))

    @bot.command(name="탐사행동", aliases=["expeditionaction", "globalexpeditionaction"], help="신호분석·구조·복구·확보 행동으로 공동 진행도를 올립니다.")
    async def expedition_action(ctx: commands.Context, 행동: str = "신호분석") -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        locale = _locale_from_context(ctx)
        token = re.sub(r"\s+", "", str(행동).casefold())
        aliases = {
            "신호분석": "scan", "분석": "scan", "scan": "scan", "analyze": "scan", "signalanalysis": "scan",
            "구조": "rescue", "rescue": "rescue", "save": "rescue",
            "복구": "repair", "수리": "repair", "repair": "repair", "restore": "repair",
            "확보": "secure", "경계": "secure", "secure": "secure", "guard": "secure",
        }
        action = aliases.get(token)
        if action is None:
            await ctx.send("행동: `신호분석` · `구조` · `복구` · `확보`" if locale == "ko" else "Actions: `scan` · `rescue` · `repair` · `secure`")
            return
        state = _guild_state(root, ctx.guild.id)
        expedition = state["expedition"]
        uid = str(ctx.author.id)
        if uid not in expedition["members"]:
            await ctx.send(L(locale, "expedition_not_joined"))
            return
        if expedition.get("status") != "active":
            await ctx.send(L(locale, "expedition_complete"))
            return
        role = str(expedition["members"][uid])
        role_match = {"scan": "scout", "rescue": "medic", "repair": "engineer", "secure": "guard"}
        level = _safe_int(user.get("level"), 1)
        base = 55 + min(90, level * 2) + secrets.randbelow(31)
        if role_match[action] == role:
            base += 25
        companion_bonus = 0
        companion_bond = 0
        companion_key = ""
        companion_hook = getattr(bot, "v1010_companion_bonus", None)
        if callable(companion_hook):
            try:
                companion_bonus, companion_bond, companion_key = companion_hook(user, action)
                base += max(0, int(companion_bonus))
            except Exception:
                companion_bonus, companion_bond, companion_key = 0, 0, ""
        before = _safe_int(expedition["progress"])
        actual = min(base, max(0, _safe_int(expedition["target"]) - before))
        expedition["progress"] = before + actual
        expedition["contributions"][uid] = _safe_int(expedition["contributions"].get(uid)) + actual
        expedition["actions"].append({"user": uid, "action": action, "gain": actual, "at": _now_iso()})
        del expedition["actions"][:-100]
        profile = _profile(user)
        profile["stats"]["expedition_actions"] = _safe_int(profile["stats"].get("expedition_actions")) + 1
        npc = str(EXPEDITION_TEMPLATES[expedition["key"]]["npc"])
        bond = 3 + (2 if role_match[action] == role else 0) + max(0, int(companion_bond))
        profile["relationships"][npc] = _safe_int(profile["relationships"].get(npc)) + bond
        profile["stats"]["relationships"] = max(_safe_int(profile["stats"].get("relationships")), profile["relationships"][npc])
        target = max(1, _safe_int(expedition["target"], 1))
        if expedition["progress"] >= target:
            expedition["status"] = "completed"
            expedition["completed_at"] = _now_iso()
        try:
            add_season_points(user, min(10, 2 + actual // 40))
        except Exception:
            pass
        save_data()
        start_percent = before / target * 100
        end_percent = expedition["progress"] / target * 100
        action_name = ACTION_NAMES[action][locale]
        companion_note = ""
        if companion_bonus and companion_key:
            try:
                companion_row = getattr(bot, "v1010_companions", {}).get(companion_key, {})
                companion_name = companion_row.get(locale, companion_key)
                companion_note = (f" · 동료 {companion_name} **+{companion_bonus}**" if locale == "ko" else f" · Companion {companion_name} **+{companion_bonus}**")
            except Exception:
                companion_note = ""
        note = (f"✅ {action_name} · 공동 진행도 **+{actual}** · 인연 **+{bond}**{companion_note}" if locale == "ko" else f"✅ {action_name} · Shared progress **+{actual}** · Bond **+{bond}**{companion_note}")
        await animate_progress(ctx, locale=locale, start_percent=start_percent, end_percent=end_percent, title=L(locale, "expedition_title"), final_note=note)
        if expedition.get("status") == "completed":
            await ctx.send(L(locale, "expedition_complete"))

    @bot.command(name="탐사정산", aliases=["settleexpedition", "expeditionsettle"], help="완료된 주간 글로벌 탐사 작전을 한 번만 정산합니다.")
    async def expedition_settle(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        locale = _locale_from_context(ctx)
        state = _guild_state(root, ctx.guild.id)
        expedition = state["expedition"]
        if expedition.get("status") != "completed":
            await ctx.send(L(locale, "expedition_not_ready"))
            return
        if expedition.get("settled"):
            await ctx.send("ℹ️ 이미 정산된 탐사 작전입니다." if locale == "ko" else "ℹ️ This expedition has already been settled.")
            return
        expedition["settled"] = True
        expedition["settled_at"] = _now_iso()
        state["expedition_history"].insert(0, copy.deepcopy(expedition))
        root["stats"]["expeditions"] = _safe_int(root["stats"].get("expeditions")) + 1
        save_data()
        await ctx.send(L(locale, "expedition_settled"))

    async def claim_expedition_reward(ctx: commands.Context, *, quiet: bool = False) -> bool:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return False
        locale = _locale_from_context(ctx)
        state = _guild_state(root, ctx.guild.id)
        profile = _profile(user)
        uid = str(ctx.author.id)
        candidates = []
        if isinstance(state.get("expedition"), dict):
            candidates.append(state["expedition"])
        candidates.extend(x for x in state.get("expedition_history", []) if isinstance(x, dict))
        expedition = next((x for x in candidates if x.get("settled") and _safe_int(x.get("contributions", {}).get(uid)) > 0 and f"{x.get('id')}:{uid}" not in profile["expedition_claims"]), None)
        if expedition is None:
            if not quiet:
                await ctx.send(L(locale, "expedition_no_reward"))
            return False
        contribution = _safe_int(expedition["contributions"].get(uid))
        food = min(90000, 18000 + contribution * 24)
        fragments = max(2, min(15, contribution // 220))
        bond = max(3, min(12, contribution // 180))
        _give(user, "식량", food)
        _give(user, "보물파편", fragments)
        npc = str(EXPEDITION_TEMPLATES[str(expedition["key"])]["npc"])
        profile["relationships"][npc] = _safe_int(profile["relationships"].get(npc)) + bond
        profile["expedition_claims"].append(f"{expedition['id']}:{uid}")
        root["stats"]["claims"] = _safe_int(root["stats"].get("claims")) + 1
        _add_notification(user, f"탐사 작전 보상 {food:,} 식량을 수령했습니다.", f"Claimed {food:,} Food from the global expedition.")
        save_data()
        if not quiet:
            await ctx.send(L(locale, "expedition_claimed", food=food, fragments=fragments, bond=bond))
        return True

    @bot.command(name="탐사보상", aliases=["claimexpedition", "expeditionreward"], help="정산된 글로벌 탐사 작전의 개인 기여 보상을 받습니다.")
    async def expedition_reward(ctx: commands.Context) -> None:
        await claim_expedition_reward(ctx)

    @bot.command(name="탐사기록", aliases=["expeditionhistory", "globalexpeditionhistory"], help="최근 서버 공동 글로벌 탐사 기록을 확인합니다.")
    async def expedition_history(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        locale = _locale_from_context(ctx)
        rows = _guild_state(root, ctx.guild.id).get("expedition_history", [])
        lines = []
        for row in rows[:15]:
            info = EXPEDITION_TEMPLATES.get(str(row.get("key")), {})
            name = info.get(locale, ("Unknown", ""))[0] if info else "Unknown"
            lines.append(f"• `{row.get('id')}` · {name} · {len(row.get('members', {}))} {'명' if locale == 'ko' else 'members'}")
        await ctx.send(("🗃️ **글로벌 탐사 기록**\n" if locale == "ko" else "🗃️ **Global Expedition History**\n") + ("\n".join(lines) if lines else ("완료 기록이 없습니다." if locale == "ko" else "There are no completed records.")))

    # v7.9 already owns !알림센터. Enhance that command instead of registering a duplicate.
    existing_notification_center = bot.get_command("알림센터")
    if existing_notification_center is not None and not getattr(existing_notification_center, "_abaddon_v1000_enhanced", False):
        original_notification_center = existing_notification_center.callback

        @functools.wraps(original_notification_center)
        async def enhanced_notification_center(*args: Any, **kwargs: Any) -> Any:
            result = await original_notification_center(*args, **kwargs)
            ctx = next((x for x in args if isinstance(x, commands.Context)), None)
            if ctx is None:
                return result
            user = get_user(ctx.author.id)
            if user is None:
                return result
            locale = _locale_from_context(ctx)
            notifications = _profile(user).get("notifications", [])
            lines = []
            for row in notifications[:12]:
                lines.append(f"• {row.get(locale, row.get('ko', ''))}")
                row["read"] = True
            if ctx.guild is not None:
                unclaimed = _unclaimed_summary(world_data, root, user, ctx.guild.id, ctx.author.id)
                if unclaimed:
                    lines.append("")
                    lines.append("🎁 " + ("미수령 보상" if locale == "ko" else "Unclaimed Rewards"))
                    for _key, ko_label, en_label in unclaimed[:8]:
                        lines.append(f"• {ko_label if locale == 'ko' else en_label}")
            save_data()
            await ctx.send(embed=discord.Embed(
                title=L(locale, "notifications_title"),
                description="\n".join(lines) if lines else L(locale, "no_notifications"),
                colour=0x5865F2,
            ))
            return result

        existing_notification_center.callback = enhanced_notification_center
        existing_notification_center._abaddon_v1000_enhanced = True

    @bot.command(name="미수령보상", aliases=["unclaimedrewards", "rewardqueue"], help="현재 감지 가능한 미수령 공동 콘텐츠 보상을 점검합니다.")
    async def unclaimed_rewards(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        locale = _locale_from_context(ctx)
        rows = _unclaimed_summary(world_data, root, user, ctx.guild.id, ctx.author.id)
        if locale == "ko":
            lines = [f"• {ko}" for _key, ko, _en in rows] or ["미수령 보상이 없습니다."]
        else:
            lines = [f"• {en}" for _key, _ko, en in rows] or ["There are no unclaimed rewards."]
        await ctx.send(embed=discord.Embed(title=L(locale, "unclaimed_title"), description="\n".join(lines), colour=0xF1C40F))

    @bot.command(name="전체보상수령", aliases=["claimallrewards", "claimall"], help="중복 지급 방지 기록을 확인하며 안전한 미수령 보상을 순서대로 수령합니다.")
    async def claim_all_rewards(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None or ctx.guild is None:
            return
        locale = _locale_from_context(ctx)
        claimed: List[str] = []
        if await claim_expedition_reward(ctx, quiet=True):
            claimed.append("글로벌 탐사" if locale == "ko" else "Global Expedition")
        # Existing reward commands retain their own transaction/duplicate guards.
        for command_name, label_ko, label_en in (
            ("현상금보고", "현상금", "Bounty"),
            ("수사레이드보상", "수사 레이드", "Investigation Raid"),
            ("호송보상", "호송", "Convoy"),
            ("전쟁보상", "세력전쟁", "Faction War"),
            ("복구보상", "복구 작전", "Restoration Operation"),
        ):
            command = bot.get_command(command_name)
            if command is None:
                continue
            try:
                await ctx.invoke(command)
                claimed.append(label_ko if locale == "ko" else label_en)
            except (commands.CommandError, TypeError, ValueError):
                continue
        summary = " · ".join(claimed) if claimed else ("추가 수령 없음" if locale == "ko" else "No additional claims")
        await ctx.send(L(locale, "claim_all_done") + "\n" + summary)

    @bot.command(name="다국어검수", aliases=["languageaudit", "localizationaudit"], help="선택 언어 단일 출력과 번역 런타임 상태를 검사합니다.")
    async def language_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        locale = _locale_from_context(ctx)
        translation = root.get("translation", {})
        sample_ko = "🔎 사건판 · 현장 수색 · 보상 수령"
        sample_en = translate_text(sample_ko, "en", bot=bot)
        checks = [
            ("한글 출력 경로" if locale == "ko" else "Korean rendering path", translate_text(sample_ko, "ko", bot=bot) == sample_ko),
            ("영문 한글 누출 0" if locale == "ko" else "Zero Hangul leakage in English", not HANGUL_RE.search(sample_en)),
            ("개인 언어 저장" if locale == "ko" else "Personal locale storage", isinstance(root.get("users"), dict)),
            ("서버 언어 저장" if locale == "ko" else "Server locale storage", isinstance(root.get("guilds"), dict)),
            ("병렬 출력 차단" if locale == "ko" else "Stacked bilingual output blocked", _safe_int(translation.get("parallel_blocks")) == 0),
        ]
        embed = discord.Embed(title=L(locale, "audit_title"), colour=0x2ECC71 if all(ok for _name, ok in checks) else 0xE67E22)
        for name, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value=L(locale, "audit_ok" if ok else "audit_fail"), inline=True)
        embed.add_field(name=("희귀 문구 대체 기록" if locale == "ko" else "Legacy fallback records"), value=str(_safe_int(translation.get("fallback_total"))), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="번역누락", aliases=["missingtranslations", "translationfallbacks"], help="희귀 구버전 문구가 사전 번역 대신 안전 대체된 기록을 확인합니다.")
    async def missing_translations(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        locale = _locale_from_context(ctx)
        rows = root.get("translation", {}).get("fallbacks", {})
        ordered = sorted((x for x in rows.items() if isinstance(x[1], dict)), key=lambda item: _safe_int(item[1].get("count")), reverse=True)[:15]
        lines = [f"• `{key}` ×{row.get('count', 0)} · {row.get('output_preview', '')[:80]}" for key, row in ordered]
        if not lines:
            lines = ["대체 기록이 없습니다." if locale == "ko" else "No fallback records have been generated."]
        await ctx.send(embed=discord.Embed(title=L(locale, "missing_title"), description="\n".join(lines), colour=0xE67E22))

    @bot.command(name="명령어검수", aliases=["commandaudit", "commandaliasaudit"], help="전체 prefix 명령의 한글·영문 실행 이름과 충돌을 검사합니다.")
    async def command_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        locale = _locale_from_context(ctx)
        commands_seen = list(bot.walk_commands())
        missing_ascii = []
        token_owner: Dict[str, str] = {}
        collisions: List[str] = []
        for command in commands_seen:
            names = [str(command.name), *(str(x) for x in command.aliases)]
            if not any(ASCII_RE.fullmatch(x) and any(ch.isalpha() for ch in x) for x in names):
                missing_ascii.append(command.qualified_name)
            for token in names:
                norm = token.casefold()
                owner = token_owner.setdefault(norm, command.qualified_name)
                if owner != command.qualified_name:
                    collisions.append(f"{token}: {owner}/{command.qualified_name}")
        checks = [
            ("전체 명령" if locale == "ko" else "Total commands", len(commands_seen)),
            ("영문 누락" if locale == "ko" else "Missing English access", len(missing_ascii)),
            ("이름 충돌" if locale == "ko" else "Name collisions", len(set(collisions))),
        ]
        desc = "\n".join(f"• {name}: **{value}**" for name, value in checks)
        if missing_ascii:
            desc += "\n" + ("누락: " if locale == "ko" else "Missing: ") + ", ".join(missing_ascii[:10])
        await ctx.send(embed=discord.Embed(title=L(locale, "command_audit_title"), description=desc, colour=0x2ECC71 if not missing_ascii and not collisions else 0xE67E22))

    @bot.command(name="1000안정화검수", aliases=["v1000audit", "1000audit"], help="v10 한·영 현지화·진행 연출·신규 연결 콘텐츠를 읽기 전용 검사합니다.")
    async def v1000_audit(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        locale = _locale_from_context(ctx)
        action_index = getattr(bot, "v600_action_index", {})
        command_names = [str(c.name) for c in bot.walk_commands()]
        checks = [
            ("한·영 단일 출력 런타임" if locale == "ko" else "Single-language localization runtime", _PATCHED),
            ("언어 선택 저장" if locale == "ko" else "Language preference storage", isinstance(root.get("users"), dict)),
            ("글로벌 탐사 6종" if locale == "ko" else "Six global expeditions", len(EXPEDITION_TEMPLATES) == 6),
            ("NPC 인연 6명" if locale == "ko" else "Six NPC relationships", len(NPC_RELATIONSHIPS) == 6),
            ("진행 애니메이션" if locale == "ko" else "Progress animation", callable(getattr(bot, "v1000_animate_progress", None))),
            ("게임센터 v10 연결" if locale == "ko" else "v10 game-center links", all(key in action_index for key in ("tasks_v1000", "codex_v1000", "global_expedition_v1000", "language_v1000"))),
            ("필수 명령 등록" if locale == "ko" else "Required commands registered", all(name in command_names for name in ("언어", "할일", "생존도감", "탐사작전", "알림센터"))),
            ("삭제 기록 0" if locale == "ko" else "Zero deletions", _safe_int(root.get("stats", {}).get("deletions")) == 0),
        ]
        embed = discord.Embed(title=L(locale, "audit_title"), colour=0x2ECC71 if all(ok for _name, ok in checks) else 0xE67E22)
        for name, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value=L(locale, "audit_ok" if ok else "audit_fail"), inline=True)
        embed.set_footer(text=L(locale, "help_footer"))
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        locale = _locale_from_context(ctx)
        checks = [
            ("언어 선택" if locale == "ko" else "Language selection", bot.get_command("언어") is not None),
            ("명령 최신화" if locale == "ko" else "Command refresh", bot.get_command("commandaudit") is not None),
            ("임무 추적기" if locale == "ko" else "Mission tracker", bot.get_command("tasks") is not None),
            ("생존 도감" if locale == "ko" else "Survival codex", bot.get_command("survivalcodex") is not None),
            ("NPC 인연" if locale == "ko" else "NPC relationships", bot.get_command("relationships") is not None),
            ("글로벌 탐사" if locale == "ko" else "Global expedition", bot.get_command("expeditionoperation") is not None),
            ("보상 센터" if locale == "ko" else "Reward center", bot.get_command("unclaimedrewards") is not None),
            ("진행 연출" if locale == "ko" else "Progress animation", callable(getattr(bot, "v1000_animate_progress", None))),
        ]
        embed = discord.Embed(title=("🧪 최신 패치 상세 검사 · v10.0.0" if locale == "ko" else "🧪 Latest Patch Detail Audit · v10.0.0"), colour=0x2ECC71 if all(ok for _name, ok in checks) else 0xE67E22)
        for name, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value=L(locale, "audit_ok" if ok else "audit_fail"), inline=True)
        embed.set_footer(text=("이번 패치에서 추가·수정된 기능만 검사합니다." if locale == "ko" else "Only features added or changed in this patch are tested."))
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "v10.0.0에서 추가·수정된 현지화와 신규 연결 기능만 검사합니다."
        test_command.description = test_command.help

    # The old !help surface was English-only. v10 makes it follow the selected locale
    # without maintaining a second gameplay implementation.
    help_command = bot.get_command("help")
    if help_command is not None:
        async def v1000_help(ctx: commands.Context, *, keyword: str = "") -> None:
            locale = _locale_from_context(ctx)
            keyword = str(keyword or "").strip()
            if locale == "ko":
                embed = discord.Embed(
                    title="📚 아바돈 명령어 안내",
                    description=(
                        "현재 선택한 언어는 **한국어**입니다. 게임 화면에는 한국어만 표시됩니다.\n"
                        "`!명령어` 또는 `!게임`에서 전체 기능을 찾을 수 있습니다."
                    ),
                    colour=0x5865F2,
                )
                embed.add_field(name="🔎 검색", value=(f"검색어: **{keyword}**\n`!명령어 {keyword}`로 상세 검색하세요." if keyword else "예: `!명령어 파밍`, `!명령어 길드`, `!명령어 수사`"), inline=False)
                embed.add_field(name="🌐 언어 변경", value="`!언어 한국어` · `!언어 영어`", inline=False)
            else:
                embed = discord.Embed(
                    title="📚 ABADDON Command Guide",
                    description=(
                        "Your display language is **English**. Only English game text is shown.\n"
                        "Use `!commands` or `!game` to browse every feature."
                    ),
                    colour=0x5865F2,
                )
                embed.add_field(name="🔎 Search", value=(f"Keyword: **{keyword}**\nUse `!commands {keyword}` for a detailed search." if keyword else "Examples: `!commands scavenging`, `!commands guild`, `!commands investigation`"), inline=False)
                embed.add_field(name="🌐 Change Language", value="`!language korean` · `!language english`", inline=False)
            embed.set_footer(text=L(locale, "help_footer"))
            await ctx.send(embed=embed)
        help_command.callback = v1000_help
        help_command.help = "선택 언어에 맞는 ABADDON 명령어 안내를 엽니다."
        help_command.description = help_command.help

    intro = bot.get_command("봇소개")
    if intro is not None:
        async def v1000_bot_intro(ctx: commands.Context) -> None:
            locale = _locale_from_context(ctx)
            if locale == "ko":
                embed = discord.Embed(title="🛰️ 아바돈 · 생존 RPG", description="성장, 탐험, 스토리, 길드, 재난, 세계 상태, 수사와 협동 작전을 하나의 생존 세계에서 진행합니다.", colour=0xC8AA62)
                rows = [("⚔️ 생존", "전투·던전·레이드·월드 보스"), ("🧭 탐험", "파밍·세계지도·지역 개척·글로벌 탐사"), ("🤝 공동체", "길드·세력·호송·복구·수사 레이드"), ("🚀 시작", "`!시작안내` → `!가입 생존자` → `!게임`")]
            else:
                embed = discord.Embed(title="🛰️ ABADDON · Survival RPG", description="Progress, exploration, story, guilds, disasters, world states, investigations, and co-op operations share one survival world.", colour=0xC8AA62)
                rows = [("⚔️ Survival", "Combat, dungeons, raids, and world bosses"), ("🧭 Exploration", "Scavenging, world map, regional development, and global expeditions"), ("🤝 Community", "Guilds, factions, convoys, restoration, and investigation raids"), ("🚀 Start", "`!gettingstarted` → `!register survivor` → `!game`")]
            for name, value in rows:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=L(locale, "help_footer"))
            await ctx.send(embed=embed)
        intro.callback = v1000_bot_intro
        intro.help = "선택 언어에 맞는 ABADDON 소개를 확인합니다."
        intro.description = intro.help

    # Patch-note entry now follows the selected language.
    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v1000_patch_notes(ctx: commands.Context) -> None:
            locale = _locale_from_context(ctx)
            if locale == "ko":
                embed = discord.Embed(title="🌐 ABADDON v10.0.0 — 글로벌 생존자 통합 패치", description="선택한 언어 하나만 표시하는 완전 한·영 렌더링 계층과 신규 연결 콘텐츠를 추가했습니다.", colour=0x5865F2)
                fields = [
                    ("🌐 완전 한·영 화면", "개인 언어·서버 언어 분리 · 임베드·버튼·드롭다운·모달·오류 안내 현지화"),
                    ("⌨️ 명령어 최신화", "모든 prefix 명령에 충돌 없는 영문 접근 이름 유지 · 한글·영문 입력값 공통 처리"),
                    ("📋 탐색 편의", "임무 추적기 · 생존 도감 · 신규·복귀 안내 · 알림·미수령 보상 센터"),
                    ("🤝 신규 콘텐츠", "NPC 인연 기억 6명 · 주간 글로벌 탐사 6종 · 역할·행동·공동 정산"),
                    ("💨 이모지 진행 연출", "이동 경로 프레임과 실제 퍼센트 게이지를 메시지 편집으로 표시"),
                ]
            else:
                embed = discord.Embed(title="🌐 ABADDON v10.0.0 — Global Survivor Update", description="Adds a complete single-language Korean/English rendering layer and new connected gameplay systems.", colour=0x5865F2)
                fields = [
                    ("🌐 Complete Localization", "Separate personal/server language settings for embeds, buttons, dropdowns, modals, and errors"),
                    ("⌨️ Command Refresh", "Collision-safe English access for every prefix command and shared Korean/English arguments"),
                    ("📋 Navigation", "Mission tracker, survival codex, new/returning guides, notifications, and unclaimed rewards"),
                    ("🤝 New Gameplay", "Six NPC relationship records and six weekly global expedition scenarios"),
                    ("💨 Emoji Progress FX", "Moving route frames and live percentage gauges rendered through message edits"),
                ]
            for name, value in fields:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=L(locale, "help_footer"))
            await ctx.send(embed=embed)
        patch.callback = v1000_patch_notes
        patch.help = "ABADDON v10.0.0 글로벌 생존자 통합 패치노트입니다."
        patch.description = patch.help

    # Existing start/action commands receive lightweight movement FX without changing their calculations.
    animation_targets = {
        "파밍출발": ("🧭 폐허 파밍", "🧭 Ruin Scavenging"),
        "지역정찰": ("🗺️ 지역 정찰", "🗺️ Region Scout"),
        "호송출발": ("🚚 호송 출발", "🚚 Convoy Departure"),
        "수사레이드출발": ("🕵️ 수사 레이드", "🕵️ Investigation Raid"),
        "분대작전": ("🛡️ 분대 작전", "🛡️ Squad Operation"),
    }
    for command_name, titles in animation_targets.items():
        command = bot.get_command(command_name)
        if command is None or getattr(command, "_abaddon_v1000_animated", False):
            continue
        original = command.callback

        @functools.wraps(original)
        async def animated_callback(*args: Any, __original: Callable[..., Any] = original, __titles: Tuple[str, str] = titles, **kwargs: Any) -> Any:
            ctx = next((x for x in args if isinstance(x, commands.Context)), None)
            if ctx is not None:
                locale = _locale_from_context(ctx)
                await animate_progress(ctx, locale=locale, start_percent=0, end_percent=35, title=__titles[0 if locale == "ko" else 1], steps=3, delay=0.22)
            return await __original(*args, **kwargs)

        command.callback = animated_callback
        command._abaddon_v1000_animated = True

    # v10 commands in the classic Korean command browser.
    command_guide_categories.append({
        "id": "v1000_global",
        "emoji": "🌐",
        "title": "v10.0 글로벌 생존자",
        "hint": "언어·임무·도감·인연·글로벌 탐사·보상 센터",
        "commands": [
            "!언어", "!서버언어", "!할일", "!생존도감", "!인연",
            "!탐사작전", "!탐사참가", "!탐사행동", "!미수령보상",
            "!1000안정화검수",
        ],
    })

    bot.v1000_root = root
    bot.v1000_version = VERSION
    bot.v1000_translate = translate_text
    bot.v1000_animate_progress = animate_progress
    bot.v1000_language_check_sentinel = LANGUAGE_CHECK_SENTINEL
    bot._abaddon_v1000_registered = True
    print(f"[ABADDON v{VERSION}] global localization/mission/codex/relationship/expedition registered expeditions={len(EXPEDITION_TEMPLATES)} npcs={len(NPC_RELATIONSHIPS)} deletions=0")
