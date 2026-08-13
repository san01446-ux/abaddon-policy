from __future__ import annotations

"""ABADDON v11.9.0 unified schedule, broadcast and collection expansion.

Additive design:
* v11.7 server-local event calendar and game reservations;
* v11.8 public-only live broadcast cards and final settlement coverage;
* v11.9 game achievements and collectible catalogues.

No private hand data is exposed by the broadcast formatter. Automatic reminders are
only sent for events explicitly created in that guild.
"""

import asyncio
import io
import re
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from apocalypse_bot.commands.v40_black_casino import casino_chips
from apocalypse_bot.commands.v651_card_games import ACTIVE_GAMES
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1092_visual_status_horserace import LIVE_RACE_STATES
from apocalypse_bot.commands.v1092_horse_racing_rules import HORSES, FINISH, render_track_lane
from apocalypse_bot.commands.v1100_game_city_overhaul import _find_settlement, _format_settlement, _root as _v1100_root
from apocalypse_bot.commands.v1140_championship_alliance_casino_story import DEALERS, DECORATIONS

VERSION = "11.9.0"
PATCH_DATE = "2026-08-04"
KST = timezone(timedelta(hours=9))
MAX_EVENTS_PER_GUILD = 200
DEFAULT_REMINDERS = (1440, 60, 0)

EVENT_TYPES: Dict[str, Tuple[str, str]] = {
    "게임": ("🎮", "Game"),
    "챔피언십": ("🏆", "Championship"),
    "연합": ("⚔️", "Alliance"),
    "경마": ("🏇", "Horse Racing"),
    "월드보스": ("👹", "World Boss"),
    "재난": ("☣️", "Disaster"),
    "스토리": ("📖", "Story"),
    "시즌": ("🗓️", "Season"),
    "점검": ("🛠️", "Maintenance"),
    "기타": ("📌", "Other"),
}

POKER_HANDS = (
    ("high_card", "하이 카드", "High Card"),
    ("one_pair", "원 페어", "One Pair"),
    ("two_pair", "투 페어", "Two Pair"),
    ("trips", "트리플", "Three of a Kind"),
    ("straight", "스트레이트", "Straight"),
    ("flush", "플러시", "Flush"),
    ("full_house", "풀하우스", "Full House"),
    ("quads", "포카드", "Four of a Kind"),
    ("straight_flush", "스트레이트 플러시", "Straight Flush"),
    ("royal_flush", "로열 스트레이트 플러시", "Royal Flush"),
)

ACHIEVEMENTS: Tuple[Dict[str, Any], ...] = (
    {"id":"first_game","emoji":"🎮","ko":"첫 테이블","en":"First Table","desc_ko":"카드게임을 1회 플레이","desc_en":"Play one card game","kind":"games","target":1},
    {"id":"ten_games","emoji":"🃏","ko":"테이블 단골","en":"Table Regular","desc_ko":"카드게임 10회 플레이","desc_en":"Play 10 card games","kind":"games","target":10},
    {"id":"hundred_games","emoji":"🏙️","ko":"게임도시 주민","en":"Game City Resident","desc_ko":"카드게임 100회 플레이","desc_en":"Play 100 card games","kind":"games","target":100},
    {"id":"first_win","emoji":"🏆","ko":"첫 승리","en":"First Victory","desc_ko":"카드게임 1승","desc_en":"Win one card game","kind":"wins","target":1},
    {"id":"ten_wins","emoji":"🥇","ko":"열 번의 생존","en":"Ten Survivals","desc_ko":"카드게임 10승","desc_en":"Win 10 card games","kind":"wins","target":10},
    {"id":"streak5","emoji":"🔥","ko":"5연승","en":"Five-Win Streak","desc_ko":"최고 연승 5회","desc_en":"Reach a five-win streak","kind":"best_streak","target":5},
    {"id":"debt","emoji":"💸","ko":"파산자의 밤","en":"Bankrupt Night","desc_ko":"칩 잔액이 음수가 됨","desc_en":"Reach a negative chip balance","kind":"debt","target":1},
    {"id":"profit_million","emoji":"💰","ko":"백만 칩 생존자","en":"Million-Chip Survivor","desc_ko":"누적 순이익 1,000,000칩","desc_en":"Earn 1,000,000 chips net","kind":"profit","target":1_000_000},
    {"id":"hwatu10","emoji":"🎴","ko":"화투 수집가","en":"Hwatu Collector","desc_ko":"화투 계열 10회 플레이","desc_en":"Play 10 hwatu games","kind":"hwatu_games","target":10},
    {"id":"horse5","emoji":"🏇","ko":"경마장 단골","en":"Track Regular","desc_ko":"경마 5회 참여","desc_en":"Enter five horse races","kind":"races","target":5},
    {"id":"horsewin","emoji":"🏁","ko":"적중의 순간","en":"Winning Ticket","desc_ko":"경마 1회 적중","desc_en":"Win one horse race","kind":"race_wins","target":1},
    {"id":"collector5","emoji":"🧰","ko":"장식 수집가","en":"Decoration Collector","desc_ko":"개인 카지노 장식 5개 보유","desc_en":"Own five casino decorations","kind":"decorations","target":5},
    {"id":"dealer3","emoji":"🎩","ko":"딜러의 신뢰","en":"Dealer Trust","desc_ko":"NPC 딜러 친밀도 합계 30","desc_en":"Reach 30 total dealer affinity","kind":"dealer_affinity","target":30},
    {"id":"season_lp10","emoji":"🌟","ko":"시즌 도전자","en":"Season Challenger","desc_ko":"챔피언십 LP 10","desc_en":"Reach 10 championship LP","kind":"season_lp","target":10},
)


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1190_event_hub", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1190_event_hub"] = root
    root.setdefault("schema_version", 1)
    root.setdefault("guilds", {})
    root.setdefault("audit_runs", [])
    return root


