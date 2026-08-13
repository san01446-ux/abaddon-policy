from __future__ import annotations

"""ABADDON v12.2.0 Chaos Festival Complete.

A broad, additive entertainment expansion covering:
* opt-in guild chaos events;
* party games with restart-safe state;
* NPC relationships, companions and expeditions;
* player businesses and public variety reports;
* social games, safe anonymous encouragement and secret friends;
* cosmetic collections, guild trophies and discoverable secrets.

Automatic posting is disabled by default. Rewards use an idempotency ledger and
all session state is stored under a guild/user scoped schema so restarts do not
silently duplicate payouts.
"""

import asyncio
import copy
import hashlib
import io
import json
import random
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _interaction_locale, _locale as _selected_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1220_fun_core import (
    BACKGROUNDS,
    BALANCE_QUESTIONS,
    BINGO_WORDS,
    BUSINESSES,
    CARD_BACKS,
    CHAOS_EVENTS,
    EXPEDITIONS,
    EVOLUTIONS,
    NPCS,
    PETS,
    SECRET_HINTS,
    SHADOW_QUIZZES,
    TABLE_SKINS,
    TITLES,
    VERSION,
    advance_expedition,
    assign_secret_friends,
    audit_catalogues,
    bingo_lines,
    business_income,
    business_key,
    compatibility_score,
    event_key,
    expedition_key,
    fortune_for,
    liar_roles,
    mafia_roles,
    make_bingo,
    normalize_token,
    reward_once,
    sanitize_anonymous_message,
    secret_flags,
    stable_pick,
    stable_seed,
    start_expedition,
    unlock_cosmetics,
)

KST = timezone(timedelta(hours=9))
PATCH_DATE = "2026-08-05"
MAX_ACTIVE_PARTY_MINUTES = 90

_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_COMMAND_EN = {
    "!혼돈축제":"!chaosfestival", "!재미기능":"!funhub", "!돌발이벤트":"!chaosevent", "!이벤트참가":"!joinevent", "!이벤트순위":"!eventranking", "!이벤트설정":"!eventsettings",
    "!파티게임":"!partygames", "!폭탄돌리기":"!hotpotato", "!폭탄참가":"!joinbomb", "!폭탄넘기기":"!passbomb", "!마피아참가":"!joinmafia", "!마피아시작":"!startmafia", "!마피아투표":"!mafiavote",
    "!라이어게임":"!liargame", "!라이어참가":"!joinliar", "!라이어시작":"!startliar", "!라이어투표":"!liarvote", "!그림자추리":"!shadowquiz", "!그림자정답":"!shadowanswer",
    "!생존룰렛":"!survivalroulette", "!생존선택":"!survivalpick", "!심리전":"!mindgame", "!심리선택":"!mindchoice", "!축제대화":"!talkabaddon", "!딜러대화":"!dealertalk", "!딜러선물":"!dealergift",
    "!관계도":"!festivalrelations", "!축제인물도감":"!npccatalog", "!오늘의대화":"!dailytalk", "!펫센터":"!petcenter", "!동료뽑기":"!drawcompanion", "!동료먹이":"!feedcompanion", "!동료탐험":"!petexpedition",
    "!동료진화":"!evolvecompanion", "!동료도감":"!companioncatalog", "!펫레이스":"!petrace", "!탐험":"!festivalexpedition", "!파티탐험":"!partyexpedition", "!탐험참가":"!joinpartyexpedition", "!탐험선택":"!expeditionchoice",
    "!탐험가방":"!expeditionbag", "!보물도감":"!treasurecatalog", "!던전순위":"!dungeonranking", "!내사업":"!mybusiness", "!사업개설":"!openbusiness", "!상품설정":"!setproduct", "!직원고용":"!hirestaff",
    "!가게방문":"!visitshop", "!서버상권":"!servermarket", "!사업순위":"!businessranking", "!오늘의명장면":"!dailyhighlight", "!주간예능":"!weeklyvariety", "!월간시상식":"!monthlyawards", "!불운왕":"!unluckiest",
    "!역전왕":"!comebackking", "!블러프분석":"!bluffanalysis", "!축제운세":"!festivalfortune", "!궁합":"!compatibility", "!축제밸런스":"!chaosbalance", "!밸런스선택":"!balancechoice", "!월드컵":"!worldcup", "!월드컵선택":"!worldcupchoice",
    "!랜덤벌칙":"!randompenalty", "!칭찬릴레이":"!praiserelay", "!친목설정":"!socialsettings", "!익명응원":"!anonymouscheer", "!익명응원로그":"!anonymouslog", "!익명응원신고":"!reportanonymous", "!비밀친구":"!secretfriend",
    "!비밀친구참가":"!joinsecretfriend", "!비밀친구시작":"!startsecretfriend", "!서버빙고":"!serverbingo", "!빙고체크":"!bingocheck", "!출석도장":"!attendance", "!생일카드":"!birthdaycard", "!꾸미기센터":"!cosmeticcenter",
    "!프로필꾸미기":"!customizeprofile", "!칭호도감":"!titlecatalog", "!배경도감":"!backgroundcatalog", "!카드뒷면":"!cardbacks", "!테이블스킨":"!tableskins", "!트로피룸":"!chaostrophyroom", "!공동트로피룸":"!guildtrophyroom",
    "!비밀힌트":"!secrethint", "!수상한상인":"!mysteriousmerchant", "!숨겨진임무":"!hiddenmission", "!전설아이템":"!legendaryitem", "!혼돈설정":"!festivalsettings", "!혼돈백업":"!chaosbackup", "!혼돈복구":"!chaosrestore",
    "!1220통합검수":"!v1220audit", "!테스트":"!test", "!패치노트":"!patchnotes",
}

_AUTO_EN_REPLACEMENTS = (
    ("진행 중인", "active"), ("진행 중", "in progress"), ("참가 가능한", "joinable"), ("찾지 못했습니다", "was not found"), ("필요합니다", "is required"),
    ("이미", "already"), ("완료", "complete"), ("시작", "start"), ("종료", "finished"), ("참가", "join"), ("현재", "current"), ("보상", "reward"),
    ("승리", "victory"), ("패배", "defeat"), ("선택", "choice"), ("투표", "vote"), ("기록", "record"), ("서버", "guild"), ("관리자", "admin"),
    ("사용자", "user"), ("동료", "companion"), ("탐험", "expedition"), ("사업", "business"), ("가게", "shop"), ("친밀도", "affinity"), ("재미 점수", "fun score"),
    ("칩", " chips"), ("명", " players"), ("초", " sec"), ("분", " min"), ("회", " times"), ("점", " pts"), ("줄", " lines"),
    ("켜짐", "enabled"), ("꺼짐", "disabled"), ("없습니다", "none"), ("있습니다", "available"), ("다시", "again"), ("오늘", "today"), ("내일", "tomorrow"),
)

def _auto_en(text: str) -> str:
    value = str(text)
    for ko, en in sorted(_COMMAND_EN.items(), key=lambda item: -len(item[0])):
        value = value.replace(ko, en)
    name_map = {
        "루시안":"Lucian", "미라":"Mira", "도일":"Doyle", "로제":"Rosé", "브릭":"Brick", "세라":"Sera",
        "카페":"Café", "카지노":"Casino", "경마장":"Racetrack", "탐정사무소":"Detective Agency", "방송국":"Studio", "장난감 가게":"Toy Shop", "용병 길드":"Mercenary Guild", "화투 공방":"Hwatu Workshop",
        "정찰":"Scout", "돌진":"Charge", "휴식":"Rest", "공동":"Community", "개인":"Self", "시민":"Citizen", "마피아":"Mafia", "의사":"Doctor", "경찰":"Detective", "광대":"Jester",
        "텍사스홀덤":"Texas Hold'em", "맞고":"Matgo", "고스톱":"Go-Stop", "섯다":"Seotda", "경마":"Horse Racing", "블랙잭":"Blackjack",
    }
    for ko, en in sorted(name_map.items(), key=lambda item: -len(item[0])):
        value = value.replace(ko, en)
    for ko, en in _AUTO_EN_REPLACEMENTS:
        value = value.replace(ko, en)
    if _HANGUL_RE.search(value):
        tokens = re.findall(r"`[^`]+`|<@!?\d+>|<@&\d+>|<t:\d+(?::[A-Za-z])?>|[A-Za-z][A-Za-z0-9 .,'’:+/×%-]*|[0-9][0-9,.]*|[🎪☄️🎉🕵️🤥🎯🧠🎩🔮🧭💼📺🏆☔🔥🎭💞⚖️🎲🌟💌🎁📅🎂🎨🗝️🕯️🏺💾↩️✅❌💣💥🗳️🥚🍖✨🏁🛍️👔🏛️]+", value)
        compact = " ".join(token.strip() for token in tokens if token.strip())
        return ("ABADDON activity update. " + compact).strip()[:1900]
    return value[:1900]

_BINGO_EN = {
    "첫 승리":"First Win", "파산":"Bankruptcy", "경마 적중":"Race Win", "화투 광":"Hwatu Bright", "포커 플러시":"Poker Flush", "아바돈 승리":"Beat ABADDON", "보물 발견":"Find Treasure", "NPC 선물":"NPC Gift",
    "동료 진화":"Companion Evolve", "사업 수익":"Business Profit", "돌발 이벤트":"Chaos Event", "비밀 상인":"Hidden Merchant", "칭찬 받기":"Receive Praise", "출석":"Check-in", "탐험 성공":"Expedition Clear", "월드보스":"World Boss",
    "연합 승리":"Alliance Win", "예약 경기":"Reserved Match", "중계 응원":"Broadcast Cheer", "업적 해금":"Achievement", "전설 아이템":"Legendary Item", "게임 복구":"Game Recovery", "고블린":"Goblin", "운석 파괴":"Meteor Broken", "자유칸":"Free",
}


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1220_chaos_festival", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1220_chaos_festival"] = root
    root.setdefault("schema_version", 3)
    root.setdefault("guilds", {})
    root.setdefault("audit_runs", [])
    return root


def _guild(root: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = root.setdefault("guilds", {})
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("settings", {
        "auto_events": False,
        "event_channel_id": 0,
        "mention_role_id": 0,
        "frequency_minutes": 180,
        "anonymous_enabled": False,
        "social_enabled": True,
        "party_enabled": True,
    })
    row.setdefault("active_event", None)
    row.setdefault("event_stats", {})
    row.setdefault("party", {})
    row.setdefault("businesses", {})
    row.setdefault("social", {})
    row.setdefault("bingo", {})
    row.setdefault("secret_friend", {})
    row.setdefault("anonymous_log", [])
    row.setdefault("trophies", [])
    row.setdefault("backups", {})
    row.setdefault("next_auto_event_at", int(time.time()) + 3600)
    return row


def _fun(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault("v1220_fun", {})
    if not isinstance(row, dict):
        row = {}
        user["v1220_fun"] = row
    row.setdefault("fun_score", 0)
    row.setdefault("event_wins", 0)
    row.setdefault("event_plays", 0)
    row.setdefault("party_wins", 0)
    row.setdefault("party_plays", 0)
    row.setdefault("biggest_reward", 0)
    row.setdefault("npc", {})
    row.setdefault("pets", {})
    row.setdefault("active_pet", "")
    row.setdefault("pet_expedition", {})
    row.setdefault("expedition", {})
    row.setdefault("treasures", {})
    row.setdefault("expeditions_complete", 0)
    row.setdefault("business_earnings", 0)
    row.setdefault("cosmetics", {})
    row.setdefault("profile", {"title": "festival_rookie", "background": "night_casino", "table": "classic", "card_back": "abaddon"})
    row.setdefault("daily", {})
    row.setdefault("worldcup", {})
    row.setdefault("bingo_marked", {})
    row.setdefault("secret_flags", [])
    row.setdefault("secret_points", 0)
    row.setdefault("legendary_items", [])
    row.setdefault("reward_ledger", {})
    row.setdefault("cooldowns", {})
    unlock_cosmetics(row)
    return row


def _event_id(prefix: str = "C") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _now() -> int:
    return int(time.time())


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _safe_name(member: Any) -> str:
    return str(getattr(member, "display_name", getattr(member, "name", "Survivor")))[:40]


def _cooldown(fun: MutableMapping[str, Any], key: str, seconds: int) -> int:
    now = _now()
    bucket = fun.setdefault("cooldowns", {})
    until = int(bucket.get(key, 0) or 0)
    if until > now:
        return until - now
    bucket[key] = now + max(1, int(seconds))
    return 0


def _award(user: MutableMapping[str, Any], ledger_key: str, amount: int, *, score: int = 1) -> Tuple[bool, int, List[str]]:
    fun = _fun(user)
    result = reward_once(fun, ledger_key, int(amount))
    if not result.ok:
        return False, 0, []
    add_casino_chips(user, int(amount))
    fun["fun_score"] = int(fun.get("fun_score", 0)) + max(0, int(score))
    fun["biggest_reward"] = max(int(fun.get("biggest_reward", 0)), int(amount))
    unlocked = unlock_cosmetics(fun)
    return True, int(amount), unlocked


def _stats_row(grow: MutableMapping[str, Any], user_id: int) -> MutableMapping[str, Any]:
    stats = grow.setdefault("event_stats", {})
    row = stats.setdefault(str(int(user_id)), {"plays": 0, "wins": 0, "damage": 0, "reward": 0})
    if not isinstance(row, dict):
        row = {"plays": 0, "wins": 0, "damage": 0, "reward": 0}
        stats[str(int(user_id))] = row
    return row


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _profile_png(locale: str, name: str, user: Mapping[str, Any]) -> io.BytesIO:
    fun = _fun(user if isinstance(user, MutableMapping) else dict(user))
    profile = fun.get("profile", {}) if isinstance(fun.get("profile"), Mapping) else {}
    title = TITLES.get(str(profile.get("title", "festival_rookie")), TITLES["festival_rookie"])
    bg = BACKGROUNDS.get(str(profile.get("background", "night_casino")), BACKGROUNDS["night_casino"])
    table = TABLE_SKINS.get(str(profile.get("table", "classic")), TABLE_SKINS["classic"])
    back = CARD_BACKS.get(str(profile.get("card_back", "abaddon")), CARD_BACKS["abaddon"])
    image = Image.new("RGB", (1100, 600), (16, 18, 28))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 35, 1065, 565), radius=30, fill=(28, 31, 48), outline=(170, 125, 255), width=4)
    draw.text((75, 70), "ABADDON CHAOS PROFILE", font=_font(44), fill=(245, 235, 255))
    draw.text((75, 135), name[:28], font=_font(52), fill=(255, 215, 115))
    draw.text((75, 215), f"{title[0]} {title[1] if locale == 'ko' else title[2]}", font=_font(32), fill=(235, 235, 245))
    rows = [
        ("🎪 Fun Score" if locale != "ko" else "🎪 재미 점수", int(fun.get("fun_score", 0))),
        ("🎉 Party Wins" if locale != "ko" else "🎉 파티 승리", int(fun.get("party_wins", 0))),
        ("🧭 Expeditions" if locale != "ko" else "🧭 탐험 완료", int(fun.get("expeditions_complete", 0))),
        ("💼 Business" if locale != "ko" else "💼 사업 수익", int(fun.get("business_earnings", 0))),
    ]
    y = 295
    for label, value in rows:
        draw.text((85, y), label, font=_font(25), fill=(205, 205, 220))
        draw.text((440, y), f"{value:,}", font=_font(27), fill=(255, 255, 255))
        y += 55
    draw.rounded_rectangle((650, 145, 1010, 485), radius=25, fill=(20, 22, 35), outline=(90, 90, 120), width=3)
    visual = [
        f"{bg[0]} {bg[1] if locale == 'ko' else bg[2]}",
        f"{table[0]} {table[1] if locale == 'ko' else table[2]}",
        f"{back[0]} {back[1] if locale == 'ko' else back[2]}",
    ]
    draw.text((690, 190), "STYLE" if locale != "ko" else "꾸미기", font=_font(31), fill=(190, 155, 255))
    for idx, line in enumerate(visual):
        draw.text((690, 260 + idx * 70), line, font=_font(24), fill=(235, 235, 245))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


