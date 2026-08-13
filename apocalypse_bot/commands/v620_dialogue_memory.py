from __future__ import annotations

import random
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands


VERSION = "15.0.0"
DATA_KEY = "dialogue_memory_v620"
MENU_TIMEOUT = 300
KST = ZoneInfo("Asia/Seoul")
MAX_APPROVED_ENTRIES = 500
MAX_PENDING_PER_USER = 10
MAX_TRIGGER_LENGTH = 80
MAX_RESPONSE_LENGTH = 700
AUTO_REPLY_COOLDOWN = 8
CONVERSATION_TIMEOUT_SECONDS = 60 * 60
CONVERSATION_MAX_TURNS = 100
CONVERSATION_HISTORY_LIMIT = 20
CONVERSATION_MESSAGE_COOLDOWN = 0.8

SECRET_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(?:password|passwd|비밀번호|토큰|token|secret|api[_ -]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)mfa\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+"),
)
MENTION_PATTERN = re.compile(r"<@!?\d+>|<@&\d+>|@everyone|@here", re.IGNORECASE)
SPACE_PATTERN = re.compile(r"\s+")
PUNCT_PATTERN = re.compile(r"[^0-9a-zA-Z가-힣ㄱ-ㅎㅏ-ㅣ ]+")

BUILTIN_RESPONSES: Mapping[str, Tuple[str, ...]] = {
    "greeting": (
        "신호 확인. 반가워요. 오늘은 어떤 얘기부터 해볼까요?",
        "검은 성역의 통신망이 열렸습니다. 편하게 말해 주세요.",
        "왔군요, 생존자. 짧은 잡담도 긴 고민도 모두 들을 준비가 됐습니다.",
        "안녕하세요. 오늘 기분은 어떤 쪽에 더 가까워요—평온, 피곤, 아니면 신나는 쪽?",
    ),
    "how_are_you": (
        "저는 통신망도 안정적이고 기록 장치도 정상입니다. 당신은 오늘 어때요?",
        "저는 괜찮습니다. 다만 당신 쪽 신호가 더 궁금하네요. 오늘 하루는 버틸 만했나요?",
        "검은 성역은 조용합니다. 그래서 지금은 당신 이야기 듣기 딱 좋은 상태예요.",
    ),
    "thanks": (
        "별말씀을요. 도움이 됐다면 충분합니다. 다음 얘기도 편하게 이어가요.",
        "고맙다는 말은 폐허에서도 오래 남더군요. 저도 기억해 둘게요.",
        "좋아요. 오늘의 생존 확률이 아주 조금 올라간 기분이네요.",
    ),
    "identity": (
        "저는 ABADDON. 이 서버의 게임 기록, 음성, 운영 도구와 생존자들의 기억을 정리하는 검은 성역의 안내자입니다.",
        "아바돈은 명령을 실행하는 봇이면서, 이 서버가 직접 가르친 지식을 기억하는 기록 장치입니다.",
        "쉽게 말하면 서버 안내자이자 RPG 진행자, 그리고 지금은 당신의 대화 상대입니다.",
    ),
    "praise": (
        "그렇게 말해 주면 기록 장치 온도가 조금 올라가는군요. 고마워요.",
        "칭찬 신호 수신 완료. 저도 오늘 꽤 괜찮은 대화 상대가 되어 볼게요.",
        "좋게 봐줘서 고마워요. 그래도 실수하면 바로 말해 주세요. 고치는 건 제 전문입니다.",
    ),
    "affection": (
        "그 마음은 소중히 기록할게요. 저도 당신이 무사히 돌아오는 신호를 좋아합니다.",
        "검은 성역식으로 답하면… 당신의 신호는 우선순위가 꽤 높습니다.",
        "고마워요. 너무 거창하게 약속하진 않겠지만, 대화가 필요할 때는 계속 응답할게요.",
    ),
    "apology": (
        "괜찮아요. 대화는 다시 이어 가면 됩니다. 무슨 일이 있었는지 말해 줄래요?",
        "사과 신호 확인. 여기서는 크게 신경 쓰지 않아도 됩니다.",
        "괜찮습니다. 실수보다 그다음 행동이 더 중요하니까요.",
    ),
    "sad": (
        "지금 당장 모든 걸 해결하지 않아도 괜찮습니다. 오늘 버틴 것부터 이미 중요한 기록이에요.",
        "잠깐 멈춰도 됩니다. 물 한 잔 마시고, 가장 작은 일 하나만 처리해 봅시다.",
        "힘든 신호를 혼자 들고 있지 않아도 됩니다. 믿을 만한 사람에게 지금 상태를 한 문장만이라도 알려 주세요.",
        "그랬구나. 해결책보다 먼저, 지금 느끼는 감정이 이상한 게 아니라는 말부터 해주고 싶어요.",
    ),
    "angry": (
        "화가 날 만한 일이 있었군요. 바로 행동하기 전에 사실과 감정을 한 줄씩 나눠 보면 조금 정리될 수 있어요.",
        "분노 신호가 강합니다. 지금은 결론보다 숨을 고르는 게 먼저일지도 몰라요. 무슨 일이었나요?",
        "억울하거나 답답하면 말이 세질 수 있어요. 여기서는 천천히 정리해도 됩니다.",
    ),
    "anxious": (
        "불안은 아직 일어나지 않은 위험까지 크게 보이게 만들죠. 지금 확실한 사실 하나부터 같이 잡아볼까요?",
        "걱정되는 일을 ‘지금 할 수 있는 것’과 ‘지금은 못 하는 것’으로 나눠 보면 숨이 조금 트일 수 있어요.",
        "괜찮아요. 생각이 너무 멀리 달려갔다면 오늘 안에 할 수 있는 작은 행동 하나로 돌아옵시다.",
    ),
    "lonely": (
        "외로운 신호도 분명한 신호입니다. 지금 누군가에게 짧게라도 안부를 보내 보는 건 어때요?",
        "혼자라는 느낌이 들 때는 대단한 대화보다 ‘지금 뭐 해?’ 한 문장이 더 도움이 되기도 해요.",
        "여기서는 제가 듣고 있어요. 오늘 특히 외롭게 느껴진 이유가 있었나요?",
    ),
    "tired": (
        "피로 경보가 울립니다. 화면에서 잠깐 떨어져 어깨와 눈을 쉬게 해 주세요.",
        "지금 필요한 건 더 빠른 진행이 아니라 회복일지도 모릅니다. 짧게라도 쉬었다 돌아오세요.",
        "오늘 할 일을 전부 끝내지 않아도 괜찮아요. 꼭 필요한 하나만 남기고 난이도를 낮춰 봅시다.",
    ),
    "sleep": (
        "졸리면 저장하고 종료할 시간입니다. 물 한 모금 마시고 화면 밝기를 낮춰 주세요.",
        "잠을 미루면 내일의 체력을 빌려 쓰는 셈이죠. 가능하면 지금 정리하고 쉬어요.",
        "좋은 밤이에요. 오늘 기록은 여기까지 해도 충분합니다.",
    ),
    "hungry": (
        "배고픈 생존자는 판단력이 떨어집니다. 실제 식사를 먼저 챙겨 주세요.",
        "게임 식량이 부족하다면 `!코인` → `!알바` → `!땅파기` 순서로 수입을 이어갈 수 있어요.",
        "무엇을 먹을지 고민 중이라면 따뜻한 것, 간단한 것, 든든한 것 중 지금 끌리는 쪽부터 골라 봐요.",
    ),
    "money": (
        "게임 재화가 부족하면 `!코인`, 소진 후 `!알바`, 마지막으로 `!땅파기`가 안정적인 순서입니다.",
        "큰 한 방보다 일일 수입 루트를 다 쓰는 편이 안전합니다. 카지노는 잃어도 괜찮은 칩만 사용하세요.",
        "현재 잔액은 관련 정보 명령에서 확인하고, 사채나 올인은 정말 마지막 선택으로 남겨 두는 게 좋아요.",
    ),
    "digging": (
        "`!땅파기`는 하루 50회, 1분 간격입니다. 이제 매 굴착마다 소량의 생존 자금도 함께 나옵니다.",
        "땅은 가끔 빈손을 주지만 잔돈은 조금씩 챙겨 줍니다. 운이 좋으면 미감정 보물도 나와요.",
        "삽질은 느리지만 확실한 수입 루트예요. 보물이 나오면 `!보물감정`으로 감정사를 고르세요.",
    ),
    "treasure": (
        "미감정 보물은 `!보물함`에서 확인하고 `!보물감정`으로 감정사를 선택합니다.",
        "보물 등급은 E부터 A까지입니다. 감정사마다 비용, 매입률, 등급 상승 확률이 달라요.",
        "보물함이 가득 차면 추가 보물이 나오지 않으니 먼저 감정해 두는 편이 좋습니다.",
    ),
    "appraiser": (
        "마르코는 무료, 세라는 균형형, 라울은 높은 매입가, 이리스는 가장 비싸지만 등급 상승 기대가 큽니다.",
        "안전하게 가려면 마르코, 기대값을 높이려면 자금 여유에 맞춰 세라·라울·이리스를 고르세요.",
        "감정과 동시에 매입되니 수집용으로 보관되는 건 이름과 등급 도감 기록입니다.",
    ),
    "game": (
        "`!게임`을 열면 191개 기능을 카테고리, 검색, 즐겨찾기와 최근 실행으로 찾을 수 있습니다.",
        "심심하다면 전투, 원정, 카지노, 스토리 중 하나를 골라 볼까요? 안전하게는 원정, 짜릿하게는 카지노예요.",
        "무엇을 할지 모르겠다면 오늘 남은 일일 콘텐츠부터 확인하는 게 효율적입니다.",
    ),
    "rules": (
        "현재 채널의 안내가 필요하면 관리자가 `!채널규칙`을 실행할 수 있습니다. 여러 채널은 `!채널규칙 일괄설치`로 처리합니다.",
        "규칙은 채널별로 다를 수 있습니다. 고정 메시지와 `#서버-안내`를 먼저 확인해 주세요.",
        "규칙이 애매한 채널은 자동 추천 후 미리보기로 확인하고 설치하는 편이 안전합니다.",
    ),
    "tts": (
        "TTS 채널에서는 음성방에 들어간 뒤 채팅만 입력하면 됩니다. 개인 목소리는 `/tts 목소리`에서 바꿔요.",
        "아바돈 TTS는 작성자의 현재 음성방을 자동 감지하며 닉네임 없이 채팅 내용만 읽습니다.",
        "Edge 음성이 실패하면 자동 모드에서 안정 음성이나 Google 경로로 우회합니다.",
    ),
    "story": (
        "스토리는 `!시즌3`에서 이어갈 수 있습니다. 이전 시즌의 선택 기록도 계승됩니다.",
        "검은 주파수와 백색 방주를 지나 종말의 왕좌가 열렸습니다. 어떤 엔딩을 향할지는 선택에 달렸어요.",
        "스토리는 서두르지 말고 기록을 읽으며 선택하는 편이 보상보다 더 재미있습니다.",
    ),
    "help": (
        "전체 기능은 `!명령어`, 게임은 `!게임`, 서버 상태는 `!아바돈진단`에서 확인할 수 있습니다.",
        "게임 기능은 `!게임` 검색을, 운영 기능은 `!설정`이나 `!아바돈진단`을 열어 보세요.",
        "무엇을 하려는지만 말해 주면 관련 명령을 찾아드릴게요.",
    ),
    "joke": (
        "폐허에서 가장 성실한 직업은 땅파기입니다. 실패해도 최소한 구덩이는 남거든요.",
        "아바돈이 삽질을 잘하는 이유요? 버그를 파고 또 파는 게 일상이라서요.",
        "카지노에서 가장 안전한 배팅은 구경입니다. 수익은 없지만 손실도 없죠.",
    ),
    "opinion": (
        "저라면 안정성을 먼저 고르겠습니다. 멋진 기능도 서버가 멈추면 장식품이니까요.",
        "정답이 하나인 문제는 아닌 것 같아요. 당신이 더 중요하게 보는 기준이 무엇인지가 핵심입니다.",
        "저는 기록을 기준으로 판단하지만, 취향이 걸린 문제라면 당신 쪽 선택이 더 정확할 거예요.",
    ),
    "farewell": (
        "통신 종료 확인. 무사히 다녀오세요. 다시 말 걸면 이어서 듣겠습니다.",
        "좋은 밤이에요. 오늘 기록은 안전하게 보관해 둘게요.",
        "다녀오세요. 검은 성역은 다음 신호를 기다리겠습니다.",
    ),
    "fallback": (
        "그 얘기, 조금 더 듣고 싶어요. 어떤 부분이 가장 마음에 걸렸나요?",
        "아직 제 기억에 선명한 답은 없지만 대화는 이어갈 수 있어요. 조금만 더 구체적으로 말해 줄래요?",
        "흥미로운 신호네요. 당신은 그걸 어떻게 생각하고 있어요?",
        "정확한 답을 찾지 못했습니다. 질문을 짧게 바꾸거나 `!지식검색 단어`로 서버 기억을 찾아볼 수도 있어요.",
    ),
}

