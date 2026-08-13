from __future__ import annotations

"""Pure rules for ABADDON v10.5.1 authentic card-game hotfix.

No discord.py dependency.  The audit suite imports this module directly to test
betting, Baccarat third-card logic, Seotda rankings, debt settlement and
Go-Stop capture rules.
"""

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

VERSION = "10.6.0"
Card = Tuple[int, str]


# ---------------------------------------------------------------------------
# Debt / wagering
# ---------------------------------------------------------------------------
def validate_unbounded_wager(amount: int, minimum: int = 10_000) -> Optional[str]:
    amount = int(amount)
    if amount < int(minimum):
        return f"최소 참가비는 **{int(minimum):,}칩**입니다."
    return None


def uncapped_extra_payment(bet: int, multiplier: int) -> int:
    """Return the full extra payment. Balances are intentionally allowed below 0."""
    return max(0, int(bet)) * max(0, int(multiplier) - 1)


@dataclass
class BettingRound:
    """Small no-limit betting state used by multiplayer and AI sessions.

    `stacks` are table stacks already reserved from wallets.  This state never
    checks a wallet balance and therefore naturally supports negative wallet
    balances when the table stake was reserved.
    """

    order: List[int]
    stacks: Dict[int, int]
    current_index: int = 0
    current_bet: int = 0
    min_raise: int = 1
    round_bets: Dict[int, int] = field(default_factory=dict)
    committed: Dict[int, int] = field(default_factory=dict)
    folded: set[int] = field(default_factory=set)
    all_in: set[int] = field(default_factory=set)
    acted: set[int] = field(default_factory=set)
    last_raiser: Optional[int] = None

    def __post_init__(self) -> None:
        self.order = [int(uid) for uid in self.order]
        self.stacks = {int(uid): max(0, int(value)) for uid, value in self.stacks.items()}
        self.round_bets = {uid: int(self.round_bets.get(uid, 0)) for uid in self.order}
        self.committed = {uid: int(self.committed.get(uid, 0)) for uid in self.order}
        self.current_index %= max(1, len(self.order))
        self.min_raise = max(1, int(self.min_raise))

    @property
    def active(self) -> List[int]:
        return [uid for uid in self.order if uid not in self.folded]

    @property
    def actionable(self) -> List[int]:
        return [uid for uid in self.order if uid not in self.folded and uid not in self.all_in]

    @property
    def current_uid(self) -> Optional[int]:
        if len(self.active) <= 1:
            return None
        for offset in range(len(self.order)):
            idx = (self.current_index + offset) % len(self.order)
            uid = self.order[idx]
            if uid not in self.folded and uid not in self.all_in:
                self.current_index = idx
                return uid
        return None

    def to_call(self, uid: int) -> int:
        return max(0, int(self.current_bet) - int(self.round_bets.get(int(uid), 0)))

    def _put(self, uid: int, amount: int) -> int:
        uid = int(uid)
        amount = max(0, min(int(amount), int(self.stacks.get(uid, 0))))
        self.stacks[uid] -= amount
        self.round_bets[uid] = int(self.round_bets.get(uid, 0)) + amount
        self.committed[uid] = int(self.committed.get(uid, 0)) + amount
        if self.stacks[uid] == 0:
            self.all_in.add(uid)
        return amount

    def post(self, uid: int, amount: int) -> int:
        paid = self._put(uid, amount)
        self.current_bet = max(self.current_bet, self.round_bets[int(uid)])
        return paid

    def check_or_call(self, uid: int) -> Tuple[str, int]:
        uid = int(uid)
        need = self.to_call(uid)
        paid = self._put(uid, need)
        self.acted.add(uid)
        self._advance()
        return ("check" if need == 0 else ("all_in_call" if paid < need else "call"), paid)

    def raise_to(self, uid: int, target_total: int) -> Tuple[str, int]:
        uid = int(uid)
        before = int(self.round_bets.get(uid, 0))
        max_total = before + int(self.stacks.get(uid, 0))
        target_total = min(int(target_total), max_total)
        if target_total <= self.current_bet and max_total > self.current_bet:
            raise ValueError("raise target must exceed current bet")
        if target_total > self.current_bet:
            raise_size = target_total - self.current_bet
            if raise_size < self.min_raise and target_total != max_total:
                raise ValueError("raise is smaller than minimum raise")
            self.min_raise = max(self.min_raise, raise_size)
            self.current_bet = target_total
            self.last_raiser = uid
            self.acted = {uid}
        else:
            self.acted.add(uid)
        paid = self._put(uid, target_total - before)
        self._advance()
        return ("all_in" if uid in self.all_in else "raise", paid)

    def fold(self, uid: int) -> None:
        uid = int(uid)
        self.folded.add(uid)
        self.acted.add(uid)
        self._advance()

    def _advance(self) -> None:
        if not self.order:
            return
        self.current_index = (self.current_index + 1) % len(self.order)

    def complete(self) -> bool:
        if len(self.active) <= 1:
            return True
        for uid in self.actionable:
            if uid not in self.acted:
                return False
            if int(self.round_bets.get(uid, 0)) != int(self.current_bet):
                return False
        return True

    def reset_for_next_street(self, first_index: int = 0, min_raise: Optional[int] = None) -> None:
        self.current_bet = 0
        self.round_bets = {uid: 0 for uid in self.order}
        self.acted.clear()
        self.last_raiser = None
        self.current_index = int(first_index) % max(1, len(self.order))
        if min_raise is not None:
            self.min_raise = max(1, int(min_raise))

    @property
    def pot(self) -> int:
        return sum(int(v) for v in self.committed.values())



