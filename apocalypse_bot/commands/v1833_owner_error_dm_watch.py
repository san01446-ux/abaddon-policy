from __future__ import annotations

"""ABADDON v18.3.3 OWNER ERROR DM WATCH.

Captures unexpected runtime failures from prefix/hybrid commands, app/slash
commands and discord.ui component callbacks, stores a compact incident ledger in
/var/data/abaddon.sqlite3, and notifies the bot owner by DM without flooding.

Expected user mistakes (unknown commands, bad/missing arguments, cooldowns and
permission/check failures) are intentionally ignored.
"""

import asyncio
import hashlib
import os
import re
import sqlite3
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner

VERSION = "18.3.3"
DEFAULT_DB_PATH = os.getenv("ABADDON_DB_PATH", "/var/data/abaddon.sqlite3")
EVENT_LIMIT = 1200
DEFAULT_DM_COOLDOWN = 600


def _db_path() -> Path:
    return Path(os.getenv("ABADDON_DB_PATH") or DEFAULT_DB_PATH)


def _connect() -> sqlite3.Connection:
    target = _db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=12)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _initialize_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS owner_error_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                incident_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                source TEXT NOT NULL,
                guild_id TEXT NOT NULL DEFAULT '',
                guild_name TEXT NOT NULL DEFAULT '',
                channel_id TEXT NOT NULL DEFAULT '',
                channel_name TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                user_name TEXT NOT NULL DEFAULT '',
                command_name TEXT NOT NULL DEFAULT '',
                component_name TEXT NOT NULL DEFAULT '',
                error_type TEXT NOT NULL,
                error_text TEXT NOT NULL DEFAULT '',
                traceback_text TEXT NOT NULL DEFAULT '',
                notified INTEGER NOT NULL DEFAULT 0,
                dm_error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_owner_error_events_ts
                ON owner_error_events(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_owner_error_events_fp
                ON owner_error_events(fingerprint, ts DESC);
            CREATE TABLE IF NOT EXISTS owner_error_fingerprints (
                fingerprint TEXT PRIMARY KEY,
                first_ts REAL NOT NULL,
                last_ts REAL NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                last_notified_ts REAL NOT NULL DEFAULT 0,
                suppressed_since_notify INTEGER NOT NULL DEFAULT 0,
                last_incident_id TEXT NOT NULL DEFAULT ''
            );
            """
        )


def _safe_text(value: Any, limit: int = 300) -> str:
    text = str(value or "").replace("\x00", "")
    # Never leak configured secrets into owner telemetry/logging.
    for key in ("DISCORD_TOKEN", "BOT_TOKEN", "TOKEN", "KOREANBOTS_TOKEN"):
        secret = os.getenv(key, "")
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    # Best-effort Discord token-shaped redaction.
    text = re.sub(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}", "[REDACTED_TOKEN]", text)
    return text[: max(0, int(limit))]


def _unwrap(error: BaseException) -> BaseException:
    current: BaseException = error
    for _ in range(3):
        original = getattr(current, "original", None)
        if isinstance(original, BaseException) and original is not current:
            current = original
            continue
        break
    return current


def _trace(error: BaseException) -> str:
    try:
        raw = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    except Exception:
        raw = f"{type(error).__name__}: {error}"
    return _safe_text(raw, 7000)


def _frame_key(error: BaseException) -> str:
    tb = error.__traceback__
    last = None
    while tb is not None:
        last = tb
        tb = tb.tb_next
    if last is None:
        return "no-frame"
    try:
        filename = Path(last.tb_frame.f_code.co_filename).name
        func = last.tb_frame.f_code.co_name
        return f"{filename}:{last.tb_lineno}:{func}"
    except Exception:
        return "unknown-frame"


def _fingerprint(source: str, command_name: str, component_name: str, error: BaseException) -> str:
    key = "|".join(
        [
            str(source or "unknown"),
            str(command_name or "unknown"),
            str(component_name or ""),
            type(error).__name__,
            _frame_key(error),
        ]
    )
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:20]


def _prefix_expected(error: BaseException) -> bool:
    return isinstance(
        error,
        (
            commands.CommandNotFound,
            commands.MissingRequiredArgument,
            commands.BadArgument,
            commands.BadUnionArgument,
            commands.TooManyArguments,
            commands.CommandOnCooldown,
            commands.CheckFailure,
            commands.DisabledCommand,
            commands.MaxConcurrencyReached,
            commands.UserInputError,
        ),
    )


def _app_expected(error: BaseException) -> bool:
    expected: Tuple[type, ...] = tuple(
        cls
        for cls in (
            getattr(app_commands, "CheckFailure", None),
            getattr(app_commands, "CommandOnCooldown", None),
            getattr(app_commands, "TransformerError", None),
            getattr(app_commands, "CommandSignatureMismatch", None),
            getattr(app_commands, "CommandNotFound", None),
        )
        if isinstance(cls, type)
    )
    return bool(expected and isinstance(error, expected))


def _transient_discord_http(error: BaseException) -> bool:
    # 429/1015 are transport/rate-limit incidents rather than user feature bugs.
    if isinstance(error, discord.HTTPException):
        try:
            if int(getattr(error, "status", 0) or 0) == 429:
                return True
        except Exception:
            pass
        text = str(error).casefold()
        if "1015" in text or "rate limit" in text:
            return True
    return False


def _cooldown_seconds() -> int:
    raw = os.getenv("ABADDON_ERROR_DM_COOLDOWN", "").strip()
    try:
        return max(60, min(86400, int(raw))) if raw else DEFAULT_DM_COOLDOWN
    except ValueError:
        return DEFAULT_DM_COOLDOWN


def _record_incident(row: Mapping[str, Any]) -> Dict[str, Any]:
    _initialize_db()
    now = float(row["ts"])
    fp = str(row["fingerprint"])
    cooldown = _cooldown_seconds()
    notify_due = False
    suppressed_before = 0

    with _connect() as conn:
        existing = conn.execute(
            "SELECT first_ts,last_ts,total,last_notified_ts,suppressed_since_notify,last_incident_id "
            "FROM owner_error_fingerprints WHERE fingerprint=?",
            (fp,),
        ).fetchone()
        if existing is None:
            notify_due = True
            conn.execute(
                "INSERT INTO owner_error_fingerprints(fingerprint,first_ts,last_ts,total,last_notified_ts,suppressed_since_notify,last_incident_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (fp, now, now, 1, now, 0, str(row["incident_id"])),
            )
        else:
            last_notified = float(existing[3] or 0)
            suppressed_before = int(existing[4] or 0)
            notify_due = (now - last_notified) >= cooldown
            if notify_due:
                conn.execute(
                    "UPDATE owner_error_fingerprints SET last_ts=?,total=total+1,last_notified_ts=?,suppressed_since_notify=0,last_incident_id=? WHERE fingerprint=?",
                    (now, now, str(row["incident_id"]), fp),
                )
            else:
                conn.execute(
                    "UPDATE owner_error_fingerprints SET last_ts=?,total=total+1,suppressed_since_notify=suppressed_since_notify+1,last_incident_id=? WHERE fingerprint=?",
                    (now, str(row["incident_id"]), fp),
                )

        cur = conn.execute(
            """
            INSERT INTO owner_error_events(
                ts,incident_id,fingerprint,source,guild_id,guild_name,channel_id,channel_name,
                user_id,user_name,command_name,component_name,error_type,error_text,traceback_text,notified,dm_error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now,
                str(row["incident_id"]),
                fp,
                str(row.get("source") or "unknown"),
                str(row.get("guild_id") or ""),
                str(row.get("guild_name") or "")[:120],
                str(row.get("channel_id") or ""),
                str(row.get("channel_name") or "")[:120],
                str(row.get("user_id") or ""),
                str(row.get("user_name") or "")[:120],
                str(row.get("command_name") or "")[:160],
                str(row.get("component_name") or "")[:180],
                str(row.get("error_type") or "Exception")[:120],
                str(row.get("error_text") or "")[:1000],
                str(row.get("traceback_text") or "")[:7000],
                0,
                "",
            ),
        )
        event_id = int(cur.lastrowid or 0)
        if event_id and event_id % 50 == 0:
            conn.execute(
                "DELETE FROM owner_error_events WHERE id NOT IN (SELECT id FROM owner_error_events ORDER BY id DESC LIMIT ?)",
                (EVENT_LIMIT,),
            )
    return {"event_id": event_id, "notify_due": notify_due, "suppressed_before": suppressed_before, "cooldown": cooldown}


