from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import importlib.util
import logging
import os
import shutil
import sys
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


VERSION = "6.5.1"
TTS_MAX_TEXT = 450
TTS_CHUNK_LENGTH = 180
TTS_CACHE_TTL = 21600
TTS_CACHE_LIMIT = 100
TTS_QUEUE_LIMIT = 20
TTS_USER_COOLDOWN = 4.0
DEFAULT_IDLE_SECONDS = 600
TTS_MIN_AUDIO_BYTES = 512
EDGE_FAILURE_BACKOFF_SECONDS = 120
EDGE_RETRY_DELAYS = (0.0, 2.0)
EDGE_STABLE_FALLBACK_VOICES = ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural")
EDGE_VOICE_FAILURE_THRESHOLD = 2
EDGE_VOICE_QUARANTINE_SECONDS = 1800
RENEWAL_EDIT_DELAY = 6.0
RENEWAL_API_TIMEOUT = 45.0
RENEWAL_STEP_COOLDOWN = 300
RENEWAL_PLAN_WARMUP = 300
RENEWAL_429_QUARANTINE = 900
BACKUP_LIMIT = 10
RENEWAL_RATE_LIMIT_CAP = 30.0
RENEWAL_TASKS: Dict[int, asyncio.Task[Any]] = {}
RENEWAL_AUTOPILOT_TASKS: Dict[int, asyncio.Task[Any]] = {}
RENEWAL_HTTP_429_UNTIL = 0
RENEWAL_HTTP_429_LAST = ""

VOICE_PRESETS: Dict[str, Dict[str, str]] = {
    "선히": {"edge": "ko-KR-SunHiNeural", "label": "밝고 자연스러운 여성 음성", "gender": "여성"},
    "서현": {"edge": "ko-KR-SeoHyeonNeural", "label": "차분하고 선명한 여성 음성", "gender": "여성"},
    "지민": {"edge": "ko-KR-JiMinNeural", "label": "부드럽고 친근한 여성 음성", "gender": "여성"},
    "순복": {"edge": "ko-KR-SoonBokNeural", "label": "편안하고 안정적인 여성 음성", "gender": "여성"},
    "유진": {"edge": "ko-KR-YuJinNeural", "label": "또렷하고 생기 있는 여성 음성", "gender": "여성"},
    "인준": {"edge": "ko-KR-InJoonNeural", "label": "차분하고 부드러운 남성 음성", "gender": "남성"},
    "봉진": {"edge": "ko-KR-BongJinNeural", "label": "낮고 안정적인 남성 음성", "gender": "남성"},
    "국민": {"edge": "ko-KR-GookMinNeural", "label": "또렷하고 힘 있는 남성 음성", "gender": "남성"},
    "현수": {"edge": "ko-KR-HyunsuNeural", "label": "담백하고 자연스러운 남성 음성", "gender": "남성"},
    "현수다국어": {"edge": "ko-KR-HyunsuMultilingualNeural", "label": "외국어 발음도 지원하는 남성 음성", "gender": "남성"},
}

VOICE_CHOICE_LABELS: Dict[str, str] = {
    name: f"{name} · {data['gender']} · {data['label']}"
    for name, data in VOICE_PRESETS.items()
}

VOICE_APP_CHOICES: List[app_commands.Choice[str]] = [
    app_commands.Choice(name=label[:100], value=name)
    for name, label in VOICE_CHOICE_LABELS.items()
]
EDGE_VOICE_TO_NAME: Dict[str, str] = {data["edge"]: name for name, data in VOICE_PRESETS.items()}


def _voice_name_or_default(value: Any, default: str = "선히") -> str:
    name = str(value or default)
    return name if name in VOICE_PRESETS else default


def _personal_voice(settings: Dict[str, Any], user_id: int) -> str:
    user_voices = settings.setdefault("user_voices", {})
    return _voice_name_or_default(user_voices.get(str(user_id)), _voice_name_or_default(settings.get("voice")))


THEME_META: Dict[str, Dict[str, Any]] = {
    "깔끔": {"label": "정돈된 기본형", "color": 0x5865F2},
    "고딕": {"label": "검은 성역", "color": 0x6D2335},
    "커뮤니티": {"label": "친근한 커뮤니티", "color": 0x57F287},
    "미니멀": {"label": "짧고 단순한 메뉴", "color": 0x99AAB5},
    "사이버": {"label": "네온·터미널", "color": 0x00D9FF},
    "아포칼립스": {"label": "폐허 생존기지", "color": 0xF47B20},
    "판타지": {"label": "길드·왕국", "color": 0x9B59B6},
}


def _theme_color(style: str) -> int:
    return int(THEME_META.get(style, THEME_META["깔끔"])["color"])


def _text_channel_specs(style: str) -> List[Dict[str, Any]]:
    themes: Dict[str, List[Tuple[str, str, str, Tuple[str, ...]]]] = {
        "깔끔": [
            ("notice", "〔 시작 〕", "📢・공지", ("공지", "announcement", "notice")),
            ("rules", "〔 시작 〕", "📕・규칙", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "〔 시작 〕", "🎭・역할", ("역할", "role", "인증")),
            ("help", "〔 시작 〕", "❓・도움", ("도움", "가이드", "guide", "help")),
            ("general", "〔 대화 〕", "💬・일반", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "〔 대화 〕", "🎮・게임", ("게임", "game")),
            ("bot", "〔 대화 〕", "🤖・봇", ("봇", "명령어", "command")),
            ("media", "〔 미디어 〕", "🖼・사진", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "〔 미디어 〕", "🎞・영상", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "〔 문의 〕", "🎫・문의", ("문의", "신고", "건의", "ticket")),
            ("admin", "〔 운영 〕", "🔒・관리", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "〔 운영 〕", "📋・로그", ("로그", "기록", "log")),
        ],
        "고딕": [
            ("notice", "╭─〔 ☩ 성역의 문 〕─╮", "📜・성역-공지", ("공지", "announcement", "notice")),
            ("rules", "╭─〔 ☩ 성역의 문 〕─╮", "📕・성역-규율", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "╭─〔 ☩ 성역의 문 〕─╮", "🎭・서약-선택", ("역할", "role", "인증")),
            ("help", "╭─〔 ☩ 성역의 문 〕─╮", "🕯・길잡이", ("도움", "가이드", "guide", "help")),
            ("general", "╭─〔 🕯 순례자 광장 〕─╮", "💬・순례자-광장", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "╭─〔 🕯 순례자 광장 〕─╮", "🎮・게임-회랑", ("게임", "game")),
            ("bot", "╭─〔 ⚙ 검은 장치실 〕─╮", "🤖・봇-명령실", ("봇", "명령어", "command")),
            ("media", "╭─〔 🖼 기억의 전당 〕─╮", "🖼・사진과-기록", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "╭─〔 🖼 기억의 전당 〕─╮", "🎞・영상과-클립", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "╭─〔 🎫 고해의 방 〕─╮", "🎫・문의-접수", ("문의", "신고", "건의", "ticket")),
            ("admin", "╭─〔 🛡 검은 의회 〕─╮", "🔒・의회-회의실", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "╭─〔 🛡 검은 의회 〕─╮", "📋・감시-기록", ("로그", "기록", "log")),
        ],
        "커뮤니티": [
            ("notice", "━━━ 시작하기 ━━━", "📢・공지사항", ("공지", "announcement", "notice")),
            ("rules", "━━━ 시작하기 ━━━", "📕・이용규칙", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "━━━ 시작하기 ━━━", "🎭・역할선택", ("역할", "role", "인증")),
            ("help", "━━━ 시작하기 ━━━", "❓・도움말", ("도움", "가이드", "guide", "help")),
            ("general", "━━━ 커뮤니티 ━━━", "💬・자유채팅", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "━━━ 커뮤니티 ━━━", "🎮・게임이야기", ("게임", "game")),
            ("bot", "━━━ 커뮤니티 ━━━", "🤖・봇명령어", ("봇", "명령어", "command")),
            ("media", "━━━ 미디어 ━━━", "🖼・사진공유", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "━━━ 미디어 ━━━", "🎞・영상클립", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "━━━ 문의지원 ━━━", "🎫・문의접수", ("문의", "신고", "건의", "ticket")),
            ("admin", "━━━ 운영지원 ━━━", "🔒・운영진채팅", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "━━━ 운영지원 ━━━", "📋・운영로그", ("로그", "기록", "log")),
        ],
        "미니멀": [
            ("notice", "START", "notice", ("공지", "announcement", "notice")),
            ("rules", "START", "rules", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "START", "roles", ("역할", "role", "인증")),
            ("help", "START", "guide", ("도움", "가이드", "guide", "help")),
            ("general", "CHAT", "general", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "CHAT", "games", ("게임", "game")),
            ("bot", "CHAT", "bot", ("봇", "명령어", "command")),
            ("media", "MEDIA", "photos", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "MEDIA", "clips", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "SUPPORT", "support", ("문의", "신고", "건의", "ticket")),
            ("admin", "STAFF", "staff", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "STAFF", "logs", ("로그", "기록", "log")),
        ],
        "사이버": [
            ("notice", "【 00 · BOOT 】", "📡・system-news", ("공지", "announcement", "notice")),
            ("rules", "【 00 · BOOT 】", "📑・protocol", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "【 00 · BOOT 】", "🪪・access-role", ("역할", "role", "인증")),
            ("help", "【 00 · BOOT 】", "💾・manual", ("도움", "가이드", "guide", "help")),
            ("general", "【 01 · NETWORK 】", "💬・main-link", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "【 01 · NETWORK 】", "🎮・game-node", ("게임", "game")),
            ("bot", "【 02 · TERMINAL 】", "⌨️・bot-terminal", ("봇", "명령어", "command")),
            ("media", "【 03 · ARCHIVE 】", "🖼・image-cache", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "【 03 · ARCHIVE 】", "🎞・video-cache", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "【 04 · SUPPORT 】", "🎫・support-ticket", ("문의", "신고", "건의", "ticket")),
            ("admin", "【 99 · ADMIN 】", "🔒・admin-core", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "【 99 · ADMIN 】", "📋・system-log", ("로그", "기록", "log")),
        ],
        "아포칼립스": [
            ("notice", "╔〔 생존자 전초기지 〕╗", "📻・비상-방송", ("공지", "announcement", "notice")),
            ("rules", "╔〔 생존자 전초기지 〕╗", "📕・생존-수칙", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "╔〔 생존자 전초기지 〕╗", "🪪・생존자-등록", ("역할", "role", "인증")),
            ("help", "╔〔 생존자 전초기지 〕╗", "🧭・작전-안내", ("도움", "가이드", "guide", "help")),
            ("general", "╠〔 공동 대피소 〕╣", "💬・대피소-광장", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "╠〔 공동 대피소 〕╣", "🎮・휴식-구역", ("게임", "game")),
            ("bot", "╠〔 통제 장치실 〕╣", "🤖・작전-단말기", ("봇", "명령어", "command")),
            ("media", "╠〔 기록 보관소 〕╣", "📸・현장-사진", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "╠〔 기록 보관소 〕╣", "🎞・생존-기록", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "╠〔 구조 요청소 〕╣", "🆘・구조-요청", ("문의", "신고", "건의", "ticket")),
            ("admin", "╚〔 지휘 통제실 〕╝", "🔒・지휘관-회의", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "╚〔 지휘 통제실 〕╝", "📋・감시-일지", ("로그", "기록", "log")),
        ],
        "판타지": [
            ("notice", "✦ 왕국의 관문 ✦", "📜・왕국-칙령", ("공지", "announcement", "notice")),
            ("rules", "✦ 왕국의 관문 ✦", "📖・모험가-규율", ("규칙", "룰", "이용규칙", "rule")),
            ("roles", "✦ 왕국의 관문 ✦", "🎭・직업-선택", ("역할", "role", "인증")),
            ("help", "✦ 왕국의 관문 ✦", "🗺・모험-안내", ("도움", "가이드", "guide", "help")),
            ("general", "✦ 모험가 길드 ✦", "💬・길드-홀", ("일반", "자유", "잡담", "광장", "general", "chat")),
            ("game", "✦ 모험가 길드 ✦", "🎮・놀이-광장", ("게임", "game")),
            ("bot", "✦ 마도 공방 ✦", "🔮・마법-명령실", ("봇", "명령어", "command")),
            ("media", "✦ 기억의 수정관 ✦", "🖼・모험-사진", ("사진", "미디어", "이미지", "스크린샷", "media")),
            ("clips", "✦ 기억의 수정관 ✦", "🎞・영웅-연대기", ("영상", "클립", "동영상", "clip", "video")),
            ("ticket", "✦ 의뢰 게시소 ✦", "📨・길드-의뢰", ("문의", "신고", "건의", "ticket")),
            ("admin", "✦ 왕실 회의실 ✦", "🔒・원탁-회의", ("관리자", "운영진", "스태프", "admin")),
            ("logs", "✦ 왕실 회의실 ✦", "📚・왕국-기록", ("로그", "기록", "log")),
        ],
    }
    rows = themes.get(style, themes["깔끔"])
    return [{"key": key, "category": category, "name": name, "keywords": keywords} for key, category, name, keywords in rows]


def _voice_channel_specs(style: str) -> List[Dict[str, Any]]:
    mapping: Dict[str, Tuple[str, Tuple[str, str, str]]] = {
        "깔끔": ("〔 음성 〕", ("🔊・로비", "🎮・게임", "🌙・잠수")),
        "고딕": ("╭─〔 🔊 메아리의 회랑 〕─╮", ("🔊・메아리-대기실", "🎮・전장의-방", "🌙・침묵의-방")),
        "커뮤니티": ("━━━ 음성채널 ━━━", ("🔊・음성로비", "🎮・게임방", "🌙・잠수방")),
        "미니멀": ("VOICE", ("lobby", "game", "afk")),
        "사이버": ("【 05 · VOICE LINK 】", ("🔊・voice-lobby", "🎮・squad-link", "🌙・idle-mode")),
        "아포칼립스": ("╠〔 무전 통신망 〕╣", ("📻・공용-무전", "🎮・분대-통신", "🌙・무전-대기")),
        "판타지": ("✦ 음유시인의 회랑 ✦", ("🔊・모험가-휴게실", "🎮・파티-원정", "🌙・고요한-숲")),
    }
    category, names = mapping.get(style, mapping["깔끔"])
    return [
        {"key": "voice_lobby", "category": category, "name": names[0], "keywords": ("로비", "대기", "일반", "lobby")},
        {"key": "voice_game", "category": category, "name": names[1], "keywords": ("게임", "game")},
        {"key": "voice_afk", "category": category, "name": names[2], "keywords": ("잠수", "afk")},
    ]


def _game_zone_specs(style: str) -> List[Dict[str, Any]]:
    category_sets: Dict[str, Dict[str, str]] = {
        "깔끔": {"growth": "〔 RPG · 성장 〕", "game": "〔 게임 · 도박 〕", "media": "〔 음악 · 미디어 〕", "test": "〔 테스트 〕", "voice": "〔 음성 라운지 〕"},
        "고딕": {"growth": "╭─〔 ⚔ 종말 전장 〕─╮", "game": "╭─〔 🎲 운명의 방 〕─╮", "media": "╭─〔 🎵 망자의 선율 〕─╮", "test": "╭─〔 🧪 봉인 실험실 〕─╮", "voice": "╭─〔 🔊 메아리의 방 〕─╮"},
        "커뮤니티": {"growth": "━━━ RPG · 성장 ━━━", "game": "━━━ 게임 · 도박 ━━━", "media": "━━━ 음악 · 미디어 ━━━", "test": "━━━ 테스트 ━━━", "voice": "━━━ 음성 라운지 ━━━"},
        "미니멀": {"growth": "RPG", "game": "GAMES", "media": "MEDIA", "test": "TEST", "voice": "VOICE ROOMS"},
        "사이버": {"growth": "【 10 · RPG CORE 】", "game": "【 11 · GAME GRID 】", "media": "【 12 · MEDIA CACHE 】", "test": "【 98 · TEST LAB 】", "voice": "【 13 · VOICE LINK 】"},
        "아포칼립스": {"growth": "╠〔 원정 지휘소 〕╣", "game": "╠〔 휴식·도박 구역 〕╣", "media": "╠〔 방송·기록소 〕╣", "test": "╠〔 장비 시험소 〕╣", "voice": "╠〔 무전 통신망 〕╣"},
        "판타지": {"growth": "✦ 모험가 성장관 ✦", "game": "✦ 주사위 선술집 ✦", "media": "✦ 음유시인 무대 ✦", "test": "✦ 마법 실험실 ✦", "voice": "✦ 파티 음성관 ✦"},
    }
    categories = category_sets.get(style, category_sets["깔끔"])
    names: Dict[str, Dict[str, str]] = {
        "깔끔": {"rpg": "⚔️・아포칼립스-rpg", "level": "🎉・레벨-알림", "quiz": "🧭・오늘의-퀴즈방", "gambling": "🎲・도박장", "ksi": "🤖・크시", "tiktok": "📱・틱톡", "karaoke": "🎵・노래방", "test": "🧪・봇-테스트"},
        "고딕": {"rpg": "⚔️・종말-rpg", "level": "🩸・성장-기록", "quiz": "🧭・운명의-문답", "gambling": "🎲・운명의-도박장", "ksi": "🤖・검은-인형", "tiktok": "📱・짧은-기억", "karaoke": "🎵・망자의-노래", "test": "🧪・봉인-실험"},
        "커뮤니티": {"rpg": "⚔️・아포칼립스-rpg", "level": "🎉・레벨업-알림", "quiz": "🧭・오늘의-퀴즈", "gambling": "🎲・도박장", "ksi": "🤖・크시", "tiktok": "📱・틱톡", "karaoke": "🎵・노래방", "test": "🧪・봇-테스트"},
        "미니멀": {"rpg": "rpg", "level": "level-up", "quiz": "daily-quiz", "gambling": "casino", "ksi": "ksi", "tiktok": "shorts", "karaoke": "music", "test": "bot-test"},
        "사이버": {"rpg": "⚔️・rpg-core", "level": "📈・level-signal", "quiz": "🧠・daily-query", "gambling": "🎲・casino-node", "ksi": "🤖・ksi-bot", "tiktok": "📱・short-cache", "karaoke": "🎵・audio-stream", "test": "🧪・sandbox"},
        "아포칼립스": {"rpg": "⚔️・생존-rpg", "level": "📈・생존자-성장", "quiz": "🧭・일일-작전", "gambling": "🎲・암시장-도박", "ksi": "🤖・보조-단말", "tiktok": "📱・현장-숏폼", "karaoke": "🎵・대피소-방송", "test": "🧪・장비-시험"},
        "판타지": {"rpg": "⚔️・모험가-rpg", "level": "✨・성장-축복", "quiz": "🗺・오늘의-의뢰", "gambling": "🎲・선술집-주사위", "ksi": "🤖・마도-골렘", "tiktok": "📱・짧은-연대기", "karaoke": "🎵・음유시인-무대", "test": "🧪・마법-실험"},
    }
    n = names.get(style, names["깔끔"])
    return [
        {"key": "rpg", "category": categories["growth"], "name": n["rpg"], "keywords": ("아포칼립스rpg", "아포칼립스", "rpg")},
        {"key": "level_notice", "category": categories["growth"], "name": n["level"], "keywords": ("레벨알림", "레벨", "levelnotify", "levelup")},
        {"key": "daily_quiz", "category": categories["growth"], "name": n["quiz"], "keywords": ("오늘의퀴즈방", "오늘의퀴즈", "퀴즈방", "퀴즈", "quiz")},
        {"key": "gambling", "category": categories["game"], "name": n["gambling"], "keywords": ("도박장", "도박", "카지노", "casino", "gambling")},
        {"key": "ksi", "category": categories["game"], "name": n["ksi"], "keywords": ("크시", "kshi", "ksi")},
        {"key": "tiktok", "category": categories["media"], "name": n["tiktok"], "keywords": ("틱톡", "tiktok", "shorts")},
        {"key": "karaoke", "category": categories["media"], "name": n["karaoke"], "keywords": ("노래방", "음악", "뮤직", "music", "song")},
        {"key": "bot_test", "category": categories["test"], "name": n["test"], "keywords": ("봇테스트", "테스트", "test")},
    ]