@dataclass
class DebtBettingRound:
    """No-limit betting round where every player may continue into debt.

    Unlike :class:`BettingRound`, this model has no stack or all-in limit.  The
    caller applies each returned payment directly to the persistent wallet, so
    a losing balance may become negative by design.
    """

    order: List[int]
    current_index: int = 0
    current_bet: int = 0
    min_raise: int = 1
    round_bets: Dict[int, int] = field(default_factory=dict)
    committed: Dict[int, int] = field(default_factory=dict)
    folded: set[int] = field(default_factory=set)
    acted: set[int] = field(default_factory=set)
    last_raiser: Optional[int] = None

    def __post_init__(self) -> None:
        self.order = [int(uid) for uid in self.order]
        self.round_bets = {uid: max(0, int(self.round_bets.get(uid, 0))) for uid in self.order}
        self.committed = {uid: max(0, int(self.committed.get(uid, 0))) for uid in self.order}
        self.current_index %= max(1, len(self.order))
        self.min_raise = max(1, int(self.min_raise))

    @property
    def active(self) -> List[int]:
        return [uid for uid in self.order if uid not in self.folded]

    @property
    def current_uid(self) -> Optional[int]:
        if len(self.active) <= 1:
            return None
        for offset in range(len(self.order)):
            idx = (self.current_index + offset) % len(self.order)
            uid = self.order[idx]
            if uid not in self.folded:
                self.current_index = idx
                return uid
        return None

    def to_call(self, uid: int) -> int:
        return max(0, int(self.current_bet) - int(self.round_bets.get(int(uid), 0)))

    def _put(self, uid: int, amount: int) -> int:
        uid = int(uid)
        paid = max(0, int(amount))
        self.round_bets[uid] = int(self.round_bets.get(uid, 0)) + paid
        self.committed[uid] = int(self.committed.get(uid, 0)) + paid
        return paid

    def post(self, uid: int, amount: int) -> int:
        """Post an ante or blind without marking the player as acted."""
        paid = self._put(int(uid), amount)
        self.current_bet = max(self.current_bet, int(self.round_bets.get(int(uid), 0)))
        return paid

    def check_or_call(self, uid: int) -> Tuple[str, int]:
        uid = int(uid)
        need = self.to_call(uid)
        paid = self._put(uid, need)
        self.acted.add(uid)
        self._advance()
        return ("check" if need == 0 else "call", paid)

    def raise_to(self, uid: int, target_total: int) -> Tuple[str, int]:
        uid = int(uid)
        before = int(self.round_bets.get(uid, 0))
        target_total = int(target_total)
        if target_total <= self.current_bet:
            raise ValueError("raise target must exceed current bet")
        raise_size = target_total - self.current_bet
        if raise_size < self.min_raise:
            raise ValueError("raise is smaller than minimum raise")
        paid = self._put(uid, target_total - before)
        self.min_raise = raise_size
        self.current_bet = target_total
        self.last_raiser = uid
        self.acted = {uid}
        self._advance()
        return "raise", paid

    def fold(self, uid: int) -> None:
        uid = int(uid)
        self.folded.add(uid)
        self.acted.add(uid)
        self._advance()

    def _advance(self) -> None:
        if self.order:
            self.current_index = (self.current_index + 1) % len(self.order)

    def complete(self) -> bool:
        if len(self.active) <= 1:
            return True
        return all(uid in self.acted and int(self.round_bets.get(uid, 0)) == int(self.current_bet) for uid in self.active)

    def reset_for_next_street(self, first_index: int = 0, min_raise: Optional[int] = None) -> None:
        self.current_bet = 0
        self.round_bets = {uid: 0 for uid in self.order}
        self.acted.clear()
        self.last_raiser = None
        self.current_index = int(first_index) % max(1, len(self.order))
        if min_raise is not None:
            self.min_raise = max(1, int(min_raise))

    @property
    def pot(self) -> int:
        return sum(int(value) for value in self.committed.values())

