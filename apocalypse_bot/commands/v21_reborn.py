import random
from datetime import datetime

import discord


OPTION_POOL = {
    "공격력": (1, 18),
    "방어력": (1, 18),
    "치명타": (1, 8),
    "회피": (1, 8),
    "감염저항": (1, 10),
    "행운": (1, 8),
}

SET_RULES = {
    "타이탄": {"keywords": ["타이탄", "중장갑"], "need": 2, "bonus": "공격력·방어력 +12", "power": 24},
    "심연": {"keywords": ["심연", "공허"], "need": 2, "bonus": "공격력 +18, 치명타 +4%", "power": 26},
    "천공": {"keywords": ["천공", "오메가"], "need": 2, "bonus": "방어력 +15, 회피 +4%", "power": 25},
    "종말": {"keywords": ["종말", "아포칼립스"], "need": 2, "bonus": "전투력 +35", "power": 35},
}

ROOMS = ["일반 전투", "함정", "보물방", "구조 신호", "정예 감염체", "오염 구역"]
HIDDEN_BOSSES = ["백색 포식자", "균열의 수문장", "지하왕 모르가나", "실험체 ZERO"]


PATCH_HISTORY = [
    {
        "version": "7.2.0",
        "date": "2026-08-03",
        "title": "통합 환영 · 패치 자동 공지 · 아바돈 동료전",
        "summary": "겹치던 입장 환영 메시지와 신규 역할을 하나로 합치고, 새 버전 공지 자동 게시와 혼자 즐기는 AI 미니게임을 추가했습니다.",
        "points": [
            "기존 환영 안내와 선택형 테마 패널을 통합하여 입장 메시지 1개만 전송",
            "기존 자동 역할과 새싹 역할을 단일 역할 설정으로 이관하고 임시/영구 모드 지원",
            "지정 패치 채널에 버전당 한 번 자동 게시하고 재부팅 중복 게시 차단",
            "아바돈과 1:1 미니게임 7종 및 전적 기록 추가",
            "생존자 레이스·포커·원카드·조커잡기 모집방에 아바돈 초대 동선 추가",
            "명령어/별칭 충돌, 중복 리스너, 저장/정산, Discord 컴포넌트 제한 재검사",
            "신규 이미지 없이 이모지·버튼·드롭다운만 사용",
        ],
    },
    {
        "version": "7.1.2",
        "date": "2026-08-03",
        "title": "선택형 환영 테마 · Render 시작 오류 핫픽스",
        "summary": "서버별 환영 테마 6종을 고정 선택하고 백업 명령 별칭 충돌로 발생한 Render 부팅 오류를 수정했습니다.",
        "points": [
            "새싹·벚꽃·버블·별빛·동물·아포칼립스 환영 테마 6종",
            "선택한 테마 안에서만 제목·문구·장식 이모지 랜덤 출력",
            "환영 역할 색상과 지원 서버의 역할 아이콘을 테마에 맞춰 반영",
            "!백업생성에서 기존 !데이터백업과 충돌하던 별칭 제거",
            "신규 이미지를 추가하지 않고 이모지 중심으로 구성",
            "신규 이미지 없이 표준 이모지·진행 게이지만 사용",
        ],
    },
    {
        "version": "7.0.2",
        "date": "2026-08-03",
        "title": "운영 안정화 · 데이터 보호 패치",
        "summary": "다중 시점 백업과 자동 복구, 사용자별 명령 트랜잭션 잠금, 성공·실패 통계와 관리자 운영 점검 도구를 추가했습니다.",
        "points": [
            "주 데이터·.bak·최근 정상 스냅샷 순서의 자동 복구 체계",
            "시작 시 및 50회 저장마다 검증된 회전 백업 생성",
            "사용자별 동시 명령 실행 잠금으로 중복 차감·중복 보상 위험 완화",
            "명령별 실행·성공·실패·평균 처리시간 통계",
            "최근 오류 사건 번호·명령·길드·사용자 기록",
            "!시스템점검·!오류현황·!백업목록·!백업생성·!백업검증·!복구미리보기 추가",
            "Render 재시작 시 데이터 원본과 복구 출처 표시",
            "v7.0.1 명령 UX와 v7.0.0 월드보스 시스템 보존",
        ],
    },
    {
        "version": "7.0.1",
        "date": "2026-08-03",
        "title": "초보자 접근성 · 명령어 가시성 패치",
        "summary": "처음 시작·오늘 추천·목적별 기능군을 추가하고 227개 게임 기능을 이해하기 쉬운 2단계 메뉴로 정리했습니다.",
        "points": [
            "!처음·!초보 5단계 시작 가이드 추가",
            "!명령어에 처음 시작·오늘 할 일·대표/전체 전환·검색 버튼 추가",
            "!도움말을 통합 명령어 브라우저로 연결",
            "!게임에 처음 시작·오늘 추천·목적별 빠른 경로 추가",
            "장비 26개·생활 35개 등 Discord 드롭다운 25개 제한 초과 문제 해결",
            "카지노·은행·스토리·월드보스·길드·거래 기능을 목적별 기능군으로 통합 표시",
            "기능 상세 화면에 실행 순서·입력 여부·직접 명령·위험 경고 표시",
            "기존 한국어 명령과 v6.5.4 영어 명령은 삭제 없이 모두 유지",
        ],
    },
    {
        "version": "7.0.0",
        "date": "2026-08-03",
        "title": "월드보스 리빌드 · 실전 기믹과 안전 보상 큐",
        "summary": "고품질 월드보스 아트 10종과 함께 보상 유실 방지, 테스트 샌드박스, 실제 약점·페이즈·부위 파괴·반격 시스템을 적용했습니다.",
        "points": [
            "처치 전투를 completed 보상 큐에 저장해 새 보스 출현 후에도 보상 수령 가능",
            "실전 active와 테스트 test_active 완전 분리, 테스트는 경제·내구도·도감 미반영",
            "보스 6종 약점을 장비 강화·직업·자원·유물·역할 다양성에 따라 실제 피해에 반영",
            "4단계 페이즈마다 방어·회피·패턴·반격 수치가 실제 변경",
            "보스별 부위 파괴 효과를 방어·회피·회복·환영·반격 시스템과 연결",
            "보스 반격 시 실제 식량 손실 적용, 테스트에서는 시뮬레이션만 표시",
            "월드보스 보상 목록·토벌 이력·테스트 상태/공격/종료 명령 추가",
            "월드보스 및 이벤트 배너 고품질 이미지 10종 교체",
        ],
    },
    {
        "version": "6.3.2",
        "date": "2026-08-01",
        "title": "생활 콘텐츠 2차 비주얼 · 랜덤 인카운트 확장",
        "summary": "낚시·광산·코인·도박 탐색·돈주세요 장면과 선택형 랜덤 인카운트를 추가하면서 기존 경제·도박·보물 감정 규칙을 보존했습니다.",
        "points": [
            "낚시·광산 각각 독립 2분 쿨타임",
            "코인 탐색 1분·하루 30회, 돈주세요 1분·하루 50회",
            "랜덤 인카운트 하루 최대 8회에서 12회로 확대",
            "특별 교섭 버튼 성공 시 추가 5,000~20,000 식량",
            "인카운트 성공 시 하루 최대 1회 영웅·전설 거래 장비 희귀 드롭",
            "탐색 방향·배팅·카지노 드롭다운과 감정사 NPC 시스템 보존",
        ],
    },
    {
        "version": "6.3.1",
        "date": "2026-08-01",
        "title": "생활 콘텐츠 1차 비주얼 · 버튼형 인카운트",
        "summary": "알바·땅파기·채집·벌목에 실제 장면형 이미지 풀과 결과 리액션, 선택형 인카운트를 적용했습니다.",
        "points": [
            "알바·땅파기·채집·벌목 각 12장, 실제 고유 장면 이미지 총 48장",
            "일반 성공·희귀 발견·실패·인카운트 발견·선택 결과 이미지 풀 분리",
            "다른 봇과 유사했던 알바 실패 문구를 ABADDON 오리지널 현장 사고로 교체",
            "콘텐츠별 TIP과 성공·희귀·실패 자동 이모지 리액션",
            "각 콘텐츠 3종씩 총 12종 버튼형 랜덤 인카운트",
            "실행자 전용 버튼·150초 제한·중복 클릭 방지·최근 조우 반복 방지",
            "`!인카운트도감` 추가, 신규 최상위 슬래시 명령은 없음",
        ],
    },
    {
        "version": "6.3.0",
        "date": "2026-08-01",
        "title": "다중 월드보스 · 전면 단계형 연출",
        "summary": "월드보스 6종과 전용 이미지, 기여도·보상·부위 파괴를 추가하고 지원금·알바·굴착·카지노 연출을 통합했습니다.",
        "points": [
            "검은 성역의 문지기부터 종말의 왕 아바돈까지 월드보스 6종",
            "서버 공동 HP·10회 일일 공격·45초 간격·4단계 페이즈·부위 파괴",
            "보스별 출현 이미지와 페이즈·광폭화·처치·보상 배너 10장",
            "기여도 순위와 처치 후 1회 수령 보상, 마지막 일격·상위권 칭호",
            "돈주세요·알바·땅파기 단계형 임베드와 로컬 이미지 카드",
            "카지노 기존 게임의 단계형 연출 전수 점검과 카지노 로비 이미지",
            "기존 탐색·주파수·룰렛·파산신청 중복 구현 비등록 처리",
            "게임 제어실에 독립 월드보스·레이드 카테고리 연결",
        ],
    },
    {
        "version": "6.2.4",
        "date": "2026-08-01",
        "title": "게임 결과 연출 · 실패 비용",
        "summary": "코인·땅파기·보물 감정·제작 결과를 단계형 연출과 항목별 임베드로 바꾸고, 실패 시 소액 비용이 발생합니다.",
        "points": [
            "코인 스캐너 회전 연출과 성공·실패 결과 임베드",
            "코인 탐색 실패 시 잔액을 넘지 않는 60~350 식량 수리비",
            "땅파기 발견물·굴착 잔돈·현재 보유량을 한눈에 표시",
            "보물 감정 준비·분석·등급 공개 단계 연출",
            "제작 실패 확률과 무작위 작업대 수리비, 제작 재료 보존",
            "새 명령어와 슬래시 명령 추가 없음",
        ],
    },
    {
        "version": "6.2.3",
        "date": "2026-08-01",
        "title": "게임 제어실 굴착·보물 연결",
        "summary": "누락됐던 땅파기와 보물 감정 기능을 `!게임` 드롭다운에 정식 연결했습니다.",
        "points": [
            "신규 `⛏️ 굴착·보물` 게임 카테고리",
            "`!땅파기`, `!보물함`, `!감정사`, `!보물감정` 연결",
            "게임 검색·즐겨찾기·최근 실행에서 굴착 기능 지원",
            "카테고리별 선택지 25개 제한을 피하기 위해 독립 분류",
            "전체 게임 연결 기능 195개",
        ],
    },
    {
        "version": "6.2.2",
        "date": "2026-08-01",
        "title": "패치노트 기록실",
        "summary": "접두사와 슬래시 명령 하나로 최신·이전 업데이트를 드롭다운과 버튼으로 열람합니다.",
        "points": [
            "`!패치노트`, `!업데이트`, `/패치노트` 통합",
            "버전 선택 드롭다운과 이전·다음·최신 버튼",
            "최근 주요 버전의 핵심 변경 사항 보관",
            "기존 V2.1 고정 문구를 현재 통합 패치 기록으로 교체",
            "새 슬래시 명령 추가 없이 기존 명령을 갱신",
        ],
    },
    {
        "version": "6.2.1",
        "date": "2026-08-01",
        "title": "자연 연속 대화 · 굴착 잔돈",
        "summary": "모달 없이 대화를 시작하고 일반 채팅과 답글로 이어가며, 땅파기마다 소량의 생존 자금을 얻습니다.",
        "points": [
            "`!말걸기` 이후 15분·최대 30회 연속 대화",
            "아바돈 메시지 답글과 멘션 대화 연결",
            "감정·게임·TTS·스토리·보물 관련 응답 확장",
            "`!땅파기`마다 8~35 식량 추가 지급",
        ],
    },
    {
        "version": "6.2.0",
        "date": "2026-08-01",
        "title": "독립 대화 코어 · 기억 공방",
        "summary": "서버 구성원이 지식을 제출하고 운영진이 검수하며, 아바돈과 대화·질문·교감 기능을 이용합니다.",
        "points": [
            "`!가르치기` 기억 등록 양식",
            "일반 사용자 제출 검수 대기와 운영진 승인·반려",
            "`!대화`, `!아바돈`, 오늘의 질문·밸런스게임",
            "민감정보·멘션·도배 방지 안전 필터",
        ],
    },
    {
        "version": "6.1.0",
        "date": "2026-08-01",
        "title": "채널 규칙 일괄설치 · 땅파기 · 보물 감정",
        "summary": "여러 채널의 안내 규칙을 안전하게 설치하고, 굴착과 감정사 기반 보물 경제를 추가했습니다.",
        "points": [
            "최대 25개 채널 규칙 일괄 선택·미리보기",
            "채널별 자동 규칙 추천과 안전 간격 설치",
            "하루 50회·1분 쿨타임 `!땅파기`",
            "A~E 보물 등급과 감정사 4명",
        ],
    },
    {
        "version": "6.0.2",
        "date": "2026-08-01",
        "title": "채널 규칙 자동 작성·고정",
        "summary": "채널 성격에 맞는 규칙을 미리보고 작성·고정하며 기존 메시지는 중복 없이 갱신합니다.",
        "points": [
            "25종 채널 규칙 템플릿",
            "채널 이름·주제 기반 자동 추천",
            "작성·미리보기·갱신·제거 제어실",
            "메시지 관리 권한 진단",
        ],
    },
    {
        "version": "6.0.1",
        "date": "2026-08-01",
        "title": "게임 즐겨찾기 · 검색 · 안전 미리보기",
        "summary": "게임 기능을 바로 실행하지 않고 확인한 뒤 실행하며 즐겨찾기와 최근 실행, 검색을 제공합니다.",
        "points": [
            "게임 기능 상세 미리보기 후 실행",
            "사용자별 즐겨찾기 최대 20개",
            "최근 실행 최대 10개",
            "이름·설명·명령어 통합 검색",
        ],
    },
    {
        "version": "6.0.0",
        "date": "2026-08-01",
        "title": "통합 게임 제어실 · 종말의 왕좌",
        "summary": "기존 게임 기능을 카테고리 드롭다운으로 묶고 스토리 시즌 3을 추가했습니다.",
        "points": [
            "9개 게임 카테고리 통합 제어실",
            "기존 직접 입력 명령 호환 유지",
            "스토리 시즌 3 종말의 왕좌",
            "신규 장면·선택지·엔딩·보상",
        ],
    },
    {
        "version": "5.2.1",
        "date": "2026-08-01",
        "title": "통합 진단 · 설정 제어실",
        "summary": "봇 상태와 서버 주요 설정을 드롭다운에서 확인하고 관리합니다.",
        "points": [
            "`!아바돈진단` 통합 점검",
            "TTS·리뉴얼·슬래시·피드·권한 진단",
            "`!설정` 채널·엔진·환영·로그 관리",
            "오류 보고서 생성",
        ],
    },
    {
        "version": "5.2.0",
        "date": "2026-08-01",
        "title": "리뉴얼 안전 자동진행 · TTS 음성 격리",
        "summary": "서버 리뉴얼을 안전 간격으로 진행하고 반복 실패하는 Edge 음성만 임시 격리합니다.",
        "points": [
            "리뉴얼 계획 안전 자동 진행",
            "429 감지 시 자동 격리·중지",
            "Edge 목소리별 회로 차단",
            "대체 음성과 최근 합성 경로 표시",
        ],
    },

]