def _mark_delivery(event_id: int, ok: bool, error: str = "") -> None:
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE owner_error_events SET notified=?, dm_error=? WHERE id=?",
                (1 if ok else 0, _safe_text(error, 400), int(event_id)),
            )
    except Exception:
        pass


def _recent_events(limit: int = 20) -> List[Dict[str, Any]]:
    _initialize_db()
    safe_limit = max(1, min(50, int(limit)))
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM owner_error_events ORDER BY id DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def _error_stats() -> Dict[str, int]:
    _initialize_db()
    with _connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM owner_error_events").fetchone()[0])
        notified = int(conn.execute("SELECT COUNT(*) FROM owner_error_events WHERE notified=1").fetchone()[0])
        unique = int(conn.execute("SELECT COUNT(*) FROM owner_error_fingerprints").fetchone()[0])
        recent = int(conn.execute("SELECT COUNT(*) FROM owner_error_events WHERE ts>=?", (time.time() - 86400,)).fetchone()[0])
    return {"total": total, "notified": notified, "unique": unique, "recent24h": recent}


async def _resolve_owner(bot: commands.Bot) -> Optional[discord.User]:
    configured = os.getenv("ABADDON_OWNER_ID", "").strip()
    owner_id = int(configured) if configured.isdigit() else 0
    if not owner_id:
        owner_id = int(getattr(bot, "owner_id", 0) or 0)
    if not owner_id:
        ids = list(getattr(bot, "owner_ids", None) or [])
        if ids:
            owner_id = int(ids[0])
    if not owner_id:
        try:
            info = await bot.application_info()
            owner = getattr(info, "owner", None)
            owner_id = int(getattr(owner, "id", 0) or 0)
        except Exception:
            owner_id = 0
    if not owner_id:
        return None
    cached = bot.get_user(owner_id)
    if cached is not None:
        return cached
    try:
        return await bot.fetch_user(owner_id)
    except Exception:
        return None


