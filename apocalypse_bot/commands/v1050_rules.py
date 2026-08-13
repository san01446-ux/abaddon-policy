from __future__ import annotations

"""Pure rule helpers for ABADDON v10.5.0.

This module deliberately has no discord.py dependency so deployment audits can
exercise game rules, settlement multipliers, brackets, and season progression
without logging a bot into Discord.
"""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

VERSION = "10.5.0"
Card = Tuple[int, str]


# ---------------------------------------------------------------------------
# Card evaluators
# ---------------------------------------------------------------------------
def blackjack_value(cards: Sequence[Card]) -> Tuple[int, bool]:
    """Return (best total, soft) with aces counted as 11 when possible."""
    total = 0
    aces = 0
    for rank, _suit in cards:
        if rank == 14:
            total += 11
            aces += 1
        elif rank >= 10:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def baccarat_value(cards: Sequence[Card]) -> int:
    total = 0
    for rank, _suit in cards:
        if rank == 14:
            value = 1
        elif rank >= 10:
            value = 0
        else:
            value = int(rank)
        total += value
    return total % 10


def ace_to_five_low(cards: Sequence[Card]) -> Optional[Tuple[int, ...]]:
    """Return an A-to-5 low tuple where a lexicographically smaller tuple wins.

    Pairs are allowed but rank behind unpaired lows. Suits and straights do not
    matter. The tuple begins with duplicate count, then descending low ranks.
    """
    if len(cards) < 5:
        return None
    best: Optional[Tuple[int, ...]] = None
    for combo in combinations(cards, 5):
        ranks = [1 if rank == 14 else int(rank) for rank, _ in combo]
        counts = Counter(ranks)
        duplicate_penalty = sum(count - 1 for count in counts.values())
        key = (duplicate_penalty, *sorted(ranks, reverse=True))
        if best is None or key < best:
            best = key
    return best


def badugi_score(cards: Sequence[Card]) -> Tuple[int, Tuple[int, ...], Tuple[Card, ...]]:
    """Return a Badugi score.

    More cards is better. For equal card counts, lower A-to-high ranks are
    better. The returned rank tuple is descending and should be minimized.
    """
    best: Optional[Tuple[int, Tuple[int, ...], Tuple[Card, ...]]] = None
    for length in range(1, min(4, len(cards)) + 1):
        for combo in combinations(cards, length):
            ranks = [1 if rank == 14 else int(rank) for rank, _ in combo]
            suits = [suit for _rank, suit in combo]
            if len(set(ranks)) != length or len(set(suits)) != length:
                continue
            rank_key = tuple(sorted(ranks, reverse=True))
            candidate = (length, rank_key, tuple(combo))
            if best is None or length > best[0] or (length == best[0] and rank_key < best[1]):
                best = candidate
    return best or (0, tuple(), tuple())


def short_deck_score(hand: Sequence[Card]) -> Tuple[Tuple[int, ...], str]:
    """Evaluate a five-card 6+ Hold'em hand.

    ABADDON uses the common short-deck order where a flush beats a full house.
    A-6-7-8-9 is the wheel straight.
    """
    if len(hand) != 5:
        raise ValueError("short_deck_score requires exactly five cards")
    ranks = sorted((int(rank) for rank, _ in hand), reverse=True)
    counts = Counter(ranks)
    ordered = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    flush = len({suit for _rank, suit in hand}) == 1
    unique = sorted(set(ranks), reverse=True)
    if unique == [14, 9, 8, 7, 6]:
        straight_high = 9
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
    if flush:
        return (6, *ranks), "플러시"
    if sorted(counts.values()) == [2, 3]:
        triple = max(rank for rank, count in counts.items() if count == 3)
        pair = max(rank for rank, count in counts.items() if count == 2)
        return (5, triple, pair), "풀하우스"
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


def best_short_deck(cards: Sequence[Card]) -> Tuple[Tuple[int, ...], str, Tuple[Card, ...]]:
    if len(cards) < 5:
        raise ValueError("at least five cards are required")
    best_score: Optional[Tuple[int, ...]] = None
    best_label = ""
    best_hand: Tuple[Card, ...] = tuple()
    for combo in combinations(cards, 5):
        score, label = short_deck_score(combo)
        if best_score is None or score > best_score:
            best_score, best_label, best_hand = score, label, tuple(combo)
    assert best_score is not None
    return best_score, best_label, best_hand


def pineapple_best(
    hole: Sequence[Card],
    board: Sequence[Card],
    poker_score: Any,
) -> Tuple[Tuple[int, ...], str, Tuple[Card, ...], Card]:
    """Choose the optimal pre-flop discard and return the best legal hand."""
    if len(hole) != 3 or len(board) != 5:
        raise ValueError("pineapple requires three hole cards and five board cards")
    best: Optional[Tuple[Tuple[int, ...], str, Tuple[Card, ...], Card]] = None
    for discard_index, discarded in enumerate(hole):
        remaining = [card for index, card in enumerate(hole) if index != discard_index]
        for combo in combinations(remaining + list(board), 5):
            score, label = poker_score(combo)
            candidate = (score, label, tuple(combo), discarded)
            if best is None or score > best[0]:
                best = candidate
    assert best is not None
    return best


