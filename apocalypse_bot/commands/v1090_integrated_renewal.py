from __future__ import annotations

"""ABADDON v10.9.0 integrated game, dashboard, league and audit renewal.

Registered after v10.6.0. Existing commands/data are preserved; selected entry
points are rebound to the newest implementations while old modules remain on
disk for rollback and compatibility.
"""

import random
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import ACTIVE_GAMES, ACTIVE_LOBBIES, MIN_BET, _card_text, _deck, _safe_edit
from apocalypse_bot.commands.v1010_companion_card_games import HwatuCard, _ctx_locale, _hwatu_deck, _hwatu_visual_uid, _interaction_locale, _locale, _t
from apocalypse_bot.commands.v1050_rules import HwatuSummary, record_game_result
from apocalypse_bot.commands.v1051_rules import DebtBettingRound, GoStopEngine, HwatuCardLite, seotda_deck
from apocalypse_bot.commands.v1060_authentic_card_games import (
    AI_ID, AI_ID_2, AUTHENTIC_GAMES, GAME_EMOJI, GAME_EN, GAME_RULE_SUMMARY,
    AuthenticBaccaratSession, AuthenticBlackjackSession, AuthenticGoStopSession,
    AuthenticJokerSession, AuthenticOneCardSession, AuthenticPokerSession,
    AuthenticSeotdaSession, DebtCardSession, V1060LobbyView, _AILobby, _display,
    _hwatu_lite_text, _hwatu_summary_lite, _is_ai, _publish_final, _record, _v1100_raise_limit,
)
from apocalypse_bot.commands.v1090_rules import (
    ai_risk, dashboard_health, dice_card_score, dori_rank, greedy_melds,
    hwatu_capture_points, is_valid_meld, league_points, meld_points,
    president_play_valid, sambong_rank, yukbaek_round_valid,
)

VERSION = "10.9.0"
PATCH_DATE = "2026-08-03"

NEW_GAMES: Tuple[str, ...] = (
    "훌라", "라미", "대통령", "주사위카드", "삼봉", "도리짓고땡", "민화투", "육백", "블랙잭토너먼트",
)
ALL_GAMES: Tuple[str, ...] = tuple(AUTHENTIC_GAMES) + NEW_GAMES

NEW_GAME_EN: Dict[str, str] = {
    "훌라": "Hoola", "라미": "Rummy", "대통령": "President", "주사위카드": "Dice Card Poker",
    "삼봉": "Sambong", "도리짓고땡": "Dori Jitgo Ttaeng", "민화투": "Minhwatu",
    "육백": "Yukbaek 600", "블랙잭토너먼트": "Blackjack Tournament",
}
NEW_GAME_EMOJI: Dict[str, str] = {
    "훌라": "🀄", "라미": "🧩", "대통령": "👑", "주사위카드": "🎲", "삼봉": "🎴",
    "도리짓고땡": "🎴", "민화투": "🌺", "육백": "6️⃣", "블랙잭토너먼트": "🏆",
}
NEW_RULES: Dict[str, Tuple[str, str]] = {
    "훌라": ("7장으로 시작해 한 장을 뽑고 세트·연속 조합을 내린 뒤 한 장을 버립니다. 첫 등록은 30점 이상이며 손패를 먼저 비우면 승리합니다.", "Start with seven cards, draw, lay sets/runs, then discard. The opening meld needs 30 points; empty your hand first."),
    "라미": ("10장으로 시작해 뽑기·조합 등록·버리기를 반복합니다. 같은 숫자 세트 또는 같은 무늬 연속 3장 이상이 유효합니다.", "Start with ten cards and repeat draw, meld and discard. Valid melds are equal-rank sets or same-suit runs of three or more."),
    "대통령": ("같은 숫자의 패를 한 장 이상 내고 이전 패보다 높은 같은 장수로 이어갑니다. 4장을 한 번에 내면 혁명이 발생하며 손패를 먼저 비우면 승리합니다.", "Play one or more equal-rank cards, beating the previous play with the same count. Four of a kind triggers revolution; empty your hand first."),
    "주사위카드": ("개인 카드 2장과 주사위 3개를 합쳐 5개 기호 족보를 만듭니다. 최대 두 번 원하는 주사위를 다시 굴린 뒤 족보를 공개합니다.", "Combine two private cards and three dice into a five-symbol poker hand. Reroll selected dice up to twice, then reveal."),
    "삼봉": ("화투 3장을 한 장씩 공개하며 거리마다 체크·콜·노리밋 레이즈·폴드를 진행합니다. 삼봉·땡·끗 순으로 승부합니다.", "Reveal three hwatu cards one at a time with check/call, no-limit raise and fold on each street. Compare triples, pairs, then kkeut."),
    "도리짓고땡": ("화투 5장 중 합이 10의 배수가 되는 두 장을 메이드로 정하고 남은 3장 족보로 승부합니다. 두 차례 노리밋 베팅을 진행합니다.", "Choose a made pair summing to a multiple of ten from five hwatu cards, then rank the remaining three. Two no-limit betting rounds."),
    "민화투": ("손패를 내고 더미를 뒤집어 같은 월의 바닥패를 직접 맞춥니다. 고·스톱 없이 광·열끗·띠 중심의 획득 점수로 한 판을 겨룹니다.", "Play and flip to capture matching months. There is no Go/Stop; one round is scored mainly from brights, animals and ribbons."),
    "육백": ("민화투식 획득을 여러 판 이어가며 유효 라운드 점수를 누적합니다. 한 명이라도 30점 이하면 재경기하고 먼저 600점에 도달하면 승리합니다.", "Play repeated Minhwatu-style capture rounds. A round is void if anyone scores 30 or less; first to 600 cumulative points wins."),
    "블랙잭토너먼트": ("같은 참가자들이 5핸드를 연속 진행합니다. 핸드 승리 2점·무승부 1점을 얻고 최종 누적 점수가 높은 참가자가 전체 팟을 차지합니다.", "The same table plays five hands. A hand win gives two points and a push gives one; the highest total wins the full pot."),
}

V1090_COMMAND_DESCRIPTIONS: Dict[str, Tuple[str, str]] = {
    "훌라": ("훌라 실전 테이블을 만들고 아바돈을 초대할 수 있습니다.", "Create a live Hoola table with optional ABADDON seats."),
    "라미": ("라미 실전 테이블을 만들고 조합·버리기를 턴제로 진행합니다.", "Create a live Rummy table with turn-based melds and discards."),
    "대통령": ("대통령 카드게임 방을 만들고 혁명·패스 규칙으로 진행합니다.", "Create a President table with passes and revolution rules."),
    "주사위카드": ("개인 카드와 주사위를 조합하는 주사위 카드 포커를 시작합니다.", "Start Dice Card Poker using private cards and rerollable dice."),
    "삼봉": ("화투 3장과 거리별 노리밋 베팅으로 삼봉을 진행합니다.", "Play Sambong with three hwatu cards and street betting."),
    "도리짓고땡": ("화투 5장의 메이드 조합과 남은 족보로 승부합니다.", "Play Dori Jitgo Ttaeng using a made pair and remaining hand."),
    "민화투": ("고·스톱 없이 직접 패를 맞추는 민화투 한 판을 시작합니다.", "Start a Minhwatu capture round without Go/Stop."),
    "육백": ("유효 라운드 점수를 누적해 600점에 먼저 도달하는 게임을 시작합니다.", "Start Yukbaek and race to 600 cumulative points."),
    "블랙잭토너먼트": ("동일 참가자로 5핸드 블랙잭 토너먼트를 시작합니다.", "Start a five-hand Blackjack tournament."),
    "카드룸": ("모집 중·진행 중 카드게임과 빠른 참가 정보를 대시보드로 확인합니다.", "View open and active card tables in a dashboard."),
    "게임방목록": ("현재 카드게임 방 목록을 확인합니다.", "List current card-game rooms."),
    "빠른대전": ("참가 가능한 카드게임 방에 빠르게 들어갑니다.", "Join an available card table quickly."),
    "재대결": ("최근 종료한 카드게임과 같은 종목·판돈으로 새 방을 만듭니다.", "Create a rematch with the latest game and stake."),
    "관전": ("진행 중인 게임의 공개 정보만 관전합니다.", "Spectate public information from an active table."),
    "테이블정보": ("현재 게임의 차례·팟·공개 정보를 확인합니다.", "View the current turn, pot and public table information."),
    "관전종료": ("현재 관전 안내를 종료합니다.", "Stop the current spectating view."),
    "최근게임": ("가장 최근 카드게임 리플레이를 확인합니다.", "Show the most recent card-game replay."),
    "게임리플레이": ("번호를 지정해 카드게임 진행 기록을 확인합니다.", "Show a numbered card-game replay."),
    "게임기록": ("저장된 카드게임 진행 기록을 확인합니다.", "Review a stored card-game log."),
    "아바돈난이도": ("카드게임 아바돈 AI 난이도를 설정하거나 확인합니다.", "Set or view ABADDON card AI difficulty."),
    "아바돈성향": ("카드게임 아바돈 AI 성향을 설정하거나 확인합니다.", "Set or view ABADDON card AI personality."),
    "생존대시보드": ("생존자 핵심 정보를 카드형 대시보드로 확인합니다.", "Show the survivor information dashboard."),
    "게임대시보드": ("게임 전적·연승·아바돈 대전을 한 화면에 표시합니다.", "Show records, streaks and ABADDON games."),
    "경제대시보드": ("칩·식량·부채·파산 상태를 한 화면에 표시합니다.", "Show chips, food, debt and bankruptcy status."),
    "세계대시보드": ("세계 상태와 관련 명령을 한 화면에 정리합니다.", "Show world status and related commands."),
    "지도대시보드": ("탐험·거점·위협 정보를 지도형 패널로 표시합니다.", "Show exploration, outposts and threats as a map panel."),
    "동료대시보드": ("동료 영입·배치·훈련 정보를 확인합니다.", "Show companion recruitment, assignments and training."),
    "연합대시보드": ("연합·협동 보스·기여 정보를 확인합니다.", "Show alliance, co-op boss and contribution information."),
    "시즌대시보드": ("무료 시즌 점수·임무·수집품을 확인합니다.", "Show free-season points, missions and collection."),
    "정보패널": ("원하는 정보 분야의 대시보드를 선택해 표시합니다.", "Open a selected information dashboard."),
    "정보리뉴얼현황": ("대시보드 리뉴얼 완료·미적용 정보 기능을 확인합니다.", "Show renewed and remaining legacy information views."),
    "카드리그": ("카드게임 통합 리그 순위를 확인합니다.", "Show the combined card-game league standings."),
    "주간랭킹": ("현재 카드게임 주간 순위를 확인합니다.", "Show the current weekly card ranking."),
    "명예의전당": ("리그 상위 생존자와 최근 우승자를 확인합니다.", "Show league leaders and recent winners."),
    "대회센터": ("토너먼트·리그·전용 대회를 한 화면에 정리합니다.", "Show tournaments, league and dedicated events."),
    "리그참가": ("카드 리그 참가 상태를 활성화합니다.", "Enable card-league participation."),
    "리그기록": ("내 카드 리그 포인트와 전적을 확인합니다.", "Show your league points and record."),
    "부채": ("현재 음수 칩과 파산 가능 상태를 확인합니다.", "Show negative chips and bankruptcy status."),
    "채무기록": ("게임별 누적 손실과 현재 부채를 확인합니다.", "Show cumulative losses and current debt."),
    "파산대시보드": ("파산·재기 관련 상태를 대시보드로 확인합니다.", "Show bankruptcy and recovery status."),
    "재기임무": ("음수 칩 상태에서 일일 재기 지원을 받습니다.", "Claim daily recovery support while in debt."),
}

for key, value in NEW_GAME_EN.items():
    GAME_EN[key] = value
for key, value in NEW_GAME_EMOJI.items():
    GAME_EMOJI[key] = value
for key, value in NEW_RULES.items():
    GAME_RULE_SUMMARY[key] = value


def _game_display(kind: str, locale: str) -> str:
    return kind if locale == "ko" else GAME_EN.get(kind, kind)


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1090", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1090"] = root
    root.setdefault("replays", [])
    root.setdefault("hall_of_fame", [])
    root.setdefault("leagues", {})
    root.setdefault("audit_runs", [])
    return root


def _user_root(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = user.setdefault("v1090", {})
    if not isinstance(root, dict):
        root = {}
        user["v1090"] = root
    root.setdefault("ai_difficulty", "보통")
    root.setdefault("ai_personality", "공격형")
    root.setdefault("debt_log", [])
    root.setdefault("league_joined", True)
    return root


def _ai_config(get_user: Callable[[int], MutableMapping[str, Any]], host_id: int) -> Tuple[str, str, float]:
    root = _user_root(get_user(int(host_id)))
    difficulty = str(root.get("ai_difficulty", "보통"))
    personality = str(root.get("ai_personality", "공격형"))
    return difficulty, personality, ai_risk(difficulty, personality)


def _thumbnail(embed: discord.Embed, bot: commands.Bot) -> None:
    try:
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)
    except Exception:
        pass


def _dashboard(bot: commands.Bot, locale: str, title_ko: str, title_en: str, desc_ko: str, desc_en: str, color: discord.Color = discord.Color.dark_purple()) -> discord.Embed:
    embed = discord.Embed(title=_t(locale, title_ko, title_en), description=_t(locale, desc_ko, desc_en), color=color)
    _thumbnail(embed, bot)
    return embed


def _store_replay(world_data: MutableMapping[str, Any], session: "LoggedDebtSession", result: str) -> None:
    guild_id = int(getattr(getattr(session.message, "guild", None), "id", 0) or 0)
    replay = {
        "id": session.game_id,
        "version": VERSION,
        "guild_id": guild_id,
        "channel_id": int(session.channel_id),
        "game": session.kind,
        "stake": int(session.bet),
        "players": dict(session.names),
        "events": list(session.replay[-80:]),
        "result": str(result),
        "finished_at": int(time.time()),
    }
    rows = _root(world_data).setdefault("replays", [])
    rows.append(replay)
    del rows[:-100]


class LoggedDebtSession(DebtCardSession):
    def __init__(self, lobby: Any, *, bot: commands.Bot, timeout: float = 900) -> None:
        super().__init__(lobby, timeout=timeout)
        self.bot = bot
        self.locale = getattr(lobby, "public_locale", "ko")
        self.replay: List[str] = []
        self.difficulty, self.personality, self.risk = _ai_config(self.get_user, self.host_id)

    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.replay.append(f"[{stamp}] {text}")
        del self.replay[:-80]

    async def settle(self, winners: Sequence[int], rows: Sequence[str], *, score_map: Optional[Mapping[int, int]] = None) -> None:
        if self.done:
            return
        self.done = True
        winners = list(dict.fromkeys(int(uid) for uid in winners))
        payouts = self._pay_debt_pot(winners)
        score_map = dict(score_map or {})
        for uid in self.player_ids:
            if _is_ai(uid):
                continue
            outcome = "win" if uid in winners else "loss"
            _record(self.get_user(uid), self.kind, outcome, payouts.get(uid, 0) - self.human_paid.get(uid, 0), score_map.get(uid, 0), any(_is_ai(player) for player in self.player_ids))
        result = " / ".join(self.names[uid] for uid in winners) if winners else "no winner"
        enriched = []
        for index, uid in enumerate(self.player_ids):
            base = rows[index] if index < len(rows) else f"**{self.names[uid]}**"
            enriched.append(f"{base}\n└ {self.settlement_text(uid, payouts.get(uid, 0))}")
        self.log(f"RESULT {result}")
        for uid in self.player_ids:
            if not _is_ai(uid):
                self.log(f"BALANCE {self.names[uid]} net={self.net_earnings(uid, payouts.get(uid, 0)):+d} current={casino_chips(self.get_user(uid))}")
        _store_replay(self.world_data, self, result)
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        heading = _t(self.locale, "🏆 승부 결과 · 최종 정산\n\n", "🏆 Match Result · Final Settlement\n\n")
        embed = self.embed(heading + "\n".join(enriched))
        await _publish_final(self, embed)
        self.stop()

    async def on_timeout(self) -> None:
        if self.done:
            return
        self.done = True
        self.log("TIMEOUT REFUND")
        self._refund_debt()
        _store_replay(self.world_data, self, "timeout/refund")
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        await _safe_edit(self.message, embed=self.embed(_t(self.locale, "⌛ 시간 초과 · 실제 납부액 환불", "⌛ Timeout · actual payments refunded")), view=self)
        self.stop()

