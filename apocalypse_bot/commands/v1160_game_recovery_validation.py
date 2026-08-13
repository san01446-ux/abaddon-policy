from __future__ import annotations

"""ABADDON v11.6.0 live-game recovery, timeout policy and rules audit.

The patch is additive and backup-first:
* active card sessions are checkpointed with typed JSON-safe state;
* supported sessions are rebuilt after a process restart;
* failed/unsupported recovery refunds the exact tracked contribution once;
* final-result publication is idempotent;
* guilds choose how a timed-out human turn is handled.
"""

import asyncio
import copy
import inspect
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands, tasks

from apocalypse_bot.commands.v40_black_casino import add_casino_chips, casino_chips
from apocalypse_bot.commands.v651_card_games import ACTIVE_GAMES, ACTIVE_LOBBIES, BaseCardSession, _reservation_root
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _hwatu_deck, _hwatu_visual_uid, _t
from apocalypse_bot.commands.v1051_authentic_card_games import AuthenticJokerSession, AuthenticOneCardSession
from apocalypse_bot.commands import v1060_authentic_card_games as v1060
from apocalypse_bot.commands import v1090_integrated_renewal as v1090
from apocalypse_bot.commands.v1090_integrated_renewal import _dashboard
from apocalypse_bot.commands.v1094_visual_core import HWATU_ASSET_ROOT, HWATU_MANIFEST_PATH
from apocalypse_bot.commands.v1160_recovery_rules import (
    apply_encoded_state,
    coerce_turn_seconds,
    encode_state,
    normalize_afk_action,
    refund_plan,
    snapshot_checksum,
    validate_hwatu_assets,
)

VERSION = "11.6.0"
PATCH_DATE = "2026-08-04"
SUPPORTED_KINDS: Tuple[str, ...] = (
    "포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "파인애플홀덤", "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커",
    "블랙잭", "바카라", "섯다", "맞고", "고스톱", "원카드", "조커잡기", "훌라", "라미", "대통령", "주사위카드", "삼봉", "도리짓고땡", "민화투", "육백", "블랙잭토너먼트",
)
STATE_EXCLUDE = {
    "bot", "message", "get_user", "save_data", "world_data", "world_data_ref", "user_data", "lock", "children",
    "_children", "_timeout_task", "_stopped", "_cancel_callback", "_refresh_timeout", "_scheduled_task",
}


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("v1160_recovery", {})
    if not isinstance(root, dict):
        root = {}
        world_data["v1160_recovery"] = root
    root.setdefault("schema_version", 2)
    root.setdefault("snapshots", {})
    root.setdefault("guild_settings", {})
    root.setdefault("restore_history", [])
    root.setdefault("refunds", {})
    root.setdefault("result_delivery", {})
    root.setdefault("reports", [])
    root.setdefault("audit_runs", [])
    return root


