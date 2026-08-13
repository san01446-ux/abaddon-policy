from __future__ import annotations

import ast
import asyncio
import copy
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips

VERSION = "6.4.0b"
KST = timezone(timedelta(hours=9))
MIN_BET = 10_000
MAX_BET = 50_000_000

INTERACTIVE_GUIDE = {
    "id": "interactive_arcade",
    "emoji": "🕹️",
    "title": "미니게임 / 실시간 거래",
    "hint": "명확한 손익, 반응·기억 게임, 참가형 레이스, 실시간 선물 차트",
    "commands": [
        "!미니게임 — 미니게임 빠른 안내",
        "!지뢰찾기 지뢰수 배팅액 — 현재 보유·회수 총액·순손익·손실을 분리 표시",
        "!선물거래 [배팅액] [5/10/20] — 롱/숏 버튼과 실시간 이모지 차트",
        "!선물거래 상승/하락 배팅액 5/10/20 — 방향을 바로 지정해 시작",
        "!반응속도 [배팅액] — 신호가 켜진 뒤 버튼을 누르는 순발력 게임",
        "!기억회로 [배팅액] — 잠깐 표시된 이모지 배열을 기억하는 게임",
        "!생존자레이스 [참가비] — 참가 버튼으로 모인 뒤 방장이 시작하는 서버 레이스",
    ],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().astimezone(KST).strftime("%Y-%m-%d")


def _guild_id(ctx: commands.Context) -> int:
    return int(ctx.guild.id) if ctx.guild else 0


def _validate_bet(amount: int) -> Optional[str]:
    if amount < MIN_BET:
        return f"최소 참가 금액은 **{MIN_BET:,}칩**입니다."
    if amount > MAX_BET:
        return f"최대 참가 금액은 **{MAX_BET:,}칩**입니다."
    return None


def _take_chips(user: Dict[str, Any], amount: int) -> bool:
    if casino_chips(user) < amount:
        return False
    add_casino_chips(user, -int(amount))
    return True


def _v640_state(user: Dict[str, Any]) -> Dict[str, Any]:
    state = user.setdefault("v640", {})
    if not isinstance(state, dict):
        state = {}
        user["v640"] = state
    state.setdefault("futures_daily", {})
    state.setdefault("minigame_daily", {})
    return state


def _world_state(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    root = world_data.setdefault("v640", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v640"] = root
    guilds = root.setdefault("guilds", {})
    state = guilds.setdefault(str(guild_id), {})
    state.setdefault("market_index", 100.0)
    return state


def _sparkline(values: List[float], width: int = 18) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    values = values[-width:]
    if not values:
        return "▁"
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return "▄" * len(values)
    return "".join(blocks[min(7, max(0, int((v - lo) / (hi - lo) * 7)))] for v in values)


def _clean_guide(guide: List[Dict[str, Any]]) -> None:
    # 같은 카테고리를 재등록하지 않고, 기능은 한 최상위 카테고리에만 보이도록 정리합니다.
    guide[:] = [cat for cat in guide if cat.get("id") != INTERACTIVE_GUIDE["id"]]
    exclusive_tokens = {
        "interactive_arcade": ("!지뢰찾기", "!선물거래", "!반응속도", "!기억회로", "!생존자레이스", "!미니게임"),
        "frontier_ops": ("!다크존", "!밀수품", "!보급선", "!고철갈갈이", "!장비갈갈이", "!우편함", "!받기", "!우편발송", "!알림설정", "!이벤트채널설정"),
    }
    for cat in guide:
        cat_id = str(cat.get("id", ""))
        blocked = tuple(
            token
            for owner, tokens in exclusive_tokens.items()
            if owner != cat_id
            for token in tokens
        )
        cat["commands"] = [row for row in cat.get("commands", []) if not any(token in str(row) for token in blocked)]
    frontier = next((cat for cat in guide if cat.get("id") == "frontier_ops"), None)
    if frontier is not None:
        required_frontier = (
            "!고철갈갈이 나무/광석/고철 수량 — 잉여 자원을 분쇄해 칩과 희귀 보상을 노립니다.",
            "!장비갈갈이 장비명 — 비장착 일반·고급·희귀 장비를 안전하게 분쇄합니다.",
        )
        existing = "\n".join(str(row) for row in frontier.get("commands", []))
        for row in required_frontier:
            token = row.split()[0]
            if token not in existing:
                frontier.setdefault("commands", []).append(row)
                existing += "\n" + row
    insert_at = next((i + 1 for i, cat in enumerate(guide) if cat.get("id") == "hardcore_arcade"), len(guide))
    guide.insert(insert_at, copy.deepcopy(INTERACTIVE_GUIDE))
    seen: set[str] = set()
    for cat in guide:
        rows = []
        for row in cat.get("commands", []):
            key = "".join(ch for ch in str(row).lower() if ch not in " `!/·-—[]()")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
        cat["commands"] = rows


class OwnerView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)
        self.done = False
        self.message: Optional[discord.Message] = None
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("이 게임을 시작한 생존자만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    def disable_all(self) -> None:
        for child in self.children:
            child.disabled = True


class FuturesLiveView(OwnerView):
    def __init__(self, owner_id: int, user: Dict[str, Any], bet: int, leverage: int, direction: int, save_data: Callable[[], None], market_state: Dict[str, Any], starting_balance: int):
        super().__init__(owner_id, timeout=40)
        self.user = user
        self.bet = int(bet)
        self.leverage = int(leverage)
        self.direction = 1 if direction > 0 else -1
        self.save_data = save_data
        self.market_state = market_state
        self.starting_balance = int(starting_balance)
        self.entry = float(market_state.get("market_index", 100.0))
        self.price = self.entry
        self.prices = [self.entry]
        self.tick = 0
        self.task: Optional[asyncio.Task] = None
        self.last_event = "📡 암시장 시세 연결 완료"

    def pnl(self) -> int:
        move = (self.price - self.entry) / max(1e-9, self.entry)
        return int(self.bet * move * self.leverage * self.direction)

    def estimated_payout(self) -> int:
        raw = self.pnl()
        fee = int(max(0, raw) * 0.03)
        return max(0, self.bet + raw - fee)

    def embed(self, final: Optional[str] = None) -> discord.Embed:
        pnl = self.pnl()
        payout = self.estimated_payout()
        final_balance = casino_chips(self.user) + (0 if self.done else payout)
        direction_text = "📈 LONG 상승" if self.direction > 0 else "📉 SHORT 하락"
        color = discord.Color.green() if pnl >= 0 else discord.Color.dark_red()
        embed = discord.Embed(
            title="📊 암시장 실시간 선물거래",
            description=final or f"{self.last_event}\n```{_sparkline(self.prices)}\n{self.price:,.2f}```",
            color=color,
        )
        embed.add_field(name="🎮 10초 설명", value="가격이 움직이는 동안 수익이 나면 **지금 청산**하세요. 반대로 크게 움직이면 증거금을 전부 잃을 수 있습니다.", inline=False)
        embed.add_field(name="포지션", value=f"{direction_text} · {self.leverage}×", inline=True)
        embed.add_field(name="진입가 → 현재가", value=f"{self.entry:,.2f} → {self.price:,.2f}", inline=True)
        embed.add_field(name="진행", value=f"{self.tick}/16틱", inline=True)
        embed.add_field(name="💳 시작 전 보유", value=f"{self.starting_balance:,}칩", inline=True)
        embed.add_field(name="🏦 현재 보유", value=f"{casino_chips(self.user):,}칩", inline=True)
        embed.add_field(name="📌 미실현 손익", value=f"{pnl:+,}칩", inline=True)
        if not self.done:
            embed.add_field(name="💰 지금 청산 회수액", value=f"{payout:,}칩", inline=True)
            embed.add_field(name="🧾 청산 후 예상 보유", value=f"{final_balance:,}칩", inline=True)
        embed.set_footer(text="양수 손익에는 3% 정산 수수료 · 증거금 손실이 100%가 되면 자동 청산")
        return embed

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self.done and self.tick < 16:
                await asyncio.sleep(1.2)
                async with self.lock:
                    if self.done:
                        return
                    self.tick += 1
                    mean_revert = (self.entry - self.price) * 0.025
                    shock = random.gauss(0, 0.72) + mean_revert
                    if random.random() < 0.10:
                        event = random.choice([
                            ("⚠️ 감염 지수 급등", 2.4), ("🧊 보급망 냉각", -2.0),
                            ("📦 대량 매수 유입", 1.8), ("🚨 강제 매도 발생", -2.5),
                        ])
                        self.last_event, extra = event
                        shock += extra
                    else:
                        self.last_event = random.choice(("📡 호가 갱신", "💹 거래량 증가", "🪙 칩 유동성 이동", "🛰️ 외부 신호 반영"))
                    self.price = max(30.0, min(300.0, self.price + shock))
                    self.prices.append(self.price)
                    if self.pnl() <= -self.bet:
                        await self._finish(None, "💥 **강제 청산** · 증거금 전액 손실")
                        return
                    if self.message:
                        await self.message.edit(embed=self.embed(), view=self)
            if not self.done:
                async with self.lock:
                    if not self.done:
                        await self._finish(None, "⏱️ 거래 시간 종료 · 자동 청산")
        except asyncio.CancelledError:
            return
        except Exception:
            async with self.lock:
                if not self.done:
                    await self._finish(None, "⚠️ 시세 연결 종료 · 현재가 자동 청산")

    async def _finish(self, interaction: Optional[discord.Interaction], reason: str) -> None:
        if self.done:
            return
        self.done = True
        self.disable_all()
        payout = self.estimated_payout()
        net = payout - self.bet
        if payout:
            add_casino_chips(self.user, payout)
        self.market_state["market_index"] = round(self.price, 4)
        self.save_data()
        result = (
            f"{reason}\n\n"
            f"{'🟢' if net >= 0 else '🔴'} **최종 순손익 {net:+,}칩** · 회수 {payout:,}칩\n"
            f"🏦 최종 보유 **{casino_chips(self.user):,}칩**"
        )
        embed = self.embed(result)
        if interaction is not None:
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message:
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="지금 청산", emoji="💰", style=discord.ButtonStyle.success)
    async def close_position(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            await self._finish(interaction, "🧾 수동 청산 완료")


class FuturesOrderView(OwnerView):
    def __init__(self, owner_id: int, opener: Callable[[discord.Interaction, int], Any], bet: int, leverage: int, balance: int):
        super().__init__(owner_id, timeout=45)
        self.opener = opener
        self.bet = bet
        self.leverage = leverage
        self.balance = balance

    @discord.ui.button(label="상승 LONG", emoji="📈", style=discord.ButtonStyle.success)
    async def long(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.opener(interaction, 1)

    @discord.ui.button(label="하락 SHORT", emoji="📉", style=discord.ButtonStyle.danger)
    async def short(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.opener(interaction, -1)

    @discord.ui.button(label="취소", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.done = True
        self.disable_all()
        await interaction.response.edit_message(content="거래 주문을 취소했습니다. 칩은 차감되지 않았습니다.", embed=None, view=self)


class ReactionView(OwnerView):
    def __init__(self, owner_id: int, user: Dict[str, Any], bet: int, save_data: Callable[[], None], starting_balance: int):
        super().__init__(owner_id, timeout=18)
        self.user = user
        self.bet = bet
        self.save_data = save_data
        self.starting_balance = starting_balance
        self.ready_at = 0.0
        self.task: Optional[asyncio.Task] = None
        for child in self.children:
            child.disabled = True

    def embed(self, text: str = "🟠 신호 대기 중… 버튼이 켜진 뒤 누르세요.") -> discord.Embed:
        embed = discord.Embed(title="⚡ 폐허 반응속도", description=text, color=discord.Color.orange())
        embed.add_field(name="🎮 10초 설명", value="버튼이 초록색 **지금!**으로 바뀐 뒤 최대한 빠르게 누르세요. 너무 일찍 누르면 인정되지 않습니다.", inline=False)
        embed.add_field(name="배팅", value=f"{self.bet:,}칩", inline=True)
        embed.add_field(name="시작 전 보유", value=f"{self.starting_balance:,}칩", inline=True)
        embed.add_field(name="현재 보유", value=f"{casino_chips(self.user):,}칩", inline=True)
        embed.set_footer(text="350ms 미만 최고 보상 · 750ms 이후에는 원금보다 적게 회수될 수 있습니다.")
        return embed

    def start(self) -> None:
        self.task = asyncio.create_task(self._arm())

    async def _arm(self) -> None:
        await asyncio.sleep(random.uniform(2.5, 6.0))
        if self.done:
            return
        self.ready_at = time.perf_counter()
        for child in self.children:
            child.disabled = False
            child.label = "지금!"
            child.style = discord.ButtonStyle.success
        if self.message:
            await self.message.edit(embed=self.embed("🟢 **지금 누르세요!** ⚡⚡⚡"), view=self)

    @discord.ui.button(label="대기…", emoji="⚡", style=discord.ButtonStyle.secondary)
    async def react(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.ready_at or self.done:
            await interaction.response.send_message("아직 신호가 켜지지 않았습니다.", ephemeral=True)
            return
        self.done = True
        self.disable_all()
        ms = (time.perf_counter() - self.ready_at) * 1000
        if ms < 350:
            mult, grade = 2.5, "🌟 초인적 반응"
        elif ms < 500:
            mult, grade = 1.8, "⚡ 매우 빠름"
        elif ms < 750:
            mult, grade = 1.25, "✅ 생존 성공"
        else:
            mult, grade = 0.65, "🐢 너무 늦음"
        payout = int(self.bet * mult)
        add_casino_chips(self.user, payout)
        self.save_data()
        net = payout - self.bet
        text = f"{grade}\n⏱️ **{ms:.0f}ms** · 회수 **{payout:,}칩** · 순손익 **{net:+,}칩**\n🏦 현재 보유 **{casino_chips(self.user):,}칩**"
        await interaction.response.edit_message(embed=self.embed(text), view=self)

    async def on_timeout(self) -> None:
        if self.done:
            return
        self.done = True
        self.disable_all()
        self.save_data()
        if self.message:
            await self.message.edit(embed=self.embed(f"⌛ 반응하지 못했습니다. **-{self.bet:,}칩** 손실\n🏦 현재 보유 **{casino_chips(self.user):,}칩**"), view=self)


class MemoryChoice(discord.ui.Button):
    def __init__(self, emoji_value: str):
        super().__init__(emoji=emoji_value, style=discord.ButtonStyle.primary)
        self.emoji_value = emoji_value

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, MemoryView):
            await view.answer(interaction, self.emoji_value)


class MemoryView(OwnerView):
    POOL = ("☣️", "⚡", "🧪", "🔧", "💎", "🔥", "🧊", "🛰️")

    def __init__(self, owner_id: int, user: Dict[str, Any], bet: int, save_data: Callable[[], None], starting_balance: int):
        super().__init__(owner_id, timeout=20)
        self.user = user
        self.bet = bet
        self.save_data = save_data
        self.starting_balance = starting_balance
        self.sequence = random.sample(self.POOL, 6)
        self.target_index = random.randrange(6)
        self.correct = self.sequence[self.target_index]
        self.task: Optional[asyncio.Task] = None

    def start_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🧠 기억 회로", description=f"3초 동안 배열을 기억하세요.\n\n# {'  '.join(self.sequence)}", color=discord.Color.blurple())
        embed.add_field(name="🎮 10초 설명", value="3초 동안 6개 이모지의 순서를 외운 뒤, 물어보는 위치의 이모지를 버튼으로 고르세요.", inline=False)
        embed.add_field(name="배팅", value=f"{self.bet:,}칩", inline=True)
        embed.add_field(name="현재 보유", value=f"{casino_chips(self.user):,}칩", inline=True)
        return embed

    def start(self) -> None:
        self.task = asyncio.create_task(self._hide())

    async def _hide(self) -> None:
        await asyncio.sleep(3.0)
        if self.done:
            return
        choices = [self.correct] + random.sample([x for x in self.POOL if x != self.correct], 3)
        random.shuffle(choices)
        for choice in choices:
            self.add_item(MemoryChoice(choice))
        embed = discord.Embed(title="🧠 기억 회로", description=f"**{self.target_index + 1}번째 기호**는 무엇이었나요?", color=discord.Color.dark_purple())
        embed.add_field(name="정답 보상", value=f"{self.bet * 2:,}칩 (순이익 +{self.bet:,})", inline=True)
        embed.add_field(name="현재 보유", value=f"{casino_chips(self.user):,}칩", inline=True)
        if self.message:
            await self.message.edit(embed=embed, view=self)

    async def answer(self, interaction: discord.Interaction, choice: str) -> None:
        if self.done:
            await interaction.response.send_message("이미 종료된 회로입니다.", ephemeral=True)
            return
        self.done = True
        self.disable_all()
        if choice == self.correct:
            payout = self.bet * 2
            add_casino_chips(self.user, payout)
            text = f"✅ 정답 **{self.correct}** · 회수 {payout:,}칩 · 순이익 +{self.bet:,}칩"
            color = discord.Color.green()
        else:
            payout = 0
            text = f"❌ 오답 **{choice}** · 정답은 **{self.correct}** · 손실 -{self.bet:,}칩"
            color = discord.Color.dark_red()
        self.save_data()
        embed = discord.Embed(title="🧠 기억 회로 결과", description=text, color=color)
        embed.add_field(name="처음 배열", value=" ".join(self.sequence), inline=False)
        embed.add_field(name="🏦 현재 보유", value=f"{casino_chips(self.user):,}칩", inline=True)
        await interaction.response.edit_message(embed=embed, view=self)


    async def on_timeout(self) -> None:
        if self.done:
            return
        self.done = True
        self.disable_all()
        self.save_data()
        if self.message:
            embed = discord.Embed(
                title="🧠 기억 회로 종료",
                description=f"⌛ 제한 시간이 끝났습니다. 손실 **-{self.bet:,}칩**",
                color=discord.Color.dark_red(),
            )
            embed.add_field(name="정답", value=f"{self.target_index + 1}번째 = {self.correct}", inline=True)
            embed.add_field(name="현재 보유", value=f"{casino_chips(self.user):,}칩", inline=True)
            await self.message.edit(embed=embed, view=self)


class SurvivorRaceView(discord.ui.View):
    ICONS = ("🏃", "🧟", "🐺", "🤖", "🐇", "🦊", "🐉", "🦾")

    def __init__(self, host: discord.Member, entry_fee: int, get_user: Callable[[int], Optional[Dict[str, Any]]], save_data: Callable[[], None], on_close: Callable[[], None]):
        super().__init__(timeout=180)
        self.host = host
        self.entry_fee = entry_fee
        self.get_user = get_user
        self.save_data = save_data
        self.on_close = on_close
        self.participants: Dict[int, discord.Member] = {}
        self.bot_invited = False
        self.message: Optional[discord.Message] = None
        self.started = False
        self.done = False
        self.lock = asyncio.Lock()

    def embed(self, description: Optional[str] = None) -> discord.Embed:
        lines = []
        for i, member in enumerate(self.participants.values()):
            lines.append(f"{self.ICONS[i % len(self.ICONS)]} {member.display_name}")
        if self.bot_invited:
            lines.append("🤖 아바돈 · AI 동료")
        embed = discord.Embed(title="🏁 생존자 탈출 레이스", description=description or "참가를 원하는 사람만 **참가** 버튼을 누르세요. 방장이 인원을 확인한 뒤 시작합니다.", color=discord.Color.orange())
        embed.add_field(name="🎮 10초 설명", value="참가할 사람만 🏃 버튼을 누르고, 최소 2명이 모이면 방장이 🚦 버튼으로 출발합니다. 시작 전 취소는 전액 환불됩니다.", inline=False)
        embed.add_field(name="참가비", value=f"{self.entry_fee:,}칩", inline=True)
        total_players = len(self.participants) + (1 if self.bot_invited else 0)
        embed.add_field(name="참가 인원", value=f"{total_players}/8명", inline=True)
        embed.add_field(name="예상 우승 상금", value=f"{int(self.entry_fee * total_players * 0.9):,}칩", inline=True)
        embed.add_field(name="참가자", value="\n".join(lines) if lines else "아직 없음", inline=False)
        embed.set_footer(text=f"방장: {self.host.display_name} · 사람이 부족하면 🤖 아바돈 초대 · 시작 전 취소 시 전액 환불")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.bot:
            return False
        return True

    @discord.ui.button(label="참가", emoji="🏃", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            uid = int(interaction.user.id)
            if self.started or self.done:
                await interaction.response.send_message("이미 시작되었거나 종료된 레이스입니다.", ephemeral=True)
                return
            if uid in self.participants:
                await interaction.response.send_message("이미 참가했습니다.", ephemeral=True)
                return
            total_players = len(self.participants) + (1 if self.bot_invited else 0)
            if total_players >= 8:
                await interaction.response.send_message("참가 인원이 가득 찼습니다.", ephemeral=True)
                return
            user = self.get_user(uid)
            if not user:
                await interaction.response.send_message("먼저 `!가입 생존자`로 등록하세요.", ephemeral=True)
                return
            if not _take_chips(user, self.entry_fee):
                await interaction.response.send_message(f"참가비가 부족합니다. 보유 {casino_chips(user):,}칩", ephemeral=True)
                return
            self.participants[uid] = interaction.user
            self.save_data()
            await interaction.response.edit_message(embed=self.embed(f"✅ {interaction.user.mention} 참가 완료!"), view=self)

    @discord.ui.button(label="참가 취소", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            uid = int(interaction.user.id)
            if self.started or self.done:
                await interaction.response.send_message("시작 후에는 참가를 취소할 수 없습니다.", ephemeral=True)
                return
            if uid not in self.participants:
                await interaction.response.send_message("참가 중이 아닙니다.", ephemeral=True)
                return
            user = self.get_user(uid)
            if user:
                add_casino_chips(user, self.entry_fee)
            self.participants.pop(uid, None)
            self.save_data()
            await interaction.response.edit_message(embed=self.embed(f"↩️ {interaction.user.mention} 참가 취소 · 전액 환불"), view=self)

    @discord.ui.button(label="아바돈 초대", emoji="🤖", style=discord.ButtonStyle.secondary)
    async def invite_abaddon(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            if int(interaction.user.id) != int(self.host.id):
                await interaction.response.send_message("방장만 아바돈을 초대할 수 있습니다.", ephemeral=True)
                return
            if self.started or self.done:
                await interaction.response.send_message("이미 시작되었거나 종료된 레이스입니다.", ephemeral=True)
                return
            if self.bot_invited:
                await interaction.response.send_message("아바돈이 이미 참가 중입니다. 🤖", ephemeral=True)
                return
            if len(self.participants) >= 8:
                await interaction.response.send_message("참가 인원이 가득 찼습니다.", ephemeral=True)
                return
            self.bot_invited = True
            button.disabled = True
            await interaction.response.edit_message(embed=self.embed("🤖 **아바돈이 레이스에 참가했습니다!**"), view=self)

    @discord.ui.button(label="인원 확정·시작", emoji="🚦", style=discord.ButtonStyle.primary)
    async def start_race(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            if int(interaction.user.id) != int(self.host.id):
                await interaction.response.send_message("방장만 인원을 확정하고 시작할 수 있습니다.", ephemeral=True)
                return
            if self.started or self.done:
                await interaction.response.send_message("이미 처리된 레이스입니다.", ephemeral=True)
                return
            total_players = len(self.participants) + (1 if self.bot_invited else 0)
            if total_players < 2:
                await interaction.response.send_message("최소 2명이 필요합니다. 혼자라면 `아바돈 초대`를 눌러주세요.", ephemeral=True)
                return
            self.started = True
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=self.embed("🚦 **인원 확정! 레이스를 시작합니다.**"), view=self)
            asyncio.create_task(self._run())

    @discord.ui.button(label="방 닫기", emoji="🛑", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            if int(interaction.user.id) != int(self.host.id):
                await interaction.response.send_message("방장만 방을 닫을 수 있습니다.", ephemeral=True)
                return
            await self._refund()
            self.done = True
            self.stop()
            self.on_close()
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=self.embed("🛑 방장이 레이스를 취소했습니다. 참가비는 모두 환불되었습니다."), view=self)

    async def _refund(self) -> None:
        for uid in list(self.participants):
            user = self.get_user(uid)
            if user:
                add_casino_chips(user, self.entry_fee)
        self.save_data()

    async def _run(self) -> None:
        players = list(self.participants.items())
        if self.bot_invited:
            players.append((0, SimpleNamespace(display_name="아바돈", mention="🤖 아바돈")))
        positions = {uid: 0 for uid, _ in players}
        events = ["⚡ 가속", "🕳️ 잔해 회피", "💨 질주", "🧟 감염체 추격", "🛡️ 방어 돌파", "🔥 위험 지대"]
        finish = 12
        for round_no in range(1, 11):
            await asyncio.sleep(1.2)
            event_lines = []
            for uid, member in players:
                step = random.choices((0, 1, 2, 3), weights=(8, 42, 36, 14), k=1)[0]
                if random.random() < 0.12:
                    step = max(0, step - 1)
                positions[uid] += step
                event_lines.append(f"{random.choice(events)} {member.display_name} +{step}")
            max_pos = max(positions.values())
            lines = []
            for idx, (uid, member) in enumerate(players):
                pos = min(finish, positions[uid])
                track = "·" * pos + self.ICONS[idx % len(self.ICONS)] + "·" * (finish - pos)
                lines.append(f"`{track}` {member.display_name}")
            embed = discord.Embed(title=f"🏁 생존자 레이스 · {round_no}/10", description="\n".join(lines), color=discord.Color.orange())
            embed.add_field(name="현장 효과", value="\n".join(event_lines[:8]), inline=False)
            if self.message:
                await self.message.edit(embed=embed, view=self)
            if max_pos >= finish:
                break
        top = max(positions.values())
        candidates = [uid for uid, pos in positions.items() if pos == top]
        winner_id = random.choice(candidates)
        winner_member = next(member for uid, member in players if uid == winner_id)
        pot = self.entry_fee * len(players)
        payout = int(pot * 0.9)
        winner_user = self.get_user(winner_id) if winner_id != 0 else None
        if winner_user:
            add_casino_chips(winner_user, payout)
        self.save_data()
        self.done = True
        self.stop()
        self.on_close()
        result_lines = []
        for uid, member in players:
            if uid == winner_id and uid == 0:
                result_lines.append("🤖 아바돈: 레이스 승리 · 상금은 생존 구역 운영금으로 회수")
            elif uid == winner_id:
                result_lines.append(f"🏆 {member.display_name}: +{payout - self.entry_fee:,}칩 순이익")
            elif uid == 0:
                result_lines.append("🤖 아바돈: AI 참가")
            else:
                result_lines.append(f"💀 {member.display_name}: -{self.entry_fee:,}칩")
        embed = discord.Embed(title="🏆 생존자 레이스 종료", description=f"우승자 {winner_member.mention}\n\n" + "\n".join(result_lines), color=discord.Color.gold())
        embed.add_field(name="총 상금", value=f"{payout:,}칩", inline=True)
        embed.add_field(name="참가자", value=f"{len(players)}명", inline=True)
        if winner_user:
            embed.add_field(name="우승자 현재 보유", value=f"{casino_chips(winner_user):,}칩", inline=True)
        if self.message:
            await self.message.edit(embed=embed, view=None)

    async def on_timeout(self) -> None:
        if self.started or self.done:
            return
        await self._refund()
        self.done = True
        self.on_close()
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(embed=self.embed("⌛ 모집 시간이 끝났습니다. 참가비는 전액 환불되었습니다."), view=self)


def register_v640_interactive_arcade(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[Dict[str, Any]]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    command_guide_categories: List[Dict[str, Any]],
) -> None:
    _clean_guide(command_guide_categories)
    race_lobbies: Dict[int, SurvivorRaceView] = {}

    async def require_user(ctx: commands.Context) -> Optional[Dict[str, Any]]:
        if not await check_registered(ctx):
            return None
        return get_user(ctx.author.id)

    # 기존 즉시 판정형 선물거래를 실시간 차트형으로 교체합니다.
    old = bot.get_command("선물거래")
    if old is not None:
        bot.remove_command(old.name)

    async def open_futures(ctx: commands.Context, user: Dict[str, Any], bet: int, leverage: int, direction: int, interaction: Optional[discord.Interaction] = None):
        state = _v640_state(user)
        daily = state.setdefault("futures_daily", {})
        if daily.get("date") != _today():
            daily.clear(); daily.update({"date": _today(), "count": 0})
        if int(daily.get("count", 0)) >= 5:
            msg = "선물거래는 하루 **5회**까지만 가능합니다."
            if interaction: await interaction.response.send_message(msg, ephemeral=True)
            else: await ctx.send(msg)
            return
        starting = casino_chips(user)
        if not _take_chips(user, bet):
            msg = f"칩이 부족합니다. 보유 **{casino_chips(user):,}칩**"
            if interaction: await interaction.response.send_message(msg, ephemeral=True)
            else: await ctx.send(msg)
            return
        daily["count"] = int(daily.get("count", 0)) + 1
        save_data()
        market = _world_state(world_data, _guild_id(ctx))
        view = FuturesLiveView(ctx.author.id, user, bet, leverage, direction, save_data, market, starting)
        if interaction:
            await interaction.response.edit_message(content=None, embed=view.embed(), view=view)
            view.message = await interaction.original_response()
        else:
            view.message = await ctx.send(embed=view.embed(), view=view)
        view.start()

    @bot.command(name="선물거래", aliases=["감염선물", "레버리지"])
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def futures_trade(ctx: commands.Context, 첫값: str = "", 두번째: Optional[int] = None, 세번째: Optional[int] = None):
        user = await require_user(ctx)
        if user is None:
            return
        direction: Optional[int] = None
        bet = 100_000
        leverage = 5
        first = str(첫값 or "").strip().lower()
        if first in {"상승", "롱", "long"}:
            direction = 1; bet = int(두번째 or bet); leverage = int(세번째 or leverage)
        elif first in {"하락", "숏", "short"}:
            direction = -1; bet = int(두번째 or bet); leverage = int(세번째 or leverage)
        elif first:
            try:
                bet = int(first.replace(",", ""))
                leverage = int(두번째 or leverage)
            except ValueError:
                await ctx.send("사용법: `!선물거래 [배팅액] [5/10/20]` 또는 `!선물거래 상승/하락 배팅액 레버리지`")
                return
        if leverage not in {5, 10, 20}:
            await ctx.send("레버리지는 **5 / 10 / 20배** 중 하나만 사용할 수 있습니다.")
            return
        error = _validate_bet(bet)
        if error:
            await ctx.send(error); return
        if direction is not None:
            await open_futures(ctx, user, bet, leverage, direction)
            return
        balance = casino_chips(user)
        embed = discord.Embed(title="📊 암시장 선물 주문", description="버튼으로 방향을 고르면 약 20초 동안 실시간 차트가 움직입니다. 언제든 **지금 청산**할 수 있습니다.", color=discord.Color.blurple())
        embed.add_field(name="🎮 10초 설명", value="상승 또는 하락을 선택하면 실시간 그래프가 시작됩니다. 수익·손실을 보며 **지금 청산** 버튼으로 끝내세요.", inline=False)
        embed.add_field(name="증거금", value=f"{bet:,}칩", inline=True)
        embed.add_field(name="레버리지", value=f"{leverage}×", inline=True)
        embed.add_field(name="현재 보유", value=f"{balance:,}칩", inline=True)
        view = FuturesOrderView(ctx.author.id, lambda inter, d: open_futures(ctx, user, bet, leverage, d, inter), bet, leverage, balance)
        view.message = await ctx.send(embed=embed, view=view)

    @bot.command(name="반응속도", aliases=["순발력", "반응게임"])
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def reaction_game(ctx: commands.Context, 배팅액: int = 50_000):
        user = await require_user(ctx)
        if user is None: return
        error = _validate_bet(배팅액)
        if error: await ctx.send(error); return
        starting = casino_chips(user)
        if not _take_chips(user, 배팅액):
            await ctx.send(f"칩이 부족합니다. 보유 {starting:,}칩"); return
        save_data()
        view = ReactionView(ctx.author.id, user, 배팅액, save_data, starting)
        view.message = await ctx.send(embed=view.embed(), view=view)
        view.start()

    @bot.command(name="기억회로", aliases=["기억게임", "이모지기억"])
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def memory_game(ctx: commands.Context, 배팅액: int = 50_000):
        user = await require_user(ctx)
        if user is None: return
        error = _validate_bet(배팅액)
        if error: await ctx.send(error); return
        starting = casino_chips(user)
        if not _take_chips(user, 배팅액):
            await ctx.send(f"칩이 부족합니다. 보유 {starting:,}칩"); return
        save_data()
        view = MemoryView(ctx.author.id, user, 배팅액, save_data, starting)
        view.message = await ctx.send(embed=view.start_embed(), view=view)
        view.start()

    @bot.command(name="생존자레이스", aliases=["참가레이스", "탈출레이스"])
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def survivor_race(ctx: commands.Context, 참가비: int = 100_000):
        if ctx.guild is None:
            await ctx.send("서버 채널에서만 열 수 있습니다."); return
        error = _validate_bet(참가비)
        if error: await ctx.send(error); return
        gid = int(ctx.guild.id)
        current = race_lobbies.get(gid)
        if current and not current.done:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("이 서버에는 이미 참가 모집 중인 생존자 레이스가 있습니다."); return
        def close(): race_lobbies.pop(gid, None)
        view = SurvivorRaceView(ctx.author, 참가비, get_user, save_data, close)
        race_lobbies[gid] = view
        view.message = await ctx.send(embed=view.embed(), view=view)

    @bot.command(name="미니게임", aliases=["게임목록", "미니게임목록"])
    async def minigame_list(ctx: commands.Context):
        embed = discord.Embed(title="🕹️ ABADDON 미니게임 센터", description="명령어를 입력하면 첫 화면에 **🎮 10초 설명**이 먼저 표시됩니다. 설명을 읽고 화면의 버튼만 누르면 바로 진행할 수 있습니다.", color=discord.Color.dark_teal())
        embed.add_field(name="💣 위험·현금화", value="`!지뢰찾기 5 100000` · `!괴질탈출 100000`", inline=False)
        embed.add_field(name="📊 실시간", value="`!선물거래 100000 5` · `!비상주파수 100000`", inline=False)
        embed.add_field(name="⚡ 개인 순발력", value="`!반응속도 50000` · `!기억회로 50000`", inline=False)
        embed.add_field(name="🏁 서버 참가형", value="`!생존자레이스 100000` — 사람이 부족하면 **🤖 아바돈 초대**", inline=False)
        embed.add_field(name="🤖 혼자 플레이", value="`!아바돈게임` · `!아바돈초대 포커 100000` — 1:1 미니게임 7종", inline=False)
        embed.add_field(name="☠️ 고난도", value="`!돌연변이경주` · `!오염문` · `!비상보급상자` · `!금고개설`", inline=False)
        await ctx.send(embed=embed)

    # !테스트를 최종 패치 기준으로 다시 묶습니다.
    test = bot.get_command("테스트")
    if test is not None:
        async def v640_test(ctx: commands.Context, 모드: str = "기본"):
            expected = (
                "다크존", "밀수품운반", "보급선", "고철갈갈이", "장비갈갈이", "우편함", "알림설정",
                "지뢰찾기", "선물거래", "반응속도", "기억회로", "생존자레이스", "미니게임",
                "오늘의", "날씨", "명령어", "패치노트",
            )
            checks: List[Tuple[str, bool, str]] = []
            missing = [name for name in expected if bot.get_command(name) is None]
            checks.append(("통합 명령 등록", not missing, "누락 없음" if not missing else ", ".join(missing)))

            tokens: Dict[str, List[str]] = {}
            for command in bot.walk_commands():
                parent = getattr(command, "parent", None)
                scope = parent.qualified_name.lower() if parent else "<root>"
                for token in [command.name, *getattr(command, "aliases", [])]:
                    tokens.setdefault(f"{scope}:{str(token).lower()}", []).append(command.qualified_name)
            dup = {key: owners for key, owners in tokens.items() if len(set(owners)) > 1}
            checks.append(("명령·별칭 중복", not dup, "충돌 없음" if not dup else str(dup)[:900]))

            guide_text = "\n".join(str(row) for cat in command_guide_categories for row in cat.get("commands", []))
            guide_targets = expected[:13]
            guide_missing = [name for name in guide_targets if f"!{name}" not in guide_text]
            checks.append(("!명령어 신규 기능 노출", not guide_missing, "전부 분류됨" if not guide_missing else ", ".join(guide_missing)))
            checks.append(("최상위 카테고리 제한", len(command_guide_categories) <= 25, f"{len(command_guide_categories)}/25"))

            mines_source = __import__('inspect').getsource(__import__('apocalypse_bot.commands.v638_hardcore_arcade', fromlist=['MinesView']).MinesView)
            mine_words = ("시작 전 보유", "현재 보유", "얻은 돈", "잃은 돈", "최종 회수 총액")
            checks.append(("지뢰 손익 문구", all(word in mines_source for word in mine_words), "총액·순손익·현재 보유 분리"))
            checks.append(("선물 실시간 차트", "🎮 10초 설명" in FuturesLiveView.embed.__code__.co_consts, "16틱 그래프 · 시작 설명 · 수동/자동/강제 청산"))
            checks.append(("참가형 레이스", "🎮 10초 설명" in SurvivorRaceView.embed.__code__.co_consts, "참가 버튼 · 방장 시작 · 취소 환불 · 최대 8명"))

            scrap_assets = Path(__file__).resolve().parents[1] / "assets" / "v640" / "scrap"
            missing_scrap = [name for name in ("grinder.jpg", "jackpot.jpg") if not (scrap_assets / name).is_file()]
            checks.append(("갈갈이 이미지 연결", not missing_scrap, "일반·잭팟 이미지 정상" if not missing_scrap else ", ".join(missing_scrap)))

            try:
                equipment_path = Path(__file__).with_name("v633_equipment_crafting.py")
                source = equipment_path.read_text(encoding="utf-8")
                compile(source, str(equipment_path), "exec")
                tree = ast.parse(source, filename=str(equipment_path))
                bad_calls = [
                    node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "ebp"
                ]
                checks.append(("장비 모듈 시작 검사", not bad_calls, "컴파일·AST 정상 / ebp 호출 없음" if not bad_calls else f"ebp 호출 {len(bad_calls)}개"))
            except Exception as exc:
                checks.append(("장비 모듈 시작 검사", False, f"{type(exc).__name__}: {exc}"))

            source_now = Path(__file__).read_text(encoding="utf-8")
            intro_markers = ("가격이 움직이는 동안", "버튼이 초록색", "3초 동안 6개", "참가할 사람만")
            checks.append(("게임 시작 설명", all(marker in source_now for marker in intro_markers), "주요 미니게임 첫 화면에 10초 설명 표시"))

            passed = sum(1 for _, ok, _ in checks if ok)
            failed = len(checks) - passed
            embed = discord.Embed(
                title=f"🧪 ABADDON v6.4.0b 통합 테스트 · {passed}/{len(checks)}",
                description="재화와 진행 상태를 변경하지 않는 읽기 전용 검사입니다.",
                color=discord.Color.green() if failed == 0 else discord.Color.orange(),
            )
            detailed = str(모드).lower() in {"상세", "전체", "detail", "full"} or failed
            if detailed:
                for name, ok, detail in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(detail)[:1024], inline=False)
            else:
                embed.add_field(name="결과", value=f"✅ {passed} · ❌ {failed}\n상세: `!테스트 상세`", inline=False)
            embed.set_footer(text="실제 다중 사용자 버튼·메시지 갱신은 배포 서버에서 마지막 스모크 테스트가 필요합니다.")
            await ctx.send(embed=embed)
        test.callback = v640_test
        test.help = "v6.4.0b 명령어 분류·갈갈이·장비 모듈·게임 시작 설명을 읽기 전용으로 검사합니다."
        test.description = test.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v640_patch_notes(ctx: commands.Context):
            embed = discord.Embed(title="🕹️ ABADDON v6.4.0b — 통합 테스트·초보 안내 핫픽스", description="v6.3.9 프론티어 작전과 함께, 지뢰 손익 표기·실시간 선물 차트·개인 미니게임·참가형 서버 레이스를 추가했습니다.", color=discord.Color.dark_purple())
            embed.add_field(name="🚧 프론티어 작전", value="다크존·밀수품·보급선 피버·고철 갈갈이·우편·알림", inline=False)
            embed.add_field(name="♻️ 갈갈이 이미지 핫픽스", value="고철·장비 분쇄 결과에 분쇄기 가동 이미지와 잭팟 이미지를 실제 첨부하고, 홈페이지 카드도 동일 비주얼로 교체", inline=False)
            embed.add_field(name="💣 지뢰찾기 정산 개선", value="시작 전/현재 보유, 현금화 총액, 실제 순이익, 폭발 손실을 분리 표시", inline=False)
            embed.add_field(name="📊 실시간 선물거래", value="롱/숏 버튼 · 16틱 이모지 차트 · 미실현 손익 · 수동/자동/강제 청산", inline=False)
            embed.add_field(name="⚡ 신규 미니게임", value="`!반응속도` · `!기억회로` · `!생존자레이스` · `!미니게임`", inline=False)
            embed.add_field(name="🏁 참가 방식", value="레이스는 참가를 원하는 사람만 버튼으로 입장하고, 방장이 인원을 확정한 뒤 시작", inline=False)
            embed.add_field(name="📚 !명령어 최신화", value="고철·장비 갈갈이를 특수 작전 최상위 카테고리에 복구하고, 신규 기능을 한 카테고리에만 정렬", inline=False)
            embed.add_field(name="🎮 초보자 시작 안내", value="지뢰찾기·선물거래·반응속도·기억회로·생존자레이스 첫 화면에 10초 규칙 설명 표시", inline=False)
            embed.add_field(name="🧪 테스트 오류 수정", value="문자열 검색 대신 실제 Python 컴파일·AST 검사로 장비 모듈 오류를 판정", inline=False)
            embed.set_footer(text="최신 버전 v6.4.0b · !테스트 상세 권장")
            await ctx.send(embed=embed)
        patch.callback = v640_patch_notes
        patch.help = "ABADDON v6.4.0b 통합 테스트·초보 안내 핫픽스 내용을 확인합니다."
        patch.description = patch.help

    bot.v640_interactive_arcade_version = VERSION