# ---------------------------------------------------------------------------
# Full hwatu settlement rules
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HwatuSummary:
    score: int
    bright_count: int
    animal_count: int
    ribbon_count: int
    junk_points: int
    labels: Tuple[str, ...] = tuple()


DEFAULT_HWATU_RULES: Dict[str, bool] = {
    "bomb": True,
    "shake": True,
    "pi_bak": True,
    "gwang_bak": True,
    "meong_tta": True,
    "go_bak": True,
    "chongtong": True,
    "side_events": True,
    "nagari": True,
}


def normalize_hwatu_rules(value: Optional[Mapping[str, Any]]) -> Dict[str, bool]:
    rules = dict(DEFAULT_HWATU_RULES)
    if isinstance(value, Mapping):
        for key in rules:
            if key in value:
                rules[key] = bool(value[key])
    return rules


def hwatu_multiplier(
    winner: HwatuSummary,
    loser: HwatuSummary,
    *,
    go_count: int = 0,
    shakes: int = 0,
    bombs: int = 0,
    loser_declared_go: bool = False,
    nagari_multiplier: int = 1,
    rules: Optional[Mapping[str, Any]] = None,
) -> Tuple[int, List[str]]:
    settings = normalize_hwatu_rules(rules)
    multiplier = max(1, int(nagari_multiplier or 1))
    reasons: List[str] = []
    if multiplier > 1:
        reasons.append(f"나가리 x{multiplier}")
    if settings["shake"] and shakes:
        value = 2 ** max(0, int(shakes))
        multiplier *= value
        reasons.append(f"흔들기 {shakes}회 x{value}")
    if settings["bomb"] and bombs:
        value = 2 ** max(0, int(bombs))
        multiplier *= value
        reasons.append(f"폭탄 {bombs}회 x{value}")
    if go_count >= 3:
        value = 2 ** (int(go_count) - 2)
        multiplier *= value
        reasons.append(f"{go_count}고 x{value}")
    if settings["pi_bak"] and winner.junk_points >= 10 and loser.junk_points <= 5:
        multiplier *= 2
        reasons.append("피박 x2")
    if settings["gwang_bak"] and winner.bright_count >= 3 and loser.bright_count == 0:
        multiplier *= 2
        reasons.append("광박 x2")
    if settings["meong_tta"] and winner.animal_count >= 7 and loser.animal_count < 7:
        multiplier *= 2
        reasons.append("멍따 x2")
    if settings["go_bak"] and loser_declared_go:
        multiplier *= 2
        reasons.append("고박 x2")
    return max(1, multiplier), reasons


def capped_extra_payment(balance: int, bet: int, multiplier: int, cap_multiple: int = 16) -> int:
    """Safely cap an extra hwatu payment to player balance and economy limits."""
    requested = max(0, int(bet)) * max(0, int(multiplier) - 1)
    hard_cap = max(0, int(bet)) * max(1, int(cap_multiple))
    return max(0, min(max(0, int(balance)), requested, hard_cap))


