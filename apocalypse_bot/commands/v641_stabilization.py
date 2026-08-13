from __future__ import annotations

import ast
import copy
import json
import os
import py_compile
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "7.8.0"
KST = timezone(timedelta(hours=9))
PATCH_DATE = "2026-08-03"

THEMES: Dict[str, Dict[str, Any]] = {
    # 아포칼립스 / 생존
    "검은성당": {"group":"아포칼립스","emoji":"🕯️","title":"검은 성당","color":0x6C3B73,"tagline":"침묵 속에서 신호를 지키는 생존 성역","briefing":"낮은 조명과 차분한 경보 문구를 사용하는 정통 ABADDON 테마입니다."},
    "폐허도시": {"group":"아포칼립스","emoji":"🏙️","title":"폐허 도시","color":0x7A5943,"tagline":"무너진 도심을 거점으로 삼은 전투 생존 테마","briefing":"작전·탐색·거래 안내를 거칠고 실용적인 문구로 정리합니다."},
    "격리연구소": {"group":"아포칼립스","emoji":"🧪","title":"격리 연구소","color":0x2A7F78,"tagline":"감염 수치와 표본을 추적하는 연구 거점","briefing":"날씨·감염·무전·장비 상태를 계측 보고서처럼 표시합니다."},
    "황혼전초기지": {"group":"아포칼립스","emoji":"🏕️","title":"황혼 전초기지","color":0xB0783C,"tagline":"생활과 기지 성장을 중심으로 한 개척 테마","briefing":"채집·기지·보급선·시장 정보를 한눈에 확인하기 좋습니다."},
    "종말방송국": {"group":"아포칼립스","emoji":"📻","title":"종말 방송국","color":0x425D8C,"tagline":"끊어진 통신망을 다시 잇는 서버 이벤트 테마","briefing":"SOS·날씨·공개 작전·서버 알림을 방송 속보 형식으로 정리합니다."},
    "방사능항구": {"group":"아포칼립스","emoji":"⚓","title":"방사능 항구","color":0x397B72,"tagline":"오염된 부두와 밀수 항로를 지키는 해안 거점","briefing":"밀수품·보급선·자원 시장과 위험 수치를 항만 관제 보고처럼 표시합니다."},
    "붉은사막": {"group":"아포칼립스","emoji":"🏜️","title":"붉은 사막","color":0xA85A42,"tagline":"모래폭풍 속 이동과 자원 확보에 특화된 유목 거점","briefing":"날씨·원정·생활 활동의 위험과 보상을 거친 탐사 기록으로 정리합니다."},
    "침수지하철": {"group":"아포칼립스","emoji":"🚇","title":"침수 지하철","color":0x315F75,"tagline":"물에 잠긴 노선을 따라 생존자를 연결하는 지하 거점","briefing":"이동·무전·스토리·위험구역 정보를 노선 관제판처럼 표시합니다."},
    "설원벙커": {"group":"아포칼립스","emoji":"❄️","title":"설원 벙커","color":0x6A8297,"tagline":"극저온 한파를 버티는 폐쇄형 방어 거점","briefing":"기지 방어·식량·장비 내구도와 체력 상태를 보급 장부 형식으로 정리합니다."},
    "무너진방벽": {"group":"아포칼립스","emoji":"🧱","title":"무너진 방벽","color":0x7C6758,"tagline":"끊어진 방어선을 복구하는 최전선 요새","briefing":"전투·레이드·기지 강화와 공동 목표를 전선 상황판처럼 표시합니다."},
    "밤의시장": {"group":"아포칼립스","emoji":"🌃","title":"밤의 시장","color":0x674C83,"tagline":"희귀 물자와 소문이 오가는 암시장 생존 테마","briefing":"거래·까마귀 상점·우편·보물 감정을 야시장 전광판처럼 정리합니다."},
    "신호관측소": {"group":"아포칼립스","emoji":"📡","title":"신호 관측소","color":0x486D91,"tagline":"날씨와 통신 교란을 감시하는 고지대 관측 거점","briefing":"날씨 변화·SOS·서버 이벤트의 남은 시간을 신호 분석표처럼 표시합니다."},

    # 깔끔 / 고딕
    "깔끔고딕": {"group":"깔끔고딕","emoji":"🏰","title":"깔끔 고딕","color":0x4B4458,"tagline":"장식을 덜어낸 흑백 고딕 성역","briefing":"검정·회색·은색 중심의 정돈된 문장과 최소한의 장식으로 브리핑합니다."},
    "순백성당": {"group":"깔끔고딕","emoji":"🤍","title":"순백 성당","color":0xB8B7C8,"tagline":"밝은 석조와 은빛 유리의 깨끗한 성역","briefing":"경고는 선명하게, 일반 안내는 밝고 차분한 문구로 표시합니다."},
    "은빛도서관": {"group":"깔끔고딕","emoji":"📖","title":"은빛 도서관","color":0x7D8397,"tagline":"차가운 은색과 잉크색 기록실","briefing":"임무·기록·도감 정보를 서고 색인처럼 정갈하게 정리합니다."},
    "왕실무도회": {"group":"깔끔고딕","emoji":"👑","title":"왕실 무도회","color":0x8B658B,"tagline":"보랏빛 벨벳과 금장 장식의 우아한 성역","briefing":"서버 이벤트와 보상을 초대장·연회 공지처럼 표현합니다."},

    # 화사 / 자연
    "벚꽃정원": {"group":"화사자연","emoji":"🌸","title":"벚꽃 정원","color":0xE58FA8,"tagline":"분홍 꽃잎이 흐르는 밝은 휴식 거점","briefing":"오늘 할 일·운세·펫·생활 정보를 부드럽고 따뜻한 문구로 안내합니다."},
    "라벤더문": {"group":"화사자연","emoji":"🪻","title":"라벤더 문","color":0x9C85D8,"tagline":"라벤더빛 밤하늘과 은은한 달빛 테마","briefing":"스토리·보물·펫 정보를 몽환적이지만 읽기 쉬운 색상으로 표시합니다."},
    "민트온실": {"group":"화사자연","emoji":"🌿","title":"민트 온실","color":0x62BFA7,"tagline":"초록 유리와 맑은 민트빛 생존 정원","briefing":"채집·날씨·회복·기지 생산 정보를 산뜻한 연구 노트처럼 정리합니다."},
    "해변리조트": {"group":"화사자연","emoji":"🏖️","title":"해변 리조트","color":0x4BAFD1,"tagline":"푸른 바다와 햇빛이 있는 여유로운 서버 테마","briefing":"낚시·지원·이벤트 정보를 밝고 시원한 안내판처럼 표시합니다."},
    "천공정원": {"group":"화사자연","emoji":"☁️","title":"천공 정원","color":0x79A9E8,"tagline":"구름 위 흰 정원과 푸른 하늘의 테마","briefing":"브리핑·퀘스트·성장 정보를 가볍고 맑은 색으로 정리합니다."},
    "황금들판": {"group":"화사자연","emoji":"🌾","title":"황금 들판","color":0xD6A84E,"tagline":"햇살과 수확의 온기를 담은 생활 중심 테마","briefing":"생활 보상·기지 생산·시장 변동을 따뜻한 수확 기록처럼 표시합니다."},

    # 모던 / 판타지
    "코발트시티": {"group":"모던판타지","emoji":"🔷","title":"코발트 시티","color":0x3F6FD1,"tagline":"파란 유리와 정돈된 도시형 대시보드","briefing":"전투·거래·상태 정보를 명확한 블루 패널 스타일로 정리합니다."},
    "네온아카데미": {"group":"모던판타지","emoji":"💠","title":"네온 아카데미","color":0xB53CDD,"tagline":"보라·청록 네온이 빛나는 마법 공학 학교","briefing":"미니게임·개조·연구 기능을 생동감 있는 실험실 공지처럼 표시합니다."},
    "별빛극장": {"group":"모던판타지","emoji":"🎭","title":"별빛 극장","color":0x6A5AD7,"tagline":"별과 무대 조명이 흐르는 이야기 중심 테마","briefing":"스토리·원정·시즌 이벤트를 공연 순서표처럼 드라마틱하게 정리합니다."},
    "아르데코": {"group":"모던판타지","emoji":"◆","title":"아르데코","color":0xB78A3A,"tagline":"검정과 금색의 기하학적 고급 테마","briefing":"거래·장비·보물·패치노트를 간결한 금장 패널로 표시합니다."},
    "마법학원": {"group":"모던판타지","emoji":"🪄","title":"마법 학원","color":0x596AC8,"tagline":"푸른 마력과 고서가 공존하는 판타지 캠퍼스","briefing":"강화·제작·펫·퀘스트를 수업·연구 과제처럼 즐겁게 안내합니다."},
    "달빛서재": {"group":"모던판타지","emoji":"🌙","title":"달빛 서재","color":0x5B5E9B,"tagline":"남색 밤과 따뜻한 책등이 어우러진 조용한 테마","briefing":"대화·기억·도감·업데이트 기록을 편안한 독서 기록처럼 정리합니다."},
}
THEME_GROUPS: Dict[str, Tuple[str, ...]] = {
    "아포칼립스": tuple(k for k,v in THEMES.items() if v.get("group") == "아포칼립스"),
    "깔끔고딕": tuple(k for k,v in THEMES.items() if v.get("group") == "깔끔고딕"),
    "화사자연": tuple(k for k,v in THEMES.items() if v.get("group") == "화사자연"),
    "모던판타지": tuple(k for k,v in THEMES.items() if v.get("group") == "모던판타지"),
}
DEFAULT_THEME = "검은성당"

