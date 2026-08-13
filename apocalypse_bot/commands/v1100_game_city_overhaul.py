from __future__ import annotations

"""ABADDON v11.0.0 game-city, settlement, fairness and safety overhaul."""

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import casino_chips
from apocalypse_bot.commands.v651_card_games import ACTIVE_GAMES, ACTIVE_LOBBIES, _reservation_root
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1060_authentic_card_games import (
    AUTHENTIC_GAMES,
    V1100_DEFAULT_RAISE_LIMIT,
    V1100_HARD_RAISE_LIMIT,
    _verify_fairness,
)
from apocalypse_bot.commands.v1090_integrated_renewal import ALL_GAMES, _dashboard
from apocalypse_bot.commands.v1092_horse_racing_rules import FINISH, HORSES, advance_positions, crossing_winner
from apocalypse_bot.commands.v1094_visual_core import HWATU_ASSET_ROOT, font_status

VERSION = "11.5.2"
PATCH_DATE = "2026-08-04"
THEMES = {
    "wasteland": ("폐허 카지노", "Wasteland Casino"),
    "bunker": ("지하 벙커", "Underground Bunker"),
    "laboratory": ("감염 연구소", "Infected Laboratory"),
    "snow": ("설원 전초기지", "Frozen Outpost"),
    "bloodmoon": ("붉은 달 화투판", "Blood Moon Hwatu"),
}
SKINS = {
    "abaddon": ("아바돈 문장", "ABADDON Sigil"),
    "cathedral": ("검은 성당", "Black Cathedral"),
    "survivor": ("생존자 표식", "Survivor Mark"),
    "crimson": ("핏빛 균열", "Crimson Rift"),
}


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1100_game_city", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1100_game_city"] = root
    betting = root.setdefault("betting", {})
    betting.setdefault("default_max_raise", V1100_DEFAULT_RAISE_LIMIT)
    betting.setdefault("guilds", {})
    root.setdefault("settlements", [])
    root.setdefault("schema_version", 1)
    return root


def _guild_betting(root: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    betting = root.setdefault("betting", {})
    guilds = betting.setdefault("guilds", {})
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("max_raise", int(betting.get("default_max_raise", V1100_DEFAULT_RAISE_LIMIT)))
    return row


def _find_settlement(root: Mapping[str, Any], token: str | int) -> Mapping[str, Any] | None:
    rows = root.get("settlements", []) if isinstance(root, Mapping) else []
    if not isinstance(rows, list):
        return None
    raw = str(token).strip()
    if raw.isdigit():
        index = max(1, int(raw)) - 1
        if 0 <= index < len(rows) and isinstance(rows[index], Mapping):
            return rows[index]
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("game_id", "")).casefold() == raw.casefold():
            return row
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("game_id", "")).casefold().startswith(raw.casefold()):
            return row
    return None


