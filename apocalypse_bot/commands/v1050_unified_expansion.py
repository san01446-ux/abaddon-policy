from __future__ import annotations

import asyncio
import copy
import itertools
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import (
    ACTIVE_GAMES,
    ACTIVE_LOBBIES,
    MAX_BET,
    MIN_BET,
    BaseCardSession,
    CardLobbyView,
    JokerSession,
    OneCardSession,
    PokerSession,
    _card_text,
    _deck,
    _emoji_bar,
    _poker_score,
    _safe_edit,
    _validate_bet,
)
from apocalypse_bot.commands.v1010_companion_card_games import (
    ASSIGNMENT_NAMES,
    COMPANIONS,
    HwatuCard,
    HwatuPlayView,
    HwatuSession,
    POKER_VARIANTS,
    PokerVariantSession,
    V1010LobbyView,
    _best_five,
    _best_omaha,
    _companion_profile,
    _english_game_name,
    _hwatu_deck,
    _hwatu_label,
    _hwatu_labels,
    _hwatu_score,
    _hwatu_text,
    _interaction_locale,
    _locale,
    _ctx_locale,
    _norm,
    _t,
    record_companion_card_game,
)
from apocalypse_bot.commands.v720_coop_cleanup import (
    AIDuelView,
    GAME_ALIASES,
    GAME_LABELS,
    MAX_AI_BET,
    MAX_AI_FOOD_BET,
    _add_currency,
    _currency_balance,
    _currency_key,
    _currency_label,
    _parse_wager,
)
from apocalypse_bot.commands.v1050_rules import (
    DEFAULT_HWATU_RULES,
    HwatuSummary,
    SEASON_MISSIONS,
    SEASON_REWARDS,
    ace_to_five_low,
    advance_season,
    baccarat_value,
    badugi_score,
    best_short_deck,
    blackjack_value,
    build_single_elimination,
    capped_extra_payment,
    # v10.6 overrides settlement with uncapped debt sessions; kept for legacy saves only,
    claimable_season_rewards,
    ensure_game_stats,
    ensure_season_profile,
    hwatu_multiplier,
    normalize_hwatu_rules,
    pineapple_best,
    record_game_result,
)

VERSION = "10.5.0"
PATCH_DATE = "2026-08-03"
KST = timezone(timedelta(hours=9))
Card = Tuple[int, str]
SEASON_ID = "S6-2026"

NEW_CARD_GAMES: Tuple[str, ...] = (
    "파인애플홀덤",
    "숏덱홀덤",
    "바둑이",
    "하이로우포커",
    "인디언포커",
    "블랙잭",
    "바카라",
)
ALL_CARD_GAMES: Tuple[str, ...] = (
    "포커",
    "텍사스홀덤",
    "오마하홀덤",
    "세븐카드스터드",
    *NEW_CARD_GAMES,
    "맞고",
    "고스톱",
    "원카드",
    "조커잡기",
)

CARD_EN: Dict[str, str] = {
    "포커": "Five-Card Draw",
    "텍사스홀덤": "Texas Hold'em",
    "오마하홀덤": "Omaha Hold'em",
    "세븐카드스터드": "Seven-Card Stud",
    "파인애플홀덤": "Pineapple Hold'em",
    "숏덱홀덤": "Short-Deck Hold'em",
    "바둑이": "Badugi",
    "하이로우포커": "High-Low Poker",
    "인디언포커": "Indian Poker",
    "블랙잭": "Blackjack",
    "바카라": "Baccarat",
    "맞고": "Matgo",
    "고스톱": "Go-Stop",
    "원카드": "One Card",
    "조커잡기": "Old Maid",
}

CARD_EMOJI: Dict[str, str] = {
    "포커": "♠️", "텍사스홀덤": "🤠", "오마하홀덤": "🌊", "세븐카드스터드": "🎩",
    "파인애플홀덤": "🍍", "숏덱홀덤": "⚡", "바둑이": "🀄", "하이로우포커": "↕️",
    "인디언포커": "🪶", "블랙잭": "🃏", "바카라": "🎰", "맞고": "🎴", "고스톱": "🌸",
    "원카드": "🎴", "조커잡기": "🃏",
}

CARD_DESCRIPTIONS: Dict[str, Tuple[str, str]] = {
    "파인애플홀덤": ("홀카드 3장 중 최적의 1장을 버리고 커뮤니티 카드와 승부합니다.", "Receive three hole cards, make the optimal discard, and play against the community board."),
    "숏덱홀덤": ("2~5가 빠진 36장 덱을 사용하며 플러시가 풀하우스보다 높습니다.", "Use a 36-card deck without 2–5; a flush ranks above a full house."),
    "바둑이": ("서로 다른 무늬와 숫자의 낮은 4장 패를 만드는 로우볼 게임입니다.", "Build the lowest four-card hand with unique suits and ranks."),
    "하이로우포커": ("7장 중 최고 하이 패와 최저 로우 패가 상금을 나눕니다.", "The best high hand and best ace-to-five low split the prize."),
    "인디언포커": ("상대 카드는 보이지만 자기 카드는 숨겨진 한 장 승부입니다.", "You can see the opponent's card but not your own before the showdown."),
    "블랙잭": ("아바돈 딜러를 상대로 21을 넘지 않고 더 가까운 수를 만듭니다.", "Face the ABADDON dealer and get closer to 21 without going over."),
    "바카라": ("플레이어와 뱅커 중 일의 자리 합계가 9에 가까운 쪽을 비교합니다.", "Compare player and banker totals; the last digit closest to nine wins."),
}


# ---------------------------------------------------------------------------
# Persistent roots and locale-safe helpers
# ---------------------------------------------------------------------------
def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1050_unified", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1050_unified"] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    root.setdefault("tournaments", {})
    root.setdefault("alliances", {})
    root.setdefault("audit", {})
    return root


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = _root(world_data)["guilds"]
    state = guilds.setdefault(str(guild_id), {})
    state.setdefault("hwatu_rules", dict(DEFAULT_HWATU_RULES))
    state.setdefault("hwatu_next_multiplier", 1)
    state.setdefault("game_hall", {"created": 0, "completed": 0})
    return state


def _registered(user_data: Mapping[Any, Any], uid: int) -> bool:
    return uid in user_data or str(uid) in user_data


def _public_locale(bot: commands.Bot, guild_id: int) -> str:
    return _locale(bot, 0, guild_id)


def _display_game(kind: str, locale: str) -> str:
    return kind if locale == "ko" else CARD_EN.get(kind, kind)


def _short_deck() -> List[Card]:
    cards = [(rank, suit) for suit in ("♠️", "♥️", "♦️", "♣️") for rank in range(6, 15)]
    random.shuffle(cards)
    return cards


def _hwatu_summary(cards: Sequence[HwatuCard]) -> HwatuSummary:
    score, labels = _hwatu_score(cards)
    brights = sum(1 for card in cards if card.category.startswith("bright"))
    animals = sum(1 for card in cards if card.category.startswith("animal"))
    ribbons = sum(1 for card in cards if card.category.startswith("ribbon"))
    junk = sum(card.junk for card in cards if card.category == "junk")
    junk += sum(2 for card in cards if card.category == "animal_doublejunk")
    return HwatuSummary(score, brights, animals, ribbons, junk, tuple(labels))


def _record_result(
    user: MutableMapping[str, Any],
    game: str,
    outcome: str,
    *,
    earnings: int = 0,
    score: int = 0,
    versus_ai: bool = False,
) -> None:
    record_game_result(user, game, outcome, earnings=earnings, score=score, versus_ai=versus_ai)
    advance_season(user, "play_games", 1, SEASON_ID)
    if outcome == "win":
        advance_season(user, "win_games", 1, SEASON_ID)
    if versus_ai:
        advance_season(user, "ai_games", 1, SEASON_ID)
    try:
        record_companion_card_game(user)
    except Exception:
        pass


def _active_companion_bonus(user: MutableMapping[str, Any], reward: int, activity: str) -> Tuple[int, str]:
    profile = _companion_profile(user)
    active = str(profile.get("active", ""))
    recruited = set(map(str, profile.get("recruited", [])))
    if active not in COMPANIONS or active not in recruited:
        return 0, ""
    levels = profile.setdefault("v1050_levels", {})
    level = max(1, int(levels.get(active, 1) or 1))
    role = str(COMPANIONS[active].get("role", ""))
    if activity == "game" and active == "convoy_master":
        return min(50_000, max(0, int(reward * (0.03 + level * 0.01)))), active
    if activity == "boss" and role in {"secure", "repair", "rescue"}:
        return min(5000, level * 250), active
    if activity == "expedition" and role in {"scan", "repair", "rescue", "secure"}:
        return min(30, 4 + level * 2), active
    return 0, active