def _location_from_context(ctx: Optional[commands.Context] = None, interaction: Optional[discord.Interaction] = None) -> Dict[str, str]:
    guild = getattr(ctx, "guild", None) if ctx is not None else getattr(interaction, "guild", None)
    channel = getattr(ctx, "channel", None) if ctx is not None else getattr(interaction, "channel", None)
    user = getattr(ctx, "author", None) if ctx is not None else getattr(interaction, "user", None)
    return {
        "guild_id": str(getattr(guild, "id", "") or ""),
        "guild_name": _safe_text(getattr(guild, "name", "DM") or "DM", 120),
        "channel_id": str(getattr(channel, "id", "") or ""),
        "channel_name": _safe_text(getattr(channel, "name", "DM") or "DM", 120),
        "user_id": str(getattr(user, "id", "") or ""),
        "user_name": _safe_text(user or "unknown", 120),
    }


async def _send_owner_dm(bot: commands.Bot, row: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    owner = await _resolve_owner(bot)
    if owner is None:
        return False
    source_labels = {"prefix": "!명령어", "button": "버튼/드롭다운", "slash": "슬래시", "hybrid": "하이브리드", "test": "테스트"}
    source = str(row.get("source") or "unknown")
    embed = discord.Embed(
        title="🚨 ABADDON 자동 오류 감지",
        description=(
            f"**{source_labels.get(source, source)}** 실행 중 실제 내부 예외가 감지됐습니다.\n"
            "사용자 입력 실수·쿨타임·일반 권한 오류·429/1015는 자동 DM 대상에서 제외됩니다."
        ),
        color=0xE74C3C,
        timestamp=datetime.now(timezone.utc),
    )
    guild_name = str(row.get("guild_name") or "DM")
    guild_id = str(row.get("guild_id") or "-")
    channel_name = str(row.get("channel_name") or "DM")
    channel_id = str(row.get("channel_id") or "-")
    user_name = str(row.get("user_name") or "unknown")
    user_id = str(row.get("user_id") or "-")
    embed.add_field(name="📍 위치", value=f"서버 **{guild_name}** (`{guild_id}`)\n채널 **{channel_name}** (`{channel_id}`)", inline=False)
    embed.add_field(name="👤 사용자", value=f"{user_name} (`{user_id}`)", inline=True)
    feature = str(row.get("command_name") or row.get("component_name") or "unknown")
    component = str(row.get("component_name") or "")
    value = f"`{_safe_text(feature, 300)}`"
    if component and component != feature:
        value += f"\nUI: `{_safe_text(component, 300)}`"
    embed.add_field(name="🧩 기능", value=value[:1024], inline=False)
    embed.add_field(
        name="💥 오류",
        value=f"`{row.get('error_type', 'Exception')}`\n{_safe_text(row.get('error_text'), 800) or '(메시지 없음)'}"[:1024],
        inline=False,
    )
    suppressed = int(meta.get("suppressed_before", 0) or 0)
    if suppressed:
        embed.add_field(name="🔁 동일 오류 묶음", value=f"이전 알림 이후 같은 오류 **{suppressed}건**이 추가 발생했습니다.", inline=False)
    embed.add_field(name="🆔 사건 번호", value=f"`{row.get('incident_id')}` · fingerprint `{row.get('fingerprint')}`", inline=False)
    embed.set_footer(text=f"중복 DM 억제 {int(meta.get('cooldown', DEFAULT_DM_COOLDOWN)) // 60}분 · 상세 기록 /var/data/abaddon.sqlite3")
    try:
        await owner.send(embed=embed)
        return True
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] owner error DM failed · {type(exc).__name__}: {exc}", flush=True)
        return False


