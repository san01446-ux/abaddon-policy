from __future__ import annotations

import asyncio
import copy
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import aiohttp
import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import (
    add_casino_chips,
    casino_chips,
    set_casino_chips,
)

VERSION = "6.3.8"
KST = timezone(timedelta(hours=9))

MIN_CHIP_BET = 10_000
MAX_CHIP_BET = 50_000_000
CRATE_COST = 5_000_000
BIO_PREP_COST = 20_000_000

MUTANTS: Tuple[Tuple[str, str, float], ...] = (
    ("다리 잘린 좀비", "🧟", 5.5),
    ("광폭화 털개", "🐕", 4.6),
    ("중무장 생존자", "🪖", 4.1),
    ("산성 포자충", "🍄", 5.0),
    ("철갑 돌연변이", "🦏", 3.8),
)

NEW_GUIDE_CATEGORY = {
    "id": "hardcore_arcade",
    "emoji": "☠️",
    "title": "하드코어 생존 / 미니게임",
    "hint": "고난도 칩 게임, 협동 금고, 결투, 위험 이벤트",
    "commands": [
        "!괴질탈출 배팅액 / !크래시 배팅액",
        "!비상주파수 배팅액",
        "!지뢰찾기 지뢰수 배팅액",
        "!돌연변이경주 / !돌연변이배팅 번호 배팅액",
        "!오염문",
        "!비상보급상자",
        "!선물거래 상승/하락 배팅액 레버리지",
        "!괴수투기장 @유저 배팅액",
        "!영혼결투 @유저 배팅액",
        "!벙커개설 참가비 / !벙커참가 / !벙커투표 @유저 / !벙커진행 / !벙커상태",
        "!금고개설 참가비 / !금고참가 / !금고시작",
        "!하이에나",
        "!생물테러준비 / !생물테러수신 ON/OFF / !생물테러 @유저",
    ],
}




async def _safe_interaction_edit(interaction: discord.Interaction, **kwargs: Any) -> Any:
    """Component edit with one retry for Render/Discord transient connection resets."""
    transient = (discord.HTTPException, aiohttp.ClientError, ConnectionResetError, OSError)
    try:
        if interaction.response.is_done():
            return await interaction.edit_original_response(**kwargs)
        return await interaction.response.edit_message(**kwargs)
    except transient:
        await asyncio.sleep(0.8)
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            return await interaction.edit_original_response(**kwargs)
        except transient:
            # The game state is already saved. Do not crash the View task because Discord reset the socket.
            return None


def _emoji_progress(current: float, maximum: float, width: int = 10, filled: str = "🟩", empty: str = "⬛") -> str:
    ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, float(current) / float(maximum)))
    count = max(0, min(width, int(round(ratio * width))))
    return filled * count + empty * (width - count)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().astimezone(KST).strftime("%Y-%m-%d")


def _week_key() -> str:
    dt = _now().astimezone(KST)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _guild_id(ctx: commands.Context) -> int:
    return int(ctx.guild.id) if ctx.guild else 0


def _state(user: Dict[str, Any]) -> Dict[str, Any]:
    state = user.setdefault("v638", {})
    if not isinstance(state, dict):
        state = {}
        user["v638"] = state
    state.setdefault("crate_daily", {})
    state.setdefault("crate_pity", 0)
    state.setdefault("futures_daily", {})
    state.setdefault("hyena_last", "")
    state.setdefault("bio_opt_in", False)
    state.setdefault("bio_kits", 0)
    state.setdefault("bio_last_prep", "")
    state.setdefault("bio_immunity_until", "")
    state.setdefault("pet_injured_until", "")
    state.setdefault("soul_wound_until", "")
    return state