def _guild(root: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = root.setdefault("guilds", {})
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("events", {})
    row.setdefault("broadcast", {"enabled": True, "interval": 8, "commentary": True, "channels": {}})
    row.setdefault("display", {"achievement_users": []})
    return row


def _user(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault("v1190_collections", {})
    if not isinstance(row, dict):
        row = {}
        user["v1190_collections"] = row
    row.setdefault("unlocked", {})
    row.setdefault("display", [])
    row.setdefault("poker_hands", [])
    row.setdefault("hwatu_months", [])
    row.setdefault("horse_winners", [])
    row.setdefault("dealer_affinity", {})
    row.setdefault("last_scan", 0)
    return row


def _normalize_event_type(value: str) -> str:
    token = str(value or "기타").strip().casefold().replace(" ", "")
    aliases = {
        "game":"게임","card":"게임","게임":"게임",
        "championship":"챔피언십","league":"챔피언십","리그":"챔피언십","챔피언십":"챔피언십",
        "alliance":"연합","연합":"연합","연합전":"연합",
        "race":"경마","horse":"경마","경마":"경마",
        "worldboss":"월드보스","boss":"월드보스","월드보스":"월드보스",
        "disaster":"재난","재난":"재난",
        "story":"스토리","스토리":"스토리",
        "season":"시즌","시즌":"시즌",
        "maintenance":"점검","점검":"점검",
    }
    return aliases.get(token, "기타")


def _parse_dt(date_text: str, time_text: str) -> int:
    raw = f"{date_text} {time_text}".strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%m-%d %H:%M", "%m/%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=datetime.now(KST).year)
            return int(dt.replace(tzinfo=KST).timestamp())
        except ValueError:
            continue
    raise ValueError("날짜는 YYYY-MM-DD, 시간은 HH:MM 형식으로 입력하세요.")


def _event_id() -> str:
    return f"E-{uuid.uuid4().hex[:8].upper()}"


def _sorted_events(guild_row: Mapping[str, Any], *, now: Optional[int] = None, until: Optional[int] = None) -> List[Dict[str, Any]]:
    now = int(now or time.time())
    events = guild_row.get("events", {}) if isinstance(guild_row, Mapping) else {}
    rows = []
    for value in events.values() if isinstance(events, Mapping) else ():
        if not isinstance(value, Mapping) or value.get("status") == "cancelled":
            continue
        ts = int(value.get("starts_at", 0) or 0)
        if ts < now - 3600:
            continue
        if until is not None and ts > int(until):
            continue
        rows.append(dict(value))
    rows.sort(key=lambda row: int(row.get("starts_at", 0) or 0))
    return rows


def _event_line(locale: str, row: Mapping[str, Any]) -> str:
    event_type = str(row.get("type", "기타"))
    emoji, en = EVENT_TYPES.get(event_type, EVENT_TYPES["기타"])
    label = event_type if locale == "ko" else en
    participants = row.get("participants", []) if isinstance(row.get("participants"), list) else []
    suffix = f" · {len(participants)}명" if participants else ""
    if locale != "ko" and participants:
        suffix = f" · {len(participants)} joined"
    return f"{emoji} <t:{int(row.get('starts_at',0))}:f> · **{row.get('title','-')}** · {label}{suffix} · `{row.get('id','-')}`"


def _public_session_state(session: Any) -> Dict[str, Any]:
    """Return only fields safe for spectators. Never inspect hands/private state."""
    message = getattr(session, "message", None)
    names = getattr(session, "names", {})
    if not isinstance(names, Mapping):
        names = getattr(session, "players", {})
    player_ids = list(getattr(session, "player_ids", []))
    rows = []
    for uid in player_ids[:12]:
        name = str(names.get(uid, names.get(str(uid), "ABADDON" if int(uid) < 0 else uid))) if isinstance(names, Mapping) else str(uid)
        folded = uid in set(getattr(session, "folded", set()) or set())
        rows.append({"uid": int(uid), "name": name, "folded": bool(folded)})
    board = getattr(session, "board", getattr(session, "community", getattr(session, "floor", [])))
    if not isinstance(board, (list, tuple)):
        board = []
    board_public = [str(card) for card in list(board)[:12]]
    return {
        "game_id": str(getattr(session, "game_id", "-")),
        "kind": str(getattr(session, "variant", getattr(session, "mode", getattr(session, "kind", "게임")))),
        "pot": int(getattr(session, "pot", 0) or 0),
        "current_uid": int(getattr(session, "current_uid", 0) or 0) if not callable(getattr(session, "current_uid", None)) else 0,
        "stage": str(getattr(session, "stage", getattr(session, "phase", "진행 중"))),
        "players": rows,
        "board": board_public,
        "channel_id": int(getattr(getattr(message, "channel", None), "id", getattr(session, "channel_id", 0)) or 0),
    }


def _public_race_state(guild_id: int, owner_id: int = 0) -> Optional[Dict[str, Any]]:
    """Return one public race state for a guild without exposing user-private data."""
    candidates: List[Tuple[int, Mapping[str, Any]]] = []
    for uid, raw in LIVE_RACE_STATES.items():
        if not isinstance(raw, Mapping):
            continue
        if int(raw.get("guild_id", 0) or 0) != int(guild_id):
            continue
        if owner_id and int(uid) != int(owner_id):
            continue
        candidates.append((int(uid), raw))
    if not candidates:
        return None
    uid, raw = max(candidates, key=lambda pair: int(pair[1].get("tick", 0) or 0))
    positions = [max(0, min(FINISH, int(v))) for v in list(raw.get("positions", []))[:len(HORSES)]]
    if len(positions) < len(HORSES):
        positions += [0] * (len(HORSES) - len(positions))
    odds_raw = list(raw.get("odds", []))
    odds = [float(odds_raw[i]) if i < len(odds_raw) else float(HORSES[i].get("odds", 1.0)) for i in range(len(HORSES))]
    horses=[]
    for index, horse in enumerate(HORSES):
        horses.append({
            "index": index,
            "name_ko": str(horse.get("name_ko", index + 1)),
            "name_en": str(horse.get("name_en", index + 1)),
            "emoji": str(horse.get("emoji", "🐎")),
            "position": positions[index],
            "odds": odds[index],
        })
    return {
        "source": "race",
        "race_owner_id": uid,
        "game_id": f"RACE-{uid}",
        "kind": "경마",
        "status": str(raw.get("status", "racing")),
        "stage": str(raw.get("status", "racing")),
        "tick": int(raw.get("tick", 0) or 0),
        "bet": int(raw.get("bet", 0) or 0),
        "selected": int(raw.get("selected", -1) or -1),
        "selected_name": str(raw.get("selected_name", "-")),
        "leader_name": str(raw.get("leader_name", "-")),
        "net": int(raw.get("net", 0) or 0),
        "horses": horses,
    }


def _broadcast_state(channel_id: int, guild_id: int, source: str = "auto", race_owner_id: int = 0) -> Optional[Dict[str, Any]]:
    source = str(source or "auto").casefold()
    if source in {"auto", "card"}:
        session = ACTIVE_GAMES.get(int(channel_id))
        if session is not None:
            state = _public_session_state(session)
            state["source"] = "card"
            return state
        if source == "card":
            return None
    if source in {"auto", "race"}:
        return _public_race_state(int(guild_id), int(race_owner_id or 0))
    return None


def _stats_from_user(user: Mapping[str, Any]) -> Dict[str, int]:
    game_stats = user.get("v1050_game_stats", {}) if isinstance(user.get("v1050_game_stats"), Mapping) else {}
    total = game_stats.get("total", {}) if isinstance(game_stats.get("total"), Mapping) else {}
    games = int(total.get("plays", total.get("games", 0)) or 0)
    wins = int(total.get("wins", 0) or 0)
    best_streak = int(total.get("best_streak", total.get("max_streak", 0)) or 0)
    profit = int(total.get("profit", total.get("net", 0)) or 0)
    by_game = game_stats.get("games", {}) if isinstance(game_stats.get("games"), Mapping) else {}
    hwatu_games = 0
    for key, value in by_game.items():
        if str(key) in {"맞고","고스톱","민화투","육백","섯다","삼봉","도리짓고땡"} and isinstance(value, Mapping):
            hwatu_games += int(value.get("plays", value.get("games", 0)) or 0)
    race = user.get("v1092_horse_racing", {}) if isinstance(user.get("v1092_horse_racing"), Mapping) else {}
    casino = user.get("v1140", {}) if isinstance(user.get("v1140"), Mapping) else {}
    personal = casino.get("casino", {}) if isinstance(casino.get("casino"), Mapping) else {}
    coll = user.get("v1190_collections", {}) if isinstance(user.get("v1190_collections"), Mapping) else {}
    affinity = coll.get("dealer_affinity", {}) if isinstance(coll.get("dealer_affinity"), Mapping) else {}
    return {
        "games": games,
        "wins": wins,
        "best_streak": best_streak,
        "profit": profit,
        "debt": int(casino_chips(user) < 0),
        "hwatu_games": hwatu_games,
        "races": int(race.get("plays", 0) or 0),
        "race_wins": int(race.get("wins", 0) or 0),
        "decorations": len(personal.get("decorations", [])) if isinstance(personal.get("decorations"), list) else 0,
        "dealer_affinity": sum(int(v or 0) for v in affinity.values()),
        "season_lp": int(coll.get("season_lp", 0) or 0),
    }


def _sync_collections_from_history(user: MutableMapping[str, Any], user_id: int, world_data: Mapping[str, Any], guild_id: int) -> None:
    row=_user(user)
    settlements=world_data.get("v1100_game_city",{}).get("settlements",[]) if isinstance(world_data.get("v1100_game_city",{}),Mapping) else []
    hwatu_kinds={"맞고","고스톱","민화투","육백","섯다","삼봉","도리짓고땡"}
    games=wins=0
    for settlement in settlements if isinstance(settlements,list) else ():
        if not isinstance(settlement,Mapping) or int(settlement.get("guild_id",0) or 0)!=int(guild_id): continue
        mine=next((p for p in settlement.get("players",[]) if isinstance(p,Mapping) and int(p.get("user_id",0) or 0)==int(user_id)),None)
        if mine is None: continue
        games+=1; wins+=int(int(mine.get("net",0) or 0)>0)
        kind=str(settlement.get("kind",""))
        if kind in hwatu_kinds:
            digest=hashlib.sha256(str(settlement.get("game_id",games)).encode()).digest()
            month=1+(digest[0]%12)
            months=row.setdefault("hwatu_months",[])
            if month not in months: months.append(month)
    row["season_lp"]=games+wins*3
    race=user.get("v1092_horse_racing",{}) if isinstance(user.get("v1092_horse_racing"),Mapping) else {}
    for record in race.get("history",[]) if isinstance(race.get("history"),list) else ():
        if isinstance(record,Mapping) and int(record.get("gross",0) or 0)>0:
            winner=str(record.get("winner",""))
            if winner and winner not in row.setdefault("horse_winners",[]): row["horse_winners"].append(winner)
    replay_root=world_data.get("v1090",{}) if isinstance(world_data.get("v1090"),Mapping) else {}
    token_map={
        "royal_flush":("로열","royal flush"),"straight_flush":("스트레이트 플러시","straight flush"),"quads":("포카드","four of a kind"),
        "full_house":("풀하우스","full house"),"flush":("플러시","flush"),"straight":("스트레이트","straight"),
        "trips":("트리플","three of a kind"),"two_pair":("투 페어","two pair"),"one_pair":("원 페어","one pair"),"high_card":("하이 카드","high card"),
    }
    for replay in replay_root.get("replays",[]) if isinstance(replay_root.get("replays"),list) else ():
        if not isinstance(replay,Mapping) or int(replay.get("guild_id",0) or 0)!=int(guild_id): continue
        players=replay.get("players",{})
        ids={int(k) for k in players.keys() if str(k).lstrip("-").isdigit()} if isinstance(players,Mapping) else set()
        if int(user_id) not in ids: continue
        text=(str(replay.get("result",""))+" "+" ".join(map(str,replay.get("events",[])))).casefold()
        for key,tokens in token_map.items():
            if any(token.casefold() in text for token in tokens) and key not in row.setdefault("poker_hands",[]): row["poker_hands"].append(key)
    profile=user.get("v1140",{}) if isinstance(user.get("v1140"),Mapping) else {}
    dealer=str(profile.get("dealer","iris")); affinity=row.setdefault("dealer_affinity",{}); affinity[dealer]=max(int(affinity.get(dealer,0)),min(100,games))


def _scan_achievements(user: MutableMapping[str, Any]) -> Tuple[List[str], Dict[str, int]]:
    row = _user(user)
    stats = _stats_from_user(user)
    newly: List[str] = []
    unlocked = row.setdefault("unlocked", {})
    now = int(time.time())
    for item in ACHIEVEMENTS:
        if int(stats.get(str(item["kind"]), 0)) >= int(item["target"]):
            if item["id"] not in unlocked:
                unlocked[item["id"]] = now
                newly.append(str(item["id"]))
    row["last_scan"] = now
    return newly, stats


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf" if bold else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _png_calendar(locale: str, guild_name: str, events: Sequence[Mapping[str, Any]]) -> io.BytesIO:
    width, height = 1400, 860
    image = Image.new("RGB", (width, height), (12, 10, 20))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 30, width-35, height-30), radius=30, fill=(24, 19, 36), outline=(150, 78, 206), width=3)
    draw.text((75, 65), _t(locale, "ABADDON 서버 일정센터", "ABADDON Server Schedule"), font=_font(48, True), fill=(245, 236, 255))
    draw.text((78, 125), guild_name[:40], font=_font(24, True), fill=(102, 216, 255))
    y = 190
    if not events:
        draw.text((80, y), _t(locale, "등록된 예정 일정이 없습니다.", "No upcoming events are registered."), font=_font(30), fill=(200, 190, 210))
    for index, row in enumerate(events[:10], 1):
        draw.rounded_rectangle((70, y, width-70, y+58), radius=14, fill=(39, 31, 53), outline=(85, 69, 105), width=1)
        dt = datetime.fromtimestamp(int(row.get("starts_at", 0)), KST).strftime("%m/%d %H:%M")
        typ = str(row.get("type", "기타"))
        emoji, en = EVENT_TYPES.get(typ, EVENT_TYPES["기타"])
        label = typ if locale == "ko" else en
        text = f"{index:02d}  {dt}  {emoji} {label}  {row.get('title','-')}  [{row.get('id','-')}]"
        draw.text((92, y+14), text[:100], font=_font(24, True), fill=(236, 229, 243))
        y += 66
    draw.text((75, height-75), f"ABADDON v{VERSION} · {_t(locale, '서버별 일정만 표시', 'Guild-local events only')}", font=_font(20), fill=(155, 143, 166))
    output = io.BytesIO(); image.save(output, format="PNG", optimize=True); output.seek(0); return output


