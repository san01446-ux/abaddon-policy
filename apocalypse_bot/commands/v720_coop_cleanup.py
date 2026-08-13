from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import _card_text, _deck, _poker_score

VERSION = "7.8.0"
PATCH_DATE = "2026-08-03"
MAX_AI_BET = 5_000_000
MAX_AI_FOOD_BET = 10_000_000




CURRENCY_ALIASES = {
    "칩": "chips", "카지노칩": "chips", "chip": "chips", "chips": "chips",
    "식량": "food", "돈": "food", "재화": "food", "food": "food",
}


def _currency_key(value: str) -> Optional[str]:
    return CURRENCY_ALIASES.get(str(value or "").strip().casefold())


def _currency_label(currency: str) -> str:
    return "칩" if currency == "chips" else "식량"


def _currency_balance(user: Dict[str, Any], currency: str) -> int:
    if currency == "chips":
        return casino_chips(user)
    return max(0, int(user.get("balance", 0) or 0))


def _add_currency(user: Dict[str, Any], currency: str, amount: int) -> None:
    amount = int(amount or 0)
    if currency == "chips":
        add_casino_chips(user, amount)
        return
    before = max(0, int(user.get("balance", 0) or 0))
    user["balance"] = max(0, before + amount)


def _parse_wager(first: str, second: int = 0) -> Tuple[Optional[str], int, Optional[str]]:
    raw = str(first or "0").strip()
    try:
        # 기존 문법: !아바돈게임 1000 / !아바돈초대 포커 1000
        amount = int(raw.replace(",", ""))
        return "chips", max(0, amount), None
    except ValueError:
        pass
    currency = _currency_key(raw)
    if currency is None:
        return None, 0, "재화는 `칩` 또는 `식량`으로 입력해주세요."
    amount = max(0, int(second or 0))
    maximum = MAX_AI_BET if currency == "chips" else MAX_AI_FOOD_BET
    if amount > maximum:
        return None, 0, f"최대 베팅은 **{maximum:,}{_currency_label(currency)}**입니다."
    return currency, amount, None


