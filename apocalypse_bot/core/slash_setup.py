from __future__ import annotations

from typing import Dict, Tuple

from discord import app_commands
from discord.ext import commands


GROUP_DESCRIPTIONS: Dict[str, str] = {
    "직업": "직업 목록, 선택, 정보, 변경 기능을 사용합니다.",
    "의료": "상태 확인, 휴식, 의약품 구매와 치료 기능을 사용합니다.",
    "지역": "지역 목록, 정보, 이동, 탐색과 좀비 도감을 확인합니다.",
    "퀴즈": "오늘의 퀴즈, 정답, 랭킹과 알림 설정을 관리합니다.",
    "강화기능": "보호 강화, 옵션, 세트 효과와 강화 랭킹을 확인합니다.",
    "심층": "심층 던전, 기록, 보스 도감과 종합 랭킹을 확인합니다.",
    "경매": "경매 등록, 입찰, 검색, 마감과 거래 기록을 관리합니다.",
    "침공": "서버 침공 참가, 공격, 랭킹, 상점과 관리자 기능을 사용합니다.",
    "관리": "아바돈 관리자 전용 유저 및 아이템 관리 기능입니다.",
    "서버": "서버별 채널과 기능 설정을 관리합니다.",
    "튜토리얼": "초보자 튜토리얼 상태를 확인하거나 건너뜁니다.",
    "생존": "출석, 지원금 등 기본 생존 활동을 확인합니다.",
    "장비": "상점, 인벤토리, 장착, 강화, 제작 기능을 사용합니다.",
    "전투": "훈련, 던전, 레이드, 월드보스와 PVP 기능을 사용합니다.",
    "도박": "일반 도박, 경마, 지뢰·생존 게임과 도박 통계를 확인합니다.",
    "생활": "알바, 코인 탐색, 채집, 낚시, 벌목과 광산 활동을 합니다.",
    "기지": "기지 현황, 건설, 강화와 자원 수확 기능을 사용합니다.",
    "길드": "길드 생성, 가입, 기부, 강화와 탈퇴 기능을 사용합니다.",
    "거래": "지갑, 송금, 거래소 판매와 구매 기능을 사용합니다.",
    "파티": "파티 생성, 가입, 정보, 사냥과 탈퇴 기능을 사용합니다.",
    "시즌": "일일·주간 퀘스트, 업적, 칭호와 시즌 보상을 확인합니다.",
    "운영": "경고, 타임아웃, 채널 관리, 로그와 문의 기능을 사용합니다.",
    "커뮤니티": "문의, 임시 음성방, 버튼 역할과 웹 대시보드 기능을 사용합니다.",
}


