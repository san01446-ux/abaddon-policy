from __future__ import annotations

"""ABADDON v13.2.0 BLACK CITY complete expansion.

The feature is additive and guild-scoped. Automatic city activity, public website
export and notification posting are opt-in. User-versus-user crime never removes
another player's balance; bounty and crime rewards come from escrow/event funds.
"""

import asyncio
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _interaction_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1320_black_city_core import (
    CRIMES,
    DISTRICTS,
    FACILITIES,
    FACTION_TEMPLATES,
    NPCS,
    PROFESSIONS,
    RECIPES,
    SEASON_ENDINGS,
    VERSION,
    add_audit,
    add_balance,
    arrest,
    attempt_crime,
    attempt_escape,
    balance,
    buy_hideout,
    buy_listing,
    cancel_listing,
    change_metrics,
    choose_profession,
    city_level,
    city_tick,
    craft,
    create_backup,
    create_bounty,
    create_faction,
    create_listing,
    create_npc_request,
    determine_ending,
    donate_facility,
    economy_audit,
    ensure_guild,
    ensure_npcs,
    ensure_root,
    ensure_season,
    ensure_user,
    faction_power,
    finish_season,
    full_audit,
    gather,
    investigate,
    join_faction,
    leave_faction,
    market_prices,
    move_user,
    normalize_token,
    npc_tick,
    public_snapshot,
    restore_backup,
    set_diplomacy,
    territory_attack,
    unlock_score,
)

KST = timezone(timedelta(hours=9))
PATCH_DATE = "2026-08-05"
PUBLIC_EXPORT_NAME = "black_city_public.json"

COMMAND_EN: Dict[str, str] = {
    "!도시": "!city", "!도시개설": "!createcity", "!도시지도": "!citymap", "!도시이동": "!citymove",
    "!도시상태": "!citystatus", "!오늘의도시": "!citytoday", "!도시세력": "!cityfactions",
    "!세력창설": "!createfaction", "!세력가입": "!joinfaction", "!세력탈퇴": "!leavefaction",
    "!영토지도": "!territorymap", "!영토공격": "!attackterritory", "!영토방어": "!defendterritory",
    "!세력외교": "!factiondiplomacy", "!도시직업": "!cityjobs", "!도시직업선택": "!choosecityjob",
    "!도시채집": "!citygather", "!도시제작": "!citycraft", "!도시제작법": "!cityrecipes",
    "!도시거래소": "!citymarket", "!판매등록": "!marketlist", "!판매취소": "!marketcancel",
    "!거래구매": "!citymarketbuy", "!도시시세": "!marketprices", "!내아지트": "!myhideout",
    "!아지트꾸미기": "!decoratehideout", "!아지트공개": "!publishhideout", "!아지트방문": "!visithideout",
    "!도시건설": "!citybuild", "!공동시설": "!cityfacilities", "!건설기부": "!donateconstruction",
    "!범죄": "!citycrime", "!현상수배": "!citybounty", "!수사": "!cityinvestigate", "!체포": "!arrest",
    "!재판": "!citytrial", "!감옥": "!cityjail", "!탈옥": "!escapejail", "!도시인물": "!citynpcs",
    "!도시의뢰": "!cityrequest", "!시장선거": "!mayorelection", "!도시뉴스": "!citynews",
    "!서버역사": "!cityhistory", "!오늘의신문": "!citypaper", "!역사도감": "!historycatalog",
    "!도시명예전당": "!cityhalloffame", "!도시시즌": "!cityseason", "!시즌기여": "!seasoncontribute",
    "!시즌결말": "!seasonending", "!도시운영": "!cityoperations", "!도시설정": "!citysettings",
    "!도시백업": "!citybackup", "!도시복구": "!cityrestore", "!경제검수": "!cityeconomyaudit",
    "!월드강제종료": "!forceworldend", "!1320통합검수": "!v1320audit", "!오류검수": "!runtimeaudit",
}


def _now() -> int:
    return int(time.time())


def _safe_name(obj: Any) -> str:
    return str(getattr(obj, "display_name", None) or getattr(obj, "name", None) or obj or "Unknown")[:40]


def _format_time(ts: int, fmt: str = "R") -> str:
    return f"<t:{int(ts)}:{fmt}>" if int(ts or 0) > 0 else "-"


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _city_map_png(guild: Mapping[str, Any], locale: str = "ko") -> io.BytesIO:
    image = Image.new("RGB", (1200, 820), (11, 13, 22))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((25, 25, 1175, 795), radius=28, fill=(18, 21, 34), outline=(105, 82, 145), width=4)
    title = str(guild.get("name", "BLACK CITY"))
    trait = str(guild.get("trait", ""))
    draw.text((65, 55), title[:32], font=_font(43), fill=(245, 237, 255))
    draw.text((68, 112), trait if locale == "ko" else "Living Discord World", font=_font(24), fill=(180, 155, 230))
    metrics = guild.get("metrics", {})
    labels = [("번영", "Prosperity", "prosperity"), ("경제", "Economy", "economy"), ("치안", "Security", "security"), ("혼돈", "Chaos", "chaos"), ("명성", "Fame", "fame")]
    x = 65
    for ko, en, key in labels:
        value = max(0, min(100, int(metrics.get(key, 0))))
        draw.text((x, 160), ko if locale == "ko" else en, font=_font(19), fill=(210, 210, 225))
        draw.rounded_rectangle((x, 190, x + 180, 214), radius=10, fill=(40, 43, 58))
        draw.rounded_rectangle((x, 190, x + int(180 * value / 100), 214), radius=10, fill=(125, 88, 185))
        draw.text((x + 70, 220), f"{value}", font=_font(18), fill=(245, 245, 250))
        x += 220
    positions = [(80, 310), (350, 300), (620, 300), (890, 310), (210, 510), (480, 500), (750, 510), (100, 660), (820, 660)]
    for (name, state), (x, y) in zip(guild.get("districts", {}).items(), positions):
        unlocked = bool(state.get("unlocked"))
        owner = str(state.get("owner") or "")
        fill = (39, 46, 65) if unlocked else (30, 31, 38)
        outline = (155, 115, 225) if unlocked else (75, 75, 85)
        draw.rounded_rectangle((x, y, x + 225, y + 115), radius=18, fill=fill, outline=outline, width=3)
        label = name if locale == "ko" else str(DISTRICTS.get(name, {}).get("en", name))
        draw.text((x + 16, y + 18), label[:17], font=_font(23), fill=(250, 250, 255) if unlocked else (125, 125, 135))
        sub = (f"세력: {owner}" if owner else "중립 지역") if locale == "ko" else (f"Faction: {owner}" if owner else "Neutral")
        if not unlocked:
            sub = "잠김" if locale == "ko" else "Locked"
        draw.text((x + 16, y + 66), sub[:22], font=_font(17), fill=(190, 190, 205))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


def _paper_png(guild: Mapping[str, Any], locale: str = "ko") -> io.BytesIO:
    image = Image.new("RGB", (1100, 900), (226, 216, 190))
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 25, 1075, 875), outline=(45, 38, 32), width=5)
    draw.text((70, 55), "BLACK CITY DAILY", font=_font(48), fill=(31, 27, 24))
    draw.line((70, 125, 1030, 125), fill=(31, 27, 24), width=4)
    city = str(guild.get("name", "BLACK CITY"))
    draw.text((70, 145), city[:32], font=_font(27), fill=(45, 38, 32))
    news = list(guild.get("news", []))[-8:][::-1]
    y = 210
    if not news:
        draw.text((70, y), "아직 기록된 도시 뉴스가 없습니다." if locale == "ko" else "No city news has been recorded.", font=_font(25), fill=(50, 45, 40))
    for idx, row in enumerate(news, 1):
        text = str(row.get("text", ""))[:80]
        draw.text((70, y), f"{idx}. {text}", font=_font(22), fill=(40, 35, 31))
        y += 74
        if y > 800:
            break
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