STABILITY_GUIDE = {
    "id": "stability_theme",
    "emoji": "🧰",
    "title": "안정화 / 서버 테마",
    "hint": "통합 점검, 이모지 성장 보드, 서버 브리핑, 28종 서버 리뉴얼·카드게임",
    "commands": [
        "!안정화상태 — 현재 버전·데이터·명령어·텍스트 우선 정책 확인",
        "!오늘할일 — 일일·주간 성장 진행률과 다음 추천 행동을 이모지로 확인",
        "!서버브리핑 — 날씨·위험구역·보급선·기지방어를 한 화면에 요약",
        "!서버테마 [전체/아포칼립스/깔끔고딕/화사자연/모던판타지] — 28종 테마 확인",
        "!서버테마미리보기 [테마명] — 텍스트형 테마를 적용 전 확인",
        "!서버테마설정 테마명 — 관리자가 서버 브리핑 테마 변경",
        "!서버리뉴얼 — 28종 테마·채널 구조·알림·백업·복구 통합 드롭다운",
        "!서버리뉴얼 테마목록 — 최신 테마와 채널 구조 매핑 확인",
        "!데이터백업 — 관리자가 현재 생존 데이터를 수동 백업",
        "!시스템점검 / !오류현황 / !운영통계 — v7.0.2 운영 상태와 사건 기록 확인",
        "!백업목록 / !백업생성 / !백업검증 / !복구미리보기 — 검증된 데이터 보호 도구",
        "!테스트 상세 — 명령어·가이드·데이터·이미지 정책 통합 진단",
        "!봇소개 — ABADDON 핵심 기능과 빠른 시작 확인",
    ],
}