def _root(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault("v720_coop_cleanup", {})
    root.setdefault("guilds", {})
    root.setdefault("ai_stats", {})
    return root


def _guild_settings(world_data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    settings = _root(world_data)["guilds"].setdefault(str(guild_id), {})
    settings.setdefault("patch_auto", True)
    settings.setdefault("patch_channel_id", 0)
    settings.setdefault("posted_versions", [])
    return settings


def _patch_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🚨 ABADDON v7.8.0 — 서버 공동 재난·파밍 연출 안정화",
        description=(
            "서버 전체가 역할 수행과 자원 납품으로 재난을 해결하는 공동 콘텐츠를 추가했습니다. "
            "파밍에는 출발·이동·위험·발견·복귀 진행 효과를 넣고 운영 점검 오류를 수정했습니다."
        ),
        colour=discord.Colour.from_rgb(195, 74, 54),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="🚨 서버 공동 재난", value="정전·식수 오염·감염체 습격·통신망 붕괴·화재·독성 안개", inline=False)
    embed.add_field(name="🧑‍🚒 공동 대응", value="정찰·구조·수리·방어 역할 · 자원 납품 · 기여도·개인 보상·서버 버프", inline=False)
    embed.add_field(name="🧭 파밍 진행 효과", value="🚪 출발 → 🗺️ 이동 → 📡 탐색 → ⚠️ 위험/✨ 발견 → 📦 복귀", inline=False)
    embed.add_field(name="🛠️ 오류 수정", value="시스템점검 datetime 참조 안전화 · 테스트 상세 구현 누락 복구", inline=False)
    embed.add_field(name="🧪 검사 정책", value="`!테스트 상세`는 직전 패치에서 추가·수정된 기능만 검사", inline=False)
    embed.add_field(name="🧹 데이터 정책", value="기존 기능·기록·이미지 폐기 0건", inline=False)
    embed.set_footer(text=f"ABADDON v{VERSION} · {PATCH_DATE} · 공개 확률 수치 없음")
    return embed


def _can_send(channel: Any, guild: discord.Guild) -> bool:
    if not isinstance(channel, discord.TextChannel) or guild.me is None:
        return False
    perms = channel.permissions_for(guild.me)
    return perms.view_channel and perms.send_messages and perms.embed_links


def _find_patch_channel(guild: discord.Guild, settings: Dict[str, Any]) -> Optional[discord.TextChannel]:
    try:
        configured = guild.get_channel(int(settings.get("patch_channel_id", 0) or 0))
    except (TypeError, ValueError):
        configured = None
    if _can_send(configured, guild):
        return configured  # type: ignore[return-value]
    keywords = ("패치", "업데이트", "공지", "소식", "update", "patch", "announcement")
    for channel in guild.text_channels:
        lowered = channel.name.casefold()
        if any(token in lowered for token in keywords) and _can_send(channel, guild):
            return channel
    return None


def _parse_toggle(value: str) -> Optional[bool]:
    value = str(value or "").strip().casefold()
    if value in {"켜기", "켜", "on", "true", "1", "활성화"}:
        return True
    if value in {"끄기", "꺼", "off", "false", "0", "비활성화"}:
        return False
    return None


def _registered(user_data: Mapping[Any, Any], user_id: int) -> bool:
    return str(user_id) in user_data or user_id in user_data


def _stats(world_data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    state = _root(world_data)["ai_stats"].setdefault(str(user_id), {})
    state.setdefault("wins", 0)
    state.setdefault("draws", 0)
    state.setdefault("losses", 0)
    state.setdefault("games", {})
    state.setdefault("wager", {})
    return state


class AIDuelView(discord.ui.View):
    win_multiplier = 2
    def __init__(
        self,
        *,
        owner_id: int,
        user: Dict[str, Any],
        bet: int,
        save_data: Callable[[], None],
        world_data: Dict[str, Any],
        game_key: str,
        title: str,
        currency: str = "chips",
        timeout: float = 90,
    ) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = int(owner_id)
        self.user = user
        self.bet = int(bet)
        self.save_data = save_data
        self.world_data = world_data
        self.game_key = game_key
        self.title = title
        self.currency = currency if currency in {"chips", "food"} else "chips"
        self.done = False
        self.message: Optional[discord.Message] = None
        self.lock = asyncio.Lock()
        self.settle_lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("이 대전은 초대한 생존자만 조작할 수 있어요. 🤖", ephemeral=True)
            return False
        return True

    def _disable(self) -> None:
        for child in self.children:
            child.disabled = True

    async def finish(self, interaction: discord.Interaction, outcome: str, detail: str) -> None:
        async with self.settle_lock:
            if self.done:
                return
            self.done = True
            payout = 0
            if outcome == "win":
                payout = self.bet * int(self.win_multiplier)
                if payout:
                    _add_currency(self.user, self.currency, payout)
            elif outcome == "draw":
                payout = self.bet
                if payout:
                    _add_currency(self.user, self.currency, payout)
            state = _stats(self.world_data, self.owner_id)
            key = {"win": "wins", "draw": "draws", "lose": "losses"}[outcome]
            state[key] = int(state.get(key, 0) or 0) + 1
            games = state.setdefault("games", {})
            games[self.game_key] = int(games.get(self.game_key, 0) or 0) + 1
            wager_stats = state.setdefault("wager", {}).setdefault(self.currency, {"staked": 0, "returned": 0})
            wager_stats["staked"] = int(wager_stats.get("staked", 0) or 0) + self.bet
            wager_stats["returned"] = int(wager_stats.get("returned", 0) or 0) + payout
            self.save_data()
            self._disable()
            mark = {"win": "🏆 승리", "draw": "🤝 무승부", "lose": "💀 패배"}[outcome]
            colour = {"win": discord.Colour.gold(), "draw": discord.Colour.blurple(), "lose": discord.Colour.dark_red()}[outcome]
            embed = discord.Embed(title=f"{self.title} · {mark}", description=detail, colour=colour)
            if self.bet:
                net = payout - self.bet
                label = _currency_label(self.currency)
                embed.add_field(name="💰 정산", value=f"{net:+,}{label} · 현재 {_currency_balance(self.user, self.currency):,}{label}", inline=False)
            embed.set_footer(text="🤖 아바돈은 서버의 다른 생존자가 없어도 언제든 함께합니다.")
            if interaction.response.is_done():
                target = self.message or interaction.message
                if target:
                    await target.edit(content=None, embed=embed, view=self)
            else:
                await interaction.response.edit_message(content=None, embed=embed, view=self)
                self.message = interaction.message or self.message
            self.stop()

    async def on_timeout(self) -> None:
        async with self.settle_lock:
            if self.done:
                return
            self.done = True
            if self.bet:
                _add_currency(self.user, self.currency, self.bet)
                self.save_data()
            self._disable()
            if self.message:
                embed = discord.Embed(
                    title=f"{self.title} · ⌛ 종료",
                    description="시간이 지나 대전이 종료됐어요. 참가비는 전액 돌려드렸습니다.",
                    colour=discord.Colour.dark_grey(),
                )
                try:
                    await self.message.edit(embed=embed, view=self)
                except discord.HTTPException:
                    pass


class RPSView(AIDuelView):
    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="✊ 아바돈 가위바위보",
            description="아바돈이 선택하기 전에 하나를 골라주세요. `✊ > ✌️ > ✋ > ✊`",
            colour=discord.Colour.teal(),
        )

    async def play(self, interaction: discord.Interaction, choice: str) -> None:
        ai = random.choice(("rock", "paper", "scissors"))
        labels = {"rock": "✊ 바위", "paper": "✋ 보", "scissors": "✌️ 가위"}
        if choice == ai:
            outcome = "draw"
        elif (choice, ai) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}:
            outcome = "win"
        else:
            outcome = "lose"
        await self.finish(interaction, outcome, f"생존자: **{labels[choice]}**\n아바돈: **{labels[ai]}**")

    @discord.ui.button(label="바위", emoji="✊", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.play(interaction, "rock")

    @discord.ui.button(label="보", emoji="✋", style=discord.ButtonStyle.success)
    async def paper(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.play(interaction, "paper")

    @discord.ui.button(label="가위", emoji="✌️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.play(interaction, "scissors")


class OddEvenView(AIDuelView):
    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="🎲 아바돈 홀짝 대결",
            description="아바돈이 1~6 신호 주사위를 굴립니다. 홀수인지 짝수인지 예측하세요.",
            colour=discord.Colour.orange(),
        )

    async def play(self, interaction: discord.Interaction, choice: str) -> None:
        roll = random.randint(1, 6)
        actual = "odd" if roll % 2 else "even"
        await self.finish(
            interaction,
            "win" if choice == actual else "lose",
            f"선택: **{'홀수' if choice == 'odd' else '짝수'}**\n아바돈의 주사위: **{roll}**",
        )

    @discord.ui.button(label="홀수", emoji="1️⃣", style=discord.ButtonStyle.primary)
    async def odd(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.play(interaction, "odd")

    @discord.ui.button(label="짝수", emoji="2️⃣", style=discord.ButtonStyle.success)
    async def even(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.play(interaction, "even")


class NumberDuelView(AIDuelView):
    win_multiplier = 5

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="🔢 아바돈 숫자결투",
            description="아바돈이 숨긴 1~5 신호 숫자를 맞혀보세요. 정확히 맞히면 5배 총지급입니다.",
            colour=discord.Colour.blurple(),
        )

    async def play(self, interaction: discord.Interaction, number: int) -> None:
        ai = random.randint(1, 5)
        outcome = "win" if number == ai else "lose"
        await self.finish(interaction, outcome, f"예측: **{number}** · 아바돈의 숨은 숫자: **{ai}**")

    @discord.ui.button(label="1", emoji="1️⃣", style=discord.ButtonStyle.secondary)
    async def one(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 1)
    @discord.ui.button(label="2", emoji="2️⃣", style=discord.ButtonStyle.secondary)
    async def two(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 2)
    @discord.ui.button(label="3", emoji="3️⃣", style=discord.ButtonStyle.primary)
    async def three(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 3)
    @discord.ui.button(label="4", emoji="4️⃣", style=discord.ButtonStyle.success)
    async def four(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 4)
    @discord.ui.button(label="5", emoji="5️⃣", style=discord.ButtonStyle.danger)
    async def five(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 5)


class SignalDuelView(AIDuelView):
    win_multiplier = 4
    SIGNALS = ("☣️", "📡", "🔥", "💧")

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="📡 아바돈 신호 예측",
            description="폐허에서 송신될 신호를 예측하세요. 같은 신호를 고르면 승리합니다.",
            colour=discord.Colour.purple(),
        )

    async def play(self, interaction: discord.Interaction, choice: str) -> None:
        ai = random.choice(self.SIGNALS)
        await self.finish(interaction, "win" if choice == ai else "lose", f"예측: **{choice}** · 수신 신호: **{ai}**")

    @discord.ui.button(label="오염", emoji="☣️", style=discord.ButtonStyle.danger)
    async def toxic(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, "☣️")
    @discord.ui.button(label="무전", emoji="📡", style=discord.ButtonStyle.primary)
    async def radio(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, "📡")
    @discord.ui.button(label="화염", emoji="🔥", style=discord.ButtonStyle.secondary)
    async def fire(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, "🔥")
    @discord.ui.button(label="정수", emoji="💧", style=discord.ButtonStyle.success)
    async def water(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, "💧")


class PokerDuelView(AIDuelView):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        deck = _deck()
        self.player_hand = [deck.pop() for _ in range(5)]
        self.ai_hand = [deck.pop() for _ in range(5)]
        self.deck = deck
        self.exchanged = False

    def embed(self) -> discord.Embed:
        _, label = _poker_score(self.player_hand)
        embed = discord.Embed(
            title="♠️ 아바돈 1:1 포커",
            description="패를 그대로 공개하거나, 가장 낮은 카드 한 장을 자동 교환한 뒤 승부하세요.",
            colour=discord.Colour.gold(),
        )
        embed.add_field(name="🂠 내 패", value="  ".join(_card_text(card) for card in self.player_hand), inline=False)
        embed.add_field(name="현재 족보", value=label, inline=True)
        embed.add_field(name="아바돈", value="🂠 🂠 🂠 🂠 🂠", inline=True)
        return embed

    def _ai_exchange(self) -> None:
        score, _ = _poker_score(self.ai_hand)
        if score[0] <= 1 and self.deck:
            idx = min(range(len(self.ai_hand)), key=lambda index: self.ai_hand[index][0])
            self.ai_hand[idx] = self.deck.pop()

    async def showdown(self, interaction: discord.Interaction) -> None:
        self._ai_exchange()
        player_score, player_label = _poker_score(self.player_hand)
        ai_score, ai_label = _poker_score(self.ai_hand)
        outcome = "win" if player_score > ai_score else ("draw" if player_score == ai_score else "lose")
        detail = (
            f"생존자: {'  '.join(_card_text(card) for card in self.player_hand)} · **{player_label}**\n"
            f"아바돈: {'  '.join(_card_text(card) for card in self.ai_hand)} · **{ai_label}**"
        )
        await self.finish(interaction, outcome, detail)

    @discord.ui.button(label="그대로 승부", emoji="🏆", style=discord.ButtonStyle.danger)
    async def keep(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.showdown(interaction)

    @discord.ui.button(label="낮은 카드 교환", emoji="🔄", style=discord.ButtonStyle.primary)
    async def exchange(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.exchanged:
            await interaction.response.send_message("이미 한 번 교환했어요.", ephemeral=True)
            return
        self.exchanged = True
        idx = min(range(len(self.player_hand)), key=lambda index: self.player_hand[index][0])
        old = self.player_hand[idx]
        self.player_hand[idx] = self.deck.pop()
        await interaction.response.edit_message(
            content=f"🔄 {_card_text(old)} → {_card_text(self.player_hand[idx])}",
            embed=self.embed(),
            view=self,
        )


class JokerGuessView(AIDuelView):
    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="🃏 아바돈 조커 추적",
            description="세 장 중 한 장이 조커입니다. 먼저 한 장을 고르세요. 아바돈이 남은 카드 중 한 장을 뽑습니다.",
            colour=discord.Colour.fuchsia(),
        )

    async def play(self, interaction: discord.Interaction, index: int) -> None:
        joker = random.randint(0, 2)
        remaining = [item for item in range(3) if item != index]
        ai = random.choice(remaining)
        if index == joker:
            outcome = "lose"
        elif ai == joker:
            outcome = "win"
        else:
            outcome = "draw"
        cards = ["🃏" if item == joker else "🎴" for item in range(3)]
        await self.finish(interaction, outcome, f"공개 카드: {' '.join(cards)}\n생존자 선택: **{index + 1}번** · 아바돈 선택: **{ai + 1}번**")

    @discord.ui.button(label="1번", emoji="🎴", style=discord.ButtonStyle.secondary)
    async def first(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 0)
    @discord.ui.button(label="2번", emoji="🎴", style=discord.ButtonStyle.primary)
    async def second(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 1)
    @discord.ui.button(label="3번", emoji="🎴", style=discord.ButtonStyle.secondary)
    async def third(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.play(interaction, 2)


class OneCardPlaySelect(discord.ui.Select):
    def __init__(self, session: "OneCardDuelView") -> None:
        self.session = session
        options = []
        for index, card in enumerate(session.player_hand[:25]):
            playable = session.playable(card)
            options.append(discord.SelectOption(label=f"{index + 1}번 · {_card_text(card)}", value=str(index), emoji="✅" if playable else "⛔"))
        super().__init__(placeholder="낼 카드를 고르세요", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.play_card(interaction, int(self.values[0]))


class OneCardSelectView(discord.ui.View):
    def __init__(self, session: "OneCardDuelView") -> None:
        super().__init__(timeout=45)
        self.add_item(OneCardPlaySelect(session))


class OneCardDuelView(AIDuelView):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(timeout=180, **kwargs)
        deck = [(rank, suit) for suit in ("♠", "♥", "♦", "♣") for rank in range(2, 15)]
        random.shuffle(deck)
        self.deck = deck
        self.player_hand = [self.deck.pop() for _ in range(5)]
        self.ai_hand = [self.deck.pop() for _ in range(5)]
        self.discard = [self.deck.pop()]
        self.last_action = "📡 카드 통신 연결 완료"

    def playable(self, card: Tuple[int, str]) -> bool:
        top = self.discard[-1]
        return card[0] == top[0] or card[1] == top[1]

    def embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎴 아바돈 간편 원카드",
            description=f"{self.last_action}\n같은 숫자 또는 무늬를 내세요. 특수 카드 효과는 없는 빠른 1:1 규칙입니다.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="바닥 카드", value=f"**{_card_text(self.discard[-1])}**", inline=True)
        embed.add_field(name="내 패", value="  ".join(_card_text(card) for card in self.player_hand), inline=False)
        embed.add_field(name="남은 카드", value=f"생존자 {len(self.player_hand)}장 · 아바돈 {len(self.ai_hand)}장", inline=False)
        return embed

    def _draw(self) -> Tuple[int, str]:
        if not self.deck:
            top = self.discard[-1]
            self.deck = self.discard[:-1]
            self.discard = [top]
            random.shuffle(self.deck)
        return self.deck.pop()

    async def _ai_turn(self) -> Optional[str]:
        await asyncio.sleep(0.35)
        playable = [index for index, card in enumerate(self.ai_hand) if self.playable(card)]
        if playable:
            index = random.choice(playable)
            card = self.ai_hand.pop(index)
            self.discard.append(card)
            self.last_action = f"🤖 아바돈이 **{_card_text(card)}** 카드를 냈습니다."
            if not self.ai_hand:
                return "ai_win"
        else:
            card = self._draw()
            self.ai_hand.append(card)
            self.last_action = "🤖 아바돈이 낼 카드가 없어 한 장 뽑았습니다."
        return None

    @discord.ui.button(label="카드 내기", emoji="🎴", style=discord.ButtonStyle.primary)
    async def choose(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_message("낼 카드를 선택하세요.", view=OneCardSelectView(self), ephemeral=True)

    @discord.ui.button(label="한 장 뽑기", emoji="➕", style=discord.ButtonStyle.success)
    async def draw(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with self.lock:
            card = self._draw()
            self.player_hand.append(card)
            self.last_action = f"➕ 생존자가 **{_card_text(card)}** 카드를 뽑았습니다."
            result = await self._ai_turn()
            if result == "ai_win":
                await self.finish(interaction, "lose", "🤖 아바돈이 먼저 패를 모두 비웠습니다.")
                return
            await interaction.response.edit_message(embed=self.embed(), view=self)

    async def play_card(self, interaction: discord.Interaction, index: int) -> None:
        async with self.lock:
            if index >= len(self.player_hand):
                await interaction.response.send_message("패가 바뀌었어요. 다시 골라주세요.", ephemeral=True)
                return
            card = self.player_hand[index]
            if not self.playable(card):
                await interaction.response.send_message("현재 바닥 카드에는 낼 수 없어요.", ephemeral=True)
                return
            self.player_hand.pop(index)
            self.discard.append(card)
            if not self.player_hand:
                await interaction.response.edit_message(content=f"✅ {_card_text(card)} 제출", view=None)
                if interaction.message:
                    await self.finish(interaction, "win", "🏆 생존자가 먼저 패를 모두 비웠습니다.")
                return
            self.last_action = f"🧑 생존자가 **{_card_text(card)}** 카드를 냈습니다."
            await interaction.response.edit_message(content=f"✅ {_card_text(card)} 제출", view=None)
            result = await self._ai_turn()
            if result == "ai_win":
                await self.finish(interaction, "lose", "🤖 아바돈이 먼저 패를 모두 비웠습니다.")
                return
            if self.message:
                await self.message.edit(embed=self.embed(), view=self)


GAME_ALIASES = {
    "가위바위보": "rps", "가위": "rps", "rps": "rps",
    "홀짝": "odd", "홀짝대결": "odd", "dice": "odd",
    "숫자": "number", "숫자결투": "number", "number": "number",
    "포커": "poker", "아바돈포커": "poker", "poker": "poker",
    "원카드": "onecard", "아바돈원카드": "onecard", "onecard": "onecard",
    "조커": "joker", "조커잡기": "joker", "joker": "joker",
    "신호": "signal", "신호예측": "signal", "signal": "signal",
}

GAME_LABELS = {
    "rps": "✊ 가위바위보",
    "odd": "🎲 홀짝 대결",
    "number": "🔢 숫자결투",
    "poker": "♠️ 1:1 포커",
    "onecard": "🎴 간편 원카드",
    "joker": "🃏 조커 추적",
    "signal": "📡 신호 예측",
}


class AIGameSelect(discord.ui.Select):
    def __init__(self, starter: Callable[..., Any], bet: int, currency: str) -> None:
        self.starter = starter
        self.bet = int(bet)
        self.currency = currency
        super().__init__(
            placeholder="아바돈과 할 게임을 골라주세요",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="가위바위보", value="rps", emoji="✊", description="빠른 1판 승부"),
                discord.SelectOption(label="홀짝 대결", value="odd", emoji="🎲", description="주사위 홀수/짝수 예측"),
                discord.SelectOption(label="숫자결투", value="number", emoji="🔢", description="1~5 숨은 숫자 맞히기"),
                discord.SelectOption(label="1:1 포커", value="poker", emoji="♠️", description="5장 족보와 한 장 교환"),
                discord.SelectOption(label="간편 원카드", value="onecard", emoji="🎴", description="같은 숫자/무늬 빠른 대전"),
                discord.SelectOption(label="조커 추적", value="joker", emoji="🃏", description="세 카드 중 조커 피하기"),
                discord.SelectOption(label="신호 예측", value="signal", emoji="📡", description="폐허 신호 맞히기"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.starter(interaction, self.values[0], self.bet, currency=self.currency)


class AIGameMenuView(discord.ui.View):
    def __init__(self, starter: Callable[..., Any], bet: int, currency: str) -> None:
        super().__init__(timeout=180)
        self.add_item(AIGameSelect(starter, bet, currency))


def register_v720_coop_cleanup(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Mapping[Any, Dict[str, Any]],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v720_registered", False):
        return

    patch_post_lock = asyncio.Lock()

    interactive = next((category for category in guide if category.get("id") == "interactive_arcade"), None)
    if interactive is not None:
        existing = "\n".join(str(row) for row in interactive.get("commands", []))
        for row in (
            "!아바돈게임 [참가비] — 혼자일 때 아바돈과 1:1 미니게임 7종",
            "!아바돈초대 게임이름 [참가비] — 가위바위보/홀짝/숫자/포커/원카드/조커/신호",
            "!아바돈전적 — 아바돈 상대 승/무/패 기록",
            "!아바돈내기 게임 재화 금액 — 칩 또는 식량을 걸고 아바돈과 1:1",
        ):
            if row.split()[0] not in existing:
                interactive.setdefault("commands", []).append(row)
                existing += "\n" + row
    server = next((category for category in guide if category.get("id") == "server"), None)
    if server is not None:
        existing = "\n".join(str(row) for row in server.get("commands", []))
        for row in (
            "!패치채널 [#채널] — 새 버전 자동 공지 채널 지정",
            "!패치자동공지 ON/OFF — 버전당 한 번 자동 게시",
            "!패치공지상태 / !패치공지게시 — 상태 확인 및 수동 게시",
        ):
            if row.split()[0] not in existing:
                server.setdefault("commands", []).append(row)
                existing += "\n" + row

    async def start_ai_game(interaction: discord.Interaction, kind: str, bet: int, *, currency: str = "chips", replace_message: bool = True) -> None:
        uid = int(interaction.user.id)
        if not _registered(user_data, uid):
            if interaction.response.is_done():
                await interaction.followup.send("먼저 `!가입 생존자`로 등록해주세요.", ephemeral=True)
            else:
                await interaction.response.send_message("먼저 `!가입 생존자`로 등록해주세요.", ephemeral=True)
            return
        kind = GAME_ALIASES.get(str(kind).casefold(), str(kind).casefold())
        if kind not in GAME_LABELS:
            if interaction.response.is_done():
                await interaction.followup.send("지원하지 않는 게임입니다.", ephemeral=True)
            else:
                await interaction.response.send_message("지원하지 않는 게임입니다.", ephemeral=True)
            return
        currency = currency if currency in {"chips", "food"} else "chips"
        maximum = MAX_AI_BET if currency == "chips" else MAX_AI_FOOD_BET
        bet = max(0, min(maximum, int(bet or 0)))
        user = get_user(uid)
        if bet and _currency_balance(user, currency) < bet:
            label = _currency_label(currency)
            message = f"참가비가 부족해요. 현재 **{_currency_balance(user, currency):,}{label}**"
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        if bet:
            _add_currency(user, currency, -bet)
            save_data()
        kwargs = dict(owner_id=uid, user=user, bet=bet, save_data=save_data, world_data=world_data, game_key=kind, title=GAME_LABELS[kind], currency=currency)
        if kind == "rps": view: AIDuelView = RPSView(**kwargs)
        elif kind == "odd": view = OddEvenView(**kwargs)
        elif kind == "number": view = NumberDuelView(**kwargs)
        elif kind == "poker": view = PokerDuelView(**kwargs)
        elif kind == "onecard": view = OneCardDuelView(**kwargs)
        elif kind == "joker": view = JokerGuessView(**kwargs)
        else: view = SignalDuelView(**kwargs)
        embed = view.embed()  # type: ignore[attr-defined]
        try:
            if interaction.response.is_done():
                if replace_message and interaction.message:
                    await interaction.message.edit(content=None, embed=embed, view=view)
                    view.message = interaction.message
                else:
                    message = await interaction.followup.send(embed=embed, view=view, wait=True)
                    view.message = message
            else:
                if replace_message:
                    await interaction.response.edit_message(content=None, embed=embed, view=view)
                    view.message = interaction.message
                else:
                    await interaction.response.send_message(embed=embed, view=view)
                    view.message = await interaction.original_response()
        except Exception:
            if bet:
                _add_currency(user, currency, bet)
                save_data()
            raise

    async def start_ai_card(interaction: discord.Interaction, kind: str, bet: int) -> None:
        mapping = {"포커": "poker", "원카드": "onecard", "조커잡기": "joker"}
        await start_ai_game(interaction, mapping.get(kind, "rps"), bet, replace_message=True)

    @bot.command(name="아바돈게임", aliases=["봇대전", "혼자게임", "AI게임"], help="혼자서 아바돈과 1:1 미니게임을 즐깁니다.")
    async def ai_game_menu(ctx: commands.Context, 재화또는금액: str = "0", 금액: int = 0) -> None:
        if not await check_registered(ctx):
            return
        currency, 참가비, error = _parse_wager(재화또는금액, 금액)
        if error or currency is None:
            await ctx.send(f"⚠️ {error}\n예: `!아바돈게임 1000` · `!아바돈게임 식량 5000`")
            return
        embed = discord.Embed(
            title="🤖 아바돈 1:1 미니게임",
            description="같이 할 사람이 없어도 괜찮아요. 아래에서 게임을 고르면 아바돈이 바로 참가합니다.",
            colour=discord.Colour.purple(),
        )
        embed.add_field(name="🎮 게임 7종", value="가위바위보 · 홀짝 · 숫자결투 · 포커 · 원카드 · 조커 추적 · 신호 예측", inline=False)
        label = _currency_label(currency)
        embed.add_field(name="💰 참가비", value=f"{참가비:,}{label}" if 참가비 else "무료 친선전", inline=True)
        embed.add_field(name="📈 배당", value="일반 2배 · 숫자결투 5배 · 신호예측 4배 · 무승부 전액 환급", inline=False)
        embed.set_footer(text="기존 `!아바돈게임 1000`은 칩 베팅 · 식량은 `!아바돈게임 식량 5000`")
        await ctx.send(embed=embed, view=AIGameMenuView(start_ai_game, 참가비, currency))

    @bot.command(name="아바돈초대", aliases=["봇초대", "AI초대"], help="지정한 게임에 아바돈을 초대합니다.")
    async def invite_abaddon(ctx: commands.Context, 게임: str = "가위바위보", 재화또는금액: str = "0", 금액: int = 0) -> None:
        if not await check_registered(ctx):
            return
        kind = GAME_ALIASES.get(str(게임).casefold())
        if kind is None:
            await ctx.send("게임 이름: `가위바위보`, `홀짝`, `숫자`, `포커`, `원카드`, `조커`, `신호`")
            return
        currency, 참가비, error = _parse_wager(재화또는금액, 금액)
        if error or currency is None:
            await ctx.send(f"⚠️ {error}\n예: `!아바돈초대 포커 1000` · `!아바돈초대 포커 식량 5000`")
            return
        user = get_user(ctx.author.id)
        if 참가비 and _currency_balance(user, currency) < 참가비:
            label = _currency_label(currency)
            await ctx.send(f"참가비가 부족해요. 현재 **{_currency_balance(user, currency):,}{label}**")
            return
        if 참가비:
            _add_currency(user, currency, -참가비)
            save_data()
        kwargs = dict(owner_id=ctx.author.id, user=user, bet=참가비, save_data=save_data, world_data=world_data, game_key=kind, title=GAME_LABELS[kind], currency=currency)
        if kind == "rps": view: AIDuelView = RPSView(**kwargs)
        elif kind == "odd": view = OddEvenView(**kwargs)
        elif kind == "number": view = NumberDuelView(**kwargs)
        elif kind == "poker": view = PokerDuelView(**kwargs)
        elif kind == "onecard": view = OneCardDuelView(**kwargs)
        elif kind == "joker": view = JokerGuessView(**kwargs)
        else: view = SignalDuelView(**kwargs)
        try:
            view.message = await ctx.send(embed=view.embed(), view=view)  # type: ignore[attr-defined]
        except Exception:
            if 참가비:
                _add_currency(user, currency, 참가비)
                save_data()
            raise

    @bot.command(name="아바돈내기", aliases=["AI내기", "봇내기"], help="아바돈과 게임 내 칩 또는 식량을 걸고 1:1 대결합니다.")
    async def abaddon_wager(ctx: commands.Context, 게임: str = "가위바위보", 재화: str = "칩", 금액: int = 1000) -> None:
        await invite_abaddon.callback(ctx, 게임, 재화, 금액)

    @bot.command(name="아바돈전적", aliases=["봇전적", "AI전적"], help="아바돈과의 1:1 미니게임 전적을 확인합니다.")
    async def ai_record(ctx: commands.Context) -> None:
        state = _stats(world_data, ctx.author.id)
        games = state.get("games", {})
        rows = [f"{GAME_LABELS.get(key, key)} · {count}회" for key, count in sorted(games.items(), key=lambda item: int(item[1]), reverse=True)]
        embed = discord.Embed(title="🤖 아바돈 대전 기록", colour=discord.Colour.purple())
        embed.add_field(name="전체", value=f"🏆 {state['wins']}승 · 🤝 {state['draws']}무 · 💀 {state['losses']}패", inline=False)
        embed.add_field(name="게임별", value="\n".join(rows[:12]) or "아직 대전 기록이 없어요.", inline=False)
        wager = state.get("wager", {})
        wager_rows = []
        for currency in ("chips", "food"):
            info = wager.get(currency, {}) if isinstance(wager, dict) else {}
            staked = int(info.get("staked", 0) or 0)
            returned = int(info.get("returned", 0) or 0)
            if staked or returned:
                label = _currency_label(currency)
                wager_rows.append(f"{label} · 누적 베팅 {staked:,} · 회수 {returned:,} · 순손익 {returned - staked:+,}")
        embed.add_field(name="💰 1:1 베팅 기록", value="\n".join(wager_rows) or "아직 유료 대전 기록이 없어요.", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="패치채널", aliases=["업데이트채널"], help="패치 자동 공지가 올라갈 채널을 지정합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def patch_channel(ctx: commands.Context, 채널: Optional[discord.TextChannel] = None) -> None:
        if ctx.guild is None:
            await ctx.send("서버 안에서만 설정할 수 있습니다.")
            return
        target = 채널 or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        if target is None:
            await ctx.send("텍스트 채널을 지정해주세요.")
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        settings["patch_channel_id"] = target.id
        settings["patch_auto"] = True
        save_data()
        await ctx.send(f"📣 패치 자동 공지 채널을 {target.mention}(으)로 설정하고 자동 게시를 켰습니다.")

    @bot.command(name="패치자동공지", aliases=["업데이트자동공지"], help="새 버전 자동 공지를 켜거나 끕니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def patch_auto(ctx: commands.Context, 상태: str = "") -> None:
        if ctx.guild is None:
            return
        toggle = _parse_toggle(상태)
        if toggle is None:
            await ctx.send("사용법: `!패치자동공지 ON` 또는 `!패치자동공지 OFF`")
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        settings["patch_auto"] = toggle
        save_data()
        await ctx.send(f"📣 패치 자동 공지를 **{'켰습니다' if toggle else '껐습니다'}**.")

    @bot.command(name="패치공지상태", aliases=["업데이트공지상태"], help="패치 자동 공지 설정과 게시 이력을 확인합니다.")
    async def patch_status(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        channel = _find_patch_channel(ctx.guild, settings)
        posted = settings.get("posted_versions", [])
        await ctx.send(
            "📣 **패치 자동 공지 상태**\n"
            f"상태: {'✅ 켜짐' if settings.get('patch_auto', True) else '⏸️ 꺼짐'}\n"
            f"채널: {channel.mention if channel else '미설정 · `!패치채널`로 현재 채널 지정'}\n"
            f"최근 게시 버전: `{posted[-1] if posted else '없음'}`"
        )

    @bot.command(name="패치공지게시", aliases=["업데이트공지게시"], help="현재 버전 패치노트를 지정 채널에 수동 게시합니다.")
    @commands.has_guild_permissions(manage_guild=True)
    async def patch_post(ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        settings = _guild_settings(world_data, ctx.guild.id)
        channel = _find_patch_channel(ctx.guild, settings)
        if channel is None:
            await ctx.send("패치 채널을 찾지 못했습니다. 먼저 `!패치채널`을 실행해주세요.")
            return
        await channel.send(embed=_patch_embed())
        posted = settings.setdefault("posted_versions", [])
        if VERSION not in posted:
            posted.append(VERSION)
            del posted[:-20]
            save_data()
        await ctx.send(f"✅ {channel.mention}에 v{VERSION} 패치노트를 게시했습니다.")

    async def auto_post_patch_notes() -> None:
        await bot.wait_until_ready()
        await asyncio.sleep(2)
        async with patch_post_lock:
            changed = False
            for guild in list(bot.guilds):
                settings = _guild_settings(world_data, guild.id)
                if not settings.get("patch_auto", True):
                    continue
                posted = settings.setdefault("posted_versions", [])
                if VERSION in posted:
                    continue
                channel = _find_patch_channel(guild, settings)
                if channel is None:
                    continue
                try:
                    await channel.send(embed=_patch_embed())
                except (discord.Forbidden, discord.HTTPException):
                    continue
                posted.append(VERSION)
                del posted[:-20]
                changed = True
            if changed:
                save_data()

    bot.add_listener(auto_post_patch_notes, "on_ready")
    bot.v720_start_ai_card = start_ai_card  # type: ignore[attr-defined]
    bot.v720_start_ai_game = start_ai_game  # type: ignore[attr-defined]
    bot.v720_patch_embed = _patch_embed  # type: ignore[attr-defined]
    bot._abaddon_v720_registered = True  # type: ignore[attr-defined]
    print("[V7.8.0 SERVER DISASTER] 공동 재난·파밍 연출·기존 협동 기능 등록 완료", flush=True)
