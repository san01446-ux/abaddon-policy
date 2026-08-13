from __future__ import annotations

import asyncio
import copy
import random
import time
from collections import Counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips

VERSION = "6.5.1c"
MIN_BET = 10_000
MAX_BET = 0  # v10.5.1 compatibility constant; card games have no upper limit

CARD_GUIDE: Dict[str, Any] = {
    "id": "card_games",
    "emoji": "🃏",
    "title": "카드게임 / 파티",
    "hint": "참가 버튼·비공개 패 확인·턴제 선택으로 즐기는 카드게임",
    "commands": [
        "!카드게임 — 포커·원카드·조커잡기 시작 메뉴",
        "!포커 [참가비] — 2~6명, 비공개 패 확인과 1회 교환 후 승부",
        "!원카드 [참가비] — 2~6명, 같은 무늬·숫자를 내는 턴제 카드게임",
        "!조커잡기 [참가비] — 2~8명, 짝을 버리고 마지막 조커를 피하는 파티게임",
    ],
}

SUITS: Tuple[str, ...] = ("♠️", "♥️", "♦️", "♣️")
RANK_LABELS: Dict[int, str] = {11: "J", 12: "Q", 13: "K", 14: "A"}
Card = Tuple[int, str]

ACTIVE_LOBBIES: Dict[int, "CardLobbyView"] = {}
ACTIVE_GAMES: Dict[int, "BaseCardSession"] = {}
ABADDON_AI_ID = -1060


def _card_text(card: Card) -> str:
    rank, suit = card
    if rank == 0:
        return "🃏"
    return f"{suit}{RANK_LABELS.get(rank, str(rank))}"


def _deck(*, jokers: int = 0) -> List[Card]:
    cards = [(rank, suit) for suit in SUITS for rank in range(2, 15)]
    cards.extend([(0, "🃏") for _ in range(max(0, jokers))])
    random.shuffle(cards)
    return cards


def _emoji_bar(value: float, total: int = 10) -> str:
    ratio = max(0.0, min(1.0, float(value)))
    filled = int(round(ratio * total))
    return "🟩" * filled + "⬛" * (total - filled)


def _validate_bet(amount: int) -> Optional[str]:
    if amount < MIN_BET:
        return f"최소 참가비는 **{MIN_BET:,}칩**입니다."
    return None


def _guide_update(guide: List[Dict[str, Any]]) -> None:
    guide[:] = [cat for cat in guide if cat.get("id") != CARD_GUIDE["id"]]
    tokens = ("!카드게임", "!포커", "!원카드", "!조커잡기")
    for category in guide:
        category["commands"] = [
            row for row in category.get("commands", [])
            if not any(token in str(row) for token in tokens)
        ]
    insert_at = next((i + 1 for i, cat in enumerate(guide) if cat.get("id") == "interactive_arcade"), len(guide))
    guide.insert(insert_at, copy.deepcopy(CARD_GUIDE))