EXPECTED_RECENT_COMMANDS: Tuple[str, ...] = (
    # v6.3.7
    "날씨", "무전", "무전해독", "SOS", "내구도", "무기수리", "개조목록", "개조부품제작",
    "무기개조", "개조해제", "까마귀", "까마귀구매", "위험구역", "오늘의운세", "랜덤박스",
    # v6.3.8
    "괴질탈출", "비상주파수", "지뢰찾기", "돌연변이경주", "돌연변이배팅", "오염문",
    "비상보급상자", "선물거래", "괴수투기장", "영혼결투", "벙커개설", "금고개설",
    "하이에나", "생물테러준비",
    # v6.3.9
    "다크존", "다크존진입", "다크존탐색", "다크존탈출", "밀수품운반", "보급선",
    "보급선수색", "고철갈갈이", "장비갈갈이", "우편함", "받기", "알림설정",
    # v6.4.0
    "미니게임", "반응속도", "기억회로", "생존자레이스",
    # v6.4.1
    "안정화상태", "오늘할일", "서버브리핑", "서버테마", "서버테마미리보기", "서버테마설정", "데이터백업",
    # v6.5.1
    "카드게임", "포커", "원카드", "조커잡기", "서버리뉴얼", "봇소개",
    # v7.0.2
    "시스템점검", "오류현황", "운영통계", "백업목록", "백업생성", "백업검증", "복구미리보기",
    # v7.1.0
    "성장보드", "미션보상", "누적보상", "장비프리셋", "월드보스주간랭킹", "월드보스주간보상", "복귀보급",
    # v7.2.0
    "귀여운메뉴", "새싹설정", "환영테마", "새싹역할설치", "새싹정리",
    # v7.2.0
    "아바돈게임", "아바돈초대", "아바돈전적", "패치채널", "패치자동공지", "패치공지상태", "패치공지게시",
    # v7.2.1
    "채널규칙",
    # v7.5.1
    "길드관리", "길드기지", "길드건설", "길드시설강화", "길드기지수확",
    "길드임무", "길드임무보상", "길드금고", "길드입금", "길드출금요청",
    "길드출금승인", "길드거래내역", "길드레이드", "길드레이드공격",
    "길드레이드보상", "길드레이드랭킹", "길드종합랭킹", "길드검수",
    "길드복구미리보기", "750안정화검수",
)

VISUAL_MODULES: Tuple[str, ...] = (
    "v631_life_visuals.py", "v632_life_visuals.py", "v633_equipment_crafting.py",
    "v634_equipment_menu.py", "v634_pet_visuals.py", "v635_visuals.py",
    "v432_forge_live.py", "v639_frontier_operations.py",
)


def _now_kst() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def _today() -> str:
    return _now_kst().strftime("%Y-%m-%d")


def _guild_id(ctx: commands.Context) -> int:
    return int(ctx.guild.id) if ctx.guild else 0


