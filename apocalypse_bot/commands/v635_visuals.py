from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import discord

VERSION = "6.3.5"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v635"


def _safe_filename(prefix: str, path: Path) -> str:
    suffix = path.suffix.lower() or ".jpg"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix).strip("_") or "visual"
    return f"abaddon_v635_{safe}{suffix}"


def attach_asset(embed: discord.Embed, path: Path, prefix: str) -> Optional[discord.File]:
    if not path.is_file():
        return None
    filename = _safe_filename(prefix, path)
    file = discord.File(str(path), filename=filename)
    embed.set_image(url=f"attachment://{filename}")
    return file


def casino_reaction(title: str, description: str, delta: int, bet: int) -> Tuple[str, str]:
    text = f"{title} {description}".lower()
    if "슬롯" in text:
        game = "slot"
    elif "블랙잭" in text:
        game = "blackjack"
    elif "하이로우" in text:
        game = "highlow"
    elif "바카라" in text:
        game = "baccarat"
    elif "다이스" in text or "주사위" in text:
        game = "dice"
    elif "룰렛" in text:
        game = "roulette"
    else:
        game = "roulette"

    if delta == 0 or any(key in text for key in ("무승부", "타이", "원금 반환", "현금화")):
        return game, "draw"
    if any(key in text for key in ("잭팟", "전 서버 누적", "완전 일치", "내추럴 블랙잭")):
        return game, "jackpot"
    ratio = (float(delta) / max(1, int(bet))) if delta > 0 else 0.0
    if delta > 0:
        if any(key in text for key in ("최대 연승", "5연승", "8연승", "대승")) or ratio >= 4.0:
            return game, "big_win"
        return game, "win"
    if delta < 0:
        if any(key in text for key in ("저주", "파산", "버스트", "탕!", "3배", "연속 실패")) or abs(delta) >= max(1, int(bet)) * 2:
            return game, "critical_loss"
        return game, "loss"
    return game, "draw"


def casino_asset(title: str, description: str, delta: int, bet: int) -> Path:
    game, reaction = casino_reaction(title, description, delta, bet)
    game_dir = ASSET_ROOT / "casino" / game
    candidates = [
        game_dir / f"{reaction}.jpg",
        game_dir / ("big_win.jpg" if reaction == "jackpot" else f"{reaction}.jpg"),
        ASSET_ROOT / "casino" / ("draw.jpg" if reaction == "draw" else "lobby.jpg"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return ASSET_ROOT / "casino" / "lobby.jpg"


def apply_casino_visual(embed: discord.Embed, title: str, description: str, delta: int, bet: int) -> Optional[discord.File]:
    return None


def base_stage_asset(level: int) -> Path:
    level = max(0, min(5, int(level)))
    return ASSET_ROOT / "base" / "stages" / f"level_{level}.jpg"


def base_reaction_asset(reaction: str) -> Path:
    return ASSET_ROOT / "base" / "reactions" / f"{reaction}.jpg"


def apply_base_stage_visual(embed: discord.Embed, level: int) -> Optional[discord.File]:
    return attach_asset(embed, base_stage_asset(level), f"base_level_{level}")


def apply_base_reaction_visual(embed: discord.Embed, reaction: str) -> Optional[discord.File]:
    return attach_asset(embed, base_reaction_asset(reaction), f"base_{reaction}")


def format_remaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {sec}초"
    return f"{sec}초"


def parse_iso(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