# ---------------------------------------------------------------------------
# Tournament / stats / season helpers
# ---------------------------------------------------------------------------
def build_single_elimination(participants: Sequence[str]) -> List[List[Tuple[str, Optional[str]]]]:
    """Build deterministic bracket rounds, padding the first round with byes."""
    unique: List[str] = []
    seen = set()
    for participant in participants:
        key = str(participant)
        if key not in seen:
            seen.add(key)
            unique.append(key)
    if len(unique) < 2:
        return []
    size = 1
    while size < len(unique):
        size *= 2
    seeded: List[Optional[str]] = list(unique) + [None] * (size - len(unique))
    rounds: List[List[Tuple[str, Optional[str]]]] = []
    first: List[Tuple[str, Optional[str]]] = []
    for index in range(0, size, 2):
        left = seeded[index]
        right = seeded[index + 1]
        if left is None and right is None:
            continue
        first.append((left or right or "", right if left is not None else None))
    rounds.append(first)
    remaining = size // 2
    while remaining > 1:
        rounds.append([(f"WINNER R{len(rounds)}M{index * 2 + 1}", f"WINNER R{len(rounds)}M{index * 2 + 2}") for index in range(remaining // 2)])
        remaining //= 2
    return rounds


def ensure_game_stats(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = user.setdefault("v1050_game_stats", {})
    if not isinstance(root, dict):
        root = {}
        user["v1050_game_stats"] = root
    root.setdefault("games", {})
    root.setdefault("total", {"plays": 0, "wins": 0, "losses": 0, "draws": 0, "earnings": 0, "streak": 0, "best_streak": 0, "ai_plays": 0})
    root.setdefault("achievements", [])
    return root


def record_game_result(
    user: MutableMapping[str, Any],
    game: str,
    outcome: str,
    *,
    earnings: int = 0,
    score: int = 0,
    versus_ai: bool = False,
) -> MutableMapping[str, Any]:
    root = ensure_game_stats(user)
    total = root["total"]
    games = root["games"]
    row = games.setdefault(str(game), {"plays": 0, "wins": 0, "losses": 0, "draws": 0, "earnings": 0, "best_score": 0, "ai_plays": 0})
    outcome = outcome if outcome in {"win", "loss", "draw"} else "draw"
    key = {"win": "wins", "loss": "losses", "draw": "draws"}[outcome]
    for target in (total, row):
        target["plays"] = int(target.get("plays", 0) or 0) + 1
        target[key] = int(target.get(key, 0) or 0) + 1
        target["earnings"] = int(target.get("earnings", 0) or 0) + int(earnings)
        target["best_score"] = max(int(target.get("best_score", 0) or 0), int(score))
        if versus_ai:
            target["ai_plays"] = int(target.get("ai_plays", 0) or 0) + 1
    if outcome == "win":
        total["streak"] = int(total.get("streak", 0) or 0) + 1
        total["best_streak"] = max(int(total.get("best_streak", 0) or 0), int(total["streak"]))
    else:
        total["streak"] = 0
    achievements = set(map(str, root.get("achievements", [])))
    if int(total.get("plays", 0)) >= 1:
        achievements.add("첫 게임")
    if int(total.get("wins", 0)) >= 10:
        achievements.add("10승 생존자")
    if int(total.get("best_streak", 0)) >= 5:
        achievements.add("5연승")
    if int(total.get("ai_plays", 0)) >= 10:
        achievements.add("아바돈의 단골")
    if int(total.get("earnings", 0)) >= 1_000_000:
        achievements.add("백만 칩 승부사")
    root["achievements"] = sorted(achievements)
    return root


SEASON_MISSIONS: Dict[str, Dict[str, Any]] = {
    "play_games": {"target": 10, "points": 20, "ko": "게임 10회 플레이", "en": "Play 10 games"},
    "win_games": {"target": 5, "points": 25, "ko": "게임 5회 승리", "en": "Win 5 games"},
    "ai_games": {"target": 5, "points": 15, "ko": "아바돈과 5회 플레이", "en": "Play 5 games with ABADDON"},
    "companion": {"target": 5, "points": 20, "ko": "동료 활동 5회", "en": "Complete 5 companion activities"},
    "alliance_boss": {"target": 3, "points": 30, "ko": "연합 보스 3회 공격", "en": "Attack the alliance boss 3 times"},
}

SEASON_REWARDS: Tuple[Tuple[int, int, str, str], ...] = (
    (20, 25_000, "황폐한 카드 조각", "Wasteland Card Fragment"),
    (50, 75_000, "연합 보급 휘장", "Alliance Supply Insignia"),
    (80, 150_000, "아바돈 게임 토큰", "ABADDON Game Token"),
    (110, 300_000, "시즌 6 생존자", "Season 6 Survivor"),
)


def ensure_season_profile(user: MutableMapping[str, Any], season_id: str = "S6-2026") -> MutableMapping[str, Any]:
    root = user.setdefault("v1050_season", {})
    if not isinstance(root, dict) or root.get("season_id") != season_id:
        root = {"season_id": season_id, "progress": {}, "points": 0, "completed": [], "claimed": [], "collection": []}
        user["v1050_season"] = root
    root.setdefault("progress", {})
    root.setdefault("points", 0)
    root.setdefault("completed", [])
    root.setdefault("claimed", [])
    root.setdefault("collection", [])
    return root


def advance_season(user: MutableMapping[str, Any], mission: str, amount: int = 1, season_id: str = "S6-2026") -> Tuple[int, bool]:
    root = ensure_season_profile(user, season_id)
    config = SEASON_MISSIONS.get(mission)
    if config is None:
        return int(root.get("points", 0) or 0), False
    progress = root["progress"]
    before = int(progress.get(mission, 0) or 0)
    after = min(int(config["target"]), before + max(0, int(amount)))
    progress[mission] = after
    completed = set(map(str, root.get("completed", [])))
    newly_completed = after >= int(config["target"]) and mission not in completed
    if newly_completed:
        completed.add(mission)
        root["points"] = int(root.get("points", 0) or 0) + int(config["points"])
        root["completed"] = sorted(completed)
    return int(root.get("points", 0) or 0), newly_completed


def claimable_season_rewards(user: MutableMapping[str, Any], season_id: str = "S6-2026") -> List[Tuple[int, int, str, str]]:
    root = ensure_season_profile(user, season_id)
    points = int(root.get("points", 0) or 0)
    claimed = set(int(value) for value in root.get("claimed", []) if str(value).isdigit())
    return [reward for reward in SEASON_REWARDS if reward[0] <= points and reward[0] not in claimed]