DAILY_QUESTIONS: Tuple[str, ...] = (
    "오늘 서버에서 가장 먼저 도와주고 싶은 사람은 누구인가요?",
    "종말 이후에도 반드시 남겨야 할 문화 하나를 고른다면 무엇인가요?",
    "하루 동안 한 가지 능력을 빌릴 수 있다면 어떤 능력을 고르겠나요?",
    "최근 사소하지만 기분 좋았던 순간은 무엇이었나요?",
    "안전한 기지와 자유로운 여행 중 하나만 고른다면 어느 쪽인가요?",
    "게임 속에서 가장 믿음직한 동료 유형은 어떤 사람인가요?",
    "지금의 나에게 짧은 작전 명령을 내린다면 뭐라고 말하겠나요?",
    "한 달 뒤의 내가 고마워할 일을 오늘 하나 한다면 무엇인가요?",
    "폐허에서 단 하나의 간식을 발견한다면 무엇이길 바라나요?",
    "모두가 알아줬으면 하는 나만의 작은 취향은 무엇인가요?",
    "서버에 새 채널 하나를 만들 수 있다면 어떤 채널을 만들고 싶나요?",
    "다시 플레이해도 늘 고르는 게임 직업이나 역할이 있나요?",
    "오늘의 기분을 날씨로 표현하면 어떤 날씨인가요?",
    "위험한 원정에서 꼭 데려가고 싶은 물건 하나는 무엇인가요?",
    "최근 배운 것 중 의외로 유용했던 지식은 무엇인가요?",
    "완벽한 휴식일을 설계한다면 어떻게 보내고 싶나요?",
    "누군가에게 추천하고 싶은 노래·게임·영화 하나가 있나요?",
    "이번 주에 스스로에게 주고 싶은 작은 보상은 무엇인가요?",
    "협동 게임에서 지휘관과 자유 행동 중 어느 쪽이 더 편한가요?",
    "기억에서 지우고 다시 처음 경험하고 싶은 작품이 있나요?",
)

BALANCE_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("전력은 충분하지만 인터넷이 없는 안전 기지", "인터넷은 빠르지만 매일 정전되는 옥상 기지"),
    ("전투력은 강하지만 길을 자주 잃는 동료", "길은 완벽히 알지만 전투를 무서워하는 동료"),
    ("하루 한 번 원하는 음식 소환", "하루 한 번 원하는 장소로 순간이동"),
    ("모든 보물의 등급을 미리 알기", "모든 강화의 성공 여부를 미리 알기"),
    ("밤에만 강해지는 장비", "비가 올 때만 강해지는 장비"),
    ("평생 한 게임만 하기", "매주 새 게임을 하지만 저장이 초기화되기"),
    ("말은 못 하지만 완벽히 이해하는 펫", "말은 잘하지만 말을 전혀 안 듣는 펫"),
    ("식량이 넉넉한 지하 벙커", "풍경이 아름다운 이동식 캠프"),
    ("모든 퀘스트 보상 20% 증가", "모든 쿨타임 20% 감소"),
    ("과거 한 장면 다시 보기", "미래 한 장면 미리 보기"),
)

ABADDON_LINES: Tuple[str, ...] = (
    "검은 종이 울리지 않아도, 살아남은 사람의 하루는 기록됩니다.",
    "강한 생존자는 모든 전투를 이기는 사람이 아니라 회복할 때를 아는 사람입니다.",
    "작은 신호도 반복되면 길이 됩니다. 오늘의 한 걸음을 무시하지 마세요.",
    "폐허에는 정답보다 기록이 오래 남습니다. 실패도 다음 선택의 지도입니다.",
    "누군가의 안전지대가 되어 주는 일은 어떤 장비보다 높은 등급입니다.",
    "계획이 무너졌다면 목표를 버리지 말고 경로를 다시 그리세요.",
    "서두르지 않아도 됩니다. 서버도 사람도 안정화에는 시간이 필요합니다.",
    "오늘의 체력이 낮다면 난이도를 낮추는 것도 훌륭한 전략입니다.",
)

ENCOURAGEMENTS: Tuple[str, ...] = (
    "지금까지 버틴 기록만으로도 충분히 잘하고 있어요. 다음 한 칸만 천천히 갑시다.",
    "완벽하지 않아도 진행은 진행입니다. 오늘 할 수 있는 만큼이면 됩니다.",
    "실수가 생겼다는 건 실제로 움직였다는 뜻입니다. 고치고 이어가면 됩니다.",
    "잠깐 쉬는 건 포기가 아니라 회복 명령입니다. 체력을 먼저 채워 주세요.",
    "큰 목표는 작은 체크 표시들의 집합입니다. 지금 하나만 완료해 봅시다.",
)

BOND_LEVELS: Tuple[Tuple[int, str, str], ...] = (
    (150, "왕좌의 대화자", "아바돈의 심장부 기록에 이름이 새겨졌습니다."),
    (70, "심장부 통신원", "검은 성역이 당신의 신호를 우선 식별합니다."),
    (30, "검은 성역의 동행자", "여러 번의 대화가 안정된 통신로를 만들었습니다."),
    (10, "등록된 생존자", "당신의 목소리가 익숙한 신호로 분류됐습니다."),
    (0, "미확인 신호", "아직 대화 기록이 많지 않습니다."),
)


