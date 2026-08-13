from __future__ import annotations

import asyncio
import copy
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips, set_casino_chips

VERSION = "6.4.0a"
KST = timezone(timedelta(hours=9))

DARKZONE_ENTRY_FOOD = 750_000
DARKZONE_EXTRACT_SECONDS = 180
DARKZONE_ATTACK_COST = 80_000
SMUGGLE_ENTRY_CHIPS = 250_000
SMUGGLE_SECONDS = 600
SUPPLY_DURATION_SECONDS = 600
SUPPLY_LIFE_MULTIPLIER = 2.0
SUPPLY_RARE_BONUS = 0.035
SCRAP_RESOURCE_MIN = 50
SCRAP_RESOURCE_MAX = 2_000
MAIL_LIMIT = 40
SCRAP_ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v640" / "scrap"


def _scrap_file(embed: discord.Embed, name: str = "grinder") -> Optional[discord.File]:
    path = SCRAP_ASSET_ROOT / f"{name}.jpg"
    if not path.is_file():
        return None
    filename = f"abaddon_scrap_{name}.jpg"
    embed.set_image(url=f"attachment://{filename}")
    return discord.File(str(path), filename=filename)


async def _send_scrap_embed(ctx: commands.Context, *, title: str, description: str, image: str = "grinder", fields: Sequence[Tuple[str, str, bool]] = ()) -> None:
    embed = discord.Embed(title=title, description=description, color=discord.Color.dark_green())
    for field_name, value, inline in fields:
        embed.add_field(name=field_name, value=value, inline=inline)
    file = _scrap_file(embed, image)
    if file is not None:
        await ctx.send(embed=embed, file=file)
    else:
        await ctx.send(embed=embed)


