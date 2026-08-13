from __future__ import annotations

"""ABADDON v10.9.2 visual re-application, live status and horse-racing patch."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _interaction_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1091_card_dashboard_hotfix import CATEGORIES
from apocalypse_bot.commands.v1060_authentic_card_games import GAME_EN
from apocalypse_bot.commands.v1092_visual_assets import build_card_catalog, build_profile_card, build_world_map_card, dashboard_font_status
from apocalypse_bot.commands.v1092_horse_racing_rules import FINISH, HORSES, advance_positions, choose_winner, crossing_winner, generate_race_odds, race_settlement, render_track_lane
from apocalypse_bot.commands import v810_world_map_ux as world_map_runtime

VERSION = "10.9.2"
V1093_PROFILE_USES_DISCORD_AVATAR = True
PATCH_DATE = "2026-08-03"
MIN_RACE_BET = 1_000
ACTIVE_RACES: set[int] = set()
LIVE_RACE_STATES: Dict[int, Dict[str, Any]] = {}

EN_TEXT = {
    "연구원": "Researcher", "의사": "Medic", "군인": "Soldier", "정비공": "Mechanic", "요리사": "Cook", "정찰병": "Scout",
    "정상": "Normal", "부상": "Injured", "중상": "Critical", "감염": "Infected", "피로": "Fatigued",
    "신입 생존자": "Rookie Survivor", "미선택": "Unselected", "없음": "None",
}

def _en(value: Any, fallback: str = "-") -> str:
    text = str(value or fallback)
    return EN_TEXT.get(text, text if text.isascii() else fallback)


def _name(horse: Mapping[str, Any], locale: str) -> str:
    return str(horse["name_ko"] if locale == "ko" else horse["name_en"])


def _race_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1092_horse_racing", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1092_horse_racing"] = root
    root.setdefault("races", 0)
    root.setdefault("history", [])
    root.setdefault("schema_version", 1)
    return root


def _user_race(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault("v1092_horse_racing", {})
    if not isinstance(row, dict):
        row = {}
        user["v1092_horse_racing"] = row
    row.setdefault("plays", 0)
    row.setdefault("wins", 0)
    row.setdefault("losses", 0)
    row.setdefault("profit", 0)
    row.setdefault("best_payout", 0)
    row.setdefault("history", [])
    return row


def _recover_interrupted_races(user_data: Mapping[Any, Any]) -> int:
    """Refund stakes left pending by a process restart before race settlement."""
    recovered = 0
    for value in user_data.values() if isinstance(user_data, Mapping) else ():
        if not isinstance(value, MutableMapping):
            continue
        row = value.get("v1092_horse_racing")
        if not isinstance(row, MutableMapping):
            continue
        pending = row.get("pending")
        if not isinstance(pending, Mapping):
            continue
        bet = int(pending.get("bet", 0) or 0)
        if bet > 0:
            add_casino_chips(value, bet)
            recovered += 1
        row.pop("pending", None)
    return recovered


def _track(locale: str, positions: Sequence[int], selected: Optional[int] = None) -> str:
    """Render visible horses on lanes that all share one finish coordinate."""
    rows: List[str] = []
    for index, (horse, pos) in enumerate(zip(HORSES, positions)):
        marker = min(FINISH, max(0, int(pos)))
        prefix = "👉" if selected == index else "▫️"
        horse_emoji = str(horse.get("emoji") or "🐎")
        rows.append(f"{prefix} **{index + 1}. {horse_emoji} {_name(horse, locale)}** · {marker}/{FINISH}")
        # ♞ is a stable text-width horse marker inside the monospace lane.
        # The full-colour horse emoji remains visible beside the horse name.
        rows.append(f"`   {render_track_lane(marker)}`")
    return "\n".join(rows)


def _race_embed(bot: commands.Bot, locale: str, *, title: str, positions: Sequence[int], selected: Optional[int], bet: int, tick: int, note: str, odds: Optional[Sequence[float]] = None) -> discord.Embed:
    embed = _dashboard(
        bot,
        locale,
        title,
        title,
        note,
        note,
        discord.Color.gold(),
    )
    embed.add_field(name=_t(locale, "실시간 트랙", "Live Track"), value=_track(locale, positions, selected), inline=False)
    embed.add_field(name=_t(locale, "판돈", "Stake"), value=f"**{bet:,}** {_t(locale, '칩', 'chips')}", inline=True)
    embed.add_field(name=_t(locale, "진행", "Progress"), value=f"**{tick}** {_t(locale, '틱', 'ticks')}", inline=True)
    if odds is not None:
        compact = " · ".join(f"{index + 1} x{float(value):.1f}" for index, value in enumerate(odds))
        embed.add_field(name=_t(locale, "이번 경주 배당", "This Race Odds"), value=compact, inline=False)
    embed.set_footer(text=_t(locale, "경주를 만들 때마다 배당이 바뀌고 출발 후에는 고정됩니다. 잔액 음수 허용", "Odds reroll for every new race and lock after the start. Negative balance allowed"))
    return embed


async def _avatar_bytes(member: Any) -> bytes | None:
    try:
        return await member.display_avatar.read()
    except Exception:
        return None


def register_v1092_visual_status_horserace(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[MutableMapping[str, Any]], int],
    get_max_hp: Callable[[MutableMapping[str, Any]], int],
    get_max_stamina: Callable[[MutableMapping[str, Any]], int],
    refresh_vitals: Callable[[MutableMapping[str, Any]], None],
    refresh_conditions: Callable[..., Any],
    condition_text: Callable[[MutableMapping[str, Any]], str],
    jobs: Mapping[str, Mapping[str, Any]],
    get_pet_record: Callable[[MutableMapping[str, Any]], Tuple[Any, Any]],
    get_pet_display_name: Callable[[Any, Any], str],
) -> None:
    if getattr(bot, "_abaddon_v1092_registered", False):
        return
    bot._abaddon_v1092_registered = True
    _race_root(world_data)
    recovered_races = _recover_interrupted_races(user_data)
    if recovered_races:
        save_data()

    from apocalypse_bot.commands.v600_game_center import _invoke_command

    class ProfileQuickActionView(discord.ui.View):
        def __init__(self, owner_id: int, locale: str) -> None:
            super().__init__(timeout=300)
            self.owner_id = int(owner_id)
            self.locale = locale
            actions = (
                ("🥫", "지갑", "Wallet", "지갑", discord.ButtonStyle.success),
                ("🎮", "게임", "Games", "게임대시보드", discord.ButtonStyle.primary),
                ("💰", "경제", "Economy", "경제대시보드", discord.ButtonStyle.primary),
                ("🗺️", "세계지도", "World Map", "세계지도", discord.ButtonStyle.secondary),
                ("📚", "전체 명령어", "All Commands", "명령어", discord.ButtonStyle.secondary),
            )
            for emoji, ko, en, command_name, style in actions:
                button = discord.ui.Button(label=_t(locale, ko, en), emoji=emoji, style=style, row=0)

                async def callback(interaction: discord.Interaction, command_name=command_name) -> None:
                    if int(interaction.user.id) != self.owner_id:
                        await interaction.response.send_message(_t(self.locale, "이 정보 화면은 실행자만 사용할 수 있습니다.", "Only the opener can use this dashboard."), ephemeral=True)
                        return
                    pass  # v18.1.3: _invoke_command owns the single interaction ACK
                    await _invoke_command(bot, interaction, command_name)

                button.callback = callback
                self.add_item(button)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if int(interaction.user.id) == self.owner_id:
                return True
            await interaction.response.send_message(_t(self.locale, "이 정보 화면은 실행자만 사용할 수 있습니다.", "Only the opener can use this dashboard."), ephemeral=True)
            return False

    async def send_profile_dashboard(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        refresh_vitals(user)
        try:
            refresh_conditions(user, get_max_hp)
        except TypeError:
            refresh_conditions(user)
        max_hp = int(get_max_hp(user))
        max_stamina = int(get_max_stamina(user))
        active_pet_name, active_pet_record = get_pet_record(user)
        pet = get_pet_display_name(active_pet_name, active_pet_record) + f" Lv.{active_pet_record.get('level', 1)}" if active_pet_name else _t(locale, "없음", "None")
        job_name = str(user.get("job") or _t(locale, "미선택", "Unselected"))
        title = str(user.get("title") or _t(locale, "신입 생존자", "Rookie Survivor"))
        condition_value = str(condition_text(user))
        if locale != "ko":
            job_name = _en(job_name, "Survivor")
            title = _en(title, "Survivor")
            condition_value = _en(condition_value, "Normal")
            pet = "Companion" + (f" Lv.{active_pet_record.get('level', 1)}" if active_pet_name else "") if active_pet_name else "None"
        stats = user.get("stats", {}) if isinstance(user.get("stats"), Mapping) else {}
        image = build_profile_card(
            locale=locale,
            display_name=str(getattr(ctx.author, "display_name", ctx.author.name)),
            title=title,
            job=job_name,
            level=int(user.get("level", 1)),
            hp=int(user.get("hp", 0)),
            max_hp=max_hp,
            stamina=int(user.get("stamina", 0)),
            max_stamina=max_stamina,
            infection=int(user.get("infection", 0)),
            condition=condition_value,
            power=int(calculate_user_power(user)),
            food=int(user.get("balance", 0)),
            chips=casino_chips(user),
            inventory_count=len(user.get("inventory", [])) if isinstance(user.get("inventory"), (list, dict)) else 0,
            pet=pet,
            dungeon_wins=int(stats.get("dungeon_wins", 0)),
            avatar_bytes=await _avatar_bytes(ctx.author),
        )
        embed = _dashboard(
            bot,
            locale,
            f"📊 {ctx.author.display_name} · 생존자 이미지 대시보드",
            f"📊 {ctx.author.display_name} · Survivor Image Dashboard",
            "기존 텍스트 정보 화면을 실제 PNG 카드로 교체했습니다.",
            "The legacy text profile is replaced with a real PNG dashboard card.",
            discord.Color.dark_teal(),
        )
        file = discord.File(image, filename="abaddon_survivor_dashboard.png")
        embed.set_image(url="attachment://abaddon_survivor_dashboard.png")
        embed.add_field(name=_t(locale, "바로가기", "Quick Actions"), value=_t(locale, "아래 버튼으로 즉시 실행 · 복사할 필요 없음", "Use the buttons below · no copy/paste required"), inline=False)
        await ctx.send(embed=embed, file=file, view=ProfileQuickActionView(ctx.author.id, locale))
        save_data()

    info_command = bot.get_command("정보")
    if info_command is not None:
        info_command.callback = send_profile_dashboard
        info_command.help = "생존자 핵심 정보를 실제 이미지 카드 대시보드로 확인합니다."
        info_command.description = info_command.help

    survivor_command = bot.get_command("생존대시보드")
    if survivor_command is not None:
        survivor_command.callback = send_profile_dashboard
        survivor_command.help = "생존자 핵심 정보를 실제 이미지 카드 대시보드로 확인합니다."
        survivor_command.description = survivor_command.help

    async def send_world_map_dashboard(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send(_t(_ctx_locale(bot, ctx), "서버에서만 사용할 수 있습니다.", "Use this in a server."))
            return
        locale = _ctx_locale(bot, ctx)
        state = world_map_runtime._guild_state(world_data, int(ctx.guild.id))
        weather, risk, _mult = world_map_runtime._weather(world_data, int(ctx.guild.id))
        regions = []
        for key in world_map_runtime.REGION_ORDER:
            info = world_map_runtime.REGIONS[key]
            row = state["regions"][key]
            regions.append({
                "name": str(info["name"] if locale == "ko" else key.replace("_", " ").title()),
                "unlocked": bool(row.get("unlocked")),
                "progress": int(row.get("progress", 0)),
                "target": int(row.get("target", info["target"])),
                "boss_defeated": bool(row.get("boss", {}).get("defeated")),
            })
        image = build_world_map_card(locale=locale, guild_name=str(ctx.guild.name), weather=weather, risk=risk, regions=regions)
        embed = _dashboard(
            bot,
            locale,
            "🗺️ ABADDON 공동 탐험 이미지 지도",
            "🗺️ ABADDON Shared Expedition Image Map",
            "지역 해금·진행도·보스 격파 상태를 이미지 지도 한 장으로 표시합니다.",
            "Shows unlocks, progress and boss clears in one image map.",
            discord.Color.blue(),
        )
        file = discord.File(image, filename="abaddon_world_map.png")
        embed.set_image(url="attachment://abaddon_world_map.png")
        embed.add_field(name=_t(locale, "진행 명령", "Progress Commands"), value=_t(locale, "`!지역정찰 지역` → `!지역선택 행동` → `!개척기부` / `!거점건설` / `!지역보스공격`", "`!regionscout region` → `!regionchoice action` → donate / build / attack boss"), inline=False)
        await ctx.send(embed=embed, file=file)

    map_command = bot.get_command("세계지도")
    if map_command is not None:
        map_command.callback = send_world_map_dashboard
        map_command.help = "서버 공동 개척 상태를 실제 이미지 지도 대시보드로 확인합니다."
        map_command.description = map_command.help

    map_dashboard_command = bot.get_command("지도대시보드")
    if map_dashboard_command is not None:
        map_dashboard_command.callback = send_world_map_dashboard

    # Make sure the catalogue command visibly contains a real image even when an older callback survived deployment.
    card_dashboard = bot.get_command("카드대시보드")
    if card_dashboard is not None:
        async def v1092_card_dashboard(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            image = build_card_catalog(locale=locale, categories=CATEGORIES, game_en=GAME_EN)
            embed = _dashboard(
                bot,
                locale,
                "🎴 카드게임 25종 · 이미지 대시보드",
                "🎴 25 Card Modes · Image Dashboard",
                "아래 이미지가 표시되지 않으면 v10.9.2 파일이 실제 배포되지 않은 것입니다.",
                "If this image is missing, the v10.9.2 package is not the deployed build.",
                discord.Color.dark_purple(),
            )
            file = discord.File(image, filename="abaddon_card_catalog.png")
            embed.set_image(url="attachment://abaddon_card_catalog.png")
            view_factory = getattr(bot, "v1091_card_catalog_view_factory", None)
            view = view_factory(locale) if callable(view_factory) else None
            await ctx.send(embed=embed, file=file, view=view)
        card_dashboard.callback = v1092_card_dashboard
        card_dashboard.help = "카드게임 25종을 실제 PNG 이미지 대시보드와 상세 선택 메뉴로 확인합니다."
        card_dashboard.description = card_dashboard.help

    class HorseRaceView(discord.ui.View):
        def __init__(self, owner_id: int, bet: int, locale: str, user: MutableMapping[str, Any], odds: Sequence[float]) -> None:
            super().__init__(timeout=180)
            self.owner_id = owner_id
            self.bet = int(bet)
            self.locale = locale
            self.user = user
            self.odds = tuple(float(value) for value in odds)
            if len(self.odds) != len(HORSES):
                raise ValueError("invalid horse odds count")
            options = [
                discord.SelectOption(
                    label=f"{i + 1}. {_name(horse, locale)}",
                    value=str(i),
                    emoji=horse["emoji"],
                    description=_t(locale, f"이번 경주 x{self.odds[i]:.1f} · ABADDON 기수", f"This race x{self.odds[i]:.1f} · ABADDON jockey"),
                )
                for i, horse in enumerate(HORSES)
            ]
            select = discord.ui.Select(placeholder=_t(locale, "베팅할 말을 선택하세요", "Choose your horse"), options=options, min_values=1, max_values=1)
            select.callback = self._select  # type: ignore[assignment]
            self.add_item(select)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if int(interaction.user.id) != self.owner_id:
                await interaction.response.send_message(_t(self.locale, "이 경마표는 명령을 실행한 생존자만 사용할 수 있습니다.", "Only the race owner can use this ticket."), ephemeral=True)
                return False
            return True

        async def _select(self, interaction: discord.Interaction) -> None:
            if self.owner_id in ACTIVE_RACES:
                await interaction.response.send_message(_t(self.locale, "이미 경마가 진행 중입니다.", "A race is already running."), ephemeral=True)
                return
            selected = int(self.children[0].values[0])  # type: ignore[attr-defined]
            ACTIVE_RACES.add(self.owner_id)
            before = casino_chips(self.user)
            add_casino_chips(self.user, -self.bet)
            race_row = _user_race(self.user)
            race_row["pending"] = {
                "bet": self.bet,
                "before": before,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "odds": list(self.odds),
                "selected": selected,
                "selected_odds": self.odds[selected],
            }
            save_data()
            for child in self.children:
                child.disabled = True
            positions = [0] * len(HORSES)
            LIVE_RACE_STATES[self.owner_id] = {
                "owner_id": self.owner_id,
                "guild_id": int(getattr(interaction.guild, "id", 0) or 0),
                "locale": self.locale,
                "bet": self.bet,
                "selected": selected,
                "selected_name": _name(HORSES[selected], self.locale),
                "leader_name": _name(HORSES[0], self.locale),
                "positions": list(positions),
                "tick": 0,
                "status": "starting",
                "odds": list(self.odds),
            }
            embed = _race_embed(bot, self.locale, title=_t(self.locale, "🏁 ABADDON 실시간 경마 · 출발", "🏁 ABADDON Live Horse Race · Start"), positions=positions, selected=selected, bet=self.bet, tick=0, note=_t(self.locale, "선택 완료. 이번 배당이 고정됐습니다. 전 말이 ABADDON 기수와 함께 출발합니다.", "Selection locked. This race market is now fixed. Every horse starts with an ABADDON jockey."), odds=self.odds)
            await interaction.response.edit_message(embed=embed, view=self)
            message = interaction.message
            asyncio.create_task(self._run(message, selected, before))

        async def _run(self, message: discord.Message, selected: int, before: int) -> None:
            positions = [0] * len(HORSES)
            tick = 0
            try:
                winner: Optional[int] = None
                while max(positions) < FINISH:
                    tick += 1
                    previous_positions = list(positions)
                    positions = advance_positions(positions)
                    winner = crossing_winner(previous_positions, positions)
                    leader_index = max(range(len(positions)), key=lambda idx: int(positions[idx]))
                    LIVE_RACE_STATES[self.owner_id] = {
                        "owner_id": self.owner_id,
                        "guild_id": int(LIVE_RACE_STATES.get(self.owner_id, {}).get("guild_id", 0) or 0),
                        "locale": self.locale,
                        "bet": self.bet,
                        "selected": selected,
                        "selected_name": _name(HORSES[selected], self.locale),
                        "leader_name": _name(HORSES[leader_index], self.locale),
                        "positions": list(positions),
                        "tick": tick,
                        "status": "racing",
                        "odds": list(self.odds),
                    }
                    embed = _race_embed(bot, self.locale, title=_t(self.locale, "🏇 ABADDON 실시간 경마 · 질주 중", "🏇 ABADDON Live Horse Race · Racing"), positions=positions, selected=selected, bet=self.bet, tick=tick, note=_t(self.locale, "순위가 실시간으로 바뀝니다. 결승선을 먼저 넘는 말이 승리합니다.", "Standings update live. First across the line wins."), odds=self.odds)
                    try:
                        await message.edit(embed=embed, view=self)
                    except discord.HTTPException:
                        pass
                    await asyncio.sleep(1.4)
                    if winner is not None or tick >= 30:
                        break

                if winner is None:
                    winner = choose_winner(positions)
                horse = HORSES[winner]
                gross, expected_net = race_settlement(self.bet, selected, winner, self.odds)
                if gross:
                    add_casino_chips(self.user, gross)
                after = casino_chips(self.user)
                net = after - before
                if net != expected_net:
                    raise RuntimeError(f"horse settlement invariant failed: {net} != {expected_net}")
                stats = _user_race(self.user)
                stats["plays"] = int(stats.get("plays", 0)) + 1
                stats["wins" if winner == selected else "losses"] = int(stats.get("wins" if winner == selected else "losses", 0)) + 1
                stats["profit"] = int(stats.get("profit", 0)) + net
                stats["best_payout"] = max(int(stats.get("best_payout", 0)), gross)
                record = {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "selected": _name(HORSES[selected], "ko"),
                    "winner": _name(horse, "ko"),
                    "bet": self.bet,
                    "gross": gross,
                    "net": net,
                    "before": before,
                    "after": after,
                    "selected_odds": self.odds[selected],
                    "winner_odds": self.odds[winner],
                    "market_odds": list(self.odds),
                }
                stats["history"].insert(0, record)
                del stats["history"][20:]
                stats.pop("pending", None)
                root = _race_root(world_data)
                root["races"] = int(root.get("races", 0)) + 1
                root["history"].insert(0, {**record, "user_id": self.owner_id})
                del root["history"][50:]
                save_data()
                for child in self.children:
                    child.disabled = True
                title = _t(self.locale, "🏆 적중! ABADDON 실시간 경마 결과", "🏆 Winner! ABADDON Live Race Result") if winner == selected else _t(self.locale, "💀 미적중 · ABADDON 실시간 경마 결과", "💀 Miss · ABADDON Live Race Result")
                embed = _race_embed(bot, self.locale, title=title, positions=positions, selected=selected, bet=self.bet, tick=tick, note=_t(self.locale, "결승 판정과 잔액 정산이 완료됐습니다.", "Finish and balance settlement are complete."), odds=self.odds)
                embed.add_field(name=_t(self.locale, "우승마", "Winner"), value=f"**{winner + 1}. {_name(horse, self.locale)}** · x{self.odds[winner]:.1f}", inline=True)
                embed.add_field(name=_t(self.locale, "내 선택", "Your Pick"), value=f"**{selected + 1}. {_name(HORSES[selected], self.locale)}** · x{self.odds[selected]:.1f}", inline=True)
                embed.add_field(name=_t(self.locale, "정산", "Settlement"), value=_t(self.locale, f"총 지급 **{gross:+,}칩** · 이번 게임 **{net:+,}칩**\n잔액 **{before:,} → {after:,}칩**", f"Gross **{gross:+,} chips** · game net **{net:+,} chips**\nBalance **{before:,} → {after:,} chips**"), inline=False)
                LIVE_RACE_STATES[self.owner_id] = {
                    "owner_id": self.owner_id,
                    "guild_id": int(LIVE_RACE_STATES.get(self.owner_id, {}).get("guild_id", 0) or 0),
                    "locale": self.locale,
                    "bet": self.bet,
                    "selected": selected,
                    "selected_name": _name(HORSES[selected], self.locale),
                    "leader_name": _name(horse, self.locale),
                    "positions": list(positions),
                    "tick": tick,
                    "status": "finished",
                    "net": net,
                    "odds": list(self.odds),
                }
                try:
                    await message.edit(embed=embed, view=self)
                except discord.HTTPException:
                    channel = getattr(message, "channel", None)
                    if channel is not None:
                        await channel.send(embed=embed)
            except Exception as exc:
                # A race must never silently consume a stake when Discord editing or
                # an unexpected runtime branch fails. Refund the exact entry stake.
                row = _user_race(self.user)
                pending = row.pop("pending", None)
                if isinstance(pending, Mapping):
                    add_casino_chips(self.user, int(pending.get("bet", self.bet) or self.bet))
                    save_data()
                channel = getattr(message, "channel", None)
                if channel is not None:
                    failure = _dashboard(
                        bot,
                        self.locale,
                        "⚠️ 경마 중단 · 판돈 자동 환불",
                        "⚠️ Race Interrupted · Stake Refunded",
                        f"진행 중 오류가 발생해 {self.bet:,}칩을 전액 환불했습니다.",
                        f"The race stopped unexpectedly and {self.bet:,} chips were fully refunded.",
                        discord.Color.orange(),
                    )
                    failure.set_footer(text=f"{type(exc).__name__} · ABADDON v{VERSION}")
                    try:
                        await channel.send(embed=failure)
                    except discord.HTTPException:
                        pass
            finally:
                ACTIVE_RACES.discard(self.owner_id)
                LIVE_RACE_STATES.pop(self.owner_id, None)
                self.stop()

    async def horse_race(ctx: commands.Context, 판돈: int = 10_000) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        if int(판돈) < MIN_RACE_BET:
            await ctx.send(_t(locale, f"최소 판돈은 {MIN_RACE_BET:,}칩입니다. 상한은 없습니다.", f"Minimum stake is {MIN_RACE_BET:,} chips. There is no maximum."))
            return
        uid = int(ctx.author.id)
        if uid in ACTIVE_RACES:
            await ctx.send(_t(locale, "이미 경마가 진행 중입니다.", "A race is already running."))
            return
        user = get_user(uid)
        positions = [0] * len(HORSES)
        race_odds = generate_race_odds()
        embed = _race_embed(bot, locale, title=_t(locale, "🏇 ABADDON 실시간 경마장", "🏇 ABADDON Live Horse Track"), positions=positions, selected=None, bet=int(판돈), tick=0, note=_t(locale, "이 경주만의 배당이 새로 배정됐습니다. 말을 선택하면 배당이 고정되고 약 1.4초마다 트랙이 움직입니다.", "A fresh market was generated for this race. Choose a horse to lock the odds and start the live track."), odds=race_odds)
        odds_text = "\n".join(f"**{i + 1}. {_name(h, locale)}** · x{race_odds[i]:.1f}" for i, h in enumerate(HORSES))
        embed.add_field(name=_t(locale, "이번 경주 랜덤 배당", "Random Odds for This Race"), value=odds_text, inline=False)
        await ctx.send(embed=embed, view=HorseRaceView(uid, int(판돈), locale, user, race_odds))

    horse_command = bot.command(name="경마", aliases=["horserace", "horse", "race"], help="실시간으로 움직이는 6마리 경주에 베팅합니다.")(horse_race)

    @bot.command(name="경마장", aliases=["racetrack", "horsearena"], help="경주마다 새로 바뀌는 배당과 실시간 경마 규칙을 확인합니다.")
    async def horse_track(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        embed = _dashboard(bot, locale, "🏟️ ABADDON 실시간 경마장 대시보드", "🏟️ ABADDON Live Racetrack Dashboard", "6마리의 ABADDON 기수가 약 1.4초 간격으로 실제 순위를 바꿉니다.", "Six ABADDON jockeys change position about every 1.4 seconds.", discord.Color.gold())
        embed.add_field(name=_t(locale, "시작", "Start"), value=_t(locale, "`!경마 10000` 또는 `!아바돈초대 경마 10000`", "`!horserace 10000` or `!inviteabaddon horse 10000`"), inline=False)
        embed.add_field(name=_t(locale, "경제", "Economy"), value=_t(locale, "음수 잔액 허용 · 판돈 상한 없음 · 경주마다 랜덤 배당 · 출발 후 배당 고정", "Negative balance · uncapped stake · fresh odds every race · odds lock after start"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="경마전적", aliases=["horseracestats", "racestats"], help="내 실시간 경마 전적과 손익을 확인합니다.")
    async def horse_stats(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        row = _user_race(get_user(int(ctx.author.id)))
        embed = _dashboard(bot, locale, "🏇 내 경마 전적", "🏇 My Horse-Racing Record", "최근 경주 결과와 누적 손익을 표시합니다.", "Shows recent races and cumulative profit.", discord.Color.gold())
        embed.add_field(name=_t(locale, "전적", "Record"), value=f"{int(row['plays'])} {_t(locale,'경주','races')} · {int(row['wins'])}W / {int(row['losses'])}L", inline=True)
        embed.add_field(name=_t(locale, "누적 손익", "Total Net"), value=f"**{int(row['profit']):+,}** {_t(locale,'칩','chips')}", inline=True)
        embed.add_field(name=_t(locale, "최고 지급", "Best Payout"), value=f"**{int(row['best_payout']):,}** {_t(locale,'칩','chips')}", inline=True)
        history = row.get("history", [])[:5]
        lines = [f"{record.get('winner')} · {int(record.get('net',0)):+,} · {int(record.get('before',0)):,}→{int(record.get('after',0)):,}" for record in history]
        embed.add_field(name=_t(locale, "최근 5경주", "Last Five"), value="\n".join(lines) or "-", inline=False)
        await ctx.send(embed=embed)

    invite = bot.get_command("아바돈초대")
    if invite is not None:
        previous_invite = invite.callback
        async def v1092_invite(ctx: commands.Context, 게임: str = "포커", 금액: int = 10_000) -> None:
            token = str(게임 or "").replace(" ", "").casefold()
            if token in {"경마", "horserace", "horse", "race", "racetrack"}:
                await horse_command.callback(ctx, int(금액))
                return
            await previous_invite(ctx, 게임, 금액)
        invite.callback = v1092_invite
        invite.help = "카드게임 25종과 실시간 경마에서 ABADDON을 초대합니다."
        invite.description = invite.help

    ai_menu = bot.get_command("아바돈게임")
    if ai_menu is not None:
        previous_ai_menu = ai_menu.callback
        async def v1092_ai_menu(ctx: commands.Context, 재화또는금액: str = "0", 금액: int = 0) -> None:
            await previous_ai_menu(ctx, 재화또는금액, 금액)
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, "🏇 실시간 경마 추가", "🏇 Live Horse Race Added", "카드게임 메뉴와 별도로 ABADDON 기수 6마리의 실시간 경마를 시작할 수 있습니다.", "Start a live six-horse race with ABADDON jockeys alongside the card menu.", discord.Color.gold())
            embed.add_field(name=_t(locale, "명령", "Command"), value=_t(locale, "`!경마 10000` · `!아바돈초대 경마 10000`", "`!horserace 10000` · `!inviteabaddon horse 10000`"), inline=False)
            await ctx.send(embed=embed)
        ai_menu.callback = v1092_ai_menu

    info_panel = bot.get_command("정보패널")
    if info_panel is not None:
        previous_info_panel = info_panel.callback
        async def v1092_info_panel(ctx: commands.Context, 종류: str = "생존") -> None:
            token = str(종류).replace(" ", "").casefold()
            if token in {"생존", "survivor", "profile", "정보"}:
                await send_profile_dashboard(ctx)
                return
            if token in {"지도", "map", "세계지도", "worldmap"}:
                await send_world_map_dashboard(ctx)
                return
            if token in {"카드", "card", "카드게임", "cardgames"} and card_dashboard is not None:
                await card_dashboard.callback(ctx)
                return
            if token in {"경마", "horse", "race"}:
                await horse_track.callback(ctx)
                return
            await previous_info_panel(ctx, 종류)
        info_panel.callback = v1092_info_panel
        info_panel.help = "생존자·세계지도·카드게임·경마를 실제 이미지/대시보드 화면으로 확인합니다."
        info_panel.description = info_panel.help

    def latest_checks() -> List[Tuple[str, bool, str]]:
        feed_server = getattr(bot, "abaddon_public_feed_server", {})
        return [
            ("정보 이미지 콜백", bot.get_command("정보") is not None and bot.get_command("정보").callback is send_profile_dashboard, "!정보 → PNG attachment"),
            ("세계지도 이미지 콜백", bot.get_command("세계지도") is not None and bot.get_command("세계지도").callback is send_world_map_dashboard, "!세계지도 → PNG attachment"),
            ("카드 이미지 대시보드", bot.get_command("카드대시보드") is not None and "PNG" in str(bot.get_command("카드대시보드").help), "25 modes"),
            ("이미지 글꼴 폴백", bool(dashboard_font_status().get("regular")) and bool(dashboard_font_status().get("bold")), str(dict(dashboard_font_status()))),
            ("실시간 경마 명령", bot.get_command("경마") is not None, "6 horses / 1.4s ticks"),
            ("경마 ABADDON 초대", bot.get_command("아바돈초대") is not None and "경마" in str(bot.get_command("아바돈초대").help), "!아바돈초대 경마"),
            ("경마 음수 잔액", callable(add_casino_chips) and casino_chips({"black_casino": {"chips": -123}}) == -123, "negative chips preserved"),
            ("홈페이지 피드 서버 코드", bot.get_command("실시간피드상태") is not None, f"embedded={bool(feed_server.get('started'))}"),
            ("정보패널 라우팅", bot.get_command("정보패널") is not None and "이미지" in str(bot.get_command("정보패널").help), "profile/map/card/race"),
            ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
        ]

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1092_test(ctx: commands.Context, 모드: str = "기본") -> None:
            locale = _ctx_locale(bot, ctx)
            checks = latest_checks()
            passed = sum(1 for _name, ok, _detail in checks if ok)
            failed = len(checks) - passed
            embed = _dashboard(bot, locale, f"🧪 ABADDON v{VERSION} 재적용 검수 · {passed}/{len(checks)}", f"🧪 ABADDON v{VERSION} Re-application Audit · {passed}/{len(checks)}", "이번 패치에서 실제로 다시 연결한 이미지 출력·실시간 경마·홈페이지 피드 경로만 검사합니다.", "Checks only the visual output, live horse-racing and website-feed routes reconnected in this patch.", discord.Color.green() if failed == 0 else discord.Color.orange())
            detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or failed > 0
            if detail:
                for name, ok, value in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value), inline=True)
            else:
                embed.add_field(name=_t(locale, "결과", "Result"), value=_t(locale, f"✅ {passed} · ❌ {failed}\n상세: `!테스트 상세`", f"✅ {passed} · ❌ {failed}\nDetails: `!test detail`"), inline=False)
            embed.add_field(name=_t(locale, "배포 판별", "Deployment Check"), value=_t(locale, "`!정보`와 `!세계지도`에 PNG 이미지가 없거나 `!경마`가 없으면 이전 ZIP이 실행 중입니다.", "If `!info`/`!worldmap` have no PNG or `!horserace` is missing, the old ZIP is still deployed."), inline=False)
            await ctx.send(embed=embed)
        test_command.callback = v1092_test
        test_command.help = "v10.9.2에서 재적용한 이미지 출력·실시간 경마·홈페이지 피드만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1092_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, f"🧩 ABADDON v{VERSION} — 이미지 재적용·실시간 경마·온라인 피드", f"🧩 ABADDON v{VERSION} — Visual Re-application, Live Racing & Online Feed", "이번 패치에서 실제로 수정한 기능만 표시합니다.", "Only features actually changed in this patch are listed.", discord.Color.dark_teal())
            embed.add_field(name=_t(locale, "🖼️ 이미지 화면 실제 적용", "🖼️ Real Image Views"), value=_t(locale, "`!정보` · `!생존대시보드` · `!세계지도` · `!지도대시보드` · `!카드대시보드`를 PNG 첨부형 화면으로 교체", "Replaced `!info`, survivor, world-map and card dashboards with attached PNG views"), inline=False)
            embed.add_field(name=_t(locale, "🏇 실시간 경마", "🏇 Live Horse Racing"), value=_t(locale, "6마리 순위가 약 1.4초마다 움직이며 적중 배당·이번 손익·게임 전→후 잔액을 최종 표시", "Six horses move about every 1.4 seconds; final view shows odds, net and balance before→after"), inline=False)
            embed.add_field(name=_t(locale, "🤖 ABADDON 초대", "🤖 Invite ABADDON"), value=_t(locale, "`!아바돈초대 경마 판돈` 지원 · 모든 상대 기수는 ABADDON", "Supports `!inviteabaddon horse stake`; every rival jockey is ABADDON"), inline=False)
            embed.add_field(name=_t(locale, "🟢 홈페이지 ONLINE", "🟢 Website ONLINE"), value=_t(locale, "실시간 API 미설정 시에도 config 상태로 온라인 불을 표시하고, API 연결 시 실제 서버·멤버·지연시간으로 자동 전환", "Shows configured ONLINE state when no API is set, then switches to real guild/member/latency data when connected"), inline=False)
            embed.add_field(name=_t(locale, "🧪 최신 검수", "🧪 Latest Audit"), value=_t(locale, "`!테스트 상세`가 v10.9.2 재적용 범위만 검사", "`!test detail` checks only the v10.9.2 re-application scope"), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1092_patch_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1092_visual_status_horserace"]
    guide.append({
        "id": "v1092_visual_status_horserace",
        "emoji": "🏇",
        "title": "v10.9.2 이미지 재적용·실시간 경마",
        "hint": "정보/지도/카드 PNG 대시보드 · 홈페이지 ONLINE · 실시간 경마 · 최신 범위 검수",
        "commands": [
            "!정보 · !생존대시보드",
            "!세계지도 · !지도대시보드",
            "!카드대시보드 · !카드도감",
            "!경마 10000 · !경마장 · !경마전적",
            "!아바돈초대 경마 10000",
            "!테스트 상세 · !패치노트",
        ],
    })

    bot.v1092_version = VERSION  # type: ignore[attr-defined]
    bot.v1092_latest_checks = latest_checks  # type: ignore[attr-defined]
    bot.v1092_visual_dashboards = ("정보", "생존대시보드", "세계지도", "지도대시보드", "카드대시보드")  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] visual_dashboards=5 horse_racing=live online_feed=fallback+api recovered_races={recovered_races}", flush=True)
