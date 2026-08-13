from __future__ import annotations

"""Pure, Discord-free rules used by ABADDON v10.9.0.

The module intentionally contains no discord.py imports so the newest patch can
be audited offline with deterministic unit tests.
"""

from collections import Counter
from itertools import combinations
from typing import Iterable, List, Mapping, Sequence, Tuple

Card = Tuple[int, str]


def card_points(card: Card) -> int:
    rank, _ = card
    if rank == 14:
        return 15
    return 10 if rank >= 10 else int(rank)


def _ace_variants(ranks: Sequence[int]) -> List[List[int]]:
    base = sorted(int(v) for v in ranks)
    rows = [base]
    if 14 in base:
        rows.append(sorted(1 if value == 14 else value for value in base))
    return rows


def is_set(cards: Sequence[Card]) -> bool:
    """Rummy set: three/four cards of one rank with different suits."""
    return 3 <= len(cards) <= 4 and len({rank for rank, _ in cards}) == 1 and len({suit for _, suit in cards}) == len(cards)


def is_run(cards: Sequence[Card]) -> bool:
    """Rummy run: at least three unique consecutive ranks in one suit."""
    if len(cards) < 3 or len({suit for _, suit in cards}) != 1:
        return False
    ranks = [rank for rank, _ in cards]
    if len(set(ranks)) != len(ranks):
        return False
    return any(all(row[i] + 1 == row[i + 1] for i in range(len(row) - 1)) for row in _ace_variants(ranks))


def is_valid_meld(cards: Sequence[Card]) -> bool:
    return is_set(cards) or is_run(cards)


def meld_points(cards: Sequence[Card]) -> int:
    return sum(card_points(card) for card in cards)


def greedy_melds(hand: Sequence[Card]) -> List[List[int]]:
    """Find non-overlapping melds, preferring longer and higher-value groups."""
    remaining = set(range(len(hand)))
    candidates = []
    for size in range(min(7, len(hand)), 2, -1):
        for combo in combinations(range(len(hand)), size):
            cards = [hand[index] for index in combo]
            if is_valid_meld(cards):
                candidates.append((size, meld_points(cards), combo))
    candidates.sort(reverse=True)
    result: List[List[int]] = []
    for _size, _points, combo in candidates:
        if set(combo) <= remaining:
            result.append(list(combo))
            remaining.difference_update(combo)
    return result


PRESIDENT_ORDER = {rank: index for index, rank in enumerate(list(range(3, 15)) + [2])}


def president_strength(rank: int, revolution: bool = False) -> int:
    strength = PRESIDENT_ORDER[int(rank)]
    return -strength if revolution else strength


def president_play_valid(ranks: Sequence[int], current_rank: int | None, current_count: int, revolution: bool = False) -> bool:
    if not ranks or len(set(ranks)) != 1:
        return False
    if current_rank is None:
        return True
    if len(ranks) != int(current_count):
        return False
    return president_strength(ranks[0], revolution) > president_strength(current_rank, revolution)


def dice_card_score(cards: Sequence[Card], dice: Sequence[int]) -> Tuple[int, ...]:
    """Rank ABADDON's two-card plus three-dice five-symbol poker hand."""
    if len(cards) != 2 or len(dice) != 3:
        raise ValueError("two cards and three dice are required")
    ranks = [min(14, max(2, int(rank))) for rank, _ in cards] + [int(value) + 1 for value in dice]
    counts = Counter(ranks)
    ordered = sorted(counts.items(), key=lambda row: (row[1], row[0]), reverse=True)
    unique = sorted(set(ranks))
    straight = len(unique) == 5 and unique[-1] - unique[0] == 4
    if ordered[0][1] == 5:
        return (8, ordered[0][0])
    if ordered[0][1] == 4:
        return (7, ordered[0][0], ordered[1][0])
    if sorted(counts.values()) == [2, 3]:
        return (6, ordered[0][0], ordered[1][0])
    if straight:
        return (5, unique[-1])
    if ordered[0][1] == 3:
        kickers = sorted((rank for rank in ranks if rank != ordered[0][0]), reverse=True)
        return (4, ordered[0][0], *kickers)
    pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = max(rank for rank in ranks if rank not in pairs)
        return (3, pairs[0], pairs[1], kicker)
    if len(pairs) == 1:
        kickers = sorted((rank for rank in ranks if rank != pairs[0]), reverse=True)
        return (2, pairs[0], *kickers)
    return (1, *sorted(ranks, reverse=True))