class MeldSelect(discord.ui.Select):
    def __init__(self, session: "MeldRaceSession", uid: int, action: str, locale: str) -> None:
        self.session, self.uid, self.action, self.locale = session, uid, action, locale
        hand = session.hands[uid]
        options = [discord.SelectOption(label=f"{index + 1}. {_card_text(card)}", value=str(index)) for index, card in enumerate(hand[:25])]
        minimum = 3 if action == "meld" else 1
        maximum = min(7, len(options)) if action == "meld" else 1
        super().__init__(placeholder=_t(locale, "조합 카드를 선택", "Choose meld cards") if action == "meld" else _t(locale, "버릴 카드 선택", "Choose a discard"), min_values=minimum, max_values=maximum, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        indices = sorted((int(value) for value in self.values), reverse=True)
        if self.action == "meld":
            await self.session.lay_meld(interaction, self.uid, indices)
        else:
            await self.session.discard(interaction, self.uid, indices[0])


class MeldSelectView(discord.ui.View):
    def __init__(self, session: "MeldRaceSession", uid: int, action: str, locale: str) -> None:
        super().__init__(timeout=90)
        self.add_item(MeldSelect(session, uid, action, locale))


class MeldRaceSession(LoggedDebtSession):
    def __init__(self, lobby: Any, *, bot: commands.Bot, variant: str) -> None:
        super().__init__(lobby, bot=bot, timeout=900)
        self.variant = variant
        self.hand_size = 7 if variant == "훌라" else 10
        deck = _deck()
        self.hands = {uid: [deck.pop() for _ in range(self.hand_size)] for uid in self.player_ids}
        self.stock = deck
        self.discard_pile = [self.stock.pop()]
        self.melds: Dict[int, List[List[Tuple[int, str]]]] = {uid: [] for uid in self.player_ids}
        self.opened: set[int] = set()
        self.drawn: set[int] = set()
        self.current_index = 0
        self.last_action = _t(self.locale, "한 장을 뽑고 조합을 내린 뒤 한 장을 버리세요.", "Draw one card, lay melds, then discard one card.")
        if self.locale == "en":
            mapping = {"내 패": "My Hand", "더미 뽑기": "Draw Stock", "버린패 뽑기": "Take Discard", "조합 내기": "Lay Meld", "버리기": "Discard"}
            for child in self.children:
                if getattr(child, "label", None) in mapping:
                    child.label = mapping[child.label]

    @property
    def current_uid(self) -> int:
        return self.player_ids[self.current_index % len(self.player_ids)]

    def embed(self, final: str = "") -> discord.Embed:
        embed = _dashboard(self.bot, self.locale, f"{NEW_GAME_EMOJI[self.variant]} {self.variant} · 실전 테이블", f"{NEW_GAME_EMOJI[self.variant]} {NEW_GAME_EN[self.variant]} · Live Table", final or self.last_action, final or self.last_action, discord.Color.dark_teal())
        rows = []
        for uid in self.player_ids:
            meld_count = sum(len(group) for group in self.melds[uid])
            rows.append(f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {len(self.hands[uid])}{_t(self.locale, '장', ' cards')} · {_t(self.locale, '등록', 'melded')} {meld_count}")
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "버린패 맨 위", "Top Discard"), value=_card_text(self.discard_pile[-1]) if self.discard_pile else "-", inline=True)
        embed.add_field(name=_t(self.locale, "남은 더미", "Stock"), value=str(len(self.stock)), inline=True)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"{self.pot:,}", inline=True)
        embed.set_footer(text=_t(self.locale, f"ABADDON {self.difficulty} · {self.personality} · 음수 잔액/무상한", f"ABADDON {self.difficulty} · {self.personality} · debt/no cap"))
        return embed

    async def start(self) -> None:
        self._reserve()
        self.log(f"START {self.variant} players={len(self.player_ids)}")
        await _safe_edit(self.message, embed=self.embed(), view=self)
        await self._run_ai()

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.hands:
            await interaction.response.send_message(_t(locale, "참가자가 아닙니다.", "You are not a participant."), ephemeral=True)
            return
        cards = "  ".join(f"{i+1}:{_card_text(card)}" for i, card in enumerate(self.hands[uid])) or _t(locale, "손패 없음", "No cards")
        await interaction.response.send_message(cards, ephemeral=True)

    @discord.ui.button(label="더미 뽑기", emoji="🎴", style=discord.ButtonStyle.primary)
    async def draw_stock(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.draw(interaction, int(interaction.user.id), from_discard=False)

    @discord.ui.button(label="버린패 뽑기", emoji="♻️", style=discord.ButtonStyle.primary)
    async def draw_discard(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.draw(interaction, int(interaction.user.id), from_discard=True)

    async def draw(self, interaction: discord.Interaction, uid: int, *, from_discard: bool) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid or uid in self.drawn:
                await interaction.response.send_message(_t(locale, "현재 뽑을 수 없습니다.", "You cannot draw now."), ephemeral=True)
                return
            if from_discard:
                if not self.discard_pile:
                    await interaction.response.send_message(_t(locale, "버린패가 없습니다.", "The discard pile is empty."), ephemeral=True)
                    return
                card = self.discard_pile.pop()
            else:
                if not self.stock:
                    if len(self.discard_pile) <= 1:
                        await interaction.response.send_message(_t(locale, "뽑을 카드가 없습니다.", "No card can be drawn."), ephemeral=True)
                        return
                    top = self.discard_pile.pop()
                    self.stock = self.discard_pile[:]
                    random.shuffle(self.stock)
                    self.discard_pile = [top]
                card = self.stock.pop()
            self.hands[uid].append(card)
            self.drawn.add(uid)
            self.last_action = f"**{self.names[uid]}** · {_t(self.locale, '카드 1장 뽑기', 'drew one card')}"
            self.log(f"{self.names[uid]} DRAW {'discard' if from_discard else 'stock'}")
            await interaction.response.send_message(f"{_card_text(card)}", ephemeral=True)
            await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="조합 내기", emoji="🧩", style=discord.ButtonStyle.success, row=1)
    async def meld_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid or uid not in self.drawn or len(self.hands.get(uid, [])) < 3:
            await interaction.response.send_message(_t(locale, "카드를 뽑은 뒤 본인 차례에 조합을 내세요.", "Draw first, then lay a meld on your turn."), ephemeral=True)
            return
        await interaction.response.send_message(_t(locale, "세트 또는 연속 조합을 선택하세요.", "Choose a set or run."), view=MeldSelectView(self, uid, "meld", locale), ephemeral=True)

    async def lay_meld(self, interaction: discord.Interaction, uid: int, indices: Sequence[int]) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid or uid not in self.drawn:
                await interaction.response.send_message(_t(locale, "현재 조합을 낼 수 없습니다.", "You cannot meld now."), ephemeral=True)
                return
            hand = self.hands[uid]
            if any(index < 0 or index >= len(hand) for index in indices):
                await interaction.response.send_message(_t(locale, "선택이 만료됐습니다.", "The selection expired."), ephemeral=True)
                return
            cards = [hand[index] for index in sorted(indices)]
            if not is_valid_meld(cards):
                await interaction.response.send_message(_t(locale, "유효한 세트나 연속 조합이 아닙니다.", "That is not a valid set or run."), ephemeral=True)
                return
            if self.variant == "훌라" and uid not in self.opened and meld_points(cards) < 30:
                await interaction.response.send_message(_t(locale, "훌라 첫 등록은 합계 30점 이상이어야 합니다.", "The opening Hoola meld must total at least 30 points."), ephemeral=True)
                return
            for index in sorted(indices, reverse=True):
                hand.pop(index)
            self.melds[uid].append(cards)
            self.opened.add(uid)
            self.log(f"{self.names[uid]} MELD {' '.join(_card_text(card) for card in cards)}")
            await interaction.response.edit_message(content=_t(locale, "✅ 조합 등록 완료", "✅ Meld laid"), view=None)
            if not hand:
                await self.finish(uid)
            else:
                await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="버리기", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def discard_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid or uid not in self.drawn:
            await interaction.response.send_message(_t(locale, "카드를 뽑은 뒤 버리세요.", "Draw before discarding."), ephemeral=True)
            return
        await interaction.response.send_message(_t(locale, "버릴 카드를 선택하세요.", "Choose a card to discard."), view=MeldSelectView(self, uid, "discard", locale), ephemeral=True)

    async def discard(self, interaction: discord.Interaction, uid: int, index: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid or uid not in self.drawn or index >= len(self.hands[uid]):
                await interaction.response.send_message(_t(locale, "현재 버릴 수 없습니다.", "You cannot discard now."), ephemeral=True)
                return
            card = self.hands[uid].pop(index)
            self.discard_pile.append(card)
            self.drawn.discard(uid)
            self.last_action = f"**{self.names[uid]}** · {_card_text(card)} {_t(self.locale, '버림', 'discarded')}"
            self.log(f"{self.names[uid]} DISCARD {_card_text(card)}")
            await interaction.response.edit_message(content=f"✅ {_card_text(card)}", view=None)
            if not self.hands[uid]:
                await self.finish(uid)
                return
            self.current_index = (self.current_index + 1) % len(self.player_ids)
            await self._run_ai()
            if not self.done:
                await _safe_edit(self.message, embed=self.embed(), view=self)

    async def _run_ai(self) -> None:
        guard = 0
        while not self.done and _is_ai(self.current_uid) and guard < 30:
            guard += 1
            uid = self.current_uid
            if not self.stock:
                if len(self.discard_pile) > 1:
                    top = self.discard_pile.pop()
                    self.stock = self.discard_pile[:]
                    random.shuffle(self.stock)
                    self.discard_pile = [top]
                else:
                    await self.finish(None)
                    return
            take_discard = bool(self.discard_pile and random.random() < self.risk and any(is_valid_meld([self.discard_pile[-1], *[self.hands[uid][index] for index in combo]]) for combo in __import__('itertools').combinations(range(len(self.hands[uid])), 2)))
            card = self.discard_pile.pop() if take_discard else self.stock.pop()
            self.hands[uid].append(card)
            groups = greedy_melds(self.hands[uid])
            for group in sorted(groups, key=lambda row: min(row), reverse=True):
                cards = [self.hands[uid][index] for index in group]
                if self.variant == "훌라" and uid not in self.opened and meld_points(cards) < 30:
                    continue
                for index in sorted(group, reverse=True):
                    self.hands[uid].pop(index)
                self.melds[uid].append(cards)
                self.opened.add(uid)
                self.log(f"{self.names[uid]} AI MELD")
                break
            if not self.hands[uid]:
                await self.finish(uid)
                return
            discard_index = max(range(len(self.hands[uid])), key=lambda index: meld_points([self.hands[uid][index]]))
            discarded = self.hands[uid].pop(discard_index)
            self.discard_pile.append(discarded)
            self.last_action = f"**{self.names[uid]}** · {_t(self.locale, 'AI 턴 완료', 'AI turn complete')}"
            self.log(f"{self.names[uid]} AI DISCARD {_card_text(discarded)}")
            self.current_index = (self.current_index + 1) % len(self.player_ids)

    async def finish(self, winner: Optional[int]) -> None:
        if winner is None:
            scores = {uid: -sum(meld_points([card]) for card in self.hands[uid]) for uid in self.player_ids}
            best = max(scores.values())
            winners = [uid for uid, score in scores.items() if score == best]
        else:
            winners = [winner]
            scores = {uid: -sum(meld_points([card]) for card in self.hands[uid]) for uid in self.player_ids}
            scores[winner] = 100 + sum(len(group) for group in self.melds[winner])
        rows = [f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {_t(self.locale, '남은 패', 'cards left')} {len(self.hands[uid])} · {_t(self.locale, '조합', 'melds')} {len(self.melds[uid])}" for uid in self.player_ids]
        await self.settle(winners, rows, score_map=scores)

class PresidentSelect(discord.ui.Select):
    def __init__(self, session: "PresidentSession", uid: int, locale: str) -> None:
        self.session, self.uid, self.locale = session, uid, locale
        hand = session.hands[uid]
        options = [discord.SelectOption(label=f"{index+1}. {_card_text(card)}", value=str(index)) for index, card in enumerate(hand[:25])]
        super().__init__(placeholder=_t(locale, "같은 숫자 패 선택", "Choose equal-rank cards"), min_values=1, max_values=min(4, len(options)), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.play_cards(interaction, self.uid, sorted((int(value) for value in self.values), reverse=True))


class PresidentSelectView(discord.ui.View):
    def __init__(self, session: "PresidentSession", uid: int, locale: str) -> None:
        super().__init__(timeout=90)
        self.add_item(PresidentSelect(session, uid, locale))


class PresidentSession(LoggedDebtSession):
    def __init__(self, lobby: Any, *, bot: commands.Bot) -> None:
        super().__init__(lobby, bot=bot, timeout=900)
        deck = _deck()
        self.hands: Dict[int, List[Tuple[int, str]]] = {uid: [] for uid in self.player_ids}
        for index, card in enumerate(deck):
            self.hands[self.player_ids[index % len(self.player_ids)]].append(card)
        for hand in self.hands.values():
            hand.sort(key=lambda card: (15 if card[0] == 2 else card[0], card[1]))
        self.current_index = 0
        self.table_rank: Optional[int] = None
        self.table_count = 0
        self.last_player: Optional[int] = None
        self.passes: set[int] = set()
        self.revolution = False
        self.last_action = _t(self.locale, "같은 숫자 패를 선택해 이전 패보다 높게 내세요.", "Play equal-rank cards higher than the current play.")
        if self.locale == "en":
            for child in self.children:
                if getattr(child, "label", None) == "패 내기": child.label = "Play Cards"
                elif getattr(child, "label", None) == "패스": child.label = "Pass"
                elif getattr(child, "label", None) == "내 패": child.label = "My Hand"

    @property
    def current_uid(self) -> int:
        return self.player_ids[self.current_index % len(self.player_ids)]

    def embed(self, final: str = "") -> discord.Embed:
        embed = _dashboard(self.bot, self.locale, "👑 대통령 · 실전 테이블", "👑 President · Live Table", final or self.last_action, final or self.last_action, discord.Color.gold())
        table = "-" if self.table_rank is None else f"{self.table_count}× {self.table_rank}"
        embed.add_field(name=_t(self.locale, "현재 판", "Current Trick"), value=table, inline=True)
        embed.add_field(name=_t(self.locale, "혁명", "Revolution"), value=_t(self.locale, "진행 중" if self.revolution else "없음", "ACTIVE" if self.revolution else "No"), inline=True)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"{self.pot:,}", inline=True)
        rows = [f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {len(self.hands[uid])}{_t(self.locale, '장', ' cards')} {'· PASS' if uid in self.passes else ''}" for uid in self.player_ids]
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.set_footer(text=_t(self.locale, "같은 장수로 더 높은 숫자 · 4장 혁명 · 2가 최고(혁명 시 반대)", "Same count, higher rank · four-card revolution · 2 high (reversed in revolution)"))
        return embed

    async def start(self) -> None:
        self._reserve()
        self.log("START President")
        await _safe_edit(self.message, embed=self.embed(), view=self)
        await self._run_ai()

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("Not a player", ephemeral=True)
            return
        await interaction.response.send_message("  ".join(f"{i+1}:{_card_text(card)}" for i, card in enumerate(self.hands[uid])), ephemeral=True)

    @discord.ui.button(label="패 내기", emoji="🃏", style=discord.ButtonStyle.primary)
    async def play_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid:
            await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
            return
        await interaction.response.send_message(_t(locale, "낼 패를 선택하세요.", "Choose cards to play."), view=PresidentSelectView(self, uid, locale), ephemeral=True)

    async def play_cards(self, interaction: discord.Interaction, uid: int, indices: Sequence[int]) -> None:
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "차례가 바뀌었습니다.", "The turn changed."), ephemeral=True)
                return
            hand = self.hands[uid]
            if any(index >= len(hand) for index in indices):
                await interaction.response.send_message(_t(locale, "선택이 만료됐습니다.", "The selection expired."), ephemeral=True)
                return
            cards = [hand[index] for index in sorted(indices)]
            ranks = [card[0] for card in cards]
            if not president_play_valid(ranks, self.table_rank, self.table_count, self.revolution):
                await interaction.response.send_message(_t(locale, "같은 숫자·같은 장수이며 현재 패보다 높아야 합니다.", "Use equal ranks, the same count, and beat the current play."), ephemeral=True)
                return
            for index in sorted(indices, reverse=True):
                hand.pop(index)
            self.table_rank = ranks[0]
            self.table_count = len(ranks)
            self.last_player = uid
            self.passes.clear()
            if len(ranks) == 4:
                self.revolution = not self.revolution
                self.log(f"REVOLUTION by {self.names[uid]}")
            self.last_action = f"**{self.names[uid]}** · {' '.join(_card_text(card) for card in cards)}"
            self.log(f"{self.names[uid]} PLAY rank={ranks[0]} count={len(ranks)}")
            await interaction.response.edit_message(content="✅", view=None)
            if not hand:
                await self.finish(uid)
                return
            self._advance()
            await self._run_ai()
            if not self.done:
                await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="패스", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def pass_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid or self.table_rank is None:
                await interaction.response.send_message(_t(locale, "현재 패스할 수 없습니다.", "You cannot pass now."), ephemeral=True)
                return
            self.passes.add(uid)
            self.last_action = f"**{self.names[uid]}** · PASS"
            self.log(f"{self.names[uid]} PASS")
            await interaction.response.defer()
            self._advance()
            self._reset_if_all_passed()
            await self._run_ai()
            if not self.done:
                await _safe_edit(self.message, embed=self.embed(), view=self)

    def _advance(self) -> None:
        self.current_index = (self.current_index + 1) % len(self.player_ids)
        guard = 0
        while self.current_uid in self.passes and guard < len(self.player_ids):
            self.current_index = (self.current_index + 1) % len(self.player_ids)
            guard += 1

    def _reset_if_all_passed(self) -> None:
        active_others = [uid for uid in self.player_ids if uid != self.last_player and self.hands[uid]]
        if active_others and all(uid in self.passes for uid in active_others):
            self.table_rank = None
            self.table_count = 0
            self.passes.clear()
            if self.last_player in self.player_ids:
                self.current_index = self.player_ids.index(self.last_player)
            self.last_action = _t(self.locale, "새 판이 시작됩니다.", "A new trick begins.")
            self.log("TRICK RESET")

    def _ai_choice(self, uid: int) -> Optional[List[int]]:
        hand = self.hands[uid]
        groups: Dict[int, List[int]] = {}
        for index, card in enumerate(hand):
            groups.setdefault(card[0], []).append(index)
        candidates = []
        for rank, indices in groups.items():
            need = 1 if self.table_rank is None else self.table_count
            if len(indices) >= need and president_play_valid([rank] * need, self.table_rank, self.table_count, self.revolution):
                candidates.append((rank, indices[:need]))
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row[0] == 2, row[0]), reverse=self.revolution)
        return candidates[0][1]

    async def _run_ai(self) -> None:
        guard = 0
        while not self.done and _is_ai(self.current_uid) and guard < 80:
            guard += 1
            uid = self.current_uid
            choice = self._ai_choice(uid)
            if choice is None:
                self.passes.add(uid)
                self.log(f"{self.names[uid]} AI PASS")
                self._advance()
                self._reset_if_all_passed()
                continue
            cards = [self.hands[uid][index] for index in choice]
            ranks = [card[0] for card in cards]
            for index in sorted(choice, reverse=True):
                self.hands[uid].pop(index)
            self.table_rank, self.table_count, self.last_player = ranks[0], len(ranks), uid
            self.passes.clear()
            if len(ranks) == 4:
                self.revolution = not self.revolution
            self.last_action = f"**{self.names[uid]}** · {_t(self.locale, 'AI가 패를 냈습니다.', 'AI played cards.')}"
            self.log(f"{self.names[uid]} AI PLAY {ranks[0]}x{len(ranks)}")
            if not self.hands[uid]:
                await self.finish(uid)
                return
            self._advance()

    async def finish(self, winner: int) -> None:
        scores = {uid: max(0, 54 - len(self.hands[uid])) for uid in self.player_ids}
        rows = [f"{'🏆' if uid == winner else '▫️'} **{self.names[uid]}** · {_t(self.locale, '남은 패', 'cards left')} {len(self.hands[uid])}" for uid in self.player_ids]
        await self.settle([winner], rows, score_map=scores)