def _game_zone_category_names(style: str) -> Dict[str, str]:
    specs = _game_zone_specs(style)
    result = {"growth": specs[0]["category"], "game": specs[3]["category"], "media": specs[5]["category"], "test": specs[7]["category"]}
    result["voice"] = _voice_channel_specs(style)[0]["category"]
    return result

def _roman_label(index: int) -> str:
    romans = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
    return romans[index] if 0 <= index < len(romans) else str(index + 1)


class RenewalApiTimeout(RuntimeError):
    pass


class _Renewal429LogHandler(logging.Handler):
    """discord.py가 내부 재시도한 429도 감지해 리뉴얼 작업을 격리합니다."""

    _abaddon_renewal_429_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        global RENEWAL_HTTP_429_UNTIL, RENEWAL_HTTP_429_LAST
        try:
            message = record.getMessage()
        except Exception:
            return
        if "429" not in message or "rate limit" not in message.lower():
            return
        RENEWAL_HTTP_429_UNTIL = max(
            RENEWAL_HTTP_429_UNTIL,
            int(time.time()) + RENEWAL_429_QUARANTINE,
        )
        RENEWAL_HTTP_429_LAST = message[:300]


def _install_renewal_429_handler() -> None:
    logger = logging.getLogger("discord.http")
    if any(getattr(handler, "_abaddon_renewal_429_handler", False) for handler in logger.handlers):
        return
    logger.addHandler(_Renewal429LogHandler())


def _renewal_quarantine_remaining() -> int:
    return max(0, int(RENEWAL_HTTP_429_UNTIL - time.time()))


async def _renewal_api(awaitable):
    """Discord 채널 변경 요청이 장시간 429 대기에 갇히는 것을 차단합니다."""
    try:
        return await asyncio.wait_for(awaitable, timeout=RENEWAL_API_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise RenewalApiTimeout(
            f"Discord 채널 변경 응답이 {int(RENEWAL_API_TIMEOUT)}초 안에 오지 않아 안전 중단했습니다."
        ) from exc


async def _renewal_pause() -> None:
    # 채널 이름·카테고리 변경은 같은 Discord 라우트 제한을 공유하므로 넉넉히 간격을 둡니다.
    await asyncio.sleep(RENEWAL_EDIT_DELAY)


def _renewal_running(guild_id: int) -> bool:
    task = RENEWAL_TASKS.get(guild_id)
    return task is not None and not task.done()


def _layout_category_aliases(target_name: str) -> set[str]:
    target_signature = None
    style_groups = []
    for style in STYLE_NAMES:
        groups: Dict[str, set[str]] = {}
        for spec in [*_text_channel_specs(style), *_voice_channel_specs(style)]:
            groups.setdefault(spec["category"], set()).add(spec["key"])
        style_groups.append(groups)
        if target_name in groups:
            target_signature = frozenset(groups[target_name])
    if target_signature is None:
        return {target_name}
    aliases = {
        category_name
        for groups in style_groups
        for category_name, keys in groups.items()
        if frozenset(keys) == target_signature
    }
    aliases.add(target_name)
    return aliases


def _game_category_aliases(target_name: str) -> set[str]:
    role = None
    mappings = []
    for style in STYLE_NAMES:
        mapping = _game_zone_category_names(style)
        mappings.append(mapping)
        for key, value in mapping.items():
            if value == target_name:
                role = key
                break
    if role is None:
        return {target_name}
    aliases = {mapping[role] for mapping in mappings if role in mapping}
    aliases.add(target_name)
    return aliases


def _find_semantic_category(
    guild: discord.Guild,
    target_name: str,
    used_ids: set[int],
    *,
    family: str,
) -> Optional[discord.CategoryChannel]:
    exact = discord.utils.get(guild.categories, name=target_name)
    if exact is not None and exact.id not in used_ids:
        return exact
    aliases = _layout_category_aliases(target_name) if family == "layout" else _game_category_aliases(target_name)
    normalised = {_normalise_name(name) for name in aliases}
    candidates = [
        category for category in guild.categories
        if category.id not in used_ids and _normalise_name(category.name) in normalised
    ]
    # 빈 카테고리를 우선 재사용해 중복 생성 가능성을 낮춥니다.
    candidates.sort(key=lambda category: (bool(category.channels), category.position, category.id))
    return candidates[0] if candidates else None


def _category_score(category: discord.CategoryChannel, keywords: Iterable[str]) -> int:
    name = _normalise_name(category.name)
    score = 0
    for keyword in keywords:
        norm = _normalise_name(keyword)
        if not norm:
            continue
        if name == norm:
            score = max(score, 100)
        elif norm in name:
            score = max(score, 70)
    return score


def _best_category(guild: discord.Guild, keywords: Iterable[str], excluded: set[int]) -> Optional[discord.CategoryChannel]:
    best = None
    best_score = 0
    for category in guild.categories:
        if category.id in excluded:
            continue
        score = _category_score(category, keywords)
        if score > best_score:
            best = category
            best_score = score
    return best if best_score >= 70 else None


def _detect_game_zone_channels(
    guild: discord.Guild,
    style: str,
) -> Tuple[List[Tuple[Dict[str, Any], Optional[discord.TextChannel]]], List[discord.VoiceChannel], Optional[discord.CategoryChannel], Optional[discord.CategoryChannel], Optional[discord.CategoryChannel]]:
    used: set[int] = set()
    text_matches: List[Tuple[Dict[str, Any], Optional[discord.TextChannel]]] = []
    for spec in _game_zone_specs(style):
        channel = _best_channel(guild.text_channels, spec["keywords"], used)
        if isinstance(channel, discord.TextChannel):
            used.add(channel.id)
        else:
            channel = None
        text_matches.append((spec, channel))

    excluded: set[int] = set()
    bot_game_category = _best_category(guild, ("BOT GAME", "봇게임", "봇 게임", "게임봇"), excluded)
    if bot_game_category is not None:
        excluded.add(bot_game_category.id)
    voice_category = _best_category(guild, ("말해라", "음성", "voice", "보이스"), excluded)
    if voice_category is not None:
        excluded.add(voice_category.id)
    test_category = _best_category(guild, ("테스트", "test"), excluded)

    numbered_names = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
    voices: List[discord.VoiceChannel] = []
    if voice_category is not None:
        voices = [channel for channel in voice_category.voice_channels]
    if not voices:
        voices = [
            channel
            for channel in guild.voice_channels
            if _normalise_name(channel.name) in numbered_names
            or any(keyword in _normalise_name(channel.name) for keyword in ("말해라", "음성", "voice", "보이스"))
        ]
    voices.sort(key=lambda channel: (channel.category.position if channel.category else 9999, channel.position, channel.id))
    return text_matches, voices, bot_game_category, voice_category, test_category


def _game_zone_preview_embed(guild: discord.Guild, style: str) -> discord.Embed:
    text_matches, voices, bot_game_category, voice_category, test_category = _detect_game_zone_channels(guild, style)
    categories = _game_zone_category_names(style)
    embed = discord.Embed(
        title=f"🎮 봇 게임·음성 구역 정리 미리보기 · {style}",
        description=(
            "사용 중인 채널을 삭제하지 않고 **RPG·성장 / 게임·도박 / 음악·미디어 / 테스트 / 음성 라운지**로 나눕니다.\n"
            "기존 `BOT GAME`, `말해라`, `테스트` 카테고리는 가능한 경우 새 이름으로 재사용합니다."
        ),
        color=_theme_color(style),
    )
    detected = [channel for _, channel in text_matches if channel is not None]
    embed.add_field(name="찾은 텍스트 채널", value=f"**{len(detected)}개 / {len(text_matches)}개**", inline=True)
    embed.add_field(name="찾은 음성 채널", value=f"**{len(voices)}개**", inline=True)
    reused = sum(category is not None for category in (bot_game_category, voice_category, test_category))
    embed.add_field(name="재사용할 카테고리", value=f"**{reused}개**", inline=True)

    lines: List[str] = []
    for spec, channel in text_matches:
        if channel is not None:
            lines.append(f"• {channel.mention} → `{spec['category']}` / `{spec['name']}`")
    for index, channel in enumerate(voices):
        lines.append(f"• {channel.mention} → `{categories['voice']}` / `🔊・음성-{_roman_label(index)}`")
    embed.add_field(name="정리 계획", value="\n".join(lines[:20]) or "인식한 대상 채널이 없습니다.", inline=False)
    embed.add_field(
        name="적용 명령",
        value=f"`!서버리뉴얼 게임정리 {style}`\n되돌리기: `!서버리뉴얼 되돌리기`",
        inline=False,
    )
    return embed


STYLE_NAMES = set(THEME_META)
ESSENTIAL_KEYS = {"notice", "rules", "roles", "general", "bot", "voice_lobby", "voice_afk"}
ADMIN_KEYS = {"admin", "logs"}
READ_ONLY_KEYS = {"notice", "rules", "roles", "help"}


def _normalise_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣]+", "", value or "").lower()
    return value


def _best_channel(channels: Sequence[Any], keywords: Iterable[str], used: set[int]) -> Optional[Any]:
    best: Optional[Any] = None
    best_score = 0
    normalised_keywords = [_normalise_name(keyword) for keyword in keywords]
    for channel in channels:
        if channel.id in used:
            continue
        name = _normalise_name(channel.name)
        score = 0
        for keyword in normalised_keywords:
            if not keyword:
                continue
            if name == keyword:
                score = max(score, 100)
            elif keyword in name:
                score = max(score, 60 + min(20, len(keyword)))
        if score > best_score:
            best = channel
            best_score = score
    return best if best_score >= 60 else None


def _layout_settings(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = world_data.setdefault("voice_sanctuary", {})
    settings = root.setdefault(str(guild_id), {})
    settings.setdefault("tts", {})
    tts = settings["tts"]
    tts.setdefault("enabled", False)
    tts.setdefault("text_channel_id", None)
    tts.setdefault("voice_channel_id", None)
    tts.setdefault("mode", "author_voice")
    if tts.get("mode") not in {"author_voice", "fixed"}:
        tts["mode"] = "author_voice"
    # v4.3.3.3부터 실제 Microsoft 음성 이름과 표시 이름을 일치시킵니다.
    # 구버전의 "서현"은 실제로 SunHi 음성을 사용했으므로 선히로 자동 이관합니다.
    if int(tts.get("voice_schema_version", 0) or 0) < 2:
        if tts.get("voice") == "서현":
            tts["voice"] = "선히"
        tts["voice_schema_version"] = 2
    tts.setdefault("voice", "선히")
    tts["voice"] = _voice_name_or_default(tts.get("voice"))
    tts.setdefault("user_voices", {})
    if not isinstance(tts.get("user_voices"), dict):
        tts["user_voices"] = {}
    tts.setdefault("speed", 1.0)
    tts.setdefault("volume", 1.0)
    tts.setdefault("idle_seconds", DEFAULT_IDLE_SECONDS)
    tts["announce_names"] = False  # v5.0.2: 닉네임은 읽지 않고 채팅 내용만 낭독
    tts.setdefault("auto_join", True)
    tts.setdefault("require_author_in_voice", True)
    tts.setdefault("engine", "auto")
    if tts.get("engine") not in {"auto", "edge", "google"}:
        tts["engine"] = "auto"
    settings.setdefault("layout", {})
    settings["layout"].setdefault("style", None)
    settings["layout"].setdefault("backup", None)
    settings["layout"].setdefault("backup_history", [])
    if not isinstance(settings["layout"].get("backup_history"), list):
        settings["layout"]["backup_history"] = []
    for backup_item in _backup_candidates(settings["layout"]):
        backup_item.setdefault("backup_id", f"legacy-{backup_item.get('created_at', 0)}")
        backup_item.setdefault("name", "기존 자동 백업")
    settings["layout"].setdefault("renewal_plan", None)
    settings["layout"].setdefault("autopilot", {})
    autopilot = settings["layout"]["autopilot"]
    if not isinstance(autopilot, dict):
        autopilot = {}
        settings["layout"]["autopilot"] = autopilot
    autopilot.setdefault("enabled", False)
    autopilot.setdefault("mode", None)
    autopilot.setdefault("channel_id", None)
    autopilot.setdefault("started_by", None)
    autopilot.setdefault("started_at", 0)
    autopilot.setdefault("next_run_at", 0)
    autopilot.setdefault("last_reason", "아직 실행 기록 없음")
    settings["layout"].setdefault("menu_channel_id", None)
    settings["layout"].setdefault("menu_message_id", None)
    return settings



def _serialize_overwrites(channel: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for target, overwrite in getattr(channel, "overwrites", {}).items():
        allow, deny = overwrite.pair()
        rows.append({
            "id": int(target.id),
            "type": "role" if isinstance(target, discord.Role) else "member",
            "allow": int(allow.value),
            "deny": int(deny.value),
        })
    rows.sort(key=lambda row: (row["type"], row["id"]))
    return rows


def _backup_id(guild_id: int) -> str:
    return f"{guild_id}-{int(time.time() * 1000)}"


def _backup_candidates(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    current = layout.get("backup")
    if isinstance(current, dict):
        items.append(current)
    history = layout.get("backup_history", [])
    if isinstance(history, list):
        items.extend(reversed([item for item in history if isinstance(item, dict)]))

    unique: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identity = str(item.get("backup_id") or f"legacy-{item.get('created_at', 0)}")
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(item)
    return unique[:BACKUP_LIMIT]


def _backup_title(item: Dict[str, Any], index: int) -> str:
    name = str(item.get("name") or item.get("backup_name") or "자동 백업")
    operation = str(item.get("operation") or "legacy")
    return f"{index}. {name} · {operation}"[:100]


def _find_backup(layout: Dict[str, Any], backup_id: str) -> Optional[Dict[str, Any]]:
    for item in _backup_candidates(layout):
        identity = str(item.get("backup_id") or f"legacy-{item.get('created_at', 0)}")
        if identity == str(backup_id):
            return item
    return None

def _snapshot_guild(
    guild: discord.Guild,
    *,
    operation: str = "manual",
    style: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    created_at = int(time.time())
    return {
        "snapshot_version": 3,
        "backup_id": _backup_id(guild.id),
        "name": (str(name or "").strip() or "현재 서버 상태")[:60],
        "created_at": created_at,
        "operation": operation,
        "style": style,
        "guild_id": guild.id,
        "created_category_ids": [],
        "created_channel_ids": [],
        "reused_category_ids": [],
        "categories": [
            {
                "id": category.id,
                "name": category.name,
                "position": category.position,
                "overwrites": _serialize_overwrites(category),
            }
            for category in guild.categories
        ],
        "channels": [
            {
                "id": channel.id,
                "name": channel.name,
                "category_id": channel.category_id,
                "position": channel.position,
                "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
                "overwrites": _serialize_overwrites(channel),
                "nsfw": bool(getattr(channel, "nsfw", False)),
                "slowmode_delay": int(getattr(channel, "slowmode_delay", 0) or 0),
                "bitrate": int(getattr(channel, "bitrate", 0) or 0),
                "user_limit": int(getattr(channel, "user_limit", 0) or 0),
            }
            for channel in [*guild.text_channels, *guild.voice_channels]
        ],
    }

def _store_backup(layout: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    snapshot.setdefault("backup_id", f"legacy-{snapshot.get('created_at', int(time.time()))}")
    snapshot.setdefault("name", "자동 백업")
    previous = layout.get("backup")
    history = layout.setdefault("backup_history", [])
    if not isinstance(history, list):
        history = []
        layout["backup_history"] = history
    if isinstance(previous, dict):
        previous.setdefault("backup_id", f"legacy-{previous.get('created_at', 0)}")
        previous.setdefault("name", "기존 백업")
        previous_id = str(previous.get("backup_id"))
        if not history or str(history[-1].get("backup_id")) != previous_id:
            history.append(previous)
    history[:] = history[-(BACKUP_LIMIT - 1):]
    layout["backup"] = snapshot
    return snapshot

def _record_created(backup: Dict[str, Any], kind: str, object_id: int) -> None:
    key = "created_category_ids" if kind == "category" else "created_channel_ids"
    values = backup.setdefault(key, [])
    if object_id not in values:
        values.append(object_id)


def _all_theme_category_names() -> set[str]:
    names: set[str] = set()
    for style in STYLE_NAMES:
        for spec in [*_text_channel_specs(style), *_voice_channel_specs(style), *_game_zone_specs(style)]:
            names.add(str(spec["category"]))
        names.update(_game_zone_category_names(style).values())
    return names


def _all_theme_channel_names() -> set[str]:
    names: set[str] = set()
    for style in STYLE_NAMES:
        for spec in [*_text_channel_specs(style), *_voice_channel_specs(style), *_game_zone_specs(style)]:
            names.add(str(spec["name"]))
        for index in range(10):
            names.add(f"🔊・음성-{_roman_label(index)}")
    return names


def _empty_categories(guild: discord.Guild) -> List[discord.CategoryChannel]:
    return sorted(
        [category for category in guild.categories if not category.channels],
        key=lambda category: (category.position, category.id),
    )


def _parse_category_selection(raw: str, empty: Sequence[discord.CategoryChannel]) -> List[discord.CategoryChannel]:
    value = (raw or "").strip().lower()
    if value in {"전체", "all"}:
        return list(empty)
    indices: set[int] = set()
    for token in re.split(r"[,\s]+", value):
        if not token:
            continue
        if "-" in token:
            left, _, right = token.partition("-")
            if left.isdigit() and right.isdigit():
                start_i, end_i = int(left), int(right)
                for number in range(min(start_i, end_i), max(start_i, end_i) + 1):
                    indices.add(number)
        elif token.isdigit():
            indices.add(int(token))
    return [category for index, category in enumerate(empty, start=1) if index in indices]

def _admin_category_overwrites(
    guild: discord.Guild,
    author: discord.Member,
    bot_member: discord.Member,
) -> Dict[Any, discord.PermissionOverwrite]:
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
        ),
    }


def _public_read_only_overwrites(
    guild: discord.Guild,
    author: discord.Member,
    bot_member: discord.Member,
    allow_reactions: bool = False,
) -> Dict[Any, discord.PermissionOverwrite]:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=allow_reactions,
        ),
        author: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            add_reactions=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            add_reactions=True,
            embed_links=True,
        ),
    }


