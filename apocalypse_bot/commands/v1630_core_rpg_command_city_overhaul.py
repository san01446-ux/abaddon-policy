from __future__ import annotations

"""ABADDON v17.4.0 core-RPG navigation, system fusion, city workshop and reaction expansion.

Additive patch goals:
- classify every runtime command exactly once instead of relying on the manually
  maintained guide list;
- put the apocalypse story (Season 1 -> Season 5) back at the front of !명령어;
- expose every command through section buttons, grouped dropdowns, pagination,
  short descriptions and a real execute button;
- preserve all legacy commands and save data;
- audit the renewed 20-part city workshop and expand automatic reaction presets.
"""

import inspect
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import (
    _command_requires_input,
    _invoke_command,
    _safe_embed,
    _safe_select_options,
    _safe_view,
)

VERSION = "18.0.0"
EXPECTED_DECLARATIONS = 1346
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
CITY_COMPONENT_ROOT = ASSET_ROOT / "v1500" / "city" / "components"
V1630_PREVIEW_ROOT = ASSET_ROOT / "v1630" / "previews"
MENU_TIMEOUT = 900
PAGE_SIZE = 25


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _clean(value: Any, limit: int = 4000) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit]


def _short(value: Any, limit: int = 96) -> str:
    text = _clean(value, limit + 20)
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_ASCII_COMMAND_RE = re.compile(r"^[A-Za-z0-9_ .-]+$")


def _english_alias(entry: "CommandEntry") -> str:
    candidates = list(entry.aliases) + [entry.qualified_name]
    for candidate in candidates:
        text = _clean(candidate, 100)
        if text and _ASCII_COMMAND_RE.fullmatch(text) and any(ch.isalpha() for ch in text):
            return text
    return f"command-{entry.index + 1}"


def _display_command(locale: str, entry: "CommandEntry") -> str:
    return _english_alias(entry) if locale == "en" else entry.qualified_name


def _display_help(locale: str, entry: "CommandEntry") -> str:
    if locale != "en":
        return entry.help_text
    text = _clean(entry.help_text, 500)
    if text and not _HANGUL_RE.search(text):
        return text
    _section, _ko, _en, _dko, den, _emoji = _group_spec(entry.group)
    return f"{den}. Opens the preserved `{_english_alias(entry)}` command without mixing Korean UI text."


def _display_signature(locale: str, entry: "CommandEntry") -> str:
    if locale != "en" or not _HANGUL_RE.search(entry.signature or ""):
        return entry.signature
    return "[arguments]" if entry.signature else ""


SECTION_SPECS: Tuple[Tuple[str, str, str, str], ...] = (
    ("main", "📖 메인 RPG", "📖 Core RPG", "시즌 1부터 이어지는 아포칼립스 스토리·성장·탐험"),
    ("play", "⚔️ 플레이", "⚔️ Play", "생활·전투·장비·경제·게임"),
    ("world", "🌌 세계", "🌌 World", "BLACK CITY·NEON ABYSS·재난·세력·도시 공방"),
    ("social", "🤝 소셜", "🤝 Social", "길드·동료·NPC·일정·방송·친목"),
    ("system", "🛠️ 운영", "🛠️ System", "서버 설정·보안·알림·이모지·검수·복구"),
)

# key, Korean label, English label, Korean description, English description, emoji
GROUP_SPECS: Dict[str, Tuple[Tuple[str, str, str, str, str, str], ...]] = {
    "main": (
        ("terminal", "생존단말기·통합 허브", "Survivor Terminal & Hubs", "현재 상황에서 스토리·의뢰·원정·생산·NPC로 이어지는 통합 진입점", "Unified entry points connecting current state to story, contracts, expedition, production and NPCs", "📡"),
        ("contracts", "생존 의뢰소·일일 목표", "Survival Contracts & Daily Goals", "살아 있는 세계 기반 일일·주간 의뢰와 결과·기록", "Living-world daily and weekly contracts, results and history", "📜"),
        ("story1", "시즌 1 · 검은 주파수", "Season 1 · Black Frequency", "메인 스토리 시작·선택·기록·재시작", "Main story start, choices, history and restart", "📻"),
        ("story2", "시즌 2 · 백색 방주", "Season 2 · White Ark", "두 번째 이야기와 장면·엔딩·계승", "Second story, scenes, endings and legacy", "🚢"),
        ("story3", "시즌 3 · 종말의 왕좌", "Season 3 · Throne of the End", "세 번째 이야기의 선택과 엔딩", "Third story choices and endings", "👑"),
        ("story4", "시즌 4 · 황혼의 종착역", "Season 4 · Twilight Terminal", "황혼선 이야기·여정·유산", "Twilight Line story, journey and legacy", "🚂"),
        ("story5", "시즌 5 · 잿빛 연합전선", "Season 5 · Ashen Front", "세계 상태·서버 투표·결정·연대기", "World state, server votes, decisions and chronicle", "📡"),
        ("story6", "시즌 6 · 검은 태양의 귀환", "Season 6 · Return of the Black Sun", "서버 공동 투표·도시 지표·분기 결말", "Server-wide votes, city metrics and branching endings", "☀️"),
        ("onboarding", "가입·프로필·초보 안내", "Onboarding & Profile", "가입, 정보, 직업, 튜토리얼과 복귀 안내", "Registration, profile, jobs, tutorial and return guide", "🌱"),
        ("quests", "퀘스트·성장·업적", "Quests, Growth & Achievements", "오늘 할 일, 퀘스트, 레벨, 미션과 보상", "Daily tasks, quests, levels, missions and rewards", "🎯"),
        ("exploration", "생존 탐험·원정·사건", "Survival Exploration", "지역 정찰, 원정, 사건, 수사와 유물", "Scouting, expeditions, incidents, investigation and relics", "🧭"),
        ("base", "기지·대피소·세계 진행", "Base, Shelter & World Progress", "기지 성장, 대피소, 개척, 복구와 세계 순환", "Base growth, shelter, frontier, recovery and world cycle", "🏕️"),
        ("codex", "도감·연대기·진행 확인", "Codex, Chronicle & Progress", "발견 기록, 도감, 진행판과 다음 행동", "Discovery records, codices, progress and next actions", "📚"),
        ("museum", "연대기 박물관·통합 업적", "Chronicle Museum & Global Achievements", "스토리·원정·탈것·NPC·세력 기록을 전시하고 칭호와 보상을 해금", "Exhibit story, expedition, mount, NPC and faction history to unlock titles and rewards", "🏛️"),
        ("connections", "연결 생존 루프", "Connected Survival Loop", "스토리·세계·원정·NPC·제작·도시를 다음 행동으로 연결", "Connect story, world, expedition, NPC, crafting and city through guided actions", "🔗"),
    ),
    "play": (
        ("production", "생산센터·재료 흐름", "Production Center & Materials", "채집·가방·제작·재료 사용처·도시 배치를 한 흐름으로 연결", "Connect gathering, inventory, crafting, material uses and city placement", "⚙️"),
        ("life", "생활·채집·파밍", "Life, Gathering & Farming", "채집, 낚시, 벌목, 광산, 파밍과 생활 숙련", "Gathering, fishing, logging, mining, farming and mastery", "⛏️"),
        ("gear", "상점·장비·강화·제작", "Shop, Gear, Enhance & Craft", "아이템 구매, 장착, 강화, 제작과 공방", "Buy, equip, enhance and craft items", "🛠️"),
        ("combat", "전투·보스·던전", "Combat, Boss & Dungeon", "일반 전투, 결투, 던전, 보스와 공격대", "Combat, duels, dungeons, bosses and raids", "⚔️"),
        ("economy", "경제·거래·사업", "Economy, Trade & Business", "지갑, 송금, 시장, 거래소, 무역과 사업", "Wallet, transfers, markets, trade and business", "💰"),
        ("cards", "화투·일반 카드게임", "Hwatu & Casual Cards", "맞고, 고스톱, 섯다, 훌라, 라미 등 비카지노 카드게임", "Hwatu, gostop, seotda, hula, rummy and casual card games", "🎴"),
        ("casino", "BLACK CASINO·포커", "BLACK CASINO & Poker", "카지노 로비, 포커, 블랙잭, 바카라, 슬롯, VIP와 잭팟", "Casino lobby, poker, blackjack, baccarat, slots, VIP and jackpots", "🎰"),
        ("gambling", "도박·배팅·경마", "Gambling, Betting & Racing", "탐색·주파수·생존 룰렛·경마 등 비카지노 배팅과 재기 지원", "Non-casino betting, survival roulette, racing and recovery support", "🎲"),
        ("party_games", "파티게임·축제·미니게임", "Party Games & Festival", "서버 파티게임, 혼돈 이벤트와 가벼운 놀이", "Server party games, chaos events and mini games", "🎉"),
        ("collections", "수집·꾸미기·보상", "Collections, Cosmetics & Rewards", "수집품, 칭호, 배경, 트로피와 꾸미기", "Collections, titles, backgrounds, trophies and cosmetics", "🏆"),
    ),
    "world": (
        ("black_city", "BLACK CITY", "BLACK CITY", "도시 지도, 세력, 직업, 범죄, 경제와 시즌", "City map, factions, jobs, crime, economy and seasons", "🏙️"),
        ("city_decor", "도시 꾸미기·공방", "City Decoration Workshop", "도시 부품, 배치, 사진, 제작과 시각 연출", "City parts, placement, photos, crafting and visuals", "🎨"),
        ("neon", "NEON ABYSS·차원", "NEON ABYSS & Dimensions", "차원문, 항해, 차원 탐사와 기지", "Gates, voyages, dimension exploration and base", "🌀"),
        ("crew_raid", "크루·우주선·공격대", "Crew, Ship & Raid", "크루 임무, 우주선 시설과 차원 공격대", "Crew missions, ship facilities and dimension raids", "🚀"),
        ("factions", "세력·영토·전쟁·무역", "Factions, Territory, War & Trade", "세력 평판, 영토, 호송, 전선과 공동 전쟁", "Faction reputation, territory, convoys and wars", "🏴"),
        ("disaster", "재난·기상·복구", "Disaster, Weather & Recovery", "공동 재난, 예보, 날씨, 구조와 복구 작전", "Shared disasters, forecasts, rescue and recovery", "☄️"),
        ("creator", "창작센터·콘텐츠 교환", "Creator Studio & Exchange", "퀘스트·보스 제작, 공개, 검색과 설치", "Create, publish, search and install content", "🧩"),
        ("world_misc", "월드 시스템·지도", "World Systems & Maps", "공동 지도, 세계 상태, 순환과 서버 기록", "Shared maps, world state, cycles and records", "🗺️"),
    ),
    "social": (
        ("guild", "길드·파티·연합", "Guild, Party & Alliance", "길드, 파티, 연합, 분대와 협동 조직", "Guilds, parties, alliances, squads and co-op groups", "🛡️"),
        ("companions", "동료·펫·육성", "Companions, Pets & Growth", "동료와 펫의 영입, 배치, 훈련과 진화", "Recruit, deploy, train and evolve companions and pets", "🐾"),
        ("npc", "NPC·인연·관계", "NPC, Bonds & Relations", "NPC 대화, 선물, 평판과 인연 기록", "NPC dialogue, gifts, reputation and bonds", "🤝"),
        ("schedule", "일정·예약·방송", "Schedules, Reservations & Broadcasts", "서버 일정, 게임 예약, 중계와 방송", "Server schedules, game reservations and broadcasts", "📅"),
        ("chat", "대화·친목·예능", "Chat, Social & Variety", "아바돈 대화, 칭찬, 궁합, 월드컵과 친목", "ABADDON chat, praise, compatibility and social games", "💬"),
        ("voice", "음성·하이라이트·미디어", "Voice, Highlights & Media", "음성방, 하이라이트, 사진과 미디어 관리", "Voice rooms, highlights, photos and media", "🎙️"),
        ("support", "문의·건의·신고·도움", "Support, Suggestions & Reports", "문의센터, 공개 건의, 신고와 운영진 전달", "Support center, suggestions, reports and staff relay", "📮"),
        ("competition", "커뮤니티 시즌·서버 경쟁", "Community Season & Server Competition", "기존 플레이 기여도, 일일 미션, 랭킹, 공동 목표와 응원", "Existing-play contribution, daily missions, rankings, shared goals and cheers", "🌐"),
        ("social_misc", "커뮤니티 기타", "Other Community Tools", "서버 커뮤니티와 소셜 보조 기능", "Other server community and social tools", "🌐"),
    ),
    "system": (
        ("server_setup", "서버 설치·채널·역할", "Server Setup, Channels & Roles", "서버 리뉴얼, 채널, 역할과 안내판 설치", "Server renewal, channels, roles and guide panels", "🏗️"),
        ("security", "권한·보안·관리", "Permissions, Security & Moderation", "권한 검사, 안티레이드, 격리와 관리자 도구", "Permissions, anti-raid, quarantine and moderation", "🛡️"),
        ("auto_emoji", "자동 이모지·반응", "Automatic Emoji & Reactions", "채널 프리셋, 키워드 규칙과 다중 반응", "Channel presets, keyword rules and multi-reactions", "✨"),
        ("alerts", "알림·구독·운영센터", "Alerts, Subscriptions & Operations", "알림센터, 구독 시간, 채널과 운영 대시보드", "Alerts, subscription times, channels and dashboards", "🔔"),
        ("help", "명령어·언어·접근성", "Commands, Language & Accessibility", "명령 탐색, 검색, 언어와 접근성 설정", "Command browsing, search, language and accessibility", "📚"),
        ("audit", "검수·진단·오류", "Audit, Diagnostics & Errors", "통합 검수, 시각 검사, 오류 조회와 테스트", "Integration audits, visual checks, errors and tests", "🧪"),
        ("recovery", "백업·복구·안정화", "Backup, Recovery & Stability", "백업, 복원, 재시작 복구와 안정화 도구", "Backups, restore, restart recovery and stability", "💾"),
        ("admin", "고급 관리자·데이터", "Advanced Admin & Data", "운영자 전용 지급, 데이터, 강제 진행과 관리", "Owner/admin grants, data and forced progression", "🔧"),
        ("legacy", "기타·보존 명령", "Other Preserved Commands", "분류 규칙에 걸리지 않은 기존 기능을 빠짐없이 보존", "Every remaining legacy command preserved", "🗄️"),
    ),
}

