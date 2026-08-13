from __future__ import annotations

"""ABADDON v10.6.0 authentic card-game flow and uncapped debt hotfix.

This module is registered after v10.5.0 and deliberately rebinds only the
card-game entry points. Existing save data and non-card commands remain intact.
"""

import asyncio
import random
import re
import time
import hashlib
import json
import secrets
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import (
    ACTIVE_GAMES,
    ACTIVE_LOBBIES,
    MIN_BET,
    BaseCardSession,
    CardLobbyView,
    JokerSession,
    OneCardSession,
    _card_text,
    _deck,
    _emoji_bar,
    _poker_score,
    _reservation_root,
    _safe_edit,
)
from apocalypse_bot.commands.v1010_companion_card_games import (
    HwatuCard,
    _best_five,
    _best_omaha,
    _ctx_locale,
    _hwatu_deck,
    _hwatu_label,
    _hwatu_labels,
    _hwatu_score,
    _hwatu_visual_uid,
    _interaction_locale,
    _locale,
    _poker_label,
    _t,
)
from apocalypse_bot.commands.v1050_rules import (
    HwatuSummary,
    badugi_score,
    best_short_deck,
    hwatu_multiplier,
    normalize_hwatu_rules,
    record_game_result,
)
from apocalypse_bot.commands.v1050_unified_expansion import (
    CARD_EMOJI,
    CARD_EN,
    V1050LobbyView,
    _guild_state,
)
from apocalypse_bot.commands.v1051_authentic_card_games import (
    AuthenticJokerSession,
    AuthenticOneCardSession,
    hwatu_event_text,
)
from apocalypse_bot.commands.v1051_rules import (
    DebtBettingRound,
    GoStopEngine,
    HwatuCardLite,
    HwatuTurnResult,
    ace_to_five_low_eight_or_better,
    baccarat_deal,
    baccarat_outcome,
    baccarat_return,
    baccarat_total,
    hwatu_payment_units,
    resolve_seotda,
    seotda_deck,
    seotda_rank,
)

VERSION = "10.6.0"
PATCH_DATE = "2026-08-03"
AI_ID = -1060
AI_ID_2 = -1061
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
AI_IDS = frozenset({AI_ID, AI_ID_2})
Card = Tuple[int, str]

AUTHENTIC_GAMES: Tuple[str, ...] = (
    "포커",
    "텍사스홀덤",
    "오마하홀덤",
    "세븐카드스터드",
    "파인애플홀덤",
    "숏덱홀덤",
    "바둑이",
    "하이로우포커",
    "인디언포커",
    "블랙잭",
    "바카라",
    "섯다",
    "맞고",
    "고스톱",
    "원카드",
    "조커잡기",
)

GAME_EN: Dict[str, str] = {
    **CARD_EN,
    "섯다": "Seotda",
}

GAME_EMOJI: Dict[str, str] = {
    **CARD_EMOJI,
    "섯다": "🎴",
}

GAME_RULE_SUMMARY: Dict[str, Tuple[str, str]] = {
    "포커": ("5장 드로우 포커: 첫 베팅 → 최대 3장 교환 → 마지막 베팅 → 족보 공개.", "Five-card draw: opening bet, exchange up to three cards, final bet, showdown."),
    "텍사스홀덤": ("홀카드 2장과 플랍·턴·리버를 순서대로 공개하며 매 거리마다 베팅합니다.", "Two hole cards with pre-flop, flop, turn and river betting rounds."),
    "오마하홀덤": ("홀카드 4장 중 정확히 2장, 보드에서 정확히 3장을 사용합니다.", "Use exactly two of four hole cards and exactly three board cards."),
    "세븐카드스터드": ("처음 3장부터 4·5·6·리버까지 카드를 받고 거리마다 베팅합니다.", "Receive cards from third street through the river, with betting on each street."),
    "파인애플홀덤": ("홀카드 3장을 받고 플랍 뒤 1장을 버린 다음 홀덤처럼 진행합니다.", "Receive three hole cards, discard one after the flop, then continue as Hold'em."),
    "숏덱홀덤": ("6 이상 36장 덱을 사용하며 플러시가 풀하우스보다 높습니다.", "Use a 36-card 6+ deck; a flush beats a full house."),
    "바둑이": ("4장 로우볼로 세 번 교환하고, 서로 다른 숫자·무늬의 낮은 패가 승리합니다.", "Four-card lowball with three draws; the lowest unique-rank, unique-suit hand wins."),
    "하이로우포커": ("세븐카드 스터드 하이/로우 8-or-better 방식으로 상금을 나눕니다.", "Seven-card stud high/low, eight-or-better, splitting the pot when a low qualifies."),
    "인디언포커": ("상대 카드만 보이는 상태에서 한 번의 노리밋 베팅 후 자기 카드를 공개합니다.", "See the opponent's card, complete one no-limit betting round, then reveal yours."),
    "블랙잭": ("각 참가자가 같은 딜러를 상대로 히트·스탠드를 선택하고 21에 가까운 쪽이 이깁니다.", "Each player chooses hit or stand against the same dealer hand."),
    "바카라": ("플레이어·뱅커·타이 중 선택한 뒤 표준 서드카드 규칙으로 결과를 계산합니다.", "Choose Player, Banker or Tie, then settle with standard third-card rules."),
    "섯다": ("첫 장 베팅 → 두 번째 장 베팅 → 광땡·땡·특수 족보·끗으로 승부합니다.", "Bet after the first card and again after the second, then compare Seotda ranks."),
    "맞고": ("2인 10장·바닥 8장. 손패를 내고 더미를 뒤집어 같은 월을 직접 맞춥니다.", "Two players, ten-card hands and eight floor cards; play and flip to match months."),
    "고스톱": ("3인 7장·바닥 6장. 획득 패 점수가 오르면 고 또는 스톱을 직접 선택합니다.", "Three players, seven-card hands and six floor cards; choose Go or Stop after scoring."),
    "원카드": ("같은 무늬·숫자를 내고 공격 카드와 방향 전환을 사용하는 턴제 게임입니다.", "Turn-based shedding game with matching ranks/suits, attacks and direction changes."),
    "조커잡기": ("짝을 버리고 다음 사람의 패에서 뽑아 마지막 조커를 피합니다.", "Discard pairs, draw from the next player, and avoid the final joker."),
}


def _display(kind: str, locale: str) -> str:
    return kind if locale == "ko" else GAME_EN.get(kind, kind)


def _short_deck() -> List[Card]:
    cards = [(rank, suit) for suit in ("♠️", "♥️", "♦️", "♣️") for rank in range(6, 15)]
    random.shuffle(cards)
    return cards


def _human_ids(ids: Iterable[int]) -> List[int]:
    return [int(uid) for uid in ids if int(uid) >= 0]


def _is_ai(uid: int) -> bool:
    return int(uid) < 0


def _hwatu_summary_lite(cards: Sequence[HwatuCardLite]) -> HwatuSummary:
    rich = [HwatuCard(c.month, c.category, c.name, c.name, c.junk) for c in cards]
    score, labels = _hwatu_score(rich)
    brights = sum(1 for c in rich if c.category.startswith("bright"))
    animals = sum(1 for c in rich if c.category.startswith("animal"))
    ribbons = sum(1 for c in rich if c.category.startswith("ribbon"))
    junk = sum(c.junk for c in rich if c.category != "animal_doublejunk")
    if any(c.category == "animal_doublejunk" for c in rich):
        # The scoring helper chooses the better interpretation. For bak checks,
        # treating the cup as double junk is the conventional generous choice.
        junk += 2 * sum(1 for c in rich if c.category == "animal_doublejunk")
    return HwatuSummary(score, brights, animals, ribbons, junk, tuple(labels))


def _hwatu_lite_text(card: HwatuCardLite, locale: str) -> str:
    symbols = {
        "bright": "✨", "bright_rain": "🌧️", "animal": "🦌", "animal_godori": "🐦",
        "animal_doublejunk": "🍶", "ribbon_blue": "🔵", "ribbon_red_poetry": "🔴",
        "ribbon_red_plain": "🎀", "ribbon": "🎗️", "junk": "🍂",
    }
    if locale == "ko":
        return f"{symbols.get(card.category, '🎴')}{card.month}월 {card.name}"
    return f"{symbols.get(card.category, '🎴')}Month {card.month}"


def _record(user: MutableMapping[str, Any], game: str, outcome: str, earnings: int, score: int = 0, versus_ai: bool = False) -> None:
    try:
        record_game_result(user, game, outcome, earnings=earnings, score=score, versus_ai=versus_ai)
    except Exception:
        pass