def _channel_url(guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


def _detect_layout(guild: discord.Guild, style: str) -> Tuple[List[Tuple[Dict[str, Any], Optional[Any]]], List[Tuple[Dict[str, Any], Optional[Any]]]]:
    used_text: set[int] = set()
    used_voice: set[int] = set()
    text_matches: List[Tuple[Dict[str, Any], Optional[Any]]] = []
    voice_matches: List[Tuple[Dict[str, Any], Optional[Any]]] = []
    for spec in _text_channel_specs(style):
        channel = _best_channel(guild.text_channels, spec["keywords"], used_text)
        if channel is not None:
            used_text.add(channel.id)
        text_matches.append((spec, channel))
    for spec in _voice_channel_specs(style):
        channel = _best_channel(guild.voice_channels, spec["keywords"], used_voice)
        if channel is not None:
            used_voice.add(channel.id)
        voice_matches.append((spec, channel))
    return text_matches, voice_matches


def _layout_preview_embed(guild: discord.Guild, style: str) -> discord.Embed:
    text_matches, voice_matches = _detect_layout(guild, style)
    move_count = sum(1 for _, channel in [*text_matches, *voice_matches] if channel is not None)
    create_count = sum(
        1
        for spec, channel in [*text_matches, *voice_matches]
        if channel is None and spec["key"] in ESSENTIAL_KEYS
    )
    category_names = []
    for spec, _ in [*text_matches, *voice_matches]:
        if spec["category"] not in category_names:
            category_names.append(spec["category"])
    existing_categories = {category.name for category in guild.categories}
    category_create = sum(1 for name in category_names if name not in existing_categories)

    embed = discord.Embed(
        title=f"🕯 서버 리뉴얼 미리보기 · {style}",
        description=(
            "기존 채널을 키워드로 찾아 이름과 위치를 정돈합니다.\n"
            "**채널·역할·메시지는 삭제하지 않으며**, 인식하지 못한 채널은 그대로 둡니다."
        ),
        color=_theme_color(style),
    )
    embed.add_field(name="찾은 기존 채널", value=f"**{move_count}개**", inline=True)
    embed.add_field(name="새 필수 채널", value=f"**{create_count}개**", inline=True)
    embed.add_field(name="새 카테고리", value=f"**{category_create}개**", inline=True)
    lines = []
    for spec, channel in [*text_matches, *voice_matches]:
        if channel is not None:
            lines.append(f"• {channel.mention} → `{spec['name']}`")
        elif spec["key"] in ESSENTIAL_KEYS:
            lines.append(f"• 새로 생성 → `{spec['name']}`")
    embed.add_field(name="적용 계획", value="\n".join(lines[:16]) or "변경할 필수 항목이 없습니다.", inline=False)
    embed.add_field(
        name="실행",
        value=f"`!서버리뉴얼 적용 {style}`\n되돌리기: `!서버리뉴얼 되돌리기`",
        inline=False,
    )
    return embed


def _menu_destinations(guild: discord.Guild) -> List[Tuple[str, str, discord.TextChannel]]:
    definitions = [
        ("공지", "📢", ("공지", "announcement", "notice")),
        ("규칙", "📕", ("규칙", "이용규칙", "rule")),
        ("역할", "🎭", ("역할", "인증", "role")),
        ("자유채팅", "💬", ("일반", "자유", "잡담", "광장", "chat")),
        ("게임", "🎮", ("게임", "game")),
        ("봇 명령", "🤖", ("봇", "명령어", "command")),
        ("사진", "🖼", ("사진", "미디어", "스크린샷", "media")),
        ("문의", "🎫", ("문의", "신고", "건의", "ticket")),
    ]
    used: set[int] = set()
    result: List[Tuple[str, str, discord.TextChannel]] = []
    for label, emoji, keywords in definitions:
        channel = _best_channel(guild.text_channels, keywords, used)
        if channel is None:
            continue
        used.add(channel.id)
        result.append((label, emoji, channel))
    return result[:10]


def _menu_embed(guild: discord.Guild, destinations: Sequence[Tuple[str, str, discord.TextChannel]]) -> discord.Embed:
    description = [
        "필요한 공간으로 바로 이동하세요. 아래 버튼은 Discord 채널 링크라 봇이 재시작돼도 유지됩니다.",
        "",
    ]
    description.extend(f"{emoji} **{label}** · {channel.mention}" for label, emoji, channel in destinations)
    embed = discord.Embed(
        title="☩ 서버 안내 성역",
        description="\n".join(description),
        color=0x2B1824,
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"{guild.name} · ABADDON 서버 메뉴")
    return embed


def _menu_view(guild: discord.Guild, destinations: Sequence[Tuple[str, str, discord.TextChannel]]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for label, emoji, channel in destinations:
        view.add_item(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.link,
                url=_channel_url(guild.id, channel.id),
            )
        )
    return view


def _dependency_state() -> Tuple[bool, bool, bool]:
    """Return PyNaCl, davey, and edge-tts availability for the actual runtime."""
    return (
        importlib.util.find_spec("nacl") is not None,
        importlib.util.find_spec("davey") is not None,
        importlib.util.find_spec("edge_tts") is not None,
    )


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "미설치"
    except Exception:
        return "확인 실패"


def _tts_diagnostic_lines() -> List[str]:
    has_nacl, has_davey, has_edge = _dependency_state()
    ffmpeg = shutil.which("ffmpeg")
    return [
        f"Python: `{sys.version.split()[0]}`",
        f"discord.py: `{_package_version('discord.py')}`",
        f"PyNaCl: `{'설치됨 ' + _package_version('PyNaCl') if has_nacl else '미설치'}`",
        f"davey: `{'설치됨 ' + _package_version('davey') if has_davey else '미설치'}`",
        f"edge-tts: `{'설치됨 ' + _package_version('edge-tts') if has_edge else '미설치'}`",
        f"FFmpeg: `{'확인됨' if ffmpeg else '찾지 못함'}`",
        f"Opus: `{'로드됨' if discord.opus.is_loaded() else '미로드'}`",
    ]


class VoiceRuntime:
    def __init__(self) -> None:
        self.queues: Dict[int, asyncio.Queue[Dict[str, Any]]] = {}
        self.workers: Dict[int, asyncio.Task[None]] = {}
        self.user_cooldowns: Dict[Tuple[int, int], float] = {}
        self.active_channel_ids: Dict[int, int] = {}
        self.speaking: Dict[int, bool] = {}
        self.last_text: Dict[int, str] = {}
        self.cache_hits: Dict[int, int] = {}

    def queue_for(self, guild_id: int) -> asyncio.Queue[Dict[str, Any]]:
        queue = self.queues.get(guild_id)
        if queue is None:
            queue = asyncio.Queue(maxsize=TTS_QUEUE_LIMIT)
            self.queues[guild_id] = queue
        return queue

    def queued_channel_ids(self, guild_id: int) -> set[int]:
        queue = self.queue_for(guild_id)
        return {
            int(item.get("voice_channel_id"))
            for item in list(getattr(queue, "_queue", []))
            if item.get("voice_channel_id")
        }

    def clear(self, guild_id: int) -> int:
        self.active_channel_ids.pop(guild_id, None)
        self.speaking.pop(guild_id, None)
        self.last_text.pop(guild_id, None)
        queue = self.queue_for(guild_id)
        removed = 0
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
                removed += 1
            except asyncio.QueueEmpty:
                return removed


VOICE_RUNTIME = VoiceRuntime()
EDGE_TTS_RUNTIME: Dict[str, Any] = {
    "backoff_until": 0.0,
    "consecutive_failures": 0,
    "last_error": "",
    "last_success_at": 0,
    "last_voice": "",
    "last_requested_voice": "",
    "last_used_voice": "",
    "voice_failures": {},
    "voice_backoff_until": {},
}


def _edge_voice_quarantine_remaining(voice: str) -> int:
    untils = EDGE_TTS_RUNTIME.setdefault("voice_backoff_until", {})
    try:
        until = float(untils.get(voice, 0.0) or 0.0)
    except (TypeError, ValueError):
        until = 0.0
    return max(0, int(until - time.monotonic()))


def _clean_spoken_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " 링크 ", text)
    text = re.sub(r"<a?:\w+:\d+>", "", text)
    text = re.sub(r"[`*_~>|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:TTS_MAX_TEXT]

def _split_spoken_text(text: str) -> List[str]:
    chunks: List[str] = []
    rest = text.strip()
    while rest:
        if len(rest) <= TTS_CHUNK_LENGTH:
            chunks.append(rest)
            break
        cut = max(rest.rfind(mark, 0, TTS_CHUNK_LENGTH + 1) for mark in (". ", "? ", "! ", ", ", " "))
        if cut < 40:
            cut = TTS_CHUNK_LENGTH
        else:
            cut += 1
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [chunk for chunk in chunks if chunk]

def _cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "abaddon_tts_cache_v51"
    path.mkdir(parents=True, exist_ok=True)
    return path

def _cache_path(text: str, voice_key: str, speed: float, engine: str) -> Path:
    import hashlib
    digest = hashlib.sha256(f"{engine}|{voice_key}|{speed:.2f}|{text}".encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.mp3"

def _prune_cache() -> None:
    now = time.time()
    files = sorted(_cache_dir().glob("*.mp3"), key=lambda x: x.stat().st_mtime, reverse=True)
    for index, item in enumerate(files):
        with contextlib.suppress(OSError):
            if index >= TTS_CACHE_LIMIT or now - item.stat().st_mtime > TTS_CACHE_TTL:
                item.unlink()


def _remove_audio_file(output_path: str) -> None:
    with contextlib.suppress(OSError):
        Path(output_path).unlink()


def _valid_audio_file(output_path: str) -> bool:
    path = Path(output_path)
    return path.is_file() and path.stat().st_size >= TTS_MIN_AUDIO_BYTES


async def _synth_edge_once(text: str, voice: str, speed: float, output_path: str) -> bool:
    try:
        import edge_tts  # type: ignore
    except ImportError:
        return False
    _remove_audio_file(output_path)
    rate = int(round((speed - 1.0) * 100))
    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=f"{rate:+d}%",
        volume="+0%",
        pitch="+0Hz",
    )
    await communicator.save(output_path)
    if not _valid_audio_file(output_path):
        _remove_audio_file(output_path)
        raise RuntimeError("합성 결과가 비어 있거나 너무 작습니다.")
    return True


async def _synth_edge(text: str, voice: str, speed: float, output_path: str) -> Optional[str]:
    """Try Edge voices safely and quarantine repeatedly failing individual voices."""
    now = time.monotonic()
    EDGE_TTS_RUNTIME["last_requested_voice"] = voice
    if now < float(EDGE_TTS_RUNTIME.get("backoff_until", 0.0) or 0.0):
        remaining = int(float(EDGE_TTS_RUNTIME["backoff_until"]) - now)
        print(f"[TTS Edge 일시 우회] 외부 합성 백오프 {max(1, remaining)}초 남음", flush=True)
        return None

    candidates: List[str] = []
    for candidate in (voice, *EDGE_STABLE_FALLBACK_VOICES):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    failures_by_voice = EDGE_TTS_RUNTIME.setdefault("voice_failures", {})
    backoff_by_voice = EDGE_TTS_RUNTIME.setdefault("voice_backoff_until", {})
    last_error = ""
    attempted_any = False
    for candidate_index, candidate in enumerate(candidates):
        remaining = _edge_voice_quarantine_remaining(candidate)
        if remaining > 0:
            label = EDGE_VOICE_TO_NAME.get(candidate, candidate)
            print(f"[TTS Edge 음성 격리] voice={label} skip={remaining}s", flush=True)
            continue
        attempted_any = True
        delays = EDGE_RETRY_DELAYS if candidate_index == 0 else (0.0,)
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                if await _synth_edge_once(text, candidate, speed, output_path):
                    failures_by_voice[candidate] = 0
                    backoff_by_voice.pop(candidate, None)
                    EDGE_TTS_RUNTIME.update({
                        "backoff_until": 0.0,
                        "consecutive_failures": 0,
                        "last_error": "",
                        "last_success_at": int(time.time()),
                        "last_voice": candidate,
                        "last_used_voice": candidate,
                    })
                    if candidate != voice:
                        print(f"[TTS Edge 대체 음성] requested={voice} used={candidate}", flush=True)
                    return candidate
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                count = int(failures_by_voice.get(candidate, 0) or 0) + 1
                failures_by_voice[candidate] = count
                if count >= EDGE_VOICE_FAILURE_THRESHOLD:
                    backoff_by_voice[candidate] = time.monotonic() + EDGE_VOICE_QUARANTINE_SECONDS
                print(
                    f"[TTS Edge 합성 실패] voice={candidate} attempt={attempt}/{len(delays)} "
                    f"failures={count} {last_error}",
                    flush=True,
                )

    failures = int(EDGE_TTS_RUNTIME.get("consecutive_failures", 0) or 0) + 1
    backoff = min(600, EDGE_FAILURE_BACKOFF_SECONDS * failures) if attempted_any else 60
    EDGE_TTS_RUNTIME.update({
        "backoff_until": time.monotonic() + backoff,
        "consecutive_failures": failures,
        "last_error": last_error or "사용 가능한 Edge 음성이 모두 임시 격리됨",
    })
    _remove_audio_file(output_path)
    print(f"[TTS Edge 우회 전환] Google 대체 합성 사용 · {backoff}초 백오프", flush=True)
    return None


async def _synth_google(text: str, speed: float, output_path: str) -> None:
    params = {
        "ie": "UTF-8",
        "client": "tw-ob",
        "tl": "ko",
        "q": text,
        "ttsspeed": "0.24" if speed < 0.9 else "1",
    }
    url = "https://translate.google.com/translate_tts?" + urlencode(params)
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": "Mozilla/5.0 ABADDON-TTS/6.0.0"}
    _remove_audio_file(output_path)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"TTS HTTP {response.status}")
            content_type = response.headers.get("Content-Type", "").lower()
            data = await response.read()
    if len(data) < TTS_MIN_AUDIO_BYTES:
        raise RuntimeError("Google TTS 음성 데이터가 비어 있거나 너무 작습니다.")
    if content_type and "audio" not in content_type and "octet-stream" not in content_type:
        raise RuntimeError(f"Google TTS 응답 형식 오류: {content_type[:80]}")
    await asyncio.to_thread(Path(output_path).write_bytes, data)
    if not _valid_audio_file(output_path):
        _remove_audio_file(output_path)
        raise RuntimeError("Google TTS 파일 검증에 실패했습니다.")


async def _synthesise(text: str, voice_key: str, speed: float, output_path: str, engine: str = "auto") -> str:
    engine = engine if engine in {"auto", "edge", "google"} else "auto"
    cache = _cache_path(text, voice_key, speed, engine)
    if _valid_audio_file(str(cache)) and time.time() - cache.stat().st_mtime <= TTS_CACHE_TTL:
        await asyncio.to_thread(shutil.copyfile, cache, output_path)
        return f"cache:{engine}"
    preset = VOICE_PRESETS.get(voice_key, VOICE_PRESETS["선히"])
    provider = ""
    if engine in {"auto", "edge"}:
        used_voice = await _synth_edge(text, preset["edge"], speed, output_path)
        if used_voice:
            provider = f"edge-tts:{used_voice}"
        elif engine == "edge":
            raise RuntimeError("Edge 전용 모드에서 음성 합성에 실패했습니다.")
    if not provider:
        await _synth_google(text, speed, output_path)
        provider = "google" if engine == "google" else "google-fallback"
    if _valid_audio_file(output_path):
        with contextlib.suppress(OSError):
            await asyncio.to_thread(shutil.copyfile, output_path, cache)
            await asyncio.to_thread(_prune_cache)
    return provider


async def _ensure_voice_connection(
    bot: commands.Bot,
    guild: discord.Guild,
    channel_id: Optional[int],
) -> Tuple[Optional[discord.VoiceClient], Optional[str]]:
    if not channel_id:
        return None, "음성 채널이 설정되지 않았습니다. 음성 채널에 들어간 뒤 `!음성입장`을 사용하세요."
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.VoiceChannel):
        return None, "설정된 음성 채널을 찾지 못했습니다."
    has_nacl, has_davey, _ = _dependency_state()
    if not has_nacl:
        return None, (
            "PyNaCl을 실제 실행 환경에서 불러오지 못했습니다. "
            "Render Build Command가 `pip install --upgrade pip && pip install -r requirements.txt`인지 확인하고 "
            "`Clear build cache & deploy`를 실행한 뒤 `!TTS 진단`으로 재확인하세요."
        )
    if not has_davey:
        return None, (
            "discord.py 2.7 음성 연결에 필요한 `davey`가 설치되지 않았습니다. "
            "v5.0.4 requirements.txt를 반영하고 Render에서 `Clear build cache & deploy`를 실행하세요."
        )
    me = guild.me
    if me is not None:
        permissions = channel.permissions_for(me)
        if not permissions.connect or not permissions.speak:
            return None, "봇에 해당 음성 채널의 `연결`과 `말하기` 권한이 필요합니다."
    voice = guild.voice_client
    try:
        if voice is None:
            voice = await channel.connect(self_deaf=True)
        elif voice.channel.id != channel.id:
            await voice.move_to(channel)
    except RuntimeError as exc:
        return None, f"음성 런타임 오류: {type(exc).__name__}: {str(exc)[:220]}"
    except (discord.ClientException, discord.Forbidden, discord.HTTPException) as exc:
        return None, f"음성 연결 실패: {type(exc).__name__}: {str(exc)[:180]}"
    return voice, None


async def _play_file(voice: discord.VoiceClient, path: str, volume: float) -> None:
    loop = asyncio.get_running_loop()
    finished: asyncio.Future[None] = loop.create_future()

    def after(error: Optional[Exception]) -> None:
        def resolve() -> None:
            if finished.done():
                return
            if error is not None:
                finished.set_exception(error)
            else:
                finished.set_result(None)
        loop.call_soon_threadsafe(resolve)

    source = discord.FFmpegPCMAudio(path, options="-vn")
    transformed = discord.PCMVolumeTransformer(source, volume=max(0.1, min(2.0, volume)))
    voice.play(transformed, after=after)
    await finished