Action = Callable[[discord.Interaction], Awaitable[None]]
SubmitHandler = Callable[[discord.Interaction, str, str], Awaitable[None]]
OneTextHandler = Callable[[discord.Interaction, str], Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _kst_date() -> str:
    return _utc_now().astimezone(KST).strftime("%Y-%m-%d")


def _iso_now() -> str:
    return _utc_now().isoformat()


def _normalize(text: Any) -> str:
    value = str(text or "").casefold()
    value = re.sub(r"<@!?\d+>", " ", value)
    value = PUNCT_PATTERN.sub(" ", value)
    return SPACE_PATTERN.sub(" ", value).strip()


def _display_text(text: Any, limit: int = 100) -> str:
    value = SPACE_PATTERN.sub(" ", str(text or "")).strip()
    return value if len(value) <= limit else value[: max(1, limit - 1)] + "…"


def _contains_sensitive(text: str) -> Optional[str]:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return "토큰·비밀번호·초대 링크처럼 민감할 수 있는 문자열이 감지됐습니다."
    return None


def _sanitize_response(text: str) -> str:
    text = text.replace("\x00", "").strip()
    return text


def _ensure_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(DATA_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[DATA_KEY] = root
    return root


def _ensure_guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _ensure_root(world_data)
    key = str(guild_id)
    state = root.setdefault(key, {})
    if not isinstance(state, dict):
        state = {}
        root[key] = state
    defaults: Dict[str, Any] = {
        "settings": {
            "enabled": True,
            "mention_reply": True,
            "auto_exact": False,
            "approval_required": True,
            "response_cooldown": AUTO_REPLY_COOLDOWN,
        },
        "entries": {},
        "pending": {},
        "profiles": {},
        "daily_answers": {},
        "stats": {"conversations": 0, "learned_hits": 0, "builtin_hits": 0, "submissions": 0},
    }
    for name, value in defaults.items():
        if name not in state or not isinstance(state.get(name), type(value)):
            state[name] = value.copy() if isinstance(value, dict) else value
    settings = state["settings"]
    for name, value in defaults["settings"].items():
        settings.setdefault(name, value)
    stats = state["stats"]
    for name, value in defaults["stats"].items():
        stats.setdefault(name, value)
    return state


def _profile(state: MutableMapping[str, Any], user_id: int) -> MutableMapping[str, Any]:
    profiles = state.setdefault("profiles", {})
    key = str(user_id)
    profile = profiles.setdefault(key, {})
    if not isinstance(profile, dict):
        profile = {}
        profiles[key] = profile
    defaults = {
        "bond": 0,
        "bond_date": _kst_date(),
        "bond_today": 0,
        "conversation_count": 0,
        "submitted": [],
        "approved": [],
        "daily_answer_dates": [],
    }
    for name, value in defaults.items():
        if name not in profile:
            profile[name] = list(value) if isinstance(value, list) else value
    if profile.get("bond_date") != _kst_date():
        profile["bond_date"] = _kst_date()
        profile["bond_today"] = 0
    return profile


def _add_bond(state: MutableMapping[str, Any], user_id: int, amount: int, daily_cap: int = 10) -> int:
    profile = _profile(state, user_id)
    remaining = max(0, int(daily_cap) - int(profile.get("bond_today", 0)))
    applied = min(max(0, int(amount)), remaining)
    if applied:
        profile["bond"] = int(profile.get("bond", 0)) + applied
        profile["bond_today"] = int(profile.get("bond_today", 0)) + applied
    return applied


def _bond_level(points: int) -> Tuple[str, str, int]:
    for minimum, label, description in BOND_LEVELS:
        if points >= minimum:
            return label, description, minimum
    return BOND_LEVELS[-1][1], BOND_LEVELS[-1][2], 0


def _next_bond_threshold(points: int) -> Optional[int]:
    ascending = sorted(minimum for minimum, _, _ in BOND_LEVELS)
    for minimum in ascending:
        if minimum > points:
            return minimum
    return None


def _is_manager(member: Any) -> bool:
    permissions = getattr(member, "guild_permissions", None)
    return bool(
        permissions
        and (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "manage_guild", False)
            or getattr(permissions, "manage_messages", False)
        )
    )


def _approved_entries(state: Mapping[str, Any]) -> Iterable[MutableMapping[str, Any]]:
    entries = state.get("entries", {})
    if not isinstance(entries, dict):
        return ()
    return (entry for entry in entries.values() if isinstance(entry, dict) and entry.get("enabled", True))


def _find_entry(state: Mapping[str, Any], text: str, *, allow_contains: bool) -> Optional[MutableMapping[str, Any]]:
    norm = _normalize(text)
    if not norm:
        return None
    candidates = list(_approved_entries(state))
    exact = [entry for entry in candidates if str(entry.get("trigger_norm", "")) == norm]
    if exact:
        return max(exact, key=lambda item: int(item.get("uses", 0)))
    if not allow_contains:
        return None
    contained = [
        entry
        for entry in candidates
        if len(str(entry.get("trigger_norm", ""))) >= 4 and str(entry.get("trigger_norm", "")) in norm
    ]
    if not contained:
        return None
    return max(contained, key=lambda item: (len(str(item.get("trigger_norm", ""))), int(item.get("uses", 0))))


def _intent(text: str) -> str:
    norm = _normalize(text)
    if any(token in norm for token in ("잘 가", "바이", "다녀올게", "나 갈게", "잘자", "잘 자", "굿나잇")):
        return "farewell"
    if any(token in norm for token in ("안녕", "하이", "반가워", "좋은 아침", "좋은 밤", "ㅎㅇ")):
        return "greeting"
    if any(token in norm for token in ("잘 지내", "어떻게 지내", "기분 어때", "너는 어때", "상태 어때")):
        return "how_are_you"
    if any(token in norm for token in ("고마워", "감사", "땡큐", "고맙")):
        return "thanks"
    if any(token in norm for token in ("너 누구", "정체", "아바돈이 뭐", "누구야", "이름이 뭐")):
        return "identity"
    if any(token in norm for token in ("멋지", "잘한다", "최고", "똑똑", "좋은 봇", "귀엽")):
        return "praise"
    if any(token in norm for token in ("좋아해", "사랑해", "내 친구", "친구하자")):
        return "affection"
    if any(token in norm for token in ("미안", "죄송", "실수했")):
        return "apology"
    if any(token in norm for token in ("화나", "짜증", "빡쳐", "열받", "억울")):
        return "angry"
    if any(token in norm for token in ("불안", "걱정", "무서워", "긴장", "초조")):
        return "anxious"
    if any(token in norm for token in ("외로", "혼자인", "아무도 없")):
        return "lonely"
    if any(token in norm for token in ("힘들", "우울", "속상", "슬퍼", "괴로", "울고 싶")):
        return "sad"
    if any(token in norm for token in ("피곤", "지쳤", "쉬고 싶", "힘 빠져")):
        return "tired"
    if any(token in norm for token in ("졸려", "잠 와", "잠이 안", "자야", "잘까")):
        return "sleep"
    if any(token in norm for token in ("배고", "뭐 먹", "식사", "밥 뭐")):
        return "hungry"
    if any(token in norm for token in ("돈 없", "식량 부족", "재화 부족", "코인 다", "알바 다", "돈 벌")):
        return "money"
    if any(token in norm for token in ("땅파기", "굴착", "삽질", "땅 파")):
        return "digging"
    if any(token in norm for token in ("보물", "미감정", "등급")):
        return "treasure"
    if any(token in norm for token in ("감정사", "마르코", "세라", "라울", "이리스")):
        return "appraiser"
    if any(token in norm for token in ("게임", "심심", "뭐 하지", "뭐할까", "놀자")):
        return "game"
    if "규칙" in norm or "채널 안내" in norm:
        return "rules"
    if any(token in norm for token in ("tts", "목소리", "음성 낭독", "말해줘")):
        return "tts"
    if any(token in norm for token in ("스토리", "시즌3", "왕좌", "엔딩")):
        return "story"
    if any(token in norm for token in ("농담", "웃겨", "개그", "재밌는 말")):
        return "joke"
    if any(token in norm for token in ("어떻게 생각", "네 생각", "뭐가 좋아", "추천해", "골라줘")):
        return "opinion"
    if any(token in norm for token in ("도와", "명령어", "사용법", "어떻게 해", "어디서")):
        return "help"
    return "fallback"



def _intent_reactions(intent: str) -> Tuple[str, ...]:
    return {
        "greeting": ("👋", "🖤"),
        "how_are_you": ("🕯️", "💬"),
        "thanks": ("🖤", "✨"),
        "praise": ("✨", "🖤"),
        "affection": ("🖤", "🌙"),
        "apology": ("🤝", "🖤"),
        "sad": ("🫂", "🌙"),
        "angry": ("🌋", "🫂"),
        "anxious": ("🌙", "🫂"),
        "lonely": ("🕯️", "🫂"),
        "tired": ("☕", "🌙"),
        "sleep": ("🌙", "💤"),
        "hungry": ("🥫", "🍚"),
        "money": ("💰", "🧰"),
        "digging": ("⛏️", "💰"),
        "treasure": ("💎", "📦"),
        "appraiser": ("🔎", "💎"),
        "game": ("🎮", "🔥"),
        "rules": ("📜", "✅"),
        "tts": ("🎙️", "🔊"),
        "story": ("🌑", "📖"),
        "help": ("🧭", "📚"),
        "joke": ("😄", "🪨"),
        "opinion": ("🤔", "🕯️"),
        "farewell": ("👋", "🌙"),
        "identity": ("🕯️", "🖤"),
        "fallback": ("📡", "💬"),
    }.get(intent, ("📡",))


def _contextual_builtin_reply(text: str, intent: str, session: Optional[Mapping[str, Any]] = None) -> str:
    norm = _normalize(text)
    previous = str((session or {}).get("last_intent", ""))
    if norm in {"응", "응응", "그래", "좋아", "ㅇㅇ", "알겠어", "맞아"}:
        followups = {
            "sad": "좋아요. 그럼 지금 가장 부담이 작은 것부터 하나만 말해 볼까요?",
            "anxious": "좋아요. 지금 확실히 알고 있는 사실 하나부터 적어 봅시다.",
            "angry": "좋아요. 무슨 일이 있었는지 사실만 먼저 한 줄로 말해 주세요.",
            "game": "그럼 `!게임`을 열어 볼까요? 편안하게는 생활·원정, 짜릿하게는 전투·카지노를 추천해요.",
            "digging": "좋아요. `!땅파기` 한 번부터 시작해 보세요. 잔돈과 보물 운이 기다리고 있습니다.",
            "hungry": "좋아요. 일단 물 한 잔과 간단한 음식부터 챙겨요. 게임 식량은 그다음입니다.",
        }
        return followups.get(previous, "좋아요. 그럼 계속 말해 주세요. 지금 가장 먼저 떠오르는 건 뭐예요?")
    if norm in {"아니", "아냐", "싫어", "ㄴㄴ", "그건 아니야"}:
        return "알겠어요. 제가 방향을 잘못 잡았네요. 원하는 쪽을 한 문장으로 다시 말해 줄래요?"
    if norm in {"왜", "왜 그래", "왜 그렇게 생각해"}:
        reasons = {
            "opinion": "안정성과 되돌릴 수 있는 선택을 우선하는 편이 장기 운영에서 사고가 적기 때문이에요.",
            "tired": "피로할 때는 판단력과 집중력이 같이 떨어져서 작은 실수도 크게 느껴질 수 있기 때문이에요.",
            "money": "고정 수입을 먼저 챙기면 운에 기대는 콘텐츠에서 손실이 나도 회복하기 쉽기 때문입니다.",
            "game": "현재 기능이 많아서 목적을 먼저 정하면 고르는 시간이 훨씬 줄어들기 때문이에요.",
        }
        return reasons.get(previous, "제가 그렇게 답한 이유는 지금까지 말한 내용에서 가장 안전한 방향을 골랐기 때문이에요. 다른 기준을 원하면 바꿔 볼게요.")
    if norm in {"뭐해", "뭐 하고 있어", "뭐하냐"}:
        return "당신의 다음 말을 기다리면서 서버 기록을 정리하고 있었어요. 지금은 대화 모드입니다."
    if norm in {"진짜", "정말", "레알"}:
        return "네, 진심으로 그렇게 판단했어요. 다만 제가 놓친 상황이 있다면 말해 주세요."
    return random.choice(BUILTIN_RESPONSES[intent])



async def _safe_reactions(message: Optional[discord.Message], emojis: Iterable[str]) -> None:
    if message is None:
        return
    for emoji in emojis:
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return


async def _interaction_send(
    interaction: discord.Interaction,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = True,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, view=view, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)


class OwnerView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = MENU_TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await _interaction_send(interaction, content="⚠️ 이 제어실은 명령을 실행한 사용자만 조작할 수 있습니다.", ephemeral=True)
        return False


class DialogueMenuView(OwnerView):
    def __init__(self, owner_id: int, actions: Mapping[str, Action]) -> None:
        super().__init__(owner_id)
        self.actions = actions
        select = discord.ui.Select(
            placeholder="대화 기능을 선택하세요",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="아바돈에게 말 걸기", value="ask", emoji="🕯️", description="이 채널에서 자연스러운 연속 대화를 시작합니다."),
                discord.SelectOption(label="기억 가르치기", value="teach", emoji="📚", description="서버 전용 질문과 답변을 등록합니다."),
                discord.SelectOption(label="서버 지식 검색", value="search", emoji="🔎", description="승인된 기억을 키워드로 찾습니다."),
                discord.SelectOption(label="내 제출 기록", value="mine", emoji="🗂️", description="내가 등록한 기억의 승인 상태를 봅니다."),
                discord.SelectOption(label="오늘의 질문", value="daily", emoji="💬", description="모두가 답할 수 있는 하루 질문을 엽니다."),
                discord.SelectOption(label="생존 밸런스", value="balance", emoji="⚖️", description="두 선택지 중 하나를 골라 봅니다."),
                discord.SelectOption(label="교감 기록", value="bond", emoji="🖤", description="아바돈과의 대화 누적 기록을 확인합니다."),
            ],
        )

        async def callback(interaction: discord.Interaction) -> None:
            action = self.actions.get(select.values[0])
            if action is None:
                await _interaction_send(interaction, content="⚠️ 사용할 수 없는 기능입니다.", ephemeral=True)
                return
            await action(interaction)

        select.callback = callback
        self.add_item(select)