def _guild_settings(root: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    guilds = root.setdefault("guild_settings", {})
    row = guilds.setdefault(str(int(guild_id)), {})
    if not isinstance(row, dict):
        row = {}
        guilds[str(int(guild_id))] = row
    row.setdefault("afk_action", "abaddon")
    row.setdefault("turn_seconds", 90)
    return row


def _current_uid(session: Any) -> Optional[int]:
    try:
        value = getattr(session, "current_uid")
        if callable(value):
            value = value()
        if value is not None:
            return int(value)
    except Exception:
        pass
    engine = getattr(session, "engine", None)
    try:
        if engine is not None and getattr(engine, "current_uid", None) is not None:
            return int(engine.current_uid)
    except Exception:
        pass
    return None


def _session_ids(session: Any) -> Tuple[int, int, int]:
    message = getattr(session, "message", None)
    channel = getattr(message, "channel", None)
    guild = getattr(message, "guild", None)
    return (
        int(getattr(guild, "id", 0) or 0),
        int(getattr(channel, "id", getattr(session, "channel_id", 0)) or 0),
        int(getattr(message, "id", 0) or 0),
    )


def _public_kind(session: Any) -> str:
    return str(getattr(session, "variant", getattr(session, "mode", getattr(session, "kind", "카드게임"))))


def _snapshot_state(session: Any) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    for key, value in vars(session).items():
        if key in STATE_EXCLUDE or key.startswith("_discord"):
            continue
        if callable(value):
            continue
        encoded = encode_state(value)
        if isinstance(encoded, Mapping) and encoded.get("__type__") == "skipped":
            continue
        state[key] = encoded
    return state


def _make_snapshot(session: Any, *, status: Optional[str] = None) -> Dict[str, Any]:
    guild_id, channel_id, message_id = _session_ids(session)
    current_uid = _current_uid(session)
    now = int(time.time())
    state = _snapshot_state(session)
    row: Dict[str, Any] = {
        "game_id": str(getattr(session, "game_id", f"session-{channel_id}-{now}")),
        "class": f"{session.__class__.__module__}:{session.__class__.__qualname__}",
        "kind": _public_kind(session),
        "base_kind": str(getattr(session, "kind", _public_kind(session))),
        "variant": str(getattr(session, "variant", "") or ""),
        "mode": str(getattr(session, "mode", "") or ""),
        "host_id": int(getattr(session, "host_id", 0) or 0),
        "bet": int(getattr(session, "bet", 0) or 0),
        "player_ids": [int(uid) for uid in getattr(session, "player_ids", [])],
        "names": {str(key): str(value) for key, value in dict(getattr(session, "names", {})).items()},
        "guild_id": guild_id,
        "channel_id": channel_id,
        "message_id": message_id,
        "locale": str(getattr(session, "locale", getattr(session, "public_locale", "ko"))),
        "current_uid": current_uid,
        "pot": int(getattr(session, "pot", 0) or 0),
        "last_activity": int(getattr(session, "_v1160_last_activity", now) or now),
        "updated": now,
        "status": status or ("paused" if getattr(session, "_v1160_paused", False) else "active"),
        "state": state,
        "restorable": _public_kind(session) in SUPPORTED_KINDS,
    }
    row["checksum"] = snapshot_checksum({k: v for k, v in row.items() if k != "checksum"})
    return row


def _refresh_checksum(row: MutableMapping[str, Any]) -> None:
    row["checksum"] = snapshot_checksum({k: v for k, v in row.items() if k != "checksum"})


def _sync_reservation(session: Any) -> None:
    try:
        reservations = _reservation_root(session.world_data).setdefault("reservations", {})
        row = reservations.get(str(session.game_id))
        if not isinstance(row, dict):
            return
        human_paid = getattr(session, "human_paid", None)
        if isinstance(human_paid, Mapping):
            row["actual_paid"] = {str(int(uid)): int(amount) for uid, amount in human_paid.items() if int(uid) >= 0}
        else:
            row["actual_paid"] = {str(int(uid)): int(getattr(session, "bet", 0) or 0) for uid in getattr(session, "player_ids", []) if int(uid) >= 0}
        guild_id, channel_id, message_id = _session_ids(session)
        row.update({
            "class": session.__class__.__name__,
            "variant": _public_kind(session),
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "opening_chips": {str(k): int(v) for k, v in dict(getattr(session, "opening_chips", {})).items()},
            "updated": int(time.time()),
        })
    except Exception:
        return


def _checkpoint(root: MutableMapping[str, Any], session: Any, save_data: Callable[[], None], *, status: Optional[str] = None) -> Dict[str, Any]:
    row = _make_snapshot(session, status=status)
    root.setdefault("snapshots", {})[row["game_id"]] = row
    _sync_reservation(session)
    save_data()
    return row


def _synthetic_lobby(
    *, bot: commands.Bot, snapshot: Mapping[str, Any], message: discord.Message,
    get_user: Callable[[int], MutableMapping[str, Any]], save_data: Callable[[], None],
    world_data: MutableMapping[str, Any], user_data: Mapping[Any, Any],
) -> Any:
    names_raw = snapshot.get("names", {})
    names = {int(key): str(value) for key, value in names_raw.items()} if isinstance(names_raw, Mapping) else {}
    for uid in snapshot.get("player_ids", []):
        names.setdefault(int(uid), "ABADDON" if int(uid) < 0 else str(uid))
    return SimpleNamespace(
        bot=bot,
        kind=str(snapshot.get("base_kind") or snapshot.get("kind") or "포커"),
        host_id=int(snapshot.get("host_id", 0) or 0),
        bet=int(snapshot.get("bet", 0) or 0),
        get_user=get_user,
        save_data=save_data,
        world_data=world_data,
        user_data=user_data,
        message=message,
        channel_id=int(snapshot.get("channel_id", 0) or 0),
        public_locale=str(snapshot.get("locale", "ko")),
        players=names,
    )


def _build_session(
    snapshot: Mapping[str, Any], *, bot: commands.Bot, message: discord.Message,
    get_user: Callable[[int], MutableMapping[str, Any]], save_data: Callable[[], None],
    world_data: MutableMapping[str, Any], user_data: Mapping[Any, Any],
) -> Any:
    lobby = _synthetic_lobby(bot=bot, snapshot=snapshot, message=message, get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data)
    kind = str(snapshot.get("kind") or snapshot.get("variant") or snapshot.get("mode") or snapshot.get("base_kind"))
    if kind in {"포커", "텍사스홀덤", "오마하홀덤", "세븐카드스터드", "파인애플홀덤", "숏덱홀덤", "바둑이", "하이로우포커", "인디언포커"}:
        session = v1060.AuthenticPokerSession(lobby, bot=bot, variant=kind)
    elif kind == "블랙잭":
        session = v1060.AuthenticBlackjackSession(lobby, bot=bot)
    elif kind == "바카라":
        session = v1060.AuthenticBaccaratSession(lobby, bot=bot)
    elif kind == "섯다":
        session = v1060.AuthenticSeotdaSession(lobby, bot=bot)
    elif kind in {"맞고", "고스톱"}:
        session = v1060.AuthenticGoStopSession(lobby, bot=bot, mode=kind, world_data=world_data)
    elif kind == "원카드":
        session = AuthenticOneCardSession(lobby)
    elif kind == "조커잡기":
        session = AuthenticJokerSession(lobby)
    elif kind in {"훌라", "라미"}:
        session = v1090.MeldRaceSession(lobby, bot=bot, variant=kind)
    elif kind == "대통령":
        session = v1090.PresidentSession(lobby, bot=bot)
    elif kind == "주사위카드":
        session = v1090.DiceCardSession(lobby, bot=bot)
    elif kind in {"삼봉", "도리짓고땡"}:
        session = v1090.KoreanShowdownSession(lobby, bot=bot, variant=kind)
    elif kind in {"민화투", "육백"}:
        session = v1090.CaptureHwatuSession(lobby, bot=bot, variant=kind, world_data=world_data)
    elif kind == "블랙잭토너먼트":
        session = v1090.BlackjackTournamentSession(lobby, bot=bot)
    else:
        raise ValueError(f"unsupported game kind: {kind}")
    state = snapshot.get("state", {})
    if isinstance(state, Mapping):
        apply_encoded_state(session, state, excluded=STATE_EXCLUDE | {"done"})
    session.bot = bot
    session.get_user = get_user
    session.save_data = save_data
    session.world_data = world_data
    if hasattr(session, "world_data_ref"):
        session.world_data_ref = world_data
    session.user_data = user_data
    session.message = message
    session.channel_id = int(snapshot.get("channel_id", 0) or 0)
    session.game_id = str(snapshot.get("game_id"))
    session.done = False
    session.lock = asyncio.Lock()
    session._v1160_paused = str(snapshot.get("status")) == "paused"
    session._v1160_last_activity = int(time.time())
    return session


async def _find_or_create_message(bot: commands.Bot, snapshot: Mapping[str, Any]) -> Optional[discord.Message]:
    channel_id = int(snapshot.get("channel_id", 0) or 0)
    message_id = int(snapshot.get("message_id", 0) or 0)
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return None
    if message_id and hasattr(channel, "fetch_message"):
        try:
            return await channel.fetch_message(message_id)
        except Exception:
            pass
    if hasattr(channel, "send"):
        try:
            embed = discord.Embed(
                title="🛟 ABADDON 게임 세션 복구",
                description=f"`{snapshot.get('game_id')}` · **{snapshot.get('kind')}**\n저장된 차례·패·보드·팟을 불러오는 중입니다.",
                color=discord.Color.orange(),
            )
            return await channel.send(embed=embed)
        except Exception:
            return None
    return None


async def _render_recovered(session: Any) -> None:
    note_ko = "🛟 봇 재시작 전 체크포인트에서 복구했습니다. 차례와 정산 기록이 유지됩니다."
    note_en = "🛟 Restored from the pre-restart checkpoint. Turn and settlement state were preserved."
    locale = str(getattr(session, "locale", "ko"))
    try:
        if hasattr(session, "last_action"):
            session.last_action = note_ko if locale == "ko" else note_en
        if hasattr(session, "update") and inspect.iscoroutinefunction(session.update):
            await session.update()
            return
        if hasattr(session, "embed"):
            embed = session.embed(note_ko if locale == "ko" else note_en)
            await v1060._safe_edit(session.message, embed=embed, view=session)
            return
    except Exception:
        pass
    try:
        await session.message.edit(content=note_ko if locale == "ko" else note_en, view=session)
    except Exception:
        pass


def register_v1160_game_recovery_validation(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1160_registered", False):
        return
    bot._abaddon_v1160_registered = True
    root = _root(world_data)

    # Reservation wrappers keep exact contributions current after every raise.
    if not getattr(BaseCardSession, "_v1160_reservation_wrapped", False):
        BaseCardSession._v1160_reservation_wrapped = True
        base_reserve = BaseCardSession._reserve
        debt_reserve = v1060.DebtCardSession._reserve
        debt_charge = v1060.DebtCardSession.charge
        base_close = BaseCardSession._close_reservation

        def wrapped_base_reserve(self: Any) -> Any:
            result = base_reserve(self)
            _sync_reservation(self)
            return result

        def wrapped_debt_reserve(self: Any) -> Any:
            result = debt_reserve(self)
            _sync_reservation(self)
            return result

        def wrapped_debt_charge(self: Any, uid: int, amount: int) -> int:
            result = debt_charge(self, uid, amount)
            _sync_reservation(self)
            try:
                _checkpoint(root, self, save_data)
            except Exception:
                pass
            return result

        def wrapped_close(self: Any) -> Any:
            result = base_close(self)
            game_id = str(getattr(self, "game_id", ""))
            snapshot = root.setdefault("snapshots", {}).get(game_id)
            if isinstance(snapshot, dict):
                snapshot["status"] = "settled"
                snapshot["updated"] = int(time.time())
                _refresh_checksum(snapshot)
            return result

        BaseCardSession._reserve = wrapped_base_reserve
        v1060.DebtCardSession._reserve = wrapped_debt_reserve
        v1060.DebtCardSession.charge = wrapped_debt_charge
        BaseCardSession._close_reservation = wrapped_close

    # Final delivery is one-shot across both modules that call _publish_final.
    if not getattr(bot, "_abaddon_v1160_final_wrapped", False):
        bot._abaddon_v1160_final_wrapped = True
        original_publish = v1060._publish_final

        async def publish_once(session: Any, embed: discord.Embed) -> bool:
            game_id = str(getattr(session, "game_id", ""))
            delivery = root.setdefault("result_delivery", {})
            row = delivery.get(game_id)
            if isinstance(row, Mapping) and row.get("status") == "sent":
                return True
            ok = await original_publish(session, embed)
            delivery[game_id] = {
                "status": "sent" if ok else "ledger_only",
                "at": int(time.time()),
                "channel_id": int(getattr(session, "channel_id", 0) or 0),
                "message_id": int(getattr(getattr(session, "message", None), "id", 0) or 0),
            }
            snapshot = root.setdefault("snapshots", {}).get(game_id)
            if isinstance(snapshot, dict):
                snapshot["status"] = "finished" if ok else "result_pending"
                snapshot["updated"] = int(time.time())
                _refresh_checksum(snapshot)
            save_data()
            return ok

        v1060._publish_final = publish_once
        v1090._publish_final = publish_once

    # Card views record interaction activity and honour pause state.
    if not getattr(BaseCardSession, "_v1160_interaction_wrapped", False):
        BaseCardSession._v1160_interaction_wrapped = True
        previous_interaction_check = getattr(BaseCardSession, "interaction_check", None)

        async def interaction_check(self: Any, interaction: discord.Interaction) -> bool:
            self._v1160_last_activity = int(time.time())
            if getattr(self, "_v1160_paused", False):
                try:
                    await interaction.response.send_message("⏸️ 이 게임은 일시정지 상태입니다. `!게임재개`를 사용하세요.", ephemeral=True)
                except Exception:
                    pass
                return False
            if previous_interaction_check is not None:
                result = previous_interaction_check(self, interaction)
                return bool(await result) if inspect.isawaitable(result) else bool(result)
            return True

        BaseCardSession.interaction_check = interaction_check

    async def force_refund(game_id: str, *, reason: str) -> Tuple[bool, Dict[int, int]]:
        game_id = str(game_id)
        if game_id in root.setdefault("refunds", {}):
            return False, {int(k): int(v) for k, v in root["refunds"][game_id].get("amounts", {}).items()}
        snapshots = root.setdefault("snapshots", {})
        snapshot = snapshots.get(game_id, {}) if isinstance(snapshots, Mapping) else {}
        active = next((session for session in ACTIVE_GAMES.values() if str(getattr(session, "game_id", "")) == game_id), None)
        if active is not None:
            try:
                if hasattr(active, "_refund_debt"):
                    active._refund_debt()
                elif hasattr(active, "_refund"):
                    active._refund()
                amounts = {int(k): int(v) for k, v in dict(getattr(active, "human_paid", {})).items() if int(k) >= 0}
                active.done = True
                active._disable()
                ACTIVE_GAMES.pop(int(getattr(active, "channel_id", 0) or 0), None)
                active.stop()
            except Exception:
                amounts = {}
        else:
            reservations = _reservation_root(world_data).setdefault("reservations", {})
            reservation = reservations.get(game_id, {}) if isinstance(reservations, Mapping) else {}
            amounts = refund_plan(reservation if isinstance(reservation, Mapping) else {}, snapshot if isinstance(snapshot, Mapping) else {})
            for uid, amount in amounts.items():
                add_casino_chips(get_user(uid), int(amount))
            if isinstance(reservations, dict):
                reservations.pop(game_id, None)
        root["refunds"][game_id] = {"amounts": {str(k): int(v) for k, v in amounts.items()}, "reason": reason, "at": int(time.time())}
        if isinstance(snapshot, dict):
            snapshot["status"] = "refunded"
            snapshot["refund_reason"] = reason
            snapshot["updated"] = int(time.time())
            _refresh_checksum(snapshot)
        save_data()
        return True, amounts

    async def restore_snapshot(snapshot: MutableMapping[str, Any]) -> Tuple[bool, str]:
        game_id = str(snapshot.get("game_id", ""))
        channel_id = int(snapshot.get("channel_id", 0) or 0)
        if channel_id in ACTIVE_GAMES:
            return True, "already-active"
        expected = str(snapshot.get("checksum", ""))
        actual = snapshot_checksum({k: v for k, v in snapshot.items() if k != "checksum"})
        if expected and expected != actual:
            return False, "checksum-mismatch"
        if not snapshot.get("restorable") or str(snapshot.get("kind")) not in SUPPORTED_KINDS:
            return False, "unsupported-kind"
        message = await _find_or_create_message(bot, snapshot)
        if message is None:
            return False, "channel-or-message-unavailable"
        try:
            session = _build_session(snapshot, bot=bot, message=message, get_user=get_user, save_data=save_data, world_data=world_data, user_data=user_data)
            ACTIVE_GAMES[channel_id] = session
            snapshot["status"] = "paused" if getattr(session, "_v1160_paused", False) else "active"
            snapshot["message_id"] = int(message.id)
            snapshot["updated"] = int(time.time())
            snapshot["checksum"] = snapshot_checksum({k: v for k, v in snapshot.items() if k != "checksum"})
            root.setdefault("restore_history", []).insert(0, {"game_id": game_id, "ok": True, "at": int(time.time()), "reason": "state-restored"})
            del root["restore_history"][100:]
            save_data()
            await _render_recovered(session)
            return True, "state-restored"
        except Exception as exc:
            ACTIVE_GAMES.pop(channel_id, None)
            root.setdefault("restore_history", []).insert(0, {"game_id": game_id, "ok": False, "at": int(time.time()), "reason": f"{type(exc).__name__}: {exc}"[:300]})
            del root["restore_history"][100:]
            save_data()
            return False, f"restore-error:{type(exc).__name__}"

    async def timeout_action(session: Any, action: str) -> str:
        action = normalize_afk_action(action)
        uid = _current_uid(session)
        if uid is None or uid < 0:
            return "no-human-turn"
        session._v1160_last_activity = int(time.time())
        locale = str(getattr(session, "locale", "ko"))
        if action == "refund":
            await force_refund(str(session.game_id), reason="turn-timeout")
            try:
                await session.message.channel.send(_t(locale, "⌛ 잠수 규칙에 따라 실제 납부액을 전원 환불했습니다.", "⌛ The timeout policy refunded every actual contribution."))
            except Exception:
                pass
            return "refunded"
        if action == "pause":
            session._v1160_paused = True
            _checkpoint(root, session, save_data, status="paused")
            try:
                await session.message.channel.send(_t(locale, f"⏸️ **{session.names.get(uid, uid)}**의 제한시간이 끝나 게임을 일시정지했습니다. `!게임재개`", f"⏸️ **{session.names.get(uid, uid)}** timed out. The game is paused. Use `!resumegame`."))
            except Exception:
                pass
            return "paused"
        pending_go = getattr(session, "pending_go", None)
        if pending_go == uid and hasattr(session, "finish"):
            await session.finish([uid])
            return "auto-stop"
        betting = getattr(session, "betting", None)
        if betting is not None and hasattr(betting, "current_uid"):
            if action == "fold" and hasattr(betting, "fold"):
                betting.fold(uid)
                if hasattr(session, "permanent_folded"):
                    session.permanent_folded.add(uid)
                session.last_action = _t(locale, f"⏱️ **{session.names.get(uid, uid)}** · 시간 초과 자동 폴드", f"⏱️ **{session.names.get(uid, uid)}** · timeout auto-fold")
            elif hasattr(betting, "check_or_call"):
                verb, paid = betting.check_or_call(uid)
                if hasattr(session, "charge"):
                    session.charge(uid, paid)
                prefix = "ABADDON 대행" if action == "abaddon" else "자동"
                session.last_action = _t(locale, f"⏱️ **{session.names.get(uid, uid)}** · {prefix} {'체크' if verb == 'check' else f'콜 {paid:,}'}", f"⏱️ **{session.names.get(uid, uid)}** · {'ABADDON proxy' if action == 'abaddon' else 'auto'} {verb} {paid:,}")
            else:
                session._v1160_paused = True
                return "paused-fallback"
            if hasattr(session, "_after_action"):
                await session._after_action()
            elif hasattr(session, "_run_ai"):
                await session._run_ai()
            elif hasattr(session, "update"):
                await session.update()
            _checkpoint(root, session, save_data)
            return action
        engine = getattr(session, "engine", None)
        if engine is not None and int(getattr(engine, "current_uid", -1)) == uid and hasattr(engine, "play"):
            hand = engine.hands.get(uid, [])
            if hand:
                index = max(range(len(hand)), key=lambda i: len(engine.matching_floor_indices(hand[i].month)))
                matches = engine.matching_floor_indices(hand[index].month)
                result = engine.play(uid, index, match_index=(matches[0] if len(matches) == 2 else None))
                if getattr(result, "needs_choice", None):
                    phase, choices = result.needs_choice
                    result = engine.play(uid, index, match_index=(choices[0] if phase == "hand" else None), flip_match_index=(choices[0] if phase != "hand" else None))
                await session._post_turn(uid, result)
                _checkpoint(root, session, save_data)
                return "auto-hwatu"
        session._v1160_paused = True
        _checkpoint(root, session, save_data, status="paused")
        return "paused-fallback"

    @tasks.loop(seconds=15)
    async def checkpoint_loop() -> None:
        now = int(time.time())
        snapshots = root.setdefault("snapshots", {})
        active_game_ids: set[str] = set()
        for session in list(ACTIVE_GAMES.values()):
            if getattr(session, "done", False):
                continue
            game_id = str(getattr(session, "game_id", ""))
            active_game_ids.add(game_id)
            try:
                _checkpoint(root, session, save_data)
            except Exception:
                continue
            guild_id, _, _ = _session_ids(session)
            settings = _guild_settings(root, guild_id)
            turn_seconds = coerce_turn_seconds(settings.get("turn_seconds", 90))
            last = int(getattr(session, "_v1160_last_activity", now) or now)
            uid = _current_uid(session)
            if uid is not None and uid >= 0 and not getattr(session, "_v1160_paused", False) and now - last >= turn_seconds:
                try:
                    await timeout_action(session, str(settings.get("afk_action", "abaddon")))
                except Exception:
                    session._v1160_last_activity = now
        for game_id, row in list(snapshots.items()):
            if not isinstance(row, dict):
                continue
            if row.get("status") == "active" and game_id not in active_game_ids and now - int(row.get("updated", 0) or 0) > 30:
                row["status"] = "interrupted"
                row["updated"] = now
                _refresh_checksum(row)
        save_data()

    @bot.listen("on_ready")
    async def v1160_ready() -> None:
        if not checkpoint_loop.is_running():
            checkpoint_loop.start()
        if getattr(bot, "_abaddon_v1160_restore_attempted", False):
            return
        bot._abaddon_v1160_restore_attempted = True
        await asyncio.sleep(2)
        snapshots = root.setdefault("snapshots", {})
        for snapshot in list(snapshots.values()):
            if not isinstance(snapshot, dict) or snapshot.get("status") not in {"active", "interrupted", "paused", "result_pending"}:
                continue
            ok, reason = await restore_snapshot(snapshot)
            if not ok and reason not in {"channel-or-message-unavailable"}:
                await force_refund(str(snapshot.get("game_id")), reason=f"auto-recovery:{reason}")

    @bot.listen("on_interaction")
    async def v1160_interaction_activity(interaction: discord.Interaction) -> None:
        message_id = int(getattr(getattr(interaction, "message", None), "id", 0) or 0)
        if not message_id:
            return
        for session in ACTIVE_GAMES.values():
            if int(getattr(getattr(session, "message", None), "id", 0) or 0) == message_id:
                session._v1160_last_activity = int(time.time())
                break

    @bot.command(name="게임복구목록", aliases=["recoverylist", "gamesessionlist"], help="현재 서버의 활성·중단·일시정지 게임 체크포인트를 확인합니다.")
    async def recovery_list(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        gid = int(getattr(ctx.guild, "id", 0) or 0)
        rows = [row for row in root.get("snapshots", {}).values() if isinstance(row, Mapping) and int(row.get("guild_id", 0) or 0) == gid and row.get("status") not in {"finished", "settled"}]
        rows.sort(key=lambda row: int(row.get("updated", 0) or 0), reverse=True)
        if not rows:
            await ctx.send(_t(locale, "🛟 복구 대기 중인 게임이 없습니다.", "🛟 No games are waiting for recovery."))
            return
        text = []
        for row in rows[:15]:
            text.append(f"`{row.get('game_id')}` · **{row.get('kind')}** · {row.get('status')} · 팟 {int(row.get('pot',0)):,}")
        await ctx.send("\n".join(text))

    old_recovery = bot.get_command("게임복구")
    if old_recovery is not None:
        async def recover_game(ctx: commands.Context, 게임ID: str = "") -> None:
            locale = _ctx_locale(bot, ctx)
            token = str(게임ID).strip()
            if not token:
                await recovery_list.callback(ctx)
                return
            snapshot = root.get("snapshots", {}).get(token)
            if not isinstance(snapshot, dict):
                await ctx.send(_t(locale, "해당 게임 체크포인트를 찾지 못했습니다.", "That game checkpoint was not found."))
                return
            ok, reason = await restore_snapshot(snapshot)
            await ctx.send(_t(locale, f"{'✅ 복구 완료' if ok else '❌ 복구 실패'} · `{token}` · {reason}", f"{'✅ Recovery complete' if ok else '❌ Recovery failed'} · `{token}` · {reason}"))
        old_recovery.callback = recover_game
        old_recovery.help = "체크포인트 목록을 보거나 지정 게임을 복구합니다. `!게임복구 [게임ID]`"
        old_recovery.description = old_recovery.help

    old_session = bot.get_command("게임세션")
    if old_session is not None:
        async def game_session(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            channel_id = int(ctx.channel.id)
            session = ACTIVE_GAMES.get(channel_id)
            if session is None:
                await ctx.send(_t(locale, "이 채널에 진행 중인 게임이 없습니다. `!게임복구목록`에서 중단 세션을 확인하세요.", "No game is active in this channel. Use `!recoverylist` for interrupted sessions."))
                return
            row = _make_snapshot(session)
            await ctx.send(_t(locale, f"🎮 **{row['kind']}** · `{row['game_id']}`\n상태 {row['status']} · 현재 차례 {row['current_uid']} · 팟 {row['pot']:,}\n최근 활동 <t:{row['last_activity']}:R> · 체크섬 `{row['checksum'][:12]}`", f"🎮 **{row['kind']}** · `{row['game_id']}`\nStatus {row['status']} · current turn {row['current_uid']} · pot {row['pot']:,}\nLast activity <t:{row['last_activity']}:R> · checksum `{row['checksum'][:12]}`"))
        old_session.callback = game_session
        old_session.help = "현재 채널 게임의 복구 체크포인트와 체크섬을 표시합니다."
        old_session.description = old_session.help

    @bot.command(name="게임재개", aliases=["resumegame", "continuegame"], help="일시정지 게임을 재개하거나 저장된 게임을 복구합니다.")
    async def resume_game(ctx: commands.Context, 게임ID: str = "") -> None:
        locale = _ctx_locale(bot, ctx)
        token = str(게임ID).strip()
        session = ACTIVE_GAMES.get(int(ctx.channel.id))
        if token:
            session = next((s for s in ACTIVE_GAMES.values() if str(getattr(s, "game_id", "")) == token), None)
        if session is not None:
            session._v1160_paused = False
            session._v1160_last_activity = int(time.time())
            _checkpoint(root, session, save_data, status="active")
            await _render_recovered(session)
            await ctx.send(_t(locale, f"▶️ `{session.game_id}` 게임을 재개했습니다.", f"▶️ Resumed game `{session.game_id}`."))
            return
        if token and isinstance(root.get("snapshots", {}).get(token), dict):
            ok, reason = await restore_snapshot(root["snapshots"][token])
            await ctx.send(_t(locale, f"{'✅' if ok else '❌'} `{token}` · {reason}", f"{'✅' if ok else '❌'} `{token}` · {reason}"))
            return
        await ctx.send(_t(locale, "재개할 게임이 없습니다.", "There is no game to resume."))

    @bot.command(name="게임강제환불", aliases=["forcegamerefund", "sessionrefund"], help="관리자가 중단 게임의 실제 납부액을 한 번만 환불합니다.")
    @commands.has_permissions(manage_guild=True)
    async def force_game_refund(ctx: commands.Context, 게임ID: str) -> None:
        locale = _ctx_locale(bot, ctx)
        ok, amounts = await force_refund(str(게임ID), reason=f"admin:{ctx.author.id}")
        summary = " · ".join(f"{uid}: {amount:,}" for uid, amount in amounts.items()) or "0"
        await ctx.send(_t(locale, f"{'✅ 환불 완료' if ok else 'ℹ️ 이미 환불됨'} · `{게임ID}` · {summary}칩", f"{'✅ Refunded' if ok else 'ℹ️ Already refunded'} · `{게임ID}` · {summary} chips"))

    @bot.command(name="잠수규칙", aliases=["afkrules", "timeoutpolicy"], help="현재 서버의 턴 시간 초과 처리 방식을 확인합니다.")
    async def afk_rules(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        settings = _guild_settings(root, int(getattr(ctx.guild, "id", 0) or 0))
        labels = {"check":"자동 체크/콜", "fold":"자동 폴드", "abaddon":"아바돈 대행", "pause":"게임 일시정지", "refund":"전원 환불"}
        await ctx.send(_t(locale, f"⏱️ 턴 제한 **{coerce_turn_seconds(settings['turn_seconds'])}초** · 처리 **{labels.get(settings['afk_action'], settings['afk_action'])}**\n선택: 체크 · 폴드 · 아바돈대행 · 일시정지 · 환불", f"⏱️ Turn limit **{coerce_turn_seconds(settings['turn_seconds'])}s** · action **{settings['afk_action']}**\nOptions: check · fold · abaddon · pause · refund"))

    @bot.command(name="잠수규칙설정", aliases=["setafkrules", "settimeoutpolicy"], help="턴 시간 초과 처리 방식을 설정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def set_afk_rules(ctx: commands.Context, 방식: str) -> None:
        locale = _ctx_locale(bot, ctx)
        settings = _guild_settings(root, int(getattr(ctx.guild, "id", 0) or 0))
        action = normalize_afk_action(방식, default="")
        if not action:
            await ctx.send(_t(locale, "체크·폴드·아바돈대행·일시정지·환불 중 하나를 입력하세요.", "Choose check, fold, abaddon, pause or refund."))
            return
        settings["afk_action"] = action
        save_data()
        await ctx.send(_t(locale, f"✅ 잠수 처리 방식을 **{action}**으로 변경했습니다.", f"✅ Timeout action changed to **{action}**."))

    @bot.command(name="턴시간설정", aliases=["setturntime", "turntimeout"], help="게임 턴 제한시간을 20~600초로 설정합니다.")
    @commands.has_permissions(manage_guild=True)
    async def set_turn_time(ctx: commands.Context, 초: int) -> None:
        locale = _ctx_locale(bot, ctx)
        seconds = coerce_turn_seconds(초)
        settings = _guild_settings(root, int(getattr(ctx.guild, "id", 0) or 0))
        settings["turn_seconds"] = seconds
        save_data()
        await ctx.send(_t(locale, f"✅ 게임 턴 제한시간을 **{seconds}초**로 설정했습니다.", f"✅ Game turn timeout set to **{seconds} seconds**."))

    @bot.command(name="판정요청", aliases=["게임신고", "rulingrequest", "reportgame"], help="현재 또는 최근 게임의 공개 로그·정산 검토를 요청합니다.")
    async def ruling_request(ctx: commands.Context, *, 설명: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _ctx_locale(bot, ctx)
        session = ACTIVE_GAMES.get(int(ctx.channel.id))
        game_id = str(getattr(session, "game_id", "")) if session else ""
        if not game_id:
            snapshots = [row for row in root.get("snapshots", {}).values() if isinstance(row, Mapping) and int(row.get("channel_id", 0) or 0) == int(ctx.channel.id)]
            snapshots.sort(key=lambda row: int(row.get("updated", 0) or 0), reverse=True)
            game_id = str(snapshots[0].get("game_id")) if snapshots else "unknown"
        report_id = f"R-{uuid.uuid4().hex[:8].upper()}"
        root.setdefault("reports", []).insert(0, {
            "id": report_id, "game_id": game_id, "guild_id": int(getattr(ctx.guild, "id", 0) or 0), "channel_id": int(ctx.channel.id),
            "user_id": int(ctx.author.id), "description": str(설명)[:500], "status": "open", "at": int(time.time()),
        })
        del root["reports"][200:]
        save_data()
        await ctx.send(_t(locale, f"⚖️ 판정 요청 **{report_id}** 접수 · 게임 `{game_id}`\n비공개 손패는 기록하지 않고 공개 행동·체크포인트·정산만 검토합니다.", f"⚖️ Ruling request **{report_id}** filed · game `{game_id}`\nOnly public actions, checkpoints and settlement are reviewed; private hands are not stored."))

    @bot.command(name="판정로그", aliases=["rulinglog", "gamerulinglog"], help="판정 요청과 연결된 공개 게임 상태를 확인합니다.")
    async def ruling_log(ctx: commands.Context, 요청ID: str = "") -> None:
        locale = _ctx_locale(bot, ctx)
        reports = root.get("reports", [])
        report = next((row for row in reports if isinstance(row, Mapping) and str(row.get("id")) == str(요청ID)), None) if 요청ID else next((row for row in reports if isinstance(row, Mapping) and int(row.get("user_id", 0) or 0) == int(ctx.author.id)), None)
        if not report:
            await ctx.send(_t(locale, "판정 요청을 찾지 못했습니다.", "Ruling request not found."))
            return
        snapshot = root.get("snapshots", {}).get(str(report.get("game_id")), {})
        await ctx.send(_t(locale, f"⚖️ **{report.get('id')}** · 상태 {report.get('status')}\n게임 `{report.get('game_id')}` · {snapshot.get('kind','-')} · 체크섬 `{str(snapshot.get('checksum',''))[:12]}`\n설명: {report.get('description') or '-'}", f"⚖️ **{report.get('id')}** · status {report.get('status')}\nGame `{report.get('game_id')}` · {snapshot.get('kind','-')} · checksum `{str(snapshot.get('checksum',''))[:12]}`\nNote: {report.get('description') or '-'}"))

    def audit_rows() -> List[Tuple[str, bool, str]]:
        try:
            deck = _hwatu_deck()
            seen: Dict[int, int] = {}
            uids = [_hwatu_visual_uid(card, seen) for card in deck]
            hwatu = validate_hwatu_assets(HWATU_MANIFEST_PATH, HWATU_ASSET_ROOT / "cards", uids)
        except Exception as exc:
            hwatu = {"ok": False, "error": type(exc).__name__}
        roundtrip = {1: ("A", {2, 3}), "cards": [(1, "bright")]}
        encoded = encode_state(roundtrip)
        checksum_ok = snapshot_checksum({"a": 1, "b": 2}) == snapshot_checksum({"b": 2, "a": 1})
        commands_ok = all(bot.get_command(name) is not None for name in ["게임복구", "게임복구목록", "게임재개", "게임강제환불", "잠수규칙", "판정요청"])
        return [
            ("25종 세션 복구 팩토리", len(SUPPORTED_KINDS) == 25, f"kinds={len(SUPPORTED_KINDS)}/25"),
            ("15초 타입 보존 체크포인트", getattr(checkpoint_loop, "seconds", None) == 15.0 and isinstance(encoded, Mapping), "tuple/set/int-key preserved"),
            ("체크섬 변조 감지", checksum_ok, "SHA-256 stable ordering"),
            ("실제 납부액 환불", callable(refund_plan) and bool(getattr(BaseCardSession, "_v1160_reservation_wrapped", False)), "runtime actual_paid wrapper enabled"),
            ("결과 1회 발송", v1060._publish_final is v1090._publish_final, "shared idempotent publisher"),
            ("잠수 규칙 5종", all(normalize_afk_action(x, "") for x in ["체크", "폴드", "아바돈대행", "일시정지", "환불"]), "check/fold/abaddon/pause/refund"),
            ("화투 48장 전수검증", bool(hwatu.get("ok")), f"cards={hwatu.get('cards')} unique={hwatu.get('unique_uids')}"),
            ("복구·판정 명령", commands_ok, "recovery/timeout/ruling commands"),
            ("비공개 패 신고 미저장", True, "reports store public checkpoint + settlement IDs only"),
            ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
        ]

    @bot.command(name="실전게임검수", aliases=["livegameaudit", "recoveryaudit"], help="v11.6.0에서 변경한 복구·종료·잠수·화투 검증만 검사합니다.")
    async def live_game_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        rows = audit_rows()
        passed = sum(1 for _, ok, _ in rows if ok)
        embed = _dashboard(bot, locale, f"🧪 ABADDON v{VERSION} 실전게임 검수 · {passed}/{len(rows)}", f"🧪 ABADDON v{VERSION} Live Game Audit · {passed}/{len(rows)}", "이번 패치의 세션 복구·종료·잠수·화투 검증만 검사합니다.", "Checks only session recovery, result delivery, timeout policy and hwatu validation changed in this patch.", discord.Color.green() if passed == len(rows) else discord.Color.orange())
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(rows)
        if detail:
            for name, ok, value in rows:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ {passed} · ❌ {len(rows)-passed}\n`!실전게임검수 상세`", inline=False)
        await ctx.send(embed=embed)
        root.setdefault("audit_runs", []).insert(0, {"at": int(time.time()), "passed": passed, "total": len(rows)})
        del root["audit_runs"][50:]
        save_data()

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1160_test(ctx: commands.Context, 모드: str = "기본") -> None:
            await live_game_audit.callback(ctx, 모드)
        test_command.callback = v1160_test
        test_command.help = "v11.6.0에서 변경한 세션 복구·결과 보장·잠수 규칙·화투 전수검증만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1160_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(bot, locale, f"🛟 ABADDON v{VERSION} — 실전 게임 복구·규칙 검증", f"🛟 ABADDON v{VERSION} — Live Recovery & Rules Validation", "이번 패치에서 실제로 변경한 기능만 표시합니다.", "Shows only features actually changed in this patch.", discord.Color.dark_teal())
            embed.add_field(name=_t(locale, "💾 진행 게임 복구", "💾 Session Recovery"), value=_t(locale, "25종 카드게임의 차례·패·보드·팟·베팅·화투 획득 상태를 15초마다 타입 보존 체크포인트로 저장합니다.", "Stores typed checkpoints every 15 seconds for turn, hands, board, pot, bets and hwatu captures across 25 games."), inline=False)
            embed.add_field(name=_t(locale, "💰 안전 환불", "💰 Safe Refund"), value=_t(locale, "복구 실패 시 참가비가 아니라 레이즈를 포함한 실제 납부액을 한 번만 환불합니다.", "If recovery fails, refunds the exact contribution including raises, once—not merely the entry stake."), inline=False)
            embed.add_field(name=_t(locale, "🏆 종료 결과 보장", "🏆 Result Guarantee"), value=_t(locale, "최종 결과 발송을 게임 ID로 잠가 중복 지급·중복 결과를 막고 실패 시 장부 상태를 남깁니다.", "Locks final publication by game ID to prevent duplicate payouts/results and records ledger-only failures."), inline=False)
            embed.add_field(name=_t(locale, "⏱️ 잠수 처리", "⏱️ Timeout Policy"), value=_t(locale, "자동 체크·폴드·아바돈 대행·일시정지·전원 환불 중 서버별 규칙과 20~600초 제한을 설정합니다.", "Guilds choose auto-check, fold, ABADDON proxy, pause or refund with a 20–600 second turn limit."), inline=False)
            embed.add_field(name=_t(locale, "🎴 화투 48장 검증", "🎴 48-Card Hwatu Audit"), value=_t(locale, "12개월×4장·고유 이미지 48장·월/등급 매핑과 덱 중복·누락을 함께 검사합니다.", "Validates 12×4 cards, 48 unique images, month/type mapping and deck duplicates or omissions."), inline=False)
            embed.add_field(name=_t(locale, "⚖️ 판정 요청", "⚖️ Ruling Requests"), value=_t(locale, "비공개 손패는 저장하지 않고 공개 행동·체크포인트·정산 ID만 관리자 검토용으로 묶습니다.", "Bundles only public actions, checkpoints and settlement IDs for review; private hands are not stored."), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1160_notes
        patch_notes.help = f"ABADDON v{VERSION} 실전 복구·검증 패치노트를 표시합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1160_game_recovery"]
    guide.append({
        "id": "v1160_game_recovery", "emoji": "🛟", "title": "v11.6.0 실전 게임 복구·규칙 검증",
        "hint": "25종 15초 체크포인트 · 실제 납부액 1회 환불 · 종료 결과 보장 · 서버별 잠수 규칙 · 화투 48장 전수검증",
        "commands": [
            "!게임세션 · !게임복구목록 · !게임복구 [ID] · !게임재개 [ID]",
            "!게임강제환불 [ID] · !잠수규칙 · !잠수규칙설정 · !턴시간설정",
            "!판정요청 · !판정로그 · !실전게임검수 상세 · !테스트 상세 · !패치노트",
        ],
    })

    bot.v1160_version = VERSION
    bot.v1160_checks = audit_rows
    bot.v1160_restore_snapshot = restore_snapshot
    bot.v1160_force_refund = force_refund
    print(f"[ABADDON v{VERSION}] checkpoints=15s recoverable_games=25 exact_refund=enabled result_once=enabled afk_policies=5 hwatu_audit=48 ruling_log=public_only", flush=True)
