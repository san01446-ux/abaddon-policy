from __future__ import annotations

"""ABADDON v10.5.1 authentic interactive card-game sessions.

This module replaces one-click score comparisons with the same turn/action
engine for human multiplayer and ABADDON seats. Wallets may go below zero and
no economic upper limit is imposed on raises or hwatu multipliers.
"""

import asyncio
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import (
    ABADDON_AI_ID,
    ACTIVE_GAMES,
    BaseCardSession,
    CardLobbyView,
    JokerSession,
    OneCardSession,
    _card_text,
    _deck,
    _poker_score,
    _remove_pairs,
    _safe_edit,
)
from apocalypse_bot.commands.v1010_companion_card_games import (
    HwatuCard,
    _best_five,
    _best_omaha,
    _hwatu_deck,
    _hwatu_labels,
    _hwatu_score,
    _hwatu_text,
    _hwatu_visual_uid,
    _interaction_locale,
    _locale,
    _poker_label,
    _t,
    record_companion_card_game,
)
from apocalypse_bot.commands.v1050_rules import (
    HwatuSummary,
    badugi_score,
    best_short_deck,
    hwatu_multiplier,
    normalize_hwatu_rules,
    record_game_result,
    advance_season,
)
from apocalypse_bot.commands.v1051_rules import (
    GoStopEngine,
    HwatuCardLite,
    baccarat_deal,
    baccarat_outcome,
    baccarat_return,
    baccarat_total,
    hwatu_payment_units,
    resolve_seotda,
    seotda_deck,
    seotda_rank,
)

VERSION = "10.5.1"
V1100_DEFAULT_RAISE_LIMIT = 1_000_000_000_000_000
V1100_HARD_RAISE_LIMIT = 1_000_000_000_000_000_000

def _v1100_raise_limit(session: Any) -> int:
    try:
        root = session.world_data.setdefault("v1100_game_city", {})
        settings = root.setdefault("betting", {})
        guilds = settings.setdefault("guilds", {})
        guild_id = int(getattr(getattr(session.message, "guild", None), "id", 0) or 0)
        row = guilds.get(str(guild_id), {}) if isinstance(guilds, Mapping) else {}
        value = int(row.get("max_raise", settings.get("default_max_raise", V1100_DEFAULT_RAISE_LIMIT)))
    except Exception:
        value = V1100_DEFAULT_RAISE_LIMIT
    return max(1_000, min(V1100_HARD_RAISE_LIMIT, value))
Card = Tuple[int, str]


def is_ai(uid: int) -> bool:
    return int(uid) < 0


def public_locale(bot: commands.Bot, message: Optional[discord.Message]) -> str:
    guild_id = getattr(getattr(message, "guild", None), "id", 0)
    return _locale(bot, 0, guild_id)


def format_chips(value: int, locale: str) -> str:
    return f"{int(value):,}{'칩' if locale == 'ko' else ' chips'}"


def seotda_card_text(card: Any, locale: str) -> str:
    kind = {"bright": ("광", "Bright"), "animal": ("열끗", "Animal"), "ribbon": ("띠", "Ribbon")}.get(str(card.kind), (str(card.kind), str(card.kind)))
    return f"{int(card.month)}월 {kind[0]}" if locale == "ko" else f"Month {int(card.month)} · {kind[1]}"


def seotda_rank_text(name: str, locale: str) -> str:
    if locale == "ko":
        return str(name)
    exact = {
        "삼팔광땡": "38 Bright Pair", "일삼광땡": "13 Bright Pair", "일팔광땡": "18 Bright Pair",
        "장땡": "Ten Pair", "알리": "Ali", "독사": "Doksa", "구삥": "Guping",
        "장삥": "Jangping", "장사": "Jangsa", "세륙": "Seryuk", "갑오": "Gabo",
        "망통": "Mangtong", "땡잡이": "Ddang Catcher", "암행어사": "Secret Inspector",
        "구사": "Gusa", "멍텅구리 구사": "Meong-Gusa",
    }
    if name in exact:
        return exact[name]
    if str(name).endswith("땡"):
        return f"Pair {str(name)[:-1]}"
    if str(name).endswith("끗"):
        return f"{str(name)[:-1]} points"
    return str(name)


def hwatu_event_text(event: str, locale: str) -> str:
    if locale == "ko":
        return str(event)
    return {
        "폭탄": "Bomb", "폭탄 보너스 뒤집기": "Bomb bonus flip", "뻑": "Ppuk",
        "뻑 회수": "Ppuk capture", "따닥": "Ttadak", "쪽": "Jjok", "쓸": "Sweep",
    }.get(str(event), str(event))


def record_table_results(
    session: BaseCardSession,
    outcomes: Mapping[int, str],
    net_changes: Mapping[int, int],
    *,
    scores: Optional[Mapping[int, int]] = None,
) -> None:
    """Persist v10.5 stats/season/companion hooks for authentic tables."""
    versus_ai = any(is_ai(uid) for uid in session.player_ids)
    for uid in session.player_ids:
        if is_ai(uid):
            continue
        user = session.get_user(uid)
        outcome = outcomes.get(uid, "draw")
        record_game_result(
            user, session.kind, outcome, earnings=int(net_changes.get(uid, 0)),
            score=int((scores or {}).get(uid, 0)), versus_ai=versus_ai,
        )
        record_companion_card_game(user)
        advance_season(user, "play_games", 1)
        if versus_ai:
            advance_season(user, "ai_games", 1)
        if outcome == "win":
            advance_season(user, "win_games", 1)


def localize_children(view: discord.ui.View, locale: str) -> None:
    if locale != "en":
        return
    labels = {
        "체크/콜": "Check / Call", "레이즈": "Raise", "폴드": "Fold",
        "내 패": "View Hand", "내 패 보기": "View Hand", "카드 교환": "Draw Cards",
        "교환 없음": "Stand Pat", "파인애플 버리기": "Discard Hole Card",
        "상대 패 보기": "View Opponents", "히트": "Hit", "스탠드": "Stand",
        "더블": "Double", "플레이어": "Player", "뱅커": "Banker", "타이": "Tie",
        "패 내기": "Play Card", "폭탄": "Bomb", "흔들기": "Shake",
        "보너스 뒤집기": "Bonus Flip", "고": "Go", "스톱": "Stop",
        "카드 내기": "Play Card", "카드 뽑기": "Draw Card",
        "다음 사람에게서 뽑기": "Draw from Next", "삥": "Ping", "따당": "Double",
        "쿼터": "Quarter", "하프": "Half",
    }
    for child in view.children:
        label = getattr(child, "label", None)
        if label in labels:
            child.label = labels[label]