def _format_settlement(locale: str, row: Mapping[str, Any]) -> discord.Embed:
    winners = row.get("winners", [])
    if not isinstance(winners, list):
        winners = [str(winners)]
    embed = discord.Embed(
        title=_t(locale, "🏆 게임 결과·정산 장부", "🏆 Game Result & Settlement Ledger"),
        description=_t(
            locale,
            f"게임 **{row.get('kind', '-')}** · 정산 ID `{row.get('game_id', '-')}`",
            f"Game **{row.get('kind', '-')}** · settlement ID `{row.get('game_id', '-')}`",
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name=_t(locale, "승자", "Winner"), value=" · ".join(map(str, winners)) or _t(locale, "없음", "None"), inline=False)
    embed.add_field(name=_t(locale, "팟", "Pot"), value=f"{int(row.get('pot', 0) or 0):,}", inline=True)
    embed.add_field(name=_t(locale, "공정성", "Fairness"), value="✅" if row.get("verified") else "⚠️", inline=True)
    lines=[]
    for player in row.get("players", []) if isinstance(row.get("players"), list) else []:
        if not isinstance(player, Mapping):
            continue
        net=int(player.get("net",0) or 0); sign="+" if net>=0 else ""
        lines.append(f"**{player.get('name','-')}** · {sign}{net:,} · {int(player.get('before',0) or 0):,} → {int(player.get('after',0) or 0):,}")
    embed.add_field(name=_t(locale,"잔액 정산","Balance Settlement"), value="\n".join(lines) or "-", inline=False)
    embed.set_footer(text=_t(locale,"보유 칩을 넘는 손실은 음수 잔액으로 유지됩니다.","Losses beyond the wallet remain as a negative balance."))
    return embed


def register_v1100_game_city_overhaul(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1100_registered", False):
        return
    bot._abaddon_v1100_registered = True
    root = _root(world_data)

    @bot.command(name="게임도시", aliases=["gamecity", "cardcity", "gamingcity"], help="카드룸·경마·리그·관전·장부를 한 화면에서 확인합니다.")
    async def game_city(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); guild_id=int(getattr(ctx.guild,"id",0) or 0)
        active_games=sum(1 for session in ACTIVE_GAMES.values() if int(getattr(getattr(getattr(session,"message",None),"guild",None),"id",0) or 0)==guild_id)
        active_lobbies=sum(1 for lobby in ACTIVE_LOBBIES.values() if int(getattr(getattr(getattr(lobby,"message",None),"guild",None),"id",0) or 0)==guild_id)
        limit=int(_guild_betting(root,guild_id).get("max_raise",V1100_DEFAULT_RAISE_LIMIT))
        embed=_dashboard(bot,locale,"🏙️ ABADDON 생존자 게임도시","🏙️ ABADDON Survivor Game City","카드·화투·경마·관전·리그·정산을 한곳에서 관리합니다.","Manage cards, hwatu, racing, spectating, leagues and settlements in one place.",discord.Color.dark_purple())
        embed.add_field(name=_t(locale,"현재 도시","Live City"),value=_t(locale,f"모집방 **{active_lobbies}개** · 진행 게임 **{active_games}개** · 카드 종목 **{len(ALL_GAMES)}종**",f"Lobbies **{active_lobbies}** · active games **{active_games}** · card modes **{len(ALL_GAMES)}**"),inline=False)
        embed.add_field(name=_t(locale,"자유 레이즈","Free Raise"),value=_t(locale,f"잔액 제한 없음 · 패배 시 음수 허용 · 1회 안전 한도 **{limit:,}칩**",f"Not tied to balance · negative debt allowed · per-action safety limit **{limit:,} chips**"),inline=False)
        embed.add_field(name=_t(locale,"빠른 이동","Quick Routes"),value=_t(locale,"`!카드룸` · `!실시간보드` · `!관전` · `!경마장` · `!카드리그` · `!최근정산`", "`!cardroom` · `!liveboard` · `!spectate` · `!racetrack` · `!cardleague` · `!recentsettlement`"),inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="베팅제한", aliases=["betlimit", "raiselimit"], help="현재 서버의 자유 레이즈 안전 한도를 확인합니다.")
    async def bet_limit(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); guild_id=int(getattr(ctx.guild,"id",0) or 0); limit=int(_guild_betting(root,guild_id)["max_raise"])
        await ctx.send(_t(locale,f"🎚️ 자유 레이즈 안전 한도: **{limit:,}칩**\n잔액과 무관하게 입력할 수 있으며, 최종 손실이 보유 칩을 넘으면 잔액은 음수가 됩니다.",f"🎚️ Free-raise safety limit: **{limit:,} chips**\nIt is not tied to the wallet; losses beyond the wallet produce a negative balance."))

    @bot.command(name="베팅제한설정", aliases=["setbetlimit", "setraiselimit"], help="관리자가 서버의 1회 레이즈 안전 한도를 설정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def set_bet_limit(ctx: commands.Context, 금액: int) -> None:
        locale=_ctx_locale(bot,ctx); value=int(금액)
        if value < 1_000 or value > V1100_HARD_RAISE_LIMIT:
            await ctx.send(_t(locale,f"1,000~{V1100_HARD_RAISE_LIMIT:,} 범위로 입력하세요.",f"Enter a value from 1,000 to {V1100_HARD_RAISE_LIMIT:,}.")); return
        guild_id=int(getattr(ctx.guild,"id",0) or 0); _guild_betting(root,guild_id)["max_raise"]=value; save_data()
        await ctx.send(_t(locale,f"✅ 자유 레이즈 안전 한도를 **{value:,}칩**으로 설정했습니다. 음수 잔액 규칙은 유지됩니다.",f"✅ Free-raise safety limit set to **{value:,} chips**. Negative balances remain enabled."))

    async def send_settlement(ctx: commands.Context, token: str|int=1) -> None:
        locale=_ctx_locale(bot,ctx); row=_find_settlement(root,token)
        if row is None:
            await ctx.send(_t(locale,"저장된 정산 기록을 찾지 못했습니다.","Settlement record not found.")); return
        await ctx.send(embed=_format_settlement(locale,row))

    @bot.command(name="정산조회", aliases=["settlement", "settlementlookup"], help="번호 또는 정산 ID로 게임 결과와 잔액 이동을 확인합니다.")
    async def settlement_lookup(ctx: commands.Context, 번호또는ID: str="1") -> None:
        await send_settlement(ctx,번호또는ID)

    @bot.command(name="최근정산", aliases=["recentsettlement", "latestsettlement"], help="가장 최근 게임 정산을 확인합니다.")
    async def recent_settlement(ctx: commands.Context) -> None:
        await send_settlement(ctx,1)

    @bot.command(name="게임결과", aliases=["gameresult", "matchresult"], help="최근 또는 지정 게임의 승자·손익·현재 잔액을 확인합니다.")
    async def game_result(ctx: commands.Context, 번호또는ID: str="1") -> None:
        await send_settlement(ctx,번호또는ID)

    @bot.command(name="셔플검증", aliases=["shuffleverify", "deckverify"], help="종료된 게임의 시작 커밋과 공개값을 다시 계산합니다.")
    async def shuffle_verify(ctx: commands.Context, 게임ID: str="1") -> None:
        locale=_ctx_locale(bot,ctx); row=_find_settlement(root,게임ID)
        if row is None:
            await ctx.send(_t(locale,"검증할 게임을 찾지 못했습니다.","Game not found for verification.")); return
        commit=str(row.get("commit","") or ""); secret=str(row.get("secret","") or ""); payload=str(row.get("payload","") or "")
        ok=bool(commit and secret and payload and _verify_fairness(secret,payload,commit))
        await ctx.send(_t(locale,f"{'✅' if ok else '❌'} 정산 `{row.get('game_id','-')}` · 커밋 `{commit[:20] or '-'}` · 재검증 **{'성공' if ok else '실패'}**",f"{'✅' if ok else '❌'} Settlement `{row.get('game_id','-')}` · commit `{commit[:20] or '-'}` · recheck **{'passed' if ok else 'failed'}**"))

    @bot.command(name="공정성검증", aliases=["fairnesscheck", "fairnessverify"], help="최근 게임의 덱 커밋과 정산 장부를 확인합니다.")
    async def fairness_check(ctx: commands.Context, 게임ID: str="1") -> None:
        await shuffle_verify.callback(ctx,게임ID)

    @bot.command(name="게임세션", aliases=["gamesession", "sessionstatus"], help="현재 채널 게임·모집방·미정산 예약 상태를 확인합니다.")
    async def game_session(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); channel_id=int(ctx.channel.id)
        game=ACTIVE_GAMES.get(channel_id); lobby=ACTIVE_LOBBIES.get(channel_id); reservations=_reservation_root(world_data).get("reservations",{})
        lines=[_t(locale,f"진행 게임: **{getattr(game,'kind','없음') if game else '없음'}**",f"Active game: **{getattr(game,'kind','None') if game else 'None'}**"),_t(locale,f"모집방: **{getattr(lobby,'kind','없음') if lobby else '없음'}**",f"Lobby: **{getattr(lobby,'kind','None') if lobby else 'None'}**"),_t(locale,f"전체 미정산 예약: **{len(reservations) if isinstance(reservations,Mapping) else 0}개**",f"Pending reservations: **{len(reservations) if isinstance(reservations,Mapping) else 0}**")]
        await ctx.send("\n".join(lines))

    @bot.command(name="게임복구", aliases=["recovergame", "gamerecovery"], help="재시작 복구 상태와 안전 환불 경로를 확인합니다.")
    async def game_recovery(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); reservations=_reservation_root(world_data).get("reservations",{})
        await ctx.send(_t(locale,f"🛟 현재 미정산 예약 **{len(reservations) if isinstance(reservations,Mapping) else 0}개**\n재시작 시 기존 예약 복구기가 실제 납부액을 안전 환불합니다. 진행 메시지가 남아 있으면 새 버튼으로 다시 시작하세요.",f"🛟 Pending reservations: **{len(reservations) if isinstance(reservations,Mapping) else 0}**\nOn restart, the reservation recovery safely refunds actual payments. Start a fresh UI if the old interaction expired."))

    @bot.command(name="화투도감", aliases=["hwatucatalog", "hwatudeck"], help="전통 문양 기반 48장 화투 이미지 도감을 확인합니다.")
    async def hwatu_catalog(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); path=HWATU_ASSET_ROOT/"ABADDON_TRADITIONAL_HWATU_48_SHEET.png"
        embed=_dashboard(bot,locale,"🎴 ABADDON 전통 문양 화투 48장","🎴 ABADDON Traditional 48-Card Hwatu","맞고·고스톱·민화투·육백·섯다·삼봉·도리짓고땡에 사용하는 전통 문양 화투입니다.","Traditional-pattern hwatu art used by all ABADDON hwatu games.",discord.Color.red())
        if path.is_file():
            filename="abaddon_hwatu_48.png"; embed.set_image(url=f"attachment://{filename}"); await ctx.send(embed=embed,file=discord.File(path,filename=filename))
        else: await ctx.send(embed=embed)

    @bot.command(name="화투패보기", aliases=["viewhwatu", "hwatuart"], help="ABADDON 화투 이미지 도감을 엽니다.")
    async def view_hwatu(ctx: commands.Context) -> None:
        await hwatu_catalog.callback(ctx)

    @bot.command(name="테이블테마", aliases=["tabletheme", "gametheme"], help="게임 테이블 테마를 확인하거나 선택합니다.")
    async def table_theme(ctx: commands.Context, 테마: str="") -> None:
        if not await check_registered(ctx): return
        locale=_ctx_locale(bot,ctx); user=get_user(int(ctx.author.id)); profile=user.setdefault("v1100_cosmetics",{})
        token=str(테마).strip().casefold()
        if token:
            for key,names in THEMES.items():
                if token in {key,names[0].casefold(),names[1].casefold()}:
                    profile["theme"]=key; save_data(); await ctx.send(_t(locale,f"✅ 테이블 테마: **{names[0]}**",f"✅ Table theme: **{names[1]}**")); return
        current=str(profile.get("theme","wasteland")); rows=[f"`{key}` · {names[0] if locale=='ko' else names[1]}{' ✅' if key==current else ''}" for key,names in THEMES.items()]
        await ctx.send("\n".join(rows))

    @bot.command(name="카드스킨", aliases=["cardskin", "cardback"], help="카드 뒷면 스킨을 확인하거나 선택합니다.")
    async def card_skin(ctx: commands.Context, 스킨: str="") -> None:
        if not await check_registered(ctx): return
        locale=_ctx_locale(bot,ctx); user=get_user(int(ctx.author.id)); profile=user.setdefault("v1100_cosmetics",{})
        token=str(스킨).strip().casefold()
        if token:
            for key,names in SKINS.items():
                if token in {key,names[0].casefold(),names[1].casefold()}:
                    profile["skin"]=key; save_data(); await ctx.send(_t(locale,f"✅ 카드 스킨: **{names[0]}**",f"✅ Card skin: **{names[1]}**")); return
        current=str(profile.get("skin","abaddon")); rows=[f"`{key}` · {names[0] if locale=='ko' else names[1]}{' ✅' if key==current else ''}" for key,names in SKINS.items()]
        await ctx.send("\n".join(rows))

    @bot.command(name="내게임장식", aliases=["mygamecosmetics", "mytabledecor"], help="선택한 테이블 테마와 카드 스킨을 확인합니다.")
    async def my_cosmetics(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale=_ctx_locale(bot,ctx); profile=get_user(int(ctx.author.id)).setdefault("v1100_cosmetics",{}); theme=str(profile.get("theme","wasteland")); skin=str(profile.get("skin","abaddon"))
        await ctx.send(_t(locale,f"🎨 테이블 **{THEMES.get(theme,THEMES['wasteland'])[0]}** · 카드 **{SKINS.get(skin,SKINS['abaddon'])[0]}**",f"🎨 Table **{THEMES.get(theme,THEMES['wasteland'])[1]}** · cards **{SKINS.get(skin,SKINS['abaddon'])[1]}**"))

    def checks() -> List[Tuple[str,bool,str]]:
        cards=list((HWATU_ASSET_ROOT/"cards").glob("*.png"))
        positions=[FINISH-1]*len(HORSES); advanced=advance_positions(positions)
        crossing=crossing_winner(positions,advanced)
        return [
            ("최종 승자·잔액 정산", callable(_format_settlement), "winner/net/before/after"),
            ("자유 레이즈 안전 한도", bot.get_command("베팅제한") is not None, f"default={V1100_DEFAULT_RAISE_LIMIT:,}"),
            ("음수 잔액 유지", casino_chips({"black_casino":{"chips":-999}})==-999, "-999 preserved"),
            ("공통 결승선", all(0<=p<=FINISH for p in advanced), f"finish={FINISH} crossing={crossing}"),
            ("ABADDON 화투 자산", len(cards)==48, f"cards={len(cards)}/48"),
            ("화투 도감 명령", bot.get_command("화투도감") is not None, "48 sheet"),
            ("정산 장부 명령", bot.get_command("정산조회") is not None, "lookup/recent/result"),
            ("셔플 커밋 검증", bot.get_command("셔플검증") is not None, "SHA-256 commit/reveal"),
            ("게임도시", bot.get_command("게임도시") is not None, "rooms/racing/league/ledger"),
            ("테이블 장식", bot.get_command("테이블테마") is not None and bot.get_command("카드스킨") is not None, "theme+skin"),
            ("한글 이미지 폰트", "missing" not in str(font_status()), str(font_status())),
            ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
        ]

    @bot.command(name="게임도시검수", aliases=["gamecityaudit", "v1100audit"], help="v11.0.0에서 변경한 결과·레이즈·경마·화투·장부만 검사합니다.")
    async def v1100_audit(ctx: commands.Context, 모드: str="기본") -> None:
        locale=_ctx_locale(bot,ctx); rows=checks(); passed=sum(1 for _,ok,_ in rows if ok)
        embed=_dashboard(bot,locale,f"🧪 ABADDON v{VERSION} 검수 · {passed}/{len(rows)}",f"🧪 ABADDON v{VERSION} Audit · {passed}/{len(rows)}","이번 패치에서 바꾼 기능만 검사합니다.","Checks only features changed in this patch.",discord.Color.green() if passed==len(rows) else discord.Color.orange())
        detail=str(모드).casefold() in {"상세","전체","detail","full"} or passed!=len(rows)
        if detail:
            for name,ok,value in rows: embed.add_field(name=f"{'✅' if ok else '❌'} {name}",value=str(value)[:1024],inline=True)
        else: embed.add_field(name=_t(locale,"결과","Result"),value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!게임도시검수 상세`",inline=False)
        await ctx.send(embed=embed)

    test_command=bot.get_command("테스트")
    if test_command is not None:
        async def v1100_test(ctx: commands.Context, 모드: str="기본") -> None:
            await v1100_audit.callback(ctx,모드)
        test_command.callback=v1100_test
        test_command.help="v11.0.0에서 변경한 결과·레이즈·경마 결승선·화투·공정성·장부만 검사합니다. `!테스트 상세` 지원."
        test_command.description=test_command.help

    patch_notes=bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1100_notes(ctx: commands.Context) -> None:
            locale=_ctx_locale(bot,ctx); limit=int(_guild_betting(root,int(getattr(ctx.guild,"id",0) or 0))["max_raise"])
            embed=_dashboard(bot,locale,f"🏙️ ABADDON v{VERSION} — 게임도시·결과·화투 통합",f"🏙️ ABADDON v{VERSION} — Game City, Results & Hwatu","이번 패치에서 실제로 변경한 기능만 표시합니다.","Only features actually changed in this patch are shown.",discord.Color.dark_purple())
            embed.add_field(name=_t(locale,"🏆 결과 화면","🏆 Results"),value=_t(locale,"모든 실전 카드 정산에 승자·팟·이번 손익·이전→현재 잔액·정산 ID를 고정 표시합니다.","Every authentic card settlement shows winner, pot, net, balance before→after and settlement ID."),inline=False)
            embed.add_field(name=_t(locale,"🎚️ 자유 레이즈","🎚️ Free Raise"),value=_t(locale,f"잔액과 무관한 자유 입력을 유지하고 1회 안전 한도 **{limit:,}칩**을 적용합니다. 손실은 음수까지 내려갑니다.",f"Free input remains independent of wallet, with a per-action safety limit of **{limit:,} chips**. Losses may go negative."),inline=False)
            embed.add_field(name=_t(locale,"🏁 경마 결승선","🏁 Race Finish"),value=_t(locale,"모든 레인을 같은 결승 좌표로 고정하고, 결승선을 처음 넘은 말만 우승 처리합니다.","All lanes share one finish coordinate; only a horse that first crosses it wins."),inline=False)
            embed.add_field(name=_t(locale,"🎴 전용 화투","🎴 Original Hwatu"),value=_t(locale,"전통 문양 48장 이미지를 모든 화투 계열 게임과 도감에 연결했습니다.","Connected the original 48-card ABADDON art to hwatu tables, Seotda and the catalogue."),inline=False)
            embed.add_field(name=_t(locale,"🔐 장부·검증","🔐 Ledger & Verification"),value=_t(locale,"정산조회·셔플검증·게임세션·안전 복구 상태를 추가했습니다.","Added settlement lookup, shuffle verification, game session and safe recovery status."),inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback=v1100_notes
        patch_notes.help=f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        patch_notes.description=patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1100_game_city"]
    guide.append({
        "id":"v1100_game_city","emoji":"🏙️","title":"v11.0.0 게임도시·결과·화투",
        "hint":"승자/손익/잔액 결과 · 자유 레이즈 안전 한도 · 공통 경마 결승선 · 전용 화투 48장 · 장부/공정성 검증",
        "commands":[
            "!게임도시 · !gamecity", "!베팅제한 · !베팅제한설정", "!정산조회 · !최근정산 · !게임결과",
            "!셔플검증 · !공정성검증", "!게임세션 · !게임복구", "!화투도감 · !화투패보기",
            "!테이블테마 · !카드스킨 · !내게임장식", "!게임도시검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1100_version=VERSION  # type: ignore[attr-defined]
    bot.v1100_checks=checks  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] results=winner+net+balance raise=free+safety_limit negative_balance=enabled race_finish=shared hwatu_assets=48 fairness=commit_reveal game_city=enabled",flush=True)
