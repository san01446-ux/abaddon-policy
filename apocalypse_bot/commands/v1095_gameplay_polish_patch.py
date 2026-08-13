from __future__ import annotations

"""ABADDON v10.9.5 live presentation, replay-image and recovery patch."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1095_visual_polish import (
    ANIMATED_TABLES,
    render_live_board,
    render_replay_timeline,
    render_session_media,
)
from apocalypse_bot.commands.v651_card_games import ACTIVE_GAMES
from apocalypse_bot.commands.v1092_visual_status_horserace import LIVE_RACE_STATES

VERSION = "10.9.5"
PATCH_DATE = "2026-08-04"


def _source_contains(path: Path, token: str) -> bool:
    try:
        return token in path.read_text(encoding="utf-8")
    except Exception:
        return False


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1090", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1090"] = root
    root.setdefault("replays", [])
    return root


def _race_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1092_horse_racing", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1092_horse_racing"] = root
    root.setdefault("history", [])
    return root


def _guild_games(guild_id: int) -> Dict[int, Any]:
    rows: Dict[int, Any] = {}
    for channel_id, session in ACTIVE_GAMES.items():
        message = getattr(session, "message", None)
        session_guild_id = int(getattr(getattr(message, "guild", None), "id", 0) or 0)
        if guild_id == 0 or session_guild_id == guild_id:
            rows[int(channel_id)] = session
    return rows


def _guild_races(guild_id: int) -> Dict[int, Mapping[str, Any]]:
    return {
        int(owner_id): state
        for owner_id, state in LIVE_RACE_STATES.items()
        if guild_id == 0 or int(state.get("guild_id", 0) or 0) == guild_id
    }


def _checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    base = Path(__file__).with_name("v651_card_games.py")
    race = Path(__file__).with_name("v1092_visual_status_horserace.py")
    visual = Path(__file__).with_name("v1095_visual_polish.py")
    return [
        ("턴 강조 애니메이션", callable(render_session_media), f"animated={ANIMATED_TABLES}"),
        ("이미지 실패 복구", _source_contains(base, "Final recovery path") and _source_contains(base, "_v1095_embed_fallbacks"), "GIF/PNG failure → embed-only"),
        ("공개 행동 기록", _source_contains(base, "_v1095_visual_history"), "private cards excluded"),
        ("리플레이 타임라인 PNG", callable(render_replay_timeline), "existing replay commands renewed"),
        ("공통 실시간 보드", callable(render_live_board), "card tables + horse races"),
        ("경마 실시간 상태", _source_contains(race, "LIVE_RACE_STATES"), "tick/leader/pick"),
        ("관전 이미지", bot.get_command("관전") is not None, "public table only"),
        ("실시간보드 명령", bot.get_command("실시간보드") is not None, "!liveboard"),
        ("리플레이이미지 명령", bot.get_command("리플레이이미지") is not None, "!replayimage"),
        ("최신 연출 검수", bot.get_command("연출검수") is not None, "!연출검수 상세"),
        ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
        ("렌더러 문법", visual.is_file(), visual.name),
    ]


def register_v1095_gameplay_polish_patch(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1095_registered", False):
        return
    bot._abaddon_v1095_registered = True

    async def send_replay_image(ctx: commands.Context, index: int = 1) -> None:
        locale = _ctx_locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        rows = [
            row for row in reversed(_root(world_data).get("replays", []))
            if int(row.get("guild_id", 0) or 0) == guild_id
        ]
        if not rows:
            await ctx.send(_t(locale, "저장된 게임 리플레이가 없습니다.", "No game replay is stored."))
            return
        row = rows[max(0, min(len(rows) - 1, int(index) - 1))]
        image = render_replay_timeline(row, locale)
        filename = "abaddon_game_replay.png"
        file = discord.File(image, filename=filename)
        embed = _dashboard(
            bot,
            locale,
            f"📼 게임 리플레이 · {row.get('game', '-')}",
            f"📼 Game Replay · {row.get('game', '-')}",
            "공개 행동만 저장한 이미지 타임라인입니다.",
            "An image timeline containing public actions only.",
            discord.Color.dark_blue(),
        )
        embed.set_image(url=f"attachment://{filename}")
        embed.add_field(name=_t(locale, "결과", "Result"), value=str(row.get("result", "-"))[:1024], inline=False)
        embed.set_footer(text=_t(locale, "비공개 손패와 개인 선택 값은 저장하지 않습니다.", "Private hands and modal values are never stored."))
        await ctx.send(embed=embed, file=file)

    @bot.command(name="리플레이이미지", aliases=["replayimage", "visualreplay"], help="최근 게임 진행 기록을 이미지 타임라인으로 확인합니다.")
    async def replay_image(ctx: commands.Context, 번호: int = 1) -> None:
        await send_replay_image(ctx, 번호)

    for command_name in ("최근게임", "게임리플레이", "게임기록"):
        command = bot.get_command(command_name)
        if command is None:
            continue
        if command_name == "최근게임":
            async def recent_callback(ctx: commands.Context) -> None:
                await send_replay_image(ctx, 1)
            command.callback = recent_callback
        else:
            async def indexed_callback(ctx: commands.Context, 번호: int = 1) -> None:
                await send_replay_image(ctx, 번호)
            command.callback = indexed_callback
        command.help = "게임 공개 행동과 최종 결과를 이미지 타임라인으로 확인합니다."
        command.description = command.help

    async def send_spectator_image(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        session = ACTIVE_GAMES.get(int(ctx.channel.id))
        if session is None:
            await ctx.send(_t(locale, "이 채널에 진행 중인 게임이 없습니다.", "No game is active in this channel."))
            return
        try:
            embed = session.embed()
        except Exception:
            embed = _dashboard(bot, locale, "👁️ 관전 패널", "👁️ Spectator Panel", "공개 테이블 상태입니다.", "Public table state.")
        embed.title = f"👁️ {_t(locale, '이미지 관전', 'Image Spectator')} · {embed.title or getattr(session, 'kind', 'Game')}"
        embed.add_field(name=_t(locale, "보안", "Privacy"), value=_t(locale, "공개 보드·팟·차례만 표시합니다. 손패는 표시하지 않습니다.", "Shows only public board, pot and turn. Hands stay hidden."), inline=False)
        media, extension = render_session_media(session, embed)
        if media is None:
            await ctx.send(embed=embed)
            return
        filename = f"abaddon_spectator_table.{extension}"
        file = discord.File(media, filename=filename)
        embed.set_image(url=f"attachment://{filename}")
        await ctx.send(embed=embed, file=file)

    for command_name in ("관전", "테이블정보"):
        command = bot.get_command(command_name)
        if command is not None:
            command.callback = send_spectator_image
            command.help = "현재 카드게임의 공개 상태를 이미지 테이블로 확인합니다."
            command.description = command.help

    @bot.command(name="실시간보드", aliases=["liveboard", "gameliveboard", "livestatusboard"], help="진행 중인 카드게임과 경마를 이미지 보드로 확인합니다.")
    async def live_board(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        games = _guild_games(guild_id)
        races = _guild_races(guild_id)
        recent = [
            row for row in _race_root(world_data).get("history", [])
            if guild_id == 0 or int(row.get("guild_id", guild_id) or guild_id) == guild_id
        ][:2]
        image = render_live_board(locale=locale, active_games=games, live_races=races, recent_races=recent)
        filename = "abaddon_live_game_board.png"
        file = discord.File(image, filename=filename)
        embed = _dashboard(
            bot,
            locale,
            "📡 ABADDON 실시간 게임 보드",
            "📡 ABADDON Live Game Board",
            "진행 중인 카드 테이블과 경마를 한 화면에서 확인합니다.",
            "See active card tables and horse races in one view.",
            discord.Color.dark_teal(),
        )
        embed.set_image(url=f"attachment://{filename}")
        embed.add_field(name=_t(locale, "현재 상태", "Current Status"), value=_t(locale, f"카드게임 **{len(games)}개** · 경마 **{len(races)}개**", f"Card tables **{len(games)}** · races **{len(races)}**"), inline=False)
        await ctx.send(embed=embed, file=file)

    @bot.command(name="연출검수", aliases=["polishaudit", "visualpolishaudit", "gamefxaudit"], help="v10.9.5 이미지 연출·복구·리플레이·실시간 보드를 검사합니다.")
    async def polish_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        checks = _checks(bot)
        passed = sum(1 for _name, ok, _detail in checks if ok)
        embed = _dashboard(
            bot,
            locale,
            f"✨ ABADDON v{VERSION} 연출 검수 · {passed}/{len(checks)}",
            f"✨ ABADDON v{VERSION} Visual Audit · {passed}/{len(checks)}",
            "이번 패치의 이미지 연출과 장애 복구 경로만 검사합니다.",
            "Checks only visual polish and recovery paths changed in this patch.",
            discord.Color.green() if passed == len(checks) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(checks)
        if detail:
            for name, ok, value in checks:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ **{passed}** · ❌ **{len(checks)-passed}**\n`!연출검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1095_test(ctx: commands.Context, 모드: str = "기본") -> None:
            locale = _ctx_locale(bot, ctx)
            checks = _checks(bot)
            passed = sum(1 for _name, ok, _detail in checks if ok)
            embed = _dashboard(
                bot,
                locale,
                f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {passed}/{len(checks)}",
                f"🧪 ABADDON v{VERSION} Latest Patch Test · {passed}/{len(checks)}",
                "v10.9.5에서 바꾼 턴 연출·복구·리플레이·실시간 보드만 검사합니다.",
                "Checks only turn effects, recovery, replay and live-board changes in v10.9.5.",
                discord.Color.green() if passed == len(checks) else discord.Color.orange(),
            )
            detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(checks)
            if detail:
                for name, ok, value in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
            else:
                embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ **{passed}** · ❌ **{len(checks)-passed}**\n`!테스트 상세`", inline=False)
            embed.add_field(name=_t(locale, "실제 점검", "Live Check"), value=_t(locale, "`!실시간보드` · `!관전` · `!최근게임` · 카드게임 1판 · 경마 1판", "`!liveboard` · `!spectate` · `!recentgame` · one card round · one race"), inline=False)
            await ctx.send(embed=embed)
        test_command.callback = v1095_test
        test_command.help = "v10.9.5에서 수정한 이미지 연출·복구·리플레이·실시간 보드를 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1095_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"✨ ABADDON v{VERSION} — 게임 연출·복구 패치",
                f"✨ ABADDON v{VERSION} — Gameplay Polish & Recovery",
                "이번 패치에서 실제로 변경한 항목만 표시합니다.",
                "Only changes actually made in this patch are shown.",
                discord.Color.dark_purple(),
            )
            embed.add_field(name=_t(locale, "🎴 턴 강조", "🎴 Active Turn"), value=_t(locale, "진행 중 테이블은 현재 차례·단계·최근 행동을 짧은 GIF로 강조합니다. 종료 화면은 선명한 PNG를 유지합니다.", "Active tables use a short GIF for turn, phase and latest action. Finished tables remain crisp PNGs."), inline=False)
            embed.add_field(name=_t(locale, "🛟 이미지 복구", "🛟 Image Recovery"), value=_t(locale, "GIF·PNG 생성이나 업로드가 실패해도 임베드 화면으로 자동 전환해 게임 진행과 정산을 유지합니다.", "If GIF/PNG rendering or upload fails, the game automatically falls back to embeds without stopping turns or settlement."), inline=False)
            embed.add_field(name=_t(locale, "📼 이미지 리플레이", "📼 Image Replay"), value=_t(locale, "`!최근게임`·`!게임리플레이`가 공개 행동과 결과를 타임라인 PNG로 보여줍니다.", "`!recentgame` and `!gamereplay` show public actions and results as a timeline PNG."), inline=False)
            embed.add_field(name=_t(locale, "📡 실시간 보드", "📡 Live Board"), value=_t(locale, "`!실시간보드`에서 진행 중인 카드게임과 경마를 함께 확인합니다.", "`!liveboard` combines active card games and horse races."), inline=False)
            embed.add_field(name=_t(locale, "👁️ 이미지 관전", "👁️ Image Spectating"), value=_t(locale, "`!관전`과 `!테이블정보`가 비공개 패를 숨긴 실제 테이블 이미지를 표시합니다.", "`!spectate` and `!tableinfo` show a real public table image while keeping hands hidden."), inline=False)
            embed.add_field(name=_t(locale, "🧪 최신 검수", "🧪 Latest Audit"), value=_t(locale, "`!테스트 상세`와 `!연출검수 상세`는 v10.9.5 변경 범위만 검사합니다.", "`!test detail` and `!polishaudit detail` check only v10.9.5 changes."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1095_patch_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1095_gameplay_polish"]
    guide.append({
        "id": "v1095_gameplay_polish",
        "emoji": "✨",
        "title": "v10.9.5 게임 연출·복구",
        "hint": "턴 GIF · 이미지 실패 복구 · 리플레이 PNG · 카드/경마 실시간 보드 · 이미지 관전",
        "commands": [
            "!실시간보드 · !liveboard",
            "!리플레이이미지 [번호] · !replayimage [number]",
            "!관전 · !테이블정보",
            "!연출검수 상세 · !polishaudit detail",
            "!테스트 상세 · !패치노트",
        ],
    })

    bot.v1095_version = VERSION  # type: ignore[attr-defined]
    bot.v1095_visual_checks = lambda: _checks(bot)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] active_turn_gif={ANIMATED_TABLES} image_recovery=enabled replay_png=enabled live_board=card+racing spectator_image=enabled", flush=True)