# 기존 !명령어 이름 -> (슬래시 최상위 그룹, 슬래시 하위 명령어)
# prefix 명령어는 그대로 유지되며, slash 쪽만 보기 좋게 묶습니다.
SLASH_ROUTES: Dict[str, Tuple[str, str]] = {
    # 직업
    "직업목록": ("직업", "목록"),
    "직업선택": ("직업", "선택"),
    "직업정보": ("직업", "정보"),
    "직업변경": ("직업", "변경"),

    # 의료 / 상태
    "의약품": ("의료", "의약품"),
    "약품구매": ("의료", "구매"),
    "사용": ("의료", "사용"),
    "병원": ("의료", "병원"),
    "상태": ("의료", "상태"),
    "휴식": ("의료", "휴식"),

    # 지역
    "지역목록": ("지역", "목록"),
    "지역정보": ("지역", "정보"),
    "지역이동": ("지역", "이동"),
    "좀비도감": ("지역", "좀비도감"),
    "지역탐색": ("지역", "탐색"),

    # 퀴즈
    "오늘의퀴즈": ("퀴즈", "오늘"),
    "정답": ("퀴즈", "정답"),
    "퀴즈랭킹": ("퀴즈", "랭킹"),
    "퀴즈추가": ("퀴즈", "추가"),
    "퀴즈삭제": ("퀴즈", "삭제"),
    "퀴즈목록": ("퀴즈", "목록"),
    "퀴즈알림설정": ("퀴즈", "알림설정"),
    "퀴즈알림해제": ("퀴즈", "알림해제"),
    "퀴즈알림상태": ("퀴즈", "알림상태"),

    # 강화 확장
    "강화정보": ("강화기능", "정보"),
    "보호강화": ("강화기능", "보호강화"),
    "강화랭킹": ("강화기능", "랭킹"),
    "장비옵션": ("강화기능", "장비옵션"),
    "옵션재설정": ("강화기능", "옵션재설정"),
    "세트효과": ("강화기능", "세트효과"),

    # 심층 콘텐츠
    "심층던전": ("심층", "던전"),
    "던전기록": ("심층", "던전기록"),
    "보스도감": ("심층", "보스도감"),
    "생활숙련도": ("심층", "생활숙련도"),
    "종합랭킹": ("심층", "종합랭킹"),

    # 경매
    "거래검색": ("경매", "검색"),
    "경매등록": ("경매", "등록"),
    "입찰": ("경매", "입찰"),
    "경매마감": ("경매", "마감"),
    "거래기록": ("경매", "기록"),

    # 서버 침공
    "침공": ("침공", "현황"),
    "참전": ("침공", "참전"),
    "침공공격": ("침공", "공격"),
    "침공랭킹": ("침공", "랭킹"),
    "침공기록": ("침공", "기록"),
    "침공상점": ("침공", "상점"),
    "침공시작": ("침공", "시작"),
    "침공종료": ("침공", "종료"),
    "침공토큰지급": ("침공", "토큰지급"),

    # 관리자
    "관리자명령어": ("관리", "도움말"),
    "아이템목록": ("관리", "아이템목록"),
    "아이템검색": ("관리", "아이템검색"),
    "아이템지급": ("관리", "아이템지급"),
    "아이템회수": ("관리", "아이템회수"),
    "경험치지급": ("관리", "경험치지급"),
    "레벨설정": ("관리", "레벨설정"),
    "직업설정": ("관리", "직업설정"),
    "펫설정": ("관리", "펫설정"),
    "칭호지급": ("관리", "칭호지급"),
    "체력설정": ("관리", "체력설정"),
    "스태미나설정": ("관리", "스태미나설정"),
    "감염도설정": ("관리", "감염도설정"),
    "상태이상제거": ("관리", "상태이상제거"),
    "관리자지역이동": ("관리", "지역이동"),
    "유저정보": ("관리", "유저정보"),

    # 서버 설정
    "서버설정": ("서버", "설정"),
    "서버채널": ("서버", "채널"),
    "서버기능": ("서버", "기능"),

    # 튜토리얼
    "튜토리얼": ("튜토리얼", "상태"),
    "튜토리얼건너뛰기": ("튜토리얼", "건너뛰기"),

    # 기본 생존
    "출석": ("생존", "출석"),
    "출석보상": ("생존", "출석보상"),
    "돈주세요": ("생존", "지원"),

    # 장비 / 제작
    "상점": ("장비", "상점"),
    "장비목록": ("장비", "목록"),
    "구매": ("장비", "구매"),
    "인벤토리": ("장비", "인벤토리"),
    "장비": ("장비", "현황"),
    "장착": ("장비", "장착"),
    "해제": ("장비", "해제"),
    "버리기": ("장비", "버리기"),
    "감정": ("장비", "감정"),
    "강화": ("장비", "강화"),
    "재료": ("장비", "재료"),
    "제작목록": ("장비", "제작목록"),
    "제작": ("장비", "제작"),

    # 전투
    "훈련": ("전투", "훈련"),
    "괴물목록": ("전투", "괴물목록"),
    "던전": ("전투", "던전"),
    "레이드": ("전투", "레이드"),
    "레이드공격": ("전투", "레이드공격"),
    "월드보스": ("전투", "월드보스"),
    "보스랭킹": ("전투", "보스랭킹"),
    "월드보스공격": ("전투", "월드보스공격"),
    "pvp": ("전투", "pvp"),

    # 도박
    "탐색": ("도박", "탐색"),
    "주파수": ("도박", "주파수"),
    "룰렛": ("도박", "룰렛"),
    "파산신청": ("도박", "파산신청"),
    "도박잔액": ("도박", "잔액"),
    "도박정보": ("도박", "안내"),
    "경마": ("도박", "경마"),
    "경마장": ("도박", "경마장"),
    "경마전적": ("도박", "경마전적"),
    "괴질탈출": ("도박", "괴질탈출"),
    "비상주파수": ("도박", "비상주파수"),
    "지뢰찾기": ("도박", "지뢰찾기"),
    "돌연변이경주": ("도박", "돌연변이경주"),
    "돌연변이배팅": ("도박", "돌연변이배팅"),
    "선물거래": ("도박", "선물거래"),
    "괴수투기장": ("도박", "괴수투기장"),
    "생존룰렛": ("도박", "생존룰렛"),
    "생존선택": ("도박", "생존선택"),

    # 생활
    "알바": ("생활", "알바"),
    "코인": ("생활", "코인"),
    "채집": ("생활", "채집"),
    "낚시": ("생활", "낚시"),
    "벌목": ("생활", "벌목"),
    "광산": ("생활", "광산"),
    "자원": ("생활", "자원"),

    # 기지
    "기지": ("기지", "현황"),
    "기지건설": ("기지", "건설"),
    "기지강화": ("기지", "강화"),
    "기지수확": ("기지", "수확"),

    # 길드
    "길드목록": ("길드", "목록"),
    "길드생성": ("길드", "생성"),
    "길드가입": ("길드", "가입"),
    "길드정보": ("길드", "정보"),
    "길드기부": ("길드", "기부"),
    "길드강화": ("길드", "강화"),
    "길드탈퇴": ("길드", "탈퇴"),

    # 거래
    "지갑": ("거래", "지갑"),
    "송금": ("거래", "송금"),
    "거래소": ("거래", "거래소"),
    "판매": ("거래", "판매"),
    "구매등록번호": ("거래", "구매"),
    "판매취소": ("거래", "판매취소"),

    # 파티
    "파티생성": ("파티", "생성"),
    "파티가입": ("파티", "가입"),
    "파티정보": ("파티", "정보"),
    "파티사냥": ("파티", "사냥"),
    "파티탈퇴": ("파티", "탈퇴"),

    # 시즌 / 성장
    "일일퀘스트": ("시즌", "일일퀘스트"),
    "퀘스트보상": ("시즌", "일일보상"),
    "업적": ("시즌", "업적"),
    "칭호목록": ("시즌", "칭호목록"),
    "칭호": ("시즌", "칭호"),
    "랭킹": ("시즌", "랭킹"),
    "주간퀘스트": ("시즌", "주간퀘스트"),
    "주간보상": ("시즌", "주간보상"),
    "시즌패스": ("시즌", "시즌패스"),
    "시즌보상": ("시즌", "시즌보상"),

    # SERVER GUARD V4.1 (그룹당 최대 25개)
    "운영도움말": ("운영", "도움말"),
    "운영설정": ("운영", "설정"),
    "운영초기설정": ("운영", "초기설정"),
    "경고": ("운영", "경고"),
    "경고조회": ("운영", "경고조회"),
    "경고취소": ("운영", "경고취소"),
    "타임아웃": ("운영", "타임아웃"),
    "타임아웃해제": ("운영", "타임아웃해제"),
    "추방": ("운영", "추방"),
    "차단": ("운영", "차단"),
    "차단해제": ("운영", "차단해제"),
    "청소": ("운영", "청소"),
    "슬로우": ("운영", "슬로우"),
    "채널잠금": ("운영", "채널잠금"),
    "채널해제": ("운영", "채널해제"),
    "닉네임": ("운영", "닉네임"),
    "역할지급": ("운영", "역할지급"),
    "역할회수": ("운영", "역할회수"),
    "로그채널": ("운영", "로그채널"),
    "환영채널": ("운영", "환영채널"),
    "퇴장채널": ("운영", "퇴장채널"),
    "자동역할": ("운영", "자동역할"),
    "자동관리": ("운영", "자동관리"),
    "문의패널": ("운영", "문의패널"),
    "서버통계": ("운영", "서버통계"),

    # v18.5 커뮤니티 / 서버 편의
    "커뮤니티센터": ("커뮤니티", "센터"),
    "버튼역할패널": ("커뮤니티", "역할패널"),
    "버튼역할상태": ("커뮤니티", "역할상태"),
    "웹대시보드": ("커뮤니티", "대시보드"),
    "분대음성설정": ("커뮤니티", "임시음성설정"),
    "분대방이름": ("커뮤니티", "음성이름"),
    "분대방잠금": ("커뮤니티", "음성잠금"),
    "분대방초대": ("커뮤니티", "음성초대"),
    "분대방인원": ("커뮤니티", "음성인원"),
    "분대방방장": ("커뮤니티", "음성방장"),
    "하이라이트설정": ("커뮤니티", "하이라이트설정"),
    "하이라이트상태": ("커뮤니티", "하이라이트상태"),

    # 관리자용 최상위 하이브리드 명령어도 /관리 아래로 이동
    "가방조회": ("관리", "가방조회"),
    "식량지급": ("관리", "식량지급"),
    "식량회수": ("관리", "식량회수"),
    "월드보스리셋": ("관리", "월드보스리셋"),
    "월드보스체력": ("관리", "월드보스체력"),
    "월드보스종료": ("관리", "월드보스종료"),
}