def _png_collection(locale: str, display_name: str, unlocked: Mapping[str, Any], stats: Mapping[str, int]) -> io.BytesIO:
    width, height = 1400, 900
    image = Image.new("RGB", (width, height), (10, 12, 20)); draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 30, width-35, height-30), radius=30, fill=(21, 24, 36), outline=(72, 185, 211), width=3)
    draw.text((75, 65), _t(locale, "ABADDON 업적·수집 도감", "ABADDON Achievement Collection"), font=_font(46, True), fill=(241, 247, 255))
    draw.text((78, 125), display_name[:40], font=_font(24, True), fill=(100, 214, 255))
    cols = 2; card_w = 610; x0 = 75; y0 = 190
    for idx, item in enumerate(ACHIEVEMENTS[:12]):
        col, row = idx % cols, idx // cols
        x = x0 + col * 650; y = y0 + row * 105
        is_open = item["id"] in unlocked
        fill = (34, 56, 56) if is_open else (39, 36, 48)
        outline = (89, 220, 159) if is_open else (82, 74, 94)
        draw.rounded_rectangle((x, y, x+card_w, y+88), radius=15, fill=fill, outline=outline, width=2)
        title = item["ko"] if locale == "ko" else item["en"]
        desc = item["desc_ko"] if locale == "ko" else item["desc_en"]
        mark = "✓" if is_open else "·"
        draw.text((x+18, y+12), f"{mark} {item['emoji']} {title}", font=_font(24, True), fill=(237, 245, 241) if is_open else (177, 169, 185))
        current = int(stats.get(str(item["kind"]), 0)); target = int(item["target"])
        draw.text((x+18, y+49), f"{desc}  {min(current,target):,}/{target:,}", font=_font(18), fill=(182, 205, 199) if is_open else (147, 139, 154))
    draw.text((75, height-72), f"{len(unlocked)}/{len(ACHIEVEMENTS)} {_t(locale, '업적 해금', 'achievements unlocked')} · ABADDON v{VERSION}", font=_font(21, True), fill=(145, 209, 225))
    output = io.BytesIO(); image.save(output, format="PNG", optimize=True); output.seek(0); return output