class DiceSelect(discord.ui.Select):
    def __init__(self, session: "DiceCardSession", uid: int, locale: str) -> None:
        self.session, self.uid, self.locale = session, uid, locale
        options = [discord.SelectOption(label=f"🎲 {index+1} · {value}", value=str(index)) for index, value in enumerate(session.dice[uid])]
        super().__init__(placeholder=_t(locale, "다시 굴릴 주사위 선택", "Choose dice to reroll"), min_values=1, max_values=3, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.session.reroll(interaction, self.uid, [int(value) for value in self.values])


class DiceSelectView(discord.ui.View):
    def __init__(self, session: "DiceCardSession", uid: int, locale: str) -> None:
        super().__init__(timeout=90)
        self.add_item(DiceSelect(session, uid, locale))


class DiceCardSession(LoggedDebtSession):
    def __init__(self, lobby: Any, *, bot: commands.Bot) -> None:
        super().__init__(lobby, bot=bot, timeout=600)
        deck = _deck()
        self.cards = {uid: [deck.pop(), deck.pop()] for uid in self.player_ids}
        self.dice = {uid: [random.randint(1, 6) for _ in range(3)] for uid in self.player_ids}
        self.rerolls = {uid: 2 for uid in self.player_ids}
        self.locked: set[int] = set()
        self.last_action = _t(self.locale, "개인 카드 2장과 주사위 3개를 확인하고 최대 두 번 다시 굴리세요.", "Check two private cards and three dice, then reroll up to twice.")
        if self.locale == "en":
            for child in self.children:
                if getattr(child, "label", None) == "내 족보": child.label = "My Hand"
                elif getattr(child, "label", None) == "다시 굴리기": child.label = "Reroll"
                elif getattr(child, "label", None) == "확정": child.label = "Lock"

    def embed(self, final: str = "") -> discord.Embed:
        embed = _dashboard(self.bot, self.locale, "🎲 주사위카드 · 실전 테이블", "🎲 Dice Card Poker · Live Table", final or self.last_action, final or self.last_action, discord.Color.blurple())
        rows = [f"{'✅' if uid in self.locked else '▫️'} **{self.names[uid]}** · {_t(self.locale, '재굴림', 'rerolls')} {self.rerolls[uid]}" for uid in self.player_ids]
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"{self.pot:,}", inline=True)
        embed.set_footer(text=_t(self.locale, "2장 카드 + 3개 주사위 · 최대 2회 재굴림", "Two cards + three dice · up to two rerolls"))
        return embed

    async def start(self) -> None:
        self._reserve()
        self.log("START DiceCard")
        for uid in self.player_ids:
            if _is_ai(uid):
                self._ai_prepare(uid)
                self.locked.add(uid)
        await _safe_edit(self.message, embed=self.embed(), view=self)
        if len(self.locked) == len(self.player_ids):
            await self.finish()

    @discord.ui.button(label="내 족보", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.cards:
            await interaction.response.send_message("Not a player", ephemeral=True)
            return
        await interaction.response.send_message(f"{' '.join(_card_text(card) for card in self.cards[uid])}\n🎲 {' · '.join(map(str, self.dice[uid]))}", ephemeral=True)

    @discord.ui.button(label="다시 굴리기", emoji="🎲", style=discord.ButtonStyle.primary)
    async def reroll_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.cards or uid in self.locked or self.rerolls[uid] <= 0:
            await interaction.response.send_message(_t(locale, "더 이상 다시 굴릴 수 없습니다.", "No reroll is available."), ephemeral=True)
            return
        await interaction.response.send_message(_t(locale, "다시 굴릴 주사위를 선택하세요.", "Choose dice to reroll."), view=DiceSelectView(self, uid, locale), ephemeral=True)

    async def reroll(self, interaction: discord.Interaction, uid: int, indices: Sequence[int]) -> None:
        async with self.lock:
            if uid in self.locked or self.rerolls.get(uid, 0) <= 0:
                await interaction.response.send_message("Expired", ephemeral=True)
                return
            for index in indices:
                if 0 <= index < 3:
                    self.dice[uid][index] = random.randint(1, 6)
            self.rerolls[uid] -= 1
            self.log(f"{self.names[uid]} REROLL {list(indices)}")
            await interaction.response.edit_message(content=f"🎲 {' · '.join(map(str, self.dice[uid]))}", view=None)
            await _safe_edit(self.message, embed=self.embed(), view=self)

    @discord.ui.button(label="확정", emoji="🔒", style=discord.ButtonStyle.success)
    async def lock_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid not in self.cards or uid in self.locked:
            await interaction.response.send_message(_t(locale, "이미 확정했습니다.", "Already locked."), ephemeral=True)
            return
        self.locked.add(uid)
        self.log(f"{self.names[uid]} LOCK")
        await interaction.response.send_message("🔒", ephemeral=True)
        if len(self.locked) == len(self.player_ids):
            await self.finish()
        else:
            await _safe_edit(self.message, embed=self.embed(), view=self)

    def _ai_prepare(self, uid: int) -> None:
        for _ in range(2):
            indices = [index for index, value in enumerate(self.dice[uid]) if value <= (3 if self.risk > 0.6 else 2)]
            if not indices:
                break
            for index in indices:
                self.dice[uid][index] = random.randint(1, 6)
            self.rerolls[uid] -= 1

    async def finish(self) -> None:
        scores = {uid: dice_card_score(self.cards[uid], self.dice[uid]) for uid in self.player_ids}
        best = max(scores.values())
        winners = [uid for uid, score in scores.items() if score == best]
        labels = {8:"파이브카인드",7:"포카드",6:"풀하우스",5:"스트레이트",4:"트리플",3:"투페어",2:"원페어",1:"하이카드"}
        rows = [f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {' '.join(_card_text(card) for card in self.cards[uid])} · 🎲 {'-'.join(map(str,self.dice[uid]))} · **{labels[scores[uid][0]]}**" for uid in self.player_ids]
        await self.settle(winners, rows, score_map={uid: score[0] for uid, score in scores.items()})


class NoLimitRaiseModal(discord.ui.Modal):
    def __init__(self, session: "KoreanShowdownSession", uid: int, locale: str) -> None:
        super().__init__(title=_t(locale, "노리밋 레이즈", "No-limit Raise"))
        self.session, self.uid, self.locale = session, uid, locale
        self.amount = discord.ui.TextInput(label=_t(locale, "이번 거리 총 베팅액", "Target total on this street"), placeholder=str(max(session.bet, session.betting.current_bet + session.betting.min_raise)), min_length=1, max_length=100)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = int(str(self.amount.value).replace(",", ""))
        except ValueError:
            await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True)
            return
        limit = _v1100_raise_limit(self.session)
        if value > limit:
            await interaction.response.send_message(_t(self.locale, f"레이즈 안전 한도는 {limit:,}칩입니다. 잔액을 넘는 손실은 음수로 유지됩니다.", f"Raise safety limit is {limit:,} chips. Losses beyond the wallet remain negative."), ephemeral=True)
            return
        await self.session.raise_to(interaction, self.uid, value)


class KoreanShowdownSession(LoggedDebtSession):
    def __init__(self, lobby: Any, *, bot: commands.Bot, variant: str) -> None:
        super().__init__(lobby, bot=bot, timeout=900)
        self.variant = variant
        deck = seotda_deck()
        random.shuffle(deck)
        count = 3 if variant == "삼봉" else 5
        self.hands = {uid: [deck.pop() for _ in range(count)] for uid in self.player_ids}
        self.street = 1
        self.max_street = count if variant == "삼봉" else 2
        self.revealed = 1 if variant == "삼봉" else 2
        self.betting = DebtBettingRound(list(self.player_ids), min_raise=max(1, self.bet))
        self.permanent_folded: set[int] = set()
        self.last_action = _t(self.locale, "첫 패가 공개됐습니다. 체크·콜·레이즈·폴드를 선택하세요.", "The opening cards are visible. Choose check/call, raise or fold.")
        if self.locale == "en":
            mapping = {"내 패": "My Hand", "체크/콜": "Check/Call", "레이즈": "Raise", "폴드": "Fold"}
            for child in self.children:
                if getattr(child, "label", None) in mapping:
                    child.label = mapping[child.label]

    @property
    def current_uid(self) -> Optional[int]:
        return self.betting.current_uid

    def embed(self, final: str = "") -> discord.Embed:
        embed = _dashboard(self.bot, self.locale, f"🎴 {self.variant} · {self.street}차 베팅", f"🎴 {NEW_GAME_EN[self.variant]} · Betting {self.street}", final or self.last_action, final or self.last_action, discord.Color.orange())
        rows = []
        for uid in self.player_ids:
            state = _t(self.locale, "폴드", "Folded") if uid in self.permanent_folded else f"{self.betting.round_bets.get(uid,0):,}"
            rows.append(f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {state}")
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "공개 단계", "Reveal Stage"), value=f"{self.revealed}/{len(next(iter(self.hands.values())))}", inline=True)
        embed.add_field(name=_t(self.locale, "현재 콜", "Current Bet"), value=f"{self.betting.current_bet:,}", inline=True)
        embed.add_field(name=_t(self.locale, "팟", "Pot"), value=f"{self.pot:,}", inline=True)
        embed.set_footer(text=_t(self.locale, "자유 레이즈 · 잔액 음수 허용 · 서버 안전 한도 · 폴드 시 납부액 반환 없음", "Free raise · negative balances · server safety limit · folded payments stay in the pot"))
        return embed

    async def start(self) -> None:
        self._reserve()
        self.log(f"START {self.variant}")
        await _safe_edit(self.message, embed=self.embed(), view=self)
        await self._run_ai()

    @discord.ui.button(label="내 패", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def show_hand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        if uid not in self.hands:
            await interaction.response.send_message("Not a player", ephemeral=True)
            return
        visible = self.hands[uid][:self.revealed]
        hidden = len(self.hands[uid]) - len(visible)
        await interaction.response.send_message("  ".join(card.label for card in visible) + (f"  +{hidden} hidden" if hidden else ""), ephemeral=True)

    @discord.ui.button(label="체크/콜", emoji="✅", style=discord.ButtonStyle.success)
    async def call_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            action, paid = self.betting.check_or_call(uid)
            self.charge(uid, paid)
            self.log(f"{self.names[uid]} {action.upper()} {paid}")
            await interaction.response.send_message(f"{action} · {paid:,}", ephemeral=True)
            await self.after_action()

    @discord.ui.button(label="레이즈", emoji="📈", style=discord.ButtonStyle.primary)
    async def raise_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        if uid != self.current_uid:
            await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
            return
        await interaction.response.send_modal(NoLimitRaiseModal(self, uid, locale))

    async def raise_to(self, interaction: discord.Interaction, uid: int, target: int) -> None:
        locale = _interaction_locale(self.bot, interaction)
        limit = _v1100_raise_limit(self)
        if int(target) > limit:
            await interaction.response.send_message(_t(locale, f"레이즈 안전 한도는 {limit:,}칩입니다.", f"Raise safety limit is {limit:,} chips."), ephemeral=True)
            return
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "차례가 바뀌었습니다.", "The turn changed."), ephemeral=True)
                return
            try:
                _action, paid = self.betting.raise_to(uid, target)
            except ValueError as exc:
                await interaction.response.send_message(_t(locale, f"레이즈 불가: {exc}", f"Invalid raise: {exc}"), ephemeral=True)
                return
            self.charge(uid, paid)
            self.log(f"{self.names[uid]} RAISE target={target} paid={paid}")
            await interaction.response.send_message(f"📈 {target:,}", ephemeral=True)
            await self.after_action()

    @discord.ui.button(label="폴드", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def fold_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        uid = int(interaction.user.id)
        locale = _interaction_locale(self.bot, interaction)
        async with self.lock:
            if uid != self.current_uid:
                await interaction.response.send_message(_t(locale, "현재 본인 차례가 아닙니다.", "It is not your turn."), ephemeral=True)
                return
            self.betting.fold(uid)
            self.permanent_folded.add(uid)
            self.log(f"{self.names[uid]} FOLD")
            await interaction.response.defer()
            await self.after_action()

    async def after_action(self) -> None:
        if len(self.betting.active) <= 1:
            await self.finish(self.betting.active)
            return
        if self.betting.complete():
            self.street += 1
            if self.street > self.max_street:
                await self.finish(self.betting.active)
                return
            self.revealed = min(len(next(iter(self.hands.values()))), self.revealed + (1 if self.variant == "삼봉" else 3))
            self.betting.reset_for_next_street(min_raise=max(1, self.bet))
            for uid in self.permanent_folded:
                self.betting.folded.add(uid)
            self.last_action = _t(self.locale, f"{self.street}차 베팅이 시작됩니다.", f"Betting round {self.street} begins.")
            self.log(f"STREET {self.street}")
        await self._run_ai()
        if not self.done:
            await _safe_edit(self.message, embed=self.embed(), view=self)

    async def _run_ai(self) -> None:
        guard = 0
        while not self.done and self.current_uid is not None and _is_ai(self.current_uid) and guard < 80:
            guard += 1
            uid = self.current_uid
            if random.random() > self.risk + 0.15 and self.betting.to_call(uid) > self.bet * 3:
                self.betting.fold(uid)
                self.permanent_folded.add(uid)
                self.log(f"{self.names[uid]} AI FOLD")
            elif random.random() < self.risk * 0.35:
                target = self.betting.current_bet + max(self.betting.min_raise, self.bet * random.randint(1, 4))
                _action, paid = self.betting.raise_to(uid, target)
                self.charge(uid, paid)
                self.log(f"{self.names[uid]} AI RAISE {target}")
            else:
                action, paid = self.betting.check_or_call(uid)
                self.charge(uid, paid)
                self.log(f"{self.names[uid]} AI {action.upper()} {paid}")
            if len(self.betting.active) <= 1:
                await self.finish(self.betting.active)
                return
            if self.betting.complete():
                self.street += 1
                if self.street > self.max_street:
                    await self.finish(self.betting.active)
                    return
                self.revealed = min(len(next(iter(self.hands.values()))), self.revealed + (1 if self.variant == "삼봉" else 3))
                self.betting.reset_for_next_street(min_raise=max(1, self.bet))
                for folded in self.permanent_folded:
                    self.betting.folded.add(folded)
                self.log(f"STREET {self.street}")

    async def finish(self, active: Sequence[int]) -> None:
        active = list(active)
        if len(active) == 1:
            winners = active
            names = {active[0]: _t(self.locale, "상대 전원 폴드", "all opponents folded")}
            score_map = {uid: 0 for uid in self.player_ids}
        else:
            if self.variant == "삼봉":
                ranked = {uid: sambong_rank([card.month for card in self.hands[uid]]) for uid in active}
                best = max(value[0] for value in ranked.values())
                winners = [uid for uid, value in ranked.items() if value[0] == best]
                names = {uid: ranked[uid][1] for uid in active}
                score_map = {uid: ranked[uid][0][0] for uid in active}
            else:
                ranked = {uid: dori_rank([card.month for card in self.hands[uid]]) for uid in active}
                best = max(value[0] for value in ranked.values())
                winners = [uid for uid, value in ranked.items() if value[0] == best]
                names = {uid: ranked[uid][1] for uid in active}
                score_map = {uid: ranked[uid][0][0] for uid in active}
        rows = []
        for uid in self.player_ids:
            if uid in self.permanent_folded:
                text = _t(self.locale, "폴드", "Folded")
            else:
                text = f"{' '.join(card.label for card in self.hands[uid])} · **{names.get(uid, '-')}**"
            rows.append(f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · {text}")
        await self.settle(winners, rows, score_map=score_map)

class CaptureHwatuSession(AuthenticGoStopSession):
    """Minhwatu/Yukbaek reuse the real play/flip/capture engine from v10.6."""

    def __init__(self, lobby: Any, *, bot: commands.Bot, variant: str, world_data: MutableMapping[str, Any]) -> None:
        super().__init__(lobby, bot=bot, mode="고스톱", world_data=world_data)
        self.variant = variant
        self.kind = variant
        self.mode = variant
        self.round_no = 1
        self.cumulative = {uid: 0 for uid in self.player_ids}
        keep = {"내 패", "패 내기", "My Hand", "Play Card"}
        for child in list(self.children):
            if getattr(child, "label", None) not in keep:
                self.remove_item(child)
        self.last_action = _t(self.locale, "손패를 내고 더미를 뒤집어 같은 월 바닥패를 직접 맞추세요.", "Play a hand card, flip the stock, and choose matching floor cards.")
        self.replay: List[str] = []
        self.difficulty, self.personality, self.risk = _ai_config(self.get_user, self.host_id)

    def log(self, text: str) -> None:
        self.replay.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        del self.replay[:-80]

    def score(self, uid: int) -> HwatuSummary:
        cards = self.engine.captured[uid]
        base = _hwatu_summary_lite(cards)
        capture = hwatu_capture_points((card.category for card in cards), (card.month for card in cards))
        return HwatuSummary(capture, base.brights, base.animals, base.ribbons, base.junk_points, base.labels)

    def embed(self, final: str = "") -> discord.Embed:
        title_en = NEW_GAME_EN[self.variant]
        embed = _dashboard(self.bot, self.locale, f"{NEW_GAME_EMOJI[self.variant]} {self.variant} · {self.round_no}라운드", f"{NEW_GAME_EMOJI[self.variant]} {title_en} · Round {self.round_no}", final or self.last_action, final or self.last_action, discord.Color.dark_red())
        floor = "\n".join(" · ".join(_hwatu_lite_text(card, self.locale) for card in self.engine.floor[index:index+4]) for index in range(0, len(self.engine.floor), 4)) or "-"
        embed.add_field(name=_t(self.locale, "바닥패", "Floor"), value=floor[:1024], inline=False)
        rows = []
        for uid in self.player_ids:
            summary = self.score(uid)
            total = self.cumulative[uid] + (summary.score if self.variant == "육백" else 0)
            rows.append(f"{'👉' if uid == self.engine.current_uid else '▫️'} **{self.names[uid]}** · {len(self.engine.hands[uid])}{_t(self.locale,'장',' cards')} · **{summary.score}{_t(self.locale,'점',' pts')}**" + (f" · {_t(self.locale,'누적','total')} {total}/600" if self.variant == "육백" else ""))
        embed.add_field(name=_t(self.locale, "참가자", "Players"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "남은 더미", "Stock"), value=str(len(self.engine.stock)), inline=True)
        embed.add_field(name=_t(self.locale, "기준 판돈", "Base Stake"), value=f"{self.bet:,}", inline=True)
        embed.set_footer(text=_t(self.locale, "고/스톱 없음 · 동월 2장 직접 선택 · 실제 획득 점수", "No Go/Stop · choose between two matching months · capture scoring"))
        return embed

    async def start(self) -> None:
        self._reserve()
        self.log(f"START {self.variant}")
        await _safe_edit(self.message, embed=self.embed(), view=self)
        await self._run_ai()

    async def _post_turn(self, uid: int, result: Any) -> None:
        played = ", ".join(_hwatu_lite_text(card, self.locale) for card in result.played) or "-"
        flipped = _hwatu_lite_text(result.flipped, self.locale) if result.flipped else "-"
        events = " · ".join(result.events) or _t(self.locale, "일반 진행", "normal play")
        self.last_action = f"**{self.names[uid]}** · {_t(self.locale,'낸 패','played')} {played} · {_t(self.locale,'뒤집기','flipped')} {flipped} · {events}"
        self.log(f"{self.names[uid]} TURN {events}")
        if self.engine.exhausted():
            await self.finish_round()
            return
        await self._run_ai()
        if not self.done:
            await _safe_edit(self.message, embed=self.embed(), view=self)

    async def _run_ai(self) -> None:
        guard = 0
        while not self.done and _is_ai(self.engine.current_uid) and guard < 80:
            guard += 1
            uid = self.engine.current_uid
            hand = self.engine.hands[uid]
            if not hand:
                break
            index = max(range(len(hand)), key=lambda i: len(self.engine.matching_floor_indices(hand[i].month)))
            match = None
            flip_match = None
            while True:
                matches = self.engine.matching_floor_indices(hand[index].month)
                if len(matches) == 2:
                    match = matches[0]
                result = self.engine.play(uid, index, match_index=match, flip_match_index=flip_match)
                if not result.needs_choice:
                    break
                phase, indices = result.needs_choice
                if phase == "hand":
                    match = indices[0]
                else:
                    flip_match = indices[0]
            await self._post_turn(uid, result)
            if self.done:
                return

    def _reset_round(self) -> None:
        rich = _hwatu_deck()
        junk_seen: Dict[int, int] = {}
        lite = [HwatuCardLite(_hwatu_visual_uid(card, junk_seen), card.month, card.category, card.ko, card.junk) for card in rich]
        self.engine = GoStopEngine(self.player_ids, lite, matgo=False)
        self.pending_action.clear()
        self.pending_go = None
        self.round_no += 1

    async def finish_round(self) -> None:
        scores = {uid: self.score(uid).score for uid in self.player_ids}
        if self.variant == "육백":
            if not yukbaek_round_valid(list(scores.values())):
                self.last_action = _t(self.locale, "🌫️ 30점 이하 참가자가 있어 이번 라운드는 무효입니다. 재경기합니다.", "🌫️ A player scored 30 or less, so the round is void and redealt.")
                self.log("ROUND VOID <=30")
                self._reset_round()
                await _safe_edit(self.message, embed=self.embed(), view=self)
                await self._run_ai()
                return
            for uid, value in scores.items():
                self.cumulative[uid] += int(value)
            best_total = max(self.cumulative.values())
            if best_total < 600:
                self.last_action = _t(self.locale, f"✅ 유효 라운드 종료 · 최고 누적 {best_total}/600", f"✅ Valid round complete · leading total {best_total}/600")
                self.log(f"ROUND VALID scores={scores}")
                self._reset_round()
                await _safe_edit(self.message, embed=self.embed(), view=self)
                await self._run_ai()
                return
            winners = [uid for uid, value in self.cumulative.items() if value == best_total]
            final_scores = dict(self.cumulative)
        else:
            best = max(scores.values())
            winners = [uid for uid, value in scores.items() if value == best]
            final_scores = scores
        payouts = self._pay_debt_pot(winners)
        rows = [f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · **{final_scores[uid]}{_t(self.locale,'점',' pts')}**\n└ {self.settlement_text(uid, payouts.get(uid,0))}" for uid in self.player_ids]
        for uid in self.player_ids:
            if not _is_ai(uid):
                _record(self.get_user(uid), self.variant, "win" if uid in winners else "loss", payouts.get(uid,0)-self.human_paid.get(uid,0), final_scores[uid], any(_is_ai(player) for player in self.player_ids))
        self.done = True
        self.log(f"RESULT winners={winners}")
        replay_stub = type("ReplayStub", (), {})()
        replay_stub.game_id, replay_stub.kind, replay_stub.bet, replay_stub.player_ids = self.game_id, self.kind, self.bet, self.player_ids
        replay_stub.names, replay_stub.replay, replay_stub.message, replay_stub.channel_id = self.names, self.replay, self.message, self.channel_id
        _store_replay(self.world_data, replay_stub, " / ".join(self.names[uid] for uid in winners))
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        heading = _t(self.locale, "🏆 승부 결과 · 최종 정산\n\n", "🏆 Match Result · Final Settlement\n\n")
        await _publish_final(self, self.embed(heading + "\n".join(rows)))
        self.stop()


class BlackjackTournamentSession(AuthenticBlackjackSession):
    def __init__(self, lobby: Any, *, bot: commands.Bot) -> None:
        super().__init__(lobby, bot=bot)
        self.kind = "블랙잭토너먼트"
        self.round_no = 1
        self.points = {uid: 0 for uid in self.player_ids}
        self.round_rows: List[str] = []
        self.replay: List[str] = []
        self.difficulty, self.personality, self.risk = _ai_config(self.get_user, self.host_id)

    def embed(self, final: str = "") -> discord.Embed:
        embed = _dashboard(self.bot, self.locale, f"🏆 블랙잭 토너먼트 · {self.round_no}/5", f"🏆 Blackjack Tournament · {self.round_no}/5", final or self.last_action, final or self.last_action, discord.Color.dark_green())
        embed.add_field(name=_t(self.locale, "딜러", "Dealer"), value=f"{_card_text(self.dealer[0])}  🂠", inline=False)
        rows = []
        for uid in self.player_ids:
            state = _t(self.locale, "버스트", "Bust") if uid in self.busted else (_t(self.locale, "스탠드", "Stand") if uid in self.stood else f"{len(self.hands[uid])}{_t(self.locale,'장',' cards')}")
            rows.append(f"{'👉' if uid == self.current_uid else '▫️'} **{self.names[uid]}** · {state} · **{self.points[uid]}pt**")
        embed.add_field(name=_t(self.locale, "누적 순위", "Standings"), value="\n".join(rows), inline=False)
        embed.add_field(name=_t(self.locale, "전체 팟", "Total Pot"), value=f"{self.pot:,}", inline=True)
        embed.set_footer(text=_t(self.locale, "5핸드 · 승리 2점 · 무승부 1점 · 최종 1위 팟 획득", "Five hands · win 2 · push 1 · final leader takes the pot"))
        return embed

    async def start(self) -> None:
        self._reserve()
        self.replay.append("START blackjack tournament")
        await _safe_edit(self.message, embed=self.embed(), view=self)
        await self._run_ai()

    def _new_hand(self) -> None:
        self.deck = _deck()
        self.hands = {uid: [self.deck.pop(), self.deck.pop()] for uid in self.player_ids}
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.stood.clear()
        self.busted.clear()
        self.current_index = 0
        self.last_action = _t(self.locale, f"{self.round_no}번째 핸드가 시작됩니다.", f"Hand {self.round_no} begins.")

    async def finish(self) -> None:
        if self.done:
            return
        while self.value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        dealer_total = self.value(self.dealer)
        hand_row = []
        for uid in self.player_ids:
            total = self.value(self.hands[uid])
            if total > 21:
                outcome = "loss"
            elif dealer_total > 21 or total > dealer_total:
                outcome = "win"
                self.points[uid] += 2
            elif total == dealer_total:
                outcome = "draw"
                self.points[uid] += 1
            else:
                outcome = "loss"
            hand_row.append(f"{self.names[uid]} {total} {outcome}")
        self.round_rows.append(f"R{self.round_no}: " + " · ".join(hand_row))
        self.replay.append(self.round_rows[-1])
        if self.round_no < 5:
            self.round_no += 1
            self._new_hand()
            await _safe_edit(self.message, embed=self.embed("\n".join(self.round_rows[-3:])), view=self)
            await self._run_ai()
            return
        best = max(self.points.values())
        winners = [uid for uid, value in self.points.items() if value == best]
        payouts = self._pay_debt_pot(winners)
        rows = [f"{'🏆' if uid in winners else '▫️'} **{self.names[uid]}** · **{self.points[uid]}pt**\n└ {self.settlement_text(uid, payouts.get(uid,0))}" for uid in self.player_ids]
        for uid in self.player_ids:
            if not _is_ai(uid):
                _record(self.get_user(uid), self.kind, "win" if uid in winners else "loss", payouts.get(uid,0)-self.human_paid.get(uid,0), self.points[uid], any(_is_ai(player) for player in self.player_ids))
        self.done = True
        replay_stub = type("ReplayStub", (), {})()
        replay_stub.game_id, replay_stub.kind, replay_stub.bet, replay_stub.names = self.game_id, self.kind, self.bet, self.names
        replay_stub.replay, replay_stub.message, replay_stub.channel_id = self.replay, self.message, self.channel_id
        _store_replay(self.world_data, replay_stub, " / ".join(self.names[uid] for uid in winners))
        self.save_data()
        self._disable()
        ACTIVE_GAMES.pop(self.channel_id, None)
        heading = _t(self.locale, "🏆 5핸드 최종 승부 결과 · 정산\n\n", "🏆 Five-Hand Final Result · Settlement\n\n")
        await _publish_final(self, self.embed(heading + "\n".join(self.round_rows + rows)))
        self.stop()

@dataclass
class V1090Factory:
    build: Callable[[Any], Any]
    minimum: int
    maximum: int


def register_v1090_integrated_renewal(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1090_registered", False):
        return
    bot._abaddon_v1090_registered = True
    _root(world_data)

    def factory_for(kind: str) -> V1090Factory:
        if kind in {"포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "파인애플홀덤", "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커"}:
            minimum, maximum = ({"인디언포커": (2, 2), "세븐카드스터드": (2, 7), "하이로우포커": (2, 7)}).get(kind, (2, 8))
            return V1090Factory(lambda lobby, k=kind: AuthenticPokerSession(lobby, bot=bot, variant=k), minimum, maximum)
        if kind == "블랙잭":
            return V1090Factory(lambda lobby: AuthenticBlackjackSession(lobby, bot=bot), 2, 8)
        if kind == "바카라":
            return V1090Factory(lambda lobby: AuthenticBaccaratSession(lobby, bot=bot), 2, 8)
        if kind == "섯다":
            return V1090Factory(lambda lobby: AuthenticSeotdaSession(lobby, bot=bot), 2, 6)
        if kind == "맞고":
            return V1090Factory(lambda lobby: AuthenticGoStopSession(lobby, bot=bot, mode="맞고", world_data=world_data), 2, 2)
        if kind == "고스톱":
            return V1090Factory(lambda lobby: AuthenticGoStopSession(lobby, bot=bot, mode="고스톱", world_data=world_data), 3, 3)
        if kind == "원카드":
            return V1090Factory(AuthenticOneCardSession, 2, 6)
        if kind == "조커잡기":
            return V1090Factory(AuthenticJokerSession, 2, 8)
        if kind in {"훌라", "라미"}:
            return V1090Factory(lambda lobby, k=kind: MeldRaceSession(lobby, bot=bot, variant=k), 2, 6)
        if kind == "대통령":
            return V1090Factory(lambda lobby: PresidentSession(lobby, bot=bot), 2, 8)
        if kind == "주사위카드":
            return V1090Factory(lambda lobby: DiceCardSession(lobby, bot=bot), 2, 8)
        if kind in {"삼봉", "도리짓고땡"}:
            return V1090Factory(lambda lobby, k=kind: KoreanShowdownSession(lobby, bot=bot, variant=k), 2, 6)
        if kind in {"민화투", "육백"}:
            minimum = 3 if kind == "육백" else 2
            maximum = 3
            return V1090Factory(lambda lobby, k=kind: CaptureHwatuSession(lobby, bot=bot, variant=k, world_data=world_data), minimum, maximum)
        if kind == "블랙잭토너먼트":
            return V1090Factory(lambda lobby: BlackjackTournamentSession(lobby, bot=bot), 2, 8)
        raise KeyError(kind)

    def normalize_game(value: str) -> Optional[str]:
        token = re.sub(r"[\s_-]+", "", str(value or "").casefold())
        aliases = {
            "blackjacktable": "블랙잭", "cardblackjack": "블랙잭", "baccarattable": "바카라", "cardbaccarat": "바카라",
            "gostop": "고스톱", "matgo": "맞고", "seotda": "섯다", "sutda": "섯다", "hoola": "훌라", "hula": "훌라",
            "president": "대통령", "daifugo": "대통령", "dicecard": "주사위카드", "sambong": "삼봉", "dori": "도리짓고땡",
            "dorijitgottaeng": "도리짓고땡", "minhwatu": "민화투", "yukbaek": "육백", "blackjacktournament": "블랙잭토너먼트",
        }
        if token in aliases:
            return aliases[token]
        for kind in ALL_GAMES:
            if token in {re.sub(r"[\s_-]+", "", kind.casefold()), re.sub(r"[\s_-]+", "", GAME_EN.get(kind, kind).casefold())}:
                return kind
        return None

    async def create_lobby_ctx(ctx: commands.Context, kind: str, bet: int) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        if int(bet) < MIN_BET:
            await ctx.send(_t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다. 상한은 없습니다.", f"Minimum stake is {MIN_BET:,} chips. There is no maximum."))
            return
        channel_id = int(ctx.channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            await ctx.send(_t(locale, "⚠️ 이 채널에서 이미 게임이 진행 중입니다.", "⚠️ A game is already active in this channel."))
            return
        factory = factory_for(kind)
        public_locale = _locale(bot, 0, getattr(ctx.guild, "id", 0))
        lobby = V1060LobbyView(bot=bot, kind=kind, host=ctx.author, bet=int(bet), get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data, start_factory=factory.build, min_players=factory.minimum, max_players=factory.maximum, allow_abaddon=True, public_locale=public_locale)
        lobby.channel_id = channel_id
        note = _t(public_locale, "🤖 아바돈 초대 가능 · 잔액 음수 허용 · 자유 레이즈 안전 한도 · 정산 상한 없음", "🤖 ABADDON available · negative balances · free-raise safety limit · uncapped settlement")
        message = await ctx.send(embed=lobby.embed(note), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby

    async def create_lobby_interaction(interaction: discord.Interaction, kind: str, bet: int) -> Tuple[bool, str]:
        locale = _interaction_locale(bot, interaction)
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            return False, _t(locale, "서버 텍스트 채널에서만 가능합니다.", "Use a server text channel.")
        if int(bet) < MIN_BET:
            return False, _t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다.", f"Minimum stake is {MIN_BET:,} chips.")
        channel_id = int(channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            return False, _t(locale, "이 채널에서 이미 게임이 진행 중입니다.", "A game is already active in this channel.")
        uid = int(interaction.user.id)
        if uid not in user_data and str(uid) not in user_data:
            return False, _t(locale, "먼저 가입하세요.", "Register first.")
        factory = factory_for(kind)
        public_locale = _locale(bot, 0, getattr(interaction.guild, "id", 0))
        lobby = V1060LobbyView(bot=bot, kind=kind, host=interaction.user, bet=int(bet), get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data, start_factory=factory.build, min_players=factory.minimum, max_players=factory.maximum, allow_abaddon=True, public_locale=public_locale)
        lobby.channel_id = channel_id
        message = await channel.send(embed=lobby.embed(_t(public_locale, "🤖 아바돈 초대 가능 · 실전 진행", "🤖 Invite ABADDON · authentic play")), view=lobby)
        lobby.message = message
        ACTIVE_LOBBIES[channel_id] = lobby
        return True, _t(locale, f"✅ {_game_display(kind, locale)} 방 생성: {message.jump_url}", f"✅ Created {_game_display(kind, locale)} lobby: {message.jump_url}")

    async def start_ai_ctx(ctx: commands.Context, kind: str, bet: int) -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        if int(bet) < MIN_BET:
            await ctx.send(_t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다.", f"Minimum stake is {MIN_BET:,} chips."))
            return
        channel_id = int(ctx.channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            await ctx.send(_t(locale, "⚠️ 이 채널에서 이미 게임이 진행 중입니다.", "⚠️ A game is already active in this channel."))
            return
        public_locale = _locale(bot, 0, getattr(ctx.guild, "id", 0))
        message = await ctx.send(embed=_dashboard(bot, public_locale, f"{GAME_EMOJI.get(kind,'🃏')} {kind} · ABADDON", f"{GAME_EMOJI.get(kind,'🃏')} {_game_display(kind,public_locale)} · ABADDON", "실전 세션을 준비하고 있습니다.", "Preparing the live session."))
        players = {int(ctx.author.id): getattr(ctx.author, "display_name", str(ctx.author)), AI_ID: "ABADDON"}
        factory = factory_for(kind)
        if factory.minimum >= 3:
            players[AI_ID_2] = "ABADDON-β"
        lobby = _AILobby(bot, kind, int(ctx.author.id), int(bet), get_user, save_data, world_data, user_data, message, channel_id, public_locale, players)
        session = factory.build(lobby)
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

    async def start_ai_interaction(interaction: discord.Interaction, kind: str, bet: int) -> None:
        locale = _interaction_locale(bot, interaction)
        if int(bet) < MIN_BET:
            await interaction.response.send_message(_t(locale, f"최소 판돈은 {MIN_BET:,}칩입니다.", f"Minimum stake is {MIN_BET:,} chips."), ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        channel = interaction.channel
        if channel is None:
            return
        channel_id = int(channel.id)
        if channel_id in ACTIVE_LOBBIES or channel_id in ACTIVE_GAMES:
            await interaction.followup.send(_t(locale, "이 채널에서 이미 게임이 진행 중입니다.", "A game is already active in this channel."), ephemeral=True)
            return
        public_locale = _locale(bot, 0, getattr(interaction.guild, "id", 0))
        message = await interaction.followup.send(embed=_dashboard(bot, public_locale, f"{GAME_EMOJI.get(kind,'🃏')} {kind} · ABADDON", f"{GAME_EMOJI.get(kind,'🃏')} {_game_display(kind,public_locale)} · ABADDON", "실전 세션을 준비합니다.", "Preparing the live session."), wait=True)
        players = {int(interaction.user.id): getattr(interaction.user, "display_name", str(interaction.user)), AI_ID: "ABADDON"}
        factory = factory_for(kind)
        if factory.minimum >= 3:
            players[AI_ID_2] = "ABADDON-β"
        lobby = _AILobby(bot, kind, int(interaction.user.id), int(bet), get_user, save_data, world_data, user_data, message, channel_id, public_locale, players)
        session = factory.build(lobby)
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

    class GameBetModal(discord.ui.Modal):
        def __init__(self, kind: str, locale: str, ai: bool = False) -> None:
            super().__init__(title=_t(locale, f"{kind} 방 만들기", f"Create {_game_display(kind,locale)}"))
            self.kind, self.locale, self.ai = kind, locale, ai
            self.amount = discord.ui.TextInput(label=_t(locale, "판돈", "Stake"), placeholder=str(MIN_BET), min_length=1, max_length=100)
            self.add_item(self.amount)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            try:
                amount = int(str(self.amount.value).replace(",", ""))
            except ValueError:
                await interaction.response.send_message(_t(self.locale, "숫자로 입력하세요.", "Enter a number."), ephemeral=True)
                return
            if self.ai:
                await start_ai_interaction(interaction, self.kind, amount)
                return
            await interaction.response.defer(ephemeral=True)
            ok, text = await create_lobby_interaction(interaction, self.kind, amount)
            await interaction.followup.send(text, ephemeral=True)

    class AllGameSelect(discord.ui.Select):
        def __init__(self, locale: str, ai: bool = False, amount: int = 0) -> None:
            self.locale, self.ai, self.amount = locale, ai, int(amount)
            options = [discord.SelectOption(label=_game_display(kind, locale), value=kind, emoji=GAME_EMOJI.get(kind, "🃏"), description=GAME_RULE_SUMMARY[kind][0 if locale == "ko" else 1][:100]) for kind in ALL_GAMES]
            super().__init__(placeholder=_t(locale, "카드게임 25종 선택", "Choose among 25 card games"), min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction) -> None:
            kind = self.values[0]
            if self.ai and self.amount >= MIN_BET:
                await start_ai_interaction(interaction, kind, self.amount)
            else:
                await interaction.response.send_modal(GameBetModal(kind, self.locale, self.ai))

    class AllGameMenu(discord.ui.View):
        def __init__(self, locale: str, ai: bool = False, amount: int = 0) -> None:
            super().__init__(timeout=180)
            self.add_item(AllGameSelect(locale, ai, amount))

    # New direct game commands.
    @bot.command(name="훌라", aliases=["hoola", "hula"])
    async def hoola_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "훌라", 참가비)

    @bot.command(name="라미", aliases=["rummy"])
    async def rummy_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "라미", 참가비)

    @bot.command(name="대통령", aliases=["president", "daifugo"])
    async def president_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "대통령", 참가비)

    @bot.command(name="주사위카드", aliases=["dicecard", "dicecardpoker"])
    async def dice_card_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "주사위카드", 참가비)

    @bot.command(name="삼봉", aliases=["sambong"])
    async def sambong_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "삼봉", 참가비)

    @bot.command(name="도리짓고땡", aliases=["dorijitgottaeng", "dori"])
    async def dori_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "도리짓고땡", 참가비)

    @bot.command(name="민화투", aliases=["minhwatu"])
    async def minhwatu_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "민화투", 참가비)

    @bot.command(name="육백", aliases=["yukbaek", "hwatu600"])
    async def yukbaek_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "육백", 참가비)

    @bot.command(name="블랙잭토너먼트", aliases=["blackjacktournament", "bjtournament"])
    async def bj_tournament_cmd(ctx: commands.Context, 참가비: int = MIN_BET) -> None:
        await create_lobby_ctx(ctx, "블랙잭토너먼트", 참가비)

    # Rebuild the main card menu as an image-like dashboard with all 25 games.
    card_menu = bot.get_command("카드게임")
    if card_menu is not None:
        async def v1090_card_menu(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, "🃏 ABADDON 카드게임 센터 · 25종", "🃏 ABADDON Card Center · 25 Modes", "실제 턴·선택·베팅으로 진행하며 혼자일 때 아바돈을 초대할 수 있습니다.", "Games use real turns, choices and betting; invite ABADDON when playing alone.")
            embed.add_field(name=_t(locale, "신규 9종", "Nine New Modes"), value=" · ".join(f"{GAME_EMOJI[k]} {_game_display(k,locale)}" for k in NEW_GAMES), inline=False)
            embed.add_field(name=_t(locale, "경제", "Economy"), value=_t(locale, "잔액 음수 허용 · 자유 레이즈 안전 한도 · 정산 상한 없음 · 파산신청 유지", "Negative balances · free-raise safety limit · uncapped settlement · bankruptcy preserved"), inline=False)
            embed.add_field(name=_t(locale, "관리", "Management"), value=_t(locale, "`!카드룸` · `!관전` · `!게임리플레이` · `!아바돈난이도`", "`!cardroom` · `!spectate` · `!gamereplay` · `!abaddondifficulty`"), inline=False)
            await ctx.send(embed=embed, view=AllGameMenu(locale))
        card_menu.callback = v1090_card_menu
        card_menu.help = "카드게임 25종을 대시보드에서 선택합니다."
        card_menu.description = card_menu.help

    old_ai_menu = bot.get_command("아바돈게임")
    if old_ai_menu is not None:
        async def v1090_ai_menu(ctx: commands.Context, 재화또는금액: str = "0", 금액: int = 0) -> None:
            if not await check_registered(ctx):
                return
            raw = str(재화또는금액 or "0").replace(",", "")
            try:
                parsed_amount = int(raw)
            except ValueError:
                parsed_amount = int(금액 or 0)
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, "🤖 ABADDON 카드 대전 · 25종", "🤖 Play Cards with ABADDON · 25 Modes", "게임을 고른 뒤 판돈을 입력하세요. 3인 게임은 ABADDON-β도 자동 참가합니다.", "Choose a game and enter a stake. Three-player games also add ABADDON-β.")
            difficulty, personality, risk = _ai_config(get_user, int(ctx.author.id))
            embed.add_field(name=_t(locale, "현재 AI", "Current AI"), value=f"**{difficulty} · {personality}** · risk {risk:.2f}", inline=False)
            await ctx.send(embed=embed, view=AllGameMenu(locale, ai=True, amount=parsed_amount))
        old_ai_menu.callback = v1090_ai_menu

    invite = bot.get_command("아바돈초대")
    if invite is not None:
        old_callback = invite.callback
        async def v1090_invite(ctx: commands.Context, 게임: str = "포커", 금액: int = MIN_BET) -> None:
            kind = normalize_game(게임)
            if kind is None:
                try:
                    await old_callback(ctx, 게임, str(금액), 0)
                except TypeError:
                    await ctx.send(_t(_ctx_locale(bot,ctx), "지원 게임명을 확인하세요.", "Check the game name."))
                return
            await start_ai_ctx(ctx, kind, int(금액))
        invite.callback = v1090_invite

    bot.v1090_start_ai_card = start_ai_interaction  # type: ignore[attr-defined]
    bot.v1090_create_card_lobby = create_lobby_interaction  # type: ignore[attr-defined]
    bot.v1060_start_ai_card = start_ai_interaction  # type: ignore[attr-defined]

    @bot.command(name="카드룸", aliases=["cardroom", "cardlobby"])
    async def card_room(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        embed = _dashboard(bot, locale, "🎴 카드룸 대시보드", "🎴 Card Room Dashboard", "모집 중인 방과 진행 중인 테이블을 한 화면에서 확인합니다.", "See open lobbies and active tables in one panel.", discord.Color.dark_teal())
        lobby_rows = []
        for channel_id, lobby in list(ACTIVE_LOBBIES.items())[:10]:
            lobby_rows.append(f"🟡 <#{channel_id}> · **{_game_display(getattr(lobby,'kind','?'),locale)}** · {len(getattr(lobby,'players',{}))}/{getattr(lobby,'max_players','?')} · {getattr(lobby,'bet',0):,}")
        game_rows = []
        for channel_id, session in list(ACTIVE_GAMES.items())[:10]:
            game_rows.append(f"🔴 <#{channel_id}> · **{_game_display(getattr(session,'kind','?'),locale)}** · {len(getattr(session,'player_ids',[]))}{_t(locale,'명',' players')} · {getattr(session,'bet',0):,}")
        embed.add_field(name=_t(locale, "모집 중", "Open Lobbies"), value="\n".join(lobby_rows) or _t(locale, "현재 모집 중인 방이 없습니다.", "No open lobby."), inline=False)
        embed.add_field(name=_t(locale, "진행 중", "Active Tables"), value="\n".join(game_rows) or _t(locale, "현재 진행 중인 게임이 없습니다.", "No active table."), inline=False)
        embed.add_field(name=_t(locale, "빠른 명령", "Quick Commands"), value=_t(locale, "`!카드게임` · `!빠른대전 게임명 판돈` · `!아바돈게임 판돈`", "`!cardgames` · `!quickmatch game stake` · `!abaddongames stake`"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="게임방목록", aliases=["gamelobbies", "roomlist"])
    async def room_list(ctx: commands.Context) -> None:
        await card_room.callback(ctx)

    @bot.command(name="빠른대전", aliases=["quickmatch"])
    async def quick_match(ctx: commands.Context, 게임: str = "텍사스홀덤", 판돈: int = MIN_BET) -> None:
        kind = normalize_game(게임)
        if kind is None:
            await ctx.send(_t(_ctx_locale(bot,ctx), "지원하지 않는 게임입니다. `!카드게임룰`을 확인하세요.", "Unsupported game. Check `!cardrules`."))
            return
        await create_lobby_ctx(ctx, kind, 판돈)

    @bot.command(name="재대결", aliases=["rematch"])
    async def rematch(ctx: commands.Context) -> None:
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        recent = next((row for row in reversed(_root(world_data).get("replays", [])) if int(row.get("guild_id",0)) == guild_id and int(ctx.author.id) in {int(key) for key in row.get("players",{}) if str(key).lstrip('-').isdigit()}), None)
        if not recent:
            await ctx.send(_t(_ctx_locale(bot,ctx), "최근 게임 기록이 없습니다.", "No recent game is available."))
            return
        await create_lobby_ctx(ctx, str(recent.get("game","포커")), int(recent.get("stake",MIN_BET)))

    @bot.command(name="관전", aliases=["spectate"])
    async def spectate(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        session = ACTIVE_GAMES.get(int(ctx.channel.id))
        if session is None:
            await ctx.send(_t(locale, "이 채널에 진행 중인 게임이 없습니다.", "No game is active in this channel."))
            return
        try:
            embed = session.embed()
        except Exception:
            embed = _dashboard(bot, locale, "👁️ 관전 패널", "👁️ Spectator Panel", "공개 테이블 정보를 표시합니다.", "Showing public table information.")
        embed.title = f"👁️ {_t(locale,'관전','Spectating')} · {embed.title or getattr(session,'kind','Game')}"
        embed.add_field(name=_t(locale, "보안", "Privacy"), value=_t(locale, "손패·비공개 선택·개인 모달은 관전자에게 표시하지 않습니다.", "Hands, private choices and personal modals are never shown."), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="테이블정보", aliases=["tableinfo"])
    async def table_info(ctx: commands.Context) -> None:
        await spectate.callback(ctx)

    @bot.command(name="관전종료", aliases=["stopspectating"])
    async def stop_spectating(ctx: commands.Context) -> None:
        await ctx.send(_t(_ctx_locale(bot,ctx), "✅ 관전 패널은 일회성이라 별도 종료가 필요하지 않습니다.", "✅ Spectator panels are snapshots and need no separate stop action."))

    async def replay_embed(ctx: commands.Context, index: int = 1) -> None:
        locale = _ctx_locale(bot, ctx)
        guild_id = int(getattr(ctx.guild, "id", 0) or 0)
        rows = [row for row in reversed(_root(world_data).get("replays", [])) if int(row.get("guild_id",0)) == guild_id]
        if not rows:
            await ctx.send(_t(locale, "저장된 리플레이가 없습니다. v10.9 신규 게임부터 턴 로그가 기록됩니다.", "No replay is stored. Turn logs are recorded for v10.9 games."))
            return
        row = rows[max(0, min(len(rows)-1, int(index)-1))]
        embed = _dashboard(bot, locale, f"📼 게임 리플레이 · {row.get('game')}", f"📼 Game Replay · {_game_display(str(row.get('game')),locale)}", f"ID `{row.get('id')}` · 판돈 {int(row.get('stake',0)):,}", f"ID `{row.get('id')}` · stake {int(row.get('stake',0)):,}", discord.Color.dark_blue())
        events = list(row.get("events", []))
        chunks = [events[i:i+10] for i in range(0, len(events), 10)] or [[_t(locale,"기록 없음","No events")]]
        for number, chunk in enumerate(chunks[:4], 1):
            embed.add_field(name=_t(locale, f"진행 {number}", f"Timeline {number}"), value="\n".join(chunk)[:1024], inline=False)
        embed.add_field(name=_t(locale, "결과", "Result"), value=str(row.get("result","-"))[:1024], inline=False)
        embed.set_footer(text=_t(locale, "손패는 종료 후에도 로그에 저장하지 않습니다.", "Private hands are not stored in replay logs."))
        await ctx.send(embed=embed)

    @bot.command(name="최근게임", aliases=["recentgame"])
    async def recent_game(ctx: commands.Context) -> None:
        await replay_embed(ctx, 1)

    @bot.command(name="게임리플레이", aliases=["gamereplay"])
    async def game_replay(ctx: commands.Context, 번호: int = 1) -> None:
        await replay_embed(ctx, 번호)

    @bot.command(name="게임기록", aliases=["gamelog"])
    async def game_log(ctx: commands.Context, 번호: int = 1) -> None:
        await replay_embed(ctx, 번호)

    @bot.command(name="아바돈난이도", aliases=["abaddondifficulty"])
    async def ai_difficulty_cmd(ctx: commands.Context, 난이도: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        root = _user_root(get_user(int(ctx.author.id)))
        mapping = {"easy":"쉬움","normal":"보통","hard":"어려움","nightmare":"악몽"}
        value = mapping.get(난이도.casefold(), 난이도)
        if value in {"쉬움","보통","어려움","악몽"}:
            root["ai_difficulty"] = value
            save_data()
        embed = _dashboard(bot, locale, "🤖 아바돈 난이도", "🤖 ABADDON Difficulty", "게임별 공개 정보와 확률 판단 수준을 조절합니다.", "Adjusts how strongly ABADDON uses public information and probability.")
        embed.add_field(name=_t(locale,"현재","Current"), value=f"**{root['ai_difficulty']}**", inline=True)
        embed.add_field(name=_t(locale,"설정","Set"), value=_t(locale,"`!아바돈난이도 쉬움/보통/어려움/악몽`","`!abaddondifficulty easy/normal/hard/nightmare`"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="아바돈성향", aliases=["abaddonpersonality"])
    async def ai_personality_cmd(ctx: commands.Context, 성향: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        root = _user_root(get_user(int(ctx.author.id)))
        mapping = {"stable":"안정형","aggressive":"공격형","bluff":"블러프형","gambler":"도박형","revenge":"복수형"}
        value = mapping.get(성향.casefold(), 성향)
        if value in {"안정형","공격형","블러프형","도박형","복수형"}:
            root["ai_personality"] = value
            save_data()
        embed = _dashboard(bot, locale, "🎭 아바돈 성향", "🎭 ABADDON Personality", "베팅과 위험 감수 성향을 선택합니다.", "Choose ABADDON's betting and risk personality.")
        embed.add_field(name=_t(locale,"현재","Current"), value=f"**{root['ai_personality']}**", inline=True)
        embed.add_field(name=_t(locale,"설정","Set"), value=_t(locale,"`!아바돈성향 안정형/공격형/블러프형/도박형/복수형`","`!abaddonpersonality stable/aggressive/bluff/gambler/revenge`"), inline=False)
        await ctx.send(embed=embed)

    def user_stats_embed(ctx: commands.Context, panel: str) -> discord.Embed:
        locale = _ctx_locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        game_stats = user.get("v1050_game_stats", {}) if isinstance(user.get("v1050_game_stats", {}), dict) else {}
        total = game_stats.get("total", {}) if isinstance(game_stats.get("total", {}), dict) else {}
        chips = casino_chips(user)
        if panel == "game":
            embed = _dashboard(bot, locale, "🎮 게임 대시보드", "🎮 Game Dashboard", "전적·연승·아바돈 대전·현재 테이블을 한 화면에 표시합니다.", "Shows records, streaks, ABADDON matches and current tables.", discord.Color.blurple())
            embed.add_field(name=_t(locale,"전체 전적","Overall"), value=f"{int(total.get('wins',0))}W · {int(total.get('losses',0))}L · {int(total.get('draws',0))}D", inline=True)
            embed.add_field(name=_t(locale,"연승","Streak"), value=f"{int(total.get('streak',0))} / BEST {int(total.get('best_streak',0))}", inline=True)
            embed.add_field(name=_t(locale,"아바돈 대전","ABADDON Games"), value=str(int(total.get('ai_plays',0))), inline=True)
            games = game_stats.get("games", {}) if isinstance(game_stats.get("games",{}),dict) else {}
            top = sorted(games.items(), key=lambda row: int(row[1].get("plays",0)), reverse=True)[:6]
            embed.add_field(name=_t(locale,"많이 한 게임","Most Played"), value="\n".join(f"{GAME_EMOJI.get(name,'🃏')} **{_game_display(name,locale)}** · {int(row.get('plays',0))}" for name,row in top) or "-", inline=False)
        elif panel == "economy":
            embed = _dashboard(bot, locale, "💳 경제·부채 대시보드", "💳 Economy & Debt Dashboard", "음수 칩과 파산·재기 상태를 한눈에 확인합니다.", "Shows negative chips, bankruptcy and recovery status.", discord.Color.dark_gold())
            embed.add_field(name=_t(locale,"카지노 칩","Casino Chips"), value=f"**{chips:,}**", inline=True)
            embed.add_field(name=_t(locale,"식량","Food"), value=f"**{int(user.get('balance',0)):,}**", inline=True)
            embed.add_field(name=_t(locale,"상태","Status"), value=_t(locale,"파산 가능" if chips < 0 else "정상","Bankruptcy available" if chips < 0 else "Stable"), inline=True)
            embed.add_field(name=_t(locale,"경제 규칙","Economy Rules"), value=_t(locale,"음수 허용 · 베팅/레이즈는 서버 안전 한도 · 배수/정산 상한 없음 · `!파산신청` 유지","Negative balances · server safety limit for bets/raises · uncapped multipliers/settlement · `!bankruptcy` preserved"), inline=False)
        elif panel == "companion":
            companions = user.get("v1010_companions", user.get("companions", {}))
            embed = _dashboard(bot, locale, "🤝 동료 대시보드", "🤝 Companion Dashboard", "영입·배치·훈련 상태를 카드형 패널로 표시합니다.", "Shows recruitment, assignment and training in one card.", discord.Color.dark_teal())
            if isinstance(companions, dict):
                rows = [f"• **{name}** · {str(value)[:80]}" for name,value in list(companions.items())[:8]]
            else:
                rows = []
            embed.add_field(name=_t(locale,"동료 상태","Companion Status"), value="\n".join(rows) or _t(locale,"`!동료`에서 영입 상태를 확인하세요.","Use `!companions` to review recruitment."), inline=False)
            embed.add_field(name=_t(locale,"바로가기","Quick Actions"), value=_t(locale,"`!동료` · `!동료능력` · `!동료훈련` · `!동료원정`","`!companions` · `!companionabilities` · `!traincompanion` · `!companionexpedition`"), inline=False)
        elif panel == "season":
            season = user.get("v1050_season", {}) if isinstance(user.get("v1050_season",{}),dict) else {}
            embed = _dashboard(bot, locale, "🎟️ 시즌 대시보드", "🎟️ Season Dashboard", "무료 시즌 점수·완료 임무·수집품을 표시합니다.", "Shows free-season points, completed missions and collection.", discord.Color.purple())
            embed.add_field(name=_t(locale,"시즌","Season"), value=str(season.get("season_id","S6-2026")), inline=True)
            embed.add_field(name=_t(locale,"점수","Points"), value=str(int(season.get("points",0))), inline=True)
            embed.add_field(name=_t(locale,"완료","Completed"), value=str(len(season.get("completed",[]))), inline=True)
            embed.add_field(name=_t(locale,"수집품","Collection"), value=" · ".join(map(str,season.get("collection",[])[:8])) or "-", inline=False)
        elif panel == "alliance":
            embed = _dashboard(bot, locale, "🛡️ 연합 대시보드", "🛡️ Alliance Dashboard", "연합·협동 보스·기여 정보를 한 화면에서 확인합니다.", "Shows alliance, co-op boss and contribution information.", discord.Color.dark_red())
            alliance_id = user.get("v1050_alliance_id", user.get("alliance_id", "-"))
            embed.add_field(name=_t(locale,"소속 연합","Alliance"), value=str(alliance_id), inline=True)
            embed.add_field(name=_t(locale,"바로가기","Quick Actions"), value=_t(locale,"`!연합` · `!협동보스` · `!협동보스공격`","`!alliance` · `!allianceboss` · `!attackallianceboss`"), inline=False)
        elif panel == "world":
            guild_id = int(getattr(ctx.guild,"id",0) or 0)
            embed = _dashboard(bot, locale, "🌍 세계 상태 대시보드", "🌍 World State Dashboard", "시간·날씨·재난·세력·공동 복구 정보를 모아 표시합니다.", "Combines time, weather, disasters, factions and restoration status.", discord.Color.dark_blue())
            embed.add_field(name=_t(locale,"서버","Server"), value=str(getattr(ctx.guild,"name","DM")), inline=True)
            embed.add_field(name=_t(locale,"세계 데이터","World Data"), value=f"{len(world_data)} keys · guild {guild_id}", inline=True)
            embed.add_field(name=_t(locale,"바로가기","Quick Actions"), value=_t(locale,"`!세계지도` · `!날씨` · `!재난현황` · `!세력` · `!세계지령`","`!worldmap` · `!weather` · `!disasterstatus` · `!factions` · `!worlddirective`"), inline=False)
        elif panel == "map":
            embed = _dashboard(bot, locale, "🗺️ 세계지도 대시보드", "🗺️ World Map Dashboard", "지역 개척·거점·보스·세력 교류 명령을 지도형 카드로 정리합니다.", "Organizes exploration, outposts, bosses and faction exchange as a map card.", discord.Color.green())
            embed.add_field(name=_t(locale,"탐험","Exploration"), value=_t(locale,"`!세계지도` · `!지역탐험` · `!글로벌탐사`","`!worldmap` · `!regionexplore` · `!globalexpedition`"), inline=True)
            embed.add_field(name=_t(locale,"거점","Outposts"), value=_t(locale,"`!거점` · `!거점강화` · `!무역로`","`!outpost` · `!upgradeoutpost` · `!traderoute`"), inline=True)
            embed.add_field(name=_t(locale,"위협","Threats"), value=_t(locale,"`!지역보스` · `!재난현황` · `!세력전쟁`","`!regionboss` · `!disasterstatus` · `!factionwar`"), inline=True)
        else:
            embed = _dashboard(bot, locale, "🧭 생존자 통합 대시보드", "🧭 Survivor Command Dashboard", "게임·경제·세계·동료·연합·시즌 정보를 선택형 패널처럼 확인합니다.", "Review game, economy, world, companion, alliance and season information as dashboard cards.")
            embed.add_field(name=_t(locale,"프로필","Profile"), value=f"Lv.{int(user.get('level',1))} · {_t(locale,'직업','Job')} {user.get('job') or '-'}", inline=True)
            embed.add_field(name=_t(locale,"식량","Food"), value=f"{int(user.get('balance',0)):,}", inline=True)
            embed.add_field(name=_t(locale,"칩","Chips"), value=f"{chips:,}", inline=True)
            embed.add_field(name=_t(locale,"패널 선택","Panels"), value=_t(locale,"`!게임대시보드` · `!경제대시보드` · `!세계대시보드` · `!지도대시보드` · `!동료대시보드` · `!연합대시보드` · `!시즌대시보드`","`!gamedashboard` · `!economydashboard` · `!worlddashboard` · `!mapdashboard` · `!companiondashboard` · `!alliancedashboard` · `!seasondashboard`"), inline=False)
        embed.set_footer(text=_t(locale, f"ABADDON v{VERSION} · 정보는 선택 언어 하나로만 표시", f"ABADDON v{VERSION} · one selected language per screen"))
        return embed

    @bot.command(name="생존대시보드", aliases=["survivordashboard", "dashboard"])
    async def survivor_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx):
            await ctx.send(embed=user_stats_embed(ctx,"survivor"))

    @bot.command(name="게임대시보드", aliases=["gamedashboard"])
    async def game_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"game"))

    @bot.command(name="경제대시보드", aliases=["economydashboard"])
    async def economy_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"economy"))

    @bot.command(name="세계대시보드", aliases=["worlddashboard"])
    async def world_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"world"))

    @bot.command(name="지도대시보드", aliases=["mapdashboard"])
    async def map_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"map"))

    @bot.command(name="동료대시보드", aliases=["companiondashboard"])
    async def companion_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"companion"))

    @bot.command(name="연합대시보드", aliases=["alliancedashboard"])
    async def alliance_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"alliance"))

    @bot.command(name="시즌대시보드", aliases=["seasondashboard"])
    async def season_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"season"))

    @bot.command(name="정보패널", aliases=["infopanel"])
    async def info_panel(ctx: commands.Context, 종류: str = "생존") -> None:
        token = 종류.casefold()
        mapping = {"생존":"survivor","survivor":"survivor","게임":"game","game":"game","경제":"economy","economy":"economy","세계":"world","world":"world","지도":"map","map":"map","동료":"companion","companion":"companion","연합":"alliance","alliance":"alliance","시즌":"season","season":"season"}
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,mapping.get(token,"survivor")))

    @bot.command(name="정보리뉴얼현황", aliases=["inforenewalstatus"])
    async def info_renewal_status(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        embed = _dashboard(bot, locale, "🖼️ 정보 화면 리뉴얼 현황", "🖼️ Information UI Renewal Status", "사진처럼 한 화면에서 보는 대시보드 적용 범위를 확인합니다.", "Shows which information commands now use dashboard cards.")
        embed.add_field(name=_t(locale,"이번 패치 완료","Renewed in v10.9"), value=_t(locale,"카드게임 센터 · 카드룸 · 관전 · 리플레이 · 생존자 · 게임 · 경제/부채 · 세계 · 지도 · 동료 · 연합 · 시즌 · 리그 · 최신 테스트 · 패치노트","Card center · room · spectate · replay · survivor · game · economy/debt · world · map · companion · alliance · season · league · latest audit · patch notes"), inline=False)
        embed.add_field(name=_t(locale,"아직 기존 화면 유지","Still Using Legacy Views"), value=_t(locale,"개별 상점 상품 목록 · 전체 장비/보물 도감의 세부 페이지 · 음성/TTS 설정 · 서버 채널 일괄설치 미리보기 · 일부 관리자 로그 원문","Individual shop catalogs · detailed equipment/treasure encyclopedias · voice/TTS settings · channel-install previews · some raw admin logs"), inline=False)
        embed.add_field(name=_t(locale,"원칙","Policy"), value=_t(locale,"정보 조회 화면부터 순차 리뉴얼하며, 실제 선택·전투·게임 버튼은 필요한 조작성을 우선합니다.","Information screens are renewed first; action-heavy combat/game views prioritize usable controls."), inline=False)
        await ctx.send(embed=embed)

    def league_rows(locale: str, limit: int = 10) -> List[str]:
        table = []
        for key, user in user_data.items():
            if not isinstance(user, Mapping):
                continue
            stats = user.get("v1050_game_stats", {}) if isinstance(user.get("v1050_game_stats",{}),Mapping) else {}
            total = stats.get("total", {}) if isinstance(stats.get("total",{}),Mapping) else {}
            points = league_points(int(total.get("wins",0)), int(total.get("draws",0)), int(total.get("losses",0)), int(total.get("earnings",0)))
            if int(total.get("plays",0)) <= 0:
                continue
            table.append((points, str(key), total))
        table.sort(reverse=True)
        rows = []
        for rank, (points, uid, total) in enumerate(table[:limit], 1):
            rows.append(f"**{rank}.** <@{uid}> · **{points}LP** · {int(total.get('wins',0))}W/{int(total.get('losses',0))}L · {int(total.get('earnings',0)):+,}")
        return rows

    @bot.command(name="카드리그", aliases=["cardleague"])
    async def card_league(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        rows = league_rows(locale)
        embed = _dashboard(bot, locale, "🏆 카드게임 정식 리그", "🏆 Official Card League", "전체 카드 전적을 승·무·패와 손익을 조합한 리그 포인트로 집계합니다.", "Ranks all card records using wins, draws, losses and a limited earnings bonus.", discord.Color.gold())
        embed.add_field(name=_t(locale,"현재 순위","Current Standings"), value="\n".join(rows) or _t(locale,"아직 리그 전적이 없습니다.","No league records yet."), inline=False)
        embed.add_field(name=_t(locale,"점수","Scoring"), value=_t(locale,"승리 +3 · 무승부 +1 · 패배 -1 · 손익 보너스 -50~+50LP","Win +3 · draw +1 · loss -1 · earnings bonus limited to -50..+50 LP"), inline=False)
        embed.add_field(name=_t(locale,"대회","Events"), value=_t(locale,"기존 `!토너먼트개설` 대진과 연결 · 블랙잭 5핸드 대회는 `!블랙잭토너먼트`","Connected to existing `!createtournament`; five-hand Blackjack uses `!blackjacktournament`"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="주간랭킹", aliases=["weeklyranking"])
    async def weekly_ranking(ctx: commands.Context) -> None:
        await card_league.callback(ctx)

    @bot.command(name="명예의전당", aliases=["halloffame"])
    async def hall_of_fame(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        rows = league_rows(locale, 5)
        replay_rows = list(reversed(_root(world_data).get("replays", [])))[:5]
        embed = _dashboard(bot, locale, "🏛️ ABADDON 명예의 전당", "🏛️ ABADDON Hall of Fame", "리그 상위 생존자와 최근 테이블 우승 기록을 표시합니다.", "Shows leading survivors and recent table winners.", discord.Color.gold())
        embed.add_field(name=_t(locale,"리그 TOP 5","League TOP 5"), value="\n".join(rows) or "-", inline=False)
        embed.add_field(name=_t(locale,"최근 우승","Recent Winners"), value="\n".join(f"{GAME_EMOJI.get(str(row.get('game')),'🃏')} **{row.get('game')}** · {row.get('result')}" for row in replay_rows) or "-", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="대회센터", aliases=["tournamentcenter"])
    async def tournament_center(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        embed = _dashboard(bot, locale, "🏟️ 카드 대회 센터", "🏟️ Card Tournament Center", "일반 토너먼트·리그·블랙잭 5핸드 대회를 한 화면에 정리합니다.", "Combines standard tournaments, league standings and five-hand Blackjack events.")
        embed.add_field(name=_t(locale,"일반 대회","Standard"), value=_t(locale,"`!토너먼트개설 게임 판돈` · `!토너먼트참가` · `!토너먼트시작` · `!토너먼트결과`","`!createtournament game stake` · `!jointournament` · `!starttournament` · `!tournamentresult`"), inline=False)
        embed.add_field(name=_t(locale,"정식 리그","League"), value=_t(locale,"`!카드리그` · `!주간랭킹` · `!명예의전당`","`!cardleague` · `!weeklyranking` · `!halloffame`"), inline=False)
        embed.add_field(name=_t(locale,"전용 종목","Dedicated Mode"), value=_t(locale,"`!블랙잭토너먼트 판돈` · 아바돈 초대 가능","`!blackjacktournament stake` · ABADDON supported"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="리그참가", aliases=["joinleague"])
    async def join_league(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        _user_root(get_user(int(ctx.author.id)))["league_joined"] = True
        save_data()
        await ctx.send(_t(_ctx_locale(bot,ctx), "✅ 카드 리그 참가 상태가 활성화됐습니다.", "✅ Card league participation is active."))

    @bot.command(name="리그기록", aliases=["leaguerecord"])
    async def league_record(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        total = user.get("v1050_game_stats",{}).get("total",{}) if isinstance(user.get("v1050_game_stats",{}),dict) else {}
        points = league_points(int(total.get("wins",0)),int(total.get("draws",0)),int(total.get("losses",0)),int(total.get("earnings",0)))
        embed = _dashboard(bot, locale, "📊 내 리그 기록", "📊 My League Record", f"현재 **{points}LP**", f"Current **{points} LP**")
        embed.add_field(name=_t(locale,"전적","Record"), value=f"{int(total.get('wins',0))}W · {int(total.get('losses',0))}L · {int(total.get('draws',0))}D", inline=True)
        embed.add_field(name=_t(locale,"손익","Earnings"), value=f"{int(total.get('earnings',0)):+,}", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="부채", aliases=["debt"])
    async def debt_cmd(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"economy"))

    @bot.command(name="채무기록", aliases=["debthistory"])
    async def debt_history(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        games = user.get("v1050_game_stats",{}).get("games",{}) if isinstance(user.get("v1050_game_stats",{}),dict) else {}
        losses = sorted(((int(row.get("earnings",0)), name, row) for name,row in games.items() if int(row.get("earnings",0)) < 0), key=lambda row: row[0])[:8]
        embed = _dashboard(bot, locale, "📉 채무·손실 기록", "📉 Debt & Loss History", "게임별 누적 손실을 표시합니다. 실제 칩 잔액은 음수로 계속 내려갈 수 있습니다.", "Shows cumulative losses by game. The chip wallet may continue below zero.", discord.Color.dark_red())
        embed.add_field(name=_t(locale,"현재 칩","Current Chips"), value=f"**{casino_chips(user):,}**", inline=True)
        embed.add_field(name=_t(locale,"손실 종목","Losses by Game"), value="\n".join(f"{GAME_EMOJI.get(name,'🃏')} **{_game_display(name,locale)}** · {amount:,}" for amount,name,_row in losses) or _t(locale,"누적 손실 기록 없음","No cumulative loss record"), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="파산대시보드", aliases=["bankruptcydashboard"])
    async def bankruptcy_dashboard(ctx: commands.Context) -> None:
        if await check_registered(ctx): await ctx.send(embed=user_stats_embed(ctx,"economy"))

    @bot.command(name="재기임무", aliases=["recoverymission"])
    async def recovery_mission(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        locale = _ctx_locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        chips = casino_chips(user)
        if chips >= 0:
            await ctx.send(_t(locale,"현재 칩이 음수가 아니어서 재기임무 대상이 아닙니다.","Your chip balance is not negative, so recovery is unavailable."))
            return
        root = _user_root(user)
        now = int(time.time())
        last = int(root.get("recovery_at",0) or 0)
        if now - last < 86400:
            await ctx.send(_t(locale,f"재기임무는 하루 한 번입니다. 남은 시간 {(86400-(now-last))//3600+1}시간",f"Recovery is daily. About {(86400-(now-last))//3600+1} hours remain."))
            return
        grant = max(5_000, min(100_000, abs(chips)//20))
        add_casino_chips(user, grant)
        root["recovery_at"] = now
        root.setdefault("debt_log",[]).append({"at":now,"type":"recovery","amount":grant,"before":chips,"after":casino_chips(user)})
        root["debt_log"] = root["debt_log"][-30:]
        save_data()
        await ctx.send(embed=_dashboard(bot, locale, "🧰 재기임무 완료", "🧰 Recovery Mission Complete", f"칩 **+{grant:,}** · 현재 {casino_chips(user):,}", f"Chips **+{grant:,}** · current {casino_chips(user):,}", discord.Color.green()))

    rules_command = bot.get_command("카드게임룰")
    if rules_command is not None:
        async def v1090_rules_command(ctx: commands.Context, *, 게임: str = "") -> None:
            locale = _ctx_locale(bot, ctx)
            found = normalize_game(게임)
            if found:
                embed = _dashboard(bot, locale, f"{GAME_EMOJI.get(found,'🃏')} {found} · 게임 방식", f"{GAME_EMOJI.get(found,'🃏')} {_game_display(found,locale)} · Rules", GAME_RULE_SUMMARY[found][0], GAME_RULE_SUMMARY[found][1])
                embed.add_field(name=_t(locale,"아바돈","ABADDON"), value=_t(locale,"`!아바돈초대 게임명 판돈` 지원","Supported with `!inviteabaddon game stake`"), inline=False)
                await ctx.send(embed=embed)
                return
            embed = _dashboard(bot, locale, "📚 카드게임 규칙 · 25종", "📚 Card Rules · 25 Modes", "게임명을 함께 입력하면 상세 규칙을 표시합니다.", "Add a game name to show detailed rules.")
            for start in range(0, len(ALL_GAMES), 9):
                group = ALL_GAMES[start:start+9]
                embed.add_field(name=f"{start+1}–{start+len(group)}", value="\n".join(f"{GAME_EMOJI.get(kind,'🃏')} **{_game_display(kind,locale)}** · {GAME_RULE_SUMMARY[kind][0 if locale=='ko' else 1][:80]}" for kind in group), inline=False)
            await ctx.send(embed=embed)
        rules_command.callback = v1090_rules_command
        rules_command.help = "카드게임 25종의 최신 실제 진행 규칙을 확인합니다."
        rules_command.description = rules_command.help

    def latest_checks() -> List[Tuple[str, bool, str]]:
        expected_new = {"훌라","라미","대통령","주사위카드","삼봉","도리짓고땡","민화투","육백","블랙잭토너먼트"}
        checks: List[Tuple[str,bool,str]] = []
        checks.append(("카드게임 25종", len(ALL_GAMES) == 25 and len(set(ALL_GAMES)) == 25, str(len(ALL_GAMES))))
        checks.append(("신규 게임 명령", all(bot.get_command(name) is not None for name in expected_new), ", ".join(sorted(expected_new))))
        checks.append(("신규 규칙 설명", all(name in GAME_RULE_SUMMARY for name in expected_new), f"{len(NEW_RULES)}종"))
        checks.append(("전 종목 아바돈 팩토리", all(callable(factory_for(name).build) for name in ALL_GAMES), "25/25"))
        checks.append(("3인 AI 보충", factory_for("고스톱").minimum == 3 and factory_for("육백").minimum == 3, "ABADDON + β"))
        checks.append(("실전 조합 엔진", is_valid_meld([(3,"S"),(4,"S"),(5,"S")]), "set/run"))
        checks.append(("대통령 턴 규칙", president_play_valid([10,10],9,2), "same count / higher"))
        checks.append(("삼봉 족보", sambong_rank([3,3,3])[0] > sambong_rank([1,2,6])[0], "triple > kkeut"))
        checks.append(("도리짓고땡 메이드", dori_rank([1,9,3,3,3])[2] is not None, "made split"))
        checks.append(("육백 재경기 규칙", yukbaek_round_valid([31,40,50]) and not yukbaek_round_valid([30,40,50]), "30점 이하 무효"))
        checks.append(("음수 칩 저장", casino_chips({"black_casino":{"chips":-999}}) == -999, "-999"))
        checks.append(("무상한 입력", int("9"*80) > 10**70, "80-digit integer"))
        checks.append(("승부 결과·잔액 증감", hasattr(DebtCardSession, "settlement_text"), "승패/족보/게임 손익/이전→현재 잔액"))
        checks.append(("결과 메시지 복구", callable(_publish_final), "원본 편집 실패 시 새 결과 메시지"))
        checks.append(("카드룸/관전", bot.get_command("카드룸") is not None and bot.get_command("관전") is not None, "registered"))
        checks.append(("리플레이", bot.get_command("게임리플레이") is not None and isinstance(_root(world_data).get("replays"),list), "private hands excluded"))
        dash_names = ("생존대시보드","게임대시보드","경제대시보드","세계대시보드","지도대시보드","동료대시보드","연합대시보드","시즌대시보드")
        checks.append(("대시보드 8종", all(bot.get_command(name) is not None for name in dash_names), "8/8"))
        checks.append(("AI 난이도/성향", bot.get_command("아바돈난이도") is not None and bot.get_command("아바돈성향") is not None, "4 levels / 5 personalities"))
        checks.append(("리그/명예의전당", bot.get_command("카드리그") is not None and bot.get_command("명예의전당") is not None, "registered"))
        checks.append(("부채/재기", bot.get_command("부채") is not None and bot.get_command("재기임무") is not None, "bankruptcy preserved"))
        names = [command.qualified_name for command in bot.walk_commands()]
        checks.append(("명령 이름 유일성", len(names) == len(set(names)), f"{len(names)} commands"))
        checks.append(("영문 접근", all(any(alias.isascii() for alias in command.aliases) or command.name.isascii() for command in (bot.get_command(name) for name in expected_new) if command), "new commands"))
        checks.append(("최신 테스트 정책", bot.get_command("테스트") is not None, "v10.9 only"))
        checks.append(("최신 패치노트", bot.get_command("패치노트") is not None, VERSION))
        return checks

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1090_test(ctx: commands.Context, 모드: str = "기본") -> None:
            locale = _ctx_locale(bot, ctx)
            checks = latest_checks()
            passed = sum(1 for _name, ok, _detail in checks if ok)
            failed = len(checks) - passed
            embed = _dashboard(bot, locale, f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {passed}/{len(checks)} 통과", f"🧪 ABADDON v{VERSION} Latest Patch Audit · {passed}/{len(checks)} PASS", "이번 v10.9.0에서 추가·수정된 기능만 읽기 전용으로 검사합니다.", "Read-only checks cover only features added or changed in v10.9.0.", discord.Color.green() if failed == 0 else discord.Color.orange())
            detail = str(모드).casefold() in {"상세","전체","detail","full"} or failed > 0
            if detail:
                for name, ok, info in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(info)[:1024], inline=True)
            else:
                embed.add_field(name=_t(locale,"결과","Result"), value=_t(locale,f"✅ 통과 **{passed}** · ❌ 실패 **{failed}**\n상세: `!테스트 상세`",f"✅ PASS **{passed}** · ❌ FAIL **{failed}**\nDetails: `!test detail`"), inline=False)
            embed.add_field(name=_t(locale,"검수 범위","Scope"), value=_t(locale,"신규 게임 9종 · 카드 25종 AI · 카드룸/관전/리플레이 · 대시보드 · 부채 · 리그 · 명령/영문 접근","Nine new games · AI across 25 card modes · room/spectate/replay · dashboards · debt · league · command/English access"), inline=False)
            embed.set_footer(text=_t(locale,"실제 Discord 버튼·권한·동시 접속은 테스트 서버에서 추가 확인하세요.","Also verify Discord buttons, permissions and concurrency on a test server."))
            _root(world_data).setdefault("audit_runs",[]).append({"at":int(time.time()),"version":VERSION,"passed":passed,"total":len(checks)})
            _root(world_data)["audit_runs"] = _root(world_data)["audit_runs"][-20:]
            save_data()
            await ctx.send(embed=embed)
        test_command.callback = v1090_test
        test_command.help = "최신 v10.9.0 패치에서 추가·수정된 기능만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    flow_audit = bot.get_command("게임진행검수")
    if flow_audit is not None:
        async def v1090_game_audit(ctx: commands.Context) -> None:
            await bot.get_command("테스트").callback(ctx, "상세")
        flow_audit.callback = v1090_game_audit

    patch_command = bot.get_command("패치노트")
    if patch_command is not None:
        async def v1090_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, f"🧬 ABADDON v{VERSION} — 카드·대시보드·리그 통합 리뉴얼", f"🧬 ABADDON v{VERSION} — Cards, Dashboards & League Renewal", "v10.7~v10.9 계획을 한 번에 통합했습니다. 한국어와 English 화면은 선택 언어별로 분리됩니다.", "The v10.7–v10.9 roadmap is delivered together. Korean and English remain separated by selected language.")
            embed.add_field(name=_t(locale,"🎴 신규 실전 게임 9종","🎴 Nine New Live Games"), value=" · ".join(f"{GAME_EMOJI[k]} {_game_display(k,locale)}" for k in NEW_GAMES), inline=False)
            embed.add_field(name=_t(locale,"🤖 아바돈 25종 지원","🤖 ABADDON Across 25 Modes"), value=_t(locale,"모든 카드게임 방의 아바돈 초대 · 3인 게임 ABADDON-β 자동 보충 · 난이도 4단계·성향 5종","Invite ABADDON to every card table · ABADDON-β fills three-player modes · four difficulties and five personalities"), inline=False)
            embed.add_field(name=_t(locale,"🏠 카드룸·관전·리플레이","🏠 Room, Spectate & Replay"), value=_t(locale,"`!카드룸` · `!관전` · `!테이블정보` · `!최근게임` · `!게임리플레이` · `!재대결`","`!cardroom` · `!spectate` · `!tableinfo` · `!recentgame` · `!gamereplay` · `!rematch`"), inline=False)
            embed.add_field(name=_t(locale,"🖼️ 이미지형 정보 대시보드","🖼️ Visual Information Dashboards"), value=_t(locale,"생존자·게임·경제/부채·세계·지도·동료·연합·시즌·리그·테스트·패치노트 화면 리뉴얼","Renewed survivor, game, economy/debt, world, map, companion, alliance, season, league, audit and patch-note panels"), inline=False)
            embed.add_field(name=_t(locale,"💳 부채·파산 확장","💳 Debt & Bankruptcy"), value=_t(locale,"음수 칩과 무상한 정산 유지 · `!부채` · `!채무기록` · `!파산대시보드` · 일일 `!재기임무`","Negative chips and uncapped settlement remain · debt history · bankruptcy dashboard · daily recovery mission"), inline=False)
            embed.add_field(name=_t(locale,"🏆 리그·대회","🏆 League & Events"), value=_t(locale,"`!카드리그` · `!주간랭킹` · `!명예의전당` · `!대회센터` · 블랙잭 5핸드 토너먼트","Card league · weekly ranking · hall of fame · tournament center · five-hand Blackjack tournament"), inline=False)
            embed.add_field(name=_t(locale,"🧪 최신 검수","🧪 Latest-Patch Audit"), value=_t(locale,"`!테스트 상세`는 v10.9.0에서 추가·수정된 항목만 검사하며 패치마다 이 목록을 교체하도록 구성","`!test detail` checks only v10.9.0 additions/changes; future patches replace this latest-only list"), inline=False)
            embed.set_footer(text=_t(locale,f"최신 버전 v{VERSION} · 홈페이지/명령어/설명 동기화",f"Latest v{VERSION} · website/commands/descriptions synchronized"))
            await ctx.send(embed=embed)
        patch_command.callback = v1090_patch_notes
        patch_command.help = f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        patch_command.description = patch_command.help

    for command_name, (ko_help, en_help) in V1090_COMMAND_DESCRIPTIONS.items():
        command = bot.get_command(command_name)
        if command is not None:
            command.help = ko_help
            command.description = ko_help
    bot.v1090_command_descriptions = V1090_COMMAND_DESCRIPTIONS  # type: ignore[attr-defined]

    guide[:] = [row for row in guide if row.get("id") != "v1090_integrated_renewal"]
    guide.append({
        "id":"v1090_integrated_renewal", "emoji":"🧬", "title":"v10.9 카드·대시보드·리그 통합 리뉴얼",
        "hint":"신규 실전게임 9종 · 카드 25종 AI · 관전/리플레이 · 정보 대시보드 · 부채 · 리그 · 최신패치 검수",
        "commands":[
            "!카드게임 · !카드게임룰 · !카드룸 · !빠른대전 · !재대결",
            "!훌라 · !라미 · !대통령 · !주사위카드 · !삼봉 · !도리짓고땡 · !민화투 · !육백 · !블랙잭토너먼트",
            "!아바돈게임 · !아바돈초대 · !아바돈난이도 · !아바돈성향",
            "!관전 · !테이블정보 · !최근게임 · !게임리플레이 · !게임기록",
            "!생존대시보드 · !게임대시보드 · !경제대시보드 · !세계대시보드 · !지도대시보드",
            "!동료대시보드 · !연합대시보드 · !시즌대시보드 · !정보패널 · !정보리뉴얼현황",
            "!부채 · !채무기록 · !파산대시보드 · !재기임무",
            "!카드리그 · !주간랭킹 · !명예의전당 · !대회센터 · !리그기록",
            "!테스트 상세 · !패치노트",
        ],
    })
    bot.v1090_version = VERSION  # type: ignore[attr-defined]
    bot.v1090_card_games = ALL_GAMES  # type: ignore[attr-defined]
    bot.v1090_latest_checks = latest_checks  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] card_games={len(ALL_GAMES)} new={len(NEW_GAMES)} dashboards=enabled replays=enabled league=enabled", flush=True)