def register_v1833_owner_error_dm_watch(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1833_registered", False):
        return
    bot._abaddon_v1833_registered = True
    bot.abaddon_version = VERSION
    _initialize_db()

    report_lock = asyncio.Lock()

    async def report_error(
        error: BaseException,
        *,
        source: str,
        ctx: Optional[commands.Context] = None,
        interaction: Optional[discord.Interaction] = None,
        command_name: str = "",
        component_name: str = "",
        force_notify: bool = False,
    ) -> Optional[str]:
        original = _unwrap(error)
        if source in {"prefix", "button", "hybrid"} and _prefix_expected(error):
            return None
        if source == "slash" and (_app_expected(error) or _app_expected(original)):
            return None
        if not force_notify and _transient_discord_http(original):
            return None

        if not command_name:
            if ctx is not None:
                cmd = getattr(ctx, "command", None)
                command_name = str(getattr(cmd, "qualified_name", "") or getattr(cmd, "name", "") or "unknown")
            elif interaction is not None:
                cmd = getattr(interaction, "command", None)
                command_name = str(getattr(cmd, "qualified_name", "") or getattr(cmd, "name", "") or "unknown")
            else:
                command_name = "unknown"

        if source == "prefix" and ctx is not None:
            if bool(getattr(ctx, "_v1813_button_bridge", False)):
                source = "button"
            elif getattr(ctx, "interaction", None) is not None:
                source = "hybrid"

        incident_id = f"E{datetime.now(timezone.utc).strftime('%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        fp = _fingerprint(source, command_name, component_name, original)
        location = _location_from_context(ctx, interaction)
        row: Dict[str, Any] = {
            "ts": time.time(),
            "incident_id": incident_id,
            "fingerprint": fp,
            "source": source,
            **location,
            "command_name": _safe_text(command_name, 160),
            "component_name": _safe_text(component_name, 180),
            "error_type": type(original).__name__,
            "error_text": _safe_text(original, 1000),
            "traceback_text": _trace(original),
        }

        async with report_lock:
            try:
                meta = _record_incident(row)
            except Exception as exc:
                print(f"[ABADDON v{VERSION}] incident DB failure · {type(exc).__name__}: {exc}", flush=True)
                return incident_id
            should_notify = bool(meta.get("notify_due")) or force_notify
            delivered = False
            dm_error = ""
            if should_notify:
                try:
                    delivered = await _send_owner_dm(bot, row, meta)
                    if not delivered:
                        dm_error = "owner_unresolved_or_dm_failed"
                except Exception as exc:
                    dm_error = f"{type(exc).__name__}: {exc}"
                _mark_delivery(int(meta.get("event_id", 0) or 0), delivered, dm_error)

        print(
            f"[ABADDON v{VERSION}] incident={incident_id} source={source} command={command_name!r} "
            f"error={type(original).__name__} dm={'sent' if delivered else ('suppressed' if not should_notify else 'failed')}",
            flush=True,
        )
        return incident_id

    bot.v1833_report_error = report_error

    @bot.listen("on_command_error")
    async def v1833_prefix_error(ctx: commands.Context, error: commands.CommandError) -> None:
        if _prefix_expected(error):
            return
        await report_error(error, source="prefix", ctx=ctx)

    # App/slash commands have a separate error dispatch path from prefix commands.
    previous_tree_error = bot.tree.on_error

    async def v1833_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if not (_app_expected(error) or _app_expected(_unwrap(error))):
            await report_error(error, source="slash", interaction=interaction)
        try:
            await previous_tree_error(interaction, error)
        except Exception as chained:
            print(f"[ABADDON v{VERSION}] previous tree error handler failed · {type(chained).__name__}: {chained}", flush=True)

    bot.tree.error(v1833_tree_error)

    # discord.py's BaseView._scheduled_task catches callback exceptions before
    # they reach Client.on_error. Patch this single central dispatcher so every
    # ABADDON Button/Select View is covered even when a subclass overrides
    # View.on_error. requirements.txt pins discord.py==2.7.1.
    try:
        from discord.ui.view import BaseView  # type: ignore

        if not getattr(BaseView, "_abaddon_v1833_error_watch", False):
            original_scheduled_task = BaseView._scheduled_task

            async def v1833_scheduled_task(self: Any, item: Any, interaction: discord.Interaction) -> None:
                try:
                    item._refresh_state(interaction, interaction.data)
                    allow = await item._run_checks(interaction) and await self.interaction_check(interaction)
                    if not allow:
                        return
                    if self.timeout:
                        try:
                            setattr(self, "_BaseView__timeout_expiry", time.monotonic() + self.timeout)
                        except Exception:
                            pass
                    await item.callback(interaction)
                except Exception as exc:
                    label = str(getattr(item, "label", "") or getattr(item, "placeholder", "") or item.__class__.__name__)
                    custom_id = str(getattr(item, "custom_id", "") or "")
                    component = label if not custom_id else f"{label} · {custom_id}"
                    try:
                        await report_error(exc, source="button", interaction=interaction, component_name=component)
                    except Exception as reporter_exc:
                        print(f"[ABADDON v{VERSION}] UI reporter failed · {type(reporter_exc).__name__}: {reporter_exc}", flush=True)
                    return await self.on_error(interaction, exc, item)

            BaseView._abaddon_v1833_original_scheduled_task = original_scheduled_task  # type: ignore[attr-defined]
            BaseView._scheduled_task = v1833_scheduled_task  # type: ignore[assignment]
            BaseView._abaddon_v1833_error_watch = True  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"[ABADDON v{VERSION}] UI error watch install warning · {type(exc).__name__}: {exc}", flush=True)

    async def _owner_dm_target(ctx: commands.Context) -> Optional[discord.DMChannel]:
        if not await _private_owner(bot, ctx.author):
            return None
        try:
            return await ctx.author.create_dm()
        except Exception:
            return None

    @bot.command(name="오류DM테스트", aliases=["errordmtest"], hidden=True, help="[봇 소유자 전용] 자동 오류 DM 수신 경로를 테스트합니다.")
    async def error_dm_test(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        test_error = RuntimeError("v18.3.3 owner DM watcher test — 실제 기능 오류가 아닙니다.")
        incident = await report_error(test_error, source="test", ctx=ctx, command_name="오류DM테스트", component_name="manual-test", force_notify=True)
        await ctx.send(f"✅ 자동 오류 DM 테스트를 실행했습니다. 사건 번호: `{incident or '-'}`")

    @bot.command(name="오류알림상태", aliases=["errorwatchstatus"], hidden=True, help="[봇 소유자 전용] 자동 오류 DM/SQLite 기록 상태를 확인합니다.")
    async def error_watch_status(ctx: commands.Context) -> None:
        dm = await _owner_dm_target(ctx)
        if dm is None:
            return
        stats = _error_stats()
        owner = await _resolve_owner(bot)
        embed = discord.Embed(title="🚨 ABADDON 자동 오류 DM 상태", color=0x5865F2)
        embed.add_field(name="감시 범위", value="`!명령어` · 하이브리드 · 버튼/드롭다운 · 슬래시", inline=False)
        embed.add_field(name="저장", value=f"`{_db_path()}`\n최근 보관 {EVENT_LIMIT}건", inline=False)
        embed.add_field(name="기록", value=f"전체 **{stats['total']}** · 24시간 **{stats['recent24h']}** · 유형 **{stats['unique']}** · DM 성공 **{stats['notified']}**", inline=False)
        embed.add_field(name="중복 억제", value=f"동일 오류 **{_cooldown_seconds() // 60}분** 동안 DM 1회 · 발생 자체는 모두 SQLite 기록", inline=False)
        embed.add_field(name="DM 대상", value=f"{owner} (`{getattr(owner, 'id', '-')}`)" if owner else "⚠️ 봇 소유자를 확인하지 못했습니다.", inline=False)
        embed.set_footer(text="사용자 입력 실수/쿨타임/일반 체크 실패/429·1015는 DM 제외")
        await dm.send(embed=embed)
        try:
            await ctx.message.add_reaction("✅")
        except Exception:
            pass

    @bot.command(name="자동오류최근", aliases=["recentautoerrors"], hidden=True, help="[봇 소유자 전용] 자동 수집된 최근 내부 오류를 DM으로 확인합니다.")
    async def recent_auto_errors(ctx: commands.Context, 개수: int = 15) -> None:
        dm = await _owner_dm_target(ctx)
        if dm is None:
            return
        rows = _recent_events(max(1, min(30, int(개수 or 15))))
        embed = discord.Embed(title="🧯 ABADDON 최근 자동 오류", color=0xE67E22)
        if not rows:
            embed.description = "아직 자동 수집된 내부 오류가 없습니다."
        else:
            lines: List[str] = []
            for row in rows[:30]:
                stamp = datetime.fromtimestamp(float(row.get("ts") or 0), tz=timezone.utc).strftime("%m-%d %H:%M")
                src = str(row.get("source") or "?")
                cmd = str(row.get("command_name") or row.get("component_name") or "unknown")
                err = str(row.get("error_type") or "Exception")
                gid = str(row.get("guild_id") or "DM")
                bell = "📨" if int(row.get("notified") or 0) else "📝"
                lines.append(f"{bell} `{row.get('incident_id')}` {stamp} · **{src}** · `{cmd[:35]}` · `{err}` · G:{gid}")
            embed.description = "\n".join(lines)[:4000]
        embed.set_footer(text="📨=DM 전송 · 📝=중복 억제/기록만 저장")
        await dm.send(embed=embed)
        try:
            await ctx.message.add_reaction("✅")
        except Exception:
            pass

    @bot.command(name="1833오류검수", aliases=["1833erroraudit"], hidden=True, help="[봇 소유자 전용] v18.3.3 자동 오류 감시 기능 검수")
    async def audit_v1833(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        stats = _error_stats()
        owner = await _resolve_owner(bot)
        try:
            from discord.ui.view import BaseView  # type: ignore
            ui_hook = bool(getattr(BaseView, "_abaddon_v1833_error_watch", False))
        except Exception:
            ui_hook = False
        checks = [
            ("Prefix error listener", True),
            ("Slash tree error handler", getattr(bot.tree.on_error, "__name__", "") == "v1833_tree_error"),
            ("Button/Select central watcher", ui_hook),
            ("SQLite ledger", _db_path().parent.exists()),
            ("Owner DM target", owner is not None),
        ]
        good = sum(1 for _, ok in checks if ok)
        embed = discord.Embed(title="🧪 ABADDON v18.3.3 오류 DM 검수", color=0x2ECC71 if good == len(checks) else 0xF1C40F)
        embed.description = "\n".join(f"{'✅' if ok else '⚠️'} {name}" for name, ok in checks)
        embed.add_field(name="Ledger", value=f"total {stats['total']} · 24h {stats['recent24h']} · unique {stats['unique']}", inline=False)
        embed.add_field(name="Test", value="`!오류DM테스트`로 실제 DM 수신까지 확인", inline=False)
        await ctx.send(embed=embed)

    patch = bot.get_command("패치노트")
    if patch is not None:
        previous = patch.callback

        async def patch_v1833(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            embed = discord.Embed(title="🚨 ABADDON v18.3.3 — OWNER ERROR DM WATCH", color=0xD35400)
            embed.description = "다른 서버 사용자가 기능을 쓰다가 실제 내부 오류가 발생하면 제작자에게 자동 DM을 보내는 운영 감시 패치입니다."
            embed.add_field(name="자동 감시", value="일반 명령 · 하이브리드 · 버튼/드롭다운 · 슬래시", inline=False)
            embed.add_field(name="스팸 방지", value=f"같은 오류는 {_cooldown_seconds() // 60}분 동안 DM 1회만 전송하고 모든 발생 건은 SQLite에 누적", inline=False)
            embed.add_field(name="제외", value="오타/입력값 오류/쿨타임/일반 체크 실패/Discord 429·Cloudflare 1015", inline=False)
            embed.add_field(name="제작자 명령", value="`!오류DM테스트` · `!오류알림상태` · `!자동오류최근` · `!1833오류검수`", inline=False)
            embed.set_footer(text="메시지 원문/명령 인수는 자동 오류 DM에 저장하지 않음")
            await ctx.send(embed=embed)

        patch.callback = patch_v1833
        patch.help = "ABADDON v18.3.3 제작자 자동 오류 DM 감시 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1833_previous_callback"] = previous

    print(
        f"[ABADDON v{VERSION}] owner error DM watch ready · db={_db_path()} cooldown={_cooldown_seconds()}s "
        "sources=prefix,hybrid,button,slash",
        flush=True,
    )