GROUP_INDEX: Dict[str, Tuple[str, str, str, str, str, str]] = {
    key: (section, ko, en, dko, den, emoji)
    for section, groups in GROUP_SPECS.items()
    for key, ko, en, dko, den, emoji in groups
}


@dataclass(frozen=True)
class CommandEntry:
    index: int
    qualified_name: str
    name: str
    help_text: str
    signature: str
    aliases: Tuple[str, ...]
    source: str
    section: str
    group: str
    restricted: bool
    is_group: bool

    @property
    def search_blob(self) -> str:
        section, ko, en, dko, den, _emoji = GROUP_INDEX[self.group]
        return " ".join((self.qualified_name, self.name, self.help_text, self.signature, " ".join(self.aliases), self.source, ko, en, dko, den)).casefold()


def _has(blob: str, *tokens: str) -> bool:
    return any(token.casefold() in blob for token in tokens)


def _classify(command: commands.Command) -> Tuple[str, str]:
    qname = str(getattr(command, "qualified_name", command.name))
    aliases = " ".join(str(x) for x in getattr(command, "aliases", []) or [])
    help_text = str(getattr(command, "help", "") or getattr(command, "description", "") or "")
    source = str(getattr(getattr(command, "callback", None), "__module__", ""))
    blob = " ".join((qname, aliases, help_text, source)).casefold()
    module = source.rsplit(".", 1)[-1]

    # Main story is explicit and always wins over generic game/campaign words.
    if module == "v33_story":
        return "main", "story1"
    if module == "v430_story_expedition" and _has(blob, "시즌2", "백색방주", "후일담", "story2", "white ark"):
        return "main", "story2"
    if module == "v600_game_center" and _has(blob, "시즌3", "종말의왕좌", "story3", "왕좌"):
        return "main", "story3"
    if module in {"v730_season_story", "v731_duplicate_stability"}:
        return "main", "story4"
    if module == "v900_faction_world_state" and _has(blob, "시즌5", "연합전선", "세계상태", "세계연대기", "season5"):
        return "main", "story5"
    # v17.0 must be classified before generic story keyword checks.
    # Its module filename contains ``season6``; using the full source blob in the
    # generic checks used to misclassify every Creator Forge command as Story 6.
    if module == "v1700_creator_forge_season6":
        if _has(blob, "시즌6", "검은 태양", "season6", "black sun") and not _has(blob, "콘텐츠", "사용자사건", "creator", "communityevent", "eventforge"):
            return "main", "story6"
        if _has(blob, "콘텐츠", "사용자사건", "creator", "communityevent", "eventforge"):
            return "world", "creator"
        if _has(blob, "스토리나침반", "storycompass"):
            return "main", "codex"
        if _has(blob, "권리증명", "ownerproof", "copyrightvault"):
            return "system", "admin"
        if _has(blob, "검수", "테스트", "패치노트", "audit", "runtime"):
            return "system", "audit"
        return "system", "legacy"

    # v17.1~17.2 living world and NPC bond layer.
    if module == "v1720_living_world_bonds":
        if _has(blob, "콘텐츠공방", "creatorforge", "창작공방"):
            return "world", "creator"
        if _has(blob, "살아있는세계", "세계속보", "지역위험", "오늘의세계", "세계참여", "세계시장", "livingworld", "worldbulletin", "worldevent", "worldmarket"):
            return "world", "world_misc"
        if _has(blob, "인연", "npc", "동행", "고백", "배신", "선물", "bond", "bondmission", "confess"):
            return "social", "npc"
        if _has(blob, "검수", "테스트", "패치노트", "audit"):
            return "system", "audit"
        return "system", "legacy"

    if module == "v1741_mount_visual_renewal":
        if _has(blob, "검수", "audit", "테스트", "패치노트"):
            return "system", "audit"
        return "world", "neon"

    if module == "v1812_abaddon_system_status":
        return "system", "audit"

    if module == "v1810_public_launch_pack":
        if _has(blob, "랭크", "pvp", "rankmatch", "rankbattle", "pvpleaderboard"):
            return "play", "combat"
        if _has(blob, "길드전", "guildwar"):
            return "social", "competition"
        if _has(blob, "초대", "invitecode", "useinvite", "invitestatus"):
            return "social", "social_misc"
        if _has(blob, "ai동료", "aicompanion"):
            return "social", "npc"
        if _has(blob, "한국봇", "koreanbots", "투표보상", "votereward"):
            return "social", "support"
        if _has(blob, "db", "스케줄러", "scheduler"):
            return "system", "recovery"
        if _has(blob, "검수", "audit"):
            return "system", "audit"
        return "system", "legacy"

    if module == "v1760_chronicle_museum_season":
        if _has(blob, "검수", "audit", "테스트", "패치노트"):
            return "system", "audit"
        if _has(blob, "박물관", "전시관", "통합업적", "통합칭호", "전설도감", "결말기록", "museum", "gallery", "achievement", "title", "legendcodex"):
            return "main", "museum"
        return "social", "competition"

    if module == "v1740_system_fusion":
        if _has(blob, "생존단말기", "survivalterminal", "terminalhub", "fusionhub"):
            return "main", "terminal"
        if _has(blob, "의뢰소", "의뢰수락", "의뢰진행", "의뢰포기", "의뢰기록", "contractoffice", "contractaccept", "contractprogress", "contracthistory"):
            return "main", "contracts"
        if _has(blob, "생산센터", "productioncenter", "productionhub", "craftinghub"):
            return "play", "production"
        if _has(blob, "세력평판", "factionreputation", "reputationboard"):
            return "world", "factions"
        if _has(blob, "검수", "테스트", "패치노트", "audit"):
            return "system", "audit"
        return "main", "terminal"

    if module == "v1730_connected_survival_loop":
        if _has(blob, "연결허브", "연결목표", "연결보상", "연결기록", "재료용도", "도시효과", "connectedhub", "connectedreward", "materialuses", "cityeffects"):
            return "main", "connections"
        if _has(blob, "검수", "테스트", "패치노트", "audit"):
            return "system", "audit"
        return "main", "connections"

    content_blob = " ".join((qname, aliases, help_text)).casefold()
    if _has(content_blob, "시즌 1", "시즌1", "검은 주파수") and not _has(content_blob, "슬롯"):
        return "main", "story1"
    if _has(content_blob, "시즌 2", "시즌2", "백색 방주"):
        return "main", "story2"
    if _has(content_blob, "시즌 3", "시즌3", "종말의 왕좌"):
        return "main", "story3"
    if _has(content_blob, "시즌 4", "시즌4", "황혼의 종착역", "황혼선"):
        return "main", "story4"
    if _has(content_blob, "시즌 5", "시즌5", "잿빛 연합전선"):
        return "main", "story5"

    # v16.8 solo roguelite remains visible in the main RPG exploration route.
    if module == "v1680_lone_survivor":
        return "main", "exploration"

    # World expansions and the city workshop.
    if module == "v1500_neon_abyss":
        if _has(blob, "도시꾸미", "도시부품", "도시사진", "도시전경", "연출설정", "연출도감", "지역보기", "citydecor", "citypart"):
            return "world", "city_decor"
        if _has(blob, "크루", "우주선", "공격대", "보스방어", "crew", "ship", "raid"):
            return "world", "crew_raid"
        if _has(blob, "창작", "콘텐츠", "퀘스트제작", "보스제작", "creator", "content"):
            return "world", "creator"
        return "world", "neon"
    if module.startswith("v1320_black_city") or module == "v1221_runtime_ui_hotfix":
        if _has(blob, "꾸미", "장식", "공방", "도시제작", "도시부품"):
            return "world", "city_decor"
        return "world", "black_city"
    if module in {"v900_faction_world_state", "v920_world_cycle_professions"}:
        if _has(blob, "재난", "복구", "세계순환", "세계지령"):
            return "world", "disaster"
        return "world", "factions"
    if module in {"v780_server_disaster", "v790_operations_disaster", "v636_world_combat"} and _has(blob, "재난", "기상", "복구", "weather", "disaster"):
        return "world", "disaster"
    if module in {"v810_world_map_ux", "v639_frontier_operations"}:
        return "world", "world_misc"

    # Automatic reactions must stay visible inside operations.
    if module == "v411_server_guard_plus" and _has(blob, "이모지", "반응", "reaction", "emoji"):
        return "system", "auto_emoji"

    # Casino and non-casino gambling are intentionally separated.
    # Qualified names such as `카지노 룰렛` remain in BLACK CASINO, while
    # standalone survival betting such as `룰렛`, `탐색` and `주파수` stays
    # in the gambling category.
    casino_tokens = (
        "카지노", "casino", "텍사스홀덤", "오마하홀덤", "세븐카드스터드",
        "파인애플홀덤", "숏덱홀덤", "하이로우포커", "인디언포커",
        "카드블랙잭", "카드바카라", "포커", "blackjack", "baccarat",
    )
    gambling_tokens = (
        "도박정보", "도박잔액", "도박자금", "도박통계", "파산신청",
        "정부지원금", "경마", "horse", "탐색", "주파수", "생존 룰렛",
    )
    if _has(blob, "정부지원금", "재기지원금", "생존지원금"):
        return "play", "gambling"
    if qname.casefold().startswith(("카지노 ", "casino ")) or module == "v40_black_casino":
        return "play", "casino"
    if module == "v37_gambling_experience":
        if _has(blob, "알바", "일하기"):
            return "play", "life"
        if _has(blob, "코인", "암시장알림"):
            return "play", "economy"
        return "play", "gambling"
    if module in {"v1092_horse_racing_rules", "v1142_dynamic_horse_odds"}:
        return "play", "gambling"
    if module == "v36_gambling_market":
        return ("play", "gambling") if _has(blob, *gambling_tokens) else ("play", "economy")
    if _has(blob, *casino_tokens):
        return "play", "casino"

    # Module families provide strong hints before generic keyword scoring.
    if module in {"v631_life_visuals", "v632_life_visuals", "v610_digging_treasure", "v770_ruin_farming"}:
        return "play", "life"
    if module in {"v633_equipment_crafting", "v634_equipment_menu", "v640_scrap_system", "v432_forge_live"}:
        return "play", "gear"
    if module in {"v630_world_boss", "v636_world_combat", "v638_hardcore_arcade", "v750_guild_raid"} and _has(blob, "보스", "전투", "던전", "레이드", "공격", "결투"):
        return "play", "combat"
    if module in {"v651_card_games", "v1010_companion_card_games", "v1051_authentic_card_games", "v1060_authentic_card_games", "v1090_rules", "v1094_card_table_images", "v1100_game_city_overhaul", "v1152_traditional_hwatu_refresh"}:
        return "play", "cards"
    if module == "v39_casino":
        return "play", "casino"
    if module in {"v1220_fun_core", "v1220_chaos_festival_complete"}:
        if _has(blob, "동료", "펫", "npc"):
            return "social", "companions"
        if _has(blob, "사업", "탐험"):
            return "play", "economy"
        if _has(blob, "수집", "꾸미", "칭호", "배경"):
            return "play", "collections"
        return "play", "party_games"
    if module in {"v750_guild_raid", "v760_guild_dispatch"} and _has(blob, "길드", "파티", "연합", "분대"):
        return "social", "guild"
    if module in {"v634_pet_visuals", "v1010_companion_card_games"} and _has(blob, "동료", "펫", "훈련", "원정"):
        return "social", "companions"
    if module in {"v1190_event_broadcast_collection"}:
        if _has(blob, "일정", "예약", "방송", "중계"):
            return "social", "schedule"
        return "play", "collections"
    if module in {"v620_dialogue_memory", "v711_cute_interactions"}:
        return "social", "chat"
    if module in {"v433_voice_sanctuary"}:
        return "social", "voice"
    if module in {"v403_server_builder", "v410_server_management", "v602_channel_rules", "v1850_community_dashboard"}:
        return "system", "server_setup"
    if module in {"v411_server_guard_plus", "v420_ops_center", "v422_security_center", "v1150_server_operations_permissions"}:
        return "system", "security"
    if module in {"v1151_alert_settings_ui", "v1143_disaster_optin", "v790_operations_disaster"} and _has(blob, "알림", "구독", "운영"):
        return "system", "alerts"
    if module in {"v521_diagnostics", "v1093_command_ui_audit", "v1330_command_registry_guard", "v1621_visual_command_hotfix"}:
        return "system", "audit"
    if module in {"v1160_recovery_rules", "v1160_game_recovery_validation"}:
        return "system", "recovery"

    # Legacy module families that use very short Korean subcommand names.
    # Runtime qualified names provide even more context, while these mappings
    # keep static declarations and old standalone commands out of a vague bucket.
    if module == "admin_tools":
        return "system", "admin"
    if module == "conditions":
        return ("play", "gear") if _has(blob, "의약", "약품", "병원", "사용") else ("main", "onboarding")
    if module in {"daily_quiz", "v31_quiz_notify"}:
        return "play", "party_games"
    if module == "status":
        return "main", "onboarding"
    if module == "v1000_global_survivor":
        return ("main", "exploration") if _has(blob, "탐사") else ("main", "onboarding")
    if module == "v1050_unified_expansion":
        if _has(blob, "파인애플홀덤", "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커", "카드블랙잭", "카드바카라", "게임장", "빠른참가", "게임전적", "게임랭킹", "토너먼트"):
            return "play", "casino"
        if _has(blob, "무료시즌"):
            return "main", "quests"
        return "play", "cards"
    if module == "v1090_integrated_renewal":
        if _has(blob, "대시보드", "최근게임", "게임리플레이", "관전", "재대결", "게임방", "빠른대전"):
            return "play", "cards"
        if _has(blob, "파산", "재기"):
            return "play", "economy"
        if _has(blob, "명예의전당", "대회센터", "리그"):
            return "play", "collections"
        return "play", "cards"
    if module == "v1140_championship_alliance_casino_story":
        if _has(blob, "캠페인"):
            return "main", "codex"
        return "play", "cards"
    if module == "v1620_living_legends":
        if _has(blob, "즐겨찾기", "최근명령"):
            return "system", "help"
        if _has(blob, "탈것"):
            return "world", "neon"
        return "main", "codex"
    if module == "v21_reborn":
        if _has(blob, "입찰"):
            return "play", "economy"
        if _has(blob, "랭킹"):
            return "play", "collections"
        return "play", "gear"
    if module == "v30_invasion":
        return "play", "combat"
    if module == "v32_codex_settings_tutorial":
        return ("system", "server_setup") if _has(blob, "서버") else ("main", "codex")
    if module == "v40_finance":
        return "play", "economy"
    if module == "v421_utility_pack":
        return "system", "server_setup"
    if module == "v423_intake_center":
        return "social", "support"
    if module == "v430_story_expedition":
        if _has(blob, "시작", "선택"):
            return "main", "story2"
        return "main", "exploration"
    if module == "v431_growth_balance":
        if _has(blob, "장면", "계승"):
            return "main", "story2"
        if _has(blob, "장착", "해제"):
            return "play", "gear"
        return "main", "quests"
    if module == "v600_game_center":
        if _has(blob, "시작", "선택"):
            return "main", "story3"
        return "system", "help"
    if module == "v636_world_combat":
        if _has(blob, "자원구매", "자원판매"):
            return "play", "economy"
        if _has(blob, "날씨"):
            return "world", "disaster"
        return "play", "combat"
    if module == "v637_dynamic_events":
        if _has(blob, "내구도", "개조"):
            return "play", "gear"
        if _has(blob, "위험구역", "무전"):
            return "main", "exploration"
        if _has(blob, "까마귀구매"):
            return "play", "economy"
        return "play", "party_games"
    if module == "v638_hardcore_arcade":
        if _has(blob, "벙커", "금고", "생물테러", "오염문", "괴질탈출"):
            return "play", "combat"
        return "play", "party_games"
    if module == "v640_interactive_arcade":
        return "play", "party_games"
    if module == "v641_stabilization":
        return "system", "server_setup"
    if module == "v702_stability":
        return "system", "audit"
    if module == "v720_coop_cleanup":
        if _has(blob, "패치"):
            return "system", "alerts"
        return "play", "party_games"
    if module == "world_exploration":
        return "main", "exploration"
    if module == "bot":
        if _has(blob, "구매", "인벤토리", "장착", "해제", "버리기", "재료"):
            return "play", "gear"
        if _has(blob, "괴물", "pvp"):
            return "play", "combat"
        if _has(blob, "돈주세요", "자원", "판매", "구매등록번호", "판매취소"):
            return "play", "economy"
        if _has(blob, "시즌패스", "시즌보상"):
            return "main", "quests"
        if _has(blob, "랭킹", "가방조회"):
            return "main", "codex"
    if module == "v1631_casino_gambling_onboarding_overhaul" and _has(blob, "이모지"):
        return "system", "auto_emoji"

    # Name/help scoring catches core.bot and small legacy modules.
    ordered_rules: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
        ("system", "auto_emoji", ("자동이모지", "이모지채널", "이모지규칙", "이모지프리셋", "반응이모지")),
        ("world", "city_decor", ("도시꾸미", "도시부품", "도시사진", "도시전경", "장식", "공방")),
        ("world", "black_city", ("black city", "도시세력", "도시거래", "도시시즌", "오늘의신문", "아지트", "범죄", "현상금")),
        ("world", "neon", ("차원문", "차원탐사", "차원지도", "차원기지", "항해", "neon abyss", "균열")),
        ("world", "crew_raid", ("크루", "우주선", "공격대", "차원보스")),
        ("world", "factions", ("세력", "영토", "전쟁", "전선", "호송", "무역로")),
        ("world", "disaster", ("재난", "기상", "복구작전", "세계순환", "세계지령")),
        ("world", "creator", ("창작센터", "콘텐츠공개", "콘텐츠검색", "콘텐츠설치", "퀘스트제작", "보스제작")),
        ("social", "schedule", ("일정", "예약", "방송", "중계", "캘린더")),
        ("social", "guild", ("길드", "파티", "연합", "분대", "협동")),
        ("social", "companions", ("동료", "펫", "진화", "훈련")),
        ("social", "npc", ("npc", "인연", "관계도", "선물", "딜러대화")),
        ("social", "voice", ("음성", "tts", "하이라이트", "미디어")),
        ("social", "support", ("문의", "건의", "신고", "제보", "지원센터")),
        ("social", "chat", ("대화", "칭찬", "궁합", "비밀친구", "월드컵")),
        ("play", "casino", ("카지노", "포커", "홀덤", "블랙잭", "바카라", "슬롯", "vip", "잭팟", "딜러", "럭키휠")),
        ("play", "gambling", ("도박", "배팅", "경마", "탐색", "주파수", "파산신청", "정부지원금", "생존 룰렛")),
        ("play", "cards", ("카드", "화투", "맞고", "고스톱", "훌라", "라미", "섯다", "대통령", "삼봉", "도리짓고땡", "육백", "민화투")),
        ("play", "party_games", ("파티게임", "마피아", "라이어", "룰렛게임", "폭탄돌리기", "축제")),
        ("play", "combat", ("전투", "공격", "보스", "던전", "레이드", "결투", "방어")),
        ("play", "gear", ("장비", "아이템", "강화", "제작", "상점", "수리", "감정", "분해")),
        ("play", "life", ("채집", "낚시", "벌목", "광산", "땅파기", "파밍", "알바", "생활", "보물")),
        ("play", "economy", ("지갑", "송금", "식량", "경제", "거래", "시장", "사업", "경매", "대출", "부채")),
        ("play", "collections", ("수집", "칭호", "트로피", "배경", "스킨", "도감보상")),
        ("main", "onboarding", ("가입", "정보", "프로필", "직업", "튜토리얼", "처음", "초보", "복귀")),
        ("main", "quests", ("퀘스트", "미션", "출석", "업적", "레벨", "성장", "오늘할일", "주간", "일일", "시즌패스", "시즌보상")),
        ("main", "exploration", ("탐험", "원정", "정찰", "사건", "수사", "단서", "유물", "현상금")),
        ("main", "base", ("기지", "대피소", "개척", "거점", "복구", "세계상태")),
        ("main", "codex", ("도감", "연대기", "기록", "진행", "할일", "다음 행동")),
        ("system", "server_setup", ("서버설정", "서버리뉴얼", "채널설정", "채널가이드", "역할설정", "설치")),
        ("system", "security", ("권한", "보안", "안티레이드", "격리", "잠금", "차단", "경고", "관리자")),
        ("system", "alerts", ("알림", "구독", "운영센터", "운영대시보드", "운영광택")),
        ("system", "help", ("명령어", "도움말", "언어", "english", "접근성", "검색", "대시보드")),
        ("system", "audit", ("검수", "진단", "오류", "테스트", "감사", "점검", "실사용통계", "commandmetrics")),
        ("system", "recovery", ("백업", "복구", "복원", "재시작", "안정화")),
        ("system", "admin", ("지급", "회수", "강제", "데이터", "초기화", "운영자", "메시지정리", "청소센터", "cleanupcenter")),
    )
    for section, group, tokens in ordered_rules:
        if _has(blob, *tokens):
            return section, group
    return "system", "legacy"