def _root_state(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault("v641", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v641"] = root
    root.setdefault("schema_version", 1)
    root.setdefault("guilds", {})
    return root


def _guild_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = _root_state(world_data)
    guilds = root.setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        guilds[str(guild_id)] = state
    state.setdefault("theme", DEFAULT_THEME)
    state.setdefault("selective_visuals", True)
    return state


def _theme_key(raw: str) -> Optional[str]:
    token = str(raw or "").strip().replace(" ", "")
    if token in THEMES:
        return token
    lowered = token.lower()
    for key, info in THEMES.items():
        if lowered in {key.lower(), str(info["title"]).replace(" ", "").lower()}:
            return key
    return None


def _theme(world_data: Dict[str, Any], guild_id: int) -> Tuple[str, Dict[str, Any]]:
    state = _guild_state(world_data, guild_id)
    key = str(state.get("theme", DEFAULT_THEME))
    if key not in THEMES:
        key = DEFAULT_THEME
        state["theme"] = key
    return key, THEMES[key]


def _normalize_guide(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch not in " `!/·-—[]()")


def update_command_guide(guide: List[Dict[str, Any]]) -> None:
    guide[:] = [category for category in guide if category.get("id") != STABILITY_GUIDE["id"]]
    server_index = next((i for i, category in enumerate(guide) if category.get("id") == "server"), len(guide))
    guide.insert(server_index, copy.deepcopy(STABILITY_GUIDE))

    # 같은 설명 문구가 여러 최상위 카테고리에 겹치지 않게 정리합니다.
    seen: set[str] = set()
    for category in guide:
        rows: List[str] = []
        for row in category.get("commands", []):
            key = _normalize_guide(row)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(str(row))
        category["commands"] = rows


def _guide_tokens(guide: Sequence[Mapping[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for category in guide:
        for row in category.get("commands", []):
            text = str(row)
            for part in text.replace("/", " ").split():
                if part.startswith("!"):
                    tokens.add(part[1:].split("[")[0].split("—")[0].strip())
    return {token for token in tokens if token}


def _runtime_duplicate_tokens(bot: commands.Bot) -> List[str]:
    seen: Dict[str, str] = {}
    duplicates: List[str] = []
    for command in bot.walk_commands():
        if command.parent is not None:
            continue
        names = [command.name, *getattr(command, "aliases", [])]
        for name in names:
            token = str(name).lower()
            owner = command.qualified_name
            if token in seen and seen[token] != owner:
                duplicates.append(f"{token}: {seen[token]} / {owner}")
            else:
                seen[token] = owner
    return sorted(set(duplicates))


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"




def _emoji_bar(percent: float, width: int = 10, filled: str = "🟩", empty: str = "⬛") -> str:
    pct = max(0.0, min(100.0, float(percent)))
    count = max(0, min(width, int(round(pct / 100 * width))))
    return filled * count + empty * (width - count)


def _backup_data_file(data_file: str, *, keep: int = 5) -> Path:
    source = Path(data_file)
    if not source.is_file():
        raise FileNotFoundError("아직 저장된 생존 데이터 파일이 없습니다.")
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_kst().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"{source.stem}_{stamp}{source.suffix or '.json'}"
    shutil.copy2(source, target)
    backups = sorted(backup_dir.glob(f"{source.stem}_*{source.suffix or '.json'}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(1, int(keep)):]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def register_v641_stabilization(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Mapping[str, Dict[str, Any]],
    guide: List[Dict[str, Any]],
    *,
    data_file: str,
) -> None:
    _root_state(world_data)
    update_command_guide(guide)

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("⚠️ 서버에서만 사용할 수 있습니다.")
            return False
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("⚠️ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    @bot.command(name="안정화상태", aliases=["안정화", "봇상태점검"])
    async def stabilization_status(ctx: commands.Context) -> None:
        key, theme = _theme(world_data, _guild_id(ctx))
        embed = discord.Embed(
            title="🧩 ABADDON v7.2.0 통합 환영·동료전 운영 상태",
            description="환영 메시지/역할 중복을 통합하고 패치 자동 공지와 아바돈 AI 미니게임을 함께 적용했습니다.",
            color=int(theme["color"]),
        )
        embed.add_field(name="서버 테마", value=f"{theme['emoji']} **{theme['title']}** (`{key}`)", inline=True)
        embed.add_field(name="명령어", value=f"등록 **{len(list(bot.walk_commands()))}개** · 가이드 **{len(guide)}/25**", inline=True)
        embed.add_field(name="데이터", value=f"생존자 **{len(user_data):,}명** · 원자적 저장/백업 보호", inline=True)
        embed.add_field(name="빠른 진단", value="`!테스트 상세`", inline=False)
        embed.set_footer(text="운영 상태 요약 · 최신 안내는 !명령어 / !봇소개")
        await ctx.send(embed=embed)

    @bot.command(name="봇소개", aliases=["아바돈소개", "봇정보"])
    async def bot_introduction(ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="🛰️ ABADDON · 종말 생존 RPG",
            description=(
                "ABADDON은 Discord에서 즐기는 종말 생존 RPG 봇입니다. "
                "성장·스토리·던전·월드보스·장비·보물·펫·기지·생활·거래·카드게임과 "
                "서버 리뉴얼·운영 기능을 버튼·드롭다운·모달로 제공합니다."
            ),
            color=0xC8AA62,
        )
        embed.add_field(name="⚔️ 생존 RPG", value="시즌 스토리 · FINAL ECLIPSE · 솔로 원정 · 던전 · 레이드 · 월드보스", inline=False)
        embed.add_field(name="🧰 성장과 수집", value="장비 강화·개조 · 제작/생산 · 보물 감정 · 펫/탈것 · 기지/도시 성장", inline=False)
        embed.add_field(name="🎮 커뮤니티 콘텐츠", value="생활·거래·카드게임 · 카지노/일반 도박 · 길드/PvP · 박물관/커뮤니티 시즌", inline=False)
        embed.add_field(name="🛡️ 안전 설계", value="원자적 저장·백업·복구 · 정산 보호 · 오류 사건 번호 · 읽기 전용 `!테스트 상세`", inline=False)
        embed.add_field(name="🚀 빠른 시작", value="`!가입 생존자` → `!첫10분` → `!오늘할일` → `!명령어`", inline=False)
        embed.add_field(name="🛟 장애·버그 문의", value="`!문의처` 또는 **Discord DM `jjonga0022`** · 오류 화면/사건 번호를 함께 보내주시면 확인이 빠릅니다.", inline=False)
        embed.set_footer(text="ABADDON v18.3.4 · 쉬운 시작 · 30초 상태 순환 · 장애문의 jjonga0022")
        await ctx.send(embed=embed)

    @bot.command(name="오늘할일", aliases=["오늘뭐하지", "일일체크"])
    async def today_tasks(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        today = _today()
        legacy_today = datetime.now().strftime("%Y-%m-%d")
        valid_dates = {today, legacy_today}
        attendance_done = str(user.get("last_attendance", "")) in valid_dates
        fortune = user.get("daily_fortune")
        fortune_done = isinstance(fortune, Mapping) and str(fortune.get("date")) in valid_dates
        quiz = user.get("daily_quiz")
        quiz_done = isinstance(quiz, Mapping) and str(quiz.get("date")) in valid_dates and bool(quiz.get("solved"))
        daily_quest = user.get("daily_quest")
        quest_done = isinstance(daily_quest, Mapping) and bool(
            daily_quest.get("claimed") or int(daily_quest.get("progress", 0) or 0) >= int(daily_quest.get("target", 1) or 1)
        )
        rows = [
            f"{'✅' if attendance_done else '⬜'} 출석 — `!출석`",
            f"{'✅' if fortune_done else '⬜'} 오늘의 운세 — `!오늘의 운세`",
            f"{'✅' if quiz_done else '⬜'} 오늘의 퀴즈 — `!오늘의퀴즈`",
            f"{'✅' if quest_done else '⬜'} 일일 퀘스트 — `!일일퀘스트`",
            "🌿 생활 루틴 — `!채집` `!낚시` `!광산` 중 선택",
            "⚔️ 전투 루틴 — `!던전 보통` 또는 `!전투 보통`",
            "📻 세계 확인 — `!서버브리핑`",
        ]
        done = sum((attendance_done, fortune_done, quiz_done, quest_done))
        embed = discord.Embed(
            title=f"📋 {ctx.author.display_name}님의 오늘 할 일",
            description="\n".join(rows),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="핵심 일일 진행", value=f"{_emoji_bar(done / 4 * 100)} **{done}/4 · {done / 4 * 100:.0f}%**", inline=False)
        embed.add_field(name="안내", value="체크는 보상을 강제로 수령하지 않고 현재 기록만 읽습니다.", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="서버브리핑", aliases=["세계브리핑", "오늘의서버"])
    async def server_briefing(ctx: commands.Context) -> None:
        guild_id = _guild_id(ctx)
        key, theme = _theme(world_data, guild_id)
        from apocalypse_bot.commands.v636_world_combat import get_weather_state
        from apocalypse_bot.commands.v637_dynamic_events import get_hazard_zone
        from apocalypse_bot.commands.v639_frontier_operations import active_supply_drop

        weather = get_weather_state(guild_id)
        hazard = get_hazard_zone(guild_id)
        supply = active_supply_drop(world_data, guild_id)
        defense = world_data.get("base_defense_raids", {}).get(str(guild_id), {})
        if isinstance(defense, Mapping) and defense:
            hp = int(defense.get("hp", 0) or 0)
            max_hp = max(1, int(defense.get("max_hp", 1) or 1))
            defense_text = f"{defense.get('name', '미확인 군체')}\n{_emoji_bar(hp / max_hp * 100, filled='🟥')} **{hp:,}/{max_hp:,} · {hp / max_hp * 100:.1f}%**"
        else:
            defense_text = "아직 이번 주 방어전 정보 없음 · `!기지방어`로 확인"

        if supply.get("active"):
            supply_text = f"활성 중 · 종료까지 {_format_seconds(int(supply.get('remaining', 0) or 0))}"
        else:
            supply_state = world_data.get("v639", {}).get("guilds", {}).get(str(guild_id), {}).get("supply", {})
            now_utc = datetime.now(timezone.utc)
            upcoming = []
            if isinstance(supply_state, Mapping):
                for raw_time in supply_state.get("schedule", []):
                    try:
                        point = datetime.fromisoformat(str(raw_time))
                        if point.tzinfo is None:
                            point = point.replace(tzinfo=timezone.utc)
                        if point > now_utc:
                            upcoming.append(point)
                    except (TypeError, ValueError):
                        continue
            if upcoming:
                next_time = min(upcoming).astimezone(KST).strftime("%H:%M")
                supply_text = f"비활성 · 다음 예정 **{next_time} KST**"
            else:
                supply_text = "비활성 · 오늘 남은 예정 없음"
        embed = discord.Embed(
            title=f"{theme['emoji']} {theme['title']} · 서버 브리핑",
            description=f"**{theme['tagline']}**\n{theme['briefing']}",
            color=int(theme["color"]),
        )
        embed.add_field(
            name=f"{weather.get('emoji', '🌦️')} 현재 날씨 · {weather.get('name', '미확인')}",
            value=(lambda remaining, total: f"{weather.get('desc', '')}\n{_emoji_bar((total-remaining)/max(1,total)*100, filled='🟦')} **경과 {(total-remaining)/max(1,total)*100:.0f}%**\n변경까지 **{_format_seconds(remaining)}**")(int(weather.get('remaining', 0)), int(weather.get('duration_hours', 1))*3600),
            inline=False,
        )
        embed.add_field(name="☣️ 돌연변이 위험구역", value=f"**{hazard.get('region', '미확인')}** · 보상 ×{float(hazard.get('reward_mult', 1.0)):.2f}", inline=True)
        embed.add_field(name="🎁 보급선", value=supply_text, inline=True)
        embed.add_field(name="🛡️ 기지 방어", value=defense_text, inline=False)
        embed.set_footer(text=f"테마 키: {key} · 설정: !서버테마설정 테마명 · {len(THEMES)}종 선택 가능")
        await ctx.send(embed=embed)

    @bot.command(name="서버테마", aliases=["테마목록"])
    async def server_theme(ctx: commands.Context, *, 분류: str = "전체") -> None:
        current_key, current = _theme(world_data, _guild_id(ctx))
        token = str(분류 or "전체").strip().replace(" ", "")
        aliases = {
            "전체":"전체", "all":"전체",
            "아포칼립스":"아포칼립스", "생존":"아포칼립스", "다크":"아포칼립스",
            "깔끔고딕":"깔끔고딕", "고딕":"깔끔고딕", "깔끔":"깔끔고딕",
            "화사자연":"화사자연", "화사":"화사자연", "자연":"화사자연", "밝음":"화사자연",
            "모던판타지":"모던판타지", "모던":"모던판타지", "판타지":"모던판타지",
        }
        selected = aliases.get(token.lower(), aliases.get(token, "전체"))
        groups = THEME_GROUPS if selected == "전체" else {selected: THEME_GROUPS[selected]}
        embed = discord.Embed(
            title=f"🎨 ABADDON 서버 테마 {len(THEMES)}종" + ("" if selected == "전체" else f" · {selected}"),
            description=f"현재 테마: {current['emoji']} **{current['title']}** (`{current_key}`)\n분류: `전체` `아포칼립스` `깔끔고딕` `화사자연` `모던판타지`",
            color=int(current["color"]),
        )
        group_icons = {"아포칼립스":"☣️", "깔끔고딕":"🏰", "화사자연":"🌸", "모던판타지":"🔮"}
        for group_name, keys in groups.items():
            rows=[]
            for key in keys:
                info=THEMES[key]
                marker="✅" if key == current_key else "▫️"
                rows.append(f"{marker} {info['emoji']} **{info['title']}** · `{key}`")
            embed.add_field(name=f"{group_icons.get(group_name,'🎨')} {group_name} · {len(keys)}종", value="\n".join(rows)[:1024], inline=False)
        embed.add_field(name="사용법", value="`!서버테마 화사` · `!서버테마미리보기 벚꽃정원` · `!서버테마설정 깔끔고딕`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="서버테마미리보기", aliases=["테마미리보기"])
    async def theme_preview(ctx: commands.Context, *, 테마명: str = "") -> None:
        key = _theme_key(테마명) if 테마명 else _theme(world_data, _guild_id(ctx))[0]
        if key is None:
            await ctx.send("⚠️ 테마를 찾지 못했습니다. `!서버테마`에서 목록을 확인하세요.")
            return
        info = THEMES[key]
        embed = discord.Embed(
            title=f"{info['emoji']} {info['title']} · 미리보기",
            description=f"**{info['tagline']}**\n{info['briefing']}",
            color=int(info["color"]),
        )
        embed.add_field(name="📡 속보", value="전자기 교란이 감지되었습니다. 야외 활동 전 `!날씨`를 확인하세요.", inline=False)
        embed.add_field(name="🧭 추천 행동", value="`!서버브리핑` → `!오늘할일` → 원하는 생활/전투 콘텐츠", inline=False)
        embed.set_footer(text="게임 이미지 정책과 무관하며, 서버 브리핑의 색상·이모지·문장 구성만 변경됩니다.")
        await ctx.send(embed=embed)

    @bot.command(name="서버테마설정", aliases=["테마설정"])
    async def theme_set(ctx: commands.Context, *, 테마명: str) -> None:
        if not await require_admin(ctx):
            return
        key = _theme_key(테마명)
        if key is None:
            await ctx.send("⚠️ 지원하지 않는 테마입니다. `!서버테마`에서 목록을 확인하세요.")
            return
        state = _guild_state(world_data, _guild_id(ctx))
        state["theme"] = key
        state["updated_at"] = _now_kst().isoformat()
        state["updated_by"] = int(ctx.author.id)
        save_data()
        info = THEMES[key]
        await ctx.send(f"✅ 서버 테마를 {info['emoji']} **{info['title']}**로 변경했습니다. `!서버브리핑`에서 확인하세요.")

    @bot.command(name="데이터백업", aliases=["수동백업"])
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def data_backup(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        try:
            save_data()
            target = _backup_data_file(data_file, keep=5)
        except Exception as exc:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"❌ 백업에 실패했습니다: `{type(exc).__name__}`")
            return
        await ctx.send(f"✅ 데이터 백업 완료 · `{target.name}`\n최근 백업은 최대 **5개**까지 유지합니다.")

    @bot.command(name="안정화도움말", aliases=["안정화명령어"])
    async def stabilization_help(ctx: commands.Context) -> None:
        category = next((category for category in guide if category.get("id") == STABILITY_GUIDE["id"]), STABILITY_GUIDE)
        embed = discord.Embed(title="🧰 안정화 / 서버 테마", description=category["hint"], color=discord.Color.dark_teal())
        embed.add_field(name="명령어", value="\n".join(f"• `{row}`" for row in category["commands"])[:1024], inline=False)
        await ctx.send(embed=embed)

    previous_test = bot.get_command("테스트")
    if previous_test is not None:
        async def v641_test(ctx: commands.Context, 모드: str = "기본") -> None:
            checks: List[Tuple[str, bool, str]] = []
            command_names: set[str] = set()
            for command in bot.walk_commands():
                if command.parent is not None:
                    continue
                command_names.add(str(command.name).lower())
                command_names.update(str(alias).lower() for alias in getattr(command, "aliases", []))
            missing_commands = [name for name in EXPECTED_RECENT_COMMANDS if str(name).lower() not in command_names]
            checks.append(("최근 패치 명령 등록", not missing_commands, "누락 없음" if not missing_commands else ", ".join(missing_commands[:20])))

            duplicates = _runtime_duplicate_tokens(bot)
            checks.append(("명령·별칭 중복", not duplicates, "충돌 없음" if not duplicates else " / ".join(duplicates[:10])))

            category_ids = [str(category.get("id", "")) for category in guide]
            checks.append(("최상위 카테고리 제한", len(guide) <= 25 and len(category_ids) == len(set(category_ids)), f"{len(guide)}/25 · ID 중복 {len(category_ids) - len(set(category_ids))}개"))

            guide_tokens = _guide_tokens(guide)
            missing_guide = [name for name in EXPECTED_RECENT_COMMANDS if name not in guide_tokens]
            checks.append(("!명령어 최신화", not missing_guide, "최근 기능 전부 노출" if not missing_guide else ", ".join(missing_guide[:20])))

            growth_commands = ("성장보드", "미션보상", "누적보상", "장비프리셋", "월드보스주간랭킹", "월드보스주간보상", "복귀보급")
            missing_growth = [name for name in growth_commands if bot.get_command(name) is None]
            growth_root = world_data.get("growth_loop_v710", {})
            growth_ok = not missing_growth and callable(getattr(bot, "v710_record_worldboss_damage", None)) and isinstance(growth_root, dict)
            checks.append(("v7.1 성장 루프", growth_ok, "명령 7종·월드보스 훅·저장 루트 정상" if growth_ok else f"누락: {', '.join(missing_growth) or '월드보스 훅/저장 루트'}"))

            project_root = Path(__file__).resolve().parents[2]
            py_files = sorted(project_root.rglob("*.py"))
            compile_errors: List[str] = []
            for path in py_files:
                try:
                    py_compile.compile(str(path), doraise=True)
                except Exception as exc:
                    compile_errors.append(f"{path.name}: {type(exc).__name__}")
            checks.append(("Python 전체 컴파일", not compile_errors, f"{len(py_files)}개 통과" if not compile_errors else ", ".join(compile_errors[:8])))

            suspicious: List[str] = []
            for path in py_files:
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except Exception:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ebp":
                        suspicious.append(f"{path.name}:{getattr(node, 'lineno', '?')}")
            checks.append(("장비 시작 오류 재발 방지", not suspicious, "ebp(...) 호출 0개" if not suspicious else ", ".join(suspicious)))

            try:
                json.dumps({"users": user_data, "world": world_data}, ensure_ascii=False)
                serializable = True
                serial_detail = "현재 데이터 JSON 직렬화 가능"
            except Exception as exc:
                serializable = False
                serial_detail = f"{type(exc).__name__}: {exc}"
            checks.append(("저장 데이터 구조", serializable, serial_detail))

            parent = Path(data_file).expanduser().resolve().parent
            writable = parent.exists() and os.access(parent, os.W_OK)
            checks.append(("영구 저장 경로", writable, f"{parent} · {'쓰기 가능' if writable else '쓰기 불가/미생성'}"))
            modules_dir = Path(__file__).resolve().parent
            visual_failures: List[str] = []
            for filename in VISUAL_MODULES:
                path = modules_dir / filename
                if not path.is_file():
                    visual_failures.append(f"{filename}: 없음")
                    continue
                source = path.read_text(encoding="utf-8")
                if "ABADDON_TEXT_FIRST_DISABLED" in source:
                    visual_failures.append(f"{filename}: 비활성 표식 잔존")
            checks.append(("핵심 이미지 복구", not visual_failures, "생활·장비·보물·제작·펫·기지·갈갈이 이미지 활성" if not visual_failures else ", ".join(visual_failures)))

            casino_module = (modules_dir / "v635_visuals.py").read_text(encoding="utf-8") + (modules_dir / "v39_casino.py").read_text(encoding="utf-8")
            casino_disabled = "def apply_casino_visual" in casino_module and "return None" in casino_module and "카지노 로비 이미지는 사용하지 않습니다" in casino_module
            checks.append(("카지노 이미지 미사용", casino_disabled, "카지노만 이미지 비활성" if casino_disabled else "카지노 이미지 정책 점검 필요"))

            fx_source = (modules_dir / "v633_equipment_crafting.py").read_text(encoding="utf-8")
            checks.append(("강화 이펙트 안전화", "V650_SAFE_ENHANCEMENT_FX = True" in fx_source, "+0~+4 원본 픽셀 유지 · 바깥 여백 전용 FX · 공통 사선 0개"))

            arcade_source = (modules_dir / "v638_hardcore_arcade.py").read_text(encoding="utf-8")
            checks.append(("버튼 네트워크 재시도", "_safe_interaction_edit" in arcade_source, "Connection reset 1회 재시도·상태 저장 유지"))

            world_boss_root = project_root / "apocalypse_bot" / "assets" / "world_boss"
            boss_images = list(world_boss_root.glob("*.png")) + list(world_boss_root.glob("*.jpg")) + list(world_boss_root.glob("*.webp"))
            checks.append(("월드보스 이미지 예외", bool(boss_images), f"{len(boss_images)}개 유지" if boss_images else "월드보스 이미지 없음"))

            theme_ok = _guild_state(world_data, _guild_id(ctx)).get("theme") in THEMES
            checks.append(("서버 테마 상태", theme_ok and len(THEMES) >= 28, f"현재 {_guild_state(world_data, _guild_id(ctx)).get('theme')} · 총 {len(THEMES)}종"))
            renewal_ok = int(getattr(bot, "v651_server_theme_count", 0) or 0) == len(THEMES)
            checks.append(("서버리뉴얼 테마 동기화", renewal_ok, f"드롭다운 {getattr(bot, 'v651_server_theme_count', 0)}종 / 카탈로그 {len(THEMES)}종"))
            card_commands = tuple(getattr(bot, "v651_card_game_commands", ()))
            checks.append(("카드게임 등록", set(card_commands) == {"카드게임", "포커", "원카드", "조커잡기"}, "포커·원카드·조커잡기" if card_commands else "등록 누락"))
            ai_commands = {name for name in ("아바돈게임", "아바돈초대", "아바돈전적") if bot.get_command(name) is not None}
            checks.append(("아바돈 AI 동료전", len(ai_commands) == 3 and callable(getattr(bot, "v720_start_ai_card", None)), "1:1 게임 7종·카드 모집방 AI 초대" if len(ai_commands) == 3 else "AI 동료전 등록 누락"))
            unified_listener = callable(getattr(bot, "v720_unified_member_join", None))
            checks.append(("환영/역할 단일 처리", unified_listener, "SERVER GUARD 입장 리스너 1곳에서 통합 핸들러 호출" if unified_listener else "통합 환영 핸들러 누락"))
            patch_auto = all(bot.get_command(name) is not None for name in ("패치채널", "패치자동공지", "패치공지상태", "패치공지게시"))
            checks.append(("패치 자동 공지", patch_auto, "버전당 1회 게시·채널 자동 감지·수동 게시" if patch_auto else "패치 공지 명령 누락"))
            channel_rule = bot.get_command("채널규칙")
            channel_guide_ok = channel_rule is not None and channel_rule.get_command("전체설치") is not None
            checks.append(("채널별 고정 가이드", channel_guide_ok, "공식 채널명 전용 안내·전체설치·기존 메시지 갱신" if channel_guide_ok else "채널가이드 전체설치 등록 누락"))

            guild_commands = (
                "길드관리", "길드기지", "길드임무", "길드금고", "길드입금",
                "길드출금요청", "길드출금승인", "길드레이드", "길드레이드공격",
                "길드레이드준비", "길드전술설정", "길드레이드연습", "길드레이드기록",
                "길드레이드보상", "길드검수", "750안정화검수",
                "길드파견", "길드파견모집", "길드파견참가", "길드파견출발",
                "길드파견정산", "길드파견보상", "길드파견기록", "길드파견모의", "760안정화검수",
            )
            missing_guild = [name for name in guild_commands if bot.get_command(name) is None]
            guild_audit_fn = getattr(bot, "v750_audit_guilds", None)
            try:
                guild_audit = guild_audit_fn() if callable(guild_audit_fn) else {}
            except Exception as exc:
                guild_audit = {"critical": 1, "warning": 0, "error": f"{type(exc).__name__}: {exc}"}
            guild_ok = not missing_guild and callable(guild_audit_fn) and int(guild_audit.get("critical", 1) or 0) == 0
            checks.append((
                "v7.7.0 길드·생활 통합",
                guild_ok,
                "길드·파견 명령 정상" if guild_ok else f"누락 {', '.join(missing_guild) or '-'} · 치명 {guild_audit.get('critical', '?')}",
            ))
            life_commands = (
                "파밍", "파밍지역", "파밍출발", "파밍선택", "파밍기록",
                "공방", "폐품감정", "폐품분해", "폐품수리",
                "전파탐색", "신호해독", "주파수기록",
                "의뢰게시판", "계약수락", "납품", "계약현황",
                "연구소", "연구시작", "연구진행", "설계도", "770안정화검수",
            )
            missing_life = [name for name in life_commands if bot.get_command(name) is None]
            checks.append(("v7.7 생활 기능 등록", not missing_life, "파밍·인카운트·공방·신호·계약·연구 정상" if not missing_life else f"누락 {', '.join(missing_life)}"))
            checks.append(("길드 폐기 안전", int(guild_audit.get("deletions", 0) or 0) == 0, "자동 삭제·비활성화 0건 · 휴면 보존"))

            english_aliases = getattr(bot, "v652_english_aliases", {})
            english_skipped = getattr(bot, "v652_english_alias_skipped", {})
            english_total = sum(len(v) for v in english_aliases.values())
            english_help = bot.get_command("help")
            english_help_names = (bot.get_command("commands"), bot.get_command("english"), bot.get_command("enhelp"))
            english_help_separated = (
                english_help is not None
                and all(command is english_help for command in english_help_names)
                and english_help is not bot.get_command("명령어")
                and english_help is not bot.get_command("도움말")
                and int(getattr(bot, "v654_english_help_categories", 0) or 0) >= 13
            )
            english_ok = english_total >= 120 and english_help_separated
            checks.append((
                "영어 도움말 완전 분리",
                english_ok,
                f"영문 별칭 {english_total}개 · 영어 카테고리 {getattr(bot, 'v654_english_help_categories', 0)}개 · help/commands/english 동일 화면 · 한국어 브라우저 분리",
            ))

            component_sources = (modules_dir / "v651_card_games.py").read_text(encoding="utf-8") + (modules_dir / "v651_server_renewal.py").read_text(encoding="utf-8")
            invalid_component_emoji = [token for token in ("🂡", "♜") if token in component_sources]
            checks.append(("Discord 컴포넌트 이모지", not invalid_component_emoji, "표준 이모지 ♠️·🏰 사용" if not invalid_component_emoji else f"유효하지 않은 이모지 잔존: {', '.join(invalid_component_emoji)}"))

            failed = sum(1 for _, ok, _ in checks if not ok)
            passed = len(checks) - failed
            embed = discord.Embed(
                title=f"🧪 ABADDON v7.7.0 생활 확장·회귀 안정화 테스트 · {passed}/{len(checks)} 통과",
                description="재화·전투·인벤토리를 변경하지 않는 읽기 전용 검사입니다.",
                color=discord.Color.green() if failed == 0 else discord.Color.orange(),
            )
            detailed = str(모드).lower() in {"상세", "전체", "detail", "full"} or failed > 0
            if detailed:
                for name, ok, detail in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(detail)[:1024], inline=False)
            else:
                embed.add_field(name="결과", value=f"✅ {passed} · ❌ {failed}\n상세: `!테스트 상세`", inline=False)
            embed.set_footer(text="실제 Discord 버튼 동시성·권한·DM 전달은 배포 서버 스모크 테스트가 필요합니다.")
            await ctx.send(embed=embed)

        previous_test.callback = v641_test
        previous_test.help = "v7.7.0 게임센터 연결, 길드·파밍·인카운트·생활 기술과 기존 데이터 보호를 읽기 전용으로 검사합니다."
        previous_test.description = previous_test.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v641_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="🧭 ABADDON v7.7.0 — 폐허 파밍·생활 기술",
                description="지역 선택형 파밍과 랜덤 인카운트, 폐품 공방, 전파 해독, 납품 계약과 생활 연구를 추가했습니다.",
                color=0x307E62,
            )
            embed.add_field(name="🗺️ 폐허 파밍", value="마트·주거구역·화물역·격리구역 · 전투·회피·구조·추가 탐색 선택", inline=False)
            embed.add_field(name="💎 회수 물자", value="식량·생활 재료·보물 파편·미감정 보물·미감정 폐품", inline=False)
            embed.add_field(name="🔧 생활 기술", value="폐품 감정·분해·수리 · 전파 해독 · 일일 납품 · 연구소와 설계도", inline=False)
            embed.add_field(name="🛡️ 안전 정산", value="사용자별 잠금 · 재접속 복구 · 인카운트·계약·폐품 보상 중복 지급 방지", inline=False)
            embed.add_field(name="🧹 중복·폐기 안전", value="채집·광산·벌목·굴착·길드 파견과 역할 분리 · 삭제·비활성화 **0건**", inline=False)
            embed.add_field(name="📅 패치 날짜", value=f"**{PATCH_DATE}** · 신규 이미지 0장", inline=False)
            embed.set_footer(text=f"최신 버전 v7.7.0 · {PATCH_DATE}")
            await ctx.send(embed=embed)

        patch.callback = v641_patch_notes
        patch.help = "ABADDON v7.7.0 폐허 파밍·생활 기술 패치 내용을 확인합니다."
        patch.description = patch.help

    bot.v641_version = VERSION
    bot.v650_version = VERSION
    bot.v651_version = VERSION
    bot.v641_themes = THEMES
    bot.v641_text_first = False
    bot.v641_selective_visuals = True
    bot.v641_backup_data_file = lambda: _backup_data_file(data_file, keep=5)
