from __future__ import annotations

"""ABADDON v11.4.0 unified championship, alliance, casino and story patch.

The module is intentionally additive. It reads the v11 settlement ledger rather
than changing game rules, so older save data and all existing games stay intact.
"""

import asyncio
import datetime as dt
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import ACTIVE_GAMES, ACTIVE_LOBBIES, _reservation_root
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1050_unified_expansion import _root as _v1050_root
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1094_visual_core import draw_wrapped, fit_font, font, png, rounded, truncate

VERSION = "11.4.0"
PATCH_DATE = "2026-08-04"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v1140"

DEALERS: Dict[str, Dict[str, str]] = {
    "iris": {"ko": "아이리스", "en": "Iris", "style_ko": "냉정한 확률형", "style_en": "Calm probability", "personality": "안정형"},
    "raven": {"ko": "레이븐", "en": "Raven", "style_ko": "공격적인 레이즈형", "style_en": "Aggressive raiser", "personality": "공격형"},
    "bella": {"ko": "벨라", "en": "Bella", "style_ko": "블러프형", "style_en": "Bluff specialist", "personality": "블러프형"},
    "sujin": {"ko": "수진", "en": "Sujin", "style_ko": "화투 수집형", "style_en": "Hwatu collector", "personality": "안정형"},
    "shade": {"ko": "쉐이드", "en": "Shade", "style_ko": "복수형", "style_en": "Vengeful", "personality": "복수형"},
    "marie": {"ko": "마리", "en": "Marie", "style_ko": "초보자 배려형", "style_en": "Beginner friendly", "personality": "안정형"},
}

SEASON_EVENTS: Tuple[Dict[str, str], ...] = (
    {"id": "bloodmoon", "ko": "붉은 달", "en": "Blood Moon", "ko_desc": "맞고·고스톱·섯다 승리 시 리그 보너스 +1LP", "en_desc": "Matgo, Go-Stop and Seotda wins gain +1 LP"},
    {"id": "darkcasino", "ko": "암흑 카지노", "en": "Dark Casino", "ko_desc": "포커 계열 승리 시 리그 보너스 +1LP", "en_desc": "Poker-family wins gain +1 LP"},
    {"id": "bankruptnight", "ko": "파산의 밤", "en": "Bankruptcy Night", "ko_desc": "음수 손익으로 완주해도 참가 보너스 +1LP", "en_desc": "Finishing with a negative net still grants +1 LP"},
    {"id": "abaddonrage", "ko": "아바돈 폭주", "en": "ABADDON Rampage", "ko_desc": "이번 주 모든 승리에 리그 보너스 +2LP", "en_desc": "Every win this week gains +2 LP"},
    {"id": "luckyrace", "ko": "행운의 경마", "en": "Lucky Race", "ko_desc": "경마·카드게임을 합친 게임도시 참여 주간", "en_desc": "A mixed horse-racing and card-game city week"},
)

DECORATIONS: Dict[str, Dict[str, Any]] = {
    "neon_sign": {"ko": "네온 간판", "en": "Neon Sign", "cost": 25_000},
    "bloodmoon_table": {"ko": "붉은 달 테이블", "en": "Blood Moon Table", "cost": 80_000},
    "dealer_bell": {"ko": "딜러 호출 벨", "en": "Dealer Bell", "cost": 40_000},
    "abaddon_statue": {"ko": "아바돈 석상", "en": "ABADDON Statue", "cost": 150_000},
    "champion_banner": {"ko": "챔피언 깃발", "en": "Champion Banner", "cost": 100_000},
    "jukebox": {"ko": "폐허 주크박스", "en": "Wasteland Jukebox", "cost": 60_000},
}

CHAPTERS: Tuple[Dict[str, Any], ...] = (
    {"id": 1, "ko": "붉은 달의 초대", "en": "Invitation of the Blood Moon", "need": "play", "value": 1, "reward": 50_000},
    {"id": 2, "ko": "검은 성당의 딜러", "en": "Dealer of the Black Cathedral", "need": "wins", "value": 2, "reward": 80_000},
    {"id": 3, "ko": "파산자의 밤", "en": "Night of the Bankrupt", "need": "games", "value": 5, "reward": 120_000},
    {"id": 4, "ko": "화투 도시의 비밀", "en": "Secret of Hwatu City", "need": "hwatu", "value": 2, "reward": 180_000},
    {"id": 5, "ko": "연합의 결투", "en": "Alliance Duel", "need": "alliance", "value": 1, "reward": 250_000},
    {"id": 6, "ko": "최후의 테이블", "en": "The Final Table", "need": "lp", "value": 20, "reward": 500_000},
)


def _season_id(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(dt.timezone.utc)
    iso = current.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _season_start_ts(now: dt.datetime | None = None) -> int:
    current = now or dt.datetime.now(dt.timezone.utc)
    monday = current - dt.timedelta(days=current.weekday(), hours=current.hour, minutes=current.minute, seconds=current.second, microseconds=current.microsecond)
    return int(monday.timestamp())


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1140_unified", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1140_unified"] = root
    root.setdefault("schema_version", 1)
    root.setdefault("season", {"id": _season_id(), "joined": {}})
    root.setdefault("alliance_war", {"joined": {}, "history": []})
    root.setdefault("snapshots", {})
    root.setdefault("audit_runs", [])
    return root


def _user_root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault("v1140", {})
    if not isinstance(row, dict):
        row = {}
        user["v1140"] = row
    row.setdefault("dealer", "iris")
    row.setdefault("casino", {"name": "생존자 카지노", "decorations": [], "public": True})
    row.setdefault("campaign", {"chapter": 1, "choice": "", "claimed": [], "completed": False})
    return row