def _fairness_snapshot(session: Any) -> str:
    def serial(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(k): serial(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (list, tuple)):
            return [serial(v) for v in value]
        if isinstance(value, set):
            return sorted(serial(v) for v in value)
        if hasattr(value, "__dict__"):
            return serial(vars(value))
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return repr(value)
    state = {
        "kind": getattr(session, "kind", "card"),
        "variant": getattr(session, "variant", None),
        "mode": getattr(session, "mode", None),
        "players": list(getattr(session, "player_ids", [])),
        "deck": serial(getattr(session, "deck", [])),
        "hands": serial(getattr(session, "hands", {})),
        "board": serial(getattr(session, "board", [])),
        "dealer": serial(getattr(session, "dealer", [])),
    }
    engine = getattr(session, "engine", None)
    if engine is not None:
        state["engine"] = {
            "stock": serial(getattr(engine, "stock", [])),
            "floor": serial(getattr(engine, "floor", [])),
            "hands": serial(getattr(engine, "hands", {})),
        }
    return json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _create_fairness_commitment(session: Any) -> None:
    if getattr(session, "fairness_commit", None):
        return
    secret = secrets.token_hex(16)
    payload = _fairness_snapshot(session)
    commit = hashlib.sha256(f"{secret}|{payload}".encode("utf-8")).hexdigest()
    session.fairness_secret = secret
    session.fairness_payload = payload
    session.fairness_commit = commit

def _verify_fairness(secret: str, payload: str, commit: str) -> bool:
    return hashlib.sha256(f"{secret}|{payload}".encode("utf-8")).hexdigest() == str(commit)

class DebtCardSession(BaseCardSession):
    """Base session that intentionally permits negative wallets and uncapped bets."""

    def __init__(self, lobby: CardLobbyView, *, timeout: float) -> None:
        super().__init__(lobby, timeout=timeout)
        self.human_paid: Dict[int, int] = {uid: 0 for uid in _human_ids(self.player_ids)}
        self.opening_chips: Dict[int, int] = {uid: casino_chips(self.get_user(uid)) for uid in _human_ids(self.player_ids)}
        self.pot = self.bet * len(self.player_ids)

    def _reserve(self) -> None:
        deducted: List[int] = []
        try:
            for uid in _human_ids(self.player_ids):
                add_casino_chips(self.get_user(uid), -self.bet)
                self.human_paid[uid] += self.bet
                deducted.append(uid)
            _create_fairness_commitment(self)
            root = _reservation_root(self.world_data)
            root["reservations"][self.game_id] = {
                "kind": self.kind,
                "bet": self.bet,
                "players": list(self.player_ids),
                "created_at": int(time.time()),
                "negative_balance_allowed": True,
                "uncapped": False,
                "raise_safety_limit": _v1100_raise_limit(self),
                "fairness_commit": getattr(self, "fairness_commit", ""),
            }
            self.save_data()
        except Exception:
            for uid in deducted:
                add_casino_chips(self.get_user(uid), self.bet)
            self.save_data()
            raise

    def charge(self, uid: int, amount: int) -> int:
        amount = max(0, int(amount))
        if amount <= 0:
            return 0
        if not _is_ai(uid):
            add_casino_chips(self.get_user(uid), -amount)
            self.human_paid[uid] = int(self.human_paid.get(uid, 0)) + amount
        self.pot += amount
        self.save_data()
        return amount

    def _pay_debt_pot(self, winners: Sequence[int]) -> Dict[int, int]:
        winners = list(dict.fromkeys(int(uid) for uid in winners))
        if not winners:
            self._close_reservation()
            self.save_data()
            return {}
        share, remainder = divmod(int(self.pot), len(winners))
        payouts: Dict[int, int] = {}
        for index, uid in enumerate(winners):
            amount = share + (1 if index < remainder else 0)
            payouts[uid] = amount
            if not _is_ai(uid):
                add_casino_chips(self.get_user(uid), amount)
        self._close_reservation()
        self.save_data()
        return payouts

    def _refund_debt(self) -> None:
        for uid, amount in self.human_paid.items():
            add_casino_chips(self.get_user(uid), int(amount))
        self._close_reservation()
        self.save_data()

    def net_earnings(self, uid: int, payout: int = 0) -> int:
        return int(payout) - int(self.human_paid.get(int(uid), 0))

    def settlement_text(self, uid: int, payout: int = 0) -> str:
        """Localized game-only delta and current wallet for final result cards."""
        if _is_ai(uid):
            return _t(getattr(self, "locale", "ko"), "AI 좌석", "AI seat")
        locale = getattr(self, "locale", "ko")
        net = self.net_earnings(uid, payout)
        current = casino_chips(self.get_user(uid))
        before = current - net
        sign = "+" if net >= 0 else ""
        if locale == "ko":
            return f"이번 게임 **{sign}{net:,}칩** · 잔액 **{before:,} → {current:,}칩**"
        return f"Game net **{sign}{net:,} chips** · balance **{before:,} → {current:,}**"


def _enhance_final_result(session: DebtCardSession, embed: discord.Embed) -> discord.Embed:
    locale = getattr(session, "locale", "ko")
    description = str(embed.description or "")
    winners = re.findall(r"🏆\s+\*\*(.+?)\*\*", description)
    if not winners:
        winners = re.findall(r"승리[:· ]+([^\n]+)", description) if locale == "ko" else re.findall(r"Winner[:· ]+([^\n]+)", description)
    if winners and not any(str(field.name) in {"🏆 승자", "🏆 Winner"} for field in embed.fields):
        embed.add_field(name=_t(locale, "🏆 승자", "🏆 Winner"), value=" · ".join(dict.fromkeys(winners))[:1024], inline=False)
    settlement_rows=[]
    ledger_players=[]
    for uid in _human_ids(getattr(session, "player_ids", [])):
        before=int(getattr(session, "opening_chips", {}).get(uid, casino_chips(session.get_user(uid))))
        after=casino_chips(session.get_user(uid))
        net=after-before
        sign="+" if net>=0 else ""
        name=str(getattr(session, "names", {}).get(uid, uid))
        settlement_rows.append(_t(locale, f"**{name}** · {sign}{net:,}칩 · {before:,} → {after:,}칩", f"**{name}** · {sign}{net:,} chips · {before:,} → {after:,}"))
        ledger_players.append({"user_id":uid,"name":name,"before":before,"after":after,"net":net})
    if settlement_rows and not any(str(field.name) in {"💰 잔액 정산", "💰 Balance Settlement"} for field in embed.fields):
        embed.add_field(name=_t(locale, "💰 잔액 정산", "💰 Balance Settlement"), value="\n".join(settlement_rows)[:1024], inline=False)
    commit=str(getattr(session,"fairness_commit","") or "")
    secret=str(getattr(session,"fairness_secret","") or "")
    payload=str(getattr(session,"fairness_payload","") or "")
    verified=bool(commit and secret and payload and _verify_fairness(secret,payload,commit))
    if commit and not any(str(field.name) in {"🔐 공정성 검증", "🔐 Fairness"} for field in embed.fields):
        embed.add_field(name=_t(locale,"🔐 공정성 검증","🔐 Fairness"),value=_t(locale,f"커밋 `{commit[:16]}` · 검증 {'성공' if verified else '실패'} · `!셔플검증 {session.game_id}`",f"Commit `{commit[:16]}` · {'verified' if verified else 'failed'} · `!shuffleverify {session.game_id}`"),inline=False)
    root=session.world_data.setdefault("v1100_game_city",{})
    ledger=root.setdefault("settlements",[])
    if not any(str(row.get("game_id"))==str(session.game_id) for row in ledger if isinstance(row,Mapping)):
        ledger.insert(0,{
            "game_id":str(session.game_id),"kind":str(getattr(session,"variant",getattr(session,"mode",session.kind))),
            "guild_id":int(getattr(getattr(session.message,"guild",None),"id",0) or 0),
            "winners":list(dict.fromkeys(winners)),"pot":int(getattr(session,"pot",0) or 0),"players":ledger_players,
            "commit":commit,"secret":secret,"payload":payload,"verified":verified,"at":int(time.time()),
        })
        del ledger[200:]
        session.save_data()
    return embed

async def _publish_final(session: DebtCardSession, embed: discord.Embed) -> bool:
    """Publish a final result reliably, falling back to a new channel message."""
    embed = _enhance_final_result(session, embed)
    published = await _safe_edit(session.message, embed=embed, view=session)
    if published:
        return True
    channel = getattr(session.message, "channel", None)
    if channel is None or not hasattr(channel, "send"):
        return False
    try:
        from apocalypse_bot.commands.v1095_visual_polish import render_session_media
        image, extension = render_session_media(session, embed)
        if image is not None:
            filename = f"abaddon_table_{getattr(session, 'game_id', 'final')}.{extension}"
            file = discord.File(image, filename=filename)
            media_embed = embed.copy()
            media_embed.set_image(url=f"attachment://{filename}")
            session.message = await channel.send(embed=media_embed, view=session, file=file)
        else:
            session.message = await channel.send(embed=embed, view=session)
        return True
    except Exception:
        try:
            session.message = await channel.send(embed=embed, view=session)
            return True
        except Exception:
            return False


class RaiseModal(discord.ui.Modal):
    def __init__(self, session: "AuthenticPokerSession", uid: int, locale: str) -> None:
        super().__init__(title=_t(locale, "레이즈 금액", "Raise Amount"))
        self.session = session
        self.uid = int(uid)
        minimum = session.betting.current_bet + session.betting.min_raise
        self.amount = discord.ui.TextInput(
            label=_t(locale, "이번 거리 총 베팅액", "Total bet for this street"),
            placeholder=str(max(session.bet, minimum)),
            min_length=1,
            max_length=100,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        locale = _interaction_locale(self.session.bot, interaction)
        try:
            target = int(str(self.amount.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message(_t(locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True)
            return
        limit = _v1100_raise_limit(self.session)
        if target > limit:
            await interaction.response.send_message(_t(locale, f"한 번에 입력할 수 있는 총 베팅 안전 한도는 {limit:,}칩입니다. 잔액과는 무관하며 패배 시 음수 잔액이 유지됩니다.", f"The per-action safety limit is {limit:,} chips. It is not tied to your balance, and losses may still make it negative."), ephemeral=True)
            return
        await self.session.raise_action(interaction, self.uid, target)


class CardExchangeSelect(discord.ui.Select):
    def __init__(self, session: "AuthenticPokerSession", uid: int, locale: str, *, exact: Optional[int] = None, maximum: int = 3) -> None:
        self.session = session
        self.uid = int(uid)
        hand = session.hands[uid]
        options = [discord.SelectOption(label=f"{i + 1}. {_card_text(card)}", value=str(i)) for i, card in enumerate(hand[:25])]
        min_values = exact if exact is not None else 1
        max_values = exact if exact is not None else min(maximum, len(options))
        super().__init__(placeholder=_t(locale, "버리거나 교환할 카드를 선택", "Choose cards to discard/exchange"), min_values=min_values, max_values=max_values, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.submit_exchange(interaction, self.uid, sorted({int(value) for value in self.values}, reverse=True))


class CardExchangeView(discord.ui.View):
    def __init__(self, session: "AuthenticPokerSession", uid: int, locale: str, *, exact: Optional[int] = None, maximum: int = 3) -> None:
        super().__init__(timeout=60)
        self.add_item(CardExchangeSelect(session, uid, locale, exact=exact, maximum=maximum))


class AuthenticPokerSession(DebtCardSession):
    """Staged no-limit flow for all poker-family games."""

    HOLD_EM = {"텍사스홀덤", "오마하홀덤", "파인애플홀덤", "숏덱홀덤"}
    STUD = {"세븐카드스터드", "하이로우포커"}

    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, variant: str) -> None:
        super().__init__(lobby, timeout=720)
        self.bot = bot
        self.variant = variant
        self.locale = getattr(lobby, "public_locale", "ko")
        self.deck = _short_deck() if variant == "숏덱홀덤" else _deck()
        self.hands: Dict[int, List[Card]] = {uid: [] for uid in self.player_ids}
        self.board: List[Card] = []
        self.upcards: Dict[int, List[Card]] = {uid: [] for uid in self.player_ids}
        self.downcards: Dict[int, List[Card]] = {uid: [] for uid in self.player_ids}
        self.stage = ""
        self.stage_label = ""
        self.exchange_pending: set[int] = set()
        self.last_action = _t(self.locale, "카드를 배분했습니다.", "Cards have been dealt.")
        self._deal_initial()
        self.betting = DebtBettingRound(list(self.player_ids), min_raise=max(1, self.bet))
        self._localize_buttons()

    def _localize_buttons(self) -> None:
        if self.locale != "en":
            return
        labels = {"내 패": "My Hand", "체크/콜": "Check/Call", "레이즈": "Raise", "폴드": "Fold", "교환/버리기": "Draw/Discard", "교환 없음": "Stand Pat"}
        for child in self.children:
            label = getattr(child, "label", None)
            if label in labels:
                child.label = labels[label]

    def _deal_initial(self) -> None:
        if self.variant == "포커":
            for uid in self.player_ids:
                self.hands[uid] = [self.deck.pop() for _ in range(5)]
            self.stage = "draw_bet_1"; self.stage_label = "첫 베팅"
        elif self.variant == "인디언포커":
            for uid in self.player_ids:
                self.hands[uid] = [self.deck.pop()]
            self.stage = "indian_bet"; self.stage_label = "단일 베팅"
        elif self.variant in self.HOLD_EM:
            count = 4 if self.variant == "오마하홀덤" else (3 if self.variant == "파인애플홀덤" else 2)
            for uid in self.player_ids:
                self.hands[uid] = [self.deck.pop() for _ in range(count)]
            self.stage = "preflop"; self.stage_label = "프리플랍"
        elif self.variant in self.STUD:
            for uid in self.player_ids:
                cards = [self.deck.pop() for _ in range(3)]
                self.downcards[uid] = cards[:2]
                self.upcards[uid] = cards[2:]
                self.hands[uid] = cards
            self.stage = "third"; self.stage_label = "서드 스트리트"
        elif self.variant == "바둑이":
            for uid in self.player_ids:
                self.hands[uid] = [self.deck.pop() for _ in range(4)]
            self.stage = "badugi_bet_1"; self.stage_label = "첫 베팅"
        else:
            raise KeyError(self.variant)

    @property
    def current_uid(self) -> Optional[int]:
        return self.betting.current_uid

    @property
    def active_ids(self) -> List[int]:
        return self.betting.active

    def _private_hand_text(self, uid: int) -> str:
        cards = self.hands[uid]
        if self.variant in self.STUD:
            return f"{_t(self.locale, '비공개', 'Down')}: {' '.join(_card_text(c) for c in self.downcards[uid])}\n{_t(self.locale, '공개', 'Up')}: {' '.join(_card_text(c) for c in self.upcards[uid])}"
        return "  ".join(_card_text(card) for card in cards)

    def _public_player_line(self, uid: int) -> str:
        marker = "👉" if uid == self.current_uid and not self.exchange_pending else "▫️"
        status = _t(self.locale, "폴드", "Folded") if uid in self.betting.folded else f"{self.betting.round_bets.get(uid, 0):,}"
        visible = ""
        if self.variant in self.STUD:
            visible = " · " + " ".join(_card_text(c) for c in self.upcards[uid])
        elif self.variant == "인디언포커":
            opponents = [other for other in self.player_ids if other != uid]
            visible = " · " + _t(self.locale, "상대에게만 공개", "Visible to opponents")
        return f"{marker} **{self.names[uid]}** · {status}{visible}"

    def embed(self, final: str = "") -> discord.Embed:
        desc = final or f"{self.last_action}\n{_t(self.locale, '차례에 체크/콜·레이즈·폴드를 선택하세요. 추가 베팅은 잔액과 무관하게 전액 반영됩니다.', 'Choose check/call, raise or fold on your turn. Extra betting is fully charged even when the wallet becomes negative.')}"
        embed = discord.Embed(title=f"{GAME_EMOJI.get(self.variant, '🃏')} {_display(self.variant, self.locale)} · {self.stage_label}", description=desc, color=discord.Color.gold())
        if self.board:
            embed.add_field(name=_t(self.locale, "커뮤니티 보드", "Community Board"), value="  ".join(_card_text(c) for c in self.board), inline=False)
        embed.add_field(name=_t(self.locale, "참가자·거리 베팅", "Players · Street Bets"), value="\n".join(self._public_player_line(uid) for uid in self.player_ids), inline=False)
        embed.add_field(name=_t(self.locale, "현재 콜 금액", "Current Bet"), value=f"{self.betting.current_bet:,}", inline=True)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"**{self.pot:,}**", inline=True)
        if self.exchange_pending:
            names = ", ".join(self.names[uid] for uid in self.exchange_pending)
            embed.add_field(name=_t(self.locale, "교환 선택 대기", "Waiting for Draw/Discard"), value=names, inline=False)
        embed.set_footer(text=_t(self.locale, "자유 레이즈 · 잔액 음수 허용 · 서버 안전 한도 · 시간 초과 시 실제 납부액 환불", "Free raise · negative balances allowed · server safety limit · timeout refunds actual payments"))
        return embed

    async def start(self) -> None:
        self._reserve()
        if self.variant in self.HOLD_EM and len(self.player_ids) >= 2:
            # The base stake is the table ante. Hold'em additionally posts real
            # small/big blinds so pre-flop action begins with a live call amount.
            small_uid = self.player_ids[0]
            big_uid = self.player_ids[1]
            small = max(1, self.bet // 2)
            big = max(small + 1, self.bet)
            self.charge(small_uid, self.betting.post(small_uid, small))
            self.charge(big_uid, self.betting.post(big_uid, big))
            self.betting.current_index = 2 % len(self.player_ids)
            self.last_action = _t(
                self.locale,
                f"스몰 블라인드 {self.names[small_uid]} {small:,} · 빅 블라인드 {self.names[big_uid]} {big:,}",
                f"Small blind {self.names[small_uid]} {small:,} · big blind {self.names[big_uid]} {big:,}",
            )
        elif self.variant in self.STUD:
            # Third street opens from the lowest exposed card (bring-in order).
            self.betting.current_index = min(
                range(len(self.player_ids)),
                key=lambda index: self.upcards[self.player_ids[index]][0][0],
            )
            self.last_action = _t(self.locale, "서드 스트리트 최저 공개패부터 액션을 시작합니다.", "Third-street action starts from the lowest upcard.")
        await _safe_edit(self.message, embed=self.embed(), view=self)
        await self._run_ai_turns()

    async def update(self) -> None:
        await _safe_edit(self.message, embed=self.embed(), view=self)

    def _check_turn(self, interaction: discord.Interaction) -> Tuple[bool, int, str]:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if self.done:
            return False, uid, _t(locale, "이미 게임이 끝났습니다.", "The game is already over.")
        if self.exchange_pending:
            return False, uid, _t(locale, "먼저 교환·버리기 선택을 완료하세요.", "Complete the draw/discard decision first.")
        if uid != self.current_uid:
            return False, uid, _t(locale, f"현재 **{self.names.get(self.current_uid, 'ABADDON')}** 차례입니다.", f"It is **{self.names.get(self.current_uid, 'ABADDON')}**'s turn.")
        return True, uid, ""

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        extra = ""
        if self.variant == "인디언포커":
            others = [other for other in self.player_ids if other != uid and other not in self.betting.folded]
            extra = "\n" + "\n".join(f"{self.names[o]}: {_card_text(self.hands[o][0])}" for o in others)
            text = _t(locale, "내 카드는 승부 전까지 볼 수 없습니다.", "Your own card remains hidden until showdown.") + extra
        else:
            text = self._private_hand_text(uid)
        from apocalypse_bot.commands.v1094_card_table_images import render_private_hand
        cards = self.hands[uid]
        hidden = {0} if self.variant == "인디언포커" else set()
        image = render_private_hand(
            locale=locale,
            title=f"{_display(self.variant, locale)} · {_t(locale, '내 패', 'My Hand')}",
            cards=cards,
            note=text,
            hidden_indices=hidden,
        )
        filename = "abaddon_poker_private_hand.png"
        embed = discord.Embed(title=f"🂠 {_t(locale, '내 패', 'My Hand')}", color=discord.Color.dark_purple())
        embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(embed=embed, file=discord.File(image, filename=filename), ephemeral=True)

    @discord.ui.button(label="체크/콜", emoji="✅", style=discord.ButtonStyle.success)
    async def check_call(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, uid, error = self._check_turn(interaction)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True); return
        async with self.lock:
            action, paid = self.betting.check_or_call(uid)
            self.charge(uid, paid)
            self.last_action = _t(self.locale, f"**{self.names[uid]}** · {'체크' if action == 'check' else f'콜 {paid:,}'}", f"**{self.names[uid]}** · {'check' if action == 'check' else f'call {paid:,}'}")
            await interaction.response.defer()
            await self._after_action()

    @discord.ui.button(label="레이즈", emoji="⬆️", style=discord.ButtonStyle.primary)
    async def raise_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, uid, error = self._check_turn(interaction)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True); return
        await interaction.response.send_modal(RaiseModal(self, uid, _interaction_locale(self.bot, interaction)))

    async def raise_action(self, interaction: discord.Interaction, uid: int, target: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        limit = _v1100_raise_limit(self)
        if int(target) > limit:
            await interaction.response.send_message(_t(locale, f"레이즈 안전 한도는 {limit:,}칩입니다.", f"Raise safety limit is {limit:,} chips."), ephemeral=True); return
        async with self.lock:
            if uid != self.current_uid or self.exchange_pending:
                await interaction.response.send_message(_t(locale, "현재 레이즈할 수 없습니다.", "You cannot raise now."), ephemeral=True); return
            try:
                _action, paid = self.betting.raise_to(uid, target)
            except ValueError:
                minimum = self.betting.current_bet + self.betting.min_raise
                await interaction.response.send_message(_t(locale, f"최소 총 베팅액은 {minimum:,}입니다.", f"Minimum total bet is {minimum:,}."), ephemeral=True); return
            self.charge(uid, paid)
            self.last_action = _t(self.locale, f"**{self.names[uid]}** · {target:,}까지 레이즈", f"**{self.names[uid]}** · raises to {target:,}")
            await interaction.response.defer()
            await self._after_action()

    @discord.ui.button(label="폴드", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def fold_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, uid, error = self._check_turn(interaction)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True); return
        async with self.lock:
            self.betting.fold(uid)
            self.last_action = _t(self.locale, f"**{self.names[uid]}** · 폴드", f"**{self.names[uid]}** · folds")
            await interaction.response.defer()
            await self._after_action()

    @discord.ui.button(label="교환/버리기", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def exchange_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.exchange_pending:
            await interaction.response.send_message(_t(locale, "현재 교환 단계가 아닙니다.", "This is not a draw/discard stage."), ephemeral=True); return
        if self.variant == "파인애플홀덤":
            view = CardExchangeView(self, uid, locale, exact=1, maximum=1)
        elif self.variant == "바둑이":
            view = CardExchangeView(self, uid, locale, maximum=4)
        else:
            view = CardExchangeView(self, uid, locale, maximum=3)
        await interaction.response.send_message(_t(locale, "카드를 선택하세요.", "Choose cards."), view=view, ephemeral=True)

    @discord.ui.button(label="교환 없음", emoji="✋", style=discord.ButtonStyle.secondary, row=1)
    async def stand_pat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.exchange_pending or self.variant == "파인애플홀덤":
            await interaction.response.send_message(_t(locale, "현재 패스할 수 없습니다.", "You cannot stand pat now."), ephemeral=True); return
        await self.submit_exchange(interaction, uid, [])

    async def submit_exchange(self, interaction: discord.Interaction, uid: int, indices: Sequence[int]) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid not in self.exchange_pending:
                await interaction.response.send_message(_t(locale, "이미 선택을 완료했습니다.", "Your choice is already complete."), ephemeral=True); return
            if self.variant == "파인애플홀덤" and len(indices) != 1:
                await interaction.response.send_message(_t(locale, "정확히 한 장을 버리세요.", "Discard exactly one card."), ephemeral=True); return
            if any(index < 0 or index >= len(self.hands[uid]) for index in indices):
                await interaction.response.send_message(_t(locale, "패가 바뀌었습니다. 다시 선택하세요.", "Your hand changed. Choose again."), ephemeral=True); return
            discarded = [self.hands[uid][index] for index in indices]
            for index in sorted(indices, reverse=True):
                self.hands[uid].pop(index)
            if self.variant != "파인애플홀덤":
                for _ in discarded:
                    self.hands[uid].append(self.deck.pop())
            self.exchange_pending.remove(uid)
            await interaction.response.edit_message(content=_t(locale, f"✅ {len(discarded)}장 처리 완료", f"✅ {len(discarded)} card(s) processed"), view=None)
            if not self.exchange_pending:
                self._begin_post_exchange_bet()
                await self._run_ai_turns()
            await self.update()

    async def _after_action(self) -> None:
        if len(self.active_ids) <= 1:
            await self.finish(self.active_ids)
            return
        if self.betting.complete():
            await self._advance_stage()
        else:
            await self._run_ai_turns()
            await self.update()

    async def _run_ai_turns(self) -> None:
        guard = 0
        while not self.done and not self.exchange_pending and self.current_uid == AI_ID and guard < 20:
            guard += 1
            need = self.betting.to_call(AI_ID)
            strength = self._ai_strength()
            if need > self.bet * 8 and strength < 2 and random.random() < 0.55:
                self.betting.fold(AI_ID)
                self.last_action = _t(self.locale, "**ABADDON** · 폴드", "**ABADDON** · folds")
            elif strength >= 4 and random.random() < 0.35:
                target = max(self.betting.current_bet + self.betting.min_raise, self.betting.current_bet + self.bet * random.randint(1, 3))
                try:
                    _, paid = self.betting.raise_to(AI_ID, target)
                    self.charge(AI_ID, paid)
                    self.last_action = _t(self.locale, f"**ABADDON** · {target:,}까지 레이즈", f"**ABADDON** · raises to {target:,}")
                except ValueError:
                    _, paid = self.betting.check_or_call(AI_ID); self.charge(AI_ID, paid)
            else:
                action, paid = self.betting.check_or_call(AI_ID)
                self.charge(AI_ID, paid)
                self.last_action = _t(self.locale, f"**ABADDON** · {'체크' if action == 'check' else f'콜 {paid:,}'}", f"**ABADDON** · {'check' if action == 'check' else f'call {paid:,}'}")
            if len(self.active_ids) <= 1:
                await self.finish(self.active_ids); return
            if self.betting.complete():
                await self._advance_stage()
                if self.done or self.exchange_pending:
                    return
        await self.update()

    def _ai_strength(self) -> int:
        cards = self.hands.get(AI_ID, [])
        try:
            if self.variant == "바둑이":
                return badugi_score(cards)[0]
            if self.variant in self.HOLD_EM and len(cards) + len(self.board) >= 5:
                return int((_best_omaha(cards, self.board)[0] if self.variant == "오마하홀덤" else (_best_five(cards + self.board)[0]))[0])
            if self.variant in self.STUD and len(cards) >= 5:
                return int(_best_five(cards)[0][0])
            if len(cards) >= 5:
                return int(_poker_score(cards)[0][0])
            return max((rank for rank, _ in cards), default=0) // 3
        except Exception:
            return 1

    def _set_exchange(self) -> None:
        self.exchange_pending = {uid for uid in self.active_ids if not _is_ai(uid)}
        if AI_ID in self.active_ids:
            self._ai_exchange()
        if not self.exchange_pending:
            self._begin_post_exchange_bet()

    def _ai_exchange(self) -> None:
        hand = self.hands[AI_ID]
        if self.variant == "파인애플홀덤":
            discard = min(range(len(hand)), key=lambda i: hand[i][0])
            hand.pop(discard)
        elif self.variant == "바둑이":
            _count, _key, best = badugi_score(hand)
            keep = list(best)
            discard_count = len(hand) - len(keep)
            self.hands[AI_ID] = keep + [self.deck.pop() for _ in range(discard_count)]
        else:
            counts = Counter(rank for rank, _ in hand)
            keep_indices = [i for i, (rank, _suit) in enumerate(hand) if counts[rank] >= 2 or rank >= 11]
            discard_indices = [i for i in range(len(hand)) if i not in keep_indices][:3]
            for i in sorted(discard_indices, reverse=True):
                hand.pop(i)
            for _ in discard_indices:
                hand.append(self.deck.pop())

    def _begin_post_exchange_bet(self) -> None:
        mapping = {
            "draw_exchange": ("draw_bet_2", "마지막 베팅"),
            "pineapple_discard": ("flop_bet", "플랍 베팅"),
            "badugi_draw_1": ("badugi_bet_2", "두 번째 베팅"),
            "badugi_draw_2": ("badugi_bet_3", "세 번째 베팅"),
            "badugi_draw_3": ("badugi_bet_4", "마지막 베팅"),
        }
        self.stage, self.stage_label = mapping[self.stage]
        self.betting.reset_for_next_street(min_raise=max(1, self.bet))
        self.last_action = _t(self.locale, "교환·버리기가 끝났습니다.", "The draw/discard stage is complete.")

    async def _advance_stage(self) -> None:
        if len(self.active_ids) <= 1:
            await self.finish(self.active_ids); return
        if self.variant == "인디언포커":
            await self.finish_showdown(); return
        if self.variant == "포커":
            if self.stage == "draw_bet_1":
                self.stage = "draw_exchange"; self.stage_label = "카드 교환"; self._set_exchange(); await self._run_ai_turns(); return
            await self.finish_showdown(); return
        if self.variant == "바둑이":
            transitions = {
                "badugi_bet_1": "badugi_draw_1",
                "badugi_bet_2": "badugi_draw_2",
                "badugi_bet_3": "badugi_draw_3",
            }
            if self.stage in transitions:
                self.stage = transitions[self.stage]; self.stage_label = self.stage.replace("badugi_draw_", "드로우 ")
                self._set_exchange(); await self._run_ai_turns(); return
            await self.finish_showdown(); return
        if self.variant in self.HOLD_EM:
            if self.stage == "preflop":
                self.board.extend(self.deck.pop() for _ in range(3)); self.stage = "flop"
                if self.variant == "파인애플홀덤":
                    self.stage = "pineapple_discard"; self.stage_label = "플랍 뒤 1장 버리기"; self._set_exchange(); await self._run_ai_turns(); return
                self.stage_label = "플랍 베팅"
            elif self.stage in {"flop", "flop_bet"}:
                self.board.append(self.deck.pop()); self.stage = "turn"; self.stage_label = "턴 베팅"
            elif self.stage == "turn":
                self.board.append(self.deck.pop()); self.stage = "river"; self.stage_label = "리버 베팅"
            else:
                await self.finish_showdown(); return
            self.betting.reset_for_next_street(min_raise=max(1, self.bet)); await self._run_ai_turns(); return
        if self.variant in self.STUD:
            street = {"third": ("fourth", "포스 스트리트", True), "fourth": ("fifth", "피프스 스트리트", True), "fifth": ("sixth", "식스 스트리트", True), "sixth": ("river", "리버", False)}
            if self.stage not in street:
                await self.finish_showdown(); return
            next_stage, label, face_up = street[self.stage]
            for uid in self.active_ids:
                card = self.deck.pop(); self.hands[uid].append(card)
                (self.upcards[uid] if face_up else self.downcards[uid]).append(card)
            self.stage, self.stage_label = next_stage, label
            self.betting.reset_for_next_street(min_raise=max(1, self.bet)); await self._run_ai_turns(); return

    def _score(self, uid: int) -> Tuple[Any, str, Optional[Any]]:
        cards = self.hands[uid]
        if self.variant == "텍사스홀덤" or self.variant == "파인애플홀덤":
            score, label, best = _best_five(cards + self.board); return score, label, best
        if self.variant == "오마하홀덤":
            score, label, best = _best_omaha(cards, self.board); return score, label, best
        if self.variant == "숏덱홀덤":
            score, label, best = best_short_deck(cards + self.board); return score, label, best
        if self.variant in self.STUD:
            score, label, best = _best_five(cards); return score, label, best
        if self.variant == "바둑이":
            count, low, best = badugi_score(cards); return (count, *tuple(-value for value in low)), f"{count}카드 바둑이", best
        if self.variant == "인디언포커":
            return (cards[0][0],), "한 장", tuple(cards)
        score, label = _poker_score(cards); return score, label, tuple(cards)

    async def finish_showdown(self) -> None:
        if self.variant == "하이로우포커":
            await self._finish_high_low(); return
        scores = {uid: self._score(uid) for uid in self.active_ids}
        best = max(value[0] for value in scores.values())
        winners = [uid for uid, value in scores.items() if value[0] == best]
        await self.finish(winners, scores=scores)

    async def _finish_high_low(self) -> None:
        scores = {uid: self._score(uid) for uid in self.active_ids}
        best_high = max(value[0] for value in scores.values())
        high_winners = [uid for uid, value in scores.items() if value[0] == best_high]
        lows = {uid: ace_to_five_low_eight_or_better(self.hands[uid]) for uid in self.active_ids}
        qualified = {uid: value for uid, value in lows.items() if value is not None}
        if not qualified:
            await self.finish(high_winners, scores=scores, extra={uid: "Low 없음" for uid in self.active_ids}); return
        best_low = min(qualified.values())
        low_winners = [uid for uid, value in qualified.items() if value == best_low]
        # Split pot into high and low halves and distribute each independently.
        total = self.pot
        self.pot = total // 2 + total % 2
        high_payouts = self._pay_partial(high_winners, self.pot)
        low_amount = total // 2
        low_payouts = self._pay_partial(low_winners, low_amount)
        self.pot = total
        self._close_reservation(); self.save_data(); self.done = True
        rows = []
        for uid in self.player_ids:
            payout = high_payouts.get(uid, 0) + low_payouts.get(uid, 0)
            if uid in self.betting.folded:
                detail = _t(self.locale, "폴드", "Folded")
            else:
                label = scores[uid][1]
                low = lows[uid]
                detail = f"{label} · Low {low or '-'}"
            money = self.settlement_text(uid, payout)
            rows.append(f"{'🏆' if payout else '▫️'} **{self.names[uid]}** · {detail}\n└ {money}")
            if not _is_ai(uid):
                _record(self.get_user(uid), self.variant, "win" if payout else "loss", self.net_earnings(uid, payout), versus_ai=AI_ID in self.player_ids)
        await self._finish_message(rows)

    def _pay_partial(self, winners: Sequence[int], amount: int) -> Dict[int, int]:
        if not winners: return {}
        share, remainder = divmod(int(amount), len(winners)); payouts = {}
        for i, uid in enumerate(winners):
            value = share + (1 if i < remainder else 0); payouts[uid] = value
            if not _is_ai(uid): add_casino_chips(self.get_user(uid), value)
        return payouts

    async def finish(self, winners: Sequence[int], *, scores: Optional[Mapping[int, Tuple[Any, str, Any]]] = None) -> None:
        if self.done: return
        self.done = True
        payouts = self._pay_debt_pot(winners)
        rows = []
        for uid in self.player_ids:
            payout = payouts.get(uid, 0)
            if uid in self.betting.folded:
                detail = _t(self.locale, "폴드", "Folded")
            else:
                value = scores.get(uid) if scores else None
                label = value[1] if value else _t(self.locale, "마지막 생존", "Last player standing")
                cards = " ".join(_card_text(c) for c in self.hands.get(uid, []))
                detail = f"{cards} · **{_poker_label(label, self.locale)}**"
            rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {detail}\n└ {self.settlement_text(uid, payout)}")
            if not _is_ai(uid):
                _record(self.get_user(uid), self.variant, "win" if uid in winners else "loss", self.net_earnings(uid, payout), versus_ai=AI_ID in self.player_ids)
        await self._finish_message(rows)

    async def _finish_message(self, rows: Sequence[str]) -> None:
        self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        title = _t(self.locale, "🏆 승부 결과 · 최종 정산\n\n", "🏆 Match Result · Final Settlement\n\n")
        embed = self.embed(title + "\n".join(rows))
        await _publish_final(self, embed)
        self.stop()

    async def on_timeout(self) -> None:
        async with self.lock:
            if self.done: return
            self.done = True; self._refund_debt(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
            await _safe_edit(self.message, embed=self.embed(_t(self.locale, "⌛ 시간 초과 · 실제 납부액 전액 환불", "⌛ Timeout · all actual payments refunded")), view=self); self.stop()

class AuthenticBlackjackSession(DebtCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot) -> None:
        super().__init__(lobby, timeout=360)
        self.bot = bot
        self.locale = getattr(lobby, "public_locale", "ko")
        self.deck = _deck()
        self.hands: Dict[int, List[Card]] = {uid: [self.deck.pop(), self.deck.pop()] for uid in self.player_ids}
        self.dealer: List[Card] = [self.deck.pop(), self.deck.pop()]
        self.stood: set[int] = set()
        self.busted: set[int] = set()
        self.current_index = 0
        self.last_action = _t(self.locale, "각 참가자가 차례대로 히트 또는 스탠드를 선택합니다.", "Each player chooses Hit or Stand in turn.")
        if self.locale == "en":
            for child in self.children:
                labels = {"내 패": "My Hand", "히트": "Hit", "스탠드": "Stand"}
                if getattr(child, "label", None) in labels: child.label = labels[child.label]

    @staticmethod
    def value(cards: Sequence[Card]) -> int:
        total = sum(11 if rank == 14 else min(rank, 10) for rank, _ in cards)
        aces = sum(1 for rank, _ in cards if rank == 14)
        while total > 21 and aces:
            total -= 10; aces -= 1
        return total

    @property
    def current_uid(self) -> Optional[int]:
        active = [uid for uid in self.player_ids if uid not in self.stood and uid not in self.busted]
        if not active: return None
        for _ in range(len(self.player_ids)):
            uid = self.player_ids[self.current_index % len(self.player_ids)]
            if uid not in self.stood and uid not in self.busted: return uid
            self.current_index = (self.current_index + 1) % len(self.player_ids)
        return None

    def embed(self, final: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"🃏 {_display('블랙잭', self.locale)}", description=final or self.last_action, color=discord.Color.dark_green())
        embed.add_field(name=_t(self.locale, "딜러", "Dealer"), value=f"{_card_text(self.dealer[0])}  🂠", inline=False)
        rows = []
        for uid in self.player_ids:
            state = _t(self.locale, "버스트", "Bust") if uid in self.busted else (_t(self.locale, "스탠드", "Stand") if uid in self.stood else f"{len(self.hands[uid])}{_t(self.locale, '장', ' cards')}")
            rows.append(f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {state}")
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"{self.pot:,}", inline=True)
        embed.set_footer(text=_t(self.locale, "블랙잭 3:2 · 딜러 17 이상 스탠드 · 음수 잔액 허용", "Blackjack pays 3:2 · dealer stands on 17 · negative balances allowed"))
        return embed

    async def start(self) -> None:
        self._reserve(); await _safe_edit(self.message, embed=self.embed(), view=self); await self._run_ai()

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def hand_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True); return
        from apocalypse_bot.commands.v1094_card_table_images import render_private_hand
        total = self.value(self.hands[uid])
        image = render_private_hand(locale=locale, title=_t(locale, "블랙잭 · 내 패", "Blackjack · My Hand"), cards=self.hands[uid], note=_t(locale, f"현재 합계 {total}", f"Current total {total}"))
        filename = "abaddon_blackjack_private_hand.png"
        embed = discord.Embed(title=_t(locale, "🃏 블랙잭 내 패", "🃏 Blackjack Hand"), color=discord.Color.dark_green())
        embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(embed=embed, file=discord.File(image, filename=filename), ephemeral=True)

    @discord.ui.button(label="히트", emoji="➕", style=discord.ButtonStyle.success)
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid:
            await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True); return
        async with self.lock:
            card = self.deck.pop(); self.hands[uid].append(card); total = self.value(self.hands[uid])
            if total > 21: self.busted.add(uid)
            elif total == 21: self.stood.add(uid)
            self.last_action = f"**{self.names[uid]}** · {_card_text(card)} · {total}"
            self.current_index = (self.current_index + 1) % len(self.player_ids)
            await interaction.response.send_message(f"{_card_text(card)} · **{total}**", ephemeral=True)
            await self._after_turn()

    @discord.ui.button(label="스탠드", emoji="✋", style=discord.ButtonStyle.primary)
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid:
            await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True); return
        async with self.lock:
            self.stood.add(uid); self.last_action = f"**{self.names[uid]}** · {_t(self.locale, '스탠드', 'stands')}"
            self.current_index = (self.current_index + 1) % len(self.player_ids)
            await interaction.response.defer(); await self._after_turn()

    async def _run_ai(self) -> None:
        while self.current_uid == AI_ID and not self.done:
            total = self.value(self.hands[AI_ID])
            if total < 17:
                self.hands[AI_ID].append(self.deck.pop())
                if self.value(self.hands[AI_ID]) > 21: self.busted.add(AI_ID)
            else: self.stood.add(AI_ID)
            self.current_index = (self.current_index + 1) % len(self.player_ids)
        if self.current_uid is None and not self.done: await self.finish()
        elif not self.done: await _safe_edit(self.message, embed=self.embed(), view=self)

    async def _after_turn(self) -> None:
        if self.current_uid is None: await self.finish(); return
        await self._run_ai()

    async def finish(self) -> None:
        if self.done: return
        self.done = True
        while self.value(self.dealer) < 17: self.dealer.append(self.deck.pop())
        dealer_total = self.value(self.dealer)
        payouts: Dict[int, int] = {}
        rows = []
        outcome_labels = {"win": _t(self.locale, "승리", "WIN"), "draw": _t(self.locale, "무승부", "PUSH"), "loss": _t(self.locale, "패배", "LOSS")}
        for uid in self.player_ids:
            total = self.value(self.hands[uid])
            natural = len(self.hands[uid]) == 2 and total == 21
            if total > 21: outcome, returned = "loss", 0
            elif dealer_total > 21 or total > dealer_total:
                outcome = "win"; returned = (self.bet * 5 // 2) if natural else self.bet * 2
            elif total == dealer_total: outcome, returned = "draw", self.bet
            else: outcome, returned = "loss", 0
            if not _is_ai(uid) and returned:
                add_casino_chips(self.get_user(uid), returned); payouts[uid] = returned
            rows.append(f"{'🏆' if outcome == 'win' else ('➖' if outcome == 'draw' else '▫️')} **{self.names[uid]}** · **{outcome_labels[outcome]}** · {' '.join(_card_text(c) for c in self.hands[uid])} · {total}\n└ {self.settlement_text(uid, returned)}")
            if not _is_ai(uid): _record(self.get_user(uid), "블랙잭", outcome, returned - self.human_paid.get(uid, 0), total, AI_ID in self.player_ids)
        self._close_reservation(); self.save_data(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        detail = _t(self.locale, "🏆 승부 결과 · 최종 정산\n", "🏆 Match Result · Final Settlement\n") + f"{_t(self.locale, '딜러', 'Dealer')}: {' '.join(_card_text(c) for c in self.dealer)} · **{dealer_total}**\n\n" + "\n".join(rows)
        await _publish_final(self, self.embed(detail)); self.stop()

    async def on_timeout(self) -> None:
        if self.done: return
        self.done = True; self._refund_debt(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(_t(self.locale, "⌛ 시간 초과 · 실제 납부액 환불", "⌛ Timeout · actual payments refunded")), view=self); self.stop()


class BaccaratChoiceView(discord.ui.View):
    def __init__(self, session: "AuthenticBaccaratSession", uid: int, locale: str) -> None:
        super().__init__(timeout=60); self.session = session; self.uid = uid; self.locale = locale
        for value, ko, en, emoji in (("player", "플레이어", "Player", "🔵"), ("banker", "뱅커", "Banker", "🔴"), ("tie", "타이", "Tie", "🟢")):
            button = discord.ui.Button(label=ko if locale == "ko" else en, emoji=emoji, style=discord.ButtonStyle.secondary)
            async def callback(interaction: discord.Interaction, choice: str = value) -> None:
                await self.session.choose(interaction, self.uid, choice)
            button.callback = callback; self.add_item(button)


class AuthenticBaccaratSession(DebtCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot) -> None:
        super().__init__(lobby, timeout=240); self.bot = bot; self.locale = getattr(lobby, "public_locale", "ko")
        self.choices: Dict[int, str] = {}; self.result: Optional[Tuple[List[Card], List[Card], str]] = None
        if self.locale == "en":
            for child in self.children:
                if getattr(child, "label", None) == "베팅 선택": child.label = "Choose Bet"

    def embed(self, final: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"🎰 {_display('바카라', self.locale)}", description=final or _t(self.locale, "플레이어·뱅커·타이 중 하나를 선택하세요. 전원이 선택하면 표준 서드카드 규칙으로 즉시 딜합니다.", "Choose Player, Banker or Tie. The standard third-card deal starts after everyone chooses."), color=discord.Color.dark_red())
        rows = [f"{'✅' if uid in self.choices else '▫️'} **{self.names[uid]}** · {self.choices.get(uid, _t(self.locale, '선택 대기', 'Waiting'))}" for uid in self.player_ids]
        embed.add_field(name=_t(self.locale, "선택 현황", "Selections"), value="\n".join(rows), inline=False)
        embed.set_footer(text=_t(self.locale, "플레이어 1:1 · 뱅커 0.95:1 · 타이 8:1", "Player 1:1 · Banker 0.95:1 · Tie 8:1"))
        return embed

    async def start(self) -> None:
        self._reserve(); await _safe_edit(self.message, embed=self.embed(), view=self)
        if AI_ID in self.player_ids: self.choices[AI_ID] = random.choice(["player", "banker", "banker"])

    @discord.ui.button(label="베팅 선택", emoji="🎯", style=discord.ButtonStyle.primary)
    async def choose_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid not in self.player_ids or uid in self.choices:
            await interaction.response.send_message(_t(locale, "이미 선택했거나 참가자가 아닙니다.", "You already chose or are not a participant."), ephemeral=True); return
        await interaction.response.send_message(_t(locale, "베팅 대상을 선택하세요.", "Choose a bet."), view=BaccaratChoiceView(self, uid, locale), ephemeral=True)

    async def choose(self, interaction: discord.Interaction, uid: int, choice: str) -> None:
        async with self.lock:
            if uid in self.choices:
                await interaction.response.send_message(_t(self.locale, "이미 선택했습니다.", "Already selected."), ephemeral=True); return
            self.choices[uid] = choice
            await interaction.response.edit_message(content=f"✅ {choice}", view=None)
            if len(self.choices) == len(self.player_ids): await self.finish()
            else: await _safe_edit(self.message, embed=self.embed(), view=self)

    async def finish(self) -> None:
        if self.done: return
        self.done = True; deck = _deck(); player, banker = baccarat_deal(deck); outcome = baccarat_outcome(player, banker)
        rows = []
        outcome_labels = {"win": _t(self.locale, "승리", "WIN"), "draw": _t(self.locale, "적중 반환", "RETURN"), "loss": _t(self.locale, "패배", "LOSS")}
        choice_labels = {"player": _t(self.locale, "플레이어", "Player"), "banker": _t(self.locale, "뱅커", "Banker"), "tie": _t(self.locale, "타이", "Tie")}
        for uid in self.player_ids:
            returned = baccarat_return(self.bet, self.choices[uid], outcome)
            if returned and not _is_ai(uid): add_casino_chips(self.get_user(uid), returned)
            result = "win" if returned > self.bet else ("draw" if returned == self.bet else "loss")
            rows.append(f"{'🏆' if result == 'win' else ('➖' if result == 'draw' else '▫️')} **{self.names[uid]}** · {choice_labels.get(self.choices[uid], self.choices[uid])} · **{outcome_labels[result]}**\n└ {self.settlement_text(uid, returned)}")
            if not _is_ai(uid): _record(self.get_user(uid), "바카라", result, returned - self.human_paid.get(uid, 0), baccarat_total(player), AI_ID in self.player_ids)
        self._close_reservation(); self.save_data(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        detail = _t(self.locale, "🏆 승부 결과 · 최종 정산\n", "🏆 Match Result · Final Settlement\n") + f"🔵 Player: {' '.join(_card_text(c) for c in player)} · **{baccarat_total(player)}**\n🔴 Banker: {' '.join(_card_text(c) for c in banker)} · **{baccarat_total(banker)}**\n🏁 **{outcome.upper()}**\n\n" + "\n".join(rows)
        await _publish_final(self, self.embed(detail)); self.stop()

    async def on_timeout(self) -> None:
        if self.done: return
        self.done = True; self._refund_debt(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(_t(self.locale, "⌛ 선택 시간 초과 · 환불", "⌛ Selection timeout · refunded")), view=self); self.stop()

class AuthenticSeotdaSession(DebtCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot) -> None:
        super().__init__(lobby, timeout=480); self.bot = bot; self.locale = getattr(lobby, "public_locale", "ko")
        self.deck = seotda_deck(); random.shuffle(self.deck)
        self.hands = {uid: [self.deck.pop()] for uid in self.player_ids}
        self.street = 1; self.redeals = 0; self.permanent_folded: set[int] = set(); self.betting = DebtBettingRound(list(self.player_ids), min_raise=max(1, self.bet))
        self.last_action = _t(self.locale, "첫 장이 배분됐습니다. 첫 번째 베팅을 시작합니다.", "The first card is dealt. Opening betting begins.")
        if self.locale == "en":
            labels = {"내 패": "My Hand", "체크/콜": "Check/Call", "레이즈": "Raise", "폴드": "Fold"}
            for child in self.children:
                if getattr(child, "label", None) in labels: child.label = labels[child.label]

    @property
    def current_uid(self) -> Optional[int]: return self.betting.current_uid

    def embed(self, final: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"🎴 {_display('섯다', self.locale)} · {_t(self.locale, f'{self.street}차 베팅', f'Betting Round {self.street}')}", description=final or self.last_action, color=discord.Color.orange())
        rows = []
        for uid in self.player_ids:
            state = _t(self.locale, "폴드", "Folded") if uid in self.permanent_folded or uid in self.betting.folded else f"{len(self.hands[uid])}{_t(self.locale, '장', ' cards')} · {self.betting.round_bets.get(uid, 0):,}"
            rows.append(f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {state}")
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "콜 기준", "Current Bet"), value=f"{self.betting.current_bet:,}", inline=True)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"{self.pot:,}", inline=True)
        embed.set_footer(text=_t(self.locale, "첫 장·두 번째 장마다 노리밋 베팅 · 구사 재경기 · 음수 잔액 허용", "No-limit betting after each card · Gusa redeals · negative balances allowed"))
        return embed

    async def start(self) -> None:
        self._reserve(); await _safe_edit(self.message, embed=self.embed(), view=self); await self._run_ai()

    def _turn_ok(self, interaction: discord.Interaction) -> Tuple[bool, int, str]:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid: return False, uid, _t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn.")
        return True, uid, ""

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True); return
        cards = "  ".join(f"🎴{card.label}" for card in self.hands[uid])
        rank = seotda_rank(self.hands[uid]).name if len(self.hands[uid]) == 2 else _t(locale, "두 번째 장 대기", "Waiting for second card")
        from apocalypse_bot.commands.v1094_card_table_images import render_private_hand
        image = render_private_hand(locale=locale, title=_t(locale, "섯다 · 내 패", "Seotda · My Hand"), cards=self.hands[uid], note=rank, hwatu=True)
        filename = "abaddon_seotda_private_hand.png"
        embed = discord.Embed(title=_t(locale, "🎴 섯다 내 패", "🎴 Seotda Hand"), color=discord.Color.orange())
        embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(embed=embed, file=discord.File(image, filename=filename), ephemeral=True)

    @discord.ui.button(label="체크/콜", emoji="✅", style=discord.ButtonStyle.success)
    async def call(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, uid, error = self._turn_ok(interaction)
        if not ok: await interaction.response.send_message(error, ephemeral=True); return
        async with self.lock:
            action, paid = self.betting.check_or_call(uid); self.charge(uid, paid)
            self.last_action = f"**{self.names[uid]}** · {_t(self.locale, '체크' if action == 'check' else f'콜 {paid:,}', 'check' if action == 'check' else f'call {paid:,}')}"
            await interaction.response.defer(); await self._after_action()

    @discord.ui.button(label="레이즈", emoji="⬆️", style=discord.ButtonStyle.primary)
    async def raise_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, uid, error = self._turn_ok(interaction)
        if not ok: await interaction.response.send_message(error, ephemeral=True); return
        # Reuse the modal contract; this session exposes raise_action and betting.
        await interaction.response.send_modal(RaiseModal(self, uid, _interaction_locale(self.bot, interaction)))  # type: ignore[arg-type]

    async def raise_action(self, interaction: discord.Interaction, uid: int, target: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        limit = _v1100_raise_limit(self)
        if int(target) > limit:
            await interaction.response.send_message(_t(locale, f"레이즈 안전 한도는 {limit:,}칩입니다.", f"Raise safety limit is {limit:,} chips."), ephemeral=True); return
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 레이즈할 수 없습니다.", "You cannot raise now."), ephemeral=True); return
            try: _, paid = self.betting.raise_to(uid, target)
            except ValueError:
                minimum = self.betting.current_bet + self.betting.min_raise
                await interaction.response.send_message(_t(locale, f"최소 총 베팅액 {minimum:,}", f"Minimum total bet {minimum:,}"), ephemeral=True); return
            self.charge(uid, paid); self.last_action = f"**{self.names[uid]}** · {_t(self.locale, f'{target:,}까지 레이즈', f'raises to {target:,}')}"
            await interaction.response.defer(); await self._after_action()

    @discord.ui.button(label="폴드", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def fold(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ok, uid, error = self._turn_ok(interaction)
        if not ok: await interaction.response.send_message(error, ephemeral=True); return
        async with self.lock:
            self.betting.fold(uid); self.permanent_folded.add(uid); self.last_action = f"**{self.names[uid]}** · {_t(self.locale, '폴드', 'folds')}"
            await interaction.response.defer(); await self._after_action()

    async def _run_ai(self) -> None:
        while self.current_uid == AI_ID and not self.done:
            rank = seotda_rank(self.hands[AI_ID]).category if len(self.hands[AI_ID]) == 2 else self.hands[AI_ID][0].month
            need = self.betting.to_call(AI_ID)
            if need > self.bet * 10 and rank < 70 and random.random() < 0.55:
                self.betting.fold(AI_ID); self.last_action = "**ABADDON** · fold"
            elif rank >= 76 and random.random() < 0.45:
                target = max(self.betting.current_bet + self.betting.min_raise, self.betting.current_bet + self.bet * random.randint(1, 4))
                try: _, paid = self.betting.raise_to(AI_ID, target); self.charge(AI_ID, paid); self.last_action = f"**ABADDON** · raise {target:,}"
                except ValueError: _, paid = self.betting.check_or_call(AI_ID); self.charge(AI_ID, paid)
            else:
                action, paid = self.betting.check_or_call(AI_ID); self.charge(AI_ID, paid); self.last_action = f"**ABADDON** · {action} {paid:,}"
            if len(self.betting.active) <= 1: await self.finish(self.betting.active); return
            if self.betting.complete(): await self._advance_street(); return
        if not self.done: await _safe_edit(self.message, embed=self.embed(), view=self)

    async def _after_action(self) -> None:
        if len(self.betting.active) <= 1: await self.finish(self.betting.active); return
        if self.betting.complete(): await self._advance_street(); return
        await self._run_ai()

    async def _advance_street(self) -> None:
        if self.street == 1:
            for uid in self.betting.active: self.hands[uid].append(self.deck.pop())
            self.street = 2; self.betting.reset_for_next_street(min_raise=max(1, self.bet)); self.last_action = _t(self.locale, "두 번째 장이 배분됐습니다. 마지막 베팅입니다.", "The second card is dealt. Final betting begins.")
            await self._run_ai(); return
        status, winners, ranks = resolve_seotda({uid: self.hands[uid] for uid in self.betting.active})
        if status == "redeal" and self.redeals < 3:
            self.redeals += 1; active = list(self.betting.active); self.deck = seotda_deck(); random.shuffle(self.deck); self.hands = {uid: ([self.deck.pop()] if uid in active else self.hands.get(uid, [])) for uid in self.player_ids}
            self.street = 1; self.betting = DebtBettingRound(active, min_raise=max(1, self.bet)); self.last_action = _t(self.locale, f"구사 계열 재경기 {self.redeals}회 · 팟과 추가 베팅은 유지됩니다.", f"Gusa redeal {self.redeals}; the pot and prior bets remain.")
            await self._run_ai(); return
        await self.finish(winners, ranks=ranks)

    async def finish(self, winners: Sequence[int], *, ranks: Optional[Mapping[int, Any]] = None) -> None:
        if self.done: return
        self.done = True; payouts = self._pay_debt_pot(winners); rows = []
        for uid in self.player_ids:
            payout = payouts.get(uid, 0)
            if uid in self.permanent_folded or uid in self.betting.folded:
                detail = _t(self.locale, "폴드", "Folded")
                rank = None
            else:
                rank = ranks[uid] if ranks and uid in ranks else (seotda_rank(self.hands[uid]) if len(self.hands[uid]) == 2 else None)
                cards = " ".join(f"🎴{card.label}" for card in self.hands[uid])
                detail = f"{cards} · **{rank.name if rank else '-'}**"
            rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {detail}\n└ {self.settlement_text(uid, payout)}")
            if not _is_ai(uid): _record(self.get_user(uid), "섯다", "win" if uid in winners else "loss", self.net_earnings(uid, payout), int(rank.category if rank else 0), AI_ID in self.player_ids)
        self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        detail = _t(self.locale, "🏆 섯다 승부 결과 · 최종 정산\n\n", "🏆 Seotda Result · Final Settlement\n\n") + "\n".join(rows)
        await _publish_final(self, self.embed(detail)); self.stop()

    async def on_timeout(self) -> None:
        if self.done: return
        self.done = True; self._refund_debt(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(_t(self.locale, "⌛ 시간 초과 · 실제 납부액 환불", "⌛ Timeout · actual payments refunded")), view=self); self.stop()


class GoStopHandSelect(discord.ui.Select):
    def __init__(self, session: "AuthenticGoStopSession", uid: int, locale: str) -> None:
        self.session = session; self.uid = uid
        options = [discord.SelectOption(label=_hwatu_lite_text(card, locale)[:100], value=str(index)) for index, card in enumerate(session.engine.hands[uid][:25])]
        super().__init__(placeholder=_t(locale, "낼 화투패를 선택", "Choose a hwatu card"), min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.begin_play(interaction, self.uid, int(self.values[0]))


class GoStopHandView(discord.ui.View):
    def __init__(self, session: "AuthenticGoStopSession", uid: int, locale: str) -> None:
        super().__init__(timeout=60); self.add_item(GoStopHandSelect(session, uid, locale))


class GoStopMatchView(discord.ui.View):
    def __init__(self, session: "AuthenticGoStopSession", uid: int, locale: str, phase: str, indices: Sequence[int]) -> None:
        super().__init__(timeout=60); self.session = session; self.uid = uid; self.phase = phase
        options = [discord.SelectOption(label=_hwatu_lite_text(session.engine.floor[index], locale)[:100], value=str(index)) for index in indices]
        select = discord.ui.Select(placeholder=_t(locale, "가져올 바닥패 선택", "Choose a floor card"), min_values=1, max_values=1, options=options)
        async def callback(interaction: discord.Interaction) -> None:
            await session.choose_match(interaction, uid, phase, int(select.values[0]))
        select.callback = callback; self.add_item(select)


class GoStopMonthView(discord.ui.View):
    def __init__(self, session: "AuthenticGoStopSession", uid: int, locale: str, action: str, months: Sequence[int]) -> None:
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(
                label=_t(locale, f"{month}월", f"Month {month}"),
                value=str(month),
                emoji="💣" if action == "bomb" else "〰️",
            )
            for month in months[:25]
        ]
        select = discord.ui.Select(
            placeholder=_t(locale, "사용할 월을 선택", "Choose a month"),
            min_values=1,
            max_values=1,
            options=options,
        )

        async def callback(interaction: discord.Interaction) -> None:
            month = int(select.values[0])
            if action == "bomb":
                await session.execute_bomb(interaction, uid, month)
            else:
                await session.execute_shake(interaction, uid, month)

        select.callback = callback
        self.add_item(select)


class AuthenticGoStopSession(DebtCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, mode: str, world_data: MutableMapping[str, Any]) -> None:
        super().__init__(lobby, timeout=900); self.bot = bot; self.mode = mode; self.locale = getattr(lobby, "public_locale", "ko"); self.world_data_ref = world_data
        rich = _hwatu_deck()
        junk_seen: Dict[int, int] = {}
        lite = [HwatuCardLite(_hwatu_visual_uid(card, junk_seen), card.month, card.category, card.ko, card.junk) for card in rich]
        self.engine = GoStopEngine(self.player_ids, lite, matgo=(mode == "맞고"))
        self.go_counts = {uid: 0 for uid in self.player_ids}; self.previous_scores = {uid: 0 for uid in self.player_ids}; self.pending_go: Optional[int] = None; self.declared_go: set[int] = set(); self.pending_action: Dict[int, Dict[str, Any]] = {}; self._ai_running = False
        self.last_action = _t(self.locale, "손패를 내고 더미 한 장을 뒤집어 같은 월 패를 직접 맞추세요.", "Play one hand card, flip one stock card, and match the same month.")
        if self.locale == "en":
            labels = {"내 패": "My Hand", "패 내기": "Play Card", "폭탄": "Bomb", "흔들기": "Shake", "보너스 뒤집기": "Bonus Flip", "고": "Go", "스톱": "Stop"}
            for child in self.children:
                if getattr(child, "label", None) in labels: child.label = labels[child.label]

    def rules(self) -> Dict[str, bool]:
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0)
        return normalize_hwatu_rules(_guild_state(self.world_data_ref, guild_id).get("hwatu_rules"))

    def _sync_rule_flags(self) -> None:
        self.engine.side_events_enabled = bool(self.rules().get("side_events", True))

    def threshold(self) -> int: return 7 if self.mode == "맞고" else 3

    def score(self, uid: int) -> HwatuSummary: return _hwatu_summary_lite(self.engine.captured[uid])

    def embed(self, final: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"🎴 {_display(self.mode, self.locale)} · {_t(self.locale, '실전 진행', 'Authentic Play')}", description=final or self.last_action, color=discord.Color.dark_red())
        floor = "\n".join(" · ".join(_hwatu_lite_text(c, self.locale) for c in self.engine.floor[i:i+4]) for i in range(0, len(self.engine.floor), 4)) or _t(self.locale, "바닥패 없음", "No floor cards")
        embed.add_field(name=_t(self.locale, "바닥패", "Floor"), value=floor[:1024], inline=False)
        rows = []
        for uid in self.player_ids:
            summary = self.score(uid); marker = "👉" if uid == self.engine.current_uid and self.pending_go is None else "▫️"
            rows.append(f"{marker} **{self.names[uid]}** · {len(self.engine.hands[uid])}{_t(self.locale, '장', ' cards')} · **{summary.score}{_t(self.locale, '점', ' pts')}** · {_t(self.locale, '고', 'Go')} {self.go_counts[uid]} · {_t(self.locale, '피', 'Junk')} {summary.junk_points} · {_t(self.locale, '보너스', 'Bonus')} {self.engine.skip_credits[uid]}")
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "남은 더미", "Stock"), value=str(len(self.engine.stock)), inline=True)
        embed.add_field(name=_t(self.locale, "기준 판돈", "Base Stake"), value=f"{self.bet:,}", inline=True)
        if self.pending_go is not None: embed.add_field(name=_t(self.locale, "고/스톱", "Go/Stop"), value=f"**{self.names[self.pending_go]}**", inline=False)
        embed.set_footer(text=_t(self.locale, "동월 2장 중 직접 선택 · 뻑/쪽/따닥/쓸/폭탄/흔들기 · 배수 상한 없음 · 음수 허용", "Choose between two month matches · ppuk/jjok/ttadak/sweep/bomb/shake · uncapped · debt allowed"))
        return embed

    async def start(self) -> None:
        self._reserve(); self._sync_rule_flags()
        winners = self.engine.chongtong_winners()
        if winners and self.rules().get("chongtong", True): await self.finish(winners, chongtong=True); return
        await _safe_edit(self.message, embed=self.embed(), view=self); await self._run_ai()

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid not in self.engine.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True); return
        cards = "\n".join(f"{i+1}. {_hwatu_lite_text(card, locale)}" for i, card in enumerate(self.engine.hands[uid])) or _t(locale, "남은 패 없음", "No cards left")
        summary = self.score(uid)
        from apocalypse_bot.commands.v1094_card_table_images import render_private_hand
        note = f"{summary.score}{_t(locale, '점', ' pts')} · {_hwatu_labels(summary.labels, locale)}"
        image = render_private_hand(locale=locale, title=f"{_display(self.mode, locale)} · {_t(locale, '내 패', 'My Hand')}", cards=self.engine.hands[uid], note=note, hwatu=True)
        filename = "abaddon_hwatu_private_hand.png"
        embed = discord.Embed(title=f"🎴 {_t(locale, '내 패', 'My Hand')}", color=discord.Color.dark_red())
        embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(embed=embed, file=discord.File(image, filename=filename), ephemeral=True)

    @discord.ui.button(label="패 내기", emoji="🎴", style=discord.ButtonStyle.primary)
    async def play_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if self.pending_go is not None or uid != self.engine.current_uid:
            await interaction.response.send_message(_t(locale, "현재 본인 차례가 아니거나 고/스톱 선택 중입니다.", "It is not your turn or a Go/Stop decision is pending."), ephemeral=True); return
        await interaction.response.send_message(_t(locale, "낼 패를 선택하세요.", "Choose a card to play."), view=GoStopHandView(self, uid, locale), ephemeral=True)

    async def begin_play(self, interaction: discord.Interaction, uid: int, hand_index: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.engine.current_uid or self.pending_go is not None:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True); return
            self.pending_action[uid] = {"hand_index": hand_index, "match_index": None, "flip_match_index": None}
            result = self.engine.play(uid, hand_index)
            if result.needs_choice:
                phase, indices = result.needs_choice
                await interaction.response.edit_message(content=_t(locale, "가져올 바닥패를 선택하세요.", "Choose the floor card to capture."), view=GoStopMatchView(self, uid, locale, phase, indices)); return
            await interaction.response.edit_message(content=_t(locale, "✅ 턴 처리 완료", "✅ Turn resolved"), view=None)
            await self._post_turn(uid, result)

    async def choose_match(self, interaction: discord.Interaction, uid: int, phase: str, index: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            action = self.pending_action.get(uid)
            if not action:
                await interaction.response.send_message(_t(locale, "선택 정보가 만료됐습니다.", "The pending choice expired."), ephemeral=True); return
            self._sync_rule_flags()
            if action.get("kind") == "bomb":
                result = self.engine.play_bomb(uid, int(action["month"]), flip_match_index=index)
            elif action.get("kind") == "skip":
                result = self.engine.play(uid, None, skip=True, flip_match_index=index)
            else:
                action["match_index" if phase == "hand" else "flip_match_index"] = index
                result = self.engine.play(uid, action["hand_index"], match_index=action.get("match_index"), flip_match_index=action.get("flip_match_index"))
            if result.needs_choice:
                next_phase, indices = result.needs_choice
                await interaction.response.edit_message(content=_t(locale, "뒤집힌 패와 맞출 바닥패를 선택하세요.", "Choose the floor card for the flipped card."), view=GoStopMatchView(self, uid, locale, next_phase, indices)); return
            self.pending_action.pop(uid, None)
            await interaction.response.edit_message(content=_t(locale, "✅ 선택 완료", "✅ Choice complete"), view=None)
            await self._post_turn(uid, result)

    @discord.ui.button(label="폭탄", emoji="💣", style=discord.ButtonStyle.danger, row=1)
    async def bomb(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        months = self.engine.can_bomb(uid) if uid in self.engine.hands else []
        if uid != self.engine.current_uid or self.pending_go is not None or not months or not self.rules().get("bomb", True):
            await interaction.response.send_message(_t(locale, "현재 사용할 수 있는 폭탄이 없습니다.", "No bomb is available now."), ephemeral=True); return
        if len(months) > 1:
            await interaction.response.send_message(_t(locale, "폭탄으로 사용할 월을 선택하세요.", "Choose the month for the bomb."), view=GoStopMonthView(self, uid, locale, "bomb", months), ephemeral=True); return
        await self.execute_bomb(interaction, uid, months[0])

    async def execute_bomb(self, interaction: discord.Interaction, uid: int, month: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            self._sync_rule_flags()
            if uid != self.engine.current_uid or month not in self.engine.can_bomb(uid) or not self.rules().get("bomb", True):
                await interaction.response.send_message(_t(locale, "폭탄 조건이 더 이상 유효하지 않습니다.", "The bomb is no longer valid."), ephemeral=True); return
            result = self.engine.play_bomb(uid, month)
            if result.needs_choice:
                phase, indices = result.needs_choice
                self.pending_action[uid] = {"kind": "bomb", "month": month}
                await interaction.response.send_message(_t(locale, "폭탄 뒤집기와 맞출 바닥패를 선택하세요.", "Choose the floor match for the bomb flip."), view=GoStopMatchView(self, uid, locale, phase, indices), ephemeral=True); return
            await interaction.response.send_message(_t(locale, f"💣 {month}월 폭탄! 보너스 뒤집기 2회가 생겼습니다.", f"💣 Month {month} bomb! Two bonus flips are available."), ephemeral=True)
            await self._post_turn(uid, result)

    @discord.ui.button(label="흔들기", emoji="〰️", style=discord.ButtonStyle.secondary, row=1)
    async def shake(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        months = self.engine.can_shake(uid) if uid in self.engine.hands else []
        if uid != self.engine.current_uid or self.pending_go is not None or not months or not self.rules().get("shake", True):
            await interaction.response.send_message(_t(locale, "흔들기를 선언할 수 없습니다.", "You cannot declare a shake."), ephemeral=True); return
        if len(months) > 1:
            await interaction.response.send_message(_t(locale, "흔들기로 공개할 월을 선택하세요.", "Choose the month to reveal for Shake."), view=GoStopMonthView(self, uid, locale, "shake", months), ephemeral=True); return
        await self.execute_shake(interaction, uid, months[0])

    async def execute_shake(self, interaction: discord.Interaction, uid: int, month: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        if uid != self.engine.current_uid or not self.rules().get("shake", True) or not self.engine.declare_shake(uid, month):
            await interaction.response.send_message(_t(locale, "흔들기 조건이 더 이상 유효하지 않습니다.", "The Shake is no longer valid."), ephemeral=True); return
        await interaction.response.send_message(_t(locale, f"〰️ {month}월 3장을 공개하고 흔들기를 선언했습니다.", f"〰️ Revealed three Month {month} cards and declared Shake."), ephemeral=True)
        await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="보너스 뒤집기", emoji="🎁", style=discord.ButtonStyle.primary, row=2)
    async def bonus_flip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if uid != self.engine.current_uid or self.pending_go is not None or self.engine.skip_credits.get(uid, 0) <= 0:
            await interaction.response.send_message(_t(locale, "사용할 수 있는 폭탄 보너스 뒤집기가 없습니다.", "No bomb bonus flip is available."), ephemeral=True); return
        async with self.lock:
            self._sync_rule_flags()
            result = self.engine.play(uid, None, skip=True)
            if result.needs_choice:
                phase, indices = result.needs_choice
                self.pending_action[uid] = {"kind": "skip"}
                await interaction.response.send_message(_t(locale, "보너스 뒤집기와 맞출 바닥패를 선택하세요.", "Choose the floor match for the bonus flip."), view=GoStopMatchView(self, uid, locale, phase, indices), ephemeral=True); return
            await interaction.response.send_message(_t(locale, "🎁 보너스 뒤집기를 사용했습니다.", "🎁 Bonus flip used."), ephemeral=True)
            await self._post_turn(uid, result)

    @discord.ui.button(label="고", emoji="▶️", style=discord.ButtonStyle.success, row=1)
    async def go(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if self.pending_go != uid:
            await interaction.response.send_message(_t(locale, "현재 고를 선택할 수 없습니다.", "You cannot choose Go now."), ephemeral=True); return
        self.go_counts[uid] += 1; self.declared_go.add(uid); self.pending_go = None
        await interaction.response.send_message(_t(locale, f"▶️ {self.go_counts[uid]}고!", f"▶️ Go {self.go_counts[uid]}!"), ephemeral=True); await self._run_ai(); await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="스톱", emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def stop_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id); locale = _interaction_locale(self.bot, interaction)
        if self.pending_go != uid:
            await interaction.response.send_message(_t(locale, "현재 스톱할 수 없습니다.", "You cannot Stop now."), ephemeral=True); return
        await interaction.response.defer(); await self.finish([uid])

    async def _post_turn(self, uid: int, result: HwatuTurnResult) -> None:
        played = ", ".join(_hwatu_lite_text(c, self.locale) for c in result.played) or "-"
        flipped = _hwatu_lite_text(result.flipped, self.locale) if result.flipped else "-"
        events = " · ".join(result.events) or _t(self.locale, "일반 진행", "normal play")
        self.last_action = f"**{self.names[uid]}** · {_t(self.locale, '낸 패', 'played')} {played} · {_t(self.locale, '뒤집기', 'flipped')} {flipped} · {events}"
        summary = self.score(uid); previous = self.previous_scores[uid]; self.previous_scores[uid] = summary.score
        if summary.score >= self.threshold() and summary.score > previous and not self.engine.exhausted():
            if _is_ai(uid):
                if summary.score < (10 if self.mode == "맞고" else 7) and len(self.engine.stock) > 2: self.go_counts[uid] += 1; self.declared_go.add(uid)
                else: await self.finish([uid]); return
            else:
                self.pending_go = uid; await _safe_edit(self.message, embed=self.embed(), view=self); return
        if self.engine.exhausted():
            best = max(self.score(player).score + self.go_counts[player] for player in self.player_ids)
            winners = [player for player in self.player_ids if self.score(player).score + self.go_counts[player] == best]
            if best <= 0 or len(winners) == len(self.player_ids): await self.nagari(); return
            await self.finish(winners); return
        await self._run_ai(); await _safe_edit(self.message, embed=self.embed(), view=self)

    async def _run_ai(self) -> None:
        guard = 0
        while not self.done and self.pending_go is None and _is_ai(self.engine.current_uid) and guard < 60:
            guard += 1
            ai_uid = self.engine.current_uid
            shakes = self.engine.can_shake(ai_uid)
            if self.rules().get("shake", True) and shakes and random.random() < 0.7:
                self.engine.declare_shake(ai_uid, shakes[0])
            bombs = self.engine.can_bomb(ai_uid)
            if self.rules().get("bomb", True) and bombs:
                result = self.engine.play_bomb(ai_uid, bombs[0])
            else:
                hand = self.engine.hands[ai_uid]
                if not hand:
                    break
                index = max(range(len(hand)), key=lambda i: len(self.engine.matching_floor_indices(hand[i].month)))
                matches = self.engine.matching_floor_indices(hand[index].month); match = matches[0] if len(matches) == 2 else None
                flip_match = None
                while True:
                    result = self.engine.play(ai_uid, index, match_index=match, flip_match_index=flip_match)
                    if not result.needs_choice:
                        break
                    phase, indices = result.needs_choice
                    if phase == "hand":
                        match = indices[0]
                    else:
                        flip_match = indices[0]
            await self._post_turn(ai_uid, result)
            if self.pending_go is not None or self.done:
                return

    async def nagari(self) -> None:
        if self.done: return
        self.done = True; guild_id = getattr(getattr(self.message, "guild", None), "id", 0); state = _guild_state(self.world_data_ref, guild_id)
        state["hwatu_next_multiplier"] = max(2, int(state.get("hwatu_next_multiplier", 1) or 1) * 2)
        self._refund_debt(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(_t(self.locale, f"🌫️ 나가리 · 환불 · 다음 판 x{state['hwatu_next_multiplier']} (상한 없음)", f"🌫️ Nagari · refund · next round x{state['hwatu_next_multiplier']} (uncapped)")), view=self); self.stop()

    async def finish(self, winners: Sequence[int], *, chongtong: bool = False) -> None:
        if self.done: return
        self.done = True; winners = list(winners)
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0); state = _guild_state(self.world_data_ref, guild_id); carry = max(1, int(state.get("hwatu_next_multiplier", 1) or 1)); state["hwatu_next_multiplier"] = 1
        extra_wins = {uid: 0 for uid in winners}; extra_losses = {uid: 0 for uid in self.player_ids if uid not in winners}; reason_rows = []
        for loser in [uid for uid in self.player_ids if uid not in winners]:
            loser_summary = self.score(loser)
            for winner in winners:
                winner_summary = self.score(winner)
                if chongtong:
                    units, multiplier, reasons = 4, carry, ["총통 x4"]
                else:
                    units, _go_factor = hwatu_payment_units(winner_summary.score, self.go_counts[winner])
                    multiplier, reasons = hwatu_multiplier(winner_summary, loser_summary, go_count=self.go_counts[winner], shakes=self.engine.shakes[winner], bombs=self.engine.bombs[winner], loser_declared_go=loser in self.declared_go, nagari_multiplier=carry, rules=self.rules())
                factor = max(1, int(units)) * max(1, int(multiplier)); total_due = self.bet * factor; extra = max(0, total_due - self.bet)
                if extra:
                    if not _is_ai(loser): add_casino_chips(self.get_user(loser), -extra); self.human_paid[loser] = int(self.human_paid.get(loser, 0)) + extra
                    if not _is_ai(winner): add_casino_chips(self.get_user(winner), extra)
                    extra_wins[winner] += extra; extra_losses[loser] += extra
                reason_rows.append(f"⚖️ **{self.names[winner]}** vs {self.names[loser]} · {units}점단위 x{multiplier} = **x{factor}**" + (" · " + " · ".join(reasons) if reasons else ""))
        payouts = self._pay_debt_pot(winners); rows = []
        for uid in self.player_ids:
            summary = self.score(uid); payout = payouts.get(uid, 0) + extra_wins.get(uid, 0)
            rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · **{summary.score}{_t(self.locale, '점', ' pts')}** · {_hwatu_labels(summary.labels, self.locale)} · {_t(self.locale, '고', 'Go')} {self.go_counts[uid]} · 💣{self.engine.bombs[uid]} 〰️{self.engine.shakes[uid]}\n└ {self.settlement_text(uid, payout)}")
            if not _is_ai(uid): _record(self.get_user(uid), self.mode, "win" if uid in winners else "loss", payout - self.human_paid.get(uid, 0), summary.score, AI_ID in self.player_ids)
        self.save_data(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        detail = _t(self.locale, "🏆 승부 결과 · 최종 정산 · 배수 상한 없음\n", "🏆 Match Result · Final Settlement · uncapped multipliers\n") + "\n".join(reason_rows + rows)
        await _publish_final(self, self.embed(detail)); self.stop()

    async def on_timeout(self) -> None:
        if self.done: return
        self.done = True; self._refund_debt(); self._disable(); ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(_t(self.locale, "⌛ 시간 초과 · 실제 납부액 환불", "⌛ Timeout · actual payments refunded")), view=self); self.stop()

class V1060LobbyView(V1050LobbyView):
    """Localized lobby that advertises the real staged rule flow and debt rules."""

    def embed(self, note: str = "") -> discord.Embed:
        locale = self.public_locale
        display = _display(self.kind, locale)
        summary = GAME_RULE_SUMMARY.get(self.kind, (self.kind, GAME_EN.get(self.kind, self.kind)))[0 if locale == "ko" else 1]
        embed = discord.Embed(
            title=f"{GAME_EMOJI.get(self.kind, '🃏')} {display} · " + _t(locale, "실전 참가 모집", "Authentic Lobby"),
            description=(f"**{_t(locale, '실제 진행 규칙', 'Real Play Flow')}**\n{summary}\n\n{note}").strip(),
            color=discord.Color.dark_purple(),
        )
        names = "\n".join(
            f"{idx}. **{name}**{' 👑' if uid == self.host_id else ''}"
            for idx, (uid, name) in enumerate(self.players.items(), 1)
        )
        embed.add_field(
            name=_t(locale, f"참가자 {len(self.players)}/{self.max_players}", f"Players {len(self.players)}/{self.max_players}"),
            value=names or _t(locale, "없음", "None"),
            inline=False,
        )
        embed.add_field(
            name=_t(locale, "기준 판돈", "Base Stake"),
            value=f"**{self.bet:,}{_t(locale, '칩', ' chips')}** · " + _t(locale, "시작 시 전액 차감", "charged in full on start"),
            inline=True,
        )
        embed.add_field(
            name=_t(locale, "현재 기본 팟", "Current Base Pot"),
            value=f"**{self.bet * len(self.players):,}{_t(locale, '칩', ' chips')}**",
            inline=True,
        )
        embed.add_field(
            name=_t(locale, "경제 규칙", "Economy"),
            value=_t(locale, "잔액 음수 허용 · 자유 레이즈(서버 안전 한도) · 배수/정산 상한 없음 · 파산신청 가능", "Negative balances · free raise with server safety limit · uncapped multipliers/settlement · bankruptcy available"),
            inline=False,
        )
        embed.add_field(
            name=_t(locale, "진행", "Lobby Fill"),
            value=f"{_emoji_bar(len(self.players) / self.max_players)} **{len(self.players)}/{self.max_players}**",
            inline=False,
        )
        embed.set_footer(text=_t(locale, "혼자면 아바돈 초대 · 턴/선택/베팅 직접 진행 · 시간 초과 시 실제 납부액 환불", "Invite ABADDON when alone · real turns/choices/betting · timeout refunds actual payments"))
        return embed


class AuthenticGameSelect(discord.ui.Select):
    def __init__(self, create_lobby: Callable[[discord.Interaction, str, int], Any], locale: str) -> None:
        self.create_lobby = create_lobby; self.locale = locale
        options = [discord.SelectOption(label=_display(kind, locale), value=kind, emoji=GAME_EMOJI.get(kind, "🃏"), description=GAME_RULE_SUMMARY[kind][0 if locale == "ko" else 1][:100]) for kind in AUTHENTIC_GAMES]
        super().__init__(placeholder=_t(locale, "실전 카드게임 선택", "Choose an authentic card game"), min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AuthenticBetModal(self.create_lobby, self.values[0], self.locale))


class AuthenticBetModal(discord.ui.Modal):
    def __init__(self, create_lobby: Callable[[discord.Interaction, str, int], Any], kind: str, locale: str) -> None:
        super().__init__(title=_t(locale, f"{kind} 방 만들기", f"Create {_display(kind, locale)} Lobby")); self.create_lobby = create_lobby; self.kind = kind; self.locale = locale
        self.amount = discord.ui.TextInput(label=_t(locale, "기준 판돈/참가비", "Base stake / entry fee"), placeholder="10000", min_length=1, max_length=100); self.add_item(self.amount)
    async def on_submit(self, interaction: discord.Interaction) -> None:
        try: amount = int(str(self.amount.value).replace(",", ""))
        except ValueError:
            await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True); return
        await interaction.response.defer(ephemeral=True); ok, text = await self.create_lobby(interaction, self.kind, amount); await interaction.followup.send(text, ephemeral=True)


class AuthenticGameMenu(discord.ui.View):
    def __init__(self, create_lobby: Callable[[discord.Interaction, str, int], Any], locale: str) -> None:
        super().__init__(timeout=180); self.add_item(AuthenticGameSelect(create_lobby, locale))


@dataclass
class _AILobby:
    bot: commands.Bot
    kind: str
    host_id: int
    bet: int
    get_user: Callable[[int], MutableMapping[str, Any]]
    save_data: Callable[[], None]
    world_data: MutableMapping[str, Any]
    user_data: Mapping[Any, Any]
    message: Optional[discord.Message]
    channel_id: int
    public_locale: str
    players: Dict[int, str]


def register_v1060_authentic_card_games(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1060_registered", False): return
    bot._abaddon_v1060_registered = True
    previous_ai_starter = getattr(bot, "v720_start_ai_card", None)
    previous_ai_game = getattr(bot, "v720_start_ai_game", None)

    def factory_for(kind: str) -> Tuple[Callable[[CardLobbyView], BaseCardSession], int, int]:
        if kind in {"포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "파인애플홀덤", "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커"}:
            limits = {"인디언포커": (2, 2), "세븐카드스터드": (2, 7), "하이로우포커": (2, 7)}
            minimum, maximum = limits.get(kind, (2, 8))
            return (lambda lobby, k=kind: AuthenticPokerSession(lobby, bot=bot, variant=k)), minimum, maximum
        if kind == "블랙잭": return (lambda lobby: AuthenticBlackjackSession(lobby, bot=bot)), 2, 8
        if kind == "바카라": return (lambda lobby: AuthenticBaccaratSession(lobby, bot=bot)), 2, 8
        if kind == "섯다": return (lambda lobby: AuthenticSeotdaSession(lobby, bot=bot)), 2, 6
        if kind == "맞고": return (lambda lobby: AuthenticGoStopSession(lobby, bot=bot, mode="맞고", world_data=world_data)), 2, 2
        if kind == "고스톱": return (lambda lobby: AuthenticGoStopSession(lobby, bot=bot, mode="고스톱", world_data=world_data)), 3, 3
        if kind == "원카드": return AuthenticOneCardSession, 2, 6
        if kind == "조커잡기": return AuthenticJokerSession, 2, 8
        raise KeyError(kind)

    def valid_bet(amount: int) -> Optional[str]:
        if int(amount) < MIN_BET: return f"{MIN_BET:,}"
        return None

    async def create_lobby_interaction(interaction: discord.Interaction, kind: str, bet: int) -> Tuple[bool, str]:
        locale = _interaction_locale(bot, interaction); channel = interaction.channel
        if channel is None or not hasattr(channel, "send"): return False, _t(locale, "서버 텍스트 채널에서만 가능합니다.", "Use a server text channel.")
        if valid_bet(bet): return False, _t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다. 상한은 없습니다.", f"Minimum stake is {MIN_BET:,} chips. There is no maximum.")
        channel_id = int(channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES: return False, _t(locale, "이 채널에서 이미 게임이 진행 중입니다.", "A game is already active in this channel.")
        uid = int(interaction.user.id)
        if uid not in user_data and str(uid) not in user_data: return False, _t(locale, "먼저 가입하세요.", "Register first.")
        factory, minimum, maximum = factory_for(kind); public_locale = _locale(bot, 0, getattr(interaction.guild, "id", 0))
        lobby = V1060LobbyView(bot=bot, kind=kind, host=interaction.user, bet=int(bet), get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data, start_factory=factory, min_players=minimum, max_players=maximum, allow_abaddon=True, public_locale=public_locale)
        lobby.channel_id = channel_id; message = await channel.send(embed=lobby.embed(_t(public_locale, "💳 잔액이 부족해도 음수로 내려갑니다. 추가 베팅은 서버 안전 한도 안에서 자유 입력하며 화투 배수는 상한이 없습니다.", "💳 The wallet may go negative. Extra bets are free within the server safety limit; hwatu multipliers remain uncapped.")), view=lobby); lobby.message = message; ACTIVE_LOBBIES[channel_id] = lobby
        return True, _t(locale, f"✅ {_display(kind, locale)} 실전 방 생성: {message.jump_url}", f"✅ Created authentic {_display(kind, locale)} lobby: {message.jump_url}")

    async def create_lobby_ctx(ctx: commands.Context, kind: str, bet: int) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx)
        if valid_bet(bet): await ctx.send(_t(locale, f"최소 판돈은 {MIN_BET:,}칩이며 상한은 없습니다.", f"Minimum stake is {MIN_BET:,} chips with no maximum.")); return
        channel_id = int(ctx.channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES: await ctx.send(_t(locale, "⚠️ 이 채널에서 이미 게임이 진행 중입니다.", "⚠️ A game is already active in this channel.")); return
        factory, minimum, maximum = factory_for(kind); public_locale = _locale(bot, 0, getattr(ctx.guild, "id", 0))
        lobby = V1060LobbyView(bot=bot, kind=kind, host=ctx.author, bet=int(bet), get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data, start_factory=factory, min_players=minimum, max_players=maximum, allow_abaddon=True, public_locale=public_locale)
        lobby.channel_id = channel_id; message = await ctx.send(embed=lobby.embed(_t(public_locale, "💳 잔액 음수 허용 · 자유 레이즈 안전 한도 · 배수 상한 없음", "💳 Negative balances · free-raise safety limit · uncapped multipliers")), view=lobby); lobby.message = message; ACTIVE_LOBBIES[channel_id] = lobby

    async def authentic_ai_starter(interaction: discord.Interaction, kind: str, bet: int) -> None:
        locale = _interaction_locale(bot, interaction); uid = int(interaction.user.id)
        if valid_bet(bet):
            await interaction.response.send_message(_t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다.", f"Minimum stake is {MIN_BET:,} chips."), ephemeral=True); return
        if interaction.response.is_done() is False:
            await interaction.response.defer()
        channel_id = int(getattr(interaction.channel, "id", 0)); public_locale = _locale(bot, 0, getattr(interaction.guild, "id", 0)); factory, _min, _max = factory_for(kind)
        message = interaction.message
        if message is None:
            message = await interaction.followup.send(
                embed=discord.Embed(
                    title=f"{GAME_EMOJI.get(kind, '🃏')} {_display(kind, public_locale)} · ABADDON",
                    description=_t(public_locale, "실전 세션을 준비하고 있습니다.", "Preparing the authentic session."),
                    color=discord.Color.dark_purple(),
                ),
                wait=True,
            )
        players = {uid: getattr(interaction.user, "display_name", str(interaction.user)), AI_ID: "ABADDON"}
        if kind == "고스톱":
            players[AI_ID_2] = "ABADDON-β"
        lobby = _AILobby(bot, kind, uid, int(bet), get_user, save_data, world_data, user_data, message, channel_id, public_locale, players)
        session = factory(lobby)  # type: ignore[arg-type]
        ACTIVE_GAMES[channel_id] = session
        try:
            await session.start()
        except Exception:
            ACTIVE_GAMES.pop(channel_id, None)
            if isinstance(session, DebtCardSession):
                try:
                    session._refund_debt()
                except Exception:
                    pass
            raise

    async def start_ai_ctx(ctx: commands.Context, kind: str, bet: int) -> None:
        locale = _ctx_locale(bot, ctx)
        if not await check_registered(ctx):
            return
        if valid_bet(bet):
            await ctx.send(_t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다. 상한은 없습니다.", f"Minimum stake is {MIN_BET:,} chips. There is no maximum."))
            return
        channel_id = int(ctx.channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            await ctx.send(_t(locale, "⚠️ 이 채널에서 이미 게임이 진행 중입니다.", "⚠️ A game is already active in this channel."))
            return
        public_locale = _locale(bot, 0, getattr(ctx.guild, "id", 0)); factory, _min, _max = factory_for(kind)
        message = await ctx.send(
            embed=discord.Embed(
                title=f"{GAME_EMOJI.get(kind, '🃏')} {_display(kind, public_locale)} · ABADDON",
                description=_t(public_locale, "실전 세션을 준비하고 있습니다.", "Preparing the authentic session."),
                color=discord.Color.dark_purple(),
            )
        )
        players = {int(ctx.author.id): getattr(ctx.author, "display_name", str(ctx.author)), AI_ID: "ABADDON"}
        if kind == "고스톱":
            players[AI_ID_2] = "ABADDON-β"
        lobby = _AILobby(bot, kind, int(ctx.author.id), int(bet), get_user, save_data, world_data, user_data, message, channel_id, public_locale, players)
        session = factory(lobby)  # type: ignore[arg-type]
        ACTIVE_GAMES[channel_id] = session
        try:
            await session.start()
        except Exception:
            ACTIVE_GAMES.pop(channel_id, None)
            if isinstance(session, DebtCardSession):
                try:
                    session._refund_debt()
                except Exception:
                    pass
            raise

    def normalize_game_name(value: str) -> Optional[str]:
        token = re.sub(r"[\s_-]+", "", str(value).casefold())
        aliases = {
            "카드블랙잭": "블랙잭", "blackjacktable": "블랙잭", "cardblackjack": "블랙잭",
            "카드바카라": "바카라", "baccarattable": "바카라", "cardbaccarat": "바카라",
            "seotda": "섯다", "sutda": "섯다", "gostop": "고스톱", "matgo": "맞고",
        }
        if token in aliases:
            return aliases[token]
        for game in AUTHENTIC_GAMES:
            if token in {re.sub(r"[\s_-]+", "", game.casefold()), re.sub(r"[\s_-]+", "", GAME_EN.get(game, game).casefold())}:
                return game
        return None

    def parse_wager(first: str, second: int = 0) -> Tuple[str, int]:
        raw = str(first or "0").strip().replace(",", "")
        currency_aliases = {"칩": "chips", "chip": "chips", "chips": "chips", "식량": "food", "food": "food", "탄약": "ammo", "ammo": "ammo"}
        if raw.casefold() in currency_aliases:
            return currency_aliases[raw.casefold()], max(0, int(second or 0))
        try:
            return "chips", max(0, int(raw))
        except ValueError:
            return "chips", max(0, int(second or 0))

    class DirectAIBetModal(discord.ui.Modal):
        def __init__(self, kind: str, locale: str) -> None:
            super().__init__(title=_t(locale, f"{kind} · 아바돈 대전", f"{_display(kind, locale)} · ABADDON")); self.kind = kind; self.locale = locale
            self.amount = discord.ui.TextInput(label=_t(locale, "기준 판돈", "Base stake"), placeholder=str(MIN_BET), min_length=1, max_length=100)
            self.add_item(self.amount)
        async def on_submit(self, interaction: discord.Interaction) -> None:
            try:
                amount = int(str(self.amount.value).replace(",", ""))
            except ValueError:
                await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True); return
            await authentic_ai_starter(interaction, self.kind, amount)

    class AuthenticAISelect(discord.ui.Select):
        def __init__(self, locale: str, currency: str, amount: int) -> None:
            self.locale, self.currency, self.amount = locale, currency, int(amount)
            mini = [("rps", "가위바위보", "Rock Paper Scissors", "✊"), ("odd", "홀짝", "Odd or Even", "🎲"), ("number", "숫자결투", "Number Duel", "🔢"), ("signal", "신호예측", "Signal Prediction", "📡")]
            options = [discord.SelectOption(label=(ko if locale == "ko" else en), value=f"mini:{key}", emoji=emoji) for key, ko, en, emoji in mini]
            options.extend(discord.SelectOption(label=_display(kind, locale), value=f"card:{kind}", emoji=GAME_EMOJI.get(kind, "🃏"), description=GAME_RULE_SUMMARY[kind][0 if locale == "ko" else 1][:100]) for kind in AUTHENTIC_GAMES)
            super().__init__(placeholder=_t(locale, "아바돈과 할 게임 선택", "Choose a game with ABADDON"), min_values=1, max_values=1, options=options)
        async def callback(self, interaction: discord.Interaction) -> None:
            group, value = self.values[0].split(":", 1)
            if group == "card":
                if self.currency != "chips":
                    await interaction.response.send_message(_t(self.locale, "카드게임은 칩을 사용합니다.", "Card games use chips."), ephemeral=True); return
                if self.amount < MIN_BET:
                    await interaction.response.send_modal(DirectAIBetModal(value, self.locale)); return
                await authentic_ai_starter(interaction, value, self.amount); return
            if not callable(previous_ai_game):
                await interaction.response.send_message(_t(self.locale, "미니게임 AI 모듈을 찾지 못했습니다.", "The mini-game AI module is unavailable."), ephemeral=True); return
            await previous_ai_game(interaction, value, self.amount, currency=self.currency, replace_message=True)

    class AuthenticAIMenu(discord.ui.View):
        def __init__(self, locale: str, currency: str, amount: int) -> None:
            super().__init__(timeout=180); self.add_item(AuthenticAISelect(locale, currency, amount))

    bot.v720_start_ai_card = authentic_ai_starter  # type: ignore[attr-defined]
    bot.v1050_start_ai_card = authentic_ai_starter  # type: ignore[attr-defined]
    bot.v1060_start_ai_card = authentic_ai_starter  # type: ignore[attr-defined]

    ai_menu_command = bot.get_command("아바돈게임")
    if ai_menu_command is not None:
        async def authentic_ai_menu(ctx: commands.Context, 재화또는금액: str = "0", 금액: int = 0) -> None:
            if not await check_registered(ctx):
                return
            locale = _ctx_locale(bot, ctx); currency, amount = parse_wager(재화또는금액, 금액)
            embed = discord.Embed(
                title=_t(locale, "🤖 아바돈 실전 게임", "🤖 Authentic Games with ABADDON"),
                description=_t(locale, "미니게임 4종과 실전 카드게임 16종을 선택합니다. 카드게임은 자동 비교 없이 실제 턴·베팅·선택으로 진행됩니다.", "Choose four quick mini-games or 16 authentic card modes. Card games use real turns, betting and choices instead of instant comparison."),
                color=discord.Color.purple(),
            )
            embed.add_field(name=_t(locale, "카드 경제", "Card Economy"), value=_t(locale, "잔액 음수 허용 · 자유 레이즈 안전 한도 · 배수/정산 상한 없음", "Negative balances · free-raise safety limit · uncapped multipliers/settlement"), inline=False)
            await ctx.send(embed=embed, view=AuthenticAIMenu(locale, currency, amount))
        ai_menu_command.callback = authentic_ai_menu

    invite_command = bot.get_command("아바돈초대")
    if invite_command is not None:
        old_invite_callback = invite_command.callback
        async def authentic_invite(ctx: commands.Context, 게임: str = "포커", 재화또는금액: str = "0", 금액: int = 0) -> None:
            kind = normalize_game_name(게임)
            if kind is None:
                await old_invite_callback(ctx, 게임, 재화또는금액, 금액)
                return
            currency, amount = parse_wager(재화또는금액, 금액)
            locale = _ctx_locale(bot, ctx)
            if currency != "chips":
                await ctx.send(_t(locale, "카드게임은 칩을 사용합니다.", "Card games use chips.")); return
            await start_ai_ctx(ctx, kind, amount if amount >= MIN_BET else MIN_BET)
        invite_command.callback = authentic_invite

    menu_command = bot.get_command("카드게임")
    if menu_command is not None:
        async def authentic_menu(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, f"🃏 ABADDON 실전 카드게임 {len(AUTHENTIC_GAMES)}종", f"🃏 ABADDON Authentic Card Games · {len(AUTHENTIC_GAMES)} Modes"), description=_t(locale, "자동 패 비교를 폐기했습니다. 각 게임의 턴·선택·베팅·공개 단계를 직접 진행합니다. 혼자면 아바돈을 초대할 수 있습니다.", "Automatic hand comparison has been removed. Play each game's turns, choices, betting streets and reveals. Invite ABADDON when alone."), color=discord.Color.dark_purple())
            embed.add_field(name=_t(locale, "경제 규칙", "Economy"), value=_t(locale, "잔액 음수 허용 · 자유 레이즈 안전 한도 · 배수 상한 없음 · 파산신청 연계", "Negative balances · free-raise safety limit · uncapped multipliers · bankruptcy remains available"), inline=False)
            embed.add_field(name=_t(locale, "신규", "New"), value=_t(locale, "섯다 · 실제 고스톱/맞고 턴 엔진 · 전 포커 거리별 베팅", "Seotda · true Go-Stop/Matgo turns · street betting across poker modes"), inline=False)
            await ctx.send(embed=embed, view=AuthenticGameMenu(create_lobby_interaction, locale))
        menu_command.callback = authentic_menu

    # Rebind all existing direct entries to the authentic lobby.
    command_map = {
        "포커": "포커", "텍사스홀덤": "텍사스홀덤", "오마하홀덤": "오마하홀덤", "세븐카드스터드": "세븐카드스터드",
        "파인애플홀덤": "파인애플홀덤", "숏덱홀덤": "숏덱홀덤", "바둑이": "바둑이", "하이로우포커": "하이로우포커",
        "인디언포커": "인디언포커", "카드블랙잭": "블랙잭", "카드바카라": "바카라", "맞고": "맞고", "고스톱": "고스톱",
        "원카드": "원카드", "조커잡기": "조커잡기",
    }
    for command_name, kind in command_map.items():
        command = bot.get_command(command_name)
        if command is None: continue
        async def rebound(ctx: commands.Context, 참가비: int = MIN_BET, _kind: str = kind) -> None: await create_lobby_ctx(ctx, _kind, 참가비)
        command.callback = rebound

    @bot.command(name="섯다", aliases=["seotda", "sutda", "seotdagame"])
    async def seotda_command(ctx: commands.Context, 참가비: int = MIN_BET) -> None: await create_lobby_ctx(ctx, "섯다", 참가비)

    @bot.command(name="카드게임룰", aliases=["cardrules", "cardgamerules"])
    async def card_rules(ctx: commands.Context, *, 게임: str = "") -> None:
        locale = _ctx_locale(bot, ctx); token = re.sub(r"[\s_-]+", "", 게임.casefold())
        found = next((kind for kind in AUTHENTIC_GAMES if token in {re.sub(r'[\s_-]+', '', kind.casefold()), re.sub(r'[\s_-]+', '', GAME_EN.get(kind, kind).casefold())}), None)
        if found:
            await ctx.send(embed=discord.Embed(title=f"{GAME_EMOJI.get(found, '🃏')} {_display(found, locale)}", description=GAME_RULE_SUMMARY[found][0 if locale == "ko" else 1], color=discord.Color.dark_purple())); return
        rows = [f"{GAME_EMOJI.get(kind, '🃏')} **{_display(kind, locale)}** · {GAME_RULE_SUMMARY[kind][0 if locale == 'ko' else 1]}" for kind in AUTHENTIC_GAMES]
        await ctx.send(embed=discord.Embed(title=_t(locale, "📚 카드게임 실전 규칙", "📚 Authentic Card Rules"), description="\n".join(rows), color=discord.Color.dark_purple()))

    @bot.command(name="게임진행검수", aliases=["gameplayaudit", "cardflowaudit"])
    async def gameplay_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        checks = [
            (_t(locale, "카드게임 16종", "16 card modes"), len(AUTHENTIC_GAMES) == 16),
            (_t(locale, "섯다 등록", "Seotda registered"), bot.get_command("섯다") is not None),
            (_t(locale, "실전 고스톱 엔진", "Authentic Go-Stop engine"), GoStopEngine is not None),
            (_t(locale, "자유 레이즈 빚 베팅", "Free-raise debt betting"), DebtBettingRound is not None),
            (_t(locale, "잔액 음수 저장", "Negative wallet storage"), casino_chips({"black_casino": {"chips": -1}}) <= 0),
            (_t(locale, "아바돈 실전 세션", "Authentic ABADDON sessions"), callable(getattr(bot, "v1060_start_ai_card", None))),
        ]
        embed = discord.Embed(title=_t(locale, "🧪 v10.6 실전 게임 검수", "🧪 v10.6 Gameplay Audit"), color=discord.Color.green() if all(ok for _, ok in checks) else discord.Color.orange())
        for label, ok in checks: embed.add_field(name=("✅ " if ok else "❌ ") + label, value=_t(locale, "정상", "PASS") if ok else _t(locale, "확인 필요", "REVIEW"), inline=True)
        await ctx.send(embed=embed)

    guide[:] = [row for row in guide if row.get("id") != "v1060_authentic_cards"]
    guide.append({"id": "v1060_authentic_cards", "emoji": "🎴", "title": "v10.6 실전 카드게임·무제한 부채", "hint": "자동 비교 폐기 · 턴/베팅/선택 실전 진행 · 섯다 · 음수/무상한", "commands": ["!카드게임 · !카드게임룰 · !게임진행검수", "!섯다 · !맞고 · !고스톱", "!포커 · !텍사스홀덤 · !오마하홀덤 · !세븐카드스터드", "!파인애플홀덤 · !숏덱홀덤 · !바둑이 · !하이로우포커 · !인디언포커", "!카드블랙잭 · !카드바카라 · !원카드 · !조커잡기"]})
    bot.v1060_version = VERSION  # type: ignore[attr-defined]
    bot.v1060_card_games = AUTHENTIC_GAMES  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] authentic_card_games={len(AUTHENTIC_GAMES)} debt=enabled caps=none seotda=enabled", flush=True)