def side_pots(committed: Mapping[int, int], eligible: Iterable[int]) -> List[Tuple[int, List[int]]]:
    """Build side pots as (amount, eligible winners) from total commitments."""
    remaining = {int(uid): max(0, int(amount)) for uid, amount in committed.items() if int(amount) > 0}
    live = {int(uid) for uid in eligible}
    pots: List[Tuple[int, List[int]]] = []
    while remaining:
        level = min(remaining.values())
        contributors = list(remaining)
        amount = level * len(contributors)
        pot_eligible = [uid for uid in contributors if uid in live]
        pots.append((amount, pot_eligible))
        next_remaining: Dict[int, int] = {}
        for uid, value in remaining.items():
            left = value - level
            if left > 0:
                next_remaining[uid] = left
        remaining = next_remaining
    return pots


# ---------------------------------------------------------------------------
# Baccarat
# ---------------------------------------------------------------------------
def baccarat_card_value(rank: int) -> int:
    rank = int(rank)
    if rank == 14:
        return 1
    if rank >= 10:
        return 0
    return rank


def baccarat_total(cards: Sequence[Card]) -> int:
    return sum(baccarat_card_value(rank) for rank, _ in cards) % 10


def baccarat_deal(deck: List[Card]) -> Tuple[List[Card], List[Card]]:
    """Deal Player/Banker using standard punto banco third-card rules."""
    player = [deck.pop(), deck.pop()]
    banker = [deck.pop(), deck.pop()]
    p_total, b_total = baccarat_total(player), baccarat_total(banker)
    if p_total in {8, 9} or b_total in {8, 9}:
        return player, banker

    p_third_value: Optional[int] = None
    if p_total <= 5:
        card = deck.pop()
        player.append(card)
        p_third_value = baccarat_card_value(card[0])

    b_total = baccarat_total(banker)
    draw_banker = False
    if p_third_value is None:
        draw_banker = b_total <= 5
    elif b_total <= 2:
        draw_banker = True
    elif b_total == 3:
        draw_banker = p_third_value != 8
    elif b_total == 4:
        draw_banker = 2 <= p_third_value <= 7
    elif b_total == 5:
        draw_banker = 4 <= p_third_value <= 7
    elif b_total == 6:
        draw_banker = 6 <= p_third_value <= 7
    if draw_banker:
        banker.append(deck.pop())
    return player, banker