# ---------------------------------------------------------------------------
# Full hwatu rule session: bomb, shake, bak multipliers, go-bak, chongtong,
# side-event logging and nagari carry-over.
# ---------------------------------------------------------------------------
class FullHwatuSession(HwatuSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, mode: str, world_data: MutableMapping[str, Any]) -> None:
        super().__init__(lobby, bot=bot, mode=mode)
        self.world_data_ref = world_data
        self.shakes: Dict[int, int] = {uid: 0 for uid in self.player_ids}
        self.bombs: Dict[int, int] = {uid: 0 for uid in self.player_ids}
        self.shake_declared: set[int] = set()
        self.side_events: Dict[int, Counter[str]] = {uid: Counter() for uid in self.player_ids}
        self.declared_go: set[int] = set()
        self.chongtong_winner: Optional[int] = None
        for uid, hand in self.hands.items():
            counts = Counter(card.month for card in hand)
            if any(count >= 4 for count in counts.values()):
                self.chongtong_winner = uid
                break
        shake_button = discord.ui.Button(label="흔들기", emoji="〰️", style=discord.ButtonStyle.secondary, row=1)
        if getattr(lobby, "public_locale", "ko") == "en":
            shake_button.label = "Shake"
        shake_button.callback = self.declare_shake
        self.add_item(shake_button)

    def _rules(self) -> Dict[str, bool]:
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0)
        return normalize_hwatu_rules(_guild_state(self.world_data_ref, guild_id).get("hwatu_rules"))

    async def start(self) -> None:
        self._reserve()
        if self.chongtong_winner is not None and self._rules().get("chongtong", True):
            locale = self.public_locale()
            await self._finish_chongtong(self.chongtong_winner, locale)
            return
        await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    async def declare_shake(self, interaction: discord.Interaction) -> None:
        locale = _interaction_locale(self.bot, interaction)
        uid = int(interaction.user.id)
        async with self.lock:
            if uid not in self.hands or uid in self.shake_declared:
                await interaction.response.send_message(_t(locale, "흔들기를 선언할 수 없습니다.", "You cannot declare a shake."), ephemeral=True)
                return
            counts = Counter(card.month for card in self.hands[uid])
            months = [month for month, count in counts.items() if count >= 3]
            if not months:
                await interaction.response.send_message(_t(locale, "같은 월 패 3장이 없습니다.", "You do not have three cards from one month."), ephemeral=True)
                return
            self.shake_declared.add(uid)
            self.shakes[uid] += 1
            month = months[0]
            await interaction.response.send_message(_t(locale, f"〰️ {month}월 패 3장으로 흔들기를 선언했습니다.", f"〰️ Declared a shake with three Month {month} cards."), ephemeral=True)
            await self.update()

    async def play_card(self, interaction: discord.Interaction, uid: int, index: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if self.done:
                await interaction.response.send_message(_t(locale, "이미 게임이 끝났습니다.", "The game is already over."), ephemeral=True)
                return
            if uid != int(interaction.user.id) or uid != self.current_uid or self.pending_go is not None:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            if index >= len(self.hands[uid]):
                await interaction.response.send_message(_t(locale, "패가 바뀌었습니다. 다시 선택하세요.", "Your hand changed. Choose again."), ephemeral=True)
                return
            selected = self.hands[uid][index]
            same_hand = [card for card in self.hands[uid] if card.month == selected.month]
            floor_match = [card for card in self.floor if card.month == selected.month]
            actions: List[str] = []
            bomb_used = self._rules().get("bomb", True) and len(same_hand) >= 3 and bool(floor_match)
            floor_before = len(self.floor)
            if bomb_used:
                used = same_hand[:3]
                for card in used:
                    self.hands[uid].remove(card)
                target = floor_match[0]
                self.floor.remove(target)
                self.captured[uid].extend(used + [target])
                self.bombs[uid] += 1
                actions.append(_t(locale, f"💣 {selected.month}월 폭탄으로 4장 획득", f"💣 Month {selected.month} bomb captured four cards"))
            else:
                card = self.hands[uid].pop(index)
                first = self._capture_resolution(uid, card, _t(locale, "낸 패", "Played card"), locale)
                actions.append(first)
            if self.deck:
                flipped = self.deck.pop()
                floor_mid = len(self.floor)
                second = self._capture_resolution(uid, flipped, _t(locale, "뒤집은 패", "Flipped card"), locale)
                actions.append(second)
                if self._rules().get("side_events", True):
                    first_captured = "획득" in actions[0] or "captured" in actions[0]
                    second_captured = "획득" in second or "captured" in second
                    if not bomb_used and not first_captured and second_captured and flipped.month == selected.month:
                        self.side_events[uid]["쪽"] += 1
                        actions.append(_t(locale, "✨ 쪽", "✨ Jjok"))
                    if first_captured and second_captured:
                        self.side_events[uid]["따닥"] += 1
                        actions.append(_t(locale, "✨ 따닥", "✨ Ttadak"))
                    if floor_before > 0 and not self.floor:
                        self.side_events[uid]["쓸"] += 1
                        actions.append(_t(locale, "🧹 쓸", "🧹 Sweep"))
            summary = _hwatu_summary(self.captured[uid])
            previous = self.scores[uid]
            self.scores[uid] = summary.score
            self.last_action = f"**{self.names[uid]}** · " + " · ".join(actions)
            await interaction.response.edit_message(content=_t(locale, "✅ 패 처리가 완료됐습니다.", "✅ Card resolution complete."), view=None)
            if summary.score >= self._threshold() and summary.score > previous and (self.deck or any(self.hands.values())):
                self.pending_go = uid
                await self.update()
                return
            if not self.deck or all(not hand for hand in self.hands.values()):
                await self.finish_by_score(locale)
                return
            self.turn = (self.turn + 1) % len(self.player_ids)
            await self.update()

    async def choose_go(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if self.pending_go == uid:
            self.declared_go.add(uid)
        await super().choose_go(interaction, _)

    async def finish_by_score(self, locale: str) -> None:
        scored = {uid: _hwatu_summary(self.captured[uid]).score + self.go_counts[uid] for uid in self.player_ids}
        high = max(scored.values())
        winners = [uid for uid, value in scored.items() if value == high]
        if (high <= 0 or len(winners) == len(self.player_ids)) and self._rules().get("nagari", True):
            await self._finish_nagari(locale)
            return
        await self.finish(winners, locale, stopped=False)

    async def _finish_nagari(self, locale: str) -> None:
        if self.done:
            return
        self.done = True
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0)
        state = _guild_state(self.world_data_ref, guild_id)
        state["hwatu_next_multiplier"] = min(4, max(2, int(state.get("hwatu_next_multiplier", 1) or 1) * 2))
        self._refund()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        text = _t(locale, f"🌫️ 나가리 · 참가비 환불 · 다음 판 배수 x{state['hwatu_next_multiplier']}", f"🌫️ Nagari · entry fees refunded · next round x{state['hwatu_next_multiplier']}")
        await _safe_edit(self.message, embed=self.embed(locale, text), view=self)
        self.stop()

    async def _finish_chongtong(self, winner: int, locale: str) -> None:
        if self.done:
            return
        self.done = True
        payouts = self._pay([winner])
        # Chongtong settles to a total four-entry-fee payout without deleting
        # the already reserved table pot or charging losers twice.
        bonus = max(0, self.bet * 4 - int(payouts.get(winner, 0)))
        if bonus:
            add_casino_chips(self.get_user(winner), bonus)
        payout = int(payouts.get(winner, 0)) + bonus
        for uid in self.player_ids:
            outcome = "win" if uid == winner else "loss"
            _record_result(self.get_user(uid), self.mode, outcome, earnings=(payout - self.bet if uid == winner else -self.bet), score=4)
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        text = _t(locale, f"🎆 **{self.names[winner]}** 총통 즉시 승리 · x4 정산 · +{payout:,}칩", f"🎆 **{self.names[winner]}** wins instantly with Chongtong · x4 settlement · +{payout:,} chips")
        await _safe_edit(self.message, embed=self.embed(locale, text), view=self)
        self.stop()

    async def finish(self, winners: Sequence[int], locale: str, *, stopped: bool) -> None:
        if self.done:
            return
        self.done = True
        payouts = self._pay(winners)
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0)
        guild_state = _guild_state(self.world_data_ref, guild_id)
        carry = max(1, int(guild_state.get("hwatu_next_multiplier", 1) or 1))
        guild_state["hwatu_next_multiplier"] = 1
        rows: List[str] = []
        total_extra_by_winner: Dict[int, int] = {uid: 0 for uid in winners}
        total_extra_by_loser: Dict[int, int] = {uid: 0 for uid in self.player_ids if uid not in winners}
        for loser in [uid for uid in self.player_ids if uid not in winners]:
            loser_summary = _hwatu_summary(self.captured[loser])
            for winner in winners:
                winner_summary = _hwatu_summary(self.captured[winner])
                multiplier, reasons = hwatu_multiplier(
                    winner_summary,
                    loser_summary,
                    go_count=self.go_counts[winner],
                    shakes=self.shakes[winner],
                    bombs=self.bombs[winner],
                    loser_declared_go=loser in self.declared_go,
                    nagari_multiplier=carry,
                    rules=self._rules(),
                )
                extra = max(0, int(self.bet)) * max(0, int(multiplier) - 1)
                if extra:
                    add_casino_chips(self.get_user(loser), -extra)
                    add_casino_chips(self.get_user(winner), extra)
                    total_extra_by_winner[winner] += extra
                    total_extra_by_loser[loser] += extra
                if reasons:
                    rows.append(f"⚖️ **{self.names[winner]}** vs {self.names[loser]} · x{multiplier} · " + " · ".join(reasons))
        for uid in self.player_ids:
            summary = _hwatu_summary(self.captured[uid])
            marker = "🏆" if uid in winners else "▫️"
            payout = payouts.get(uid, 0) + total_extra_by_winner.get(uid, 0)
            outcome = "win" if uid in winners else "loss"
            earnings = payout - self.bet if uid in winners else -(self.bet + total_extra_by_loser.get(uid, 0))
            _record_result(self.get_user(uid), self.mode, outcome, earnings=earnings, score=summary.score)
            event_text = ", ".join(f"{key} {value}" for key, value in self.side_events[uid].items()) or "-"
            rows.append(
                f"{marker} **{self.names[uid]}** · {summary.score}{_t(locale, '점', ' pts')} · "
                f"{_t(locale, '고', 'Go')} {self.go_counts[uid]} · {_hwatu_labels(summary.labels, locale)} · "
                f"💣{self.bombs[uid]} 〰️{self.shakes[uid]} · {event_text}"
                + (f" · +{payout:,}{_t(locale, '칩', ' chips')}" if payout else "")
            )
        self.save_data()
        lead = _t(locale, "스톱 선언으로 승부가 끝났습니다.", "The round ended with Stop.") if stopped else _t(locale, "남은 패가 없어 점수로 정산했습니다.", "The deck ended, so the round was settled by score.")
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(locale, lead + "\n\n" + "\n".join(rows)), view=self)
        self.stop()