# 이미 /펫 그룹에 동일 기능이 있으므로 최상위 slash만 제거하고 !명령어는 유지합니다.
REMOVE_TOP_LEVEL_SLASH = {
    "펫상점",
    "펫구매",
    "펫정보",
    "펫훈련",
}


# 기존 하이브리드 그룹에 하위 명령어로 붙일 항목
EXISTING_GROUP_ROUTES: Dict[str, Tuple[str, str]] = {
    "도감보상": ("도감", "보상"),
}


def _command_description(prefix_command: commands.Command) -> str:
    description = prefix_command.short_doc or prefix_command.description
    if not description:
        description = f"{prefix_command.name} 기능을 실행합니다."
    return description[:100]


def _remove_top_level_slash(bot: commands.Bot, prefix_command: commands.Command) -> bool:
    """하이브리드 명령어의 최상위 slash 등록만 제거하고 !명령어는 유지합니다."""
    if not isinstance(prefix_command, (commands.HybridCommand, commands.HybridGroup)):
        return False
    app_command = prefix_command.app_command
    if app_command is None or app_command.parent is not None:
        return False
    removed = bot.tree.remove_command(app_command.name)
    return removed is not None


def _make_slash_app_command(
    prefix_command: commands.Command,
    slash_name: str,
) -> app_commands.Command:
    """기존 명령어 로직을 그대로 사용하는 그룹용 slash 명령어를 만듭니다."""
    description = _command_description(prefix_command)

    # 기존 하이브리드 명령어는 app command를 복사해 체크, 자동완성, 옵션 정보를 보존합니다.
    if isinstance(prefix_command, commands.HybridCommand) and prefix_command.app_command is not None:
        app_command = prefix_command.app_command.copy()
        app_command.name = slash_name
        app_command.description = description
        return app_command

    # 기존 !전용 명령어는 같은 callback을 사용하는 slash bridge를 만듭니다.
    bridge = commands.HybridCommand(
        prefix_command.callback,
        name=prefix_command.name,
        description=description,
        enabled=prefix_command.enabled,
        hidden=prefix_command.hidden,
        cooldown_after_parsing=prefix_command.cooldown_after_parsing,
    )
    if bridge.app_command is None:
        raise RuntimeError(f"슬래시 명령어 생성 실패: {prefix_command.name}")

    bridge.app_command.name = slash_name
    bridge.app_command.description = description
    return bridge.app_command