def register_v433_voice_sanctuary(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    save_data,
) -> None:
    _install_renewal_429_handler()

    async def require_guild(ctx: commands.Context) -> Optional[discord.Guild]:
        if ctx.guild is None:
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return None
        return ctx.guild

    async def require_admin(ctx: commands.Context) -> Optional[discord.Guild]:
        guild = await require_guild(ctx)
        if guild is None:
            return None
        if not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ 서버 관리자만 사용할 수 있습니다.")
            return None
        return guild

    async def enqueue_tts(
        guild: discord.Guild,
        author: discord.Member,
        text: str,
        *,
        announce_name: bool,
        voice_key: Optional[str] = None,
        target_voice_channel_id: Optional[int] = None,
    ) -> Tuple[bool, str]:
        settings = _layout_settings(world_data, guild.id)["tts"]
        clean = _clean_spoken_text(text)
        if not clean:
            return False, "읽을 수 있는 내용이 없습니다."
        queue = VOICE_RUNTIME.queue_for(guild.id)
        chunks = _split_spoken_text(clean)
        if queue.qsize() + len(chunks) > TTS_QUEUE_LIMIT:
            return False, f"대기열 공간이 부족합니다. 현재 {queue.qsize()}/{TTS_QUEUE_LIMIT}개입니다."
        spoken = clean
        resolved_voice = _voice_name_or_default(voice_key, _personal_voice(settings, author.id))
        resolved_channel_id = int(target_voice_channel_id or settings.get("voice_channel_id") or 0)
        if not resolved_channel_id:
            return False, "입장할 음성 채널을 찾지 못했습니다."
        for index, chunk in enumerate(chunks, start=1):
            await queue.put({
                "text": chunk,
                "author_id": author.id,
                "voice": resolved_voice,
                "voice_channel_id": resolved_channel_id,
                "queued_at": time.time(),
                "chunk_index": index,
                "chunk_total": len(chunks),
            })
        task = VOICE_RUNTIME.workers.get(guild.id)
        if task is None or task.done():
            VOICE_RUNTIME.workers[guild.id] = asyncio.create_task(tts_worker(guild.id))
        suffix = f" · 긴 문장 {len(chunks)}조각" if len(chunks) > 1 else ""
        return True, f"대기열에 추가했습니다{suffix}. 현재 **{queue.qsize()}/{TTS_QUEUE_LIMIT}**"

    async def tts_worker(guild_id: int) -> None:
        queue = VOICE_RUNTIME.queue_for(guild_id)
        while True:
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            settings = _layout_settings(world_data, guild_id)["tts"]
            idle_seconds = max(120, min(3600, int(settings.get("idle_seconds", DEFAULT_IDLE_SECONDS))))
            try:
                item = await asyncio.wait_for(queue.get(), timeout=idle_seconds)
            except asyncio.TimeoutError:
                voice = guild.voice_client
                if voice is not None and voice.is_connected():
                    with contextlib.suppress(discord.ClientException, discord.HTTPException):
                        await voice.disconnect(force=False)
                VOICE_RUNTIME.active_channel_ids.pop(guild_id, None)
                return

            temp_path = ""
            try:
                voice, error = await _ensure_voice_connection(bot, guild, item.get("voice_channel_id"))
                if voice is None:
                    print(f"[TTS 연결 실패] guild={guild_id} error={error}", flush=True)
                    continue
                VOICE_RUNTIME.active_channel_ids[guild_id] = int(item.get("voice_channel_id") or 0)
                fd, temp_path = tempfile.mkstemp(prefix="abaddon_tts_", suffix=".mp3")
                os.close(fd)
                VOICE_RUNTIME.speaking[guild_id] = True
                VOICE_RUNTIME.last_text[guild_id] = str(item["text"])[:80]
                provider = await _synthesise(
                    str(item["text"]),
                    _voice_name_or_default(item.get("voice"), _voice_name_or_default(settings.get("voice"))),
                    float(settings.get("speed", 1.0)),
                    temp_path,
                    str(settings.get("engine", "auto")),
                )
                if provider.startswith("cache:"):
                    VOICE_RUNTIME.cache_hits[guild_id] = VOICE_RUNTIME.cache_hits.get(guild_id, 0) + 1
                if not _valid_audio_file(temp_path):
                    raise RuntimeError("재생 직전 TTS 음성 파일 검증에 실패했습니다.")
                print(
                    f"[TTS 합성 완료] guild={guild_id} provider={provider} bytes={Path(temp_path).stat().st_size}",
                    flush=True,
                )
                await _play_file(voice, temp_path, float(settings.get("volume", 1.0)))
                settings["last_provider"] = provider
                settings["last_played_at"] = int(time.time())
            except Exception as exc:
                print(f"[TTS 재생 오류] guild={guild_id} {type(exc).__name__}: {exc}", flush=True)
            finally:
                VOICE_RUNTIME.speaking[guild_id] = False
                queue.task_done()
                if temp_path:
                    with contextlib.suppress(OSError):
                        os.remove(temp_path)

    @bot.group(name="TTS", aliases=["티티에스", "음성성역"], invoke_without_command=True, case_insensitive=True)
    async def tts_group(ctx: commands.Context):
        guild = await require_guild(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        queue = VOICE_RUNTIME.queue_for(guild.id)
        embed = discord.Embed(
            title="🔊 ABADDON 음성 성역",
            description=(
                "텍스트를 음성 채널에서 읽고, 지정한 채팅 채널의 메시지를 자동 낭독합니다.\n\n"
                "`!음성입장` · `!말해 내용` · `!음성퇴장`\n"
                "`!TTS채널` · `!TTS 켜기` · `!TTS 끄기`\n"
                "`/tts 목소리` · `/tts 내설정` · `!TTS엔진 자동` · `!TTS 진단`"
            ),
            color=0x6D2335,
        )
        embed.add_field(name="자동 낭독", value="켜짐" if settings.get("enabled") else "꺼짐", inline=True)
        embed.add_field(name="대기열", value=f"{queue.qsize()}/{TTS_QUEUE_LIMIT}", inline=True)
        embed.add_field(name="서버 기본 목소리", value=str(settings.get("voice", "선히")), inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="음성입장", aliases=["보이스입장"])
    async def voice_join(ctx: commands.Context):
        guild = await require_guild(ctx)
        if guild is None or not isinstance(ctx.author, discord.Member):
            return
        if not ctx.author.voice or not isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            await ctx.send("❌ 먼저 음성 채널에 들어가 주세요.")
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["voice_channel_id"] = ctx.author.voice.channel.id
        voice, error = await _ensure_voice_connection(bot, guild, ctx.author.voice.channel.id)
        if voice is None:
            await ctx.send(f"❌ {error}")
            return
        save_data()
        await ctx.send(f"🔊 {ctx.author.voice.channel.mention}에 입장했습니다.")

    @bot.command(name="음성퇴장", aliases=["보이스퇴장"])
    async def voice_leave(ctx: commands.Context):
        guild = await require_guild(ctx)
        if guild is None:
            return
        voice = guild.voice_client
        if voice is None:
            await ctx.send("⚠️ 현재 음성 채널에 연결되어 있지 않습니다.")
            return
        VOICE_RUNTIME.clear(guild.id)
        await voice.disconnect(force=False)
        await ctx.send("🔇 음성 성역에서 퇴장했습니다.")

    @bot.command(name="말해", aliases=["읽어", "say"])
    async def voice_say(ctx: commands.Context, *, text: str):
        guild = await require_guild(ctx)
        if guild is None or not isinstance(ctx.author, discord.Member):
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        if not ctx.author.voice or not isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            await ctx.send("❌ 먼저 음성 채널에 들어가 주세요.")
            return
        voice_channel_id = ctx.author.voice.channel.id
        now = time.monotonic()
        key = (guild.id, ctx.author.id)
        remaining = TTS_USER_COOLDOWN - (now - VOICE_RUNTIME.user_cooldowns.get(key, 0.0))
        if remaining > 0:
            await ctx.send(f"⏳ TTS 쿨다운 **{remaining:.1f}초**가 남았습니다.", delete_after=5)
            return
        VOICE_RUNTIME.user_cooldowns[key] = now
        ok, message = await enqueue_tts(
            guild,
            ctx.author,
            text,
            announce_name=False,
            target_voice_channel_id=voice_channel_id,
        )
        await ctx.send(("✅ " if ok else "❌ ") + message, delete_after=8)

    async def configure_tts_text_channel(
        ctx: commands.Context,
        text_channel: discord.TextChannel,
        *,
        enable: bool = True,
    ) -> None:
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["text_channel_id"] = text_channel.id
        settings["enabled"] = bool(enable)
        settings["auto_join"] = True
        settings["require_author_in_voice"] = True
        settings["mode"] = "author_voice"
        save_data()
        state = "켜짐" if enable else "꺼짐"
        await ctx.send(
            "✅ TTS 채팅 채널을 저장했습니다.\n"
            f"채팅: {text_channel.mention}\n"
            f"자동 낭독: **{state}**\n\n"
            "이 채널에서 메시지를 쓴 사용자가 들어가 있는 음성방을 자동으로 찾아 입장합니다."
        )

    @tts_group.command(name="채널", aliases=["채널설정", "자동채널", "setchannel"])
    async def tts_channel_setup(ctx: commands.Context, text_channel: Optional[discord.TextChannel] = None):
        target = text_channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("❌ TTS 채팅 채널에서 실행하거나 채널을 지정해 주세요.")
            return
        await configure_tts_text_channel(ctx, target, enable=True)

    @bot.command(name="TTS채널", aliases=["채널설정", "TTS채널설정"])
    async def tts_channel_setup_shortcut(ctx: commands.Context, text_channel: Optional[discord.TextChannel] = None):
        target = text_channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("❌ TTS 채팅 채널에서 실행하거나 채널을 지정해 주세요.")
            return
        await configure_tts_text_channel(ctx, target, enable=True)

    @tts_group.command(name="켜기", aliases=["on"])
    async def tts_enable(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        if isinstance(ctx.channel, discord.TextChannel) and not settings.get("text_channel_id"):
            settings["text_channel_id"] = ctx.channel.id
        if not settings.get("text_channel_id"):
            await ctx.send("❌ TTS 채팅 채널에서 `!TTS채널` 또는 `/tts 채널`을 먼저 실행하세요.")
            return
        settings["enabled"] = True
        settings["auto_join"] = True
        settings["require_author_in_voice"] = True
        settings["mode"] = "author_voice"
        save_data()
        text_channel = guild.get_channel(int(settings["text_channel_id"]))
        await ctx.send(
            "✅ 자동 TTS를 켰습니다.\n"
            f"채팅: {getattr(text_channel, 'mention', '미설정')}\n"
            "메시지 작성자가 들어가 있는 음성방으로 자동 입장합니다."
        )

    @tts_group.command(name="끄기", aliases=["off"])
    async def tts_disable(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["enabled"] = False
        removed = VOICE_RUNTIME.clear(guild.id)
        save_data()
        await ctx.send(f"✅ 자동 TTS를 껐습니다. 대기 메시지 **{removed}개**를 비웠습니다.")

    @tts_group.command(name="음성채널", aliases=["보이스채널"])
    async def tts_voice_channel(ctx: commands.Context, channel: discord.VoiceChannel):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["voice_channel_id"] = channel.id
        settings["auto_join"] = True
        settings["mode"] = "fixed"
        settings["require_author_in_voice"] = False
        save_data()
        await ctx.send(f"✅ 고정 음성방 모드를 켰습니다: {channel.mention}\n자동 감지로 복귀: TTS 채팅방에서 `!TTS채널`")

    @tts_group.command(name="목소리", aliases=["음성"])
    async def tts_voice(ctx: commands.Context, voice_name: Optional[str] = None):
        guild = await require_guild(ctx)
        if guild is None or not isinstance(ctx.author, discord.Member):
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        if voice_name is None:
            lines = [f"• **{name}** — {data['label']}" for name, data in VOICE_PRESETS.items()]
            current = _personal_voice(settings, ctx.author.id)
            await ctx.send(
                "🔊 **사용 가능한 한국어 목소리 10종**\n"
                + "\n".join(lines)
                + f"\n\n내 목소리: **{current}**\n설정: `!TTS 목소리 선히` 또는 `/tts 목소리`"
            )
            return
        voice_name = voice_name.strip()
        if voice_name.casefold() in {"기본", "초기화", "default", "reset"}:
            settings.setdefault("user_voices", {}).pop(str(ctx.author.id), None)
            save_data()
            await ctx.send(f"✅ 개인 목소리 설정을 지웠습니다. 이제 서버 기본 **{settings.get('voice', '선히')}**을 사용합니다.")
            return
        if voice_name not in VOICE_PRESETS:
            await ctx.send("❌ 지원하지 않는 목소리입니다. `!TTS 목소리`로 목록을 확인하세요.")
            return
        settings.setdefault("user_voices", {})[str(ctx.author.id)] = voice_name
        save_data()
        await ctx.send(f"✅ 앞으로 {ctx.author.mention}님의 메시지는 **{voice_name}** 목소리로 읽습니다.")

    @tts_group.command(name="기본목소리", aliases=["서버목소리", "defaultvoice"])
    async def tts_default_voice(ctx: commands.Context, voice_name: Optional[str] = None):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        if voice_name is None:
            await ctx.send(
                f"🔊 서버 기본 목소리: **{settings.get('voice', '선히')}**\n"
                "변경: `!TTS 기본목소리 선히`"
            )
            return
        voice_name = voice_name.strip()
        if voice_name not in VOICE_PRESETS:
            await ctx.send("❌ 지원하지 않는 목소리입니다. `!TTS 목소리`로 목록을 확인하세요.")
            return
        settings["voice"] = voice_name
        save_data()
        await ctx.send(f"✅ 개인 설정이 없는 사용자의 기본 목소리를 **{voice_name}**으로 변경했습니다.")

    @tts_group.command(name="엔진", aliases=["provider"])
    async def tts_engine(ctx: commands.Context, engine: Optional[str] = None):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        labels = {"auto": "자동 (Edge 실패 시 Google)", "edge": "Edge 전용", "google": "Google 전용"}
        if engine is None:
            await ctx.send(f"🎙️ 현재 TTS 엔진: **{labels.get(settings.get('engine', 'auto'), '자동')}**\n변경: `!TTS엔진 자동`, `!TTS엔진 edge`, `!TTS엔진 google`")
            return
        normalized = {"자동": "auto", "auto": "auto", "엣지": "edge", "edge": "edge", "구글": "google", "google": "google"}.get(engine.casefold())
        if normalized is None:
            await ctx.send("❌ 엔진은 `자동`, `edge`, `google` 중 하나를 선택하세요.")
            return
        settings["engine"] = normalized
        save_data()
        await ctx.send(f"✅ TTS 엔진을 **{labels[normalized]}**으로 설정했습니다.")

    @bot.command(name="TTS엔진")
    async def tts_engine_shortcut(ctx: commands.Context, engine: Optional[str] = None):
        await ctx.invoke(tts_engine, engine=engine)

    @tts_group.command(name="음성격리초기화", aliases=["음성복구", "voice-reset"])
    async def tts_voice_quarantine_reset(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        EDGE_TTS_RUNTIME.setdefault("voice_failures", {}).clear()
        EDGE_TTS_RUNTIME.setdefault("voice_backoff_until", {}).clear()
        EDGE_TTS_RUNTIME["backoff_until"] = 0.0
        EDGE_TTS_RUNTIME["consecutive_failures"] = 0
        EDGE_TTS_RUNTIME["last_error"] = ""
        await ctx.send("✅ Edge 목소리별 임시 격리와 전체 백오프를 초기화했습니다. 다음 낭독부터 다시 시험합니다.")

    @tts_group.command(name="속도")
    async def tts_speed(ctx: commands.Context, speed: float):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if not 0.7 <= speed <= 1.5:
            await ctx.send("❌ 속도는 `0.7`부터 `1.5` 사이로 입력하세요.")
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["speed"] = round(speed, 2)
        save_data()
        await ctx.send(f"✅ TTS 속도를 **{speed:.2f}배**로 설정했습니다.")

    @tts_group.command(name="볼륨")
    async def tts_volume(ctx: commands.Context, volume: int):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if not 10 <= volume <= 200:
            await ctx.send("❌ 볼륨은 `10`부터 `200` 사이로 입력하세요.")
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["volume"] = round(volume / 100, 2)
        save_data()
        await ctx.send(f"✅ TTS 볼륨을 **{volume}%**로 설정했습니다.")

    @tts_group.command(name="대기열", aliases=["queue"])
    async def tts_queue(ctx: commands.Context):
        guild = await require_guild(ctx)
        if guild is None:
            return
        queue = VOICE_RUNTIME.queue_for(guild.id)
        speaking = "말하는 중" if VOICE_RUNTIME.speaking.get(guild.id) else "대기"
        await ctx.send(f"🔊 TTS 상태: **{speaking}** · 대기열 **{queue.qsize()}/{TTS_QUEUE_LIMIT}개** · 캐시 적중 **{VOICE_RUNTIME.cache_hits.get(guild.id, 0)}회**")

    @tts_group.command(name="비우기", aliases=["clear"])
    async def tts_clear(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        removed = VOICE_RUNTIME.clear(guild.id)
        if guild.voice_client and guild.voice_client.is_playing():
            guild.voice_client.stop()
        await ctx.send(f"✅ TTS 대기열 **{removed}개**를 비웠습니다.")

    @tts_group.command(name="진단", aliases=["diagnose", "검사"])
    async def tts_diagnose(ctx: commands.Context):
        guild = await require_guild(ctx)
        if guild is None:
            return
        has_nacl, has_davey, has_edge = _dependency_state()
        embed = discord.Embed(title="🩺 TTS 실행 환경 진단", color=0x6D2335)
        embed.description = "\n".join(_tts_diagnostic_lines())
        if not has_nacl or not has_davey:
            embed.add_field(
                name="Render 조치",
                value=(
                    "1. Build Command를 `pip install --upgrade pip && pip install -r requirements.txt`로 확인\n"
                    "2. `discord.py==2.7.1`, `PyNaCl==1.6.2`, `davey==0.1.6` 확인\n"
                    "3. Manual Deploy → Clear build cache & deploy"
                ),
                inline=False,
            )
        elif not has_edge:
            embed.add_field(name="안내", value="edge-tts가 없어 Google 대체 음성을 사용합니다.", inline=False)
        else:
            embed.add_field(name="결과", value="필수 음성 패키지가 정상적으로 감지됐습니다. 외부 Edge 합성 연결은 실제 낭독 때 별도로 확인됩니다.", inline=False)
        await ctx.send(embed=embed)

    @tts_group.command(name="상태", aliases=["status"])
    async def tts_status(ctx: commands.Context):
        guild = await require_guild(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        text_channel = guild.get_channel(settings.get("text_channel_id") or 0)
        voice_channel = guild.get_channel(settings.get("voice_channel_id") or 0)
        has_nacl, has_davey, has_edge = _dependency_state()
        embed = discord.Embed(title="🔊 TTS 음성 성역 상태", color=0x6D2335)
        embed.add_field(name="자동 낭독", value="켜짐" if settings.get("enabled") else "꺼짐", inline=True)
        embed.add_field(name="음성 연결", value="연결됨" if guild.voice_client else "연결 안 됨", inline=True)
        embed.add_field(name="대기열", value=f"{VOICE_RUNTIME.queue_for(guild.id).qsize()}/{TTS_QUEUE_LIMIT}", inline=True)
        embed.add_field(name="텍스트 채널", value=getattr(text_channel, "mention", "미설정"), inline=True)
        embed.add_field(name="음성 대상", value=("작성자 음성방 자동 감지" if settings.get("mode") == "author_voice" else getattr(voice_channel, "mention", "미설정")), inline=True)
        embed.add_field(name="자동 입장", value="켜짐" if settings.get("auto_join", True) else "꺼짐", inline=True)
        engine_labels = {"auto": "자동", "edge": "Edge", "google": "Google"}
        embed.add_field(name="TTS 엔진", value=engine_labels.get(settings.get("engine", "auto"), "자동"), inline=True)
        embed.add_field(name="재생 상태", value="말하는 중" if VOICE_RUNTIME.speaking.get(guild.id) else "대기", inline=True)
        embed.add_field(name="캐시", value=f"적중 {VOICE_RUNTIME.cache_hits.get(guild.id, 0)}회", inline=True)
        embed.add_field(name="목소리", value=f"{settings.get('voice', '선히')} · {settings.get('speed', 1.0)}배 · {int(float(settings.get('volume', 1.0))*100)}%", inline=True)
        embed.add_field(
            name="음성 의존성",
            value=f"PyNaCl: {'✅' if has_nacl else '❌'}\ndavey: {'✅' if has_davey else '❌'}\nedge-tts: {'✅' if has_edge else '대체 음성 사용'}",
            inline=False,
        )
        last_provider = str(settings.get("last_provider") or "아직 재생 기록 없음")
        backoff_remaining = max(0, int(float(EDGE_TTS_RUNTIME.get("backoff_until", 0.0) or 0.0) - time.monotonic()))
        provider_value = last_provider
        if backoff_remaining:
            provider_value += f"\nEdge 외부 합성 우회: 약 {backoff_remaining}초 남음"
        embed.add_field(name="최근 합성 경로", value=provider_value[:1024], inline=False)
        requested_voice = str(EDGE_TTS_RUNTIME.get("last_requested_voice") or "")
        used_voice = str(EDGE_TTS_RUNTIME.get("last_used_voice") or "")
        if requested_voice and used_voice and requested_voice != used_voice:
            embed.add_field(
                name="최근 음성 자동 우회",
                value=f"{EDGE_VOICE_TO_NAME.get(requested_voice, requested_voice)} → {EDGE_VOICE_TO_NAME.get(used_voice, used_voice)}",
                inline=False,
            )
        quarantined: List[str] = []
        for edge_voice, display_name in EDGE_VOICE_TO_NAME.items():
            remaining = _edge_voice_quarantine_remaining(edge_voice)
            if remaining > 0:
                quarantined.append(f"{display_name} · 약 {remaining // 60 + 1}분")
        if quarantined:
            embed.add_field(
                name="Edge 임시 격리 음성",
                value="\n".join(quarantined[:10]) + "\n초기화: `!TTS 음성격리초기화`",
                inline=False,
            )
        await ctx.send(embed=embed)

    # Discord 슬래시 명령어: 일반 사용자는 개인 목소리/미리듣기, 관리자는 서버 설정을 변경합니다.
    tts_slash = app_commands.Group(name="tts", description="TTS 목소리와 자동 낭독 설정을 관리합니다.")

    async def slash_guild_member(interaction: discord.Interaction) -> Tuple[Optional[discord.Guild], Optional[discord.Member]]:
        guild = interaction.guild
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or member is None:
            if interaction.response.is_done():
                await interaction.followup.send("❌ 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return None, None
        return guild, member

    async def slash_require_admin(interaction: discord.Interaction) -> Tuple[Optional[discord.Guild], Optional[discord.Member]]:
        guild, member = await slash_guild_member(interaction)
        if guild is None or member is None:
            return None, None
        if not (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
            if interaction.response.is_done():
                await interaction.followup.send("❌ 서버 관리자만 사용할 수 있습니다.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 서버 관리자만 사용할 수 있습니다.", ephemeral=True)
            return None, None
        return guild, member

    @tts_slash.command(name="목소리", description="내 TTS 목소리를 드롭다운에서 선택합니다.")
    @app_commands.describe(voice="내 메시지를 읽을 목소리")
    @app_commands.choices(voice=VOICE_APP_CHOICES)
    async def slash_tts_voice(interaction: discord.Interaction, voice: app_commands.Choice[str]):
        guild, member = await slash_guild_member(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings.setdefault("user_voices", {})[str(member.id)] = voice.value
        save_data()
        await interaction.response.send_message(
            f"✅ 내 TTS 목소리를 **{voice.value}**으로 저장했습니다.\n{VOICE_PRESETS[voice.value]['label']}",
            ephemeral=True,
        )

    @tts_slash.command(name="내설정", description="내 TTS 목소리와 서버 기본 설정을 확인합니다.")
    async def slash_tts_my_settings(interaction: discord.Interaction):
        guild, member = await slash_guild_member(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        personal = _personal_voice(settings, member.id)
        inherited = str(member.id) not in settings.get("user_voices", {})
        await interaction.response.send_message(
            "🔊 **내 TTS 설정**\n"
            f"• 목소리: **{personal}**{' (서버 기본값)' if inherited else ''}\n"
            f"• 설명: {VOICE_PRESETS[personal]['label']}\n"
            f"• 서버 속도: {settings.get('speed', 1.0)}배",
            ephemeral=True,
        )

    @tts_slash.command(name="초기화", description="내 개인 목소리 설정을 지우고 서버 기본값을 사용합니다.")
    async def slash_tts_reset(interaction: discord.Interaction):
        guild, member = await slash_guild_member(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings.setdefault("user_voices", {}).pop(str(member.id), None)
        save_data()
        await interaction.response.send_message(
            f"✅ 개인 목소리 설정을 초기화했습니다. 서버 기본 **{settings.get('voice', '선히')}**을 사용합니다.",
            ephemeral=True,
        )

    @tts_slash.command(name="미리듣기", description="선택한 목소리를 지정 음성 채널에서 시험 재생합니다.")
    @app_commands.describe(voice="미리 들을 목소리")
    @app_commands.choices(voice=VOICE_APP_CHOICES)
    async def slash_tts_preview(interaction: discord.Interaction, voice: app_commands.Choice[str]):
        guild, member = await slash_guild_member(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        if not member.voice or not isinstance(member.voice.channel, discord.VoiceChannel):
            await interaction.response.send_message("❌ 목소리 미리듣기는 먼저 음성 채널에 들어가 주세요.", ephemeral=True)
            return
        preview_voice_channel_id = member.voice.channel.id
        now = time.monotonic()
        key = (guild.id, member.id)
        remaining = TTS_USER_COOLDOWN - (now - VOICE_RUNTIME.user_cooldowns.get(key, 0.0))
        if remaining > 0:
            await interaction.response.send_message(f"⏳ {remaining:.1f}초 뒤에 다시 시도하세요.", ephemeral=True)
            return
        VOICE_RUNTIME.user_cooldowns[key] = now
        ok, message = await enqueue_tts(
            guild,
            member,
            f"{voice.value} 목소리 미리 듣기입니다. 검은 성역에 오신 것을 환영합니다.",
            announce_name=False,
            voice_key=voice.value,
            target_voice_channel_id=preview_voice_channel_id,
        )
        await interaction.response.send_message(("✅ " if ok else "❌ ") + message, ephemeral=True)

    @tts_slash.command(name="기본목소리", description="개인 설정이 없는 사용자의 서버 기본 목소리를 정합니다.")
    @app_commands.describe(voice="서버 기본 목소리")
    @app_commands.choices(voice=VOICE_APP_CHOICES)
    async def slash_tts_default_voice(interaction: discord.Interaction, voice: app_commands.Choice[str]):
        guild, member = await slash_require_admin(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["voice"] = voice.value
        save_data()
        await interaction.response.send_message(f"✅ 서버 기본 TTS 목소리를 **{voice.value}**으로 변경했습니다.", ephemeral=True)

    ENGINE_CHOICES = [
        app_commands.Choice(name="자동 · Edge 실패 시 Google", value="auto"),
        app_commands.Choice(name="Edge 전용", value="edge"),
        app_commands.Choice(name="Google 전용", value="google"),
    ]

    @tts_slash.command(name="엔진", description="서버 TTS 합성 엔진을 선택합니다.")
    @app_commands.describe(engine="사용할 TTS 엔진")
    @app_commands.choices(engine=ENGINE_CHOICES)
    async def slash_tts_engine(interaction: discord.Interaction, engine: app_commands.Choice[str]):
        guild, member = await slash_require_admin(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["engine"] = engine.value
        save_data()
        await interaction.response.send_message(f"✅ TTS 엔진을 **{engine.name}**으로 설정했습니다.", ephemeral=True)

    @tts_slash.command(name="채널", description="현재 채널을 TTS 채팅 채널로 지정합니다.")
    @app_commands.describe(channel="다른 채널을 지정할 때만 선택")
    async def slash_tts_channel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        guild, member = await slash_require_admin(interaction)
        if guild is None or member is None:
            return
        target = channel or (interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None)
        if target is None:
            await interaction.response.send_message("❌ 텍스트 채널에서 실행하거나 채널을 선택해 주세요.", ephemeral=True)
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["text_channel_id"] = target.id
        settings["enabled"] = True
        settings["auto_join"] = True
        settings["require_author_in_voice"] = True
        settings["mode"] = "author_voice"
        save_data()
        await interaction.response.send_message(
            f"✅ TTS 채팅 채널: {target.mention}\n메시지 작성자의 현재 음성방을 자동 감지합니다.",
            ephemeral=True,
        )

    @tts_slash.command(name="켜기", description="저장된 채널에서 자동 TTS를 켭니다.")
    async def slash_tts_enable(interaction: discord.Interaction):
        guild, member = await slash_require_admin(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        if not settings.get("text_channel_id"):
            await interaction.response.send_message("❌ `/tts 채널`을 먼저 실행하세요.", ephemeral=True)
            return
        settings["enabled"] = True
        settings["mode"] = "author_voice"
        settings["require_author_in_voice"] = True
        save_data()
        await interaction.response.send_message("✅ 자동 TTS를 켰습니다. 작성자의 현재 음성방을 자동 감지합니다.", ephemeral=True)

    @tts_slash.command(name="끄기", description="자동 TTS를 끄고 대기열을 비웁니다.")
    async def slash_tts_disable(interaction: discord.Interaction):
        guild, member = await slash_require_admin(interaction)
        if guild is None or member is None:
            return
        settings = _layout_settings(world_data, guild.id)["tts"]
        settings["enabled"] = False
        removed = VOICE_RUNTIME.clear(guild.id)
        save_data()
        await interaction.response.send_message(f"✅ 자동 TTS를 끄고 대기 메시지 {removed}개를 비웠습니다.", ephemeral=True)

    if bot.tree.get_command("tts") is not None:
        raise RuntimeError("슬래시 명령어 충돌: /tts가 이미 등록되어 있습니다.")
    bot.tree.add_command(tts_slash)

    def build_recovery_plan(guild: discord.Guild, backup: Dict[str, Any]) -> Dict[str, Any]:
        category_map = {category.id: category for category in guild.categories}
        channel_map = {channel.id: channel for channel in [*guild.text_channels, *guild.voice_channels]}
        actions: List[Dict[str, Any]] = []

        for row in backup.get("categories", []):
            category = category_map.get(int(row.get("id", 0)))
            if category is None:
                continue
            original_name = str(row.get("name", category.name))
            if category.name != original_name:
                actions.append({"kind": "rename", "id": category.id, "name": original_name, "label": f"카테고리 이름 → {original_name}"})

        for row in backup.get("channels", []):
            channel = channel_map.get(int(row.get("id", 0)))
            if channel is None:
                continue
            original_name = str(row.get("name", channel.name))
            if channel.name != original_name:
                actions.append({"kind": "rename", "id": channel.id, "name": original_name, "label": f"채널 이름 → {original_name}"})
            original_parent = int(row.get("category_id")) if row.get("category_id") else None
            if channel.category_id != original_parent:
                parent = category_map.get(original_parent) if original_parent else None
                parent_label = parent.name if parent else "카테고리 없음"
                actions.append({"kind": "move", "id": channel.id, "parent_id": original_parent, "label": f"{channel.name} → {parent_label}"})

        return {
            "backup_id": str(backup.get("backup_id") or f"legacy-{backup.get('created_at', 0)}"),
            "backup_created_at": int(backup.get("created_at", 0) or 0),
            "created_at": int(time.time()),
            "cursor": 0,
            "actions": actions,
            "next_allowed_at": int(time.time()) + RENEWAL_PLAN_WARMUP,
            "status": "warming_up",
            "last_error": None,
        }

    def build_theme_plan(guild: discord.Guild, style: str, operation: str = "layout") -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        used_category_ids: set[int] = set()
        category_targets: Dict[str, Optional[int]] = {}

        if operation == "game_zone":
            text_matches, voices, _, _, _ = _detect_game_zone_channels(guild, style)
            category_names = _game_zone_category_names(style)
            required_names: List[str] = []
            for spec, channel in text_matches:
                if channel is not None and spec["category"] not in required_names:
                    required_names.append(spec["category"])
            if voices and category_names["voice"] not in required_names:
                required_names.append(category_names["voice"])
            for name in required_names:
                category = _find_semantic_category(guild, name, used_category_ids, family="game")
                if category is None:
                    actions.append({"kind": "create_category", "name": name, "label": f"카테고리 생성 → {name}"})
                    category_targets[name] = None
                else:
                    used_category_ids.add(category.id)
                    category_targets[name] = category.id
                    if category.name != name:
                        actions.append({"kind": "rename", "id": category.id, "name": name, "label": f"카테고리 이름 → {name}"})
            for spec, channel in text_matches:
                if channel is None:
                    continue
                if channel.name != spec["name"] or channel.category_id != category_targets.get(spec["category"]):
                    actions.append({"kind": "edit_channel", "id": channel.id, "name": spec["name"], "category_name": spec["category"], "label": f"{channel.name} → {spec['name']}"})
            voice_category = category_names["voice"]
            for index, channel in enumerate(voices):
                target_name = f"🔊・음성-{_roman_label(index)}"
                if channel.name != target_name or channel.category_id != category_targets.get(voice_category):
                    actions.append({"kind": "edit_channel", "id": channel.id, "name": target_name, "category_name": voice_category, "label": f"{channel.name} → {target_name}"})
            return actions

        text_matches, voice_matches = _detect_layout(guild, style)
        planned = [
            (spec, channel, "text") for spec, channel in text_matches
            if channel is not None or spec["key"] in ESSENTIAL_KEYS
        ] + [
            (spec, channel, "voice") for spec, channel in voice_matches
            if channel is not None or spec["key"] in ESSENTIAL_KEYS
        ]
        category_names: List[str] = []
        for spec, _, _ in planned:
            if spec["category"] not in category_names:
                category_names.append(spec["category"])
        for name in category_names:
            category = _find_semantic_category(guild, name, used_category_ids, family="layout")
            if category is None:
                admin_only = any(spec["category"] == name and spec["key"] in ADMIN_KEYS for spec, _, _ in planned)
                actions.append({"kind": "create_category", "name": name, "admin_only": admin_only, "label": f"카테고리 생성 → {name}"})
                category_targets[name] = None
            else:
                used_category_ids.add(category.id)
                category_targets[name] = category.id
                if category.name != name:
                    actions.append({"kind": "rename", "id": category.id, "name": name, "label": f"카테고리 이름 → {name}"})
        for spec, channel, channel_type in planned:
            if channel is None:
                actions.append({
                    "kind": "create_text" if channel_type == "text" else "create_voice",
                    "name": spec["name"],
                    "category_name": spec["category"],
                    "read_only": spec["key"] in READ_ONLY_KEYS,
                    "allow_reactions": spec["key"] == "roles",
                    "label": f"채널 생성 → {spec['name']}",
                })
            elif channel.name != spec["name"] or channel.category_id != category_targets.get(spec["category"]):
                actions.append({"kind": "edit_channel", "id": channel.id, "name": spec["name"], "category_name": spec["category"], "label": f"{channel.name} → {spec['name']}"})
        return actions

    def locate_category(guild: discord.Guild, category_name: str) -> Optional[discord.CategoryChannel]:
        return discord.utils.get(guild.categories, name=category_name)

    async def execute_renewal_action(ctx: commands.Context, guild: discord.Guild, action: Dict[str, Any], plan: Dict[str, Any]) -> None:
        bot_member = guild.me
        if bot_member is None:
            raise RuntimeError("봇 멤버 정보를 찾지 못했습니다.")
        reason = f"ABADDON v{VERSION} 단계별 서버 리뉴얼 / {ctx.author}"
        kind = str(action.get("kind"))
        if kind == "create_category":
            kwargs: Dict[str, Any] = {"reason": reason}
            if action.get("admin_only") and isinstance(ctx.author, discord.Member):
                kwargs["overwrites"] = _admin_category_overwrites(guild, ctx.author, bot_member)
            created = await guild.create_category(str(action["name"]), **kwargs)
            backup = _find_backup(_layout_settings(world_data, guild.id)["layout"], str(plan.get("backup_id")))
            if backup is not None:
                _record_created(backup, "category", created.id)
            return
        if kind in {"create_text", "create_voice"}:
            category = locate_category(guild, str(action.get("category_name")))
            if category is None:
                raise RuntimeError("대상 카테고리가 아직 생성되지 않았습니다. `다음`을 다시 실행하세요.")
            if kind == "create_text":
                kwargs = {"category": category, "reason": reason}
                if action.get("read_only") and isinstance(ctx.author, discord.Member):
                    kwargs["overwrites"] = _public_read_only_overwrites(guild, ctx.author, bot_member, bool(action.get("allow_reactions")))
                created = await guild.create_text_channel(str(action["name"]), **kwargs)
            else:
                created = await guild.create_voice_channel(str(action["name"]), category=category, reason=reason)
            backup = _find_backup(_layout_settings(world_data, guild.id)["layout"], str(plan.get("backup_id")))
            if backup is not None:
                _record_created(backup, "channel", created.id)
            return
        channel = guild.get_channel(int(action.get("id", 0)))
        if channel is None:
            raise LookupError("대상 채널이 없어 건너뜁니다.")
        if kind == "rename":
            await bot.http.edit_channel(channel.id, name=str(action.get("name", channel.name)), reason=reason)
            return
        if kind == "move":
            await bot.http.edit_channel(channel.id, parent_id=action.get("parent_id"), reason=reason)
            return
        if kind == "edit_channel":
            category = locate_category(guild, str(action.get("category_name")))
            if category is None:
                raise RuntimeError("대상 카테고리를 찾지 못했습니다.")
            await bot.http.edit_channel(channel.id, name=str(action.get("name", channel.name)), parent_id=category.id, reason=reason)
            return
        raise RuntimeError(f"알 수 없는 작업: {kind}")

    @bot.group(name="서버리뉴얼", aliases=["서버정리", "서버디자인"], invoke_without_command=True, case_insensitive=True)
    async def server_renewal(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        owner_id = ctx.author.id

        async def run_command(interaction: discord.Interaction, subcommand_name: str, *args: Any, **kwargs: Any) -> None:
            if interaction.user.id != owner_id:
                await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return
            command_obj = bot.get_command(f"서버리뉴얼 {subcommand_name}")
            if command_obj is None:
                await interaction.response.send_message(
                    f"❌ 서버 리뉴얼 하위 명령 `{subcommand_name}`을 찾지 못했습니다.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True)
            try:
                await command_obj.callback(ctx, *args, **kwargs)
                await interaction.followup.send("✅ 선택한 서버 리뉴얼 기능을 실행했습니다.", ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ 메뉴 실행 실패: `{type(exc).__name__}: {str(exc)[:180]}`",
                    ephemeral=True,
                )

        class ThemeSelect(discord.ui.Select):
            def __init__(self, mode: str) -> None:
                self.mode = mode
                options = [
                    discord.SelectOption(
                        label=f"{name} · {THEME_META[name]['label']}"[:100],
                        value=name,
                        emoji="🎨",
                    )
                    for name in STYLE_NAMES
                ]
                placeholder = "미리 볼 테마 선택" if "preview" in mode else "적용 계획을 만들 테마 선택"
                super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction) -> None:
                if interaction.user.id != owner_id:
                    await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                    return
                style = self.values[0]
                command_map = {
                    "layout_preview": "미리보기",
                    "layout_apply": "적용",
                    "game_preview": "게임미리보기",
                    "game_apply": "게임정리",
                }
                await run_command(interaction, command_map[self.mode], style)

        class ThemeView(discord.ui.View):
            def __init__(self, mode: str) -> None:
                super().__init__(timeout=300)
                self.add_item(ThemeSelect(mode))

        class RenewalMenu(discord.ui.Select):
            def __init__(self) -> None:
                options = [
                    discord.SelectOption(label="테마 미리보기", value="layout_preview", emoji="🔎", description="일반 서버 구조 변경 계획만 확인"),
                    discord.SelectOption(label="테마 적용 계획 만들기", value="layout_apply", emoji="🎨", description="백업 후 단계별 계획 생성"),
                    discord.SelectOption(label="게임·음성 구역 미리보기", value="game_preview", emoji="🎮", description="RPG·게임·음성 구역만 확인"),
                    discord.SelectOption(label="게임·음성 구역 계획 만들기", value="game_apply", emoji="🧭", description="게임 구역 단계별 계획 생성"),
                    discord.SelectOption(label="현재 상태 수동 백업", value="backup", emoji="💾", description="현재 깨끗한 서버 구조 저장"),
                    discord.SelectOption(label="백업 목록·복구 선택", value="backups", emoji="🗃️", description="드롭다운으로 복구 기준 선택"),
                    discord.SelectOption(label="계획 상태 확인", value="plan_status", emoji="📋", description="진행률과 다음 작업 확인"),
                    discord.SelectOption(label="안전 자동 진행 시작", value="auto_start", emoji="⏯️", description="대기시간을 지키며 한 단계씩 자동 실행"),
                    discord.SelectOption(label="자동 진행 일시정지", value="auto_stop", emoji="⏸️", description="자동 실행만 멈추고 계획은 보존"),
                    discord.SelectOption(label="자동 진행 상태", value="auto_status", emoji="🛰️", description="진행률·다음 실행시간 확인"),
                    discord.SelectOption(label="다음 단계 1개 실행", value="next", emoji="▶️", description="Discord 변경을 한 개만 처리"),
                    discord.SelectOption(label="복구 다음 단계 1개", value="recover_next", emoji="🛟", description="선택한 백업 복구를 한 개 진행"),
                    discord.SelectOption(label="계획 취소", value="cancel", emoji="⏹️", description="남은 리뉴얼 계획 제거"),
                    discord.SelectOption(label="429 안전상태", value="ratelimit", emoji="🛡️", description="현재 격리·대기시간 확인"),
                    discord.SelectOption(label="빈 카테고리 선택 삭제", value="empty", emoji="🗑️", description="비어 있는 카테고리만 선택"),
                ]
                super().__init__(placeholder="서버 리뉴얼 기능을 선택하세요", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction) -> None:
                if interaction.user.id != owner_id:
                    await interaction.response.send_message("❌ 이 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                    return
                choice = self.values[0]
                if choice in {"layout_preview", "layout_apply", "game_preview", "game_apply"}:
                    await interaction.response.send_message(
                        "🎨 테마를 선택하세요. 선택만으로 미리보기 또는 안전 계획 생성이 실행됩니다.",
                        view=ThemeView(choice),
                        ephemeral=True,
                    )
                    return
                command_map = {
                    "backups": ("백업목록", (), {}),
                    "plan_status": ("계획상태", (), {}),
                    "auto_start": ("자동시작", (), {}),
                    "auto_stop": ("자동중지", (), {}),
                    "auto_status": ("자동상태", (), {}),
                    "next": ("다음", (), {}),
                    "recover_next": ("복구다음", (), {}),
                    "cancel": ("계획취소", (), {}),
                    "ratelimit": ("429상태", (), {}),
                    "empty": ("빈카테고리선택", (), {}),
                    "backup": ("백업", (), {"name": "드롭다운 수동 백업"}),
                }
                subcommand_name, args, kwargs = command_map[choice]
                await run_command(interaction, subcommand_name, *args, **kwargs)

        class RenewalMenuView(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=300)
                self.add_item(RenewalMenu())

        embed = discord.Embed(
            title="🕯 ABADDON 서버 리뉴얼 제어실",
            description=(
                "아래 드롭다운에서 기능을 선택하세요.\n"
                "테마 적용과 복구는 **계획 생성 후 한 번에 Discord 변경 1개만** 처리합니다."
            ),
            color=0x6D2335,
        )
        embed.add_field(name="권장 순서", value="수동 백업 → 미리보기 → 적용 계획 → 안전 자동 진행", inline=False)
        embed.add_field(name="안전 원칙", value="미인식 채널 유지 · 적용 전 자동 백업 · 수동/자동 모두 5분 간격 · 429 시 15분 격리", inline=False)
        await ctx.send(embed=embed, view=RenewalMenuView())

    @server_renewal.command(name="테마목록", aliases=["themes", "테마"])
    async def server_renewal_themes(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        lines = [f"• **{name}** · {THEME_META[name]['label']}" for name in THEME_META]
        embed = discord.Embed(
            title="🎨 서버 리뉴얼 테마 7종",
            description="\n".join(lines),
            color=0x6D2335,
        )
        embed.add_field(name="미리보기", value="`!서버리뉴얼 미리보기 테마명`", inline=False)
        embed.add_field(name="게임·음성 구역", value="`!서버리뉴얼 게임미리보기 테마명`", inline=False)
        await ctx.send(embed=embed)

    @server_renewal.command(name="미리보기", aliases=["preview"])
    async def server_renewal_preview(ctx: commands.Context, style: str = "깔끔"):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if style not in STYLE_NAMES:
            await ctx.send("❌ 지원 테마: `깔끔`, `고딕`, `커뮤니티`, `미니멀`, `사이버`, `아포칼립스`, `판타지`")
            return
        await ctx.send(embed=_layout_preview_embed(guild, style))

    @server_renewal.command(name="적용", aliases=["apply", "계획"])
    async def server_renewal_apply(ctx: commands.Context, style: str = "깔끔"):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if style not in STYLE_NAMES:
            await ctx.send("❌ 지원 테마: `깔끔`, `고딕`, `커뮤니티`, `미니멀`, `사이버`, `아포칼립스`, `판타지`")
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        backup = _store_backup(settings, _snapshot_guild(guild, operation="layout", style=style, name=f"{style} 적용 전"))
        actions = build_theme_plan(guild, style, "layout")
        settings["renewal_plan"] = {
            "plan_id": f"layout-{int(time.time() * 1000)}",
            "backup_id": backup["backup_id"],
            "operation": "layout",
            "style": style,
            "created_at": int(time.time()),
            "cursor": 0,
            "actions": actions,
            "next_allowed_at": int(time.time()) + RENEWAL_PLAN_WARMUP,
            "status": "warming_up",
            "last_error": None,
        }
        auto_task = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        if auto_task is not None and not auto_task.done():
            auto_task.cancel()
        settings["autopilot"]["enabled"] = False
        settings["autopilot"]["last_reason"] = "새 리뉴얼 계획 생성"
        settings["last_operation_status"] = "renewal_plan_ready"
        save_data()
        action_lines = [f"{index}. {item.get('label', item.get('kind', '작업'))}" for index, item in enumerate(actions[:12], start=1)]
        if not actions:
            settings.pop("renewal_plan", None)
            settings["last_operation_status"] = "renewal_no_changes"
            save_data()
            await ctx.send(
                f"✅ **{style} 테마 기준으로 바꿀 항목이 없습니다.**\n"
                "현재 인식된 기존 채널은 이미 목표 이름·카테고리와 같거나, 테마 대상 채널로 인식되지 않았습니다.\n"
                "`!서버리뉴얼 미리보기 테마`에서 인식 목록을 먼저 확인하세요."
            )
            return
        await ctx.send(
            f"🧭 **{style} 테마 안전 계획 생성 완료**\n"
            f"변경 항목: **{len(actions)}개** · 자동 백업: **{backup.get('name')}**\n\n"
            + "\n".join(action_lines)
            + (f"\n… 외 {len(actions)-12}개" if len(actions) > 12 else "")
            + f"\n\n아직 채널을 수정하지 않았습니다. 429 예방을 위해 첫 실행은 <t:{settings['renewal_plan']['next_allowed_at']}:R> 가능합니다.\n"
            "그 뒤 드롭다운의 `다음 단계 1개 실행` 또는 `!서버리뉴얼 다음`을 사용하세요.\n"
            "상태: `!서버리뉴얼 계획상태` · 취소: `!서버리뉴얼 계획취소`"
        )

    @server_renewal.command(name="게임미리보기", aliases=["봇게임미리보기", "게임프리뷰"])
    async def server_renewal_game_preview(ctx: commands.Context, style: str = "깔끔"):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if style not in STYLE_NAMES:
            await ctx.send("❌ 지원 테마: `깔끔`, `고딕`, `커뮤니티`, `미니멀`, `사이버`, `아포칼립스`, `판타지`")
            return
        await ctx.send(embed=_game_zone_preview_embed(guild, style))

    @server_renewal.command(name="게임정리", aliases=["봇게임정리", "게임채널정리"])
    async def server_renewal_game_apply(ctx: commands.Context, style: str = "깔끔"):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if style not in STYLE_NAMES:
            await ctx.send("❌ 지원 테마: `깔끔`, `고딕`, `커뮤니티`, `미니멀`, `사이버`, `아포칼립스`, `판타지`")
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        backup = _store_backup(settings, _snapshot_guild(guild, operation="game_zone", style=style, name=f"게임구역 {style} 적용 전"))
        actions = build_theme_plan(guild, style, "game_zone")
        settings["renewal_plan"] = {
            "plan_id": f"game-{int(time.time() * 1000)}",
            "backup_id": backup["backup_id"],
            "operation": "game_zone",
            "style": style,
            "created_at": int(time.time()),
            "cursor": 0,
            "actions": actions,
            "next_allowed_at": int(time.time()) + RENEWAL_PLAN_WARMUP,
            "status": "warming_up",
            "last_error": None,
        }
        auto_task = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        if auto_task is not None and not auto_task.done():
            auto_task.cancel()
        settings["autopilot"]["enabled"] = False
        settings["autopilot"]["last_reason"] = "새 게임·음성 구역 계획 생성"
        settings["last_operation_status"] = "game_plan_ready"
        save_data()
        action_lines = [f"{index}. {item.get('label', item.get('kind', '작업'))}" for index, item in enumerate(actions[:12], start=1)]
        if not actions:
            settings.pop("renewal_plan", None)
            settings["last_operation_status"] = "game_plan_no_changes"
            save_data()
            await ctx.send("✅ 게임·음성 구역에서 변경할 항목을 찾지 못했습니다. 미리보기에서 인식된 채널을 확인하세요.")
            return
        await ctx.send(
            f"🎮 **게임·음성 구역 {style} 안전 계획 생성 완료**\n"
            f"변경 항목: **{len(actions)}개** · 자동 백업 저장 완료\n\n"
            + "\n".join(action_lines)
            + (f"\n… 외 {len(actions)-12}개" if len(actions) > 12 else "")
            + f"\n\n429 예방을 위해 첫 실행은 <t:{settings['renewal_plan']['next_allowed_at']}:R> 가능합니다. 이후 `!서버리뉴얼 다음`을 사용하세요."
        )

    @server_renewal.command(name="백업", aliases=["수동백업", "backup"])
    async def server_renewal_manual_backup(ctx: commands.Context, *, name: str = "현재 정상 상태"):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        snapshot = _store_backup(settings, _snapshot_guild(guild, operation="manual", name=name))
        settings["last_operation_status"] = "manual_backup_saved"
        save_data()
        await ctx.send(
            f"✅ **수동 백업 저장 완료**\n"
            f"이름: **{snapshot['name']}**\n"
            f"카테고리: **{len(snapshot['categories'])}개** · 채널: **{len(snapshot['channels'])}개**\n"
            f"백업 ID: `{snapshot['backup_id']}`"
        )

    @server_renewal.command(name="백업목록", aliases=["backups", "복구목록"])
    async def server_renewal_backup_list(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        backups = _backup_candidates(settings)
        if not backups:
            await ctx.send("⚠️ 저장된 서버 리뉴얼 백업이 없습니다.")
            return

        class BackupSelect(discord.ui.Select):
            def __init__(self) -> None:
                options: List[discord.SelectOption] = []
                for index, item in enumerate(backups[:25], start=1):
                    stamp = int(item.get("created_at", 0) or 0)
                    description = f"{item.get('operation', 'legacy')} · 채널 {len(item.get('channels', []))}개 · {stamp}"
                    options.append(discord.SelectOption(
                        label=_backup_title(item, index),
                        value=str(item.get("backup_id") or f"legacy-{stamp}"),
                        description=description[:100],
                    ))
                super().__init__(placeholder="복구 기준 백업을 선택하세요", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction) -> None:
                member = interaction.user if isinstance(interaction.user, discord.Member) else None
                if member is None or not (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
                    await interaction.response.send_message("❌ 서버 관리자만 선택할 수 있습니다.", ephemeral=True)
                    return
                selected = _find_backup(settings, self.values[0])
                if selected is None:
                    await interaction.response.send_message("❌ 선택한 백업을 찾지 못했습니다. 목록을 다시 열어주세요.", ephemeral=True)
                    return
                plan = build_recovery_plan(guild, selected)
                settings["recovery_plan"] = plan
                settings["last_operation_status"] = "recovery_plan_ready"
                save_data()
                count = len(plan.get("actions", []))
                if count == 0:
                    await interaction.response.send_message(
                        "✅ 선택한 백업과 현재 기존 채널 구조가 같습니다. 복구할 변경이 없습니다.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"🛟 복구 계획 생성 완료 · **{count}개**\n실제 복구: `!서버리뉴얼 복구다음`",
                        ephemeral=True,
                    )

        class BackupView(discord.ui.View):
            def __init__(self) -> None:
                super().__init__(timeout=300)
                self.add_item(BackupSelect())

        lines = []
        for index, item in enumerate(backups, start=1):
            stamp = int(item.get("created_at", 0) or 0)
            dt = f"<t:{stamp}:F>" if stamp else "시간 미상"
            lines.append(
                f"**{index}.** {dt} · **{item.get('name', '기존 백업')}** · "
                f"`{item.get('operation', 'legacy')}` · 채널 {len(item.get('channels', []))}개"
            )
        await ctx.send(
            "🗃️ **서버 리뉴얼 복구 지점**\n"
            + "\n".join(lines)
            + "\n\n아래 목록에서 선택하거나 `!서버리뉴얼 되돌리기 번호`를 입력하세요.",
            view=BackupView(),
        )

    @server_renewal.command(name="되돌리기", aliases=["undo", "복원"])
    async def server_renewal_undo(ctx: commands.Context, backup_number: int = 1):
        """복구 계획만 생성합니다. 이 명령 자체는 Discord 채널을 수정하지 않습니다."""
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        backups = _backup_candidates(settings)
        if not backups:
            await ctx.send("⚠️ 되돌릴 서버 리뉴얼 백업이 없습니다.")
            return
        if backup_number < 1 or backup_number > len(backups):
            await ctx.send(f"❌ 백업 번호는 1부터 {len(backups)} 사이여야 합니다. `!서버리뉴얼 백업목록`을 확인하세요.")
            return
        backup = backups[backup_number - 1]
        plan = build_recovery_plan(guild, backup)
        settings["recovery_plan"] = plan
        settings["last_operation_status"] = "recovery_plan_ready"
        save_data()
        actions = plan.get("actions", [])
        if not actions:
            await ctx.send(
                "✅ 선택한 백업과 현재 기존 채널 구조가 같습니다. 복구할 변경이 없습니다.\n"
                "현재 상태를 새 기준점으로 저장하려면 `!서버리뉴얼 백업 현재정상`을 사용하세요."
            )
            return
        await ctx.send(
            "🛟 **안전 복구 계획을 만들었습니다.**\n"
            f"백업: **{backup_number}번 · {backup.get('name', '기존 백업')}** · 처리 항목: **{len(actions)}개**\n\n"
            "이 명령은 채널을 수정하지 않았습니다. 실제 복구: `!서버리뉴얼 복구다음`\n"
            "진행 확인: `!서버리뉴얼 복구상태`"
        )

    def _recovery_rate_limit_cap(seconds: float = RENEWAL_RATE_LIMIT_CAP):
        http = bot.http
        old_main = getattr(http, "max_ratelimit_timeout", None)
        old_buckets = []
        setattr(http, "max_ratelimit_timeout", seconds)
        for bucket in getattr(http, "_buckets", {}).values():
            if hasattr(bucket, "_max_ratelimit_timeout"):
                old_buckets.append((bucket, getattr(bucket, "_max_ratelimit_timeout", None)))
                setattr(bucket, "_max_ratelimit_timeout", seconds)
        return http, old_main, old_buckets

    def _restore_recovery_rate_limit_cap(state) -> None:
        http, old_main, old_buckets = state
        setattr(http, "max_ratelimit_timeout", old_main)
        restored = {id(bucket) for bucket, _ in old_buckets}
        for bucket, old_value in old_buckets:
            with contextlib.suppress(Exception):
                setattr(bucket, "_max_ratelimit_timeout", old_value)
        for bucket in getattr(http, "_buckets", {}).values():
            if id(bucket) not in restored and hasattr(bucket, "_max_ratelimit_timeout"):
                with contextlib.suppress(Exception):
                    setattr(bucket, "_max_ratelimit_timeout", old_main)

    def _rate_limit_wait(exc: BaseException) -> int:
        value = getattr(exc, "retry_after", None)
        try:
            wait = int(float(value)) if value is not None else 180
        except (TypeError, ValueError):
            wait = 180
        return max(RENEWAL_429_QUARANTINE, min(wait + 60, 1800))

    @server_renewal.command(name="다음", aliases=["next", "계속"])
    async def server_renewal_next(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        plan = settings.get("renewal_plan")
        if not isinstance(plan, dict):
            await ctx.send("ℹ️ 실행할 서버 리뉴얼 계획이 없습니다. 먼저 `!서버리뉴얼 적용 테마`를 실행하세요.")
            return
        actions = plan.get("actions", [])
        cursor = int(plan.get("cursor", 0) or 0)
        if cursor >= len(actions):
            plan["status"] = "complete"
            settings["style"] = plan.get("style")
            settings["last_operation_status"] = "renewal_complete"
            save_data()
            await ctx.send("✅ 서버 리뉴얼 계획이 모두 끝났습니다.")
            return
        now = int(time.time())
        if now < RENEWAL_HTTP_429_UNTIL:
            plan["next_allowed_at"] = max(int(plan.get("next_allowed_at", 0) or 0), RENEWAL_HTTP_429_UNTIL)
            plan["status"] = "quarantine"
            plan["last_error"] = "최근 Discord HTTP 429 감지 — 15분 안전 격리"
            settings["last_operation_status"] = "renewal_429_quarantine"
            save_data()
            await ctx.send(f"🛡️ 최근 429가 감지되어 리뉴얼을 격리 중입니다. <t:{RENEWAL_HTTP_429_UNTIL}:R> 다시 실행하세요.")
            return
        next_allowed = int(plan.get("next_allowed_at", 0) or 0)
        if now < next_allowed:
            await ctx.send(f"⏳ 안전 대기 중입니다. <t:{next_allowed}:R> 다시 실행하세요.")
            return
        action = actions[cursor]
        current_task = asyncio.current_task()
        if current_task is not None:
            RENEWAL_TASKS[guild.id] = current_task
        cap_state = _recovery_rate_limit_cap()
        before_429_until = RENEWAL_HTTP_429_UNTIL
        try:
            await _renewal_api(execute_renewal_action(ctx, guild, action, plan))
            plan["cursor"] = cursor + 1
            detected_429 = RENEWAL_HTTP_429_UNTIL > before_429_until
            plan["next_allowed_at"] = max(
                int(time.time()) + RENEWAL_STEP_COOLDOWN,
                RENEWAL_HTTP_429_UNTIL if detected_429 else 0,
            )
            plan["status"] = (
                "complete" if cursor + 1 >= len(actions)
                else "quarantine" if detected_429
                else "running"
            )
            plan["last_error"] = None
            settings["last_operation_status"] = "renewal_step_ok"
            if cursor + 1 >= len(actions):
                settings["style"] = plan.get("style")
            save_data()
            await ctx.send(
                f"✅ **서버 변경 1개 완료** · {cursor + 1}/{len(actions)}\n"
                f"처리: `{action.get('label', action.get('kind'))}`\n"
                + ("모든 계획이 끝났습니다." if cursor + 1 >= len(actions) else f"다음 실행: <t:{plan['next_allowed_at']}:R>")
                + ("\n🛡️ 처리 중 429가 감지되어 15분 안전 격리를 적용했습니다." if detected_429 else "")
            )
        except LookupError as exc:
            plan["cursor"] = cursor + 1
            plan["last_error"] = str(exc)
            save_data()
            await ctx.send(f"⚠️ 대상이 없어 건너뛰었습니다. 진행: **{cursor + 1}/{len(actions)}**")
        except Exception as exc:
            name = exc.__class__.__name__
            status = getattr(exc, "status", None)
            if isinstance(exc, RenewalApiTimeout):
                wait = RENEWAL_429_QUARANTINE
                plan["next_allowed_at"] = int(time.time()) + wait
                plan["status"] = "quarantine"
                plan["last_error"] = "Discord 응답 45초 초과 — 15분 안전 격리"
                settings["last_operation_status"] = "renewal_api_timeout"
                save_data()
                await ctx.send(f"🛡️ Discord 응답이 길어져 안전 중단했습니다. <t:{plan['next_allowed_at']}:R> 다시 실행하세요.")
            elif name == "RateLimited" or status == 429:
                wait = _rate_limit_wait(exc)
                plan["next_allowed_at"] = int(time.time()) + wait
                plan["status"] = "cooldown"
                plan["last_error"] = f"429 / {wait}초 대기"
                settings["last_operation_status"] = "renewal_rate_limited"
                save_data()
                await ctx.send(f"⏸️ Discord 429를 감지해 변경 없이 중단했습니다. <t:{plan['next_allowed_at']}:R> 다시 실행하세요.")
            elif isinstance(exc, discord.Forbidden):
                plan["status"] = "blocked"
                plan["last_error"] = "권한 부족"
                save_data()
                await ctx.send("❌ 채널 관리 권한이 부족합니다.")
            else:
                plan["status"] = "error"
                plan["last_error"] = f"{name}: {str(exc)[:180]}"
                save_data()
                await ctx.send(f"❌ 단계 처리 실패: `{name}: {str(exc)[:180]}`")
        finally:
            _restore_recovery_rate_limit_cap(cap_state)
            if RENEWAL_TASKS.get(guild.id) is current_task:
                RENEWAL_TASKS.pop(guild.id, None)

    @server_renewal.command(name="계획상태", aliases=["planstatus", "적용상태"])
    async def server_renewal_plan_status(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        plan = _layout_settings(world_data, guild.id)["layout"].get("renewal_plan")
        if not isinstance(plan, dict):
            await ctx.send("ℹ️ 저장된 리뉴얼 계획이 없습니다.")
            return
        actions = plan.get("actions", [])
        cursor = int(plan.get("cursor", 0) or 0)
        next_label = "완료" if cursor >= len(actions) else str(actions[cursor].get("label", "다음 항목"))
        next_allowed = int(plan.get("next_allowed_at", 0) or 0)
        cooldown = f"<t:{next_allowed}:R>" if next_allowed > int(time.time()) else "지금 가능"
        await ctx.send(
            "🧭 **서버 리뉴얼 계획 상태**\n"
            f"테마: **{plan.get('style', '없음')}** · 작업: `{plan.get('operation', 'layout')}`\n"
            f"진행: **{cursor}/{len(actions)}** · 상태: `{plan.get('status', 'unknown')}`\n"
            f"다음: `{next_label}` · 실행 가능: {cooldown}\n"
            f"최근 오류: `{plan.get('last_error') or '없음'}`"
        )

    def _active_autopilot_plan(layout: Dict[str, Any], requested_mode: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        modes = [requested_mode] if requested_mode in {"renewal", "recovery"} else ["renewal", "recovery"]
        for mode in modes:
            key = "renewal_plan" if mode == "renewal" else "recovery_plan"
            plan = layout.get(key)
            if not isinstance(plan, dict):
                continue
            actions = plan.get("actions", [])
            cursor = int(plan.get("cursor", 0) or 0)
            if cursor < len(actions):
                return mode, plan
        return None, None

    async def _renewal_autopilot_loop(ctx: commands.Context, mode: str) -> None:
        guild = ctx.guild
        if guild is None:
            return
        guild_id = guild.id
        current_task = asyncio.current_task()
        layout = _layout_settings(world_data, guild_id)["layout"]
        auto = layout["autopilot"]
        try:
            while bool(auto.get("enabled")):
                plan_key = "renewal_plan" if mode == "renewal" else "recovery_plan"
                plan = layout.get(plan_key)
                if not isinstance(plan, dict):
                    auto["last_reason"] = "실행할 계획이 없어 종료"
                    break
                actions = plan.get("actions", [])
                cursor = int(plan.get("cursor", 0) or 0)
                if cursor >= len(actions):
                    auto["last_reason"] = "모든 단계 완료"
                    await ctx.send(f"✅ 서버 리뉴얼 안전 자동 진행이 완료됐습니다. **{cursor}/{len(actions)}**")
                    break
                if str(plan.get("status")) in {"blocked", "error", "paused"}:
                    auto["last_reason"] = f"계획 상태 {plan.get('status')}로 자동 정지"
                    await ctx.send(f"⏸️ 자동 진행을 멈췄습니다. 계획 상태: `{plan.get('status')}` · 오류: `{plan.get('last_error') or '없음'}`")
                    break
                next_allowed = max(
                    int(plan.get("next_allowed_at", 0) or 0),
                    int(RENEWAL_HTTP_429_UNTIL),
                )
                auto["next_run_at"] = next_allowed
                save_data()
                now = int(time.time())
                if now < next_allowed:
                    await asyncio.sleep(min(60, max(1, next_allowed - now)))
                    continue

                before_cursor = cursor
                if mode == "renewal":
                    await server_renewal_next.callback(ctx)
                else:
                    await server_renewal_recover_next.callback(ctx)

                layout = _layout_settings(world_data, guild_id)["layout"]
                auto = layout["autopilot"]
                plan = layout.get(plan_key)
                if not isinstance(plan, dict):
                    auto["last_reason"] = "계획이 제거되어 종료"
                    break
                after_cursor = int(plan.get("cursor", 0) or 0)
                if after_cursor <= before_cursor and int(plan.get("next_allowed_at", 0) or 0) <= int(time.time()):
                    auto["last_reason"] = "단계가 진행되지 않아 안전 정지"
                    await ctx.send("⏸️ 자동 진행에서 단계 변화가 없어 안전 정지했습니다. `!서버리뉴얼 자동상태`를 확인하세요.")
                    break
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            auto["last_reason"] = "관리자가 자동 진행을 일시정지"
            raise
        except Exception as exc:
            auto["last_reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            await ctx.send(f"❌ 서버 리뉴얼 자동 진행 오류로 정지했습니다: `{auto['last_reason']}`")
        finally:
            auto["enabled"] = False
            auto["next_run_at"] = 0
            save_data()
            if RENEWAL_AUTOPILOT_TASKS.get(guild_id) is current_task:
                RENEWAL_AUTOPILOT_TASKS.pop(guild_id, None)

    @server_renewal.command(name="자동시작", aliases=["autostart", "자동진행"])
    async def server_renewal_auto_start(ctx: commands.Context, mode: Optional[str] = None):
        guild = await require_admin(ctx)
        if guild is None:
            return
        existing = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        if existing is not None and not existing.done():
            await ctx.send("ℹ️ 이미 서버 리뉴얼 안전 자동 진행이 실행 중입니다. `!서버리뉴얼 자동상태`를 확인하세요.")
            return
        normalized = None
        if mode:
            normalized = {"리뉴얼": "renewal", "적용": "renewal", "renewal": "renewal", "복구": "recovery", "recovery": "recovery"}.get(mode.casefold())
            if normalized is None:
                await ctx.send("❌ 자동시작 모드는 `리뉴얼` 또는 `복구`로 입력하세요.")
                return
        layout = _layout_settings(world_data, guild.id)["layout"]
        selected_mode, plan = _active_autopilot_plan(layout, normalized)
        if selected_mode is None or plan is None:
            await ctx.send("ℹ️ 자동 진행할 미완료 리뉴얼·복구 계획이 없습니다. 먼저 드롭다운에서 계획을 만들어주세요.")
            return
        auto = layout["autopilot"]
        auto.update({
            "enabled": True,
            "mode": selected_mode,
            "channel_id": getattr(ctx.channel, "id", None),
            "started_by": ctx.author.id,
            "started_at": int(time.time()),
            "next_run_at": max(int(plan.get("next_allowed_at", 0) or 0), int(RENEWAL_HTTP_429_UNTIL)),
            "last_reason": "자동 진행 시작",
        })
        save_data()
        task = asyncio.create_task(_renewal_autopilot_loop(ctx, selected_mode), name=f"abaddon-renewal-auto-{guild.id}")
        RENEWAL_AUTOPILOT_TASKS[guild.id] = task
        actions = plan.get("actions", [])
        cursor = int(plan.get("cursor", 0) or 0)
        next_at = int(auto.get("next_run_at", 0) or 0)
        mode_label = "테마 적용" if selected_mode == "renewal" else "백업 복구"
        await ctx.send(
            f"⏯️ **{mode_label} 안전 자동 진행을 시작했습니다.**\n"
            f"진행: **{cursor}/{len(actions)}** · 다음 실행: "
            + (f"<t:{next_at}:R>" if next_at > int(time.time()) else "곧 실행")
            + "\n각 단계는 기존 5분 간격과 429 격리를 그대로 지킵니다. 중지: `!서버리뉴얼 자동중지`"
        )

    @server_renewal.command(name="자동중지", aliases=["autostop", "자동일시정지"])
    async def server_renewal_auto_stop(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        task = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        layout = _layout_settings(world_data, guild.id)["layout"]
        auto = layout["autopilot"]
        auto["enabled"] = False
        auto["last_reason"] = "관리자가 자동 진행을 일시정지"
        auto["next_run_at"] = 0
        if task is not None and not task.done():
            task.cancel()
        save_data()
        await ctx.send("⏸️ 서버 리뉴얼 안전 자동 진행을 멈췄습니다. 현재 계획과 진행률은 그대로 보존됩니다.")

    @server_renewal.command(name="자동상태", aliases=["autostatus"])
    async def server_renewal_auto_status(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        layout = _layout_settings(world_data, guild.id)["layout"]
        auto = layout["autopilot"]
        task = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        running = task is not None and not task.done() and bool(auto.get("enabled"))
        mode = auto.get("mode")
        plan_key = "renewal_plan" if mode == "renewal" else "recovery_plan"
        plan = layout.get(plan_key) if mode in {"renewal", "recovery"} else None
        actions = plan.get("actions", []) if isinstance(plan, dict) else []
        cursor = int(plan.get("cursor", 0) or 0) if isinstance(plan, dict) else 0
        next_at = int(auto.get("next_run_at", 0) or 0)
        await ctx.send(
            "🛰️ **서버 리뉴얼 안전 자동 진행 상태**\n"
            f"실행: **{'켜짐' if running else '꺼짐'}** · 모드: `{mode or '없음'}`\n"
            f"진행: **{cursor}/{len(actions)}** · 다음 실행: "
            + (f"<t:{next_at}:R>" if running and next_at > int(time.time()) else "대기 없음")
            + f"\n마지막 상태: `{auto.get('last_reason', '기록 없음')}`"
        )

    @server_renewal.command(name="429상태", aliases=["ratelimit", "쿨다운", "안전대기"])
    async def server_renewal_rate_limit_status(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        remaining = _renewal_quarantine_remaining()
        settings = _layout_settings(world_data, guild.id)["layout"]
        plans = [settings.get("renewal_plan"), settings.get("recovery_plan")]
        plan_waits = [int(plan.get("next_allowed_at", 0) or 0) for plan in plans if isinstance(plan, dict)]
        plan_until = max(plan_waits, default=0)
        now = int(time.time())
        if remaining <= 0 and plan_until <= now:
            await ctx.send("✅ 현재 서버 리뉴얼 429 격리 상태가 아닙니다. 새 계획은 생성 후 5분, 각 단계 사이도 5분 대기합니다.")
            return
        until = max(RENEWAL_HTTP_429_UNTIL, plan_until)
        detail = RENEWAL_HTTP_429_LAST or "저장된 안전 대기시간"
        await ctx.send(
            "🛡️ **서버 리뉴얼 429 안전상태**\n"
            f"다음 변경 가능: <t:{until}:R>\n"
            f"최근 감지: `{detail[:180]}`"
        )

    @server_renewal.command(name="계획취소", aliases=["plancancel", "적용취소"])
    async def server_renewal_plan_cancel(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        auto_task = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        if auto_task is not None and not auto_task.done():
            auto_task.cancel()
        settings["autopilot"]["enabled"] = False
        settings["autopilot"]["last_reason"] = "리뉴얼 계획 취소"
        if settings.pop("renewal_plan", None) is None:
            save_data()
            await ctx.send("ℹ️ 취소할 리뉴얼 계획이 없습니다. 자동 진행은 중지했습니다.")
            return
        settings["last_operation_status"] = "renewal_plan_cancelled"
        save_data()
        await ctx.send("✅ 리뉴얼 계획을 취소했습니다. 추가 채널 변경은 없습니다.")

    @server_renewal.command(name="복구다음", aliases=["recovernext", "복구계속"])
    async def server_renewal_recover_next(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if _renewal_running(guild.id):
            await ctx.send("⚠️ 다른 리뉴얼 작업이 진행 중입니다. `!서버리뉴얼 중지` 후 다시 시도하세요.")
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        plan = settings.get("recovery_plan")
        if not isinstance(plan, dict):
            await ctx.send("⚠️ 복구 계획이 없습니다. 먼저 `!서버리뉴얼 되돌리기 1`을 실행하세요.")
            return
        actions = plan.get("actions", [])
        cursor = int(plan.get("cursor", 0) or 0)
        if cursor >= len(actions):
            plan["status"] = "complete"
            settings["style"] = None
            settings["last_operation_status"] = "restored_stepwise"
            save_data()
            await ctx.send("✅ 단계별 복구가 모두 끝났습니다. 남은 빈 복제 카테고리는 `!서버리뉴얼 빈카테고리선택`으로 한 개씩 정리하세요.")
            return
        now = int(time.time())
        if now < RENEWAL_HTTP_429_UNTIL:
            plan["next_allowed_at"] = max(int(plan.get("next_allowed_at", 0) or 0), RENEWAL_HTTP_429_UNTIL)
            plan["status"] = "quarantine"
            plan["last_error"] = "최근 Discord HTTP 429 감지 — 15분 안전 격리"
            settings["last_operation_status"] = "recovery_429_quarantine"
            save_data()
            await ctx.send(f"🛡️ 최근 429가 감지되어 복구를 격리 중입니다. <t:{RENEWAL_HTTP_429_UNTIL}:R> 다시 실행하세요.")
            return
        next_allowed = int(plan.get("next_allowed_at", 0) or 0)
        if now < next_allowed:
            await ctx.send(f"⏳ Discord 채널 변경 제한을 식히는 중입니다. <t:{next_allowed}:R> 다시 실행하세요.")
            return
        action = actions[cursor]
        channel = guild.get_channel(int(action.get("id", 0)))
        if channel is None:
            plan["cursor"] = cursor + 1
            plan["last_error"] = "대상 채널 없음 — 건너뜀"
            save_data()
            await ctx.send(f"⚠️ 대상이 없어 **{cursor + 1}/{len(actions)}** 항목을 건너뛰었습니다. 다시 `!서버리뉴얼 복구다음`을 실행하세요.")
            return

        current_task = asyncio.current_task()
        if current_task is not None:
            RENEWAL_TASKS[guild.id] = current_task
        reason = f"ABADDON v{VERSION} 단계별 안전 복구 / {ctx.author}"
        cap_state = _recovery_rate_limit_cap()
        before_429_until = RENEWAL_HTTP_429_UNTIL
        try:
            kind = str(action.get("kind"))
            async def perform_recovery_edit() -> None:
                if kind == "rename":
                    await bot.http.edit_channel(channel.id, name=str(action.get("name", channel.name)), reason=reason)
                elif kind == "move":
                    await bot.http.edit_channel(channel.id, parent_id=action.get("parent_id"), reason=reason)
                else:
                    raise RuntimeError(f"알 수 없는 복구 작업: {kind}")
            await _renewal_api(perform_recovery_edit())
            plan["cursor"] = cursor + 1
            detected_429 = RENEWAL_HTTP_429_UNTIL > before_429_until
            plan["next_allowed_at"] = max(
                int(time.time()) + RENEWAL_STEP_COOLDOWN,
                RENEWAL_HTTP_429_UNTIL if detected_429 else 0,
            )
            plan["status"] = (
                "complete" if cursor + 1 >= len(actions)
                else "quarantine" if detected_429
                else "running"
            )
            plan["last_error"] = None
            settings["last_operation_status"] = "recovery_step_ok"
            if cursor + 1 >= len(actions):
                settings["style"] = None
            save_data()
            await ctx.send(
                f"✅ **1개 항목 복구 완료** · {cursor + 1}/{len(actions)}\n"
                f"처리: `{action.get('label', kind)}`\n"
                + ("모든 복구가 끝났습니다." if cursor + 1 >= len(actions) else f"다음 실행 가능: <t:{plan['next_allowed_at']}:R>")
                + ("\n🛡️ 처리 중 429가 감지되어 15분 안전 격리를 적용했습니다." if detected_429 else "")
            )
        except Exception as exc:
            name = exc.__class__.__name__
            status = getattr(exc, "status", None)
            if isinstance(exc, RenewalApiTimeout):
                wait = RENEWAL_429_QUARANTINE
                plan["next_allowed_at"] = int(time.time()) + wait
                plan["status"] = "quarantine"
                plan["last_error"] = "Discord 응답 45초 초과 — 15분 안전 격리"
                settings["last_operation_status"] = "recovery_api_timeout"
                save_data()
                await ctx.send(f"🛡️ Discord 응답이 길어져 복구를 안전 중단했습니다. <t:{plan['next_allowed_at']}:R> 다시 실행하세요.")
            elif name == "RateLimited" or status == 429:
                wait = _rate_limit_wait(exc)
                plan["next_allowed_at"] = int(time.time()) + wait
                plan["status"] = "cooldown"
                plan["last_error"] = f"429 / {wait}초 대기"
                settings["last_operation_status"] = "recovery_rate_limited"
                save_data()
                await ctx.send(
                    "⏸️ **Discord 429를 감지해 즉시 중단했습니다.**\n"
                    f"복구 항목은 진행하지 않았습니다. <t:{plan['next_allowed_at']}:R> 다시 `!서버리뉴얼 복구다음`을 실행하세요."
                )
            elif isinstance(exc, discord.Forbidden):
                plan["last_error"] = "권한 부족"
                plan["status"] = "blocked"
                save_data()
                await ctx.send("❌ 채널 관리 권한이 부족해 복구하지 못했습니다.")
            else:
                plan["last_error"] = f"{name}: {str(exc)[:180]}"
                plan["status"] = "error"
                save_data()
                await ctx.send(f"❌ 복구 항목 처리 실패: `{name}: {str(exc)[:180]}`")
        finally:
            _restore_recovery_rate_limit_cap(cap_state)
            if RENEWAL_TASKS.get(guild.id) is current_task:
                RENEWAL_TASKS.pop(guild.id, None)

    @server_renewal.command(name="복구상태", aliases=["recoverstatus"])
    async def server_renewal_recover_status(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        plan = _layout_settings(world_data, guild.id)["layout"].get("recovery_plan")
        if not isinstance(plan, dict):
            await ctx.send("ℹ️ 저장된 단계별 복구 계획이 없습니다.")
            return
        actions = plan.get("actions", [])
        cursor = int(plan.get("cursor", 0) or 0)
        next_label = "완료" if cursor >= len(actions) else str(actions[cursor].get("label", "다음 항목"))
        next_allowed = int(plan.get("next_allowed_at", 0) or 0)
        cooldown = f"<t:{next_allowed}:R>" if next_allowed > int(time.time()) else "지금 가능"
        await ctx.send(
            "🛟 **단계별 복구 상태**\n"
            f"진행: **{cursor}/{len(actions)}**\n"
            f"상태: `{plan.get('status', 'unknown')}`\n"
            f"다음: `{next_label}`\n"
            f"실행 가능: {cooldown}\n"
            f"최근 오류: `{plan.get('last_error') or '없음'}`"
        )

    @server_renewal.command(name="복구취소", aliases=["recovercancel"])
    async def server_renewal_recover_cancel(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        if settings.pop("recovery_plan", None) is None:
            await ctx.send("ℹ️ 취소할 복구 계획이 없습니다.")
            return
        settings["last_operation_status"] = "recovery_plan_cancelled"
        save_data()
        await ctx.send("✅ 단계별 복구 계획을 취소했습니다. 채널에는 추가 변경을 하지 않았습니다.")

    @server_renewal.command(name="중지", aliases=["stop", "취소"])
    async def server_renewal_stop(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        task = RENEWAL_TASKS.get(guild.id)
        auto_task = RENEWAL_AUTOPILOT_TASKS.get(guild.id)
        settings = _layout_settings(world_data, guild.id)["layout"]
        stopped = False
        if auto_task is not None and not auto_task.done():
            settings["autopilot"]["enabled"] = False
            settings["autopilot"]["last_reason"] = "전체 작업 중지"
            auto_task.cancel()
            stopped = True
        if task is not None and not task.done():
            task.cancel()
            stopped = True
        if isinstance(settings.get("renewal_plan"), dict):
            settings["renewal_plan"]["status"] = "paused"
            stopped = True
        if isinstance(settings.get("recovery_plan"), dict):
            settings["recovery_plan"]["status"] = "paused"
            stopped = True
        save_data()
        await ctx.send("⛔ 작업을 일시정지했습니다." if stopped else "ℹ️ 현재 진행 중이거나 준비된 작업이 없습니다.")

    @server_renewal.command(name="작업상태", aliases=["progress", "진행상태"])
    async def server_renewal_progress(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        running = _renewal_running(guild.id)
        await ctx.send(
            f"🔧 실행 중: **{'예' if running else '아니오'}**\n"
            f"리뉴얼 계획: **{'있음' if isinstance(settings.get('renewal_plan'), dict) else '없음'}**\n"
            f"복구 계획: **{'있음' if isinstance(settings.get('recovery_plan'), dict) else '없음'}**\n"
            f"자동 진행: **{'켜짐' if settings.get('autopilot', {}).get('enabled') else '꺼짐'}**\n"
            f"마지막 상태: `{settings.get('last_operation_status', '기록 없음')}`"
        )

    @server_renewal.command(name="긴급정리", aliases=["cleanup", "잔여정리"])
    async def server_renewal_emergency_cleanup(ctx: commands.Context, confirm: str = ""):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if _renewal_running(guild.id):
            await ctx.send("⚠️ 진행 중인 작업을 먼저 `!서버리뉴얼 중지`로 멈춰주세요.")
            return
        known_names = {_normalise_name(name) for name in _all_theme_category_names()}
        empty = [category for category in guild.categories if not category.channels and _normalise_name(category.name) in known_names]
        empty.sort(key=lambda category: (category.position, category.id))
        if not empty:
            await ctx.send("✅ 삭제 가능한 빈 리뉴얼 테마 카테고리가 없습니다.")
            return
        if confirm != "확인":
            lines = [f"• `{category.name}` · ID `{category.id}`" for category in empty[:25]]
            await ctx.send(
                "⚠️ **빈 리뉴얼 카테고리 긴급 정리 미리보기**\n" + "\n".join(lines)
                + "\n\n429 방지를 위해 실행할 때마다 **맨 위 1개만** 삭제합니다.\n"
                "삭제: `!서버리뉴얼 긴급정리 확인`"
            )
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        next_allowed = int(settings.get("cleanup_next_allowed_at", 0) or 0)
        if int(time.time()) < next_allowed:
            await ctx.send(f"⏳ 삭제 제한을 식히는 중입니다. <t:{next_allowed}:R> 다시 시도하세요.")
            return
        target = empty[0]
        cap_state = _recovery_rate_limit_cap()
        try:
            await bot.http.delete_channel(target.id, reason=f"ABADDON v{VERSION} 빈 카테고리 1개 안전 삭제 / {ctx.author}")
            settings["cleanup_next_allowed_at"] = int(time.time()) + RENEWAL_STEP_COOLDOWN
            save_data()
            await ctx.send(f"✅ 빈 카테고리 `{target.name}` 1개를 삭제했습니다. 다음 삭제 가능: <t:{settings['cleanup_next_allowed_at']}:R>")
        except Exception as exc:
            name = exc.__class__.__name__
            status = getattr(exc, "status", None)
            if name == "RateLimited" or status == 429:
                wait = _rate_limit_wait(exc)
                settings["cleanup_next_allowed_at"] = int(time.time()) + wait
                save_data()
                await ctx.send(f"⏸️ 429를 감지해 삭제하지 않았습니다. <t:{settings['cleanup_next_allowed_at']}:R> 다시 시도하세요.")
            else:
                await ctx.send(f"❌ 삭제 실패: `{name}: {str(exc)[:180]}`")
        finally:
            _restore_recovery_rate_limit_cap(cap_state)

    @server_renewal.command(name="상태", aliases=["status"])
    async def server_renewal_status(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        destinations = _menu_destinations(guild)
        await ctx.send(
            "🕯 **서버 리뉴얼 상태**\n"
            f"현재 테마: **{settings.get('style') or '미적용'}**\n"
            f"복구 백업: **{'있음' if settings.get('backup') else '없음'}**\n"
            f"메뉴에서 찾은 주요 채널: **{len(destinations)}개**\n"
            f"저장된 메뉴 메시지: **{'있음' if settings.get('menu_message_id') else '없음'}**"
        )

    @server_renewal.command(name="빈카테고리", aliases=["empty"])
    async def server_renewal_empty(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        empty = _empty_categories(guild)
        if not empty:
            await ctx.send("✅ 비어 있는 카테고리가 없습니다.")
            return
        lines = [f"**{index}.** `{category.name}` · ID `{category.id}`" for index, category in enumerate(empty[:40], start=1)]
        suffix = "" if len(empty) <= 40 else f"\n…외 {len(empty) - 40}개"
        await ctx.send(
            "🧹 **비어 있는 카테고리 목록**\n"
            + "\n".join(lines)
            + suffix
            + "\n\n드롭다운: `!서버리뉴얼 빈카테고리선택`"
            + "\n번호 삭제: `!서버리뉴얼 빈카테고리삭제 1,3,5 확인`"
            + "\n전체 삭제: `!서버리뉴얼 빈카테고리삭제 전체 확인`"
        )

    class EmptyCategorySelect(discord.ui.Select):
        def __init__(self, categories: Sequence[discord.CategoryChannel]):
            options = [
                discord.SelectOption(
                    label=category.name[:100],
                    value=str(category.id),
                    description=f"빈 카테고리 · 위치 {category.position}"[:100],
                    emoji="🗑️",
                )
                for category in categories[:25]
            ]
            super().__init__(
                placeholder="삭제할 빈 카테고리를 선택하세요",
                min_values=1,
                max_values=max(1, len(options)),
                options=options,
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            view = self.view
            if not isinstance(view, EmptyCategoryDeleteView):
                await interaction.response.send_message("❌ 선택 메뉴 상태를 확인하지 못했습니다.", ephemeral=True)
                return
            view.selected_ids = {int(value) for value in self.values}
            names = []
            if interaction.guild is not None:
                for category_id in view.selected_ids:
                    category = interaction.guild.get_channel(category_id)
                    if isinstance(category, discord.CategoryChannel):
                        names.append(category.name)
            await interaction.response.send_message(
                "선택됨: " + ", ".join(f"`{name}`" for name in names[:15]) + "\n아래 **선택 삭제** 버튼을 누르세요.",
                ephemeral=True,
            )

    class EmptyCategoryDeleteView(discord.ui.View):
        def __init__(self, owner_id: int, categories: Sequence[discord.CategoryChannel]):
            super().__init__(timeout=180)
            self.owner_id = owner_id
            self.category_ids = {category.id for category in categories}
            self.selected_ids: set[int] = set()
            self.add_item(EmptyCategorySelect(categories))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("❌ 이 선택 메뉴를 연 관리자만 사용할 수 있습니다.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="선택 삭제", style=discord.ButtonStyle.danger, emoji="🗑️")
        async def delete_selected(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            if interaction.guild is None:
                await interaction.response.send_message("❌ 서버에서만 사용할 수 있습니다.", ephemeral=True)
                return
            if not self.selected_ids:
                await interaction.response.send_message("⚠️ 먼저 카테고리를 선택하세요.", ephemeral=True)
                return
            category_id = next(iter(self.selected_ids))
            category = interaction.guild.get_channel(category_id)
            deleted = 0
            skipped = 0
            if not isinstance(category, discord.CategoryChannel) or category.channels:
                skipped = 1
            else:
                try:
                    await interaction.client.http.delete_channel(
                        category.id, reason=f"ABADDON v{VERSION} 선택형 빈 카테고리 1개 안전 삭제 / {interaction.user}"
                    )
                    deleted = 1
                except (discord.Forbidden, discord.HTTPException):
                    skipped = 1
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content=f"✅ 429 방지를 위해 선택 항목 중 **1개만** 처리했습니다. 삭제: **{deleted}개** · 건너뜀: **{skipped}개**",
                view=self,
            )
            self.stop()

        @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="✖️")
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content="취소했습니다.", view=self)
            self.stop()

    @server_renewal.command(name="빈카테고리선택", aliases=["emptyselect", "선택삭제"])
    async def server_renewal_empty_select(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        empty = _empty_categories(guild)
        if not empty:
            await ctx.send("✅ 선택할 빈 카테고리가 없습니다.")
            return
        view = EmptyCategoryDeleteView(ctx.author.id, empty[:25])
        note = "" if len(empty) <= 25 else f"\n⚠️ Discord 드롭다운 제한으로 앞쪽 25개만 표시합니다. 나머지는 번호 삭제를 사용하세요."
        await ctx.send("🗑️ **삭제할 빈 카테고리를 선택하세요.**" + note, view=view)

    @server_renewal.command(name="빈카테고리삭제", aliases=["cleanempty"])
    async def server_renewal_delete_empty(ctx: commands.Context, selection: str = "", confirm: str = ""):
        guild = await require_admin(ctx)
        if guild is None:
            return
        if confirm != "확인":
            await ctx.send(
                "⚠️ 사용법: `!서버리뉴얼 빈카테고리삭제 1,3 확인` 또는 "
                "`!서버리뉴얼 빈카테고리삭제 전체 확인`"
            )
            return
        empty = _empty_categories(guild)
        targets = _parse_category_selection(selection, empty)
        if not targets:
            await ctx.send("❌ 선택한 번호에 해당하는 빈 카테고리가 없습니다. `!서버리뉴얼 빈카테고리`로 번호를 확인하세요.")
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        if not settings.get("backup"):
            _store_backup(settings, _snapshot_guild(guild, operation="empty_category_delete"))
            save_data()
        target = targets[0]
        if target.channels:
            await ctx.send("⚠️ 선택한 첫 카테고리에 채널이 있어 삭제하지 않았습니다.")
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        next_allowed = int(settings.get("cleanup_next_allowed_at", 0) or 0)
        if int(time.time()) < next_allowed:
            await ctx.send(f"⏳ 삭제 제한을 식히는 중입니다. <t:{next_allowed}:R> 다시 시도하세요.")
            return
        cap_state = _recovery_rate_limit_cap()
        try:
            await bot.http.delete_channel(target.id, reason=f"ABADDON v{VERSION} 선택형 빈 카테고리 1개 안전 삭제 / {ctx.author}")
            settings["cleanup_next_allowed_at"] = int(time.time()) + RENEWAL_STEP_COOLDOWN
            save_data()
            await ctx.send(f"✅ 429 방지를 위해 `{target.name}` **1개만** 삭제했습니다. 다음 삭제 가능: <t:{settings['cleanup_next_allowed_at']}:R>")
        except Exception as exc:
            name = exc.__class__.__name__
            status = getattr(exc, "status", None)
            if name == "RateLimited" or status == 429:
                wait = _rate_limit_wait(exc)
                settings["cleanup_next_allowed_at"] = int(time.time()) + wait
                save_data()
                await ctx.send(f"⏸️ 429를 감지해 삭제하지 않았습니다. <t:{settings['cleanup_next_allowed_at']}:R> 다시 시도하세요.")
            else:
                await ctx.send(f"❌ 삭제 실패: `{name}: {str(exc)[:180]}`")
        finally:
            _restore_recovery_rate_limit_cap(cap_state)

    @bot.group(name="서버메뉴", aliases=["채널메뉴", "안내패널"], invoke_without_command=True, case_insensitive=True)
    async def server_menu(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        await ctx.send("사용법: `!서버메뉴 생성 [#채널]` · `!서버메뉴 갱신` · `!서버메뉴 삭제`")

    @server_menu.command(name="생성", aliases=["create"])
    async def server_menu_create(ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        guild = await require_admin(ctx)
        if guild is None:
            return
        target = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("❌ 메뉴를 올릴 텍스트 채널을 지정하세요.")
            return
        destinations = _menu_destinations(guild)
        if not destinations:
            await ctx.send("❌ 연결할 주요 채널을 찾지 못했습니다. 먼저 `!서버리뉴얼 미리보기 깔끔`을 확인하세요.")
            return
        message = await target.send(embed=_menu_embed(guild, destinations), view=_menu_view(guild, destinations))
        settings = _layout_settings(world_data, guild.id)["layout"]
        settings["menu_channel_id"] = target.id
        settings["menu_message_id"] = message.id
        save_data()
        await ctx.send(f"✅ {target.mention}에 서버 이동 메뉴를 만들었습니다.", delete_after=8)

    @server_menu.command(name="갱신", aliases=["update"])
    async def server_menu_update(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        channel = guild.get_channel(settings.get("menu_channel_id") or 0)
        if not isinstance(channel, discord.TextChannel) or not settings.get("menu_message_id"):
            await ctx.send("⚠️ 저장된 서버 메뉴가 없습니다. `!서버메뉴 생성`을 먼저 실행하세요.")
            return
        try:
            message = await channel.fetch_message(int(settings["menu_message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await ctx.send("❌ 저장된 메뉴 메시지를 찾지 못했습니다. 새로 생성하세요.")
            return
        destinations = _menu_destinations(guild)
        await message.edit(embed=_menu_embed(guild, destinations), view=_menu_view(guild, destinations))
        await ctx.send("✅ 현재 채널 구조를 기준으로 서버 메뉴를 갱신했습니다.", delete_after=8)

    @server_menu.command(name="삭제", aliases=["delete"])
    async def server_menu_delete(ctx: commands.Context):
        guild = await require_admin(ctx)
        if guild is None:
            return
        settings = _layout_settings(world_data, guild.id)["layout"]
        channel = guild.get_channel(settings.get("menu_channel_id") or 0)
        if isinstance(channel, discord.TextChannel) and settings.get("menu_message_id"):
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = await channel.fetch_message(int(settings["menu_message_id"]))
                await message.delete()
        settings["menu_channel_id"] = None
        settings["menu_message_id"] = None
        save_data()
        await ctx.send("✅ 저장된 서버 메뉴를 해제했습니다.")

    async def handle_auto_tts(message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return
        if message.content.startswith("!"):
            return
        if not isinstance(message.author, discord.Member):
            return
        settings = _layout_settings(world_data, message.guild.id)["tts"]
        if not settings.get("enabled"):
            return
        if message.channel.id != settings.get("text_channel_id"):
            return

        if settings.get("mode") == "fixed":
            target_channel_id = int(settings.get("voice_channel_id") or 0)
        else:
            if not message.author.voice or not isinstance(message.author.voice.channel, discord.VoiceChannel):
                return
            target_channel_id = message.author.voice.channel.id

        if not target_channel_id:
            return
        voice_client = message.guild.voice_client
        queued_targets = VOICE_RUNTIME.queued_channel_ids(message.guild.id)
        active_target = VOICE_RUNTIME.active_channel_ids.get(message.guild.id)
        current_target = int(getattr(getattr(voice_client, "channel", None), "id", 0) or 0)
        occupied_target = active_target or current_target
        if occupied_target and occupied_target != target_channel_id:
            if (voice_client is not None and voice_client.is_playing()) or queued_targets:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await message.add_reaction("⏳")
                return

        now = time.monotonic()
        key = (message.guild.id, message.author.id)
        if now - VOICE_RUNTIME.user_cooldowns.get(key, 0.0) < TTS_USER_COOLDOWN:
            return
        VOICE_RUNTIME.user_cooldowns[key] = now
        clean = message.clean_content or ""
        if not clean and message.attachments:
            clean = "파일을 올렸습니다."
        ok, _ = await enqueue_tts(
            message.guild,
            message.author,
            clean,
            announce_name=False,
            target_voice_channel_id=target_channel_id,
        )
        if not ok:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await message.add_reaction("⚠️")

    bot.add_listener(handle_auto_tts, "on_message")
