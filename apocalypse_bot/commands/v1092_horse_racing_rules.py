from __future__ import annotations

"""Pure, Discord-independent rules for ABADDON v10.9.2 horse racing."""

import random
from typing import Any, Dict, List, Mapping, MutableSequence, Sequence, Tuple

FINISH = 34

HORSES: Tuple[Dict[str, Any], ...] = (
    {"name_ko": "검은 성가", "name_en": "Black Hymn", "emoji": "🐎", "rating": 1.14, "odds": 2.2},
    {"name_ko": "재의 질주", "name_en": "Ash Sprint", "emoji": "🏇", "rating": 1.08, "odds": 2.8},
    {"name_ko": "붉은 안개", "name_en": "Red Mist", "emoji": "🐴", "rating": 1.02, "odds": 3.4},
    {"name_ko": "황혼 기관차", "name_en": "Twilight Engine", "emoji": "🏇", "rating": 0.98, "odds": 4.1},
    {"name_ko": "공허의 발굽", "name_en": "Void Hoof", "emoji": "🐎", "rating": 0.94, "odds": 5.0},
    {"name_ko": "아바돈-Ω", "name_en": "ABADDON-Ω", "emoji": "🏇", "rating": 0.90, "odds": 6.0},
)

ODDS_MIN = 1.5
ODDS_MAX = 9.9


def generate_race_odds(rng: random.Random | Any = random) -> Tuple[float, ...]:
    """Create a fresh six-horse market for one race.

    Each market is anchored to the horse's long-term rating so stronger horses
    usually remain shorter-priced, while a sizeable per-race form swing keeps
    the odds visibly different. The returned odds are locked for that race.
    """
    market: List[float] = []
    for index, horse in enumerate(HORSES):
        base = float(horse.get("odds", 3.0))
        # Market mood and track form vary independently for every new race.
        multiplier = float(rng.uniform(0.78, 1.28))
        drift = float(rng.choice((-0.3, -0.2, -0.1, 0.0, 0.0, 0.1, 0.2, 0.3)))
        value = round(max(ODDS_MIN, min(ODDS_MAX, base * multiplier + drift)), 1)
        market.append(value)

    # Avoid an all-identical-looking market after one-decimal rounding.
    if len(set(market)) < 3:
        market = [
            round(max(ODDS_MIN, min(ODDS_MAX, value + (index - 2.5) * 0.1)), 1)
            for index, value in enumerate(market)
        ]
    return tuple(float(value) for value in market)


def render_track_lane(position: int, marker: str = "♞") -> str:
    """Render one race lane with a visible horse and a shared fixed finish flag.

    FINISH is the final valid horse coordinate. Every lane therefore contains
    FINISH + 1 cells (0..FINISH), followed by exactly one finish flag.
    """
    current = min(FINISH, max(0, int(position)))
    cells = ["·"] * (FINISH + 1)
    cells[current] = str(marker or "♞")[:1]
    return f"[{''.join(cells)}🏁]"


def advance_positions(positions: Sequence[int], rng: random.Random | Any = random) -> List[int]:
    """Advance one visible race tick without moving any horse backwards."""
    if len(positions) != len(HORSES):
        raise ValueError(f"expected {len(HORSES)} positions, got {len(positions)}")
    leaders = max((int(v) for v in positions), default=0)
    next_positions: List[int] = []
    for index, horse in enumerate(HORSES):
        current = max(0, int(positions[index]))
        rating = float(horse["rating"])
        burst = rng.choices([0, 1, 2, 3, 4], weights=[5, 28, 38, 22, 7], k=1)[0]
        if current < leaders - 5:
            burst += rng.choice([0, 1])
        if rng.random() < max(0.02, rating - 0.9) * 0.16:
            burst += 1
        next_positions.append(min(FINISH, current + max(0, int(burst))))
    return next_positions


def crossing_winner(previous: Sequence[int], current: Sequence[int], rng: random.Random | Any = random) -> int | None:
    """Return a winner only when a horse crosses the one shared finish line."""
    if len(previous) != len(HORSES) or len(current) != len(HORSES):
        raise ValueError("invalid race position count")
    crossers = [index for index, value in enumerate(current) if int(value) >= FINISH and int(previous[index]) < FINISH]
    if not crossers:
        return None
    # A simultaneous photo finish is resolved among horses that crossed on the
    # same visible tick. Every lane still uses the exact same FINISH coordinate.
    return int(rng.choice(crossers))


def choose_winner(positions: Sequence[int], rng: random.Random | Any = random) -> int:
    if len(positions) != len(HORSES):
        raise ValueError(f"expected {len(HORSES)} positions, got {len(positions)}")
    best = max(int(value) for value in positions)
    candidates = [index for index, value in enumerate(positions) if int(value) == best]
    return int(rng.choice(candidates))


def race_settlement(
    bet: int,
    selected: int,
    winner: int,
    odds: Sequence[float] | None = None,
) -> Tuple[int, int]:
    """Return gross payout and net change using the market locked for the race."""
    stake = int(bet)
    if stake <= 0:
        raise ValueError("bet must be positive")
    if selected not in range(len(HORSES)) or winner not in range(len(HORSES)):
        raise ValueError("invalid horse index")
    market = tuple(float(value) for value in odds) if odds is not None else tuple(float(horse["odds"]) for horse in HORSES)
    if len(market) != len(HORSES) or any(value <= 0 for value in market):
        raise ValueError("invalid race odds")
    gross = int(round(stake * market[selected])) if selected == winner else 0
    return gross, gross - stake


def simulate_race(seed: int, max_ticks: int = 30) -> Tuple[List[int], int, int]:
    """Deterministic smoke-test simulation used by the patch audit."""
    rng = random.Random(int(seed))
    positions = [0] * len(HORSES)
    ticks = 0
    winner = None
    while max(positions) < FINISH and ticks < max_ticks:
        previous = list(positions)
        positions = advance_positions(positions, rng)
        ticks += 1
        winner = crossing_winner(previous, positions, rng)
        if winner is not None:
            break
    return positions, int(winner if winner is not None else choose_winner(positions, rng)), ticks