def _validate_discord_command_names(bot: commands.Bot) -> None:
    """Fail before Discord HTTP 400 when a slash command or option uses uppercase letters."""
    invalid: list[str] = []

    def walk_option(option: dict, path: str) -> None:
        name = str(option.get("name", ""))
        if name and name != name.lower():
            invalid.append(f"{path} option={name}")
        for child in option.get("options", []) or []:
            walk_option(child, f"{path}/{name}")

    for command in bot.tree.get_commands():
        payload = command.to_dict(bot.tree)
        name = str(payload.get("name", ""))
        if name and name != name.lower():
            invalid.append(f"command={name}")
        for option in payload.get("options", []) or []:
            walk_option(option, f"/{name}")
    if invalid:
        raise RuntimeError("Discord 슬래시 이름 규칙 위반: " + ", ".join(invalid[:20]))

def register_grouped_slash_commands(bot: commands.Bot) -> None:
    """Discord 최상위 slash 100개 제한을 넘지 않도록 명령어를 그룹으로 묶습니다."""
    if getattr(bot, "_abaddon_slash_groups_registered", False):
        return

    groups = {
        name: app_commands.Group(name=name, description=description)
        for name, description in GROUP_DESCRIPTIONS.items()
    }

    missing = []
    resolved_routes = []

    # 먼저 모든 대상을 찾고 기존 최상위 slash를 제거해 그룹을 넣을 자리를 확보합니다.
    for prefix_name, (group_name, slash_name) in SLASH_ROUTES.items():
        prefix_command = bot.get_command(prefix_name)
        if prefix_command is None:
            missing.append(prefix_name)
            continue
        resolved_routes.append((prefix_command, group_name, slash_name))
        _remove_top_level_slash(bot, prefix_command)

    for prefix_name in REMOVE_TOP_LEVEL_SLASH:
        prefix_command = bot.get_command(prefix_name)
        if prefix_command is None:
            missing.append(prefix_name)
            continue
        _remove_top_level_slash(bot, prefix_command)

    # /도감 같은 이미 존재하는 하이브리드 그룹에 붙일 명령어도 미리 확인합니다.
    resolved_existing = []
    for prefix_name, (existing_group_name, slash_name) in EXISTING_GROUP_ROUTES.items():
        prefix_command = bot.get_command(prefix_name)
        existing_group = bot.get_command(existing_group_name)
        if prefix_command is None:
            missing.append(prefix_name)
            continue
        if not isinstance(existing_group, commands.HybridGroup) or not existing_group.app_command:
            raise RuntimeError(f"하이브리드 그룹을 찾을 수 없습니다: {existing_group_name}")
        resolved_existing.append((prefix_command, existing_group, slash_name))
        _remove_top_level_slash(bot, prefix_command)

    if missing:
        raise RuntimeError("슬래시 연결 대상 명령어 누락: " + ", ".join(sorted(missing)))

    # 그룹 하위 명령어를 구성합니다.
    for prefix_command, group_name, slash_name in resolved_routes:
        app_command = _make_slash_app_command(prefix_command, slash_name)
        groups[group_name].add_command(app_command)

    for prefix_command, existing_group, slash_name in resolved_existing:
        app_command = _make_slash_app_command(prefix_command, slash_name)
        existing_group.app_command.add_command(app_command)

    # 그룹을 최상위 트리에 등록합니다.
    for group in groups.values():
        bot.tree.add_command(group)

    # 설명이 없는 명령어도 Discord 메뉴에서 알아보기 쉽게 표시합니다.
    for app_command in bot.tree.walk_commands():
        if isinstance(app_command, app_commands.Command) and app_command.description == "…":
            app_command.description = f"{app_command.name} 기능을 실행합니다."

    root_count = len(bot.tree.get_commands())
    total_count = sum(1 for _ in bot.tree.walk_commands())
    if root_count > 100:
        raise RuntimeError(f"Discord 최상위 슬래시 명령어 제한 초과: {root_count}/100")

    _validate_discord_command_names(bot)

    bot._abaddon_slash_groups_registered = True
    bot._abaddon_slash_root_count = root_count
    bot._abaddon_slash_total_count = total_count
    print(f"[슬래시 구성] 최상위 {root_count}/100개 · 전체 {total_count}개", flush=True)