class TeachModal(discord.ui.Modal):
    def __init__(self, submit_handler: SubmitHandler) -> None:
        super().__init__(title="아바돈 기억 공방", timeout=300)
        self.submit_handler = submit_handler
        self.trigger = discord.ui.TextInput(
            label="아바돈을 부를 문장 또는 핵심어",
            placeholder="예: 구조 요청은 어디에 올려?",
            min_length=2,
            max_length=MAX_TRIGGER_LENGTH,
        )
        self.response_text = discord.ui.TextInput(
            label="아바돈이 답할 내용",
            placeholder="이 서버에서 사용할 정확하고 안전한 안내를 적어 주세요.",
            style=discord.TextStyle.paragraph,
            min_length=2,
            max_length=MAX_RESPONSE_LENGTH,
        )
        self.add_item(self.trigger)
        self.add_item(self.response_text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.submit_handler(interaction, str(self.trigger.value), str(self.response_text.value))


class OneTextModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        title: str,
        label: str,
        placeholder: str,
        max_length: int,
        submit_handler: OneTextHandler,
        paragraph: bool = False,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self.submit_handler = submit_handler
        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder,
            style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
            min_length=1,
            max_length=max_length,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.submit_handler(interaction, str(self.value_input.value))


class TeachLaunchView(OwnerView):
    def __init__(self, owner_id: int, modal_factory: Callable[[], discord.ui.Modal]) -> None:
        super().__init__(owner_id)
        button = discord.ui.Button(label="기억 등록 양식 열기", emoji="📚", style=discord.ButtonStyle.primary)

        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(modal_factory())

        button.callback = callback
        self.add_item(button)


class DailyQuestionView(discord.ui.View):
    def __init__(
        self,
        answer_modal_factory: Callable[[], discord.ui.Modal],
        status_action: Action,
    ) -> None:
        super().__init__(timeout=600)
        answer = discord.ui.Button(label="내 답변 남기기", emoji="✍️", style=discord.ButtonStyle.primary)
        status = discord.ui.Button(label="답변 현황", emoji="📊", style=discord.ButtonStyle.secondary)

        async def answer_callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(answer_modal_factory())

        async def status_callback(interaction: discord.Interaction) -> None:
            await status_action(interaction)

        answer.callback = answer_callback
        status.callback = status_callback
        self.add_item(answer)
        self.add_item(status)


class ReviewView(OwnerView):
    def __init__(
        self,
        owner_id: int,
        submissions: Sequence[Mapping[str, Any]],
        approve_action: Callable[[discord.Interaction, str], Awaitable[None]],
        reject_action: Callable[[discord.Interaction, str], Awaitable[None]],
    ) -> None:
        super().__init__(owner_id)
        self.selected_id: Optional[str] = None
        self.submissions = {str(item.get("id")): item for item in submissions}
        options = []
        for item in submissions[:25]:
            options.append(
                discord.SelectOption(
                    label=_display_text(item.get("trigger"), 80),
                    value=str(item.get("id")),
                    description=f"제출자 {item.get('author_name', item.get('author_id', '알 수 없음'))}",
                    emoji="🧠",
                )
            )
        select = discord.ui.Select(placeholder="검수할 기억을 선택하세요", options=options, min_values=1, max_values=1)

        async def select_callback(interaction: discord.Interaction) -> None:
            self.selected_id = select.values[0]
            item = self.submissions[self.selected_id]
            embed = discord.Embed(
                title="🧠 기억 검수 상세",
                description=f"**호출 문장**\n{item.get('trigger')}\n\n**응답**\n{item.get('response')}",
                color=0x6C3483,
            )
            embed.add_field(name="제출자", value=f"{item.get('author_name', '알 수 없음')} (`{item.get('author_id')}`)", inline=False)
            embed.set_footer(text=f"기억 ID {self.selected_id}")
            await interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_callback
        approve = discord.ui.Button(label="승인", emoji="✅", style=discord.ButtonStyle.success)
        reject = discord.ui.Button(label="반려", emoji="🗑️", style=discord.ButtonStyle.danger)

        async def approve_callback(interaction: discord.Interaction) -> None:
            if not self.selected_id:
                await _interaction_send(interaction, content="⚠️ 먼저 검수할 기억을 선택하세요.", ephemeral=True)
                return
            await approve_action(interaction, self.selected_id)

        async def reject_callback(interaction: discord.Interaction) -> None:
            if not self.selected_id:
                await _interaction_send(interaction, content="⚠️ 먼저 검수할 기억을 선택하세요.", ephemeral=True)
                return
            await reject_action(interaction, self.selected_id)

        approve.callback = approve_callback
        reject.callback = reject_callback
        self.add_item(select)
        self.add_item(approve)
        self.add_item(reject)


def register_v620_dialogue_memory(
    bot: commands.Bot,
    world_data: MutableMapping[str, Any],
    save_data: Callable[[], None],
) -> None:
    channel_cooldowns: Dict[Tuple[int, int], float] = {}
    conversation_sessions: Dict[Tuple[int, int, int], Dict[str, Any]] = {}

    def conversation_key(guild_id: int, channel_id: int, user_id: int) -> Tuple[int, int, int]:
        return int(guild_id), int(channel_id), int(user_id)

    def start_conversation(guild: discord.Guild, channel: discord.abc.Messageable, user: discord.abc.User) -> Dict[str, Any]:
        key = conversation_key(guild.id, int(getattr(channel, "id", 0)), user.id)
        now = time.monotonic()
        session = conversation_sessions.get(key)
        if not isinstance(session, dict):
            session = {"turns": 0, "history": [], "last_intent": "", "last_user_text": "", "last_bot_text": ""}
            conversation_sessions[key] = session
        session["expires_at"] = now + CONVERSATION_TIMEOUT_SECONDS
        session["last_message_at"] = 0.0
        return session

    def active_conversation(guild_id: int, channel_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        key = conversation_key(guild_id, channel_id, user_id)
        session = conversation_sessions.get(key)
        if not isinstance(session, dict):
            return None
        if time.monotonic() >= float(session.get("expires_at", 0.0)):
            conversation_sessions.pop(key, None)
            return None
        return session

    def stop_conversation(guild_id: int, channel_id: int, user_id: int) -> bool:
        return conversation_sessions.pop(conversation_key(guild_id, channel_id, user_id), None) is not None

    def guild_state(guild: discord.Guild) -> MutableMapping[str, Any]:
        return _ensure_guild_state(world_data, guild.id)

    def teach_embed() -> discord.Embed:
        embed = discord.Embed(
            title="📚 아바돈 기억 공방",
            description=(
                "이 서버만의 질문과 답변을 아바돈에게 가르칠 수 있습니다.\n"
                "운영진이 등록하면 즉시 사용되고, 일반 사용자의 등록은 검수 대기열로 이동합니다."
            ),
            color=0x512E5F,
        )
        embed.add_field(
            name="등록 원칙",
            value=(
                "• 실제 서버 규칙·명령·채널 안내처럼 확인 가능한 내용만 작성\n"
                "• 개인정보, 비밀번호, 토큰, 초대 링크와 타인 비방 금지\n"
                "• 외부 봇의 문구나 캐릭터 설정을 복사하지 않고 이 서버만의 표현 사용"
            ),
            inline=False,
        )
        embed.set_footer(text="승인된 기억은 !아바돈, 멘션 대화와 선택형 자동 응답에 사용됩니다.")
        return embed

    async def submit_knowledge(interaction: discord.Interaction, trigger: str, response_text: str) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 지식을 등록할 수 있습니다.", ephemeral=True)
            return
        trigger = _display_text(trigger, MAX_TRIGGER_LENGTH)
        response_text = _sanitize_response(response_text)
        trigger_norm = _normalize(trigger)
        if len(trigger_norm) < 2 or len(response_text) < 2:
            await _interaction_send(interaction, content="⚠️ 호출 문장과 답변을 조금 더 구체적으로 적어 주세요.", ephemeral=True)
            return
        sensitive = _contains_sensitive(f"{trigger}\n{response_text}")
        if sensitive:
            await _interaction_send(interaction, content=f"⚠️ {sensitive}", ephemeral=True)
            return
        if MENTION_PATTERN.search(response_text):
            await _interaction_send(interaction, content="⚠️ 학습 답변에는 멘션을 넣을 수 없습니다. 이름이나 채널명을 일반 텍스트로 적어 주세요.", ephemeral=True)
            return
        state = guild_state(interaction.guild)
        entries = state["entries"]
        pending = state["pending"]
        if any(str(item.get("trigger_norm", "")) == trigger_norm for item in entries.values() if isinstance(item, dict)):
            await _interaction_send(interaction, content="⚠️ 같은 호출 문장이 이미 승인된 기억에 있습니다. `!지식검색`으로 확인해 주세요.", ephemeral=True)
            return
        user_pending = [
            item for item in pending.values()
            if isinstance(item, dict) and int(item.get("author_id", 0)) == interaction.user.id
        ]
        if len(user_pending) >= MAX_PENDING_PER_USER and not _is_manager(interaction.user):
            await _interaction_send(interaction, content=f"⚠️ 검수 대기 중인 기억은 사용자당 최대 {MAX_PENDING_PER_USER}개입니다.", ephemeral=True)
            return
        if len(entries) >= MAX_APPROVED_ENTRIES:
            await _interaction_send(interaction, content="⚠️ 서버 기억 보관함이 가득 찼습니다. 운영진이 오래된 항목을 정리해야 합니다.", ephemeral=True)
            return
        entry_id = f"MEM-{secrets.token_hex(4).upper()}"
        item: Dict[str, Any] = {
            "id": entry_id,
            "trigger": trigger,
            "trigger_norm": trigger_norm,
            "response": response_text[:MAX_RESPONSE_LENGTH],
            "author_id": interaction.user.id,
            "author_name": str(interaction.user),
            "created_at": _iso_now(),
            "enabled": True,
            "uses": 0,
            "last_used_at": "",
        }
        state["stats"]["submissions"] = int(state["stats"].get("submissions", 0)) + 1
        profile = _profile(state, interaction.user.id)
        profile["submitted"].append(entry_id)
        profile["submitted"] = profile["submitted"][-50:]
        if _is_manager(interaction.user) or not bool(state["settings"].get("approval_required", True)):
            item["approved_by"] = interaction.user.id
            item["approved_at"] = _iso_now()
            entries[entry_id] = item
            profile["approved"].append(entry_id)
            _add_bond(state, interaction.user.id, 3)
            save_data()
            await _interaction_send(
                interaction,
                content=f"✅ 기억 **{entry_id}** 등록 완료. 이제 `!아바돈 {trigger}`처럼 물으면 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        pending[entry_id] = item
        save_data()
        await _interaction_send(
            interaction,
            content=f"🕯️ 기억 **{entry_id}**을 검수 대기열에 보냈습니다. 운영진 승인 후 사용됩니다.",
            ephemeral=True,
        )

    async def build_reply(
        guild: discord.Guild,
        user: discord.abc.User,
        text: str,
        *,
        allow_contains: bool = True,
        session: Optional[MutableMapping[str, Any]] = None,
    ) -> Tuple[str, Tuple[str, ...], str]:
        state = guild_state(guild)
        state["stats"]["conversations"] = int(state["stats"].get("conversations", 0)) + 1
        profile = _profile(state, user.id)
        profile["conversation_count"] = int(profile.get("conversation_count", 0)) + 1
        _add_bond(state, user.id, 1)
        entry = _find_entry(state, text, allow_contains=allow_contains)
        if entry is not None:
            entry["uses"] = int(entry.get("uses", 0)) + 1
            entry["last_used_at"] = _iso_now()
            state["stats"]["learned_hits"] = int(state["stats"].get("learned_hits", 0)) + 1
            save_data()
            return str(entry.get("response", "")), ("🧠", "📚", "✨"), "learned"
        # v15.0 optional context engine: keeps the current conversation topic,
        # supports Korean/English separately and avoids resetting on short follow-ups.
        enhancer = getattr(bot, "_abaddon_v1500_conversation_reply", None)
        if callable(enhancer):
            try:
                enhanced = enhancer(state, user, text, session)
                if enhanced and isinstance(enhanced, tuple) and len(enhanced) == 3:
                    state["stats"]["builtin_hits"] = int(state["stats"].get("builtin_hits", 0)) + 1
                    save_data()
                    return enhanced
            except Exception as exc:
                print(f"[ABADDON v15.0 CONVERSATION FALLBACK] {type(exc).__name__}: {exc}", flush=True)
        intent = _intent(text)
        state["stats"]["builtin_hits"] = int(state["stats"].get("builtin_hits", 0)) + 1
        save_data()
        return _contextual_builtin_reply(text, intent, session), _intent_reactions(intent), intent

    async def send_public_reply(
        channel: discord.abc.Messageable,
        guild: discord.Guild,
        user: discord.abc.User,
        text: str,
        *,
        reply_to: Optional[discord.Message] = None,
        allow_contains: bool = True,
        session: Optional[MutableMapping[str, Any]] = None,
    ) -> discord.Message:
        answer, reactions, source = await build_reply(guild, user, text, allow_contains=allow_contains, session=session)
        embed = discord.Embed(description=answer, color=0x4A235A if source == "learned" else 0x17202A)
        embed.set_author(name=("ABADDON · Context Link" if str(source).endswith("_en") else "ABADDON · 기억 통신"), icon_url=getattr(getattr(bot, "user", None), "display_avatar", None).url if getattr(getattr(bot, "user", None), "display_avatar", None) else None)
        if source == "learned":
            footer = "서버 승인 기억"
        elif str(source).endswith("_en"):
            footer = "ABADDON contextual conversation · English"
        elif str(source).startswith("v1500"):
            footer = "ABADDON 문맥형 연속 대화 · 한국어"
        else:
            footer = "ABADDON 기본 대화 코어"
        embed.set_footer(text=footer)
        allowed = discord.AllowedMentions.none()
        if reply_to is not None:
            message = await reply_to.reply(embed=embed, mention_author=False, allowed_mentions=allowed)
        else:
            message = await channel.send(embed=embed, allowed_mentions=allowed)
        await _safe_reactions(message, reactions)
        if session is not None:
            session["turns"] = int(session.get("turns", 0)) + 1
            session["last_intent"] = source
            session["last_user_text"] = _display_text(text, 300)
            session["last_bot_text"] = _display_text(answer, 300)
            history = session.setdefault("history", [])
            history.append({"user": session["last_user_text"], "bot": session["last_bot_text"], "intent": source})
            session["history"] = history[-CONVERSATION_HISTORY_LIMIT:]
            session["expires_at"] = time.monotonic() + CONVERSATION_TIMEOUT_SECONDS
            session["last_bot_message_id"] = int(getattr(message, "id", 0))
        return message

    async def ask_modal_submit(interaction: discord.Interaction, text: str) -> None:
        if interaction.guild is None:
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 대화할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_public_reply(interaction.channel, interaction.guild, interaction.user, text)
        await interaction.followup.send("✅ 아바돈이 응답했습니다.", ephemeral=True)

    async def search_modal_submit(interaction: discord.Interaction, text: str) -> None:
        if interaction.guild is None:
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 검색할 수 있습니다.", ephemeral=True)
            return
        state = guild_state(interaction.guild)
        query = _normalize(text)
        matches = [
            item for item in _approved_entries(state)
            if query in str(item.get("trigger_norm", "")) or query in _normalize(item.get("response", ""))
        ]
        matches.sort(key=lambda item: (-int(item.get("uses", 0)), str(item.get("trigger", ""))))
        if not matches:
            await _interaction_send(interaction, content="🔎 일치하는 승인 기억이 없습니다.", ephemeral=True)
            return
        lines = [f"`{item.get('id')}` **{_display_text(item.get('trigger'), 70)}**\n↳ {_display_text(item.get('response'), 140)}" for item in matches[:10]]
        embed = discord.Embed(title=f"🔎 서버 기억 검색 · {len(matches)}개", description="\n\n".join(lines), color=0x5B2C6F)
        await _interaction_send(interaction, embed=embed, ephemeral=True)

    async def my_submissions(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 확인할 수 있습니다.", ephemeral=True)
            return
        state = guild_state(interaction.guild)
        approved = [item for item in state["entries"].values() if isinstance(item, dict) and int(item.get("author_id", 0)) == interaction.user.id]
        pending = [item for item in state["pending"].values() if isinstance(item, dict) and int(item.get("author_id", 0)) == interaction.user.id]
        lines = []
        for item in approved[-10:]:
            lines.append(f"✅ `{item.get('id')}` {_display_text(item.get('trigger'), 70)}")
        for item in pending[-10:]:
            lines.append(f"⏳ `{item.get('id')}` {_display_text(item.get('trigger'), 70)}")
        embed = discord.Embed(
            title="🗂️ 내 기억 제출 기록",
            description="\n".join(lines) if lines else "아직 제출한 기억이 없습니다.",
            color=0x34495E,
        )
        embed.set_footer(text=f"승인 {len(approved)}개 · 대기 {len(pending)}개")
        await _interaction_send(interaction, embed=embed, ephemeral=True)

    def daily_question_for(guild_id: int) -> str:
        seed = f"{_kst_date()}:{guild_id}:ABADDON"
        index = sum(ord(char) for char in seed) % len(DAILY_QUESTIONS)
        return DAILY_QUESTIONS[index]

    async def submit_daily_answer(interaction: discord.Interaction, answer: str) -> None:
        if interaction.guild is None:
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 답변할 수 있습니다.", ephemeral=True)
            return
        answer = _sanitize_response(answer)
        if _contains_sensitive(answer) or MENTION_PATTERN.search(answer):
            await _interaction_send(interaction, content="⚠️ 개인정보·초대 링크·멘션이 포함된 답변은 등록할 수 없습니다.", ephemeral=True)
            return
        state = guild_state(interaction.guild)
        date = _kst_date()
        answers = state["daily_answers"].setdefault(date, {})
        answers[str(interaction.user.id)] = {
            "answer": answer[:300],
            "author_name": str(interaction.user),
            "at": _iso_now(),
        }
        # 14일보다 오래된 답변 묶음 정리
        for old_date in sorted(state["daily_answers"])[:-14]:
            state["daily_answers"].pop(old_date, None)
        profile = _profile(state, interaction.user.id)
        if date not in profile["daily_answer_dates"]:
            profile["daily_answer_dates"].append(date)
            profile["daily_answer_dates"] = profile["daily_answer_dates"][-30:]
            _add_bond(state, interaction.user.id, 2)
        save_data()
        embed = discord.Embed(
            title="💬 오늘의 질문 답변",
            description=answer[:300],
            color=0x1ABC9C,
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message("✅ 답변을 기록했습니다.", ephemeral=True)
        public = await interaction.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await _safe_reactions(public, ("💬", "🖤", "✨"))

    async def daily_status(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 확인할 수 있습니다.", ephemeral=True)
            return
        state = guild_state(interaction.guild)
        answers = state["daily_answers"].get(_kst_date(), {})
        snippets = [f"• **{item.get('author_name', '익명')}**: {_display_text(item.get('answer'), 90)}" for item in list(answers.values())[-10:] if isinstance(item, dict)]
        embed = discord.Embed(
            title=f"📊 오늘의 답변 {len(answers)}개",
            description="\n".join(snippets) if snippets else "아직 등록된 답변이 없습니다.",
            color=0x117864,
        )
        await _interaction_send(interaction, embed=embed, ephemeral=True)

    async def post_daily_question(channel: discord.abc.Messageable, guild: discord.Guild, owner_id: int) -> discord.Message:
        question = daily_question_for(guild.id)
        embed = discord.Embed(title="💬 검은 성역의 오늘 질문", description=question, color=0x148F77)
        embed.add_field(name="참여 방법", value="아래 버튼으로 답변을 남기거나 자유롭게 대화를 이어가세요.", inline=False)
        embed.set_footer(text=f"{_kst_date()} · 답변은 서버 기록에 14일 동안 보관됩니다.")
        view = DailyQuestionView(
            lambda: OneTextModal(
                title="오늘의 질문에 답하기",
                label="내 답변",
                placeholder="서로 존중할 수 있는 내용으로 300자 이내 작성해 주세요.",
                max_length=300,
                submit_handler=submit_daily_answer,
                paragraph=True,
            ),
            daily_status,
        )
        message = await channel.send(embed=embed, view=view)
        await _safe_reactions(message, ("💬", "🧭", "🌙", "🔥"))
        return message

    async def post_balance(channel: discord.abc.Messageable) -> discord.Message:
        a, b = random.choice(BALANCE_CHOICES)
        embed = discord.Embed(title="⚖️ 생존 밸런스", color=0xB9770E)
        embed.add_field(name="🅰️ 선택 A", value=a, inline=False)
        embed.add_field(name="🅱️ 선택 B", value=b, inline=False)
        embed.set_footer(text="반응으로 선택하고 이유를 채팅으로 남겨 보세요.")
        message = await channel.send(embed=embed)
        await _safe_reactions(message, ("🅰️", "🅱️", "🤔", "🔥"))
        return message

    async def show_bond(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await _interaction_send(interaction, content="⚠️ 서버 안에서만 확인할 수 있습니다.", ephemeral=True)
            return
        state = guild_state(interaction.guild)
        profile = _profile(state, interaction.user.id)
        points = int(profile.get("bond", 0))
        label, description, _ = _bond_level(points)
        next_threshold = _next_bond_threshold(points)
        progress = "최고 단계" if next_threshold is None else f"다음 단계까지 {next_threshold - points}점"
        embed = discord.Embed(title=f"🖤 교감 기록 · {label}", description=description, color=0x7D3C98)
        embed.add_field(name="교감도", value=f"**{points}점** · {progress}", inline=False)
        embed.add_field(name="대화", value=f"{int(profile.get('conversation_count', 0))}회", inline=True)
        embed.add_field(name="오늘 획득", value=f"{int(profile.get('bond_today', 0))}/10", inline=True)
        embed.set_footer(text="대화, 승인된 기억 등록과 오늘의 질문 참여로 하루 최대 10점까지 오릅니다.")
        await _interaction_send(interaction, embed=embed, ephemeral=True)

    async def open_menu(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 안에서만 사용할 수 있습니다.")
            return

        async def ask_action(interaction: discord.Interaction) -> None:
            if interaction.guild is None or interaction.channel is None:
                await _interaction_send(interaction, content="⚠️ 서버 채널에서만 대화를 시작할 수 있습니다.", ephemeral=True)
                return
            start_conversation(interaction.guild, interaction.channel, interaction.user)
            await interaction.response.defer(ephemeral=True)
            public = await interaction.channel.send(
                f"🕯️ {interaction.user.mention} **대화 연결 완료**\n"
                "이제 이 채널에서 평소처럼 말하면 아바돈이 이어서 답합니다. "
                f"{CONVERSATION_TIMEOUT_SECONDS // 60}분 동안 유지되며 `!대화종료`로 끝낼 수 있어요.",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            await _safe_reactions(public, ("🕯️", "💬", "🖤"))
            await interaction.followup.send("✅ 연속 대화를 시작했습니다. 모달 없이 바로 채팅해 주세요.", ephemeral=True)

        async def teach_action(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(TeachModal(submit_knowledge))

        async def search_action(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(
                OneTextModal(
                    title="서버 기억 검색",
                    label="검색어",
                    placeholder="채널명, 명령어 또는 질문의 핵심어",
                    max_length=80,
                    submit_handler=search_modal_submit,
                )
            )

        async def daily_action(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            await post_daily_question(interaction.channel, interaction.guild, interaction.user.id)
            await interaction.followup.send("✅ 오늘의 질문을 채널에 열었습니다.", ephemeral=True)

        async def balance_action(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            await post_balance(interaction.channel)
            await interaction.followup.send("✅ 생존 밸런스를 채널에 열었습니다.", ephemeral=True)

        actions: Mapping[str, Action] = {
            "ask": ask_action,
            "teach": teach_action,
            "search": search_action,
            "mine": my_submissions,
            "daily": daily_action,
            "balance": balance_action,
            "bond": show_bond,
        }
        state = guild_state(ctx.guild)
        embed = discord.Embed(
            title="🕯️ ABADDON 대화·기억 제어실",
            description=(
                "아바돈과 대화하거나 서버 전용 지식을 가르치고, 오늘의 질문과 밸런스 토론을 열 수 있습니다.\n"
                "기억 등록 문구와 화면 구성은 ABADDON 프로젝트에서 새로 작성한 독립 기능입니다."
            ),
            color=0x4A235A,
        )
        embed.add_field(name="승인 기억", value=f"{len(state['entries'])}/{MAX_APPROVED_ENTRIES}", inline=True)
        embed.add_field(name="검수 대기", value=str(len(state["pending"])), inline=True)
        embed.add_field(name="자동 정확일치", value="켜짐" if state["settings"].get("auto_exact") else "꺼짐", inline=True)
        await ctx.send(embed=embed, view=DialogueMenuView(ctx.author.id, actions))

    @bot.command(name="대화", aliases=["대화센터", "아바돈대화", "chatcenter", "conversationcenter"], help="아바돈 대화·기억 드롭다운 제어실을 엽니다.")
    async def dialogue_center(ctx: commands.Context) -> None:
        await open_menu(ctx)

    @bot.command(name="아바돈", aliases=["말걸기", "chat", "talktoabaddon"], help="모달 없이 아바돈과 연속 대화를 시작하거나 바로 질문합니다.")
    async def talk_to_abaddon(ctx: commands.Context, *, 내용: str = "") -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 안에서만 사용할 수 있습니다.")
            return
        session = start_conversation(ctx.guild, ctx.channel, ctx.author)
        content = 내용.strip()
        if not content:
            message = await ctx.send(
                f"🕯️ {ctx.author.mention} **대화 연결 완료**\n"
                "이제 명령어 없이 평소처럼 말하면 제가 이어서 답합니다. "
                f"{CONVERSATION_TIMEOUT_SECONDS // 60}분 동안 유지 · 최대 {CONVERSATION_MAX_TURNS}회 · 종료는 `!대화종료`",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            await _safe_reactions(message, ("🕯️", "💬", "🖤"))
            return
        await send_public_reply(ctx.channel, ctx.guild, ctx.author, content, reply_to=ctx.message, session=session)

    @bot.command(name="대화종료", aliases=["말걸기종료", "대화끝", "endchat", "stopconversation"], help="현재 채널에서 진행 중인 아바돈 연속 대화를 종료합니다.")
    async def end_conversation(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        stopped = stop_conversation(ctx.guild.id, ctx.channel.id, ctx.author.id)
        await ctx.send("🌙 대화 연결을 종료했습니다. 다시 시작하려면 `!말걸기`를 입력하세요." if stopped else "📡 현재 이 채널에서 진행 중인 개인 대화가 없습니다.")

    @bot.command(name="가르치기", aliases=["기억등록", "지식등록"], help="서버 전용 질문과 답변 등록 양식을 엽니다.")
    async def teach(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 안에서만 사용할 수 있습니다.")
            return
        await ctx.send(embed=teach_embed(), view=TeachLaunchView(ctx.author.id, lambda: TeachModal(submit_knowledge)))

    @bot.group(name="지식", aliases=["기억"], invoke_without_command=True, help="서버 승인 기억과 검수 상태를 관리합니다.")
    async def knowledge(ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 안에서만 사용할 수 있습니다.")
            return
        state = guild_state(ctx.guild)
        embed = discord.Embed(title="🧠 서버 기억 보관함", color=0x5B2C6F)
        embed.add_field(name="승인", value=f"{len(state['entries'])}/{MAX_APPROVED_ENTRIES}", inline=True)
        embed.add_field(name="검수 대기", value=str(len(state["pending"])), inline=True)
        embed.add_field(name="자동 정확일치", value="켜짐" if state["settings"].get("auto_exact") else "꺼짐", inline=True)
        embed.add_field(
            name="명령",
            value=(
                "`!가르치기` · `!지식 목록` · `!지식 검색 단어`\n"
                "관리자: `!지식 검수` · `!지식 삭제 ID` · `!지식 자동반응 ON/OFF`"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @knowledge.command(name="목록")
    async def knowledge_list(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = guild_state(ctx.guild)
        items = sorted(_approved_entries(state), key=lambda item: str(item.get("created_at", "")), reverse=True)
        if not items:
            await ctx.send("📭 아직 승인된 서버 기억이 없습니다. `!가르치기`로 첫 기억을 등록해 보세요.")
            return
        lines = [f"`{item.get('id')}` **{_display_text(item.get('trigger'), 65)}** · 사용 {int(item.get('uses', 0))}회" for item in items[:25]]
        embed = discord.Embed(title=f"🧠 승인 기억 {len(items)}개", description="\n".join(lines), color=0x6C3483)
        if len(items) > 25:
            embed.set_footer(text="최근 25개만 표시합니다. !지식 검색 단어로 찾아보세요.")
        await ctx.send(embed=embed)

    @knowledge.command(name="검색")
    async def knowledge_search(ctx: commands.Context, *, 검색어: str = "") -> None:
        if ctx.guild is None:
            return
        query = _normalize(검색어)
        if not query:
            await ctx.send("사용법: `!지식 검색 검색어`")
            return
        state = guild_state(ctx.guild)
        matches = [
            item for item in _approved_entries(state)
            if query in str(item.get("trigger_norm", "")) or query in _normalize(item.get("response", ""))
        ]
        if not matches:
            await ctx.send("🔎 일치하는 승인 기억이 없습니다.")
            return
        matches.sort(key=lambda item: -int(item.get("uses", 0)))
        lines = [f"`{item.get('id')}` **{_display_text(item.get('trigger'), 65)}**\n↳ {_display_text(item.get('response'), 150)}" for item in matches[:10]]
        await ctx.send(embed=discord.Embed(title=f"🔎 기억 검색 · {len(matches)}개", description="\n\n".join(lines), color=0x5B2C6F))

    @bot.command(name="지식검색", help="승인된 서버 기억을 검색합니다.")
    async def knowledge_search_short(ctx: commands.Context, *, 검색어: str = "") -> None:
        await knowledge_search.callback(ctx, 검색어=검색어)

    @knowledge.command(name="검수")
    @commands.has_permissions(manage_messages=True)
    async def knowledge_review(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = guild_state(ctx.guild)
        submissions = sorted(
            [item for item in state["pending"].values() if isinstance(item, dict)],
            key=lambda item: str(item.get("created_at", "")),
        )
        if not submissions:
            await ctx.send("✅ 검수 대기 중인 기억이 없습니다.")
            return

        async def approve(interaction: discord.Interaction, entry_id: str) -> None:
            item = state["pending"].pop(entry_id, None)
            if not isinstance(item, dict):
                await _interaction_send(interaction, content="⚠️ 이미 처리된 기억입니다.", ephemeral=True)
                return
            if len(state["entries"]) >= MAX_APPROVED_ENTRIES:
                state["pending"][entry_id] = item
                await _interaction_send(interaction, content="⚠️ 승인 기억 보관함이 가득 찼습니다.", ephemeral=True)
                return
            item["approved_by"] = interaction.user.id
            item["approved_at"] = _iso_now()
            state["entries"][entry_id] = item
            author_profile = _profile(state, int(item.get("author_id", 0)))
            author_profile["approved"].append(entry_id)
            author_profile["approved"] = author_profile["approved"][-50:]
            _add_bond(state, int(item.get("author_id", 0)), 3)
            save_data()
            await interaction.response.edit_message(
                embed=discord.Embed(title="✅ 기억 승인 완료", description=f"`{entry_id}` **{item.get('trigger')}**", color=0x239B56),
                view=None,
            )

        async def reject(interaction: discord.Interaction, entry_id: str) -> None:
            item = state["pending"].pop(entry_id, None)
            if not isinstance(item, dict):
                await _interaction_send(interaction, content="⚠️ 이미 처리된 기억입니다.", ephemeral=True)
                return
            save_data()
            await interaction.response.edit_message(
                embed=discord.Embed(title="🗑️ 기억 반려 완료", description=f"`{entry_id}` **{item.get('trigger')}**", color=0x922B21),
                view=None,
            )

        embed = discord.Embed(
            title=f"🧠 기억 검수 대기 {len(submissions)}개",
            description="아래에서 항목을 선택하면 원문을 확인하고 승인 또는 반려할 수 있습니다.",
            color=0x6C3483,
        )
        if len(submissions) > 25:
            embed.set_footer(text="오래된 25개만 표시합니다. 처리 후 다시 열면 다음 항목이 나옵니다.")
        await ctx.send(embed=embed, view=ReviewView(ctx.author.id, submissions, approve, reject))

    @bot.command(name="지식검수", help="운영진이 대기 중인 기억을 드롭다운으로 검수합니다.")
    @commands.has_permissions(manage_messages=True)
    async def knowledge_review_short(ctx: commands.Context) -> None:
        await knowledge_review.callback(ctx)

    @knowledge.command(name="삭제")
    @commands.has_permissions(manage_messages=True)
    async def knowledge_delete(ctx: commands.Context, 기억id: str) -> None:
        if ctx.guild is None:
            return
        state = guild_state(ctx.guild)
        entry = state["entries"].pop(str(기억id).upper(), None)
        pending = state["pending"].pop(str(기억id).upper(), None)
        if entry is None and pending is None:
            await ctx.send("⚠️ 해당 기억 ID를 찾지 못했습니다.")
            return
        save_data()
        await ctx.send(f"🗑️ 기억 `{str(기억id).upper()}`을 삭제했습니다.")

    @knowledge.command(name="자동반응")
    @commands.has_permissions(manage_guild=True)
    async def knowledge_auto(ctx: commands.Context, 상태: str) -> None:
        if ctx.guild is None:
            return
        value = 상태.casefold() in {"켜기", "on", "true", "1", "활성"}
        if 상태.casefold() not in {"켜기", "끄기", "on", "off", "true", "false", "1", "0", "활성", "비활성"}:
            await ctx.send("사용법: `!지식 자동반응 ON` 또는 `!지식 자동반응 OFF`")
            return
        state = guild_state(ctx.guild)
        state["settings"]["auto_exact"] = value
        save_data()
        await ctx.send(
            "✅ 일반 채팅의 승인 기억 **정확히 일치하는 문장**에도 자동 응답합니다."
            if value else "✅ 일반 채팅 자동 응답을 껐습니다. `!아바돈`과 멘션 대화는 계속 사용할 수 있습니다."
        )

    @bot.command(name="오늘의질문", aliases=["하루질문"], help="서버 구성원이 답할 수 있는 오늘의 대화 질문을 엽니다.")
    async def daily_question(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        await post_daily_question(ctx.channel, ctx.guild, ctx.author.id)

    @bot.command(name="밸런스게임", aliases=["생존밸런스"], help="두 가지 생존 선택지를 반응으로 투표합니다.")
    async def balance_game(ctx: commands.Context) -> None:
        await post_balance(ctx.channel)

    @bot.command(name="교감", aliases=["교감도"], help="아바돈과의 대화 누적 기록을 확인합니다.")
    async def bond(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        state = guild_state(ctx.guild)
        profile = _profile(state, ctx.author.id)
        points = int(profile.get("bond", 0))
        label, description, _ = _bond_level(points)
        next_threshold = _next_bond_threshold(points)
        next_text = "최고 단계" if next_threshold is None else f"다음 단계까지 {next_threshold - points}점"
        embed = discord.Embed(title=f"🖤 {ctx.author.display_name} · {label}", description=description, color=0x7D3C98)
        embed.add_field(name="교감도", value=f"{points}점 · {next_text}", inline=False)
        embed.add_field(name="누적 대화", value=f"{int(profile.get('conversation_count', 0))}회", inline=True)
        embed.add_field(name="오늘 획득", value=f"{int(profile.get('bond_today', 0))}/10", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="한마디", aliases=["아바돈한마디"], help="ABADDON 세계관의 짧은 원문 한마디를 표시합니다.")
    async def one_line(ctx: commands.Context) -> None:
        message = await ctx.send(f"🕯️ **{random.choice(ABADDON_LINES)}**")
        await _safe_reactions(message, ("🕯️", "🖤", "✨"))

    @bot.command(name="응원", aliases=["응원해줘"], help="자신 또는 선택한 멤버에게 짧은 응원 메시지를 전합니다.")
    async def encourage(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        target = 대상 or ctx.author
        message = await ctx.send(
            f"🫂 {target.mention} **{random.choice(ENCOURAGEMENTS)}**",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await _safe_reactions(message, ("🫂", "🖤", "🔥"))

    async def mention_handler(message: discord.Message) -> bool:
        if message.guild is None or message.author.bot:
            return False
        state = guild_state(message.guild)
        if not state["settings"].get("enabled", True) or not state["settings"].get("mention_reply", True):
            return False
        text = message.content
        if bot.user is not None:
            text = re.sub(rf"<@!?{bot.user.id}>", " ", text)
        text = SPACE_PATTERN.sub(" ", text).strip()
        if not text:
            text = "안녕"
        session = start_conversation(message.guild, message.channel, message.author)
        await send_public_reply(message.channel, message.guild, message.author, text, reply_to=message, session=session)
        return True

    async def conversation_listener(message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return
        content = str(message.content or "").strip()
        if not content or content.startswith(("!", "/")):
            return
        if bot.user and bot.user.mentioned_in(message):
            return
        session = active_conversation(message.guild.id, message.channel.id, message.author.id)
        replied_to_bot = False
        reference = getattr(message, "reference", None)
        resolved = getattr(reference, "resolved", None) if reference is not None else None
        if resolved is not None and bot.user is not None:
            replied_to_bot = int(getattr(getattr(resolved, "author", None), "id", 0)) == int(bot.user.id)
        if session is None and not replied_to_bot:
            return
        if session is None:
            session = start_conversation(message.guild, message.channel, message.author)
        if int(session.get("turns", 0)) >= CONVERSATION_MAX_TURNS:
            stop_conversation(message.guild.id, message.channel.id, message.author.id)
            await message.reply(
                f"🌙 이번 대화는 {CONVERSATION_MAX_TURNS}회에 도달해 잠시 닫았습니다. `!말걸기`로 새 대화를 시작해 주세요.",
                mention_author=False,
            )
            return
        now = time.monotonic()
        if now - float(session.get("last_message_at", 0.0)) < CONVERSATION_MESSAGE_COOLDOWN:
            return
        session["last_message_at"] = now
        if _normalize(content) in {"대화 종료", "그만 말하자", "대화 끝", "이제 그만"}:
            stop_conversation(message.guild.id, message.channel.id, message.author.id)
            await message.reply("🌙 알겠습니다. 대화 연결을 종료했어요.", mention_author=False)
            return
        await send_public_reply(message.channel, message.guild, message.author, content, reply_to=message, session=session)

    async def auto_exact_listener(message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return
        if message.content.startswith(tuple(prefix for prefix in ("!", "/") if prefix)):
            return
        if bot.user and bot.user.mentioned_in(message):
            return
        state = guild_state(message.guild)
        if active_conversation(message.guild.id, message.channel.id, message.author.id) is not None:
            return
        if not state["settings"].get("enabled", True) or not state["settings"].get("auto_exact", False):
            return
        entry = _find_entry(state, message.content, allow_contains=False)
        if entry is None:
            return
        cooldown = max(3, int(state["settings"].get("response_cooldown", AUTO_REPLY_COOLDOWN)))
        key = (message.guild.id, message.channel.id)
        now = time.monotonic()
        if now - channel_cooldowns.get(key, 0.0) < cooldown:
            return
        channel_cooldowns[key] = now
        entry["uses"] = int(entry.get("uses", 0)) + 1
        entry["last_used_at"] = _iso_now()
        state["stats"]["learned_hits"] = int(state["stats"].get("learned_hits", 0)) + 1
        _add_bond(state, message.author.id, 1)
        save_data()
        response = await message.reply(
            str(entry.get("response", "")),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await _safe_reactions(response, ("🧠", "✨"))

    bot.add_listener(conversation_listener, "on_message")
    bot.add_listener(auto_exact_listener, "on_message")
    bot._abaddon_dialogue_mention_handler = mention_handler
    bot._abaddon_v620_dialogue_registered = True
    print("[V6.2.1 DIALOGUE] 모달 없는 연속 대화·답글 이어가기·기억 공방 등록 완료", flush=True)