def _bingo_png(locale: str, guild_name: str, board: Sequence[str], marked: Iterable[int]) -> io.BytesIO:
    marked_set = {int(x) for x in marked}
    image = Image.new("RGB", (1100, 850), (17, 20, 30))
    draw = ImageDraw.Draw(image)
    draw.text((50, 35), f"ABADDON SERVER BINGO · {guild_name[:28]}", font=_font(38), fill=(245, 235, 255))
    x0, y0, cell = 70, 115, 190
    for idx in range(25):
        r, c = divmod(idx, 5)
        x, y = x0 + c * cell, y0 + r * 135
        active = idx in marked_set or idx == 12
        fill = (70, 55, 105) if active else (31, 35, 49)
        draw.rounded_rectangle((x, y, x + 170, y + 115), radius=14, fill=fill, outline=(160, 125, 230), width=2)
        text = str(board[idx] if idx < len(board) else "-")
        if locale != "ko":
            text = _BINGO_EN.get(text, text)
        draw.text((x + 12, y + 18), f"{idx + 1:02d}", font=_font(18), fill=(175, 175, 195))
        draw.text((x + 12, y + 55), text[:11], font=_font(21), fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


class FunHubSelect(discord.ui.Select):
    def __init__(self, locale: str):
        self.locale = locale
        options = [
            discord.SelectOption(label=_t(locale, "돌발 이벤트", "Chaos Events"), value="events"),
            discord.SelectOption(label=_t(locale, "파티게임", "Party Games"), value="party"),
            discord.SelectOption(label=_t(locale, "NPC·동료", "NPCs & Companions"), value="life"),
            discord.SelectOption(label=_t(locale, "탐험·사업", "Expedition & Business"), value="world"),
            discord.SelectOption(label=_t(locale, "친목·꾸미기", "Social & Cosmetics"), value="social"),
            discord.SelectOption(label=_t(locale, "비밀 콘텐츠", "Secret Content"), value="secret"),
        ]
        super().__init__(placeholder=_t(locale, "놀거리를 선택하세요", "Choose an activity"), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        loc = self.locale
        value = self.values[0]
        texts = {
            "events": _t(loc, "`!돌발이벤트` · `!이벤트참가` · `!이벤트순위`", "`!chaosevent` · `!joinevent` · `!eventranking`"),
            "party": _t(loc, "`!폭탄돌리기` · `!마피아` · `!라이어게임` · `!생존룰렛` · `!심리전`", "`!hotpotato` · `!mafia` · `!liargame` · `!survivalroulette` · `!mindgame`"),
            "life": _t(loc, "`!딜러대화` · `!딜러선물` · `!관계도` · `!펫센터` · `!동료뽑기`", "`!dealertalk` · `!dealergift` · `!relationships` · `!petcenter` · `!drawcompanion`"),
            "world": _t(loc, "`!탐험` · `!파티탐험` · `!내사업` · `!사업개설` · `!서버상권`", "`!festivalexpedition` · `!partyexpedition` · `!mybusiness` · `!openbusiness` · `!servermarket`"),
            "social": _t(loc, "`!축제운세` · `!궁합` · `!축제밸런스` · `!서버빙고` · `!꾸미기센터`", "`!festivalfortune` · `!compatibility` · `!balancegame` · `!serverbingo` · `!cosmeticcenter`"),
            "secret": _t(loc, "`!비밀힌트`만 공개합니다. 조건을 만족하면 숨겨진 명령과 유물이 열립니다.", "Only `!secrethint` is public. Hidden commands and relics unlock through play."),
        }
        embed = discord.Embed(title=_t(loc, "🎪 혼돈의 축제", "🎪 Chaos Festival"), description=texts[value], color=discord.Color.dark_purple())
        await interaction.response.edit_message(embed=embed, view=self.view)


class FunHubView(discord.ui.View):
    def __init__(self, locale: str, owner_id: int):
        super().__init__(timeout=300)
        self.locale = locale
        self.owner_id = int(owner_id)
        self.add_item(FunHubSelect(locale))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(
                _t(self.locale, "이 메뉴는 명령을 실행한 사용자만 조작할 수 있습니다.", "Only the user who opened this menu can use it."),
                ephemeral=True,
            )
            return False
        return True


class EventActionButton(discord.ui.Button):
    def __init__(self, locale: str, action: str, emoji: Optional[str], style: discord.ButtonStyle, ko: str, en: str):
        # Component emoji payloads can be rejected by Discord even when the glyph
        # renders normally in chat.  Keep the label authoritative and let the
        # global v13.2 fallback remove an emoji if the API rejects it.
        super().__init__(label=_t(locale, ko, en), emoji=emoji or None, style=style)
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, ChaosEventView):
            await view.handler(interaction, self.action)


class ChaosEventView(discord.ui.View):
    def __init__(self, locale: str, handler: Callable[[discord.Interaction, str], Any]):
        super().__init__(timeout=300)
        self.locale = locale
        self.handler = handler
        self.add_item(EventActionButton(locale, "참가", "⚔️", discord.ButtonStyle.danger, "참가 / 공격", "Join / Attack"))
        self.add_item(EventActionButton(locale, "1", None, discord.ButtonStyle.secondary, "선택 1", "Choice 1"))
        self.add_item(EventActionButton(locale, "2", None, discord.ButtonStyle.secondary, "선택 2", "Choice 2"))
        self.add_item(EventActionButton(locale, "3", None, discord.ButtonStyle.secondary, "선택 3", "Choice 3"))


def register_v1220_chaos_festival_complete(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1220_registered", False):
        return
    bot._abaddon_v1220_registered = True
    root = _root(world_data)

    def locale(ctx: commands.Context) -> str:
        return _ctx_locale(bot, ctx)

    async def send(ctx: commands.Context, content: Any = None, **kwargs: Any) -> Any:
        if isinstance(content, str) and locale(ctx) != "ko":
            content = _auto_en(content)
        return await ctx.send(content=content, **kwargs)

    def grow(ctx: commands.Context) -> MutableMapping[str, Any]:
        return _guild(root, int(getattr(ctx.guild, "id", 0) or 0))

    def event_embed(loc: str, event: Mapping[str, Any]) -> discord.Embed:
        spec = CHAOS_EVENTS.get(str(event.get("type", "")), {})
        title = f"{spec.get('emoji', '🎪')} {spec.get('ko') if loc == 'ko' else spec.get('en')}"
        description = _t(loc, "서버 전체가 참여하는 돌발 이벤트입니다.", "A guild-wide chaos event is active.")
        embed = _dashboard(bot, loc, title, title, description, description, discord.Color.orange())
        mode = str(spec.get("mode", ""))
        if mode == "raid":
            embed.add_field(name=_t(loc, "남은 체력", "Remaining HP"), value=f"**{max(0, int(event.get('hp', 0))):,}**", inline=True)
        elif mode == "choice":
            embed.add_field(name=_t(loc, "선택", "Choice"), value=_t(loc, "상자 1·2·3 중 하나를 선택하세요.", "Choose chest 1, 2 or 3."), inline=False)
        elif mode == "answer":
            embed.add_field(name=_t(loc, "단서", "Clue"), value=_t(loc, str(event.get("clue", "달빛 아래 종소리를 찾으세요.")), str(event.get("clue_en", "Find the bell under moonlight."))), inline=False)
        elif mode == "teams":
            embed.add_field(name=_t(loc, "팀 배정", "Teams"), value=_t(loc, "참가하면 경찰 또는 강도 팀으로 배정됩니다.", "Join to be assigned Police or Robbers."), inline=False)
        elif mode == "modifier":
            mult = float(spec.get("multiplier", 1.0))
            embed.add_field(name=_t(loc, "축제 배율", "Festival Multiplier"), value=f"×{mult:.2f}", inline=True)
        embed.add_field(name=_t(loc, "종료", "Ends"), value=f"<t:{int(event.get('expires_at', 0))}:R>", inline=True)
        embed.add_field(name=_t(loc, "참가자", "Participants"), value=f"{len(event.get('participants', {})):,}", inline=True)
        embed.set_footer(text=f"{event.get('id', '-') } · " + _t(loc, "같은 보상은 한 번만 지급됩니다.", "Each reward is granted only once."))
        return embed

    def create_event(guild_row: MutableMapping[str, Any], kind: str, channel_id: int) -> MutableMapping[str, Any]:
        key = event_key(kind) or stable_pick(tuple(CHAOS_EVENTS), "auto-event", int(time.time()) // 900, channel_id)
        spec = CHAOS_EVENTS[key]
        now = _now()
        event: MutableMapping[str, Any] = {
            "id": _event_id("EV"), "type": key, "created_at": now,
            "expires_at": now + int(spec.get("duration", 120)), "channel_id": int(channel_id),
            "participants": {}, "resolved": False, "message_id": 0,
        }
        if spec.get("mode") == "raid":
            event["hp"] = int(spec.get("hp", 100))
        if spec.get("mode") == "answer":
            clues = (
                ("거울", "mirror", "달빛 아래에서 얼굴을 빌립니다.", "It borrows a face under moonlight."),
                ("종", "bell", "울리면 유령이 잠시 멈춥니다.", "Its sound makes the ghost pause."),
                ("촛불", "candle", "바람 없이도 흔들립니다.", "It flickers without wind."),
            )
            answer, answer_en, clue, clue_en = stable_pick(clues, event["id"])
            event["answer"] = answer
            event["answer_en"] = answer_en
            event["clue"] = clue
            event["clue_en"] = clue_en
        guild_row["active_event"] = event
        return event

    async def apply_event_action(guild_id: int, user_id: int, choice: str) -> Tuple[str, bool]:
        guild_row = _guild(root, guild_id)
        event = guild_row.get("active_event")
        if not isinstance(event, MutableMapping) or event.get("resolved") or int(event.get("expires_at", 0)) <= _now():
            return "현재 참여 가능한 돌발 이벤트가 없습니다.", False
        uid = str(int(user_id))
        participants = event.setdefault("participants", {})
        if uid in participants:
            return "이미 이 이벤트에 참여했습니다.", False
        key = str(event.get("type", ""))
        spec = CHAOS_EVENTS.get(key, {})
        mode = str(spec.get("mode", ""))
        user = get_user(int(user_id))
        fun = _fun(user)
        fun["event_plays"] = int(fun.get("event_plays", 0)) + 1
        stats = _stats_row(guild_row, int(user_id))
        stats["plays"] = int(stats.get("plays", 0)) + 1
        message = "참가했습니다."
        won = False
        reward = 0
        entry: Dict[str, Any] = {"at": _now(), "choice": str(choice)[:30]}
        if mode == "first":
            reward = int(spec.get("reward", 3000))
            won = True
            event["resolved"] = True
            message = f"황금 고블린을 가장 먼저 붙잡았습니다! +{reward:,}칩"
        elif mode == "choice":
            box = normalize_token(choice)
            if box not in {"1", "2", "3", "상자1", "상자2", "상자3"}:
                return "상자 1·2·3 중 하나를 선택하세요.", False
            number = int(re.sub(r"\D", "", box) or 1)
            roll = stable_seed(event.get("id"), user_id, number) % 100
            if roll < 15:
                message = "미믹이었습니다! 보상은 없지만 살아남았습니다."
            elif roll < 55:
                reward = 700 + roll * 12
                message = f"낡은 보물을 찾았습니다. +{reward:,}칩"
            else:
                reward = int(spec.get("reward", 2800)) + roll * 15
                won = True
                message = f"황금 상자를 열었습니다! +{reward:,}칩"
        elif mode == "raid":
            damage = 12 + stable_seed(event.get("id"), user_id, choice) % 24
            event["hp"] = max(0, int(event.get("hp", 0)) - damage)
            entry["damage"] = damage
            stats["damage"] = int(stats.get("damage", 0)) + damage
            reward = 350
            message = f"{damage} 피해를 입혔습니다. 남은 체력 {int(event.get('hp', 0)):,}"
            if int(event.get("hp", 0)) <= 0:
                event["resolved"] = True
                won = True
                reward += int(spec.get("reward", 5000))
                message += f"\n보스를 쓰러뜨렸습니다! 마무리 보상 +{reward:,}칩"
        elif mode == "answer":
            if normalize_token(choice) in {normalize_token(event.get("answer", "")), normalize_token(event.get("answer_en", ""))}:
                reward = int(spec.get("reward", 3200))
                won = True
                event["resolved"] = True
                message = f"정답입니다! 유령이 사라졌습니다. +{reward:,}칩"
            else:
                message = "유령이 웃으며 사라졌다가 다시 나타났습니다. 오답입니다."
        elif mode == "teams":
            team = "경찰" if stable_seed(event.get("id"), user_id) % 2 == 0 else "강도"
            entry["team"] = team
            message = f"{team} 팀에 배정됐습니다."
            if len(participants) + 1 >= 4:
                winning = "경찰" if stable_seed(event.get("id"), "winner") % 2 == 0 else "강도"
                event["winning_team"] = winning
                event["resolved"] = True
                if team == winning:
                    reward = int(spec.get("reward", 4200))
                    won = True
                    message += f"\n{winning} 팀 승리! +{reward:,}칩"
                else:
                    message += f"\n{winning} 팀이 승리했습니다."
        elif mode == "modifier":
            reward = 500
            message = f"{spec.get('ko')} 참가 도장을 받았습니다. +{reward:,}칩"
        participants[uid] = entry
        if reward:
            granted, amount, _ = _award(user, f"event:{event.get('id')}:{uid}", reward, score=3 if won else 1)
            if granted:
                stats["reward"] = int(stats.get("reward", 0)) + amount
        if won:
            fun["event_wins"] = int(fun.get("event_wins", 0)) + 1
            stats["wins"] = int(stats.get("wins", 0)) + 1
        save_data()
        return message, True

    @bot.command(name="혼돈축제", aliases=["재미기능", "chaosfestival", "funhub"], help="v12.2.0 재미 기능 전체 메뉴를 엽니다.")
    async def chaos_festival(ctx: commands.Context) -> None:
        loc = locale(ctx)
        embed = _dashboard(bot, loc, "🎪 ABADDON 혼돈의 축제", "🎪 ABADDON Chaos Festival", "대량 재미 기능을 분야별로 골라 시작하세요.", "Choose a category and start playing.", discord.Color.dark_purple())
        embed.add_field(name=_t(loc, "구성", "Included"), value=_t(loc, "돌발 이벤트 · 파티게임 · NPC 관계 · 동료 · 탐험 · 사업 · 예능 · 친목 · 꾸미기 · 비밀", "Events · party games · NPCs · companions · expeditions · businesses · variety · social · cosmetics · secrets"), inline=False)
        await send(ctx, embed=embed, view=FunHubView(loc, int(ctx.author.id)))

    @bot.command(name="돌발이벤트", aliases=["chaosevent", "randomevent"], help="현재 돌발 이벤트를 확인하거나 관리자가 즉시 시작합니다.")
    async def chaos_event(ctx: commands.Context, 동작: str = "보기", 종류: str = "") -> None:
        loc = locale(ctx)
        guild_row = grow(ctx)
        token = normalize_token(동작)
        event = guild_row.get("active_event")
        if token in {"시작", "start", "spawn"}:
            if not getattr(ctx.author.guild_permissions, "manage_guild", False):
                await send(ctx, _t(loc, "서버 관리 권한이 필요합니다.", "Manage Server permission is required.")); return
            if isinstance(event, Mapping) and not event.get("resolved") and int(event.get("expires_at", 0)) > _now():
                await send(ctx, _t(loc, "이미 진행 중인 돌발 이벤트가 있습니다.", "A chaos event is already active.")); return
            event = create_event(guild_row, 종류, int(ctx.channel.id))
            save_data()
        if not isinstance(event, Mapping) or event.get("resolved") or int(event.get("expires_at", 0)) <= _now():
            await send(ctx, _t(loc, "현재 진행 중인 돌발 이벤트가 없습니다. 관리자는 `!돌발이벤트 시작 [종류]`로 열 수 있습니다.", "No chaos event is active. Admins can use `!chaosevent start [type]`.")); return

        async def handler(interaction: discord.Interaction, choice: str) -> None:
            # Discord interactions expire quickly.  A large world-data save can
            # take long enough to trigger error 10062, so acknowledge first.
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True, thinking=False)
            except Exception:
                pass
            text, changed = await apply_event_action(int(interaction.guild_id or 0), int(interaction.user.id), choice)
            localized = text if _interaction_locale(bot, interaction) == "ko" else _auto_en(text)
            try:
                await interaction.followup.send(localized, ephemeral=True)
            except Exception:
                # Fallback for older discord.py builds where followup can be
                # unavailable after a failed defer.
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(localized, ephemeral=True)
                except Exception:
                    pass
            if changed:
                current = _guild(root, int(interaction.guild_id or 0)).get("active_event")
                embed = event_embed(loc, current) if isinstance(current, Mapping) else None
                if embed is not None:
                    try:
                        await interaction.message.edit(embed=embed, view=self_view)
                    except Exception:
                        pass

        self_view = ChaosEventView(loc, handler)
        await send(ctx, embed=event_embed(loc, event), view=self_view)

    @bot.command(name="이벤트참가", aliases=["joinevent", "eventaction"], help="진행 중인 돌발 이벤트에 참가합니다.")
    async def join_event(ctx: commands.Context, *, 선택: str = "참가") -> None:
        if not await check_registered(ctx): return
        text, _ = await apply_event_action(int(ctx.guild.id), int(ctx.author.id), 선택)
        await send(ctx, text)

    @bot.command(name="이벤트순위", aliases=["eventranking", "chaosranking"], help="서버 돌발 이벤트 순위를 확인합니다.")
    async def event_ranking(ctx: commands.Context) -> None:
        loc = locale(ctx)
        rows = []
        for uid, data in grow(ctx).get("event_stats", {}).items():
            if not isinstance(data, Mapping): continue
            score = int(data.get("wins", 0)) * 10 + int(data.get("damage", 0)) // 20 + int(data.get("plays", 0))
            rows.append((score, int(uid), data))
        rows.sort(reverse=True)
        lines = []
        for rank, (score, uid, data) in enumerate(rows[:15], 1):
            member = ctx.guild.get_member(uid)
            name = _safe_name(member) if member else str(uid)
            lines.append(f"`{rank:02d}` **{name}** · {score}점 · 승리 {int(data.get('wins',0))} · 피해 {int(data.get('damage',0)):,}")
        await send(ctx, "\n".join(lines) if lines else _t(loc, "아직 이벤트 기록이 없습니다.", "No event records yet."))

    @bot.command(name="이벤트설정", aliases=["eventsettings", "chaossettings"], help="돌발 이벤트 자동 출현 채널과 빈도를 설정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def event_settings(ctx: commands.Context, 상태: str = "보기", 채널: Optional[discord.TextChannel] = None, 빈도분: int = 180) -> None:
        loc = locale(ctx)
        settings = grow(ctx).setdefault("settings", {})
        token = normalize_token(상태)
        if token in {"켜기", "on", "enable"}:
            settings["auto_events"] = True
            settings["event_channel_id"] = int((채널 or ctx.channel).id)
            settings["frequency_minutes"] = max(30, min(1440, int(빈도분)))
            grow(ctx)["next_auto_event_at"] = _now() + settings["frequency_minutes"] * 60
            save_data()
        elif token in {"끄기", "off", "disable"}:
            settings["auto_events"] = False
            save_data()
        embed = _dashboard(bot, loc, "☄️ 돌발 이벤트 설정", "☄️ Chaos Event Settings", "자동 출현은 서버별 기본 꺼짐입니다.", "Automatic spawning is disabled by default per guild.", discord.Color.orange())
        embed.add_field(name=_t(loc, "자동 출현", "Auto Spawn"), value=_t(loc, "켜짐", "Enabled") if settings.get("auto_events") else _t(loc, "꺼짐", "Disabled"), inline=True)
        embed.add_field(name=_t(loc, "채널", "Channel"), value=f"<#{int(settings.get('event_channel_id',0))}>" if int(settings.get("event_channel_id",0)) else "-", inline=True)
        embed.add_field(name=_t(loc, "빈도", "Frequency"), value=_t(loc, f"{int(settings.get('frequency_minutes',180))}분", f"{int(settings.get('frequency_minutes',180))} min"), inline=True)
        await send(ctx, embed=embed)

    # ------------------------------------------------------------------
    # Party games
    # ------------------------------------------------------------------
    def party_bucket(ctx: commands.Context) -> MutableMapping[str, Any]:
        return grow(ctx).setdefault("party", {})

    def current_party(ctx: commands.Context, kind: str) -> Optional[MutableMapping[str, Any]]:
        row = party_bucket(ctx).get(kind)
        return row if isinstance(row, MutableMapping) else None

    def party_user_play(user_id: int) -> MutableMapping[str, Any]:
        fun = _fun(get_user(user_id))
        fun["party_plays"] = int(fun.get("party_plays", 0)) + 1
        return fun

    def party_reward(user_id: int, session_id: str, amount: int, *, winner: bool = False) -> None:
        user = get_user(user_id)
        fun = _fun(user)
        if winner:
            fun["party_wins"] = int(fun.get("party_wins", 0)) + 1
        _award(user, f"party:{session_id}:{user_id}", amount, score=3 if winner else 1)

    @bot.command(name="파티게임", aliases=["partygames", "partyhub"], help="폭탄·마피아·라이어·그림자·생존·심리전 메뉴를 엽니다.")
    async def party_games(ctx: commands.Context) -> None:
        loc = locale(ctx)
        embed = _dashboard(bot, loc, "🎉 파티게임 센터", "🎉 Party Game Center", "짧게 웃고 떠들 수 있는 서버용 게임입니다.", "Quick social games for the whole server.", discord.Color.magenta())
        embed.add_field(name="💣", value=_t(loc, "`!폭탄돌리기` → `!폭탄참가` → `!폭탄넘기기 @상대`", "`!hotpotato` → `!joinbomb` → `!passbomb @user`"), inline=False)
        embed.add_field(name="🕵️", value=_t(loc, "`!마피아` · `!마피아참가` · `!마피아시작` · `!마피아투표`", "`!mafia` · `!joinmafia` · `!startmafia` · `!mafiavote`"), inline=False)
        embed.add_field(name="🤥", value=_t(loc, "`!라이어게임` · `!라이어참가` · `!라이어시작` · `!라이어투표`", "`!liargame` · `!joinliar` · `!startliar` · `!liarvote`"), inline=False)
        embed.add_field(name="🎯", value=_t(loc, "`!그림자추리` · `!생존룰렛` · `!심리전`", "`!shadowquiz` · `!survivalroulette` · `!mindgame`"), inline=False)
        await send(ctx, embed=embed)

    @bot.command(name="폭탄돌리기", aliases=["hotpotato", "bombgame"], help="폭탄 돌리기 로비를 엽니다.")
    async def hot_potato(ctx: commands.Context, 제한초: int = 60) -> None:
        if not await check_registered(ctx): return
        bucket = party_bucket(ctx)
        existing = bucket.get("bomb")
        if isinstance(existing, Mapping) and existing.get("status") in {"lobby", "running"} and int(existing.get("expires_at", 0)) > _now():
            await send(ctx, "이미 폭탄 게임이 진행 중입니다. `!폭탄참가`로 들어오세요."); return
        session = {
            "id": _event_id("BOMB"), "status": "lobby", "host_id": int(ctx.author.id),
            "participants": [int(ctx.author.id)], "holder_id": int(ctx.author.id),
            "channel_id": int(ctx.channel.id), "created_at": _now(),
            "expires_at": _now() + max(30, min(180, int(제한초))), "passes": 0,
        }
        bucket["bomb"] = session
        party_user_play(int(ctx.author.id))
        save_data()
        await send(ctx, f"💣 폭탄 돌리기 `{session['id']}` 로비가 열렸습니다.\n`!폭탄참가` 후 방장이 `!폭탄넘기기 @상대`를 하면 시작됩니다. 제한 {max(30,min(180,int(제한초)))}초")

    @bot.command(name="폭탄참가", aliases=["joinbomb", "joinhotpotato"], help="진행 중인 폭탄 돌리기에 참가합니다.")
    async def join_bomb(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        session = current_party(ctx, "bomb")
        if not session or session.get("status") not in {"lobby", "running"}:
            await send(ctx, "참가 가능한 폭탄 게임이 없습니다."); return
        players = session.setdefault("participants", [])
        uid = int(ctx.author.id)
        if uid not in players:
            players.append(uid)
            party_user_play(uid)
            save_data()
        await send(ctx, f"💣 참가 완료 · 현재 {len(players)}명")

    @bot.command(name="폭탄넘기기", aliases=["passbomb", "throwbomb"], help="내가 가진 폭탄을 참가자에게 넘깁니다.")
    async def pass_bomb(ctx: commands.Context, 대상: discord.Member) -> None:
        session = current_party(ctx, "bomb")
        if not session or session.get("status") not in {"lobby", "running"}:
            await send(ctx, "진행 중인 폭탄 게임이 없습니다."); return
        uid = int(ctx.author.id); target = int(대상.id)
        players = session.setdefault("participants", [])
        if uid != int(session.get("holder_id", 0)):
            await send(ctx, "지금 폭탄을 들고 있는 사람이 아닙니다."); return
        if target not in players or target == uid:
            await send(ctx, "참가 중인 다른 사람에게만 넘길 수 있습니다."); return
        session["holder_id"] = target
        session["status"] = "running"
        session["passes"] = int(session.get("passes", 0)) + 1
        jitter = 8 + stable_seed(session.get("id"), session["passes"]) % 18
        session["expires_at"] = min(int(session.get("expires_at", _now() + 60)), _now() + jitter)
        save_data()
        await send(ctx, f"💣 {_safe_name(ctx.author)} → **{_safe_name(대상)}** · 폭발까지 <t:{int(session['expires_at'])}:R>")

    @bot.command(name="마피아", aliases=["mafia", "werewolf"], help="마피아 게임 로비를 엽니다.")
    async def mafia_lobby(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        bucket = party_bucket(ctx)
        existing = bucket.get("mafia")
        if isinstance(existing, Mapping) and existing.get("status") in {"lobby", "running"}:
            await send(ctx, "이미 마피아 게임이 진행 중입니다."); return
        bucket["mafia"] = {
            "id": _event_id("MAF"), "status": "lobby", "host_id": int(ctx.author.id),
            "channel_id": int(ctx.channel.id), "participants": [int(ctx.author.id)], "roles": {},
            "votes": {}, "alive": [int(ctx.author.id)], "created_at": _now(), "expires_at": _now() + 1800,
        }
        party_user_play(int(ctx.author.id)); save_data()
        await send(ctx, "🕵️ 마피아 로비가 열렸습니다. `!마피아참가`로 4명 이상 모인 뒤 방장이 `!마피아시작`을 실행하세요. 역할은 DM으로만 전달됩니다.")

    @bot.command(name="마피아참가", aliases=["joinmafia", "joinwerewolf"], help="마피아 로비에 참가합니다.")
    async def join_mafia(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        session = current_party(ctx, "mafia")
        if not session or session.get("status") != "lobby":
            await send(ctx, "참가 가능한 마피아 로비가 없습니다."); return
        players = session.setdefault("participants", []); uid = int(ctx.author.id)
        if uid not in players:
            players.append(uid); session["alive"] = list(players); party_user_play(uid); save_data()
        await send(ctx, f"🕵️ 마피아 참가 완료 · {len(players)}명")

    @bot.command(name="마피아시작", aliases=["startmafia", "startwerewolf"], help="마피아 역할을 배정하고 게임을 시작합니다.")
    async def start_mafia(ctx: commands.Context) -> None:
        session = current_party(ctx, "mafia")
        if not session or session.get("status") != "lobby":
            await send(ctx, "시작할 마피아 로비가 없습니다."); return
        if int(ctx.author.id) != int(session.get("host_id", 0)):
            await send(ctx, "방장만 시작할 수 있습니다."); return
        players = list(session.get("participants", []))
        roles = mafia_roles(players, session.get("id"))
        if not roles:
            await send(ctx, "마피아는 최소 4명이 필요합니다."); return
        session["roles"] = {str(k): v for k, v in roles.items()}
        session["alive"] = players; session["status"] = "running"; session["votes"] = {}; session["round"] = 1
        failed = []
        for uid, role in roles.items():
            member = ctx.guild.get_member(uid)
            if member:
                try:
                    member_loc = _selected_locale(bot, uid, ctx.guild.id)
                    role_en = {"마피아":"Mafia", "의사":"Doctor", "경찰":"Detective", "광대":"Jester", "시민":"Citizen"}.get(role, role)
                    await member.send(_t(member_loc, f"🕵️ **ABADDON 마피아 역할: {role}**\n서버에서 토론 후 `!마피아투표 @대상`을 사용하세요.", f"🕵️ **ABADDON Mafia Role: {role_en}**\nDiscuss in the guild, then use `!mafiavote @target`."))
                except Exception:
                    failed.append(uid)
        save_data()
        await send(ctx, f"🕵️ 역할 배정 완료 · {len(players)}명 · DM 실패 {len(failed)}명\n토론 후 `!마피아투표 @대상`을 사용하세요. 비밀 역할은 공개하지 마세요.")

    @bot.command(name="마피아투표", aliases=["mafiavote", "werewolfvote"], help="마피아 게임에서 처형 대상을 투표합니다.")
    async def mafia_vote(ctx: commands.Context, 대상: discord.Member) -> None:
        session = current_party(ctx, "mafia")
        if not session or session.get("status") != "running":
            await send(ctx, "진행 중인 마피아 게임이 없습니다."); return
        uid = int(ctx.author.id); target = int(대상.id); alive = [int(x) for x in session.get("alive", [])]
        if uid not in alive or target not in alive or uid == target:
            await send(ctx, "생존한 다른 참가자에게만 투표할 수 있습니다."); return
        votes = session.setdefault("votes", {}); votes[str(uid)] = target; save_data()
        await send(ctx, f"🗳️ {_safe_name(ctx.author)}의 투표가 기록됐습니다. ({len(votes)}/{len(alive)})")
        if len(votes) < len(alive): return
        counts = Counter(int(v) for v in votes.values())
        eliminated = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        roles = session.get("roles", {})
        role = str(roles.get(str(eliminated), "시민"))
        alive = [x for x in alive if x != eliminated]
        session["alive"] = alive; session["votes"] = {}
        mafias = [x for x in alive if str(roles.get(str(x))) == "마피아"]
        civilians = [x for x in alive if str(roles.get(str(x))) != "마피아"]
        finished = role == "마피아" or len(mafias) >= len(civilians)
        if finished:
            winners = civilians if role == "마피아" else mafias
            session["status"] = "finished"
            for winner in winners:
                party_reward(int(winner), str(session.get("id")), 2200, winner=True)
            save_data()
            names = [f"<@{x}>" for x in winners]
            await send(ctx, f"⚖️ <@{eliminated}> 처형 · 역할 **{role}**\n게임 종료! 승리: {', '.join(names) or '없음'}")
        else:
            session["round"] = int(session.get("round", 1)) + 1; save_data()
            await send(ctx, f"⚖️ <@{eliminated}> 처형 · 역할 **{role}**\n다음 토론 라운드가 시작됩니다.")

    @bot.command(name="라이어게임", aliases=["liargame", "wordliar"], help="라이어 게임 로비를 엽니다.")
    async def liar_lobby(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        bucket = party_bucket(ctx)
        existing = bucket.get("liar")
        if isinstance(existing, Mapping) and existing.get("status") in {"lobby", "running"}:
            await send(ctx, "이미 라이어 게임이 진행 중입니다."); return
        bucket["liar"] = {"id": _event_id("LIAR"), "status": "lobby", "host_id": int(ctx.author.id), "channel_id": int(ctx.channel.id), "participants": [int(ctx.author.id)], "votes": {}, "created_at": _now(), "expires_at": _now() + 1800}
        party_user_play(int(ctx.author.id)); save_data()
        await send(ctx, "🤥 라이어 로비가 열렸습니다. `!라이어참가`로 3명 이상 모인 뒤 `!라이어시작`을 실행하세요.")

    @bot.command(name="라이어참가", aliases=["joinliar", "joinliargame"], help="라이어 게임에 참가합니다.")
    async def join_liar(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        session = current_party(ctx, "liar")
        if not session or session.get("status") != "lobby":
            await send(ctx, "참가 가능한 라이어 로비가 없습니다."); return
        players = session.setdefault("participants", []); uid = int(ctx.author.id)
        if uid not in players:
            players.append(uid); party_user_play(uid); save_data()
        await send(ctx, f"🤥 라이어 참가 완료 · {len(players)}명")

    @bot.command(name="라이어시작", aliases=["startliar", "startliargame"], help="라이어 단어를 DM으로 배정합니다.")
    async def start_liar(ctx: commands.Context) -> None:
        session = current_party(ctx, "liar")
        if not session or session.get("status") != "lobby":
            await send(ctx, "시작할 라이어 로비가 없습니다."); return
        if int(ctx.author.id) != int(session.get("host_id", 0)):
            await send(ctx, "방장만 시작할 수 있습니다."); return
        result = liar_roles(session.get("participants", []), session.get("id"))
        if not result.ok:
            await send(ctx, "라이어 게임은 최소 3명이 필요합니다."); return
        payload = result.payload
        session.update({"status": "running", "liar_id": int(payload["liar_id"]), "normal_word": payload["normal"], "liar_word": payload["liar_word"], "votes": {}})
        failed = 0
        for uid, word in payload["words"].items():
            member = ctx.guild.get_member(int(uid))
            if member:
                try:
                    member_loc = _selected_locale(bot, uid, ctx.guild.id)
                    word_en = {"사과":"apple", "배":"pear", "고스톱":"Go-Stop", "섯다":"Seotda", "커피":"coffee", "홍차":"tea", "달":"moon", "태양":"sun", "경마":"horse racing", "자동차 경주":"car racing", "고양이":"cat", "여우":"fox", "카지노":"casino", "놀이공원":"theme park"}.get(str(word), str(word))
                    await member.send(_t(member_loc, f"🤥 당신의 단어는 **{word}** 입니다. 대화에서 너무 직접 말하지 마세요.", f"🤥 Your word is **{word_en}**. Do not say it too directly."))
                except Exception:
                    failed += 1
        save_data()
        await send(ctx, f"🤥 단어 배정 완료 · DM 실패 {failed}명\n서로 설명한 뒤 `!라이어투표 @대상`을 사용하세요.")

    @bot.command(name="라이어투표", aliases=["liarvote", "wordliarvote"], help="라이어로 의심되는 참가자에게 투표합니다.")
    async def liar_vote(ctx: commands.Context, 대상: discord.Member) -> None:
        session = current_party(ctx, "liar")
        if not session or session.get("status") != "running":
            await send(ctx, "진행 중인 라이어 게임이 없습니다."); return
        uid = int(ctx.author.id); target = int(대상.id); players = [int(x) for x in session.get("participants", [])]
        if uid not in players or target not in players:
            await send(ctx, "참가자만 참가자에게 투표할 수 있습니다."); return
        votes = session.setdefault("votes", {}); votes[str(uid)] = target; save_data()
        await send(ctx, f"🗳️ 투표 기록 ({len(votes)}/{len(players)})")
        if len(votes) < len(players): return
        counts = Counter(int(v) for v in votes.values())
        accused = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        liar_id = int(session.get("liar_id", 0)); caught = accused == liar_id
        winners = [x for x in players if (x != liar_id) == caught]
        for winner in winners:
            party_reward(winner, str(session.get("id")), 1600, winner=True)
        session["status"] = "finished"; save_data()
        await send(ctx, f"🤥 지목: <@{accused}> · 실제 라이어: <@{liar_id}>\n일반 단어 **{session.get('normal_word')}** / 라이어 단어 **{session.get('liar_word')}**\n{'시민 승리' if caught else '라이어 승리'}")

    @bot.command(name="그림자추리", aliases=["shadowquiz", "silhouettequiz"], help="그림자·단서 추리 문제를 시작합니다.")
    async def shadow_quiz(ctx: commands.Context) -> None:
        bucket = party_bucket(ctx)
        existing = bucket.get("shadow")
        if isinstance(existing, Mapping) and int(existing.get("expires_at", 0)) > _now() and not existing.get("resolved"):
            await send(ctx, "이미 그림자 문제가 진행 중입니다."); return
        emoji, clue_ko, clue_en, answer_ko, answer_en = stable_pick(SHADOW_QUIZZES, ctx.guild.id, _now() // 120)
        bucket["shadow"] = {"id": _event_id("SHD"), "emoji": emoji, "clue_ko": clue_ko, "clue_en": clue_en, "answers": [answer_ko, answer_en], "resolved": False, "expires_at": _now() + 120, "channel_id": int(ctx.channel.id)}
        save_data()
        hidden = "◼️" * 5
        await send(ctx, _t(locale(ctx), f"🕶️ **그림자 추리**\n{hidden}\n단서: {clue_ko}\n`!그림자정답 정답`", f"🕶️ **Shadow Quiz**\n{hidden}\nClue: {clue_en}\n`!shadowanswer answer`"))

    @bot.command(name="그림자정답", aliases=["shadowanswer", "silhouetteanswer"], help="그림자 추리 정답을 제출합니다.")
    async def shadow_answer(ctx: commands.Context, *, 정답: str) -> None:
        session = current_party(ctx, "shadow")
        if not session or session.get("resolved") or int(session.get("expires_at", 0)) <= _now():
            await send(ctx, "진행 중인 그림자 문제가 없습니다."); return
        if normalize_token(정답) not in {normalize_token(x) for x in session.get("answers", [])}:
            await send(ctx, "아쉽지만 오답입니다."); return
        session["resolved"] = True
        party_user_play(int(ctx.author.id)); party_reward(int(ctx.author.id), str(session.get("id")), 1200, winner=True); save_data()
        await send(ctx, f"✅ 정답! **{session.get('emoji')} {session.get('answers',[정답])[0]}** · +1,200칩")

    @bot.command(name="생존룰렛", aliases=["survivalroulette", "saferoulette"], help="안전 구역을 고르는 생존 룰렛을 시작합니다.")
    async def survival_roulette(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        bucket = party_bucket(ctx)
        existing = bucket.get("survival")
        if isinstance(existing, Mapping) and existing.get("status") == "running":
            await send(ctx, "이미 생존 룰렛이 진행 중입니다."); return
        bucket["survival"] = {"id": _event_id("SURV"), "status": "running", "round": 1, "alive": [int(ctx.author.id)], "choices": {}, "channel_id": int(ctx.channel.id), "expires_at": _now() + 180}
        party_user_play(int(ctx.author.id)); save_data()
        await send(ctx, "🎯 생존 룰렛 시작! 참가자는 `!생존선택 1`, `2`, `3` 중 하나를 고르세요. 첫 선택으로 자동 참가합니다.")

    @bot.command(name="생존선택", aliases=["survivalpick", "safezone"], help="생존 룰렛의 안전 구역을 선택합니다.")
    async def survival_pick(ctx: commands.Context, 번호: int) -> None:
        session = current_party(ctx, "survival")
        if not session or session.get("status") != "running":
            await send(ctx, "진행 중인 생존 룰렛이 없습니다."); return
        if int(번호) not in {1, 2, 3}:
            await send(ctx, "1·2·3 중 하나를 선택하세요."); return
        uid = int(ctx.author.id); alive = session.setdefault("alive", [])
        if uid not in alive:
            alive.append(uid); party_user_play(uid)
        choices = session.setdefault("choices", {}); choices[str(uid)] = int(번호); save_data()
        await send(ctx, f"🎯 {_safe_name(ctx.author)} 선택 완료 ({len(choices)}/{len(alive)})")
        if len(alive) < 2 or len(choices) < len(alive): return
        safe = 1 + stable_seed(session.get("id"), session.get("round")) % 3
        survivors = [x for x in alive if int(choices.get(str(x), 0)) == safe]
        session["round"] = int(session.get("round", 1)) + 1; session["choices"] = {}
        if len(survivors) <= 1:
            winner = survivors[0] if survivors else stable_pick(alive, session.get("id"), "mercy")
            session["status"] = "finished"
            party_reward(int(winner), str(session.get("id")), 2000, winner=True)
            save_data(); await send(ctx, f"💥 안전 구역은 **{safe}번**! 최후의 생존자 <@{winner}> · +2,000칩")
        else:
            session["alive"] = survivors; save_data(); await send(ctx, f"💥 안전 구역은 **{safe}번** · 생존 {len(survivors)}명\n다음 구역을 다시 선택하세요.")

    @bot.command(name="심리전", aliases=["mindgame", "betrayalbutton"], help="개인 보상과 공동 보상 사이에서 선택하는 심리전을 시작합니다.")
    async def mind_game(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        bucket = party_bucket(ctx)
        existing = bucket.get("mind")
        if isinstance(existing, Mapping) and existing.get("status") == "running":
            await send(ctx, "이미 심리전이 진행 중입니다."); return
        bucket["mind"] = {"id": _event_id("MIND"), "status": "running", "votes": {}, "channel_id": int(ctx.channel.id), "expires_at": _now() + 90}
        save_data()
        await send(ctx, "🧠 심리전 시작! `!심리선택 공동` 또는 `!심리선택 개인`\n공동이 과반이면 공동 선택자 전원 보상, 개인이 과반이면 첫 개인 선택자만 큰 보상을 받습니다.")

    async def resolve_mind(ctx: commands.Context, session: MutableMapping[str, Any]) -> None:
        votes = session.get("votes", {}) if isinstance(session.get("votes"), Mapping) else {}
        counts = Counter(votes.values())
        common = int(counts.get("공동", 0)); selfish = int(counts.get("개인", 0))
        if common >= selfish:
            winners = [int(uid) for uid, vote in votes.items() if vote == "공동"]
            amount = 900
            result = "공동 보상 승리"
        else:
            selfish_players = [int(uid) for uid, vote in votes.items() if vote == "개인"]
            winners = selfish_players[:1]
            amount = 2600
            result = "개인 보상 승리"
        for uid in winners:
            party_reward(uid, str(session.get("id")), amount, winner=True)
        session["status"] = "finished"; save_data()
        await send(ctx, f"🧠 **{result}** · 공동 {common} / 개인 {selfish}\n승자: {', '.join(f'<@{x}>' for x in winners) or '없음'}")

    @bot.command(name="심리선택", aliases=["mindchoice", "betrayalchoice"], help="심리전에서 공동 또는 개인을 선택합니다.")
    async def mind_choice(ctx: commands.Context, 선택: str) -> None:
        session = current_party(ctx, "mind")
        if not session or session.get("status") != "running":
            await send(ctx, "진행 중인 심리전이 없습니다."); return
        token = normalize_token(선택)
        vote = "공동" if token in {"공동", "같이", "community", "share"} else "개인" if token in {"개인", "나", "self", "solo"} else ""
        if not vote:
            await send(ctx, "`공동` 또는 `개인`을 선택하세요."); return
        uid = int(ctx.author.id); votes = session.setdefault("votes", {})
        if str(uid) not in votes:
            party_user_play(uid)
        votes[str(uid)] = vote; save_data()
        await send(ctx, f"🧠 {_safe_name(ctx.author)} 선택 완료 · 현재 {len(votes)}명")
        if len(votes) >= 5:
            await resolve_mind(ctx, session)

    # ------------------------------------------------------------------
    # NPC relationships and companions
    # ------------------------------------------------------------------
    def npc_key(value: str) -> str:
        token = normalize_token(value)
        for key, spec in NPCS.items():
            if token in {normalize_token(key), normalize_token(spec.get("en", ""))}:
                return key
        return ""

    def npc_relation(user: MutableMapping[str, Any], key: str) -> MutableMapping[str, Any]:
        fun = _fun(user)
        bucket = fun.setdefault("npc", {})
        row = bucket.setdefault(key, {"affinity": 0, "rivalry": 0, "talks": 0, "gifts": 0, "nickname": ""})
        if not isinstance(row, dict):
            row = {"affinity": 0, "rivalry": 0, "talks": 0, "gifts": 0, "nickname": ""}
            bucket[key] = row
        return row

    def npc_line(loc: str, key: str, affinity: int, seed: Any) -> str:
        spec = NPCS[key]
        ko_lines = (
            "오늘은 무리한 승부보다 한 번의 관찰이 더 값질 것 같군요.",
            "당신이 올 때마다 테이블 분위기가 조금 달라집니다.",
            "다음 판에서는 제가 먼저 웃게 될지, 당신이 먼저 웃게 될지 궁금하네요.",
            "비밀 하나를 알려 드리죠. 상자는 반짝일수록 의심해야 합니다.",
            "요즘 서버가 제법 재미있어졌어요. 당신 덕분일지도 모르겠네요.",
        )
        en_lines = (
            "One careful observation may be worth more than a reckless bet today.",
            "The table feels a little different whenever you arrive.",
            "I wonder which of us will smile first in the next round.",
            "A secret: the shinier the chest, the more suspicious it is.",
            "This server has become rather lively. You may be partly responsible.",
        )
        line = stable_pick(ko_lines if loc == "ko" else en_lines, key, affinity, seed)
        if affinity >= 30:
            line += _t(loc, " 당신에게만 하는 말입니다.", " I only say that to you.")
        return f"{spec['emoji']} **{key if loc == 'ko' else spec['en']}**: {line}"

    @bot.command(name="축제대화", aliases=["talkabaddon", "abaddontalk"], help="아바돈과 오늘의 대화를 나눕니다.")
    async def abaddon_talk(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user)
        wait = _cooldown(fun, "abaddon_talk", 300)
        if wait:
            await send(ctx, f"😈 아바돈은 지금 생각 중입니다. {wait}초 뒤 다시 말을 걸어 주세요."); return
        score = int(fun.get("fun_score", 0))
        lines = (
            "좋아. 오늘도 서버를 조금 더 시끄럽고 재미있게 만들어 보자.",
            "황금 고블린이 지나간 흔적을 봤는데… 못 본 척해 줄까?",
            "패가 좋을 때는 침착하고, 패가 나쁠 때는 더 침착해. 그게 제일 얄밉거든.",
            "숨겨진 상인은 자정 무렵에 잠이 없다는 소문이 있어.",
            "네 재미 점수가 올라갈수록 이 도시의 문이 더 많이 열린다.",
        )
        line = stable_pick(lines, int(ctx.author.id), _today(), score // 10)
        fun["fun_score"] = score + 1; unlock_cosmetics(fun); save_data()
        await send(ctx, f"😈 **ABADDON**: {line}")

    @bot.command(name="딜러대화", aliases=["dealertalk", "npctalk"], help="NPC 딜러와 대화해 친밀도를 올립니다.")
    async def dealer_talk(ctx: commands.Context, 이름: str = "루시안") -> None:
        if not await check_registered(ctx): return
        key = npc_key(이름)
        if not key:
            await send(ctx, "NPC를 찾지 못했습니다. `!축제인물도감`에서 이름을 확인하세요."); return
        user = get_user(int(ctx.author.id)); fun = _fun(user)
        wait = _cooldown(fun, f"npc_talk:{key}", 180)
        if wait:
            await send(ctx, f"{wait}초 뒤 다시 대화할 수 있습니다."); return
        relation = npc_relation(user, key)
        relation["talks"] = int(relation.get("talks", 0)) + 1
        relation["affinity"] = int(relation.get("affinity", 0)) + 1
        fun["fun_score"] = int(fun.get("fun_score", 0)) + 1; unlock_cosmetics(fun); save_data()
        await send(ctx, npc_line(locale(ctx), key, int(relation["affinity"]), _today()))

    @bot.command(name="딜러선물", aliases=["dealergift", "npcgift"], help="NPC에게 선물을 주어 관계를 변화시킵니다.")
    async def dealer_gift(ctx: commands.Context, 이름: str, *, 선물: str) -> None:
        if not await check_registered(ctx): return
        key = npc_key(이름)
        if not key:
            await send(ctx, "NPC를 찾지 못했습니다."); return
        user = get_user(int(ctx.author.id))
        if casino_chips(user) < 500:
            await send(ctx, "선물 포장 비용 500칩이 필요합니다."); return
        add_casino_chips(user, -500)
        relation = npc_relation(user, key); spec = NPCS[key]
        liked = normalize_token(선물) in {normalize_token(x) for x in spec.get("likes", ())}
        gain = 6 if liked else 2
        relation["affinity"] = int(relation.get("affinity", 0)) + gain
        relation["gifts"] = int(relation.get("gifts", 0)) + 1
        if not liked and stable_seed(key, 선물) % 5 == 0:
            relation["rivalry"] = int(relation.get("rivalry", 0)) + 1
        fun = _fun(user); fun["fun_score"] = int(fun.get("fun_score", 0)) + (2 if liked else 1); unlock_cosmetics(fun); save_data()
        reaction = "정말 마음에 들어 합니다" if liked else "흥미롭게 바라봅니다"
        await send(ctx, f"{spec['emoji']} **{key}**이(가) `{선물}`을 {reaction}. 친밀도 +{gain} · 현재 {int(relation['affinity'])}")

    @bot.command(name="관계도", aliases=["festivalrelations", "npcrelations"], help="NPC별 친밀도와 경쟁도를 확인합니다.")
    async def relationships(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        loc = locale(ctx); user = get_user(int(ctx.author.id)); lines = []
        for key, spec in NPCS.items():
            row = npc_relation(user, key)
            label = key if loc == "ko" else spec["en"]
            hearts = "♥" * min(5, max(0, int(row.get("affinity", 0)) // 10)) or "·"
            lines.append(f"{spec['emoji']} **{label}** · 친밀 {int(row.get('affinity',0))} {hearts} · 경쟁 {int(row.get('rivalry',0))}")
        await send(ctx, "\n".join(lines))

    @bot.command(name="축제인물도감", aliases=["npccatalog", "festivalcharactercodex"], help="혼돈의 축제 NPC 인물 정보를 확인합니다.")
    async def npc_catalog(ctx: commands.Context) -> None:
        loc = locale(ctx)
        lines = [f"{spec['emoji']} **{key if loc == 'ko' else spec['en']}** · {spec['trait_ko'] if loc == 'ko' else spec['trait_en']}" for key, spec in NPCS.items()]
        await send(ctx, "\n".join(lines))

    @bot.command(name="오늘의대화", aliases=["dailytalk", "todaydialogue"], help="오늘 가장 잘 맞는 NPC와 짧은 대화를 봅니다.")
    async def daily_talk(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        key = stable_pick(tuple(NPCS), int(ctx.author.id), _today(), "daily-npc")
        relation = npc_relation(get_user(int(ctx.author.id)), key)
        await send(ctx, npc_line(locale(ctx), key, int(relation.get("affinity", 0)), _today()))

    def pet_label(loc: str, key: str, row: Mapping[str, Any]) -> str:
        spec = PETS[key]
        evolution = str(row.get("evolution", ""))
        if evolution and evolution in EVOLUTIONS:
            evo = EVOLUTIONS[evolution]
            return f"{evo[0]} {evo[1] if loc == 'ko' else evo[2]}"
        return f"{spec['emoji']} {spec['ko'] if loc == 'ko' else spec['en']}"

    @bot.command(name="펫센터", aliases=["petcenter", "companioncenter"], help="보유 동료와 육성 상태를 확인합니다.")
    async def pet_center(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        loc = locale(ctx); fun = _fun(get_user(int(ctx.author.id))); pets = fun.get("pets", {}) if isinstance(fun.get("pets"), Mapping) else {}
        lines = []
        for key, row in pets.items():
            if key not in PETS or not isinstance(row, Mapping): continue
            marker = "⭐" if str(fun.get("active_pet")) == key else "▫️"
            lines.append(f"{marker} {pet_label(loc,key,row)} · Lv.{int(row.get('level',1))} · EXP {int(row.get('exp',0))}/50")
        if not lines:
            lines = [_t(loc, "보유 동료가 없습니다. `!동료뽑기`로 첫 동료를 만나세요.", "No companions yet. Use `!drawcompanion`.")]
        await send(ctx, "\n".join(lines))

    @bot.command(name="동료뽑기", aliases=["drawcompanion", "petdraw"], help="3,000칩으로 동료 알을 부화합니다.")
    async def draw_companion(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user)
        wait = _cooldown(fun, "pet_draw", 15)
        if wait:
            await send(ctx, f"알이 진정될 때까지 {wait}초 기다려 주세요."); return
        if casino_chips(user) < 3000:
            await send(ctx, f"동료 알은 3,000칩입니다. 현재 {casino_chips(user):,}칩"); return
        add_casino_chips(user, -3000)
        pool = ["raven", "slime"] * 5 + ["fox", "horse"] * 3 + ["ember", "mimic", "ghost"] * 2 + ["beetle"]
        key = stable_pick(pool, int(ctx.author.id), _now() // 3, len(fun.get("reward_ledger", {})))
        pets = fun.setdefault("pets", {}); row = pets.setdefault(key, {"level": 1, "exp": 0, "fed": 0, "evolution": "", "obtained_at": _now()})
        duplicate = int(row.get("copies", 0)); row["copies"] = duplicate + 1
        if duplicate:
            row["exp"] = int(row.get("exp", 0)) + 12
        if not fun.get("active_pet"):
            fun["active_pet"] = key
        fun["fun_score"] = int(fun.get("fun_score", 0)) + 2; unlock_cosmetics(fun); save_data()
        await send(ctx, f"🥚 알에서 **{pet_label(locale(ctx), key, row)}**이(가) 나왔습니다! · {PETS[key]['rarity']}" + (" · 중복 EXP +12" if duplicate else ""))

    @bot.command(name="동료먹이", aliases=["feedcompanion", "feedpet"], help="동료에게 먹이를 주어 경험치를 올립니다.")
    async def feed_companion(ctx: commands.Context, 동료: str = "", *, 먹이: str = "간식") -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); pets = fun.get("pets", {})
        key = normalize_token(동료) or str(fun.get("active_pet", ""))
        if key not in PETS:
            for pet_key, spec in PETS.items():
                if normalize_token(동료) in {normalize_token(spec["ko"]), normalize_token(spec["en"])}:
                    key = pet_key; break
        if not isinstance(pets, MutableMapping) or key not in pets:
            await send(ctx, "보유한 동료를 찾지 못했습니다."); return
        if casino_chips(user) < 300:
            await send(ctx, "먹이 비용 300칩이 필요합니다."); return
        add_casino_chips(user, -300)
        row = pets[key]; liked = normalize_token(먹이) == normalize_token(PETS[key]["food"])
        gain = 14 if liked else 8
        row["exp"] = int(row.get("exp", 0)) + gain; row["fed"] = int(row.get("fed", 0)) + 1
        while int(row.get("exp", 0)) >= 50:
            row["exp"] = int(row.get("exp", 0)) - 50; row["level"] = int(row.get("level", 1)) + 1
        fun["active_pet"] = key; fun["fun_score"] = int(fun.get("fun_score", 0)) + 1; unlock_cosmetics(fun); save_data()
        await send(ctx, f"🍖 {pet_label(locale(ctx),key,row)}에게 `{먹이}`을(를) 줬습니다. EXP +{gain} · Lv.{int(row.get('level',1))}")

    @bot.command(name="동료탐험", aliases=["festivalpetexpedition", "petexpedition"], help="동료를 짧은 탐험에 보내거나 귀환 보상을 받습니다.")
    async def companion_expedition(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); key = str(fun.get("active_pet", "")); pets = fun.get("pets", {})
        if key not in PETS or not isinstance(pets, Mapping) or key not in pets:
            await send(ctx, "먼저 동료를 뽑고 활성 동료를 정하세요."); return
        mission = fun.setdefault("pet_expedition", {})
        if mission and int(mission.get("return_at", 0)) > _now():
            await send(ctx, f"🧭 동료가 탐험 중입니다. 귀환 <t:{int(mission['return_at'])}:R>"); return
        if mission and int(mission.get("return_at", 0)) <= _now() and not mission.get("claimed"):
            reward = 700 + int(pets[key].get("level", 1)) * 180 + stable_seed(mission.get("id"), key) % 700
            mission["claimed"] = True
            _award(user, f"petexp:{mission.get('id')}:{ctx.author.id}", reward, score=2)
            treasure = stable_pick(("반짝 단추", "작은 톱니", "낡은 리본", "달빛 가루"), mission.get("id"))
            treasures = fun.setdefault("treasures", {}); treasures[treasure] = int(treasures.get(treasure, 0)) + 1
            save_data(); await send(ctx, f"🧭 {pet_label(locale(ctx),key,pets[key])} 귀환! `{treasure}` · +{reward:,}칩"); return
        mission.clear(); mission.update({"id": _event_id("PETX"), "pet": key, "started_at": _now(), "return_at": _now() + 900, "claimed": False}); save_data()
        await send(ctx, f"🧭 {pet_label(locale(ctx),key,pets[key])}이(가) 탐험을 떠났습니다. 귀환 <t:{int(mission['return_at'])}:R>")

    @bot.command(name="동료진화", aliases=["evolvecompanion", "evolvepet"], help="5레벨 이상 동료를 진화시킵니다.")
    async def evolve_companion(ctx: commands.Context, 동료: str = "") -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); pets = fun.get("pets", {})
        key = normalize_token(동료) or str(fun.get("active_pet", ""))
        if key not in PETS or not isinstance(pets, MutableMapping) or key not in pets:
            await send(ctx, "보유한 동료를 찾지 못했습니다."); return
        row = pets[key]
        if row.get("evolution"):
            await send(ctx, "이미 진화한 동료입니다."); return
        if int(row.get("level", 1)) < 5:
            await send(ctx, "진화에는 Lv.5가 필요합니다."); return
        row["evolution"] = PETS[key]["evolves"]
        fun["fun_score"] = int(fun.get("fun_score", 0)) + 5; unlock_cosmetics(fun); save_data()
        await send(ctx, f"✨ 진화 완료! **{pet_label(locale(ctx),key,row)}**")

    @bot.command(name="동료도감", aliases=["companioncatalog", "petcatalog"], help="전체 동료와 획득 상태를 확인합니다.")
    async def companion_catalog(ctx: commands.Context) -> None:
        loc = locale(ctx); fun = _fun(get_user(int(ctx.author.id))); owned = fun.get("pets", {}) if isinstance(fun.get("pets"), Mapping) else {}
        lines = []
        for key, spec in PETS.items():
            marker = "✅" if key in owned else "⬛"
            lines.append(f"{marker} {spec['emoji']} **{spec['ko'] if loc == 'ko' else spec['en']}** · {spec['rarity']}")
        await send(ctx, "\n".join(lines))

    @bot.command(name="펫레이스", aliases=["petrace", "companionrace"], help="활성 동료와 짧은 친선 경주를 합니다.")
    async def pet_race(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); key = str(fun.get("active_pet", "")); pets = fun.get("pets", {})
        if key not in PETS or not isinstance(pets, Mapping) or key not in pets:
            await send(ctx, "활성 동료가 없습니다."); return
        wait = _cooldown(fun, "pet_race", 60)
        if wait:
            await send(ctx, f"동료가 숨을 고르는 중입니다. {wait}초"); return
        level = int(pets[key].get("level", 1)); player_roll = stable_seed("pet-race", ctx.author.id, _now() // 30, level) % 100 + level * 3
        rival = stable_pick(tuple(k for k in PETS if k != key), ctx.author.id, _today(), "rival")
        rival_roll = stable_seed("pet-rival", rival, _now() // 30) % 115
        won = player_roll >= rival_roll
        reward = 1800 if won else 250
        _award(user, f"petrace:{_today()}:{_now()//60}:{ctx.author.id}", reward, score=3 if won else 1); save_data()
        await send(ctx, f"🏁 {pet_label(locale(ctx),key,pets[key])} **{player_roll}** vs {PETS[rival]['emoji']} {PETS[rival]['ko']} **{rival_roll}**\n{'우승' if won else '아쉽게 패배'} · +{reward:,}칩")

    # ------------------------------------------------------------------
    # Expeditions and businesses
    # ------------------------------------------------------------------
    def expedition_text(loc: str, session: Mapping[str, Any]) -> str:
        zone = EXPEDITIONS.get(str(session.get("zone", "")), {})
        label = zone.get("ko") if loc == "ko" else zone.get("en")
        return _t(loc, f"{zone.get('emoji','🧭')} **{label}** · 단계 {int(session.get('step',0))}/{int(zone.get('steps',0))} · HP {int(session.get('hp',0))} · 상태 {session.get('status')}", f"{zone.get('emoji','🧭')} **{label}** · Step {int(session.get('step',0))}/{int(zone.get('steps',0))} · HP {int(session.get('hp',0))} · {session.get('status')}")

    @bot.command(name="탐험", aliases=["festivalexpedition", "chaosadventure"], help="개인 선택형 탐험을 시작하거나 현재 상태를 확인합니다.")
    async def expedition(ctx: commands.Context, 지역: str = "") -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); session = fun.get("expedition", {})
        if isinstance(session, Mapping) and session.get("status") == "active":
            await send(ctx, expedition_text(locale(ctx), session) + "\n`!탐험선택 정찰` · `!탐험선택 돌진` · `!탐험선택 휴식`"); return
        if not 지역:
            loc = locale(ctx); lines = [f"{v['emoji']} `{k}` · {v['ko'] if loc == 'ko' else v['en']} · 난이도 {v['difficulty']}" for k, v in EXPEDITIONS.items()]
            await send(ctx, "\n".join(lines) + "\n`!탐험 지역`")
            return
        result = start_expedition(지역, int(ctx.author.id))
        if not result.ok:
            await send(ctx, "지역을 찾지 못했습니다. `!탐험`으로 목록을 확인하세요."); return
        fun["expedition"] = result.payload; fun["party_plays"] = int(fun.get("party_plays", 0)) + 1; save_data()
        await send(ctx, expedition_text(locale(ctx), result.payload) + "\n`!탐험선택 정찰/돌진/휴식`")

    @bot.command(name="파티탐험", aliases=["partyexpedition", "groupadventure"], help="서버 파티 탐험 로비를 엽니다.")
    async def party_expedition(ctx: commands.Context, 지역: str = "ruins") -> None:
        if not await check_registered(ctx): return
        key = expedition_key(지역)
        if not key:
            await send(ctx, "탐험 지역을 찾지 못했습니다."); return
        bucket = party_bucket(ctx)
        existing = bucket.get("expedition")
        if isinstance(existing, Mapping) and existing.get("status") in {"lobby", "active"}:
            await send(ctx, "이미 파티 탐험이 진행 중입니다."); return
        base = start_expedition(key, int(ctx.author.id)).payload
        bucket["expedition"] = {"id": _event_id("PX"), "status": "lobby", "host_id": int(ctx.author.id), "channel_id": int(ctx.channel.id), "participants": [int(ctx.author.id)], "session": base, "votes": {}, "expires_at": _now() + 3600}
        party_user_play(int(ctx.author.id)); save_data()
        await send(ctx, f"🧭 파티 탐험 **{EXPEDITIONS[key]['ko']}** 로비가 열렸습니다. `!탐험참가`로 합류하고 방장이 `!탐험선택 시작`을 입력하세요.")

    @bot.command(name="탐험참가", aliases=["joinpartyexpedition", "joinadventure"], help="진행 중인 파티 탐험에 참가합니다.")
    async def join_expedition(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        session = current_party(ctx, "expedition")
        if not session or session.get("status") != "lobby":
            await send(ctx, "참가 가능한 파티 탐험이 없습니다."); return
        players = session.setdefault("participants", []); uid = int(ctx.author.id)
        if uid not in players:
            players.append(uid); party_user_play(uid); save_data()
        await send(ctx, f"🧭 파티 참가 완료 · {len(players)}명")

    @bot.command(name="탐험선택", aliases=["expeditionchoice", "adventurechoice"], help="개인 또는 파티 탐험의 행동을 선택합니다.")
    async def expedition_choice(ctx: commands.Context, 선택: str) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user)
        personal = fun.get("expedition", {})
        if isinstance(personal, Mapping) and personal.get("status") == "active":
            result = advance_expedition(personal, 선택)
            if not result.ok:
                await send(ctx, "선택은 정찰·돌진·휴식 중 하나입니다."); return
            session = result.payload["session"]; fun["expedition"] = session
            reward = int(result.payload.get("reward", 0))
            if reward:
                _award(user, f"expedition:{session.get('id')}:{session.get('step')}:{ctx.author.id}", reward, score=2)
            if session.get("status") == "complete":
                fun["expeditions_complete"] = int(fun.get("expeditions_complete", 0)) + 1
                for item in session.get("treasures", []):
                    treasures = fun.setdefault("treasures", {}); treasures[item] = int(treasures.get(item, 0)) + 1
                fun["fun_score"] = int(fun.get("fun_score", 0)) + 5; unlock_cosmetics(fun)
            save_data()
            detail = {"trap": "함정 발동", "treasure": "보물 발견", "rest": "휴식", "safe": "안전 통과"}.get(result.code, result.code)
            await send(ctx, expedition_text(locale(ctx), session) + f"\n결과: **{detail}**" + (f" · +{reward:,}칩" if reward else "")); return
        party = current_party(ctx, "expedition")
        if not party:
            await send(ctx, "진행 중인 탐험이 없습니다."); return
        uid = int(ctx.author.id); players = [int(x) for x in party.get("participants", [])]
        if uid not in players:
            await send(ctx, "파티 탐험 참가자가 아닙니다."); return
        if normalize_token(선택) in {"시작", "start"}:
            if uid != int(party.get("host_id", 0)) or party.get("status") != "lobby":
                await send(ctx, "로비 방장만 파티 탐험을 시작할 수 있습니다."); return
            party["status"] = "active"; save_data(); await send(ctx, "🧭 파티 탐험 시작! 모두 `!탐험선택 정찰/돌진/휴식`으로 투표하세요."); return
        if party.get("status") != "active":
            await send(ctx, "파티 탐험이 아직 시작되지 않았습니다."); return
        votes = party.setdefault("votes", {}); votes[str(uid)] = 선택; save_data()
        await send(ctx, f"🧭 선택 기록 ({len(votes)}/{len(players)})")
        if len(votes) < len(players): return
        normalized = [normalize_token(x) for x in votes.values()]
        mapping = {"정찰": "정찰", "scout": "정찰", "돌진": "돌진", "charge": "돌진", "휴식": "휴식", "rest": "휴식"}
        choices = [mapping.get(x, "정찰") for x in normalized]
        chosen = Counter(choices).most_common(1)[0][0]
        result = advance_expedition(party.get("session", {}), chosen)
        party["session"] = result.payload.get("session", party.get("session", {})); party["votes"] = {}
        reward = int(result.payload.get("reward", 0))
        if party["session"].get("status") in {"complete", "failed"}:
            party["status"] = "finished"
            if party["session"].get("status") == "complete":
                share = max(300, reward // max(1, len(players)))
                for member_id in players:
                    member_user = get_user(member_id); member_fun = _fun(member_user)
                    member_fun["expeditions_complete"] = int(member_fun.get("expeditions_complete", 0)) + 1
                    _award(member_user, f"partyexp:{party.get('id')}:{member_id}", share, score=4)
        save_data()
        await send(ctx, f"🧭 파티 선택 **{chosen}**\n" + expedition_text(locale(ctx), party["session"]))

    @bot.command(name="탐험가방", aliases=["expeditionbag", "adventurebag"], help="탐험에서 획득한 보물을 확인합니다.")
    async def expedition_bag(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        treasures = _fun(get_user(int(ctx.author.id))).get("treasures", {})
        lines = [f"🧰 **{name}** ×{int(count)}" for name, count in treasures.items()] if isinstance(treasures, Mapping) else []
        await send(ctx, "\n".join(lines) if lines else "탐험 가방이 비어 있습니다.")

    @bot.command(name="보물도감", aliases=["treasurecatalog", "reliccatalog"], help="알려진 탐험 보물과 획득 상태를 확인합니다.")
    async def treasure_catalog(ctx: commands.Context) -> None:
        owned = _fun(get_user(int(ctx.author.id))).get("treasures", {})
        catalog = ("낡은 금화", "별의 조각", "악마의 영수증", "고대 화투 조각", "유령 승차권", "달 기지 열쇠", "반짝 단추", "작은 톱니", "낡은 리본", "달빛 가루")
        await send(ctx, "\n".join(f"{'✅' if isinstance(owned,Mapping) and x in owned else '⬛'} {x}" for x in catalog))

    @bot.command(name="던전순위", aliases=["dungeonranking", "expeditionranking"], help="서버 탐험 완료 순위를 확인합니다.")
    async def dungeon_ranking(ctx: commands.Context) -> None:
        rows = []
        for member in ctx.guild.members:
            if getattr(member, "bot", False): continue
            try: fun = _fun(get_user(int(member.id)))
            except Exception: continue
            rows.append((int(fun.get("expeditions_complete", 0)), int(fun.get("fun_score", 0)), member))
        rows.sort(key=lambda x: (-x[0], -x[1], x[2].id))
        await send(ctx, "\n".join(f"`{i:02d}` **{_safe_name(m)}** · 완료 {done} · 재미 {score}" for i, (done, score, m) in enumerate(rows[:15], 1)) or "기록이 없습니다.")

    def user_business(guild_row: MutableMapping[str, Any], user_id: int) -> Optional[MutableMapping[str, Any]]:
        row = guild_row.setdefault("businesses", {}).get(str(int(user_id)))
        return row if isinstance(row, MutableMapping) else None

    def collect_business(user_id: int, business: MutableMapping[str, Any]) -> int:
        now = _now(); last = int(business.get("last_settlement", business.get("opened_at", now)) or now)
        periods = min(7, max(0, (now - last) // 86400))
        if periods <= 0: return 0
        visitors = int(business.get("visitors", 0)); total = 0
        for offset in range(periods):
            total += business_income(business, visitors, f"{last//86400 + offset}")
        business["last_settlement"] = last + periods * 86400
        business["earnings"] = int(business.get("earnings", 0)) + total
        user = get_user(user_id); add_casino_chips(user, total)
        fun = _fun(user); fun["business_earnings"] = int(fun.get("business_earnings", 0)) + total
        fun["fun_score"] = int(fun.get("fun_score", 0)) + periods; unlock_cosmetics(fun)
        return total

    @bot.command(name="내사업", aliases=["mybusiness", "businessdashboard"], help="내 사업 현황과 정산 가능한 수익을 확인합니다.")
    async def my_business(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        business = user_business(grow(ctx), int(ctx.author.id))
        if not business:
            await send(ctx, "아직 사업이 없습니다. `!사업개설 카페`처럼 시작하세요."); return
        collected = collect_business(int(ctx.author.id), business); save_data()
        spec = BUSINESSES.get(str(business.get("type")), {})
        await send(ctx, f"{spec.get('emoji','💼')} **{business.get('name')}** · Lv.{int(business.get('level',1))}\n방문 {int(business.get('visitors',0))} · 평점 {float(business.get('rating',1.0)):.2f} · 누적 {int(business.get('earnings',0)):,}칩" + (f"\n오늘 정산 +{collected:,}칩" if collected else ""))

    @bot.command(name="사업개설", aliases=["openbusiness", "createbusiness"], help="칩을 사용해 서버 사업을 개설합니다.")
    async def open_business(ctx: commands.Context, 종류: str, *, 이름: str = "") -> None:
        if not await check_registered(ctx): return
        guild_row = grow(ctx); uid = int(ctx.author.id)
        if user_business(guild_row, uid):
            await send(ctx, "이미 운영 중인 사업이 있습니다."); return
        key = business_key(종류)
        if not key:
            await send(ctx, "사업 종류: 카페, 카지노, 경마장, 탐정, 방송국, 장난감, 용병, 화투공방"); return
        spec = BUSINESSES[key]; user = get_user(uid)
        if casino_chips(user) < int(spec["cost"]):
            await send(ctx, f"개설 비용 {int(spec['cost']):,}칩이 필요합니다."); return
        add_casino_chips(user, -int(spec["cost"]))
        guild_row.setdefault("businesses", {})[str(uid)] = {
            "id": _event_id("SHOP"), "owner_id": uid, "type": key,
            "name": (이름.strip() or f"{_safe_name(ctx.author)}의 {spec['ko']}")[:40],
            "level": 1, "employees": [], "products": {"대표 상품": 500}, "rating": 1.0,
            "visitors": 0, "visit_log": {}, "earnings": 0, "opened_at": _now(), "last_settlement": _now(),
        }
        fun = _fun(user); fun["fun_score"] = int(fun.get("fun_score", 0)) + 5; unlock_cosmetics(fun); save_data()
        await send(ctx, f"{spec['emoji']} **{guild_row['businesses'][str(uid)]['name']}** 개설 완료 · -{int(spec['cost']):,}칩")

    @bot.command(name="상품설정", aliases=["setproduct", "businessproduct"], help="내 사업의 대표 상품과 가격을 설정합니다.")
    async def set_product(ctx: commands.Context, 가격: int, *, 상품명: str) -> None:
        business = user_business(grow(ctx), int(ctx.author.id))
        if not business:
            await send(ctx, "운영 중인 사업이 없습니다."); return
        price = max(50, min(100_000, int(가격)))
        products = business.setdefault("products", {})
        if len(products) >= 5 and 상품명 not in products:
            await send(ctx, "상품은 최대 5개까지 등록할 수 있습니다."); return
        products[str(상품명)[:30]] = price; save_data()
        await send(ctx, f"🛍️ `{상품명}` 가격을 {price:,}칩으로 설정했습니다.")

    @bot.command(name="직원고용", aliases=["hirestaff", "hireemployee"], help="NPC 직원을 고용해 사업 수익을 올립니다.")
    async def hire_staff(ctx: commands.Context, 직원: str = "브릭") -> None:
        business = user_business(grow(ctx), int(ctx.author.id)); user = get_user(int(ctx.author.id))
        if not business:
            await send(ctx, "운영 중인 사업이 없습니다."); return
        key = npc_key(직원) or "브릭"
        employees = business.setdefault("employees", [])
        if key in employees:
            await send(ctx, "이미 고용한 직원입니다."); return
        cost = 5000 + len(employees) * 2500
        if casino_chips(user) < cost:
            await send(ctx, f"고용 비용 {cost:,}칩이 필요합니다."); return
        add_casino_chips(user, -cost); employees.append(key); business["rating"] = min(2.0, float(business.get("rating", 1.0)) + 0.05); save_data()
        await send(ctx, f"👔 **{key}** 고용 완료 · -{cost:,}칩")

    @bot.command(name="가게방문", aliases=["visitshop", "visitbusiness"], help="서버 구성원의 가게를 방문하고 상품을 구매합니다.")
    async def visit_shop(ctx: commands.Context, 주인: discord.Member, *, 상품명: str = "") -> None:
        if not await check_registered(ctx): return
        business = user_business(grow(ctx), int(주인.id))
        if not business:
            await send(ctx, "해당 사용자의 가게를 찾지 못했습니다."); return
        if int(주인.id) == int(ctx.author.id):
            await send(ctx, "자기 가게에는 손님으로 방문할 수 없습니다."); return
        products = business.get("products", {}) if isinstance(business.get("products"), Mapping) else {}
        if not products:
            await send(ctx, "판매 중인 상품이 없습니다."); return
        selected = 상품명 if 상품명 in products else next(iter(products))
        price = int(products[selected]); visitor_user = get_user(int(ctx.author.id)); owner_user = get_user(int(주인.id))
        date_key = _today(); log = business.setdefault("visit_log", {}); visitor_key = f"{ctx.author.id}:{date_key}"
        if visitor_key in log:
            await send(ctx, "오늘은 이미 이 가게를 방문했습니다."); return
        if casino_chips(visitor_user) < price:
            await send(ctx, f"상품 가격 {price:,}칩이 필요합니다."); return
        add_casino_chips(visitor_user, -price); add_casino_chips(owner_user, price)
        log[visitor_key] = {"product": selected, "price": price, "at": _now()}; business["visitors"] = int(business.get("visitors", 0)) + 1
        business["rating"] = min(2.0, float(business.get("rating", 1.0)) + 0.01)
        _fun(visitor_user)["fun_score"] = int(_fun(visitor_user).get("fun_score", 0)) + 1; _fun(owner_user)["business_earnings"] = int(_fun(owner_user).get("business_earnings", 0)) + price
        unlock_cosmetics(_fun(visitor_user)); unlock_cosmetics(_fun(owner_user)); save_data()
        await send(ctx, f"🛍️ **{business.get('name')}**에서 `{selected}` 구매 · {price:,}칩")

    @bot.command(name="서버상권", aliases=["servermarket", "businessdistrict"], help="서버에 개설된 사업 목록을 확인합니다.")
    async def server_market(ctx: commands.Context) -> None:
        lines = []
        for uid, business in grow(ctx).get("businesses", {}).items():
            if not isinstance(business, Mapping): continue
            spec = BUSINESSES.get(str(business.get("type")), {})
            member = ctx.guild.get_member(int(uid)); owner = _safe_name(member) if member else uid
            lines.append(f"{spec.get('emoji','💼')} **{business.get('name')}** · 주인 {owner} · 방문 {int(business.get('visitors',0))} · 평점 {float(business.get('rating',1.0)):.2f}")
        await send(ctx, "\n".join(lines[:20]) if lines else "아직 서버 상권이 비어 있습니다.")

    @bot.command(name="사업순위", aliases=["businessranking", "shopranking"], help="서버 사업 인기 순위를 확인합니다.")
    async def business_ranking(ctx: commands.Context) -> None:
        rows = []
        for uid, business in grow(ctx).get("businesses", {}).items():
            if isinstance(business, Mapping):
                score = int(business.get("visitors", 0)) * 100 + int(business.get("earnings", 0)) // 1000 + int(float(business.get("rating", 1.0)) * 50)
                rows.append((score, int(uid), business))
        rows.sort(reverse=True)
        lines = []
        for rank, (score, uid, business) in enumerate(rows[:15], 1):
            member = ctx.guild.get_member(uid); owner = _safe_name(member) if member else str(uid)
            lines.append(f"`{rank:02d}` **{business.get('name')}** · {owner} · 상권점수 {score:,}")
        await send(ctx, "\n".join(lines) if lines else "사업 순위가 아직 없습니다.")

    # ------------------------------------------------------------------
    # Variety reports and social tools
    # ------------------------------------------------------------------
    def public_fun_rows(ctx: commands.Context) -> List[Tuple[Any, MutableMapping[str, Any], MutableMapping[str, Any]]]:
        rows = []
        for member in ctx.guild.members:
            if getattr(member, "bot", False):
                continue
            try:
                user = get_user(int(member.id)); fun = _fun(user)
            except Exception:
                continue
            rows.append((member, user, fun))
        return rows

    @bot.command(name="오늘의명장면", aliases=["dailyhighlight", "todayhighlight"], help="공개 기록만으로 오늘의 서버 명장면을 뽑습니다.")
    async def daily_highlight(ctx: commands.Context) -> None:
        rows = public_fun_rows(ctx)
        if not rows:
            await send(ctx, "공개 기록이 없습니다."); return
        member, user, fun = max(rows, key=lambda x: (int(x[2].get("biggest_reward", 0)), int(x[2].get("fun_score", 0))))
        scenes = (
            f"🎬 **{_safe_name(member)}**의 최대 재미 보상 **{int(fun.get('biggest_reward',0)):,}칩**",
            f"🎬 **{_safe_name(member)}**이(가) 탐험 {int(fun.get('expeditions_complete',0))}회를 끝까지 완주한 장면",
            f"🎬 **{_safe_name(member)}**의 파티게임 승리 {int(fun.get('party_wins',0))}회",
        )
        await send(ctx, stable_pick(scenes, ctx.guild.id, _today(), "highlight") + "\n※ 비공개 손패와 개인 메시지는 분석하지 않습니다.")

    @bot.command(name="주간예능", aliases=["weeklyvariety", "weeklyshow"], help="서버의 공개 재미 기록을 주간 예능처럼 정리합니다.")
    async def weekly_variety(ctx: commands.Context) -> None:
        rows = public_fun_rows(ctx)
        if not rows:
            await send(ctx, "집계할 공개 기록이 없습니다."); return
        funniest = max(rows, key=lambda x: int(x[2].get("fun_score", 0)))
        explorer = max(rows, key=lambda x: int(x[2].get("expeditions_complete", 0)))
        entrepreneur = max(rows, key=lambda x: int(x[2].get("business_earnings", 0)))
        eventer = max(rows, key=lambda x: int(x[2].get("event_wins", 0)))
        await send(ctx, 
            f"📺 **ABADDON 주간 예능**\n"
            f"🎪 혼돈왕: **{_safe_name(funniest[0])}** · {int(funniest[2].get('fun_score',0))}점\n"
            f"🧭 탐험왕: **{_safe_name(explorer[0])}** · {int(explorer[2].get('expeditions_complete',0))}회\n"
            f"💼 경영왕: **{_safe_name(entrepreneur[0])}** · {int(entrepreneur[2].get('business_earnings',0)):,}칩\n"
            f"☄️ 이벤트왕: **{_safe_name(eventer[0])}** · {int(eventer[2].get('event_wins',0))}승"
        )

    @bot.command(name="월간시상식", aliases=["monthlyawards", "monthlyshow"], help="서버의 월간 재미 시상식을 표시합니다.")
    async def monthly_awards(ctx: commands.Context) -> None:
        rows = public_fun_rows(ctx)
        if not rows:
            await send(ctx, "시상할 기록이 없습니다."); return
        categories = [
            ("🎪 혼돈의 주인공", lambda r: int(r[2].get("fun_score", 0))),
            ("🎉 파티 챔피언", lambda r: int(r[2].get("party_wins", 0))),
            ("☄️ 돌발 영웅", lambda r: int(r[2].get("event_wins", 0))),
            ("🧭 대탐험가", lambda r: int(r[2].get("expeditions_complete", 0))),
            ("💼 상권의 별", lambda r: int(r[2].get("business_earnings", 0))),
        ]
        lines = []
        month = datetime.now(KST).strftime("%Y-%m")
        for label, score_fn in categories:
            winner = max(rows, key=score_fn)
            lines.append(f"{label}: **{_safe_name(winner[0])}** · {score_fn(winner):,}")
        trophy = f"{month} 월간 축제 트로피"
        trophies = grow(ctx).setdefault("trophies", [])
        if trophy not in trophies:
            trophies.append(trophy); save_data()
        await send(ctx, f"🏆 **{month} ABADDON 월간 시상식**\n" + "\n".join(lines))

    @bot.command(name="불운왕", aliases=["unluckiest", "badluckking"], help="공개 잔액 기준 오늘의 불운왕을 뽑습니다.")
    async def unlucky_king(ctx: commands.Context) -> None:
        rows = public_fun_rows(ctx)
        if not rows:
            await send(ctx, "집계할 기록이 없습니다."); return
        member, user, fun = min(rows, key=lambda x: casino_chips(x[1]))
        await send(ctx, f"☔ 오늘의 불운왕은 **{_safe_name(member)}** · 현재 {casino_chips(user):,}칩\n아바돈 평: ‘내일은 이것보다 나쁘기 어렵겠지. 아마도.’")

    @bot.command(name="역전왕", aliases=["comebackking", "turnaroundking"], help="공개 재미 기록에서 가장 큰 보상을 받은 사용자를 보여줍니다.")
    async def comeback_king(ctx: commands.Context) -> None:
        rows = public_fun_rows(ctx)
        if not rows:
            await send(ctx, "집계할 기록이 없습니다."); return
        member, user, fun = max(rows, key=lambda x: int(x[2].get("biggest_reward", 0)))
        await send(ctx, f"🔥 역전왕 **{_safe_name(member)}** · 단일 최대 보상 {int(fun.get('biggest_reward',0)):,}칩")

    @bot.command(name="블러프분석", aliases=["bluffanalysis", "bluffmeter"], help="공개 활동만으로 재미용 블러프 지수를 계산합니다.")
    async def bluff_analysis(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        member = 대상 or ctx.author
        score = 5 + stable_seed("bluff", member.id, _today()) % 96
        comments = (
            "표정은 완벽하지만 손이 너무 빨리 버튼으로 갑니다.",
            "체크할 때 더 수상하고 레이즈할 때 오히려 평온합니다.",
            "블러프보다 진짜 패가 좋을 때 더 긴장하는 유형입니다.",
            "상대가 읽었다고 생각한 순간 한 번 더 꼬는 스타일입니다.",
        )
        await send(ctx, f"🎭 **{_safe_name(member)} 블러프 지수 {score}/100**\n{stable_pick(comments,member.id,_today())}\n※ 비공개 손패는 읽지 않는 예능용 지표입니다.")

    @bot.command(name="축제운세", aliases=["festivalfortune", "dailyfestivalfortune"], help="사용자별 오늘의 운세와 행운 숫자를 확인합니다.")
    async def daily_fortune(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        loc = locale(ctx); ko_grade, ko_text, en_grade, en_text, lucky = fortune_for(int(ctx.author.id), _today())
        fun = _fun(get_user(int(ctx.author.id))); daily = fun.setdefault("daily", {})
        key = f"fortune:{_today()}"
        first = key not in daily
        daily[key] = True
        if first:
            fun["fun_score"] = int(fun.get("fun_score", 0)) + 1; unlock_cosmetics(fun); save_data()
        await send(ctx, _t(loc, f"🔮 **오늘의 운세: {ko_grade}**\n{ko_text}\n행운 숫자 **{lucky}**", f"🔮 **Today's Fortune: {en_grade}**\n{en_text}\nLucky number **{lucky}**"))

    @bot.command(name="궁합", aliases=["compatibility", "servercompatibility"], help="두 사용자의 오늘의 재미 궁합을 확인합니다.")
    async def compatibility(ctx: commands.Context, 상대: discord.Member) -> None:
        score = compatibility_score(int(ctx.author.id), int(상대.id), _today())
        label = "환상의 콤비" if score >= 85 else "아주 좋은 팀" if score >= 70 else "의외로 잘 맞음" if score >= 50 else "서로 다른 맛" if score >= 35 else "같은 테이블에 앉으면 사건 발생"
        await send(ctx, f"💞 **{_safe_name(ctx.author)} × {_safe_name(상대)}** · {score}%\n{label}")

    @bot.command(name="축제밸런스", aliases=["chaosbalance", "festivalbalance"], help="서버 밸런스 게임 질문을 시작합니다.")
    async def balance_game(ctx: commands.Context) -> None:
        social = grow(ctx).setdefault("social", {})
        a, b = stable_pick(BALANCE_QUESTIONS, ctx.guild.id, _now() // 300, "balance")
        social["balance"] = {"id": _event_id("BAL"), "a": a, "b": b, "votes": {}, "channel_id": int(ctx.channel.id), "expires_at": _now() + 300}
        save_data()
        await send(ctx, f"⚖️ **밸런스 게임**\n🅰️ {a}\n🅱️ {b}\n`!밸런스선택 A` 또는 `B`")

    @bot.command(name="밸런스선택", aliases=["balancechoice", "wouldyouratherchoice"], help="진행 중인 밸런스 게임에 투표합니다.")
    async def balance_choice(ctx: commands.Context, 선택: str) -> None:
        session = grow(ctx).setdefault("social", {}).get("balance")
        if not isinstance(session, MutableMapping) or int(session.get("expires_at", 0)) <= _now():
            await send(ctx, "진행 중인 밸런스 게임이 없습니다."); return
        token = normalize_token(선택)
        vote = "A" if token in {"a", "1", "에이"} else "B" if token in {"b", "2", "비"} else ""
        if not vote:
            await send(ctx, "A 또는 B를 선택하세요."); return
        votes = session.setdefault("votes", {}); votes[str(ctx.author.id)] = vote; save_data()
        count = Counter(votes.values())
        await send(ctx, f"⚖️ 투표 완료 · A {count.get('A',0)} / B {count.get('B',0)}")

    WORLD_CUP_OPTIONS = ("텍사스홀덤", "맞고", "고스톱", "섯다", "경마", "블랙잭", "라이어게임", "탐험")

    @bot.command(name="월드컵", aliases=["worldcup", "tournamentpick"], help="ABADDON 콘텐츠 이상형 월드컵을 시작합니다.")
    async def world_cup(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        fun = _fun(get_user(int(ctx.author.id)))
        options = list(WORLD_CUP_OPTIONS)
        random.Random(stable_seed("worldcup", ctx.author.id, _today())).shuffle(options)
        fun["worldcup"] = {"round": options, "next": [], "pair": options[:2], "index": 2, "status": "active"}; save_data()
        await send(ctx, f"🏆 **ABADDON 콘텐츠 월드컵**\n1️⃣ {options[0]}\n2️⃣ {options[1]}\n`!월드컵선택 1` 또는 `2`")

    @bot.command(name="월드컵선택", aliases=["worldcupchoice", "tournamentchoice"], help="월드컵 대진에서 1번 또는 2번을 선택합니다.")
    async def world_cup_choice(ctx: commands.Context, 번호: int) -> None:
        if not await check_registered(ctx): return
        fun = _fun(get_user(int(ctx.author.id))); session = fun.get("worldcup", {})
        if not isinstance(session, MutableMapping) or session.get("status") != "active" or int(번호) not in {1, 2}:
            await send(ctx, "진행 중인 월드컵에서 1 또는 2를 선택하세요."); return
        pair = list(session.get("pair", [])); winner = pair[int(번호) - 1]; next_round = session.setdefault("next", []); next_round.append(winner)
        current = list(session.get("round", [])); index = int(session.get("index", 0))
        if index < len(current):
            session["pair"] = current[index:index + 2]; session["index"] = index + 2
        elif len(next_round) > 1:
            session["round"] = list(next_round); session["next"] = []; session["pair"] = next_round[:2]; session["index"] = 2
        else:
            session["status"] = "finished"; session["winner"] = winner
            fun["fun_score"] = int(fun.get("fun_score", 0)) + 2; unlock_cosmetics(fun); save_data()
            await send(ctx, f"🏆 최종 우승은 **{winner}**!"); return
        save_data(); new_pair = session["pair"]
        await send(ctx, f"🏆 다음 대진\n1️⃣ {new_pair[0]}\n2️⃣ {new_pair[1]}\n`!월드컵선택 1/2`")

    @bot.command(name="랜덤벌칙", aliases=["randompenalty", "partyforfeit"], help="안전하고 가벼운 랜덤 벌칙을 뽑습니다.")
    async def random_penalty(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        member = 대상 or ctx.author
        penalties = (
            "다음 메시지 끝에 ‘…라고 아바돈이 시켰습니다’를 붙이기",
            "30초 동안 가장 좋아하는 이모지만 사용하기",
            "서버 사람 한 명에게 진심 어린 칭찬 한 줄 보내기",
            "다음 게임에서 결과와 상관없이 ‘좋은 경기!’ 외치기",
            "오늘의 운세를 확인하고 그대로 믿는 척하기",
            "프로필 별명을 5분 동안 ‘황금 고블린 목격자’로 상상하기",
        )
        await send(ctx, f"🎲 **{_safe_name(member)}의 벌칙**\n{stable_pick(penalties,member.id,_now()//30)}\n※ 역할·닉네임·권한을 실제로 강제 변경하지 않습니다.")

    @bot.command(name="칭찬릴레이", aliases=["praiserelay", "complimentchain"], help="다른 사용자에게 공개 칭찬을 이어갑니다.")
    async def praise_relay(ctx: commands.Context, 대상: discord.Member, *, 칭찬: str) -> None:
        if int(대상.id) == int(ctx.author.id) or getattr(대상, "bot", False):
            await send(ctx, "다른 서버 구성원을 칭찬해 주세요."); return
        text = str(칭찬).strip()[:160]
        if not text:
            await send(ctx, "칭찬 내용을 입력하세요."); return
        social = grow(ctx).setdefault("social", {}); chain = social.setdefault("praise_chain", {"count": 0, "last_at": 0, "last_sender": 0})
        now = _now()
        if now - int(chain.get("last_at", 0)) <= 300 and int(chain.get("last_sender", 0)) != int(ctx.author.id):
            chain["count"] = int(chain.get("count", 0)) + 1
        else:
            chain["count"] = 1
        chain["last_at"] = now; chain["last_sender"] = int(ctx.author.id); chain["last_target"] = int(대상.id)
        fun = _fun(get_user(int(ctx.author.id))); fun["fun_score"] = int(fun.get("fun_score", 0)) + 1
        if int(chain["count"]) >= 5:
            fun["secret_points"] = int(fun.get("secret_points", 0)) + 1
        unlock_cosmetics(fun); save_data()
        await send(ctx, f"🌟 <@{대상.id}> — **{_safe_name(ctx.author)}**: {text}\n칭찬 릴레이 **{int(chain['count'])}연속**")

    @bot.command(name="친목설정", aliases=["socialsettings", "communitysettings"], help="익명 응원 등 친목 기능을 서버별로 설정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def social_settings(ctx: commands.Context, 기능: str = "보기", 상태: str = "") -> None:
        settings = grow(ctx).setdefault("settings", {})
        feature = normalize_token(기능); token = normalize_token(상태)
        if feature in {"익명", "anonymous"} and token:
            settings["anonymous_enabled"] = token in {"켜기", "on", "enable"}
            save_data()
        await send(ctx, f"👥 친목 기능: {'켜짐' if settings.get('social_enabled',True) else '꺼짐'} · 익명 응원: {'켜짐' if settings.get('anonymous_enabled',False) else '꺼짐'}\n익명 응원은 기본 꺼짐이며 관리자 로그와 신고 기능이 함께 작동합니다.")

    @bot.command(name="익명응원", aliases=["anonymouscheer", "anonymoussupport"], help="관리자가 허용한 서버에서 익명 응원 DM을 보냅니다.")
    async def anonymous_cheer(ctx: commands.Context, 대상: discord.Member, *, 메시지: str) -> None:
        if not await check_registered(ctx): return
        guild_row = grow(ctx)
        if not guild_row.get("settings", {}).get("anonymous_enabled", False):
            await send(ctx, "이 서버는 익명 응원을 사용하지 않습니다. 관리자가 `!친목설정 익명 켜기`로 허용할 수 있습니다."); return
        if int(대상.id) == int(ctx.author.id) or getattr(대상, "bot", False):
            await send(ctx, "다른 사람에게만 보낼 수 있습니다."); return
        checked = sanitize_anonymous_message(메시지)
        if not checked.ok:
            await send(ctx, "메시지가 비어 있거나 너무 길거나 링크를 포함하고 있습니다."); return
        log_id = _event_id("ANON")
        entry = {"id": log_id, "sender_id": int(ctx.author.id), "target_id": int(대상.id), "text": checked.payload["text"], "at": _now(), "reported": False}
        logs = guild_row.setdefault("anonymous_log", []); logs.append(entry); del logs[:-200]
        try:
            target_loc = _selected_locale(bot, 대상.id, ctx.guild.id)
            await 대상.send(_t(target_loc, f"💌 **ABADDON 익명 응원**\n{entry['text']}\n신고가 필요하면 서버에서 `!익명응원신고 {log_id}`", f"💌 **ABADDON Anonymous Support**\n{entry['text']}\nTo report it, use `!reportanonymous {log_id}` in the guild."))
        except Exception:
            logs.pop(); await send(ctx, "상대방의 DM이 닫혀 있어 보내지 못했습니다."); return
        fun = _fun(get_user(int(ctx.author.id))); fun["fun_score"] = int(fun.get("fun_score", 0)) + 1; unlock_cosmetics(fun); save_data()
        await send(ctx, f"💌 익명 응원을 전달했습니다. 기록 ID `{log_id}`", delete_after=10)

    @bot.command(name="익명응원로그", aliases=["anonymouslog", "supportlog"], help="관리자가 익명 응원 감사 로그를 확인합니다.")
    @commands.has_permissions(manage_messages=True)
    async def anonymous_log(ctx: commands.Context) -> None:
        logs = grow(ctx).get("anonymous_log", [])
        lines = [f"`{x.get('id')}` <@{x.get('sender_id')}> → <@{x.get('target_id')}> · {'신고됨' if x.get('reported') else '정상'} · {str(x.get('text',''))[:60]}" for x in logs[-20:] if isinstance(x, Mapping)]
        await send(ctx, "\n".join(lines) if lines else "익명 응원 기록이 없습니다.")

    @bot.command(name="익명응원신고", aliases=["reportanonymous", "reportsupport"], help="받은 익명 응원 기록을 관리자 검토 대상으로 표시합니다.")
    async def report_anonymous(ctx: commands.Context, 기록ID: str) -> None:
        logs = grow(ctx).get("anonymous_log", [])
        for row in logs:
            if isinstance(row, MutableMapping) and str(row.get("id")) == str(기록ID).upper() and int(row.get("target_id", 0)) == int(ctx.author.id):
                row["reported"] = True; row["reported_at"] = _now(); save_data(); await send(ctx, "🚨 관리자 검토 대상으로 표시했습니다."); return
        await send(ctx, "신고 가능한 기록을 찾지 못했습니다.")

    @bot.command(name="비밀친구", aliases=["secretfriend", "secretbuddy"], help="비밀친구 이벤트 상태를 확인합니다.")
    async def secret_friend(ctx: commands.Context) -> None:
        state = grow(ctx).setdefault("secret_friend", {})
        status = state.get("status", "closed")
        await send(ctx, f"🎁 비밀친구 상태 **{status}** · 참가 {len(state.get('participants',[]))}명\n`!비밀친구참가` · 관리자는 `!비밀친구시작`")

    @bot.command(name="비밀친구참가", aliases=["joinsecretfriend", "joinsecretbuddy"], help="열린 비밀친구 모집에 참가합니다.")
    async def join_secret_friend(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        state = grow(ctx).setdefault("secret_friend", {})
        if state.get("status") not in {"open", "closed"}:
            await send(ctx, "현재 참가할 수 없습니다."); return
        state["status"] = "open"; players = state.setdefault("participants", []); uid = int(ctx.author.id)
        if uid not in players: players.append(uid)
        save_data(); await send(ctx, f"🎁 비밀친구 참가 완료 · {len(players)}명")

    @bot.command(name="비밀친구시작", aliases=["startsecretfriend", "startsecretbuddy"], help="관리자가 참가자 비밀친구를 배정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def start_secret_friend(ctx: commands.Context) -> None:
        state = grow(ctx).setdefault("secret_friend", {}); players = [int(x) for x in state.get("participants", [])]
        assignments = assign_secret_friends(players, f"{ctx.guild.id}:{_today()}")
        if not assignments:
            await send(ctx, "비밀친구는 최소 3명이 필요합니다."); return
        failed = 0
        for sender, target in assignments.items():
            member = ctx.guild.get_member(sender); target_member = ctx.guild.get_member(target)
            if member and target_member:
                try:
                    member_loc = _selected_locale(bot, sender, ctx.guild.id)
                    await member.send(_t(member_loc, f"🎁 이번 비밀친구 대상은 **{_safe_name(target_member)}**입니다. 정체를 숨기고 응원해 주세요.", f"🎁 Your secret friend is **{_safe_name(target_member)}**. Keep your identity hidden and support them."))
                except Exception: failed += 1
        state.update({"status": "running", "assignments": {str(k): v for k, v in assignments.items()}, "started_at": _now()}); save_data()
        await send(ctx, f"🎁 비밀친구 배정 완료 · {len(assignments)}명 · DM 실패 {failed}명")

    def bingo_state(ctx: commands.Context) -> MutableMapping[str, Any]:
        season = datetime.now(KST).strftime("%Y-%m")
        row = grow(ctx).setdefault("bingo", {})
        if row.get("season") != season:
            row.clear(); row.update({"season": season, "board": make_bingo(int(ctx.guild.id), season), "winners": []})
        return row

    @bot.command(name="서버빙고", aliases=["serverbingo", "guildbingo"], help="서버 월간 빙고판과 내 체크 상태를 확인합니다.")
    async def server_bingo(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        loc = locale(ctx); state = bingo_state(ctx); fun = _fun(get_user(int(ctx.author.id))); season = state["season"]
        marks = fun.setdefault("bingo_marked", {}).setdefault(season, [12])
        image = _bingo_png(loc, ctx.guild.name, state["board"], marks)
        lines = bingo_lines(marks)
        await send(ctx, f"🎯 내 빙고 **{lines}줄** · 체크는 `!빙고체크 번호`", file=discord.File(image, filename="abaddon_bingo.png"))

    @bot.command(name="빙고체크", aliases=["bingocheck", "markbingo"], help="서버 빙고 칸을 체크합니다. 월 1회 첫 빙고 보상이 있습니다.")
    async def bingo_check(ctx: commands.Context, 번호: int) -> None:
        if not await check_registered(ctx): return
        if not 1 <= int(번호) <= 25:
            await send(ctx, "1~25 번호를 입력하세요."); return
        state = bingo_state(ctx); fun = _fun(get_user(int(ctx.author.id))); season = state["season"]
        marks = fun.setdefault("bingo_marked", {}).setdefault(season, [12]); index = int(번호) - 1
        if index not in marks: marks.append(index)
        lines = bingo_lines(marks); winners = state.setdefault("winners", [])
        reward = 0
        if lines >= 1 and int(ctx.author.id) not in winners:
            winners.append(int(ctx.author.id)); reward = 1500
            _award(get_user(int(ctx.author.id)), f"bingo:{ctx.guild.id}:{season}:{ctx.author.id}", reward, score=3)
        save_data(); await send(ctx, f"🎯 `{state['board'][index]}` 체크 · 현재 {lines}줄" + (f" · 첫 빙고 +{reward:,}칩" if reward else ""))

    @bot.command(name="출석도장", aliases=["festivalattendance", "festivalcheckin"], help="하루 한 번 축제 출석 도장을 받습니다.")
    async def attendance(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); daily = fun.setdefault("daily", {}); key = f"attendance:{_today()}"
        if daily.get(key):
            await send(ctx, "오늘 출석 도장을 이미 받았습니다."); return
        daily[key] = True; streak = int(daily.get("attendance_streak", 0)) + 1; daily["attendance_streak"] = streak
        reward = 500 + min(30, streak) * 50
        _award(user, key, reward, score=1); save_data()
        await send(ctx, f"📅 출석 **{streak}일 연속** · +{reward:,}칩")

    @bot.command(name="생일카드", aliases=["birthdaycard", "celebrationcard"], help="서버 구성원에게 축하 카드를 보냅니다.")
    async def birthday_card(ctx: commands.Context, 대상: discord.Member, *, 메시지: str = "오늘 하루가 전설적인 한 판처럼 즐겁기를!") -> None:
        embed = discord.Embed(title="🎂 ABADDON 축하 카드", description=str(메시지)[:300], color=discord.Color.gold())
        embed.add_field(name="From", value=_safe_name(ctx.author), inline=True); embed.add_field(name="To", value=_safe_name(대상), inline=True)
        embed.set_footer(text="생일뿐 아니라 기념일에도 사용할 수 있습니다.")
        await send(ctx, content=f"<@{대상.id}>", embed=embed)

    # ------------------------------------------------------------------
    # Cosmetics, trophy rooms and hidden content
    # ------------------------------------------------------------------
    def cosmetic_lines(loc: str, catalog: Mapping[str, Tuple[str, str, str, int]], owned: Iterable[str], selected: str = "") -> List[str]:
        owned_set = set(owned)
        lines = []
        for key, row in catalog.items():
            marker = "⭐" if key == selected else "✅" if key in owned_set else "⬛"
            lines.append(f"{marker} `{key}` · {row[0]} {row[1] if loc == 'ko' else row[2]} · 필요 재미 {row[3]}")
        return lines

    @bot.command(name="꾸미기센터", aliases=["cosmeticcenter", "profilecosmetics"], help="프로필 이미지와 보유 꾸미기 항목을 확인합니다.")
    async def cosmetic_center(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        loc = locale(ctx); user = get_user(int(ctx.author.id)); fun = _fun(user); unlocked = unlock_cosmetics(fun)
        if unlocked: save_data()
        image = _profile_png(loc, _safe_name(ctx.author), user)
        await send(ctx, file=discord.File(image, filename="abaddon_chaos_profile.png"))

    @bot.command(name="프로필꾸미기", aliases=["customizeprofile", "setcosmetic"], help="칭호·배경·테이블·카드뒷면을 선택합니다.")
    async def customize_profile(ctx: commands.Context, 분류: str, 항목ID: str) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user); unlock_cosmetics(fun)
        token = normalize_token(분류)
        mapping = {
            "칭호": ("titles", "title", TITLES), "title": ("titles", "title", TITLES),
            "배경": ("backgrounds", "background", BACKGROUNDS), "background": ("backgrounds", "background", BACKGROUNDS),
            "테이블": ("tables", "table", TABLE_SKINS), "table": ("tables", "table", TABLE_SKINS),
            "카드": ("card_backs", "card_back", CARD_BACKS), "카드뒷면": ("card_backs", "card_back", CARD_BACKS), "cardback": ("card_backs", "card_back", CARD_BACKS),
        }
        if token not in mapping:
            await send(ctx, "분류는 칭호·배경·테이블·카드뒷면 중 하나입니다."); return
        bucket_key, profile_key, catalog = mapping[token]
        item = str(항목ID)
        owned = fun.setdefault("cosmetics", {}).setdefault(bucket_key, [])
        if item not in catalog or item not in owned:
            await send(ctx, "아직 보유하지 않은 꾸미기 항목입니다."); return
        fun.setdefault("profile", {})[profile_key] = item; save_data()
        row = catalog[item]
        await send(ctx, f"🎨 {row[0]} **{row[1]}** 적용 완료")

    @bot.command(name="칭호도감", aliases=["titlecatalog", "titles"], help="혼돈의 축제 칭호 도감을 확인합니다.")
    async def title_catalog(ctx: commands.Context) -> None:
        fun = _fun(get_user(int(ctx.author.id))); loc = locale(ctx); unlock_cosmetics(fun)
        await send(ctx, "\n".join(cosmetic_lines(loc, TITLES, fun.get("cosmetics", {}).get("titles", []), str(fun.get("profile", {}).get("title", "")))))

    @bot.command(name="배경도감", aliases=["backgroundcatalog", "backgrounds"], help="프로필 배경 도감을 확인합니다.")
    async def background_catalog(ctx: commands.Context) -> None:
        fun = _fun(get_user(int(ctx.author.id))); loc = locale(ctx); unlock_cosmetics(fun)
        await send(ctx, "\n".join(cosmetic_lines(loc, BACKGROUNDS, fun.get("cosmetics", {}).get("backgrounds", []), str(fun.get("profile", {}).get("background", "")))))

    @bot.command(name="카드뒷면", aliases=["cardbacks", "cardbackcatalog"], help="보유 카드 뒷면 스킨을 확인합니다.")
    async def card_backs(ctx: commands.Context) -> None:
        fun = _fun(get_user(int(ctx.author.id))); loc = locale(ctx); unlock_cosmetics(fun)
        await send(ctx, "\n".join(cosmetic_lines(loc, CARD_BACKS, fun.get("cosmetics", {}).get("card_backs", []), str(fun.get("profile", {}).get("card_back", "")))))

    @bot.command(name="테이블스킨", aliases=["tableskins", "tablethemes"], help="보유 게임 테이블 스킨을 확인합니다.")
    async def table_skins(ctx: commands.Context) -> None:
        fun = _fun(get_user(int(ctx.author.id))); loc = locale(ctx); unlock_cosmetics(fun)
        await send(ctx, "\n".join(cosmetic_lines(loc, TABLE_SKINS, fun.get("cosmetics", {}).get("tables", []), str(fun.get("profile", {}).get("table", "")))))

    @bot.command(name="트로피룸", aliases=["chaostrophyroom", "mytrophies"], help="내 업적·비밀·수집 트로피를 확인합니다.")
    async def trophy_room(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); fun = _fun(user)
        lines = [
            f"🎪 재미 점수 **{int(fun.get('fun_score',0))}**",
            f"☄️ 이벤트 승리 **{int(fun.get('event_wins',0))}**",
            f"🎉 파티 승리 **{int(fun.get('party_wins',0))}**",
            f"🧭 탐험 완료 **{int(fun.get('expeditions_complete',0))}**",
            f"💼 사업 수익 **{int(fun.get('business_earnings',0)):,}칩**",
            f"🗝️ 비밀 발견 **{len(fun.get('secret_flags',[]))}개**",
            f"🏺 전설 아이템 **{len(fun.get('legendary_items',[]))}개**",
        ]
        await send(ctx, "🏆 **개인 트로피룸**\n" + "\n".join(lines))

    @bot.command(name="공동트로피룸", aliases=["guildtrophyroom", "servertrophies"], help="서버 공동 트로피와 월간 기록을 확인합니다.")
    async def guild_trophy_room(ctx: commands.Context) -> None:
        trophies = grow(ctx).get("trophies", [])
        lines = [f"🏆 {x}" for x in trophies[-20:]] if isinstance(trophies, list) else []
        event_stats = grow(ctx).get("event_stats", {})
        total_wins = sum(int(x.get("wins",0)) for x in event_stats.values() if isinstance(x, Mapping)) if isinstance(event_stats, Mapping) else 0
        await send(ctx, f"🏛️ **{ctx.guild.name} 공동 트로피룸**\n☄️ 돌발 이벤트 총 승리 {total_wins}\n" + ("\n".join(lines) if lines else "아직 전시된 시즌 트로피가 없습니다."))

    def scan_secrets(ctx: commands.Context, user: MutableMapping[str, Any]) -> List[str]:
        fun = _fun(user)
        v1190 = user.get("v1190_collections", {}) if isinstance(user.get("v1190_collections"), Mapping) else {}
        hwatu_months = len(v1190.get("hwatu_months", [])) if isinstance(v1190.get("hwatu_months"), list) else 0
        horse = user.get("v1092_horse_racing", {}) if isinstance(user.get("v1092_horse_racing"), Mapping) else {}
        praise = grow(ctx).get("social", {}).get("praise_chain", {}) if isinstance(grow(ctx).get("social", {}), Mapping) else {}
        context = {
            "hwatu_months": hwatu_months,
            "balance": casino_chips(user),
            "expeditions_complete": int(fun.get("expeditions_complete", 0)),
            "underdog_race_wins": int(horse.get("underdog_wins", 0)),
            "praise_chain": int(praise.get("count", 0)) if isinstance(praise, Mapping) else 0,
        }
        found = secret_flags(fun, context)
        owned = fun.setdefault("secret_flags", [])
        new = []
        for flag in found:
            if flag not in owned:
                owned.append(flag); fun["secret_points"] = int(fun.get("secret_points", 0)) + 1; new.append(flag)
        if new:
            fun["fun_score"] = int(fun.get("fun_score", 0)) + len(new) * 5; unlock_cosmetics(fun)
        return new

    @bot.command(name="비밀힌트", aliases=["secrethint", "easteregghint"], help="숨겨진 콘텐츠의 짧은 힌트를 확인합니다.")
    async def secret_hint(ctx: commands.Context) -> None:
        hint = stable_pick(SECRET_HINTS, ctx.guild.id, ctx.author.id, _today())
        await send(ctx, f"🗝️ **비밀 힌트**\n{hint}")

    @bot.command(name="수상한상인", aliases=["mysteriousmerchant", "hiddenmerchant"], help="특정 시간에만 나타나는 숨겨진 상인을 찾습니다.")
    async def mysterious_merchant(ctx: commands.Context, 동작: str = "보기") -> None:
        if not await check_registered(ctx): return
        hour = datetime.now(KST).hour
        user = get_user(int(ctx.author.id)); fun = _fun(user)
        discovered = "midnight_merchant" in fun.get("secret_flags", [])
        if hour not in {0, 1, 22, 23} and not discovered:
            await send(ctx, "낡은 간판만 흔들리고 있습니다. 상인은 보이지 않습니다."); return
        if not discovered:
            fun.setdefault("secret_flags", []).append("midnight_merchant"); fun["secret_points"] = int(fun.get("secret_points", 0)) + 1; fun["fun_score"] = int(fun.get("fun_score",0)) + 5; unlock_cosmetics(fun)
        offer = stable_pick(("검은장미", "달빛 병", "황금수액", "고대 화투 조각"), ctx.author.id, _today())
        cost = 4000 + stable_seed(offer, _today()) % 4000
        if normalize_token(동작) in {"구매", "buy", "purchase"}:
            daily = fun.setdefault("daily", {}); key = f"merchant:{_today()}"
            if daily.get(key):
                await send(ctx, "오늘은 이미 상인에게서 물건을 샀습니다."); return
            if casino_chips(user) < cost:
                await send(ctx, f"상인은 말없이 {cost:,}칩을 가리킵니다."); return
            add_casino_chips(user, -cost); daily[key] = True
            treasures = fun.setdefault("treasures", {}); treasures[offer] = int(treasures.get(offer, 0)) + 1; save_data()
            await send(ctx, f"🕯️ `{offer}` 구매 완료 · -{cost:,}칩"); return
        save_data(); await send(ctx, f"🕯️ 수상한 상인이 `{offer}`을(를) **{cost:,}칩**에 내놓았습니다. `!수상한상인 구매`")

    @bot.command(name="숨겨진임무", aliases=["hiddenmission", "secretmission"], help="현재 조건으로 발견 가능한 숨겨진 임무를 검사합니다.")
    async def hidden_mission(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(int(ctx.author.id)); new = scan_secrets(ctx, user); save_data()
        fun = _fun(user)
        names = {
            "twelve_moons": "열두 달의 증인", "bankrupt_explorer": "빈손의 탐험가", "underdog_crown": "꼴찌의 왕관",
            "praise_door": "칭찬으로 열린 문", "abaddon_final": "아바돈의 비밀 결승", "midnight_merchant": "자정의 거래",
        }
        if new:
            await send(ctx, "🗝️ 새 비밀 발견!\n" + "\n".join(f"✅ {names.get(x,x)}" for x in new))
        else:
            await send(ctx, f"🗝️ 현재 발견한 비밀 {len(fun.get('secret_flags',[]))}개 · 새로운 조건은 아직 충족되지 않았습니다.")

    @bot.command(name="전설아이템", aliases=["legendaryitem", "guildrelic"], help="서버에 단 하나뿐인 전설 유물의 주인을 확인하거나 획득합니다.")
    async def legendary_item(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        guild_row = grow(ctx); relic = guild_row.get("legendary_relic")
        if isinstance(relic, Mapping):
            await send(ctx, f"🏺 서버 전설 유물 **{relic.get('name')}** · 소유자 <@{int(relic.get('owner_id',0))}> · `{relic.get('id')}`"); return
        user = get_user(int(ctx.author.id)); scan_secrets(ctx, user); fun = _fun(user)
        if len(fun.get("secret_flags", [])) < 3 or int(fun.get("fun_score", 0)) < 50:
            await send(ctx, "아직 전설 유물이 당신을 선택하지 않았습니다. 비밀 3개와 재미 점수 50이 필요합니다."); return
        names = ("종말의 조커", "열두 달의 왕패", "혜성마의 편자", "아바돈의 검은 주사위")
        name = stable_pick(names, ctx.guild.id, ctx.author.id)
        relic = {"id": _event_id("RELIC"), "name": name, "owner_id": int(ctx.author.id), "claimed_at": _now()}
        guild_row["legendary_relic"] = relic; fun.setdefault("legendary_items", []).append(name); fun["fun_score"] = int(fun.get("fun_score", 0)) + 10; unlock_cosmetics(fun); save_data()
        await send(ctx, f"🏺 서버에 단 하나뿐인 **{name}**이(가) <@{ctx.author.id}>을(를) 선택했습니다! `{relic['id']}`")

    # ------------------------------------------------------------------
    # Backups, settings, background maintenance and audit
    # ------------------------------------------------------------------
    @bot.command(name="혼돈설정", aliases=["festivalsettings", "funsettings"], help="혼돈의 축제 서버 설정을 확인합니다.")
    @commands.has_permissions(manage_guild=True)
    async def festival_settings(ctx: commands.Context) -> None:
        settings = grow(ctx).get("settings", {})
        await send(ctx, 
            f"🎪 **혼돈의 축제 설정**\n"
            f"자동 돌발 이벤트: {'켜짐' if settings.get('auto_events') else '꺼짐'}\n"
            f"파티게임: {'켜짐' if settings.get('party_enabled',True) else '꺼짐'}\n"
            f"친목 기능: {'켜짐' if settings.get('social_enabled',True) else '꺼짐'}\n"
            f"익명 응원: {'켜짐' if settings.get('anonymous_enabled',False) else '꺼짐'}\n"
            f"자동 채널: <#{int(settings.get('event_channel_id',0))}>"
        )

    @bot.command(name="혼돈백업", aliases=["chaosbackup", "festivalbackup"], help="관리자가 혼돈의 축제 서버 데이터와 구성원 재미 데이터를 백업합니다.")
    @commands.has_permissions(manage_guild=True)
    async def chaos_backup(ctx: commands.Context) -> None:
        guild_row = grow(ctx); backup_id = _event_id("FBK")
        member_fun = {}
        for member in ctx.guild.members:
            if getattr(member, "bot", False): continue
            user = get_user(int(member.id))
            if "v1220_fun" in user:
                member_fun[str(member.id)] = copy.deepcopy(user["v1220_fun"])
        payload = {"id": backup_id, "created_at": _now(), "creator_id": int(ctx.author.id), "guild": copy.deepcopy({k:v for k,v in guild_row.items() if k != "backups"}), "users": member_fun}
        backups = guild_row.setdefault("backups", {}); backups[backup_id] = payload
        if len(backups) > 10:
            for old in sorted(backups, key=lambda x: int(backups[x].get("created_at",0)))[:-10]: backups.pop(old, None)
        save_data(); await send(ctx, f"💾 혼돈 데이터 백업 완료 `{backup_id}` · 사용자 {len(member_fun)}명")

    @bot.command(name="혼돈복구", aliases=["chaosrestore", "festivalrestore"], help="혼돈 백업 ID로 서버 재미 데이터를 복원합니다.")
    @commands.has_permissions(administrator=True)
    async def chaos_restore(ctx: commands.Context, 백업ID: str) -> None:
        guild_row = grow(ctx); backup = guild_row.get("backups", {}).get(str(백업ID).upper())
        if not isinstance(backup, Mapping):
            await send(ctx, "백업을 찾지 못했습니다."); return
        keep_backups = guild_row.get("backups", {})
        restored = copy.deepcopy(backup.get("guild", {}))
        guild_row.clear(); guild_row.update(restored); guild_row["backups"] = keep_backups
        for uid, value in backup.get("users", {}).items():
            if isinstance(value, Mapping): get_user(int(uid))["v1220_fun"] = copy.deepcopy(dict(value))
        save_data(); await send(ctx, f"↩️ `{백업ID}` 복구 완료 · 서버 설정과 사용자 재미 데이터가 되돌아갔습니다.")

    async def post_auto_event(guild: discord.Guild, guild_row: MutableMapping[str, Any]) -> None:
        settings = guild_row.get("settings", {})
        channel = guild.get_channel(int(settings.get("event_channel_id", 0) or 0))
        if channel is None: return
        event = create_event(guild_row, "", int(channel.id))
        mention = f"<@&{int(settings.get('mention_role_id',0))}> " if int(settings.get("mention_role_id",0)) else ""
        loc = _selected_locale(bot, 0, guild.id)

        async def handler(interaction: discord.Interaction, choice: str) -> None:
            text, changed = await apply_event_action(int(interaction.guild_id or 0), int(interaction.user.id), choice)
            await interaction.response.send_message(text if _interaction_locale(bot, interaction) == "ko" else _auto_en(text), ephemeral=True)
            if changed:
                current = _guild(root, int(interaction.guild_id or 0)).get("active_event")
                if isinstance(current, Mapping):
                    try: await interaction.message.edit(embed=event_embed(loc, current), view=view)
                    except Exception: pass

        view = ChaosEventView(loc, handler)
        try:
            msg = await channel.send(content=mention or None, embed=event_embed(loc, event), view=view, allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False))
            event["message_id"] = int(msg.id)
        except Exception:
            guild_row["active_event"] = None

    @tasks.loop(seconds=30)
    async def chaos_maintenance_loop() -> None:
        now = _now(); dirty = False
        for gid_key, guild_row in list(root.get("guilds", {}).items()):
            if not isinstance(guild_row, MutableMapping): continue
            guild = bot.get_guild(int(gid_key))
            if guild is None: continue
            settings = guild_row.get("settings", {}) if isinstance(guild_row.get("settings"), Mapping) else {}
            active = guild_row.get("active_event")
            if isinstance(active, MutableMapping) and not active.get("resolved") and int(active.get("expires_at", 0)) <= now:
                active["resolved"] = True; active["expired"] = True; dirty = True
            if settings.get("auto_events") and (not isinstance(active, Mapping) or active.get("resolved")) and now >= int(guild_row.get("next_auto_event_at", 0)):
                try: await post_auto_event(guild, guild_row)
                except Exception: pass
                guild_row["next_auto_event_at"] = now + max(30, min(1440, int(settings.get("frequency_minutes", 180)))) * 60; dirty = True
            party = guild_row.get("party", {}) if isinstance(guild_row.get("party"), Mapping) else {}
            bomb = party.get("bomb") if isinstance(party, Mapping) else None
            if isinstance(bomb, MutableMapping) and bomb.get("status") in {"lobby", "running"} and int(bomb.get("expires_at", 0)) <= now:
                bomb["status"] = "finished"; loser = int(bomb.get("holder_id", 0)); dirty = True
                channel = guild.get_channel(int(bomb.get("channel_id", 0)))
                if channel:
                    try:
                        gloc = _selected_locale(bot, 0, guild.id)
                        await channel.send(_t(gloc, f"💥 폭탄 폭발! <@{loser}>이(가) 마지막으로 들고 있었습니다. 패스 {int(bomb.get('passes',0))}회", f"💥 The bomb exploded! <@{loser}> was holding it. {int(bomb.get('passes',0))} passes."))
                    except Exception: pass
            mind = party.get("mind") if isinstance(party, Mapping) else None
            if isinstance(mind, MutableMapping) and mind.get("status") == "running" and int(mind.get("expires_at", 0)) <= now:
                votes = mind.get("votes", {}) if isinstance(mind.get("votes"), Mapping) else {}
                counts = Counter(votes.values()); common = int(counts.get("공동",0)); selfish = int(counts.get("개인",0))
                winners = [int(uid) for uid,v in votes.items() if v == "공동"] if common >= selfish else [int(uid) for uid,v in votes.items() if v == "개인"][:1]
                amount = 900 if common >= selfish else 2600
                for uid in winners: party_reward(uid, str(mind.get("id")), amount, winner=True)
                mind["status"] = "finished"; dirty = True
                channel = guild.get_channel(int(mind.get("channel_id",0)))
                if channel:
                    try:
                        gloc = _selected_locale(bot, 0, guild.id)
                        await channel.send(_t(gloc, f"🧠 심리전 자동 종료 · 공동 {common} / 개인 {selfish} · 승자 {', '.join(f'<@{x}>' for x in winners) or '없음'}", f"🧠 Mind game ended · Community {common} / Self {selfish} · Winners {', '.join(f'<@{x}>' for x in winners) or 'None'}"))
                    except Exception: pass
        if dirty: save_data()

    @chaos_maintenance_loop.before_loop
    async def before_chaos_loop() -> None:
        await bot.wait_until_ready()

    @bot.listen("on_ready")
    async def v1220_ready() -> None:
        if not chaos_maintenance_loop.is_running(): chaos_maintenance_loop.start()

    catalogue = audit_catalogues()
    required_commands = (
        "혼돈축제", "돌발이벤트", "이벤트참가", "폭탄돌리기", "마피아", "라이어게임", "그림자추리", "생존룰렛", "심리전",
        "딜러대화", "동료뽑기", "탐험", "사업개설", "오늘의명장면", "축제운세", "축제밸런스", "익명응원", "비밀친구",
        "서버빙고", "꾸미기센터", "트로피룸", "비밀힌트", "전설아이템", "혼돈백업", "혼돈복구",
    )
    checks = [
        ("버전", VERSION == "12.2.0", VERSION),
        ("돌발 이벤트 8종", catalogue["events"] == 8, str(catalogue["events"])),
        ("NPC 6명", catalogue["npcs"] == 6, str(catalogue["npcs"])),
        ("동료 8종", catalogue["pets"] == 8, str(catalogue["pets"])),
        ("탐험 지역 8곳", catalogue["expeditions"] == 8, str(catalogue["expeditions"])),
        ("사업 8종", catalogue["businesses"] == 8, str(catalogue["businesses"])),
        ("빙고 25칸", catalogue["bingo_cells"] == 25, str(catalogue["bingo_cells"])),
        ("자동 이벤트 기본 꺼짐", not bool(_guild(root, 0).get("settings", {}).get("auto_events")), "opt-in"),
        ("익명 응원 기본 꺼짐", not bool(_guild(root, 0).get("settings", {}).get("anonymous_enabled")), "opt-in+audit"),
        ("보상 중복 방지", callable(reward_once), "idempotency ledger"),
        ("서버 백업·복구", all(bot.get_command(x) is not None for x in ("혼돈백업","혼돈복구")), "backup-first"),
        ("핵심 명령 등록", all(bot.get_command(x) is not None for x in required_commands), f"{len(required_commands)} required"),
    ]

    async def send_audit(ctx: commands.Context, detail: bool = False) -> None:
        loc = locale(ctx); passed = sum(1 for _, ok, _ in checks if ok)
        embed = _dashboard(bot, loc, "🧪 v12.2.0 혼돈의 축제 검수", "🧪 v12.2.0 Chaos Festival Audit", f"{passed}/{len(checks)} 통과", f"{passed}/{len(checks)} passed", discord.Color.green() if passed == len(checks) else discord.Color.orange())
        embed.add_field(name=_t(loc, "콘텐츠 규모", "Content Scale"), value=_t(loc, f"이벤트 {catalogue['events']} · 파티 6 · NPC {catalogue['npcs']} · 동료 {catalogue['pets']} · 탐험 {catalogue['expeditions']} · 사업 {catalogue['businesses']} · 꾸미기 {catalogue['titles']+catalogue['backgrounds']+catalogue['tables']+catalogue['card_backs']}", f"Events {catalogue['events']} · Party games 6 · NPCs {catalogue['npcs']} · Companions {catalogue['pets']} · Expeditions {catalogue['expeditions']} · Businesses {catalogue['businesses']} · Cosmetics {catalogue['titles']+catalogue['backgrounds']+catalogue['tables']+catalogue['card_backs']}"), inline=False)
        if detail:
            embed.add_field(name=_t(loc, "검수 항목", "Checks"), value="\n".join(f"{'✅' if ok else '❌'} {name} · `{value}`" for name, ok, value in checks), inline=False)
        await send(ctx, embed=embed)

    @bot.command(name="1220통합검수", aliases=["v1220audit", "chaosfestivalaudit"], help="v12.0~v12.2 전체 재미 기능을 검사합니다.")
    async def v1220_audit(ctx: commands.Context, 모드: str = "") -> None:
        await send_audit(ctx, normalize_token(모드) in {"상세", "detail", "full"})

    test_cmd = bot.get_command("테스트")
    if test_cmd is not None:
        async def latest_test(ctx: commands.Context, 모드: str = "") -> None:
            await send_audit(ctx, normalize_token(모드) in {"상세", "detail", "full"})
        test_cmd.callback = latest_test
        test_cmd.help = f"ABADDON v{VERSION} 최신 재미 기능을 검사합니다. `!테스트 상세`"
        test_cmd.description = test_cmd.help

    notes = bot.get_command("패치노트")
    if notes is not None:
        async def patch_notes(ctx: commands.Context) -> None:
            loc = locale(ctx)
            embed = _dashboard(bot, loc, "🎪 ABADDON v12.2.0 혼돈의 축제 완전판", "🎪 ABADDON v12.2.0 Chaos Festival Complete", "대량 재미 기능을 한 번에 추가했습니다.", "A massive entertainment expansion has arrived.", discord.Color.dark_purple())
            embed.add_field(name="☄️ v12.0", value=_t(loc, "돌발 이벤트 8종 · 파티게임 6종 · NPC 관계 · 동료 육성", "8 chaos events · 6 party games · NPC relationships · companions"), inline=False)
            embed.add_field(name="🧭 v12.1", value=_t(loc, "개인/파티 탐험 8지역 · 사업 경영 8종 · 예능 리포트 · 친목 기능", "8 expedition zones · 8 businesses · variety reports · social tools"), inline=False)
            embed.add_field(name="🗝️ v12.2", value=_t(loc, "프로필 꾸미기 · 서버 트로피룸 · 비밀 상인 · 숨겨진 임무 · 서버 유일 전설 유물", "Profile cosmetics · guild trophies · hidden merchant · secret missions · unique guild relic"), inline=False)
            embed.add_field(name=_t(loc, "안전 장치", "Safety"), value=_t(loc, "자동 기능 기본 꺼짐 · 보상 중복 차단 · 익명 관리자 로그/신고 · 재시작 상태 보존 · 백업/복구", "Auto features default off · idempotent rewards · anonymous audit/report · restart persistence · backup/restore"), inline=False)
            embed.add_field(name=_t(loc, "검수", "Audit"), value=_t(loc, "`!1220통합검수 상세` · `!테스트 상세`", "`!v1220audit detail` · `!test detail`"), inline=False)
            await send(ctx, embed=embed)
        notes.callback = patch_notes
        notes.help = f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        notes.description = notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1220_chaos_festival"]
    guide.append({
        "id": "v1220_chaos_festival", "emoji": "🎪", "title": "v12.2.0 혼돈의 축제 완전판",
        "hint": "돌발 이벤트 · 파티게임 · NPC/동료 · 탐험/사업 · 예능/친목 · 꾸미기/비밀",
        "commands": [
            "!혼돈축제 · !돌발이벤트 · !이벤트참가 · !이벤트순위 · !이벤트설정",
            "!파티게임 · !폭탄돌리기 · !마피아 · !라이어게임 · !그림자추리 · !생존룰렛 · !심리전",
            "!축제대화 · !딜러대화 · !딜러선물 · !관계도 · !펫센터 · !동료뽑기 · !동료탐험",
            "!탐험 · !파티탐험 · !탐험선택 · !내사업 · !사업개설 · !가게방문 · !서버상권",
            "!오늘의명장면 · !주간예능 · !월간시상식 · !축제운세 · !궁합 · !축제밸런스 · !월드컵",
            "!칭찬릴레이 · !익명응원 · !비밀친구 · !서버빙고 · !출석도장 · !생일카드",
            "!꾸미기센터 · !프로필꾸미기 · !칭호도감 · !배경도감 · !테이블스킨 · !트로피룸",
            "!비밀힌트 · !숨겨진임무 · !1220통합검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1220_version = VERSION  # type: ignore[attr-defined]
    bot.v1220_checks = checks  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] chaos_events=8 party_games=6 npc=6 pets=8 expeditions=8 businesses=8 social=safe cosmetics=enabled secrets=discoverable auto=opt-in rollback=enabled", flush=True)
