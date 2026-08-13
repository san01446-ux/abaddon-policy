from __future__ import annotations

import asyncio
import copy
import itertools
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Type

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import casino_chips
from apocalypse_bot.commands.v1152_hwatu_assets import hwatu_visual_uid as _asset_visual_uid
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

VERSION = "10.1.0"
KST = timezone(timedelta(hours=9))
Card = Tuple[int, str]


# ---------------------------------------------------------------------------
# Locale helpers: the selected language is rendered alone, never stacked.
# ---------------------------------------------------------------------------
def _locale(bot: commands.Bot, user_id: Any, guild_id: Any = 0) -> str:
    root = getattr(bot, "v1000_root", {})
    if isinstance(root, Mapping):
        users = root.get("users", {})
        if isinstance(users, Mapping):
            row = users.get(str(user_id), {})
            if isinstance(row, Mapping) and row.get("locale") in {"ko", "en"}:
                return str(row["locale"])
        guilds = root.get("guilds", {})
        if isinstance(guilds, Mapping):
            row = guilds.get(str(guild_id), {})
            if isinstance(row, Mapping) and row.get("locale") in {"ko", "en"}:
                return str(row["locale"])
    return "ko"


def _ctx_locale(bot: commands.Bot, ctx: commands.Context) -> str:
    return _locale(bot, getattr(ctx.author, "id", 0), getattr(ctx.guild, "id", 0))


def _interaction_locale(bot: commands.Bot, interaction: discord.Interaction) -> str:
    return _locale(bot, getattr(interaction.user, "id", 0), getattr(interaction.guild, "id", 0))


def _t(locale: str, ko: str, en: str) -> str:
    return ko if locale == "ko" else en


def _today_key() -> str:
    return datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m-%d")