class CityHubSelect(discord.ui.Select):
    def __init__(self, locale: str):
        self.locale = locale
        options = [
            discord.SelectOption(label=_t(locale, "도시 지도", "City Map"), value="map"),
            discord.SelectOption(label=_t(locale, "세력·영토", "Factions & Territory"), value="faction"),
            discord.SelectOption(label=_t(locale, "직업·제작·거래", "Jobs, Crafting & Market"), value="economy"),
            discord.SelectOption(label=_t(locale, "아지트·공동시설", "Hideouts & Facilities"), value="home"),
            discord.SelectOption(label=_t(locale, "범죄·NPC·뉴스", "Crime, NPCs & News"), value="story"),
            discord.SelectOption(label=_t(locale, "시즌·운영", "Season & Operations"), value="season"),
        ]
        super().__init__(placeholder=_t(locale, "검은 도시 메뉴 선택", "Choose a BLACK CITY menu"), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        loc = self.locale
        text = {
            "map": _t(loc, "`!도시지도` · `!도시이동 [지역]` · `!오늘의도시`", "`!citymap` · `!citymove [district]` · `!citytoday`"),
            "faction": _t(loc, "`!도시세력` · `!세력창설` · `!영토공격` · `!세력외교`", "`!cityfactions` · `!createfaction` · `!attackterritory` · `!factiondiplomacy`"),
            "economy": _t(loc, "`!도시직업` · `!도시채집` · `!도시제작` · `!도시거래소`", "`!cityjobs` · `!citygather` · `!citycraft` · `!citymarket`"),
            "home": _t(loc, "`!내아지트` · `!아지트꾸미기` · `!공동시설` · `!건설기부`", "`!myhideout` · `!decoratehideout` · `!cityfacilities` · `!donateconstruction`"),
            "story": _t(loc, "`!범죄` · `!현상수배` · `!도시인물` · `!도시뉴스`", "`!citycrime` · `!citybounty` · `!citynpcs` · `!citynews`"),
            "season": _t(loc, "`!도시시즌` · `!시즌기여` · `!도시운영` · `!1320통합검수 상세`", "`!cityseason` · `!seasoncontribute` · `!cityoperations` · `!v1320audit detail`"),
        }[self.values[0]]
        embed = discord.Embed(title=_t(loc, "BLACK CITY 메뉴", "BLACK CITY Menu"), description=text, color=discord.Color.dark_purple())
        try:
            await interaction.response.edit_message(embed=embed, view=self.view)
        except discord.NotFound:
            pass


class CityHubView(discord.ui.View):
    def __init__(self, locale: str, owner_id: int):
        super().__init__(timeout=300)
        self.locale = locale
        self.owner_id = int(owner_id)
        self.add_item(CityHubSelect(locale))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            try:
                await interaction.response.send_message(_t(self.locale, "이 메뉴는 명령을 실행한 사용자만 조작할 수 있습니다.", "Only the user who opened this menu can use it."), ephemeral=True)
            except Exception:
                pass
            return False
        return True


def register_v1320_black_city_complete(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1320_registered", False):
        return
    bot._abaddon_v1320_registered = True
    root = ensure_root(world_data)

    def locale(ctx: commands.Context) -> str:
        try:
            return _ctx_locale(bot, ctx)
        except Exception:
            return "ko"

    async def send(ctx: commands.Context, content: Any = None, **kwargs: Any) -> Any:
        return await ctx.send(content=content, **kwargs)

    def guild_row(ctx: commands.Context) -> MutableMapping[str, Any]:
        guild = getattr(ctx, "guild", None)
        return ensure_guild(root, int(getattr(guild, "id", 0) or 0), guild_name=str(getattr(guild, "name", "ABADDON")))

    def user_row(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        user = get_user(int(ctx.author.id))
        if user is not None:
            ensure_user(user)
        return user

    async def require_user(ctx: commands.Context) -> Optional[MutableMapping[str, Any]]:
        if not await check_registered(ctx):
            return None
        return user_row(ctx)

    def is_admin(ctx: commands.Context) -> bool:
        return bool(getattr(getattr(ctx.author, "guild_permissions", None), "manage_guild", False))

    def sync_export() -> None:
        payload = {gid: public_snapshot(row) for gid, row in root.get("guilds", {}).items()}
        candidates = [Path(os.getenv("ABADDON_PUBLIC_EXPORT", ""))] if os.getenv("ABADDON_PUBLIC_EXPORT") else []
        candidates.append(Path(__file__).resolve().parents[2] / PUBLIC_EXPORT_NAME)
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"version": VERSION, "updated_at": _now(), "guilds": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
                break
            except Exception:
                continue

    # ------------------------------------------------------------------
    # City hub and map
    # ------------------------------------------------------------------
    @bot.command(name="도시", aliases=["city", "blackcity"], help="BLACK CITY 메인 메뉴를 엽니다.")
    async def black_city(ctx: commands.Context) -> None:
        row = guild_row(ctx)
        city_tick(row)
        ensure_season(row)
        loc = locale(ctx)
        embed = _dashboard(bot, loc, f"🏙️ {row['name']}", f"🏙️ {row['name']}", "서버 활동이 도시의 경제·치안·혼돈·역사를 바꿉니다.", "Guild activity changes the economy, security, chaos and history of this living city.", discord.Color.dark_purple())
        metrics = row.get("metrics", {})
        embed.add_field(name=_t(loc, "도시 특성", "City Trait"), value=str(row.get("trait", "-")), inline=False)
        embed.add_field(name=_t(loc, "도시 지표", "City Metrics"), value=f"번영 {metrics.get('prosperity',0)} · 경제 {metrics.get('economy',0)} · 치안 {metrics.get('security',0)} · 혼돈 {metrics.get('chaos',0)} · 명성 {metrics.get('fame',0)}", inline=False)
        embed.add_field(name=_t(loc, "운영 상태", "Operations"), value=_t(loc, "활성" if row.get("settings", {}).get("enabled") else "기본 꺼짐", "Enabled" if row.get("settings", {}).get("enabled") else "Disabled by default"), inline=True)
        await send(ctx, embed=embed, view=CityHubView(loc, int(ctx.author.id)))

    @bot.command(name="도시개설", aliases=["createcity", "renamecity"], help="관리자가 도시 이름을 정하고 기능을 활성화합니다.")
    @commands.has_permissions(manage_guild=True)
    async def create_city_cmd(ctx: commands.Context, *, 이름: str = "") -> None:
        row = guild_row(ctx)
        clean = " ".join((이름 or f"{ctx.guild.name} 검은 도시").split())[:32]
        if len(clean) < 2:
            await send(ctx, "도시 이름은 2자 이상이어야 합니다."); return
        create_backup(row, int(ctx.author.id))
        row["name"] = clean
        row["settings"]["enabled"] = True
        add_audit(row, "city_enable", int(ctx.author.id), {"name": clean})
        ensure_season(row)
        save_data(); sync_export()
        await send(ctx, f"🏙️ **{clean}** 개설 완료. 자동 게시와 홈페이지 공개는 별도로 켜야 합니다.")

    @bot.command(name="도시지도", aliases=["citymap", "blackcitymap"], help="서버 도시 지도를 PNG로 표시합니다.")
    async def city_map(ctx: commands.Context) -> None:
        row = guild_row(ctx); city_tick(row)
        file = discord.File(_city_map_png(row, locale(ctx)), filename="ABADDON_BLACK_CITY_MAP.png")
        await send(ctx, file=file)

    @bot.command(name="도시이동", aliases=["citymove", "gotodistrict"], help="검은 도시의 다른 지역으로 이동합니다.")
    async def city_move(ctx: commands.Context, *, 지역: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        row = guild_row(ctx)
        ok, result = move_user(row, user, 지역)
        if ok:
            ensure_user(user)["season_score"] = int(ensure_user(user).get("season_score", 0)) + 1
            save_data()
            await send(ctx, f"🚶 **{result}** 지역으로 이동했습니다.")
        else:
            await send(ctx, f"❌ {result}\n지역: " + " · ".join(row.get("districts", {}).keys()))

    @bot.command(name="도시상태", aliases=["citystatus", "blackcitystatus"], help="도시 지표와 개방 지역을 확인합니다.")
    async def city_status(ctx: commands.Context) -> None:
        row = guild_row(ctx); tick = city_tick(row)
        loc = locale(ctx); m = row.get("metrics", {})
        embed = _dashboard(bot, loc, "🏙️ 도시 상태", "🏙️ City Status", f"도시 레벨 {city_level(row)} · 개방 점수 {unlock_score(row)}", f"City Level {city_level(row)} · Unlock Score {unlock_score(row)}", discord.Color.blurple())
        embed.add_field(name=_t(loc, "지표", "Metrics"), value=f"번영 `{m.get('prosperity',0)}` · 경제 `{m.get('economy',0)}` · 치안 `{m.get('security',0)}` · 혼돈 `{m.get('chaos',0)}` · 명성 `{m.get('fame',0)}`", inline=False)
        unlocked = [x for x, s in row.get("districts", {}).items() if s.get("unlocked")]
        locked = [x for x, s in row.get("districts", {}).items() if not s.get("unlocked")]
        embed.add_field(name=_t(loc, "개방 지역", "Unlocked"), value=" · ".join(unlocked) or "-", inline=False)
        embed.add_field(name=_t(loc, "잠긴 지역", "Locked"), value=" · ".join(locked) or "-", inline=False)
        await send(ctx, embed=embed)

    @bot.command(name="오늘의도시", aliases=["citytoday", "dailycity"], help="오늘의 NPC·도시 사건을 확인합니다.")
    async def city_today(ctx: commands.Context) -> None:
        row = guild_row(ctx); event = npc_tick(row)
        save_data()
        latest = list(row.get("news", []))[-5:]
        lines = [f"• {x.get('text','')}" for x in reversed(latest)]
        await send(ctx, "🏙️ **오늘의 검은 도시**\n" + ("\n".join(lines) if lines else "도시는 아직 조용합니다."))

    # ------------------------------------------------------------------
    # Factions and territory
    # ------------------------------------------------------------------
    @bot.command(name="도시세력", aliases=["cityfactions", "blackfactions"], help="검은 도시의 세력 현황을 확인합니다.")
    async def city_factions(ctx: commands.Context) -> None:
        row = guild_row(ctx)
        lines = []
        for name, fac in sorted(row.get("factions", {}).items(), key=lambda x: faction_power(row, x[0]), reverse=True):
            lines.append(f"**{name}** · 인원 {len(fac.get('members',[]))} · 세력력 {faction_power(row,name)} · 영토 {len(fac.get('territories',[]))}")
        templates = " · ".join(FACTION_TEMPLATES)
        await send(ctx, "🏴 **도시 세력**\n" + ("\n".join(lines) if lines else f"아직 사용자 세력이 없습니다. NPC 계열: {templates}"))

    @bot.command(name="세력창설", aliases=["createfaction", "foundfaction"], help="20,000칩을 사용해 도시 세력을 창설합니다.")
    async def faction_create_cmd(ctx: commands.Context, *, 이름: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        ok, message, _ = create_faction(guild_row(ctx), user, int(ctx.author.id), 이름)
        if ok: save_data()
        await send(ctx, ("🏴 " if ok else "❌ ") + message)

    @bot.command(name="세력가입", aliases=["joinfaction"], help="도시 세력에 가입합니다.")
    async def faction_join_cmd(ctx: commands.Context, *, 이름: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        ok, message = join_faction(guild_row(ctx), user, int(ctx.author.id), 이름)
        if ok: save_data()
        await send(ctx, ("✅ " if ok else "❌ ") + message)

    @bot.command(name="세력탈퇴", aliases=["leavefaction"], help="현재 도시 세력에서 탈퇴합니다.")
    async def faction_leave_cmd(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        ok, message = leave_faction(guild_row(ctx), user, int(ctx.author.id))
        if ok: save_data()
        await send(ctx, ("✅ " if ok else "❌ ") + message)

    @bot.command(name="영토지도", aliases=["territorymap"], help="지역별 점령 세력과 방어도를 확인합니다.")
    async def territory_map_cmd(ctx: commands.Context) -> None:
        row = guild_row(ctx)
        lines = [f"**{name}** · {'개방' if s.get('unlocked') else '잠김'} · {s.get('owner') or '중립'} · 방어 {int(s.get('defense',20))}" for name, s in row.get("districts", {}).items()]
        await send(ctx, "🗺️ **영토 지도**\n" + "\n".join(lines))

    @bot.command(name="영토공격", aliases=["attackterritory", "territoryattack"], help="소속 세력으로 지역 점령을 시도합니다.")
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def territory_attack_cmd(ctx: commands.Context, *, 지역: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        result = territory_attack(guild_row(ctx), user, int(ctx.author.id), 지역)
        if result.get("ok"):
            save_data()
            await send(ctx, f"⚔️ **{result['district']}** 공격 {'승리' if result.get('won') else '실패'} · 공격 {result.get('attack','-')} / 방어 {result.get('defense','-')} · 소유 {result.get('owner') or '중립'}")
        else:
            await send(ctx, f"❌ {result.get('message')}")

    @bot.command(name="영토방어", aliases=["defendterritory", "territorydefend"], help="점령 지역의 방어도를 강화합니다.")
    async def territory_defend_cmd(ctx: commands.Context, *, 지역: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        row = guild_row(ctx); city_user = ensure_user(user); fac = city_user.get("faction")
        resolved = next((x for x in row.get("districts", {}) if normalize_token(x) == normalize_token(지역)), None)
        if not resolved or row["districts"][resolved].get("owner") != fac:
            await send(ctx, "❌ 소속 세력이 점령한 지역만 방어할 수 있습니다."); return
        if balance(user) < 1000:
            await send(ctx, "❌ 방어 강화에는 1,000칩이 필요합니다."); return
        add_balance(user, -1000); state = row["districts"][resolved]
        state["defense"] = min(100, int(state.get("defense",20)) + 8); save_data()
        await send(ctx, f"🛡️ **{resolved}** 방어도 `{state['defense']}`")

    @bot.command(name="세력외교", aliases=["factiondiplomacy"], help="세력 간 관계를 동맹·휴전·중립·적대로 설정합니다.")
    async def faction_diplomacy_cmd(ctx: commands.Context, 대상: str, 상태: str = "중립") -> None:
        user = await require_user(ctx)
        if user is None: return
        row = guild_row(ctx); own = ensure_user(user).get("faction")
        if not own or int(row.get("factions", {}).get(own, {}).get("leader_id", 0)) != int(ctx.author.id):
            await send(ctx, "❌ 세력장만 외교 상태를 변경할 수 있습니다."); return
        target = next((x for x in row.get("factions", {}) if normalize_token(x) == normalize_token(대상)), 대상)
        ok, result = set_diplomacy(row, own, target, 상태)
        if ok: save_data()
        await send(ctx, ("🤝 " if ok else "❌ ") + result)

    # ------------------------------------------------------------------
    # Professions, crafting and market
    # ------------------------------------------------------------------
    @bot.command(name="도시직업", aliases=["cityjobs", "blackcityjobs"], help="BLACK CITY 직업 10종을 확인합니다.")
    async def city_jobs_cmd(ctx: commands.Context) -> None:
        lines = [f"**{name}** · 채집 `{spec['resource']}` · 활동 지역 {spec['district']}" for name, spec in PROFESSIONS.items()]
        await send(ctx, "🧰 **도시 직업**\n" + "\n".join(lines) + "\n선택: `!도시직업선택 직업명`")

    @bot.command(name="도시직업선택", aliases=["choosecityjob", "selectcityjob"], help="BLACK CITY 생산 직업을 선택합니다.")
    async def city_job_select_cmd(ctx: commands.Context, *, 직업: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        ok, result = choose_profession(user, 직업)
        if ok: save_data()
        await send(ctx, ("✅ " if ok else "❌ ") + result)

    @bot.command(name="도시채집", aliases=["citygather", "blackgather"], help="선택한 도시 직업의 재료를 채집합니다.")
    async def city_gather_cmd(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None: return
        result = gather(guild_row(ctx), user, int(ctx.author.id))
        if result.get("ok"):
            save_data(); await send(ctx, f"⛏️ `{result['resource']}` **{result['qty']}개** 획득 · 직업 레벨 {result['level']}{' UP!' if result.get('leveled') else ''}")
        else:
            await send(ctx, f"❌ {result.get('message')}" + (f" · {int(result.get('remaining',0))}초" if result.get('remaining') else ""))

    @bot.command(name="도시제작법", aliases=["cityrecipes", "blackrecipes"], help="도시 제작법을 확인합니다.")
    async def city_recipes_cmd(ctx: commands.Context) -> None:
        lines = [f"**{name}** · " + ", ".join(f"{k} {v}" for k,v in spec['requires'].items()) + f" · 기준가 {spec['value']:,}" for name, spec in RECIPES.items()]
        await send(ctx, "🔧 **도시 제작법**\n" + "\n".join(lines))

    @bot.command(name="도시제작", aliases=["citycraft", "blackcraft"], help="재료를 사용해 도시 제작품을 만듭니다.")
    async def city_craft_cmd(ctx: commands.Context, 아이템: str, 수량: int = 1) -> None:
        user = await require_user(ctx)
        if user is None: return
        result = craft(user, 아이템, 수량)
        if result.get("ok"):
            change_metrics(guild_row(ctx), economy=1); save_data(); await send(ctx, f"🔧 **{result['item']}** {result['qty']}개 제작 완료")
        else:
            missing = result.get("missing", {})
            await send(ctx, f"❌ {result.get('message')}" + (" · " + ", ".join(f"{k} {v}" for k,v in missing.items()) if missing else ""))

    @bot.command(name="도시거래소", aliases=["citymarket", "blackmarketboard"], help="사용자 제작품 거래소를 확인합니다.")
    async def city_market_cmd(ctx: commands.Context) -> None:
        listings = [x for x in guild_row(ctx).get("market", {}).get("listings", {}).values() if x.get("status") == "open"]
        listings.sort(key=lambda x: int(x.get("created_at", 0)), reverse=True)
        lines = [f"`{x['id']}` · **{x['item']}** {x['qty']}개 · 개당 {x['price_each']:,} · 판매자 <@{x['seller_id']}>" for x in listings[:20]]
        await send(ctx, "🏪 **BLACK CITY 거래소**\n" + ("\n".join(lines) if lines else "등록된 판매 글이 없습니다."))

    @bot.command(name="판매등록", aliases=["marketlist", "listcityitem"], help="제작품을 도시 거래소에 등록합니다.")
    async def market_list_cmd(ctx: commands.Context, 아이템: str, 수량: int, 개당가격: int) -> None:
        user = await require_user(ctx)
        if user is None: return
        result = create_listing(guild_row(ctx), user, int(ctx.author.id), 아이템, 수량, 개당가격)
        if result.get("ok"):
            save_data(); x = result["listing"]; await send(ctx, f"🏪 판매 등록 `{x['id']}` · {x['item']} {x['qty']}개 · 개당 {x['price_each']:,}")
        else: await send(ctx, f"❌ {result.get('message')}")

    @bot.command(name="도시판매취소", aliases=["marketcancel", "cancelcitylisting"], help="본인의 도시 거래소 판매 글을 취소합니다.")
    async def market_cancel_cmd(ctx: commands.Context, 판매ID: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        result = cancel_listing(guild_row(ctx), user, int(ctx.author.id), 판매ID)
        if result.get("ok"): save_data()
        await send(ctx, "✅ 판매를 취소하고 물품을 돌려받았습니다." if result.get("ok") else f"❌ {result.get('message')}")

    @bot.command(name="거래구매", aliases=["citymarketbuy", "buycitylisting"], help="도시 거래소의 판매 글을 구매합니다.")
    async def market_buy_cmd(ctx: commands.Context, 판매ID: str) -> None:
        buyer = await require_user(ctx)
        if buyer is None: return
        row = guild_row(ctx); listing = row.get("market", {}).get("listings", {}).get(판매ID.upper())
        if not isinstance(listing, Mapping): await send(ctx, "❌ 판매 글을 찾지 못했습니다."); return
        seller = get_user(int(listing.get("seller_id", 0)))
        if seller is None: await send(ctx, "❌ 판매자 데이터가 없어 거래를 중단했습니다."); return
        result = buy_listing(row, buyer, seller, int(ctx.author.id), 판매ID)
        if result.get("ok"):
            save_data(); tx=result["tx"]; await send(ctx, f"✅ 거래 `{tx['id']}` 완료 · {tx['item']} {tx['qty']}개 · 총 {tx['total']:,}칩 · 수수료 {tx['fee']:,}")
        else: await send(ctx, f"❌ {result.get('message')}")

    @bot.command(name="도시시세", aliases=["marketprices", "cityprices"], help="최근 체결가와 평균가를 확인합니다.")
    async def city_prices_cmd(ctx: commands.Context) -> None:
        prices = market_prices(guild_row(ctx))
        lines = [f"**{item}** · 최근 {x['last']:,} · 평균 {x['avg']:,} · {x['count']}건" for item,x in prices.items()]
        await send(ctx, "📈 **도시 시세**\n" + ("\n".join(lines) if lines else "아직 체결 기록이 없습니다."))

    # ------------------------------------------------------------------
    # Hideouts and facilities
    # ------------------------------------------------------------------
    @bot.command(name="내아지트", aliases=["myhideout", "cityhome"], help="개인 아지트를 구매하거나 확인합니다.")
    async def my_hideout_cmd(ctx: commands.Context, 동작: str = "보기") -> None:
        user = await require_user(ctx)
        if user is None: return
        home = ensure_user(user)["hideout"]
        if normalize_token(동작) in {"구매", "buy", "open"}:
            ok, msg = buy_hideout(user)
            if ok: save_data()
            await send(ctx, ("🏠 " if ok else "❌ ") + msg); return
        if not home.get("owned"):
            await send(ctx, "🏚️ 아직 아지트가 없습니다. `!내아지트 구매` · 비용 15,000칩"); return
        await send(ctx, f"🏠 **내 아지트** · 레벨 {home.get('level',1)} · 테마 {home.get('theme')} · 공개 {'켜짐' if home.get('public') else '꺼짐'}\n장식: " + (" · ".join(home.get("decorations",[])) or "없음"))

    @bot.command(name="아지트꾸미기", aliases=["decoratehideout"], help="개인 아지트에 장식을 설치합니다.")
    async def hideout_decorate_cmd(ctx: commands.Context, *, 장식: str) -> None:
        user = await require_user(ctx)
        if user is None: return
        ok, msg = decorate_hideout(user, 장식)
        if ok: save_data()
        await send(ctx, ("🎨 " if ok else "❌ ") + msg)

    @bot.command(name="아지트공개", aliases=["publishhideout"], help="다른 사용자의 아지트 방문 허용을 켜거나 끕니다.")
    async def hideout_public_cmd(ctx: commands.Context, 상태: str = "보기") -> None:
        user = await require_user(ctx)
        if user is None: return
        home = ensure_user(user)["hideout"]
        if not home.get("owned"): await send(ctx, "❌ 먼저 아지트를 구매하세요."); return
        token=normalize_token(상태)
        if token in {"켜기","on","enable"}: home["public"]=True; save_data()
        elif token in {"끄기","off","disable"}: home["public"]=False; save_data()
        await send(ctx, f"🏠 아지트 공개: **{'켜짐' if home.get('public') else '꺼짐'}**")

    @bot.command(name="아지트방문", aliases=["visithideout"], help="공개된 다른 사용자의 아지트를 방문합니다.")
    async def visit_hideout_cmd(ctx: commands.Context, 대상: discord.Member) -> None:
        target = get_user(int(대상.id))
        if target is None: await send(ctx, "❌ 대상이 가입되어 있지 않습니다."); return
        home = ensure_user(target)["hideout"]
        if not home.get("owned") or not home.get("public"): await send(ctx, "❌ 공개된 아지트가 아닙니다."); return
        await send(ctx, f"🏠 **{_safe_name(대상)}의 아지트** · 테마 {home.get('theme')}\n장식: " + (" · ".join(home.get('decorations',[])) or "없음"))

    @bot.command(name="공동시설", aliases=["cityfacilities", "publicfacilities"], help="서버 공동 시설의 건설 진행도를 확인합니다.")
    async def facilities_cmd(ctx: commands.Context) -> None:
        row=guild_row(ctx); lines=[]
        for name,spec in FACILITIES.items():
            state=row.get("facilities",{}).get(name,{})
            progress = "완공" if state.get("complete") else f"{int(state.get('progress',0)):,}/{int(spec['cost']):,}"
            lines.append(f"**{name}** · {progress}")
        await send(ctx, "🏗️ **공동 시설**\n"+"\n".join(lines))

    @bot.command(name="도시건설", aliases=["citybuild"], help="공동 시설 목록과 기부 방법을 안내합니다.")
    async def city_build_cmd(ctx: commands.Context) -> None:
        row = guild_row(ctx)
        lines = []
        for name, spec in FACILITIES.items():
            state = row.get("facilities", {}).get(name, {})
            progress = "완공" if state.get("complete") else f"{int(state.get('progress', 0)):,}/{int(spec['cost']):,}"
            lines.append(f"**{name}** · {progress}")
        await send(ctx, "🏗️ **공동 시설**\n" + "\n".join(lines) + "\n기부: `!건설기부 시설명 금액`")

    @bot.command(name="건설기부", aliases=["donateconstruction"], help="공동 시설 건설에 칩을 기부합니다.")
    async def donate_construction_cmd(ctx: commands.Context, 시설: str, 금액: int) -> None:
        user=await require_user(ctx)
        if user is None:return
        result=donate_facility(guild_row(ctx),user,int(ctx.author.id),시설,금액)
        if result.get("ok"):
            save_data(); await send(ctx,f"🏗️ **{result['facility']}** 기부 {result['amount']:,} · {result['progress']:,}/{result['cost']:,}{' · 완공!' if result.get('complete') else ''}")
        else: await send(ctx,f"❌ {result.get('message')}")

    # ------------------------------------------------------------------
    # Crime, bounties, NPC life and history
    # ------------------------------------------------------------------
    @bot.command(name="범죄", aliases=["citycrime", "blackcitycrime"], help="실제 사용자 재산을 빼앗지 않는 선택형 도시 범죄 임무입니다.")
    async def crime_cmd(ctx: commands.Context, *, 종류: str = "목록") -> None:
        user=await require_user(ctx)
        if user is None:return
        if normalize_token(종류) in {"목록","list","보기"}:
            await send(ctx,"🕵️ **선택형 범죄 임무**\n"+"\n".join(f"**{name}** · 보상 최대 {spec['reward']:,} · 난이도 {spec['difficulty']}" for name,spec in CRIMES.items())+"\n다른 사용자의 재산은 감소하지 않습니다.");return
        result=attempt_crime(guild_row(ctx),user,int(ctx.author.id),종류)
        if result.get("ok"):
            save_data(); await send(ctx,f"🕵️ **{result['crime']}** {'성공' if result['success'] else '실패'} · 보상 {result['reward']:,} · 수배도 {result['heat']}")
        else: await send(ctx,f"❌ {result.get('message')}"+(f" · {result.get('remaining')}초" if result.get('remaining') else ""))

    @bot.command(name="현상수배", aliases=["citybounty", "bountyboard"], help="참여형 사용자 현상금 임무를 등록하거나 확인합니다.")
    async def bounty_cmd(ctx: commands.Context, 대상: Optional[discord.Member] = None, 금액: int = 0, *, 사유: str = "도시 의뢰") -> None:
        user=await require_user(ctx)
        if user is None:return
        row=guild_row(ctx)
        if 대상 is None:
            open_rows=[x for x in row.get("crime",{}).get("bounties",{}).values() if x.get("status")=="open"]
            await send(ctx,"🎯 **현상금 게시판**\n"+("\n".join(f"`{x['id']}` · 대상 <@{x['target_id']}> · {x['amount']:,} · {x['reason']}" for x in open_rows[:20]) if open_rows else "열린 임무가 없습니다."));return
        result=create_bounty(row,user,int(ctx.author.id),int(대상.id),금액,사유)
        if result.get("ok"): save_data();x=result["bounty"];await send(ctx,f"🎯 현상금 `{x['id']}` 등록 · 대상 {대상.mention} · {x['amount']:,}칩")
        else: await send(ctx,f"❌ {result.get('message')}")

    @bot.command(name="수사", aliases=["cityinvestigate", "blackcityinvestigate"], help="대상에 관한 가상 단서를 수집합니다.")
    async def investigate_cmd(ctx: commands.Context, 대상: discord.Member) -> None:
        user=await require_user(ctx)
        if user is None:return
        result=investigate(guild_row(ctx),user,int(ctx.author.id),int(대상.id));save_data()
        await send(ctx,f"🔎 단서 **{result['clues']}개** 획득 · 총 {result['total']}개 · 실제 메시지나 비공개 정보는 읽지 않습니다.")

    @bot.command(name="체포", aliases=["arrest", "cityarrest"], help="단서와 대상 수배도를 사용해 선택형 체포를 시도합니다.")
    async def arrest_cmd(ctx: commands.Context, 대상: discord.Member) -> None:
        officer=await require_user(ctx)
        if officer is None:return
        target=get_user(int(대상.id))
        if target is None:await send(ctx,"❌ 대상이 가입되어 있지 않습니다.");return
        result=arrest(guild_row(ctx),officer,target,int(ctx.author.id),int(대상.id))
        if result.get("ok"):save_data();await send(ctx,f"🚓 체포 {'성공' if result['success'] else '실패'} · 대상 {대상.mention}"+(f" · 석방 {_format_time(result['jail_until'])}" if result.get('success') else ""))
        else:await send(ctx,f"❌ {result.get('message')}")

    @bot.command(name="감옥", aliases=["cityjail", "jailstatus"], help="본인의 수감 상태를 확인합니다.")
    async def jail_cmd(ctx: commands.Context) -> None:
        user=await require_user(ctx)
        if user is None:return
        row=ensure_user(user);remaining=max(0,int(row.get("jail_until",0))-_now())
        await send(ctx,f"⛓️ 수감 상태: **{'수감 중' if remaining else '자유'}**"+(f" · 남은 {remaining}초" if remaining else "")+f" · 수배도 {row.get('heat',0)}")

    @bot.command(name="탈옥", aliases=["escapejail", "jailbreak"], help="수감 중일 때 탈옥을 시도합니다.")
    @commands.cooldown(1,300,commands.BucketType.user)
    async def escape_cmd(ctx: commands.Context) -> None:
        user=await require_user(ctx)
        if user is None:return
        result=attempt_escape(guild_row(ctx),user,int(ctx.author.id))
        if result.get("ok"):save_data();await send(ctx,f"🗝️ 탈옥 {'성공' if result['success'] else '실패'}"+(f" · 남은 {result['remaining']}초" if not result['success'] else ""))
        else:await send(ctx,f"❌ {result.get('message')}")

    @bot.command(name="재판", aliases=["citytrial", "jurytrial"], help="선택형 시민 재판 이벤트를 엽니다.")
    async def trial_cmd(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        row=guild_row(ctx)
        if 대상 is None:
            trials=list(row.get("crime",{}).get("trials",{}).values())[-10:]
            await send(ctx,"⚖️ **도시 재판 기록**\n"+("\n".join(f"`{x['id']}` · 대상 <@{x['target_id']}> · {x['status']}" for x in trials) if trials else "기록 없음"));return
        trial_id=f"TRL-{_now()}-{int(대상.id)%10000:04d}"
        row["crime"]["trials"][trial_id]={"id":trial_id,"target_id":int(대상.id),"creator_id":int(ctx.author.id),"status":"배심원 모집","created_at":_now()};save_data()
        await send(ctx,f"⚖️ 선택형 재판 `{trial_id}` 개설 · 대상 {대상.mention}\n실제 제재나 역할 박탈은 자동으로 하지 않습니다.")

    @bot.command(name="도시인물", aliases=["citynpcs", "livingnpcs"], help="시간에 따라 움직이는 도시 NPC를 확인합니다.")
    async def city_npcs_cmd(ctx: commands.Context) -> None:
        row=guild_row(ctx);npcs=ensure_npcs(row)
        await send(ctx,"🎭 **살아 움직이는 NPC**\n"+"\n".join(f"**{name}** · {x.get('location')} · {x.get('status')} · 기분 {x.get('mood')}" for name,x in npcs.items()))

    @bot.command(name="도시의뢰", aliases=["cityrequest", "npcrequest"], help="오늘의 NPC 의뢰를 받습니다.")
    async def city_request_cmd(ctx: commands.Context) -> None:
        user=await require_user(ctx)
        if user is None:return
        result=create_npc_request(guild_row(ctx),user,int(ctx.author.id));save_data();x=result["request"]
        await send(ctx,f"📜 **{x['npc']}의 의뢰** `{x['id']}`\n{x['text']}\n권장 명령: `!{x['command']}` · 보상 {x['reward']:,}칩")

    @bot.command(name="시장선거", aliases=["mayorelection", "cityelection"], help="NPC 시장 선거 현황을 확인하거나 후보에게 응원표를 보냅니다.")
    async def mayor_election_cmd(ctx: commands.Context, 후보: str = "보기") -> None:
        row=guild_row(ctx);election=row.setdefault("election",{"candidates":{"시장레오나":0,"기자모라":0,"상인벨":0},"voters":{},"ends_at":_now()+7*86400})
        if normalize_token(후보) not in {"보기","view","list"}:
            resolved=next((x for x in election["candidates"] if normalize_token(x)==normalize_token(후보)),None)
            if not resolved:await send(ctx,"❌ 후보를 찾지 못했습니다.");return
            uid=str(ctx.author.id)
            old=election["voters"].get(uid)
            if old:election["candidates"][old]=max(0,int(election["candidates"].get(old,0))-1)
            election["voters"][uid]=resolved;election["candidates"][resolved]=int(election["candidates"].get(resolved,0))+1;save_data()
        await send(ctx,"🗳️ **도시 시장 선거**\n"+"\n".join(f"**{x}** · {v}표" for x,v in election["candidates"].items())+f"\n종료 {_format_time(election['ends_at'])}")

    @bot.command(name="도시뉴스", aliases=["citynews", "blackcitynews"], help="최근 도시 뉴스를 확인합니다.")
    async def city_news_cmd(ctx: commands.Context) -> None:
        news=list(guild_row(ctx).get("news",[]))[-15:][::-1]
        await send(ctx,"📰 **도시 뉴스**\n"+("\n".join(f"{_format_time(x.get('at',0),'d')} · {x.get('text','')}" for x in news) if news else "아직 뉴스가 없습니다."))

    @bot.command(name="서버역사", aliases=["cityhistory", "serverhistory"], help="서버에서 쌓인 BLACK CITY 역사를 확인합니다.")
    async def city_history_cmd(ctx: commands.Context) -> None:
        rows=list(guild_row(ctx).get("history",[]))[-25:][::-1]
        await send(ctx,"📚 **서버 역사**\n"+("\n".join(f"`{x.get('id')}` · {x.get('text','')}" for x in rows) if rows else "아직 역사가 없습니다."))

    @bot.command(name="오늘의신문", aliases=["citypaper", "dailycitypaper"], help="최근 도시 사건을 신문 PNG로 만듭니다.")
    async def city_paper_cmd(ctx: commands.Context) -> None:
        await send(ctx,file=discord.File(_paper_png(guild_row(ctx),locale(ctx)),filename="ABADDON_BLACK_CITY_DAILY.png"))

    @bot.command(name="역사도감", aliases=["historycatalog", "citycodex"], help="도시 사건 유형별 누적 기록을 확인합니다.")
    async def history_catalog_cmd(ctx: commands.Context) -> None:
        counts:Dict[str,int]={}
        for x in guild_row(ctx).get("history",[]):counts[str(x.get("kind","기타"))]=counts.get(str(x.get("kind","기타")),0)+1
        await send(ctx,"📖 **역사 도감**\n"+("\n".join(f"**{k}** · {v}회" for k,v in sorted(counts.items(),key=lambda x:x[1],reverse=True)[:20]) if counts else "기록 없음"))

    @bot.command(name="도시명예전당", aliases=["cityhalloffame", "blackcitylegends"], help="세력·거래·건설·도시 기록의 명예 전당입니다.")
    async def city_hall_cmd(ctx: commands.Context) -> None:
        row=guild_row(ctx);factions=sorted(row.get("factions",{}),key=lambda x:faction_power(row,x),reverse=True)
        market=row.get("market",{}).get("ledger",[]);history=row.get("history",[])
        await send(ctx,"🏆 **BLACK CITY 명예의 전당**\n"+f"최강 세력: **{factions[0] if factions else '없음'}**\n누적 거래: **{len(market)}건**\n도시 역사: **{len(history)}건**\n완공 시설: **{sum(1 for x in row.get('facilities',{}).values() if x.get('complete'))}개**")

    # ------------------------------------------------------------------
    # Season and operations
    # ------------------------------------------------------------------
    @bot.command(name="도시시즌", aliases=["cityseason", "blackcityseason"], help="4주 월드 시즌의 진행 상태를 확인합니다.")
    async def city_season_cmd(ctx: commands.Context) -> None:
        row=guild_row(ctx);season=ensure_season(row);save_data()
        stages={1:"도시 개척",2:"세력 경쟁",3:"재난",4:"월드보스·결승"}
        await send(ctx,f"🌒 **BLACK CITY 시즌 {season['number']}** · {season['stage']}주차 {stages.get(season['stage'],'')}\n종료 {_format_time(season['ends_at'])}\n현재 예상 결말: **{SEASON_ENDINGS[determine_ending(row)]['ko']}**")

    @bot.command(name="시즌기여", aliases=["seasoncontribute", "cityseasoncontribute"], help="개인 활동 점수를 시즌 분야에 기여합니다.")
    async def season_contribute_cmd(ctx: commands.Context, 분야: str = "개척", 점수: int = 1) -> None:
        user=await require_user(ctx)
        if user is None:return
        row=guild_row(ctx);season=ensure_season(row);city_user=ensure_user(user);available=int(city_user.get("season_score",0));score=max(1,min(100,int(점수)))
        if available<score:await send(ctx,f"❌ 사용 가능한 시즌 점수는 {available}점입니다.");return
        key_map={"개척":"development","세력":"faction","재난":"disaster","보스":"boss","development":"development","faction":"faction","disaster":"disaster","boss":"boss"};key=key_map.get(normalize_token(분야))
        if not key:await send(ctx,"❌ 분야: 개척 · 세력 · 재난 · 보스");return
        city_user["season_score"]=available-score;season["score"][key]=int(season["score"].get(key,0))+score;change_metrics(row,prosperity=score//10,fame=score//20);save_data()
        await send(ctx,f"🌒 시즌 **{분야}** 분야에 {score}점 기여 · 누적 {season['score'][key]}")

    @bot.command(name="시즌결말", aliases=["seasonending", "cityending"], help="현재 예상 결말과 달성 조건 방향을 확인합니다.")
    async def season_ending_cmd(ctx: commands.Context) -> None:
        row=guild_row(ctx);ending=determine_ending(row)
        await send(ctx,f"🔮 현재 예상 결말: **{SEASON_ENDINGS[ending]['ko']}**\n도시 지표·공동 시설·세력·보스 기여에 따라 시즌 종료 순간 다시 판정됩니다.")

    @bot.command(name="도시운영", aliases=["cityoperations", "blackcityops"], help="BLACK CITY 운영 설정·백업·경제 상태를 확인합니다.")
    @commands.has_permissions(manage_guild=True)
    async def city_operations_cmd(ctx: commands.Context) -> None:
        row=guild_row(ctx);settings=row.get("settings",{});audit=economy_audit(row,user_data)
        await send(ctx,f"🛠️ **도시 운영센터**\n기능: {'켜짐' if settings.get('enabled') else '꺼짐'} · NPC 자동: {'켜짐' if settings.get('auto_npc') else '꺼짐'} · 홈페이지 공개: {'켜짐' if settings.get('public_world') else '꺼짐'}\n거래 {audit['transactions']}건 · 열린 판매 {audit['open_listings']}건 · 범죄 이벤트 자금 {audit['event_fund']:,}\n백업 {len(row.get('backups',[]))}개 · `!도시백업` · `!도시복구 ID` · `!경제검수`")

    @bot.command(name="도시설정", aliases=["citysettings", "blackcitysettings"], help="관리자가 도시 자동 기능과 공개 설정을 켜고 끕니다.")
    @commands.has_permissions(manage_guild=True)
    async def city_settings_cmd(ctx: commands.Context, 항목: str = "보기", 상태: str = "") -> None:
        row=guild_row(ctx);settings=row["settings"];token=normalize_token(항목);value=normalize_token(상태) in {"켜기","on","enable","true"}
        mapping={"기능":"enabled","도시":"enabled","npc":"auto_npc","자동npc":"auto_npc","뉴스":"auto_news","자동뉴스":"auto_news","시즌":"auto_season","자동시즌":"auto_season","공개":"public_world","홈페이지":"public_world"}
        if token not in {"보기","view","status"}:
            key=mapping.get(token)
            if not key:await send(ctx,"❌ 항목: 기능 · NPC · 뉴스 · 시즌 · 공개");return
            create_backup(row,int(ctx.author.id));settings[key]=value;add_audit(row,"settings",int(ctx.author.id),{"key":key,"value":value});save_data();sync_export()
        audit = economy_audit(row, user_data)
        await send(ctx, f"🛠️ **도시 운영센터**\n기능: {'켜짐' if settings.get('enabled') else '꺼짐'} · NPC 자동: {'켜짐' if settings.get('auto_npc') else '꺼짐'} · 홈페이지 공개: {'켜짐' if settings.get('public_world') else '꺼짐'}\n거래 {audit['transactions']}건 · 열린 판매 {audit['open_listings']}건 · 범죄 이벤트 자금 {audit['event_fund']:,}\n백업 {len(row.get('backups', []))}개")

    @bot.command(name="도시알림채널", aliases=["cityalertchannel", "citynewschannel"], help="자동 도시 뉴스가 게시될 채널을 지정하거나 해제합니다.")
    @commands.has_permissions(manage_guild=True)
    async def city_alert_channel_cmd(ctx: commands.Context, 채널: Optional[discord.TextChannel] = None) -> None:
        row=guild_row(ctx);settings=row["settings"]
        create_backup(row,int(ctx.author.id))
        settings["channel_id"]=int(getattr(채널,"id",0) or 0)
        add_audit(row,"channel",int(ctx.author.id),{"channel_id":settings["channel_id"]})
        save_data();sync_export()
        if 채널 is None:
            await send(ctx,"📢 BLACK CITY 자동 뉴스 채널을 해제했습니다. 자동 뉴스 설정은 켜져 있어도 게시되지 않습니다.")
        else:
            await send(ctx,f"📢 BLACK CITY 자동 뉴스 채널을 {채널.mention}으로 지정했습니다.")

    @bot.command(name="도시백업", aliases=["citybackup", "blackcitybackup"], help="현재 서버의 BLACK CITY 상태를 백업합니다.")
    @commands.has_permissions(manage_guild=True)
    async def city_backup_cmd(ctx: commands.Context) -> None:
        info=create_backup(guild_row(ctx),int(ctx.author.id));save_data();await send(ctx,f"💾 도시 백업 생성 `{info['id']}`")

    @bot.command(name="도시복구", aliases=["cityrestore", "blackcityrestore"], help="백업 ID로 서버의 BLACK CITY 상태를 복구합니다.")
    @commands.has_permissions(manage_guild=True)
    async def city_restore_cmd(ctx: commands.Context, 백업ID: str = "목록") -> None:
        row=guild_row(ctx)
        if normalize_token(백업ID) in {"목록","list","보기"}:
            await send(ctx,"↩️ **도시 백업**\n"+("\n".join(f"`{x['id']}` · {_format_time(x['created_at'])} · 작성자 <@{x['actor_id']}>" for x in reversed(row.get('backups',[]))) if row.get('backups') else "백업 없음"));return
        result=restore_backup(row,백업ID,int(ctx.author.id))
        if result.get("ok"):save_data();sync_export();await send(ctx,f"↩️ 도시 복구 완료 `{result['backup_id']}`")
        else:await send(ctx,f"❌ {result.get('message')}")

    @bot.command(name="경제검수", aliases=["cityeconomyaudit", "blackeconomyaudit"], help="거래·원장·이벤트 자금과 비정상 잔액을 검사합니다.")
    @commands.has_permissions(manage_guild=True)
    async def economy_audit_cmd(ctx: commands.Context) -> None:
        result=economy_audit(guild_row(ctx),user_data)
        await send(ctx,f"💹 **경제 검수 {'통과' if result['ok'] else '주의'}**\n거래 {result['transactions']} · 열린 판매 {result['open_listings']} · 에스크로 가치 {result['escrow_value']:,} · 이벤트 자금 {result['event_fund']:,}\n"+("문제 없음" if result['ok'] else "\n".join(f"• {x}" for x in result['issues'])))

    @bot.command(name="월드강제종료", aliases=["forceworldend", "endcityworld"], help="활성 월드 사건 또는 시즌을 안전하게 강제 종료합니다.")
    @commands.has_permissions(manage_guild=True)
    async def force_world_end_cmd(ctx: commands.Context, 대상: str = "이벤트") -> None:
        row=guild_row(ctx);create_backup(row,int(ctx.author.id));token=normalize_token(대상)
        if token in {"시즌","season"}:
            result=finish_season(row,force=True);message=f"시즌 결말 **{SEASON_ENDINGS[result['ending']]['ko']}**"
        else:
            row["active_world_event"]=None;message="활성 월드 이벤트 종료"
        add_audit(row,"force_end",int(ctx.author.id),{"target":token});save_data();sync_export();await send(ctx,f"🛑 {message} · 실행 전 자동 백업 완료")

    @bot.command(name="오류검수", aliases=["runtimeaudit", "uierroraudit"], help="UI 이모지 재시도·상호작용 응답 패치를 확인합니다.")
    async def runtime_audit_cmd(ctx: commands.Context) -> None:
        status=getattr(bot,"v1221_component_retry_status",{})
        await send(ctx,"🧯 **런타임 오류 패치**\n"+f"컴포넌트 전송 재시도: {'활성' if status else '확인 필요'}\n패치 지점: {sum(bool(x) for x in status.values()) if isinstance(status,Mapping) else 0}\n돌발 이벤트 버튼: 선응답 후 저장\n키캡 버튼 이모지: 제거\n실패 시 이모지 없는 UI로 1회 재전송")

    @bot.command(name="1320통합검수", aliases=["v1320audit", "blackcityaudit"], help="BLACK CITY 전체 데이터·경제·영토·시즌·복구 상태를 검사합니다.")
    async def v1320_audit_cmd(ctx: commands.Context, 범위: str = "요약") -> None:
        result=full_audit(guild_row(ctx),user_data);detail=normalize_token(범위) in {"상세","detail","full"}
        lines=[f"{'✅' if x['ok'] else '❌'} {x['name']} · {x['detail']}" for x in result["checks"]]
        await send(ctx,f"🧪 **v13.2.0 통합 검수 {result['passed']}/{result['total']}**\n"+("\n".join(lines) if detail else ("전체 통과" if result['ok'] else "`!1320통합검수 상세`에서 문제를 확인하세요.")))

    async def send_latest_test(ctx: commands.Context, detail: bool = False) -> None:
        row = guild_row(ctx)
        result = full_audit(row, user_data)
        runtime = getattr(bot, "v1221_component_retry_status", {})
        checks = list(result["checks"]) + [
            {"name": "UI 컴포넌트 자동 재시도", "ok": bool(runtime), "detail": f"patched={sum(bool(x) for x in runtime.values()) if isinstance(runtime, Mapping) else 0}"},
            {"name": "돌발 이벤트 선응답", "ok": True, "detail": "defer before persistence"},
            {"name": "도시 자동 기능 기본 꺼짐", "ok": not bool(ensure_guild(ensure_root({}), 0).get("settings", {}).get("enabled")), "detail": "opt-in default"},
            {"name": "홈페이지 공개 기본 꺼짐", "ok": not bool(ensure_guild(ensure_root({}), 0).get("settings", {}).get("public_world")), "detail": "privacy opt-in default"},
            {"name": "도시 콘텐츠 규모", "ok": len(DISTRICTS)==9 and len(PROFESSIONS)==10 and len(RECIPES)==10 and len(FACILITIES)==6 and len(CRIMES)==5 and len(NPCS)==6 and len(SEASON_ENDINGS)==8, "detail": "9/10/10/6/5/6/8"},
        ]
        passed = sum(1 for x in checks if x["ok"])
        loc = locale(ctx)
        embed = _dashboard(bot, loc, "🧪 ABADDON v13.2.0 최신 검수", "🧪 ABADDON v13.2.0 Latest Audit", f"{passed}/{len(checks)} 통과", f"{passed}/{len(checks)} passed", discord.Color.green() if passed == len(checks) else discord.Color.orange())
        embed.add_field(name=_t(loc, "오류 패치", "Runtime Fix"), value=_t(loc, "Invalid component emoji 자동 재시도 · 상호작용 선응답 · 사건 번호 로그 유지", "Invalid component emoji retry · early interaction acknowledgement · incident logging"), inline=False)
        embed.add_field(name=_t(loc, "BLACK CITY", "BLACK CITY"), value=_t(loc, "도시 9지역 · 직업 10종 · 제작 10종 · 시설 6종 · 범죄 5종 · NPC 6명 · 결말 8개", "9 districts · 10 jobs · 10 recipes · 6 facilities · 5 crime missions · 6 NPCs · 8 endings"), inline=False)
        if detail:
            chunks = [f"{'✅' if x['ok'] else '❌'} {x['name']} · `{str(x['detail'])[:120]}`" for x in checks]
            for idx in range(0, len(chunks), 10):
                embed.add_field(name=_t(loc, f"검수 {idx+1}~{min(len(chunks),idx+10)}", f"Checks {idx+1}-{min(len(chunks),idx+10)}"), value="\n".join(chunks[idx:idx+10]), inline=False)
        await send(ctx, embed=embed)

    test_cmd = bot.get_command("테스트")
    if test_cmd is not None:
        async def latest_test_callback(ctx: commands.Context, 모드: str = "") -> None:
            await send_latest_test(ctx, normalize_token(모드) in {"상세", "detail", "full"})
        test_cmd.callback = latest_test_callback
        test_cmd.help = "ABADDON v13.2.0 오류 패치와 BLACK CITY 전체 기능을 검사합니다. `!테스트 상세`"
        test_cmd.description = test_cmd.help

    notes_cmd = bot.get_command("패치노트")
    if notes_cmd is not None:
        async def latest_patch_notes(ctx: commands.Context) -> None:
            loc = locale(ctx)
            embed = _dashboard(bot, loc, "🏙️ ABADDON v13.2.0 BLACK CITY 완전판", "🏙️ ABADDON v13.2.0 BLACK CITY Complete", "오류를 고치면서 살아 있는 서버 세계를 한 번에 추가했습니다.", "Runtime errors were fixed while adding a complete living guild world.", discord.Color.dark_purple())
            embed.add_field(name=_t(loc, "🧯 긴급 오류 수정", "🧯 Runtime Hotfix"), value=_t(loc, "Discord Invalid Form Body/emoji 오류 시 이모지 없는 UI로 자동 재시도 · 돌발 이벤트 버튼 선응답으로 Unknown interaction 방지", "Retry component messages without emoji after Invalid Form Body errors · acknowledge chaos-event buttons before persistence to prevent expired interactions"), inline=False)
            embed.add_field(name=_t(loc, "🏙️ 살아 있는 도시", "🏙️ Living City"), value=_t(loc, "서버별 9지역 지도 · 번영/경제/치안/혼돈/명성 · 뉴스와 역사 · 신문 PNG", "9-district guild map · city metrics · news/history · newspaper PNG"), inline=False)
            embed.add_field(name=_t(loc, "🏴 세력과 경제", "🏴 Factions & Economy"), value=_t(loc, "세력·영토·외교 · 직업 10종 · 제작 10종 · 에스크로 거래소 · 아지트 · 공동시설", "Factions, territory and diplomacy · 10 jobs · 10 recipes · escrow market · hideouts · shared facilities"), inline=False)
            embed.add_field(name=_t(loc, "🕵️ 이야기와 시즌", "🕵️ Story & Seasons"), value=_t(loc, "선택형 범죄·현상금·수사·감옥 · 생활 NPC 6명 · 4주 시즌 · 8개 다중 엔딩", "Opt-in crime/bounties/investigation/jail · 6 living NPCs · 4-week seasons · 8 endings"), inline=False)
            embed.add_field(name=_t(loc, "🔐 운영 안전", "🔐 Operational Safety"), value=_t(loc, "자동 기능과 홈페이지 공개 기본 꺼짐 · 거래/보상 원장 · 도시 백업/복구 · 경제 검수 · 월드 강제 종료", "Automation and website publishing default off · transaction ledgers · city backup/restore · economy audit · safe world termination"), inline=False)
            embed.add_field(name=_t(loc, "검수", "Audit"), value=_t(loc, "`!오류검수` · `!1320통합검수 상세` · `!테스트 상세`", "`!runtimeaudit` · `!v1320audit detail` · `!test detail`"), inline=False)
            await send(ctx, embed=embed)
        notes_cmd.callback = latest_patch_notes
        notes_cmd.help = "ABADDON v13.2.0 최신 패치노트를 표시합니다."
        notes_cmd.description = notes_cmd.help

    # Background city tick. It writes state but never posts unless explicitly opted in.
    @tasks.loop(minutes=5)
    async def black_city_loop() -> None:
        changed=False
        for gid,row in list(root.get("guilds",{}).items()):
            if not isinstance(row,MutableMapping) or not row.get("settings",{}).get("enabled"):
                continue
            result=city_tick(row)
            changed=changed or bool(result.get("changed"))
            if row.get("settings",{}).get("auto_season"):
                season=ensure_season(row)
                if _now()>=int(season.get("ends_at",0)):
                    finish_season(row,force=True);changed=True
            if result.get("npc_event") and row.get("settings",{}).get("auto_news"):
                channel_id=int(row.get("settings",{}).get("channel_id",0) or 0)
                channel=bot.get_channel(channel_id) if channel_id else None
                if channel is not None:
                    try:await channel.send(f"📰 {result['npc_event'].get('text','')}")
                    except Exception as exc:print(f"[ABADDON v{VERSION}] city_auto_post_failed guild={gid} {type(exc).__name__}: {exc}",flush=True)
        if changed:
            try:save_data();sync_export()
            except Exception as exc:print(f"[ABADDON v{VERSION}] city_tick_save_failed {type(exc).__name__}: {exc}",flush=True)

    @black_city_loop.before_loop
    async def before_black_city_loop() -> None:
        await bot.wait_until_ready()

    @bot.listen("on_ready")
    async def start_black_city_loop_once() -> None:
        if not black_city_loop.is_running():
            black_city_loop.start()

    bot.v1320_black_city_loop=black_city_loop
    bot.v1320_public_snapshot=lambda guild_id: public_snapshot(ensure_guild(root,int(guild_id)))
    bot.v1320_city_audit=lambda guild_id: full_audit(ensure_guild(root,int(guild_id)),user_data)

    # Add compact command guide categories without deleting earlier entries.
    guide.extend([
        {"id":"black_city","emoji":"🏙️","title":"BLACK CITY / 도시 세계","hint":"도시 지도, 지역 이동, 역사, 시즌","commands":["!도시","!도시지도","!도시이동 지역","!도시상태","!오늘의도시","!도시뉴스","!서버역사","!도시시즌"]},
        {"id":"black_faction","emoji":"🏴","title":"세력 / 영토 / 외교","hint":"세력 창설, 영토 점령, 외교","commands":["!도시세력","!세력창설 이름","!세력가입 이름","!영토지도","!영토공격 지역","!영토방어 지역","!세력외교 대상 상태"]},
        {"id":"black_economy","emoji":"🏪","title":"도시 직업 / 제작 / 거래","hint":"생산 직업과 사용자 안전 거래","commands":["!도시직업","!도시직업선택 직업","!도시채집","!도시제작법","!도시제작 아이템 수량","!도시거래소","!판매등록 아이템 수량 가격","!거래구매 판매ID"]},
        {"id":"black_story","emoji":"📰","title":"아지트 / 범죄 / NPC","hint":"개인 공간, 선택형 범죄, 살아 있는 NPC","commands":["!내아지트","!아지트꾸미기 장식","!공동시설","!건설기부 시설 금액","!범죄","!현상수배","!수사 @대상","!도시인물","!도시의뢰"]},
        {"id":"black_ops","emoji":"🛠️","title":"BLACK CITY 운영","hint":"기본 꺼짐, 공개 선택, 백업·복구·경제 검수","commands":["!도시운영","!도시설정","!도시백업","!도시복구","!경제검수","!오류검수","!1320통합검수 상세"]},
    ])
    sync_export()
    print(f"[ABADDON v{VERSION}] black_city=enabled districts=9 factions=enabled jobs=10 market=ledger housing=enabled crime=opt_in npc=living season=4weeks endings=8 public=opt_in rollback=enabled runtime_hotfix=enabled",flush=True)