def sambong_rank(months: Sequence[int]) -> Tuple[Tuple[int, ...], str]:
    """ABADDON table rank for the three-card hwatu game Sambong.

    Triple > pair > 9-kkeut ... 0-kkeut. Ties compare the remaining months.
    """
    if len(months) != 3:
        raise ValueError("Sambong requires three cards")
    values = [int(value) for value in months]
    counts = Counter(values)
    if 3 in counts.values():
        month = max(counts)
        return (4, month), f"{month}삼봉"
    if 2 in counts.values():
        pair = max(rank for rank, count in counts.items() if count == 2)
        kicker = max(rank for rank, count in counts.items() if count == 1)
        return (3, pair, kicker), f"{pair}땡-{kicker}"
    kkeut = sum(values) % 10
    name = "갑오" if kkeut == 9 else ("망통" if kkeut == 0 else f"{kkeut}끗")
    return (2, kkeut, *sorted(values, reverse=True)), name


def dori_rank(months: Sequence[int]) -> Tuple[Tuple[int, ...], str, Tuple[int, int] | None]:
    """Rank a five-card Dori-jitgo-ttaeng hand using every valid made split."""
    if len(months) != 5:
        raise ValueError("Dori-jitgo-ttaeng requires five cards")
    best: Tuple[int, ...] | None = None
    best_name = "노메이드"
    best_pair = None
    for a, b in combinations(range(5), 2):
        if (int(months[a]) + int(months[b])) % 10 != 0:
            continue
        rest = [int(months[index]) for index in range(5) if index not in {a, b}]
        rank, name = sambong_rank(rest)
        full = (*rank, max(int(months[a]), int(months[b])))
        if best is None or full > best:
            best, best_name, best_pair = full, name, (a, b)
    if best is None:
        return ((0, sum(int(v) for v in months) % 10, *sorted((int(v) for v in months), reverse=True)), "노메이드", None)
    return best, best_name, best_pair


def hwatu_capture_points(categories: Iterable[str], months: Iterable[int]) -> int:
    """Common capture points used by the Minhwatu and Yukbaek tables."""
    values = {
        "bright": 50,
        "bright_rain": 50,
        "animal": 10,
        "animal_godori": 50,
        "animal_doublejunk": 10,
        "ribbon_blue": 10,
        "ribbon_red_poetry": 10,
        "ribbon_red_plain": 10,
        "ribbon": 10,
        "junk": 0,
    }
    score = sum(values.get(str(category), 0) for category in categories)
    counts = Counter(int(month) for month in months)
    score += sum(50 for month in (1, 2, 3, 4, 8, 11, 12) if counts.get(month, 0) >= 4)
    return score


def yukbaek_round_valid(scores: Sequence[int]) -> bool:
    """Table rule: any score at 30 or below makes the Yukbaek round a redeal."""
    return bool(scores) and all(int(score) > 30 for score in scores)


def ai_risk(difficulty: str, personality: str) -> float:
    base = {"쉬움": 0.25, "보통": 0.50, "어려움": 0.72, "악몽": 0.90}.get(str(difficulty), 0.50)
    modifier = {"안정형": -0.18, "공격형": 0.16, "블러프형": 0.08, "도박형": 0.28, "복수형": 0.12}.get(str(personality), 0.0)
    return max(0.05, min(0.98, base + modifier))


def league_points(wins: int, draws: int, losses: int, earnings: int = 0) -> int:
    """Stable ranking score; earnings only contributes a small signed bonus."""
    wealth = max(-50, min(50, int(earnings) // 100_000))
    return int(wins) * 3 + int(draws) - int(losses) + wealth


def dashboard_health(checks: Mapping[str, bool]) -> Tuple[int, int, str]:
    passed = sum(1 for value in checks.values() if bool(value))
    total = len(checks)
    return passed, total, "green" if passed == total else ("orange" if passed else "red")