# ---------------------------------------------------------------------------
# Shared uncapped betting engine
# ---------------------------------------------------------------------------
class RaiseModal(discord.ui.Modal):
    def __init__(self, session: "BettingSession", locale: str) -> None:
        super().__init__(title=_t(locale, "레이즈 금액", "Raise Amount"))
        self.session = session
        self.locale = locale
        self.amount = discord.ui.TextInput(
            label=_t(locale, "이번 라운드 총 베팅액", "Total bet for this round"),
            placeholder=str(max(session.current_bet + 1, session.bet)),
            min_length=1,
            max_length=30,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            target = int(str(self.amount.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True)
            return
        limit = _v1100_raise_limit(self.session)
        if target > limit:
            await interaction.response.send_message(_t(self.locale, f"레이즈 안전 한도는 {limit:,}칩입니다. 잔액보다 크게 잃으면 음수 잔액은 그대로 유지됩니다.", f"Raise safety limit is {limit:,} chips. Losses beyond the wallet still create a negative balance."), ephemeral=True)
            return
        await self.session.raise_to(interaction, target)


class BettingSession(BaseCardSession):
    """No-limit betting where wallets may become negative.

    The entry fee remains the ante. Every later call/raise is charged directly
    to a human wallet; synthetic ABADDON seats contribute virtual chips.
    """

    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, timeout: float = 480) -> None:
        super().__init__(lobby, timeout=timeout)
        self.bot = bot
        self.folded: set[int] = set()
        self.extra: Dict[int, int] = {uid: 0 for uid in self.player_ids}
        self.round_bets: Dict[int, int] = {uid: 0 for uid in self.player_ids}
        self.current_bet = 0
        self.acted: set[int] = set()
        self.turn_index = 0
        self.last_action = ""
        self._ai_running = False
        localize_children(self, getattr(lobby, "public_locale", "ko"))

    @property
    def live_players(self) -> List[int]:
        return [uid for uid in self.player_ids if uid not in self.folded]

    @property
    def current_uid(self) -> Optional[int]:
        live = self.live_players
        if len(live) <= 1:
            return None
        for offset in range(len(self.player_ids)):
            idx = (self.turn_index + offset) % len(self.player_ids)
            uid = self.player_ids[idx]
            if uid not in self.folded:
                self.turn_index = idx
                return uid
        return None

    @property
    def total_pot(self) -> int:
        return self.pot + sum(self.extra.values())

    def _charge(self, uid: int, amount: int) -> int:
        amount = max(0, int(amount))
        if amount == 0:
            return 0
        self.extra[uid] = int(self.extra.get(uid, 0)) + amount
        if not is_ai(uid):
            add_casino_chips(self.get_user(uid), -amount)
        return amount

    def _round_complete(self) -> bool:
        live = self.live_players
        if len(live) <= 1:
            return True
        return all(uid in self.acted and self.round_bets.get(uid, 0) == self.current_bet for uid in live)

    def _advance_turn(self) -> None:
        if self.player_ids:
            self.turn_index = (self.turn_index + 1) % len(self.player_ids)

    def _reset_betting(self, *, first_index: int = 0) -> None:
        self.round_bets = {uid: 0 for uid in self.player_ids}
        self.current_bet = 0
        self.acted.clear()
        self.turn_index = first_index % max(1, len(self.player_ids))

    async def _post_action(self, locale: str) -> None:
        if len(self.live_players) <= 1:
            await self.finish_fold_win(self.live_players[0], locale)
            return
        if self._round_complete():
            await self.advance_phase(locale)
            return
        await self.refresh()
        await self.run_ai_turns()

    async def check_call(self, interaction: discord.Interaction) -> None:
        locale = _interaction_locale(self.bot, interaction)
        uid = int(interaction.user.id)
        async with self.lock:
            if self.done or uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            need = max(0, self.current_bet - self.round_bets.get(uid, 0))
            paid = self._charge(uid, need)
            self.round_bets[uid] += paid
            self.acted.add(uid)
            self.last_action = _t(locale, f"{'콜' if need else '체크'} · {self.names[uid]} · {paid:,}칩", f"{'Call' if need else 'Check'} · {self.names[uid]} · {paid:,} chips")
            self._advance_turn()
            await interaction.response.defer()
            await self._post_action(locale)

    async def raise_to(self, interaction: discord.Interaction, target: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        uid = int(interaction.user.id)
        async with self.lock:
            if self.done or uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            target = int(target)
            limit = _v1100_raise_limit(self)
            if target > limit:
                await interaction.response.send_message(_t(locale, f"레이즈 안전 한도는 {limit:,}칩입니다.", f"Raise safety limit is {limit:,} chips."), ephemeral=True)
                return
            if target <= self.current_bet:
                await interaction.response.send_message(_t(locale, f"현재 베팅 {self.current_bet:,}칩보다 크게 입력하세요.", f"Enter more than the current bet of {self.current_bet:,} chips."), ephemeral=True)
                return
            additional = target - self.round_bets.get(uid, 0)
            self._charge(uid, additional)
            self.round_bets[uid] = target
            self.current_bet = target
            self.acted = {uid}
            self.last_action = _t(locale, f"레이즈 · {self.names[uid]} · 라운드 총 {target:,}칩", f"Raise · {self.names[uid]} · round total {target:,} chips")
            self._advance_turn()
            await interaction.response.defer()
            await self._post_action(locale)

    async def fold_action(self, interaction: discord.Interaction) -> None:
        locale = _interaction_locale(self.bot, interaction)
        uid = int(interaction.user.id)
        async with self.lock:
            if self.done or uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            self.folded.add(uid)
            self.acted.add(uid)
            self.last_action = _t(locale, f"폴드 · {self.names[uid]}", f"Fold · {self.names[uid]}")
            self._advance_turn()
            await interaction.response.defer()
            await self._post_action(locale)

    @discord.ui.button(label="체크/콜", emoji="✅", style=discord.ButtonStyle.success)
    async def check_call_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.check_call(interaction)

    @discord.ui.button(label="레이즈", emoji="📈", style=discord.ButtonStyle.primary)
    async def raise_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        if int(interaction.user.id) != self.current_uid:
            await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
            return
        await interaction.response.send_modal(RaiseModal(self, locale))

    @discord.ui.button(label="폴드", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def fold_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.fold_action(interaction)

    async def ai_action(self, uid: int) -> None:
        need = max(0, self.current_bet - self.round_bets.get(uid, 0))
        # Conservative but non-trivial: mostly call, occasionally raise or fold.
        if need > max(self.bet * 8, 1) and random.random() < 0.35:
            self.folded.add(uid)
            self.acted.add(uid)
            self.last_action = f"ABADDON · Fold"
        elif random.random() < 0.18:
            target = max(self.current_bet + max(1, self.bet // 2), self.bet)
            additional = target - self.round_bets.get(uid, 0)
            self._charge(uid, additional)
            self.round_bets[uid] = target
            self.current_bet = target
            self.acted = {uid}
            self.last_action = f"ABADDON · Raise {target:,}"
        else:
            self._charge(uid, need)
            self.round_bets[uid] += need
            self.acted.add(uid)
            self.last_action = f"ABADDON · {'Call' if need else 'Check'}"
        self._advance_turn()

    async def run_ai_turns(self) -> None:
        if self.done or self._ai_running:
            return
        self._ai_running = True
        try:
            guard = 0
            while not self.done and self.current_uid is not None and is_ai(self.current_uid):
                guard += 1
                if guard > 30:
                    break
                uid = int(self.current_uid)
                await self.ai_action(uid)
                if len(self.live_players) <= 1:
                    await self.finish_fold_win(self.live_players[0], self.locale())
                    break
                if self._round_complete():
                    await self.advance_phase(self.locale())
                    if self.done:
                        break
                else:
                    await self.refresh()
        finally:
            self._ai_running = False

    async def finish_fold_win(self, winner: int, locale: str) -> None:
        await self.finish_showdown(locale, forced_winners=[winner], reason=_t(locale, "모두 폴드하여 승리했습니다.", "Everyone else folded."))

    def locale(self) -> str:
        return public_locale(self.bot, self.message)

    async def refresh(self) -> None:
        await _safe_edit(self.message, embed=self.embed(self.locale()), view=self)

    async def start(self) -> None:
        self._reserve()
        await self.refresh()
        await self.run_ai_turns()

    async def advance_phase(self, locale: str) -> None:
        raise NotImplementedError

    async def finish_showdown(self, locale: str, *, forced_winners: Optional[Sequence[int]] = None, reason: str = "") -> None:
        raise NotImplementedError

    async def on_timeout(self) -> None:
        async with self.lock:
            if self.done:
                return
            self.done = True
            # Extra bets are also returned on technical timeout.
            for uid, amount in self.extra.items():
                if not is_ai(uid) and amount:
                    add_casino_chips(self.get_user(uid), amount)
            self._refund()
            self._disable()
            ACTIVE_GAMES.pop(self.channel_id, None)
            locale = self.locale()
            await _safe_edit(self.message, embed=self.embed(locale, _t(locale, "⌛ 시간 초과로 참가비와 추가 베팅을 모두 환불했습니다.", "⌛ Timeout: entry fees and extra bets were refunded.")), view=self)
            self.stop()


# ---------------------------------------------------------------------------
# Five-card draw
# ---------------------------------------------------------------------------
class DrawSelect(discord.ui.Select):
    def __init__(self, session: "FiveCardDrawSession", uid: int, locale: str) -> None:
        self.session, self.uid = session, uid
        options = [discord.SelectOption(label=f"{idx+1}. {_card_text(card)}", value=str(idx)) for idx, card in enumerate(session.hands[uid])]
        super().__init__(placeholder=_t(locale, "교환할 카드 1~3장 선택", "Choose 1–3 cards to draw"), min_values=1, max_values=min(3, len(options)), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.complete_draw(interaction, self.uid, [int(v) for v in self.values])


class DrawView(discord.ui.View):
    def __init__(self, session: "FiveCardDrawSession", uid: int, locale: str) -> None:
        super().__init__(timeout=60)
        self.add_item(DrawSelect(session, uid, locale))


class FiveCardDrawSession(BettingSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot) -> None:
        super().__init__(lobby, bot=bot)
        self.deck = _deck()
        self.hands = {uid: [self.deck.pop() for _ in range(5)] for uid in self.player_ids}
        self.phase = "bet1"
        self.draw_done: set[int] = set()

    def embed(self, locale: str, final: str = "") -> discord.Embed:
        desc = final or _t(locale, "1차 베팅 → 최대 3장 교환 → 2차 베팅 → 족보 공개 순서입니다.", "Bet → draw up to three cards → bet → showdown.")
        e = discord.Embed(title=_t(locale, "♠️ 정통 5장 포커", "♠️ Five-Card Draw"), description=desc, color=discord.Color.gold())
        phase = {"bet1": _t(locale, "1차 베팅", "First betting"), "draw": _t(locale, "교환", "Draw"), "bet2": _t(locale, "2차 베팅", "Final betting")}.get(self.phase, self.phase)
        e.add_field(name=_t(locale, "현재 단계", "Phase"), value=phase, inline=True)
        e.add_field(name=_t(locale, "현재 차례", "Turn"), value=self.names.get(self.current_uid, "-") if self.phase.startswith("bet") else _t(locale, "각자 교환 선택", "Choose your draw"), inline=True)
        e.add_field(name=_t(locale, "팟", "Pot"), value=format_chips(self.total_pot, locale), inline=True)
        rows = []
        for uid in self.player_ids:
            mark = "🏳️" if uid in self.folded else ("✅" if uid in self.draw_done else "▫️")
            rows.append(f"{mark} **{self.names[uid]}** · {self.round_bets.get(uid,0):,}")
        e.add_field(name=_t(locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        if self.last_action:
            e.add_field(name=_t(locale, "최근 행동", "Last Action"), value=self.last_action, inline=False)
        return e

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def hand_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a player."), ephemeral=True); return
        score, label = _poker_score(self.hands[uid])
        await interaction.response.send_message(f"{' '.join(_card_text(c) for c in self.hands[uid])}\n**{_poker_label(label, locale)}**", ephemeral=True)

    @discord.ui.button(label="카드 교환", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def draw_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if self.phase != "draw" or uid in self.folded or uid in self.draw_done:
            await interaction.response.send_message(_t(locale, "지금은 교환할 수 없습니다.", "You cannot draw now."), ephemeral=True); return
        await interaction.response.send_message(_t(locale, "교환할 패를 고르세요.", "Choose cards to replace."), view=DrawView(self, uid, locale), ephemeral=True)

    @discord.ui.button(label="교환 없음", emoji="✋", style=discord.ButtonStyle.secondary, row=1)
    async def stand_pat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.complete_draw(interaction, int(interaction.user.id), [])

    async def complete_draw(self, interaction: discord.Interaction, uid: int, indices: Sequence[int]) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if self.phase != "draw" or uid != int(interaction.user.id) or uid in self.folded or uid in self.draw_done:
                await interaction.response.send_message(_t(locale, "지금은 교환할 수 없습니다.", "You cannot draw now."), ephemeral=True); return
            picks = sorted(set(int(i) for i in indices if 0 <= int(i) < 5), reverse=True)[:3]
            for idx in picks:
                self.hands[uid][idx] = self.deck.pop()
            self.draw_done.add(uid)
            await interaction.response.edit_message(content=_t(locale, f"🔄 {len(picks)}장 교환 완료", f"🔄 Replaced {len(picks)} card(s)"), view=None)
            await self._after_draw_choices(locale)

    async def _after_draw_choices(self, locale: str) -> None:
        live = set(self.live_players)
        if live.issubset(self.draw_done):
            self.phase = "bet2"; self._reset_betting()
            await self.refresh(); await self.run_ai_turns()
        else:
            await self.refresh()
            await self.run_ai_draws(locale)

    async def run_ai_draws(self, locale: str) -> None:
        if self.phase != "draw": return
        for uid in self.live_players:
            if not is_ai(uid) or uid in self.draw_done: continue
            counts = Counter(rank for rank, _ in self.hands[uid])
            keep = {rank for rank, n in counts.items() if n >= 2}
            candidates = [i for i, (rank, _) in enumerate(self.hands[uid]) if rank not in keep]
            candidates.sort(key=lambda i: self.hands[uid][i][0])
            for idx in sorted(candidates[:3], reverse=True): self.hands[uid][idx] = self.deck.pop()
            self.draw_done.add(uid)
        if set(self.live_players).issubset(self.draw_done):
            self.phase = "bet2"; self._reset_betting(); await self.refresh(); await self.run_ai_turns()

    async def advance_phase(self, locale: str) -> None:
        if self.phase == "bet1":
            self.phase = "draw"; self.draw_done = set(self.folded)
            await self.refresh(); await self.run_ai_draws(locale)
        else:
            await self.finish_showdown(locale)

    async def finish_showdown(self, locale: str, *, forced_winners: Optional[Sequence[int]] = None, reason: str = "") -> None:
        if self.done: return
        self.done = True
        live = self.live_players
        scores = {uid: _poker_score(self.hands[uid]) for uid in live}
        winners = list(forced_winners or [uid for uid in live if scores[uid][0] == max(v[0] for v in scores.values())])
        payouts = self._pay_custom(winners)
        record_table_results(
            self,
            {uid: ("win" if uid in winners else "loss") for uid in self.player_ids},
            {uid: int(payouts.get(uid, 0)) - self.bet - int(self.extra.get(uid, 0)) for uid in self.player_ids},
            scores={uid: int(scores[uid][0][0]) for uid in live},
        )
        self.save_data()
        rows=[]
        for uid in self.player_ids:
            if uid in self.folded: rows.append(f"🏳️ **{self.names[uid]}** · Fold"); continue
            score,label=scores[uid]; rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {' '.join(_card_text(c) for c in self.hands[uid])} · {_poker_label(label, locale)}" + (f" · +{payouts.get(uid,0):,}" if payouts.get(uid) else ""))
        await self._finish_ui(locale, (reason+"\n" if reason else "")+"\n".join(rows))

    def _pay_custom(self, winners: Sequence[int]) -> Dict[int,int]:
        total=self.total_pot; base=total//len(winners); rem=total%len(winners); out={}
        for i,uid in enumerate(winners):
            amount=base+(1 if i<rem else 0); out[uid]=amount
            if not is_ai(uid): add_casino_chips(self.get_user(uid), amount)
        self._close_reservation(); self.save_data(); return out

    async def _finish_ui(self, locale: str, text: str) -> None:
        self._disable(); ACTIVE_GAMES.pop(self.channel_id,None)
        await _safe_edit(self.message, embed=self.embed(locale,text), view=self); self.stop()


# ---------------------------------------------------------------------------
# Community-card poker: Texas, Omaha, Pineapple, Short Deck
# ---------------------------------------------------------------------------
class PineappleDiscardSelect(discord.ui.Select):
    def __init__(self, session: "CommunityPokerSession", uid: int, locale: str) -> None:
        self.session,self.uid=session,uid
        super().__init__(placeholder=_t(locale,"버릴 홀카드 한 장","Discard one hole card"), min_values=1,max_values=1,
                         options=[discord.SelectOption(label=f"{i+1}. {_card_text(c)}",value=str(i)) for i,c in enumerate(session.hands[uid])])
    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.discard_pineapple(interaction,self.uid,int(self.values[0]))

class PineappleDiscardView(discord.ui.View):
    def __init__(self,session:"CommunityPokerSession",uid:int,locale:str)->None:
        super().__init__(timeout=60); self.add_item(PineappleDiscardSelect(session,uid,locale))

class CommunityPokerSession(BettingSession):
    CONFIG={
        "텍사스홀덤": (2,"texas"), "오마하홀덤": (4,"omaha"),
        "파인애플홀덤": (3,"pineapple"), "숏덱홀덤": (2,"short"),
    }
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot,kind:str)->None:
        super().__init__(lobby,bot=bot); self.variant=kind
        hole,mode=self.CONFIG[kind]; self.mode=mode
        self.deck=[(r,s) for s in ("♠️","♥️","♦️","♣️") for r in range(6,15)] if mode=="short" else _deck(); random.shuffle(self.deck)
        self.hands={uid:[self.deck.pop() for _ in range(hole)] for uid in self.player_ids}; self.board=[self.deck.pop() for _ in range(5)]
        self.street=0; self.board_counts=[0,3,4,5]; self.discard_done:set[int]=set()
        self.phase="discard" if mode=="pineapple" else "bet"

    def title(self,locale:str)->str:
        en={"텍사스홀덤":"Texas Hold'em","오마하홀덤":"Omaha Hold'em","파인애플홀덤":"Pineapple Hold'em","숏덱홀덤":"Short-Deck Hold'em"}
        return self.variant if locale=="ko" else en[self.variant]

    def embed(self,locale:str,final:str="")->discord.Embed:
        desc=final or _t(locale,"프리플랍·플랍·턴·리버마다 체크·콜·레이즈·폴드를 직접 선택합니다.","Choose check/call, raise, or fold on every street.")
        e=discord.Embed(title=f"♣️ {self.title(locale)}",description=desc,color=discord.Color.gold())
        visible=self.board_counts[self.street]
        e.add_field(name=_t(locale,"커뮤니티 카드","Community Cards"),value=" ".join(_card_text(c) for c in self.board[:visible]) or _t(locale,"프리플랍","Pre-flop"),inline=False)
        phase=_t(locale,"홀카드 1장 버리기","Discard one hole card") if self.phase=="discard" else ["프리플랍","플랍","턴","리버"][self.street] if locale=="ko" else ["Pre-flop","Flop","Turn","River"][self.street]
        e.add_field(name=_t(locale,"단계","Street"),value=phase,inline=True); e.add_field(name=_t(locale,"현재 차례","Turn"),value=self.names.get(self.current_uid,"-") if self.phase=="bet" else "-",inline=True); e.add_field(name=_t(locale,"팟","Pot"),value=format_chips(self.total_pot,locale),inline=True)
        rows=[f"{'🏳️' if uid in self.folded else '▫️'} **{self.names[uid]}** · {self.round_bets.get(uid,0):,}" for uid in self.player_ids]
        e.add_field(name=_t(locale,"참가자","Players"),value="\n".join(rows),inline=False)
        if self.last_action:e.add_field(name=_t(locale,"최근 행동","Last Action"),value=self.last_action,inline=False)
        return e

    @discord.ui.button(label="내 패",emoji="👁️",style=discord.ButtonStyle.secondary,row=1)
    async def show_hand(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        uid=int(interaction.user.id); locale=_interaction_locale(self.bot,interaction)
        if uid not in self.hands: await interaction.response.send_message(_t(locale,"참가자가 아닙니다.","You are not a player."),ephemeral=True); return
        await interaction.response.send_message(" ".join(_card_text(c) for c in self.hands[uid]),ephemeral=True)

    @discord.ui.button(label="파인애플 버리기",emoji="🍍",style=discord.ButtonStyle.secondary,row=1)
    async def pineapple_button(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        uid=int(interaction.user.id); locale=_interaction_locale(self.bot,interaction)
        if self.phase!="discard" or uid in self.discard_done or uid in self.folded:
            await interaction.response.send_message(_t(locale,"지금은 버릴 수 없습니다.","You cannot discard now."),ephemeral=True); return
        await interaction.response.send_message(_t(locale,"버릴 홀카드를 선택하세요.","Choose the hole card to discard."),view=PineappleDiscardView(self,uid,locale),ephemeral=True)

    async def discard_pineapple(self,interaction:discord.Interaction,uid:int,index:int)->None:
        locale=_interaction_locale(self.bot,interaction)
        async with self.lock:
            if self.phase!="discard" or uid!=int(interaction.user.id) or uid in self.discard_done or not 0<=index<len(self.hands[uid]):
                await interaction.response.send_message(_t(locale,"선택이 유효하지 않습니다.","Invalid selection."),ephemeral=True); return
            self.hands[uid].pop(index); self.discard_done.add(uid)
            await interaction.response.edit_message(content=_t(locale,"🍍 한 장을 버렸습니다.","🍍 Discard complete."),view=None)
            await self._finish_discards(locale)

    async def _finish_discards(self,locale:str)->None:
        for uid in self.live_players:
            if is_ai(uid) and uid not in self.discard_done:
                # Discard the card producing the best current two-card high potential.
                self.hands[uid].pop(min(range(3),key=lambda i:self.hands[uid][i][0])); self.discard_done.add(uid)
        if set(self.live_players).issubset(self.discard_done): self.phase="bet"; self._reset_betting(); await self.refresh(); await self.run_ai_turns()
        else: await self.refresh()

    async def start(self)->None:
        self._reserve(); await self.refresh()
        if self.phase=="discard": await self._finish_discards(self.locale())
        else: await self.run_ai_turns()

    async def advance_phase(self,locale:str)->None:
        if self.street>=3: await self.finish_showdown(locale); return
        self.street+=1; self._reset_betting(); await self.refresh(); await self.run_ai_turns()

    def score(self,uid:int)->Tuple[Tuple[int,...],str,Tuple[Card,...]]:
        if self.mode=="omaha": return _best_omaha(self.hands[uid],self.board)
        if self.mode=="short": return best_short_deck(self.hands[uid]+self.board)
        return _best_five(self.hands[uid]+self.board)

    async def finish_showdown(self,locale:str,*,forced_winners:Optional[Sequence[int]]=None,reason:str="")->None:
        if self.done:return
        self.done=True; live=self.live_players; scores={uid:self.score(uid) for uid in live}
        winners=list(forced_winners or [uid for uid in live if scores[uid][0]==max(v[0] for v in scores.values())]); payouts=self._pay_total(winners)
        record_table_results(self,{uid:("win" if uid in winners else "loss") for uid in self.player_ids},{uid:int(payouts.get(uid,0))-self.bet-int(self.extra.get(uid,0)) for uid in self.player_ids},scores={uid:int(scores[uid][0][0]) for uid in live})
        self.save_data()
        rows=[]
        for uid in self.player_ids:
            if uid in self.folded: rows.append(f"🏳️ **{self.names[uid]}** · Fold"); continue
            _,label,best=scores[uid]; rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {' '.join(_card_text(c) for c in best)} · {_poker_label(label,locale)}"+(f" · +{payouts.get(uid,0):,}" if payouts.get(uid) else ""))
        self._disable(); ACTIVE_GAMES.pop(self.channel_id,None); await _safe_edit(self.message,embed=self.embed(locale,(reason+"\n" if reason else "")+"\n".join(rows)),view=self); self.stop()

    def _pay_total(self,winners:Sequence[int])->Dict[int,int]:
        total=self.total_pot;base=total//len(winners);rem=total%len(winners);out={}
        for i,uid in enumerate(winners):
            amount=base+(i<rem);out[uid]=int(amount)
            if not is_ai(uid):add_casino_chips(self.get_user(uid),int(amount))
        self._close_reservation();self.save_data();return out


# ---------------------------------------------------------------------------
# Seven-card stud / High-Low split
# ---------------------------------------------------------------------------
class StudSession(BettingSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot,high_low:bool=False)->None:
        super().__init__(lobby,bot=bot);self.high_low=high_low;self.deck=_deck();self.hands={uid:[self.deck.pop() for _ in range(3)] for uid in self.player_ids};self.stage=3
    def embed(self,locale:str,final:str="")->discord.Embed:
        title=_t(locale,"↕️ 세븐카드 하이로우","↕️ Seven-Card High-Low") if self.high_low else _t(locale,"🎩 세븐카드 스터드","🎩 Seven-Card Stud")
        e=discord.Embed(title=title,description=final or _t(locale,"3장부터 시작해 각 스트리트마다 한 장씩 받고 직접 베팅합니다.","Start with three cards, receive one per street, and bet each round."),color=discord.Color.gold())
        rows=[]
        for uid in self.player_ids:
            shown=self.hands[uid][2:6] if self.stage<7 else self.hands[uid][2:6]
            rows.append(f"{'🏳️' if uid in self.folded else '▫️'} **{self.names[uid]}** · "+(" ".join(_card_text(c) for c in shown) or "-"))
        e.add_field(name=_t(locale,"공개 카드","Up Cards"),value="\n".join(rows),inline=False);e.add_field(name=_t(locale,"현재 장수","Cards"),value=str(self.stage),inline=True);e.add_field(name=_t(locale,"현재 차례","Turn"),value=self.names.get(self.current_uid,"-"),inline=True);e.add_field(name=_t(locale,"팟","Pot"),value=format_chips(self.total_pot,locale),inline=True)
        if self.last_action:e.add_field(name=_t(locale,"최근 행동","Last Action"),value=self.last_action,inline=False)
        return e
    @discord.ui.button(label="내 패",emoji="👁️",style=discord.ButtonStyle.secondary,row=1)
    async def show_hand(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        uid=int(interaction.user.id);locale=_interaction_locale(self.bot,interaction)
        if uid not in self.hands:await interaction.response.send_message(_t(locale,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        await interaction.response.send_message(" ".join(_card_text(c) for c in self.hands[uid]),ephemeral=True)
    async def advance_phase(self,locale:str)->None:
        if self.stage>=7:await self.finish_showdown(locale);return
        self.stage+=1
        for uid in self.live_players:self.hands[uid].append(self.deck.pop())
        self._reset_betting();await self.refresh();await self.run_ai_turns()
    async def finish_showdown(self,locale:str,*,forced_winners:Optional[Sequence[int]]=None,reason:str="")->None:
        if self.done:return
        self.done=True;live=self.live_players;high={uid:_best_five(self.hands[uid]) for uid in live}
        if forced_winners:winners=list(forced_winners); low_winners=[]
        else:
            best=max(v[0] for v in high.values());winners=[uid for uid,v in high.items() if v[0]==best];low_winners=[]
            if self.high_low:
                from apocalypse_bot.commands.v1051_rules import ace_to_five_low_eight_or_better
                lows={uid:ace_to_five_low_eight_or_better(self.hands[uid]) for uid in live};valid={u:v for u,v in lows.items() if v is not None}
                if valid:
                    low=min(valid.values());low_winners=[u for u,v in valid.items() if v==low]
        payouts=self._split_pay(winners,low_winners)
        all_winners=set(winners)|set(low_winners)
        record_table_results(self,{uid:("win" if uid in all_winners else "loss") for uid in self.player_ids},{uid:int(payouts.get(uid,0))-self.bet-int(self.extra.get(uid,0)) for uid in self.player_ids},scores={uid:int(high[uid][0][0]) for uid in live})
        self.save_data()
        rows=[]
        for uid in self.player_ids:
            if uid in self.folded:rows.append(f"🏳️ **{self.names[uid]}** · Fold");continue
            _,label,best=high[uid];mark="🏆" if uid in set(winners)|set(low_winners) else "▫️";rows.append(f"{mark} **{self.names[uid]}** · {' '.join(_card_text(c) for c in best)} · {_poker_label(label,locale)}"+(f" · +{payouts.get(uid,0):,}" if payouts.get(uid) else ""))
        self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(locale,(reason+"\n" if reason else "")+"\n".join(rows)),view=self);self.stop()
    def _split_pay(self,high:Sequence[int],low:Sequence[int])->Dict[int,int]:
        out:Dict[int,int]={};total=self.total_pot
        groups=[(total,high)] if not low else [(total//2+total%2,high),(total//2,low)]
        for amount,winners in groups:
            base=amount//len(winners);rem=amount%len(winners)
            for i,uid in enumerate(winners):out[uid]=out.get(uid,0)+base+(i<rem)
        for uid,amount in out.items():
            if not is_ai(uid):add_casino_chips(self.get_user(uid),int(amount))
        self._close_reservation();self.save_data();return {u:int(v) for u,v in out.items()}


# ---------------------------------------------------------------------------
# Badugi: three draw rounds
# ---------------------------------------------------------------------------
class BadugiSelect(discord.ui.Select):
    def __init__(self,session:"BadugiSession",uid:int,locale:str)->None:
        self.session,self.uid=session,uid
        super().__init__(placeholder=_t(locale,"교환할 카드 선택","Choose cards to replace"),min_values=1,max_values=4,options=[discord.SelectOption(label=f"{i+1}. {_card_text(c)}",value=str(i)) for i,c in enumerate(session.hands[uid])])
    async def callback(self,interaction:discord.Interaction)->None:await self.session.draw_cards(interaction,self.uid,[int(v) for v in self.values])
class BadugiView(discord.ui.View):
    def __init__(self,s:"BadugiSession",uid:int,l:str)->None:super().__init__(timeout=60);self.add_item(BadugiSelect(s,uid,l))
class BadugiSession(BettingSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot)->None:
        super().__init__(lobby,bot=bot);self.deck=_deck();self.hands={u:[self.deck.pop() for _ in range(4)] for u in self.player_ids};self.draw_round=0;self.phase="bet";self.draw_done:set[int]=set()
    def embed(self,locale:str,final:str="")->discord.Embed:
        e=discord.Embed(title=_t(locale,"🀄 바둑이","🀄 Badugi"),description=final or _t(locale,"베팅 후 최대 3번 카드를 교환해 서로 다른 무늬·숫자의 가장 낮은 패를 만듭니다.","Bet and draw up to three times to make the lowest four-card rainbow hand."),color=discord.Color.dark_teal())
        e.add_field(name=_t(locale,"단계","Phase"),value=_t(locale,f"{'베팅' if self.phase=='bet' else '교환'} · {self.draw_round}/3",f"{'Betting' if self.phase=='bet' else 'Draw'} · {self.draw_round}/3"),inline=True);e.add_field(name=_t(locale,"현재 차례","Turn"),value=self.names.get(self.current_uid,"-") if self.phase=="bet" else "-",inline=True);e.add_field(name=_t(locale,"팟","Pot"),value=format_chips(self.total_pot,locale),inline=True)
        if self.last_action:e.add_field(name=_t(locale,"최근 행동","Last Action"),value=self.last_action,inline=False)
        return e
    @discord.ui.button(label="내 패",emoji="👁️",style=discord.ButtonStyle.secondary,row=1)
    async def hand(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        uid=int(interaction.user.id);locale=_interaction_locale(self.bot,interaction)
        if uid not in self.hands:await interaction.response.send_message(_t(locale,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        count,key,best=badugi_score(self.hands[uid]);await interaction.response.send_message(f"{' '.join(_card_text(c) for c in self.hands[uid])}\n**{count}-card Badugi · {key}**",ephemeral=True)
    @discord.ui.button(label="카드 교환",emoji="🔄",style=discord.ButtonStyle.secondary,row=1)
    async def draw_button(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        uid=int(interaction.user.id);locale=_interaction_locale(self.bot,interaction)
        if self.phase!="draw" or uid in self.draw_done or uid in self.folded:await interaction.response.send_message(_t(locale,"지금은 교환할 수 없습니다.","You cannot draw now."),ephemeral=True);return
        await interaction.response.send_message(_t(locale,"교환할 카드를 고르세요.","Choose cards to replace."),view=BadugiView(self,uid,locale),ephemeral=True)
    @discord.ui.button(label="교환 없음",emoji="✋",style=discord.ButtonStyle.secondary,row=1)
    async def no_draw(self,interaction:discord.Interaction,_:discord.ui.Button)->None:await self.draw_cards(interaction,int(interaction.user.id),[])
    async def draw_cards(self,interaction:discord.Interaction,uid:int,indices:Sequence[int])->None:
        locale=_interaction_locale(self.bot,interaction)
        async with self.lock:
            if self.phase!="draw" or uid!=int(interaction.user.id) or uid in self.draw_done or uid in self.folded:await interaction.response.send_message(_t(locale,"유효하지 않은 교환입니다.","Invalid draw."),ephemeral=True);return
            for idx in sorted(set(indices),reverse=True):
                if 0<=idx<4:self.hands[uid][idx]=self.deck.pop()
            self.draw_done.add(uid);await interaction.response.edit_message(content=_t(locale,f"🔄 {len(set(indices))}장 교환 완료",f"🔄 Replaced {len(set(indices))} card(s)"),view=None);await self._after_draw(locale)
    async def _after_draw(self,locale:str)->None:
        for uid in self.live_players:
            if is_ai(uid) and uid not in self.draw_done:
                _,_,best=badugi_score(self.hands[uid]);keep=set(best);idxs=[i for i,c in enumerate(self.hands[uid]) if c not in keep]
                for i in idxs:self.hands[uid][i]=self.deck.pop()
                self.draw_done.add(uid)
        if set(self.live_players).issubset(self.draw_done):self.phase="bet";self._reset_betting();await self.refresh();await self.run_ai_turns()
        else:await self.refresh()
    async def advance_phase(self,locale:str)->None:
        if self.draw_round>=3:await self.finish_showdown(locale);return
        self.draw_round+=1;self.phase="draw";self.draw_done=set(self.folded);await self.refresh();await self._after_draw(locale)
    async def finish_showdown(self,locale:str,*,forced_winners:Optional[Sequence[int]]=None,reason:str="")->None:
        if self.done:return
        self.done=True;live=self.live_players;scores={u:badugi_score(self.hands[u]) for u in live}
        def key(u:int)->Tuple[int,Tuple[int,...]]:c,r,_=scores[u];return(c,tuple(-x for x in r))
        winners=list(forced_winners or [u for u in live if key(u)==max(key(v) for v in live)]);payouts=self._pay_total(winners)
        record_table_results(self,{u:("win" if u in winners else "loss") for u in self.player_ids},{u:int(payouts.get(u,0))-self.bet-int(self.extra.get(u,0)) for u in self.player_ids},scores={u:int(scores[u][0]) for u in live})
        self.save_data()
        rows=[]
        for u in self.player_ids:
            if u in self.folded:rows.append(f"🏳️ **{self.names[u]}** · Fold");continue
            c,r,b=scores[u];rows.append(f"{'🏆' if u in winners else '▫️'} **{self.names[u]}** · {' '.join(_card_text(x) for x in b)} · {c}-card {r}"+(f" · +{payouts.get(u,0):,}" if payouts.get(u) else ""))
        self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(locale,(reason+"\n" if reason else "")+"\n".join(rows)),view=self);self.stop()
    def _pay_total(self,w:Sequence[int])->Dict[int,int]:
        total=self.total_pot;base=total//len(w);rem=total%len(w);out={}
        for i,u in enumerate(w):a=base+(i<rem);out[u]=int(a);not is_ai(u) and add_casino_chips(self.get_user(u),int(a))
        self._close_reservation();self.save_data();return out


# ---------------------------------------------------------------------------
# Indian Poker
# ---------------------------------------------------------------------------
class IndianPokerSession(BettingSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot)->None:
        super().__init__(lobby,bot=bot);self.deck=_deck();self.hands={u:[self.deck.pop()] for u in self.player_ids}
    def embed(self,locale:str,final:str="")->discord.Embed:
        e=discord.Embed(title=_t(locale,"🪶 인디언 포커","🪶 Indian Poker"),description=final or _t(locale,"내 카드는 보이지 않고 상대 카드만 확인한 뒤 한 번의 베팅 라운드를 진행합니다.","Your own card is hidden; view opponents' cards, then complete one betting round."),color=discord.Color.orange())
        e.add_field(name=_t(locale,"현재 차례","Turn"),value=self.names.get(self.current_uid,"-"),inline=True);e.add_field(name=_t(locale,"팟","Pot"),value=format_chips(self.total_pot,locale),inline=True)
        if self.last_action:e.add_field(name=_t(locale,"최근 행동","Last Action"),value=self.last_action,inline=False)
        return e
    @discord.ui.button(label="상대 패 보기",emoji="👁️",style=discord.ButtonStyle.secondary,row=1)
    async def view_others(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        uid=int(interaction.user.id);locale=_interaction_locale(self.bot,interaction)
        if uid not in self.hands:await interaction.response.send_message(_t(locale,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        rows=[f"**{self.names[o]}** · {_card_text(self.hands[o][0])}" for o in self.player_ids if o!=uid]
        await interaction.response.send_message("\n".join(rows)+"\n\n"+_t(locale,"내 카드는 승부 전까지 비공개입니다.","Your own card stays hidden until showdown."),ephemeral=True)
    async def advance_phase(self,locale:str)->None:await self.finish_showdown(locale)
    async def finish_showdown(self,locale:str,*,forced_winners:Optional[Sequence[int]]=None,reason:str="")->None:
        if self.done:return
        self.done=True;live=self.live_players;w=list(forced_winners or [u for u in live if self.hands[u][0][0]==max(self.hands[v][0][0] for v in live)]);p=self._pay_total(w)
        record_table_results(self,{u:("win" if u in w else "loss") for u in self.player_ids},{u:int(p.get(u,0))-self.bet-int(self.extra.get(u,0)) for u in self.player_ids},scores={u:int(self.hands[u][0][0]) for u in live})
        self.save_data()
        rows=[f"{'🏆' if u in w else ('🏳️' if u in self.folded else '▫️')} **{self.names[u]}** · {_card_text(self.hands[u][0])}"+(f" · +{p.get(u,0):,}" if p.get(u) else "") for u in self.player_ids]
        self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(locale,(reason+"\n" if reason else "")+"\n".join(rows)),view=self);self.stop()
    def _pay_total(self,w:Sequence[int])->Dict[int,int]:
        total=self.total_pot;base=total//len(w);rem=total%len(w);out={}
        for i,u in enumerate(w):a=base+(i<rem);out[u]=int(a);not is_ai(u) and add_casino_chips(self.get_user(u),int(a))
        self._close_reservation();self.save_data();return out


# ---------------------------------------------------------------------------
# Blackjack with hit / stand / double
# ---------------------------------------------------------------------------
def blackjack_value(cards:Sequence[Card])->Tuple[int,bool]:
    total=0;aces=0
    for rank,_ in cards:
        if rank==14:total+=11;aces+=1
        elif rank>=10:total+=10
        else:total+=rank
    while total>21 and aces:total-=10;aces-=1
    return total,aces>0

class AuthenticBlackjackSession(BaseCardSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot)->None:
        super().__init__(lobby,timeout=360);self.bot=bot;self.deck=_deck()*4;random.shuffle(self.deck);self.hands={u:[self.deck.pop(),self.deck.pop()] for u in self.player_ids};self.dealer=[self.deck.pop(),self.deck.pop()];self.stakes={u:self.bet for u in self.player_ids};self.finished:set[int]=set();self.turn=0;self._ai_running=False;localize_children(self,getattr(lobby,"public_locale","ko"))
    @property
    def current_uid(self)->Optional[int]:
        for _ in range(len(self.player_ids)):
            u=self.player_ids[self.turn%len(self.player_ids)]
            if u not in self.finished:return u
            self.turn=(self.turn+1)%len(self.player_ids)
        return None
    def locale(self)->str:return public_locale(self.bot,self.message)
    def embed(self,locale:str,final:str="")->discord.Embed:
        e=discord.Embed(title=_t(locale,"🃏 정통 블랙잭","🃏 Blackjack"),description=final or _t(locale,"히트·스탠드·더블다운을 직접 선택하세요. 딜러는 17 이상에서 멈춥니다.","Choose hit, stand, or double down. Dealer stands on 17."),color=discord.Color.green())
        e.add_field(name=_t(locale,"딜러","Dealer"),value=_card_text(self.dealer[0])+"  🂠",inline=False)
        rows=[f"{'✅' if u in self.finished else ('👉' if u==self.current_uid else '▫️')} **{self.names[u]}** · {len(self.hands[u])} cards · stake {self.stakes[u]:,}" for u in self.player_ids]
        e.add_field(name=_t(locale,"참가자","Players"),value="\n".join(rows),inline=False);return e
    async def start(self)->None:self._reserve();await _safe_edit(self.message,embed=self.embed(self.locale()),view=self);await self.run_ai()
    @discord.ui.button(label="내 패",emoji="👁️",style=discord.ButtonStyle.secondary)
    async def hand(self,interaction:discord.Interaction,_:discord.ui.Button)->None:
        u=int(interaction.user.id);l=_interaction_locale(self.bot,interaction)
        if u not in self.hands:await interaction.response.send_message(_t(l,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        t,s=blackjack_value(self.hands[u]);await interaction.response.send_message(f"{' '.join(_card_text(c) for c in self.hands[u])} · **{t}{' soft' if s else ''}**",ephemeral=True)
    async def _act(self,interaction:discord.Interaction,kind:str)->None:
        l=_interaction_locale(self.bot,interaction);u=int(interaction.user.id)
        async with self.lock:
            if u!=self.current_uid:await interaction.response.send_message(_t(l,"현재 본인 차례가 아닙니다.","It is not your turn."),ephemeral=True);return
            text=""
            if kind=="hit":
                c=self.deck.pop();self.hands[u].append(c);t,_=blackjack_value(self.hands[u]);text=f"{_card_text(c)} · {t}"
                if t>=21:self.finished.add(u);self.turn=(self.turn+1)%len(self.player_ids)
            elif kind=="stand":self.finished.add(u);self.turn=(self.turn+1)%len(self.player_ids);text=_t(l,"스탠드","Stand")
            else:
                if len(self.hands[u])!=2:await interaction.response.send_message(_t(l,"첫 두 장에서만 더블다운할 수 있습니다.","Double down is only available on the first two cards."),ephemeral=True);return
                if not is_ai(u):add_casino_chips(self.get_user(u),-self.bet)
                self.stakes[u]+=self.bet;c=self.deck.pop();self.hands[u].append(c);self.finished.add(u);self.turn=(self.turn+1)%len(self.player_ids);text=f"Double · {_card_text(c)}"
            await interaction.response.send_message(text,ephemeral=True)
            if self.current_uid is None:await self.finish(l)
            else:await _safe_edit(self.message,embed=self.embed(self.locale()),view=self);await self.run_ai()
    @discord.ui.button(label="히트",emoji="➕",style=discord.ButtonStyle.success)
    async def hit(self,i:discord.Interaction,b:discord.ui.Button)->None:await self._act(i,"hit")
    @discord.ui.button(label="스탠드",emoji="✋",style=discord.ButtonStyle.primary)
    async def stand(self,i:discord.Interaction,b:discord.ui.Button)->None:await self._act(i,"stand")
    @discord.ui.button(label="더블",emoji="✖️",style=discord.ButtonStyle.danger)
    async def double(self,i:discord.Interaction,b:discord.ui.Button)->None:await self._act(i,"double")
    async def run_ai(self)->None:
        if self._ai_running:return
        self._ai_running=True
        try:
            while self.current_uid is not None and is_ai(self.current_uid):
                u=int(self.current_uid);t,_=blackjack_value(self.hands[u])
                if len(self.hands[u])==2 and t in {10,11} and random.random()<.5:self.stakes[u]+=self.bet;self.hands[u].append(self.deck.pop());self.finished.add(u);self.turn=(self.turn+1)%len(self.player_ids)
                elif t<17:self.hands[u].append(self.deck.pop());t,_=blackjack_value(self.hands[u]);
                else:self.finished.add(u);self.turn=(self.turn+1)%len(self.player_ids)
                if t>=21:self.finished.add(u);self.turn=(self.turn+1)%len(self.player_ids)
            if self.current_uid is None and not self.done:await self.finish(self.locale())
            elif not self.done:await _safe_edit(self.message,embed=self.embed(self.locale()),view=self)
        finally:self._ai_running=False
    async def finish(self,locale:str)->None:
        if self.done:return
        self.done=True
        while blackjack_value(self.dealer)[0]<17:self.dealer.append(self.deck.pop())
        dt,_=blackjack_value(self.dealer);rows=[f"🤖 {_t(locale,'딜러','Dealer')} · {' '.join(_card_text(c) for c in self.dealer)} · **{dt}**"]
        payouts:Dict[int,int]={};outcomes:Dict[int,str]={};scores:Dict[int,int]={}
        for u in self.player_ids:
            t,_=blackjack_value(self.hands[u]);stake=self.stakes[u];natural=len(self.hands[u])==2 and t==21
            if t>21:payout=0;mark="💀";outcome="loss"
            elif dt>21 or t>dt:payout=int(stake*2.5) if natural else stake*2;mark="🏆";outcome="win"
            elif t==dt:payout=stake;mark="🤝";outcome="draw"
            else:payout=0;mark="▫️";outcome="loss"
            payouts[u]=int(payout);outcomes[u]=outcome;scores[u]=int(t)
            if not is_ai(u) and payout:add_casino_chips(self.get_user(u),payout)
            rows.append(f"{mark} **{self.names[u]}** · {' '.join(_card_text(c) for c in self.hands[u])} · {t} · {payout:+,}")
        record_table_results(self,outcomes,{u:int(payouts.get(u,0))-int(self.stakes[u]) for u in self.player_ids},scores=scores)
        self._close_reservation();self.save_data();self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(locale,"\n".join(rows)),view=self);self.stop()
    async def on_timeout(self)->None:
        if self.done:return
        self.done=True
        for u,stake in self.stakes.items():
            if not is_ai(u) and stake>self.bet:add_casino_chips(self.get_user(u),stake-self.bet)
        self._refund();self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(self.locale(),_t(self.locale(),"⌛ 전액 환불","⌛ Full refund")),view=self);self.stop()


# ---------------------------------------------------------------------------
# Baccarat: participants choose Player / Banker / Tie before one shared deal
# ---------------------------------------------------------------------------
class BaccaratSession(BaseCardSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot)->None:
        super().__init__(lobby,timeout=240);self.bot=bot;self.choices:Dict[int,str]={};localize_children(self,getattr(lobby,"public_locale","ko"))
    def locale(self)->str:return public_locale(self.bot,self.message)
    def embed(self,locale:str,final:str="")->discord.Embed:
        e=discord.Embed(title=_t(locale,"🎰 정통 바카라","🎰 Baccarat"),description=final or _t(locale,"각자 플레이어·뱅커·타이 중 하나를 선택하면 표준 3장 규칙으로 딜합니다.","Choose Player, Banker, or Tie; cards are then dealt using standard third-card rules."),color=discord.Color.purple())
        e.add_field(name=_t(locale,"선택 현황","Selections"),value="\n".join(f"{'✅' if u in self.choices else '▫️'} **{self.names[u]}**" for u in self.player_ids),inline=False);return e
    async def start(self)->None:
        self._reserve()
        for u in self.player_ids:
            if is_ai(u):self.choices[u]=random.choice(["player","banker","tie"])
        await _safe_edit(self.message,embed=self.embed(self.locale()),view=self)
        if len(self.choices)==len(self.player_ids):await self.finish(self.locale())
    async def choose(self,i:discord.Interaction,c:str)->None:
        l=_interaction_locale(self.bot,i);u=int(i.user.id)
        if u not in self.player_ids:await i.response.send_message(_t(l,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        self.choices[u]=c;await i.response.send_message(_t(l,"선택 완료","Choice saved"),ephemeral=True)
        if len(self.choices)==len(self.player_ids):await self.finish(l)
        else:await _safe_edit(self.message,embed=self.embed(self.locale()),view=self)
    @discord.ui.button(label="플레이어",emoji="🔵",style=discord.ButtonStyle.primary)
    async def player(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.choose(i,"player")
    @discord.ui.button(label="뱅커",emoji="🔴",style=discord.ButtonStyle.danger)
    async def banker(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.choose(i,"banker")
    @discord.ui.button(label="타이",emoji="🟢",style=discord.ButtonStyle.success)
    async def tie(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.choose(i,"tie")
    async def finish(self,locale:str)->None:
        if self.done:return
        self.done=True;deck=_deck()*6;random.shuffle(deck);p,b=baccarat_deal(deck);out=baccarat_outcome(p,b)
        names={"player":_t(locale,"플레이어","Player"),"banker":_t(locale,"뱅커","Banker"),"tie":_t(locale,"타이","Tie")};rows=[f"🔵 Player · {' '.join(_card_text(c) for c in p)} · {baccarat_total(p)}",f"🔴 Banker · {' '.join(_card_text(c) for c in b)} · {baccarat_total(b)}",f"🏁 {names[out]}"]
        returns:Dict[int,int]={};outcomes:Dict[int,str]={}
        for u,c in self.choices.items():
            ret=baccarat_return(self.bet,c,out);returns[u]=int(ret);outcomes[u]="win" if c==out else "loss"
            if not is_ai(u) and ret:add_casino_chips(self.get_user(u),ret)
            rows.append(f"{'🏆' if c==out else '▫️'} **{self.names[u]}** · {names[c]} · {ret:+,}")
        record_table_results(self,outcomes,{u:int(returns.get(u,0))-self.bet for u in self.player_ids},scores={u:baccarat_total(p) if self.choices.get(u)=="player" else baccarat_total(b) for u in self.player_ids})
        self._close_reservation();self.save_data();self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(locale,"\n".join(rows)),view=self);self.stop()
    async def on_timeout(self)->None:
        if self.done:return
        self.done=True;self._refund();self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(self.locale(),_t(self.locale(),"⌛ 전액 환불","⌛ Full refund")),view=self);self.stop()


# ---------------------------------------------------------------------------
# Seotda: two deal streets with betting
# ---------------------------------------------------------------------------
class SeotdaSession(BettingSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot)->None:
        super().__init__(lobby,bot=bot);self.deck=seotda_deck();random.shuffle(self.deck);self.hands={u:[self.deck.pop()] for u in self.player_ids};self.street=1;self.redeals=0
    def embed(self,locale:str,final:str="")->discord.Embed:
        e=discord.Embed(title=_t(locale,"🎴 섯다","🎴 Seotda"),description=final or _t(locale,"첫 패 베팅 → 둘째 패 베팅 → 족보 공개. 체크·콜·레이즈·폴드를 직접 선택합니다.","Bet after the first card, receive the second card, then bet and reveal."),color=discord.Color.red())
        e.add_field(name=_t(locale,"단계","Street"),value=_t(locale,f"{self.street}장째",f"Card {self.street}"),inline=True);e.add_field(name=_t(locale,"현재 차례","Turn"),value=self.names.get(self.current_uid,"-"),inline=True);e.add_field(name=_t(locale,"팟","Pot"),value=format_chips(self.total_pot,locale),inline=True)
        if self.last_action:e.add_field(name=_t(locale,"최근 행동","Last Action"),value=self.last_action,inline=False)
        return e
    @discord.ui.button(label="내 패",emoji="👁️",style=discord.ButtonStyle.secondary,row=1)
    async def hand(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        if u not in self.hands:await i.response.send_message(_t(l,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        cards=" ".join(seotda_card_text(c,l) for c in self.hands[u]);label=seotda_rank_text(seotda_rank(self.hands[u]).name,l) if len(self.hands[u])==2 else _t(l,"첫 패","First card");await i.response.send_message(f"{cards}\n**{label}**",ephemeral=True)
    async def shortcut_raise(self,interaction:discord.Interaction,mode:str)->None:
        locale=_interaction_locale(self.bot,interaction)
        if int(interaction.user.id)!=self.current_uid:
            await interaction.response.send_message(_t(locale,"현재 본인 차례가 아닙니다.","It is not your turn."),ephemeral=True);return
        if mode=="ping":target=max(self.current_bet+self.bet,self.bet)
        elif mode=="ddadang":target=max(self.current_bet*2,self.bet*2)
        elif mode=="quarter":target=max(self.current_bet+self.bet,self.current_bet+max(1,self.total_pot//4))
        else:target=max(self.current_bet+self.bet,self.current_bet+max(1,self.total_pot//2))
        await self.raise_to(interaction,target)
    @discord.ui.button(label="삥",emoji="🪙",style=discord.ButtonStyle.secondary,row=2)
    async def ping_button(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.shortcut_raise(i,"ping")
    @discord.ui.button(label="따당",emoji="✌️",style=discord.ButtonStyle.secondary,row=2)
    async def ddadang_button(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.shortcut_raise(i,"ddadang")
    @discord.ui.button(label="쿼터",emoji="🔹",style=discord.ButtonStyle.secondary,row=2)
    async def quarter_button(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.shortcut_raise(i,"quarter")
    @discord.ui.button(label="하프",emoji="🔸",style=discord.ButtonStyle.secondary,row=2)
    async def half_button(self,i:discord.Interaction,b:discord.ui.Button)->None:await self.shortcut_raise(i,"half")
    async def advance_phase(self,locale:str)->None:
        if self.street==1:
            self.street=2
            for u in self.live_players:self.hands[u].append(self.deck.pop())
            self._reset_betting();await self.refresh();await self.run_ai_turns()
        else:await self.finish_showdown(locale)
    async def finish_showdown(self,locale:str,*,forced_winners:Optional[Sequence[int]]=None,reason:str="")->None:
        if self.done:return
        live=self.live_players
        if forced_winners:w=list(forced_winners);ranks={u:seotda_rank(self.hands[u]) for u in live};status="win"
        else:status,w,ranks=resolve_seotda({u:self.hands[u] for u in live})
        if status=="redeal" and self.redeals<3:
            self.redeals+=1;self.deck=seotda_deck();random.shuffle(self.deck);self.hands={u:[self.deck.pop()] for u in self.player_ids};self.street=1;self._reset_betting();self.last_action=_t(locale,"구사 계열로 재경기합니다.","Gusa forces a redeal.");await self.refresh();await self.run_ai_turns();return
        self.done=True;p=self._pay_total(w)
        record_table_results(self,{u:("win" if u in w else "loss") for u in self.player_ids},{u:int(p.get(u,0))-self.bet-int(self.extra.get(u,0)) for u in self.player_ids},scores={u:int(ranks[u].category*100+ranks[u].tiebreak) for u in live})
        self.save_data();rows=[]
        for u in self.player_ids:
            if u in self.folded:rows.append(f"🏳️ **{self.names[u]}** · Fold");continue
            r=ranks[u];rows.append(f"{'🏆' if u in w else '▫️'} **{self.names[u]}** · {' '.join(seotda_card_text(c,locale) for c in self.hands[u])} · **{seotda_rank_text(r.name,locale)}**"+(f" · +{p.get(u,0):,}" if p.get(u) else ""))
        self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(locale,(reason+"\n" if reason else "")+"\n".join(rows)),view=self);self.stop()
    def _pay_total(self,w:Sequence[int])->Dict[int,int]:
        total=self.total_pot;base=total//len(w);rem=total%len(w);out={}
        for i,u in enumerate(w):a=base+(i<rem);out[u]=int(a);not is_ai(u) and add_casino_chips(self.get_user(u),int(a))
        self._close_reservation();self.save_data();return out


# ---------------------------------------------------------------------------
# Authentic Go-Stop / Matgo with ambiguous floor choices and uncapped debt
# ---------------------------------------------------------------------------
def to_lite(cards:Sequence[HwatuCard])->List[HwatuCardLite]:
    junk_seen: Dict[int, int] = {}
    return [HwatuCardLite(_hwatu_visual_uid(c,junk_seen),c.month,c.category,f"{c.ko}\x1f{c.en}",c.junk) for c in cards]
def lite_to_full(c:HwatuCardLite)->HwatuCard:
    ko,en=(str(c.name).split("\x1f",1)+[str(c.name)])[:2] if "\x1f" in str(c.name) else (str(c.name),str(c.name))
    return HwatuCard(c.month,c.category,ko,en,c.junk)
def hwatu_summary(cards:Sequence[HwatuCardLite])->HwatuSummary:
    full=[lite_to_full(c) for c in cards];score,labels=_hwatu_score(full);return HwatuSummary(score,sum(c.category.startswith("bright") for c in full),sum(c.category.startswith("animal") for c in full),sum(c.category.startswith("ribbon") for c in full),sum(c.junk for c in full),tuple(labels))
def lite_text(c:HwatuCardLite,locale:str)->str:return _hwatu_text(lite_to_full(c),locale)

class HwatuCardSelect(discord.ui.Select):
    def __init__(self,s:"AuthenticHwatuSession",u:int,l:str)->None:
        self.s,self.u=s,u;super().__init__(placeholder=_t(l,"낼 패 선택","Choose a card"),min_values=1,max_values=1,options=[discord.SelectOption(label=lite_text(c,l)[:100],value=str(i)) for i,c in enumerate(s.engine.hands[u])])
    async def callback(self,i:discord.Interaction)->None:await self.s.play_selected(i,self.u,int(self.values[0]))
class HwatuCardView(discord.ui.View):
    def __init__(self,s:"AuthenticHwatuSession",u:int,l:str)->None:super().__init__(timeout=60);self.add_item(HwatuCardSelect(s,u,l))
class HwatuFloorSelect(discord.ui.Select):
    def __init__(self,s:"AuthenticHwatuSession",u:int,hidx:int,kind:str,indices:Sequence[int],l:str)->None:
        self.s,self.u,self.hidx,self.kind=s,u,hidx,kind;super().__init__(placeholder=_t(l,"가져올 바닥패 선택","Choose the floor card"),min_values=1,max_values=1,options=[discord.SelectOption(label=lite_text(s.engine.floor[idx],l)[:100],value=str(idx)) for idx in indices])
    async def callback(self,i:discord.Interaction)->None:await self.s.resolve_choice(i,self.u,self.hidx,self.kind,int(self.values[0]))
class HwatuFloorView(discord.ui.View):
    def __init__(self,s:"AuthenticHwatuSession",u:int,h:int,k:str,idx:Sequence[int],l:str)->None:super().__init__(timeout=60);self.add_item(HwatuFloorSelect(s,u,h,k,idx,l))

class AuthenticHwatuSession(BaseCardSession):
    def __init__(self,lobby:CardLobbyView,*,bot:commands.Bot,mode:str,world_data:MutableMapping[str,Any])->None:
        super().__init__(lobby,timeout=720);self.bot=bot;self.mode=mode;self.world_data_ref=world_data;self.engine=GoStopEngine(self.player_ids,to_lite(_hwatu_deck()),matgo=(mode=="맞고"));self.go={u:0 for u in self.player_ids};self.prev_score={u:0 for u in self.player_ids};self.pending_go:Optional[int]=None;self.last_action="";self.shake_declared:set[int]=set();self.pending_matches:Dict[Tuple[int,int],int]={};self.pending_bomb_month:Dict[int,int]={};self._ai_running=False
        guild_id=int(getattr(getattr(lobby.message,"guild",None),"id",0) or 0);guild=world_data.setdefault("v1050_unified",{}).setdefault("guilds",{}).setdefault(str(guild_id),{});self.rules=normalize_hwatu_rules(guild.get("hwatu_rules"));guild.setdefault("hwatu_rules",dict(self.rules));localize_children(self,getattr(lobby,"public_locale","ko"))
    def locale(self)->str:return public_locale(self.bot,self.message)
    @property
    def current_uid(self)->int:return self.engine.current_uid
    def threshold(self)->int:return 7 if self.mode=="맞고" else 3
    def embed(self,locale:str,final:str="")->discord.Embed:
        e=discord.Embed(title=("🎴 맞고" if self.mode=="맞고" and locale=="ko" else "🎴 Matgo" if self.mode=="맞고" else "🌸 고스톱" if locale=="ko" else "🌸 Go-Stop"),description=final or _t(locale,"손패를 직접 내고 같은 월의 바닥패를 선택해 획득합니다. 뒤집기·뻑·쪽·따닥·쓸·고/스톱이 실제 턴으로 진행됩니다.","Play a hand card, choose matching floor cards, flip from stock, and resolve Go/Stop turn by turn."),color=discord.Color.dark_red())
        floor="\n".join(" · ".join(lite_text(c,locale) for c in self.engine.floor[i:i+4]) for i in range(0,len(self.engine.floor),4)) or "-";e.add_field(name=_t(locale,"바닥패","Floor"),value=floor[:1024],inline=False)
        rows=[]
        for u in self.player_ids:
            s=hwatu_summary(self.engine.captured[u]);rows.append(f"{'👉' if u==self.current_uid and self.pending_go is None else '▫️'} **{self.names[u]}** · {len(self.engine.hands[u])}{_t(locale,'장',' cards')} · {s.score}{_t(locale,'점',' pts')} · Go {self.go[u]} · {_t(locale,'피','Junk')} {s.junk_points}")
        e.add_field(name=_t(locale,"참가자","Players"),value="\n".join(rows),inline=False);e.add_field(name=_t(locale,"더미","Stock"),value=str(len(self.engine.stock)),inline=True);e.add_field(name=_t(locale,"기본 팟","Base Pot"),value=format_chips(self.pot,locale),inline=True)
        if self.last_action:e.add_field(name=_t(locale,"최근 턴","Last Turn"),value=self.last_action[:1024],inline=False)
        if self.pending_go is not None:e.add_field(name=_t(locale,"고/스톱","Go / Stop"),value=self.names[self.pending_go],inline=False)
        return e
    async def start(self)->None:
        self._reserve();chong=self.engine.chongtong_winners() if self.rules.get("chongtong",True) else []
        if chong:await self.finish([chong[0]],self.locale(),reason=_t(self.locale(),"총통 즉시 승리","Chongtong instant win"),chongtong=True);return
        await _safe_edit(self.message,embed=self.embed(self.locale()),view=self);await self.run_ai()
    @discord.ui.button(label="내 패",emoji="👁️",style=discord.ButtonStyle.secondary)
    async def hand(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        if u not in self.engine.hands:await i.response.send_message(_t(l,"참가자가 아닙니다.","You are not a player."),ephemeral=True);return
        s=hwatu_summary(self.engine.captured[u]);await i.response.send_message("\n".join(f"{n+1}. {lite_text(c,l)}" for n,c in enumerate(self.engine.hands[u]))+f"\n\n**{s.score}{_t(l,'점',' pts')} · {_hwatu_labels(s.labels,l)}**",ephemeral=True)
    @discord.ui.button(label="패 내기",emoji="🎴",style=discord.ButtonStyle.primary)
    async def play_button(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        if self.pending_go is not None or u!=self.current_uid:await i.response.send_message(_t(l,"현재 본인 차례가 아닙니다.","It is not your turn."),ephemeral=True);return
        await i.response.send_message(_t(l,"낼 패를 선택하세요.","Choose a card to play."),view=HwatuCardView(self,u,l),ephemeral=True)
    @discord.ui.button(label="폭탄",emoji="💣",style=discord.ButtonStyle.danger,row=1)
    async def bomb(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        async with self.lock:
            months=self.engine.can_bomb(u) if u==self.current_uid and self.rules.get("bomb",True) else []
            if not months:await i.response.send_message(_t(l,"사용 가능한 폭탄이 없습니다.","No bomb is available."),ephemeral=True);return
            month=months[0];r=self.engine.play_bomb(u,month)
            if r.needs_choice:
                self.pending_bomb_month[u]=month;k,idx=r.needs_choice;await i.response.send_message(_t(l,"폭탄 뒤집기와 맞을 바닥패를 선택하세요.","Choose the floor match for the bomb flip."),view=HwatuFloorView(self,u,-2,k,idx,l),ephemeral=True);return
            await i.response.send_message(_t(l,f"💣 {month}월 폭탄!",f"💣 Month {month} bomb!"),ephemeral=True);await self.after_turn(u,r,l)
    @discord.ui.button(label="흔들기",emoji="〰️",style=discord.ButtonStyle.secondary,row=1)
    async def shake(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i);months=self.engine.can_shake(u) if u in self.engine.hands and self.rules.get("shake",True) else []
        if not months or u in self.shake_declared:await i.response.send_message(_t(l,"흔들기를 선언할 수 없습니다.","You cannot declare a shake."),ephemeral=True);return
        self.engine.declare_shake(u,months[0]);self.shake_declared.add(u);await i.response.send_message(_t(l,f"〰️ {months[0]}월 흔들기 선언",f"〰️ Shake declared with Month {months[0]}"),ephemeral=True);await _safe_edit(self.message,embed=self.embed(self.locale()),view=self)
    @discord.ui.button(label="보너스 뒤집기",emoji="🃏",style=discord.ButtonStyle.secondary,row=1)
    async def skip_play(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        async with self.lock:
            try:r=self.engine.play(u,None,skip=True)
            except ValueError:await i.response.send_message(_t(l,"사용 가능한 폭탄 보너스가 없습니다.","No bomb bonus flip is available."),ephemeral=True);return
            if r.needs_choice:
                k,idx=r.needs_choice;await i.response.send_message(_t(l,"맞출 바닥패를 선택하세요.","Choose the matching floor card."),view=HwatuFloorView(self,u,-1,k,idx,l),ephemeral=True);return
            await i.response.send_message(_t(l,"보너스 뒤집기 완료","Bonus flip complete"),ephemeral=True);await self.after_turn(u,r,l)
    async def play_selected(self,i:discord.Interaction,u:int,hidx:int)->None:
        l=_interaction_locale(self.bot,i)
        async with self.lock:
            if u!=int(i.user.id) or u!=self.current_uid or self.pending_go is not None:await i.response.send_message(_t(l,"현재 본인 차례가 아닙니다.","It is not your turn."),ephemeral=True);return
            r=self.engine.play(u,hidx)
            if r.needs_choice:
                k,idx=r.needs_choice;await i.response.edit_message(content=_t(l,"가져올 바닥패를 선택하세요.","Choose the floor card to capture."),view=HwatuFloorView(self,u,hidx,k,idx,l));return
            await i.response.edit_message(content=_t(l,"✅ 턴 처리 완료","✅ Turn complete"),view=None);await self.after_turn(u,r,l)
    async def resolve_choice(self,i:discord.Interaction,u:int,hidx:int,kind:str,index:int)->None:
        l=_interaction_locale(self.bot,i)
        async with self.lock:
            key=(u,hidx)
            kwargs:Dict[str,int]={}
            if kind=="hand":
                self.pending_matches[key]=index
                kwargs["match_index"]=index
            else:
                if key in self.pending_matches:
                    kwargs["match_index"]=self.pending_matches[key]
                kwargs["flip_match_index"]=index
            if hidx==-2:
                month=self.pending_bomb_month.get(u)
                if month is None:raise ValueError("missing pending bomb")
                r=self.engine.play_bomb(u,month,flip_match_index=index)
            else:
                r=self.engine.play(u,None,skip=True,**kwargs) if hidx<0 else self.engine.play(u,hidx,**kwargs)
            if r.needs_choice:
                k,idx=r.needs_choice;await i.response.edit_message(content=_t(l,"뒤집은 패가 맞을 바닥패를 선택하세요.","Choose the floor match for the flipped card."),view=HwatuFloorView(self,u,hidx,k,idx,l));return
            self.pending_matches.pop(key,None);self.pending_bomb_month.pop(u,None)
            await i.response.edit_message(content=_t(l,"✅ 선택 완료","✅ Choice complete"),view=None);await self.after_turn(u,r,l)
    async def after_turn(self,u:int,r:Any,l:str)->None:
        parts=[]
        if r.played:parts.append(_t(l,"낸 패 ","Played ")+", ".join(lite_text(c,l) for c in r.played))
        if r.flipped:parts.append(_t(l,"뒤집기 ","Flip ")+lite_text(r.flipped,l))
        if r.captured:parts.append(_t(l,f"획득 {len(r.captured)}장",f"Captured {len(r.captured)}"))
        if r.events:parts.append(" · ".join(hwatu_event_text(event,l) for event in r.events))
        self.last_action=f"**{self.names[u]}** · "+" · ".join(parts)
        s=hwatu_summary(self.engine.captured[u]);old=self.prev_score[u];self.prev_score[u]=s.score
        if s.score>=self.threshold() and s.score>old and not self.engine.exhausted():self.pending_go=u;await _safe_edit(self.message,embed=self.embed(self.locale()),view=self);await self.run_ai();return
        if self.engine.exhausted():await self.finish_by_score(l);return
        await _safe_edit(self.message,embed=self.embed(self.locale()),view=self);await self.run_ai()
    @discord.ui.button(label="고",emoji="▶️",style=discord.ButtonStyle.success,row=2)
    async def go_button(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        if self.pending_go!=u:await i.response.send_message(_t(l,"지금은 고를 선택할 수 없습니다.","Go is not available now."),ephemeral=True);return
        self.go[u]+=1;self.pending_go=None;await i.response.send_message(_t(l,f"▶️ {self.go[u]}고",f"▶️ Go {self.go[u]}"),ephemeral=True);await _safe_edit(self.message,embed=self.embed(self.locale()),view=self);await self.run_ai()
    @discord.ui.button(label="스톱",emoji="⏹️",style=discord.ButtonStyle.danger,row=2)
    async def stop_button(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=_interaction_locale(self.bot,i)
        if self.pending_go!=u:await i.response.send_message(_t(l,"지금은 스톱할 수 없습니다.","Stop is not available now."),ephemeral=True);return
        await i.response.defer();await self.finish([u],l,reason=_t(l,"스톱 선언","Stop declared"))
    async def run_ai(self)->None:
        if self.done or self._ai_running:return
        self._ai_running=True
        try:
            guard=0
            while not self.done:
                guard+=1
                if guard>80:break
                if self.pending_go is not None:
                    u=self.pending_go
                    if not is_ai(u):break
                    s=hwatu_summary(self.engine.captured[u]);
                    if s.score>=self.threshold()+2 or len(self.engine.stock)<5:await self.finish([u],self.locale(),reason="ABADDON Stop");break
                    self.go[u]+=1;self.pending_go=None;continue
                u=self.current_uid
                if not is_ai(u):break
                months=self.engine.can_bomb(u)
                if months and self.rules.get("bomb",True) and random.random()<.7:
                    r=self.engine.play_bomb(u,months[0])
                    if r.needs_choice:
                        _,opts=r.needs_choice;r=self.engine.play_bomb(u,months[0],flip_match_index=opts[0])
                else:
                    if self.rules.get("shake",True) and u not in self.shake_declared and self.engine.can_shake(u) and random.random()<.5:self.engine.declare_shake(u,self.engine.can_shake(u)[0]);self.shake_declared.add(u)
                    # Prefer a card that can match the floor.
                    hand=self.engine.hands[u];idx=max(range(len(hand)),key=lambda x:len(self.engine.matching_floor_indices(hand[x].month)))
                    r=self.engine.play(u,idx)
                    if r.needs_choice:
                        k,opts=r.needs_choice;kw={"match_index":opts[0]} if k=="hand" else {"flip_match_index":opts[0]};r=self.engine.play(u,idx,**kw)
                        if r.needs_choice:
                            k2,o2=r.needs_choice;kw2={"match_index":o2[0]} if k2=="hand" else {"flip_match_index":o2[0]};r=self.engine.play(u,idx,**{**kw,**kw2})
                self.last_action=f"**{self.names[u]}** · "+(" · ".join(hwatu_event_text(event,self.locale()) for event in r.events) if r.events else _t(self.locale(),"패 처리","Turn resolved"));s=hwatu_summary(self.engine.captured[u]);old=self.prev_score[u];self.prev_score[u]=s.score
                if s.score>=self.threshold() and s.score>old and not self.engine.exhausted():self.pending_go=u;continue
                if self.engine.exhausted():await self.finish_by_score(self.locale());break
                await _safe_edit(self.message,embed=self.embed(self.locale()),view=self)
        finally:self._ai_running=False
    async def finish_by_score(self,l:str)->None:
        scores={u:hwatu_summary(self.engine.captured[u]).score+self.go[u] for u in self.player_ids};hi=max(scores.values())
        if hi<=0 and self.rules.get("nagari",True):
            # Nagari: no cap on carry multiplier.
            state=self.world_data_ref.setdefault("v1050_unified",{}).setdefault("guilds",{}).setdefault(str(getattr(getattr(self.message,"guild",None),"id",0)),{});state["hwatu_next_multiplier"]=max(2,int(state.get("hwatu_next_multiplier",1))*2);self.done=True;self._refund();self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(l,_t(l,f"나가리 · 다음 판 x{state['hwatu_next_multiplier']}",f"Nagari · next round x{state['hwatu_next_multiplier']}")),view=self);self.stop();return
        await self.finish([u for u,v in scores.items() if v==hi],l,reason=_t(l,"패 소진 정산","Stock exhausted"))
    async def finish(self,winners:Sequence[int],l:str,*,reason:str="",chongtong:bool=False)->None:
        if self.done:return
        self.done=True;guild=self.world_data_ref.setdefault("v1050_unified",{}).setdefault("guilds",{}).setdefault(str(getattr(getattr(self.message,"guild",None),"id",0)),{});carry=max(1,int(guild.get("hwatu_next_multiplier",1)));guild["hwatu_next_multiplier"]=1
        # Ante pot first. Every human has already paid the ante, even into debt.
        base=self.pot//len(winners);rem=self.pot%len(winners);payouts:Dict[int,int]={};net={u:(-self.bet if not is_ai(u) else 0) for u in self.player_ids};settlement=[]
        for i,w in enumerate(winners):
            a=base+(i<rem);payouts[w]=int(a);net[w]=net.get(w,0)+int(a)
            if not is_ai(w):add_casino_chips(self.get_user(w),int(a))
        # Full point settlement: no wallet floor, no bet cap, no multiplier cap.
        for loser in [u for u in self.player_ids if u not in winners]:
            ls=hwatu_summary(self.engine.captured[loser])
            for w in winners:
                ws=hwatu_summary(self.engine.captured[w]);mult,reasons=hwatu_multiplier(ws,ls,go_count=self.go[w],shakes=self.engine.shakes[w],bombs=self.engine.bombs[w],loser_declared_go=self.go[loser]>0,nagari_multiplier=carry,rules=self.rules)
                units,_go_mult=hwatu_payment_units(4 if chongtong else ws.score,self.go[w]);total_mult=max(1,units*mult);extra=max(0,self.bet*(total_mult-1))
                if not is_ai(loser):add_casino_chips(self.get_user(loser),-extra)
                if not is_ai(w):add_casino_chips(self.get_user(w),extra)
                net[loser]=net.get(loser,0)-extra;net[w]=net.get(w,0)+extra;payouts[w]=payouts.get(w,0)+extra
                localized_reasons=[reason if l=="ko" else {"피박 x2":"Pi-bak x2","광박 x2":"Gwang-bak x2","멍따 x2":"Meong-tta x2","고박 x2":"Go-bak x2"}.get(reason,reason.replace("나가리","Nagari").replace("흔들기","Shake").replace("폭탄","Bomb").replace("회","x").replace("고 x","-Go x")) for reason in reasons]
                settlement.append(f"**{self.names[loser]} → {self.names[w]}** · {units} × {mult} = {total_mult}{_t(l,'배','x')} · {extra:+,}{_t(l,'칩',' chips')}"+(f" · {', '.join(localized_reasons)}" if localized_reasons else ""))
        scores={u:hwatu_summary(self.engine.captured[u]).score for u in self.player_ids};record_table_results(self,{u:("win" if u in winners else "loss") for u in self.player_ids},net,scores=scores)
        self._close_reservation();self.save_data();rows=[]
        for u in self.player_ids:
            s=hwatu_summary(self.engine.captured[u]);rows.append(f"{'🏆' if u in winners else '▫️'} **{self.names[u]}** · {s.score}{_t(l,'점',' pts')} · Go {self.go[u]} · {_hwatu_labels(s.labels,l)} · {_t(l,'피','Junk')} {s.junk_points} · 💣{self.engine.bombs[u]} 〰️{self.engine.shakes[u]} · {net.get(u,0):+,}{_t(l,'칩',' chips')}")
        detail=("\n\n"+_t(l,"**정산 계산**","**Settlement**")+"\n"+"\n".join(settlement)) if settlement else ""
        self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(l,reason+"\n\n"+"\n".join(rows)+detail),view=self);self.stop()
    async def on_timeout(self)->None:
        if self.done:return
        self.done=True;self._refund();self._disable();ACTIVE_GAMES.pop(self.channel_id,None);await _safe_edit(self.message,embed=self.embed(self.locale(),_t(self.locale(),"⌛ 전액 환불","⌛ Full refund")),view=self);self.stop()


# ---------------------------------------------------------------------------
# AI-enabled direct One Card and Old Maid
# ---------------------------------------------------------------------------
class AuthenticOneCardSession(OneCardSession):
    def __init__(self,lobby:CardLobbyView)->None:
        super().__init__(lobby);self._ai_running=False;self.public_locale=getattr(lobby,"public_locale","ko");localize_children(self,self.public_locale)
    def embed(self,final:Optional[str]=None)->discord.Embed:
        l=self.public_locale
        e=discord.Embed(title=_t(l,"🎴 원카드","🎴 One Card"),description=final or f"{self.last_action}\n"+_t(l,"같은 무늬 또는 숫자를 직접 내세요. 2는 +2, 조커는 +4, J는 건너뛰기, A는 방향 전환입니다.","Play the same suit or rank. 2 adds two, Joker adds four, Jack skips, and Ace reverses."),color=discord.Color.blurple())
        e.add_field(name=_t(l,"바닥 카드","Top Card"),value=f"**{_card_text(self.discard[-1])}**",inline=True);e.add_field(name=_t(l,"현재 차례","Turn"),value=f"**{self.names[self.current_uid]}**",inline=True);e.add_field(name=_t(l,"누적 벌칙","Penalty"),value=f"{self.penalty}{_t(l,'장',' cards')}" if self.penalty else _t(l,"없음","None"),inline=True)
        e.add_field(name=_t(l,"남은 카드","Cards Remaining"),value="\n".join(f"{'👉' if u==self.current_uid else '▫️'} **{self.names[u]}** · {len(self.hands[u])}{_t(l,'장',' cards')}" for u in self.player_ids),inline=False);e.add_field(name=_t(l,"상금","Prize"),value=format_chips(self.pot,l),inline=True);return e
    async def update(self)->None:
        await _safe_edit(self.message,embed=self.embed(),view=self)
        if not self.done and is_ai(self.current_uid) and not self._ai_running:asyncio.create_task(self.run_ai())
    async def start(self)->None:self._reserve();await self.update();await self.run_ai()
    async def finish(self,winner:int)->None:
        if self.done:return
        self.done=True
        payouts=self._pay([winner])
        rows=[]
        outcomes={}
        earnings={}
        for u in self.player_ids:
            payout=int(payouts.get(u,0))
            net=payout-int(self.bet)
            outcomes[u]="win" if u==winner else "loss"
            if is_ai(u):
                money=_t(self.public_locale,"AI 좌석","AI seat")
            else:
                current=casino_chips(self.get_user(u));before=current-net;sign="+" if net>=0 else ""
                money=(f"이번 게임 **{sign}{net:,}칩** · 잔액 **{before:,} → {current:,}칩**" if self.public_locale=="ko" else f"Game net **{sign}{net:,} chips** · balance **{before:,} → {current:,}**")
                earnings[u]=net
            rows.append(f"{'🏆' if u==winner else '▫️'} **{self.names[u]}** · {_t(self.public_locale,'승리','WIN') if u==winner else _t(self.public_locale,'패배','LOSS')}\n└ {money}")
        record_table_results(self,outcomes,earnings)
        self.save_data();self._disable();ACTIVE_GAMES.pop(self.channel_id,None)
        final=_t(self.public_locale,"🏆 원카드 승부 결과 · 최종 정산\n\n","🏆 One Card Result · Final Settlement\n\n")+"\n".join(rows)
        embed=self.embed(final);published=await _safe_edit(self.message,embed=embed,view=self)
        if not published:
            channel=getattr(self.message,"channel",None)
            if channel is not None and hasattr(channel,"send"):
                try:self.message=await channel.send(embed=embed,view=self)
                except Exception:pass
        self.stop()
    async def run_ai(self)->None:
        if self._ai_running:return
        self._ai_running=True
        try:
            while not self.done and is_ai(self.current_uid):
                u=self.current_uid;plays=[(i,c) for i,c in enumerate(self.hands[u]) if self.playable(c)]
                if plays:
                    i,c=max(plays,key=lambda x:(x[1][0] in {0,2,11,14},x[1][0]));self.hands[u].pop(i);self.discard.append(c);rank=c[0];steps=1
                    if rank==2:self.penalty+=2
                    elif rank==0:self.penalty+=4
                    else:self.penalty=0
                    if rank==11:steps=2
                    elif rank==14:self.direction*=-1
                    self.last_action=f"🃏 ABADDON · {_card_text(c)}"
                    if not self.hands[u]:await self.finish(u);break
                    self._advance(steps)
                else:
                    count=self.penalty if self.penalty>0 else 1;self.hands[u].extend(self._draw() for _ in range(count));self.penalty=0;self._advance();self.last_action=_t(self.public_locale,f"➕ ABADDON · {count}장",f"➕ ABADDON · {count} cards")
                await _safe_edit(self.message,embed=self.embed(),view=self)
        finally:self._ai_running=False


class OldMaidPositionSelect(discord.ui.Select):
    def __init__(self,session:"AuthenticJokerSession",uid:int,target:int,locale:str)->None:
        self.session,self.uid,self.target=session,uid,target
        options=[discord.SelectOption(label=_t(locale,f"뒷면 카드 {i+1}",f"Face-down card {i+1}"),value=str(i),emoji="🎴") for i in range(min(25,len(session.hands[target])))]
        super().__init__(placeholder=_t(locale,"뽑을 뒷면 카드 선택","Choose a face-down card"),min_values=1,max_values=1,options=options)
    async def callback(self,interaction:discord.Interaction)->None:await self.session.draw_position(interaction,self.uid,self.target,int(self.values[0]))
class OldMaidPositionView(discord.ui.View):
    def __init__(self,s:"AuthenticJokerSession",u:int,t:int,l:str)->None:super().__init__(timeout=60);self.add_item(OldMaidPositionSelect(s,u,t,l))

class AuthenticJokerSession(JokerSession):
    def __init__(self,lobby:CardLobbyView)->None:
        super().__init__(lobby);self._ai_running=False;self.public_locale=getattr(lobby,"public_locale","ko");localize_children(self,self.public_locale)
    def embed(self,final:Optional[str]=None)->discord.Embed:
        l=self.public_locale;e=discord.Embed(title=_t(l,"🃏 조커잡기","🃏 Old Maid"),description=final or f"{self.last_action}\n"+_t(l,"다음 사람의 뒷면 카드 위치를 직접 고릅니다. 같은 숫자 짝은 제거되고 마지막 조커 보유자가 패배합니다.","Choose a face-down card position from the next player. Pairs are discarded; the final Joker holder loses."),color=discord.Color.fuchsia())
        rows=[]
        for u in self.player_ids:
            status=_t(l,"완료","Done") if not self.hands[u] else f"{len(self.hands[u])}{_t(l,'장',' cards')}";rows.append(f"{'👉' if u in self.active and u==self.current_uid else '▫️'} **{self.names[u]}** · {status}")
        e.add_field(name=_t(l,"참가자","Players"),value="\n".join(rows),inline=False)
        if len(self.active)>1:e.add_field(name=_t(l,"현재 뽑기","Current Draw"),value=f"**{self.names[self.current_uid]} → {self.names[self._next_target()]}**",inline=False)
        e.add_field(name=_t(l,"상금","Prize"),value=format_chips(self.pot,l),inline=True);return e
    async def update(self)->None:
        await _safe_edit(self.message,embed=self.embed(),view=self)
        if not self.done and self.active and is_ai(self.current_uid) and not self._ai_running:asyncio.create_task(self.run_ai())
    async def start(self)->None:
        self._reserve()
        if len(self.active)<=1:await self.finish(self.active[0] if self.active else self.player_ids[0]);return
        await self.update();await self.run_ai()
    @discord.ui.button(label="다음 사람에게서 뽑기",emoji="🎴",style=discord.ButtonStyle.primary)
    async def draw_from_next(self,i:discord.Interaction,b:discord.ui.Button)->None:
        u=int(i.user.id);l=self.public_locale
        if u!=self.current_uid:await i.response.send_message(_t(l,"현재 본인 차례가 아닙니다.","It is not your turn."),ephemeral=True);return
        t=self._next_target();await i.response.send_message(_t(l,"뽑을 뒷면 카드 위치를 선택하세요.","Choose a face-down card position."),view=OldMaidPositionView(self,u,t,l),ephemeral=True)
    async def draw_position(self,i:discord.Interaction,u:int,t:int,index:int)->None:
        l=self.public_locale
        async with self.lock:
            if self.done or int(i.user.id)!=u or u!=self.current_uid or t!=self._next_target() or not 0<=index<len(self.hands[t]):await i.response.send_message(_t(l,"선택이 유효하지 않습니다.","Invalid selection."),ephemeral=True);return
            c=self.hands[t].pop(index);self.hands[u].append(c);self.hands[u],removed=_remove_pairs(self.hands[u]);self.removed[u]+=removed;self.last_action=_t(l,f"🎴 {self.names[u]} 님이 뒷면 카드 {index+1}을 뽑았습니다.",f"🎴 {self.names[u]} drew face-down card {index+1}.")
            await i.response.edit_message(content=_t(l,f"뽑은 카드: {_card_text(c)}",f"Drawn card: {_card_text(c)}"),view=None);await self._advance_after_draw(u)
    async def _advance_after_draw(self,u:int)->None:
        self.active=[p for p in self.active if self.hands[p]]
        if len(self.active)<=1:await self.finish(self.active[0] if self.active else u);return
        if u in self.active:self.turn=(self.active.index(u)+1)%len(self.active)
        else:self.turn%=len(self.active)
        await self.update()
    async def finish(self,loser:int)->None:
        if self.done:return
        self.done=True
        winners=[u for u in self.player_ids if u!=loser]
        payouts=self._pay(winners)
        rows=[];outcomes={};earnings={}
        for u in self.player_ids:
            payout=int(payouts.get(u,0));net=payout-int(self.bet);won=u!=loser
            outcomes[u]="win" if won else "loss"
            if is_ai(u):
                money=_t(self.public_locale,"AI 좌석","AI seat")
            else:
                current=casino_chips(self.get_user(u));before=current-net;sign="+" if net>=0 else ""
                money=(f"이번 게임 **{sign}{net:,}칩** · 잔액 **{before:,} → {current:,}칩**" if self.public_locale=="ko" else f"Game net **{sign}{net:,} chips** · balance **{before:,} → {current:,}**")
                earnings[u]=net
            rows.append(f"{'🏆' if won else '💀'} **{self.names[u]}** · {_t(self.public_locale,'승리','WIN') if won else _t(self.public_locale,'마지막 조커 · 패배','Final Joker · LOSS')}\n└ {money}")
        record_table_results(self,outcomes,earnings)
        self.save_data();self._disable();ACTIVE_GAMES.pop(self.channel_id,None)
        final=_t(self.public_locale,"🏆 조커잡기 승부 결과 · 최종 정산\n\n","🏆 Old Maid Result · Final Settlement\n\n")+"\n".join(rows)
        embed=self.embed(final);published=await _safe_edit(self.message,embed=embed,view=self)
        if not published:
            channel=getattr(self.message,"channel",None)
            if channel is not None and hasattr(channel,"send"):
                try:self.message=await channel.send(embed=embed,view=self)
                except Exception:pass
        self.stop()
    async def run_ai(self)->None:
        if self._ai_running:return
        self._ai_running=True
        try:
            while not self.done and len(self.active)>1 and is_ai(self.current_uid):
                u=self.current_uid;t=self._next_target();idx=random.randrange(len(self.hands[t]));c=self.hands[t].pop(idx);self.hands[u].append(c);self.hands[u],removed=_remove_pairs(self.hands[u]);self.removed[u]+=removed;self.last_action=_t(self.public_locale,"🎴 ABADDON이 뒷면 카드를 뽑았습니다.","🎴 ABADDON drew a face-down card.");await self._advance_after_draw(u)
        finally:self._ai_running=False


# ---------------------------------------------------------------------------
# Factory used by v10.5.1 registration
# ---------------------------------------------------------------------------
def authentic_factory(kind:str,*,bot:commands.Bot,world_data:MutableMapping[str,Any])->Tuple[Callable[[CardLobbyView],BaseCardSession],int,int,bool]:
    if kind=="포커":return (lambda l:FiveCardDrawSession(l,bot=bot)),2,6,True
    if kind in {"텍사스홀덤","오마하홀덤","파인애플홀덤","숏덱홀덤"}:return (lambda l,k=kind:CommunityPokerSession(l,bot=bot,kind=k)),2,6,True
    if kind=="세븐카드스터드":return (lambda l:StudSession(l,bot=bot)),2,6,True
    if kind=="하이로우포커":return (lambda l:StudSession(l,bot=bot,high_low=True)),2,6,True
    if kind=="바둑이":return (lambda l:BadugiSession(l,bot=bot)),2,6,True
    if kind=="인디언포커":return (lambda l:IndianPokerSession(l,bot=bot)),2,6,True
    if kind=="블랙잭":return (lambda l:AuthenticBlackjackSession(l,bot=bot)),1,6,True
    if kind=="바카라":return (lambda l:BaccaratSession(l,bot=bot)),1,8,True
    if kind=="맞고":return (lambda l:AuthenticHwatuSession(l,bot=bot,mode="맞고",world_data=world_data)),2,2,True
    if kind=="고스톱":return (lambda l:AuthenticHwatuSession(l,bot=bot,mode="고스톱",world_data=world_data)),3,3,True
    if kind=="섯다":return (lambda l:SeotdaSession(l,bot=bot)),2,6,True
    if kind=="원카드":return AuthenticOneCardSession,2,6,True
    if kind=="조커잡기":return AuthenticJokerSession,2,8,True
    raise KeyError(kind)