PATCH_HISTORY_BY_VERSION = {entry["version"]: entry for entry in PATCH_HISTORY}


def _patch_note_embed(index: int) -> discord.Embed:
    index = max(0, min(index, len(PATCH_HISTORY) - 1))
    entry = PATCH_HISTORY[index]
    latest = index == 0
    embed = discord.Embed(
        title=f"{'🔥' if latest else '📜'} ABADDON v{entry['version']} · {entry['title']}",
        description=entry["summary"],
        color=0xE67E22 if latest else 0x5B2C6F,
    )
    embed.add_field(
        name="주요 변경",
        value="\n".join(f"• {point}" for point in entry["points"]),
        inline=False,
    )
    embed.add_field(name="배포 기록", value=f"{entry['date']} · {'현재 최신 통합본' if latest else '이전 통합 패치'}", inline=False)
    embed.set_footer(text=f"기록 {index + 1}/{len(PATCH_HISTORY)} · 드롭다운 또는 버튼으로 이동")
    return embed


class PatchNotesView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = int(owner_id)
        self.index = 0
        self.message = None

        self.selector = discord.ui.Select(
            placeholder="열람할 패치 버전을 선택하세요",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f"v{entry['version']} · {entry['title']}",
                    value=str(i),
                    description=entry["summary"][:100],
                    emoji="🔥" if i == 0 else "📜",
                    default=i == 0,
                )
                for i, entry in enumerate(PATCH_HISTORY)
            ],
        )
        self.selector.callback = self._select_callback
        self.add_item(self.selector)

        self.previous_button = discord.ui.Button(label="이전", emoji="◀️", style=discord.ButtonStyle.secondary, disabled=True)
        self.latest_button = discord.ui.Button(label="최신", emoji="🔥", style=discord.ButtonStyle.primary, disabled=True)
        self.next_button = discord.ui.Button(label="다음", emoji="▶️", style=discord.ButtonStyle.secondary, disabled=len(PATCH_HISTORY) <= 1)
        self.previous_button.callback = self._previous_callback
        self.latest_button.callback = self._latest_callback
        self.next_button.callback = self._next_callback
        self.add_item(self.previous_button)
        self.add_item(self.latest_button)
        self.add_item(self.next_button)

    def _sync_controls(self) -> None:
        self.previous_button.disabled = self.index <= 0
        self.latest_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(PATCH_HISTORY) - 1
        for option in self.selector.options:
            option.default = option.value == str(self.index)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message("⚠️ 이 패치노트 제어실은 명령을 실행한 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def _show(self, interaction: discord.Interaction, index: int) -> None:
        self.index = max(0, min(int(index), len(PATCH_HISTORY) - 1))
        self._sync_controls()
        await interaction.response.edit_message(embed=_patch_note_embed(self.index), view=self)

    async def _select_callback(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, int(self.selector.values[0]))

    async def _previous_callback(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, self.index - 1)

    async def _latest_callback(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, 0)

    async def _next_callback(self, interaction: discord.Interaction) -> None:
        await self._show(interaction, self.index + 1)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


def _ensure_user(u):
    u.setdefault("equipment_options", {})
    u.setdefault("dungeon_v21", {"max_floor": 1, "best_floor": 0, "clears": 0, "hidden_kills": 0})
    for key, value in {"max_floor": 1, "best_floor": 0, "clears": 0, "hidden_kills": 0}.items():
        u["dungeon_v21"].setdefault(key, value)
    u.setdefault("life_mastery", {"채집": 0, "낚시": 0, "벌목": 0, "광산": 0})
    for key in ["채집", "낚시", "벌목", "광산"]:
        u["life_mastery"].setdefault(key, 0)
    u.setdefault("worldboss_codex", {})
    u.setdefault("market_history", [])
    u.setdefault("materials", {})
    u["materials"].setdefault("강화석", 0)
    u["materials"].setdefault("강화보호권", 0)
    u["materials"].setdefault("옵션재설정권", 0)
    return u


def _option_count(tier):
    return {"일반": 1, "고급": 1, "희귀": 2, "영웅": 2, "전설": 3, "신화": 3, "유일": 4}.get(tier, 1)


def _roll_options(tier):
    result = {}
    keys = random.sample(list(OPTION_POOL), k=min(_option_count(tier), len(OPTION_POOL)))
    tier_mult = {"일반": 0.7, "고급": 0.9, "희귀": 1.1, "영웅": 1.35, "전설": 1.65, "신화": 2.0, "유일": 2.5}.get(tier, 1.0)
    for key in keys:
        low, high = OPTION_POOL[key]
        result[key] = max(1, int(random.randint(low, high) * tier_mult))
    return result


def _format_options(options):
    if not options:
        return "옵션 없음"
    return ", ".join(f"{k} +{v}{'%' if k in {'치명타', '회피', '감염저항'} else ''}" for k, v in options.items())


def _set_status(u):
    equipped = [x for x in u.get("equipment", {}).values() if x]
    lines = []
    total_power = 0
    for name, rule in SET_RULES.items():
        count = sum(1 for item in equipped if any(keyword in item for keyword in rule["keywords"]))
        active = count >= rule["need"]
        if active:
            total_power += rule["power"]
        lines.append(f"{'✅' if active else '⬜'} **{name} 세트** {count}/{rule['need']} — {rule['bonus']}")
    return lines, total_power


def register_v21_commands(
    bot,
    get_user,
    check_registered,
    save_data,
    send_pages,
    world_data,
    item_db,
    materials,
    find_item,
    calculate_user_power,
    spend_stamina,
    apply_damage,
    get_max_hp,
    add_season_points,
):
    for material in ["강화석", "강화보호권", "옵션재설정권"]:
        if material not in materials:
            materials.append(material)

    @bot.hybrid_command(
        name="패치노트",
        aliases=["업데이트", "변경내역"],
        description="아바돈의 최신·이전 업데이트 기록을 드롭다운으로 확인합니다.",
    )
    async def patch_notes(ctx):
        view = PatchNotesView(ctx.author.id)
        view.message = await ctx.send(embed=_patch_note_embed(0), view=view)

    @bot.command(name="강화정보")
    async def enhance_info(ctx, *, item_name: str):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        if item_name not in u.get("inventory", []):
            await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
            return
        _, info = find_item(item_name)
        current = u.get("enhancements", {}).get(item_name, 0)
        cost = int(info["price"] * (0.12 + current * 0.04))
        rate = max(15, 90 - current * 4)
        stone_need = 1 + current // 5
        await ctx.send(
            f"🔨 **[{item_name} 강화 정보]**\n"
            f"현재: **+{current}** / 다음 성공 확률: **{rate}%**\n"
            f"식량 비용: **{cost:,}개** / 강화석 권장: **{stone_need}개**\n"
            f"+10 이상 실패 시 단계 하락 가능\n"
            f"보호 강화: `!보호강화 {item_name}`"
        )

    @bot.command(name="보호강화")
    async def protected_enhance(ctx, *, item_name: str):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        if item_name not in u.get("inventory", []):
            await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
            return
        current = u["enhancements"].get(item_name, 0)
        if current >= 20:
            await ctx.send("⚠️ 이미 최대 강화 수치 +20입니다.")
            return
        _, info = find_item(item_name)
        cost = int(info["price"] * (0.18 + current * 0.05))
        stones = 1 + current // 5
        if u["materials"].get("강화보호권", 0) < 1:
            await ctx.send("⚠️ **강화보호권 1개**가 필요합니다. 심층 던전과 월드보스에서 획득할 수 있습니다.")
            return
        if u["materials"].get("강화석", 0) < stones:
            await ctx.send(f"⚠️ **강화석 {stones}개**가 필요합니다.")
            return
        if u.get("balance", 0) < cost:
            await ctx.send(f"⚠️ 식량 **{cost:,}개**가 필요합니다.")
            return
        u["balance"] -= cost
        u["materials"]["강화보호권"] -= 1
        u["materials"]["강화석"] -= stones
        rate = min(95, max(25, 95 - current * 3))
        if random.randint(1, 100) <= rate:
            u["enhancements"][item_name] = current + 1
            u.setdefault("stats", {}).setdefault("enhance_success", 0)
            u["stats"]["enhance_success"] += 1
            text = f"✅ 보호 강화 성공! **{item_name} +{current + 1}**"
        else:
            text = "🛡️ 강화 실패! 보호권이 장비의 강화 하락을 막았습니다."
        save_data()
        await ctx.send(f"🔨 **[보호 강화]**\n{text}\n성공 확률: **{rate}%** / 비용: **{cost:,}개**")

    @bot.command(name="강화랭킹")
    async def enhance_ranking(ctx):
        rows = []
        for uid in list(getattr(world_data, "keys", lambda: [])()):
            pass
        # 등록 유저는 bot 모듈의 get_user를 통해 접근할 수 없어 world_data와 분리되어 있으므로 guild 멤버를 기준으로 조회한다.
        if not ctx.guild:
            await ctx.send("⚠️ 서버 안에서 사용해 주세요.")
            return
        for member in ctx.guild.members:
            u = get_user(member.id)
            if not u:
                continue
            best = max(u.get("enhancements", {}).values(), default=0)
            total = sum(u.get("enhancements", {}).values())
            rows.append((best, total, member.id))
        rows.sort(reverse=True)
        lines = [f"{i}. <@{uid}> — 최고 **+{best}** / 총합 **{total}**" for i, (best, total, uid) in enumerate(rows[:20], 1)]
        await ctx.send("🏆 **[강화 랭킹]**\n" + ("\n".join(lines) if lines else "기록 없음"))

    @bot.command(name="장비옵션")
    async def equipment_option(ctx, *, item_name: str):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        if item_name not in u.get("inventory", []) and item_name not in u.get("equipment", {}).values():
            await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
            return
        tier, _ = find_item(item_name)
        if item_name not in u["equipment_options"]:
            u["equipment_options"][item_name] = _roll_options(tier)
            save_data()
        await ctx.send(f"💎 **[{item_name} 랜덤 옵션]**\n{_format_options(u['equipment_options'][item_name])}\n재설정: `!옵션재설정 {item_name}`")

    @bot.command(name="옵션재설정")
    async def reroll_option(ctx, *, item_name: str):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        if item_name not in u.get("inventory", []) and item_name not in u.get("equipment", {}).values():
            await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
            return
        tier, info = find_item(item_name)
        ticket = u["materials"].get("옵션재설정권", 0)
        cost = max(1500, info["price"] // 8)
        if ticket > 0:
            u["materials"]["옵션재설정권"] -= 1
            paid = "옵션재설정권 1개"
        elif u.get("balance", 0) >= cost:
            u["balance"] -= cost
            paid = f"식량 {cost:,}개"
        else:
            await ctx.send(f"⚠️ 옵션재설정권 또는 식량 **{cost:,}개**가 필요합니다.")
            return
        u["equipment_options"][item_name] = _roll_options(tier)
        save_data()
        await ctx.send(f"✨ **옵션 재설정 완료** ({paid})\n{item_name}: {_format_options(u['equipment_options'][item_name])}")

    @bot.command(name="세트효과")
    async def set_effect(ctx):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        lines, power = _set_status(u)
        await ctx.send("🧬 **[장비 세트 효과]**\n" + "\n".join(lines) + f"\n\n활성 세트 추가 전투력: **+{power}**")

    @bot.command(name="심층던전", aliases=["층던전"])
    async def deep_dungeon(ctx, floor: int = None):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        state = u["dungeon_v21"]
        floor = floor or state["max_floor"]
        if floor < 1 or floor > 100:
            await ctx.send("⚠️ 층은 1~100 사이로 입력하세요.")
            return
        if floor > state["max_floor"]:
            await ctx.send(f"🔒 현재 입장 가능한 최고 층은 **{state['max_floor']}층**입니다.")
            return
        stamina_cost = min(45, 12 + floor // 4)
        if not spend_stamina(u, stamina_cost):
            await ctx.send(f"⚠️ 스태미나가 부족합니다. 필요: **{stamina_cost}**")
            return
        room = random.choice(ROOMS)
        enemy_power = 12 + floor * 5 + random.randint(0, floor * 2 + 5)
        user_power = calculate_user_power(u)
        event_bonus = 0
        damage = 0
        details = []
        hidden = floor % 10 == 0 and random.random() < 0.45
        if hidden:
            room = f"히든 보스: {random.choice(HIDDEN_BOSSES)}"
            enemy_power = int(enemy_power * 1.7)
        if room == "함정":
            damage = random.randint(4, 10 + floor // 3)
            apply_damage(u, damage)
            event_bonus = -5
            details.append(f"🪤 함정 피해 **{damage}**")
        elif room == "보물방":
            event_bonus = 25
            details.append("💰 보물방 발견: 보상 증가")
        elif room == "구조 신호":
            heal = min(20, get_max_hp(u) - u.get("hp", 0))
            u["hp"] = min(get_max_hp(u), u.get("hp", 0) + heal)
            event_bonus = 10
            details.append(f"🚑 생존자 구조: HP **{heal} 회복**")
        elif room == "오염 구역":
            u["infection"] = min(100, u.get("infection", 0) + random.randint(2, 6))
            event_bonus = -3
            details.append("☣️ 감염도가 상승했습니다.")
        roll = user_power + random.randint(0, max(10, user_power // 2)) + event_bonus
        win = roll >= enemy_power
        if win:
            reward = 700 + floor * 260
            exp = 70 + floor * 24
            if room == "보물방":
                reward = int(reward * 1.8)
            if hidden:
                reward *= 3
                exp *= 2
                state["hidden_kills"] += 1
            u["balance"] += reward
            u["exp"] += exp
            state["clears"] += 1
            state["best_floor"] = max(state["best_floor"], floor)
            if floor == state["max_floor"] and floor < 100:
                state["max_floor"] += 1
            stone = 1 + floor // 20
            u["materials"]["강화석"] += stone
            drops = [f"강화석 {stone}개"]
            if random.random() < 0.05 + floor / 1000:
                u["materials"]["강화보호권"] += 1
                drops.append("강화보호권 1개")
            if random.random() < 0.04 + floor / 1500:
                u["materials"]["옵션재설정권"] += 1
                drops.append("옵션재설정권 1개")
            add_season_points(u, 8 + floor // 5)
            result = f"✅ **{floor}층 돌파 성공!** 식량 {reward:,} · 경험치 {exp:,}\n🎁 " + ", ".join(drops)
        else:
            loss = random.randint(8, 18 + floor // 2)
            apply_damage(u, loss)
            result = f"❌ **{floor}층 공략 실패** · HP 피해 **{loss}**"
        save_data()
        await ctx.send(
            f"🏰 **[심층 던전 {floor}층]**\n방: **{room}**\n"
            f"내 전투력 판정 **{roll}** vs 적 전투력 **{enemy_power}**\n"
            + ("\n".join(details) + "\n" if details else "") + result
        )

    @bot.command(name="던전기록")
    async def dungeon_record(ctx):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        d = u["dungeon_v21"]
        await ctx.send(
            f"🏰 **[{ctx.author.display_name}의 심층 던전 기록]**\n"
            f"입장 가능: **{d['max_floor']}층** / 최고 기록: **{d['best_floor']}층**\n"
            f"누적 클리어: **{d['clears']}회** / 히든 보스 처치: **{d['hidden_kills']}회**"
        )

    @bot.command(name="보스도감")
    async def boss_codex(ctx):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        if not u["worldboss_codex"]:
            await ctx.send("📕 아직 기록된 월드보스가 없습니다. 월드보스 전투에 참가해 보세요.")
            return
        lines = []
        for name, rec in sorted(u["worldboss_codex"].items(), key=lambda x: x[1].get("damage", 0), reverse=True):
            lines.append(f"• **{name}** — 피해 {rec.get('damage', 0):,} / 공격 {rec.get('attacks', 0)}회 / 처치 참여 {rec.get('kills', 0)}회")
        await send_pages(ctx.channel, "📕 **[월드보스 도감]**\n" + "\n".join(lines))

    @bot.command(name="생활숙련도")
    async def life_mastery(ctx):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        lines = []
        for name, exp in u["life_mastery"].items():
            level = 1 + exp // 20
            bonus = min(30, (level - 1) * 2)
            lines.append(f"• {name}: **Lv.{level}** ({exp % 20}/20) · 추가 획득 확률 **+{bonus}%**")
        await ctx.send("🎣 **[생활 숙련도]**\n" + "\n".join(lines))

    @bot.command(name="종합랭킹")
    async def total_ranking(ctx):
        if not ctx.guild:
            await ctx.send("⚠️ 서버 안에서 사용해 주세요.")
            return
        rows = []
        for member in ctx.guild.members:
            u = get_user(member.id)
            if not u:
                continue
            _ensure_user(u)
            score = calculate_user_power(u) * 10 + u.get("level", 1) * 50 + u.get("stats", {}).get("worldboss_damage", 0) // 100 + u["dungeon_v21"]["best_floor"] * 100
            rows.append((score, member.id, calculate_user_power(u), u["dungeon_v21"]["best_floor"]))
        rows.sort(reverse=True)
        lines = [f"{i}. <@{uid}> — 종합 **{score:,}점** · 전투력 {power:,} · 심층 {floor}층" for i, (score, uid, power, floor) in enumerate(rows[:20], 1)]
        await ctx.send("🏆 **[종합 생존자 랭킹]**\n" + ("\n".join(lines) if lines else "기록 없음"))

    @bot.command(name="거래검색")
    async def market_search(ctx, *, keyword: str):
        if not await check_registered(ctx):
            return
        listings = world_data.setdefault("market", {})
        lines = []
        for listing_id, listing in sorted(listings.items(), key=lambda x: int(x[0])):
            if keyword.lower() not in listing.get("item", "").lower():
                continue
            kind = "경매" if listing.get("auction") else "즉시구매"
            price = listing.get("highest_bid", listing.get("price", 0))
            lines.append(f"`#{listing_id}` **{listing.get('item')} +{listing.get('enhance', 0)}** | {kind} **{price:,}개**")
        await send_pages(ctx.channel, f"🔎 **[거래소 검색: {keyword}]**\n" + ("\n".join(lines[:50]) if lines else "검색 결과 없음"))

    @bot.command(name="경매등록")
    async def auction_register(ctx, item_name: str, start_price: int):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        if item_name not in u.get("inventory", []):
            await ctx.send("⚠️ 보유하지 않은 장비입니다.")
            return
        if start_price < 100:
            await ctx.send("⚠️ 시작가는 100 이상이어야 합니다.")
            return
        listing_id = str(world_data.setdefault("market_next_id", 1))
        world_data["market_next_id"] += 1
        enhance = u["enhancements"].get(item_name, 0)
        options = u["equipment_options"].pop(item_name, None)
        u["inventory"].remove(item_name)
        u["enhancements"].pop(item_name, None)
        world_data.setdefault("market", {})[listing_id] = {
            "seller": str(ctx.author.id), "item": item_name, "enhance": enhance,
            "price": start_price, "auction": True, "highest_bid": 0,
            "highest_bidder": None, "options": options, "created": datetime.now().isoformat(),
        }
        save_data()
        await ctx.send(f"🔨 경매 등록 완료 `#{listing_id}` — **{item_name} +{enhance}**, 시작가 **{start_price:,}개**")

    @bot.command(name="입찰")
    async def bid(ctx, listing_number: int, amount: int):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        listing = world_data.setdefault("market", {}).get(str(listing_number))
        if not listing or not listing.get("auction"):
            await ctx.send("⚠️ 해당 번호는 진행 중인 경매가 아닙니다.")
            return
        if listing["seller"] == str(ctx.author.id):
            await ctx.send("⚠️ 자신의 경매에는 입찰할 수 없습니다.")
            return
        minimum = max(listing.get("price", 0), listing.get("highest_bid", 0) + 100)
        if amount < minimum:
            await ctx.send(f"⚠️ 최소 입찰가는 **{minimum:,}개**입니다.")
            return
        if u.get("balance", 0) < amount:
            await ctx.send("⚠️ 보유 식량이 부족합니다.")
            return
        previous_uid = listing.get("highest_bidder")
        previous_bid = listing.get("highest_bid", 0)
        if previous_uid:
            previous = get_user(previous_uid)
            if previous:
                previous["balance"] += previous_bid
        u["balance"] -= amount
        listing["highest_bid"] = amount
        listing["highest_bidder"] = str(ctx.author.id)
        save_data()
        await ctx.send(f"🔨 <@{ctx.author.id}> 입찰 완료! `#{listing_number}` 현재 최고가 **{amount:,}개**")

    @bot.command(name="경매마감")
    async def auction_close(ctx, listing_number: int):
        if not await check_registered(ctx):
            return
        listing_id = str(listing_number)
        listing = world_data.setdefault("market", {}).get(listing_id)
        if not listing or not listing.get("auction"):
            await ctx.send("⚠️ 해당 번호는 진행 중인 경매가 아닙니다.")
            return
        is_admin = bool(ctx.guild and ctx.author.guild_permissions.administrator)
        if listing["seller"] != str(ctx.author.id) and not is_admin:
            await ctx.send("⚠️ 판매자 또는 관리자만 경매를 마감할 수 있습니다.")
            return
        seller = get_user(listing["seller"])
        bidder_id = listing.get("highest_bidder")
        if not bidder_id:
            if seller:
                seller["inventory"].append(listing["item"])
                seller["enhancements"][listing["item"]] = listing.get("enhance", 0)
                if listing.get("options"):
                    _ensure_user(seller)["equipment_options"][listing["item"]] = listing["options"]
            del world_data["market"][listing_id]
            save_data()
            await ctx.send("📦 입찰자가 없어 장비가 판매자에게 반환됐습니다.")
            return
        bidder = _ensure_user(get_user(bidder_id))
        bidder["inventory"].append(listing["item"])
        bidder["enhancements"][listing["item"]] = listing.get("enhance", 0)
        if listing.get("options"):
            bidder["equipment_options"][listing["item"]] = listing["options"]
        fee = max(1, int(listing["highest_bid"] * 0.05))
        payout = listing["highest_bid"] - fee
        if seller:
            seller["balance"] += payout
            _ensure_user(seller)["market_history"].append({"type": "판매", "item": listing["item"], "price": listing["highest_bid"], "date": datetime.now().isoformat()})
        bidder["market_history"].append({"type": "구매", "item": listing["item"], "price": listing["highest_bid"], "date": datetime.now().isoformat()})
        del world_data["market"][listing_id]
        save_data()
        await ctx.send(f"✅ 경매 마감! <@{bidder_id}> 낙찰 **{listing['highest_bid']:,}개** · 판매자 수령 **{payout:,}개** (수수료 5%)")

    @bot.command(name="거래기록")
    async def market_history(ctx):
        if not await check_registered(ctx):
            return
        u = _ensure_user(get_user(ctx.author.id))
        rows = u["market_history"][-15:]
        if not rows:
            await ctx.send("📭 저장된 거래 기록이 없습니다.")
            return
        lines = [f"• {r.get('type')} **{r.get('item')}** — {r.get('price', 0):,}개" for r in reversed(rows)]
        await ctx.send("📒 **[최근 거래 기록]**\n" + "\n".join(lines))