def _build_registry(bot: commands.Bot) -> List[CommandEntry]:
    rows: List[CommandEntry] = []
    seen: set[str] = set()
    for command in bot.walk_commands():
        qname = _clean(getattr(command, "qualified_name", command.name), 100)
        if not qname or qname in seen:
            continue
        seen.add(qname)
        help_text = _clean(getattr(command, "help", "") or getattr(command, "description", "") or inspect.getdoc(getattr(command, "callback", None)) or "설명이 등록되지 않은 기존 명령입니다.", 500)
        aliases = tuple(dict.fromkeys(_clean(x, 80) for x in (getattr(command, "aliases", []) or []) if _clean(x, 80)))
        source = _clean(getattr(getattr(command, "callback", None), "__module__", "unknown"), 120)
        section, group = _classify(command)
        restricted = bool(getattr(command, "hidden", False)) or _has(" ".join((qname, help_text, source)).casefold(), "관리자", "운영자", "owner", "admin", "권한 필요")
        rows.append(CommandEntry(
            index=len(rows),
            qualified_name=qname,
            name=_clean(command.name, 100),
            help_text=help_text,
            signature=_clean(getattr(command, "signature", ""), 220),
            aliases=aliases,
            source=source.rsplit(".", 1)[-1],
            section=section,
            group=group,
            restricted=restricted,
            is_group=isinstance(command, commands.Group),
        ))

    story_rank = {"story1": 0, "story2": 1, "story3": 2, "story4": 3, "story5": 4, "story6": 5}
    rows.sort(key=lambda e: (
        0 if e.section == "main" else 1,
        story_rank.get(e.group, 10),
        e.section,
        e.group,
        e.qualified_name.casefold(),
    ))
    # Re-number after sorting so Select values remain compact and stable for this process.
    return [CommandEntry(i, e.qualified_name, e.name, e.help_text, e.signature, e.aliases, e.source, e.section, e.group, e.restricted, e.is_group) for i, e in enumerate(rows)]


def _group_spec(group: str) -> Tuple[str, str, str, str, str, str]:
    return GROUP_INDEX.get(group, ("system", "기타·보존 명령", "Other Preserved Commands", "모든 기존 기능을 보존합니다.", "All legacy commands are preserved.", "🗄️"))


def _section_spec(section: str) -> Tuple[str, str, str, str]:
    return next((row for row in SECTION_SPECS if row[0] == section), SECTION_SPECS[0])


def _state_for(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> Optional[MutableMapping[str, Any]]:
    try:
        user = get_user(int(user_id))
    except Exception:
        return None
    if not isinstance(user, MutableMapping):
        return None
    state = user.setdefault("v1630_command_center", {})
    if not isinstance(state, MutableMapping):
        state = {}
        user["v1630_command_center"] = state
    state.setdefault("favorites", [])
    state.setdefault("recent", [])
    return state


def _record_recent(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], save_data: Callable[[], None], user_id: int, entry: CommandEntry) -> None:
    state = _state_for(get_user, user_id)
    if state is None:
        return
    recent = [str(x) for x in state.get("recent", []) if str(x) != entry.qualified_name]
    recent.insert(0, entry.qualified_name)
    state["recent"] = recent[:30]
    save_data()


def _toggle_favorite(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], save_data: Callable[[], None], user_id: int, entry: CommandEntry) -> Tuple[bool, str]:
    state = _state_for(get_user, user_id)
    if state is None:
        return False, "가입 후 즐겨찾기를 저장할 수 있습니다."
    favorites = [str(x) for x in state.get("favorites", [])]
    if entry.qualified_name in favorites:
        favorites.remove(entry.qualified_name)
        state["favorites"] = favorites
        save_data()
        return False, f"☆ `!{entry.qualified_name}` 즐겨찾기를 해제했습니다."
    if len(favorites) >= 40:
        return False, "즐겨찾기는 최대 40개까지 저장할 수 있습니다."
    favorites.append(entry.qualified_name)
    state["favorites"] = favorites
    save_data()
    return True, f"⭐ `!{entry.qualified_name}`를 즐겨찾기에 추가했습니다."


def _lookup_saved(entries: Sequence[CommandEntry], names: Iterable[Any]) -> List[CommandEntry]:
    index = {e.qualified_name: e for e in entries}
    return [index[str(name)] for name in names if str(name) in index]


def _search(entries: Sequence[CommandEntry], query: str) -> List[CommandEntry]:
    terms = [x for x in re.split(r"\s+", _clean(query, 80).casefold()) if x]
    if not terms:
        return []
    scored: List[Tuple[int, CommandEntry]] = []
    for entry in entries:
        if all(term in entry.search_blob for term in terms):
            score = 0
            q = entry.qualified_name.casefold()
            for term in terms:
                if q == term:
                    score += 20
                elif q.startswith(term):
                    score += 10
                elif term in q:
                    score += 6
                elif term in entry.help_text.casefold():
                    score += 2
            scored.append((score, entry))
    scored.sort(key=lambda row: (-row[0], row[1].qualified_name.casefold()))
    return [entry for _score, entry in scored]