def baccarat_outcome(player: Sequence[Card], banker: Sequence[Card]) -> str:
    p, b = baccarat_total(player), baccarat_total(banker)
    return "player" if p > b else ("banker" if b > p else "tie")


def baccarat_return(stake: int, choice: str, outcome: str) -> int:
    stake = max(0, int(stake))
    if choice != outcome:
        return 0
    if outcome == "tie":
        return stake * 9  # 8:1 plus returned stake
    if outcome == "banker":
        return (stake * 195) // 100  # 0.95:1 plus returned stake
    return stake * 2


# ---------------------------------------------------------------------------
# Seotda
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeotdaCard:
    month: int
    kind: str  # bright | animal | ribbon
    label: str


def seotda_deck() -> List[SeotdaCard]:
    """Return the standard 20-card Seotda deck (two non-junk cards per month 1-10)."""
    # Kind details matter for 1/3/8 brights, 4/7 special animal cards and 4/9 meong-gu-sa.
    rows: Dict[int, Tuple[Tuple[str, str], Tuple[str, str]]] = {
        1: (("bright", "1광"), ("ribbon", "1띠")),
        2: (("animal", "2열"), ("ribbon", "2띠")),
        3: (("bright", "3광"), ("ribbon", "3띠")),
        4: (("animal", "4열"), ("ribbon", "4띠")),
        5: (("animal", "5열"), ("ribbon", "5띠")),
        6: (("animal", "6열"), ("ribbon", "6띠")),
        7: (("animal", "7열"), ("ribbon", "7띠")),
        8: (("bright", "8광"), ("animal", "8열")),
        9: (("animal", "9열"), ("ribbon", "9띠")),
        10: (("animal", "장열"), ("ribbon", "장띠")),
    }
    return [SeotdaCard(month, kind, label) for month, pair in rows.items() for kind, label in pair]


@dataclass(frozen=True)
class SeotdaRank:
    category: int
    tiebreak: int
    name: str
    special: str = ""

    @property
    def key(self) -> Tuple[int, int]:
        return self.category, self.tiebreak


def seotda_rank(cards: Sequence[SeotdaCard]) -> SeotdaRank:
    if len(cards) != 2:
        raise ValueError("Seotda uses exactly two cards")
    a, b = cards
    months = tuple(sorted((int(a.month), int(b.month))))
    bright_months = {card.month for card in cards if card.kind == "bright"}
    animal_months = {card.month for card in cards if card.kind == "animal"}

    if months == (3, 8) and bright_months == {3, 8}:
        return SeotdaRank(100, 38, "삼팔광땡")
    if months in {(1, 3), (1, 8)} and len(bright_months) == 2:
        return SeotdaRank(99, months[1], "일삼광땡" if months == (1, 3) else "일팔광땡")
    if a.month == b.month:
        return SeotdaRank(90, int(a.month), "장땡" if a.month == 10 else f"{a.month}땡")
    specials = {
        (1, 2): (80, "알리"),
        (1, 4): (79, "독사"),
        (1, 9): (78, "구삥"),
        (1, 10): (77, "장삥"),
        (4, 10): (76, "장사"),
        (4, 6): (75, "세륙"),
    }
    if months in specials:
        score, name = specials[months]
        return SeotdaRank(score, 0, name)
    if months == (3, 7):
        return SeotdaRank(20, 0, "땡잡이", "ddang_catcher")
    if months == (4, 7) and animal_months == {4, 7}:
        return SeotdaRank(19, 0, "암행어사", "secret_inspector")
    if months == (4, 9):
        if animal_months == {4, 9}:
            return SeotdaRank(18, 0, "멍텅구리 구사", "meong_gusa")
        return SeotdaRank(17, 0, "구사", "gusa")
    points = (a.month + b.month) % 10
    if points == 9:
        return SeotdaRank(70, 9, "갑오")
    if points == 0:
        return SeotdaRank(60, 0, "망통")
    return SeotdaRank(60, points, f"{points}끗")