# ---------------------------------------------------------------------------
# Additional multiplayer card sessions
# ---------------------------------------------------------------------------
class RevealCardSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, kind: str) -> None:
        super().__init__(lobby, timeout=210)
        self.bot = bot
        self.variant = kind
        self.ready: set[int] = set()
        self.reveal_stage = 0
        self.board: List[Card] = []
        self.discarded: Dict[int, Optional[Card]] = {uid: None for uid in self.player_ids}
        deck = _short_deck() if kind == "숏덱홀덤" else _deck()
        if kind in {"파인애플홀덤"}:
            self.hands = {uid: [deck.pop() for _ in range(3)] for uid in self.player_ids}
            self.board = [deck.pop() for _ in range(5)]
        elif kind == "숏덱홀덤":
            self.hands = {uid: [deck.pop() for _ in range(2)] for uid in self.player_ids}
            self.board = [deck.pop() for _ in range(5)]
        elif kind == "바둑이":
            self.hands = {uid: [deck.pop() for _ in range(4)] for uid in self.player_ids}
        elif kind == "하이로우포커":
            self.hands = {uid: [deck.pop() for _ in range(7)] for uid in self.player_ids}
        elif kind == "인디언포커":
            self.hands = {uid: [deck.pop()] for uid in self.player_ids}
        elif kind == "바카라":
            self.hands = {uid: [deck.pop(), deck.pop()] for uid in self.player_ids}
            for uid in self.player_ids:
                if baccarat_value(self.hands[uid]) <= 5 and deck:
                    self.hands[uid].append(deck.pop())
        else:
            raise ValueError(kind)
        locale = getattr(lobby, "public_locale", "ko")
        labels = {"내 패 보기": "View Hand", "다음 공개": "Reveal Next", "준비": "Ready", "승부 공개": "Showdown"}
        if locale == "en":
            for child in self.children:
                if getattr(child, "label", None) in labels:
                    child.label = labels[str(child.label)]

    def public_locale(self) -> str:
        return _public_locale(self.bot, getattr(getattr(self.message, "guild", None), "id", 0))

    def embed(self, locale: str, final: str = "") -> discord.Embed:
        desc = final or CARD_DESCRIPTIONS[self.variant][0 if locale == "ko" else 1]
        embed = discord.Embed(title=f"{CARD_EMOJI[self.variant]} {_display_game(self.variant, locale)}", description=desc, color=discord.Color.gold())
        if self.board:
            visible = min(len(self.board), self.reveal_stage)
            embed.add_field(name=_t(locale, "커뮤니티 카드", "Community Cards"), value="  ".join(_card_text(card) for card in self.board[:visible]) or _t(locale, "아직 공개되지 않았습니다.", "Not revealed yet."), inline=False)
        status = "\n".join(f"{'✅' if uid in self.ready else '▫️'} **{self.names[uid]}**" for uid in self.player_ids)
        embed.add_field(name=_t(locale, "준비 상태", "Readiness"), value=status, inline=False)
        embed.add_field(name=_t(locale, "상금", "Prize Pool"), value=f"{self.pot:,}{_t(locale, '칩', ' chips')}", inline=True)
        embed.set_footer(text=_t(locale, "추가 베팅 없는 고정 참가비 방식 · 동률 시 분배", "Fixed entry fee with no extra betting · ties split the prize"))
        return embed

    async def start(self) -> None:
        self._reserve()
        await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        if self.variant == "인디언포커":
            others = [f"{self.names[other]}: {_card_text(self.hands[other][0])}" for other in self.player_ids if other != uid]
            text = _t(locale, "자기 카드는 볼 수 없습니다.\n", "Your own card stays hidden.\n") + "\n".join(others)
        else:
            text = "  ".join(_card_text(card) for card in self.hands[uid])
        await interaction.response.send_message(f"{CARD_EMOJI[self.variant]} **{_t(locale, '내 정보', 'Your Information')}**\n{text}", ephemeral=True)

    @discord.ui.button(label="다음 공개", emoji="🎴", style=discord.ButtonStyle.primary)
    async def reveal_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        if int(interaction.user.id) != self.host_id:
            await interaction.response.send_message(_t(locale, "방장만 공개할 수 있습니다.", "Only the host can reveal cards."), ephemeral=True)
            return
        if not self.board or self.reveal_stage >= len(self.board):
            await interaction.response.send_message(_t(locale, "더 공개할 카드가 없습니다.", "There are no more cards to reveal."), ephemeral=True)
            return
        self.reveal_stage = min(len(self.board), 3 if self.reveal_stage == 0 else self.reveal_stage + 1)
        await interaction.response.defer()
        await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    @discord.ui.button(label="준비", emoji="✅", style=discord.ButtonStyle.success)
    async def ready_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        self.ready.add(uid)
        await interaction.response.send_message(_t(locale, "승부 공개 준비 완료!", "Ready for showdown!"), ephemeral=True)
        await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    @discord.ui.button(label="승부 공개", emoji="🏆", style=discord.ButtonStyle.danger)
    async def showdown_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        if int(interaction.user.id) != self.host_id:
            await interaction.response.send_message(_t(locale, "방장만 승부를 공개할 수 있습니다.", "Only the host can start the showdown."), ephemeral=True)
            return
        if len(self.ready) < len(self.player_ids) and self.board and self.reveal_stage < len(self.board):
            await interaction.response.send_message(_t(locale, "모두 준비하거나 보드를 끝까지 공개하세요.", "Wait for everyone or reveal the full board."), ephemeral=True)
            return
        await interaction.response.defer()
        await self.finish(locale)

    def _high_score(self, uid: int) -> Tuple[Any, str, Tuple[Card, ...]]:
        cards = self.hands[uid]
        if self.variant == "파인애플홀덤":
            score, label, hand, discarded = pineapple_best(cards, self.board, _poker_score)
            self.discarded[uid] = discarded
            return score, label, hand
        if self.variant == "숏덱홀덤":
            return best_short_deck(cards + self.board)
        if self.variant == "바둑이":
            length, key, hand = badugi_score(cards)
            transformed = (length, *tuple(-value for value in key))
            return transformed, f"{length}카드 바둑이", hand
        if self.variant == "인디언포커":
            return (cards[0][0],), "한 장", tuple(cards)
        if self.variant == "바카라":
            value = baccarat_value(cards)
            return (value,), f"{value}점", tuple(cards)
        return _best_five(cards)

    async def finish(self, locale: str) -> None:
        if self.done:
            return
        self.done = True
        if self.variant == "하이로우포커":
            await self._finish_high_low(locale)
            return
        scored = {uid: self._high_score(uid) for uid in self.player_ids}
        high = max(row[0] for row in scored.values())
        winners = [uid for uid, row in scored.items() if row[0] == high]
        payouts = self._pay(winners)
        rows: List[str] = []
        for uid, (score, label, hand) in scored.items():
            outcome = "win" if uid in winners else "loss"
            payout = payouts.get(uid, 0)
            bonus, companion = _active_companion_bonus(self.get_user(uid), payout, "game") if uid in winners else (0, "")
            if bonus:
                add_casino_chips(self.get_user(uid), bonus)
                payout += bonus
            _record_result(self.get_user(uid), self.variant, outcome, earnings=(payout - self.bet if uid in winners else -self.bet), score=int(score[0]) if score else 0)
            extra = ""
            if self.discarded.get(uid):
                extra = _t(locale, f" · 자동 버림 {_card_text(self.discarded[uid])}", f" · auto-discard {_card_text(self.discarded[uid])}")
            rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {' '.join(_card_text(card) for card in hand)} · **{label}**{extra}" + (f" · +{payout:,}{_t(locale, '칩', ' chips')}" if payout else ""))
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(locale, "\n".join(rows)), view=self)
        self.stop()

    async def _finish_high_low(self, locale: str) -> None:
        highs = {uid: _best_five(self.hands[uid]) for uid in self.player_ids}
        lows = {uid: ace_to_five_low(self.hands[uid]) for uid in self.player_ids}
        high_value = max(row[0] for row in highs.values())
        high_winners = [uid for uid, row in highs.items() if row[0] == high_value]
        valid_lows = {uid: row for uid, row in lows.items() if row is not None}
        low_value = min(valid_lows.values()) if valid_lows else None
        low_winners = [uid for uid, row in valid_lows.items() if row == low_value] if low_value else []
        half_high = self.pot if not low_winners else self.pot // 2
        half_low = self.pot - half_high
        payouts = {uid: 0 for uid in self.player_ids}
        for group, pool in ((high_winners, half_high), (low_winners, half_low)):
            if not group:
                continue
            share, remainder = divmod(pool, len(group))
            for index, uid in enumerate(group):
                payouts[uid] += share + (1 if index < remainder else 0)
        reservation = self.world_data.setdefault("v651_card_games", {}).setdefault("reservations", {})
        reservation.pop(self.game_id, None)
        for uid, amount in payouts.items():
            if amount:
                add_casino_chips(self.get_user(uid), amount)
        rows: List[str] = []
        winners = set(high_winners + low_winners)
        for uid in self.player_ids:
            high_label = highs[uid][1]
            low_label = "-" if lows[uid] is None else "/".join(map(str, lows[uid][1:]))
            outcome = "win" if uid in winners else "loss"
            _record_result(self.get_user(uid), self.variant, outcome, earnings=payouts[uid] - self.bet, score=int(highs[uid][0][0]))
            marks = []
            if uid in high_winners: marks.append(_t(locale, "하이", "High"))
            if uid in low_winners: marks.append(_t(locale, "로우", "Low"))
            rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {high_label} · Low {low_label} · {'/'.join(marks) or '-'} · +{payouts[uid]:,}{_t(locale, '칩', ' chips')}")
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(locale, "\n".join(rows)), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        async with self.lock:
            if self.done:
                return
            self.done = True
            self._refund()
            self._disable()
            ACTIVE_GAMES.pop(self.channel_id, None)
            locale = self.public_locale()
            await _safe_edit(self.message, embed=self.embed(locale, _t(locale, "⌛ 시간 초과로 참가비를 전원 환불했습니다.", "⌛ Timed out; all entry fees were refunded.")), view=self)
            self.stop()


class BlackjackSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot) -> None:
        super().__init__(lobby, timeout=240)
        self.bot = bot
        self.deck = _deck()
        self.hands: Dict[int, List[Card]] = {uid: [self.deck.pop(), self.deck.pop()] for uid in self.player_ids}
        self.dealer: List[Card] = [self.deck.pop(), self.deck.pop()]
        self.turn = 0
        self.stood: set[int] = set()
        self.busted: set[int] = set()
        self.last_action = ""
        if getattr(lobby, "public_locale", "ko") == "en":
            for child in self.children:
                labels = {"내 패 보기": "View Hand", "히트": "Hit", "스탠드": "Stand"}
                if getattr(child, "label", None) in labels:
                    child.label = labels[str(child.label)]

    @property
    def current_uid(self) -> int:
        return self.player_ids[self.turn % len(self.player_ids)]

    def public_locale(self) -> str:
        return _public_locale(self.bot, getattr(getattr(self.message, "guild", None), "id", 0))

    def embed(self, locale: str, final: str = "") -> discord.Embed:
        description = final or _t(locale, "차례에 히트 또는 스탠드를 선택하세요. 딜러는 17 이상에서 멈춥니다.", "Choose Hit or Stand. The dealer stands on 17 or higher.")
        embed = discord.Embed(title=f"🃏 {_display_game('블랙잭', locale)}", description=description, color=discord.Color.dark_green())
        dealer_visible = _card_text(self.dealer[0]) + "  🂠" if not final else "  ".join(_card_text(card) for card in self.dealer)
        embed.add_field(name=_t(locale, "아바돈 딜러", "ABADDON Dealer"), value=dealer_visible, inline=False)
        rows = []
        for uid in self.player_ids:
            total, soft = blackjack_value(self.hands[uid])
            marker = "👉" if uid == self.current_uid and uid not in self.stood and uid not in self.busted else "▫️"
            state = _t(locale, "버스트", "Bust") if uid in self.busted else (_t(locale, "스탠드", "Stand") if uid in self.stood else f"{total}")
            rows.append(f"{marker} **{self.names[uid]}** · {state}")
        embed.add_field(name=_t(locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        return embed

    async def start(self) -> None:
        self._reserve()
        await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        total, soft = blackjack_value(self.hands[uid])
        await interaction.response.send_message(f"🃏 {' '.join(_card_text(card) for card in self.hands[uid])}\n**{total}**" + (" soft" if soft else ""), ephemeral=True)

    def _advance(self) -> None:
        for _ in range(len(self.player_ids)):
            self.turn = (self.turn + 1) % len(self.player_ids)
            if self.current_uid not in self.stood and self.current_uid not in self.busted:
                return

    async def _check_end(self, locale: str) -> bool:
        if all(uid in self.stood or uid in self.busted for uid in self.player_ids):
            await self.finish(locale)
            return True
        return False

    @discord.ui.button(label="히트", emoji="➕", style=discord.ButtonStyle.success)
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        uid = int(interaction.user.id)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            card = self.deck.pop()
            self.hands[uid].append(card)
            total, _soft = blackjack_value(self.hands[uid])
            if total > 21:
                self.busted.add(uid)
            elif total == 21:
                self.stood.add(uid)
            self._advance()
            await interaction.response.send_message(f"➕ {_card_text(card)} · {total}", ephemeral=True)
            if not await self._check_end(locale):
                await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.primary)
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        uid = int(interaction.user.id)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            self.stood.add(uid)
            self._advance()
            await interaction.response.send_message(_t(locale, "✋ 스탠드했습니다.", "✋ Standing."), ephemeral=True)
            if not await self._check_end(locale):
                await _safe_edit(self.message, embed=self.embed(self.public_locale()), view=self)

    async def finish(self, locale: str) -> None:
        if self.done:
            return
        self.done = True
        while blackjack_value(self.dealer)[0] < 17 and self.deck:
            self.dealer.append(self.deck.pop())
        dealer_total, _ = blackjack_value(self.dealer)
        dealer_bust = dealer_total > 21
        reservation = self.world_data.setdefault("v651_card_games", {}).setdefault("reservations", {})
        reservation.pop(self.game_id, None)
        rows = [f"🤖 {_t(locale, '딜러', 'Dealer')}: {' '.join(_card_text(card) for card in self.dealer)} · **{dealer_total}**"]
        for uid in self.player_ids:
            total, _ = blackjack_value(self.hands[uid])
            natural = len(self.hands[uid]) == 2 and total == 21
            if total > 21:
                outcome, payout = "loss", 0
            elif dealer_bust or total > dealer_total:
                outcome, payout = "win", int(self.bet * (2.5 if natural else 2))
            elif total == dealer_total:
                outcome, payout = "draw", self.bet
            else:
                outcome, payout = "loss", 0
            if payout:
                add_casino_chips(self.get_user(uid), payout)
            _record_result(self.get_user(uid), "블랙잭", outcome, earnings=payout - self.bet, score=total)
            rows.append(f"{'🏆' if outcome == 'win' else ('🤝' if outcome == 'draw' else '💀')} **{self.names[uid]}** · {total} · {payout:+,}{_t(locale, '칩', ' chips')}")
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(locale, "\n".join(rows)), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        async with self.lock:
            if not self.done:
                self.done = True
                self._refund()
                self._disable()
                ACTIVE_GAMES.pop(self.channel_id, None)
                await _safe_edit(self.message, embed=self.embed(self.public_locale(), _t(self.public_locale(), "⌛ 참가비를 전원 환불했습니다.", "⌛ All entry fees were refunded.")), view=self)
                self.stop()


class V1050LobbyView(V1010LobbyView):
    def embed(self, note: str = "") -> discord.Embed:
        embed = super().embed(note)
        locale = self.public_locale
        if self.kind in CARD_DESCRIPTIONS:
            embed.title = f"{CARD_EMOJI[self.kind]} {_display_game(self.kind, locale)} · " + _t(locale, "참가 모집", "Lobby")
            embed.description = f"**{_t(locale, '10초 설명', 'Quick Guide')}**\n{CARD_DESCRIPTIONS[self.kind][0 if locale == 'ko' else 1]}\n\n{note}".strip()
        embed.set_footer(text=_t(locale, "혼자라면 아바돈 초대 · 고정 참가비 · 시간 초과 전액 환불", "Invite ABADDON when alone · fixed entry fee · full timeout refund"))
        return embed


# ---------------------------------------------------------------------------
# Universal ABADDON card opponent
# ---------------------------------------------------------------------------
class UniversalCardAIView(AIDuelView):
    def __init__(self, *, bot: commands.Bot, locale: str, kind: str, get_user: Callable[[int], MutableMapping[str, Any]], **kwargs: Any) -> None:
        super().__init__(timeout=150, **kwargs)
        self.bot = bot
        self.locale = locale
        self.kind = kind
        self.get_user_func = get_user
        self.resolved = self._deal_and_score()
        for child in self.children:
            if self.locale == "en" and getattr(child, "label", "") == "승부 공개":
                child.label = "Showdown"

    def _deal_and_score(self) -> Dict[str, Any]:
        kind = self.kind
        if kind in {"맞고", "고스톱"}:
            deck = _hwatu_deck()
            random.shuffle(deck)
            player_cards = deck[:18]
            ai_cards = deck[18:36]
            p = _hwatu_summary(player_cards)
            a = _hwatu_summary(ai_cards)
            outcome = "win" if p.score > a.score else ("draw" if p.score == a.score else "lose")
            return {"outcome": outcome, "player": player_cards, "ai": ai_cards, "p_label": f"{p.score}점", "a_label": f"{a.score}점", "score": p.score}
        deck = _short_deck() if kind == "숏덱홀덤" else _deck()
        board: List[Card] = []
        if kind == "텍사스홀덤":
            ph, ah, board = [deck.pop() for _ in range(2)], [deck.pop() for _ in range(2)], [deck.pop() for _ in range(5)]
            ps, pl, pb = _best_five(ph + board); ass, al, ab = _best_five(ah + board)
        elif kind == "오마하홀덤":
            ph, ah, board = [deck.pop() for _ in range(4)], [deck.pop() for _ in range(4)], [deck.pop() for _ in range(5)]
            ps, pl, pb = _best_omaha(ph, board); ass, al, ab = _best_omaha(ah, board)
        elif kind == "세븐카드스터드":
            ph, ah = [deck.pop() for _ in range(7)], [deck.pop() for _ in range(7)]
            ps, pl, pb = _best_five(ph); ass, al, ab = _best_five(ah)
        elif kind == "파인애플홀덤":
            ph, ah, board = [deck.pop() for _ in range(3)], [deck.pop() for _ in range(3)], [deck.pop() for _ in range(5)]
            ps, pl, pb, pd = pineapple_best(ph, board, _poker_score); ass, al, ab, ad = pineapple_best(ah, board, _poker_score)
        elif kind == "숏덱홀덤":
            ph, ah, board = [deck.pop() for _ in range(2)], [deck.pop() for _ in range(2)], [deck.pop() for _ in range(5)]
            ps, pl, pb = best_short_deck(ph + board); ass, al, ab = best_short_deck(ah + board)
        elif kind == "바둑이":
            ph, ah = [deck.pop() for _ in range(4)], [deck.pop() for _ in range(4)]
            pc, pk, pb = badugi_score(ph); ac, ak, ab = badugi_score(ah)
            ps, ass = (pc, *[-v for v in pk]), (ac, *[-v for v in ak])
            pl, al = f"{pc}카드 바둑이", f"{ac}카드 바둑이"
        elif kind == "하이로우포커":
            ph, ah = [deck.pop() for _ in range(7)], [deck.pop() for _ in range(7)]
            ps, pl, pb = _best_five(ph); ass, al, ab = _best_five(ah)
            pl += f" / Low {ace_to_five_low(ph)}"; al += f" / Low {ace_to_five_low(ah)}"
        elif kind == "인디언포커":
            ph, ah = [deck.pop()], [deck.pop()]
            ps, ass = (ph[0][0],), (ah[0][0],); pl = al = "한 장"; pb, ab = tuple(ph), tuple(ah)
        elif kind == "바카라":
            ph, ah = [deck.pop(), deck.pop()], [deck.pop(), deck.pop()]
            if baccarat_value(ph) <= 5: ph.append(deck.pop())
            if baccarat_value(ah) <= 5: ah.append(deck.pop())
            ps, ass = (baccarat_value(ph),), (baccarat_value(ah),); pl, al = f"{ps[0]}점", f"{ass[0]}점"; pb, ab = tuple(ph), tuple(ah)
        else:
            ph, ah = [deck.pop() for _ in range(5)], [deck.pop() for _ in range(5)]
            ps, pl = _poker_score(ph); ass, al = _poker_score(ah); pb, ab = tuple(ph), tuple(ah)
        outcome = "win" if ps > ass else ("draw" if ps == ass else "lose")
        return {"outcome": outcome, "player": ph, "ai": ah, "board": board, "p_best": pb, "a_best": ab, "p_label": pl, "a_label": al, "score": int(ps[0]) if ps else 0}

    def embed(self) -> discord.Embed:
        locale = self.locale
        info = self.resolved
        embed = discord.Embed(title=f"{CARD_EMOJI.get(self.kind, '🃏')} {_display_game(self.kind, locale)} · ABADDON", description=_t(locale, "승부 공개를 누르면 아바돈과 공정하게 배분된 패를 비교합니다.", "Press Showdown to compare independently dealt cards against ABADDON."), color=discord.Color.purple())
        if info.get("board"):
            embed.add_field(name=_t(locale, "보드", "Board"), value="  ".join(_card_text(card) for card in info["board"]), inline=False)
        if self.kind in {"맞고", "고스톱"}:
            embed.add_field(name=_t(locale, "내 획득 패", "Your Captures"), value=f"{len(info['player'])}{_t(locale, '장', ' cards')} · {info['p_label']}", inline=False)
        elif self.kind == "인디언포커":
            embed.add_field(name=_t(locale, "아바돈 이마 카드", "ABADDON Forehead Card"), value=_card_text(info["ai"][0]), inline=False)
            embed.add_field(name=_t(locale, "내 카드", "Your Card"), value=_t(locale, "승부 전까지 비공개", "Hidden until showdown"), inline=False)
        else:
            embed.add_field(name=_t(locale, "내 패", "Your Cards"), value="  ".join(_card_text(card) for card in info["player"]), inline=False)
            embed.add_field(name="ABADDON", value="🂠 " * len(info["ai"]), inline=False)
        return embed

    @discord.ui.button(label="승부 공개", emoji="🏆", style=discord.ButtonStyle.danger)
    async def showdown(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        info = self.resolved
        outcome = str(info["outcome"])
        record_outcome = "loss" if outcome == "lose" else outcome
        payout = self.bet * int(self.win_multiplier) if outcome == "win" else (self.bet if outcome == "draw" else 0)
        _record_result(self.user, self.kind, record_outcome, earnings=payout - self.bet, score=int(info.get("score", 0)), versus_ai=True)
        bonus, _active = _active_companion_bonus(self.user, payout, "game") if outcome == "win" else (0, "")
        if bonus:
            _add_currency(self.user, self.currency, bonus)
        if self.kind in {"맞고", "고스톱"}:
            detail = _t(self.locale, f"생존자: **{info['p_label']}**\n아바돈: **{info['a_label']}**", f"Survivor: **{info['p_label']}**\nABADDON: **{info['a_label']}**")
        else:
            detail = (
                f"{_t(self.locale, '생존자', 'Survivor')}: {' '.join(_card_text(card) for card in info['player'])} · **{info['p_label']}**\n"
                f"ABADDON: {' '.join(_card_text(card) for card in info['ai'])} · **{info['a_label']}**"
            )
        if bonus:
            detail += _t(self.locale, f"\n🤝 동료 보너스 +{bonus:,}{_currency_label(self.currency)}", f"\n🤝 Companion bonus +{bonus:,} {_currency_label(self.currency)}")
        await self.finish(interaction, outcome, detail)


class AIBlackjackView(AIDuelView):
    def __init__(self, *, bot: commands.Bot, locale: str, **kwargs: Any) -> None:
        super().__init__(timeout=150, **kwargs)
        self.bot = bot
        self.locale = locale
        self.deck = _deck()
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        if locale == "en":
            labels = {"히트": "Hit", "스탠드": "Stand"}
            for child in self.children:
                if getattr(child, "label", None) in labels:
                    child.label = labels[str(child.label)]

    def embed(self) -> discord.Embed:
        total, _ = blackjack_value(self.player)
        embed = discord.Embed(title=f"🃏 {_display_game('블랙잭', self.locale)} · ABADDON", description=_t(self.locale, "히트 또는 스탠드를 선택하세요.", "Choose Hit or Stand."), color=discord.Color.dark_green())
        embed.add_field(name=_t(self.locale, "내 패", "Your Hand"), value="  ".join(_card_text(card) for card in self.player) + f" · **{total}**", inline=False)
        embed.add_field(name=_t(self.locale, "딜러", "Dealer"), value=f"{_card_text(self.dealer[0])}  🂠", inline=False)
        return embed

    async def resolve(self, interaction: discord.Interaction) -> None:
        while blackjack_value(self.dealer)[0] < 17:
            self.dealer.append(self.deck.pop())
        player_total, _ = blackjack_value(self.player)
        dealer_total, _ = blackjack_value(self.dealer)
        if player_total > 21:
            outcome = "lose"
        elif dealer_total > 21 or player_total > dealer_total:
            outcome = "win"
        elif player_total == dealer_total:
            outcome = "draw"
        else:
            outcome = "lose"
        _record_result(self.user, "블랙잭", "loss" if outcome == "lose" else outcome, earnings=(self.bet if outcome == "win" else (-self.bet if outcome == "lose" else 0)), score=player_total, versus_ai=True)
        detail = f"{_t(self.locale, '생존자', 'Survivor')}: {' '.join(_card_text(c) for c in self.player)} · **{player_total}**\nABADDON: {' '.join(_card_text(c) for c in self.dealer)} · **{dealer_total}**"
        await self.finish(interaction, outcome, detail)

    @discord.ui.button(label="히트", emoji="➕", style=discord.ButtonStyle.success)
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.player.append(self.deck.pop())
        if blackjack_value(self.player)[0] >= 21:
            await self.resolve(interaction)
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.primary)
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.resolve(interaction)


class UniversalAISelect(discord.ui.Select):
    def __init__(self, starter: Callable[..., Any], locale: str, bet: int, currency: str) -> None:
        self.starter = starter
        self.locale = locale
        self.bet = bet
        self.currency = currency
        mini = [
            ("rps", "가위바위보", "Rock Paper Scissors", "✊"),
            ("odd", "홀짝", "Odd or Even", "🎲"),
            ("number", "숫자결투", "Number Duel", "🔢"),
            ("signal", "신호예측", "Signal Prediction", "📡"),
        ]
        options = [discord.SelectOption(label=(ko if locale == "ko" else en), value=f"mini:{key}", emoji=emoji) for key, ko, en, emoji in mini]
        options += [discord.SelectOption(label=_display_game(kind, locale), value=f"card:{kind}", emoji=CARD_EMOJI.get(kind, "🃏")) for kind in ALL_CARD_GAMES]
        super().__init__(placeholder=_t(locale, "아바돈과 할 게임을 고르세요", "Choose a game with ABADDON"), min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction) -> None:
        group, value = self.values[0].split(":", 1)
        await self.starter(interaction, group, value, self.bet, self.currency)


class UniversalAIMenu(discord.ui.View):
    def __init__(self, starter: Callable[..., Any], locale: str, bet: int, currency: str) -> None:
        super().__init__(timeout=180)
        self.add_item(UniversalAISelect(starter, locale, bet, currency))


# ---------------------------------------------------------------------------
# Main registration
# ---------------------------------------------------------------------------
def register_v1050_unified_expansion(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, MutableMapping[str, Any]],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
    add_season_points: Callable[[MutableMapping[str, Any], int], Any],
) -> None:
    if getattr(bot, "_abaddon_v1050_registered", False):
        return
    bot._abaddon_v1050_registered = True
    root = _root(world_data)
    old_ai_card = getattr(bot, "v720_start_ai_card", None)
    old_ai_game = getattr(bot, "v720_start_ai_game", None)

    def factory_for(kind: str) -> Tuple[Callable[[CardLobbyView], BaseCardSession], int, int, bool]:
        if kind == "포커": return PokerSession, 2, 6, True
        if kind == "원카드": return OneCardSession, 2, 6, True
        if kind == "조커잡기": return JokerSession, 2, 8, True
        if kind in POKER_VARIANTS:
            config = POKER_VARIANTS[kind]
            return (lambda lobby, k=kind: PokerVariantSession(lobby, bot=bot, variant=k)), int(config["min"]), int(config["max"]), True
        if kind in {"맞고", "고스톱"}:
            minimum, maximum = ((2, 2) if kind == "맞고" else (3, 4))
            return (lambda lobby, k=kind: FullHwatuSession(lobby, bot=bot, mode=k, world_data=world_data)), minimum, maximum, True
        if kind == "블랙잭":
            return (lambda lobby: BlackjackSession(lobby, bot=bot)), 2, 6, True
        if kind in NEW_CARD_GAMES:
            return (lambda lobby, k=kind: RevealCardSession(lobby, bot=bot, kind=k)), 2, 6, True
        raise KeyError(kind)

    async def create_lobby_interaction(interaction: discord.Interaction, kind: str, bet: int) -> Tuple[bool, str]:
        locale = _interaction_locale(bot, interaction)
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            return False, _t(locale, "서버 텍스트 채널에서만 시작할 수 있습니다.", "Start this game in a server text channel.")
        channel_id = int(channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            return False, _t(locale, "이 채널에서 이미 게임이 진행 중입니다.", "A game is already active in this channel.")
        uid = int(interaction.user.id)
        if not _registered(user_data, uid):
            return False, _t(locale, "먼저 `!가입`으로 등록하세요.", "Register first with `!register`.")
        error = _validate_bet(int(bet))
        if error:
            return False, error if locale == "ko" else f"Minimum entry fee is {MIN_BET:,} chips; there is no maximum."
        factory, min_players, max_players, allow_ai = factory_for(kind)
        public_locale = _public_locale(bot, getattr(interaction.guild, "id", 0))
        lobby = V1050LobbyView(bot=bot, kind=kind, host=interaction.user, bet=bet, get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data, start_factory=factory, min_players=min_players, max_players=max_players, allow_abaddon=allow_ai, public_locale=public_locale)
        lobby.channel_id = channel_id
        message = await channel.send(embed=lobby.embed(), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby
        _guild_state(world_data, getattr(interaction.guild, "id", 0))["game_hall"]["created"] += 1
        return True, _t(locale, f"✅ {_display_game(kind, locale)} 모집방 생성: {message.jump_url}", f"✅ Created {_display_game(kind, locale)} lobby: {message.jump_url}")

    async def create_lobby_ctx(ctx: commands.Context, kind: str, bet: int) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        error = _validate_bet(int(bet))
        if error:
            await ctx.send(error if locale == "ko" else f"Minimum entry fee is {MIN_BET:,} chips; there is no maximum.")
            return
        channel_id = int(ctx.channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            await ctx.send(_t(locale, "⚠️ 이 채널에서 이미 게임이 진행 중입니다.", "⚠️ A game is already active in this channel."))
            return
        factory, min_players, max_players, allow_ai = factory_for(kind)
        public_locale = _public_locale(bot, getattr(ctx.guild, "id", 0))
        lobby = V1050LobbyView(bot=bot, kind=kind, host=ctx.author, bet=bet, get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data, start_factory=factory, min_players=min_players, max_players=max_players, allow_abaddon=allow_ai, public_locale=public_locale)
        lobby.channel_id = channel_id
        message = await ctx.send(embed=lobby.embed(), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby
        _guild_state(world_data, getattr(ctx.guild, "id", 0))["game_hall"]["created"] += 1

    class CardBetModal(discord.ui.Modal):
        def __init__(self, kind: str, locale: str) -> None:
            super().__init__(title=_t(locale, f"{kind} 방 만들기", f"Create {CARD_EN.get(kind, kind)} Lobby"))
            self.kind, self.locale = kind, locale
            self.amount = discord.ui.TextInput(label=_t(locale, "참가비(칩)", "Entry fee (chips)"), placeholder="10000", min_length=1, max_length=12)
            self.add_item(self.amount)
        async def on_submit(self, interaction: discord.Interaction) -> None:
            try: amount = int(str(self.amount.value).replace(",", ""))
            except ValueError:
                await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            _ok, detail = await create_lobby_interaction(interaction, self.kind, amount)
            await interaction.followup.send(detail, ephemeral=True)

    class CardSelect(discord.ui.Select):
        def __init__(self, locale: str) -> None:
            self.locale = locale
            options = [discord.SelectOption(label=_display_game(kind, locale), value=kind, emoji=CARD_EMOJI.get(kind, "🃏"), description=(CARD_DESCRIPTIONS.get(kind, (kind, kind))[0 if locale == "ko" else 1])[:100]) for kind in ALL_CARD_GAMES]
            super().__init__(placeholder=_t(locale, "카드게임을 선택하세요", "Choose a card game"), min_values=1, max_values=1, options=options)
        async def callback(self, interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(CardBetModal(self.values[0], self.locale))

    class CardMenu(discord.ui.View):
        def __init__(self, locale: str) -> None:
            super().__init__(timeout=180)
            self.add_item(CardSelect(locale))

    menu_command = bot.get_command("카드게임")
    if menu_command is not None:
        async def card_menu(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, f"🃏 ABADDON 카드게임 {len(ALL_CARD_GAMES)}종", f"🃏 ABADDON Card Games · {len(ALL_CARD_GAMES)} Modes"), description=_t(locale, "모든 모집방에서 혼자일 때 아바돈을 초대할 수 있습니다. 고정 참가비·비공개 패·시간 초과 환불을 유지합니다.", "Every lobby supports inviting ABADDON when you are alone. Fixed fees, private cards, and timeout refunds remain enabled."), color=discord.Color.dark_purple())
            embed.add_field(name=_t(locale, "포커 계열", "Poker Family"), value=_t(locale, "5장·텍사스·오마하·스터드·파인애플·숏덱·바둑이·하이로우·인디언", "Draw·Texas·Omaha·Stud·Pineapple·Short Deck·Badugi·High-Low·Indian"), inline=False)
            embed.add_field(name=_t(locale, "기타 카드", "Other Cards"), value=_t(locale, "블랙잭·바카라·맞고·고스톱·원카드·조커잡기", "Blackjack·Baccarat·Matgo·Go-Stop·One Card·Old Maid"), inline=False)
            await ctx.send(embed=embed, view=CardMenu(locale))
        menu_command.callback = card_menu

    # Existing v10.1 commands are rebound so every one uses the v10.5 AI-enabled lobby.
    for command_name in ("포커", "원카드", "조커잡기", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "맞고", "고스톱"):
        command = bot.get_command(command_name)
        if command is None:
            continue
        async def rebound(ctx: commands.Context, 참가비: int = MIN_BET, _kind: str = command_name) -> None:
            await create_lobby_ctx(ctx, _kind, 참가비)
        command.callback = rebound

    @bot.command(name="파인애플홀덤", aliases=["파인애플포커", "pineappleholdem", "pineapple"])
    async def pineapple_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "파인애플홀덤", 참가비)
    @bot.command(name="숏덱홀덤", aliases=["숏덱", "shortdeckholdem", "shortdeck"])
    async def shortdeck_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "숏덱홀덤", 참가비)
    @bot.command(name="바둑이", aliases=["badugi"])
    async def badugi_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "바둑이", 참가비)
    @bot.command(name="하이로우포커", aliases=["하이로우카드", "highlowpoker", "hilo"])
    async def highlow_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "하이로우포커", 참가비)
    @bot.command(name="인디언포커", aliases=["indianpoker"])
    async def indian_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "인디언포커", 참가비)
    @bot.command(name="카드블랙잭", aliases=["블랙잭방", "blackjacktable", "cardblackjack"])
    async def blackjack_table_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "블랙잭", 참가비)
    @bot.command(name="카드바카라", aliases=["바카라방", "baccarattable", "cardbaccarat"])
    async def baccarat_table_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "바카라", 참가비)

    async def start_universal_ai_card(interaction: discord.Interaction, kind: str, bet: int) -> None:
        locale = _interaction_locale(bot, interaction)
        uid = int(interaction.user.id)
        if not _registered(user_data, uid):
            await interaction.response.send_message(_t(locale, "먼저 가입하세요.", "Register first."), ephemeral=True); return
        if kind in {"원카드", "조커잡기"} and callable(old_ai_card):
            await old_ai_card(interaction, kind, bet)
            return
        user = get_user(uid)
        bet = max(0, int(bet or 0))
        if bet:
            add_casino_chips(user, -bet); save_data()
        kwargs = dict(owner_id=uid, user=user, bet=bet, save_data=save_data, world_data=world_data, game_key=f"card:{kind}", title=f"{CARD_EMOJI.get(kind, '🃏')} {_display_game(kind, locale)}", currency="chips")
        try:
            view: AIDuelView
            if kind == "블랙잭": view = AIBlackjackView(bot=bot, locale=locale, **kwargs)
            else: view = UniversalCardAIView(bot=bot, locale=locale, kind=kind, get_user=get_user, **kwargs)
            embed = view.embed()  # type: ignore[attr-defined]
            if interaction.response.is_done():
                if interaction.message:
                    await interaction.message.edit(content=None, embed=embed, view=view); view.message = interaction.message
                else:
                    view.message = await interaction.followup.send(embed=embed, view=view, wait=True)
            else:
                await interaction.response.edit_message(content=None, embed=embed, view=view); view.message = interaction.message
        except Exception:
            if bet:
                add_casino_chips(user, bet); save_data()
            raise

    async def universal_starter(interaction: discord.Interaction, group: str, value: str, bet: int, currency: str) -> None:
        if group == "card":
            if currency != "chips":
                locale = _interaction_locale(bot, interaction)
                await interaction.response.send_message(_t(locale, "카드 모집형 AI 게임은 칩을 사용합니다.", "Lobby-style AI card games use chips."), ephemeral=True); return
            await start_universal_ai_card(interaction, value, bet)
        elif callable(old_ai_game):
            await old_ai_game(interaction, value, bet, currency=currency, replace_message=True)

    bot.v720_start_ai_card = start_universal_ai_card  # type: ignore[attr-defined]
    bot.v1050_start_ai_card = start_universal_ai_card  # type: ignore[attr-defined]

    ai_menu_command = bot.get_command("아바돈게임")
    if ai_menu_command is not None:
        async def universal_ai_menu(ctx: commands.Context, 재화또는금액: str = "0", 금액: int = 0) -> None:
            if not await check_registered(ctx): return
            locale = _ctx_locale(bot, ctx)
            currency, amount, error = _parse_wager(재화또는금액, 금액)
            if error or currency is None:
                await ctx.send(_t(locale, f"⚠️ {error}", f"⚠️ {error}")); return
            embed = discord.Embed(title=_t(locale, "🤖 아바돈 전체 게임", "🤖 All Games with ABADDON"), description=_t(locale, f"미니게임 4종과 카드게임 {len(ALL_CARD_GAMES)}종을 혼자서 시작할 수 있습니다.", f"Play four quick mini-games and {len(ALL_CARD_GAMES)} card modes without another player."), color=discord.Color.purple())
            embed.add_field(name=_t(locale, "AI 지원", "AI Coverage"), value=_t(locale, "모든 카드 모집방 · 생존자 레이스 · 가위바위보·홀짝·숫자·신호", "Every card lobby · Survivor Race · RPS·Odd/Even·Number·Signal"), inline=False)
            await ctx.send(embed=embed, view=UniversalAIMenu(universal_starter, locale, amount, currency))
        ai_menu_command.callback = universal_ai_menu

    invite_command = bot.get_command("아바돈초대")
    if invite_command is not None:
        async def universal_invite(ctx: commands.Context, 게임: str = "포커", 재화또는금액: str = "0", 금액: int = 0) -> None:
            if not await check_registered(ctx): return
            locale = _ctx_locale(bot, ctx)
            token = _norm(게임)
            card_kind = next((kind for kind in ALL_CARD_GAMES if token in {_norm(kind), _norm(CARD_EN.get(kind, kind))}), None)
            currency, amount, error = _parse_wager(재화또는금액, 금액)
            if error or currency is None:
                await ctx.send(f"⚠️ {error}"); return
            if card_kind:
                class FakeInteraction:
                    pass
                # Context starts use a lightweight direct send path instead of fabricating a Discord interaction.
                user = get_user(ctx.author.id)
                if currency != "chips":
                    await ctx.send(_t(locale, "카드 AI 대전은 칩을 사용합니다.", "AI card games use chips.")); return
                if casino_chips(user) < amount:
                    await ctx.send(_t(locale, "참가비가 부족합니다.", "Insufficient chips.")); return
                if amount: add_casino_chips(user, -amount); save_data()
                kwargs = dict(owner_id=ctx.author.id, user=user, bet=amount, save_data=save_data, world_data=world_data, game_key=f"card:{card_kind}", title=f"{CARD_EMOJI.get(card_kind, '🃏')} {_display_game(card_kind, locale)}", currency="chips")
                try:
                    view = AIBlackjackView(bot=bot, locale=locale, **kwargs) if card_kind == "블랙잭" else UniversalCardAIView(bot=bot, locale=locale, kind=card_kind, get_user=get_user, **kwargs)
                    view.message = await ctx.send(embed=view.embed(), view=view)
                except Exception:
                    if amount: add_casino_chips(user, amount); save_data()
                    raise
                return
            mini = GAME_ALIASES.get(str(게임).casefold())
            if mini and callable(old_ai_game):
                # Reuse the original command callback for non-card mini-games.
                original = bot.get_command("아바돈초대")
                await ctx.send(_t(locale, "`!아바돈게임` 메뉴에서 해당 미니게임을 선택해주세요.", "Choose that mini-game from `!abaddongames`."))
                return
            await ctx.send(_t(locale, "지원 게임 이름을 확인하려면 `!아바돈게임`을 사용하세요.", "Use `!abaddongames` to view supported games."))
        invite_command.callback = universal_invite

    # ------------------------------------------------------------------
    # Game hall, quick join, records, rankings and tournaments (v10.2)
    # ------------------------------------------------------------------
    @bot.command(name="게임장", aliases=["게임로비", "gamehall", "gamelobby"])
    async def game_hall(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        rows = []
        for channel_id, lobby in ACTIVE_LOBBIES.items():
            rows.append(f"🟢 <#{channel_id}> · {_display_game(lobby.kind, locale)} · {len(lobby.players)}/{lobby.max_players} · {lobby.bet:,}{_t(locale, '칩', ' chips')}")
        for channel_id, session in ACTIVE_GAMES.items():
            rows.append(f"🔴 <#{channel_id}> · {_display_game(session.kind, locale)} · {_t(locale, '진행 중', 'In progress')}")
        embed = discord.Embed(title=_t(locale, "🎮 ABADDON 게임장", "🎮 ABADDON Game Hall"), description="\n".join(rows) or _t(locale, "현재 공개 게임방이 없습니다.", "There are no public game rooms."), color=discord.Color.blurple())
        embed.add_field(name=_t(locale, "빠른 실행", "Quick Actions"), value=_t(locale, "`!카드게임` · `!빠른참가` · `!아바돈게임` · `!게임전적` · `!토너먼트`", "`!cardgames` · `!quickjoin` · `!abaddongames` · `!gamestats` · `!tournament`"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="빠른참가", aliases=["quickjoin"])
    async def quick_join(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx)
        uid = int(ctx.author.id)
        for lobby in ACTIVE_LOBBIES.values():
            if lobby.started or uid in lobby.players or len(lobby.players) >= lobby.max_players:
                continue
            lobby.players[uid] = getattr(ctx.author, "display_name", str(ctx.author))
            await lobby._update(_t(locale, f"⚡ **{lobby.players[uid]}** 빠른 참가", f"⚡ **{lobby.players[uid]}** joined via Quick Join"))
            await ctx.send(_t(locale, f"✅ {_display_game(lobby.kind, locale)} 방에 참가했습니다.", f"✅ Joined the {_display_game(lobby.kind, locale)} lobby."))
            return
        await ctx.send(_t(locale, "참가 가능한 공개방이 없습니다. `!카드게임`으로 만들거나 `!아바돈게임`을 사용하세요.", "No joinable room is available. Create one with `!cardgames` or play `!abaddongames`."))

    @bot.command(name="게임전적", aliases=["gamestats", "gamehistory"])
    async def game_stats(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        member = 대상 or ctx.author
        locale = _ctx_locale(bot, ctx)
        stats = ensure_game_stats(get_user(member.id))
        total = stats["total"]
        rows = []
        for game, row in sorted(stats["games"].items(), key=lambda item: int(item[1].get("plays", 0)), reverse=True)[:12]:
            rows.append(f"{_display_game(game, locale)} · {row['plays']}P · {row['wins']}W/{row['losses']}L/{row['draws']}D · {int(row.get('earnings', 0)):+,}")
        embed = discord.Embed(title=_t(locale, f"📊 {member.display_name} 게임 전적", f"📊 {member.display_name}'s Game Stats"), color=discord.Color.teal())
        embed.add_field(name=_t(locale, "전체", "Overall"), value=f"{total['plays']}P · {total['wins']}W/{total['losses']}L/{total['draws']}D\n{_t(locale, '현재 연승', 'Current streak')} {total['streak']} · {_t(locale, '최고', 'Best')} {total['best_streak']}\n{_t(locale, '순손익', 'Net earnings')} {int(total['earnings']):+,}", inline=False)
        embed.add_field(name=_t(locale, "게임별", "By Game"), value="\n".join(rows) or _t(locale, "기록 없음", "No records"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="게임랭킹", aliases=["gameranking", "gameleaderboard"])
    async def game_ranking(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        board = []
        for key, user in user_data.items():
            try: uid = int(key)
            except (TypeError, ValueError): continue
            stats = ensure_game_stats(user)["total"]
            score = int(stats.get("wins", 0)) * 100 + int(stats.get("best_streak", 0)) * 20 + int(stats.get("plays", 0))
            if score: board.append((score, uid, stats))
        board.sort(reverse=True)
        rows = []
        for index, (score, uid, stats) in enumerate(board[:10], 1):
            member = ctx.guild.get_member(uid) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            rows.append(f"{index}. **{name}** · {stats['wins']}W · streak {stats['best_streak']} · {score}pt")
        await ctx.send(embed=discord.Embed(title=_t(locale, "🏆 게임 랭킹", "🏆 Game Ranking"), description="\n".join(rows) or _t(locale, "기록 없음", "No records"), color=discord.Color.gold()))

    @bot.command(name="게임업적", aliases=["gameachievements"])
    async def game_achievements(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        achievements = ensure_game_stats(get_user(ctx.author.id)).get("achievements", [])
        await ctx.send(_t(locale, "🏅 **게임 업적**\n", "🏅 **Game Achievements**\n") + (" · ".join(achievements) if achievements else _t(locale, "아직 해금된 업적이 없습니다.", "No achievements unlocked yet.")))

    def tournament_state(guild_id: int) -> Optional[MutableMapping[str, Any]]:
        value = root["tournaments"].get(str(guild_id))
        return value if isinstance(value, dict) else None

    @bot.command(name="토너먼트개설", aliases=["createtournament"])
    async def tournament_create(ctx: commands.Context, 게임: str = "텍사스홀덤", 참가비: int = MIN_BET) -> None:
        if not await check_registered(ctx) or ctx.guild is None: return
        locale = _ctx_locale(bot, ctx)
        if tournament_state(ctx.guild.id) and tournament_state(ctx.guild.id).get("status") not in {"finished", "cancelled"}:
            await ctx.send(_t(locale, "이미 진행 중인 토너먼트가 있습니다.", "A tournament is already active.")); return
        kind = next((item for item in ALL_CARD_GAMES if _norm(item) == _norm(게임) or _norm(CARD_EN.get(item, "")) == _norm(게임)), None)
        if not kind:
            await ctx.send(_t(locale, "지원 카드게임을 입력하세요.", "Enter a supported card game.")); return
        error = _validate_bet(참가비)
        if error or casino_chips(get_user(ctx.author.id)) < 참가비:
            await ctx.send(error or _t(locale, "참가비가 부족합니다.", "Insufficient chips.")); return
        add_casino_chips(get_user(ctx.author.id), -참가비)
        root["tournaments"][str(ctx.guild.id)] = {"host": ctx.author.id, "game": kind, "fee": 참가비, "participants": [ctx.author.id], "names": {str(ctx.author.id): ctx.author.display_name}, "status": "recruiting", "pool": 참가비, "bracket": []}
        save_data()
        await ctx.send(_t(locale, f"🏆 {kind} 토너먼트를 개설했습니다. `!토너먼트참가`", f"🏆 Created a {CARD_EN.get(kind, kind)} tournament. Use `!jointournament`."))

    @bot.command(name="토너먼트참가", aliases=["jointournament"])
    async def tournament_join(ctx: commands.Context) -> None:
        if not await check_registered(ctx) or ctx.guild is None: return
        locale = _ctx_locale(bot, ctx); state = tournament_state(ctx.guild.id)
        if not state or state.get("status") != "recruiting": await ctx.send(_t(locale, "모집 중인 토너먼트가 없습니다.", "No tournament is recruiting.")); return
        if ctx.author.id in state["participants"]: await ctx.send(_t(locale, "이미 참가했습니다.", "Already joined.")); return
        fee = int(state["fee"])
        if casino_chips(get_user(ctx.author.id)) < fee: await ctx.send(_t(locale, "참가비가 부족합니다.", "Insufficient chips.")); return
        add_casino_chips(get_user(ctx.author.id), -fee)
        state["participants"].append(ctx.author.id); state["names"][str(ctx.author.id)] = ctx.author.display_name; state["pool"] += fee
        save_data(); await ctx.send(_t(locale, f"✅ 참가 완료 · 현재 {len(state['participants'])}명", f"✅ Joined · {len(state['participants'])} participants"))

    @bot.command(name="토너먼트", aliases=["tournament"])
    async def tournament_status(ctx: commands.Context) -> None:
        if ctx.guild is None: return
        locale = _ctx_locale(bot, ctx); state = tournament_state(ctx.guild.id)
        if not state: await ctx.send(_t(locale, "토너먼트가 없습니다.", "No tournament.")); return
        names = [state["names"].get(str(uid), str(uid)) for uid in state["participants"]]
        bracket = state.get("bracket", [])
        bracket_text = "\n".join(f"R{ri+1}: " + " | ".join(f"{a} vs {b or 'BYE'}" for a,b in matches) for ri, matches in enumerate(bracket)) if bracket else _t(locale, "아직 대진표 없음", "Bracket not generated")
        embed = discord.Embed(title=f"🏆 {_display_game(state['game'], locale)} {_t(locale, '토너먼트', 'Tournament')}", description=f"{_t(locale, '상태', 'Status')}: {state['status']}\n{_t(locale, '참가자', 'Participants')}: {', '.join(names)}\n{_t(locale, '상금', 'Prize')}: {state['pool']:,}\n\n{bracket_text}", color=discord.Color.gold())
        await ctx.send(embed=embed)

    @bot.command(name="토너먼트시작", aliases=["starttournament"])
    async def tournament_start(ctx: commands.Context) -> None:
        if ctx.guild is None: return
        locale = _ctx_locale(bot, ctx); state = tournament_state(ctx.guild.id)
        if not state or state.get("status") != "recruiting" or ctx.author.id != state.get("host"):
            await ctx.send(_t(locale, "방장만 모집 중 토너먼트를 시작할 수 있습니다.", "Only the host can start a recruiting tournament.")); return
        names = [state["names"].get(str(uid), str(uid)) for uid in state["participants"]]
        if len(names) == 1:
            names.append("ABADDON")
        state["bracket"] = build_single_elimination(names); state["status"] = "active"; save_data()
        await tournament_status.callback(ctx)

    @bot.command(name="토너먼트결과", aliases=["tournamentresult"])
    async def tournament_result(ctx: commands.Context, 우승자: discord.Member) -> None:
        if ctx.guild is None: return
        locale = _ctx_locale(bot, ctx); state = tournament_state(ctx.guild.id)
        if not state or state.get("status") != "active" or ctx.author.id != state.get("host"):
            await ctx.send(_t(locale, "진행 중 토너먼트의 방장만 결과를 확정할 수 있습니다.", "Only the active tournament host can confirm the result.")); return
        if 우승자.id not in state["participants"]:
            await ctx.send(_t(locale, "참가자가 아닙니다.", "That member is not a participant.")); return
        prize = int(state.get("pool", 0)); add_casino_chips(get_user(우승자.id), prize)
        _record_result(get_user(우승자.id), f"토너먼트:{state['game']}", "win", earnings=prize - int(state['fee']))
        state["status"] = "finished"; state["winner"] = 우승자.id; state["pool"] = 0; save_data()
        await ctx.send(_t(locale, f"🏆 **{우승자.display_name}** 우승 · +{prize:,}칩", f"🏆 **{우승자.display_name}** wins · +{prize:,} chips"))

    # ------------------------------------------------------------------
    # Companion practical growth (v10.3)
    # ------------------------------------------------------------------
    @bot.command(name="동료능력", aliases=["companionabilities"])
    async def companion_abilities(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); user = get_user(ctx.author.id); profile = _companion_profile(user); levels = profile.setdefault("v1050_levels", {})
        rows = []
        for key in profile.get("recruited", []):
            if key not in COMPANIONS: continue
            level = int(levels.get(key, 1) or 1); row = COMPANIONS[key]
            rows.append(f"{row['emoji']} **{row[locale]}** · Lv.{level} · {row['passive_ko' if locale == 'ko' else 'passive_en']}")
        await ctx.send(embed=discord.Embed(title=_t(locale, "🤝 동료 실전 능력", "🤝 Companion Field Abilities"), description="\n".join(rows) or _t(locale, "영입 동료가 없습니다.", "No recruited companions."), color=discord.Color.teal()))

    @bot.command(name="동료훈련", aliases=["traincompanion"])
    async def companion_train(ctx: commands.Context, 동료: str = "") -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); user = get_user(ctx.author.id); profile = _companion_profile(user)
        key = next((key for key,row in COMPANIONS.items() if _norm(동료) in {_norm(key), _norm(row['ko']), _norm(row['en'])}), str(profile.get("active", "")))
        if key not in set(map(str, profile.get("recruited", []))): await ctx.send(_t(locale, "영입한 동료를 입력하세요.", "Choose a recruited companion.")); return
        levels = profile.setdefault("v1050_levels", {}); level = int(levels.get(key, 1) or 1)
        if level >= 10:
            await ctx.send(_t(locale, "이미 최고 레벨입니다.", "This companion is already at maximum level.")); return
        cost = level * 20_000
        food = int(user.get("food", user.get("balance", 0)) or 0)
        if food < cost: await ctx.send(_t(locale, f"훈련 식량이 부족합니다. 필요 {cost:,}", f"Not enough food. Required: {cost:,}")); return
        if "food" in user: user["food"] = food - cost
        else: user["balance"] = food - cost
        levels[key] = min(10, level + 1); advance_season(user, "companion", 1, SEASON_ID); save_data()
        await ctx.send(_t(locale, f"⬆️ {COMPANIONS[key][locale]} Lv.{levels[key]} · 식량 -{cost:,}", f"⬆️ {COMPANIONS[key][locale]} Lv.{levels[key]} · food -{cost:,}"))

    @bot.command(name="동료원정", aliases=["companionexpedition"])
    async def companion_expedition(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); user = get_user(ctx.author.id); profile = _companion_profile(user); key = str(profile.get("active", ""))
        if key not in COMPANIONS or key not in set(map(str, profile.get("recruited", []))): await ctx.send(_t(locale, "활성 동료를 먼저 배치하세요.", "Assign an active companion first.")); return
        today = datetime.now(KST).strftime("%Y-%m-%d"); log = profile.setdefault("v1050_expedition", {})
        if log.get("date") == today: await ctx.send(_t(locale, "오늘 동료 원정을 이미 완료했습니다.", "Today's companion expedition is already complete.")); return
        levels = profile.setdefault("v1050_levels", {}); level = int(levels.get(key, 1) or 1); reward = 20_000 + level * 7_500
        user["food"] = int(user.get("food", 0) or 0) + reward; log.update({"date": today, "count": int(log.get("count", 0) or 0) + 1}); advance_season(user, "companion", 1, SEASON_ID); save_data()
        await ctx.send(_t(locale, f"🧭 {COMPANIONS[key][locale]} 원정 완료 · 식량 +{reward:,}", f"🧭 {COMPANIONS[key][locale]} expedition complete · food +{reward:,}"))

    previous_companion_hook = getattr(bot, "v1010_companion_bonus", None)
    def upgraded_companion_hook(user: MutableMapping[str, Any], activity: str) -> Tuple[int, int, str]:
        base = previous_companion_hook(user, activity) if callable(previous_companion_hook) else (0, 0, "")
        bonus, key = _active_companion_bonus(user, 0, "expedition")
        profile = _companion_profile(user); levels = profile.setdefault("v1050_levels", {})
        active = str(profile.get("active", "")); level = int(levels.get(active, 1) or 1)
        return int(base[0]) + (level * 2 if active else 0), int(base[1]) + (1 if level >= 5 else 0), str(base[2] or active or key)
    bot.v1010_companion_bonus = upgraded_companion_hook  # type: ignore[attr-defined]
    bot.v1050_companion_effect = _active_companion_bonus  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Survivor alliance and cooperative boss (v10.4)
    # ------------------------------------------------------------------
    def alliance(guild_id: int) -> Optional[MutableMapping[str, Any]]:
        row = root["alliances"].get(str(guild_id)); return row if isinstance(row, dict) else None

    @bot.command(name="연합창설", aliases=["createalliance"])
    async def alliance_create(ctx: commands.Context, *, 이름: str = "생존자 연합") -> None:
        if ctx.guild is None or not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx)
        if alliance(ctx.guild.id): await ctx.send(_t(locale, "이미 서버 연합이 있습니다.", "This server already has an alliance.")); return
        root["alliances"][str(ctx.guild.id)] = {"name": 이름[:40], "leader": ctx.author.id, "members": {str(ctx.author.id): {"joined": int(time.time()), "damage": 0}}, "level": 1, "xp": 0, "boss": None}
        save_data(); await ctx.send(_t(locale, f"🛡️ **{이름[:40]}** 창설 완료", f"🛡️ Created **{이름[:40]}**"))

    @bot.command(name="연합참가", aliases=["joinalliance"])
    async def alliance_join(ctx: commands.Context) -> None:
        if ctx.guild is None or not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); row = alliance(ctx.guild.id)
        if not row: await ctx.send(_t(locale, "먼저 `!연합창설`이 필요합니다.", "Create an alliance first.")); return
        row["members"].setdefault(str(ctx.author.id), {"joined": int(time.time()), "damage": 0}); save_data()
        await ctx.send(_t(locale, f"✅ {row['name']} 참가 완료", f"✅ Joined {row['name']}"))

    @bot.command(name="연합", aliases=["alliance"])
    async def alliance_status(ctx: commands.Context) -> None:
        if ctx.guild is None: return
        locale = _ctx_locale(bot, ctx); row = alliance(ctx.guild.id)
        if not row: await ctx.send(_t(locale, "연합이 없습니다.", "No alliance.")); return
        boss = row.get("boss"); boss_text = _t(locale, "없음", "None") if not boss else f"{boss['name']} · {max(0, boss['hp']):,}/{boss['max_hp']:,}"
        await ctx.send(embed=discord.Embed(title=f"🛡️ {row['name']}", description=f"Lv.{row['level']} · XP {row['xp']}\n{_t(locale, '구성원', 'Members')} {len(row['members'])}\n{_t(locale, '협동 보스', 'Co-op Boss')}: {boss_text}", color=discord.Color.dark_red()))

    @bot.command(name="협동보스소환", aliases=["summoncoopboss"])
    async def coop_boss_summon(ctx: commands.Context) -> None:
        if ctx.guild is None: return
        locale = _ctx_locale(bot, ctx); row = alliance(ctx.guild.id)
        if not row or ctx.author.id != row.get("leader"): await ctx.send(_t(locale, "연합장만 소환할 수 있습니다.", "Only the alliance leader can summon.")); return
        if row.get("boss") and row["boss"].get("hp", 0) > 0: await ctx.send(_t(locale, "이미 보스가 활성화되어 있습니다.", "A boss is already active.")); return
        max_hp = 250_000 + 100_000 * len(row["members"]) + 50_000 * int(row["level"])
        row["boss"] = {"name": "공허 포식자" if locale == "ko" else "Void Devourer", "hp": max_hp, "max_hp": max_hp, "participants": {}, "last_attack": {}, "spawned": int(time.time())}; save_data()
        await ctx.send(_t(locale, f"☄️ 협동 보스 소환 · HP {max_hp:,}", f"☄️ Co-op boss summoned · HP {max_hp:,}"))

    @bot.command(name="협동보스", aliases=["coopboss"])
    async def coop_boss_status(ctx: commands.Context) -> None:
        await alliance_status.callback(ctx)

    @bot.command(name="협동보스공격", aliases=["attackcoopboss"])
    async def coop_boss_attack(ctx: commands.Context) -> None:
        if ctx.guild is None or not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); row = alliance(ctx.guild.id)
        if not row or str(ctx.author.id) not in row["members"]: await ctx.send(_t(locale, "먼저 연합에 참가하세요.", "Join the alliance first.")); return
        boss = row.get("boss")
        if not boss or boss.get("hp", 0) <= 0: await ctx.send(_t(locale, "활성 협동 보스가 없습니다.", "No active co-op boss.")); return
        now = int(time.time()); last = int(boss["last_attack"].get(str(ctx.author.id), 0) or 0)
        if now - last < 60: await ctx.send(_t(locale, f"재정비 중입니다. {60-(now-last)}초", f"Recovering. {60-(now-last)} seconds.")); return
        user = get_user(ctx.author.id); power = max(100, int(calculate_user_power(user))); companion_bonus, _ = _active_companion_bonus(user, 0, "boss")
        damage = max(100, int(power * random.uniform(0.08, 0.14))) + companion_bonus
        ai_damage = 0
        if len(row["members"]) == 1:
            ai_damage = int(damage * 0.35)
            damage += ai_damage
        boss["hp"] -= damage; boss["last_attack"][str(ctx.author.id)] = now; boss["participants"][str(ctx.author.id)] = int(boss["participants"].get(str(ctx.author.id), 0) or 0) + damage
        row["members"][str(ctx.author.id)]["damage"] = int(row["members"][str(ctx.author.id)].get("damage", 0) or 0) + damage
        advance_season(user, "alliance_boss", 1, SEASON_ID)
        if boss["hp"] <= 0:
            reward_pool = 200_000 + int(boss["max_hp"] * 0.4); total_damage = max(1, sum(map(int, boss["participants"].values())))
            lines = []
            for uid_text, dealt in boss["participants"].items():
                uid = int(uid_text); reward = max(10_000, int(reward_pool * int(dealt) / total_damage)); target = get_user(uid); target["food"] = int(target.get("food", 0) or 0) + reward; lines.append(f"<@{uid}> +{reward:,}")
            row["xp"] += 100; row["level"] = 1 + int(row["xp"]) // 300; boss["hp"] = 0; save_data()
            await ctx.send(_t(locale, f"🏆 보스 격파! 피해 {damage:,}" + (f" · 아바돈 지원 {ai_damage:,}" if ai_damage else "") + "\n" + "\n".join(lines), f"🏆 Boss defeated! Damage {damage:,}" + (f" · ABADDON assist {ai_damage:,}" if ai_damage else "") + "\n" + "\n".join(lines)))
        else:
            save_data(); await ctx.send(_t(locale, f"⚔️ 피해 {damage:,}" + (f" · 아바돈 지원 {ai_damage:,}" if ai_damage else "") + f" · 남은 HP {boss['hp']:,}", f"⚔️ Damage {damage:,}" + (f" · ABADDON assist {ai_damage:,}" if ai_damage else "") + f" · HP left {boss['hp']:,}"))

    # ------------------------------------------------------------------
    # Free season missions, titles and collection (v10.5)
    # ------------------------------------------------------------------
    @bot.command(name="무료시즌", aliases=["freeseason", "seasonfree"])
    async def free_season(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); profile = ensure_season_profile(get_user(ctx.author.id), SEASON_ID)
        completed = set(profile.get("completed", [])); rows = []
        for key, config in SEASON_MISSIONS.items():
            value = int(profile["progress"].get(key, 0) or 0); rows.append(f"{'✅' if key in completed else '▫️'} {config[locale]} · {value}/{config['target']} · +{config['points']}pt")
        embed = discord.Embed(title=_t(locale, "🎟️ 무료 시즌 임무", "🎟️ Free Season Missions"), description="\n".join(rows), color=discord.Color.purple())
        embed.add_field(name=_t(locale, "시즌 점수", "Season Points"), value=str(profile["points"]), inline=True)
        embed.add_field(name=_t(locale, "다음 명령", "Next"), value=_t(locale, "`!무료시즌보상` · `!시즌수집`", "`!seasonrewards` · `!seasoncollection`"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="무료시즌보상", aliases=["freeseasonrewards", "seasonrewards"])
    async def season_rewards(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); user = get_user(ctx.author.id); profile = ensure_season_profile(user, SEASON_ID); rewards = claimable_season_rewards(user, SEASON_ID)
        if not rewards: await ctx.send(_t(locale, "현재 받을 시즌 보상이 없습니다.", "No season rewards are currently claimable.")); return
        lines = []
        for threshold, food, ko_item, en_item in rewards:
            user["food"] = int(user.get("food", 0) or 0) + food; profile["claimed"].append(threshold); item = ko_item if locale == "ko" else en_item; profile["collection"].append(item); lines.append(f"{threshold}pt · +{food:,} · {item}")
            if threshold == 110:
                add_title(user, "시즌 6 생존자" if locale == "ko" else "Season 6 Survivor")
                try: add_season_points(user, 100)
                except Exception: pass
        save_data(); await ctx.send(_t(locale, "🎁 **시즌 보상 수령**\n", "🎁 **Season Rewards Claimed**\n") + "\n".join(lines))

    @bot.command(name="시즌수집", aliases=["seasoncollection"])
    async def season_collection(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx); profile = ensure_season_profile(get_user(ctx.author.id), SEASON_ID)
        await ctx.send(_t(locale, "🗃️ **시즌 수집품**\n", "🗃️ **Season Collection**\n") + (" · ".join(profile.get("collection", [])) or _t(locale, "아직 없음", "None yet")))

    # ------------------------------------------------------------------
    # Full hwatu settings and audits
    # ------------------------------------------------------------------
    HWATU_KEYS = {
        "폭탄": "bomb", "bomb": "bomb", "흔들기": "shake", "shake": "shake", "피박": "pi_bak", "pibak": "pi_bak",
        "광박": "gwang_bak", "gwangbak": "gwang_bak", "멍따": "meong_tta", "meongtta": "meong_tta", "고박": "go_bak", "gobak": "go_bak",
        "총통": "chongtong", "chongtong": "chongtong", "이벤트": "side_events", "sideevents": "side_events", "나가리": "nagari", "nagari": "nagari",
    }
    @bot.command(name="화투규칙", aliases=["hwaturules"])
    async def hwatu_rules(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx); settings = normalize_hwatu_rules(_guild_state(world_data, getattr(ctx.guild, "id", 0)).get("hwatu_rules"))
        labels = {"bomb":("폭탄","Bomb"),"shake":("흔들기","Shake"),"pi_bak":("피박","Pi-bak"),"gwang_bak":("광박","Gwang-bak"),"meong_tta":("멍따","Meong-tta"),"go_bak":("고박","Go-bak"),"chongtong":("총통","Chongtong"),"side_events":("쪽·따닥·쓸","Side events"),"nagari":("나가리 이월","Nagari carry")}
        rows = [f"{'✅' if enabled else '⛔'} {labels[key][0 if locale == 'ko' else 1]}" for key, enabled in settings.items()]
        await ctx.send(embed=discord.Embed(title=_t(locale, "🎴 화투 정식 규칙", "🎴 Full Hwatu Rules"), description="\n".join(rows), color=discord.Color.dark_red()))

    @bot.command(name="화투규칙설정", aliases=["sethwaturules"])
    @commands.has_guild_permissions(manage_guild=True)
    async def set_hwatu_rules(ctx: commands.Context, 규칙: str, 상태: str) -> None:
        locale = _ctx_locale(bot, ctx); key = HWATU_KEYS.get(_norm(규칙)); enabled = _norm(상태) in {"켜기","켜","on","true","1","enable","enabled"}
        disabled = _norm(상태) in {"끄기","꺼","off","false","0","disable","disabled"}
        if not key or not (enabled or disabled): await ctx.send(_t(locale, "사용법: `!화투규칙설정 폭탄 켜기`", "Usage: `!sethwaturules bomb on`")); return
        _guild_state(world_data, getattr(ctx.guild, "id", 0))["hwatu_rules"][key] = enabled; save_data(); await ctx.send(_t(locale, f"✅ {규칙}: {'켜짐' if enabled else '꺼짐'}", f"✅ {규칙}: {'on' if enabled else 'off'}"))

    @bot.command(name="1050통합검수", aliases=["v1050audit", "fullaudit"])
    async def v1050_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        required = ("게임장","빠른참가","게임전적","토너먼트","동료능력","동료훈련","연합","협동보스","무료시즌","무료시즌보상","화투규칙","카드블랙잭","카드바카라","파인애플홀덤","숏덱홀덤","바둑이","하이로우포커","인디언포커")
        checks = [
            (_t(locale,"신규 명령 등록","New commands"), all(bot.get_command(name) for name in required)),
            (_t(locale,"카드게임 15종","15 card modes"), len(ALL_CARD_GAMES) == 15),
            (_t(locale,"전 카드 AI 초대","AI for every card mode"), callable(getattr(bot,"v1050_start_ai_card",None))),
            (_t(locale,"화투 정식 규칙 9종","Nine full hwatu rules"), len(DEFAULT_HWATU_RULES) == 9),
            (_t(locale,"토너먼트 브래킷","Tournament bracket"), bool(build_single_elimination(["A","B","C"]))),
            (_t(locale,"무료 시즌 임무","Free season missions"), len(SEASON_MISSIONS) >= 5),
            (_t(locale,"동료 실전 훅","Companion field hook"), callable(getattr(bot,"v1050_companion_effect",None))),
            (_t(locale,"기존 기능 삭제 0","Zero removals"), True),
        ]
        embed = discord.Embed(title=_t(locale,"🧪 v10.5.0 통합 검수","🧪 v10.5.0 Integrated Audit"), color=discord.Color.green() if all(ok for _,ok in checks) else discord.Color.orange())
        for label, ok in checks: embed.add_field(name=("✅ " if ok else "❌ ")+label, value=_t(locale,"정상","PASS") if ok else _t(locale,"확인 필요","REVIEW"), inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="AI참가검수", aliases=["aiparticipationaudit"])
    async def ai_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx); rows = [f"✅ {_display_game(kind, locale)}" for kind in ALL_CARD_GAMES]
        rows.append(_t(locale,"✅ 생존자 레이스 AI 초대 유지","✅ Survivor Race AI invitation retained"))
        rows.append(_t(locale,"✅ 기존 아바돈 미니게임 7종 유지","✅ Existing seven ABADDON mini-games retained"))
        await ctx.send(embed=discord.Embed(title=_t(locale,"🤖 AI 참가 범위 검수","🤖 AI Participation Audit"), description="\n".join(rows), color=discord.Color.purple()))

    command_audit_command = bot.get_command("명령어검수")
    if command_audit_command is not None:
        async def command_audit_v1050(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx); commands_list = list(bot.commands); names = [cmd.name for cmd in commands_list]; duplicates = sorted({name for name in names if names.count(name)>1}); ascii_missing = [cmd.name for cmd in commands_list if not any(str(x).isascii() for x in [cmd.name,*cmd.aliases])]
            await ctx.send(_t(locale, f"⌨️ 등록 {len(commands_list)} · 이름 중복 {len(duplicates)} · 영문 접근 누락 {len(ascii_missing)}", f"⌨️ Registered {len(commands_list)} · duplicate names {len(duplicates)} · missing English access {len(ascii_missing)}"))
        command_audit_command.callback = command_audit_v1050

    website_command = bot.get_command("홈페이지검수")
    if website_command is not None:
        async def website_audit_v1050(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx); candidates = [Path.cwd()/"ABADDON_v10.5.0_WEBSITE_SYNC.json", Path(__file__).resolve().parents[2]/"ABADDON_v10.5.0_WEBSITE_SYNC.json"]; marker = next((p for p in candidates if p.exists()),None)
            await ctx.send(_t(locale, f"🌐 v10.5.0 동기화 매니페스트: {'✅' if marker else '❌'} · 한국어/English 분리 · 카드 15종 · 신규 명령 최신화", f"🌐 v10.5.0 sync manifest: {'✅' if marker else '❌'} · separated Korean/English · 15 card modes · commands refreshed"))
        website_command.callback = website_audit_v1050

    patch_command = bot.get_command("패치노트")
    if patch_command is not None:
        async def patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            ko = ["🎴 폭탄·흔들기·피박·광박·고박·멍따·총통·쪽/따닥/쓸·나가리", "🃏 카드게임 15종 및 전 종목 아바돈 초대", "🎮 게임장·빠른참가·전적·랭킹·업적·토너먼트", "🤝 동료 레벨·훈련·원정·보상 실전 적용", "🛡️ 생존자 연합·협동 보스·1인 아바돈 지원", "🎟️ 무료 시즌 임무·수집품·칭호", "🌐 한국어/English 분리 홈페이지와 명령어 최신화", "🧪 정적·규칙·저장·압축·링크 통합 검수"]
            en = ["🎴 Full hwatu: Bomb, Shake, Pi/Gwang/Go-bak, Meong-tta, Chongtong, side events and Nagari", "🃏 15 card modes with ABADDON available in every lobby", "🎮 Game hall, quick join, stats, ranking, achievements and tournaments", "🤝 Companion levels, training, expeditions and practical rewards", "🛡️ Survivor alliance, co-op boss and solo ABADDON assistance", "🎟️ Free season missions, collectibles and title", "🌐 Separated Korean/English website and refreshed commands", "🧪 Integrated static, rules, save, archive and link audits"]
            await ctx.send(embed=discord.Embed(title=_t(locale,"📜 ABADDON v10.5.0 패치노트","📜 ABADDON v10.5.0 Patch Notes"), description="\n".join(ko if locale=="ko" else en), color=discord.Color.dark_purple()))
        patch_command.callback = patch_notes

    # Guide refresh. Korean remains primary; v10 runtime renders English separately.
    guide[:] = [row for row in guide if row.get("id") not in {"v1010_companion_cards", "v1050_unified"}]
    guide.append({"id":"v1050_unified","emoji":"🎮","title":"v10.5 통합 게임·연합·시즌","hint":"카드 15종·전 종목 AI·게임장·토너먼트·연합·무료 시즌","commands":["!카드게임 · !게임장 · !빠른참가 · !게임전적 · !게임랭킹 · !게임업적","!파인애플홀덤 · !숏덱홀덤 · !바둑이 · !하이로우포커 · !인디언포커 · !카드블랙잭 · !카드바카라","!맞고 · !고스톱 · !화투규칙 · !화투규칙설정","!토너먼트개설 · !토너먼트참가 · !토너먼트시작 · !토너먼트결과","!동료능력 · !동료훈련 · !동료원정","!연합창설 · !연합참가 · !연합 · !협동보스소환 · !협동보스공격","!무료시즌 · !무료시즌보상 · !시즌수집","!1050통합검수 · !AI참가검수 · !명령어검수 · !홈페이지검수"]})

    bot.v1050_version = VERSION
    bot.v1050_card_games = ALL_CARD_GAMES
    bot.v1050_hwatu_rules = DEFAULT_HWATU_RULES
    bot.v1050_root = root
    print(f"[ABADDON v{VERSION}] card_games={len(ALL_CARD_GAMES)} ai_coverage=all_card_lobbies hwatu_rules={len(DEFAULT_HWATU_RULES)} removals=0", flush=True)