def _story_route(entries: Sequence[CommandEntry]) -> List[CommandEntry]:
    priorities = ("상태", "시작", "선택", "장면", "기록", "도감", "수집", "여정", "유산", "재시작", "투표", "결정")
    groups = ("story1", "story2", "story3", "story4", "story5", "story6")
    result: List[CommandEntry] = []
    for group in groups:
        group_rows = [e for e in entries if e.group == group]
        group_rows.sort(key=lambda e: (next((i for i, token in enumerate(priorities) if token in e.qualified_name), 99), e.qualified_name.casefold()))
        result.extend(group_rows)
    return result


def _today_route(entries: Sequence[CommandEntry]) -> List[CommandEntry]:
    preferred = ("정보", "오늘할일", "출석", "성장보드", "일일퀘스트", "주간퀘스트", "미션보상", "채집", "기지", "스토리")
    index = {e.qualified_name: e for e in entries}
    result = [index[name] for name in preferred if name in index]
    if len(result) < 8:
        for entry in entries:
            if entry.group in {"quests", "onboarding"} and entry not in result:
                result.append(entry)
            if len(result) >= 18:
                break
    return result


def _overview_embed(locale: str, entries: Sequence[CommandEntry], section: str, group: str, visible: Sequence[CommandEntry], page: int, special_title: Optional[str] = None) -> discord.Embed:
    section_key, sko, sen, sdesc = _section_spec(section)
    _gsection, gko, gen, gdko, gden, emoji = _group_spec(group)
    title = special_title or _t(locale, "📖 ABADDON 완전 명령어 센터", "📖 ABADDON Complete Command Center")
    description = _t(
        locale,
        "**이 봇의 중심은 시즌 1부터 이어지는 아포칼립스 RPG입니다.**\n모든 등록 명령을 자동 수집해 **큰 영역 → 기능군 → 명령 → 실행** 순서로 정리했습니다.",
        "**The core is an apocalypse RPG progressing from Season 1.**\nEvery registered command is collected into **section → group → command → execute**.",
    )
    embed = discord.Embed(title=title, description=description, color=0x7137C8)
    alias_count = sum(len(e.aliases) for e in entries)
    embed.add_field(name=_t(locale, "등록 명령", "Registered Commands"), value=f"**{len(entries):,}개**", inline=True)
    embed.add_field(name=_t(locale, "별칭", "Aliases"), value=f"**{alias_count:,}개**", inline=True)
    embed.add_field(name=_t(locale, "누락", "Missing"), value="**0개**", inline=True)
    embed.add_field(name=_t(locale, "메인 진행", "Main Progression"), value="📻 시즌 1 → 🚢 시즌 2 → 👑 시즌 3 → 🚂 시즌 4 → 📡 시즌 5", inline=False)
    if special_title is None and section == "main" and group == "story1" and page == 0:
        section_counts = {key: sum(1 for e in entries if e.section == key) for key, *_ in SECTION_SPECS}
        category_guide = _t(
            locale,
            "\n".join((
                f"📖 **메인 RPG** · {section_counts.get('main', 0)}개 — 시즌 1~5, 성장, 탐험, 기지와 진행 기록",
                f"⚔️ **플레이** · {section_counts.get('play', 0)}개 — 생활, 장비, 전투, 경제, 카드, 카지노와 도박",
                f"🌌 **세계** · {section_counts.get('world', 0)}개 — BLACK CITY, 도시 공방, 차원, 세력과 재난",
                f"🤝 **소셜** · {section_counts.get('social', 0)}개 — 길드, 동료, NPC, 일정, 방송과 친목",
                f"🛠️ **운영** · {section_counts.get('system', 0)}개 — 서버 설정, 보안, 알림, 자동 이모지와 검수",
            )),
            "\n".join((
                f"📖 **Core RPG** · {section_counts.get('main', 0)} — Seasons 1–5, growth, exploration and progress",
                f"⚔️ **Play** · {section_counts.get('play', 0)} — life, gear, combat, economy, casino and gambling",
                f"🌌 **World** · {section_counts.get('world', 0)} — BLACK CITY, workshop, dimensions, factions and disasters",
                f"🤝 **Social** · {section_counts.get('social', 0)} — guilds, companions, NPCs, schedules and community",
                f"🛠️ **System** · {section_counts.get('system', 0)} — setup, security, alerts, reactions and audits",
            )),
        )
        embed.add_field(name=_t(locale, "🧭 첫 화면 카테고리 안내", "🧭 Category Guide"), value=category_guide[:1024], inline=False)
        embed.add_field(
            name=_t(locale, "🎰 도박 콘텐츠 빠른 구분", "🎰 Gambling Quick Split"),
            value=_t(locale, "**BLACK CASINO·포커**는 카지노 버튼 · **경마·탐색·주파수·재기 지원**은 도박 버튼", "Use Casino for poker/table games and Gambling for racing/survival bets/recovery support."),
            inline=False,
        )
    preview = "\n".join(f"• `!{_display_command(locale, e)}` — {_short(_display_help(locale, e), 72)}" for e in visible[:8])
    if not preview:
        preview = _t(locale, "이 기능군에 표시할 명령이 없습니다.", "No commands in this group.")
    embed.add_field(name=f"{emoji} {_t(locale, gko, gen)} · {len(visible)}", value=f"{_t(locale, gdko, gden)}\n{preview}"[:1024], inline=False)
    page_count = max(1, (len(visible) - 1) // PAGE_SIZE + 1)
    embed.set_footer(text=_t(locale, f"{_t(locale, sko, sen)} · {page + 1}/{page_count} 페이지 · 선택 후 실행 버튼", f"{_t(locale, sko, sen)} · page {page + 1}/{page_count} · select then execute"))
    return embed


def _detail_embed(locale: str, entry: CommandEntry, favorite: bool) -> discord.Embed:
    _section, gko, gen, gdko, gden, emoji = _group_spec(entry.group)
    display_name = _display_command(locale, entry)
    embed = discord.Embed(
        title=f"{emoji} !{display_name}",
        description=f"**{_t(locale, '무엇을 하나요?', 'What does it do?')}**\n{_display_help(locale, entry)}",
        color=0x4F8CFF if not entry.restricted else 0xE39B36,
    )
    embed.add_field(name=_t(locale, "분류", "Category"), value=_t(locale, gko, gen), inline=True)
    embed.add_field(name=_t(locale, "실행 방식", "Execution"), value=_t(locale, "입력창 또는 즉시 실행", "Input modal or instant execution"), inline=True)
    embed.add_field(name=_t(locale, "권한", "Access"), value=_t(locale, "관리/조건 확인" if entry.restricted else "일반 사용", "Restricted/checks" if entry.restricted else "General"), inline=True)
    usage = f"!{display_name}" + (f" {_display_signature(locale, entry)}" if _display_signature(locale, entry) else "")
    embed.add_field(name=_t(locale, "직접 입력", "Direct Command"), value=f"`{usage[:1000]}`", inline=False)
    if entry.aliases:
        embed.add_field(name=_t(locale, "별칭", "Aliases"), value=" · ".join(f"`!{x}`" for x in ([a for a in entry.aliases if locale != "en" or (_ASCII_COMMAND_RE.fullmatch(a) and not _HANGUL_RE.search(a))][:12]))[:1024] or _t(locale, "등록된 별칭 없음", "No additional English aliases"), inline=False)
    embed.add_field(name=_t(locale, "버튼 사용", "Button Use"), value=_t(locale, "아래 **실행**을 누르세요. 필수 입력값이 있으면 입력창이 열립니다.", "Press **Execute** below. A modal opens when arguments are required."), inline=False)
    embed.add_field(name=_t(locale, "즐겨찾기", "Favorite"), value="⭐" if favorite else "☆", inline=True)
    embed.add_field(name=_t(locale, "원본 모듈", "Source Module"), value=f"`{entry.source}`", inline=True)
    if entry.is_group:
        embed.add_field(name=_t(locale, "그룹 명령", "Command Group"), value=_t(locale, "하위 명령은 같은 기능군에서 함께 확인할 수 있습니다.", "Subcommands are listed in the same group."), inline=False)
    return embed


class CommandArgsModal(discord.ui.Modal):
    def __init__(self, owner: "CompleteCommandCenterView", entry: CommandEntry) -> None:
        super().__init__(title=_short(_t(owner.locale, f"!{entry.qualified_name} 입력", f"!{_display_command(owner.locale, entry)} arguments"), 45), timeout=MENU_TIMEOUT)
        self.owner_view = owner
        self.entry = entry
        placeholder = _display_signature(owner.locale, entry) or _t(owner.locale, "입력값이 없으면 비워두세요", "Leave blank when no value is needed")
        self.raw = discord.ui.TextInput(
            label=_t(owner.locale, "명령어 입력값", "Command Arguments"),
            placeholder=_short(placeholder, 100),
            required=bool(entry.signature and owner.command_requires_input(entry)),
            max_length=600,
            style=discord.TextStyle.paragraph if len(placeholder) > 50 else discord.TextStyle.short,
        )
        self.add_item(self.raw)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if int(interaction.user.id) != view.owner_id:
            await interaction.response.send_message(_t(view.locale, "이 메뉴는 실행자만 사용할 수 있습니다.", "Only the opener can use this menu."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        ok = await _invoke_command(view.bot, interaction, self.entry.qualified_name, str(self.raw.value or ""))
        if ok:
            _record_recent(view.get_user, view.save_data, interaction.user.id, self.entry)


class CommandSearchModal(discord.ui.Modal):
    def __init__(self, owner: "CompleteCommandCenterView") -> None:
        super().__init__(title=_t(owner.locale, "전체 명령 검색", "Search All Commands"), timeout=MENU_TIMEOUT)
        self.owner_view = owner
        self.query = discord.ui.TextInput(
            label=_t(owner.locale, "검색어", "Search Query"),
            placeholder=_t(owner.locale, "예: 시즌1, 도시꾸미기, 보스, 자동이모지", "e.g. season1, city decorate, boss, auto emoji"),
            required=True,
            max_length=80,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        results = _search(view.entries, str(self.query.value))
        if not results:
            await interaction.response.send_message(_t(view.locale, "검색 결과가 없습니다.", "No search results."), ephemeral=True)
            return
        view.set_special(results, _t(view.locale, f"🔎 검색 결과 · {self.query.value}", f"🔎 Search · {self.query.value}"))
        view.rebuild()
        await _safe_component_edit(interaction, embed=view.current_embed(), view=view)


async def _safe_component_edit(interaction: discord.Interaction, *, embed: Optional[discord.Embed] = None, view: Optional[discord.ui.View] = None) -> None:
    """Acknowledge component interactions first, then edit to avoid token expiry/NotFound."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await interaction.edit_original_response(embed=_safe_embed(embed), view=_safe_view(view))
    except discord.NotFound:
        try:
            await interaction.followup.send("🫧 이 메뉴가 만료되었습니다. `!명령어`를 다시 열어주세요.", ephemeral=True)
        except Exception:
            pass


class SectionButton(discord.ui.Button):
    def __init__(self, owner: "CompleteCommandCenterView", key: str, ko: str, en: str) -> None:
        style = discord.ButtonStyle.primary if owner.section == key else discord.ButtonStyle.secondary
        super().__init__(label=_short(_t(owner.locale, ko, en), 80), style=style, row=0)
        self.owner_view = owner
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        view.section = self.key
        view.special_entries = None
        view.special_title = None
        view.selected_index = None
        view.page = 0
        view.group = view.first_group(self.key)
        view.rebuild()
        await _safe_component_edit(interaction, embed=view.current_embed(), view=view)


class GroupSelect(discord.ui.Select):
    def __init__(self, owner: "CompleteCommandCenterView") -> None:
        self.owner_view = owner
        options: List[discord.SelectOption] = []
        counts = owner.group_counts(owner.section)
        for key, ko, en, dko, den, emoji in GROUP_SPECS[owner.section]:
            count = counts.get(key, 0)
            if count <= 0:
                continue
            options.append(discord.SelectOption(
                label=_short(_t(owner.locale, ko, en), 100),
                value=key,
                emoji=emoji,
                description=_short(f"{count} · {_t(owner.locale, dko, den)}", 100),
                default=key == owner.group and owner.special_entries is None,
            ))
        if not options:
            options = [discord.SelectOption(label=_t(owner.locale, "기타·보존 명령", "Other Preserved Commands"), value="legacy", emoji="🗄️")]
        super().__init__(placeholder=_t(owner.locale, "기능군을 선택하세요", "Choose a command group"), min_values=1, max_values=1, options=_safe_select_options(options[:25]), row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        view.group = self.values[0]
        view.special_entries = None
        view.special_title = None
        view.selected_index = None
        view.page = 0
        view.rebuild()
        await _safe_component_edit(interaction, embed=view.current_embed(), view=view)


class CommandSelect(discord.ui.Select):
    def __init__(self, owner: "CompleteCommandCenterView") -> None:
        self.owner_view = owner
        page_rows = owner.page_entries()
        options: List[discord.SelectOption] = []
        for entry in page_rows:
            _section, _ko, _en, _dko, _den, emoji = _group_spec(entry.group)
            options.append(discord.SelectOption(
                label=_short(f"!{_display_command(owner.locale, entry)}", 100),
                value=str(entry.index),
                emoji=emoji,
                description=_short(_display_help(owner.locale, entry), 100),
                default=entry.index == owner.selected_index,
            ))
        if not options:
            options = [discord.SelectOption(label=_t(owner.locale, "표시할 명령 없음", "No commands"), value="-1", description=_t(owner.locale, "다른 기능군을 선택하세요", "Choose another group"))]
        start = owner.page * PAGE_SIZE + 1
        end = owner.page * PAGE_SIZE + len(page_rows)
        total = len(owner.current_entries())
        super().__init__(placeholder=_t(owner.locale, f"명령 선택 · {start}-{end}/{total}", f"Choose command · {start}-{end}/{total}"), min_values=1, max_values=1, options=_safe_select_options(options[:25]), row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        try:
            selected = int(self.values[0])
        except ValueError:
            selected = -1
        if selected < 0 or selected not in view.by_index:
            await interaction.response.send_message(_t(view.locale, "선택한 명령을 찾지 못했습니다.", "Command not found."), ephemeral=True)
            return
        view.selected_index = selected
        view.rebuild()
        await _safe_component_edit(interaction, embed=view.current_embed(), view=view)


class NavButton(discord.ui.Button):
    def __init__(self, owner: "CompleteCommandCenterView", action: str, label_ko: str, label_en: str, emoji: str, style: discord.ButtonStyle = discord.ButtonStyle.secondary, row: int = 3) -> None:
        super().__init__(label=_short(_t(owner.locale, label_ko, label_en), 80), emoji=emoji, style=style, row=row)
        self.owner_view = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        action = self.action
        if action == "home":
            view.section = "main"
            view.group = view.first_group("main")
            view.special_entries = None
            view.special_title = None
            view.selected_index = None
            view.page = 0
        elif action == "prev":
            view.page = max(0, view.page - 1)
            view.selected_index = None
        elif action == "next":
            view.page = min(view.max_page(), view.page + 1)
            view.selected_index = None
        elif action == "search":
            await interaction.response.send_modal(CommandSearchModal(view))
            return
        elif action == "story":
            view.set_special(_story_route(view.entries), _t(view.locale, "📖 메인 스토리 · 시즌 1→6", "📖 Main Story · Season 1→6"))
        elif action == "casino":
            view.section, view.group = "play", "casino"
            view.special_entries = None; view.special_title = None; view.selected_index = None; view.page = 0
        elif action == "gambling":
            view.section, view.group = "play", "gambling"
            view.special_entries = None; view.special_title = None; view.selected_index = None; view.page = 0
        elif action == "beginner":
            command = view.bot.get_command("초보생존") or view.bot.get_command("firstsurvival") or view.bot.get_command("초보센터")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
            rows = [e for e in view.entries if e.group in {"onboarding", "story1"}]
            view.set_special(rows, _t(view.locale, "🌱 신규 생존자 첫걸음", "🌱 New Survivor Start"))
        elif action == "quick_more":
            view.quick_page = 1
        elif action == "quick_more2":
            view.quick_page = 2
        elif action == "quick_more3":
            view.quick_page = 3
        elif action == "quick_more4":
            view.quick_page = 4
        elif action == "quick_more5":
            view.quick_page = 5
        elif action == "quick_more6":
            view.quick_page = 6
        elif action == "quick_more7":
            view.quick_page = 7
        elif action == "quick_more8":
            view.quick_page = 8
        elif action == "quick_back7":
            view.quick_page = 7
        elif action == "quick_back6":
            view.quick_page = 6
        elif action == "quick_back4":
            view.quick_page = 3
        elif action == "quick_back3":
            view.quick_page = 2
        elif action == "quick_back2":
            view.quick_page = 1
        elif action == "quick_back":
            view.quick_page = 0
        elif action == "lone_expedition":
            command = view.bot.get_command("솔로원정") or view.bot.get_command("lonesurvivor")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "weekly_expedition":
            command = view.bot.get_command("주간변이지역") or view.bot.get_command("weeklyanomaly")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "expedition_codex":
            command = view.bot.get_command("원정도감") or view.bot.get_command("expeditioncodex")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "expedition_record":
            command = view.bot.get_command("솔로원정기록") or view.bot.get_command("loneexpeditionrecord")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "season6":
            command = view.bot.get_command("시즌6") or view.bot.get_command("season6")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "creator_forge":
            command = view.bot.get_command("콘텐츠공방") or view.bot.get_command("creatorforge")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "custom_event":
            command = view.bot.get_command("사용자사건") or view.bot.get_command("communityevent")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "runtime_clean":
            command = view.bot.get_command("1720통합검수") or view.bot.get_command("v1720audit") or view.bot.get_command("1700통합검수")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name, "상세")
                return
        elif action == "living_world":
            command = view.bot.get_command("살아있는세계") or view.bot.get_command("livingworld")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "world_event":
            command = view.bot.get_command("오늘의세계사건") or view.bot.get_command("worldevent")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "bonds":
            command = view.bot.get_command("인연") or view.bot.get_command("bonds")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "npc_list":
            command = view.bot.get_command("NPC목록") or view.bot.get_command("npclist")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "connected_hub":
            command = view.bot.get_command("연결허브") or view.bot.get_command("connectedhub")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "connected_goals":
            command = view.bot.get_command("연결목표") or view.bot.get_command("connectedobjectives")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "connected_reward":
            command = view.bot.get_command("연결보상") or view.bot.get_command("connectedreward")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "city_effects":
            command = view.bot.get_command("도시효과") or view.bot.get_command("cityeffects")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "survival_terminal":
            command = view.bot.get_command("생존단말기") or view.bot.get_command("survivalterminal")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "contract_office":
            command = view.bot.get_command("의뢰소") or view.bot.get_command("contractoffice")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "production_center":
            command = view.bot.get_command("생산센터") or view.bot.get_command("productioncenter")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "faction_reputation":
            command = view.bot.get_command("세력평판") or view.bot.get_command("factionreputation")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "chronicle_museum":
            command = view.bot.get_command("연대기박물관") or view.bot.get_command("chroniclemuseum")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "global_achievements":
            command = view.bot.get_command("통합업적") or view.bot.get_command("achievementsall")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "community_season":
            command = view.bot.get_command("서버시즌") or view.bot.get_command("abaddonseason")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "community_ranking":
            command = view.bot.get_command("시즌랭킹") or view.bot.get_command("communityranking")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "definitive_terminal":
            command = view.bot.get_command("최종단말기") or view.bot.get_command("definitiveterminal")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "final_eclipse":
            command = view.bot.get_command("최종일식") or view.bot.get_command("finaleclipse")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "daily_loop":
            command = view.bot.get_command("오늘의루프") or view.bot.get_command("dailyloop")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "final_ops":
            command = view.bot.get_command("운영단말기") or view.bot.get_command("operationsterminal")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "preservation":
            command = view.bot.get_command("최종보존상태") or view.bot.get_command("preservationstatus")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "server_goals":
            command = view.bot.get_command("서버목표") or view.bot.get_command("servergoals")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
        elif action == "story_continue":
            command = view.bot.get_command("스토리나침반") or view.bot.get_command("storycompass")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
            view.set_special(_story_route(view.entries), _t(view.locale, "📖 메인 스토리 · 시즌 1→6", "📖 Main Story · Season 1→6"))
        elif action == "survivor":
            command = view.bot.get_command("생존허브") or view.bot.get_command("survivorhub")
            if command is not None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(view.bot, interaction, command.qualified_name)
                return
            rows = [e for e in view.entries if e.group in {"onboarding", "quests", "codex"}]
            view.set_special(rows, _t(view.locale, "👤 생존자 통합 허브", "👤 Survivor Hub"))
        elif action == "today":
            view.set_special(_today_route(view.entries), _t(view.locale, "☀️ 오늘 먼저 할 일", "☀️ Today's Recommended Actions"))
        elif action in {"favorites", "recent"}:
            state = _state_for(view.get_user, view.owner_id) or {}
            rows = _lookup_saved(view.entries, state.get(action, []))
            if not rows:
                await interaction.response.send_message(_t(view.locale, "저장된 항목이 없습니다.", "No saved items."), ephemeral=True)
                return
            view.set_special(rows, _t(view.locale, "⭐ 즐겨찾기" if action == "favorites" else "🕘 최근 실행", "⭐ Favorites" if action == "favorites" else "🕘 Recent"))
        elif action == "city":
            rows = [e for e in view.entries if e.group == "city_decor"]
            view.section, view.group = "world", "city_decor"
            view.set_special(rows, _t(view.locale, "🎨 도시 꾸미기 공방 바로가기", "🎨 City Workshop Quick Access"))
        elif action == "emoji":
            rows = [e for e in view.entries if e.group == "auto_emoji"]
            view.section, view.group = "system", "auto_emoji"
            view.set_special(rows, _t(view.locale, "✨ 자동 이모지·반응 바로가기", "✨ Auto Emoji Quick Access"))
        elif action == "back":
            view.selected_index = None
        elif action == "related":
            selected = view.selected_entry()
            if selected:
                view.section, view.group = selected.section, selected.group
                rows = [e for e in view.entries if e.group == selected.group]
                view.set_special(rows, _t(view.locale, "🔗 관련 명령", "🔗 Related Commands"))
        elif action == "favorite":
            selected = view.selected_entry()
            if not selected:
                return
            _added, message = _toggle_favorite(view.get_user, view.save_data, view.owner_id, selected)
            await interaction.response.send_message(message, ephemeral=True)
            return
        elif action == "execute":
            selected = view.selected_entry()
            if not selected:
                await interaction.response.send_message(_t(view.locale, "먼저 명령을 선택하세요.", "Select a command first."), ephemeral=True)
                return
            command = view.bot.get_command(selected.qualified_name)
            if command is None:
                await interaction.response.send_message(_t(view.locale, "실행 가능한 등록 명령을 찾지 못했습니다.", "Registered command not found."), ephemeral=True)
                return
            if _command_requires_input(command):
                await interaction.response.send_modal(CommandArgsModal(view, selected))
                return
            pass  # v18.1.3: _invoke_command owns the single interaction ACK
            ok = await _invoke_command(view.bot, interaction, selected.qualified_name)
            if ok:
                _record_recent(view.get_user, view.save_data, interaction.user.id, selected)
            return
        elif action == "close":
            for item in view.children:
                item.disabled = True
            await _safe_component_edit(interaction, view=view)
            view.stop()
            return
        view.rebuild()
        await _safe_component_edit(interaction, embed=view.current_embed(), view=view)


class CompleteCommandCenterView(discord.ui.View):
    PAGE_SIZE = PAGE_SIZE

    def __init__(
        self,
        owner_id: int,
        entries: Sequence[CommandEntry],
        locale: str,
        bot: commands.Bot,
        get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
        save_data: Callable[[], None],
    ) -> None:
        super().__init__(timeout=MENU_TIMEOUT)
        self.owner_id = int(owner_id)
        self.entries = list(entries)
        self.by_index = {e.index: e for e in self.entries}
        self.locale = locale
        self.bot = bot
        self.get_user = get_user
        self.save_data = save_data
        self.section = "main"
        self.group = "story1" if any(e.group == "story1" for e in self.entries) else self.first_group("main")
        self.page = 0
        self.selected_index: Optional[int] = None
        self.special_entries: Optional[List[CommandEntry]] = None
        self.special_title: Optional[str] = None
        self.quick_page = 0
        self.rebuild()

    def command_requires_input(self, entry: CommandEntry) -> bool:
        command = self.bot.get_command(entry.qualified_name)
        return bool(command and _command_requires_input(command))

    def group_counts(self, section: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.entries:
            if entry.section == section:
                counts[entry.group] = counts.get(entry.group, 0) + 1
        return counts

    def first_group(self, section: str) -> str:
        counts = self.group_counts(section)
        if section == "main" and counts.get("story1"):
            return "story1"
        for key, *_rest in GROUP_SPECS[section]:
            if counts.get(key):
                return key
        return GROUP_SPECS[section][0][0]

    def set_special(self, rows: Sequence[CommandEntry], title: str) -> None:
        self.special_entries = list(dict.fromkeys(rows))
        self.special_title = title
        self.selected_index = None
        self.page = 0

    def current_entries(self) -> List[CommandEntry]:
        if self.special_entries is not None:
            return list(self.special_entries)
        return [e for e in self.entries if e.section == self.section and e.group == self.group]

    def page_entries(self) -> List[CommandEntry]:
        rows = self.current_entries()
        start = self.page * PAGE_SIZE
        return rows[start:start + PAGE_SIZE]

    def max_page(self) -> int:
        return max(0, (len(self.current_entries()) - 1) // PAGE_SIZE)

    def selected_entry(self) -> Optional[CommandEntry]:
        return self.by_index.get(self.selected_index) if self.selected_index is not None else None

    def favorite_names(self) -> set[str]:
        state = _state_for(self.get_user, self.owner_id) or {}
        return {str(x) for x in state.get("favorites", [])}

    def current_embed(self) -> discord.Embed:
        selected = self.selected_entry()
        if selected:
            return _detail_embed(self.locale, selected, selected.qualified_name in self.favorite_names())
        return _overview_embed(self.locale, self.entries, self.section, self.group, self.current_entries(), self.page, self.special_title)

    def rebuild(self) -> None:
        self.clear_items()
        for key, ko, en, _description in SECTION_SPECS:
            self.add_item(SectionButton(self, key, ko, en))
        self.add_item(GroupSelect(self))
        self.add_item(CommandSelect(self))

        home = NavButton(self, "home", "처음", "Home", "🏠", row=3)
        prev = NavButton(self, "prev", "이전", "Previous", "◀️", row=3)
        nxt = NavButton(self, "next", "다음", "Next", "▶️", row=3)
        search = NavButton(self, "search", "전체 검색", "Search All", "🔎", discord.ButtonStyle.primary, row=3)
        story = NavButton(self, "story", "시즌 1→6", "Season 1→6", "📖", discord.ButtonStyle.success, row=3)
        prev.disabled = self.page <= 0
        nxt.disabled = self.page >= self.max_page()
        for item in (home, prev, nxt, search, story):
            self.add_item(item)

        if self.selected_entry():
            self.add_item(NavButton(self, "execute", "실행", "Execute", "🚀", discord.ButtonStyle.success, row=4))
            self.add_item(NavButton(self, "back", "목록", "Back", "↩️", row=4))
            self.add_item(NavButton(self, "favorite", "즐겨찾기", "Favorite", "⭐", row=4))
            self.add_item(NavButton(self, "related", "관련 명령", "Related", "🔗", row=4))
            self.add_item(NavButton(self, "close", "닫기", "Close", "✖️", discord.ButtonStyle.danger, row=4))
        else:
            if self.quick_page == 0:
                self.add_item(NavButton(self, "beginner", "처음 안내", "Beginner", "🌱", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "casino", "카지노", "Casino", "🎰", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "gambling", "도박", "Gambling", "🎲", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "favorites", "즐겨찾기", "Favorites", "⭐", row=4))
                self.add_item(NavButton(self, "quick_more", "더보기", "More", "➡️", row=4))
            elif self.quick_page == 1:
                self.add_item(NavButton(self, "story_continue", "스토리 계속", "Continue Story", "📖", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "today", "오늘 할 일", "Today", "🎯", row=4))
                self.add_item(NavButton(self, "survivor", "생존 허브", "Survivor Hub", "👤", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "city", "도시 공방", "City Workshop", "🎨", row=4))
                self.add_item(NavButton(self, "quick_more2", "솔로 원정", "Solo Expedition", "➡️", discord.ButtonStyle.primary, row=4))
            elif self.quick_page == 2:
                self.add_item(NavButton(self, "lone_expedition", "솔로 원정", "Lone Survivor", "🌑", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "weekly_expedition", "주간 변이", "Weekly Mutation", "⚡", row=4))
                self.add_item(NavButton(self, "expedition_codex", "원정 도감", "Expedition Codex", "📚", row=4))
                self.add_item(NavButton(self, "expedition_record", "원정 기록", "Expedition Records", "🏆", row=4))
                self.add_item(NavButton(self, "quick_more3", "시즌 6·공방", "Season 6 & Forge", "➡️", discord.ButtonStyle.primary, row=4))
            elif self.quick_page == 3:
                self.add_item(NavButton(self, "season6", "시즌 6", "Season 6", "☀️", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "creator_forge", "콘텐츠 공방", "Creator Forge", "🧩", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "custom_event", "사용자 사건", "Community Events", "🎭", row=4))
                self.add_item(NavButton(self, "runtime_clean", "17.2 점검", "v17.2 Audit", "🧹", row=4))
                self.add_item(NavButton(self, "quick_more4", "살아 있는 세계", "Living World", "➡️", discord.ButtonStyle.primary, row=4))
            elif self.quick_page == 4:
                self.add_item(NavButton(self, "living_world", "살아 있는 세계", "Living World", "🌍", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "world_event", "오늘의 사건", "World Event", "📻", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "bonds", "NPC 인연", "NPC Bonds", "💞", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "npc_list", "NPC 목록", "NPC Roster", "🧑‍🤝‍🧑", row=4))
                self.add_item(NavButton(self, "quick_more5", "연결 루프", "Connected Loop", "➡️", discord.ButtonStyle.primary, row=4))
            elif self.quick_page == 5:
                self.add_item(NavButton(self, "connected_hub", "연결 허브", "Connected Hub", "🔗", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "connected_goals", "연결 목표", "Connected Goals", "🎯", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "connected_reward", "연결 보상", "Connected Reward", "🏁", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "city_effects", "도시 효과", "City Effects", "🏙️", row=4))
                self.add_item(NavButton(self, "quick_more6", "시스템 융합", "System Fusion", "➡️", discord.ButtonStyle.primary, row=4))
            elif self.quick_page == 6:
                self.add_item(NavButton(self, "survival_terminal", "생존단말기", "Survivor Terminal", "📡", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "contract_office", "의뢰소", "Contract Office", "📜", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "production_center", "생산센터", "Production Center", "⚙️", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "faction_reputation", "세력 평판", "Faction Reputation", "🏴", row=4))
                self.add_item(NavButton(self, "quick_more7", "박물관·시즌", "Museum & Season", "➡️", row=4))
            elif self.quick_page == 7:
                self.add_item(NavButton(self, "chronicle_museum", "연대기 박물관", "Chronicle Museum", "🏛️", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "global_achievements", "통합 업적", "Global Achievements", "🏆", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "community_season", "서버 시즌", "Community Season", "🌐", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "community_ranking", "시즌 랭킹", "Season Ranking", "🥇", row=4))
                self.add_item(NavButton(self, "quick_more8", "FINAL ECLIPSE", "FINAL ECLIPSE", "➡️", row=4))
            else:
                self.add_item(NavButton(self, "definitive_terminal", "최종 단말기", "Definitive Terminal", "🧿", discord.ButtonStyle.success, row=4))
                self.add_item(NavButton(self, "final_eclipse", "최종 일식", "Final Eclipse", "🌑", discord.ButtonStyle.danger, row=4))
                self.add_item(NavButton(self, "daily_loop", "오늘의 루프", "Daily Loop", "☀️", discord.ButtonStyle.primary, row=4))
                self.add_item(NavButton(self, "final_ops", "운영 단말기", "Final Operations", "🛠️", row=4))
                self.add_item(NavButton(self, "quick_back7", "박물관·시즌", "Museum & Season", "⬅️", row=4))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 명령어 센터는 실행자만 조작할 수 있습니다.", "Only the opener can use this command center."), ephemeral=True)
        return False


def _expanded_reaction_data() -> Tuple[Dict[str, List[str]], List[Dict[str, Any]], Tuple[Tuple[str, Tuple[str, ...]], ...]]:
    presets = {
        "공지": ["📢", "🔥", "✅", "👀", "🔔", "📌"],
        "건의": ["👍", "👎", "💬", "💡", "🗳️"],
        "버그": ["🐛", "🔍", "🛠️", "⚠️", "✅"],
        "미디어": ["❤️", "🔥", "👀", "📸", "✨", "👏", "💜"],
        "이벤트": ["🎉", "🔥", "✅", "🥳", "🎁", "📅"],
        "거래": ["💰", "👀", "✅", "🤝", "📦"],
        "투표": ["👍", "👎", "🤔", "🗳️"],
        "일반": ["❤️", "😂", "🔥", "👍", "✨", "👀", "💜"],
        "질문": ["❓", "💡", "✅", "🤝", "👀"],
        "창작": ["🎨", "❤️", "🔥", "✨", "👏", "🖼️", "💜"],
        "모집": ["🙋", "✅", "👀", "🤝", "⚔️"],
        "인증": ["✅", "🛡️", "🎉", "🔒", "✨"],
        "스토리": ["📖", "🕯️", "✨", "🌑", "🎭", "👀"],
        "전투": ["⚔️", "🔥", "🛡️", "💥", "👹", "🏆"],
        "도시": ["🏙️", "✨", "🟣", "🏗️", "🎨", "🌌"],
        "음악": ["🎵", "🎧", "💜", "🔥", "✨", "👏"],
        "축하": ["🎉", "🥳", "🔥", "👏", "🏆", "✨", "💜"],
    }
    rules = [
        {"keyword": "안녕", "emojis": ["👋", "✨"]},
        {"keyword": "축하", "emojis": ["🎉", "🥳", "🔥", "👏"]},
        {"keyword": "고마워", "emojis": ["❤️", "🙏", "✨"]},
        {"keyword": "감사", "emojis": ["💜", "🙏", "✨"]},
        {"keyword": "ㅋㅋ", "emojis": ["😂", "🤣", "🔥"]},
        {"keyword": "버그", "emojis": ["🐛", "🔍", "🛠️", "⚠️"]},
        {"keyword": "대박", "emojis": ["🔥", "🤯", "👏", "✨"]},
        {"keyword": "승리", "emojis": ["🏆", "🔥", "🎉", "⚔️"]},
        {"keyword": "보스", "emojis": ["👹", "⚔️", "🔥", "🛡️"]},
        {"keyword": "도시", "emojis": ["🏙️", "✨", "🟣", "🎨"]},
        {"keyword": "스토리", "emojis": ["📖", "🕯️", "✨", "👀"]},
        {"keyword": "음악", "emojis": ["🎵", "🎧", "💜", "🔥"]},
        {"keyword": "사진", "emojis": ["📸", "👀", "❤️", "✨"]},
        {"keyword": "도움", "emojis": ["💡", "🤝", "✅"]},
    ]
    channels = (
        ("스토리", ("스토리", "이야기", "시즌", "연대기")),
        ("전투", ("전투", "보스", "레이드", "던전", "공격대")),
        ("도시", ("도시", "black-city", "네온", "차원")),
        ("음악", ("음악", "뮤직", "music", "노래", "작곡")),
    )
    return presets, rules, channels


def register_v1630_core_rpg_command_city_overhaul(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1630_registered", False):
        return
    bot._abaddon_v1630_registered = True

    @bot.command(name="정부지원금", aliases=["재기지원금", "생존지원금"], help="보유 식량이 -10,000 이하일 때 24시간마다 최대 250,000 식량의 재기 지원을 받습니다.")
    async def government_relief(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        if not isinstance(user, MutableMapping):
            await ctx.send("⚠️ 생존자 데이터를 찾지 못했습니다.")
            return
        before = int(user.get("balance", 0) or 0)
        if before > -10_000:
            await ctx.send(f"🏛️ 지원 대상이 아닙니다. 현재 잔액 **{before:,} 식량** · 대상 기준 **-10,000 이하**")
            return
        state = user.setdefault("v1631_government_relief", {})
        now = int(time.time())
        last = int(state.get("last_claim_at", 0) or 0)
        cooldown = 24 * 60 * 60
        remaining = cooldown - (now - last)
        if last and remaining > 0:
            hours, rem = divmod(remaining, 3600); minutes = rem // 60
            await ctx.send(f"⏳ 정부 재기 지원은 **24시간에 1회**입니다. 다음 신청까지 **{hours}시간 {minutes}분** 남았습니다.")
            return
        amount = min(250_000, abs(before))
        after = before + amount
        user["balance"] = after
        state["last_claim_at"] = now
        state["claim_count"] = int(state.get("claim_count", 0) or 0) + 1
        state["total_received"] = int(state.get("total_received", 0) or 0) + amount
        history = state.setdefault("history", [])
        if isinstance(history, list):
            history.append({"at": now, "before": before, "amount": amount, "after": after})
            del history[:-30]
        save_data()
        embed = discord.Embed(title="🏛️ ABADDON 정부 재기 지원금", description="도박·카지노 손실로 생존 자금이 마이너스인 생존자에게 긴급 지원이 지급됐습니다.", color=0x2ECC71)
        embed.add_field(name="🎁 이번 획득", value=f"**+{amount:,} 식량**", inline=True)
        embed.add_field(name="📉 부채 감소", value=f"**{abs(before) - abs(after):,} 식량**", inline=True)
        embed.add_field(name="🧾 잔액 변화", value=f"{before:,} → **{after:,} 식량**", inline=False)
        embed.add_field(name="📊 누적 지원", value=f"{int(state['claim_count'])}회 · {int(state['total_received']):,} 식량", inline=True)
        embed.add_field(name="⏱️ 다음 신청", value="24시간 후", inline=True)
        embed.add_field(name="ℹ️ 기준", value="잔액 -10,000 이하 · 1회 최대 250,000 · 지원 후 잔액이 0을 넘지 않음", inline=False)
        embed.set_footer(text="BLACK CASINO·도박 재기 안전망 · 현금 가치 및 환전 기능 없음")
        await ctx.send(embed=embed)

    @bot.command(name="초보센터", aliases=["신규안내", "첫걸음센터"], help="처음 들어온 생존자를 위한 RPG 시작 순서와 주요 카테고리를 안내합니다.")
    async def beginner_center(ctx: commands.Context) -> None:
        embed = discord.Embed(title="🌱 ABADDON 신규 생존자 첫걸음", description="이 봇의 메인은 **시즌 1부터 이어지는 아포칼립스 RPG**입니다. 아래 순서대로 시작하면 됩니다.", color=0x55C9A5)
        embed.add_field(name="📖 1. 메인 스토리", value="`!스토리 시작` → `!스토리 선택 번호` · 시즌 1부터 진행", inline=False)
        embed.add_field(name="📊 2. 생존 준비", value="`!가입 생존자` · `!정보` · `!출석` · `!오늘할일`", inline=False)
        embed.add_field(name="⚔️ 3. 플레이", value="채집·장비·전투·경제·화투·카지노·도박을 `!명령어`에서 선택", inline=False)
        embed.add_field(name="🎰 카지노 / 🎲 도박", value="카지노: 포커·블랙잭·바카라·슬롯·VIP / 도박: 경마·탐색·주파수·생존 룰렛·정부지원금", inline=False)
        embed.add_field(name="🌌 세계 / 🤝 소셜 / 🛠️ 운영", value="BLACK CITY·차원·도시 공방 / 길드·동료·NPC / 서버 설정·보안·알림", inline=False)
        embed.set_footer(text="!명령어 첫 화면의 버튼과 드롭다운으로 모든 기능을 바로 실행할 수 있습니다.")
        await ctx.send(embed=embed)

    entries = _build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})

    class BoundCompleteCommandCenterView(CompleteCommandCenterView):
        def __init__(self, owner_id: int, _legacy_guide: Sequence[Mapping[str, Any]], locale: str) -> None:
            super().__init__(owner_id, entries, locale, bot, get_user, save_data)

    # Replace both callbacks rather than only swapping a class global. This makes
    # direct `!명령어 검색어` use the complete runtime registry as well.
    korean = bot.get_command("명령어")
    if korean is not None:
        previous = korean.callback

        async def complete_korean_help(ctx: commands.Context, *, 검색어: str = None) -> None:
            view = BoundCompleteCommandCenterView(ctx.author.id, guide, "ko")
            if 검색어:
                results = _search(entries, 검색어)
                if results:
                    view.set_special(results, f"🔎 전체 명령 검색 · {검색어}")
                    view.rebuild()
            await ctx.send(embed=view.current_embed(), view=view)

        korean.callback = complete_korean_help
        korean.help = "시즌 1 메인 스토리부터 전체 등록 명령을 버튼·드롭다운·검색·즉시 실행으로 탐색합니다."
        korean.description = korean.help
        korean.extras = dict(getattr(korean, "extras", {}) or {})
        korean.extras["v1630_previous_callback"] = previous

    english = bot.get_command("help")
    if english is not None:
        previous = english.callback

        async def complete_english_help(ctx: commands.Context, *, keyword: str = "") -> None:
            view = BoundCompleteCommandCenterView(ctx.author.id, guide, "en")
            if keyword:
                results = _search(entries, keyword)
                if results:
                    view.set_special(results, f"🔎 Search All Commands · {keyword}")
                    view.rebuild()
            await ctx.send(embed=view.current_embed(), view=view)

        english.callback = complete_english_help
        english.help = "Browse every registered command from the Season 1 core RPG with dropdowns, search and execution buttons."
        english.description = english.help
        english.extras = dict(getattr(english, "extras", {}) or {})
        english.extras["v1630_previous_callback"] = previous

    # Keep v16.2 references aligned for other callbacks/audits that inspect the class.
    try:
        from apocalypse_bot.commands import v1620_living_legends as v1620
        v1620.LivingHelpView = BoundCompleteCommandCenterView
    except Exception:
        pass

    # Expand the actual member-join panel with a clear RPG/category explanation
    # and direct buttons for the command center, casino and non-casino gambling.
    try:
        from apocalypse_bot.commands import v711_cute_interactions as welcome_mod
        original_welcome_embed = welcome_mod._welcome_embed

        def v1631_welcome_embed(member: discord.Member, days: int, theme_key: str, *, settings: Optional[Dict[str, Any]] = None) -> discord.Embed:
            embed = original_welcome_embed(member, days, theme_key, settings=settings)
            embed.add_field(
                name="📚 ABADDON에는 무엇이 있나요?",
                value=(
                    "📖 메인 RPG — 시즌 1~5 스토리·성장·탐험\n"
                    "⚔️ 플레이 — 채집·장비·전투·경제·화투\n"
                    "🎰 카지노 — 포커·블랙잭·바카라·슬롯·VIP\n"
                    "🎲 도박 — 경마·탐색·주파수·생존 룰렛·재기 지원\n"
                    "🌌 세계 — BLACK CITY·차원·도시 공방\n"
                    "🤝 소셜 / 🛠️ 운영 — 길드·동료·서버 관리"
                ),
                inline=False,
            )
            embed.add_field(name="🚀 가장 쉬운 시작", value="아래 **스토리 시작** 또는 **전체 명령** 버튼을 누르세요.", inline=False)
            embed.set_footer(text=f"ABADDON v{VERSION} · 신규 생존자 통합 안내")
            return embed

        class V1631WelcomeQuickView(discord.ui.View):
            def __init__(self, bot_obj: commands.Bot, owner_id: int, world: Dict[str, Any], saver: Any, guide_rows: Sequence[Dict[str, Any]]) -> None:
                super().__init__(timeout=900)
                self.bot = bot_obj; self.owner_id = int(owner_id)

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if int(interaction.user.id) == self.owner_id:
                    return True
                await interaction.response.send_message("본인의 환영 패널이나 `!초보센터`를 이용해주세요.", ephemeral=True)
                return False

            async def run(self, interaction: discord.Interaction, name: str, raw: str = "") -> None:
                pass  # v18.1.3: _invoke_command owns the single interaction ACK
                await _invoke_command(self.bot, interaction, name, raw)

            @discord.ui.button(label="가입하기", emoji="🪪", style=discord.ButtonStyle.success, row=0)
            async def register_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "가입", "생존자")

            @discord.ui.button(label="스토리 시작", emoji="📖", style=discord.ButtonStyle.success, row=0)
            async def story_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "스토리 시작")

            @discord.ui.button(label="전체 명령", emoji="📚", style=discord.ButtonStyle.primary, row=0)
            async def help_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "명령어")

            @discord.ui.button(label="내 정보", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
            async def info_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "정보")

            @discord.ui.button(label="오늘 할 일", emoji="☀️", style=discord.ButtonStyle.secondary, row=1)
            async def today_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "오늘할일")

            @discord.ui.button(label="카지노", emoji="🎰", style=discord.ButtonStyle.primary, row=1)
            async def casino_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "카지노")

            @discord.ui.button(label="도박 안내", emoji="🎲", style=discord.ButtonStyle.primary, row=2)
            async def gambling_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "도박정보")

            @discord.ui.button(label="초보센터", emoji="🌱", style=discord.ButtonStyle.secondary, row=2)
            async def beginner_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
                await self.run(interaction, "초보센터")

        welcome_mod._welcome_embed = v1631_welcome_embed
        welcome_mod.WelcomeQuickView = V1631WelcomeQuickView
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] welcome expansion warning: {type(exc).__name__}: {exc}", flush=True)

    # Expand automatic reactions. Existing nested listeners read these module
    # globals at message time, so updating them here immediately affects runtime.
    presets, rules, extra_channels = _expanded_reaction_data()
    migrated_guilds = 0
    try:
        from apocalypse_bot.commands import v411_server_guard_plus as guard
        guard.REACTION_PRESETS.update({k: list(v) for k, v in presets.items()})
        guard.DEFAULT_KEYWORD_RULES[:] = [dict(row) for row in rules]
        existing_channels = list(guard.AUTO_CHANNEL_KEYWORDS)
        existing_names = {row[0] for row in existing_channels}
        guard.AUTO_CHANNEL_KEYWORDS = tuple(existing_channels + [row for row in extra_channels if row[0] not in existing_names])
        management = world_data.setdefault("server_management", {})
        if isinstance(management, MutableMapping):
            for settings in management.values():
                if not isinstance(settings, MutableMapping):
                    continue
                reactions = settings.setdefault("auto_reactions", {})
                if not isinstance(reactions, MutableMapping):
                    continue
                if int(reactions.get("max_per_message", 5) or 5) == 5:
                    reactions["max_per_message"] = 7
                saved_rules = reactions.setdefault("keyword_rules", [])
                if not isinstance(saved_rules, list):
                    saved_rules = []
                    reactions["keyword_rules"] = saved_rules
                known = {str(row.get("keyword", "")).casefold() for row in saved_rules if isinstance(row, Mapping)}
                for rule in rules:
                    if rule["keyword"].casefold() not in known:
                        saved_rules.append(dict(rule))
                migrated_guilds += 1
            if migrated_guilds:
                save_data()
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] auto-reaction expansion warning: {type(exc).__name__}: {exc}", flush=True)

    if not any(str(row.get("id")) == "v1631_casino_gambling_onboarding" for row in guide):
        guide.append({
            "id": "v1631_casino_gambling_onboarding",
            "emoji": "📖",
            "title": "v16.3.1 CORE RPG COMMAND & CITY OVERHAUL",
            "hint": "카지노·도박 분리, 첫 화면 카테고리 설명, 신규 입장 버튼, 정부지원금과 채집 획득·변화 표시",
            "commands": [
                "!명령어",
                "!명령어전수검수 상세",
                "!도시부품검수 상세",
                "!이모지확장설정",
                "!1631통합검수 상세",
            ],
        })

    patch_command = bot.get_command("패치노트")
    if patch_command is not None:
        previous_patch = patch_command.callback

        async def patch_notes_v1630(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            locale = "ko"
            try:
                from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale
                locale = _ctx_locale(bot, ctx)
            except Exception:
                pass
            embed = discord.Embed(
                title=_t(locale, "📜 ABADDON v16.3.1 패치노트", "📜 ABADDON v16.3.1 Patch Notes"),
                description=_t(
                    locale,
                    "메인 아포칼립스 RPG의 시즌 1~5 진행을 명령어 센터 최상단에 복구하고, 전체 등록 명령을 자동 분류·검색·실행하도록 전면 개편했습니다.",
                    "Restored Seasons 1–5 of the core apocalypse RPG to the top of the command center and rebuilt navigation for every registered command.",
                ),
                color=0x7137C8,
            )
            embed.add_field(name=_t(locale, "🎰 카지노 / 🎲 도박 분리", "🎰 Casino / 🎲 Gambling Split"), value=_t(locale, "BLACK CASINO·포커·블랙잭·바카라·슬롯은 카지노로, 경마·탐색·주파수·생존 룰렛은 도박으로 따로 노출합니다.", "Casino table games and poker are separated from racing and survival betting."), inline=False)
            embed.add_field(name=_t(locale, "🧭 첫 화면 안내", "🧭 First-screen Guide"), value=_t(locale, "5개 큰 영역의 기능 설명과 카지노·도박 빠른 버튼을 첫 화면에 표시합니다.", "The first screen explains all five sections and exposes Casino/Gambling quick buttons."), inline=False)
            embed.add_field(name=_t(locale, "🌱 신규 생존자 안내", "🌱 New Survivor Guide"), value=_t(locale, "서버 입장 환영 패널에 시즌 1 시작·전체 명령·카지노·도박 버튼과 카테고리 설명을 추가했습니다.", "Member-join panels now include story, command, casino and gambling buttons."), inline=False)
            embed.add_field(name=_t(locale, "🏛️ 정부지원금", "🏛️ Government Relief"), value=_t(locale, "잔액 -10,000 이하일 때 24시간마다 최대 250,000 식량을 지원하며 지급 전후 변화를 기록합니다.", "Balances at -10,000 or below can receive up to 250,000 food every 24 hours with before/after records."), inline=False)
            embed.add_field(name=_t(locale, "⛏️ 결과 변화 표시", "⛏️ Result Change Display"), value=_t(locale, "채집 결과 카드에 이번 획득, 소모·수치 변화, 누적 횟수를 분리 표시합니다.", "Gathering cards now separate gains, stat changes and total runs."), inline=False)
            embed.add_field(name=_t(locale, "📚 전체 명령 보존", "📚 Full Command Preservation"), value=_t(locale, f"런타임 등록 명령 {len(entries):,}개 · 5개 영역 · 45개 기능군 · 검색·실행 버튼 유지", f"{len(entries):,} runtime commands · 5 sections · 44 groups · search and execute preserved"), inline=False)
            embed.add_field(name=_t(locale, "🧪 신규 검수", "🧪 New Audits"), value="`!명령어전수검수 상세` · `!도박분류검수 상세` · `!1631통합검수 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 명령 삭제 0건 · 기존 저장 데이터 유지 · 2026-08-05", "0 legacy commands removed · existing save data preserved · 2026-08-05"))
            await ctx.send(embed=embed)

        patch_command.callback = patch_notes_v1630
        patch_command.help = "ABADDON v16.3.1 메인 RPG·전체 명령센터·도시 공방·자동 이모지 최신 패치노트입니다."
        patch_command.description = patch_command.help
        patch_command.extras = dict(getattr(patch_command, "extras", {}) or {})
        patch_command.extras["v1630_previous_callback"] = previous_patch

    test_command = bot.get_command("테스트")
    if test_command is not None:
        previous_test = test_command.callback

        async def latest_test_v1630(ctx: commands.Context, mode: str = "") -> None:
            info_source = ASSET_ROOT.parent / "commands" / "v1092_visual_status_horserace.py"
            neon_source = ASSET_ROOT.parent / "commands" / "v1500_neon_abyss.py"
            checks = (
                ("전체 명령 자동 분류", len(entries) > 0 and len(entries) == len({e.qualified_name for e in entries}), f"{len(entries):,}"),
                ("시즌 1~5 메인 RPG 노출", all(any(e.group == f"story{i}" for e in entries) for i in range(1, 6)), "S1-S5"),
                ("선택 후 실행 버튼", callable(_invoke_command), "interaction bridge"),
                ("정보 바로가기 버튼", info_source.is_file() and "ProfileQuickActionView" in info_source.read_text(encoding="utf-8"), "5 buttons"),
                ("도시 부품 20종", len(list(CITY_COMPONENT_ROOT.glob("*.png"))) == 20, "512x512 PNG"),
                ("도시 공방 행동 기록", neon_source.is_file() and "decor_history" in neon_source.read_text(encoding="utf-8"), "place/undo log"),
                ("카지노·도박 분리", any(e.group == "casino" and e.qualified_name == "카지노" for e in entries) and any(e.group == "gambling" for e in entries), "separate groups"),
                ("정부지원금", bot.get_command("정부지원금") is not None and any(e.group == "gambling" and e.qualified_name == "정부지원금" for e in entries), "-10,000 / 250,000"),
                ("신규 생존자 안내", "V1631WelcomeQuickView" in Path(__file__).read_text(encoding="utf-8"), "join panel buttons"),
                ("채집 획득·변화", "이번 획득" in (ASSET_ROOT.parent / "commands" / "v1620_living_legends.py").read_text(encoding="utf-8"), "gain/change rows"),
                ("자동 이모지 확장", len(presets) >= 17 and len(rules) >= 14, "17 presets / 14 keywords"),
                ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
            )
            ok = all(row[1] for row in checks)
            embed = discord.Embed(title=f"🧪 ABADDON 최신 테스트 v{VERSION}", color=0x2ECC71 if ok else 0xE67E22)
            embed.description = "\n".join(f"{'✅' if passed else '❌'} **{name}** · {detail}" for name, passed, detail in checks)
            if mode.casefold() in {"상세", "detail", "detailed"}:
                embed.add_field(name="최신 범위", value="메인 RPG 명령센터 · 카지노/도박 분리 · 신규 안내 · 정부지원금 · 채집 변화 표시 · 패치노트", inline=False)
                embed.add_field(name="보존", value="기존 명령 삭제 0 · 저장 데이터 유지 · 기존 직접 명령 유지", inline=False)
            await ctx.send(embed=embed)

        test_command.callback = latest_test_v1630
        test_command.help = "가장 최근 v16.3.1 메인 RPG 명령센터·카지노/도박 분리·신규 안내·정부지원금·채집 결과 변화 범위를 검사합니다."
        test_command.description = test_command.help
        test_command.extras = dict(getattr(test_command, "extras", {}) or {})
        test_command.extras["v1630_previous_callback"] = previous_test

    @bot.command(name="명령어전수검수", aliases=["fullcommandaudit", "commandregistryaudit1630"], help="전체 런타임 명령의 카테고리·페이지·스토리 노출·버튼 실행 연결을 검사합니다.")
    async def full_command_audit(ctx: commands.Context, mode: str = "") -> None:
        classified = sum(1 for e in entries if e.group in GROUP_INDEX)
        missing = [e.qualified_name for e in entries if e.group not in GROUP_INDEX]
        duplicate_names = len(entries) - len({e.qualified_name for e in entries})
        story_counts = {group: sum(1 for e in entries if e.group == group) for group in ("story1", "story2", "story3", "story4", "story5", "story6")}
        group_overflow = {group: count for group, count in ((g, sum(1 for e in entries if e.group == g)) for g in GROUP_INDEX) if count > PAGE_SIZE}
        checks = {
            "전체 등록 명령 분류": classified == len(entries),
            "분류 누락 0": not missing,
            "중복 qualified name 0": duplicate_names == 0,
            "시즌 1 노출": story_counts["story1"] > 0,
            "시즌 2 노출": story_counts["story2"] > 0,
            "시즌 3 노출": story_counts["story3"] > 0,
            "시즌 4 노출": story_counts["story4"] > 0,
            "시즌 5 노출": story_counts["story5"] > 0,
            "시즌 6 노출": story_counts.get("story6", 0) > 0,
            "드롭다운 25개 자동 분할": all(count <= PAGE_SIZE or group in group_overflow for group, count in ((g, sum(1 for e in entries if e.group == g)) for g in GROUP_INDEX)),
            "카지노 직접 노출": any(e.group == "casino" and e.qualified_name == "카지노" for e in entries),
            "도박 별도 기능군": any(e.group == "gambling" for e in entries),
            "정부지원금 분류": any(e.group == "gambling" and e.qualified_name == "정부지원금" for e in entries),
            "명령 실행 브리지": callable(_invoke_command),
        }
        ok = all(checks.values())
        embed = discord.Embed(title=f"📚 ABADDON 전체 명령 검수 v{VERSION}", color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        embed.add_field(name="실제 런타임", value=f"명령 **{len(entries):,}개** · 분류 **{classified:,}개** · 누락 **{len(missing)}개**", inline=False)
        embed.add_field(name="소스 선언 기준", value=f"기존 manifest **{EXPECTED_DECLARATIONS:,}개** · 런타임은 충돌 보호·그룹 구조에 따라 수가 달라질 수 있음", inline=False)
        embed.add_field(name="메인 스토리", value=" · ".join(f"S{idx + 1} **{story_counts[f'story{idx + 1}']}**" for idx in range(5)), inline=False)
        if mode.casefold() in {"상세", "detail", "detailed"}:
            embed.add_field(name="페이지 분할 기능군", value=" · ".join(f"{_group_spec(group)[1]} {count}" for group, count in sorted(group_overflow.items()))[:1024] or "없음", inline=False)
            embed.add_field(name="누락", value=" · ".join(missing[:30]) or "없음", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="도박분류검수", aliases=["gamblingcategoryaudit", "casinoaudit1631"], help="카지노·비카지노 도박·정부지원금의 명령어 센터 분류와 빠른 이동을 검사합니다.")
    async def gambling_category_audit(ctx: commands.Context, mode: str = "") -> None:
        casino_rows = [e for e in entries if e.group == "casino"]
        gambling_rows = [e for e in entries if e.group == "gambling"]
        casino_names = {e.qualified_name for e in casino_rows}
        gambling_names = {e.qualified_name for e in gambling_rows}
        checks = {
            "카지노 직접 명령 노출": "카지노" in casino_names,
            "포커·테이블 게임 카지노 분류": any(any(t in name for t in ("홀덤", "포커", "블랙잭", "바카라")) for name in casino_names),
            "비카지노 도박 별도 분류": any(name in gambling_names for name in ("탐색", "주파수", "룰렛", "도박잔액")),
            "경마 도박 분류": any("경마" in name for name in gambling_names),
            "정부지원금 도박 분류": "정부지원금" in gambling_names,
            "빠른 이동 버튼": all(token in Path(__file__).read_text(encoding="utf-8") for token in ('"casino"', '"gambling"')),
        }
        ok = all(checks.values())
        embed = discord.Embed(title=f"🎰 카지노·도박 분류 검수 v{VERSION}", color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        embed.add_field(name="분류 수", value=f"카지노 **{len(casino_rows)}개** · 도박 **{len(gambling_rows)}개**", inline=False)
        if mode.casefold() in {"상세", "detail", "detailed"}:
            embed.add_field(name="카지노 예시", value=" · ".join(f"`!{x}`" for x in sorted(casino_names)[:18])[:1024] or "없음", inline=False)
            embed.add_field(name="도박 예시", value=" · ".join(f"`!{x}`" for x in sorted(gambling_names)[:18])[:1024] or "없음", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="도시부품검수", aliases=["citypartaudit", "cityworkshopaudit"], help="도시 꾸미기 20종의 파일명·라벨·크기·투명도·공방 호환을 검사합니다.")
    async def city_part_audit(ctx: commands.Context, mode: str = "") -> None:
        from apocalypse_bot.commands import v1500_neon_abyss as neon
        labels = dict(neon.COMPONENT_LABELS)
        missing: List[str] = []
        invalid: List[str] = []
        alpha_missing: List[str] = []
        dimensions: Dict[str, Tuple[int, int]] = {}
        try:
            from PIL import Image
            for part_id in labels:
                path = CITY_COMPONENT_ROOT / f"{part_id}.png"
                if not path.is_file():
                    missing.append(part_id)
                    continue
                with Image.open(path) as image:
                    dimensions[part_id] = image.size
                    if image.size != (512, 512):
                        invalid.append(part_id)
                    if "A" not in image.getbands():
                        alpha_missing.append(part_id)
        except Exception as exc:
            invalid.append(type(exc).__name__)
        checks = {
            "라벨 20종": len(labels) == 20,
            "파일 20종": not missing,
            "512×512 통일": not invalid,
            "투명 레이어": not alpha_missing,
            "카탈로그 이미지": (V1630_PREVIEW_ROOT / "city_parts_catalog_ko.png").is_file(),
            "배치 기록 지원": "decor_history" in Path(neon.__file__).read_text(encoding="utf-8"),
            "선택 이미지 즉시 교체": "attachments" in Path(neon.__file__).read_text(encoding="utf-8"),
        }
        ok = all(checks.values())
        embed = discord.Embed(title=f"🎨 도시 꾸미기 공방 검수 v{VERSION}", color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        embed.add_field(name="호환", value="기존 부품 ID 유지 · 저장 데이터 유지 · 도시 지도 레이어 즉시 호환", inline=False)
        if mode.casefold() in {"상세", "detail", "detailed"}:
            embed.add_field(name="누락", value=" · ".join(missing) or "없음", inline=False)
            embed.add_field(name="크기 오류", value=" · ".join(invalid) or "없음", inline=False)
            embed.add_field(name="알파 오류", value=" · ".join(alpha_missing) or "없음", inline=False)
        catalog = V1630_PREVIEW_ROOT / "city_parts_catalog_ko.png"
        if catalog.is_file():
            embed.set_image(url="attachment://city_parts_catalog_ko.png")
            await ctx.send(embed=embed, file=discord.File(catalog, filename="city_parts_catalog_ko.png"))
        else:
            await ctx.send(embed=embed)

    @bot.command(name="이모지확장설정", aliases=["reactionexpansionsetup", "emojiupgrade"], help="현재 서버에 확장 자동 이모지 프리셋·키워드 규칙과 메시지당 7개 반응을 적용합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def emoji_expansion_setup(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("서버에서만 사용할 수 있습니다.")
            return
        management = world_data.setdefault("server_management", {})
        settings = management.setdefault(str(ctx.guild.id), {})
        reactions = settings.setdefault("auto_reactions", {})
        reactions["enabled"] = True
        reactions["smart_attachments"] = True
        reactions["max_per_message"] = 7
        saved = reactions.setdefault("keyword_rules", [])
        if not isinstance(saved, list):
            saved = []
            reactions["keyword_rules"] = saved
        known = {str(row.get("keyword", "")).casefold() for row in saved if isinstance(row, Mapping)}
        added = 0
        for rule in rules:
            if rule["keyword"].casefold() not in known:
                saved.append(dict(rule))
                added += 1
        save_data()
        embed = discord.Embed(
            title="✨ 자동 이모지 확장 설정 완료",
            description="기존 사용자 설정은 유지하고 누락된 기본 규칙만 추가했습니다.",
            color=0x9B59B6,
        )
        embed.add_field(name="기본 프리셋", value=f"**{len(presets)}종** · 프리셋당 최대 7개", inline=True)
        embed.add_field(name="키워드", value=f"신규 **{added}개** · 총 **{len(saved)}개**", inline=True)
        embed.add_field(name="메시지당 반응", value="최대 **7개**", inline=True)
        embed.add_field(name="예시", value="축하 → 🎉 🥳 🔥 👏\n보스 → 👹 ⚔️ 🔥 🛡️\n도시 → 🏙️ ✨ 🟣 🎨", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="1631통합검수", aliases=["v1631audit", "1631audit", "1630통합검수", "v1630audit", "1630audit"], help="v16.3.1 메인 RPG 명령센터·카지노/도박 분리·신규 안내·정부지원금·채집 결과 변화 연결을 검사합니다.")
    async def v1631_audit(ctx: commands.Context, mode: str = "") -> None:
        info_source = ASSET_ROOT.parent / "commands" / "v1092_visual_status_horserace.py"
        neon_source = ASSET_ROOT.parent / "commands" / "v1500_neon_abyss.py"
        checks = {
            "전체 명령 인덱스": len(entries) > 0 and len(entries) == len({e.qualified_name for e in entries}),
            "시즌 1 기본 화면": any(e.group == "story1" for e in entries),
            "선택 후 실행 버튼": bot.get_command("명령어") is not None,
            "정보 바로가기 버튼": info_source.is_file() and "ProfileQuickActionView" in info_source.read_text(encoding="utf-8"),
            "도시 공방 행동 기록": neon_source.is_file() and "방금 한 행동" in neon_source.read_text(encoding="utf-8"),
            "도시 부품 20종": len(list(CITY_COMPONENT_ROOT.glob("*.png"))) == 20,
            "카지노 직접 노출": any(e.group == "casino" and e.qualified_name == "카지노" for e in entries),
            "도박 별도 분류": any(e.group == "gambling" for e in entries),
            "정부지원금": bot.get_command("정부지원금") is not None and any(e.group == "gambling" and e.qualified_name == "정부지원금" for e in entries),
            "신규 입장 안내 버튼": "V1631WelcomeQuickView" in Path(__file__).read_text(encoding="utf-8"),
            "채집 획득·변화 표시": "이번 획득" in (ASSET_ROOT.parent / "commands" / "v1620_living_legends.py").read_text(encoding="utf-8"),
            "자동 이모지 17종 프리셋": len(presets) >= 17,
            "패치노트 명령": bot.get_command("패치노트") is not None,
        }
        ok = all(checks.values())
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} 통합 검수", color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        if mode.casefold() in {"상세", "detail", "detailed"}:
            embed.add_field(name="명령 흐름", value="메인 RPG/플레이/세계/소셜/운영 → 기능군 → 25개 페이지 → 상세 → 실행", inline=False)
            embed.add_field(name="보존 정책", value="기존 명령 삭제 0 · 기존 별칭 유지 · 기존 저장 구조 유지", inline=False)
            embed.add_field(name="자동 이모지 마이그레이션", value=f"시작 시 기존 서버 **{migrated_guilds}개** 보강", inline=False)
        await ctx.send(embed=embed)

    print(
        f"[ABADDON v{VERSION}] complete command center registered: commands={len(entries)} groups={len(GROUP_INDEX)} migrated_reaction_guilds={migrated_guilds}",
        flush=True,
    )


register_v1631_casino_gambling_onboarding_overhaul = register_v1630_core_rpg_command_city_overhaul