def resolve_seotda(hands: Mapping[int, Sequence[SeotdaCard]]) -> Tuple[str, List[int], Dict[int, SeotdaRank]]:
    """Resolve special catches/redeals and return (status, winners, ranks)."""
    ranks = {int(uid): seotda_rank(cards) for uid, cards in hands.items()}
    normal = sorted(ranks, key=lambda uid: ranks[uid].key, reverse=True)
    top_uid = normal[0]
    top = ranks[top_uid]

    # Secret inspector defeats 13/18 bright ddang, otherwise counts as 1 point.
    inspectors = [uid for uid, rank in ranks.items() if rank.special == "secret_inspector"]
    if top.name in {"일삼광땡", "일팔광땡"} and inspectors:
        return "win", inspectors, ranks

    # Ddang catcher defeats 1-9 ddang, but not 10-ddang or bright ddang.
    catchers = [uid for uid, rank in ranks.items() if rank.special == "ddang_catcher"]
    if top.category == 90 and top.tiebreak <= 9 and catchers:
        return "win", catchers, ranks

    # Meong-gusa can redeal against anything up to 9-ddang; gusa against Ali or lower.
    meong = [uid for uid, rank in ranks.items() if rank.special == "meong_gusa"]
    if meong and ((top.category < 90) or (top.category == 90 and top.tiebreak <= 9)):
        return "redeal", meong, ranks
    gusa = [uid for uid, rank in ranks.items() if rank.special == "gusa"]
    if gusa and top.category <= 80:
        return "redeal", gusa, ranks

    best_key = max(rank.key for rank in ranks.values())
    winners = [uid for uid, rank in ranks.items() if rank.key == best_key]
    return "win", winners, ranks


# ---------------------------------------------------------------------------
# Poker low helper
# ---------------------------------------------------------------------------
def ace_to_five_low_eight_or_better(cards: Sequence[Card]) -> Optional[Tuple[int, ...]]:
    best: Optional[Tuple[int, ...]] = None
    for combo in combinations(cards, 5):
        ranks = [1 if rank == 14 else int(rank) for rank, _ in combo]
        if len(set(ranks)) != 5 or max(ranks) > 8:
            continue
        key = tuple(sorted(ranks, reverse=True))
        if best is None or key < best:
            best = key
    return best


# ---------------------------------------------------------------------------
# Go-Stop pure engine
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HwatuCardLite:
    uid: int
    month: int
    category: str
    name: str
    junk: int = 0


@dataclass
class HwatuTurnResult:
    played: List[HwatuCardLite] = field(default_factory=list)
    flipped: Optional[HwatuCardLite] = None
    captured: List[HwatuCardLite] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    needs_choice: Optional[Tuple[str, List[int]]] = None