def _ledger(world_data: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    root = world_data.get("v1100_game_city", {}) if isinstance(world_data, Mapping) else {}
    rows = root.get("settlements", []) if isinstance(root, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _event() -> Mapping[str, str]:
    week = dt.datetime.now(dt.timezone.utc).isocalendar().week
    return SEASON_EVENTS[(week - 1) % len(SEASON_EVENTS)]


def _is_hwatu(kind: str) -> bool:
    text = str(kind).casefold()
    return any(token in text for token in ("고스톱", "맞고", "섯다", "민화투", "육백", "gostop", "matgo", "seotda", "hwatu"))


def _is_poker(kind: str) -> bool:
    text = str(kind).casefold()
    return any(token in text for token in ("포커", "홀덤", "스터드", "바둑이", "poker", "holdem", "stud", "badugi"))


def _season_rows(world_data: Mapping[str, Any], guild_id: int) -> List[Mapping[str, Any]]:
    start = _season_start_ts()
    return [row for row in _ledger(world_data) if int(row.get("at", 0) or 0) >= start and int(row.get("guild_id", 0) or 0) == int(guild_id)]


def _player_stats(world_data: Mapping[str, Any], guild_id: int) -> Dict[int, Dict[str, Any]]:
    event = _event()
    stats: Dict[int, Dict[str, Any]] = {}
    for row in _season_rows(world_data, guild_id):
        winners = {str(name).casefold() for name in row.get("winners", []) if str(name).strip()} if isinstance(row.get("winners"), list) else set()
        kind = str(row.get("kind", ""))
        players = row.get("players", []) if isinstance(row.get("players"), list) else []
        for player in players:
            if not isinstance(player, Mapping):
                continue
            uid = int(player.get("user_id", 0) or 0)
            if uid <= 0:
                continue
            name = str(player.get("name", uid))
            net = int(player.get("net", 0) or 0)
            won = name.casefold() in winners
            entry = stats.setdefault(uid, {"name": name, "games": 0, "wins": 0, "net": 0, "lp": 0})
            entry["games"] += 1
            entry["wins"] += int(won)
            entry["net"] += net
            points = 1 + (3 if won else 0)
            if won and event.get("id") == "bloodmoon" and _is_hwatu(kind):
                points += 1
            if won and event.get("id") == "darkcasino" and _is_poker(kind):
                points += 1
            if event.get("id") == "bankruptnight" and net < 0:
                points += 1
            if won and event.get("id") == "abaddonrage":
                points += 2
            entry["lp"] += points
    return stats


def _ranked(world_data: Mapping[str, Any], guild_id: int) -> List[Tuple[int, Dict[str, Any]]]:
    rows = list(_player_stats(world_data, guild_id).items())
    rows.sort(key=lambda item: (int(item[1]["lp"]), int(item[1]["wins"]), int(item[1]["net"])), reverse=True)
    return rows


def _alliance_rows(world_data: MutableMapping[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
    alliances = _v1050_root(world_data).get("alliances", {})
    joined = _root(world_data).setdefault("alliance_war", {}).setdefault("joined", {})
    result: List[Tuple[int, Dict[str, Any]]] = []
    if not isinstance(alliances, Mapping):
        return result
    ledger = _ledger(world_data)
    start = _season_start_ts()
    for guild_key, alliance in alliances.items():
        if not isinstance(alliance, Mapping) or str(guild_key) not in joined:
            continue
        guild_id = int(guild_key)
        net = wins = games = 0
        for row in ledger:
            if int(row.get("at", 0) or 0) < start or int(row.get("guild_id", 0) or 0) != guild_id:
                continue
            players = row.get("players", []) if isinstance(row.get("players"), list) else []
            net += sum(int(p.get("net", 0) or 0) for p in players if isinstance(p, Mapping))
            games += 1
            wins += 1 if row.get("winners") else 0
        damage = sum(int(m.get("damage", 0) or 0) for m in alliance.get("members", {}).values() if isinstance(m, Mapping)) if isinstance(alliance.get("members"), Mapping) else 0
        score = wins * 100 + games * 10 + max(0, net // 100_000) + damage // 1_000 + int(alliance.get("xp", 0) or 0)
        result.append((guild_id, {"name": str(alliance.get("name", guild_id)), "score": score, "wins": wins, "games": games, "net": net, "damage": damage, "members": len(alliance.get("members", {})) if isinstance(alliance.get("members"), Mapping) else 0}))
    result.sort(key=lambda item: int(item[1]["score"]), reverse=True)
    return result


def _campaign_counts(world_data: Mapping[str, Any], user_id: int, guild_id: int) -> Dict[str, int]:
    games = wins = hwatu = 0
    for row in _season_rows(world_data, guild_id):
        winners = {str(x).casefold() for x in row.get("winners", [])} if isinstance(row.get("winners"), list) else set()
        for player in row.get("players", []) if isinstance(row.get("players"), list) else []:
            if not isinstance(player, Mapping) or int(player.get("user_id", 0) or 0) != int(user_id):
                continue
            games += 1
            wins += int(str(player.get("name", "")).casefold() in winners)
            hwatu += int(_is_hwatu(str(row.get("kind", ""))))
    lp = int(_player_stats(world_data, guild_id).get(int(user_id), {}).get("lp", 0))
    return {"play": games, "games": games, "wins": wins, "hwatu": hwatu, "lp": lp}


def _send_asset_path(name: str) -> Path:
    return ASSET_ROOT / name


def _personal_casino_image(locale: str, display_name: str, casino: Mapping[str, Any], dealer: Mapping[str, str], level: int, chips: int) -> Any:
    background_path = _send_asset_path("ABADDON_v11.4.0_PERSONAL_CASINO.png")
    if background_path.is_file():
        base = Image.open(background_path).convert("RGB").resize((1280, 720))
    else:
        base = Image.new("RGB", (1280, 720), (22, 18, 28))
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 120))
    base = Image.alpha_composite(base.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(base)
    rounded(draw, (45, 40, 1235, 680), 28, fill=(21, 18, 28, 225), outline=(151, 80, 210, 255), width=4)
    title = _t(locale, f"🎰 {casino.get('name', '생존자 카지노')}", f"🎰 {casino.get('name', 'Survivor Casino')}")
    draw.text((85, 75), truncate(draw, title, font(48, True), 1080), font=font(48, True), fill=(246, 239, 255))
    draw.text((88, 145), _t(locale, f"소유자 {display_name}", f"Owner {display_name}"), font=font(25, True), fill=(89, 211, 255))
    rows = [
        _t(locale, f"카지노 레벨  Lv.{level}", f"Casino level  Lv.{level}"),
        _t(locale, f"현재 칩  {chips:,}", f"Current chips  {chips:,}"),
        _t(locale, f"전속 딜러  {dealer['ko']}", f"House dealer  {dealer['en']}"),
        _t(locale, f"딜러 성향  {dealer['style_ko']}", f"Dealer style  {dealer['style_en']}"),
        _t(locale, f"보유 장식  {len(casino.get('decorations', []))}개", f"Decorations  {len(casino.get('decorations', []))}"),
    ]
    y = 230
    for row in rows:
        draw.text((100, y), row, font=font(30, True), fill=(237, 229, 246))
        y += 70
    draw_wrapped(draw, (650, 245), _t(locale, "게임을 플레이해 카지노 명성을 높이고, 장식과 딜러를 모아 나만의 테이블을 완성하세요.", "Play games, raise your casino fame, and collect decorations and dealers for your own table."), font(27), 500, fill=(225, 213, 232), max_lines=5, spacing=10)
    draw.text((88, 630), f"ABADDON v{VERSION} · {_season_id()}", font=font(20), fill=(167, 155, 175))
    return png(base.convert("RGB"))


def register_v1140_championship_alliance_casino_story(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1140_registered", False):
        return
    bot._abaddon_v1140_registered = True
    root = _root(world_data)

    def ensure_season() -> MutableMapping[str, Any]:
        season = root.setdefault("season", {})
        current = _season_id()
        if str(season.get("id")) != current:
            season.clear()
            season.update({"id": current, "joined": {}, "started": int(time.time())})
        season.setdefault("joined", {})
        return season

    def joined(guild_id: int, user_id: int) -> bool:
        season = ensure_season()
        guilds = season.setdefault("joined", {})
        users = guilds.setdefault(str(int(guild_id)), {})
        return str(int(user_id)) in users

    def join(guild_id: int, user_id: int, name: str) -> None:
        season = ensure_season()
        guilds = season.setdefault("joined", {})
        users = guilds.setdefault(str(int(guild_id)), {})
        users[str(int(user_id))] = {"name": name[:80], "joined": int(time.time())}

    async def send_asset(ctx: commands.Context, filename: str, embed: discord.Embed) -> None:
        path = _send_asset_path(filename)
        if path.is_file():
            attach = f"v1140_{filename.lower().replace(' ', '_')}"
            embed.set_image(url=f"attachment://{attach}")
            await ctx.send(embed=embed, file=discord.File(path, filename=attach))
        else:
            await ctx.send(embed=embed)

    @bot.command(name="챔피언십", aliases=["championship", "abaddonchampionship"], help="현재 시즌 이벤트·리그 점수·챔피언 도전 조건을 확인합니다.")
    async def championship(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        stats = _player_stats(world_data, guild_id).get(int(ctx.author.id), {"games": 0, "wins": 0, "net": 0, "lp": 0})
        event = _event()
        embed = _dashboard(bot, locale, f"🏆 ABADDON 챔피언십 · {ensure_season()['id']}", f"🏆 ABADDON Championship · {ensure_season()['id']}", "주간 성적과 시즌 사건을 합산해 챔피언을 결정합니다.", "Weekly results and the season event decide the champion.", discord.Color.gold())
        embed.add_field(name=_t(locale, "내 시즌", "My Season"), value=_t(locale, f"참가 {'✅' if joined(guild_id, ctx.author.id) else '❌'} · **{stats['lp']}LP** · {stats['wins']}승/{stats['games']}게임 · 손익 {stats['net']:+,}", f"Joined {'✅' if joined(guild_id, ctx.author.id) else '❌'} · **{stats['lp']} LP** · {stats['wins']} wins/{stats['games']} games · net {stats['net']:+,}"), inline=False)
        embed.add_field(name=_t(locale, "이번 시즌 사건", "Current Season Event"), value=f"**{event['ko'] if locale == 'ko' else event['en']}**\n{event['ko_desc'] if locale == 'ko' else event['en_desc']}", inline=False)
        embed.add_field(name=_t(locale, "빠른 명령", "Quick Commands"), value=_t(locale, "`!리그참가` · `!시즌순위` · `!챔피언도전 게임 판돈` · `!NPC딜러`", "`!joinleague` · `!seasonranking` · `!challengechampion game stake` · `!npcdealers`"), inline=False)
        await send_asset(ctx, "ABADDON_v11.4.0_CHAMPIONSHIP.png", embed)

    league_join = bot.get_command("리그참가")
    if league_join is not None:
        old_join = league_join.callback
        async def v1140_join_league(ctx: commands.Context) -> None:
            try:
                await old_join(ctx)
            except Exception:
                if not await check_registered(ctx):
                    return
            join(int(getattr(ctx.guild, "id", 0) or 0), int(ctx.author.id), str(ctx.author.display_name))
            save_data()
            await ctx.send(_t(_ctx_locale(bot, ctx), f"🏆 **{ensure_season()['id']} 챔피언십** 참가 등록도 완료됐습니다.", f"🏆 You are also registered for the **{ensure_season()['id']} Championship**."))
        league_join.callback = v1140_join_league
        league_join.help = "카드 리그와 v11.4.0 챔피언십에 함께 참가합니다."
        league_join.description = league_join.help

    @bot.command(name="시즌순위", aliases=["seasonranking", "championshipranking"], help="현재 서버의 챔피언십 순위를 확인합니다.")
    async def season_ranking(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        rank = _ranked(world_data, guild_id)[:10]
        lines = [f"**{i}. {row['name']}** · {row['lp']}LP · {row['wins']}W/{row['games']}G · {row['net']:+,}" for i, (_, row) in enumerate(rank, 1)]
        embed = _dashboard(bot, locale, "🏅 시즌 순위", "🏅 Season Ranking", f"시즌 `{ensure_season()['id']}`", f"Season `{ensure_season()['id']}`", discord.Color.gold())
        embed.add_field(name=_t(locale, "TOP 10", "TOP 10"), value="\n".join(lines) or _t(locale, "아직 기록이 없습니다.", "No records yet."), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="챔피언도전", aliases=["challengechampion", "championchallenge"], help="10LP 이상이면 챔피언 테이블에서 아바돈에게 도전합니다.")
    async def champion_challenge(ctx: commands.Context, 게임: str = "텍사스홀덤", 판돈: int = 10_000) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        stats = _player_stats(world_data, guild_id).get(int(ctx.author.id), {})
        if int(stats.get("lp", 0) or 0) < 10:
            await ctx.send(_t(locale, "챔피언 도전에는 시즌 10LP가 필요합니다.", "You need 10 season LP to challenge the champion."))
            return
        invite = bot.get_command("아바돈초대")
        if invite is None:
            await ctx.send(_t(locale, "아바돈 초대 명령을 찾지 못했습니다.", "ABADDON invite command is unavailable."))
            return
        profile = _user_root(get_user(int(ctx.author.id)))
        profile["champion_challenges"] = int(profile.get("champion_challenges", 0) or 0) + 1
        save_data()
        await ctx.send(_t(locale, f"👑 챔피언 테이블 개방 · **{게임}** · {int(판돈):,}칩", f"👑 Champion table opened · **{게임}** · {int(판돈):,} chips"))
        try:
            await ctx.invoke(invite, 게임=게임, 금액=max(1_000, int(판돈)))
        except TypeError:
            await ctx.invoke(invite, 게임, max(1_000, int(판돈)))

    @bot.command(name="대회일정", aliases=["tournamentschedule", "championshipschedule"], help="주간 챔피언십과 시즌 종료 일정을 확인합니다.")
    async def tournament_schedule(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        now = dt.datetime.now(dt.timezone.utc)
        next_monday = (now + dt.timedelta(days=7 - now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        await ctx.send(_t(locale, f"📅 시즌 `{ensure_season()['id']}` · 다음 정산까지 약 **{next_monday - now}**\n매주 월요일 새 사건과 순위가 시작됩니다.", f"📅 Season `{ensure_season()['id']}` · about **{next_monday - now}** until settlement.\nA new event and ranking begin every Monday."))

    @bot.command(name="NPC딜러", aliases=["npcdealers", "dealerroster"], help="ABADDON 게임도시의 NPC 딜러 6명을 확인합니다.")
    async def npc_dealers(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        lines = [f"`{key}` · **{row['ko'] if locale == 'ko' else row['en']}** · {row['style_ko'] if locale == 'ko' else row['style_en']}" for key, row in DEALERS.items()]
        embed = _dashboard(bot, locale, "🎩 NPC 딜러 6명", "🎩 Six NPC Dealers", "딜러 선택은 AI 승률을 조작하지 않고 대사·성향·테이블 연출만 바꿉니다.", "Dealer choice changes dialogue, personality and table presentation, never hidden odds.", discord.Color.dark_purple())
        embed.add_field(name=_t(locale, "딜러 목록", "Dealer Roster"), value="\n".join(lines), inline=False)
        await send_asset(ctx, "ABADDON_v11.4.0_NPC_DEALERS.png", embed)

    @bot.command(name="딜러선택", aliases=["selectdealer", "choosedealer"], help="개인 카지노와 아바돈 대전에 사용할 NPC 딜러를 선택합니다.")
    async def dealer_select(ctx: commands.Context, 딜러: str = "iris") -> None:
        if not await check_registered(ctx):
            return
        token = str(딜러).casefold().strip()
        key = next((k for k, row in DEALERS.items() if token in {k, row['ko'].casefold(), row['en'].casefold()}), None)
        locale = _ctx_locale(bot, ctx)
        if key is None:
            await ctx.send(_t(locale, "딜러 키: `iris`, `raven`, `bella`, `sujin`, `shade`, `marie`", "Dealer keys: `iris`, `raven`, `bella`, `sujin`, `shade`, `marie`"))
            return
        user = get_user(int(ctx.author.id))
        _user_root(user)["dealer"] = key
        v1090 = user.setdefault("v1090", {})
        if isinstance(v1090, dict):
            v1090["ai_personality"] = DEALERS[key]["personality"]
        save_data()
        row = DEALERS[key]
        await ctx.send(_t(locale, f"✅ 전속 딜러를 **{row['ko']} · {row['style_ko']}**으로 선택했습니다.", f"✅ House dealer set to **{row['en']} · {row['style_en']}**."))

    @bot.command(name="시즌사건", aliases=["seasonevent", "weeklyevent"], help="이번 주 챔피언십 특별 규칙을 확인합니다.")
    async def season_event(ctx: commands.Context) -> None:
        event = _event(); locale = _ctx_locale(bot, ctx)
        await ctx.send(f"🌒 **{event['ko'] if locale == 'ko' else event['en']}**\n{event['ko_desc'] if locale == 'ko' else event['en_desc']}")

    @bot.command(name="연합대항전", aliases=["alliancewar", "alliancechampionship"], help="연합 대항전 상태와 현재 점수를 확인합니다.")
    async def alliance_war(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx); gid = int(getattr(ctx.guild, "id", 0) or 0)
        rows = dict(_alliance_rows(world_data)); mine = rows.get(gid)
        embed = _dashboard(bot, locale, "⚔️ 연합 대항전", "⚔️ Alliance War", "게임 승리·순손익·협동 보스 피해·연합 경험치를 합산합니다.", "Combines game wins, net earnings, co-op boss damage and alliance XP.", discord.Color.red())
        embed.add_field(name=_t(locale, "우리 연합", "Our Alliance"), value=_t(locale, f"{'참가 중' if mine else '미참가'}" + (f" · {mine['name']} · {mine['score']}점" if mine else " · `!연합대항전참가`"), f"{'Joined' if mine else 'Not joined'}" + (f" · {mine['name']} · {mine['score']} points" if mine else " · `!joinalliancewar`")), inline=False)
        embed.add_field(name=_t(locale, "점수 구성", "Scoring"), value=_t(locale, "승리 100 · 게임 10 · 순이익/100,000 · 보스 피해/1,000 · 연합 XP", "Win 100 · game 10 · net/100,000 · boss damage/1,000 · alliance XP"), inline=False)
        await send_asset(ctx, "ABADDON_v11.4.0_ALLIANCE_WAR.png", embed)

    @bot.command(name="연합대항전참가", aliases=["joinalliancewar", "alliancewarjoin"], help="현재 서버 연합을 시즌 대항전에 등록합니다.")
    async def alliance_war_join(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        gid = int(getattr(ctx.guild, "id", 0) or 0); locale = _ctx_locale(bot, ctx)
        alliances = _v1050_root(world_data).get("alliances", {})
        alliance = alliances.get(str(gid)) if isinstance(alliances, Mapping) else None
        if not isinstance(alliance, Mapping):
            await ctx.send(_t(locale, "먼저 `!연합창설`이 필요합니다.", "Create an alliance first with `!createalliance`."))
            return
        root["alliance_war"].setdefault("joined", {})[str(gid)] = {"at": int(time.time()), "name": str(alliance.get("name", gid))}
        save_data()
        await ctx.send(_t(locale, f"✅ **{alliance.get('name', gid)}** 연합이 대항전에 참가했습니다.", f"✅ Alliance **{alliance.get('name', gid)}** joined the war."))

    @bot.command(name="연합대항순위", aliases=["alliancewarranking", "allianceranking"], help="전체 서버 연합 대항전 순위를 확인합니다.")
    async def alliance_war_ranking(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx); rows = _alliance_rows(world_data)[:10]
        lines = [f"**{i}. {row['name']}** · {row['score']}점 · {row['wins']}승 · {row['members']}명" for i, (_, row) in enumerate(rows, 1)]
        await ctx.send(embed=_dashboard(bot, locale, "🛡️ 연합 대항 순위", "🛡️ Alliance War Ranking", "\n".join(lines) or _t(locale, "참가 연합이 없습니다.", "No alliances have joined."), "\n".join(lines) or _t(locale, "참가 연합이 없습니다.", "No alliances have joined."), discord.Color.orange()))

    @bot.command(name="연합임무", aliases=["alliancemissions", "alliancewarquests"], help="연합 대항전 주간 임무를 확인합니다.")
    async def alliance_missions(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        await ctx.send(_t(locale, "🛡️ 주간 연합 임무\n• 카드게임 20승\n• 화투게임 10회\n• 협동 보스 피해 500,000\n• 연합원 합산 순이익 10,000,000칩", "🛡️ Weekly alliance missions\n• 20 card-game wins\n• 10 hwatu games\n• 500,000 co-op boss damage\n• 10,000,000 combined chip net"))

    @bot.command(name="연합상점", aliases=["allianceshop", "alliancewarshop"], help="연합 대항전에서 해금할 수 있는 장식을 확인합니다.")
    async def alliance_shop(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        await ctx.send(_t(locale, "🏪 연합 상점\n`붉은 성채 테마` 5,000점 · `연합 깃발` 3,000점 · `전쟁 카드 뒷면` 2,500점\n현재 버전에서는 시즌 순위 보상으로 자동 지급됩니다.", "🏪 Alliance Shop\n`Crimson Fortress` 5,000 pts · `Alliance Banner` 3,000 pts · `War Card Back` 2,500 pts\nIn this version, rewards are granted automatically from season ranking."))

    @bot.command(name="개인카지노", aliases=["mycasino", "personalcasino"], help="내 전속 딜러·장식·레벨을 이미지 카드로 확인합니다.")
    async def personal_casino(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); user = get_user(int(ctx.author.id)); profile = _user_root(user); casino = profile["casino"]
        stats = _player_stats(world_data, int(getattr(ctx.guild, "id", 0) or 0)).get(int(ctx.author.id), {})
        level = max(1, 1 + int(stats.get("games", 0) or 0) // 10 + len(casino.get("decorations", [])) // 2)
        dealer = DEALERS.get(str(profile.get("dealer", "iris")), DEALERS["iris"])
        image = _personal_casino_image(locale, str(ctx.author.display_name), casino, dealer, level, casino_chips(user))
        filename = "abaddon_personal_casino.png"
        embed = _dashboard(bot, locale, "🎰 내 개인 카지노", "🎰 My Personal Casino", "장식과 딜러를 모아 나만의 게임 공간을 만듭니다.", "Collect decorations and dealers to build your own game space.", discord.Color.purple())
        embed.set_image(url=f"attachment://{filename}")
        await ctx.send(embed=embed, file=discord.File(image, filename=filename))

    @bot.command(name="카지노꾸미기", aliases=["decoratecasino", "casinodesign"], help="개인 카지노 이름을 변경합니다.")
    async def casino_decorate(ctx: commands.Context, *, 이름: str = "생존자 카지노") -> None:
        if not await check_registered(ctx):
            return
        casino = _user_root(get_user(int(ctx.author.id)))["casino"]
        casino["name"] = str(이름)[:40]
        save_data()
        await ctx.send(_t(_ctx_locale(bot, ctx), f"✅ 개인 카지노 이름: **{casino['name']}**", f"✅ Personal casino name: **{casino['name']}**"))

    @bot.command(name="장식상점", aliases=["decorationshop", "casinodecorstore"], help="개인 카지노 장식 목록과 가격을 확인합니다.")
    async def decoration_shop(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        lines = [f"`{key}` · {row['ko'] if locale == 'ko' else row['en']} · **{row['cost']:,}칩**" for key, row in DECORATIONS.items()]
        await ctx.send("\n".join(lines))

    @bot.command(name="장식구매", aliases=["buydecoration", "purchasedecor"], help="칩으로 개인 카지노 장식을 구매합니다.")
    async def decoration_buy(ctx: commands.Context, 장식: str) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); token = str(장식).casefold(); key = next((k for k, row in DECORATIONS.items() if token in {k, row['ko'].casefold(), row['en'].casefold()}), None)
        if key is None:
            await ctx.send(_t(locale, "`!장식상점`에서 장식 키를 확인하세요.", "Check decoration keys with `!decorationshop`.")); return
        user = get_user(int(ctx.author.id)); casino = _user_root(user)["casino"]; owned = casino.setdefault("decorations", [])
        if key in owned:
            await ctx.send(_t(locale, "이미 보유한 장식입니다.", "You already own this decoration.")); return
        cost = int(DECORATIONS[key]["cost"])
        if casino_chips(user) < cost:
            await ctx.send(_t(locale, f"장식 구매에는 {cost:,}칩이 필요합니다. 게임 손실은 음수가 될 수 있지만 상점 구매는 보유 칩 안에서만 가능합니다.", f"This decoration costs {cost:,} chips. Game losses may go negative, but shop purchases require available chips.")); return
        add_casino_chips(user, -cost); owned.append(key); save_data()
        await ctx.send(_t(locale, f"✅ **{DECORATIONS[key]['ko']}** 구매 완료 · 현재 {casino_chips(user):,}칩", f"✅ Purchased **{DECORATIONS[key]['en']}** · balance {casino_chips(user):,} chips"))

    @bot.command(name="딜러고용", aliases=["hiredealer", "employdealer"], help="NPC 딜러를 개인 카지노 전속 딜러로 고용합니다.")
    async def dealer_hire(ctx: commands.Context, 딜러: str = "iris") -> None:
        await dealer_select.callback(ctx, 딜러)

    @bot.command(name="카지노공개", aliases=["publishcasino", "casinoprivacy"], help="개인 카지노 공개 여부를 설정합니다.")
    async def casino_public(ctx: commands.Context, 상태: str = "켜기") -> None:
        if not await check_registered(ctx):
            return
        enabled = str(상태).casefold() not in {"끄기", "off", "false", "0", "비공개"}
        _user_root(get_user(int(ctx.author.id)))["casino"]["public"] = enabled; save_data()
        await ctx.send(_t(_ctx_locale(bot, ctx), f"✅ 개인 카지노 공개: **{'켜짐' if enabled else '꺼짐'}**", f"✅ Personal casino visibility: **{'on' if enabled else 'off'}**"))

    @bot.command(name="카드캠페인", aliases=["cardcampaign", "storycampaign"], help="ABADDON 스토리형 카드 캠페인 진행 상황을 확인합니다.")
    async def card_campaign(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); campaign = _user_root(get_user(int(ctx.author.id)))["campaign"]; chapter = min(len(CHAPTERS), int(campaign.get("chapter", 1) or 1)); info = CHAPTERS[chapter - 1]
        embed = _dashboard(bot, locale, f"📖 카드 캠페인 · Chapter {chapter}", f"📖 Card Campaign · Chapter {chapter}", info['ko'] if locale == 'ko' else info['en'], info['ko'] if locale == 'ko' else info['en'], discord.Color.dark_teal())
        embed.add_field(name=_t(locale, "진행", "Progress"), value=_t(locale, f"선택 **{campaign.get('choice') or '미정'}** · 수령 보상 {len(campaign.get('claimed', []))}/{len(CHAPTERS)}", f"Choice **{campaign.get('choice') or 'unset'}** · rewards {len(campaign.get('claimed', []))}/{len(CHAPTERS)}"), inline=False)
        embed.add_field(name=_t(locale, "명령", "Commands"), value=_t(locale, "`!캠페인선택 용기|거래` · `!캠페인진행` · `!캠페인보상`", "`!campaignchoice courage|deal` · `!advancecampaign` · `!campaignreward`"), inline=False)
        await send_asset(ctx, "ABADDON_v11.4.0_STORY_CAMPAIGN.png", embed)

    @bot.command(name="캠페인선택", aliases=["campaignchoice", "storychoice"], help="스토리 캠페인의 기본 성향을 선택합니다.")
    async def campaign_choice(ctx: commands.Context, 선택: str = "용기") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); token = str(선택).casefold()
        if token not in {"용기", "거래", "courage", "deal"}:
            await ctx.send(_t(locale, "`용기` 또는 `거래`를 선택하세요.", "Choose `courage` or `deal`.")); return
        value = "용기" if token in {"용기", "courage"} else "거래"
        _user_root(get_user(int(ctx.author.id)))["campaign"]["choice"] = value; save_data()
        await ctx.send(_t(locale, f"✅ 캠페인 성향: **{value}**", f"✅ Campaign path: **{'Courage' if value == '용기' else 'Deal'}**"))

    def campaign_ready(ctx: commands.Context, info: Mapping[str, Any]) -> Tuple[bool, str]:
        uid = int(ctx.author.id); gid = int(getattr(ctx.guild, "id", 0) or 0); counts = _campaign_counts(world_data, uid, gid)
        need = str(info["need"]); target = int(info["value"])
        if need == "alliance":
            alliances = _v1050_root(world_data).get("alliances", {})
            alliance = alliances.get(str(gid)) if isinstance(alliances, Mapping) else None
            ok = isinstance(alliance, Mapping) and str(uid) in alliance.get("members", {})
            return ok, f"alliance={'yes' if ok else 'no'}"
        current = int(counts.get(need, 0))
        return current >= target, f"{need}={current}/{target}"

    @bot.command(name="캠페인진행", aliases=["advancecampaign", "campaignadvance"], help="현재 챕터 조건을 검사하고 다음 챕터로 진행합니다.")
    async def campaign_advance(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); campaign = _user_root(get_user(int(ctx.author.id)))["campaign"]
        if not campaign.get("choice"):
            await ctx.send(_t(locale, "먼저 `!캠페인선택 용기` 또는 `!캠페인선택 거래`를 사용하세요.", "First use `!campaignchoice courage` or `!campaignchoice deal`.")); return
        if int(campaign.get("ready_reward", 0) or 0) > 0:
            await ctx.send(_t(locale, "먼저 `!캠페인보상`으로 이전 챕터 보상을 수령하세요.", "Claim the previous chapter with `!campaignreward` first.")); return
        chapter = min(len(CHAPTERS), int(campaign.get("chapter", 1) or 1)); info = CHAPTERS[chapter - 1]; ok, detail = campaign_ready(ctx, info)
        if not ok:
            await ctx.send(_t(locale, f"아직 챕터 조건을 충족하지 못했습니다: `{detail}`", f"Chapter requirement is not complete: `{detail}`")); return
        campaign["ready_reward"] = chapter
        if chapter < len(CHAPTERS):
            campaign["chapter"] = chapter + 1
        else:
            campaign["completed"] = True
        save_data()
        await ctx.send(_t(locale, f"✅ Chapter {chapter} 완료 · `!캠페인보상`으로 {int(info['reward']):,}칩을 받으세요.", f"✅ Chapter {chapter} complete · claim {int(info['reward']):,} chips with `!campaignreward`."))

    @bot.command(name="캠페인보상", aliases=["campaignreward", "storyreward"], help="완료한 캠페인 챕터 보상을 수령합니다.")
    async def campaign_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); user = get_user(int(ctx.author.id)); campaign = _user_root(user)["campaign"]; chapter = int(campaign.get("ready_reward", 0) or 0); claimed = campaign.setdefault("claimed", [])
        if chapter <= 0 or chapter in claimed:
            await ctx.send(_t(locale, "수령 가능한 새 보상이 없습니다.", "No new campaign reward is available.")); return
        info = CHAPTERS[chapter - 1]; reward = int(info["reward"]); add_casino_chips(user, reward); claimed.append(chapter); campaign["ready_reward"] = 0; save_data()
        await ctx.send(_t(locale, f"🎁 Chapter {chapter} 보상 **+{reward:,}칩** · 현재 {casino_chips(user):,}칩", f"🎁 Chapter {chapter} reward **+{reward:,} chips** · balance {casino_chips(user):,}"))

    @bot.command(name="캠페인기록", aliases=["campaignlog", "storylog"], help="완료 챕터·선택·보상 기록을 확인합니다.")
    async def campaign_log(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx); campaign = _user_root(get_user(int(ctx.author.id)))["campaign"]
        await ctx.send(_t(locale, f"📚 현재 Chapter **{campaign.get('chapter', 1)}** · 선택 **{campaign.get('choice') or '미정'}** · 보상 {len(campaign.get('claimed', []))}/{len(CHAPTERS)} · 완결 {'✅' if campaign.get('completed') else '❌'}", f"📚 Current Chapter **{campaign.get('chapter', 1)}** · choice **{campaign.get('choice') or 'unset'}** · rewards {len(campaign.get('claimed', []))}/{len(CHAPTERS)} · completed {'✅' if campaign.get('completed') else '❌'}"))

    @bot.command(name="스토리도감", aliases=["storycodex", "campaigncodex"], help="카드 캠페인 전체 챕터 목록을 확인합니다.")
    async def story_codex(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        lines = [f"**Chapter {row['id']}** · {row['ko'] if locale == 'ko' else row['en']} · {int(row['reward']):,}" for row in CHAPTERS]
        await ctx.send("\n".join(lines))

    @tasks.loop(seconds=45)
    async def snapshot_loop() -> None:
        snapshots = root.setdefault("snapshots", {})
        active_channels = set()
        for channel_id, session in list(ACTIVE_GAMES.items()):
            active_channels.add(str(channel_id))
            snapshots[str(channel_id)] = {
                "game_id": str(getattr(session, "game_id", "")),
                "kind": str(getattr(session, "kind", "")),
                "guild_id": int(getattr(getattr(getattr(session, "message", None), "guild", None), "id", 0) or 0),
                "channel_id": int(channel_id),
                "stage": str(getattr(session, "stage_label", getattr(session, "stage", ""))),
                "current_uid": int(getattr(session, "current_uid", 0) or 0),
                "pot": int(getattr(session, "pot", 0) or 0),
                "updated": int(time.time()),
                "status": "active",
            }
        changed = bool(active_channels)
        for key in list(snapshots):
            if key not in active_channels and isinstance(snapshots[key], dict) and snapshots[key].get("status") == "active":
                snapshots[key]["status"] = "stale"
                changed = True
        if changed:
            save_data()

    @bot.listen("on_ready")
    async def v1140_start_snapshot_loop() -> None:
        if not snapshot_loop.is_running():
            snapshot_loop.start()

    old_recovery = bot.get_command("게임복구")
    if old_recovery is not None:
        async def v1140_recovery(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx); gid = int(getattr(ctx.guild, "id", 0) or 0); snapshots = root.get("snapshots", {})
            rows = [row for row in snapshots.values() if isinstance(row, Mapping) and int(row.get("guild_id", 0) or 0) in {0, gid}]
            active = sum(1 for row in rows if row.get("status") == "active"); stale = sum(1 for row in rows if row.get("status") == "stale")
            reservations = _reservation_root(world_data).get("reservations", {})
            await ctx.send(_t(locale, f"🛟 체크포인트 **{active}개 활성 / {stale}개 중단** · 미정산 예약 **{len(reservations) if isinstance(reservations, Mapping) else 0}개**\n복구 가능한 세션은 상태를 재표시하며, 복구 불가 세션은 기존 예약 복구기가 실제 납부액을 환불합니다.", f"🛟 Checkpoints **{active} active / {stale} interrupted** · pending reservations **{len(reservations) if isinstance(reservations, Mapping) else 0}**\nRecoverable sessions can be re-displayed; unrecoverable sessions use the existing reservation refund path."))
        old_recovery.callback = v1140_recovery
        old_recovery.help = "진행 게임 체크포인트와 안전 환불 상태를 확인합니다."
        old_recovery.description = old_recovery.help

    def checks() -> List[Tuple[str, bool, str]]:
        assets = list(ASSET_ROOT.glob("*.png"))
        names = ["챔피언십", "시즌순위", "챔피언도전", "NPC딜러", "연합대항전", "개인카지노", "카드캠페인"]
        return [
            ("v11.0.1 체크포인트", bot.get_command("게임복구") is not None and hasattr(snapshot_loop, "start"), "45초 상태 체크포인트 + 기존 안전 환불"),
            ("v11.1 챔피언십", all(bot.get_command(name) is not None for name in names[:4]), "리그/딜러/주간 사건"),
            ("v11.2 연합 대항전", bot.get_command("연합대항전") is not None and bot.get_command("연합대항순위") is not None, "연합 승리·손익·보스 피해 합산"),
            ("v11.3 개인 카지노", bot.get_command("개인카지노") is not None and bot.get_command("장식구매") is not None, "딜러/장식/이미지 카드"),
            ("v11.4 스토리 캠페인", bot.get_command("카드캠페인") is not None and bot.get_command("캠페인진행") is not None, f"chapters={len(CHAPTERS)}"),
            ("이미지 자산 일괄", len(assets) >= 8 and all(path.stat().st_size > 10_000 for path in assets), f"assets={len(assets)}"),
            ("한영 분리 명령", all(any(ord(ch) < 128 for ch in alias) for name in names if (cmd := bot.get_command(name)) for alias in cmd.aliases[:1]), "ASCII aliases"),
            ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
        ]

    @bot.command(name="1140통합검수", aliases=["v1140audit", "unified1140audit"], help="v11.0.1~v11.4.0에서 추가·수정한 기능만 검사합니다.")
    async def v1140_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx); rows = checks(); passed = sum(1 for _, ok, _ in rows if ok)
        embed = _dashboard(bot, locale, f"🧪 ABADDON v{VERSION} 검수 · {passed}/{len(rows)}", f"🧪 ABADDON v{VERSION} Audit · {passed}/{len(rows)}", "이번 통합 패치 범위만 검사합니다.", "Checks only this unified patch scope.", discord.Color.green() if passed == len(rows) else discord.Color.orange())
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!1140통합검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1140_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await v1140_audit.callback(ctx, 모드)
        test_command.callback = v1140_test
        test_command.help = "v11.0.1~v11.4.0 통합 패치에서 변경한 기능만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1140_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx); event = _event()
            embed = _dashboard(bot, locale, f"🌆 ABADDON v{VERSION} — 챔피언십·연합·카지노·스토리", f"🌆 ABADDON v{VERSION} — Championship, Alliance, Casino & Story", "v11.0.1부터 v11.4.0까지 한 번에 적용한 기능만 표시합니다.", "Shows only features applied in the v11.0.1–v11.4.0 unified patch.", discord.Color.dark_purple())
            embed.add_field(name="🛟 v11.0.1", value=_t(locale, "게임 상태 체크포인트·중단 세션 감지·기존 예약 안전 환불 경로 강화", "Game checkpoints, interrupted-session detection and safer reservation recovery"), inline=False)
            embed.add_field(name="🏆 v11.1.0", value=_t(locale, f"챔피언십·NPC 딜러 6명·주간 사건 **{event['ko']}**", f"Championship, six NPC dealers and weekly event **{event['en']}**"), inline=False)
            embed.add_field(name="⚔️ v11.2.0", value=_t(locale, "연합 대항전·연합 순위·주간 임무·시즌 장식 보상", "Alliance war, ranking, weekly missions and seasonal cosmetic rewards"), inline=False)
            embed.add_field(name="🎰 v11.3.0", value=_t(locale, "개인 카지노 이미지 카드·딜러 선택·장식 상점·공개 설정", "Personal casino image card, dealer selection, decoration shop and visibility"), inline=False)
            embed.add_field(name="📖 v11.4.0", value=_t(locale, "6챕터 카드 캠페인·분기 선택·조건 진행·보상·스토리 도감", "Six-chapter card campaign, path choices, progression, rewards and story codex"), inline=False)
            await send_asset(ctx, "ABADDON_v11.4.0_MASTER_POSTER.png", embed)
        patch_notes.callback = v1140_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 통합 패치노트를 표시합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1140_unified"]
    guide.append({
        "id": "v1140_unified", "emoji": "🌆", "title": "v11.4.0 챔피언십·연합·카지노·스토리",
        "hint": "체크포인트 · 챔피언십/NPC 딜러 · 연합 대항전 · 개인 카지노 · 6챕터 카드 캠페인",
        "commands": [
            "!챔피언십 · !리그참가 · !시즌순위 · !챔피언도전 · !대회일정",
            "!NPC딜러 · !딜러선택 · !시즌사건",
            "!연합대항전 · !연합대항전참가 · !연합대항순위 · !연합임무 · !연합상점",
            "!개인카지노 · !카지노꾸미기 · !장식상점 · !장식구매 · !딜러고용 · !카지노공개",
            "!카드캠페인 · !캠페인선택 · !캠페인진행 · !캠페인보상 · !캠페인기록 · !스토리도감",
            "!1140통합검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1140_version = VERSION  # type: ignore[attr-defined]
    bot.v1140_checks = checks  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] checkpoint=45s championship=enabled npc_dealers=6 alliance_war=enabled personal_casino=enabled campaign_chapters={len(CHAPTERS)} assets=batched", flush=True)