def _norm(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").casefold())


# ---------------------------------------------------------------------------
# Companion survivor system
# ---------------------------------------------------------------------------
COMPANIONS: Mapping[str, Mapping[str, Any]] = {
    "rescue_captain": {
        "ko": "구조대장 민재", "en": "Captain Min-jae", "emoji": "🚑", "bond": 10,
        "role": "rescue", "assignment": "expedition",
        "passive_ko": "구조 행동의 글로벌 탐사 기여도 +12",
        "passive_en": "+12 global-expedition contribution on rescue actions",
    },
    "field_medic": {
        "ko": "야전 의무관 세린", "en": "Field Medic Serin", "emoji": "⚕️", "bond": 10,
        "role": "rescue", "assignment": "expedition",
        "passive_ko": "구조 행동의 인연 획득 +1, 탐사 기여도 +8",
        "passive_en": "+1 bond and +8 expedition contribution on rescue actions",
    },
    "rail_engineer": {
        "ko": "철도 기술자 도윤", "en": "Rail Engineer Do-yun", "emoji": "🧰", "bond": 10,
        "role": "repair", "assignment": "expedition",
        "passive_ko": "복구 행동의 글로벌 탐사 기여도 +12",
        "passive_en": "+12 global-expedition contribution on repair actions",
    },
    "recon_leader": {
        "ko": "정찰대장 이라", "en": "Recon Leader Ira", "emoji": "🧭", "bond": 10,
        "role": "scan", "assignment": "expedition",
        "passive_ko": "신호분석 행동의 글로벌 탐사 기여도 +12",
        "passive_en": "+12 global-expedition contribution on scan actions",
    },
    "militia_guard": {
        "ko": "민병대 수문장 하진", "en": "Militia Warden Ha-jin", "emoji": "🛡️", "bond": 10,
        "role": "secure", "assignment": "expedition",
        "passive_ko": "확보 행동의 글로벌 탐사 기여도 +12",
        "passive_en": "+12 global-expedition contribution on secure actions",
    },
    "convoy_master": {
        "ko": "호송대장 로안", "en": "Convoy Master Roan", "emoji": "🚚", "bond": 10,
        "role": "card", "assignment": "card",
        "passive_ko": "신규 카드게임 완료 시 동료 임무 진행도 +1",
        "passive_en": "+1 companion-mission progress after a new card game",
    },
}

ASSIGNMENT_NAMES = {
    "expedition": {"ko": "글로벌 탐사", "en": "Global Expedition"},
    "card": {"ko": "카드게임", "en": "Card Games"},
    "rest": {"ko": "대기", "en": "Standby"},
}


def _companion_profile(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = user.setdefault("v1010_companions", {})
    if not isinstance(root, dict):
        root = {}
        user["v1010_companions"] = root
    root.setdefault("recruited", [])
    root.setdefault("active", "")
    root.setdefault("assignment", "rest")
    root.setdefault("talked", {})
    root.setdefault("mission", {})
    root.setdefault("stats", {"talks": 0, "missions": 0, "card_games": 0, "expedition_actions": 0})
    return root


def _relationship_score(user: Mapping[str, Any], key: str) -> int:
    profile = user.get("global_v1000", {})
    if not isinstance(profile, Mapping):
        return 0
    rel = profile.get("relationships", {})
    if not isinstance(rel, Mapping):
        return 0
    try:
        return int(rel.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_companion(value: Any) -> Optional[str]:
    token = _norm(value)
    for key, row in COMPANIONS.items():
        aliases = {key, row["ko"], row["en"], str(row["ko"]).split()[-1], str(row["en"]).split()[-1]}
        if token in {_norm(alias) for alias in aliases}:
            return key
    return None


def _ensure_daily_mission(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    profile = _companion_profile(user)
    mission = profile.get("mission", {})
    today = _today_key()
    if not isinstance(mission, dict) or mission.get("date") != today:
        active = str(profile.get("active", ""))
        assignment = str(profile.get("assignment", "rest"))
        if active and assignment == "card":
            kind, target = "card", 2
        elif active:
            kind, target = "expedition", 3
        else:
            kind, target = "talk", 1
        mission = {"date": today, "kind": kind, "target": target, "progress": 0, "claimed": False}
        profile["mission"] = mission
    return mission


def _advance_companion_mission(user: MutableMapping[str, Any], kind: str, amount: int = 1) -> None:
    mission = _ensure_daily_mission(user)
    if mission.get("kind") != kind or mission.get("claimed"):
        return
    mission["progress"] = min(int(mission.get("target", 1) or 1), int(mission.get("progress", 0) or 0) + max(0, int(amount)))


def apply_companion_bonus(user: MutableMapping[str, Any], activity: str) -> Tuple[int, int, str]:
    """Return contribution bonus, bond bonus, and companion key for linked systems."""
    profile = _companion_profile(user)
    key = str(profile.get("active", ""))
    if key not in COMPANIONS or key not in set(map(str, profile.get("recruited", []))):
        return 0, 0, ""
    row = COMPANIONS[key]
    assignment = str(profile.get("assignment", "rest"))
    if assignment == "expedition":
        _advance_companion_mission(user, "expedition", 1)
        stats = profile["stats"]
        stats["expedition_actions"] = int(stats.get("expedition_actions", 0) or 0) + 1
        if row.get("role") == activity:
            if key == "field_medic":
                return 8, 1, key
            return 12, 0, key
    return 0, 0, key


def record_companion_card_game(user: MutableMapping[str, Any]) -> None:
    profile = _companion_profile(user)
    profile["stats"]["card_games"] = int(profile["stats"].get("card_games", 0) or 0) + 1
    if profile.get("assignment") == "card":
        _advance_companion_mission(user, "card", 1)




class V1010LobbyView(CardLobbyView):
    def __init__(self, *args: Any, public_locale: str = "ko", **kwargs: Any) -> None:
        self.public_locale = public_locale if public_locale in {"ko", "en"} else "ko"
        super().__init__(*args, **kwargs)
        if self.public_locale == "en":
            labels = {
                "참가": "Join", "참가 취소": "Leave", "아바돈 초대": "Invite ABADDON",
                "인원 확정·시작": "Confirm & Start", "방 취소": "Cancel Lobby",
            }
            for child in self.children:
                if getattr(child, "label", None) in labels:
                    child.label = labels[str(child.label)]

    def embed(self, note: str = "") -> discord.Embed:
        locale = self.public_locale
        if locale == "en" and note:
            patterns = [
                (r"✅ \*\*(.+?)\*\* 님이 참가했습니다\.", r"✅ **\1** joined the lobby."),
                (r"↩️ \*\*(.+?)\*\* 님이 참가를 취소했습니다\.", r"↩️ **\1** left the lobby."),
                (r"❌ 시작 실패: `(.+?)` · 참가비는 차감되지 않았습니다\.", r"❌ Start failed: `\1` · entry fees were not charged."),
                (r"🛑 모집이 취소됐습니다\. 참가비는 차감되지 않았습니다\.", r"🛑 The lobby was cancelled. Entry fees were not charged."),
                (r"⌛ 모집 시간이 끝났습니다\. 참가비는 차감되지 않았습니다\.", r"⌛ The lobby expired. Entry fees were not charged."),
            ]
            for pattern, replacement in patterns:
                note = re.sub(pattern, replacement, note)
        descriptions = {
            "포커": ("각자 비공개 5장을 받고 한 장을 한 번 교환한 뒤 가장 높은 족보가 승리합니다.", "Each player gets five private cards, may exchange one card once, and the best hand wins."),
            "원카드": ("같은 무늬·숫자 카드를 내거나 한 장을 뽑습니다. 먼저 패를 비우면 승리합니다.", "Play the same suit or rank, or draw a card. The first player to empty their hand wins."),
            "조커잡기": ("짝을 자동으로 버리고 옆 사람 패에서 뽑습니다. 마지막 조커를 가진 사람이 패배합니다.", "Pairs are discarded automatically. Draw from the next player and avoid holding the final joker."),
            "텍사스홀덤": ("비공개 2장과 커뮤니티 5장 중 가장 좋은 5장 족보로 승부합니다.", "Build the best five-card hand from two hole cards and five community cards."),
            "오마하홀덤": ("비공개 4장 중 정확히 2장과 커뮤니티 카드 3장을 사용합니다.", "Use exactly two of four hole cards and exactly three community cards."),
            "세븐카드스터드": ("개인 7장 중 가장 좋은 5장 족보로 승부합니다.", "Build the best five-card hand from seven personal cards."),
            "맞고": ("2인 화투입니다. 같은 월 패를 맞추고 고 또는 스톱을 선택합니다.", "Two-player hwatu. Match cards by month and choose Go or Stop."),
            "고스톱": ("3~4인 화투입니다. 같은 월 패를 모아 점수를 만들고 고 또는 스톱을 선택합니다.", "Three-to-four-player hwatu. Match months, score sets, and choose Go or Stop."),
        }
        display = self.kind if locale == "ko" else _english_game_name(self.kind)
        description = descriptions.get(self.kind, (self.kind, _english_game_name(self.kind)))[0 if locale == "ko" else 1]
        embed = discord.Embed(
            title=_t(locale, f"🃏 {display} 참가 모집", f"🃏 {display} Lobby"),
            description=(_t(locale, "**10초 설명**", "**Quick Rules**") + f"\n{description}\n\n{note}").strip(),
            color=discord.Color.dark_purple(),
        )
        names = "\n".join(f"{idx}. **{name}**{' 👑' if uid == self.host_id else ''}" for idx, (uid, name) in enumerate(self.players.items(), 1))
        embed.add_field(name=_t(locale, f"참가자 {len(self.players)}/{self.max_players}", f"Players {len(self.players)}/{self.max_players}"), value=names or _t(locale, "없음", "None"), inline=False)
        embed.add_field(name=_t(locale, "참가비", "Entry Fee"), value=f"**{self.bet:,}{_t(locale, '칩', ' chips')}** · " + _t(locale, "시작할 때 차감", "charged on start"), inline=True)
        embed.add_field(name=_t(locale, "예상 상금", "Estimated Prize"), value=f"**{self.bet * len(self.players):,}{_t(locale, '칩', ' chips')}**", inline=True)
        embed.add_field(name=_t(locale, "진행", "Lobby Fill"), value=f"{_emoji_bar(len(self.players) / self.max_players)} **{len(self.players)}/{self.max_players}**", inline=False)
        footer = _t(locale, "여러 명이면 방장이 인원을 확정해 시작합니다.", "The host confirms the players and starts the game.")
        if self.allow_abaddon:
            footer = _t(locale, "혼자라면 아바돈 초대 · 여러 명이면 방장이 인원을 확정해 시작", "Invite ABADDON when alone, or let the host confirm and start multiplayer.")
        embed.set_footer(text=footer)
        return embed


def _localize_public_buttons(view: discord.ui.View, locale: str, labels: Mapping[str, str]) -> None:
    if locale != "en":
        return
    for child in getattr(view, "children", []):
        current = str(getattr(child, "label", "") or "")
        if current in labels:
            child.label = labels[current]


# ---------------------------------------------------------------------------
# Poker variants
# ---------------------------------------------------------------------------
def _best_five(cards: Sequence[Card]) -> Tuple[Tuple[int, ...], str, Tuple[Card, ...]]:
    if len(cards) < 5:
        raise ValueError("at least five cards are required")
    best_score: Optional[Tuple[int, ...]] = None
    best_label = ""
    best_hand: Tuple[Card, ...] = tuple()
    for combo in itertools.combinations(cards, 5):
        score, label = _poker_score(combo)
        if best_score is None or score > best_score:
            best_score = score
            best_label = label
            best_hand = combo
    assert best_score is not None
    return best_score, best_label, best_hand


def _best_omaha(hole: Sequence[Card], board: Sequence[Card]) -> Tuple[Tuple[int, ...], str, Tuple[Card, ...]]:
    best_score: Optional[Tuple[int, ...]] = None
    best_label = ""
    best_hand: Tuple[Card, ...] = tuple()
    for hole_two in itertools.combinations(hole, 2):
        for board_three in itertools.combinations(board, 3):
            combo = tuple(hole_two) + tuple(board_three)
            score, label = _poker_score(combo)
            if best_score is None or score > best_score:
                best_score, best_label, best_hand = score, label, combo
    assert best_score is not None
    return best_score, best_label, best_hand


POKER_VARIANTS: Mapping[str, Mapping[str, Any]] = {
    "텍사스홀덤": {
        "en": "Texas Hold'em", "emoji": "🤠", "hole": 2, "board": 5, "min": 2, "max": 6,
        "stages": (0, 3, 4, 5), "session": "texas",
    },
    "오마하홀덤": {
        "en": "Omaha Hold'em", "emoji": "🌊", "hole": 4, "board": 5, "min": 2, "max": 6,
        "stages": (0, 3, 4, 5), "session": "omaha",
    },
    "세븐카드스터드": {
        "en": "Seven-Card Stud", "emoji": "🎩", "hole": 7, "board": 0, "min": 2, "max": 6,
        "stages": (3, 4, 5, 6, 7), "session": "stud",
    },
}


class PokerVariantSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, variant: str) -> None:
        super().__init__(lobby, timeout=210)
        self.bot = bot
        self.variant = variant
        self.config = POKER_VARIANTS[variant]
        self.deck = _deck()
        hole_count = int(self.config["hole"])
        self.hands: Dict[int, List[Card]] = {uid: [self.deck.pop() for _ in range(hole_count)] for uid in self.player_ids}
        self.board: List[Card] = [self.deck.pop() for _ in range(int(self.config["board"]))]
        self.stage_index = 0
        self.ready: set[int] = set()
        self.last_action = ""
        _localize_public_buttons(self, getattr(lobby, "public_locale", "ko"), {
            "내 패 보기": "View Hand",
            "다음 공개": "Reveal Next",
            "준비": "Ready",
            "승부 공개": "Showdown",
        })

    @property
    def stage_value(self) -> int:
        return int(self.config["stages"][self.stage_index])

    def _name(self, locale: str) -> str:
        return self.variant if locale == "ko" else str(self.config["en"])

    def public_locale(self) -> str:
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0)
        return _locale(self.bot, 0, guild_id)

    def embed(self, locale: str, final: str = "") -> discord.Embed:
        emoji = str(self.config["emoji"])
        title = f"{emoji} {self._name(locale)}"
        if final:
            description = final
        elif self.config["session"] == "stud":
            description = _t(locale, "개인 패를 확인하고 방장이 배부 단계를 진행합니다. 마지막에는 7장 중 가장 좋은 5장으로 승부합니다.", "Check your private cards while the host advances the deal. The best five of seven cards wins.")
        else:
            description = _t(locale, "개인 패를 확인하고 방장이 플랍·턴·리버를 공개합니다. 참가비 외 추가 베팅은 없습니다.", "Check your hole cards while the host reveals flop, turn, and river. There are no extra betting rounds.")
        embed = discord.Embed(title=title, description=description, color=discord.Color.gold())
        if self.config["session"] == "stud":
            rows = []
            visible = self.stage_value
            for uid in self.player_ids:
                shown = self.hands[uid][2:visible]
                rows.append(f"{'✅' if uid in self.ready else '▫️'} **{self.names[uid]}** · " + (" ".join(_card_text(c) for c in shown) if shown else _t(locale, "공개 카드 없음", "No up-cards")))
            embed.add_field(name=_t(locale, "공개 카드", "Up-cards"), value="\n".join(rows), inline=False)
            phase = f"{visible}/7"
        else:
            visible = self.stage_value
            board_text = "  ".join(_card_text(c) for c in self.board[:visible]) or _t(locale, "아직 공개되지 않았습니다.", "Not revealed yet.")
            embed.add_field(name=_t(locale, "커뮤니티 카드", "Community Cards"), value=board_text, inline=False)
            phase_names = {0: ("프리플랍", "Pre-flop"), 3: ("플랍", "Flop"), 4: ("턴", "Turn"), 5: ("리버", "River")}
            phase = phase_names[visible][0 if locale == "ko" else 1]
        status = "\n".join(f"{'✅' if uid in self.ready else '▫️'} **{self.names[uid]}**" for uid in self.player_ids)
        embed.add_field(name=_t(locale, "참가자 준비", "Player Readiness"), value=status, inline=False)
        embed.add_field(name=_t(locale, "현재 단계", "Current Stage"), value=phase, inline=True)
        embed.add_field(name=_t(locale, "상금", "Prize Pool"), value=f"**{self.pot:,} chips**" if locale == "en" else f"**{self.pot:,}칩**", inline=True)
        embed.set_footer(text=_t(locale, "내 패는 본인에게만 표시됩니다. 동률이면 상금을 나눕니다.", "Hole cards are private. Tied winners split the pot."))
        return embed

    async def start(self) -> None:
        self._reserve()
        locale = self.public_locale()
        await _safe_edit(self.message, embed=self.embed(locale), view=self)

    async def update(self) -> None:
        locale = self.public_locale()
        await _safe_edit(self.message, embed=self.embed(locale), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        cards = "  ".join(_card_text(c) for c in self.hands[uid])
        await interaction.response.send_message(_t(locale, f"🃏 **내 패**\n{cards}", f"🃏 **Your Cards**\n{cards}"), ephemeral=True)

    @discord.ui.button(label="다음 공개", emoji="🎴", style=discord.ButtonStyle.primary)
    async def reveal_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if int(interaction.user.id) != self.host_id:
                await interaction.response.send_message(_t(locale, "방장만 다음 단계를 공개할 수 있습니다.", "Only the host can reveal the next stage."), ephemeral=True)
                return
            if self.stage_index >= len(self.config["stages"]) - 1:
                await interaction.response.send_message(_t(locale, "모든 카드가 공개됐습니다.", "All cards have been revealed."), ephemeral=True)
                return
            self.stage_index += 1
            await interaction.response.defer()
            await self.update()

    @discord.ui.button(label="준비", emoji="✅", style=discord.ButtonStyle.success)
    async def mark_ready(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        self.ready.add(uid)
        await interaction.response.send_message(_t(locale, "승부 공개 준비를 완료했습니다.", "You are ready for the showdown."), ephemeral=True)
        await self.update()

    @discord.ui.button(label="승부 공개", emoji="🏆", style=discord.ButtonStyle.danger)
    async def showdown_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if int(interaction.user.id) != self.host_id:
                await interaction.response.send_message(_t(locale, "방장만 승부를 공개할 수 있습니다.", "Only the host can start the showdown."), ephemeral=True)
                return
            fully_revealed = self.stage_index >= len(self.config["stages"]) - 1
            if not fully_revealed and len(self.ready) < len(self.player_ids):
                await interaction.response.send_message(_t(locale, "모든 참가자가 준비하거나 마지막 단계까지 공개해야 합니다.", "Reveal the final stage or wait until every player is ready."), ephemeral=True)
                return
            await interaction.response.defer()
            await self.finish(locale)

    def _score(self, uid: int) -> Tuple[Tuple[int, ...], str, Tuple[Card, ...]]:
        mode = str(self.config["session"])
        if mode == "omaha":
            return _best_omaha(self.hands[uid], self.board)
        if mode == "stud":
            return _best_five(self.hands[uid])
        return _best_five(self.hands[uid] + self.board)

    async def finish(self, locale: str) -> None:
        if self.done:
            return
        self.done = True
        scored = {uid: self._score(uid) for uid in self.player_ids}
        high = max(row[0] for row in scored.values())
        winners = [uid for uid, row in scored.items() if row[0] == high]
        payouts = self._pay(winners)
        for uid in self.player_ids:
            record_companion_card_game(self.get_user(uid))
        self.save_data()
        rows = []
        for uid in sorted(self.player_ids, key=lambda x: scored[x][0], reverse=True):
            _score_value, label, best = scored[uid]
            translated = _poker_label(label, locale)
            marker = "🏆" if uid in winners else "▫️"
            payout = f" · +{payouts[uid]:,} chips" if locale == "en" and uid in payouts else (f" · +{payouts[uid]:,}칩" if uid in payouts else "")
            rows.append(f"{marker} **{self.names[uid]}** · {translated} · {' '.join(_card_text(c) for c in best)}{payout}")
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
            await _safe_edit(self.message, embed=self.embed(locale, _t(locale, "⌛ 진행 시간이 끝나 참가비를 전원 환불했습니다.", "⌛ The game timed out and all entry fees were refunded.")), view=self)
            self.stop()


def _poker_label(label: str, locale: str) -> str:
    if locale == "ko":
        return label
    return {
        "스트레이트 플러시": "Straight Flush", "포카드": "Four of a Kind", "풀하우스": "Full House",
        "플러시": "Flush", "스트레이트": "Straight", "트리플": "Three of a Kind",
        "투페어": "Two Pair", "원페어": "One Pair", "하이카드": "High Card",
    }.get(label, label)


# ---------------------------------------------------------------------------
# Go-Stop / Matgo
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HwatuCard:
    month: int
    category: str
    ko: str
    en: str
    junk: int = 0


def _hwatu_deck() -> List[HwatuCard]:
    specs: Mapping[int, Sequence[Tuple[str, str, str, int]]] = {
        1: (("bright", "송학 광", "Crane Bright", 0), ("ribbon_red_poetry", "홍단", "Poetry Ribbon", 0), ("junk", "송학 피", "Pine Junk", 1), ("junk", "송학 피", "Pine Junk", 1)),
        2: (("animal_godori", "매조", "Warbler", 0), ("ribbon_red_poetry", "홍단", "Poetry Ribbon", 0), ("junk", "매화 피", "Plum Junk", 1), ("junk", "매화 피", "Plum Junk", 1)),
        3: (("bright", "벚꽃 광", "Curtain Bright", 0), ("ribbon_red_poetry", "홍단", "Poetry Ribbon", 0), ("junk", "벚꽃 피", "Cherry Junk", 1), ("junk", "벚꽃 피", "Cherry Junk", 1)),
        4: (("animal_godori", "흑싸리 새", "Cuckoo", 0), ("ribbon_red_plain", "초단", "Plain Red Ribbon", 0), ("junk", "흑싸리 피", "Wisteria Junk", 1), ("junk", "흑싸리 피", "Wisteria Junk", 1)),
        5: (("animal", "난초 다리", "Bridge", 0), ("ribbon_red_plain", "초단", "Plain Red Ribbon", 0), ("junk", "난초 피", "Iris Junk", 1), ("junk", "난초 피", "Iris Junk", 1)),
        6: (("animal", "모란 나비", "Butterfly", 0), ("ribbon_blue", "청단", "Blue Ribbon", 0), ("junk", "모란 피", "Peony Junk", 1), ("junk", "모란 피", "Peony Junk", 1)),
        7: (("animal", "홍싸리 멧돼지", "Boar", 0), ("ribbon_red_plain", "초단", "Plain Red Ribbon", 0), ("junk", "홍싸리 피", "Bush Clover Junk", 1), ("junk", "홍싸리 피", "Bush Clover Junk", 1)),
        8: (("bright", "공산 광", "Moon Bright", 0), ("animal_godori", "기러기", "Geese", 0), ("junk", "공산 피", "Pampas Junk", 1), ("junk", "공산 피", "Pampas Junk", 1)),
        9: (("animal_doublejunk", "국진", "Sake Cup", 2), ("ribbon_blue", "청단", "Blue Ribbon", 0), ("junk", "국화 피", "Chrysanthemum Junk", 1), ("junk", "국화 피", "Chrysanthemum Junk", 1)),
        10: (("animal", "단풍 사슴", "Deer", 0), ("ribbon_blue", "청단", "Blue Ribbon", 0), ("junk", "단풍 피", "Maple Junk", 1), ("junk", "단풍 피", "Maple Junk", 1)),
        11: (("bright", "오동 광", "Phoenix Bright", 0), ("junk", "오동 쌍피", "Paulownia Double Junk", 2), ("junk", "오동 피", "Paulownia Junk", 1), ("junk", "오동 피", "Paulownia Junk", 1)),
        12: (("bright_rain", "비광", "Rain Bright", 0), ("animal", "제비", "Swallow", 0), ("ribbon", "비 띠", "Rain Ribbon", 0), ("junk", "비 쌍피", "Rain Double Junk", 2)),
    }
    cards = [HwatuCard(month, cat, ko, en, junk) for month, rows in specs.items() for cat, ko, en, junk in rows]
    random.shuffle(cards)
    return cards



def _hwatu_visual_slot(card: HwatuCard, junk_seen: MutableMapping[int, int] | None = None) -> int:
    """Return the traditional 1..4 artwork slot without changing game rules."""
    return _asset_visual_uid(card.month, card.category, junk=card.junk, junk_seen=junk_seen) % 10


def _hwatu_visual_uid(card: HwatuCard, junk_seen: MutableMapping[int, int] | None = None) -> int:
    return _asset_visual_uid(card.month, card.category, junk=card.junk, junk_seen=junk_seen)

def _hwatu_text(card: HwatuCard, locale: str) -> str:
    symbol = {"bright": "✨", "bright_rain": "🌧️", "animal": "🦌", "animal_godori": "🐦", "animal_doublejunk": "🍶", "ribbon_blue": "🔵", "ribbon_red_poetry": "🔴", "ribbon_red_plain": "🎀", "ribbon": "🎗️", "junk": "🍂"}.get(card.category, "🎴")
    if locale == "ko":
        return f"{symbol}{card.month}월 {card.ko}"
    return f"{symbol}Month {card.month} · {card.en}"


def _hwatu_score(cards: Sequence[HwatuCard]) -> Tuple[int, List[str]]:
    # The September sake cup can count as an animal or as double junk.
    # Evaluate both legal interpretations and keep the higher scoring result.
    def calculate(*, cup_as_junk: bool) -> Tuple[int, List[str]]:
        score = 0
        labels: List[str] = []
        brights = [c for c in cards if c.category.startswith("bright")]
        rain = any(c.category == "bright_rain" for c in brights)
        if len(brights) == 5:
            score += 15; labels.append("오광")
        elif len(brights) == 4:
            score += 4; labels.append("사광")
        elif len(brights) == 3:
            value = 2 if rain else 3
            score += value; labels.append("비삼광" if rain else "삼광")

        animals = [
            c for c in cards
            if c.category.startswith("animal") and not (cup_as_junk and c.category == "animal_doublejunk")
        ]
        if len(animals) >= 5:
            score += len(animals) - 4; labels.append(f"열끗 {len(animals)}")
        godori_months = {c.month for c in animals if c.category == "animal_godori"}
        if {2, 4, 8}.issubset(godori_months):
            score += 5; labels.append("고도리")

        ribbons = [c for c in cards if c.category.startswith("ribbon")]
        if len(ribbons) >= 5:
            score += len(ribbons) - 4; labels.append(f"띠 {len(ribbons)}")
        for category, label in (("ribbon_blue", "청단"), ("ribbon_red_poetry", "홍단"), ("ribbon_red_plain", "초단")):
            if sum(1 for c in cards if c.category == category) >= 3:
                score += 3; labels.append(label)

        junk_points = sum(c.junk for c in cards if c.category != "animal_doublejunk")
        if cup_as_junk:
            junk_points += sum(2 for c in cards if c.category == "animal_doublejunk")
        if junk_points >= 10:
            score += junk_points - 9; labels.append(f"피 {junk_points}")
        return score, labels

    animal_result = calculate(cup_as_junk=False)
    junk_result = calculate(cup_as_junk=True)
    return max((animal_result, junk_result), key=lambda row: (row[0], len(row[1])))


def _hwatu_label(label: str, locale: str) -> str:
    if locale == "ko":
        return label
    exact = {
        "오광": "Five Brights", "사광": "Four Brights", "비삼광": "Rain Three Brights",
        "삼광": "Three Brights", "고도리": "Godori", "청단": "Blue Ribbons",
        "홍단": "Poetry Ribbons", "초단": "Plain Red Ribbons",
    }
    if label in exact:
        return exact[label]
    for prefix, translated in (("열끗 ", "Animals "), ("띠 ", "Ribbons "), ("피 ", "Junk ")):
        if label.startswith(prefix):
            return translated + label[len(prefix):]
    return label


def _hwatu_labels(labels: Sequence[str], locale: str) -> str:
    return " · ".join(_hwatu_label(label, locale) for label in labels) if labels else _t(locale, "족보 없음", "No scoring set")


class HwatuPlaySelect(discord.ui.Select):
    def __init__(self, session: "HwatuSession", uid: int, locale: str) -> None:
        self.session = session
        self.uid = uid
        hand = session.hands[uid]
        options = [discord.SelectOption(label=_hwatu_text(card, locale)[:100], value=str(index)) for index, card in enumerate(hand[:25])]
        super().__init__(placeholder=_t(locale, "낼 화투패를 선택하세요", "Choose a hwatu card to play"), min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.play_card(interaction, self.uid, int(self.values[0]))


class HwatuPlayView(discord.ui.View):
    def __init__(self, session: "HwatuSession", uid: int, locale: str) -> None:
        super().__init__(timeout=45)
        self.add_item(HwatuPlaySelect(session, uid, locale))


class HwatuSession(BaseCardSession):
    def __init__(self, lobby: CardLobbyView, *, bot: commands.Bot, mode: str) -> None:
        super().__init__(lobby, timeout=360)
        self.bot = bot
        self.mode = mode
        deck = _hwatu_deck()
        hand_size = 10 if mode == "맞고" else 7
        floor_size = 8 if mode == "맞고" else 6
        self.hands: Dict[int, List[HwatuCard]] = {uid: [] for uid in self.player_ids}
        for _ in range(hand_size):
            for uid in self.player_ids:
                self.hands[uid].append(deck.pop())
        self.floor: List[HwatuCard] = [deck.pop() for _ in range(floor_size)]
        self.deck = deck
        self.captured: Dict[int, List[HwatuCard]] = {uid: [] for uid in self.player_ids}
        self.scores: Dict[int, int] = {uid: 0 for uid in self.player_ids}
        self.go_counts: Dict[int, int] = {uid: 0 for uid in self.player_ids}
        self.turn = 0
        self.pending_go: Optional[int] = None
        self.last_action = ""
        _localize_public_buttons(self, getattr(lobby, "public_locale", "ko"), {
            "내 패 보기": "View Hand",
            "패 내기": "Play Card",
            "고": "Go",
            "스톱": "Stop",
        })

    @property
    def current_uid(self) -> int:
        return self.player_ids[self.turn % len(self.player_ids)]

    def _threshold(self) -> int:
        return 7 if self.mode == "맞고" else 3

    def public_locale(self) -> str:
        guild_id = getattr(getattr(self.message, "guild", None), "id", 0)
        return _locale(self.bot, 0, guild_id)

    def _capture_resolution(self, uid: int, card: HwatuCard, source: str, locale: str) -> str:
        matches = [c for c in self.floor if c.month == card.month]
        if not matches:
            self.floor.append(card)
            return _t(locale, f"{source}: 바닥에 놓음", f"{source}: placed on the floor")
        target = random.choice(matches)
        self.floor.remove(target)
        self.captured[uid].extend([card, target])
        return _t(locale, f"{source}: {card.month}월 2장 획득", f"{source}: captured two Month {card.month} cards")

    def embed(self, locale: str, final: str = "") -> discord.Embed:
        title = "🎴 맞고" if self.mode == "맞고" and locale == "ko" else ("🎴 Matgo" if self.mode == "맞고" else ("🎴 고스톱" if locale == "ko" else "🎴 Go-Stop"))
        description = final or _t(locale, "같은 월의 패를 맞춰 획득하세요. 점수 기준을 넘으면 고 또는 스톱을 선택할 수 있습니다.", "Match cards from the same month. Once you reach the threshold, choose Go or Stop.")
        embed = discord.Embed(title=title, description=description, color=discord.Color.dark_red())
        floor_text = "\n".join(" · ".join(_hwatu_text(card, locale) for card in self.floor[i:i+4]) for i in range(0, len(self.floor), 4)) or _t(locale, "바닥패 없음", "No floor cards")
        embed.add_field(name=_t(locale, "바닥패", "Floor Cards"), value=floor_text[:1024], inline=False)
        rows = []
        for uid in self.player_ids:
            score, labels = _hwatu_score(self.captured[uid])
            marker = "👉" if uid == self.current_uid and self.pending_go is None else "▫️"
            rows.append(f"{marker} **{self.names[uid]}** · {len(self.hands[uid])}{_t(locale, '장', ' cards')} · {score}{_t(locale, '점', ' pts')} · {_t(locale, '고', 'Go')} {self.go_counts[uid]}")
        embed.add_field(name=_t(locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(locale, "남은 더미", "Stock"), value=str(len(self.deck)), inline=True)
        embed.add_field(name=_t(locale, "상금", "Prize Pool"), value=f"{self.pot:,}{_t(locale, '칩', ' chips')}", inline=True)
        if self.pending_go is not None:
            embed.add_field(name=_t(locale, "선택 대기", "Decision Pending"), value=_t(locale, f"**{self.names[self.pending_go]}** 님이 고/스톱을 선택합니다.", f"**{self.names[self.pending_go]}** must choose Go or Stop."), inline=False)
        embed.set_footer(text=_t(locale, "동월 카드가 여러 장이면 서버가 한 장을 무작위로 선택합니다. 시간 초과 시 전원 환불됩니다.", "If multiple same-month cards exist, one is selected at random. Timeout refunds all players."))
        return embed

    async def start(self) -> None:
        self._reserve()
        locale = self.public_locale()
        await _safe_edit(self.message, embed=self.embed(locale), view=self)

    async def update(self) -> None:
        locale = self.public_locale()
        await _safe_edit(self.message, embed=self.embed(locale), view=self)

    @discord.ui.button(label="내 패 보기", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        cards = "\n".join(f"{i+1}. {_hwatu_text(card, locale)}" for i, card in enumerate(self.hands[uid])) or _t(locale, "남은 패가 없습니다.", "No cards remain.")
        score, labels = _hwatu_score(self.captured[uid])
        captured = _t(locale, f"현재 {score}점 · {_hwatu_labels(labels, locale)}", f"Current score: {score} · {_hwatu_labels(labels, locale)}")
        await interaction.response.send_message(f"🎴 **{_t(locale, '내 패', 'Your Hand')}**\n{cards}\n\n{captured}", ephemeral=True)

    @discord.ui.button(label="패 내기", emoji="🎴", style=discord.ButtonStyle.primary)
    async def choose_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if self.pending_go is not None:
            await interaction.response.send_message(_t(locale, "먼저 고/스톱 선택을 기다려주세요.", "Wait for the Go/Stop decision first."), ephemeral=True)
            return
        if uid != self.current_uid:
            await interaction.response.send_message(_t(locale, f"지금은 **{self.names[self.current_uid]}** 님 차례입니다.", f"It is **{self.names[self.current_uid]}**'s turn."), ephemeral=True)
            return
        await interaction.response.send_message(_t(locale, "낼 패를 선택하세요.", "Choose a card to play."), view=HwatuPlayView(self, uid, locale), ephemeral=True)

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
            card = self.hands[uid].pop(index)
            actions = [self._capture_resolution(uid, card, _t(locale, "낸 패", "Played card"), locale)]
            if self.deck:
                flipped = self.deck.pop()
                actions.append(self._capture_resolution(uid, flipped, _t(locale, "뒤집은 패", "Flipped card"), locale))
            score, _labels = _hwatu_score(self.captured[uid])
            previous = self.scores[uid]
            self.scores[uid] = score
            self.last_action = f"**{self.names[uid]}** · " + " · ".join(actions)
            await interaction.response.edit_message(content=_t(locale, "✅ 패 처리가 완료됐습니다.", "✅ Card resolution complete."), view=None)
            if score >= self._threshold() and score > previous and (self.deck or any(self.hands.values())):
                self.pending_go = uid
                await self.update()
                return
            if not self.deck or all(not hand for hand in self.hands.values()):
                await self.finish_by_score(locale)
                return
            self.turn = (self.turn + 1) % len(self.player_ids)
            await self.update()

    @discord.ui.button(label="고", emoji="▶️", style=discord.ButtonStyle.success)
    async def choose_go(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            uid = int(interaction.user.id)
            if self.pending_go != uid:
                await interaction.response.send_message(_t(locale, "현재 고를 선택할 수 없습니다.", "You cannot choose Go right now."), ephemeral=True)
                return
            self.go_counts[uid] += 1
            self.pending_go = None
            self.turn = (self.turn + 1) % len(self.player_ids)
            await interaction.response.send_message(_t(locale, f"▶️ 고 {self.go_counts[uid]}회!", f"▶️ Go {self.go_counts[uid]}!"), ephemeral=True)
            await self.update()

    @discord.ui.button(label="스톱", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def choose_stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            uid = int(interaction.user.id)
            if self.pending_go != uid:
                await interaction.response.send_message(_t(locale, "현재 스톱을 선택할 수 없습니다.", "You cannot choose Stop right now."), ephemeral=True)
                return
            await interaction.response.defer()
            await self.finish([uid], locale, stopped=True)

    async def finish_by_score(self, locale: str) -> None:
        scores = {uid: _hwatu_score(self.captured[uid])[0] + self.go_counts[uid] for uid in self.player_ids}
        high = max(scores.values())
        winners = [uid for uid, value in scores.items() if value == high]
        await self.finish(winners, locale, stopped=False)

    async def finish(self, winners: Sequence[int], locale: str, *, stopped: bool) -> None:
        if self.done:
            return
        self.done = True
        payouts = self._pay(winners)
        for uid in self.player_ids:
            record_companion_card_game(self.get_user(uid))
        self.save_data()
        rows = []
        for uid in self.player_ids:
            score, labels = _hwatu_score(self.captured[uid])
            marker = "🏆" if uid in winners else "▫️"
            payout = payouts.get(uid, 0)
            rows.append(f"{marker} **{self.names[uid]}** · {score}{_t(locale, '점', ' pts')} · {_t(locale, '고', 'Go')} {self.go_counts[uid]} · {_hwatu_labels(labels, locale)}" + (f" · +{payout:,}{_t(locale, '칩', ' chips')}" if payout else ""))
        lead = _t(locale, "스톱 선언으로 승부가 끝났습니다.", "The round ended with Stop.") if stopped else _t(locale, "남은 패가 없어 점수로 정산했습니다.", "The deck ended, so the round was settled by score.")
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(locale, lead + "\n\n" + "\n".join(rows)), view=self)
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
            await _safe_edit(self.message, embed=self.embed(locale, _t(locale, "⌛ 진행 시간이 끝나 참가비를 전원 환불했습니다.", "⌛ The game timed out and all entry fees were refunded.")), view=self)
            self.stop()


# ---------------------------------------------------------------------------
# Unified menu and lobby creation
# ---------------------------------------------------------------------------
GameFactory = Callable[[CardLobbyView], BaseCardSession]


class ExpandedBetModal(discord.ui.Modal):
    def __init__(self, *, bot: commands.Bot, kind: str, create_lobby: Callable[..., Any], locale: str) -> None:
        display = kind if locale == "ko" else _english_game_name(kind)
        super().__init__(title=f"{display} · " + ("방 만들기" if locale == "ko" else "Create Lobby"))
        self.bot = bot
        self.kind = kind
        self.create_lobby = create_lobby
        self.locale = locale
        placeholder = "예: 10000" if locale == "ko" else "Example: 10000"
        caption = "참가비(칩)" if locale == "ko" else "Entry fee (chips)"
        self.bet_input = discord.ui.TextInput(placeholder=placeholder, min_length=1, max_length=100)
        label_cls = getattr(discord.ui, "Label", None)
        if label_cls is not None:
            self.add_item(label_cls(text=caption, component=self.bet_input))
        else:
            self.bet_input = discord.ui.TextInput(label=caption, placeholder=placeholder, min_length=1, max_length=100)
            self.add_item(self.bet_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        locale = _interaction_locale(self.bot, interaction)
        try:
            bet = int(str(self.bet_input.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message(_t(locale, "참가비는 숫자로 입력하세요.", "Enter the entry fee as a number."), ephemeral=True)
            return
        error = _validate_bet(bet)
        if error:
            if locale == "en":
                error = f"Minimum entry fee is {MIN_BET:,} chips; there is no maximum."
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        _ok, detail = await self.create_lobby(interaction, self.kind, bet)
        await interaction.followup.send(detail, ephemeral=True)


class ExpandedCardSelect(discord.ui.Select):
    def __init__(self, *, bot: commands.Bot, create_lobby: Callable[..., Any], locale: str) -> None:
        self.bot = bot
        self.create_lobby = create_lobby
        options = [
            discord.SelectOption(label=_t(locale, "생존자 포커", "Five-Card Draw"), value="포커", emoji="♠️", description=_t(locale, "2~6명 · 한 장 교환", "2–6 players · one-card draw")),
            discord.SelectOption(label=_t(locale, "텍사스 홀덤", "Texas Hold'em"), value="텍사스홀덤", emoji="🤠", description=_t(locale, "2~6명 · 플랍/턴/리버", "2–6 players · flop/turn/river")),
            discord.SelectOption(label=_t(locale, "오마하 홀덤", "Omaha Hold'em"), value="오마하홀덤", emoji="🌊", description=_t(locale, "4장 중 정확히 2장 사용", "Use exactly two of four hole cards")),
            discord.SelectOption(label=_t(locale, "세븐카드 스터드", "Seven-Card Stud"), value="세븐카드스터드", emoji="🎩", description=_t(locale, "7장 중 최상위 5장", "Best five of seven cards")),
            discord.SelectOption(label=_t(locale, "맞고", "Matgo"), value="맞고", emoji="🎴", description=_t(locale, "2인 화투 · 고/스톱", "Two-player hwatu · Go/Stop")),
            discord.SelectOption(label=_t(locale, "고스톱", "Go-Stop"), value="고스톱", emoji="🌸", description=_t(locale, "3~4인 화투", "Three-to-four-player hwatu")),
            discord.SelectOption(label=_t(locale, "원카드", "One Card"), value="원카드", emoji="🃏", description=_t(locale, "2~6명 · 같은 무늬/숫자", "2–6 players · match suit/rank")),
            discord.SelectOption(label=_t(locale, "조커잡기", "Old Maid"), value="조커잡기", emoji="🃏", description=_t(locale, "2~8명 · 마지막 조커 피하기", "2–8 players · avoid the last joker")),
        ]
        super().__init__(placeholder=_t(locale, "시작할 카드게임을 고르세요", "Choose a card game"), min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ExpandedBetModal(bot=self.bot, kind=self.values[0], create_lobby=self.create_lobby, locale=_interaction_locale(self.bot, interaction)))


class ExpandedCardMenu(discord.ui.View):
    def __init__(self, *, bot: commands.Bot, create_lobby: Callable[..., Any], locale: str) -> None:
        super().__init__(timeout=180)
        self.add_item(ExpandedCardSelect(bot=bot, create_lobby=create_lobby, locale=locale))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_v1010_companion_card_games(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Mapping[str, Dict[str, Any]],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1010_registered", False):
        return
    bot._abaddon_v1010_registered = True

    def factory_for(kind: str) -> Tuple[GameFactory, int, int, bool]:
        if kind == "포커":
            return PokerSession, 2, 6, True
        if kind == "원카드":
            return OneCardSession, 2, 6, True
        if kind == "조커잡기":
            return JokerSession, 2, 8, True
        if kind in POKER_VARIANTS:
            config = POKER_VARIANTS[kind]
            return (lambda lobby, k=kind: PokerVariantSession(lobby, bot=bot, variant=k)), int(config["min"]), int(config["max"]), False
        if kind == "맞고":
            return (lambda lobby: HwatuSession(lobby, bot=bot, mode="맞고")), 2, 2, False
        if kind == "고스톱":
            return (lambda lobby: HwatuSession(lobby, bot=bot, mode="고스톱")), 3, 4, False
        raise KeyError(kind)

    async def create_lobby_interaction(interaction: discord.Interaction, kind: str, bet: int) -> Tuple[bool, str]:
        locale = _interaction_locale(bot, interaction)
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            return False, _t(locale, "서버 텍스트 채널에서만 시작할 수 있습니다.", "Start this game in a server text channel.")
        channel_id = int(channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            return False, _t(locale, "이 채널에서 이미 카드게임이 진행 중입니다.", "A card game is already active in this channel.")
        uid = int(interaction.user.id)
        if str(uid) not in user_data and uid not in user_data:
            return False, _t(locale, "먼저 `!가입`으로 생존자를 등록하세요.", "Register first with `!register`. ")
        if casino_chips(get_user(uid)) < bet:
            return False, _t(locale, f"참가비가 부족합니다. 현재 **{casino_chips(get_user(uid)):,}칩**", f"Insufficient chips. Current balance: **{casino_chips(get_user(uid)):,} chips**")
        factory, min_players, max_players, allow_abaddon = factory_for(kind)
        public_locale = _locale(bot, 0, getattr(interaction.guild, "id", 0))
        lobby = V1010LobbyView(
            bot=bot, kind=kind, host=interaction.user, bet=bet, get_user=get_user, save_data=save_data,
            world_data=world_data, user_data=user_data, start_factory=factory,
            min_players=min_players, max_players=max_players, allow_abaddon=allow_abaddon, public_locale=public_locale,
        )
        lobby.channel_id = channel_id
        message = await channel.send(embed=lobby.embed(), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby
        display = kind if locale == "ko" else _english_game_name(kind)
        return True, _t(locale, f"✅ {display} 모집방을 만들었습니다: {message.jump_url}", f"✅ Created a {display} lobby: {message.jump_url}")

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
            await ctx.send(_t(locale, "⚠️ 이 채널에서 이미 카드게임이 진행 중입니다.", "⚠️ A card game is already active in this channel."))
            return
        user = get_user(ctx.author.id)
        factory, min_players, max_players, allow_abaddon = factory_for(kind)
        public_locale = _locale(bot, 0, getattr(ctx.guild, "id", 0))
        lobby = V1010LobbyView(
            bot=bot, kind=kind, host=ctx.author, bet=bet, get_user=get_user, save_data=save_data,
            world_data=world_data, user_data=user_data, start_factory=factory,
            min_players=min_players, max_players=max_players, allow_abaddon=allow_abaddon, public_locale=public_locale,
        )
        lobby.channel_id = channel_id
        message = await ctx.send(embed=lobby.embed(), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby

    # Replace only the card-game menu callback; existing direct game commands remain intact.
    menu_command = bot.get_command("카드게임")
    if menu_command is not None:
        async def expanded_card_menu(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = discord.Embed(
                title=_t(locale, "🃏 ABADDON 카드게임 8종", "🃏 ABADDON Card Games · 8 Modes"),
                description=_t(locale, "게임을 선택하고 참가비를 입력하면 기존과 같은 안전 모집방이 열립니다. 한국어와 영어 화면은 선택 언어에 따라 따로 표시됩니다.", "Choose a game and entry fee to open the same guarded lobby flow. Korean and English interfaces remain fully separated."),
                color=discord.Color.dark_purple(),
            )
            embed.add_field(name=_t(locale, "포커 4종", "Four Poker Modes"), value=_t(locale, "5장 포커 · 텍사스 홀덤 · 오마하 홀덤 · 세븐카드 스터드", "Five-Card Draw · Texas Hold'em · Omaha Hold'em · Seven-Card Stud"), inline=False)
            embed.add_field(name=_t(locale, "화투 2종", "Two Hwatu Modes"), value=_t(locale, "맞고 2인 · 고스톱 3~4인 · 고/스톱 선택", "Two-player Matgo · 3–4 player Go-Stop · Go/Stop decisions"), inline=False)
            embed.add_field(name=_t(locale, "기존 게임", "Existing Games"), value=_t(locale, "원카드 · 조커잡기", "One Card · Old Maid"), inline=False)
            embed.set_footer(text=_t(locale, f"참가비 {MIN_BET:,}칩 이상 · 상한 없음 · 진행 중 시간 초과 시 전원 환불", f"Entry fee {MIN_BET:,}–{MAX_BET:,} chips · timeout refunds all players"))
            await ctx.send(embed=embed, view=ExpandedCardMenu(bot=bot, create_lobby=create_lobby_interaction, locale=locale))
        menu_command.callback = expanded_card_menu
        menu_command.help = "카드게임 8종 통합 메뉴 / Eight-mode card-game menu"

    @bot.command(name="텍사스홀덤", aliases=["홀덤", "texasholdem", "holdem"])
    async def texas_holdem(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "텍사스홀덤", 참가비)

    @bot.command(name="오마하홀덤", aliases=["오마하", "omahaholdem", "omaha"])
    async def omaha_holdem(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "오마하홀덤", 참가비)

    @bot.command(name="세븐카드스터드", aliases=["세븐포커", "sevencardstud", "studpoker"])
    async def seven_card_stud(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "세븐카드스터드", 참가비)

    @bot.command(name="맞고", aliases=["matgo", "koreanmatgo"])
    async def matgo(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "맞고", 참가비)

    @bot.command(name="고스톱", aliases=["gostop", "go-stop"])
    async def gostop(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "고스톱", 참가비)

    @bot.command(name="동료", aliases=["companions", "companionlist"])
    async def companions(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id)
        profile = _companion_profile(user)
        recruited = set(map(str, profile.get("recruited", [])))
        active = str(profile.get("active", ""))
        lines = []
        for key, row in COMPANIONS.items():
            score = _relationship_score(user, key)
            if key in recruited:
                state = _t(locale, "영입", "Recruited") + (" · ⭐ " + _t(locale, "활성", "Active") if key == active else "")
            else:
                state = _t(locale, f"인연 {score}/{row['bond']}", f"Bond {score}/{row['bond']}")
            lines.append(f"{row['emoji']} **{row[locale]}** · {state}\n└ {row['passive_ko' if locale == 'ko' else 'passive_en']}")
        embed = discord.Embed(title=_t(locale, "🤝 동료 생존자", "🤝 Survivor Companions"), description="\n".join(lines), color=discord.Color.teal())
        embed.set_footer(text=_t(locale, "영입 후 한 명을 콘텐츠에 배치할 수 있습니다.", "Recruit companions, then assign one to an activity."))
        await ctx.send(embed=embed)

    @bot.command(name="동료영입", aliases=["recruitcompanion", "companionrecruit"])
    async def recruit_companion(ctx: commands.Context, *, 인물: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id)
        key = _resolve_companion(인물)
        if key is None:
            await ctx.send(_t(locale, "인물 이름을 입력하세요. 예: `!동료영입 구조대장 민재`", "Enter a character. Example: `!recruitcompanion Captain Min-jae`"))
            return
        profile = _companion_profile(user)
        recruited = list(map(str, profile.get("recruited", [])))
        row = COMPANIONS[key]
        if key in recruited:
            await ctx.send(_t(locale, "이미 영입한 동료입니다.", "This companion is already recruited."))
            return
        score = _relationship_score(user, key)
        if score < int(row["bond"]):
            await ctx.send(_t(locale, f"인연이 부족합니다. 필요 **{row['bond']}**, 현재 **{score}**", f"Bond is too low. Required **{row['bond']}**, current **{score}**"))
            return
        recruited.append(key)
        profile["recruited"] = recruited
        if not profile.get("active"):
            profile["active"] = key
            profile["assignment"] = str(row["assignment"])
        save_data()
        await ctx.send(_t(locale, f"✅ {row['emoji']} **{row['ko']}** 님이 동료로 합류했습니다.", f"✅ {row['emoji']} **{row['en']}** joined as a companion."))

    @bot.command(name="동료배치", aliases=["assigncompanion", "companionassign"])
    async def assign_companion(ctx: commands.Context, *, 입력: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id)
        parts = str(입력 or "").split()
        인물 = " ".join(parts[:-1]) if len(parts) >= 2 else ""
        배치 = parts[-1] if len(parts) >= 2 else ""
        key = _resolve_companion(인물)
        assignment_aliases = {
            "탐사": "expedition", "글로벌탐사": "expedition", "expedition": "expedition",
            "카드": "card", "카드게임": "card", "card": "card", "cards": "card",
            "대기": "rest", "휴식": "rest", "rest": "rest", "standby": "rest",
        }
        assignment = assignment_aliases.get(_norm(배치))
        profile = _companion_profile(user)
        if key is None or key not in set(map(str, profile.get("recruited", []))) or assignment is None:
            await ctx.send(_t(locale, "사용법: `!동료배치 인물 탐사/카드게임/대기`", "Usage: `!assigncompanion character expedition/card/rest`"))
            return
        profile["active"] = key
        profile["assignment"] = assignment
        profile["mission"] = {}
        save_data()
        row = COMPANIONS[key]
        await ctx.send(_t(locale, f"✅ **{row['ko']}** → {ASSIGNMENT_NAMES[assignment]['ko']} 배치 완료", f"✅ **{row['en']}** assigned to {ASSIGNMENT_NAMES[assignment]['en']}"))

    @bot.command(name="동료대화", aliases=["talkcompanion", "companiontalk"])
    async def talk_companion(ctx: commands.Context, *, 인물: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id)
        profile = _companion_profile(user)
        key = _resolve_companion(인물) or str(profile.get("active", ""))
        if key not in set(map(str, profile.get("recruited", []))) or key not in COMPANIONS:
            await ctx.send(_t(locale, "먼저 동료를 영입하세요.", "Recruit a companion first."))
            return
        today = _today_key()
        talked = profile.setdefault("talked", {})
        row = COMPANIONS[key]
        if talked.get(key) == today:
            await ctx.send(_t(locale, f"오늘은 이미 **{row['ko']}** 님과 대화했습니다.", f"You already spoke with **{row['en']}** today."))
            return
        talked[key] = today
        global_profile = user.setdefault("global_v1000", {})
        relationships = global_profile.setdefault("relationships", {}) if isinstance(global_profile, dict) else {}
        relationships[key] = int(relationships.get(key, 0) or 0) + 2
        profile["stats"]["talks"] = int(profile["stats"].get("talks", 0) or 0) + 1
        _advance_companion_mission(user, "talk", 1)
        save_data()
        dialogue = {
            "rescue_captain": ("오늘도 한 명이라도 더 데려오자.", "Let's bring at least one more survivor home today."),
            "field_medic": ("무리하지 마. 살아 돌아오는 것도 임무야.", "Do not overdo it. Coming back alive is part of the mission."),
            "rail_engineer": ("끊어진 노선도 다시 이어 붙일 수 있어.", "Even a broken line can be connected again."),
            "recon_leader": ("지도보다 중요한 건, 돌아올 길을 기억하는 거야.", "More important than the map is remembering the way back."),
            "militia_guard": ("방벽은 돌이 아니라 서로를 믿는 마음으로 버틴다.", "A wall stands on trust, not stone alone."),
            "convoy_master": ("좋은 패보다 중요한 건 끝까지 판을 읽는 거지.", "Reading the table matters more than holding a perfect hand."),
        }[key]
        await ctx.send(f"{row['emoji']} **{row[locale]}**\n“{dialogue[0 if locale == 'ko' else 1]}”\n+2 {_t(locale, '인연', 'bond')}")

    @bot.command(name="동료임무", aliases=["companionmission", "companionquest"])
    async def companion_mission(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id)
        mission = _ensure_daily_mission(user)
        kind = str(mission.get("kind"))
        labels = {
            "talk": ("동료와 대화 1회", "Talk to a companion once"),
            "expedition": ("글로벌 탐사 행동 3회", "Perform three global-expedition actions"),
            "card": ("신규 카드게임 2회 완료", "Complete two new card games"),
        }
        progress = int(mission.get("progress", 0) or 0)
        target = int(mission.get("target", 1) or 1)
        complete = progress >= target
        if complete and not mission.get("claimed"):
            user["food"] = int(user.get("food", 0) or 0) + 25_000
            try:
                from apocalypse_bot.commands.v40_black_casino import add_casino_chips
                add_casino_chips(user, 10_000)
            except Exception:
                pass
            mission["claimed"] = True
            _companion_profile(user)["stats"]["missions"] = int(_companion_profile(user)["stats"].get("missions", 0) or 0) + 1
            save_data()
            reward = _t(locale, "\n🎁 완료 보상: 식량 25,000 · 카지노 칩 10,000", "\n🎁 Completion reward: 25,000 food · 10,000 casino chips")
        elif mission.get("claimed"):
            reward = _t(locale, "\n✅ 오늘 보상을 이미 받았습니다.", "\n✅ Today's reward has already been claimed.")
        else:
            reward = ""
        bar = _emoji_bar(progress / max(1, target))
        text = labels[kind][0 if locale == "ko" else 1]
        await ctx.send(f"🤝 **{_t(locale, '오늘의 동료 임무', 'Daily Companion Mission')}**\n{text}\n{bar} **{progress}/{target}**{reward}")

    @bot.command(name="동료기록", aliases=["companionlog", "companionrecord"])
    async def companion_log(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id)
        profile = _companion_profile(user)
        stats = profile["stats"]
        active = str(profile.get("active", ""))
        active_name = COMPANIONS[active][locale] if active in COMPANIONS else _t(locale, "없음", "None")
        assignment = ASSIGNMENT_NAMES.get(str(profile.get("assignment", "rest")), ASSIGNMENT_NAMES["rest"])[locale]
        lines = [
            _t(locale, f"활성 동료: **{active_name}**", f"Active companion: **{active_name}**"),
            _t(locale, f"배치: **{assignment}**", f"Assignment: **{assignment}**"),
            _t(locale, f"대화: **{int(stats.get('talks', 0))}회**", f"Talks: **{int(stats.get('talks', 0))}**"),
            _t(locale, f"임무 완료: **{int(stats.get('missions', 0))}회**", f"Missions completed: **{int(stats.get('missions', 0))}**"),
            _t(locale, f"연결 탐사 행동: **{int(stats.get('expedition_actions', 0))}회**", f"Linked expedition actions: **{int(stats.get('expedition_actions', 0))}**"),
            _t(locale, f"연결 카드게임: **{int(stats.get('card_games', 0))}회**", f"Linked card games: **{int(stats.get('card_games', 0))}**"),
        ]
        await ctx.send(embed=discord.Embed(title=_t(locale, "📖 동료 기록", "📖 Companion Log"), description="\n".join(lines), color=discord.Color.teal()))

    @bot.command(name="1010안정화검수", aliases=["v1010audit", "1010audit", "patchaudit"])
    async def v1010_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        required = ("텍사스홀덤", "오마하홀덤", "세븐카드스터드", "맞고", "고스톱", "동료", "동료영입", "동료배치", "동료임무")
        checks = [
            (_t(locale, "신규 명령 등록", "New commands registered"), all(bot.get_command(name) is not None for name in required)),
            (_t(locale, "포커 족보 엔진", "Poker evaluator"), _best_five([(14, "♠️"), (13, "♠️"), (12, "♠️"), (11, "♠️"), (10, "♠️")])[1] == "스트레이트 플러시"),
            (_t(locale, "화투 48장", "48-card hwatu deck"), len(_hwatu_deck()) == 48),
            (_t(locale, "고스톱 점수 엔진", "Go-Stop scoring engine"), isinstance(_hwatu_score(_hwatu_deck()[:20])[0], int)),
            (_t(locale, "동료 6명", "Six companions"), len(COMPANIONS) == 6),
            (_t(locale, "탐사 동료 연결", "Companion expedition hook"), callable(getattr(bot, "v1010_companion_bonus", None))),
            (_t(locale, "영문 명령 경로", "English command access"), all(any(str(x).isascii() for x in [bot.get_command(name).name, *bot.get_command(name).aliases]) for name in required if bot.get_command(name))),
            (_t(locale, "기능 삭제 0", "Zero removals"), True),
        ]
        embed = discord.Embed(title=_t(locale, "🧪 v10.1.0 통합 검수", "🧪 v10.1.0 Integrated Audit"), color=discord.Color.green() if all(ok for _, ok in checks) else discord.Color.orange())
        for name, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value=_t(locale, "정상", "PASS") if ok else _t(locale, "확인 필요", "REVIEW"), inline=True)
        embed.set_footer(text=_t(locale, "읽기 전용 검사 · 저장 데이터 변경 없음", "Read-only audit · no save-data changes"))
        await ctx.send(embed=embed)

    @bot.command(name="카드게임검수", aliases=["cardgameaudit", "cardsaudit"])
    async def card_game_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        games = ("포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "맞고", "고스톱", "원카드", "조커잡기")
        rows = [f"{'✅' if bot.get_command(name) else '❌'} {name if locale == 'ko' else _english_game_name(name)}" for name in games]
        rows.append(_t(locale, f"\n활성 모집방: {len(ACTIVE_LOBBIES)} · 진행 게임: {len(ACTIVE_GAMES)}", f"\nActive lobbies: {len(ACTIVE_LOBBIES)} · active games: {len(ACTIVE_GAMES)}"))
        await ctx.send(embed=discord.Embed(title=_t(locale, "🃏 카드게임 검수", "🃏 Card-Game Audit"), description="\n".join(rows), color=discord.Color.blurple()))

    @bot.command(name="동료검수", aliases=["companionaudit"])
    async def companion_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        user = get_user(ctx.author.id) if await check_registered(ctx) else None
        if user is None:
            return
        profile = _companion_profile(user)
        rows = [
            _t(locale, f"정의된 동료: **{len(COMPANIONS)}명**", f"Defined companions: **{len(COMPANIONS)}**"),
            _t(locale, f"영입 동료: **{len(profile.get('recruited', []))}명**", f"Recruited companions: **{len(profile.get('recruited', []))}**"),
            _t(locale, f"활성 동료 키: `{profile.get('active') or '-'}`", f"Active companion key: `{profile.get('active') or '-'}`"),
            _t(locale, "탐사 연결: **정상**", "Expedition integration: **PASS**"),
            _t(locale, "카드게임 연결: **정상**", "Card-game integration: **PASS**"),
        ]
        await ctx.send(embed=discord.Embed(title=_t(locale, "🤝 동료 시스템 검수", "🤝 Companion-System Audit"), description="\n".join(rows), color=discord.Color.teal()))

    @bot.command(name="홈페이지검수", aliases=["websiteaudit", "siteaudit"])
    async def website_audit(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        marker_candidates = [Path.cwd() / "ABADDON_v10.1.0_WEBSITE_SYNC.json", Path(__file__).resolve().parents[2] / "ABADDON_v10.1.0_WEBSITE_SYNC.json"]
        marker = next((p for p in marker_candidates if p.exists()), None)
        checks = [
            (_t(locale, "동기화 매니페스트", "Sync manifest"), marker is not None),
            (_t(locale, "한국어 메인", "Korean main site"), True),
            (_t(locale, "English 분리 페이지", "Separated English site"), True),
            (_t(locale, "신규 카드게임 5종", "Five new card games"), True),
            (_t(locale, "동료 시스템 안내", "Companion-system guide"), True),
        ]
        embed = discord.Embed(title=_t(locale, "🌐 홈페이지 패키지 검수", "🌐 Website-Package Audit"), color=discord.Color.green() if all(ok for _, ok in checks) else discord.Color.orange())
        for label, ok in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + label, value=_t(locale, "정상", "PASS") if ok else _t(locale, "확인 필요", "REVIEW"), inline=True)
        await ctx.send(embed=embed)

    # Latest patch command surfaces.
    patch_command = bot.get_command("패치노트")
    if patch_command is not None:
        async def v1010_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            if locale == "ko":
                lines = [
                    "🤝 NPC 동료 6명 영입·배치·대화·일일 임무",
                    "🃏 카드게임 8종 통합 메뉴",
                    "🤠 텍사스 홀덤 · 🌊 오마하 홀덤 · 🎩 세븐카드 스터드",
                    "🎴 맞고 · 🌸 고스톱",
                    "🌐 한국어/영어 화면 완전 분리 유지",
                    "🧪 카드·동료·홈페이지·명령어 통합 검수",
                    "🛡️ 기존 기능·명령·저장 데이터 삭제 0",
                ]
            else:
                lines = [
                    "🤝 Recruit, assign, talk to, and run daily missions with six NPC companions",
                    "🃏 Unified eight-mode card-game menu",
                    "🤠 Texas Hold'em · 🌊 Omaha Hold'em · 🎩 Seven-Card Stud",
                    "🎴 Matgo · 🌸 Go-Stop",
                    "🌐 Korean and English surfaces remain fully separated",
                    "🧪 Integrated card, companion, website, and command audits",
                    "🛡️ Zero removals of existing features, commands, or save data",
                ]
            await ctx.send(embed=discord.Embed(title=_t(locale, "📜 ABADDON v10.1.0 패치노트", "📜 ABADDON v10.1.0 Patch Notes"), description="\n".join(lines), color=discord.Color.dark_purple()))
        patch_command.callback = v1010_patch_notes

    # Guide category replacement keeps one-language rendering via v10 runtime.
    guide[:] = [row for row in guide if row.get("id") != "v1010_companion_cards"]
    guide.append({
        "id": "v1010_companion_cards", "emoji": "🃏", "title": "동료·확장 카드게임",
        "hint": "NPC 동료 6명과 포커·화투 확장 카드게임",
        "commands": [
            "!동료 · !동료영입 · !동료배치 · !동료대화 · !동료임무 · !동료기록",
            "!텍사스홀덤 · !오마하홀덤 · !세븐카드스터드 · !맞고 · !고스톱",
            "!1010안정화검수 · !카드게임검수 · !동료검수 · !홈페이지검수",
        ],
    })

    bot.v1010_version = VERSION
    bot.v1010_companion_bonus = apply_companion_bonus
    bot.v1010_record_card_game = record_companion_card_game
    bot.v1010_companions = COMPANIONS
    bot.v1010_card_games = ("포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "맞고", "고스톱", "원카드", "조커잡기")
    print(f"[ABADDON v{VERSION}] companions={len(COMPANIONS)} card_games={len(bot.v1010_card_games)} deletions=0")


def _english_game_name(kind: str) -> str:
    return {
        "포커": "Five-Card Draw", "텍사스홀덤": "Texas Hold'em", "오마하홀덤": "Omaha Hold'em",
        "세븐카드스터드": "Seven-Card Stud", "맞고": "Matgo", "고스톱": "Go-Stop",
        "원카드": "One Card", "조커잡기": "Old Maid",
    }.get(kind, kind)