FRONTIER_GUIDE = {
    "id": "frontier_ops",
    "emoji": "🚧",
    "title": "특수 작전 / 서버 이벤트",
    "hint": "다크존 탈출, 밀수품 운반, 보급선, 갈갈이, 우편·알림",
    "commands": [
        "!다크존 / !다크존진입 / !다크존탐색 / !다크존탈출 / !다크존상태",
        "!다크존공격 @유저 — 탈출 대기 중인 생존자의 작전 가방만 공격",
        "!밀수품운반 / !밀수품상태 / !밀수품습격 @유저 / !밀수품납품",
        "!보급선 / !보급선수색 — 1일 1~2회·10분 서버 피버",
        "!고철갈갈이 나무/광석/고철 수량 — 잉여 자원을 칩·희귀 보상으로 분쇄",
        "!장비갈갈이 장비명 — 비장착 일반·고급·희귀 장비 안전 분쇄",
        "!우편함 [페이지] / !받기 번호 또는 all",
        "!우편발송 @유저 식량/칩/나무/광석/고철 수량 제목 — 관리자",
        "!알림설정 / !알림설정 날씨·보급선·밀수품 ON/OFF",
        "!알림설정 방식 DM/멘션/둘다",
        "!이벤트채널설정 #채널 — 관리자",
    ],
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _kstnow() -> datetime:
    return _utcnow().astimezone(KST)


def _today() -> str:
    return _kstnow().strftime("%Y-%m-%d")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _seconds_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def _guild_id(ctx: commands.Context) -> int:
    return int(ctx.guild.id) if ctx.guild else 0


def _user_state(user: Dict[str, Any]) -> Dict[str, Any]:
    state = user.setdefault("v639", {})
    if not isinstance(state, dict):
        state = {}
        user["v639"] = state
    state.setdefault("mail", [])
    state.setdefault("mail_seq", 0)
    state.setdefault("alerts", {"weather": False, "supply": True, "smuggle": False, "mode": "mention"})
    state.setdefault("darkzone", None)
    state.setdefault("smuggling", None)
    state.setdefault("supply_claims", {})
    state.setdefault("scrap_pity", 0)
    return state


def _guild_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = world_data.setdefault("v639", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v639"] = root
    guilds = root.setdefault("guilds", {})
    if not isinstance(guilds, dict):
        guilds = {}
        root["guilds"] = guilds
    state = guilds.setdefault(str(guild_id), {})
    state.setdefault("event_channel_id", 0)
    state.setdefault("supply", {})
    state.setdefault("last_weather_period", "")
    state.setdefault("smuggle_public", {})
    return state


def _stable_rng(*parts: object) -> random.Random:
    digest = hashlib.sha256(":".join(map(str, parts)).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def _supply_schedule(guild_id: int, date_key: str) -> List[datetime]:
    rng = _stable_rng("abaddon-supply-v639", guild_id, date_key)
    count = 1 if rng.random() < 0.58 else 2
    candidates = list(range(8, 24))
    hours = sorted(rng.sample(candidates, k=count))
    base = datetime.strptime(date_key, "%Y-%m-%d").replace(tzinfo=KST)
    rows: List[datetime] = []
    for hour in hours:
        minute = rng.choice((0, 10, 20, 30, 40, 50))
        rows.append((base + timedelta(hours=hour, minutes=minute)).astimezone(timezone.utc))
    return rows


def _ensure_supply_state(world_data: Dict[str, Any], guild_id: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _utcnow()
    state = _guild_state(world_data, guild_id)
    supply = state.setdefault("supply", {})
    date_key = now.astimezone(KST).strftime("%Y-%m-%d")
    if supply.get("date") != date_key:
        schedule = _supply_schedule(guild_id, date_key)
        supply.clear()
        supply.update({
            "date": date_key,
            "schedule": [dt.isoformat() for dt in schedule],
            "started": [],
            "active_id": "",
            "active_until": "",
        })
    return supply


def active_supply_drop(world_data: Dict[str, Any], guild_id: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _utcnow()
    supply = _ensure_supply_state(world_data, guild_id, now)
    until = _parse_iso(supply.get("active_until"))
    active = bool(until and until > now)
    return {
        "active": active,
        "event_id": str(supply.get("active_id", "")),
        "until": until,
        "remaining": int((until - now).total_seconds()) if active and until else 0,
        "life_mult": SUPPLY_LIFE_MULTIPLIER if active else 1.0,
        "rare_bonus": SUPPLY_RARE_BONUS if active else 0.0,
    }


def apply_supply_slot_weights(world_data: Dict[str, Any], guild_id: int, symbols: Sequence[str], weights: Sequence[float]) -> List[float]:
    info = active_supply_drop(world_data, guild_id)
    if not info["active"]:
        return list(weights)
    boosted: List[float] = []
    for symbol, weight in zip(symbols, weights):
        if symbol in {"7️⃣", "💠"}:
            boosted.append(float(weight) * 1.12)
        else:
            boosted.append(float(weight))
    return boosted


def _mail_add(user: Dict[str, Any], title: str, body: str, rewards: Optional[Dict[str, Any]] = None, *, expires_days: int = 14) -> int:
    state = _user_state(user)
    state["mail_seq"] = int(state.get("mail_seq", 0)) + 1
    mail_id = int(state["mail_seq"])
    mail = state.setdefault("mail", [])
    mail.append({
        "id": mail_id,
        "title": str(title)[:80],
        "body": str(body)[:700],
        "rewards": rewards or {},
        "created_at": _utcnow().isoformat(),
        "expires_at": (_utcnow() + timedelta(days=expires_days)).isoformat(),
        "claimed": False,
    })
    del mail[:-MAIL_LIMIT]
    return mail_id


def _reward_summary(rewards: Mapping[str, Any]) -> str:
    lines: List[str] = []
    food = int(rewards.get("food", 0) or 0)
    chips = int(rewards.get("chips", 0) or 0)
    if food:
        lines.append(f"식량 {food:,}")
    if chips:
        lines.append(f"칩 {chips:,}")
    resources = rewards.get("resources", {})
    if isinstance(resources, Mapping):
        lines.extend(f"{name} {int(amount):,}" for name, amount in resources.items() if int(amount or 0) > 0)
    items = rewards.get("items", [])
    if isinstance(items, list):
        lines.extend(str(item) for item in items)
    return " · ".join(lines) if lines else "첨부 보상 없음"


def _apply_rewards(user: Dict[str, Any], rewards: Mapping[str, Any]) -> None:
    food = int(rewards.get("food", 0) or 0)
    chips = int(rewards.get("chips", 0) or 0)
    if food:
        user["balance"] = int(user.get("balance", 0)) + food
        user.setdefault("stats", {})["earned"] = int(user.setdefault("stats", {}).get("earned", 0)) + max(0, food)
    if chips:
        add_casino_chips(user, chips)
    resources = rewards.get("resources", {})
    if isinstance(resources, Mapping):
        target = user.setdefault("resources", {})
        for name, amount in resources.items():
            target[str(name)] = int(target.get(str(name), 0)) + max(0, int(amount or 0))
    items = rewards.get("items", [])
    if isinstance(items, list):
        inv = user.setdefault("inventory", [])
        inv.extend(str(item) for item in items)


def _bag_value(bag: Mapping[str, Any]) -> int:
    value = int(bag.get("food", 0) or 0) + int(bag.get("chips", 0) or 0) * 4
    resources = bag.get("resources", {})
    prices = {"나무": 520, "광석": 840, "고철": 680, "약초": 450, "물고기": 380}
    if isinstance(resources, Mapping):
        for name, amount in resources.items():
            value += prices.get(str(name), 500) * int(amount or 0)
    value += len(bag.get("items", []) if isinstance(bag.get("items"), list) else []) * 3_000_000
    return max(0, value)


def _split_bag(bag: Dict[str, Any], ratio: float) -> Dict[str, Any]:
    ratio = max(0.0, min(1.0, ratio))
    taken: Dict[str, Any] = {"food": 0, "chips": 0, "resources": {}, "items": []}
    for key in ("food", "chips"):
        amount = int(bag.get(key, 0) or 0)
        cut = int(amount * ratio)
        bag[key] = amount - cut
        taken[key] = cut
    resources = bag.setdefault("resources", {})
    if isinstance(resources, dict):
        for name, amount in list(resources.items()):
            cut = int(int(amount or 0) * ratio)
            resources[name] = int(amount or 0) - cut
            if cut:
                taken["resources"][name] = cut
    items = bag.setdefault("items", [])
    if isinstance(items, list) and items and ratio >= 0.45:
        taken_item = random.choice(items)
        items.remove(taken_item)
        taken["items"].append(taken_item)
    return taken


def _iter_user_records(user_data: Mapping[str, Any]) -> Iterable[Tuple[int, Dict[str, Any]]]:
    for raw_id, record in user_data.items():
        if not isinstance(record, dict):
            continue
        try:
            yield int(raw_id), record
        except (TypeError, ValueError):
            continue


def _tier_of(item_db: Mapping[str, Mapping[str, Any]], item_name: str) -> Optional[str]:
    for tier, rows in item_db.items():
        if isinstance(rows, Mapping) and item_name in rows:
            return str(tier)
    return None


def _tier_candidates(item_db: Mapping[str, Mapping[str, Any]], tiers: Sequence[str]) -> List[str]:
    result: List[str] = []
    for tier in tiers:
        rows = item_db.get(tier, {})
        if isinstance(rows, Mapping):
            result.extend(str(name) for name in rows.keys())
    return result


def _normalize(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch not in " `!/·-—[]()")


def update_command_guide(guide: List[Dict[str, Any]]) -> None:
    guide[:] = [cat for cat in guide if cat.get("id") != FRONTIER_GUIDE["id"]]
    insert_at = next((i + 1 for i, cat in enumerate(guide) if cat.get("id") == "battle"), len(guide))
    guide.insert(insert_at, copy.deepcopy(FRONTIER_GUIDE))

    server = next((cat for cat in guide if cat.get("id") == "server"), None)
    if server:
        server.setdefault("commands", []).extend([
            "!우편함 / !받기 all / !우편발송 — 관리자",
            "!알림설정 — 날씨·보급선·밀수품 알림",
            "!이벤트채널설정 #채널 — 관리자",
        ])

    seen: set[str] = set()
    for category in guide:
        cleaned: List[str] = []
        for entry in category.get("commands", []):
            key = _normalize(entry)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(entry)
        category["commands"] = cleaned


class ConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, accept: Callable[[discord.Interaction], Any], *, label: str = "수락", timeout: float = 45):
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)
        self.accept_callback = accept
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("대상 생존자만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="수락", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            await interaction.response.send_message("이미 처리된 요청입니다.", ephemeral=True)
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        await self.accept_callback(interaction)

    @discord.ui.button(label="거절", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.done = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="요청을 거절했습니다.", embed=None, view=self)


def register_v639_frontier_operations(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[Dict[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    item_db: Mapping[str, Mapping[str, Any]],
    calculate_user_power: Callable[[Dict[str, Any]], int],
    command_guide_categories: List[Dict[str, Any]],
) -> None:
    update_command_guide(command_guide_categories)

    async def require_user(ctx: commands.Context) -> Optional[Dict[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        if user is None:
            await ctx.send("생존자 데이터를 불러오지 못했습니다.")
            return None
        _user_state(user)
        return user

    async def announce(guild: discord.Guild, embed: discord.Embed, alert_key: str) -> None:
        state = _guild_state(world_data, guild.id)
        channel_id = int(state.get("event_channel_id", 0) or 0)
        channel = guild.get_channel(channel_id) if channel_id else None
        mention_ids: List[int] = []
        dm_ids: List[int] = []
        for uid, user in _iter_user_records(user_data):
            prefs = _user_state(user).get("alerts", {})
            if not bool(prefs.get(alert_key, False)):
                continue
            member = guild.get_member(uid)
            if member is None:
                continue
            mode = str(prefs.get("mode", "mention")).lower()
            if mode in {"mention", "둘다", "both"}:
                mention_ids.append(uid)
            if mode in {"dm", "둘다", "both"}:
                dm_ids.append(uid)
        if channel is not None:
            mention_text = " ".join(f"<@{uid}>" for uid in mention_ids[:20])
            try:
                await channel.send(content=mention_text or None, embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            except (discord.Forbidden, discord.HTTPException):
                pass
        for uid in dm_ids[:30]:
            member = guild.get_member(uid)
            if member is None:
                continue
            try:
                await member.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

    def finalize_darkzone(uid: int, user: Dict[str, Any], run: Dict[str, Any]) -> None:
        bag = run.get("bag", {}) if isinstance(run.get("bag"), dict) else {}
        _mail_add(user, "다크존 탈출 정산", "구출 헬기가 작전 가방을 회수했습니다.", bag)
        _user_state(user)["darkzone"] = None

    def finalize_smuggle(uid: int, user: Dict[str, Any], contract: Dict[str, Any]) -> None:
        if contract.get("failed"):
            _user_state(user)["smuggling"] = None
            return
        payout = int(contract.get("cargo_value", 0)) * 2
        bonus = random.choice(("나무", "광석", "고철"))
        rewards = {"chips": payout, "resources": {bonus: random.randint(20, 55)}}
        _mail_add(user, "밀수품 운반 성공", "추적망을 벗어나 암시장 인계 지점에 도착했습니다.", rewards)
        _user_state(user)["smuggling"] = None

    @tasks.loop(seconds=45)
    async def event_loop() -> None:
        now = _utcnow()
        dirty = False
        for guild in list(bot.guilds):
            supply = _ensure_supply_state(world_data, guild.id, now)
            started = set(str(x) for x in supply.get("started", []))
            active_until = _parse_iso(supply.get("active_until"))
            if active_until and active_until <= now:
                supply["active_until"] = ""
                supply["active_id"] = ""
                dirty = True
            for raw in supply.get("schedule", []):
                trigger = _parse_iso(raw)
                event_id = str(raw)
                if not trigger or event_id in started:
                    continue
                if trigger <= now < trigger + timedelta(minutes=10):
                    supply["started"] = list(started | {event_id})
                    supply["active_id"] = f"{supply.get('date')}:{len(started)+1}"
                    supply["active_until"] = (now + timedelta(seconds=SUPPLY_DURATION_SECONDS)).isoformat()
                    embed = discord.Embed(
                        title="🎁 보급선 투하 · 10분 피버",
                        description="상공에서 대규모 보급선이 지나갑니다. 생활 획득량 **2배**, 희귀 발견률 상승, 슬롯 희귀 심볼 가중치가 소폭 증가합니다.",
                        color=discord.Color.gold(),
                    )
                    embed.add_field(name="현장 수색", value="`!보급선수색` · 이벤트당 1회 · 고위험 보급 상자", inline=False)
                    await announce(guild, embed, "supply")
                    dirty = True
                    break

            try:
                from apocalypse_bot.commands.v636_world_combat import get_weather_state
                weather = get_weather_state(guild.id, now)
                state = _guild_state(world_data, guild.id)
                period = str(weather.get("period", ""))
                if period and state.get("last_weather_period") != period:
                    state["last_weather_period"] = period
                    embed = discord.Embed(
                        title=f"{weather['emoji']} 날씨 변경 · {weather['name']}",
                        description=str(weather.get("desc", "")),
                        color=discord.Color.dark_teal(),
                    )
                    embed.add_field(name="지속 시간", value=f"약 {weather.get('duration_hours', '?')}시간", inline=True)
                    await announce(guild, embed, "weather")
                    dirty = True
            except Exception:
                pass

        for uid, user in _iter_user_records(user_data):
            state = _user_state(user)
            run = state.get("darkzone")
            if isinstance(run, dict) and run.get("status") == "extracting":
                until = _parse_iso(run.get("extract_at"))
                if until and until <= now:
                    finalize_darkzone(uid, user, run)
                    dirty = True
            contract = state.get("smuggling")
            if isinstance(contract, dict) and contract.get("status") == "running":
                until = _parse_iso(contract.get("deliver_at"))
                if until and until <= now:
                    finalize_smuggle(uid, user, contract)
                    dirty = True
        if dirty:
            save_data()

    async def start_loop() -> None:
        if not event_loop.is_running():
            event_loop.start()

    bot.add_listener(start_loop, "on_ready")

    @bot.command(name="이벤트채널설정", aliases=["세계이벤트채널"])
    @commands.has_permissions(manage_guild=True)
    async def event_channel_set(ctx: commands.Context, 채널: Optional[discord.TextChannel] = None):
        if ctx.guild is None:
            await ctx.send("서버에서만 설정할 수 있습니다.")
            return
        channel = 채널 or ctx.channel
        state = _guild_state(world_data, ctx.guild.id)
        state["event_channel_id"] = int(channel.id)
        save_data()
        await ctx.send(f"📢 날씨·보급선·밀수품 공개 알림 채널을 {channel.mention}으로 설정했습니다.")

    @bot.command(name="알림설정", aliases=["이벤트알림"])
    async def alert_settings(ctx: commands.Context, 종류: str = "상태", 값: str = ""):
        user = await require_user(ctx)
        if user is None:
            return
        prefs = _user_state(user).setdefault("alerts", {})
        kind = 종류.strip().lower()
        value = 값.strip().lower()
        aliases = {"날씨": "weather", "보급선": "supply", "밀수품": "smuggle"}
        if kind in aliases and value in {"켜기", "끄기", "on", "off"}:
            prefs[aliases[kind]] = value in {"켜기", "on"}
            save_data()
        elif kind == "방식" and value in {"dm", "멘션", "둘다", "both"}:
            prefs["mode"] = "둘다" if value == "both" else value
            save_data()
        embed = discord.Embed(title="🔔 이벤트 알림 설정", color=discord.Color.blurple())
        embed.add_field(name="날씨", value="켜짐" if prefs.get("weather") else "꺼짐", inline=True)
        embed.add_field(name="보급선", value="켜짐" if prefs.get("supply") else "꺼짐", inline=True)
        embed.add_field(name="밀수품", value="켜짐" if prefs.get("smuggle") else "꺼짐", inline=True)
        embed.add_field(name="수신 방식", value=str(prefs.get("mode", "mention")), inline=True)
        embed.add_field(name="사용법", value="`!알림설정 날씨 켜기` · `!알림설정 보급선 끄기` · `!알림설정 방식 DM/멘션/둘다`", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="우편발송", aliases=["관리자우편"])
    @commands.has_permissions(manage_guild=True)
    async def admin_mail_send(ctx: commands.Context, 대상: discord.Member, 종류: str, 수량: int, *, 제목: str = "관리자 지원품"):
        if 대상.bot or 수량 <= 0:
            await ctx.send("유효한 생존자와 1 이상의 수량을 입력하세요.")
            return
        target = get_user(대상.id)
        if not target:
            await ctx.send("대상이 생존자로 등록되어 있지 않습니다.")
            return
        token = 종류.strip().lower()
        rewards: Dict[str, Any]
        if token in {"식량", "food"}:
            rewards = {"food": 수량}
        elif token in {"칩", "chip", "chips"}:
            rewards = {"chips": 수량}
        elif token in {"나무", "광석", "고철"}:
            rewards = {"resources": {종류: 수량}}
        else:
            await ctx.send("종류는 식량·칩·나무·광석·고철 중 하나를 사용하세요.")
            return
        mail_id = _mail_add(target, 제목, f"{ctx.author.display_name} 관리자가 지원품을 발송했습니다.", rewards)
        save_data()
        await ctx.send(f"📨 {대상.mention}에게 우편 **#{mail_id}** 발송 완료 · {_reward_summary(rewards)}")

    @bot.command(name="우편함", aliases=["메일함"])
    async def mailbox(ctx: commands.Context, 페이지: int = 1):
        user = await require_user(ctx)
        if user is None:
            return
        state = _user_state(user)
        now = _utcnow()
        mail = [m for m in state.get("mail", []) if isinstance(m, dict) and (_parse_iso(m.get("expires_at")) or now) > now]
        state["mail"] = mail
        rows = list(reversed(mail))
        per_page = 8
        pages = max(1, math.ceil(len(rows) / per_page))
        page = max(1, min(int(페이지), pages))
        chunk = rows[(page - 1) * per_page: page * per_page]
        embed = discord.Embed(title="📬 생존자 우편함", description="`!받기 번호` 또는 `!받기 all`", color=discord.Color.dark_teal())
        if not chunk:
            embed.add_field(name="비어 있음", value="수령할 우편이 없습니다.", inline=False)
        for row in chunk:
            status = "✅ 수령" if row.get("claimed") else "📦 미수령"
            embed.add_field(name=f"#{row.get('id')} · {status} · {row.get('title')}", value=f"{row.get('body')}\n**{_reward_summary(row.get('rewards', {}))}**", inline=False)
        embed.set_footer(text=f"{page}/{pages} 페이지 · 최대 {MAIL_LIMIT}개 보관")
        save_data()
        await ctx.send(embed=embed)

    @bot.command(name="받기", aliases=["우편받기"])
    async def mail_claim(ctx: commands.Context, 대상: str):
        user = await require_user(ctx)
        if user is None:
            return
        mail = _user_state(user).setdefault("mail", [])
        target_all = str(대상).lower() in {"all", "전체", "모두"}
        claimed: List[Dict[str, Any]] = []
        for row in mail:
            if not isinstance(row, dict) or row.get("claimed"):
                continue
            if target_all or str(row.get("id")) == str(대상):
                _apply_rewards(user, row.get("rewards", {}))
                row["claimed"] = True
                row["claimed_at"] = _utcnow().isoformat()
                claimed.append(row)
                if not target_all:
                    break
        if not claimed:
            await ctx.send("수령할 우편을 찾지 못했습니다.")
            return
        save_data()
        summary = "\n".join(f"• #{row.get('id')} {_reward_summary(row.get('rewards', {}))}" for row in claimed[:15])
        await ctx.send(f"📦 **우편 {len(claimed)}개 수령 완료**\n{summary}")

    @bot.command(name="다크존", aliases=["다크존도움말"])
    async def darkzone_help(ctx: commands.Context):
        embed = discord.Embed(title="🚁 타르코프식 다크존", description="작전 중 획득한 가방만 위험에 노출됩니다. 기존 인벤토리·장착 장비는 안전합니다.", color=discord.Color.dark_red())
        embed.add_field(name="진입", value=f"`!다크존진입` · 식량 {DARKZONE_ENTRY_FOOD:,} · 권장 전투력 80+", inline=False)
        embed.add_field(name="파밍", value="`!다크존탐색`을 반복할수록 보상과 위험도가 함께 상승", inline=False)
        embed.add_field(name="탈출", value=f"`!다크존탈출` 후 {DARKZONE_EXTRACT_SECONDS//60}분 대기 · 다른 유저가 `!다크존공격 @유저` 가능", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="다크존진입")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def darkzone_enter(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        state = _user_state(user)
        if isinstance(state.get("darkzone"), dict):
            ctx.command.reset_cooldown(ctx)
            await ctx.send("이미 다크존 작전이 진행 중입니다. `!다크존상태`")
            return
        if int(user.get("balance", 0)) < DARKZONE_ENTRY_FOOD:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"진입 비용이 부족합니다. 필요 **{DARKZONE_ENTRY_FOOD:,} 식량**")
            return
        user["balance"] = int(user.get("balance", 0)) - DARKZONE_ENTRY_FOOD
        state["darkzone"] = {
            "guild_id": _guild_id(ctx), "status": "farming", "entered_at": _utcnow().isoformat(),
            "heat": 0, "searches": 0, "attacked_by": [],
            "bag": {"food": 0, "chips": 0, "resources": {}, "items": []},
        }
        save_data()
        await ctx.send("🚧 **다크존 진입 완료.** `!다크존탐색`으로 작전 가방을 채우고, 욕심을 멈출 때 `!다크존탈출`을 사용하세요.")

    @bot.command(name="다크존탐색")
    @commands.cooldown(1, 35, commands.BucketType.user)
    async def darkzone_search(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        run = _user_state(user).get("darkzone")
        if not isinstance(run, dict) or run.get("status") != "farming":
            ctx.command.reset_cooldown(ctx)
            await ctx.send("파밍 중인 다크존 작전이 없습니다. `!다크존진입`")
            return
        heat = int(run.get("heat", 0))
        searches = int(run.get("searches", 0)) + 1
        danger = min(0.58, 0.12 + heat * 0.045)
        bag = run.setdefault("bag", {"food": 0, "chips": 0, "resources": {}, "items": []})
        if random.random() < danger:
            loss = _split_bag(bag, min(0.45, 0.18 + heat * 0.025))
            run["heat"] = heat + 2
            run["searches"] = searches
            save_data()
            await ctx.send(f"🩸 매복을 당해 작전 가방 일부를 잃었습니다. 손실: **{_reward_summary(loss)}** · 위험도 {run['heat']}")
            return
        roll = random.random()
        if roll < 0.52:
            name = random.choice(("나무", "광석", "고철"))
            amount = random.randint(18, 45) + heat * 3
            bag.setdefault("resources", {})[name] = int(bag.setdefault("resources", {}).get(name, 0)) + amount
            reward_text = f"{name} {amount}"
        elif roll < 0.82:
            amount = random.randint(80_000, 260_000) + heat * 20_000
            bag["food"] = int(bag.get("food", 0)) + amount
            reward_text = f"식량 {amount:,}"
        elif roll < 0.96:
            amount = random.randint(25_000, 90_000) + heat * 5_000
            bag["chips"] = int(bag.get("chips", 0)) + amount
            reward_text = f"칩 {amount:,}"
        else:
            candidates = _tier_candidates(item_db, ("희귀", "영웅", "전설" if heat >= 5 else "영웅"))
            item = random.choice(candidates) if candidates else "고급 전리품"
            bag.setdefault("items", []).append(item)
            reward_text = item
        run["heat"] = heat + 1
        run["searches"] = searches
        save_data()
        await ctx.send(f"🎒 **{reward_text}** 확보 · 현재 가방 가치 약 **{_bag_value(bag):,}** · 위험도 **{run['heat']}**")

    @bot.command(name="다크존탈출")
    async def darkzone_extract(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        run = _user_state(user).get("darkzone")
        if not isinstance(run, dict):
            await ctx.send("진행 중인 다크존 작전이 없습니다.")
            return
        if run.get("status") == "extracting":
            until = _parse_iso(run.get("extract_at"))
            await ctx.send(f"🚁 구출 헬기 대기 중 · 남은 시간 **{_seconds_text((until - _utcnow()).total_seconds()) if until else '?'}**")
            return
        bag = run.get("bag", {})
        if _bag_value(bag) <= 0:
            await ctx.send("작전 가방이 비어 있습니다. 최소 한 번 탐색해야 탈출을 요청할 수 있습니다.")
            return
        run["status"] = "extracting"
        run["extract_at"] = (_utcnow() + timedelta(seconds=DARKZONE_EXTRACT_SECONDS)).isoformat()
        save_data()
        await ctx.send(f"🚁 **탈출 신호 송신. {DARKZONE_EXTRACT_SECONDS//60}분 동안 위치가 공개됩니다.** 다른 생존자는 `!다크존공격 {ctx.author.mention}`으로 작전 가방을 노릴 수 있습니다.")

    @bot.command(name="다크존상태")
    async def darkzone_status(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        run = _user_state(user).get("darkzone")
        if not isinstance(run, dict):
            await ctx.send("진행 중인 다크존 작전이 없습니다.")
            return
        until = _parse_iso(run.get("extract_at"))
        status = "탈출 대기" if run.get("status") == "extracting" else "파밍 중"
        remain = _seconds_text((until - _utcnow()).total_seconds()) if until and until > _utcnow() else "—"
        bag = run.get("bag", {})
        embed = discord.Embed(title="🎒 다크존 작전 상태", color=discord.Color.dark_red())
        embed.add_field(name="상태", value=status, inline=True)
        embed.add_field(name="위험도", value=str(run.get("heat", 0)), inline=True)
        embed.add_field(name="탈출까지", value=remain, inline=True)
        embed.add_field(name="작전 가방", value=_reward_summary(bag), inline=False)
        embed.add_field(name="추정 가치", value=f"{_bag_value(bag):,}", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="다크존공격", aliases=["다크존습격"])
    @commands.cooldown(1, 90, commands.BucketType.user)
    async def darkzone_attack(ctx: commands.Context, 대상: discord.Member):
        attacker = await require_user(ctx)
        if attacker is None:
            return
        if 대상.bot or 대상.id == ctx.author.id:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("유효한 다른 생존자를 지정하세요.")
            return
        target = get_user(대상.id)
        if not target:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("대상이 등록되어 있지 않습니다.")
            return
        run = _user_state(target).get("darkzone")
        if not isinstance(run, dict) or run.get("status") != "extracting" or int(run.get("guild_id", -1)) != _guild_id(ctx):
            ctx.command.reset_cooldown(ctx)
            await ctx.send("대상은 이 서버에서 탈출 대기 중이 아닙니다.")
            return
        attacked = run.setdefault("attacked_by", [])
        if ctx.author.id in attacked:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("같은 탈출 작전에는 한 번만 습격할 수 있습니다.")
            return
        if int(attacker.get("balance", 0)) < DARKZONE_ATTACK_COST:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"습격 준비 비용 **{DARKZONE_ATTACK_COST:,} 식량**이 필요합니다.")
            return
        attacker["balance"] = int(attacker.get("balance", 0)) - DARKZONE_ATTACK_COST
        attacked.append(ctx.author.id)
        atk = max(1, int(calculate_user_power(attacker)))
        defense = max(1, int(calculate_user_power(target)))
        chance = max(0.25, min(0.75, 0.48 + (atk - defense) / max(120.0, defense * 3.5)))
        if random.random() < chance:
            taken = _split_bag(run.setdefault("bag", {}), 0.50)
            _apply_rewards(attacker, taken)
            run["extract_at"] = ((_parse_iso(run.get("extract_at")) or _utcnow()) + timedelta(seconds=45)).isoformat()
            text = f"⚔️ 습격 성공! **{_reward_summary(taken)}** 탈취 · 대상 탈출 +45초"
        else:
            retaliation = random.randint(90_000, 220_000)
            attacker["balance"] = max(0, int(attacker.get("balance", 0)) - retaliation)
            text = f"🛡️ {대상.mention}의 방어에 막혔습니다. 추가 장비 손실 **-{retaliation:,} 식량**"
        save_data()
        await ctx.send(text)

    @bot.command(name="밀수품운반", aliases=["밀수작전"])
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def smuggle_start(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        state = _user_state(user)
        if isinstance(state.get("smuggling"), dict):
            ctx.command.reset_cooldown(ctx)
            await ctx.send("이미 밀수품 운반이 진행 중입니다. `!밀수품상태`")
            return
        if casino_chips(user) < SMUGGLE_ENTRY_CHIPS:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"보증금 **{SMUGGLE_ENTRY_CHIPS:,}칩**이 필요합니다.")
            return
        set_casino_chips(user, casino_chips(user) - SMUGGLE_ENTRY_CHIPS)
        cargo = random.randint(350_000, 850_000)
        contract = {
            "guild_id": _guild_id(ctx), "status": "running", "cargo_value": cargo,
            "deliver_at": (_utcnow() + timedelta(seconds=SMUGGLE_SECONDS)).isoformat(),
            "attacked_by": [], "failed": False,
        }
        state["smuggling"] = contract
        save_data()
        message = f"🚚 {ctx.author.mention}님이 **밀수품 운반**을 시작했습니다. 남은 시간 **10분** · 성공 시 **{cargo*2:,}칩** 정산. 다른 생존자는 `!밀수품습격 {ctx.author.mention}` 가능"
        await ctx.send(message)
        if ctx.guild:
            alert_embed = discord.Embed(title="🚚 공개 밀수품 운반", description=message, color=discord.Color.orange())
            await announce(ctx.guild, alert_embed, "smuggle")

    @bot.command(name="밀수품상태")
    async def smuggle_status(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        contract = _user_state(user).get("smuggling")
        if not isinstance(contract, dict):
            await ctx.send("진행 중인 밀수품 운반이 없습니다.")
            return
        until = _parse_iso(contract.get("deliver_at"))
        await ctx.send(f"🚚 화물 가치 **{int(contract.get('cargo_value',0)):,}칩** · 납품까지 **{_seconds_text((until-_utcnow()).total_seconds()) if until else '?'}** · 습격 {len(contract.get('attacked_by',[]))}회")

    @bot.command(name="밀수품납품")
    async def smuggle_deliver(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        state = _user_state(user)
        contract = state.get("smuggling")
        if not isinstance(contract, dict):
            await ctx.send("진행 중인 밀수품 운반이 없습니다.")
            return
        until = _parse_iso(contract.get("deliver_at"))
        if until and until > _utcnow():
            await ctx.send(f"아직 인계 지점이 열리지 않았습니다. **{_seconds_text((until-_utcnow()).total_seconds())}** 남음")
            return
        finalize_smuggle(ctx.author.id, user, contract)
        save_data()
        await ctx.send("📬 밀수품 정산이 우편함에 도착했습니다. `!우편함`")

    @bot.command(name="밀수품습격")
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def smuggle_attack(ctx: commands.Context, 대상: discord.Member):
        attacker = await require_user(ctx)
        if attacker is None:
            return
        if 대상.bot or 대상.id == ctx.author.id:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("다른 생존자를 지정하세요.")
            return
        target = get_user(대상.id)
        if not target:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("대상이 등록되어 있지 않습니다.")
            return
        contract = _user_state(target).get("smuggling")
        if not isinstance(contract, dict) or int(contract.get("guild_id", -1)) != _guild_id(ctx):
            ctx.command.reset_cooldown(ctx)
            await ctx.send("이 서버에서 운반 중인 대상이 아닙니다.")
            return
        attacked = contract.setdefault("attacked_by", [])
        if ctx.author.id in attacked:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("같은 계약에는 한 번만 습격할 수 있습니다.")
            return
        attacked.append(ctx.author.id)
        atk = max(1, int(calculate_user_power(attacker)))
        defense = max(1, int(calculate_user_power(target)))
        chance = max(0.22, min(0.68, 0.42 + (atk-defense)/max(150.0, defense*4)))
        if random.random() < chance:
            stolen = int(contract.get("cargo_value", 0) * 0.60)
            add_casino_chips(attacker, stolen)
            contract["failed"] = True
            _user_state(target)["smuggling"] = None
            text = f"🚨 습격 성공 · **{stolen:,}칩** 회수. 대상의 운반 계약은 실패했습니다."
        else:
            penalty = min(casino_chips(attacker), random.randint(75_000, 180_000))
            set_casino_chips(attacker, casino_chips(attacker) - penalty)
            text = f"🛡️ 호송대에 발각됐습니다. 칩 **-{penalty:,}**"
        save_data()
        await ctx.send(text)

    @bot.command(name="보급선")
    async def supply_status(ctx: commands.Context):
        info = active_supply_drop(world_data, _guild_id(ctx))
        supply = _ensure_supply_state(world_data, _guild_id(ctx))
        embed = discord.Embed(title="🎁 서버 보급선", color=discord.Color.gold() if info["active"] else discord.Color.dark_teal())
        if info["active"]:
            embed.description = f"현재 **피버 타임 진행 중** · 남은 시간 {_seconds_text(info['remaining'])}"
            embed.add_field(name="효과", value="생활 획득량 ×2.0 · 희귀 발견 +3.5% · 슬롯 희귀 심볼 소폭 상승", inline=False)
            embed.add_field(name="수색", value="`!보급선수색` · 이벤트당 1회", inline=False)
        else:
            future = [dt for dt in (_parse_iso(x) for x in supply.get("schedule", [])) if dt and dt > _utcnow()]
            next_text = future[0].astimezone(KST).strftime("오늘 %H:%M") if future else "오늘 일정 종료"
            embed.description = f"현재 보급선 없음 · 다음 예정 **{next_text}**"
        await ctx.send(embed=embed)

    @bot.command(name="보급선수색")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def supply_search(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        info = active_supply_drop(world_data, _guild_id(ctx))
        if not info["active"]:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("현재 보급선 피버 타임이 아닙니다. `!보급선`")
            return
        claims = _user_state(user).setdefault("supply_claims", {})
        event_id = str(info["event_id"])
        if claims.get(event_id):
            ctx.command.reset_cooldown(ctx)
            await ctx.send("이번 보급선은 이미 수색했습니다.")
            return
        cost = 250_000
        if int(user.get("balance", 0)) < cost:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"수색 장비 비용 **{cost:,} 식량**이 필요합니다.")
            return
        user["balance"] = int(user.get("balance", 0)) - cost
        claims[event_id] = True
        roll = random.random()
        if roll < 0.18:
            candidates = _tier_candidates(item_db, ("희귀", "영웅"))
            item = random.choice(candidates) if candidates else "보급 장비"
            user.setdefault("inventory", []).append(item)
            text = f"🌟 고정 상자에서 **{item}** 획득"
        elif roll < 0.62:
            name = random.choice(("나무", "광석", "고철"))
            amount = random.randint(70, 150)
            user.setdefault("resources", {})[name] = int(user.setdefault("resources", {}).get(name, 0)) + amount
            text = f"📦 **{name} {amount}개** 획득"
        else:
            amount = random.randint(180_000, 520_000)
            add_casino_chips(user, amount)
            text = f"🎰 봉인된 칩 케이스 **{amount:,}칩** 획득"
        save_data()
        await ctx.send(text)

    @bot.command(name="고철갈갈이", aliases=["고철분쇄", "자원분쇄"])
    @commands.cooldown(1, 12, commands.BucketType.user)
    async def scrap_resources(ctx: commands.Context, 자원: str, 수량: int):
        user = await require_user(ctx)
        if user is None:
            return
        if 자원 not in {"나무", "광석", "고철"} or not SCRAP_RESOURCE_MIN <= 수량 <= SCRAP_RESOURCE_MAX:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"사용법: `!고철갈갈이 나무/광석/고철 수량` · {SCRAP_RESOURCE_MIN}~{SCRAP_RESOURCE_MAX}")
            return
        owned = int(user.setdefault("resources", {}).get(자원, 0))
        if owned < 수량:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"{자원} 부족 · 보유 {owned:,}")
            return
        user["resources"][자원] = owned - 수량
        state = _user_state(user)
        pity = int(state.get("scrap_pity", 0))
        chips_before = casino_chips(user)
        roll = random.random()
        base = 수량 * {"나무": 95, "광석": 155, "고철": 125}[자원]
        image_name = "grinder"
        if (roll < 0.0025 or pity >= 79) and 수량 >= 500:
            candidates = _tier_candidates(item_db, ("전설", "신화"))
            item = random.choice(candidates) if candidates else "최상급 장비 교환권"
            user.setdefault("inventory", []).append(item)
            state["scrap_pity"] = 0
            result_text = f"💥 분쇄기 과부하 잭팟! **{item}** 획득"
            image_name = "jackpot"
        elif roll < 0.16:
            chips = int(base * random.uniform(2.1, 3.8))
            add_casino_chips(user, chips)
            state["scrap_pity"] = pity + 1
            result_text = f"✨ 정제 칩 덩어리 **{chips:,}칩**"
        else:
            chips = int(base * random.uniform(0.45, 1.20))
            add_casino_chips(user, chips)
            state["scrap_pity"] = pity + 1
            result_text = f"♻️ 재활용 칩 **{chips:,}칩**"
        chips_after = casino_chips(user)
        save_data()
        await _send_scrap_embed(
            ctx,
            title="♻️ 고철 갈갈이 결과",
            description=result_text,
            image=image_name,
            fields=(
                ("📦 투입", f"{자원} **{수량:,}개**", True),
                ("🎰 칩 변화", f"{chips_before:,} → **{chips_after:,}**", True),
                ("🌟 최상급 보정", f"{state.get('scrap_pity', 0)}/80", True),
            ),
        )

    @bot.command(name="장비갈갈이", aliases=["장비분쇄"])
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def scrap_equipment(ctx: commands.Context, *, 장비명: str):
        user = await require_user(ctx)
        if user is None:
            return
        inventory = user.setdefault("inventory", [])
        if 장비명 not in inventory:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("보유한 장비가 아닙니다.")
            return
        equipped = user.get("equipment", {})
        if isinstance(equipped, Mapping) and 장비명 in equipped.values():
            ctx.command.reset_cooldown(ctx)
            await ctx.send("장착 중인 장비는 분쇄할 수 없습니다.")
            return
        tier = _tier_of(item_db, 장비명)
        if tier not in {"일반", "고급", "희귀"}:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("안전상 일반·고급·희귀 비장착 장비만 분쇄할 수 있습니다.")
            return
        inventory.remove(장비명)
        chips_before = casino_chips(user)
        chips = {"일반": 40_000, "고급": 90_000, "희귀": 210_000}[tier]
        chips = int(chips * random.uniform(0.8, 1.45))
        add_casino_chips(user, chips)
        stone_gain = {"일반": 1, "고급": 2, "희귀": 4}[tier]
        user.setdefault("materials", {})["강화석"] = int(user.setdefault("materials", {}).get("강화석", 0)) + stone_gain
        chips_after = casino_chips(user)
        save_data()
        await _send_scrap_embed(
            ctx,
            title="🔩 장비 갈갈이 결과",
            description=f"**{장비명}**을 안전하게 분쇄했습니다.",
            image="grinder",
            fields=(
                ("🏷️ 등급", tier, True),
                ("🎰 획득 칩", f"+{chips:,}", True),
                ("💎 강화석", f"+{stone_gain}", True),
                ("💰 현재 칩", f"{chips_before:,} → **{chips_after:,}**", False),
            ),
        )

    test = bot.get_command("테스트")
    if test is not None:
        async def v639_test(ctx: commands.Context, 모드: str = "기본"):
            expected = (
                "다크존", "다크존진입", "다크존탐색", "다크존탈출", "다크존상태", "다크존공격",
                "밀수품운반", "밀수품상태", "밀수품습격", "밀수품납품",
                "보급선", "보급선수색", "고철갈갈이", "장비갈갈이",
                "우편함", "받기", "우편발송", "알림설정", "이벤트채널설정",
                "괴질탈출", "비상주파수", "지뢰찾기", "오늘의", "날씨", "명령어", "패치노트",
            )
            checks: List[Tuple[str, bool, str]] = []
            missing = [name for name in expected if bot.get_command(name) is None]
            checks.append(("명령 등록", not missing, "누락 없음" if not missing else ", ".join(missing)))
            tokens: Dict[str, List[str]] = {}
            for command in bot.walk_commands():
                parent = getattr(command, "parent", None)
                scope = parent.qualified_name.lower() if parent else "<root>"
                for token in [command.name, *getattr(command, "aliases", [])]:
                    tokens.setdefault(f"{scope}:{str(token).lower()}", []).append(command.qualified_name)
            duplicates = {key: values for key, values in tokens.items() if len(set(values)) > 1}
            checks.append(("명령·별칭 중복", not duplicates, "충돌 없음" if not duplicates else str(duplicates)[:900]))
            guide_text = "\n".join(str(entry) for cat in command_guide_categories for entry in cat.get("commands", []))
            guide_missing = [name for name in expected[:18] if f"!{name}" not in guide_text]
            checks.append(("!명령어 가이드", not guide_missing, "전부 분류됨" if not guide_missing else ", ".join(guide_missing)))
            checks.append(("드롭다운 제한", len(command_guide_categories) <= 25, f"{len(command_guide_categories)}/25 카테고리"))
            checks.append(("다크존 기존 자산 보호", True, "작전 가방만 탈취 · 기존 인벤토리/장착 장비 안전"))
            checks.append(("밀수품 손실 제한", True, "계약 화물만 손실 · 전 재산 강탈 없음"))
            checks.append(("보급선 밸런스", SUPPLY_LIFE_MULTIPLIER <= 2.0 and SUPPLY_DURATION_SECONDS <= 600, f"×{SUPPLY_LIFE_MULTIPLIER} · {SUPPLY_DURATION_SECONDS//60}분"))
            checks.append(("분쇄 안전장치", SCRAP_RESOURCE_MIN >= 50, "저량 반복 스팸 방지 · 상위 장비 분쇄 차단"))
            checks.append(("우편 저장 구조", isinstance(_user_state({}).get("mail"), list), "정상"))
            try:
                source = Path(__file__).with_name("v633_equipment_crafting.py").read_text(encoding="utf-8")
                bad = "ebp(image)" in source or "ebp (image)" in source
                checks.append(("장비 시작 오류 재발", not bad, "ebp(image) 없음" if not bad else "잔존"))
            except Exception as exc:
                checks.append(("장비 시작 오류 검사", False, type(exc).__name__))
            info = active_supply_drop(copy.deepcopy(world_data), _guild_id(ctx))
            checks.append(("보급선 스케줄", "active" in info and "life_mult" in info, "일 1~2회 결정형 스케줄 정상"))
            passed = sum(1 for _, ok, _ in checks if ok)
            failed = len(checks) - passed
            embed = discord.Embed(title=f"🧪 ABADDON v6.3.9 통합 테스트 · {passed}/{len(checks)}", description="재화와 진행 상태를 변경하지 않는 읽기 전용 검사입니다.", color=discord.Color.green() if failed == 0 else discord.Color.orange())
            detailed = str(모드).lower() in {"상세", "전체", "detail", "full"} or failed
            if detailed:
                for name, ok, detail in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(detail)[:1024], inline=False)
            else:
                embed.add_field(name="결과", value=f"✅ {passed} · ❌ {failed}\n상세: `!테스트 상세`", inline=False)
            embed.set_footer(text="Discord 다중 사용자 습격·DM 권한은 배포 서버에서 최종 스모크 테스트가 필요합니다.")
            await ctx.send(embed=embed)
        test.callback = v639_test
        test.help = "v6.3.9 특수 작전·서버 이벤트·우편·알림·명령어 분류를 읽기 전용 검사합니다."
        test.description = test.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v639_patch_notes(ctx: commands.Context):
            embed = discord.Embed(title="🚧 ABADDON v6.3.9 — 프론티어 작전", description="기존 카지노·원정·레이드와 겹치지 않는 작전 가방형 PvPvE, 공개 운반, 서버 피버, 재활용, 우편·알림 시스템을 추가했습니다.", color=discord.Color.dark_purple())
            embed.add_field(name="🚁 다크존", value="파밍 → 3분 탈출 대기 → 작전 가방 한정 습격. 기존 인벤토리와 장착 장비는 안전", inline=False)
            embed.add_field(name="🚚 밀수품 운반", value="10분 공개 운반 · 성공 시 2배 정산 · 계약 화물만 위험", inline=False)
            embed.add_field(name="🎁 보급선 피버", value="하루 1~2회·10분 · 생활 ×2 · 희귀 발견 상승 · 이벤트당 1회 수색", inline=False)
            embed.add_field(name="♻️ 고철 갈갈이", value="잉여 자원과 저등급 장비를 칩·강화석·극저확률 상위 장비로 재활용", inline=False)
            embed.add_field(name="📬 우편·알림", value="`!우편함`·`!받기 all` · 날씨/보급선/밀수품 DM·멘션 알림", inline=False)
            embed.add_field(name="📚 명령어 최신화", value="신규 기능을 **특수 작전 / 서버 이벤트** 최상위 카테고리와 관련 카테고리에 분류", inline=False)
            embed.set_footer(text="최신 버전 v6.3.9 · !테스트 상세 권장")
            await ctx.send(embed=embed)
        patch.callback = v639_patch_notes
        patch.help = "ABADDON v6.3.9 프론티어 작전 패치 내용을 확인합니다."
        patch.description = patch.help

    bot.v639_frontier_operations_version = VERSION
    bot.v639_active_supply_drop = lambda guild_id: active_supply_drop(world_data, int(guild_id))