def _reservation_root(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault("v651_card_games", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v651_card_games"] = root
    root.setdefault("reservations", {})
    root.setdefault("completed", 0)
    return root


async def _safe_edit(message: Optional[discord.Message], *, embed: discord.Embed, view: Optional[discord.ui.View]) -> bool:
    """Publish a game state with resilient v10.9.5 visual media.

    Active tables use a short public GIF turn pulse when enabled; finished
    tables use PNG. Rendering/upload failure never stops gameplay: the function
    retries once, then falls back to embed-only editing while recording a small
    per-session diagnostic counter.
    """
    if message is None:
        return False

    async def publish_media() -> None:
        file = None
        media_embed = embed.copy()
        if view is not None and hasattr(view, "player_ids"):
            try:
                from apocalypse_bot.commands.v1095_visual_polish import render_session_media
                image, extension = render_session_media(view, media_embed)
                if image is not None:
                    filename = f"abaddon_table_{getattr(view, 'game_id', 'live')}.{extension}"
                    file = discord.File(image, filename=filename)
                    media_embed.set_image(url=f"attachment://{filename}")
                    setattr(view, "_v1095_last_render_ok", True)
            except Exception as exc:
                setattr(view, "_v1095_last_render_ok", False)
                setattr(view, "_v1095_last_render_error", type(exc).__name__)
                setattr(view, "_v1095_render_failures", int(getattr(view, "_v1095_render_failures", 0)) + 1)
                file = None
        if file is not None:
            await message.edit(embed=media_embed, view=view, attachments=[file])
        else:
            await message.edit(embed=embed, view=view)

    # Capture a short public-only action history for table overlays. No cards or
    # private modal values are stored here.
    if view is not None:
        try:
            action = str(getattr(view, "last_action", "") or "").strip()
            if action:
                history = list(getattr(view, "_v1095_visual_history", []))
                if not history or history[-1] != action:
                    history.append(action)
                    del history[:-6]
                    setattr(view, "_v1095_visual_history", history)
        except Exception:
            pass

    for delay in (0.0, 0.65):
        if delay:
            await asyncio.sleep(delay)
        try:
            await publish_media()
            return True
        except (discord.HTTPException, OSError, asyncio.TimeoutError):
            continue
        except Exception:
            break

    # Final recovery path: do not let an attachment/GIF issue break the turn.
    try:
        await message.edit(embed=embed, view=view)
        if view is not None:
            setattr(view, "_v1095_embed_fallbacks", int(getattr(view, "_v1095_embed_fallbacks", 0)) + 1)
        return True
    except Exception:
        return False


def _poker_score(hand: Sequence[Card]) -> Tuple[Tuple[int, ...], str]:
    ranks = sorted((rank for rank, _ in hand), reverse=True)
    counts = Counter(ranks)
    ordered = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    flush = len({suit for _, suit in hand}) == 1
    unique = sorted(set(ranks), reverse=True)
    if unique == [14, 5, 4, 3, 2]:
        straight_high = 5
    elif len(unique) == 5 and unique[0] - unique[-1] == 4:
        straight_high = unique[0]
    else:
        straight_high = 0
    if flush and straight_high:
        return (8, straight_high), "스트레이트 플러시"
    if ordered[0][1] == 4:
        four = ordered[0][0]
        kicker = max(rank for rank in ranks if rank != four)
        return (7, four, kicker), "포카드"
    if sorted(counts.values()) == [2, 3]:
        triple = max(rank for rank, count in counts.items() if count == 3)
        pair = max(rank for rank, count in counts.items() if count == 2)
        return (6, triple, pair), "풀하우스"
    if flush:
        return (5, *ranks), "플러시"
    if straight_high:
        return (4, straight_high), "스트레이트"
    if ordered[0][1] == 3:
        triple = ordered[0][0]
        kickers = sorted((rank for rank in ranks if rank != triple), reverse=True)
        return (3, triple, *kickers), "트리플"
    pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = max(rank for rank in ranks if rank not in pairs)
        return (2, pairs[0], pairs[1], kicker), "투페어"
    if len(pairs) == 1:
        pair = pairs[0]
        kickers = sorted((rank for rank in ranks if rank != pair), reverse=True)
        return (1, pair, *kickers), "원페어"
    return (0, *ranks), "하이카드"


class CardLobbyView(discord.ui.View):
    def __init__(
        self,
        *,
        bot: commands.Bot,
        kind: str,
        host: discord.abc.User,
        bet: int,
        get_user: Callable[[int], Dict[str, Any]],
        save_data: Callable[[], None],
        world_data: Dict[str, Any],
        user_data: Mapping[str, Dict[str, Any]],
        start_factory: Callable[["CardLobbyView"], "BaseCardSession"],
        min_players: int,
        max_players: int,
        allow_abaddon: bool = True,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.kind = kind
        self.host_id = int(host.id)
        self.bet = int(bet)
        self.get_user = get_user
        self.save_data = save_data
        self.world_data = world_data
        self.user_data = user_data
        self.start_factory = start_factory
        self.min_players = min_players
        self.max_players = max_players
        self.allow_abaddon = bool(allow_abaddon)
        self.players: Dict[int, str] = {int(host.id): getattr(host, "display_name", str(host))}
        self.message: Optional[discord.Message] = None
        self.channel_id = 0
        self.started = False
        self.lock = asyncio.Lock()
        if not self.allow_abaddon:
            for child in list(self.children):
                if getattr(child, "label", "") == "아바돈 초대":
                    self.remove_item(child)

    def embed(self, note: str = "") -> discord.Embed:
        descriptions = {
            "포커": "각자 비공개 5장을 받고 **한 장을 한 번 교환**한 뒤 가장 높은 족보가 승리합니다.",
            "원카드": "내 차례에 같은 무늬·숫자 카드를 내거나 한 장을 뽑습니다. 먼저 패를 비우면 승리합니다.",
            "조커잡기": "짝이 맞는 카드는 자동으로 버립니다. 옆 사람 패에서 한 장씩 뽑고 마지막 조커를 피하세요.",
            "텍사스홀덤": "각자 비공개 2장과 커뮤니티 5장 중 가장 좋은 5장 족보로 승부합니다.",
            "오마하홀덤": "비공개 4장 중 정확히 2장과 커뮤니티 카드 3장을 조합해 승부합니다.",
            "세븐카드스터드": "개인 7장 중 가장 좋은 5장 족보로 승부합니다.",
            "맞고": "2인 화투입니다. 같은 월 패를 맞추고 점수 기준을 넘으면 고 또는 스톱을 선택합니다.",
            "고스톱": "3~4인 화투입니다. 같은 월 패를 모아 점수를 만들고 고 또는 스톱을 선택합니다.",
        }
        embed = discord.Embed(
            title=f"🃏 {self.kind} 참가 모집",
            description=f"**10초 설명**\n{descriptions.get(self.kind, self.kind)}\n\n{note}".strip(),
            color=discord.Color.dark_purple(),
        )
        names = "\n".join(f"{idx}. **{name}**{' 👑' if uid == self.host_id else ''}" for idx, (uid, name) in enumerate(self.players.items(), 1))
        embed.add_field(name=f"참가자 {len(self.players)}/{self.max_players}", value=names or "없음", inline=False)
        embed.add_field(name="참가비", value=f"**{self.bet:,}칩** · 시작할 때 차감", inline=True)
        embed.add_field(name="예상 상금", value=f"현재 **{self.bet * len(self.players):,}칩**", inline=True)
        embed.add_field(name="진행", value=f"{_emoji_bar(len(self.players) / self.max_players)} **{len(self.players)}/{self.max_players}**", inline=False)
        embed.set_footer(text="혼자라면 🤖 아바돈 초대 · 여러 명이면 방장이 인원을 확정해 시작")
        return embed

    async def _update(self, note: str = "") -> None:
        await _safe_edit(self.message, embed=self.embed(note), view=self)

    @discord.ui.button(label="참가", emoji="✅", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.lock:
            uid = int(interaction.user.id)
            if self.started:
                await interaction.response.send_message("이미 시작된 방입니다.", ephemeral=True)
                return
            if str(uid) not in self.user_data and uid not in self.user_data:
                await interaction.response.send_message("먼저 `!가입`으로 생존자를 등록하세요.", ephemeral=True)
                return
            if uid in self.players:
                await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
                return
            if len(self.players) >= self.max_players:
                await interaction.response.send_message("참가 인원이 가득 찼습니다.", ephemeral=True)
                return
            self.players[uid] = getattr(interaction.user, "display_name", str(interaction.user))
            await interaction.response.defer()
            await self._update(f"✅ **{self.players[uid]}** 님이 참가했습니다.")

    @discord.ui.button(label="참가 취소", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.lock:
            uid = int(interaction.user.id)
            if uid == self.host_id:
                await interaction.response.send_message("방장은 방 취소 버튼을 사용하세요.", ephemeral=True)
                return
            if uid not in self.players:
                await interaction.response.send_message("참가 중이 아닙니다.", ephemeral=True)
                return
            name = self.players.pop(uid)
            await interaction.response.defer()
            await self._update(f"↩️ **{name}** 님이 참가를 취소했습니다.")

    @discord.ui.button(label="아바돈 초대", emoji="🤖", style=discord.ButtonStyle.secondary)
    async def invite_abaddon(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Start the exact same table engine with ABADDON as a synthetic player.

        Older builds jumped to a one-click score comparison.  v10.5.1 keeps the
        lobby, rules, turns, cards and settlement identical to human multiplayer.
        """
        async with self.lock:
            if not self.allow_abaddon:
                await interaction.response.send_message("이 게임은 아바돈 참가를 지원하지 않습니다.", ephemeral=True)
                return
            if int(interaction.user.id) != self.host_id:
                await interaction.response.send_message("방장만 아바돈을 초대할 수 있습니다.", ephemeral=True)
                return
            if self.started:
                await interaction.response.send_message("이미 시작된 방입니다.", ephemeral=True)
                return
            if len(self.players) != 1:
                await interaction.response.send_message("생존자가 참가 중일 때는 일반 멀티플레이로 시작해주세요.", ephemeral=True)
                return
            self.players[ABADDON_AI_ID] = "ABADDON"
            if self.kind == "고스톱":
                self.players[ABADDON_AI_ID - 1] = "ABADDON-β"
            self.started = True
            await interaction.response.defer()
            session = self.start_factory(self)
            try:
                await session.start()
            except Exception as exc:
                self.players.pop(ABADDON_AI_ID, None)
                self.players.pop(ABADDON_AI_ID - 1, None)
                self.started = False
                await self._update(f"❌ 아바돈 대전 시작 실패: `{type(exc).__name__}` · 참가비는 차감되지 않았습니다.")
                return
            ACTIVE_LOBBIES.pop(self.channel_id, None)
            ACTIVE_GAMES[self.channel_id] = session
            self.stop()

    @discord.ui.button(label="인원 확정·시작", emoji="🚦", style=discord.ButtonStyle.primary)
    async def start_game(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.lock:
            if int(interaction.user.id) != self.host_id:
                await interaction.response.send_message("방장만 시작할 수 있습니다.", ephemeral=True)
                return
            if self.started:
                await interaction.response.send_message("이미 시작 중입니다.", ephemeral=True)
                return
            if len(self.players) < self.min_players:
                await interaction.response.send_message(f"최소 {self.min_players}명이 필요합니다.", ephemeral=True)
                return
            self.started = True
            await interaction.response.defer()
            session = self.start_factory(self)
            try:
                await session.start()
            except Exception as exc:
                self.started = False
                await self._update(f"❌ 시작 실패: `{type(exc).__name__}` · 참가비는 차감되지 않았습니다.")
                return
            ACTIVE_LOBBIES.pop(self.channel_id, None)
            ACTIVE_GAMES[self.channel_id] = session

    @discord.ui.button(label="방 취소", emoji="🛑", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if int(interaction.user.id) != self.host_id:
            await interaction.response.send_message("방장만 취소할 수 있습니다.", ephemeral=True)
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        ACTIVE_LOBBIES.pop(self.channel_id, None)
        await interaction.response.defer()
        await self._update("🛑 모집이 취소됐습니다. 참가비는 차감되지 않았습니다.")

    async def on_timeout(self) -> None:
        if self.started:
            return
        for child in self.children:
            child.disabled = True
        ACTIVE_LOBBIES.pop(self.channel_id, None)
        await self._update("⌛ 모집 시간이 끝났습니다. 참가비는 차감되지 않았습니다.")


class BaseCardSession(discord.ui.View):
    def __init__(self, lobby: CardLobbyView, *, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.kind = lobby.kind
        self.host_id = lobby.host_id
        self.bet = lobby.bet
        self.player_ids = list(lobby.players)
        self.names = dict(lobby.players)
        self.get_user = lobby.get_user
        self.save_data = lobby.save_data
        self.world_data = lobby.world_data
        self.message = lobby.message
        self.channel_id = lobby.channel_id
        self.pot = self.bet * len(self.player_ids)
        # v11.0.0: keep the pre-game wallet so every legacy card result can
        # show exact net change and balance before→after, including debt.
        self.opening_chips: Dict[int, int] = {
            uid: casino_chips(self.get_user(uid)) for uid in self.player_ids if uid >= 0
        }
        self.game_id = f"{self.kind}-{self.channel_id}-{int(time.time() * 1000)}"
        self.done = False
        self.lock = asyncio.Lock()

    def _reserve(self) -> None:
        deducted: List[int] = []
        try:
            for uid in self.player_ids:
                if uid < 0:
                    continue
                user = self.get_user(uid)
                add_casino_chips(user, -self.bet)
                deducted.append(uid)
            root = _reservation_root(self.world_data)
            root["reservations"][self.game_id] = {
                "kind": self.kind,
                "bet": self.bet,
                "players": [uid for uid in self.player_ids if uid >= 0],
                "created_at": int(time.time()),
            }
            self.save_data()
        except Exception:
            for uid in deducted:
                add_casino_chips(self.get_user(uid), self.bet)
            self.save_data()
            raise

    def _close_reservation(self) -> None:
        root = _reservation_root(self.world_data)
        root.get("reservations", {}).pop(self.game_id, None)
        root["completed"] = int(root.get("completed", 0) or 0) + 1

    def _pay(self, winners: Sequence[int]) -> Dict[int, int]:
        if not winners:
            return {}
        base = self.pot // len(winners)
        remainder = self.pot % len(winners)
        payouts: Dict[int, int] = {}
        for index, uid in enumerate(winners):
            amount = base + (1 if index < remainder else 0)
            if uid >= 0:
                add_casino_chips(self.get_user(uid), amount)
            payouts[uid] = amount
        self._close_reservation()
        self.save_data()
        return payouts

    def _refund(self) -> None:
        for uid in self.player_ids:
            if uid >= 0:
                add_casino_chips(self.get_user(uid), self.bet)
        self._close_reservation()
        self.save_data()

    def _disable(self) -> None:
        for child in self.children:
            child.disabled = True

    def settlement_text(self, uid: int) -> str:
        """v11.0.0 game-only net and wallet before→after for legacy modes."""
        if uid < 0:
            return "AI 좌석"
        before = int(self.opening_chips.get(uid, casino_chips(self.get_user(uid))))
        after = int(casino_chips(self.get_user(uid)))
        net = after - before
        sign = "+" if net >= 0 else ""
        return f"이번 게임 **{sign}{net:,}칩** · 잔액 **{before:,} → {after:,}칩**"

    async def start(self) -> None:
        raise NotImplementedError


class PokerDiscardSelect(discord.ui.Select):
    def __init__(self, session: "PokerSession", uid: int) -> None:
        self.session = session
        self.uid = uid
        hand = session.hands[uid]
        options = [discord.SelectOption(label=f"{index + 1}번 · {_card_text(card)}", value=str(index)) for index, card in enumerate(hand)]
        super().__init__(placeholder="교환할 카드 한 장 선택", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.session.lock:
            if self.session.done:
                await interaction.response.send_message("이미 승부가 끝났습니다.", ephemeral=True)
                return
            if int(interaction.user.id) != self.uid:
                await interaction.response.send_message("본인 패만 교환할 수 있습니다.", ephemeral=True)
                return
            if self.uid in self.session.exchanged:
                await interaction.response.send_message("이미 한 번 교환했습니다.", ephemeral=True)
                return
            index = int(self.values[0])
            old = self.session.hands[self.uid][index]
            new = self.session.deck.pop()
            self.session.hands[self.uid][index] = new
            self.session.exchanged.add(self.uid)
            await interaction.response.edit_message(content=f"🔄 {_card_text(old)} → **{_card_text(new)}** 교환 완료", view=None)
            await self.session.update()


class PokerDiscardView(discord.ui.View):
    def __init__(self, session: "PokerSession", uid: int) -> None:
        super().__init__(timeout=45)
        self.add_item(PokerDiscardSelect(session, uid))


class PokerSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView) -> None:
        super().__init__(lobby, timeout=150)
        self.deck = _deck()
        self.hands: Dict[int, List[Card]] = {uid: [self.deck.pop() for _ in range(5)] for uid in self.player_ids}
        self.exchanged: set[int] = set()
        self.ready: set[int] = set()

    def embed(self, final: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(
            title="♠️ 생존자 포커 · 5장 승부",
            description=final or "`내 패 보기`로 비공개 패를 확인하고, 필요하면 **한 장만 교환**한 뒤 준비를 누르세요.",
            color=discord.Color.gold(),
        )
        status = []
        for uid in self.player_ids:
            marks = []
            if uid in self.exchanged:
                marks.append("🔄")
            if uid in self.ready:
                marks.append("✅")
            status.append(f"{' '.join(marks) or '▫️'} **{self.names[uid]}**")
        embed.add_field(name="참가자 상태", value="\n".join(status), inline=False)
        embed.add_field(name="상금", value=f"**{self.pot:,}칩**", inline=True)
        embed.add_field(name="준비 진행", value=f"{_emoji_bar(len(self.ready) / len(self.player_ids))} **{len(self.ready)}/{len(self.player_ids)}**", inline=False)
        embed.set_footer(text="교환은 1인 1회 · 방장은 전원 준비 전에도 승부 공개 가능")
        return embed

    async def start(self) -> None:
        self._reserve()
        await _safe_edit(self.message, embed=self.embed(), view=self)

    async def update(self) -> None:
        await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("이 승부의 참가자가 아닙니다.", ephemeral=True)
            return
        score, label = _poker_score(self.hands[uid])
        await interaction.response.send_message(
            f"🂠 **내 패**\n{'  '.join(_card_text(card) for card in self.hands[uid])}\n현재 족보: **{label}**",
            ephemeral=True,
        )

    @discord.ui.button(label="한 장 교환", emoji="🔄", style=discord.ButtonStyle.primary)
    async def exchange(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("참가자만 교환할 수 있습니다.", ephemeral=True)
            return
        if uid in self.exchanged:
            await interaction.response.send_message("이미 한 번 교환했습니다.", ephemeral=True)
            return
        await interaction.response.send_message("교환할 카드 한 장을 고르세요.", view=PokerDiscardView(self, uid), ephemeral=True)

    @discord.ui.button(label="준비 완료", emoji="✅", style=discord.ButtonStyle.success)
    async def ready_up(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("참가자만 준비할 수 있습니다.", ephemeral=True)
            return
        async with self.lock:
            self.ready.add(uid)
            await interaction.response.defer()
            if len(self.ready) == len(self.player_ids):
                await self.finish("✅ 전원이 준비해 자동으로 승부를 공개합니다.")
            else:
                await self.update()

    @discord.ui.button(label="승부 공개", emoji="🏆", style=discord.ButtonStyle.danger)
    async def showdown(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if int(interaction.user.id) != self.host_id:
            await interaction.response.send_message("방장만 승부를 공개할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.defer()
        async with self.lock:
            await self.finish("🏆 방장이 승부를 공개했습니다.")

    async def finish(self, reason: str) -> None:
        if self.done:
            return
        self.done = True
        scored = {uid: _poker_score(hand) for uid, hand in self.hands.items()}
        best = max(value[0] for value in scored.values())
        winners = [uid for uid, value in scored.items() if value[0] == best]
        payouts = self._pay(winners)
        rows = []
        for uid in self.player_ids:
            _, label = scored[uid]
            marker = "🏆" if uid in winners else "▫️"
            payout = f" · +{payouts[uid]:,}칩" if uid in payouts else ""
            rows.append(f"{marker} **{self.names[uid]}** · {' '.join(_card_text(card) for card in self.hands[uid])} · **{label}**{payout}\n└ {self.settlement_text(uid)}")
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(reason + "\n\n" + "\n".join(rows)), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        async with self.lock:
            if not self.done:
                await self.finish("⌛ 제한 시간이 끝나 자동으로 승부를 공개합니다.")


class OneCardPlaySelect(discord.ui.Select):
    def __init__(self, session: "OneCardSession", uid: int) -> None:
        self.session = session
        self.uid = uid
        hand = session.hands[uid]
        options = [
            discord.SelectOption(label=f"{index + 1}번 · {_card_text(card)}", value=str(index), description="낼 수 있음" if session.playable(card) else "현재 낼 수 없음")
            for index, card in enumerate(hand[:25])
        ]
        super().__init__(placeholder="낼 카드를 선택하세요", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.play_card(interaction, self.uid, int(self.values[0]))


class OneCardPlayView(discord.ui.View):
    def __init__(self, session: "OneCardSession", uid: int) -> None:
        super().__init__(timeout=45)
        self.add_item(OneCardPlaySelect(session, uid))


class OneCardSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView) -> None:
        super().__init__(lobby, timeout=240)
        self.deck = _deck(jokers=2)
        self.hands = {uid: [self.deck.pop() for _ in range(5)] for uid in self.player_ids}
        first = self.deck.pop()
        while first[0] == 0:
            self.deck.insert(0, first)
            random.shuffle(self.deck)
            first = self.deck.pop()
        self.discard: List[Card] = [first]
        self.turn = 0
        self.direction = 1
        self.penalty = 0
        self.last_action = "🎴 첫 카드가 공개됐습니다."

    @property
    def current_uid(self) -> int:
        return self.player_ids[self.turn]

    def _advance(self, steps: int = 1) -> None:
        self.turn = (self.turn + self.direction * steps) % len(self.player_ids)

    def _draw(self) -> Card:
        if not self.deck:
            top = self.discard.pop()
            self.deck = self.discard
            self.discard = [top]
            random.shuffle(self.deck)
        return self.deck.pop()

    def playable(self, card: Card) -> bool:
        top = self.discard[-1]
        if self.penalty > 0:
            return card[0] in {0, 2}
        if card[0] == 0 or top[0] == 0:
            return True
        return card[0] == top[0] or card[1] == top[1]

    def embed(self, final: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(
            title="🎴 원카드 생존전",
            description=final or f"{self.last_action}\n같은 **무늬 또는 숫자**를 내세요. `2`는 +2장, `🃏`는 +4장, `J`는 건너뛰기, `A`는 방향 전환입니다.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="바닥 카드", value=f"# **{_card_text(self.discard[-1])}**", inline=True)
        embed.add_field(name="현재 차례", value=f"👉 **{self.names[self.current_uid]}**", inline=True)
        embed.add_field(name="누적 벌칙", value=f"**{self.penalty}장**" if self.penalty else "없음", inline=True)
        counts = "\n".join(f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {len(self.hands[uid])}장" for uid in self.player_ids)
        embed.add_field(name="남은 카드", value=counts, inline=False)
        total_left = sum(len(hand) for hand in self.hands.values())
        embed.add_field(name="게임 진행", value=f"{_emoji_bar(1 - total_left / max(1, len(self.player_ids) * 5 + 15))} **남은 {total_left}장**", inline=False)
        embed.add_field(name="상금", value=f"**{self.pot:,}칩**", inline=True)
        embed.set_footer(text="내 패는 본인에게만 표시 · 손에 25장이 넘으면 앞 25장부터 선택")
        return embed

    async def start(self) -> None:
        self._reserve()
        await _safe_edit(self.message, embed=self.embed(), view=self)

    async def update(self) -> None:
        await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("참가자가 아닙니다.", ephemeral=True)
            return
        locale = getattr(self, "public_locale", "ko")
        from apocalypse_bot.commands.v1094_card_table_images import render_private_hand
        image = render_private_hand(
            locale=locale,
            title="원카드 · 내 패" if locale == "ko" else "One Card · My Hand",
            cards=self.hands[uid],
            note="현재 낼 수 있는 패는 카드 내기 메뉴에서 확인하세요." if locale == "ko" else "Use Play Card to see currently legal choices.",
        )
        filename = "abaddon_onecard_hand.png"
        embed = discord.Embed(title="🎴 내 패" if locale == "ko" else "🎴 My Hand", color=discord.Color.blurple())
        embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(embed=embed, file=discord.File(image, filename=filename), ephemeral=True)

    @discord.ui.button(label="카드 내기", emoji="🃏", style=discord.ButtonStyle.primary)
    async def choose_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid != self.current_uid:
            await interaction.response.send_message(f"지금은 **{self.names[self.current_uid]}** 님 차례입니다.", ephemeral=True)
            return
        await interaction.response.send_message("낼 카드를 선택하세요.", view=OneCardPlayView(self, uid), ephemeral=True)

    async def play_card(self, interaction: discord.Interaction, uid: int, index: int) -> None:
        async with self.lock:
            if self.done:
                await interaction.response.send_message("이미 게임이 끝났습니다.", ephemeral=True)
                return
            if int(interaction.user.id) != uid or uid != self.current_uid:
                await interaction.response.send_message("현재 본인 차례가 아닙니다.", ephemeral=True)
                return
            if index >= len(self.hands[uid]):
                await interaction.response.send_message("패가 바뀌었습니다. 다시 선택하세요.", ephemeral=True)
                return
            card = self.hands[uid][index]
            if not self.playable(card):
                await interaction.response.send_message("현재 바닥 카드에는 그 카드를 낼 수 없습니다.", ephemeral=True)
                return
            self.hands[uid].pop(index)
            self.discard.append(card)
            rank = card[0]
            steps = 1
            if rank == 2:
                self.penalty += 2
            elif rank == 0:
                self.penalty += 4
            else:
                self.penalty = 0
            if rank == 11:
                steps = 2
            elif rank == 14:
                self.direction *= -1
            self.last_action = f"{_card_text(card)} · **{self.names[uid]}** 님이 카드를 냈습니다."
            await interaction.response.edit_message(content=f"✅ {_card_text(card)} 제출 완료", view=None)
            if not self.hands[uid]:
                await self.finish(uid)
                return
            self._advance(steps)
            await self.update()

    @discord.ui.button(label="카드 뽑기", emoji="➕", style=discord.ButtonStyle.success)
    async def draw_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(f"지금은 **{self.names[self.current_uid]}** 님 차례입니다.", ephemeral=True)
                return
            count = self.penalty if self.penalty > 0 else 1
            cards = [self._draw() for _ in range(count)]
            self.hands[uid].extend(cards)
            self.penalty = 0
            self.last_action = f"➕ **{self.names[uid]}** 님이 {count}장을 뽑았습니다."
            self._advance()
            await interaction.response.send_message("뽑은 카드: " + " ".join(_card_text(card) for card in cards), ephemeral=True)
            await self.update()

    async def finish(self, winner: int) -> None:
        if self.done:
            return
        self.done = True
        payout = self._pay([winner])[winner]
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        result_rows = [f"🏆 **{self.names[winner]}** 님이 패를 모두 비워 승리했습니다!\n상금 **+{payout:,}칩**"]
        result_rows.extend(f"{'🏆' if uid == winner else '▫️'} **{self.names[uid]}**\n└ {self.settlement_text(uid)}" for uid in self.player_ids)
        text = "\n\n".join(result_rows)
        await _safe_edit(self.message, embed=self.embed(text), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        async with self.lock:
            if self.done:
                return
            self.done = True
            self._refund()
            self._disable()
            ACTIVE_GAMES.pop(self.channel_id, None)
            await _safe_edit(self.message, embed=self.embed("⌛ 진행 시간이 끝나 참가비를 전원 환불했습니다."), view=self)
            self.stop()


def _remove_pairs(cards: List[Card]) -> Tuple[List[Card], int]:
    by_rank: Dict[int, List[Card]] = {}
    joker_cards: List[Card] = []
    for card in cards:
        if card[0] == 0:
            joker_cards.append(card)
        else:
            by_rank.setdefault(card[0], []).append(card)
    remaining: List[Card] = list(joker_cards)
    removed = 0
    for rank_cards in by_rank.values():
        pairs = len(rank_cards) // 2
        removed += pairs * 2
        remaining.extend(rank_cards[pairs * 2:])
    random.shuffle(remaining)
    return remaining, removed


class JokerSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView) -> None:
        super().__init__(lobby, timeout=240)
        deck = [(rank, suit) for suit in SUITS for rank in range(2, 15)] + [(0, "🃏")]
        random.shuffle(deck)
        self.hands: Dict[int, List[Card]] = {uid: [] for uid in self.player_ids}
        for index, card in enumerate(deck):
            self.hands[self.player_ids[index % len(self.player_ids)]].append(card)
        self.removed: Dict[int, int] = {}
        for uid in self.player_ids:
            self.hands[uid], self.removed[uid] = _remove_pairs(self.hands[uid])
        self.active = [uid for uid in self.player_ids if self.hands[uid]]
        self.turn = 0
        self.last_action = "🧹 시작 패에서 같은 숫자 짝을 자동으로 버렸습니다."

    @property
    def current_uid(self) -> int:
        return self.active[self.turn % len(self.active)]

    def _next_target(self) -> int:
        return self.active[(self.turn + 1) % len(self.active)]

    def embed(self, final: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(
            title="🃏 조커잡기",
            description=final or f"{self.last_action}\n내 차례에 다음 생존자의 패에서 무작위 한 장을 뽑습니다. 같은 숫자 짝은 자동 제거됩니다.",
            color=discord.Color.fuchsia(),
        )
        rows = []
        for uid in self.player_ids:
            status = "완료" if not self.hands[uid] else f"{len(self.hands[uid])}장"
            marker = "👉" if uid in self.active and uid == self.current_uid else "▫️"
            rows.append(f"{marker} **{self.names[uid]}** · {status} · 짝 {self.removed.get(uid, 0)//2}개")
        embed.add_field(name="생존자 현황", value="\n".join(rows), inline=False)
        embed.add_field(name="현재 차례", value=f"**{self.names[self.current_uid]}** → {self.names[self._next_target()]}에게서 뽑기", inline=False)
        embed.add_field(name="상금", value=f"**{self.pot:,}칩** · 조커 보유자 제외 분배", inline=True)
        remaining = sum(len(hand) for hand in self.hands.values())
        embed.add_field(name="진행", value=f"{_emoji_bar(1 - remaining / 53)} **남은 {remaining}장**", inline=False)
        return embed

    async def start(self) -> None:
        self._reserve()
        if len(self.active) <= 1:
            await self.finish(self.active[0] if self.active else self.player_ids[0])
            return
        await _safe_edit(self.message, embed=self.embed(), view=self)

    async def update(self) -> None:
        await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("참가자가 아닙니다.", ephemeral=True)
            return
        cards = self.hands[uid]
        locale = getattr(self, "public_locale", "ko")
        from apocalypse_bot.commands.v1094_card_table_images import render_private_hand
        image = render_private_hand(
            locale=locale,
            title="조커잡기 · 내 패" if locale == "ko" else "Old Maid · My Hand",
            cards=cards,
            note=("짝을 모두 버렸다면 다음 차례를 기다리세요." if locale == "ko" else "If all pairs are gone, wait for the next turn."),
        )
        filename = "abaddon_oldmaid_hand.png"
        embed = discord.Embed(title="🃏 내 패" if locale == "ko" else "🃏 My Hand", color=discord.Color.fuchsia())
        embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(embed=embed, file=discord.File(image, filename=filename), ephemeral=True)

    @discord.ui.button(label="다음 사람에게서 뽑기", emoji="🎴", style=discord.ButtonStyle.primary)
    async def draw_from_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(f"지금은 **{self.names[self.current_uid]}** 님 차례입니다.", ephemeral=True)
                return
            target = self._next_target()
            card = random.choice(self.hands[target])
            self.hands[target].remove(card)
            self.hands[uid].append(card)
            before = len(self.hands[uid])
            self.hands[uid], removed = _remove_pairs(self.hands[uid])
            self.removed[uid] += removed
            self.last_action = f"🎴 **{self.names[uid]}** 님이 {self.names[target]}에게서 한 장을 뽑았습니다."
            if removed:
                self.last_action += f" · 짝 {removed // 2}개 제거!"
            await interaction.response.send_message(f"뽑은 카드: **{_card_text(card)}**" + (f" · 짝 {removed // 2}개 제거" if removed else ""), ephemeral=True)
            self.active = [pid for pid in self.active if self.hands[pid]]
            if len(self.active) <= 1:
                loser = self.active[0] if self.active else uid
                await self.finish(loser)
                return
            if uid in self.active:
                self.turn = self.active.index(uid)
                self.turn = (self.turn + 1) % len(self.active)
            else:
                self.turn %= len(self.active)
            await self.update()

    async def finish(self, loser: int) -> None:
        if self.done:
            return
        self.done = True
        winners = [uid for uid in self.player_ids if uid != loser]
        payouts = self._pay(winners)
        rows = [f"💀 **{self.names[loser]}** 님이 마지막 조커를 보유했습니다.\n└ {self.settlement_text(loser)}"]
        rows.extend(f"🏆 **{self.names[uid]}** · +{payouts[uid]:,}칩\n└ {self.settlement_text(uid)}" for uid in winners)
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed("\n".join(rows)), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        async with self.lock:
            if self.done:
                return
            self.done = True
            self._refund()
            self._disable()
            ACTIVE_GAMES.pop(self.channel_id, None)
            await _safe_edit(self.message, embed=self.embed("⌛ 진행 시간이 끝나 참가비를 전원 환불했습니다."), view=self)
            self.stop()


class CardGameBetModal(discord.ui.Modal):
    bet_input = discord.ui.TextInput(label="참가비(칩)", placeholder="예: 10000", min_length=1, max_length=12)

    def __init__(self, *, kind: str, create_lobby: Callable[..., Any]) -> None:
        super().__init__(title=f"{kind} 방 만들기")
        self.kind = kind
        self.create_lobby = create_lobby

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            bet = int(str(self.bet_input.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("참가비는 숫자로 입력하세요.", ephemeral=True)
            return
        error = _validate_bet(bet)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok, detail = await self.create_lobby(interaction, self.kind, bet)
        await interaction.followup.send(detail, ephemeral=True)


class CardGameSelect(discord.ui.Select):
    def __init__(self, create_lobby: Callable[..., Any]) -> None:
        self.create_lobby = create_lobby
        super().__init__(
            placeholder="시작할 카드게임을 고르세요",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="생존자 포커", value="포커", emoji="♠️", description="2~6명 · 한 장 교환 후 족보 승부"),
                discord.SelectOption(label="원카드", value="원카드", emoji="🎴", description="2~6명 · 턴제 카드 내기"),
                discord.SelectOption(label="조커잡기", value="조커잡기", emoji="🃏", description="2~8명 · 마지막 조커 피하기"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CardGameBetModal(kind=self.values[0], create_lobby=self.create_lobby))


class CardGameMenuView(discord.ui.View):
    def __init__(self, create_lobby: Callable[..., Any]) -> None:
        super().__init__(timeout=180)
        self.add_item(CardGameSelect(create_lobby))


def register_v651_card_games(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Mapping[str, Dict[str, Any]],
    guide: List[Dict[str, Any]],
) -> None:
    _guide_update(guide)
    root = _reservation_root(world_data)
    stale = list(root.get("reservations", {}).values())
    if stale:
        for reservation in stale:
            amount = int(reservation.get("bet", 0) or 0)
            for uid in reservation.get("players", []):
                try:
                    add_casino_chips(get_user(int(uid)), amount)
                except Exception:
                    continue
        root["reservations"] = {}
        save_data()

    async def create_lobby_from_interaction(interaction: discord.Interaction, kind: str, bet: int) -> Tuple[bool, str]:
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            return False, "서버 텍스트 채널에서만 시작할 수 있습니다."
        channel_id = int(channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            return False, "이 채널에서 이미 카드게임이 진행 중입니다."
        if str(interaction.user.id) not in user_data and int(interaction.user.id) not in user_data:
            return False, "먼저 `!가입`으로 생존자를 등록하세요."
        min_players, max_players = (2, 8) if kind == "조커잡기" else (2, 6)
        factory_map = {"포커": PokerSession, "원카드": OneCardSession, "조커잡기": JokerSession}
        lobby = CardLobbyView(
            bot=bot,
            kind=kind,
            host=interaction.user,
            bet=bet,
            get_user=get_user,
            save_data=save_data,
            world_data=world_data,
            user_data=user_data,
            start_factory=factory_map[kind],
            min_players=min_players,
            max_players=max_players,
        )
        lobby.channel_id = channel_id
        message = await channel.send(embed=lobby.embed(), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby
        return True, f"✅ {kind} 모집방을 만들었습니다: {message.jump_url}"

    async def create_lobby_from_ctx(ctx: commands.Context, kind: str, bet: int) -> None:
        if not await check_registered(ctx):
            return
        error = _validate_bet(int(bet))
        if error:
            await ctx.send(error)
            return
        channel_id = int(ctx.channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            await ctx.send("⚠️ 이 채널에서 이미 카드게임이 진행 중입니다.")
            return
        user = get_user(ctx.author.id)
        min_players, max_players = (2, 8) if kind == "조커잡기" else (2, 6)
        factory_map = {"포커": PokerSession, "원카드": OneCardSession, "조커잡기": JokerSession}
        lobby = CardLobbyView(
            bot=bot,
            kind=kind,
            host=ctx.author,
            bet=bet,
            get_user=get_user,
            save_data=save_data,
            world_data=world_data,
            user_data=user_data,
            start_factory=factory_map[kind],
            min_players=min_players,
            max_players=max_players,
        )
        lobby.channel_id = channel_id
        message = await ctx.send(embed=lobby.embed(), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby

    @bot.command(name="카드게임", aliases=["카드게임메뉴", "카드놀이"])
    async def card_games(ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="🃏 ABADDON 카드게임",
            description="드롭다운에서 게임을 고르고 참가비를 입력하면 모집방이 열립니다. 혼자라면 **🤖 아바돈 초대**로 즉시 1:1 대전을 시작할 수 있습니다.",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="♠️ 포커", value="비공개 5장 · 한 장 교환 · 족보 승부", inline=False)
        embed.add_field(name="🎴 원카드", value="턴제 선택 · 같은 무늬/숫자 · 특수 카드", inline=False)
        embed.add_field(name="🃏 조커잡기", value="짝 자동 제거 · 옆 사람 패에서 뽑기 · 마지막 조커 패배", inline=False)
        embed.set_footer(text=f"최소 참가비 {MIN_BET:,}칩 · 상한 없음 · 잔액 음수 허용 · 시간 초과 시 전원 환불")
        await ctx.send(embed=embed, view=CardGameMenuView(create_lobby_from_interaction))

    @bot.command(name="포커", aliases=["생존자포커"])
    async def poker(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_from_ctx(ctx, "포커", 참가비)

    @bot.command(name="원카드", aliases=["원카드게임"])
    async def one_card(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_from_ctx(ctx, "원카드", 참가비)

    @bot.command(name="조커잡기", aliases=["조커게임", "도둑잡기"])
    async def joker_game(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_from_ctx(ctx, "조커잡기", 참가비)

    bot.v651_card_games_version = VERSION
    bot.v651_card_game_commands = ("카드게임", "포커", "원카드", "조커잡기")