class ScheduleView(discord.ui.View):
    def __init__(self, bot: commands.Bot, root: MutableMapping[str, Any], guild_id: int, locale: str, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot; self.root = root; self.guild_id = guild_id; self.locale = locale; self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.author_id:
            await interaction.response.send_message(_t(self.locale, "이 일정 패널은 명령 실행자만 조작할 수 있습니다.", "Only the command author can use this schedule panel."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="새로고침", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        row = _guild(self.root, self.guild_id)
        events = _sorted_events(row, until=int(time.time()) + 7*86400)
        image = _png_calendar(self.locale, getattr(guild, "name", "ABADDON"), events)
        embed = _dashboard(self.bot, self.locale, "🗓️ 서버 일정센터", "🗓️ Server Schedule Center", "오늘과 이번 주 일정을 한 장에서 확인합니다.", "Review today and this week's events in one card.", discord.Color.dark_teal())
        embed.set_image(url="attachment://abaddon_schedule.png")
        try:
            await interaction.message.edit(embed=embed, attachments=[discord.File(image, filename="abaddon_schedule.png")], view=self)
        except Exception:
            await interaction.followup.send(embed=embed, file=discord.File(image, filename="abaddon_schedule.png"), ephemeral=True)


class BroadcastView(discord.ui.View):
    def __init__(self, bot: commands.Bot, root: MutableMapping[str, Any], guild_id: int, channel_id: int, owner_id: int, locale: str):
        super().__init__(timeout=None)
        self.bot=bot; self.root=root; self.guild_id=guild_id; self.channel_id=channel_id; self.owner_id=owner_id; self.locale=locale

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id and not getattr(interaction.user.guild_permissions, "manage_guild", False):
            await interaction.response.send_message(_t(self.locale,"중계 개설자 또는 관리자만 조작할 수 있습니다.","Only the broadcast owner or a manager can control this."),ephemeral=True)
            return False
        return True

    @discord.ui.button(label="즉시 갱신", style=discord.ButtonStyle.primary, emoji="📡", custom_id="abaddon:v1190:broadcast_refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        try:
            channel_row=_guild(self.root,self.guild_id).get("broadcast",{}).get("channels",{}).get(str(self.channel_id),{})
            state=_broadcast_state(self.channel_id,self.guild_id,str(channel_row.get("source","auto")),int(channel_row.get("race_owner_id",0) or 0))
            if state is None:
                await interaction.followup.send(_t(self.locale,"이 서버에 진행 중인 카드게임이나 경마가 없습니다.","No card game or horse race is active in this server."),ephemeral=True); return
            embed=_broadcast_embed(self.bot,self.locale,state,_guild(self.root,self.guild_id).get("broadcast",{}),self.channel_id)
            await interaction.message.edit(embed=embed,view=self)
        except Exception as exc:
            await interaction.followup.send(f"refresh failed: {type(exc).__name__}",ephemeral=True)

    @discord.ui.button(label="중계 종료", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="abaddon:v1190:broadcast_stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        row=_guild(self.root,self.guild_id).setdefault("broadcast",{}).setdefault("channels",{})
        row.pop(str(self.channel_id),None)
        for child in self.children: child.disabled=True
        await interaction.response.edit_message(view=self)


def _broadcast_embed(bot: commands.Bot, locale: str, state: Mapping[str, Any], settings: Mapping[str, Any], channel_id: int) -> discord.Embed:
    source=str(state.get("source","card"))
    if source == "race":
        embed=_dashboard(bot,locale,"🏇 ABADDON 실시간 경마 중계","🏇 ABADDON Live Horse-Race Broadcast",_t(locale,"공개 순위·배당·결승선만 표시합니다.","Shows public standings, odds and the finish line only."),discord.Color.orange())
        embed.add_field(name=_t(locale,"상태","Status"),value=f"**{state.get('stage','-')}** · {_t(locale,'틱','tick')} {int(state.get('tick',0))}",inline=True)
        embed.add_field(name=_t(locale,"선두","Leader"),value=str(state.get("leader_name","-")),inline=True)
        embed.add_field(name=_t(locale,"선택·판돈","Pick · Stake"),value=f"{state.get('selected_name','-')} · {int(state.get('bet',0)):,}",inline=True)
        rows=[]
        for horse in state.get("horses",[]):
            if not isinstance(horse,Mapping): continue
            label=horse.get("name_ko") if locale=="ko" else horse.get("name_en")
            rows.append(f"{horse.get('emoji','🐎')} **{int(horse.get('index',0))+1}. {label}** x{float(horse.get('odds',1.0)):.1f}\n`{render_track_lane(int(horse.get('position',0)))}`")
        embed.add_field(name=_t(locale,"실시간 트랙","Live Track"),value="\n".join(rows)[:1024] or "-",inline=False)
        if str(state.get("status"))=="finished":
            embed.add_field(name=_t(locale,"결과","Result"),value=_t(locale,f"완주 · 이번 손익 {int(state.get('net',0)):+,}칩",f"Finished · net {int(state.get('net',0)):+,} chips"),inline=False)
    else:
        embed=_dashboard(bot,locale,"📡 ABADDON 실시간 경기 중계","📡 ABADDON Live Match Broadcast",_t(locale,"비공개 손패는 제외하고 공개 정보만 표시합니다.","Only public information is shown; private hands are excluded."),discord.Color.red())
        embed.add_field(name=_t(locale,"경기","Match"),value=f"**{state.get('kind','-')}** · `{state.get('game_id','-')}`",inline=False)
        embed.add_field(name=_t(locale,"단계","Stage"),value=str(state.get("stage","-"))[:100],inline=True)
        embed.add_field(name=_t(locale,"팟","Pot"),value=f"{int(state.get('pot',0)):,}",inline=True)
        embed.add_field(name=_t(locale,"현재 차례","Current Turn"),value=str(state.get("current_uid",0)),inline=True)
        players=[]
        for player in state.get("players",[]):
            if isinstance(player,Mapping): players.append(f"{'❌' if player.get('folded') else '✅'} {player.get('name','-')}")
        embed.add_field(name=_t(locale,"참가자","Players"),value="\n".join(players) or "-",inline=True)
        board=state.get("board",[])
        embed.add_field(name=_t(locale,"공개 보드","Public Board"),value=" · ".join(map(str,board)) if board else _t(locale,"공개 카드 없음","No public cards"),inline=True)
    cheer_count=int(settings.get("cheers",{}).get(str(channel_id),0)) if isinstance(settings.get("cheers"),Mapping) else 0
    embed.add_field(name=_t(locale,"응원","Cheers"),value=f"📣 {cheer_count:,}",inline=True)
    embed.set_footer(text=_t(locale,"중계는 공개 상태만 읽으며 결과 정산에는 영향을 주지 않습니다.","Broadcasts read public state only and never affect settlement."))
    return embed


def register_v1190_event_broadcast_collection(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot,"_abaddon_v1190_registered",False): return
    bot._abaddon_v1190_registered=True
    root=_root(world_data)

    def locale(ctx: commands.Context)->str: return _ctx_locale(bot,ctx)
    def guild_row(ctx: commands.Context)->MutableMapping[str,Any]: return _guild(root,int(getattr(ctx.guild,"id",0) or 0))

    async def send_calendar(ctx: commands.Context, days: int=7)->None:
        loc=locale(ctx); row=guild_row(ctx); now=int(time.time()); events=_sorted_events(row,now=now,until=now+days*86400)
        image=_png_calendar(loc,getattr(ctx.guild,"name","ABADDON"),events)
        embed=_dashboard(bot,loc,"🗓️ 서버 일정센터","🗓️ Server Schedule Center","서버에 등록된 예정 일정만 표시합니다.","Only events registered in this server are shown.",discord.Color.dark_teal())
        if events: embed.add_field(name=_t(loc,"예정 일정","Upcoming"),value="\n".join(_event_line(loc,e) for e in events[:8]),inline=False)
        else: embed.add_field(name=_t(loc,"예정 일정","Upcoming"),value=_t(loc,"등록된 일정이 없습니다.","No events are registered."),inline=False)
        embed.add_field(name=_t(loc,"빠른 명령","Quick Commands"),value=_t(loc,"`!일정등록 YYYY-MM-DD HH:MM 종류 제목` · `!게임예약 게임 날짜 시간 판돈`","`!addevent YYYY-MM-DD HH:MM type title` · `!reservegame game date time stake`"),inline=False)
        embed.set_image(url="attachment://abaddon_schedule.png")
        await ctx.send(embed=embed,file=discord.File(image,filename="abaddon_schedule.png"),view=ScheduleView(bot,root,int(ctx.guild.id),loc,int(ctx.author.id)))

    @bot.command(name="일정",aliases=["일정센터","schedule","schedulecenter"],help="서버의 오늘·이번 주 이벤트를 이미지 달력으로 확인합니다.")
    async def schedule_center(ctx: commands.Context)->None: await send_calendar(ctx,7)

    @bot.command(name="이벤트달력",aliases=["eventcalendar","servercalendar"],help="서버 이벤트 달력을 확인합니다.")
    async def event_calendar(ctx: commands.Context)->None: await send_calendar(ctx,31)

    @bot.command(name="오늘일정",aliases=["todayschedule","todayevents"],help="오늘 남은 서버 일정을 확인합니다.")
    async def today_schedule(ctx: commands.Context)->None:
        loc=locale(ctx); now=datetime.now(KST); end=int(now.replace(hour=23,minute=59,second=59).timestamp()); rows=_sorted_events(guild_row(ctx),now=int(now.timestamp()),until=end)
        await ctx.send("\n".join(_event_line(loc,r) for r in rows) if rows else _t(loc,"오늘 남은 일정이 없습니다.","No events remain today."))

    @bot.command(name="이번주일정",aliases=["weekschedule","weekevents"],help="앞으로 7일 일정을 확인합니다.")
    async def week_schedule(ctx: commands.Context)->None: await send_calendar(ctx,7)

    @bot.command(name="일정등록",aliases=["addevent","createevent"],help="관리자가 서버 일정을 등록합니다. `!일정등록 YYYY-MM-DD HH:MM 종류 제목`")
    @commands.has_permissions(manage_guild=True)
    async def add_event(ctx: commands.Context, 날짜: str, 시간: str, 종류: str="기타", *, 제목: str="ABADDON 이벤트")->None:
        loc=locale(ctx)
        try: starts=_parse_dt(날짜,시간)
        except ValueError as exc: await ctx.send(_t(loc,str(exc),"Use YYYY-MM-DD and HH:MM.")); return
        if starts < int(time.time())+60: await ctx.send(_t(loc,"현재보다 최소 1분 뒤로 등록하세요.","Schedule it at least one minute in the future.")); return
        row=guild_row(ctx); events=row.setdefault("events",{})
        if len(events)>=MAX_EVENTS_PER_GUILD: await ctx.send(_t(loc,"서버 일정 저장 한도에 도달했습니다.","This server reached its event limit.")); return
        eid=_event_id(); event_type=_normalize_event_type(종류)
        events[eid]={"id":eid,"title":str(제목)[:100],"type":event_type,"starts_at":starts,"channel_id":int(ctx.channel.id),"creator_id":int(ctx.author.id),"reminders":list(DEFAULT_REMINDERS),"notified":[],"participants":[],"status":"scheduled","locale":loc,"created_at":int(time.time())}
        save_data(); await ctx.send(_t(loc,f"✅ 일정 등록 `{eid}` · <t:{starts}:F> · **{제목}**",f"✅ Event `{eid}` · <t:{starts}:F> · **{제목}**"))

    @bot.command(name="일정삭제",aliases=["deleteevent","removeevent"],help="관리자가 등록한 서버 일정을 삭제합니다.")
    @commands.has_permissions(manage_guild=True)
    async def delete_event(ctx: commands.Context, 일정ID: str)->None:
        loc=locale(ctx); events=guild_row(ctx).setdefault("events",{}); row=events.get(str(일정ID).upper())
        if not isinstance(row,dict): await ctx.send(_t(loc,"일정을 찾지 못했습니다.","Event not found.")); return
        row["status"]="cancelled"; save_data(); await ctx.send(_t(loc,f"🗑️ `{일정ID}` 일정을 취소했습니다.",f"🗑️ Event `{일정ID}` was cancelled."))

    @bot.command(name="게임예약",aliases=["reservegame","gamebooking"],help="게임 일정을 예약합니다. `!게임예약 텍사스홀덤 2026-08-05 21:00 10000 아바돈허용`")
    async def reserve_game(ctx: commands.Context, 게임: str, 날짜: str, 시간: str, 판돈: int=10000, *, 옵션: str="")->None:
        if not await check_registered(ctx): return
        loc=locale(ctx)
        try: starts=_parse_dt(날짜,시간)
        except ValueError as exc: await ctx.send(_t(loc,str(exc),"Use YYYY-MM-DD and HH:MM.")); return
        if starts<int(time.time())+60 or int(판돈)<=0: await ctx.send(_t(loc,"시간과 판돈을 확인하세요.","Check the time and stake.")); return
        eid=_event_id(); allow="아바돈" in 옵션 or "abaddon" in 옵션.casefold()
        guild_row(ctx).setdefault("events",{})[eid]={"id":eid,"title":f"{게임} 예약 경기","type":"게임","starts_at":starts,"channel_id":int(ctx.channel.id),"creator_id":int(ctx.author.id),"reminders":[60,0],"notified":[],"participants":[int(ctx.author.id)],"status":"scheduled","game":str(게임),"stake":int(판돈),"allow_abaddon":allow,"locale":loc,"created_at":int(time.time())}
        save_data(); await ctx.send(_t(loc,f"✅ 게임 예약 `{eid}` · **{게임}** · {판돈:,}칩 · <t:{starts}:F>\n참가: `!예약참가 {eid}`",f"✅ Game reservation `{eid}` · **{게임}** · {판돈:,} chips · <t:{starts}:F>\nJoin: `!joinreservation {eid}`"))

    @bot.command(name="예약참가",aliases=["joinreservation","joinbooking"],help="예약된 게임에 참가합니다.")
    async def join_reservation(ctx: commands.Context, 예약ID: str)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); row=guild_row(ctx).setdefault("events",{}).get(str(예약ID).upper())
        if not isinstance(row,dict) or not row.get("game") or row.get("status")!="scheduled": await ctx.send(_t(loc,"참가 가능한 게임 예약을 찾지 못했습니다.","No joinable game reservation was found.")); return
        players=row.setdefault("participants",[]); uid=int(ctx.author.id)
        if uid not in players: players.append(uid); save_data()
        await ctx.send(_t(loc,f"✅ `{예약ID}` 참가 완료 · 현재 {len(players)}명",f"✅ Joined `{예약ID}` · {len(players)} participants"))

    @bot.command(name="예약취소",aliases=["cancelreservation","cancelbooking"],help="내 게임 예약 참가를 취소하거나 방장이 예약을 취소합니다.")
    async def cancel_reservation(ctx: commands.Context, 예약ID: str)->None:
        loc=locale(ctx); row=guild_row(ctx).setdefault("events",{}).get(str(예약ID).upper())
        if not isinstance(row,dict): await ctx.send(_t(loc,"예약을 찾지 못했습니다.","Reservation not found.")); return
        uid=int(ctx.author.id)
        if uid==int(row.get("creator_id",0)) or getattr(ctx.author.guild_permissions,"manage_guild",False): row["status"]="cancelled"
        else:
            players=row.setdefault("participants",[])
            if uid in players: players.remove(uid)
        save_data(); await ctx.send(_t(loc,"✅ 예약 상태를 변경했습니다.","✅ Reservation updated."))

    @bot.command(name="예약목록",aliases=["reservationlist","gamebookings"],help="서버의 예정 게임 예약을 확인합니다.")
    async def reservation_list(ctx: commands.Context)->None:
        loc=locale(ctx); rows=[r for r in _sorted_events(guild_row(ctx)) if r.get("game")]
        await ctx.send("\n".join(_event_line(loc,r)+f" · {r.get('stake',0):,}칩" for r in rows[:15]) if rows else _t(loc,"예정 게임 예약이 없습니다.","No game reservations are scheduled."))

    @bot.command(name="중계",aliases=["경기중계","broadcast","livebroadcast"],help="현재 채널의 카드게임 또는 서버의 진행 중 경마를 공개 정보만으로 실시간 중계합니다.")
    async def live_broadcast(ctx: commands.Context)->None:
        loc=locale(ctx); state=_broadcast_state(int(ctx.channel.id),int(ctx.guild.id),"auto")
        if state is None: await ctx.send(_t(loc,"이 서버에 진행 중인 카드게임이나 경마가 없습니다.","No card game or horse race is active in this server.")); return
        grow=guild_row(ctx); settings=grow.setdefault("broadcast",{}); channels=settings.setdefault("channels",{})
        source=str(state.get("source","card")); race_owner=int(state.get("race_owner_id",0) or 0)
        embed=_broadcast_embed(bot,loc,state,settings,int(ctx.channel.id)); view=BroadcastView(bot,root,int(ctx.guild.id),int(ctx.channel.id),int(ctx.author.id),loc)
        msg=await ctx.send(embed=embed,view=view); channels[str(ctx.channel.id)]={"message_id":int(msg.id),"owner_id":int(ctx.author.id),"locale":loc,"started_at":int(time.time()),"source":source,"race_owner_id":race_owner}; save_data()

    @bot.command(name="중계종료",aliases=["stopbroadcast","endbroadcast"],help="현재 채널의 자동 경기 중계를 종료합니다.")
    async def stop_broadcast(ctx: commands.Context)->None:
        loc=locale(ctx); row=guild_row(ctx).setdefault("broadcast",{}).setdefault("channels",{}); row.pop(str(ctx.channel.id),None); save_data(); await ctx.send(_t(loc,"⏹️ 중계를 종료했습니다.","⏹️ Broadcast stopped."))

    @bot.command(name="결승중계",aliases=["finalbroadcast","finalscast"],help="최근 또는 지정 정산을 결승 결과 카드로 표시합니다.")
    async def final_broadcast(ctx: commands.Context, 정산ID: str="1")->None:
        loc=locale(ctx); row=_find_settlement(_v1100_root(world_data),정산ID)
        if row is None: await ctx.send(_t(loc,"정산 기록을 찾지 못했습니다.","Settlement not found.")); return
        embed=_format_settlement(loc,row); embed.title=_t(loc,"🎙️ ABADDON 결승 중계 결과","🎙️ ABADDON Final Broadcast Result"); await ctx.send(embed=embed)

    @bot.command(name="중계응원",aliases=["cheermatch","broadcastcheer"],help="현재 경기 중계에 응원 수를 추가합니다. 결과에는 영향을 주지 않습니다.")
    async def cheer_match(ctx: commands.Context)->None:
        loc=locale(ctx); settings=guild_row(ctx).setdefault("broadcast",{}); cheers=settings.setdefault("cheers",{}); key=str(ctx.channel.id); cheers[key]=int(cheers.get(key,0))+1; save_data(); await ctx.send(_t(loc,f"📣 응원 **{cheers[key]:,}회**! 경기 결과에는 영향을 주지 않습니다.",f"📣 **{cheers[key]:,} cheers**! This does not affect the match."))

    @bot.command(name="중계설정",aliases=["broadcastsettings","castsettings"],help="관리자가 중계 갱신 간격과 해설을 설정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def broadcast_settings(ctx: commands.Context, 간격: int=8, 해설: str="켜기")->None:
        loc=locale(ctx); settings=guild_row(ctx).setdefault("broadcast",{}); settings["interval"]=max(5,min(60,int(간격))); settings["commentary"]=str(해설).casefold() not in {"끄기","off","false","0"}; save_data(); await ctx.send(_t(loc,f"✅ 중계 간격 {settings['interval']}초 · 해설 {'켜짐' if settings['commentary'] else '꺼짐'}",f"✅ Broadcast interval {settings['interval']}s · commentary {'on' if settings['commentary'] else 'off'}"))

    @bot.command(name="업적센터",aliases=["achievementcenter","gameachievementscenter"],help="게임 업적과 수집 진행도를 이미지 카드로 확인합니다.")
    async def achievement_center(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); user=get_user(int(ctx.author.id)); _sync_collections_from_history(user,int(ctx.author.id),world_data,int(getattr(ctx.guild,"id",0) or 0)); newly,stats=_scan_achievements(user); save_data(); row=_user(user)
        image=_png_collection(loc,str(ctx.author.display_name),row.get("unlocked",{}),stats)
        embed=_dashboard(bot,loc,"🏅 업적·수집 센터","🏅 Achievement & Collection Center",f"해금 {len(row.get('unlocked',{}))}/{len(ACHIEVEMENTS)} · 새 업적 {len(newly)}개",f"Unlocked {len(row.get('unlocked',{}))}/{len(ACHIEVEMENTS)} · {len(newly)} new",discord.Color.gold())
        embed.set_image(url="attachment://abaddon_achievements.png"); await ctx.send(embed=embed,file=discord.File(image,filename="abaddon_achievements.png"))

    @bot.command(name="업적도감",aliases=["achievementcatalog","achievementbook"],help="전체 게임 업적 조건과 해금 상태를 확인합니다.")
    async def achievement_catalog(ctx: commands.Context)->None: await achievement_center.callback(ctx)

    @bot.command(name="수집도감",aliases=["collectioncatalog","collectionbook"],help="화투·포커 족보·경마 우승마·딜러·장식 수집을 확인합니다.")
    async def collection_catalog(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); user=get_user(int(ctx.author.id)); _sync_collections_from_history(user,int(ctx.author.id),world_data,int(getattr(ctx.guild,"id",0) or 0)); row=_user(user); save_data(); embed=_dashboard(bot,loc,"🧳 수집 도감","🧳 Collection Catalogue","화투·포커·경마·딜러·장식을 한곳에서 확인합니다.","Review hwatu, poker, racing, dealers and decorations in one place.",discord.Color.blue())
        embed.add_field(name=_t(loc,"화투 월","Hwatu Months"),value=f"{len(row.get('hwatu_months',[]))}/12",inline=True)
        embed.add_field(name=_t(loc,"포커 족보","Poker Hands"),value=f"{len(row.get('poker_hands',[]))}/{len(POKER_HANDS)}",inline=True)
        embed.add_field(name=_t(loc,"경마 우승마","Winning Horses"),value=f"{len(row.get('horse_winners',[]))}/6",inline=True)
        embed.add_field(name=_t(loc,"딜러 친밀도","Dealer Affinity"),value=str(sum(int(v or 0) for v in row.get('dealer_affinity',{}).values())),inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="화투수집",aliases=["hwatucollection","hwatucodex"],help="수집한 화투 월과 48장 도감 진행도를 확인합니다.")
    async def hwatu_collection(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); user=get_user(int(ctx.author.id)); _sync_collections_from_history(user,int(ctx.author.id),world_data,int(getattr(ctx.guild,"id",0) or 0)); row=_user(user); save_data(); months=sorted({int(x) for x in row.get("hwatu_months",[]) if str(x).isdigit()})
        await ctx.send(_t(loc,f"🎴 수집 월 **{len(months)}/12** · {', '.join(map(str,months)) or '없음'}\n실제 48장 이미지는 `!화투도감`에서 확인하세요.",f"🎴 Collected months **{len(months)}/12** · {', '.join(map(str,months)) or 'None'}\nUse `!hwatucatalog` for the 48-card art."))

    @bot.command(name="포커족보도감",aliases=["pokerhandcatalog","pokerhandbook"],help="발견한 포커 족보를 확인합니다.")
    async def poker_hand_catalog(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); user=get_user(int(ctx.author.id)); _sync_collections_from_history(user,int(ctx.author.id),world_data,int(getattr(ctx.guild,"id",0) or 0)); save_data(); found=set(_user(user).get("poker_hands",[])); lines=[]
        for key,ko,en in POKER_HANDS: lines.append(f"{'✅' if key in found else '⬛'} {ko if loc=='ko' else en}")
        await ctx.send("\n".join(lines))

    @bot.command(name="경마우승마도감",aliases=["winninghorsecatalog","horsewinnerbook"],help="내가 적중한 경마 우승마를 확인합니다.")
    async def horse_winner_catalog(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); user=get_user(int(ctx.author.id)); _sync_collections_from_history(user,int(ctx.author.id),world_data,int(getattr(ctx.guild,"id",0) or 0)); save_data(); found=_user(user).get("horse_winners",[]); await ctx.send(_t(loc,f"🏇 적중 우승마 **{len(set(found))}/6** · {', '.join(map(str,found)) or '없음'}",f"🏇 Winning horses hit **{len(set(found))}/6** · {', '.join(map(str,found)) or 'None'}"))

    @bot.command(name="딜러친밀도",aliases=["dealeraffinity","dealerbond"],help="NPC 딜러 6명의 친밀도를 확인합니다.")
    async def dealer_affinity(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); user=get_user(int(ctx.author.id)); _sync_collections_from_history(user,int(ctx.author.id),world_data,int(getattr(ctx.guild,"id",0) or 0)); save_data(); affinity=_user(user).setdefault("dealer_affinity",{}); lines=[]
        for key,row in DEALERS.items(): lines.append(f"**{row['ko'] if loc=='ko' else row['en']}** · {int(affinity.get(key,0))}/100")
        await ctx.send("\n".join(lines))

    @bot.command(name="장식도감",aliases=["decorationcatalog","decorbook"],help="개인 카지노 장식 수집 현황을 확인합니다.")
    async def decoration_catalog(ctx: commands.Context)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); v1140=get_user(int(ctx.author.id)).get("v1140",{}); casino=v1140.get("casino",{}) if isinstance(v1140,Mapping) else {}; owned=set(casino.get("decorations",[])) if isinstance(casino,Mapping) else set(); lines=[]
        for key,row in DECORATIONS.items(): lines.append(f"{'✅' if key in owned else '⬛'} {row['ko'] if loc=='ko' else row['en']}")
        await ctx.send("\n".join(lines))

    @bot.command(name="업적전시",aliases=["achievementdisplay","showcaseachievements"],help="프로필에 전시할 업적을 최대 3개 선택합니다.")
    async def achievement_display(ctx: commands.Context, *업적ID: str)->None:
        if not await check_registered(ctx): return
        loc=locale(ctx); row=_user(get_user(int(ctx.author.id))); unlocked=set(row.get("unlocked",{})); selected=[x for x in 업적ID if x in unlocked][:3]
        if not 업적ID:
            labels=[]
            for aid in row.get("display",[]):
                item=next((a for a in ACHIEVEMENTS if a['id']==aid),None)
                if item: labels.append(item['ko'] if loc=='ko' else item['en'])
            await ctx.send(_t(loc,f"🏅 현재 전시: {', '.join(labels) or '없음'}",f"🏅 Displayed: {', '.join(labels) or 'None'}")); return
        row["display"]=selected; save_data(); await ctx.send(_t(loc,f"✅ 업적 {len(selected)}개를 전시했습니다.",f"✅ Displaying {len(selected)} achievements."))

    checks = [
        ("일정 데이터 루트", isinstance(root,dict), "v1190_event_hub"),
        ("서버별 일정 격리", "guilds" in root, "guild-scoped"),
        ("일정 명령", all(bot.get_command(x) is not None for x in ("일정","일정등록","게임예약","예약참가")), "schedule commands"),
        ("공개 중계", all(bot.get_command(x) is not None for x in ("중계","결승중계","중계응원")), "card/race broadcast commands"),
        ("경마 중계", callable(_public_race_state) and callable(_broadcast_state), "public race-state adapter"),
        ("비공개 패 차단", "hands" not in _public_session_state(type("S",(),{"player_ids":[],"pot":0})()), "public-state only"),
        ("업적·수집", all(bot.get_command(x) is not None for x in ("업적센터","수집도감","화투수집","포커족보도감")), "collection commands"),
        ("업적 정의", len(ACHIEVEMENTS)>=12, f"{len(ACHIEVEMENTS)} achievements"),
        ("포커 족보 정의", len(POKER_HANDS)==10, "10 hands"),
    ]

    async def send_audit(ctx: commands.Context, detail: bool=False)->None:
        loc=locale(ctx); ok=sum(1 for _,passed,_ in checks if passed); embed=_dashboard(bot,loc,"🧪 v11.9.0 통합 검수","🧪 v11.9.0 Unified Audit",f"{ok}/{len(checks)} 통과",f"{ok}/{len(checks)} passed",discord.Color.green() if ok==len(checks) else discord.Color.orange())
        if detail:
            embed.add_field(name=_t(loc,"검수 항목","Checks"),value="\n".join(f"{'✅' if p else '❌'} {n} · `{d}`" for n,p,d in checks),inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="1190통합검수",aliases=["v1190audit","eventbroadcastcollectionaudit"],help="v11.7~v11.9 통합 기능을 검사합니다.")
    async def v1190_audit(ctx: commands.Context, 모드: str="")->None: await send_audit(ctx,str(모드).casefold() in {"상세","detail","full"})

    @tasks.loop(seconds=30)
    async def event_and_broadcast_loop() -> None:
        now=int(time.time()); dirty=False
        for gid_key,grow in list(root.get("guilds",{}).items()):
            if not isinstance(grow,MutableMapping): continue
            guild=bot.get_guild(int(gid_key))
            if guild is None: continue
            # reminders and reservation start notices
            events=grow.get("events",{})
            for event in list(events.values()) if isinstance(events,Mapping) else ():
                if not isinstance(event,MutableMapping) or event.get("status")!="scheduled": continue
                starts=int(event.get("starts_at",0) or 0); notified=event.setdefault("notified",[])
                for minutes in event.get("reminders",DEFAULT_REMINDERS):
                    minutes=int(minutes); key=str(minutes); threshold=starts-minutes*60
                    if key in notified or now < threshold: continue
                    # If an event was created after a reminder threshold, mark that old
                    # reminder consumed instead of sending a misleading late notice.
                    if minutes > 0 and int(event.get("created_at", now) or now) > threshold:
                        notified.append(key); dirty=True; continue
                    channel=guild.get_channel(int(event.get("channel_id",0) or 0))
                    if channel is not None:
                        try:
                            event_locale=str(event.get("locale","ko"))
                            prefix="⏰" if int(minutes)>0 else "🚨"
                            when=_t(event_locale,f"{int(minutes)}분 전" if int(minutes)>0 else "시작",f"{int(minutes)} minutes before" if int(minutes)>0 else "Starting now")
                            text=f"{prefix} **{event.get('title','ABADDON Event')}** · {when} · <t:{starts}:R> · `{event.get('id')}`"
                            if event.get("game"):
                                text+=_t(event_locale,f"\n게임 **{event.get('game')}** · {int(event.get('stake',0)):,}칩 · 참가 {len(event.get('participants',[]))}명",f"\nGame **{event.get('game')}** · {int(event.get('stake',0)):,} chips · {len(event.get('participants',[]))} joined")
                                if int(minutes)==0:
                                    text+=_t(event_locale,f"\n방장 시작 명령: `!아바돈초대 {event.get('game')} {int(event.get('stake',0))}`" if event.get("allow_abaddon") else f"\n방장 시작 명령: `!{event.get('game')} {int(event.get('stake',0))}`",f"\nHost start command: `!inviteabaddon {event.get('game')} {int(event.get('stake',0))}`" if event.get("allow_abaddon") else f"\nHost start command: `!{event.get('game')} {int(event.get('stake',0))}`")
                            await channel.send(text)
                        except Exception:
                            pass
                    notified.append(key); dirty=True
                if now>starts+3600: event["status"]="finished"; dirty=True
            # live broadcast updates
            bset=grow.get("broadcast",{}) if isinstance(grow.get("broadcast"),Mapping) else {}
            channels=bset.get("channels",{}) if isinstance(bset.get("channels"),Mapping) else {}
            interval=max(5,min(60,int(bset.get("interval",8) or 8)))
            for cid_key,brow in list(channels.items()):
                if not isinstance(brow,MutableMapping): continue
                last=int(brow.get("last_update",0) or 0)
                if now-last<interval: continue
                channel=guild.get_channel(int(cid_key))
                state=_broadcast_state(int(cid_key),int(gid_key),str(brow.get("source","auto")),int(brow.get("race_owner_id",0) or 0))
                if channel is None or state is None: continue
                try:
                    msg=await channel.fetch_message(int(brow.get("message_id",0)))
                    loc=str(brow.get("locale","ko")); embed=_broadcast_embed(bot,loc,state,bset,int(cid_key)); view=BroadcastView(bot,root,int(gid_key),int(cid_key),int(brow.get("owner_id",0)),loc)
                    await msg.edit(embed=embed,view=view); brow["last_update"]=now; dirty=True
                except Exception:
                    continue
        if dirty: save_data()

    @event_and_broadcast_loop.before_loop
    async def before_loop() -> None: await bot.wait_until_ready()

    @bot.listen("on_ready")
    async def v1190_ready() -> None:
        if not event_and_broadcast_loop.is_running(): event_and_broadcast_loop.start()

    # Upgrade the generic latest-patch commands to the v11.9.0 scope.
    test_cmd=bot.get_command("테스트")
    if test_cmd is not None:
        async def latest_test(ctx: commands.Context, 모드: str="") -> None:
            await send_audit(ctx, str(모드).casefold() in {"상세","detail","full"})
        test_cmd.callback=latest_test
        test_cmd.help=f"ABADDON v{VERSION} 최신 변경 기능을 검사합니다. `!테스트 상세`"
        test_cmd.description=test_cmd.help

    notes=bot.get_command("패치노트")
    if notes is not None:
        async def patch_notes(ctx: commands.Context) -> None:
            loc=locale(ctx); embed=_dashboard(bot,loc,"📌 ABADDON v11.9.0 통합 패치","📌 ABADDON v11.9.0 Unified Update","일정센터·결승 중계·업적 수집을 한 번에 추가했습니다.","Added schedules, final broadcasts and achievement collections together.",discord.Color.dark_purple())
            embed.add_field(name="🗓️ v11.7.0",value=_t(loc,"서버별 이벤트 달력, 게임 예약, 1시간 전·시작 알림","Guild event calendar, game reservations and 1-hour/start reminders"),inline=False)
            embed.add_field(name="📡 v11.8.0",value=_t(loc,"공개 정보 경기 중계, 결승 정산 중계, 안전한 응원","Public-state live broadcast, final settlement cast and safe cheering"),inline=False)
            embed.add_field(name="🏅 v11.9.0",value=_t(loc,"업적 센터, 화투·포커·경마·딜러·장식 수집 도감","Achievement center and hwatu, poker, racing, dealer and decoration collections"),inline=False)
            embed.add_field(name=_t(loc,"점검","Audit"),value=_t(loc,"`!1190통합검수 상세` · `!테스트 상세`","`!v1190audit detail` · `!test detail`"),inline=False)
            await ctx.send(embed=embed)
        notes.callback=patch_notes; notes.help=f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."; notes.description=notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1190_event_broadcast_collection"]
    guide.append({"id":"v1190_event_broadcast_collection","emoji":"🗓️","title":"v11.9.0 일정·중계·수집","hint":"서버 달력/게임 예약 · 공개 경기 중계 · 업적과 수집 도감","commands":["!일정 · !이벤트달력 · !오늘일정 · !이번주일정","!일정등록 · !일정삭제 · !게임예약 · !예약참가 · !예약목록","!중계 · !결승중계 · !중계응원 · !중계설정 · !중계종료","!업적센터 · !업적도감 · !수집도감 · !화투수집 · !포커족보도감","!경마우승마도감 · !딜러친밀도 · !장식도감 · !업적전시","!1190통합검수 상세 · !테스트 상세 · !패치노트"]})

    bot.v1190_version=VERSION  # type: ignore[attr-defined]
    bot.v1190_checks=checks  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] schedule=guild-local reservations=enabled broadcast=public-only collections=achievements+codex reminders=opt-in-events",flush=True)