class GoStopEngine:
    """Turn engine for standard 2/3-player Go-Stop without jokers.

    Floor cards are kept as a flat list; a three-card month naturally behaves as
    the ppuk stack.  Ambiguous two-card matches are returned to the UI as a
    pending choice instead of being selected randomly.
    """

    def __init__(self, player_ids: Sequence[int], cards: Sequence[HwatuCardLite], *, matgo: bool = False) -> None:
        if len(player_ids) not in {2, 3}:
            raise ValueError("Go-Stop supports two or three active players")
        self.players = [int(uid) for uid in player_ids]
        self.matgo = bool(matgo)
        self.hands: Dict[int, List[HwatuCardLite]] = {uid: [] for uid in self.players}
        self.floor: List[HwatuCardLite] = []
        self.stock: List[HwatuCardLite] = list(cards)
        self.captured: Dict[int, List[HwatuCardLite]] = {uid: [] for uid in self.players}
        self.turn_index = 0
        self.skip_credits: Dict[int, int] = {uid: 0 for uid in self.players}
        self.shakes: Dict[int, int] = {uid: 0 for uid in self.players}
        self.shaken_months: Dict[int, set[int]] = {uid: set() for uid in self.players}
        self.bombs: Dict[int, int] = {uid: 0 for uid in self.players}
        self.ppuk_count: Dict[int, int] = {uid: 0 for uid in self.players}
        self.side_events_enabled = True
        self._deal()

    @property
    def current_uid(self) -> int:
        return self.players[self.turn_index % len(self.players)]

    def _deal(self) -> None:
        hand_size = 10 if self.matgo else 7
        floor_size = 8 if self.matgo else 6
        attempts = 0
        original = list(self.stock)
        import random
        while True:
            attempts += 1
            deck = list(original)
            random.shuffle(deck)
            hands = {uid: [] for uid in self.players}
            for _ in range(hand_size):
                for uid in self.players:
                    hands[uid].append(deck.pop())
            floor = [deck.pop() for _ in range(floor_size)]
            if max(Counter(card.month for card in floor).values(), default=0) < 4:
                self.hands, self.floor, self.stock = hands, floor, deck
                return
            if attempts >= 100:
                raise RuntimeError("could not produce a legal Go-Stop deal")

    def chongtong_winners(self) -> List[int]:
        return [uid for uid, hand in self.hands.items() if any(v == 4 for v in Counter(c.month for c in hand).values())]

    def matching_floor_indices(self, month: int) -> List[int]:
        return [idx for idx, card in enumerate(self.floor) if card.month == int(month)]

    def can_shake(self, uid: int) -> List[int]:
        uid = int(uid)
        declared = self.shaken_months.setdefault(uid, set())
        return [month for month, count in Counter(card.month for card in self.hands[uid]).items() if count >= 3 and month not in declared]

    def declare_shake(self, uid: int, month: int) -> bool:
        uid = int(uid)
        if month not in self.can_shake(uid):
            return False
        self.shakes[uid] += 1
        self.shaken_months.setdefault(uid, set()).add(int(month))
        return True

    def can_bomb(self, uid: int) -> List[int]:
        uid = int(uid)
        hand_counts = Counter(card.month for card in self.hands[uid])
        floor_counts = Counter(card.month for card in self.floor)
        return [month for month, count in hand_counts.items() if count >= 3 and floor_counts.get(month, 0) == 1]

    def play_bomb(
        self, uid: int, month: int, *, flip_match_index: Optional[int] = None
    ) -> HwatuTurnResult:
        """Play a bomb while preserving an explicit ambiguous floor choice.

        The operation is transactional. If the stock flip can match either of
        two floor cards, state is restored and the UI receives ``bomb_flip``
        choices instead of silently selecting one.
        """
        uid = int(uid)
        if uid != self.current_uid or month not in self.can_bomb(uid):
            raise ValueError("illegal bomb")
        import copy
        snapshot = (
            copy.deepcopy(self.hands), copy.deepcopy(self.floor), copy.deepcopy(self.stock),
            copy.deepcopy(self.captured), dict(self.skip_credits), dict(self.shakes),
            dict(self.bombs), dict(self.ppuk_count), self.turn_index,
        )
        result = HwatuTurnResult(events=["폭탄"])
        selected = [card for card in self.hands[uid] if card.month == month][:3]
        for card in selected:
            self.hands[uid].remove(card)
        floor_card = next(card for card in self.floor if card.month == month)
        self.floor.remove(floor_card)
        result.played.extend(selected)
        result.captured.extend(selected + [floor_card])
        self.captured[uid].extend(result.captured)
        self.bombs[uid] += 1
        self.skip_credits[uid] += 2
        pending = self._flip_and_resolve(uid, result, flip_match_index=flip_match_index)
        if pending is not None:
            (
                self.hands, self.floor, self.stock, self.captured, self.skip_credits,
                self.shakes, self.bombs, self.ppuk_count, self.turn_index,
            ) = snapshot
            result.needs_choice = ("bomb_flip", pending)
            return result
        self._finalize_events(uid, result)
        self.advance_turn()
        return result

    def play(
        self,
        uid: int,
        hand_index: Optional[int],
        *,
        match_index: Optional[int] = None,
        flip_match_index: Optional[int] = None,
        skip: bool = False,
    ) -> HwatuTurnResult:
        uid = int(uid)
        if uid != self.current_uid:
            raise ValueError("not this player's turn")
        import copy
        snapshot = (
            copy.deepcopy(self.hands), copy.deepcopy(self.floor), copy.deepcopy(self.stock),
            copy.deepcopy(self.captured), dict(self.skip_credits), dict(self.ppuk_count), self.turn_index,
        )
        result = HwatuTurnResult()
        if skip:
            if self.skip_credits[uid] <= 0:
                raise ValueError("no bomb skip credit")
            self.skip_credits[uid] -= 1
            result.events.append("폭탄 보너스 뒤집기")
            pending = self._flip_and_resolve(uid, result, flip_match_index=flip_match_index)
            if pending is not None:
                self.hands, self.floor, self.stock, self.captured, self.skip_credits, self.ppuk_count, self.turn_index = snapshot
                result.needs_choice = ("flip", pending)
                return result
            self._finalize_events(uid, result)
            self.advance_turn()
            return result
        if hand_index is None or hand_index < 0 or hand_index >= len(self.hands[uid]):
            raise ValueError("invalid hand card")
        card = self.hands[uid][hand_index]
        matches = self.matching_floor_indices(card.month)
        if len(matches) == 2 and match_index is None:
            result.needs_choice = ("hand", matches)
            return result
        self.hands[uid].pop(hand_index)
        result.played.append(card)
        pending_pair: List[HwatuCardLite] = []
        play_was_unmatched = False
        play_captured_stack = False
        if len(matches) == 0:
            self.floor.append(card)
            play_was_unmatched = True
        elif len(matches) in {1, 2}:
            chosen = matches[0] if len(matches) == 1 else int(match_index)
            if chosen not in matches:
                raise ValueError("invalid floor choice")
            target = self.floor[chosen]
            self.floor.append(card)  # pair stays visible until stock card resolves
            pending_pair = [target, card]
        else:  # stack of three
            captured = [self.floor[idx] for idx in matches] + [card]
            for old in list(captured[:-1]):
                self.floor.remove(old)
            result.captured.extend(captured)
            play_captured_stack = True
            result.events.append("뻑 회수")

        if not self.stock:
            if pending_pair:
                self._capture_cards(uid, pending_pair, result)
            self._capture_cards(uid, result.captured, result, already_recorded=True)
            self._finalize_events(uid, result)
            self.advance_turn()
            return result

        flipped = self.stock.pop()
        result.flipped = flipped
        flip_matches = self.matching_floor_indices(flipped.month)
        # Pair made by played card is present in floor, so same-month flip sees 2 or 3 cards.
        if len(flip_matches) == 2 and flipped.month != card.month:
            if flip_match_index is None:
                self.hands, self.floor, self.stock, self.captured, self.skip_credits, self.ppuk_count, self.turn_index = snapshot
                result.needs_choice = ("flip", flip_matches)
                return result
            chosen = int(flip_match_index)
            if chosen not in flip_matches:
                raise ValueError("invalid flipped-card floor choice")
            target = self.floor.pop(chosen)
            self._capture_cards(uid, [flipped, target], result)
            if pending_pair:
                self._remove_floor_cards(pending_pair)
                self._capture_cards(uid, pending_pair, result)
        elif pending_pair and flipped.month == card.month:
            same = self.matching_floor_indices(card.month)
            if len(same) == 3:
                # Played into two singles and flipped fourth: ttadak.
                group = [self.floor[idx] for idx in same]
                self._remove_floor_cards(group)
                self._capture_cards(uid, group + [flipped], result)
                result.events.append("따닥")
            else:
                # Played onto one card and flipped the third: ppuk, capture nothing.
                self.floor.append(flipped)
                self.ppuk_count[uid] += 1
                result.events.append("뻑")
        else:
            if pending_pair:
                self._remove_floor_cards(pending_pair)
                self._capture_cards(uid, pending_pair, result)
            flip_matches = self.matching_floor_indices(flipped.month)
            if len(flip_matches) == 0:
                self.floor.append(flipped)
            elif len(flip_matches) in {1, 2}:
                target = self.floor[flip_matches[0]]
                self.floor.remove(target)
                self._capture_cards(uid, [flipped, target], result)
                if play_was_unmatched and flipped.month == card.month:
                    # played card is target in floor and is removed above
                    result.events.append("쪽")
            else:
                group = [self.floor[idx] for idx in flip_matches]
                self._remove_floor_cards(group)
                self._capture_cards(uid, group + [flipped], result)
                result.events.append("뻑 회수")

        if play_captured_stack:
            self._capture_cards(uid, result.captured, result, already_recorded=True)
        self._finalize_events(uid, result)
        self.advance_turn()
        return result

    def _remove_floor_cards(self, cards: Sequence[HwatuCardLite]) -> None:
        for card in cards:
            if card in self.floor:
                self.floor.remove(card)

    def _capture_cards(self, uid: int, cards: Sequence[HwatuCardLite], result: HwatuTurnResult, *, already_recorded: bool = False) -> None:
        if not cards:
            return
        if not already_recorded:
            result.captured.extend(cards)
        existing_ids = {card.uid for card in self.captured[uid]}
        for card in cards:
            if card.uid not in existing_ids:
                self.captured[uid].append(card)
                existing_ids.add(card.uid)

    def _flip_and_resolve(
        self, uid: int, result: HwatuTurnResult, *, flip_match_index: Optional[int] = None
    ) -> Optional[List[int]]:
        if not self.stock:
            return None
        flipped = self.stock.pop()
        result.flipped = flipped
        matches = self.matching_floor_indices(flipped.month)
        if not matches:
            self.floor.append(flipped)
        elif len(matches) in {1, 2}:
            if len(matches) == 2 and flip_match_index is None:
                return matches
            chosen = matches[0] if len(matches) == 1 else int(flip_match_index)
            if chosen not in matches:
                raise ValueError("invalid flipped-card floor choice")
            target = self.floor[chosen]
            self.floor.remove(target)
            self._capture_cards(uid, [flipped, target], result)
        else:
            group = [self.floor[idx] for idx in matches]
            self._remove_floor_cards(group)
            self._capture_cards(uid, group + [flipped], result)
            result.events.append("뻑 회수")
        return None

    def _finalize_events(self, uid: int, result: HwatuTurnResult) -> None:
        # Sseul only if the play actually captured and cleared the floor.
        if result.captured and not self.floor:
            result.events.append("쓸")
        if self.side_events_enabled and any(event in {"쪽", "따닥", "쓸", "뻑 회수", "폭탄"} for event in result.events):
            self.steal_junk(uid, 1)

    def steal_junk(self, winner: int, amount: int) -> None:
        winner = int(winner)
        for uid in self.players:
            if uid == winner:
                continue
            for _ in range(max(0, int(amount))):
                junk = [card for card in self.captured[uid] if card.junk > 0]
                if not junk:
                    break
                # Victim choice is automated: ordinary single junk first, then lowest value.
                card = sorted(junk, key=lambda c: (c.junk, c.month, c.uid))[0]
                self.captured[uid].remove(card)
                self.captured[winner].append(card)

    def advance_turn(self) -> None:
        self.turn_index = (self.turn_index + 1) % len(self.players)

    def exhausted(self) -> bool:
        return not self.stock or all(not hand for hand in self.hands.values())


def hwatu_payment_units(score: int, go_count: int) -> Tuple[int, int]:
    score = max(0, int(score))
    go_count = max(0, int(go_count))
    if go_count in {1, 2}:
        return score + go_count, 1
    if go_count >= 3:
        return score, 2 ** (go_count - 2)
    return score, 1