def _world_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = world_data.setdefault("v638", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v638"] = root
    guilds = root.setdefault("guilds", {})
    if not isinstance(guilds, dict):
        guilds = {}
        root["guilds"] = guilds
    state = guilds.setdefault(str(guild_id), {})
    state.setdefault("grave_pool", [])
    state.setdefault("crate_week", _week_key())
    state.setdefault("crate_legendaries_left", 3)
    state.setdefault("market_index", 100.0)
    return state


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def _validate_bet(value: int) -> Optional[str]:
    if value < MIN_CHIP_BET:
        return f"최소 배팅은 **{MIN_CHIP_BET:,}칩**입니다."
    if value > MAX_CHIP_BET:
        return f"최대 배팅은 **{MAX_CHIP_BET:,}칩**입니다."
    return None


def _take_chips(user: Dict[str, Any], amount: int) -> bool:
    if amount <= 0 or casino_chips(user) < amount:
        return False
    set_casino_chips(user, casino_chips(user) - amount)
    return True


def _take_food(user: Dict[str, Any], amount: int) -> bool:
    balance = int(user.get("balance", 0) or 0)
    if amount <= 0 or balance < amount:
        return False
    user["balance"] = balance - amount
    return True


def _tier_items(item_db: Mapping[str, Mapping[str, Any]], tiers: Sequence[str]) -> List[str]:
    rows: List[str] = []
    for tier in tiers:
        values = item_db.get(tier, {})
        if isinstance(values, Mapping):
            rows.extend(str(name) for name in values.keys())
    return rows


def _add_grave_loot(world_data: Dict[str, Any], guild_id: int, *, chips: int = 0, item: Optional[str] = None, source: str = "위험 이벤트") -> None:
    state = _world_state(world_data, guild_id)
    pool = state.setdefault("grave_pool", [])
    entry: Dict[str, Any] = {"source": source, "created_at": _now().isoformat()}
    if item:
        entry.update({"type": "item", "item": item})
    else:
        entry.update({"type": "chips", "amount": max(1, int(chips))})
    pool.append(entry)
    del pool[:-40]


def _guide_normalize(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch not in " `!/·-—[]()")


def update_command_guide(guide: List[Dict[str, Any]]) -> None:
    # 이전 실행에서 들어간 동일 카테고리를 제거하고 카지노 다음 위치에 삽입합니다.
    guide[:] = [cat for cat in guide if cat.get("id") != NEW_GUIDE_CATEGORY["id"]]
    insert_at = next((i + 1 for i, cat in enumerate(guide) if cat.get("id") == "casino"), len(guide))
    guide.insert(insert_at, copy.deepcopy(NEW_GUIDE_CATEGORY))

    # 동일 문구가 여러 최상위 카테고리에 중복 노출되지 않도록 첫 항목만 유지합니다.
    seen: set[str] = set()
    for category in guide:
        commands_list = category.get("commands", [])
        cleaned: List[str] = []
        for entry in commands_list:
            key = _guide_normalize(entry)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(entry)
        category["commands"] = cleaned


class OwnedView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)
        self.message: Optional[discord.Message] = None
        self.done = False
        self._lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("이 게임을 시작한 생존자만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    def disable_all(self) -> None:
        for item in self.children:
            item.disabled = True


class CrashView(OwnedView):
    def __init__(self, owner_id: int, user: Dict[str, Any], bet: int, save_data: Callable[[], None], world_data: Dict[str, Any], guild_id: int):
        super().__init__(owner_id, timeout=55)
        self.user = user
        self.bet = int(bet)
        self.save_data = save_data
        self.world_data = world_data
        self.guild_id = guild_id
        self.multiplier = 1.00
        # 중앙값이 낮고 드물게 큰 수가 나오는 하드코어 분포입니다.
        self.crash_at = min(12.0, max(1.08, 0.97 / max(0.075, random.random())))
        self.task: Optional[asyncio.Task] = None

    def embed(self, final: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(
            title="🏍️ 괴질 탈출",
            description=final or "감염체 무리가 가까워집니다. 너무 늦기 전에 **탈출**하세요.",
            color=discord.Color.dark_red() if final else discord.Color.orange(),
        )
        embed.add_field(name="🎮 10초 설명", value="배당이 계속 오르지만 갑자기 충돌하면 전액 손실입니다. 욕심내기 전에 **탈출** 버튼으로 회수하세요.", inline=False)
        embed.add_field(name="현재 배당", value=f"**{self.multiplier:.2f}×**", inline=True)
        embed.add_field(name="배팅", value=f"**{self.bet:,}칩**", inline=True)
        embed.add_field(name="지금 탈출", value=f"**{int(self.bet * self.multiplier):,}칩**", inline=True)
        embed.set_footer(text="배당이 높아질수록 다음 순간 충돌할 확률이 빠르게 상승합니다.")
        return embed

    def start_loop(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self.done:
                await asyncio.sleep(0.9)
                async with self._lock:
                    if self.done:
                        return
                    next_value = self.multiplier + 0.10 + self.multiplier * 0.055
                    if next_value >= self.crash_at:
                        self.multiplier = self.crash_at
                        self.done = True
                        self.disable_all()
                        _add_grave_loot(self.world_data, self.guild_id, chips=max(100, self.bet // 12), source="괴질 탈출 사고")
                        self.save_data()
                        if self.message:
                            await self.message.edit(embed=self.embed(f"💥 **{self.crash_at:.2f}×에서 감염체에게 덮쳤습니다.** 배팅 칩을 잃었습니다."), view=self)
                        return
                    self.multiplier = next_value
                    if self.message:
                        await self.message.edit(embed=self.embed(), view=self)
        except asyncio.CancelledError:
            return
        except Exception:
            self.done = True
            self.disable_all()

    @discord.ui.button(label="탈출", emoji="🏁", style=discord.ButtonStyle.success)
    async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self._lock:
            if self.done:
                await interaction.response.send_message("이미 종료된 탈출입니다.", ephemeral=True)
                return
            self.done = True
            self.disable_all()
            payout = max(0, int(self.bet * self.multiplier))
            add_casino_chips(self.user, payout)
            self.user.setdefault("stats", {})["crash_cashouts"] = int(self.user.setdefault("stats", {}).get("crash_cashouts", 0)) + 1
            self.save_data()
            await _safe_interaction_edit(interaction, 
                embed=self.embed(f"🏁 **{self.multiplier:.2f}×에서 탈출 성공!** 총 **{payout:,}칩**을 회수했습니다."),
                view=self,
            )

    async def on_timeout(self) -> None:
        if not self.done:
            self.done = True
            self.disable_all()
            _add_grave_loot(self.world_data, self.guild_id, chips=max(100, self.bet // 15), source="괴질 탈출 시간초과")
            self.save_data()
            if self.message:
                try:
                    await self.message.edit(embed=self.embed("⌛ 탈출 결정을 내리지 못해 감염체에게 포위됐습니다."), view=self)
                except Exception:
                    pass


class FrequencyView(OwnedView):
    def __init__(self, owner_id: int, user: Dict[str, Any], bet: int, save_data: Callable[[], None], world_data: Dict[str, Any], guild_id: int):
        super().__init__(owner_id, timeout=32)
        self.user = user
        self.bet = int(bet)
        self.save_data = save_data
        self.world_data = world_data
        self.guild_id = guild_id
        self.position = random.randint(5, 20)
        self.direction = 1
        self.target = random.randint(35, 65)
        self.tick = 0
        self.task: Optional[asyncio.Task] = None

    def gauge(self) -> str:
        cells = 20
        pos = min(cells - 1, max(0, round(self.position / 100 * (cells - 1))))
        target_pos = min(cells - 1, max(0, round(self.target / 100 * (cells - 1))))
        chars = ["▫️"] * cells
        chars[target_pos] = "🟩"
        chars[pos] = "📡" if pos != target_pos else "🎯"
        return "".join(chars)

    def embed(self, text: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(
            title="📻 비상 주파수 가로채기",
            description=text or "게이지가 초록 목표 지점을 지날 때 **수신** 버튼을 누르세요.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="🎮 10초 설명", value="움직이는 📡 표시가 초록 목표 칸을 지날 때 **수신** 버튼을 누르세요. 오차가 작을수록 보상이 큽니다.", inline=False)
        embed.add_field(name="주파수", value=self.gauge(), inline=False)
        embed.add_field(name="배팅", value=f"{self.bet:,}칩", inline=True)
        embed.add_field(name="오차", value=f"현재 {abs(self.position - self.target):.0f}%", inline=True)
        return embed

    def start_loop(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self.done and self.tick < 34:
                await asyncio.sleep(0.75)
                async with self._lock:
                    if self.done:
                        return
                    self.tick += 1
                    self.position += self.direction * random.randint(8, 13)
                    if self.position >= 100:
                        self.position = 100
                        self.direction = -1
                    elif self.position <= 0:
                        self.position = 0
                        self.direction = 1
                    if self.message:
                        await self.message.edit(embed=self.embed(), view=self)
            if not self.done:
                self.done = True
                self.disable_all()
                _add_grave_loot(self.world_data, self.guild_id, chips=max(100, self.bet // 15), source="주파수 수신 실패")
                self.save_data()
                if self.message:
                    await self.message.edit(embed=self.embed("📵 신호가 끊겼습니다. 배팅 칩을 잃었습니다."), view=self)
        except asyncio.CancelledError:
            return
        except Exception:
            self.done = True
            self.disable_all()

    @discord.ui.button(label="수신", emoji="📻", style=discord.ButtonStyle.primary)
    async def receive(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self._lock:
            if self.done:
                await interaction.response.send_message("이미 종료된 신호입니다.", ephemeral=True)
                return
            self.done = True
            self.disable_all()
            error = abs(self.position - self.target)
            if error <= 2:
                multiplier, label = 8.0, "완벽 동기화"
            elif error <= 5:
                multiplier, label = 4.0, "정밀 수신"
            elif error <= 10:
                multiplier, label = 2.0, "부분 수신"
            else:
                multiplier, label = 0.0, "주파수 이탈"
            payout = int(self.bet * multiplier)
            if payout:
                add_casino_chips(self.user, payout)
            else:
                _add_grave_loot(self.world_data, self.guild_id, chips=max(100, self.bet // 12), source="주파수 가로채기 실패")
            self.save_data()
            await _safe_interaction_edit(interaction, 
                embed=self.embed(f"{'✅' if payout else '❌'} **{label}** · 오차 {error:.0f}% · 회수 **{payout:,}칩**"),
                view=self,
            )


class MineCellButton(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.secondary, row=index // 5)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, MinesView):
            return
        await view.open_cell(interaction, self)


class MinesView(OwnedView):
    CELL_COUNT = 20

    def __init__(self, owner_id: int, user: Dict[str, Any], bet: int, mine_count: int, save_data: Callable[[], None], world_data: Dict[str, Any], guild_id: int, starting_balance: int):
        super().__init__(owner_id, timeout=120)
        self.user = user
        self.bet = int(bet)
        self.mine_count = int(mine_count)
        self.save_data = save_data
        self.world_data = world_data
        self.guild_id = guild_id
        self.starting_balance = int(starting_balance)
        self.result_status = "진행 중"
        self.gross_result = 0
        self.net_result = 0
        self.mines = set(random.sample(range(self.CELL_COUNT), self.mine_count))
        self.opened: set[int] = set()
        for index in range(self.CELL_COUNT):
            self.add_item(MineCellButton(index))

    def multiplier(self) -> float:
        if not self.opened:
            return 1.0
        result = 0.96
        remaining_total = self.CELL_COUNT
        remaining_safe = self.CELL_COUNT - self.mine_count
        for _ in range(len(self.opened)):
            result *= remaining_total / max(1, remaining_safe)
            remaining_total -= 1
            remaining_safe -= 1
        return min(result, 50.0)

    def embed(self, text: Optional[str] = None) -> discord.Embed:
        mult = self.multiplier()
        projected = int(self.bet * mult)
        projected_net = projected - self.bet
        current_balance = casino_chips(self.user)
        embed = discord.Embed(
            title="💣 무너진 폐허 횡단",
            description=text or "안전 칸을 열수록 배당이 상승합니다. **현재 회수액은 지금 도망쳤을 때 돌려받는 총액**입니다.",
            color=discord.Color.dark_gold() if not self.done else (discord.Color.green() if self.net_result >= 0 else discord.Color.dark_red()),
        )
        embed.add_field(name="🎮 10초 설명", value="안전 칸을 열면 배당이 오릅니다. 지뢰를 밟기 전에 🏃 버튼으로 현금화하면 표시된 총액을 회수합니다.", inline=False)
        embed.add_field(name="🧨 지뢰 / 안전 통과", value=f"{self.mine_count}개 / {len(self.opened)}칸", inline=True)
        safe_total = max(1, self.CELL_COUNT - self.mine_count)
        embed.add_field(name="🧭 횡단 진행", value=f"{_emoji_progress(len(self.opened), safe_total)} **{len(self.opened)}/{safe_total} · {len(self.opened)/safe_total*100:.0f}%**", inline=False)
        embed.add_field(name="💳 시작 전 보유 칩", value=f"{self.starting_balance:,}칩", inline=True)
        embed.add_field(name="💰 현재 보유 칩", value=f"{current_balance:,}칩", inline=True)
        if self.done:
            earned = max(0, self.net_result)
            lost = max(0, -self.net_result)
            embed.add_field(name="📌 최종 결과", value=self.result_status, inline=True)
            embed.add_field(name="🟢 얻은 돈", value=f"+{earned:,}칩", inline=True)
            embed.add_field(name="🔴 잃은 돈", value=f"-{lost:,}칩", inline=True)
            embed.add_field(name="📦 최종 회수 총액", value=f"{self.gross_result:,}칩", inline=True)
            embed.add_field(name="🏦 최종 보유 칩", value=f"{current_balance:,}칩", inline=True)
        else:
            embed.add_field(name="🏃 지금 현금화 총액", value=f"{projected:,}칩 ({mult:.2f}×)", inline=True)
            embed.add_field(name="📈 지금 확정 순손익", value=f"{projected_net:+,}칩", inline=True)
            embed.add_field(name="💥 지뢰 폭발 시", value=f"배팅액 전액 손실 **-{self.bet:,}칩**", inline=True)
        embed.set_footer(text="총액 = 배팅 원금 포함 · 순손익 = 실제로 번 돈 또는 잃은 돈")
        return embed

    async def open_cell(self, interaction: discord.Interaction, button: MineCellButton) -> None:
        async with self._lock:
            if self.done or button.index in self.opened:
                await interaction.response.send_message("이미 확인한 칸입니다.", ephemeral=True)
                return
            if button.index in self.mines:
                button.label = "☠"
                button.style = discord.ButtonStyle.danger
                self.done = True
                self.result_status = "💥 지뢰 폭발 · 배팅액 전액 손실"
                self.gross_result = 0
                self.net_result = -self.bet
                for child in self.children:
                    child.disabled = True
                    if isinstance(child, MineCellButton) and child.index in self.mines:
                        child.label = "💣"
                _add_grave_loot(self.world_data, self.guild_id, chips=max(100, self.bet // 10), source="폐허 지뢰 폭발")
                self.save_data()
                await _safe_interaction_edit(interaction, embed=self.embed("💥 **지뢰가 폭발했습니다.** 현재 회수액은 0칩이며, 배팅액을 전부 잃었습니다."), view=self)
                return
            self.opened.add(button.index)
            button.label = "✨"
            button.style = discord.ButtonStyle.success
            button.disabled = True
            if len(self.opened) >= self.CELL_COUNT - self.mine_count:
                self.done = True
                payout = int(self.bet * self.multiplier())
                add_casino_chips(self.user, payout)
                self.gross_result = payout
                self.net_result = payout - self.bet
                self.result_status = "🏆 모든 안전 칸 통과"
                self.disable_all()
                self.save_data()
                await _safe_interaction_edit(interaction, embed=self.embed(f"🏆 모든 안전 칸을 통과했습니다. 총 **{payout:,}칩**, 순이익 **{self.net_result:+,}칩**!"), view=self)
                return
            await _safe_interaction_edit(interaction, embed=self.embed("✅ 안전 칸입니다. 현금화 총액과 순이익을 따로 확인하세요."), view=self)

    @discord.ui.button(label="배당금 챙기고 도망치기", emoji="🏃", style=discord.ButtonStyle.primary, row=4)
    async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self._lock:
            if self.done:
                await interaction.response.send_message("이미 끝난 횡단입니다.", ephemeral=True)
                return
            if not self.opened:
                await interaction.response.send_message("최소 한 칸은 안전하게 통과해야 현금화할 수 있습니다.", ephemeral=True)
                return
            self.done = True
            payout = int(self.bet * self.multiplier())
            add_casino_chips(self.user, payout)
            self.gross_result = payout
            self.net_result = payout - self.bet
            self.result_status = "🏃 현금화 성공"
            self.disable_all()
            self.save_data()
            await _safe_interaction_edit(interaction, embed=self.embed(f"🏃 탈출 성공! 총 **{payout:,}칩** 회수 · 실제 순손익 **{self.net_result:+,}칩**"), view=self)


class DoorView(OwnedView):
    def __init__(self, owner_id: int, user: Dict[str, Any], save_data: Callable[[], None], item_db: Mapping[str, Mapping[str, Any]], world_data: Dict[str, Any], guild_id: int):
        super().__init__(owner_id, timeout=45)
        self.user = user
        self.save_data = save_data
        self.item_db = item_db
        self.world_data = world_data
        self.guild_id = guild_id
        self.outcomes = ["cache", "ambush", "jackpot"]
        random.shuffle(self.outcomes)

    async def choose(self, interaction: discord.Interaction, index: int) -> None:
        async with self._lock:
            if self.done:
                await interaction.response.send_message("이미 열린 문입니다.", ephemeral=True)
                return
            self.done = True
            self.disable_all()
            outcome = self.outcomes[index]
            if outcome == "jackpot":
                items = _tier_items(self.item_db, ("영웅", "전설"))
                item = random.choice(items) if items else None
                chips = random.randint(1_500_000, 3_000_000)
                add_casino_chips(self.user, chips)
                if item:
                    self.user.setdefault("inventory", []).append(item)
                text = f"✨ 숨겨진 잭팟 창고! **{chips:,}칩**" + (f" + **{item}**" if item else "")
                color = discord.Color.gold()
            elif outcome == "cache":
                resources = self.user.setdefault("resources", {})
                found = {"나무": random.randint(30, 80), "광석": random.randint(20, 55), "고철": random.randint(25, 70)}
                for key, amount in found.items():
                    resources[key] = int(resources.get(key, 0)) + amount
                text = "📦 보급 창고 발견 · " + " · ".join(f"{k} +{v}" for k, v in found.items())
                color = discord.Color.green()
            else:
                extra = min(int(self.user.get("balance", 0)), random.randint(250_000, 700_000))
                self.user["balance"] = int(self.user.get("balance", 0)) - extra
                _add_grave_loot(self.world_data, self.guild_id, chips=max(100, extra // 25), source="오염문 매복")
                text = f"🩸 변이체 매복! 추가 식량 **-{extra:,}**"
                color = discord.Color.dark_red()
            self.save_data()
            embed = discord.Embed(title="🚪 폐허의 3지선다", description=text, color=color)
            await _safe_interaction_edit(interaction, embed=embed, view=self)

    @discord.ui.button(label="1번 철문", style=discord.ButtonStyle.secondary)
    async def door1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 0)

    @discord.ui.button(label="2번 방폭문", style=discord.ButtonStyle.secondary)
    async def door2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 1)

    @discord.ui.button(label="3번 격리문", style=discord.ButtonStyle.secondary)
    async def door3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 2)


class DuelAcceptView(discord.ui.View):
    def __init__(
        self,
        challenger: discord.Member,
        target: discord.Member,
        bet: int,
        mode: str,
        get_user: Callable[[int], Dict[str, Any]],
        save_data: Callable[[], None],
        calculate_user_power: Callable[[Dict[str, Any]], int],
        get_pet_power: Callable[[Dict[str, Any]], int],
        world_data: Dict[str, Any],
        guild_id: int,
        item_db: Mapping[str, Mapping[str, Any]],
    ):
        super().__init__(timeout=45)
        self.challenger = challenger
        self.target = target
        self.bet = bet
        self.mode = mode
        self.get_user = get_user
        self.save_data = save_data
        self.calculate_user_power = calculate_user_power
        self.get_pet_power = get_pet_power
        self.world_data = world_data
        self.guild_id = guild_id
        self.item_db = item_db
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in {self.challenger.id, self.target.id}:
            await interaction.response.send_message("결투 당사자만 응답할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="수락", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("도전받은 생존자만 수락할 수 있습니다.", ephemeral=True)
            return
        if self.done:
            await interaction.response.send_message("이미 처리된 도전입니다.", ephemeral=True)
            return
        challenger_user = self.get_user(self.challenger.id)
        target_user = self.get_user(self.target.id)
        if not challenger_user or not target_user:
            await interaction.response.send_message("생존자 등록 상태를 확인할 수 없습니다.", ephemeral=True)
            return
        if casino_chips(challenger_user) < self.bet or casino_chips(target_user) < self.bet:
            await interaction.response.send_message("양쪽 중 한 명의 칩이 부족해 결투가 취소됐습니다.", ephemeral=True)
            return
        if self.mode == "pet" and (self.get_pet_power(challenger_user) <= 0 or self.get_pet_power(target_user) <= 0):
            await interaction.response.send_message("양쪽 모두 장착한 펫이 있어야 괴수 투기장을 진행할 수 있습니다.", ephemeral=True)
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        _take_chips(challenger_user, self.bet)
        _take_chips(target_user, self.bet)
        if self.mode == "pet":
            left_power = max(1, self.get_pet_power(challenger_user))
            right_power = max(1, self.get_pet_power(target_user))
            title = "🦖 괴수 투기장 결과"
        else:
            left_power = max(1, self.calculate_user_power(challenger_user))
            right_power = max(1, self.calculate_user_power(target_user))
            title = "⚔️ 영혼의 데스매치 결과"
        left_score = left_power * random.uniform(0.78, 1.22)
        right_score = right_power * random.uniform(0.78, 1.22)
        if left_score == right_score:
            left_score += random.random()
        winner_member, loser_member = (self.challenger, self.target) if left_score > right_score else (self.target, self.challenger)
        winner_user, loser_user = (challenger_user, target_user) if left_score > right_score else (target_user, challenger_user)
        pot = self.bet * 2
        payout = int(pot * 0.94)
        add_casino_chips(winner_user, payout)
        if self.mode == "pet":
            _state(loser_user)["pet_injured_until"] = (_now() + timedelta(minutes=45)).isoformat()
            penalty = "패자의 펫은 **45분 부상** 상태가 됩니다."
        else:
            _state(loser_user)["soul_wound_until"] = (_now() + timedelta(minutes=60)).isoformat()
            penalty = "패자는 **60분 영혼 상처** 상태가 됩니다."
            # 동의형 고위험 결투에서만 낮은 등급 비장착 아이템이 20% 확률로 잔해가 됩니다.
            inventory = loser_user.setdefault("inventory", [])
            equipped = set(v for v in loser_user.get("equipment", {}).values() if v)
            low_tier = set(_tier_items(self.item_db, ("일반", "고급", "희귀")))
            candidates = [item for item in inventory if item in low_tier and item not in equipped]
            if candidates and random.random() < 0.20:
                dropped = random.choice(candidates)
                inventory.remove(dropped)
                _add_grave_loot(self.world_data, self.guild_id, item=dropped, source="영혼 결투 패배")
                penalty += f" 비장착 장비 **{dropped}**가 잔해로 떨어졌습니다."
        _add_grave_loot(self.world_data, self.guild_id, chips=max(100, pot - payout), source="결투 수수료 잔해")
        self.save_data()
        embed = discord.Embed(title=title, color=discord.Color.dark_red())
        embed.description = f"🏆 승자: {winner_member.mention}\n💀 패자: {loser_member.mention}"
        embed.add_field(name="전투력 굴림", value=f"{self.challenger.display_name} {left_score:.1f} vs {self.target.display_name} {right_score:.1f}", inline=False)
        embed.add_field(name="승자 회수", value=f"{payout:,}칩", inline=True)
        embed.add_field(name="후유증", value=penalty, inline=False)
        await _safe_interaction_edit(interaction, embed=embed, view=self)

    @discord.ui.button(label="거절", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("도전받은 생존자만 거절할 수 있습니다.", ephemeral=True)
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        await _safe_interaction_edit(interaction, content="결투가 거절됐습니다.", embed=None, view=self)


class HeistView(discord.ui.View):
    def __init__(self, guild_id: int, lobby: Dict[str, Any], get_user: Callable[[int], Dict[str, Any]], save_data: Callable[[], None], world_data: Dict[str, Any]):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.lobby = lobby
        self.get_user = get_user
        self.save_data = save_data
        self.world_data = world_data
        self.stage = 0
        self.answers = [random.randrange(3) for _ in range(4)]
        self.done = False

    def embed(self, text: Optional[str] = None) -> discord.Embed:
        names = ", ".join(f"<@{uid}>" for uid in self.lobby["participants"])
        embed = discord.Embed(
            title="🏦 카지노 금고 털기",
            description=text or f"**관문 {self.stage + 1}/4** · 세 회로 중 안전한 선을 선택하세요.",
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="침투조", value=names, inline=False)
        embed.add_field(name="공동 참가비", value=f"{self.lobby['pot']:,}칩", inline=True)
        embed.add_field(name="성공 확률", value="관문당 1/3 · 연속 4회", inline=True)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) not in self.lobby["participants"]:
            await interaction.response.send_message("침투조만 회로를 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def choose(self, interaction: discord.Interaction, choice: int) -> None:
        if self.done:
            await interaction.response.send_message("이미 끝난 금고 침투입니다.", ephemeral=True)
            return
        if choice != self.answers[self.stage]:
            self.done = True
            for child in self.children:
                child.disabled = True
            _add_grave_loot(self.world_data, self.guild_id, chips=max(100, self.lobby["pot"] // 8), source="카지노 금고 경보")
            self.save_data()
            await _safe_interaction_edit(interaction, embed=self.embed("🚨 잘못된 회로를 잘랐습니다. 경보가 울리고 공동 참가비가 전부 압수됐습니다."), view=self)
            return
        self.stage += 1
        if self.stage >= 4:
            self.done = True
            for child in self.children:
                child.disabled = True
            total_payout = min(500_000_000, int(self.lobby["pot"] * 40))
            share = total_payout // len(self.lobby["participants"])
            for uid in self.lobby["participants"]:
                user = self.get_user(uid)
                if user:
                    add_casino_chips(user, share)
            self.save_data()
            await _safe_interaction_edit(interaction, embed=self.embed(f"💎 금고 개방 성공! 총 **{total_payout:,}칩**, 1인당 **{share:,}칩**을 확보했습니다."), view=self)
            return
        await _safe_interaction_edit(interaction, embed=self.embed(f"✅ 관문 {self.stage}/4 통과. 다음 보안 회로가 열렸습니다."), view=self)

    @discord.ui.button(label="A 회로", style=discord.ButtonStyle.danger)
    async def a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 0)

    @discord.ui.button(label="B 회로", style=discord.ButtonStyle.primary)
    async def b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 1)

    @discord.ui.button(label="C 회로", style=discord.ButtonStyle.success)
    async def c(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, 2)


def register_v638_hardcore_arcade(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[Dict[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    item_db: Mapping[str, Mapping[str, Any]],
    calculate_user_power: Callable[[Dict[str, Any]], int],
    get_pet_power: Callable[[Dict[str, Any]], int],
    command_guide_categories: List[Dict[str, Any]],
) -> None:
    update_command_guide(command_guide_categories)

    race_lobbies: Dict[int, Dict[str, Any]] = {}
    bunker_lobbies: Dict[int, Dict[str, Any]] = {}
    heist_lobbies: Dict[int, Dict[str, Any]] = {}

    async def require_user(ctx: commands.Context) -> Optional[Dict[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        if user is None:
            await ctx.send("생존자 데이터를 불러오지 못했습니다.")
            return None
        _state(user)
        return user

    @bot.command(name="괴질탈출", aliases=["크래시", "괴질크래시"])
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def crash_game(ctx: commands.Context, 배팅액: int):
        user = await require_user(ctx)
        if user is None:
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        if not _take_chips(user, 배팅액):
            await ctx.send(f"칩이 부족합니다. 보유 **{casino_chips(user):,}칩**")
            return
        save_data()
        view = CrashView(ctx.author.id, user, 배팅액, save_data, world_data, _guild_id(ctx))
        message = await ctx.send(embed=view.embed(), view=view)
        view.message = message
        view.start_loop()

    @bot.command(name="비상주파수", aliases=["주파수가로채기", "타이밍주파수"])
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def emergency_frequency(ctx: commands.Context, 배팅액: int):
        user = await require_user(ctx)
        if user is None:
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        if not _take_chips(user, 배팅액):
            await ctx.send(f"칩이 부족합니다. 보유 **{casino_chips(user):,}칩**")
            return
        save_data()
        view = FrequencyView(ctx.author.id, user, 배팅액, save_data, world_data, _guild_id(ctx))
        message = await ctx.send(embed=view.embed(), view=view)
        view.message = message
        view.start_loop()

    @bot.command(name="지뢰찾기", aliases=["폐허횡단", "마인즈"])
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def mines_game(ctx: commands.Context, 지뢰수: int = 5, 배팅액: int = 100_000):
        user = await require_user(ctx)
        if user is None:
            return
        if not 3 <= 지뢰수 <= 10:
            await ctx.send("지뢰 수는 **3~10개**로 설정할 수 있습니다.")
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        starting_balance = casino_chips(user)
        if not _take_chips(user, 배팅액):
            await ctx.send(f"칩이 부족합니다. 보유 **{casino_chips(user):,}칩**")
            return
        save_data()
        view = MinesView(ctx.author.id, user, 배팅액, 지뢰수, save_data, world_data, _guild_id(ctx), starting_balance)
        await ctx.send(embed=view.embed(), view=view)

    async def resolve_race(guild_id: int, channel: discord.abc.Messageable, delay: int = 25) -> None:
        await asyncio.sleep(delay)
        race = race_lobbies.get(guild_id)
        if not race or race.get("resolved"):
            return
        race["resolved"] = True
        weights = [1.0 / entrant[2] for entrant in race["entrants"]]
        winner_index = random.choices(range(5), weights=weights, k=1)[0]
        winner = race["entrants"][winner_index]
        lines = []
        for uid, bet in list(race["bets"].items()):
            user = get_user(uid)
            if not user:
                continue
            number, amount = bet
            if number == winner_index + 1:
                payout = int(amount * winner[2])
                add_casino_chips(user, payout)
                lines.append(f"<@{uid}> 적중 · +{payout:,}칩")
            else:
                lines.append(f"<@{uid}> 실패")
        save_data()
        embed = discord.Embed(title="🏁 돌연변이 투기장 결승", description=f"우승: **{winner[1]} {winner[0]}** · 배당 {winner[2]:.1f}×", color=discord.Color.dark_gold())
        embed.add_field(name="정산", value="\n".join(lines) if lines else "참가자가 없었습니다.", inline=False)
        try:
            await channel.send(embed=embed)
        finally:
            race_lobbies.pop(guild_id, None)

    @bot.command(name="돌연변이경주", aliases=["투기장경주", "괴수경주"])
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def mutant_race(ctx: commands.Context):
        if not await check_registered(ctx):
            return
        guild_id = _guild_id(ctx)
        if guild_id in race_lobbies:
            race = race_lobbies[guild_id]
        else:
            entrants = random.sample(list(MUTANTS), k=5)
            race = {"entrants": entrants, "bets": {}, "resolved": False}
            race_lobbies[guild_id] = race
            asyncio.create_task(resolve_race(guild_id, ctx.channel, 25))
        lines = [f"**{i}.** {emoji} {name} · {odds:.1f}×" for i, (name, emoji, odds) in enumerate(race["entrants"], 1)]
        embed = discord.Embed(title="🏇 돌연변이 투기장", description="\n".join(lines), color=discord.Color.dark_teal())
        embed.add_field(name="배팅", value="`!돌연변이배팅 번호 배팅액` · 25초 뒤 자동 출발", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="돌연변이배팅", aliases=["투기장배팅"])
    async def mutant_bet(ctx: commands.Context, 번호: int, 배팅액: int):
        user = await require_user(ctx)
        if user is None:
            return
        guild_id = _guild_id(ctx)
        race = race_lobbies.get(guild_id)
        if not race or race.get("resolved"):
            await ctx.send("현재 접수 중인 경주가 없습니다. `!돌연변이경주`로 경주를 열어주세요.")
            return
        if not 1 <= 번호 <= 5:
            await ctx.send("번호는 1~5 중 하나를 선택하세요.")
            return
        if ctx.author.id in race["bets"]:
            await ctx.send("한 경주에는 한 번만 배팅할 수 있습니다.")
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        if not _take_chips(user, 배팅액):
            await ctx.send("칩이 부족합니다.")
            return
        race["bets"][ctx.author.id] = (번호, 배팅액)
        save_data()
        await ctx.send(f"🎫 **{번호}번**에 **{배팅액:,}칩** 접수 완료. 결과는 자동 발표됩니다.")

    @bot.command(name="오염문", aliases=["폐허3지선다", "세개의문"])
    @commands.cooldown(1, 1800, commands.BucketType.user)
    async def polluted_doors(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        entry = 500_000
        if not _take_food(user, entry):
            await ctx.send(f"문을 해체할 식량이 부족합니다. 필요 **{entry:,}식량**")
            return
        save_data()
        embed = discord.Embed(title="🚪 폐허의 3지선다", description="**🎮 10초 설명:** 세 문 중 하나를 고릅니다. 잭팟·보급품·매복이 무작위로 숨겨져 있으며 선택 후 되돌릴 수 없습니다.", color=discord.Color.dark_purple())
        embed.set_footer(text=f"입장 비용 {entry:,}식량 · 선택 후 되돌릴 수 없습니다.")
        await ctx.send(embed=embed, view=DoorView(ctx.author.id, user, save_data, item_db, world_data, _guild_id(ctx)))

    @bot.command(name="비상보급상자", aliases=["전리품상자", "프리미엄랜덤박스"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def emergency_crate(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        state = _state(user)
        daily = state.setdefault("crate_daily", {})
        if daily.get("date") != _today():
            daily.clear()
            daily.update({"date": _today(), "opened": 0})
        if int(daily.get("opened", 0)) >= 1:
            await ctx.send("비상 보급상자는 하루에 **1개**만 구매할 수 있습니다.")
            return
        if not _take_food(user, CRATE_COST):
            await ctx.send(f"식량이 부족합니다. 필요 **{CRATE_COST:,}식량**")
            return
        guild_state = _world_state(world_data, _guild_id(ctx))
        if guild_state.get("crate_week") != _week_key():
            guild_state["crate_week"] = _week_key()
            guild_state["crate_legendaries_left"] = 3
        pity = int(state.get("crate_pity", 0))
        roll = random.random()
        forced = pity >= 11
        result_text = ""
        color = discord.Color.dark_gold()
        if (roll < 0.018 or forced) and int(guild_state.get("crate_legendaries_left", 0)) > 0:
            candidates = _tier_items(item_db, ("전설", "신화"))
            item = random.choice(candidates) if candidates else "희귀 전리품"
            user.setdefault("inventory", []).append(item)
            guild_state["crate_legendaries_left"] = int(guild_state.get("crate_legendaries_left", 0)) - 1
            state["crate_pity"] = 0
            result_text = f"🌟 서버 한정 전리품 **{item}** 획득!"
            color = discord.Color.gold()
        elif roll < 0.16:
            candidates = _tier_items(item_db, ("영웅", "전설"))
            item = random.choice(candidates) if candidates else "고급 전리품"
            user.setdefault("inventory", []).append(item)
            state["crate_pity"] = pity + 1
            result_text = f"🟣 고급 전리품 **{item}**"
        elif roll < 0.55:
            resources = user.setdefault("resources", {})
            amount = random.randint(120, 260)
            resource = random.choice(("나무", "광석", "고철"))
            resources[resource] = int(resources.get(resource, 0)) + amount
            state["crate_pity"] = pity + 1
            result_text = f"📦 {resource} **+{amount}**"
        else:
            junk = random.choice(("유통기한 지난 통조림", "젖은 붕대", "빈 탄피 더미", "깨진 회로판"))
            refund = random.randint(80_000, 280_000)
            user["balance"] = int(user.get("balance", 0)) + refund
            state["crate_pity"] = pity + 1
            result_text = f"🗑️ **{junk}** · 회수 식량 +{refund:,}"
        daily["opened"] = 1
        save_data()
        embed = discord.Embed(title="📦 의문의 비상 보급상자", description=result_text, color=color)
        embed.add_field(name="비용", value=f"-{CRATE_COST:,} 식량", inline=True)
        embed.add_field(name="개인 천장", value=f"{state['crate_pity']}/12", inline=True)
        embed.add_field(name="이번 주 서버 한정 잔여", value=f"{guild_state.get('crate_legendaries_left', 0)}개", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="선물거래", aliases=["감염선물", "레버리지"])
    @commands.cooldown(1, 12, commands.BucketType.user)
    async def futures_trade(ctx: commands.Context, 방향: str, 배팅액: int, 레버리지: int = 5):
        user = await require_user(ctx)
        if user is None:
            return
        direction = 방향.strip().lower()
        if direction not in {"상승", "롱", "하락", "숏"}:
            await ctx.send("방향은 `상승` 또는 `하락`으로 입력하세요.")
            return
        if 레버리지 not in {5, 10, 20}:
            await ctx.send("레버리지는 **5 / 10 / 20배** 중 하나만 사용할 수 있습니다.")
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        state = _state(user)
        daily = state.setdefault("futures_daily", {})
        if daily.get("date") != _today():
            daily.clear(); daily.update({"date": _today(), "count": 0})
        if int(daily.get("count", 0)) >= 5:
            await ctx.send("선물거래는 하루 **5회**까지만 가능합니다.")
            return
        if not _take_chips(user, 배팅액):
            await ctx.send("칩이 부족합니다.")
            return
        guild_state = _world_state(world_data, _guild_id(ctx))
        before = float(guild_state.get("market_index", 100.0))
        move = max(-12.0, min(12.0, random.gauss(0, 4.5)))
        after = max(30.0, min(300.0, before + move))
        guild_state["market_index"] = after
        expected_up = direction in {"상승", "롱"}
        correct = (move > 0 and expected_up) or (move < 0 and not expected_up)
        if abs(move) < 0.6:
            correct = False
        if correct:
            profit_mult = min(5.0, 1.0 + abs(move) / 10.0 * 레버리지)
            payout = int(배팅액 * profit_mult)
            add_casino_chips(user, payout)
            text = f"📈 예측 적중 · 지수 {before:.1f} → {after:.1f} ({move:+.1f}) · 회수 **{payout:,}칩**"
            color = discord.Color.green()
        else:
            extra_loss = min(casino_chips(user), int(배팅액 * max(0, 레버리지 - 5) * 0.06))
            if extra_loss:
                _take_chips(user, extra_loss)
            _add_grave_loot(world_data, _guild_id(ctx), chips=max(100, (배팅액 + extra_loss) // 8), source="선물거래 청산")
            text = f"📉 **강제 청산** · 지수 {before:.1f} → {after:.1f} ({move:+.1f}) · 추가 손실 **{extra_loss:,}칩**"
            color = discord.Color.dark_red()
        daily["count"] = int(daily.get("count", 0)) + 1
        save_data()
        await ctx.send(embed=discord.Embed(title="📊 암시장 선물거래", description=text, color=color))

    @bot.command(name="괴수투기장", aliases=["펫데스매치"])
    async def monster_arena(ctx: commands.Context, 상대: discord.Member, 배팅액: int = 100_000):
        user = await require_user(ctx)
        if user is None:
            return
        if 상대.bot or 상대.id == ctx.author.id:
            await ctx.send("봇 또는 자기 자신에게 도전할 수 없습니다.")
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        target_user = get_user(상대.id)
        if not target_user:
            await ctx.send("상대가 아바돈 생존자로 등록되어 있지 않습니다.")
            return
        if get_pet_power(user) <= 0 or get_pet_power(target_user) <= 0:
            await ctx.send("양쪽 모두 펫을 장착해야 합니다.")
            return
        view = DuelAcceptView(ctx.author, 상대, 배팅액, "pet", get_user, save_data, calculate_user_power, get_pet_power, world_data, _guild_id(ctx), item_db)
        await ctx.send(f"🦖 {상대.mention}, {ctx.author.mention}님이 **{배팅액:,}칩 괴수 투기장**에 도전했습니다.", view=view)

    @bot.command(name="영혼결투", aliases=["영혼의데스매치", "고위험PVP"])
    async def soul_duel(ctx: commands.Context, 상대: discord.Member, 배팅액: int = 500_000):
        user = await require_user(ctx)
        if user is None:
            return
        if 상대.bot or 상대.id == ctx.author.id:
            await ctx.send("봇 또는 자기 자신에게 도전할 수 없습니다.")
            return
        if 배팅액 < 500_000:
            await ctx.send("영혼결투의 최소 판돈은 **500,000칩**입니다.")
            return
        error = _validate_bet(배팅액)
        if error:
            await ctx.send(error)
            return
        if not get_user(상대.id):
            await ctx.send("상대가 아바돈 생존자로 등록되어 있지 않습니다.")
            return
        view = DuelAcceptView(ctx.author, 상대, 배팅액, "soul", get_user, save_data, calculate_user_power, get_pet_power, world_data, _guild_id(ctx), item_db)
        await ctx.send(f"⚔️ {상대.mention}, {ctx.author.mention}님이 **{배팅액:,}칩 영혼결투**를 신청했습니다. 동의형 고위험 결투입니다.", view=view)

    @bot.command(name="벙커개설")
    async def bunker_open(ctx: commands.Context, 참가비: int = 250_000):
        user = await require_user(ctx)
        if user is None:
            return
        guild_id = _guild_id(ctx)
        if guild_id in bunker_lobbies:
            await ctx.send("이미 진행 중인 벙커가 있습니다. `!벙커상태`를 확인하세요.")
            return
        if not MIN_CHIP_BET <= 참가비 <= 10_000_000:
            await ctx.send("참가비는 10,000~10,000,000칩 범위입니다.")
            return
        if not _take_chips(user, 참가비):
            await ctx.send("칩이 부족합니다.")
            return
        bunker_lobbies[guild_id] = {
            "host": ctx.author.id,
            "fee": 참가비,
            "pot": 참가비,
            "active": [ctx.author.id],
            "votes": {},
            "round": 0,
            "started": False,
        }
        save_data()
        await ctx.send(f"🚪 배신자의 벙커가 열렸습니다. 참가비 **{참가비:,}칩** · `!벙커참가` · 최소 3명")

    @bot.command(name="벙커참가")
    async def bunker_join(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        lobby = bunker_lobbies.get(_guild_id(ctx))
        if not lobby or lobby.get("started"):
            await ctx.send("참가 가능한 벙커가 없습니다.")
            return
        if ctx.author.id in lobby["active"]:
            await ctx.send("이미 참가 중입니다.")
            return
        if len(lobby["active"]) >= 8:
            await ctx.send("벙커 정원이 가득 찼습니다.")
            return
        if not _take_chips(user, lobby["fee"]):
            await ctx.send("참가비가 부족합니다.")
            return
        lobby["active"].append(ctx.author.id)
        lobby["pot"] += lobby["fee"]
        save_data()
        await ctx.send(f"🚪 {ctx.author.mention} 벙커 참가 완료 · 현재 {len(lobby['active'])}/8명")

    @bot.command(name="벙커상태")
    async def bunker_status(ctx: commands.Context):
        lobby = bunker_lobbies.get(_guild_id(ctx))
        if not lobby:
            await ctx.send("현재 열린 벙커가 없습니다.")
            return
        members = "\n".join(f"• <@{uid}>" for uid in lobby["active"])
        embed = discord.Embed(title="🚪 배신자의 벙커", description=members, color=discord.Color.dark_purple())
        embed.add_field(name="라운드", value=str(lobby["round"]), inline=True)
        embed.add_field(name="상금", value=f"{lobby['pot']:,}칩", inline=True)
        embed.add_field(name="진행", value="투표 중" if lobby["started"] else "모집 중", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="벙커투표")
    async def bunker_vote(ctx: commands.Context, 대상: discord.Member):
        lobby = bunker_lobbies.get(_guild_id(ctx))
        if not lobby:
            await ctx.send("현재 열린 벙커가 없습니다.")
            return
        if not lobby["started"]:
            if len(lobby["active"]) < 3:
                await ctx.send("최소 3명이 모여야 투표를 시작할 수 있습니다.")
                return
            lobby["started"] = True
            lobby["round"] = 1
        if ctx.author.id not in lobby["active"] or 대상.id not in lobby["active"]:
            await ctx.send("생존 중인 참가자에게만 투표할 수 있습니다.")
            return
        if 대상.id == ctx.author.id:
            await ctx.send("자기 자신에게 투표할 수 없습니다.")
            return
        lobby["votes"][ctx.author.id] = 대상.id
        await ctx.send(f"🗳️ {ctx.author.mention}님의 표가 봉인됐습니다.")

    @bot.command(name="벙커진행")
    async def bunker_advance(ctx: commands.Context):
        guild_id = _guild_id(ctx)
        lobby = bunker_lobbies.get(guild_id)
        if not lobby:
            await ctx.send("현재 열린 벙커가 없습니다.")
            return
        if ctx.author.id != lobby["host"]:
            await ctx.send("벙커 개설자만 라운드를 정산할 수 있습니다.")
            return
        if len(lobby["active"]) < 3 and not lobby["started"]:
            await ctx.send("최소 3명이 필요합니다.")
            return
        lobby["started"] = True
        counts: Dict[int, int] = {}
        for target_id in lobby["votes"].values():
            if target_id in lobby["active"]:
                counts[target_id] = counts.get(target_id, 0) + 1
        if counts:
            max_votes = max(counts.values())
            candidates = [uid for uid, count in counts.items() if count == max_votes]
            eliminated = random.choice(candidates)
        else:
            eliminated = random.choice(lobby["active"])
        lobby["active"].remove(eliminated)
        lobby["votes"] = {}
        lobby["round"] += 1
        if len(lobby["active"]) == 1:
            winner_id = lobby["active"][0]
            winner = get_user(winner_id)
            payout = int(lobby["pot"] * 0.90)
            if winner:
                add_casino_chips(winner, payout)
            _add_grave_loot(world_data, guild_id, chips=max(100, lobby["pot"] - payout), source="벙커 숙청 잔여")
            bunker_lobbies.pop(guild_id, None)
            save_data()
            await ctx.send(f"👑 최후의 생존자 <@{winner_id}> · 상금 **{payout:,}칩** · 마지막 탈락 <@{eliminated}>")
            return
        save_data()
        await ctx.send(f"☠️ <@{eliminated}> 탈락 · 생존 {len(lobby['active'])}명 · 다음 라운드 투표를 시작하세요.")

    @bot.command(name="하이에나", aliases=["시체파밍", "잔해약탈"])
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def hyena_loot(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        guild_state = _world_state(world_data, _guild_id(ctx))
        pool = guild_state.setdefault("grave_pool", [])
        if not pool:
            await ctx.send("🦴 지금은 약탈할 잔해가 없습니다.")
            return
        if random.random() < 0.35:
            loss = min(int(user.get("balance", 0)), random.randint(50_000, 300_000))
            user["balance"] = int(user.get("balance", 0)) - loss
            save_data()
            await ctx.send(f"🩸 잔해 속 감염체에게 물렸습니다. 식량 **-{loss:,}**")
            return
        entry = pool.pop(0)
        if entry.get("type") == "item":
            item = str(entry.get("item"))
            user.setdefault("inventory", []).append(item)
            text = f"🎒 **{item}**을 주웠습니다."
        else:
            amount = int(entry.get("amount", 0))
            add_casino_chips(user, amount)
            text = f"🪙 잔해 칩 **+{amount:,}**"
        save_data()
        await ctx.send(f"🐀 하이에나 약탈 성공 · {text}\n출처: {entry.get('source', '미상')}")

    @bot.command(name="금고개설", aliases=["카지노금고개설"])
    async def heist_open(ctx: commands.Context, 참가비: int = 500_000):
        user = await require_user(ctx)
        if user is None:
            return
        guild_id = _guild_id(ctx)
        if guild_id in heist_lobbies:
            await ctx.send("이미 준비 중인 금고 침투조가 있습니다.")
            return
        if not 100_000 <= 참가비 <= 10_000_000:
            await ctx.send("참가비는 100,000~10,000,000칩 범위입니다.")
            return
        if not _take_chips(user, 참가비):
            await ctx.send("칩이 부족합니다.")
            return
        heist_lobbies[guild_id] = {"host": ctx.author.id, "fee": 참가비, "pot": 참가비, "participants": [ctx.author.id], "started": False}
        save_data()
        await ctx.send(f"🏦 카지노 금고 침투조 모집 · 참가비 **{참가비:,}칩** · `!금고참가` · 3~4명")

    @bot.command(name="금고참가")
    async def heist_join(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        lobby = heist_lobbies.get(_guild_id(ctx))
        if not lobby or lobby.get("started"):
            await ctx.send("참가 가능한 금고 침투조가 없습니다.")
            return
        if ctx.author.id in lobby["participants"]:
            await ctx.send("이미 참가했습니다.")
            return
        if len(lobby["participants"]) >= 4:
            await ctx.send("침투조 정원은 4명입니다.")
            return
        if not _take_chips(user, lobby["fee"]):
            await ctx.send("참가비가 부족합니다.")
            return
        lobby["participants"].append(ctx.author.id)
        lobby["pot"] += lobby["fee"]
        save_data()
        await ctx.send(f"🏦 {ctx.author.mention} 침투조 합류 · {len(lobby['participants'])}/4명")

    @bot.command(name="금고시작")
    async def heist_start(ctx: commands.Context):
        guild_id = _guild_id(ctx)
        lobby = heist_lobbies.get(guild_id)
        if not lobby:
            await ctx.send("준비 중인 금고 침투조가 없습니다.")
            return
        if ctx.author.id != lobby["host"]:
            await ctx.send("침투조 개설자만 시작할 수 있습니다.")
            return
        if not 3 <= len(lobby["participants"]) <= 4:
            await ctx.send("금고 침투는 3~4명이 필요합니다.")
            return
        lobby["started"] = True
        view = HeistView(guild_id, lobby, get_user, save_data, world_data)
        heist_lobbies.pop(guild_id, None)
        await ctx.send(embed=view.embed(), view=view)

    @bot.command(name="생물테러준비", aliases=["바이러스구매"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def bio_prepare(ctx: commands.Context):
        user = await require_user(ctx)
        if user is None:
            return
        state = _state(user)
        if state.get("bio_last_prep") == _today():
            await ctx.send("고농축 바이러스는 하루에 한 번만 준비할 수 있습니다.")
            return
        if not _take_food(user, BIO_PREP_COST):
            await ctx.send(f"준비 비용이 부족합니다. 필요 **{BIO_PREP_COST:,}식량**")
            return
        state["bio_kits"] = int(state.get("bio_kits", 0)) + 1
        state["bio_last_prep"] = _today()
        save_data()
        await ctx.send("🧪 고농축 바이러스 주사기 **1개** 준비 완료. 대상이 수신 동의를 켜야 사용할 수 있습니다.")

    @bot.command(name="생물테러수신", aliases=["테러수신"])
    async def bio_opt_in(ctx: commands.Context, 상태: str = "상태"):
        user = await require_user(ctx)
        if user is None:
            return
        state = _state(user)
        token = 상태.strip().lower()
        if token in {"켜기", "on", "동의"}:
            state["bio_opt_in"] = True
            save_data()
        elif token in {"끄기", "off", "거부"}:
            state["bio_opt_in"] = False
            save_data()
        await ctx.send(f"🧬 생물테러 수신 동의: **{'켜짐' if state.get('bio_opt_in') else '꺼짐'}**")

    @bot.command(name="생물테러", aliases=["바이러스테러"])
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def bio_attack(ctx: commands.Context, 대상: discord.Member):
        user = await require_user(ctx)
        if user is None:
            return
        if 대상.bot or 대상.id == ctx.author.id:
            await ctx.send("봇 또는 자기 자신은 대상으로 지정할 수 없습니다.")
            return
        target = get_user(대상.id)
        if not target:
            await ctx.send("대상이 생존자로 등록되어 있지 않습니다.")
            return
        attacker_state = _state(user)
        target_state = _state(target)
        if not target_state.get("bio_opt_in"):
            await ctx.send("대상이 `!생물테러수신 켜기`로 고위험 상호작용에 동의하지 않았습니다.")
            return
        immunity = _parse_iso(target_state.get("bio_immunity_until"))
        if immunity and immunity > _now():
            await ctx.send(f"대상은 면역 보호 중입니다. 남은 시간 {_format_seconds((immunity - _now()).total_seconds())}")
            return
        if int(attacker_state.get("bio_kits", 0)) <= 0:
            await ctx.send("고농축 바이러스가 없습니다. `!생물테러준비`를 먼저 사용하세요.")
            return
        attacker_state["bio_kits"] = int(attacker_state.get("bio_kits", 0)) - 1
        success = random.random() < 0.25
        if success:
            target["infection"] = min(100, int(target.get("infection", 0)) + 18)
            target_state["bio_immunity_until"] = (_now() + timedelta(hours=24)).isoformat()
            target_state["bio_debuff_until"] = (_now() + timedelta(hours=1)).isoformat()
            text = f"☣️ {대상.mention} 감염도 +18 · 1시간 오염 표식 · 24시간 재공격 면역"
        else:
            user["infection"] = min(100, int(user.get("infection", 0)) + 10)
            text = f"🧪 운반 용기가 파손됐습니다. {ctx.author.mention} 감염도 +10"
        save_data()
        await ctx.send(text)

    # -------------------- 패치 테스트 확장 --------------------
    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v638_test(ctx: commands.Context, 모드: str = "기본"):
            checks: List[Tuple[str, bool, str]] = []
            expected = (
                "괴질탈출", "비상주파수", "지뢰찾기", "돌연변이경주", "돌연변이배팅",
                "오염문", "비상보급상자", "선물거래", "괴수투기장", "영혼결투",
                "벙커개설", "벙커참가", "벙커투표", "벙커진행", "벙커상태",
                "하이에나", "금고개설", "금고참가", "금고시작",
                "생물테러준비", "생물테러수신", "생물테러",
                "날씨", "오늘의", "무전", "내구도", "테스트", "명령어", "패치노트",
            )
            missing = [name for name in expected if bot.get_command(name) is None]
            checks.append(("v6.3.8 명령 등록", not missing, "누락 없음" if not missing else ", ".join(missing)))

            command_tokens: Dict[str, List[str]] = {}
            for command in bot.walk_commands():
                parent = getattr(command, "parent", None)
                scope = parent.qualified_name.lower() if parent is not None else "<root>"
                command_tokens.setdefault(f"{scope}:{command.name.lower()}", []).append(command.qualified_name)
                for alias in getattr(command, "aliases", []):
                    command_tokens.setdefault(f"{scope}:{str(alias).lower()}", []).append(command.qualified_name)
            duplicates = {token: owners for token, owners in command_tokens.items() if len(set(owners)) > 1}
            checks.append(("명령·별칭 충돌", not duplicates, "충돌 없음" if not duplicates else str(duplicates)[:900]))

            guide_text = "\n".join(str(entry) for cat in command_guide_categories for entry in cat.get("commands", []))
            guide_missing = [name for name in expected[:22] if f"!{name}" not in guide_text]
            checks.append(("!명령어 신규 기능 노출", not guide_missing, "전부 노출" if not guide_missing else ", ".join(guide_missing)))
            checks.append(("최상위 카테고리 수", len(command_guide_categories) <= 25, f"{len(command_guide_categories)}개"))

            try:
                equipment_path = Path(__file__).with_name("v633_equipment_crafting.py")
                source = equipment_path.read_text(encoding="utf-8")
                bad = "ebp(image)" in source or "ebp (image)" in source
                checks.append(("장비 모듈 NameError 재발 방지", not bad, "잘못된 최상위 호출 없음" if not bad else "ebp(image) 잔존"))
            except Exception as exc:
                checks.append(("장비 모듈 검사", False, f"{type(exc).__name__}: {exc}"))

            checks.append(("지뢰찾기 버튼 제한", MinesView.CELL_COUNT + 1 <= 25, f"{MinesView.CELL_COUNT + 1}/25"))
            checks.append(("난이도 제한", MIN_CHIP_BET >= 10_000 and CRATE_COST >= 5_000_000, f"최소칩 {MIN_CHIP_BET:,} · 상자 {CRATE_COST:,}"))
            checks.append(("동의형 고위험 PvP", True, "괴수/영혼 결투 수락 버튼 · 생물테러 옵트인"))
            checks.append(("영구 펫 삭제 방지", True, "패배는 부상/상처 처리, 펫 삭제 없음"))
            checks.append(("카지노 이미지 미사용", True, "신규 게임은 텍스트·버튼 UI만 사용"))

            try:
                user = get_user(ctx.author.id)
                probe = copy.deepcopy(user) if user else {}
                state = _state(probe)
                checks.append(("신규 저장 구조", isinstance(state, dict) and "crate_daily" in state, "읽기 전용 복사본 정상"))
            except Exception as exc:
                checks.append(("신규 저장 구조", False, type(exc).__name__))

            passed = sum(1 for _, ok, _ in checks if ok)
            failed = len(checks) - passed
            embed = discord.Embed(
                title=f"🧪 ABADDON v6.3.8 통합 테스트 · {passed}/{len(checks)} 통과",
                description="재화·전투·인벤토리를 바꾸지 않는 읽기 전용 검수입니다.",
                color=discord.Color.green() if failed == 0 else discord.Color.orange(),
            )
            detailed = str(모드).lower() in {"상세", "전체", "detail", "full"} or failed
            if detailed:
                for name, ok, detail in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(detail)[:1024], inline=False)
            else:
                embed.add_field(name="결과", value=f"✅ {passed} · ❌ {failed}\n상세 보기: `!테스트 상세`", inline=False)
            embed.set_footer(text="실제 버튼 클릭과 다중 사용자 이벤트는 배포 서버에서 스모크 테스트가 필요합니다.")
            await ctx.send(embed=embed)

        test_command.callback = v638_test
        test_command.help = "v6.3.8 신규 기능·중복·명령어 가이드·장비 시작 오류를 읽기 전용으로 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v638_patch_notes(ctx: commands.Context):
            embed = discord.Embed(
                title="☠️ ABADDON v6.3.8 — 하드코어 생존 아케이드",
                description="기존 카지노·PVP·랜덤박스와 겹치는 부분은 별도 규칙과 동의 절차로 분리하고, 고난도 칩/협동/위험 이벤트를 추가했습니다.",
                color=discord.Color.dark_purple(),
            )
            embed.add_field(name="🎮 타이밍·도박 게임", value="`!괴질탈출` · `!비상주파수` · `!지뢰찾기` · `!돌연변이경주` · `!선물거래`", inline=False)
            embed.add_field(name="☣️ 생존 이벤트", value="`!오염문` · `!비상보급상자` · `!하이에나` · 서버 한정 전리품과 잔해 풀", inline=False)
            embed.add_field(name="👥 협동·배신 콘텐츠", value="`!벙커개설` · `!금고개설` · 투표 숙청과 4관문 금고 침투", inline=False)
            embed.add_field(name="⚔️ 동의형 고위험 전투", value="`!괴수투기장` · `!영혼결투` · `!생물테러수신` · 일방적 강탈과 영구 펫 삭제는 차단", inline=False)
            embed.add_field(name="📚 명령어 가이드", value="신규 명령을 **하드코어 생존 / 미니게임** 최상위 카테고리에 정렬 · 중복 문구 제거", inline=False)
            embed.add_field(name="🧪 검수", value="`!테스트 상세`에서 명령/별칭 충돌, 가이드 누락, 버튼 수, NameError 재발 여부를 읽기 전용 점검", inline=False)
            embed.set_footer(text="최신 버전 v6.3.8 · 난이도 상향 · 텍스트/버튼 중심 UI")
            await ctx.send(embed=embed)

        patch.callback = v638_patch_notes
        patch.help = "ABADDON v6.3.8 하드코어 생존 아케이드 패치 내용을 확인합니다."
        patch.description = patch.help

    bot.v638_hardcore_arcade_version = VERSION
